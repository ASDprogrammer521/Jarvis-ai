from __future__ import annotations

import urllib.parse


def _get(url: str, timeout: int = 8):
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Jarvis-Assistant/1.0", "Accept": "application/json"})
    return r


def wiki(topic: str, lang: str) -> str:
    lang = (lang or "en").lower()[:3]
    title = urllib.parse.quote(topic.strip().replace(" ", "_"))
    r = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}?redirect=true")
    if r.status_code == 404:
        s = _get(f"https://{lang}.wikipedia.org/w/rest.php/v1/search/title?q={urllib.parse.quote(topic)}&limit=1").json()
        pages = s.get("pages") or []
        if not pages:
            return f"I couldn't find anything about '{topic}' on Wikipedia, sir."
        r = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(pages[0]['key'])}")
    if r.status_code != 200:
        return f"Wikipedia isn't answering right now (HTTP {r.status_code})."
    j = r.json()
    if j.get("type") == "disambiguation":
        return f"'{topic}' can mean several things — be a little more specific, sir."
    text = (j.get("extract") or "").strip()
    if not text:
        return f"I found a page for '{topic}' but it has no summary."
    sents = text.replace("\n", " ").split(". ")
    short = ". ".join(sents[:3]).strip()
    return f"{j.get('title', topic)}: {short}{'' if short.endswith('.') else '.'}"


def define(word: str, lang: str) -> str:
    lang = (lang or "en").lower()[:2]
    r = _get(f"https://api.dictionaryapi.dev/api/v2/entries/{lang}/{urllib.parse.quote(word.strip().lower())}")
    if r.status_code != 200:
        return f"I couldn't find a definition for '{word}', sir."
    entry = r.json()[0]
    lines = []
    for m in entry.get("meanings", [])[:3]:
        d = (m.get("definitions") or [{}])[0]
        syn = ", ".join((m.get("synonyms") or d.get("synonyms") or [])[:4])
        lines.append(f"({m.get('partOfSpeech', '')}) {d.get('definition', '')}" + (f" — synonyms: {syn}" if syn else ""))
    ph = entry.get("phonetic") or ""
    return f"{entry.get('word', word)} {ph}\n" + "\n".join(lines)


def knowledge_lookup(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "wiki").lower().strip()
    q = str(p.get("query") or p.get("topic") or p.get("word") or "").strip()
    if not q:
        return "Sir, what should I look up?"
    try:
        if action in ("wiki", "wikipedia", "about", "who", "what", "summary"):
            text = wiki(q, str(p.get("language") or "en"))
        elif action in ("define", "definition", "meaning", "synonyms"):
            text = define(q, str(p.get("language") or "en"))
        else:
            return "Unknown action. Available: wiki, define."
    except ImportError:
        return "Sir, I need the 'requests' package: pip install requests"
    except Exception as e:
        return f"I couldn't reach the lookup service ({type(e).__name__}) — check your internet, sir."
    if player is not None and hasattr(player, "show_content"):
        player.show_content(q.upper()[:30], text)
    return text


TOOL = {
    "name": "knowledge_lookup",
    "description": (
        "Quick factual lookup without web browsing: a short Wikipedia summary of a person, place, concept or event "
        "(any Wikipedia language), or the dictionary definition, phonetics and synonyms of an English word. "
        "Use for 'who is…', 'what is…', 'tell me about…', 'define…', 'what does … mean'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "wiki | define"},
            "query": {"type": "STRING", "description": "Topic, person or word"},
            "language": {"type": "STRING", "description": "Wikipedia language code: en, uz, ru, tr… (default en)"},
        },
        "required": ["query"],
    },
    "handler": knowledge_lookup,
}

# by ASDcuber521
