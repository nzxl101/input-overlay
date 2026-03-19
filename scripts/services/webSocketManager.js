//gup
import { RAW_CODE_TO_KEY_NAME, MOUSE_BUTTON_MAP } from "../consts.js";

/**
 * @typedef {Object} KeyboardInputEvent
 * @property {"key_pressed" | "key_released"} event_type
 * @property {number} rawcode
 */

/**
 * @typedef {Object} MouseMoveEvent
 * @property {"mouse_moved" | "mouse_dragged"} event_type
 */

/**
 * @typedef {Object} MouseButtonEvent
 * @property {"mouse_pressed" | "mouse_released"} event_type
 * @property {number} button
 */

/**
 * @typedef {Object} MouseWheelEvent
 * @property {"mouse_wheel"} event_type
 * @property {number} rotation
 */

/**
 * @typedef {Object} AnalogDepthEvent
 * @property {"analog_depth"} event_type
 * @property {number} depth
 * @property {number} [rawcode]
 */

/**
 * @typedef {KeyboardInputEvent | MouseMoveEvent | MouseButtonEvent | MouseWheelEvent | AnalogDepthEvent} InputEvent
 */

export class WebSocketManager {
    constructor(url, statusEl, visualizer, authToken) {
        this.wsUrl = url;
        this.statusEl = statusEl;
        this.visualizer = visualizer;
        this.authToken = authToken;
        this.elements = visualizer.previewElements;
        this.ws = null;
        this.connectionAttempts = 0;
        this.authenticated = false;

        this.messageHistory = [];
        this.keyStates = {};
        this.keyDepths = {};
        this.HISTORY_MAX_LENGTH = 100;
    }

    connect() {
        this.connectionAttempts++;
        this.statusEl.textContent = `connecting to ${this.wsUrl} (attempt ${this.connectionAttempts})...`;
        this.statusEl.className = "status connecting";

        this.ws = new WebSocket(this.wsUrl);

        this.ws.onopen = this.onOpen.bind(this);
        this.ws.onmessage = this.onMessage.bind(this);
        this.ws.onerror = this.onError.bind(this);
        this.ws.onclose = this.onClose.bind(this);
    }

    onOpen() {
        this.ws.send(JSON.stringify({
            type: 'auth',
            token: this.authToken || ''
        }));

        this.authenticated = true;
        this.connectionAttempts = 0;
        this.statusEl.textContent = this.authToken ? "connected (authenticated)" : "connected";
        this.statusEl.className = "status connected";
        this.clearStuckKeys();
    }

    onMessage(e) {
        try {
            const data = JSON.parse(e.data);

            if (data.type === 'auth_response') {
                if (data.status === 'error' || data.status === 'failed') {
                    this.authenticated = false;
                    const reason = data.message || "invalid token";
                    this.statusEl.textContent = `authentication failed: ${reason}`;
                    this.statusEl.className = "status error";
                    this.ws.close();
                }
                return;
            }

            if (this.authenticated) {
                this.handleOverlayInput(e.data);
            }
        } catch (err) {
            if (this.authenticated) {
                this.handleOverlayInput(e.data);
            }
        }
    }

    onError() {
        this.statusEl.textContent = "connection failed";
        this.statusEl.className = "status error";
    }

    onClose(event) {
        this.authenticated = false;
        if (event.code === 1008) {
            this.statusEl.textContent = "connection closed: authentication required";
            this.statusEl.className = "status error";
            return;
        }

        this.statusEl.textContent = "disconnected. reconnecting...";
        this.statusEl.className = "status connecting";
        this.clearStuckKeys();
        setTimeout(() => this.connect(), 2000);
    }

    getMappedKeyId(event) {
        if (event.event_type.startsWith("key_") || event.event_type === "analog_depth") {
            if (event.rawcode !== undefined) {
                return {
                    id: `k_${event.rawcode}`,
                    name: RAW_CODE_TO_KEY_NAME[event.rawcode],
                    type: "key"
                };
            }
        } else if (event.event_type.startsWith("mouse_") && event.button) {
            return {
                id: `m_${event.button}`,
                name: MOUSE_BUTTON_MAP[event.button],
                type: "mouse"
            };
        }
        return null;
    }

