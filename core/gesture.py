"""Hand-gesture control (camera + MediaPipe). Off by default; enabled and mapped in Settings → Gestures.

The controller only recognises *which* gesture is held; what it does comes from the user's mapping in
config/api_keys.json (`gesture_map`). Actions are executed by the UI through the `on_action` callback.
"""
from __future__ import annotations

import math
import time

from core.common_utils import project_root

MODEL_PATH = project_root() / "config" / "models" / "hand_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")

# gesture id → (label, default action)
GESTURES: dict[str, tuple[str, str]] = {
    "open_palm": ("✋ Open palm", "play_pause"),
    "fist": ("✊ Fist", "toggle_mic"),
    "thumbs_up": ("👍 Thumbs up", "volume_up"),
    "thumbs_down": ("👎 Thumbs down", "volume_down"),
    "peace": ("✌ Peace / two fingers", "screenshot"),
    "point": ("☝ Index finger", "next_track"),
    "three": ("🤟 Three fingers", "prev_track"),
}

# action id → label. "none" = ignore the gesture.
ACTIONS: dict[str, str] = {
    "none": "— Nothing —",
    "play_pause": "Play / pause media",
    "next_track": "Next track",
    "prev_track": "Previous track",
    "volume_up": "Volume up",
    "volume_down": "Volume down",
    "volume_mute": "Mute speakers",
    "toggle_mic": "Mute / unmute microphone",
    "wake_toggle": "Sleep / wake assistant",
    "screenshot": "Take a screenshot",
    "open_settings": "Open Settings",
    "fullscreen": "Toggle fullscreen",
}

# response speed → seconds a gesture must be held before it fires
SPEEDS = {"fast": 0.3, "normal": 0.45, "careful": 0.7}
SPEED_LABELS = {"fast": "⚡ Fast", "normal": "Normal", "careful": "🎯 Careful"}
COOLDOWN_SECONDS = 1.0  # minimum gap between two fired actions
REPEAT_ACTIONS = {"volume_up", "volume_down"}  # keep firing while held


# ── config ─────────────────────────────────────────────────────────────────────
def _cfg() -> dict:
    from memory.config_manager import load_api_keys
    return load_api_keys()


def is_enabled() -> bool:
    return bool(_cfg().get("gesture_enabled", False))


def set_enabled(on: bool) -> None:
    from memory.config_manager import _patch_config
    _patch_config(gesture_enabled=bool(on))


def get_map() -> dict[str, str]:
    saved = _cfg().get("gesture_map") or {}
    return {g: (saved.get(g) if saved.get(g) in ACTIONS else d[1]) for g, d in GESTURES.items()}


def set_mapping(gesture: str, action: str) -> None:
    if gesture not in GESTURES or action not in ACTIONS:
        return
    from memory.config_manager import _patch_config
    m = get_map()
    m[gesture] = action
    _patch_config(gesture_map=m)


def get_speed() -> str:
    v = _cfg().get("gesture_speed", "normal")
    return v if v in SPEEDS else "normal"


def set_speed(v: str) -> None:
    if v in SPEEDS:
        from memory.config_manager import _patch_config
        _patch_config(gesture_speed=v)


def hold_seconds() -> float:
    return SPEEDS[get_speed()]


def get_camera() -> int:
    try:
        return int(_cfg().get("gesture_camera", 0))
    except (TypeError, ValueError):
        return 0


def set_camera(i: int) -> None:
    from memory.config_manager import _patch_config
    _patch_config(gesture_camera=int(i))


