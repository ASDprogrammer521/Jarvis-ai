from __future__ import annotations

from datetime import date, datetime, timedelta

from actions._common import DATA_DIR, json_load, json_save

STORE = DATA_DIR / "habits.json"
DEFAULTS = {"water": (8, "glasses"), "steps": (8000, "steps"), "reading": (30, "minutes"), "exercise": (30, "minutes"),
            "sleep": (8, "hours"), "meditation": (10, "minutes"), "study": (60, "minutes")}


def _key(name: str) -> str:
    n = (name or "").strip().lower()
    return {"drink": "water", "drinking water": "water", "walk": "steps", "workout": "exercise", "read": "reading"}.get(n, n)


def _day(d) -> str:
    s = str(d or "").strip().lower()
    if s in ("", "today"):
        return date.today().isoformat()
    if s == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    return datetime.strptime(s, "%Y-%m-%d").date().isoformat()


def _streak(h: dict) -> int:
    goal, log = h["goal"], h["log"]
    d, n = date.today(), 0
    if log.get(d.isoformat(), 0) < goal:
        d -= timedelta(days=1)
    while log.get(d.isoformat(), 0) >= goal:
        n += 1
        d -= timedelta(days=1)
    return n


def _line(name: str, h: dict) -> str:
    today = h["log"].get(date.today().isoformat(), 0)
    left = max(0, h["goal"] - today)
    s = _streak(h)
    return (f"{name.title()}: {today:g} of {h['goal']:g} {h['unit']} today" + (f", {left:g} to go" if left else " — goal reached ✓") +
            (f". Streak: {s} day{'s' if s != 1 else ''}." if s else "."))


def habit_tracker(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "status").lower().strip()
    data = json_load(STORE, {"habits": {}})
    habits = data.setdefault("habits", {})
    name = _key(str(p.get("name") or p.get("habit") or ""))
    try:
        if action in ("create", "add_habit", "new"):
            if not name:
                return "Sir, what is the habit called?"
            goal = float(p.get("goal") or DEFAULTS.get(name, (1, "times"))[0])
            unit = str(p.get("unit") or DEFAULTS.get(name, (1, "times"))[1])
            habits[name] = {"goal": goal, "unit": unit, "created": date.today().isoformat(), "log": habits.get(name, {}).get("log", {})}
            json_save(STORE, data)
            return f"Tracking {name}: goal {goal:g} {unit} per day."
        if action in ("log", "add", "did", "drink", "record"):
            if not name:
                return "Sir, which habit did you do?"
            if name not in habits:
                g, u = DEFAULTS.get(name, (1, "times"))
                habits[name] = {"goal": float(p.get("goal") or g), "unit": str(p.get("unit") or u), "created": date.today().isoformat(), "log": {}}
            amount = float(p.get("amount") or 1)
            d = _day(p.get("date"))
            habits[name]["log"][d] = max(0.0, habits[name]["log"].get(d, 0) + amount)
            json_save(STORE, data)
            return ("Logged. " if d == date.today().isoformat() else f"Logged for {d}. ") + _line(name, habits[name])
        if action in ("status", "today", "progress"):
            if not habits:
                return "You aren't tracking any habits yet. Try 'I drank a glass of water'."
            pick = {name: habits[name]} if name in habits else habits
            text = "\n".join(_line(n, h) for n, h in pick.items())
            if player is not None and hasattr(player, "show_content"):
                player.show_content("HABITS", text)
            return text
        if action in ("history", "week", "report"):
            if name not in habits:
                return "I'm not tracking that habit, sir."
            h = habits[name]
            days = max(1, min(30, int(p.get("days") or 7)))
            rows = []
            for i in range(days - 1, -1, -1):
                d = (date.today() - timedelta(days=i)).isoformat()
                v = h["log"].get(d, 0)
                rows.append(f"{d[5:]}  {'█' * int(min(10, v / h['goal'] * 10)):<10} {v:g}{' ✓' if v >= h['goal'] else ''}")
            hit = sum(1 for i in range(days) if h["log"].get((date.today() - timedelta(days=i)).isoformat(), 0) >= h["goal"])
            text = f"{name.title()} — last {days} days (goal {h['goal']:g} {h['unit']}):\n" + "\n".join(rows) + f"\nGoal met on {hit} of {days} days."
            if player is not None and hasattr(player, "show_content"):
                player.show_content("HABIT HISTORY", text)
            return f"Goal met on {hit} of the last {days} days. Streak: {_streak(h)}."
        if action in ("delete", "remove"):
            if habits.pop(name, None) is None:
                return "I'm not tracking that habit, sir."
            json_save(STORE, data)
            return f"Stopped tracking {name}."
    except ValueError as e:
        return f"That didn't look right, sir: {e}"
    return "Unknown action. Available: log, status, history, create, delete."


TOOL = {
    "name": "habit_tracker",
    "description": (
        "Tracks daily habits with goals and streaks: water glasses, steps, reading, exercise, sleep, meditation, study "
        "or any custom habit. Log progress ('I drank two glasses of water'), see today's progress, history and "
        "streaks. Use when the user reports doing a habit or asks how they are doing."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "log | status | history | create | delete"},
            "name": {"type": "STRING", "description": "Habit name, e.g. water, reading"},
            "amount": {"type": "NUMBER", "description": "How much to add (default 1)"},
            "goal": {"type": "NUMBER", "description": "Daily goal (for create or first log)"},
            "unit": {"type": "STRING", "description": "Unit, e.g. glasses, minutes"},
            "date": {"type": "STRING", "description": "today | yesterday | YYYY-MM-DD"},
            "days": {"type": "INTEGER", "description": "History length in days (default 7)"},
        },
    },
    "handler": habit_tracker,
}

# by ASDcuber521
