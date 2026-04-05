from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard, mouse

from services.consts import MOUSE_BUTTON_MAP, get_rawcode

logger = logging.getLogger(__name__)


class PynputInputListener:
    def __init__(
        self,
        on_key_press:    Callable[[int], None],
        on_key_release:  Callable[[int], None],
        on_mouse_click:  Callable[[int, bool], None],
        on_mouse_scroll: Callable[[int], None],
    ) -> None:
        self._on_key_press    = on_key_press
        self._on_key_release  = on_key_release
        self._on_mouse_click  = on_mouse_click
        self._on_mouse_scroll = on_mouse_scroll

        self._kb_listener: keyboard.Listener | None = None
        self._ms_listener: mouse.Listener    | None = None

    def start(self) -> None:
        self._kb_listener = keyboard.Listener(
            on_press=self._handle_key_press,
            on_release=self._handle_key_release,
        )
        self._ms_listener = mouse.Listener(
            on_click=self._handle_mouse_click,
            on_scroll=self._handle_mouse_scroll,
        )
        self._kb_listener.start()
        self._ms_listener.start()
        logger.info("pynput input listener started")

    def stop(self) -> None:
        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._ms_listener:
            self._ms_listener.stop()
            self._ms_listener = None
        logger.info("pynput input listener stopped")

    def _handle_key_press(self, key) -> None:
        try:
            rawcode = get_rawcode(key)
            if rawcode:
                self._on_key_press(rawcode)
        except Exception:
            logger.exception("pynput: on_key_press error")

    def _handle_key_release(self, key) -> None:
        try:
            rawcode = get_rawcode(key)
            if rawcode:
                self._on_key_release(rawcode)
        except Exception:
            logger.exception("pynput: on_key_release error")

    def _handle_mouse_click(self, x, y, button, pressed) -> None:
        try:
            button_code = MOUSE_BUTTON_MAP.get(button, 0)
            if button_code:
                self._on_mouse_click(button_code, pressed)
        except Exception:
            logger.exception("pynput: on_mouse_click error")

    def _handle_mouse_scroll(self, x, y, dx, dy) -> None:
        try:
            rotation = -1 if dy > 0 else 1 if dy < 0 else 0
            if rotation:
                self._on_mouse_scroll(rotation)
        except Exception:
            logger.exception("pynput: on_mouse_scroll error")