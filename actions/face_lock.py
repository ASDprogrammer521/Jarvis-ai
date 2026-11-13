from __future__ import annotations


def face_lock(parameters: dict, player=None) -> str:
    from core import face_lock as fl
    action = str((parameters or {}).get("action") or "lock").lower().strip()
    if action == "status":
        return (f"Face lock is {'on' if fl.is_enabled() else 'off'}, auto-lock after "
                f"{fl.TIMEOUT_CHOICES[fl.timeout_minutes()]}.")
    if not fl.pin_set():
        return "I need a PIN before I can lock — set one in Settings → Face ID, then ask again."
    if player is None or not hasattr(player, "module_command"):
        return "The interface isn't ready."
    player.module_command("face_lock", "lock")
    return "Locking now. Only a saved face or the PIN opens me."


TOOL = {
    "name": "face_lock",
    "description": (
        "Locks Jarvis behind the face lock. Use for 'lock Jarvis', 'lock yourself', 'I'm leaving, lock up'. It can only lock — "
        "unlocking happens by showing a saved face or entering the PIN, never by a voice command. Also 'status'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {"action": {"type": "STRING", "description": "lock | status"}},
        "required": [],
    },
    "handler": face_lock,
}
