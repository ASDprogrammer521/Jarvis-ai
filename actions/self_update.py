from __future__ import annotations


def self_update(parameters: dict, player=None, speak=None) -> str:
    from core.updater import (apply_update, check_for_updates, get_local_version, get_repo, rollback_update, save_repo)
    p = parameters or {}
    action = str(p.get("action") or "check").strip().lower()

    if action == "set_repo":
        try:
            save_repo(str(p.get("repo") or ""))
        except ValueError:
            return "Give the repository as owner/name, for example ASDprogrammer521/Jarvis-ai."
        return f"Update source set to {get_repo()}. Say 'check for updates' next."

    if action in ("check", "status", "whats_new"):
        info = check_for_updates()
        if not info.get("ok"):
            return info.get("message") or "Update check failed."
        if info.get("update_available"):
            notes = f" What's new: {info['notes'][:200]}" if info.get("notes") else ""
            return f"{info['message']}.{notes} Say 'update Jarvis' to install it."
        return f"{info['message']} Source: {info.get('repo')}."

    if action in ("update", "upgrade", "install"):
        info = check_for_updates()
        if not info.get("ok"):
            return info.get("message") or "Update check failed."
        if not info.get("update_available"):
            return info.get("message") or "Already up to date."
        res = apply_update(info.get("zip_url"))
        if res.get("open_url"):
            import webbrowser
            webbrowser.open(res["open_url"])
        return (res.get("message") or str(res)) + (" Say 'restart Jarvis' to finish." if res.get("ok") and not res.get("manual") else "")

    if action in ("rollback", "undo", "revert"):
        return rollback_update().get("message", "Rollback failed.")

    if action == "restart":
        fn = getattr(player, "restart_app", None)
        if fn is None:
            return "I can't restart myself from here — please close and reopen Jarvis."
        fn()
        return "Restarting now, sir."

    return "Unknown action. Available: check, update, rollback, restart, set_repo."


TOOL = {
    "name": "self_update",
    "description": (
        "Updates Jarvis itself from its GitHub repository: check whether a newer version exists and what is new, "
        "download and install it (keeps your settings, memory and plugins), roll back to the previous version, or "
        "restart Jarvis. Use when the user asks to update Jarvis, check for updates, undo an update or restart."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "check | update | rollback | restart | set_repo"},
            "repo": {"type": "STRING", "description": "GitHub repo as owner/name (for set_repo)"},
        },
        "required": ["action"],
    },
    "handler": self_update,
}

# by ASDcuber521
