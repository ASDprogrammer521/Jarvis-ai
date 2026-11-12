"""Helpers for click-through overlays that must stay above everything (games in borderless mode included)."""
from __future__ import annotations

import sys

_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT, _WS_EX_TOOLWINDOW, _WS_EX_NOACTIVATE = 0x20, 0x80, 0x08000000
_HWND_TOPMOST = -1
_SWP = 0x0001 | 0x0002 | 0x0010 | 0x0040        # NOSIZE | NOMOVE | NOACTIVATE | SHOWWINDOW


def force_topmost(widget, click_through: bool = True) -> None:
    """Re-assert the always-on-top state. Games and some launchers steal it, so callers repeat this every second or so.

    Windows: topmost via SetWindowPos plus no-activate / tool-window (no taskbar button, never takes focus) and, if asked,
    a click-through style. Elsewhere: a plain raise_(). Exclusive-fullscreen games can't be overlaid by any normal
    window — borderless / windowed-fullscreen works.
    """
    if sys.platform != "win32":
        widget.raise_()
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = int(widget.winId())
        ex = u.GetWindowLongW(hwnd, _GWL_EXSTYLE) | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE
        if click_through:
            ex |= _WS_EX_TRANSPARENT
        u.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex)
        u.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP)
    except Exception:
        widget.raise_()
