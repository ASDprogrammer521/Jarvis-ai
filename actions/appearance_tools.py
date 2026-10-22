from __future__ import annotations

import platform
import random
import subprocess
from pathlib import Path

_OS = platform.system()
_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}
IMG = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _run(cmd: list, timeout: int = 8) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_HIDE)
    return (r.stdout or "").strip()


def _pick(src: str) -> Path | None:
    raw = (src or "").strip().strip('"')
    p = Path(raw).expanduser() if raw and raw.lower() not in ("random", "any") else Path.home() / "Pictures"
    if p.is_file():
        return p
    if p.is_dir():
        files = [f for f in p.rglob("*") if f.suffix.lower() in IMG and f.is_file()]
        files = files[:3000]
        return random.choice(files) if files else None
    return None


def set_wallpaper(path: Path) -> None:
    path = path.resolve()
    if _OS == "Windows":
        import ctypes
        if not ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path), 3):
            raise RuntimeError("Windows refused the wallpaper")
    elif _OS == "Darwin":
        _run(["osascript", "-e", f'tell application "System Events" to tell every desktop to set picture to POSIX file "{path}"'])
    else:
        uri = path.as_uri()
        for key in ("picture-uri", "picture-uri-dark"):
            _run(["gsettings", "set", "org.gnome.desktop.background", key, uri])


def dark_mode(mode: str) -> str:
    mode = mode.lower()
    if _OS == "Windows":
        import ctypes
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            light = winreg.QueryValueEx(k, "AppsUseLightTheme")[0]
            want_dark = (light == 1) if mode == "toggle" else mode in ("on", "dark", "night")
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0 if want_dark else 1)
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "ImmersiveColorSet", 2, 3000, None)
        return "dark" if want_dark else "light"
    if _OS == "Darwin":
        cur = _run(["osascript", "-e", 'tell application "System Events" to tell appearance preferences to get dark mode']).lower() == "true"
        want = (not cur) if mode == "toggle" else mode in ("on", "dark", "night")
        _run(["osascript", "-e", f'tell application "System Events" to tell appearance preferences to set dark mode to {str(want).lower()}'])
        return "dark" if want else "light"
    cur = "dark" in _run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"]).lower()
    want = (not cur) if mode == "toggle" else mode in ("on", "dark", "night")
    _run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", "prefer-dark" if want else "default"])
    return "dark" if want else "light"


def appearance_tools(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "wallpaper").lower().strip()
    try:
        if action in ("wallpaper", "set_wallpaper", "background", "change_wallpaper"):
            img = _pick(str(p.get("path") or p.get("source") or ""))
            if img is None:
                return "I couldn't find a picture to use, sir. Give me an image or a folder with pictures."
            set_wallpaper(img)
            return f"Wallpaper changed to {img.name}."
        if action in ("dark_mode", "theme", "dark", "light", "night"):
            mode = str(p.get("mode") or ("on" if action in ("dark", "night") else "off" if action == "light" else "toggle")).lower()
            if mode in ("off", "light", "day"):
                mode = "off"
            return f"Switched the system to {dark_mode(mode)} mode, sir."
    except FileNotFoundError:
        return "That isn't supported on this desktop environment, sir."
    except Exception as e:
        return f"Couldn't change the appearance: {e}"
    return "Unknown action. Available: wallpaper, dark_mode."


TOOL = {
    "name": "appearance_tools",
    "description": (
        "Changes the computer's look: sets the desktop wallpaper from an image or a random picture from a folder, "
        "and switches Windows/macOS/GNOME between dark and light mode. Use for 'change my wallpaper', 'random "
        "background from my Pictures', 'turn on dark mode', 'switch to light mode'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "wallpaper | dark_mode"},
            "path": {"type": "STRING", "description": "Image file or folder for the wallpaper ('random' = from Pictures)"},
            "mode": {"type": "STRING", "description": "on | off | toggle for dark_mode"},
        },
    },
    "handler": appearance_tools,
}

# by ASDcuber521
