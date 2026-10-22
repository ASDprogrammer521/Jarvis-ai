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


def human_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def own_pids() -> set:
    pids = {os.getpid()}
    try:
        import psutil
        me = psutil.Process()
        for a in me.parents():
            pids.add(a.pid)
        for c in me.children(recursive=True):
            pids.add(c.pid)
    except Exception:
        pass
    return pids


def jarvis_has_focus() -> bool:
    try:
        mine = own_pids()
        if _OS == "Windows":
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
            return pid.value in mine
        if _OS == "Darwin":
            out = subprocess.run(["osascript", "-e", 'tell application "System Events" to get unix id of first process whose frontmost is true'],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            return out.isdigit() and int(out) in mine
        out = subprocess.run(["xdotool", "getwindowfocus", "getwindowpid"], capture_output=True, text=True, timeout=3).stdout.strip()
        return out.isdigit() and int(out) in mine
    except Exception:
        return False


def clip_read() -> str:
    if _OS == "Windows":
        cmd = ["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"]
    elif _OS == "Darwin":
        cmd = ["pbpaste"]
    elif shutil_which("wl-paste"):
        cmd = ["wl-paste", "--no-newline"]
    elif shutil_which("xclip"):
        cmd = ["xclip", "-o", "-selection", "clipboard"]
    else:
        cmd = ["xsel", "--clipboard", "--output"]
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}
    r = subprocess.run(cmd, capture_output=True, timeout=6, **flags)
    return r.stdout.decode("utf-8", errors="replace").rstrip("\r\n")


def clip_write(text: str) -> None:
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}
    if _OS == "Windows":
        cmd = ["powershell", "-NoProfile", "-Command", "[Console]::InputEncoding=[Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"]
    elif _OS == "Darwin":
        cmd = ["pbcopy"]
    elif shutil_which("wl-copy"):
        cmd = ["wl-copy"]
    elif shutil_which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    else:
        cmd = ["xsel", "--clipboard", "--input"]
    subprocess.run(cmd, input=text.encode("utf-8"), timeout=6, check=True, **flags)


def shutil_which(name: str):
    import shutil
    return shutil.which(name)

# by ASDcuber521
