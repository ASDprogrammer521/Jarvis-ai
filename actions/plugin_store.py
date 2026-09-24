from __future__ import annotations

import re
import urllib.request
from pathlib import Path

from memory import config_manager as cfg

META = {
    "name": "plugin_store",
    "description": "Plugin store: list, enable, disable, install from URL. action=list|enable|disable|install. value=name or URL.",
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


def _safe_name(name: str) -> str:
    n = re.sub(r"[^a-zA-Z0-9_\-]", "", (name or "").strip().removesuffix(".py"))
    return n[:64]


def list_plugins() -> list[dict]:
    d = _plugins_dir()
    out = []
    for f in sorted(d.glob("*.py")):
        if f.name.startswith("_") or f.name == "__init__.py":
            continue
        desc = "Local plugin"
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'["\']description["\']\s*:\s*["\']([^"\']+)["\']', text)
            if m:
                desc = m.group(1)[:160]
        except Exception:
            pass
        out.append({
            "name": f.stem,
            "enabled": cfg.get_plugin_enabled(f.stem),
            "description": desc,
            "path": str(f),
        })
    return out


def install_from_url(url: str) -> str:
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "URL must start with http:// or https://"
    if "raw.githubusercontent.com" not in url and not url.endswith(".py"):
        return "Use a raw .py URL (e.g. raw.githubusercontent.com/.../plugin.py)"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-PluginStore/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        text = data.decode("utf-8", errors="replace")
        if "def run" not in text and "META" not in text:
            return "File does not look like a Jarvis plugin (need META/run)."
        name = _safe_name(Path(url.split("?")[0]).stem) or "plugin"
        dest = _plugins_dir() / f"{name}.py"
        dest.write_text(text, encoding="utf-8")
        cfg.save_plugin_enabled(name, True)
        return f"Installed plugin: {name}"
    except Exception as e:
        return f"Install failed: {e}"


def run(action: str = "list", value: str = "", **_) -> str:
    action = (action or "list").lower().strip()
    d = _plugins_dir()
    d.mkdir(parents=True, exist_ok=True)

    if action == "list":
        plugs = list_plugins()
        if not plugs:
            return "No plugins found. Open http://PC-IP:8000/plugin-store or drop .py into plugins/."
        lines = [f"{'ON ' if p['enabled'] else 'OFF'}  {p['name']} — {p['description']}" for p in plugs]
        return "Plugin store:\n" + "\n".join(lines)

    if action == "install":
        return install_from_url(value)

    name = _safe_name(value)
    if not name:
        return "Specify plugin name in value."
    path = d / f"{name}.py"
    if not path.is_file():
        return f"Plugin not found: {name}"
    if action == "enable":
        cfg.save_plugin_enabled(name, True)
        return f"Enabled: {name}"
    if action == "disable":
        cfg.save_plugin_enabled(name, False)
        return f"Disabled: {name}"
    return "Use action=list|enable|disable|install"
