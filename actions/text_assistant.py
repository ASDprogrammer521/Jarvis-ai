from __future__ import annotations

from actions._common import ask_text, clip_read, clip_write

MODES = {
    "translate": "Translate the text into {lang}. Output only the translation.",
    "summarize": "Summarize the text in {length}. Keep the key facts. Output only the summary.",
    "rewrite": "Rewrite the text in a {tone} tone, keeping the meaning. Output only the rewritten text.",
    "fix": "Fix spelling, grammar and punctuation without changing the meaning or the language. Output only the corrected text.",
    "explain": "Explain the text simply, as to a smart beginner. Be concise.",
    "expand": "Expand the text into a fuller, well-written version of about twice the length. Output only the new text.",
    "bullets": "Turn the text into a clear bullet list of key points. Output only the list.",
    "reply": "Write a polite, clear reply to this message in a {tone} tone. Output only the reply.",
}


def text_assistant(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "summarize").lower().strip()
    action = {"summary": "summarize", "grammar": "fix", "proofread": "fix", "simplify": "explain", "list": "bullets"}.get(action, action)
    if action not in MODES:
        return "Unknown action. Available: " + ", ".join(MODES) + "."
    text = str(p.get("text") or "").strip()
    if not text or str(p.get("source") or "").lower() == "clipboard":
        try:
            text = clip_read()
        except Exception:
            text = text or ""
    if not text.strip():
        return "Sir, I have no text to work on — say it or copy it first."
    instr = MODES[action].format(lang=p.get("language") or "English", tone=p.get("tone") or "professional",
                                 length=p.get("length") or "3 short sentences")
    out = ask_text(text[:12000], instr + " Reply in the same language as the text unless told otherwise.", default="", timeout_ms=45_000)
    if not out.strip():
        return "I couldn't reach the AI service right now, sir. Please try again."
    if p.get("copy", True):
        try:
            clip_write(out)
            tail = " (copied to your clipboard)"
        except Exception:
            tail = ""
    else:
        tail = ""
    if player is not None and hasattr(player, "show_content"):
        player.show_content(action.upper(), out)
    return out[:1500] + ("…" if len(out) > 1500 else "") + tail


TOOL = {
    "name": "text_assistant",
    "description": (
        "Works on text: translate, summarize, rewrite in a tone, fix grammar and spelling, explain simply, expand, "
        "turn into bullet points, or draft a reply. Takes the text from the request or from the clipboard "
        "(source=clipboard) and copies the result back to the clipboard."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "translate | summarize | rewrite | fix | explain | expand | bullets | reply"},
            "text": {"type": "STRING", "description": "The text to process (omit to use the clipboard)"},
            "source": {"type": "STRING", "description": "'clipboard' to read the text from the clipboard"},
            "language": {"type": "STRING", "description": "Target language for translate"},
            "tone": {"type": "STRING", "description": "Tone for rewrite/reply, e.g. friendly, formal"},
            "length": {"type": "STRING", "description": "Summary length, e.g. '2 sentences'"},
            "copy": {"type": "BOOLEAN", "description": "Copy the result to the clipboard (default true)"},
        },
    },
    "handler": text_assistant,
}

# by ASDcuber521
