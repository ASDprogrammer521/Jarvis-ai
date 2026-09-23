"""Switch Jarvis profiles: home / work / game."""
from __future__ import annotations

from memory import config_manager as cfg

META = {
    "name": "profile_switch",
    "description": "Switch or list user profiles (home, work, game). action=list|set, value=profile name.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["action"],
    },
}


def run(action: str = "list", value: str = "", **_) -> str:
    action = (action or "list").lower().strip()
    if action == "list":
        names = cfg.list_profiles()
        active = cfg.get_active_profile_name()
        lines = [f"{'*' if n == active else ' '} {n}  {cfg.get_profile(n)}" for n in names]
        return "Profiles:\n" + "\n".join(str(x) for x in lines)
    if action in ("set", "switch", "activate"):
        name = (value or "").strip().lower()
        if name not in cfg.list_profiles() and name not in ("home", "work", "game"):
            return f"Unknown profile: {name}. Use home, work, or game."
        cfg.set_active_profile(name)
        return f"Active profile: {name}. Some UI options apply on next relevant action."
    return "Use action=list or set"
