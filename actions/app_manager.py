from __future__ import annotations

import os
import platform
import subprocess
import time
from pathlib import Path

from actions._common import human_size, log, own_pids

_OS = platform.system()
_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}
PROTECTED = {"system", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass", "svchost", "dwm", "explorer",
             "fontdrvhost", "init", "systemd", "xorg", "gnome-shell", "kwin", "launchd", "loginwindow", "windowserver", "finder"}
BACKGROUND_APPS = {"discord", "spotify", "steam", "telegram", "slack", "teams", "whatsapp", "skype", "onedrive", "dropbox",
                   "epicgameslauncher", "battle.net", "zoom", "viber", "signal", "notion", "obsidian"}
ALIASES = {"vs code": "code", "vscode": "code", "visual studio code": "code", "google chrome": "chrome", "microsoft edge": "msedge",
           "edge": "msedge", "opera gx": "opera", "operagx": "opera", "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
           "task manager": "taskmgr", "file explorer": "explorer", "notepad": "notepad", "whatsapp": "whatsapp", "telegram": "telegram"}


def _norm(n: str) -> str:
    n = (n or "").lower().strip()
    for suf in (".exe", ".app", ".bin"):
        if n.endswith(suf):
            n = n[: -len(suf)]
    return n.replace(" ", "")


def _target(name: str) -> str:
    t = (name or "").lower().strip()
    return _norm(ALIASES.get(t, t))


def _matches(target: str) -> list:
    import psutil
    mine = own_pids()
    out = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            n = _norm(p.info["name"] or "")
            if not n or p.info["pid"] in mine or n in PROTECTED:
                continue
            if n == target or n.startswith(target) or (len(target) >= 4 and target in n):
                out.append(p)
        except Exception:
            continue
    return out


def _graceful(procs) -> None:
    for p in procs:
        try:
            if _OS == "Windows":
                subprocess.run(["taskkill", "/PID", str(p.pid)], capture_output=True, timeout=5, **_HIDE)
            elif _OS == "Darwin":
                p.terminate()
            else:
                p.terminate()
        except Exception:
            pass


def _force(procs) -> None:
    for p in procs:
        try:
            if _OS == "Windows":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=5, **_HIDE)
            else:
                p.kill()
        except Exception:
            pass


def close_app(name: str, force, player=None) -> str:
    import psutil
    target = _target(name)
    if not target:
        return "Sir, tell me which app to close."
    if target in ("jarvis", "python", "pythonw", "main") and not [p for p in _matches(target)]:
        return "I won't close myself, sir."
    procs = _matches(target)
    if not procs:
        return f"I don't see {name} running, sir."
    shown = sorted({(p.info["name"] or "").rsplit(".", 1)[0] for p in procs})[0]
    mem = sum((p.info["memory_info"].rss if p.info.get("memory_info") else 0) for p in procs)
    _graceful(procs)
    _, alive = psutil.wait_procs(procs, timeout=3.0)
    if alive:
        want_force = force if force is not None else (target in BACKGROUND_APPS)
        if want_force:
            _force(alive)
            _, alive = psutil.wait_procs(alive, timeout=2.0)
        else:
            log(f"[Apps] {shown} is still open", player)
            return (f"I asked {shown} to close but it is still running — it may be asking to save your work. "
                    f"Say 'force close {name}' if you want me to end it anyway.")
    if alive:
        return f"I couldn't fully close {shown}; {len(alive)} process(es) are still running, sir."
    log(f"[Apps] Closed {shown} ({len(procs)} processes, {human_size(mem)})", player)
    return f"Closed {shown}, sir — freed about {human_size(mem)}."


