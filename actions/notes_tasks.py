from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from actions._common import CONFIG_PATH, DATA_DIR, json_load, json_save

NOTES = DATA_DIR / "notes.json"


def _tasks() -> list:
    try:
        return list(json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("tasks") or [])
    except Exception:
        return []


def _save_tasks(tasks: list) -> None:
    try:
        from memory.config_manager import _patch_config
        _patch_config(tasks=tasks)
    except Exception:
        data = json_load(CONFIG_PATH, {})
        data["tasks"] = tasks
        json_save(CONFIG_PATH, data)


def _find(items: list, query: str):
    q = str(query or "").strip().lower()
    if q.isdigit() and 1 <= int(q) <= len(items):
        return items[int(q) - 1]
    best = [i for i in items if q and q in i["text"].lower()]
    return best[0] if best else None


def _refresh(player) -> None:
    fn = getattr(player, "refresh_tasks", None)
    if fn:
        try:
            fn()
        except Exception:
            pass


def notes_tasks(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").lower().strip()
    kind = str(p.get("kind") or "task").lower()
    text = str(p.get("text") or "").strip()

    if kind == "note":
        data = json_load(NOTES, {"notes": []})
        notes = data.setdefault("notes", [])
        if action in ("add", "save", "create"):
            if not text:
                return "Sir, what should the note say?"
            notes.append({"id": uuid.uuid4().hex[:8], "text": text, "at": datetime.now().strftime("%Y-%m-%d %H:%M")})
            json_save(NOTES, data)
            return f"Noted, sir: “{text[:80]}”."
        if action in ("list", "show", "read"):
            if not notes:
                return "You have no saved notes, sir."
            lines = [f"{i}. {n['text']}  ({n['at']})" for i, n in enumerate(notes[-15:], 1)]
            if player is not None and hasattr(player, "show_content"):
                player.show_content("NOTES", "\n".join(lines))
            return f"You have {len(notes)} notes. Latest:\n" + "\n".join(lines)
        if action == "search":
            hits = [n for n in notes if text.lower() in n["text"].lower()]
            return "\n".join(f"• {n['text']} ({n['at']})" for n in hits[:10]) or f"No notes mention '{text}'."
        if action in ("remove", "delete", "done"):
            n = _find(notes, text)
            if not n:
                return "I couldn't find that note, sir."
            notes.remove(n)
            json_save(NOTES, data)
            return f"Deleted the note “{n['text'][:60]}”."
        if action == "clear":
            json_save(NOTES, {"notes": []})
            return "All notes deleted, sir."
        return "Unknown note action. Available: add, list, search, remove, clear."

    tasks = _tasks()
    if action in ("add", "create", "new"):
        items = [t.strip() for t in re.split(r"\s*(?:;|\n|\band also\b)\s*", text) if t.strip()] or ([text] if text else [])
        if not items:
            return "Sir, what is the task?"
        for t in items:
            if len(tasks) < 14:
                tasks.append({"id": uuid.uuid4().hex[:8], "text": t[:80], "done": False})
        _save_tasks(tasks)
        _refresh(player)
        return f"Added {len(items)} task(s), sir. You have {sum(1 for t in tasks if not t['done'])} open."
    if action in ("list", "show", "today"):
        if not tasks:
            return "Your task list is empty, sir."
        lines = [f"{i}. [{'x' if t['done'] else ' '}] {t['text']}" for i, t in enumerate(tasks, 1)]
        if player is not None and hasattr(player, "show_content"):
            player.show_content("TASKS", "\n".join(lines))
        left = [t["text"] for t in tasks if not t["done"]]
        return f"{len(left)} open task(s)" + (": " + "; ".join(left[:6]) if left else " — all done!")
    if action in ("done", "complete", "finish", "check"):
        t = _find(tasks, text)
        if not t:
            return "I couldn't find that task, sir."
        t["done"] = True
        _save_tasks(tasks)
        _refresh(player)
        return f"Marked “{t['text'][:60]}” as done."
    if action in ("remove", "delete"):
        t = _find(tasks, text)
        if not t:
            return "I couldn't find that task, sir."
        tasks.remove(t)
        _save_tasks(tasks)
        _refresh(player)
        return f"Removed “{t['text'][:60]}”."
    if action in ("clear_done", "clear"):
        keep = [t for t in tasks if not t["done"]] if action == "clear_done" else []
        _save_tasks(keep)
        _refresh(player)
        return f"Cleared {len(tasks) - len(keep)} task(s), sir."
    return "Unknown action. Available: add, list, done, remove, clear_done."


TOOL = {
    "name": "notes_tasks",
    "description": (
        "Manages the user's to-do list (shown on the Dashboard) and quick notes. Tasks: add, list, mark done, remove, "
        "clear completed. Notes: save a note, list, search, delete. Use for 'add a task', 'what do I have to do today', "
        "'I finished the report', 'remember that…', 'take a note'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "add | list | done | remove | clear_done | search | clear"},
            "kind": {"type": "STRING", "description": "task (default) | note"},
            "text": {"type": "STRING", "description": "Task/note text, or a number/part of the text to find an existing one"},
        },
    },
    "handler": notes_tasks,
}

# by ASDcuber521
