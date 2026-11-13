"""Hand-controlled cursor — drive the whole UI with your bare hand (camera + MediaPipe).

Unlike core/gesture.py (which fires one action per held pose), this turns the hand into a mouse:

    index fingertip ........ moves the real system cursor (so Jarvis' own UI, games and every other app follow it)
    thumb + index pinch .... left button — quick pinch = click, keep pinching = drag
    thumb + middle pinch ... right click
    peace sign (✌) ......... scroll: move the hand up / down
    fist held 1.5 s ........ panic stop (a fist never clicks) — switches hand control off

Everything runs locally; the camera frames never leave the computer. Off by default (Settings → Gestures).
"""
from __future__ import annotations

import math
import sys
import time
from collections import deque

from core import gesture

SENSITIVITY = {"low": 0.78, "normal": 0.62, "high": 0.48}   # half-width of the camera area that maps to the screen
SENS_LABELS = {"low": "Low", "normal": "Normal", "high": "High"}

PINCH_ON = 0.32          # thumb-index distance / hand size below which the button goes down
PINCH_OFF = 0.50         # ...and above which it comes back up (hysteresis stops flicker)
APPROACH = 0.62          # fingers closing in: the cursor is frozen where you were pointing, so the click lands there
CONFIRM_FRAMES = 2       # pinch / release must hold for this many frames (kills single-frame glitches)
DRAG_PX = 48             # after pressing, the hand must travel this far before the cursor starts to drag
SETTLE = 0.18            # seconds the cursor rests after a release before it follows the hand again
LOOKBACK = 0.20          # how far back the frozen cursor position is taken from
RIGHT_ON = 0.30
SCROLL_GAIN = 2600       # wheel units per full camera height of vertical hand travel
PANIC_SECONDS = 1.5
LOST_RELEASE = 0.45      # no hand for this long → release any held button


# ── config ─────────────────────────────────────────────────────────────────────
def _cfg() -> dict:
    from memory.config_manager import load_api_keys
    return load_api_keys()


def is_enabled() -> bool:
    return bool(_cfg().get("hand_cursor_enabled", False))


def set_enabled(on: bool) -> None:
    from memory.config_manager import _patch_config
    _patch_config(hand_cursor_enabled=bool(on))


def show_skeleton() -> bool:
    """Hand outline (bones) on the overlay. Off by default: only the fingertip ring and pinch ring are drawn."""
    return bool(_cfg().get("hand_show_skeleton", False))


def set_show_skeleton(on: bool) -> None:
    from memory.config_manager import _patch_config
    _patch_config(hand_show_skeleton=bool(on))


def get_sensitivity() -> str:
    v = _cfg().get("hand_cursor_sens", "normal")
    return v if v in SENSITIVITY else "normal"


def set_sensitivity(v: str) -> None:
    if v in SENSITIVITY:
        from memory.config_manager import _patch_config
        _patch_config(hand_cursor_sens=v)


# ── OS mouse (no pyautogui pauses, never touches the fail-safe corner) ────────────
class Mouse:
    def __init__(self):
        self._win = sys.platform == "win32"
        self._pg = None
        if self._win:
            import ctypes
            self._u32 = ctypes.windll.user32
        else:
            import pyautogui
            self._pg = pyautogui

    def size(self) -> tuple[int, int]:
        if self._win:
            return self._u32.GetSystemMetrics(0), self._u32.GetSystemMetrics(1)
        return tuple(self._pg.size())

    def move(self, x: int, y: int) -> None:
        if self._win:
            self._u32.SetCursorPos(int(x), int(y))
        else:
            self._pg.moveTo(int(x), int(y), _pause=False)

    def button(self, which: str, down: bool) -> None:
        if self._win:
            flags = {("left", True): 0x0002, ("left", False): 0x0004,
                     ("right", True): 0x0008, ("right", False): 0x0010}[(which, down)]
            self._u32.mouse_event(flags, 0, 0, 0, 0)
        else:
            (self._pg.mouseDown if down else self._pg.mouseUp)(button=which, _pause=False)

    def scroll(self, amount: int) -> None:
        if not amount:
            return
        if self._win:
            self._u32.mouse_event(0x0800, 0, 0, int(amount), 0)
        else:
            self._pg.scroll(int(amount / 120) or (1 if amount > 0 else -1), _pause=False)


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class OneEuro:
    """Adaptive low-pass (1€ filter): rock steady when the hand rests, no lag when it moves fast."""

    def __init__(self, mincutoff: float = 1.1, beta: float = 0.011, dcutoff: float = 1.2):
        self.mincutoff, self.beta, self.dcutoff = mincutoff, beta, dcutoff
        self.x: float | None = None
        self.dx = 0.0
        self.t = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / max(dt, 1e-3))

    def reset(self, x: float | None = None, t: float = 0.0) -> None:
        self.x, self.dx, self.t = x, 0.0, t

    def __call__(self, v: float, t: float) -> float:
        if self.x is None:
            self.reset(v, t)
            return v
        dt = max(1e-3, min(0.2, t - self.t))
        self.t = t
        d = (v - self.x) / dt
        self.dx += self._alpha(self.dcutoff, dt) * (d - self.dx)
        cutoff = self.mincutoff + self.beta * abs(self.dx)
        self.x += self._alpha(cutoff, dt) * (v - self.x)
        return self.x


