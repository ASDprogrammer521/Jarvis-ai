from __future__ import annotations

import threading
import time

from actions._common import log

_STATE: dict = {"stop": None, "info": {}}


def _say(speak, player, text: str, instruction: str) -> None:
    log(f"[Focus] {text}", player)
    if speak:
        try:
            speak(f"[Focus] {instruction}")
        except Exception:
            pass


def _loop(player, speak, focus: float, brk: float, rounds: int, stop: threading.Event, info: dict) -> None:
    for r in range(1, rounds + 1):
        info.update(phase="focus", round=r, ends=time.time() + focus * 60)
        if stop.wait(focus * 60):
            return
        if r == rounds:
            break
        info.update(phase="break", round=r, ends=time.time() + brk * 60)
        _say(speak, player, f"Round {r} done — break time", f"Focus round {r} is over. Tell the user in one short sentence to take a {brk:g}-minute break.")
        if stop.wait(brk * 60):
            return
        _say(speak, player, "Break over — back to focus", "The break is over. Tell the user in one short sentence it's time to focus again.")
    info.update(phase="done")
    _say(speak, player, "Focus session complete", f"The focus session is complete: {rounds} round(s). Congratulate the user in one short sentence.")


def focus_timer(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "start").lower().strip()
    info = _STATE["info"]
    if action == "start":
        if _STATE["stop"] is not None:
            _STATE["stop"].set()
        focus = max(0.05, min(180.0, float(p.get("minutes") or 25)))
        brk = max(0.05, min(60.0, float(p.get("break_minutes") or 5)))
        rounds = max(1, min(12, int(p.get("rounds") or 1)))
        stop = threading.Event()
        _STATE["stop"], _STATE["info"] = stop, {}
        threading.Thread(target=_loop, args=(player, speak, focus, brk, rounds, stop, _STATE["info"]), daemon=True, name="focus-timer").start()
        extra = f" with {brk:g}-minute breaks, {rounds} rounds" if rounds > 1 else ""
        return f"Focus mode on, sir — {focus:g} minutes{extra}. I'll tell you when it's time."
    if action in ("stop", "cancel", "end"):
        if _STATE["stop"] is None or info.get("phase") in (None, "done"):
            return "No focus session is running, sir."
        _STATE["stop"].set()
        return "Focus session stopped."
    if action in ("status", "left", "remaining"):
        if not info or info.get("phase") == "done":
            return "No focus session is running, sir."
        left = max(0, int(info["ends"] - time.time()))
        return f"{info['phase'].title()} phase, round {info['round']}: {left // 60} min {left % 60} s left."
    return "Unknown action. Available: start, stop, status."


TOOL = {
    "name": "focus_timer",
    "description": (
        "Pomodoro-style focus timer. Starts a focus session (default 25 min, optional breaks and several rounds) and "
        "speaks when to take a break or return to work. Also status and stop. Use for 'focus mode', 'start a pomodoro', "
        "'let me work for 45 minutes'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "start | stop | status"},
            "minutes": {"type": "NUMBER", "description": "Focus length in minutes (default 25)"},
            "break_minutes": {"type": "NUMBER", "description": "Break length (default 5)"},
            "rounds": {"type": "INTEGER", "description": "Number of focus rounds (default 1)"},
        },
    },
    "handler": focus_timer,
}

# by ASDcuber521
