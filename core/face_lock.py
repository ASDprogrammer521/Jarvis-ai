"""Face lock — Jarvis stays locked until a saved face is seen (or the PIN is typed).

Pure logic + settings, no Qt. The lock screen lives in ui/lock_screen.py, the camera feed comes from core/camera_hub.py.

  · locks when Jarvis starts, on demand ("lock Jarvis"), and automatically after N minutes without a saved face
  · unlocks after a saved face is seen on several consecutive checks (~1 s), so one stray frame can't open it
  · a PIN is required to switch the lock on, so a broken or covered camera can never lock you out for good
  · a face match is not liveness-checked: a photo of you held to the camera could fool it — treat it as a convenience
    lock against casual access, not as strong security
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

UNLOCK_STREAK = 3                 # consecutive camera checks (≈0.4 s apart) that must show a saved face
PIN_MIN = 4
MAX_FAILS = 5                     # wrong PINs before a cool-down
COOLDOWN = 30.0
TIMEOUT_CHOICES = {0: "Never", 1: "1 min", 3: "3 min", 10: "10 min", 30: "30 min"}


def _cfg() -> dict:
    from memory.config_manager import load_api_keys
    return load_api_keys()


def _set(**kw) -> None:
    from memory.config_manager import _patch_config
    _patch_config(**kw)


def is_enabled() -> bool:
    return bool(_cfg().get("face_lock_enabled", False)) and pin_set()


def set_enabled(on: bool) -> None:
    _set(face_lock_enabled=bool(on))


def timeout_minutes() -> int:
    try:
        v = int(_cfg().get("face_lock_minutes", 3))
    except (TypeError, ValueError):
        v = 3
    return v if v in TIMEOUT_CHOICES else 3


def set_timeout_minutes(v: int) -> None:
    if int(v) in TIMEOUT_CHOICES:
        _set(face_lock_minutes=int(v))


def pin_set() -> bool:
    return bool(_cfg().get("face_lock_pin"))


def _hash(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def set_pin(pin: str) -> str:
    pin = (pin or "").strip()
    if len(pin) < PIN_MIN:
        return f"The PIN needs at least {PIN_MIN} characters."
    salt = os.urandom(16)
    _set(face_lock_pin=salt.hex() + "$" + _hash(pin, salt).hex())
    return ""


def verify_pin(pin: str) -> bool:
    stored = _cfg().get("face_lock_pin") or ""
    try:
        salt_hex, h_hex = stored.split("$", 1)
        return hmac.compare_digest(_hash((pin or "").strip(), bytes.fromhex(salt_hex)), bytes.fromhex(h_hex))
    except ValueError:
        return False


class LockLogic:
    def __init__(self):
        self.locked = False
        self.last_known = time.time()
        self.streak = 0
        self.fails = 0
        self.blocked_until = 0.0

    def on_seen(self, known: list[str], now: float | None = None) -> str | None:
        """Feed the result of one camera check. Returns 'unlock' when the face has been confirmed."""
        now = time.time() if now is None else now
        if known:
            self.last_known = now
        if not self.locked:
            return None
        self.streak = self.streak + 1 if known else 0
        return "unlock" if self.streak >= UNLOCK_STREAK else None

    def should_autolock(self, minutes: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return bool(minutes) and not self.locked and now - self.last_known > minutes * 60

    def lock(self) -> None:
        self.locked, self.streak = True, 0

    def unlock(self, now: float | None = None) -> None:
        self.locked, self.streak, self.fails = False, 0, 0
        self.last_known = time.time() if now is None else now

    def try_pin(self, pin: str, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        if now < self.blocked_until:
            return False, f"Too many attempts — wait {int(self.blocked_until - now) + 1} s."
        if verify_pin(pin):
            return True, ""
        self.fails += 1
        if self.fails >= MAX_FAILS:
            self.fails, self.blocked_until = 0, now + COOLDOWN
            return False, f"Wrong PIN. Locked out for {int(COOLDOWN)} s."
        return False, f"Wrong PIN ({MAX_FAILS - self.fails} tries left)."
