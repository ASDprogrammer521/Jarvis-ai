from __future__ import annotations


def hand_control(parameters: dict, player=None) -> str:
    from core import hand_cursor
    p = parameters or {}
    action = str(p.get("action") or "toggle").lower().strip()
    on = hand_cursor.is_enabled()
    if action in ("space", "hand_space", "cards", "open_space"):
        if player is None or not hasattr(player, "module_command"):
            return "The interface isn't ready."
        player.module_command("hand_space", "show")
        return "Hand Space is open — your drives are floating: pinch-tap a folder to go in, a picture to enlarge it, hold a fist to go back."
    if action in ("close_space", "space_off"):
        if player is not None and hasattr(player, "module_command"):
            player.module_command("hand_space", "hide")
        return "Hand Space closed."
    if action in ("status",):
        return f"Hand control is {'on' if on else 'off'}, reach {hand_cursor.get_sensitivity()}."
    if action in ("sensitivity", "reach"):
        lvl = str(p.get("level") or "").lower()
        if lvl not in hand_cursor.SENSITIVITY:
            return "Choose low, normal or high."
        hand_cursor.set_sensitivity(lvl)
        action = "restart" if on else "status"
        if action == "status":
            return f"Hand control reach set to {lvl}."
    want = {"on": True, "enable": True, "start": True, "off": False, "disable": False, "stop": False,
            "restart": True}.get(action, not on)
    if player is None or not hasattr(player, "set_hand_cursor"):
        return "The interface isn't ready for hand control."
    if action == "restart":
        player.set_hand_cursor(False)
        import threading
        threading.Timer(1.2, lambda: player.set_hand_cursor(True)).start()
        return "Hand control restarted."
    player.set_hand_cursor(want)
    return ("Hand control is on, sir — move your index finger to steer, pinch to click, show a peace sign to scroll, "
            "and hold a fist to stop." if want else "Hand control is off.")


TOOL = {
    "name": "hand_control",
    "description": (
        "Turns the webcam hand-tracking mouse on or off: the hand moves the real cursor, pinch clicks, a peace sign "
        "scrolls, a held fist stops it. Use for 'enable hand control', 'let me control the screen with my hand', "
        "'turn off hand tracking', 'make hand control more sensitive'. Also opens “Hand Space”, the Iron-Man style floating file browser (drives, folders, pictures) you move with your hands (‘open hand space’). Not for the one-shot gesture shortcuts in Settings."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "on | off | toggle | status | sensitivity | space (open Hand Space: floating file browser) | close_space"},
            "level": {"type": "STRING", "description": "low | normal | high (for sensitivity)"},
        },
        "required": ["action"],
    },
    "handler": hand_control,
}
