"""System-wide hotkey (e.g. Alt+Space) that works while any other window has focus.

Windows: `RegisterHotKey` on its own message-loop thread — unlike polling key state, a registered hotkey also stops
the system menu from popping up on Alt+Space. Other systems: `start()` returns False and the UI binds the chord as an
ordinary application shortcut instead (works while Jarvis' window has focus).
"""
from __future__ import annotations

import sys
import threading

_MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
_KEYS = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "`": 0xC0}
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012


def parse(chord: str) -> tuple[int, int] | None:
    mods, vk = 0, 0
    for part in (chord or "").lower().replace(" ", "").split("+"):
        if part in _MODS:
            mods |= _MODS[part]
        elif part in _KEYS:
            vk = _KEYS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x6F + int(part[1:])
        else:
            return None
    return (mods, vk) if mods and vk else None


def qt_name(chord: str) -> str:
    return "+".join(p.capitalize() for p in chord.lower().split("+"))


class GlobalHotkey:
    def __init__(self, chord: str, callback):
        self.chord, self.callback = chord, callback
        self._tid = 0
        self._thread: threading.Thread | None = None
        self.error = ""

    def start(self) -> bool:
        parsed = parse(self.chord)
        if sys.platform != "win32" or parsed is None:
            self.error = "global hotkeys are Windows-only" if parsed else f"can't understand '{self.chord}'"
            return False
        ready = threading.Event()
        ok = []

        def loop():
            import ctypes
            from ctypes import wintypes
            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            self._tid = k32.GetCurrentThreadId()
            if not u32.RegisterHotKey(None, 1, parsed[0] | MOD_NOREPEAT, parsed[1]):
                self.error = f"{self.chord} is already used by another program"
                ready.set()
                return
            ok.append(True)
            ready.set()
            msg = wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception:
                        pass
            u32.UnregisterHotKey(None, 1)

        self._thread = threading.Thread(target=loop, daemon=True, name="global-hotkey")
        self._thread.start()
        ready.wait(2)
        return bool(ok)

    def stop(self):
        if self._tid and sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._tid = 0
