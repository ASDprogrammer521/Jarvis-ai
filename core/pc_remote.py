"""
Commands the phone sends to this PC ("[PC_CONTROL] <command>").

Kept out of main.py so it can be tested and extended in one place. Every command returns a
short sentence for the log / the phone; nothing here raises.

    lock · shutdown · mute · volume_up · volume_down · play_pause · next · prev
    close|minimize|maximize|restore|focus <app name>
"""
from __future__ import annotations

import subprocess
import sys

_MEDIA_KEYS = {"play_pause": "playpause", "next": "nexttrack", "prev": "prevtrack"}
_APP_WINDOW_OPS = ("minimize", "maximize", "restore", "focus")


def _lock() -> str:
    if sys.platform == "win32":
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif sys.platform == "darwin":
        subprocess.Popen(["pmset", "displaysleepnow"])
    else:
        subprocess.Popen(["loginctl", "lock-session"])
    return "PC locked"


def _shutdown() -> str:
    if sys.platform == "win32":
        subprocess.Popen(["shutdown", "/s", "/t", "15"])       # `shutdown /a` cancels it
        return "PC shutdown scheduled in 15 seconds (run `shutdown /a` to cancel)"
    subprocess.Popen(["shutdown", "-h", "+1"])
    return "PC shutdown scheduled in 1 minute (`shutdown -c` cancels)"


def run(cmd: str, player=None) -> str:
    cmd = (cmd or "").strip()
    low = cmd.lower().replace("-", "_")
    try:
        if low in ("lock", "pc lock", "lock pc"):
            return _lock()
        if low in ("shutdown", "off", "poweroff", "pc off"):
            return _shutdown()

        if low in ("mute", "volume_up", "volume_down"):
            from actions.computer_settings import ACTION_MAP
            ACTION_MAP[low]()
            return {"mute": "PC mute toggled", "volume_up": "PC volume up", "volume_down": "PC volume down"}[low]

        if low in _MEDIA_KEYS:
            import pyautogui
            pyautogui.press(_MEDIA_KEYS[low])
            return {"play_pause": "Play / pause", "next": "Next track", "prev": "Previous track"}[low]

        verb, _, app = cmd.partition(" ")
        verb = verb.lower()
        app = app.strip()
        if verb == "close" and app:
            from actions.app_manager import close_app
            return close_app(app, None, player)
        if verb in _APP_WINDOW_OPS and app:
            from actions.app_manager import window_op
            return window_op(verb, app, player)
    except Exception as e:
        return f"PC control error: {e}"
    return f"Unknown PC control: {cmd}"
