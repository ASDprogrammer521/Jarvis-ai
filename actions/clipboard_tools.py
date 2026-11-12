from __future__ import annotations

from actions._common import clip_read, clip_write


def clipboard_tools(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "read").lower().strip()
    try:
        if action in ("read", "get", "show"):
            t = clip_read()
            if not t.strip():
                return "The clipboard is empty, sir."
            if player is not None and hasattr(player, "show_content"):
                player.show_content("CLIPBOARD", t[:6000])
            return f"Clipboard ({len(t)} characters):\n{t[:1500]}" + ("\n…" if len(t) > 1500 else "")
        if action in ("write", "set", "copy"):
            text = str(p.get("text") or "")
            if not text:
                return "Sir, what should I copy?"
            clip_write(text)
            return f"Copied {len(text)} characters to the clipboard."
        if action == "clear":
            clip_write("")
            return "Clipboard cleared, sir."
    except FileNotFoundError:
        return "Sir, I need a clipboard tool on this system (Linux: sudo apt install xclip)."
    except Exception as e:
        return f"Clipboard failed: {e}"
    return "Unknown action. Available: read, write, clear."


TOOL = {
    "name": "clipboard_tools",
    "description": "Reads, writes or clears the system clipboard. Use for 'what did I copy', 'copy this to the clipboard', 'clear my clipboard'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "read | write | clear"},
            "text": {"type": "STRING", "description": "Text to copy (for write)"},
        },
    },
    "handler": clipboard_tools,
}

# by ASDcuber521