class HandCursor:
    """Feed it one frame of 21 hand landmarks at a time; it moves the cursor and presses buttons.

    Click accuracy comes from three things: the cursor freezes at the spot you were pointing at the moment the fingers
    start closing (the fingertip always jerks while pinching), the press needs two consecutive frames (no phantom
    clicks), and after the press the cursor only starts to drag once the hand really travels.
    """

    def __init__(self, on_state=None, on_panic=None, mouse: Mouse | None = None, on_hand=None):
        self.on_state = on_state or (lambda x, y, s: None)   # (screen x, screen y, state) — hover|pinch|right|scroll|fist|lost
        self.on_hand = on_hand or (lambda pts, pinch: None)  # skeleton for the overlay: 21 screen points, pinch 0..1
        self.on_panic = on_panic or (lambda: None)
        self.mouse = mouse or Mouse()
        self.sw, self.sh = self.mouse.size()
        self.half = SENSITIVITY[get_sensitivity()]
        self.pos: tuple[float, float] | None = None
        self.down = False
        self.dragging = False
        self.state = "lost"
        self._seen = time.time()
        self._fist_since = 0.0
        self._right_t = 0.0
        self._scroll_y: float | None = None
        self._scroll_acc = 0.0
        self._hist: deque = deque()          # (time, smoothed pointer) while moving freely
        self._anchor: tuple[float, float] | None = None
        self._mid0: tuple[float, float] | None = None
        self._press_n = 0
        self._rel_n = 0
        self._rest_until = 0.0
        self._fx, self._fy = OneEuro(), OneEuro()

    # screen position from a normalised, un-mirrored camera point
    def _map(self, p, clamp: bool = True) -> tuple[float, float]:
        nx = 0.5 + (0.5 - p[0]) / (2 * self.half)           # mirrored: moving right moves the cursor right
        ny = 0.5 + (p[1] - 0.45) / (2 * self.half * 0.8)
        if clamp:
            nx, ny = min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny))
        return 2 + nx * (self.sw - 5), 2 + ny * (self.sh - 5)

    def _smooth(self, target: tuple[float, float], now: float) -> tuple[float, float]:
        if self.pos is None:
            self.pos = target
            self._fx.reset(target[0], now)
            self._fy.reset(target[1], now)
            return target
        self.pos = (self._fx(target[0], now), self._fy(target[1], now))
        return self.pos

    def _sync_filters(self, pos: tuple[float, float], now: float) -> None:
        self._fx.reset(pos[0], now)
        self._fy.reset(pos[1], now)

    def _set_state(self, s: str):
        self.state = s
        x, y = self.pos or (0, 0)
        try:
            self.on_state(int(x), int(y), s)
        except Exception:
            pass

    def _emit_hand(self, lm, pinch: float):
        """Skeleton in screen space, shifted so the index fingertip sits exactly on the cursor."""
        if self.pos is None:
            return
        pts = [self._map(p, clamp=False) for p in lm]
        dx, dy = self.pos[0] - pts[8][0], self.pos[1] - pts[8][1]
        k = max(0.0, min(1.0, (APPROACH - pinch) / (APPROACH - PINCH_ON)))
        try:
            self.on_hand([(x + dx, y + dy) for x, y in pts], k)
        except Exception:
            pass

    def update(self, lm, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if not lm:
            if now - self._seen > LOST_RELEASE:
                self.release()
                self._hist.clear()
                if self.state != "lost":
                    self.on_hand(None, 0.0)
                    self._set_state("lost")
            return
        self._seen = now
        scale = max(1e-6, (_d(lm[0], lm[9]) + 1.3 * _d(lm[5], lm[17])) / 2)   # hand size, stable when the hand turns
        pinch = _d(lm[4], lm[8]) / scale
        right = _d(lm[4], lm[12]) / scale
        pose = gesture.classify(lm)

        # fist: neutral pose — never clicks (a closed hand makes thumb and index touch), cursor stays put.
        # Held long enough it is the panic stop.
        if pose == "fist":
            self._end_press()
            self._fist_since = self._fist_since or now
            if now - self._fist_since >= PANIC_SECONDS:
                self.release()
                self._fist_since = 0.0
                self.on_panic()
                return
            self._set_state("fist")
            self._emit_hand(lm, 0.0)
            return
        self._fist_since = 0.0

        # scroll mode: ✌ — the cursor stays put, vertical hand travel turns the wheel
        if pose == "peace" and not self.down:
            y = lm[9][1]
            if self._scroll_y is not None:
                self._scroll_acc += (self._scroll_y - y) * SCROLL_GAIN
                step = int(self._scroll_acc)
                if abs(step) >= 40:
                    self.mouse.scroll(step)
                    self._scroll_acc -= step
            self._scroll_y = y
            self._set_state("scroll")
            self._emit_hand(lm, 0.0)
            return
        self._scroll_y, self._scroll_acc = None, 0.0

        closing = self.down or pinch < APPROACH
        state = "hover"
        if not closing:
            # free pointing: smoothed fingertip; remember where it has been
            self._anchor = None
            self._press_n = self._rel_n = 0
            if now >= self._rest_until:
                x, y = self._smooth(self._map(((lm[8][0] * 0.7 + lm[7][0] * 0.3), (lm[8][1] * 0.7 + lm[7][1] * 0.3))), now)
                self.mouse.move(x, y)
                self._hist.append((now, (x, y)))
                while self._hist and now - self._hist[0][0] > 0.6:
                    self._hist.popleft()
            if right < RIGHT_ON and now - self._right_t > 0.8:
                self._right_t = now
                self.mouse.button("right", True)
                self.mouse.button("right", False)
                state = "right"
        else:
            mid_n = ((lm[4][0] + lm[8][0]) / 2, (lm[4][1] + lm[8][1]) / 2)
            mid = self._map(mid_n, clamp=False)
            if self._anchor is None:                    # fingers just started closing: freeze where we were pointing
                old = next((p for t, p in self._hist if now - t <= LOOKBACK), None) or self.pos or self._map(lm[8])
                self._anchor, self._mid0 = old, mid
                self.pos = old
                self._sync_filters(old, now)
                self.mouse.move(*old)
            if not self.down:
                self._rel_n = 0
                self._press_n = self._press_n + 1 if pinch < PINCH_ON else 0
                if self._press_n >= CONFIRM_FRAMES:
                    self.mouse.button("left", True)
                    self.down, self.dragging = True, False
                    self._mid0 = mid
                elif pinch > APPROACH:
                    self._anchor = None
            else:
                self._rel_n = self._rel_n + 1 if pinch > PINCH_OFF else 0
                if self._rel_n >= CONFIRM_FRAMES:
                    self._end_press()
                    self._rest_until = now + SETTLE
                    self._sync_filters(self.pos, now)
                else:
                    dx, dy = mid[0] - self._mid0[0], mid[1] - self._mid0[1]
                    if not self.dragging and math.hypot(dx, dy) > DRAG_PX:
                        self.dragging = True
                    if self.dragging:
                        tx = min(self.sw - 3, max(2, self._anchor[0] + dx))
                        ty = min(self.sh - 3, max(2, self._anchor[1] + dy))
                        self.pos = (self.pos[0] + (tx - self.pos[0]) * 0.6, self.pos[1] + (ty - self.pos[1]) * 0.6)
                        self.mouse.move(*self.pos)
            state = "pinch" if self.down else "hover"
        self._set_state(state)
        self._emit_hand(lm, pinch)

    def _end_press(self) -> None:
        if self.down:
            try:
                self.mouse.button("left", False)
            except Exception:
                pass
        self.down = self.dragging = False
        self._anchor = None
        self._press_n = self._rel_n = 0

    def release(self) -> None:
        self._end_press()
        self._scroll_y, self._scroll_acc = None, 0.0
        self.pos = None
