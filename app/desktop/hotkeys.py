"""Windows 原生全局快捷键管理（Alt+Space 唤醒、Alt+S 截屏）."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_MAP: dict[str, int] = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}


def parse_hotkey(combo: str) -> tuple[int, int] | None:
    """将 'Alt+Space' / 'Ctrl+Shift+A' 解析为 (modifiers, vk_code)."""
    if not combo:
        return None
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        return None
    mods = MOD_NOREPEAT
    vk = 0
    for part in parts:
        if part in ("alt", "option"):
            mods |= MOD_ALT
        elif part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("win", "meta", "super"):
            mods |= MOD_WIN
        elif part in VK_MAP:
            vk = VK_MAP[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
    if vk == 0:
        return None
    return mods, vk


class WinHotkeyManager(QAbstractNativeEventFilter):
    def __init__(self) -> None:
        super().__init__()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_id = 1001

    def register(self, combo: str, callback: Callable[[], None]) -> bool:
        if os.name != "nt":
            return False
        parsed = parse_hotkey(combo)
        if not parsed:
            return False
        mods, vk = parsed
        hid = self._next_id
        self._next_id += 1
        ok = bool(ctypes.windll.user32.RegisterHotKey(None, hid, mods, vk))
        if ok:
            self._callbacks[hid] = callback
        return ok

    def unregister_all(self) -> None:
        if os.name != "nt":
            return
        for hid in list(self._callbacks.keys()):
            try:
                ctypes.windll.user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._callbacks.clear()

    def nativeEventFilter(self, event_type, message):  # type: ignore[override]
        if os.name != "nt" or event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                cb = self._callbacks.get(int(msg.wParam))
                if cb:
                    cb()
                    return True, 0
        except Exception:
            pass
        return False, 0
