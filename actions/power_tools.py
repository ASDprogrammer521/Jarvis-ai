from __future__ import annotations

import platform
import subprocess
import threading
import time

from actions._common import human_size, log

_OS = platform.system()
_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}
_SCHED: dict = {}
_CMDS = {
    "shutdown": {"Windows": ["shutdown", "/s", "/t", "0"], "Darwin": ["osascript", "-e", 'tell application "System Events" to shut down'],
                 "Linux": ["systemctl", "poweroff"]},
    "restart": {"Windows": ["shutdown", "/r", "/t", "0"], "Darwin": ["osascript", "-e", 'tell application "System Events" to restart'],
                "Linux": ["systemctl", "reboot"]},
    "sleep": {"Windows": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], "Darwin": ["pmset", "sleepnow"], "Linux": ["systemctl", "suspend"]},
    "lock": {"Windows": ["rundll32.exe", "user32.dll,LockWorkStation"], "Darwin": ["pmset", "displaysleepnow"], "Linux": ["loginctl", "lock-session"]},
}


def _exec(kind: str) -> None:
    subprocess.Popen(_CMDS[kind][_OS], **_HIDE)


def battery() -> str:
    import psutil
    b = psutil.sensors_battery()
    if b is None:
        return "This computer has no battery, sir — it's on mains power."
    mins = None if b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else int(b.secsleft // 60)
    state = "charging" if b.power_plugged else "on battery"
    left = f", about {mins // 60}h {mins % 60}m left" if (mins and not b.power_plugged) else ""
    return f"Battery {b.percent:.0f}% — {state}{left}."


def uptime() -> str:
    import psutil
    s = int(time.time() - psutil.boot_time())
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return f"Your computer has been on for {(str(d) + ' d ') if d else ''}{h} h {m} min."


def _schedule(kind: str, minutes: float) -> str:
    def fire():
        if _SCHED.get("kind") == kind:
            _SCHED.clear()
            _exec(kind)
    old = _SCHED.get("timer")
    if old:
        old.cancel()
    t = threading.Timer(minutes * 60, fire)
    t.daemon = True
    _SCHED.update({"kind": kind, "timer": t, "at": time.time() + minutes * 60})
    t.start()
    return f"Scheduled: {kind} in {minutes:g} minutes. Say 'cancel the shutdown' to stop it."


def power_tools(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "battery").lower().strip()
    try:
        if action in ("battery", "charge", "status"):
            return battery() + " " + uptime()
        if action == "uptime":
            return uptime()
        if action in ("lock", "sleep"):
            _exec(action)
            return "Locking the screen, sir." if action == "lock" else "Putting the computer to sleep, sir."
        if action in ("shutdown", "restart"):
            from core import confirm
            mins = float(p.get("minutes") or 0)
            if mins > 0:
                return confirm.request(f"{action}_later", f"{action.title()} in {mins:g} minutes",
                                       "Unsaved work will be lost when the timer ends.", lambda: _schedule(action, mins))
            return confirm.request(action, f"{action.title()} the computer now", "Unsaved work will be lost.", lambda: (_exec(action), "Done.")[1])
        if action in ("cancel", "cancel_shutdown", "abort"):
            t = _SCHED.get("timer")
            if t:
                t.cancel()
                _SCHED.clear()
                return "Cancelled the scheduled power action, sir."
            return "Nothing is scheduled, sir."
    except ImportError as e:
        return f"Sir, I need the '{e.name}' package: pip install {e.name}"
    except Exception as e:
        return f"Power action failed: {e}"
    return "Unknown action. Available: battery, uptime, lock, sleep, shutdown, restart, cancel."


TOOL = {
    "name": "power_tools",
    "description": (
        "Power and battery: battery level and time left, how long the PC has been on, lock the screen, put the PC to "
        "sleep, shut down or restart (immediately or after N minutes — asks for confirmation on screen) and cancel a "
        "scheduled shutdown."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "battery | uptime | lock | sleep | shutdown | restart | cancel"},
            "minutes": {"type": "NUMBER", "description": "Delay in minutes for shutdown/restart (0 = now)"},
        },
    },
    "handler": power_tools,
}

# by ASDcuber521
