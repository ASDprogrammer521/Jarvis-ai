from __future__ import annotations

import difflib
import re
import uuid
from datetime import date, timedelta

from actions._common import DATA_DIR, ask_json, json_load, json_save

STORE = DATA_DIR / "flashcards.json"
INTERVALS = [0, 1, 2, 4, 8, 16]
_CUR: dict = {}


def _norm(t: str) -> str:
    return re.sub(r"[^\w\s]", "", str(t).lower()).strip()


def _due(cards: list) -> list:
    today = date.today().isoformat()
    return sorted([c for c in cards if c["due"] <= today], key=lambda c: (c["box"], c["due"]))


def _judge(given: str, right: str) -> bool:
    g, r = _norm(given), _norm(right)
    if not g:
        return False
    if g == r or r in g and len(g) < len(r) * 2.2:
        return True
    keys = [w for w in r.split() if len(w) > 3] or r.split()
    hit = sum(1 for w in keys if w in g.split() or any(difflib.SequenceMatcher(None, w, x).ratio() >= (0.78 if len(w) >= 5 else 0.9) for x in g.split()))
    return difflib.SequenceMatcher(None, g, r).ratio() >= 0.82 or (keys and hit / len(keys) >= 0.75)


def _next(deck: str, cards: list, avoid: str = "") -> str:
    due = _due(cards)
    if len(due) > 1 and avoid:
        due = [c for c in due if c["id"] != avoid] + [c for c in due if c["id"] == avoid]
    if not due:
        return f"All caught up in '{deck}', sir — no cards are due today. 🎉"
    c = due[0]
    _CUR[deck] = c["id"]
    return f"Card ({len(due)} due): {c['q']}"


def study_cards(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "quiz").lower().strip()
    deck = str(p.get("deck") or "general").strip().lower()
    data = json_load(STORE, {"decks": {}})
    decks = data.setdefault("decks", {})
    cards = decks.setdefault(deck, []) if action not in ("decks", "list_decks") else []
    new = lambda q, a: {"id": uuid.uuid4().hex[:8], "q": q.strip(), "a": a.strip(), "box": 1, "due": date.today().isoformat(), "seen": 0, "ok": 0}

    if action in ("add", "add_card"):
        q, a = str(p.get("question") or "").strip(), str(p.get("answer") or "").strip()
        if not q or not a:
            return "Sir, I need both a question and an answer."
        cards.append(new(q, a))
        json_save(STORE, data)
        return f"Added to '{deck}'. The deck has {len(cards)} cards."
    if action in ("add_many", "import"):
        n = 0
        for line in str(p.get("text") or "").splitlines():
            m = re.split(r"\s*(?:::|=>|\t| - )\s*", line.strip(), maxsplit=1)
            if len(m) == 2 and m[0] and m[1]:
                cards.append(new(m[0], m[1]))
                n += 1
        json_save(STORE, data)
        return f"Added {n} cards to '{deck}'." if n else "Use one card per line like: question :: answer"
    if action in ("generate", "make"):
        topic = str(p.get("topic") or deck).strip()
        count = max(3, min(30, int(p.get("count") or 10)))
        res = ask_json(f"Create {count} flashcards about: {topic}. Language: {p.get('language') or 'same as the topic'}.",
                       'Reply with JSON only: [{"q": "short question", "a": "short, precise answer"}]. Questions must be self-contained.', default=None)
        items = [x for x in (res or []) if isinstance(x, dict) and x.get("q") and x.get("a")] if isinstance(res, list) else []
        if not items:
            return "I couldn't generate cards right now, sir. You can add them yourself with 'add card'."
        for x in items:
            cards.append(new(str(x["q"]), str(x["a"])))
        json_save(STORE, data)
        return f"Created {len(items)} cards about {topic} in '{deck}'. Say 'quiz me' to start."
    if action in ("quiz", "next", "start"):
        if not cards:
            return f"The deck '{deck}' is empty, sir. Say 'make flashcards about…' first."
        return _next(deck, cards)
    if action in ("answer", "check"):
        cid = _CUR.get(deck)
        c = next((x for x in cards if x["id"] == cid), None)
        if c is None:
            return "No card is active. Say 'quiz me' first."
        ok = _judge(str(p.get("text") or p.get("answer") or ""), c["a"]) if p.get("correct") is None else bool(p.get("correct"))
        c["seen"] += 1
        c["ok"] += int(ok)
        c["box"] = min(5, c["box"] + 1) if ok else 1
        c["due"] = (date.today() + timedelta(days=INTERVALS[c["box"]] if ok else 0)).isoformat()
        json_save(STORE, data)
        res = ("✓ Correct! " if ok else f"✗ Not quite. The answer is: {c['a']}. ") + (f"Next review in {INTERVALS[c['box']]} day(s). " if ok else "I'll ask again soon. ")
        return res + _next(deck, cards, c["id"])
    if action in ("stats", "progress"):
        if not cards:
            return f"No cards in '{deck}'."
        seen = sum(c["seen"] for c in cards)
        ok = sum(c["ok"] for c in cards)
        mastered = sum(1 for c in cards if c["box"] >= 4)
        return f"'{deck}': {len(cards)} cards, {len(_due(cards))} due today, {mastered} mastered, accuracy {round(ok / seen * 100) if seen else 0}%."
    if action in ("decks", "list_decks"):
        return "Decks: " + ", ".join(f"{d} ({len(c)})" for d, c in decks.items()) if decks else "You have no flashcard decks yet."
    if action in ("delete", "delete_deck"):
        if decks.pop(deck, None) is None:
            return "I couldn't find that deck, sir."
        json_save(STORE, data)
        return f"Deleted the deck '{deck}'."
    return "Unknown action. Available: generate, add, add_many, quiz, answer, stats, decks, delete."


TOOL = {
    "name": "study_cards",
    "description": (
        "Flashcards with spaced repetition (Leitner boxes). Generate a deck from a topic with AI, add cards by voice, "
        "or import 'question :: answer' lines; then quiz the user: it asks a due card, checks the spoken answer, and "
        "schedules the next review. Also stats and deck list. Use for studying, learning vocabulary, exam prep."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "generate | add | add_many | quiz | answer | stats | decks | delete"},
            "deck": {"type": "STRING", "description": "Deck name (default 'general')"},
            "topic": {"type": "STRING", "description": "Topic for generate"},
            "count": {"type": "INTEGER", "description": "Number of cards to generate (default 10)"},
            "question": {"type": "STRING", "description": "Card question (add)"},
            "answer": {"type": "STRING", "description": "Card answer (add) or the user's spoken answer (answer)"},
            "text": {"type": "STRING", "description": "Lines 'question :: answer' for add_many, or the user's answer"},
            "correct": {"type": "BOOLEAN", "description": "Grade manually instead of auto-checking"},
            "language": {"type": "STRING", "description": "Language for generated cards"},
        },
    },
    "handler": study_cards,
}

# by ASDcuber521
