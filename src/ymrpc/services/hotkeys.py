"""Глобальные горячие клавиши через RegisterHotKey + Qt native event filter."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

logger = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

VK = {
    "M": 0x4D,
    "L": 0x4C,
    "P": 0x50,
    "H": 0x48,
    "LEFT": 0x25,
    "RIGHT": 0x27,
}

BINDINGS: dict[str, tuple[int, int]] = {
    "toggle_player": (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK["M"]),
    "lyrics": (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK["L"]),
    "play_pause": (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK["P"]),
    "next": (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK["RIGHT"]),
    "previous": (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK["LEFT"]),
    "presence": (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK["H"]),
}


class GlobalHotkeys(QObject, QAbstractNativeEventFilter):
    activated = Signal(str)
    failed = Signal(str)

    def __init__(self):
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self._registered: list[int] = []
        self._ids: dict[int, str] = {}
        self._counter = 0x594D

    def register(self) -> list[str]:
        self.unregister()
        if sys.platform != "win32":
            return []
        errors = []
        for action, (modifiers, key) in BINDINGS.items():
            self._counter += 1
            hotkey_id = self._counter
            if ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                self._registered.append(hotkey_id)
                self._ids[hotkey_id] = action
            else:
                errors.append(action)
                self.failed.emit(action)
        if errors:
            logger.info("Занятые горячие клавиши: %s", ", ".join(errors))
        return errors

    def unregister(self) -> None:
        if sys.platform == "win32":
            for hotkey_id in self._registered:
                ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        self._registered.clear()
        self._ids.clear()

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if sys.platform != "win32":
            return False, 0
        try:
            if b"windows" not in bytes(event_type):
                return False, 0
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                action = self._ids.get(int(msg.wParam))
                if action:
                    self.activated.emit(action)
                    return True, 0
        except Exception:  # noqa: BLE001
            return False, 0
        return False, 0
