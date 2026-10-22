from __future__ import annotations

from memory import config_manager as cfg


def profile_switch(parameters: dict, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").lower().strip()
    if action == "list":
        active = cfg.get_active_profile_name()
        lines = []
        for n in ("home", "work", "game"):
            pr = cfg.get_profile(n)
            lines.append(f"{'*' if n == active else ' '} {n}: model {pr.get('hud')}, "
                         f"{'push-to-talk' if pr.get('talk_mode') == 'push' else 'open mic'}, quality {pr.get('quality', 'auto')}")
        return "Profiles:\n" + "\n".join(lines)
    if action in ("set", "switch", "activate"):
        name = str(p.get("value") or "").strip().lower()
        if name not in ("home", "work", "game"):
            return f"Unknown profile '{name}'. Use home, work or game."
        if player is not None and hasattr(player, "apply_profile"):
            player.apply_profile(name)
        else:
            cfg.set_active_profile(name)
        return f"Switched to the {name} profile, sir."
    return "Use action=list or action=set."


TOOL = {
    "name": "profile_switch",
    "description": (
        "Switches Jarvis between the Home, Work and Game profiles (3D model, push-to-talk or open mic, and "
        "graphics quality) or lists them. Use when the user says things like 'switch to work mode' or 'game mode on'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list | set"},
            "value": {"type": "STRING", "description": "home | work | game (for action=set)"},
        },
        "required": ["action"],
    },
    "handler": profile_switch,
}

# by ASDcuber521
