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


# ───────────────────────── window control by app name ─────────────────────────
# "minimize Discord" must act on Discord's own window, never on whatever window
# has focus (that is Jarvis itself while the user is talking to it).

_SW = {"minimize": 6, "maximize": 3, "restore": 9, "focus": 9}
WINDOW_ACTIONS = tuple(_SW)


def _win_handles(pids: set, title_hint: str) -> list:
    """Visible top-level Windows windows owned by `pids` or whose title contains the hint."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetWindow.restype = wintypes.HWND            # 64-bit handles must not be truncated
    u.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    mine = own_pids()
    found: list = []
    hint = (title_hint or "").lower().strip()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        try:
            if not u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
                return True
            if u.GetWindow(hwnd, 4):  # GW_OWNER -> owned dialogs / tool windows
                return True
            ex = u.GetWindowLongW(hwnd, -20)
            if ex & 0x80:  # WS_EX_TOOLWINDOW
                return True
            n = u.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in mine:
                return True
            if pid.value in pids or (hint and len(hint) >= 3 and hint in buf.value.lower()):
                found.append((hwnd, buf.value))
        except Exception:
            pass
        return True

    u.EnumWindows(cb, 0)
    return found


def _windows_window_op(action: str, pids: set, name: str) -> list:
    import ctypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    wins = _win_handles(pids, name)
    for hwnd, _title in wins:
        u.ShowWindow(hwnd, _SW[action])
        if action in ("restore", "focus", "maximize"):
            try:
                u.keybd_event(0x12, 0, 0, 0)          # Alt tap lets SetForegroundWindow succeed
                u.SetForegroundWindow(hwnd)
                u.keybd_event(0x12, 0, 2, 0)
            except Exception:
                pass
    return [t for _, t in wins]


def _linux_window_op(action: str, pids: set, name: str) -> list:
    import shutil
    if not shutil.which("wmctrl"):
        raise RuntimeError("wmctrl is not installed (sudo apt install wmctrl)")
    out = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=4).stdout
    hint = (name or "").lower()
    done = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        wid, _desk, pid, _host, title = parts
        if int(pid) in own_pids() or not (int(pid) in pids or (len(hint) >= 3 and hint in title.lower())):
            continue
        if action == "minimize":
            if shutil.which("xdotool"):
                subprocess.run(["xdotool", "windowminimize", wid], capture_output=True, timeout=4)
            else:
                subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "add,hidden"], capture_output=True, timeout=4)
        elif action == "maximize":
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "remove,hidden"], capture_output=True, timeout=4)
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "add,maximized_vert,maximized_horz"], capture_output=True, timeout=4)
            subprocess.run(["wmctrl", "-i", "-a", wid], capture_output=True, timeout=4)
        else:
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "remove,hidden,maximized_vert,maximized_horz"] if action == "restore"
                           else ["wmctrl", "-i", "-r", wid, "-b", "remove,hidden"], capture_output=True, timeout=4)
            subprocess.run(["wmctrl", "-i", "-a", wid], capture_output=True, timeout=4)
        done.append(title)
    return done


def _mac_window_op(action: str, procs: list, name: str) -> list:
    names = sorted({(p.info["name"] or "").rsplit(".", 1)[0] for p in procs} or {name})
    done = []
    for proc_name in names:
        if action == "minimize":
            body = 'set value of attribute "AXMinimized" of every window to true'
        elif action == "maximize":
            body = ('set value of attribute "AXMinimized" of every window to false\n'
                    'set frontmost to true\n'
                    'try\nclick (first button of window 1 whose subrole is "AXZoomButton")\nend try')
        else:
            body = ('set value of attribute "AXMinimized" of every window to false\n'
                    'set frontmost to true')
        script = f'tell application "System Events" to tell process "{proc_name}"\n{body}\nend tell'
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=6)
        if r.returncode == 0:
            done.append(proc_name)
    return done


def window_op(action: str, name: str, player=None) -> str:
    """minimize / maximize / restore / focus the window of a NAMED app."""
    action = {"unminimize": "restore", "show": "restore", "open": "focus", "bring": "focus"}.get(action, action)
    if action not in _SW:
        return f"Unknown window action: {action}"
    target = _target(name)
    if not target:
        return "Sir, tell me which app's window you mean."
    if target in ("jarvis", "main", "python", "pythonw"):
        return "That is my own window — use the minimize button on my window, sir."
    procs = _matches(target)
    pids = {p.pid for p in procs}
    try:
        if _OS == "Windows":
            titles = _windows_window_op(action, pids, name)
        elif _OS == "Darwin":
            titles = _mac_window_op(action, procs, name)
        else:
            titles = _linux_window_op(action, pids, name)
    except Exception as e:
        return f"I couldn't {action} {name}: {e}"
    if not titles:
        if not procs:
            return f"I don't see {name} running, sir."
        return (f"{name} is running but has no window I can control "
                f"(it may be hidden in the tray). Try 'open {name}' first.")
    verb = {"minimize": "Minimized", "maximize": "Maximized", "restore": "Restored", "focus": "Brought forward"}[action]
    log(f"[Apps] {verb} {name} ({len(titles)} window)", player)
    return f"{verb} {name}, sir."


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
        if action in ("minimize", "maximize", "restore", "focus", "unminimize", "show", "bring", "open"):
            return window_op(action, str(p.get("name") or p.get("app") or ""), player)
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
    return "Unknown action. Available: close, minimize, maximize, restore, focus, top, find, startup."


TOOL = {
    "name": "app_manager",
    "description": (
        "Controls a NAMED application (Discord, Chrome, Spotify, Steam, any program): close/quit it, MINIMIZE, "
        "MAXIMIZE, RESTORE or bring its window to the FRONT; also shows which apps use the most RAM or CPU, checks "
        "whether an app is running, and lists programs that start with the computer. "
        "ALWAYS use this when the user names an app with close, quit, exit, kill, minimize, maximize, restore or "
        "'bring up' — never use computer_settings minimize/maximize or Alt+F4 for a named app: those act on the "
        "focused window, which is Jarvis itself, and would hit the wrong window."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "close | minimize | maximize | restore | focus | top | find | startup"},
            "name": {"type": "STRING", "description": "App name for close/minimize/maximize/restore/focus/find, e.g. 'Discord', 'Chrome'"},
            "force": {"type": "BOOLEAN", "description": "End the app even if it asks to save (for 'force close')"},
            "sort": {"type": "STRING", "description": "memory | cpu (for top)"},
            "count": {"type": "INTEGER", "description": "How many apps to list (default 8)"},
        },
        "required": ["action"],
    },
    "handler": app_manager,
}

# by ASDcuber521