# ── classification ─────────────────────────────────────────────────────────────
# Rotation-independent: fingers are judged by distance from the wrist, not by "higher on screen".
# landmarks: 0 wrist, 2/3/4 thumb, 5/9/13/17 finger bases, 6/10/14/18 middle joints, 8/12/16/20 tips
def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def classify(lm) -> str | None:
    """lm: 21 (x, y) points (image coords, y grows down). Returns a gesture id or None."""
    scale = max(1e-6, _d(lm[0], lm[9]))          # palm size → works at any distance from the camera

    def ext(tip, pip):                            # finger is straight if its tip is clearly farther from the wrist than its joint
        return _d(lm[0], lm[tip]) > 1.12 * _d(lm[0], lm[pip])

    idx, mid, ring, pin = ext(8, 6), ext(12, 10), ext(16, 14), ext(20, 18)
    n = idx + mid + ring + pin
    thumb_out = _d(lm[4], lm[5]) > 0.6 * scale and _d(lm[4], lm[17]) > _d(lm[3], lm[17])

    if n == 4:
        return "open_palm"
    if n == 0:
        if thumb_out:
            dx, dy = lm[4][0] - lm[2][0], lm[4][1] - lm[2][1]
            if abs(dy) > 1.2 * abs(dx):           # thumb points mostly up or down
                return "thumbs_up" if dy < 0 else "thumbs_down"
            return None                           # thumb sideways: ambiguous, ignore
        return "fist"
    if idx and mid and not ring and not pin:
        return "peace"
    if idx and not mid and not ring and not pin and not thumb_out:
        return "point"
    if idx and mid and ring and not pin:
        return "three"
    return None


class HandReader:
    """MediaPipe wrapper that works with both the legacy `solutions` API and the newer Tasks API."""

    def __init__(self):
        import mediapipe as mp
        self.mp = mp
        self.mode = None
        self._t0 = time.time()
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
            self._h = mp.solutions.hands.Hands(max_num_hands=1, model_complexity=0,
                                               min_detection_confidence=0.6, min_tracking_confidence=0.5)
            self.mode = "legacy"
            return
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision
        self._ensure_model()
        opts = vision.HandLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO, num_hands=1,
            min_hand_detection_confidence=0.6, min_tracking_confidence=0.5)
        self._h = vision.HandLandmarker.create_from_options(opts)
        self.mode = "tasks"

    @staticmethod
    def _ensure_model():
        if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 1_000_000:
            return
        import requests
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(MODEL_URL, stream=True, timeout=30)
        r.raise_for_status()
        tmp = MODEL_PATH.with_suffix(".part")
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 16):
                fh.write(chunk)
        tmp.replace(MODEL_PATH)

    def detect(self, rgb):
        if self.mode == "legacy":
            res = self._h.process(rgb)
            if res.multi_hand_landmarks:
                return [(p.x, p.y) for p in res.multi_hand_landmarks[0].landmark]
            return None
        img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        res = self._h.detect_for_video(img, int((time.time() - self._t0) * 1000))
        if res.hand_landmarks:
            return [(p.x, p.y) for p in res.hand_landmarks[0]]
        return None

    def close(self):
        try:
            self._h.close()
        except Exception:
            pass


class GestureTracker:
    """Turns a stream of per-frame classifications into 'fire this action now' decisions."""

    def __init__(self):
        self.votes: list = []
        self.held = None
        self.held_since = 0.0
        self.last_fire = 0.0
        self.current: str | None = None

    def update(self, g: str | None, now: float | None = None):
        """Feed one frame's result. Returns (gesture_id, action_id) when something should fire, else None."""
        now = time.time() if now is None else now
        self.votes = (self.votes + [g])[-4:]
        stable = max(set(self.votes), key=self.votes.count)
        self.current = stable if self.votes.count(stable) >= 3 else None   # 3 of the last 4 frames agree
        cur = self.current
        if cur != self.held:
            self.held, self.held_since = cur, now
            return None
        if cur and now - self.held_since >= hold_seconds() and now - self.last_fire >= COOLDOWN_SECONDS:
            action = get_map().get(cur, "none")
            if action == "none":
                return None
            self.last_fire = now
            if action not in REPEAT_ACTIONS:
                self.held_since = now + 10_000     # release the gesture before it can fire again
            return cur, action
        return None
