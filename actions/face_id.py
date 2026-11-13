"""Voice control for Face ID: 'remember my face as Akmal', 'who is in front of the camera?', 'forget Akmal'."""
from __future__ import annotations


def face_id(parameters: dict, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "who").lower().strip()
    name = str(p.get("name") or "").strip()
    if player is None or not hasattr(player, "face_command"):
        return "Face ID isn't available right now."
    if action in ("enroll", "remember", "add") and not name:
        return "Whose face should I remember, sir?"
    if action in ("forget", "remove", "delete") and not name:
        return "Whose face should I forget?"
    action = {"remember": "enroll", "add": "enroll", "remove": "forget", "delete": "forget", "people": "list"}.get(action, action)
    return player.face_command(action, name)


TOOL = {
    "name": "face_id",
    "description": (
        "Face recognition through the webcam (must be enabled in Settings → Face ID). 'Remember my face as Akmal' → "
        "enroll; 'who is in front of the camera?' / 'kim turibdi?' → who; 'whose faces do you know?' → list; "
        "'forget Akmal' → forget."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "enroll | who | list | forget"},
            "name": {"type": "STRING", "description": "Person's name (for enroll / forget)"},
        },
        "required": ["action"],
    },
    "handler": face_id,
}
