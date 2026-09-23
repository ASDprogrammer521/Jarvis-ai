"""List / enable / disable local plugins (simple plugin store)."""
from __future__ import annotations

from pathlib import Path

from memory import config_manager as cfg

META = {
    "name": "plugin_store",
    "description": (
        "Browse local plugins folder and enable/disable plugins. "
        "Actions: list | enable | disable. value = plugin filename stem."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["action"],
    },
}


def _plugins_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "plugins"


def run(action: str = "list", value: str = "", **_) -> str:
    action = (action or "list").lower().strip()
    d = _plugins_dir()
    files = sorted(p for p in d.glob("*.py") if p.name != "__init__.py" and not p.name.startswith("_"))
    if action == "list":
        if not files:
            return "No plugins found in plugins/ folder. Drop a .py file there to install."
        lines = []
        for f in files:
            on = cfg.get_plugin_enabled(f.stem)
            lines.append(f"{'ON ' if on else 'OFF'}  {f.stem}")
        return "Plugin store:\n" + "\n".join(lines)

    name = (value or "").strip().removesuffix(".py")
    if not name:
        return "Specify plugin name in value."
    path = d / f"{name}.py"
    if not path.is_file():
        return f"Plugin not found: {name}"

    if action == "enable":
        cfg.save_plugin_enabled(name, True)
        return f"Enabled plugin: {name} (restart may be needed)."
    if action == "disable":
        cfg.save_plugin_enabled(name, False)
        return f"Disabled plugin: {name}."
    return "Use action=list|enable|disable"
