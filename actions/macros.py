"""
Modes / macros — one phrase opens and arranges a whole set-up.

    "work mode"                       → opens VS Code, Chrome and Discord, VS Code left / Chrome right
    "save a mode called study with Chrome, Notion and Spotify, side by side"
    "list my modes" · "delete the study mode"

A macro is a list of steps stored in memory/macros.json:

    {"open": "Discord"}                  start an app (and wait until its window exists)
    {"tile": ["VS Code", "Chrome"]}      two apps side by side
    {"snap": ["Discord", "right"]}       one app on a side of the screen
    {"minimize": "Spotify"} · {"maximize": "Chrome"} · {"close": "Steam"} · {"focus": "Chrome"}
    {"url": "https://…"}                 open a web page
    {"show_desktop": true}               minimize everything
    {"wait": 2}                          pause (seconds)

Only TOOL is read at start-up; the heavy imports happen when a macro runs.
"""
from __future__ import annotations

import threading

_BUILTIN = {
    "work": [{"open": "VS Code"}, {"open": "Chrome"}, {"open": "Discord"}, {"tile": ["VS Code", "Chrome"]}],
    "game": [{"open": "Steam"}, {"open": "Discord"}],
    "relax": [{"open": "Spotify"}, {"url": "https://www.youtube.com"}],
    "clean": [{"show_desktop": True}],
}
_ALIASES = {"work mode": "work", "game mode": "game", "gaming": "game", "relax mode": "relax",
            "clean desktop": "clean", "clear": "clean"}


def _store():
    from actions._common import DATA_DIR
    return DATA_DIR / "macros.json"


def _load() -> dict:
    from actions._common import json_load
    data = json_load(_store(), {})
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    from actions._common import json_save
    json_save(_store(), data)


def _key(name: str) -> str:
    n = str(name or "").lower().strip()
    n = _ALIASES.get(n, n)
    for suffix in (" mode", " macro", " routine"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.strip()


def _wait_window(name: str, seconds: float = 12.0) -> bool:
    """Poll until the app has a window (Windows/Linux); other systems just give it a moment."""
    import time
    from actions.app_manager import _first_window
    end = time.time() + seconds
    while time.time() < end:
        try:
            _, h = _first_window(name)
            if h is not None:
                return True
        except Exception:
            return False
        time.sleep(0.5)
    return False


def _run_steps(name: str, steps: list, player) -> None:
    import time
    import webbrowser
    from actions import app_manager as am
    from actions._common import log
    from actions.open_app import open_app

    def say(t):
        log(f"[Mode:{name}] {t}", player)

    for st in steps:
        try:
            if "open" in st:
                say(f"opening {st['open']}")
                open_app({"app_name": st["open"]}, player=None)
                _wait_window(st["open"]) or time.sleep(2)
            elif "tile" in st and len(st["tile"]) == 2:
                for app in st["tile"]:
                    _wait_window(app, 6)
                say(am.tile_windows(st["tile"][0], st["tile"][1], None))
            elif "snap" in st and len(st["snap"]) == 2:
                say(am.snap_window(st["snap"][0], st["snap"][1], None))
            elif any(k in st for k in ("minimize", "maximize", "restore", "focus")):
                verb = next(k for k in ("minimize", "maximize", "restore", "focus") if k in st)
                say(am.window_op(verb, st[verb], None))
            elif "close" in st:
                say(am.close_app(st["close"], None, None))
            elif "url" in st:
                u = str(st["url"])
                if u.lower().startswith(("http://", "https://")):
                    webbrowser.open(u)
            elif st.get("show_desktop"):
                say(am.minimize_all(None))
            elif "wait" in st:
                time.sleep(max(0.0, min(30.0, float(st["wait"]))))
        except Exception as e:
            say(f"step {st} failed: {e}")
    say("done")


def macros(parameters: dict = None, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "run").lower().strip()
    name = _key(p.get("name") or "")
    mine = _load()

    if action in ("list", "show"):
        names = sorted(set(_BUILTIN) | set(mine))
        if not names:
            return "No modes yet."
        return "Modes: " + ", ".join(n + (" (yours)" if n in mine else "") for n in names) + "."

    if action in ("delete", "remove"):
        if name in mine:
            del mine[name]
            _save(mine)
            return f"Deleted the {name} mode."
        return f"There is no saved mode called {name}." if name not in _BUILTIN else \
            f"{name} is built in — save your own mode with the same name to override it."

    if action in ("save", "create", "add", "define"):
        if not name:
            return "Give the mode a name."
        steps: list = []
        apps = [a.strip() for a in str(p.get("apps") or "").replace(" and ", ",").split(",") if a.strip()]
        urls = [u.strip() for u in str(p.get("urls") or "").split(",") if u.strip()]
        for a in apps:
            steps.append({"open": a})
        for u in urls:
            steps.append({"url": u})
        layout = str(p.get("layout") or "").lower()
        if len(apps) >= 2 and layout in ("tile", "side_by_side", "split", "side by side"):
            steps.append({"tile": [apps[0], apps[1]]})
        if not steps:
            return "Tell me which apps or links belong in the mode."
        mine[name] = steps
        _save(mine)
        return f"Saved the {name} mode: " + ", ".join(apps + urls) + (" (side by side)" if any("tile" in s for s in steps) else "") + "."

    # run
    if not name:
        return "Which mode? " + macros({"action": "list"})
    steps = mine.get(name) or _BUILTIN.get(name)
    if not steps:
        return f"I don't have a {name} mode. " + macros({"action": "list"})
    threading.Thread(target=_run_steps, args=(name, steps, player), daemon=True).start()
    return f"Starting {name} mode — {len(steps)} steps."


TOOL = {
    "name": "macros",
    "description": (
        "Modes / routines: one phrase opens and arranges a whole set-up. Use for 'work mode', 'game mode', 'relax mode', "
        "'clean my desktop', 'start my study mode', 'save a mode called X with these apps', 'list my modes', "
        "'delete the X mode'. Built in: work (VS Code + Chrome side by side + Discord), game (Steam + Discord), "
        "relax (Spotify + YouTube), clean (minimize everything)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "run (default) | save | list | delete"},
            "name": {"type": "STRING", "description": "Mode name, e.g. 'work', 'study'"},
            "apps": {"type": "STRING", "description": "For save: comma-separated apps, e.g. 'Chrome, Notion, Spotify'"},
            "urls": {"type": "STRING", "description": "For save: comma-separated web addresses to open"},
            "layout": {"type": "STRING", "description": "For save: 'tile' puts the first two apps side by side"},
        },
        "required": [],
    },
    "handler": macros,
}

# by ASDcuber521