    recalculateKeyStates() {
        const tempStates = {};
        const isKeyActive = {};
        this.elements = this.visualizer.previewElements;

        for (const event of this.messageHistory) {
            const keyInfo = this.getMappedKeyId(event);
            if (!keyInfo || !keyInfo.name || !this.elements) continue;

            const elementMap = keyInfo.type === "key" ? this.elements.keyElements : this.elements.mouseElements;
            const elements = elementMap.get(keyInfo.name);
            if (!elements || elements.length === 0) continue;

            if (event.event_type.endsWith("_pressed")) {
                isKeyActive[keyInfo.id] = true;
            } else if (event.event_type.endsWith("_released")) {
                isKeyActive[keyInfo.id] = false;
            }
        }

        const keysToCheck = new Set([...Object.keys(isKeyActive), ...Object.keys(this.keyStates)]);

        for (const keyId of keysToCheck) {
            const isActive = isKeyActive[keyId] !== undefined ? isKeyActive[keyId] : (this.keyStates[keyId] === true);
            const wasActive = this.keyStates[keyId] === true;

            if (isActive !== wasActive && this.elements) {
                const type = keyId.startsWith("k_") ? "key" : "mouse";
                const idValue = parseInt(keyId.substring(2));
                const keyName = type === "key" ? RAW_CODE_TO_KEY_NAME[idValue] : MOUSE_BUTTON_MAP[idValue];

                const elements = type === "key" ? this.elements.keyElements.get(keyName) : this.elements.mouseElements.get(keyName);
                const activeSet = type === "key" ? this.visualizer.activeKeys : this.visualizer.activeMouseButtons;

                if (elements && elements.length > 0) {
                    elements.forEach(el => {
                        this.visualizer.updateElementState(el, keyName, isActive, activeSet);

                        if (this.visualizer.analogMode && type === "key" && keyName.startsWith("key_")) {
                            const depth = this.keyDepths[keyId];
                            if (depth !== undefined && depth > 0) {
                                this.handleAnalogDepth({ event_type: "analog_depth", depth, rawcode: parseInt(keyId.substring(2)) });
                            }
                        } else if (type === "mouse") {
                            if (isActive) {
                                const animDur = this.visualizer.animDuration || '0.15s';
                                el.style.setProperty('transition', `all ${animDur} cubic-bezier(0.4,0,0.2,1)`, 'important');
                                const maxScale = this.visualizer.pressScaleValue || 1.05;
                                el.style.setProperty('transform', `scale(${maxScale})`, 'important');
                            } else {
                                const animDur = this.visualizer.animDuration || '0.15s';
                                el.style.setProperty('transition', `all ${animDur} cubic-bezier(0.4,0,0.2,1)`, 'important');
                                el.style.setProperty('transform', 'scale(1)', 'important');
                            }
                        }
                    });
                }
            }
            tempStates[keyId] = isActive;
        }

        this.keyStates = Object.fromEntries(
            Object.entries(tempStates).filter(([keyId, isActive]) => isActive || Object.hasOwn(isKeyActive, keyId))
        );
    }

    handleOverlayInput(data) {
        try {
            const event = JSON.parse(data);
            if (event.event_type === "mouse_moved" || event.event_type === "mouse_dragged") return;
            
            if (event.event_type === "analog_depth") {
                if (!this.visualizer.forceDisableAnalog) {
                    this.handleAnalogDepth(event);
                }
                return;
            }

            if (event.event_type === "mouse_wheel") {
                const dir = event.rotation ?? 1;
                if (this.visualizer.previewElements.scrollDisplay) {
                    this.visualizer.handleScroll(dir);
                }
                return;
            }

            this.messageHistory.push(event);
            if (this.messageHistory.length > this.HISTORY_MAX_LENGTH) {
                this.messageHistory.shift();
            }

            if (["key_released", "mouse_released", "key_pressed", "mouse_pressed"].includes(event.event_type)) {
                this.recalculateKeyStates();
            }

        } catch (err) { }
    }

    lerpColor(hexA, hexB, t) {
        const parse = (hex) => {
            if (!hex) return [128, 128, 128];
            const h = hex.replace('#', '');
            const full = h.length === 3
                ? h.split('').map(c => parseInt(c + c, 16))
                : [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
            return full;
        };
        const a = parse(hexA);
        const b = parse(hexB);
        const r = Math.round(a[0] + (b[0] - a[0]) * t);
        const g = Math.round(a[1] + (b[1] - a[1]) * t);
        const bl = Math.round(a[2] + (b[2] - a[2]) * t);
        return `rgb(${r},${g},${bl})`;
    }

    handleAnalogDepth(event) {
        if (!this.visualizer.previewElements) return;

        if (!this.visualizer.analogMode) {
            this.visualizer.analogMode = true;
        }

        const keyInfo = this.getMappedKeyId(event);
        if (!keyInfo || !keyInfo.name || !keyInfo.name.startsWith('key_')) return;

        const depth = event.depth || 0;
        const keyId = keyInfo.id;

        this.keyDepths[keyId] = depth;
        this.visualizer.setAnalogDepthTarget(keyInfo.name, depth);
    }

    clearStuckKeys() {
        if (!this.visualizer.previewElements) return;

        const clearElements = (map) => {
            map.forEach(elements => {
                elements.forEach(el => {
                    el.classList.remove("active");
                    el.classList.remove("analog-key");
                    this.visualizer.activeElements.delete(el);
                    el.style.transform = "";
                    const primaryLabel = el.querySelector('.key-label-primary');
                    if (primaryLabel) {
                        primaryLabel.style.removeProperty('color');
                    }
                    const invertedLabel = el.querySelector('.key-label-inverted');
                    if (invertedLabel) {
                        invertedLabel.style.clipPath = 'inset(100% 0 0 0)';
                    }
                });
            });
        };

        clearElements(this.visualizer.previewElements.keyElements);
        clearElements(this.visualizer.previewElements.mouseElements);

        this.visualizer.activeKeys.clear();
        this.visualizer.activeMouseButtons.clear();

        if (this.visualizer.previewElements.scrollDisplays?.length > 0) {
            this.visualizer.previewElements.scrollDisplays.forEach((display, index) => {
                display.classList.remove("active");
                this.visualizer.activeElements.delete(display);
                this.visualizer.previewElements.scrollArrows[index].textContent = display.dataset.defaultLabel || "-";
                this.visualizer.previewElements.scrollCounts[index].textContent = "";
            });
        }
        this.visualizer.currentScrollCount = 0;
        this.messageHistory = [];
        this.keyStates = {};
        this.keyDepths = {};
        if (this.visualizer.analogRafId) {
            cancelAnimationFrame(this.visualizer.analogRafId);
            this.visualizer.analogRafId = null;
        }
        this.visualizer.analogTargetDepths = {};
        this.visualizer.analogCurrentDepths = {};
    }
}