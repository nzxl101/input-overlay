from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

WM_INPUT        = 0x00FF
WM_QUIT         = 0x0012
RIM_TYPEMOUSE   = 0
RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE    = 0x00000001
RID_INPUT       = 0x10000003
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wt.USHORT),
        ("usUsage",     wt.USHORT),
        ("dwFlags",     wt.DWORD),
        ("hwndTarget",  wt.HWND),
    ]


class RAWMOUSE(ctypes.Structure):
    class _U(ctypes.Union):
        class _S(ctypes.Structure):
            _fields_ = [("usButtonFlags", wt.USHORT), ("usButtonData", wt.USHORT)]
        _fields_ = [("_s", _S), ("ulButtons", ctypes.c_ulong)]

    _fields_ = [
        ("usFlags",            wt.USHORT),
        ("_u",                 _U),
        ("ulRawButtons",       ctypes.c_ulong),
        ("lLastX",             ctypes.c_long),
        ("lLastY",             ctypes.c_long),
        ("ulExtraInformation", ctypes.c_ulong),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType",  wt.DWORD),
        ("dwSize",  wt.DWORD),
        ("hDevice", wt.HANDLE),
        ("wParam",  wt.WPARAM),
    ]


class RAWINPUT(ctypes.Structure):
    class _DATA(ctypes.Union):
        _fields_ = [("mouse", RAWMOUSE)]

    _fields_ = [("header", RAWINPUTHEADER), ("data", _DATA)]


_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_WNDPROC  = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

# 64bit sigs
_kernel32.GetModuleHandleW.restype  = ctypes.c_void_p
_kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

_user32.CreateWindowExW.restype  = wt.HWND
_user32.CreateWindowExW.argtypes = [
    wt.DWORD,    # dwExStyle
    wt.LPCWSTR,  # lpClassName
    wt.LPCWSTR,  # lpWindowName
    wt.DWORD,    # dwStyle
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,  # X, Y, nWidth, nHeight
    wt.HWND,     # hWndParent
    wt.HANDLE,   # hMenu
    ctypes.c_void_p,  # hInstance // needs to be void_p
    ctypes.c_void_p,  # lpParam
]


def _get_raw_input(lParam: int) -> RAWINPUT | None:
    buf_size = wt.UINT(0)
    _user32.GetRawInputData(lParam, RID_INPUT, None, ctypes.byref(buf_size), ctypes.sizeof(RAWINPUTHEADER))
    if buf_size.value == 0:
        return None
    buf = ctypes.create_string_buffer(buf_size.value)
    filled = _user32.GetRawInputData(lParam, RID_INPUT, buf, ctypes.byref(buf_size), ctypes.sizeof(RAWINPUTHEADER))
    if filled != buf_size.value:
        return None
    return RAWINPUT.from_buffer_copy(buf)


class RawMouseThread(threading.Thread):
    FLUSH_HZ = 125

    def __init__(self, callback: Callable[[int, int], None], min_delta: int = 0, daemon: bool = True):
        super().__init__(daemon=daemon, name="RawMouseThread")
        self._callback = callback
        self._min_delta = min_delta
        self._hwnd: int | None = None
        self._lock = threading.Lock()
        self._accum_dx = 0
        self._accum_dy = 0

    def stop(self):
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, WM_QUIT, 0, 0)
        self.join(timeout=2.0)

    def run(self):
        try:
            self._hwnd = self._create_window()
            if not self._hwnd:
                logger.error("raw_mouse: CreateWindowEx failed (error %d)", ctypes.windll.kernel32.GetLastError())
                return
            if not self._register():
                logger.error("raw_mouse: RegisterRawInputDevices failed (error %d)", ctypes.windll.kernel32.GetLastError())
                _user32.DestroyWindow(self._hwnd)
                return
            logger.info("raw_mouse: listener started (hwnd=0x%x)", self._hwnd)
            threading.Thread(target=self._flush_loop, daemon=True, name="RawMouseFlush").start()
            self._pump()
        except Exception:
            logger.exception("raw_mouse: unhandled error")
        finally:
            self._unregister()
            if self._hwnd:
                _user32.DestroyWindow(self._hwnd)
                self._hwnd = None
            logger.info("raw_mouse: listener stopped")

    def _flush_loop(self):
        interval = 1.0 / self.FLUSH_HZ
        while True:
            time.sleep(interval)
            with self._lock:
                dx, dy = self._accum_dx, self._accum_dy
                self._accum_dx = 0
                self._accum_dy = 0
            if dx == 0 and dy == 0:
                continue
            try:
                self._callback(dx, dy)
            except Exception:
                logger.exception("raw_mouse: exception in flush callback")

    def _create_window(self) -> int | None:
        def _wnd_proc(hwnd, msg, wParam, lParam):
            if msg == WM_INPUT:
                self._on_wm_input(lParam)
            return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)

        self._wnd_proc_ref = _WNDPROC(_wnd_proc)

        class WNDCLASSEX(ctypes.Structure):
            _fields_ = [
                ("cbSize",        wt.UINT),    ("style",         wt.UINT),
                ("lpfnWndProc",   _WNDPROC),   ("cbClsExtra",    ctypes.c_int),
                ("cbWndExtra",    ctypes.c_int),("hInstance",     ctypes.c_void_p),
                ("hIcon",         wt.HANDLE),  ("hCursor",       wt.HANDLE),
                ("hbrBackground", wt.HANDLE),  ("lpszMenuName",  wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm",       wt.HANDLE),
            ]

        class_name = "IOvRawMouse"
        wc = WNDCLASSEX()
        wc.cbSize        = ctypes.sizeof(WNDCLASSEX)
        wc.lpfnWndProc   = self._wnd_proc_ref
        wc.hInstance     = _kernel32.GetModuleHandleW(None)
        wc.lpszClassName = class_name
        _user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = _user32.CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            class_name, None, 0,
            0, 0, 0, 0,
            None, None, wc.hInstance, None,
        )
        return hwnd or None

    def _register(self) -> bool:
        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01
        rid.usUsage     = 0x02
        rid.dwFlags     = RIDEV_INPUTSINK
        rid.hwndTarget  = self._hwnd
        return bool(_user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)))

    def _unregister(self):
        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01
        rid.usUsage     = 0x02
        rid.dwFlags     = RIDEV_REMOVE
        rid.hwndTarget  = None
        _user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE))

    def _pump(self):
        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd",    wt.HWND),   ("message", wt.UINT),
                ("wParam",  wt.WPARAM), ("lParam",  wt.LPARAM),
                ("time",    wt.DWORD),  ("pt",      wt.POINT),
            ]

        msg = MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _on_wm_input(self, lParam: int):
        ri = _get_raw_input(lParam)
        if ri is None or ri.header.dwType != RIM_TYPEMOUSE:
            return
        m = ri.data.mouse
        if m.usFlags & 0x0001:
            return
        dx, dy = m.lLastX, m.lLastY
        if dx == 0 and dy == 0:
            return
        if abs(dx) + abs(dy) < self._min_delta:
            return
        with self._lock:
            self._accum_dx += dx
            self._accum_dy += dy