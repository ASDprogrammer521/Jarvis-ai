from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_OS = platform.system()


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = base_dir()
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
DATA_DIR = BASE_DIR / "memory"


def cfg() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def log(msg: str, player=None) -> None:
    print(msg)
    if player is not None:
        try:
            player.write_log(msg)
        except Exception:
            pass


def output_dir(sub: str = "") -> Path:
    custom = cfg().get("output_dir")
    root = Path(custom).expanduser() if custom else Path.home() / "Documents" / "Jarvis"
    if sub:
        root = root / sub
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        root = Path.home() / "Desktop"
        root.mkdir(parents=True, exist_ok=True)
    return root


def safe_name(text: str, default: str = "file", limit: int = 60) -> str:
    s = re.sub(r"[^\w\- ]+", "", str(text or ""), flags=re.UNICODE).strip().replace(" ", "_")
    return (s[:limit] or default)


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = folder / f"{stem}_{stamp}{ext}"
    n = 1
    while p.exists():
        p = folder / f"{stem}_{stamp}_{n}{ext}"
        n += 1
    return p


def open_path(path: str | Path) -> None:
    try:
        p = str(path)
        if _OS == "Windows":
            os.startfile(p)
        elif _OS == "Darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as e:
        print(f"[open_path] {e}")


def json_load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def json_save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def ask_json(prompt: str, system: str, default=None, tier: str | None = None, timeout_ms: int = 60_000):
    try:
        from google.genai import types
        from core import gemini
        return gemini.as_json(
            prompt,
            tier=tier or gemini.SMART,
            config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json"),
            timeout_ms=timeout_ms,
            default=default,
        )
    except Exception as e:
        print(f"[ask_json] {e}")
        return default


def ask_text(prompt: str, system: str, default: str = "", tier: str | None = None, timeout_ms: int = 60_000) -> str:
    try:
        from google.genai import types
        from core import gemini
        return gemini.text(
            prompt,
            tier=tier or gemini.SMART,
            config=types.GenerateContentConfig(system_instruction=system),
            timeout_ms=timeout_ms,
            default=default,
        )
    except Exception as e:
        print(f"[ask_text] {e}")
        return default


def need(module: str, pip_name: str | None = None) -> str:
    return f"The Python package '{pip_name or module}' is missing, sir. Install it with:  pip install {pip_name or module}"

# by ASDcuber521
