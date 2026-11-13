from __future__ import annotations
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(platform.system(), "linux")

def desktop_directory(os_name: str | None = None) -> Path:
    if (os_name or platform.system()) == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Desktop"

def read_json_dict(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}

def read_gemini_api_key(path) -> str:
    with open(path, "r", encoding="utf-8") as config_file:
        return json.load(config_file)["gemini_api_key"]

def ensure_pyautogui_available(available):
    if not available:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

def normalize_optional(value, allowed):
    normalized = str(value or "").strip().upper()
    return normalized if normalized in allowed else None

def run_capture(cmd, timeout=8, extra_kwargs=None):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **(extra_kwargs or {}))
    return (result.stdout or "").strip()

#by ASDcuber
