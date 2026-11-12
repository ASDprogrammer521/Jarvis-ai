from __future__ import annotations

import re

from actions._common import log


def _secs(p: dict) -> float:
    s = float(p.get("seconds") or 0) + 60.0 * float(p.get("minutes") or 0)
    return s


def _parse_binds(raw) -> list[dict]:
    """Accepts a list of {key, action} or text like 'Q: dash, E: heal, Shift = sprint'."""
    if isinstance(raw, list):
        return [b for b in raw if isinstance(b, dict)]
    out = []
    for part in re.split(r"[;,\n]+", str(raw or "")):
        m = re.match(r"\s*(.+?)\s*[:=\-–>]+\s*(.+?)\s*$", part)
        if m:
            out.append({"key": m.group(1), "action": m.group(2)})
    return out


def game_hud(parameters: dict, player=None, speak=None) -> str:
    from core.game_hud import ROUTINES, get_hud
    p = parameters or {}
    action = str(p.get("action") or "show").lower().strip().replace("-", "_").replace(" ", "_")
    hud = get_hud()
    hud.speak = speak or hud.speak
    hud.log = lambda s: log(s, player)

    def overlay(cmd: str):
        if player is not None and hasattr(player, "module_command"):
            player.module_command("game_hud", cmd)

    try:
        if action in ("show", "on", "open"):
            hud.start()
            overlay("show")
            return "Game HUD is on, sir. It stays on top of your game and never blocks the mouse."
        if action in ("hide", "off", "close"):
            overlay("hide")
            return "Game HUD hidden. Your timers keep running."
        if action == "timer":
            secs = _secs(p)
            if secs <= 0:
                return "How long should the timer be?"
            hud.add_timer(str(p.get("name") or "Timer"), secs, bool(p.get("repeat")))
            overlay("show")
            rep = ", repeating" if p.get("repeat") else ""
            return f"Timer '{p.get('name') or 'Timer'}' set for {int(secs // 60)}m {int(secs % 60)}s{rep}. I'll call it out."
        if action in ("stop_timer", "cancel_timer", "clear_timers"):
            n = hud.stop_timer(str(p.get("name") or "all"))
            return f"Stopped {n} timer(s)." if n else "No matching timer."
        if action == "tip":
            text = str(p.get("text") or "").strip()
            if not text:
                return "What should the tip say?"
            hud.add_tip(text)
            overlay("show")
            return "Tip is on screen."
        if action in ("binds", "set_binds", "keybinds"):
            binds = _parse_binds(p.get("binds") or p.get("text"))
            if binds:
                game, n = hud.set_binds(str(p.get("game") or ""), binds)
                overlay("show")
                return f"Saved {n} key binds for {game}, they're on the HUD."
            if p.get("game"):
                hud.use_game(str(p["game"]))
            overlay("show")
            b = hud.binds()
            return (f"Showing binds for {hud.game or 'your game'}." if b
                    else "No binds saved for this game yet — tell me the keys and what they do.")
        if action in ("game", "use_game"):
            hud.use_game(str(p.get("game") or ""))
            overlay("show")
            return f"Switched the HUD to {hud.game or 'no game'}."
        if action == "coach":
            every = float(p.get("minutes") or 0)
            cues = [c.strip() for c in re.split(r"[;|\n]+", str(p.get("text") or "")) if c.strip()]
            hud.set_coach(every, cues or None)
            overlay("show")
            return (f"Coach on — I'll nudge you every {every:g} minutes." if every > 0 else "Coach off.")
        if action in ("routine", "train", "drill"):
            name = str(p.get("name") or "aim_warmup").lower().replace(" ", "_")
            if not hud.start_routine(name):
                return "Available routines: " + ", ".join(ROUTINES) + "."
            overlay("show")
            return f"Starting {name.replace('_', ' ')}."
        if action == "stop_routine":
            hud.stop_routine()
            return "Routine stopped."
        if action == "position":
            corner = str(p.get("text") or p.get("corner") or "top-right").lower().replace(" ", "-")
            if corner not in ("top-left", "top-right", "bottom-left", "bottom-right"):
                return "Pick top-left, top-right, bottom-left or bottom-right."
            hud.settings["corner"] = corner
            hud.save()
            overlay("show")
            return f"HUD moved to the {corner.replace('-', ' ')}."
        if action in ("fps", "clock", "show_fps", "show_clock"):
            key = "show_fps" if "fps" in action else "show_clock"
            on = str(p.get("text") or p.get("name") or "on").lower() not in ("off", "false", "no", "hide", "0")
            hud.set_setting(key, on)
            overlay("show")
            extra = ""
            if key == "show_fps" and on and hud.fps is not None and not hud.fps.available:
                extra = " FPS needs PresentMon in the tools folder — see Settings → Modules."
            return f"{'FPS counter' if key == 'show_fps' else 'Clock'} {'on' if on else 'off'}.{extra}"
        if action == "clear":
            hud.clear()
            return "HUD cleared."
        if action == "status":
            s = hud.snapshot()
            return (f"{len(s['timers'])} timer(s), game: {s['game'] or 'none'}, coach {'on' if s['coach'] else 'off'}, "
                    f"routine: {s['routine']['name'] if s['routine'] else 'none'}.")
        return "Unknown game_hud action. Use show, hide, timer, tip, binds, coach, routine, position, clear or status."
    except Exception as e:
        return f"Sir, the game HUD failed: {e}"


TOOL = {
    "name": "game_hud",
    "description": (
        "In-game overlay + voice coach (transparent, always on top, click-through). Use for: 'show the game HUD', "
        "'start a Roshan timer 8 minutes repeating', 'set a 30 second cooldown timer', 'show a tip: rotate to B', "
        "'remind me every 5 minutes to check the minimap', 'save my keybinds for Valorant: Q dash, E heal', "
        "'start an aim warmup'. Not for the focus/pomodoro timer (use focus_timer) or one-off reminders (use reminder)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "show | hide | timer | stop_timer | tip | binds | game | coach | routine | stop_routine | position | fps | clock | clear | status"},
            "name": {"type": "STRING", "description": "Timer name or routine name (aim_warmup, eye_break, stretch)"},
            "minutes": {"type": "NUMBER", "description": "Minutes (timer length, or coach interval; 0 turns coach off)"},
            "seconds": {"type": "NUMBER", "description": "Seconds (timer length)"},
            "repeat": {"type": "BOOLEAN", "description": "Timer restarts automatically when it ends"},
            "text": {"type": "STRING", "description": "Tip text; coach cues separated by ';'; corner for position; on/off for fps and clock"},
            "game": {"type": "STRING", "description": "Game name for key binds"},
            "binds": {"type": "STRING", "description": "Key binds as 'Q: dash, E: heal, Shift: sprint'"},
        },
        "required": ["action"],
    },
    "handler": game_hud,
}