def top_apps(sort: str, n: int) -> str:
    import psutil
    groups: dict = {}
    procs = list(psutil.process_iter(["pid", "name", "memory_info"]))
    if sort == "cpu":
        for p in procs:
            try:
                p.cpu_percent(None)
            except Exception:
                pass
        time.sleep(0.7)
    for p in procs:
        try:
            name = (p.info["name"] or "?").rsplit(".", 1)[0]
            g = groups.setdefault(name.lower(), {"name": name, "mem": 0, "cpu": 0.0, "n": 0})
            g["mem"] += p.info["memory_info"].rss if p.info.get("memory_info") else 0
            g["n"] += 1
            if sort == "cpu":
                g["cpu"] += p.cpu_percent(None)
        except Exception:
            continue
    key = "cpu" if sort == "cpu" else "mem"
    rows = sorted(groups.values(), key=lambda g: g[key], reverse=True)[: max(1, min(25, n))]
    ncpu = psutil.cpu_count() or 1
    lines = [f"Top apps by {'CPU' if sort == 'cpu' else 'memory'}:"]
    for i, g in enumerate(rows, 1):
        extra = f"{g['cpu'] / ncpu:.0f}% CPU" if sort == "cpu" else human_size(g["mem"])
        lines.append(f"{i}. {g['name']} — {extra}" + (f" ({g['n']} processes)" if g["n"] > 1 else ""))
    vm = psutil.virtual_memory()
    lines.append(f"RAM in use: {human_size(vm.used)} of {human_size(vm.total)} ({vm.percent:.0f}%).")
    return "\n".join(lines)


def find_app(name: str) -> str:
    procs = _matches(_target(name))
    if not procs:
        return f"{name} is not running."
    mem = sum((p.info["memory_info"].rss if p.info.get("memory_info") else 0) for p in procs)
    return f"{name} is running: {len(procs)} process(es), using {human_size(mem)} of RAM."


def startup_items() -> str:
    items: list = []
    try:
        if _OS == "Windows":
            import winreg
            for hive, label in ((winreg.HKEY_CURRENT_USER, "user"), (winreg.HKEY_LOCAL_MACHINE, "all users")):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                        i = 0
                        while True:
                            n, v, _ = winreg.EnumValue(k, i)
                            items.append(f"{n} ({label})")
                            i += 1
                except OSError:
                    pass
            sf = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
            if sf.exists():
                items += [f"{f.stem} (startup folder)" for f in sf.iterdir() if f.is_file() and f.suffix.lower() != ".ini"]
        elif _OS == "Darwin":
            for d in (Path.home() / "Library/LaunchAgents", Path("/Library/LaunchAgents")):
                if d.exists():
                    items += [f.stem for f in d.glob("*.plist")]
        else:
            d = Path.home() / ".config/autostart"
            if d.exists():
                items += [f.stem for f in d.glob("*.desktop")]
    except Exception as e:
        return f"I couldn't read the startup list: {e}"
    if not items:
        return "No startup programs found, sir."
    return f"{len(items)} programs start with your computer:\n" + "\n".join(f"• {i}" for i in sorted(set(items)))


def app_manager(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "top").lower().strip()
    try:
        if action in ("close", "quit", "kill", "exit", "stop"):
            force = p.get("force")
            if action == "kill":
                force = True
            return close_app(str(p.get("name") or ""), force if force is not None else None, player)
        if action in ("top", "list", "usage", "ram", "cpu"):
            sort = "cpu" if action == "cpu" or str(p.get("sort") or "").lower() == "cpu" else "memory"
            text = top_apps(sort, int(p.get("count") or 8))
            if player is not None and hasattr(player, "show_content"):
                player.show_content("RUNNING APPS", text)
            return text
        if action in ("find", "status", "running"):
            return find_app(str(p.get("name") or ""))
        if action == "startup":
            text = startup_items()
            if player is not None and hasattr(player, "show_content"):
                player.show_content("STARTUP PROGRAMS", text)
            return text
    except ImportError:
        return "Sir, I need the 'psutil' package: pip install psutil"
    except Exception as e:
        return f"App manager failed: {e}"
    return "Unknown action. Available: close, top, find, startup."


TOOL = {
    "name": "app_manager",
    "description": (
        "Closes or quits a NAMED application (Discord, Chrome, Spotify, Steam, any program), shows which apps use the "
        "most RAM or CPU, checks whether an app is running, and lists programs that start with the computer. "
        "ALWAYS use this when the user says close, quit, exit, kill or shut down an app by name — never use "
        "hotkeys like Alt+F4 for that, they would close the wrong window."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "close | top | find | startup"},
            "name": {"type": "STRING", "description": "App name for close/find, e.g. 'Discord', 'Chrome'"},
            "force": {"type": "BOOLEAN", "description": "End the app even if it asks to save (for 'force close')"},
            "sort": {"type": "STRING", "description": "memory | cpu (for top)"},
            "count": {"type": "INTEGER", "description": "How many apps to list (default 8)"},
        },
        "required": ["action"],
    },
    "handler": app_manager,
}

# by ASDcuber521
