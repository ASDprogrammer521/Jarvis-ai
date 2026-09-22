"""
Check GitHub for Jarvis updates and optionally install them.
"""
from __future__ import annotations

TOOL = {
    "name": "self_update",
    "description": (
        "Check the GitHub repository for a newer Jarvis version and optionally "
        "download and install the update. Use when the user asks to update Jarvis, "
        "check for updates, or upgrade the app."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "check | update | set_repo",
                "enum": ["check", "update", "set_repo"],
            },
            "repo": {
                "type": "string",
                "description": "GitHub repo as owner/name (for set_repo), e.g. ASDcuber/Jarvis-ai",
            },
        },
        "required": ["action"],
    },
}


def run(action: str = "check", repo: str = "", **kwargs) -> str:
    from core.updater import check_for_updates, apply_update, save_repo, get_repo, get_local_version

    action = (action or "check").strip().lower()

    if action == "set_repo":
        if not repo or "/" not in repo:
            return "Provide repo as owner/name, for example: ASDcuber/Jarvis-ai"
        save_repo(repo)
        return f"GitHub repo set to {get_repo()}. Say 'check for updates' next."

    if action == "check":
        info = check_for_updates()
        if not info.get("ok"):
            return info.get("message") or "Update check failed."
        extra = f" Repo: {info.get('repo')}."
        if info.get("update_available"):
            return (
                info["message"] + extra +
                " Say 'update Jarvis' or 'install update' to download and apply."
            )
        return info["message"] + extra + f" Local version: {get_local_version()}."

    if action in ("update", "upgrade", "install"):
        info = check_for_updates()
        if not info.get("ok"):
            return info.get("message") or "Update check failed."
        if not info.get("update_available"):
            return info.get("message") or "Already up to date."
        result = apply_update(info.get("zip_url"))
        return result.get("message") or str(result)

    return "Unknown action. Use check, update, or set_repo."
