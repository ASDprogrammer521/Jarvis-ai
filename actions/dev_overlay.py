from __future__ import annotations

from actions._common import log


def dev_overlay(parameters: dict, player=None) -> str:
    from core import dev_tools
    p = parameters or {}
    action = str(p.get("action") or "show").lower().strip().replace(" ", "_")

    def overlay(cmd: str):
        if player is not None and hasattr(player, "module_command"):
            player.module_command("dev_overlay", cmd)

    try:
        if action in ("show", "open", "on"):
            overlay("show")
            return "Developer overlay is up."
        if action in ("hide", "close", "off"):
            overlay("hide")
            return "Developer overlay closed."
        if action == "set_repo":
            return dev_tools.set_repo(str(p.get("path") or ""))
        if action == "git":
            out = dev_tools.run_git(str(p.get("command") or "status"), str(p.get("message") or ""))
            log("[Dev] git " + str(p.get("command") or "status"), player)
            return out[:1500]
        if action in ("stats", "system"):
            s = dev_tools.system_stats()
            gpu = f", GPU {s['gpu']:.0f}%" if s["gpu"] is not None else ""
            return f"CPU {s['cpu']:.0f}%, RAM {s['ram']:.0f}% ({s['ram_used_gb']:.1f} of {s['ram_total_gb']:.0f} GB){gpu}."
        if action in ("explain_error", "explain", "review_code"):
            text = dev_tools.clipboard_text()
            if not text.strip():
                return "The clipboard is empty — copy the error or code first."
            task = ("Explain this error in plain words: the cause and the most likely fix, briefly."
                    if action != "review_code" else "Review this code: what it does and the top issues, briefly.")
            return f"{task}\n\n--- clipboard ---\n{text}"
        return "Unknown dev_overlay action. Use show, hide, git, set_repo, stats, explain_error or review_code."
    except Exception as e:
        return f"Sir, the developer overlay failed: {e}"


TOOL = {
    "name": "dev_overlay",
    "description": (
        "Developer productivity overlay (also opens with Alt+Space). Use for 'open the dev overlay', 'git status', "
        "'pull the repo', 'commit everything with message X', 'how much CPU/RAM/GPU am I using', 'explain this error' / "
        "'what does this error mean' (reads the clipboard), 'review the code I copied', 'use C:/projects/app as my repo'. "
        "Not for general system cleanup (use storage_analyzer) or running arbitrary terminal commands (use dev_agent)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "show | hide | git | set_repo | stats | explain_error | review_code"},
            "command": {"type": "STRING", "description": "git: status | diff | log | branch | fetch | pull | push | stash | stash pop | commit"},
            "message": {"type": "STRING", "description": "Commit message for git commit"},
            "path": {"type": "STRING", "description": "Repository folder for set_repo"},
        },
        "required": ["action"],
    },
    "handler": dev_overlay,
}
