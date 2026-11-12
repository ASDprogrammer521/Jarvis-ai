"""Hand Space — an Iron-Man-style holographic workspace you control with bare hands (camera + MediaPipe).

Glass cards (your notes and pictures from a folder) float in the air together with a 3D holographic model:

    pinch a card .......... grab it · move your hand to carry it
    quick pinch (tap) ..... open the card to read it · tap again to close
    let go while moving ... throw it — it flies, spins and bounces off the screen edges
    claw (bent fingers) ... every card is pulled towards your palm and orbits it; open the hand to release them
    pinch the model ....... spin it, it keeps turning with inertia
    both hands pinching ... rotate and zoom the model
    fist, then open ....... over the model: it explodes and reassembles
    pinch the ✕ ........... leave Hand Space

This module is pure logic (no Qt) so it can be tested without a camera; ui/hand_space.py draws it.
"""
from __future__ import annotations

import math
import random
import re
import time
from collections import deque
from pathlib import Path

CARD_W, CARD_H = 230, 150
OPEN_W, OPEN_H = 640, 440
PINCH_ON, PINCH_OFF, CONFIRM = 0.32, 0.50, 2
GAIN = 1.25                      # camera → screen: the central 80 % of the picture reaches every screen edge
MAX_THROW = 4200.0
TAP_SECONDS, TAP_PIXELS = 0.38, 42
MAX_CARDS = 40
TEXT_EXT = {".md", ".markdown", ".txt"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


# ── cards from a folder ──────────────────────────────────────────────────────────────
def _clean_md(text: str) -> str:
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)            # front matter
    text = re.sub(r"!\[\[.*?\]\]|!\[.*?\]\(.*?\)", "", text)             # embedded images
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)          # [[wiki|links]]
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)                  # [links](url)
    text = re.sub(r"^[#>\-\*\s]+", "", text, flags=re.M)
    text = re.sub(r"[*_`~]{1,3}", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_cards(folder: str | Path | None, limit: int = MAX_CARDS) -> list[dict]:
    """Newest notes and pictures first. Hidden folders (.obsidian, .git…) are skipped."""
    if not folder or not Path(folder).is_dir():
        return demo_cards()
    root = Path(folder)
    files = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in TEXT_EXT | IMG_EXT and not any(part.startswith(".") for part in p.relative_to(root).parts):
            try:
                files.append((p.stat().st_mtime, p))
            except OSError:
                pass
    cards = []
    for _, p in sorted(files, reverse=True)[:limit]:
        if p.suffix.lower() in IMG_EXT:
            cards.append({"title": p.stem[:40], "text": "", "image": str(p), "path": str(p)})
            continue
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            continue
        m = re.search(r"^#\s+(.+)$", raw, flags=re.M)
        cards.append({"title": (m.group(1) if m else p.stem).strip()[:60], "text": _clean_md(raw)[:1600], "image": None, "path": str(p)})
    return cards or demo_cards()


def demo_cards() -> list[dict]:
    return [
        {"title": "Pinch me", "text": "Touch thumb and index finger on a card to grab it, then move your hand.", "image": None},
        {"title": "Tap to open", "text": "A quick pinch opens a card so you can read it. Pinch again to close it.", "image": None},
        {"title": "Throw", "text": "Let go while your hand is moving and the card flies, spins and bounces.", "image": None},
        {"title": "Claw", "text": "Bend your fingers like a claw: every card is pulled to your palm. Open your hand to release them.", "image": None},
        {"title": "3D model", "text": "Pinch the hologram to spin it, use two hands to rotate and zoom. Make a fist and open it over the model to explode it.", "image": None},
        {"title": "Your notes", "text": "Open the Hand Space page in the side menu and choose a folder (a Markdown folder or Obsidian vault works) — or write a new card there.", "image": None},
    ]


# ── physics objects ──────────────────────────────────────────────────────────────────
class Card:
    def __init__(self, idx: int, data: dict, x: float, y: float):
        self.idx, self.data = idx, data
        self.x, self.y = x, y
        self.vx = self.vy = 0.0
        self.angle = random.uniform(-0.08, 0.08)
        self.spin = 0.0
        self.k = 0.0                 # 0 = small card … 1 = fully opened
        self.open = False
        self.held = False
        self.phase = random.uniform(0, 6.28)
        self.lift = 0.0              # 0..1, grows while held (shadow / scale)
        self._target = None          # claw orbit target

    @property
    def w(self) -> float:
        return CARD_W + (OPEN_W - CARD_W) * self.k

    @property
    def h(self) -> float:
        return CARD_H + (OPEN_H - CARD_H) * self.k

    def hit(self, px: float, py: float, pad: float = 30.0) -> bool:
        return abs(px - self.x) <= self.w / 2 + pad and abs(py - self.y) <= self.h / 2 + pad


class Model:
    """A holographic wireframe orb. `explode` runs 0 → 1 → 0."""

    def __init__(self, cx: float, cy: float, r: float):
        self.cx, self.cy, self.r = cx, cy, r
        self.yaw, self.pitch = 0.4, 0.3
        self.vyaw, self.vpitch = 0.0, 0.0
        self.scale = 1.0
        self.explode = 0.0
        self._boom_t = 0.0
        self.held = False

    @property
    def radius(self) -> float:
        return self.r * self.scale

    def boom(self, now: float):
        if self.explode < 0.05:
            self._boom_t = now

    def step(self, dt: float, now: float):
        self.yaw += (self.vyaw + (0 if self.held else 0.28)) * dt
        self.pitch += self.vpitch * dt
        self.vyaw *= math.exp(-1.6 * dt)
        self.vpitch *= math.exp(-1.6 * dt)
        self.pitch = max(-1.3, min(1.3, self.pitch))
        age = now - self._boom_t
        if self._boom_t and age < 0.45:
            self.explode = min(1.0, self.explode + 4.0 * dt)
        elif self._boom_t and age < 2.3:
            self.explode = min(1.0, self.explode)
        else:
            self.explode = max(0.0, self.explode - 1.1 * dt)
            if self.explode == 0.0:
                self._boom_t = 0.0


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Hand:
    """One tracked hand: screen-space points plus pinch / claw / fist / open classification."""

    def __init__(self):
        self.pts: list[tuple[float, float]] | None = None
        self.pinching = False
        self._pn = self._rn = 0
        self.pos = (0.0, 0.0)            # smoothed pinch point
        self.palm = (0.0, 0.0)
        self.claw = self.fist = self.open = False
        self.held = None                 # Card | "model" | None
        self.grab_off = (0.0, 0.0)
        self.down_t = 0.0
        self.down_pos = (0.0, 0.0)
        self.hist: deque = deque(maxlen=10)
        self.fist_since = 0.0
        self.fist_until = 0.0            # remembers a recent fist so "fist → open" can be detected
        self.speed = 0.0
        self._edge = (False, False)       # (pinch started, pinch ended) this frame

    def update(self, pts, ratio: float, tips: list[float], now: float):
        self.pts = pts
        prev_palm = self.palm
        mid = ((pts[4][0] + pts[8][0]) / 2, (pts[4][1] + pts[8][1]) / 2)
        palm = (sum(pts[i][0] for i in (0, 5, 9, 13, 17)) / 5, sum(pts[i][1] for i in (0, 5, 9, 13, 17)) / 5)   # the hand's body
        a = 0.55
        self.pos = mid if not self.hist else (self.pos[0] + (mid[0] - self.pos[0]) * a, self.pos[1] + (mid[1] - self.pos[1]) * a)
        self.palm = palm if self.palm == (0.0, 0.0) else (self.palm[0] + (palm[0] - self.palm[0]) * 0.6, self.palm[1] + (palm[1] - self.palm[1]) * 0.6)
        ext = sum(1 for r in tips if r > 1.7)
        bent = sum(1 for r in tips if 1.15 < r <= 1.7)
        self.fist = all(r <= 1.15 for r in tips)
        self.open = ext >= 3
        self.claw = bent >= 3 and not self.fist
        # pinch with hysteresis + confirmation; a fist never pinches (thumb and index touch in a fist)
        if self.fist:
            self._pn = 0
            self._rn = self._rn + 1 if self.pinching else 0
            if self._rn >= CONFIRM:
                self.pinching = False
        elif not self.pinching:
            self._pn = self._pn + 1 if ratio < PINCH_ON else 0
            if self._pn >= CONFIRM:
                self.pinching, self._rn = True, 0
        else:
            self._rn = self._rn + 1 if ratio > PINCH_OFF else 0
            if self._rn >= CONFIRM:
                self.pinching, self._pn = False, 0
        if self.fist:
            self.fist_since = self.fist_since or now
            if now - self.fist_since > 0.25:
                self.fist_until = now + 0.7
        else:
            self.fist_since = 0.0
        # velocity comes from the palm, not the pinch point: opening the pinch moves the point between the fingertips,
        # which would add a fake kick to every throw
        self.hist.append((now, self.palm[0], self.palm[1]))
        dt = max(1e-3, now - (self.hist[-2][0] if len(self.hist) > 1 else now - 0.033))
        self.speed = _d(self.palm, prev_palm) / dt if prev_palm != (0.0, 0.0) else 0.0

    def velocity(self) -> tuple[float, float]:
        """Palm velocity in px/s over the last ~0.1 s — what a throw is launched with."""
        if len(self.hist) < 2:
            return 0.0, 0.0
        t1, x1, y1 = self.hist[-1]
        for t0, x0, y0 in reversed(self.hist):
            if t1 - t0 >= 0.09:
                break
        dt = max(1e-3, t1 - t0)
        vx, vy = (x1 - x0) / dt, (y1 - y0) / dt
        sp = math.hypot(vx, vy)
        if sp > MAX_THROW:
            vx, vy = vx * MAX_THROW / sp, vy * MAX_THROW / sp
        return vx, vy


class Space:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.cards: list[Card] = []
        self.model = Model(w * 0.5, h * 0.52, min(w, h) * 0.17)
        self.hands: list[Hand] = [Hand(), Hand()]
        self.visible = [False, False]
        self.close_requested = False
        self.now = time.time()
        self._two: dict | None = None
        self._claw_n = 0

    # ── cards ────────────────────────────────────────────────────────────────────
    def set_cards(self, items: list[dict]):
        self.cards.clear()
        n = len(items)
        cx, cy = self.w / 2, self.h / 2
        rx, ry = self.w * 0.36, self.h * 0.34
        for i, d in enumerate(items):
            a = 2 * math.pi * i / max(1, n) + random.uniform(-0.15, 0.15)
            ring = 1.0 if i % 2 == 0 else 0.62                                  # two rings so many cards stay reachable
            self.cards.append(Card(i, d, cx + math.cos(a) * rx * ring, cy + math.sin(a) * ry * ring))

    def resize(self, w: int, h: int):
        sx, sy = w / self.w, h / self.h
        for c in self.cards:
            c.x, c.y = c.x * sx, c.y * sy
        self.w, self.h = w, h
        self.model.cx, self.model.cy, self.model.r = w * 0.5, h * 0.52, min(w, h) * 0.17

    def _opened(self) -> Card | None:
        return next((c for c in self.cards if c.open), None)

    # ── input ────────────────────────────────────────────────────────────────────
    def to_screen(self, p) -> tuple[float, float]:
        x = (0.5 - p[0]) * GAIN + 0.5                                         # mirrored, like a mirror
        y = (p[1] - 0.5) * GAIN + 0.5
        return x * self.w, y * self.h

    def update_hands(self, all_lm: list | None, now: float | None = None):
        """all_lm: for each detected hand, 21 normalised (x, y) landmarks."""
        now = time.time() if now is None else now
        self.now = now
        lms = sorted(all_lm or [], key=lambda lm: lm[9][0], reverse=True)[:2]     # camera-right (= screen-left) first → stable ids
        for i, hand in enumerate(self.hands):
            if i >= len(lms):
                if self.visible[i]:
                    self._lost(hand, now)
                self.visible[i] = False
                continue
            lm = lms[i]
            scale = max(1e-6, (_d(lm[0], lm[9]) + 1.3 * _d(lm[5], lm[17])) / 2)
            ratio = _d(lm[4], lm[8]) / scale
            tips = [_d(lm[0], lm[t]) / max(1e-6, _d(lm[0], lm[m])) for t, m in ((8, 5), (12, 9), (16, 13), (20, 17))]
            was_pinch = hand.pinching
            hand.update([self.to_screen(p) for p in lm], ratio, tips, now)
            self.visible[i] = True
            hand._edge = (not was_pinch and hand.pinching, was_pinch and not hand.pinching)
        self._interact(now)

    def mouse(self, x: float, y: float, down: bool, now: float | None = None):
        """Mouse stand-in for hand 0 so the space can be tried without a camera."""
        now = time.time() if now is None else now
        self.now = now
        h = self.hands[0]
        was = h.pinching
        h.pos = (x, y)
        h.palm = (x, y)
        h.pinching = down
        h.pts = None
        h.hist.append((now, x, y))
        h._edge = (down and not was, was and not down)
        self.visible[0] = True
        self._interact(now, mouse=True)

    # ── interaction ──────────────────────────────────────────────────────────────
    def _lost(self, hand: Hand, now: float):
        if hand.held is not None:
            self._release(hand, now)
        hand.pinching = False
        hand.pts = None
        hand.claw = hand.fist = hand.open = False
        hand.hist.clear()
        hand.palm = (0.0, 0.0)

    def _grab(self, hand: Hand, now: float):
        x, y = hand.pos
        if _d((x, y), (self.w - 60, 60)) < 46:
            self.close_requested = True
            return
        op = self._opened()
        for c in reversed(self.cards):                      # top-most first
            if c.hit(x, y) and (op is None or c is op):
                hand.held, hand.grab_off = c, (c.x - x, c.y - y)
                hand.down_t, hand.down_pos = now, hand.palm
                c.held = not c.open
                return
        if op is None and _d((x, y), (self.model.cx, self.model.cy)) < self.model.radius * 1.35:
            hand.held, hand.down_t, hand.down_pos = "model", now, hand.palm
            self.model.held = True
            self.model.vyaw = self.model.vpitch = 0.0

    def _release(self, hand: Hand, now: float):
        h = hand.held
        hand.held = None
        if h == "model":
            self.model.held = False
            return
        if not isinstance(h, Card):
            return
        h.held = False
        moved = _d(hand.palm, hand.down_pos)
        if now - hand.down_t < TAP_SECONDS and moved < TAP_PIXELS:           # a tap: open / close the card
            h.open = not h.open
            if h.open:
                for o in self.cards:
                    if o is not h:
                        o.open = False
            h.vx = h.vy = 0.0
            return
        if h.open:
            return
        vx, vy = hand.velocity()
        h.vx, h.vy = vx * 1.15, vy * 1.15
        h.spin = max(-9.0, min(9.0, vx * 0.0021))

    def _interact(self, now: float, mouse: bool = False):
        m = self.model
        act = [(i, h) for i, h in enumerate(self.hands) if self.visible[i]]
        # two hands pinching the empty space: rotate + zoom the model
        both = len(act) == 2 and all(h.pinching and h.held in (None, "model") for _, h in act)
        if both:
            a, b = act[0][1].pos, act[1][1].pos
            ang, dist = math.atan2(b[1] - a[1], b[0] - a[0]), max(40.0, _d(a, b))
            if self._two is None:
                self._two = {"ang": ang, "dist": dist, "yaw": m.yaw, "pitch": m.pitch, "scale": m.scale, "my": (a[1] + b[1]) / 2}
                for _, h in act:
                    if h.held == "model":
                        h.held = None
                m.held = True
            t = self._two
            d_ang = (ang - t["ang"] + math.pi) % (2 * math.pi) - math.pi
            m.yaw = t["yaw"] + d_ang * 2.0
            m.pitch = max(-1.3, min(1.3, t["pitch"] + ((a[1] + b[1]) / 2 - t["my"]) * 0.004))
            m.scale = max(0.5, min(2.2, t["scale"] * dist / t["dist"]))
            return
        if self._two is not None:
            self._two = None
            m.held = False

        for i, h in act:
            rise, fall = h._edge
            if rise:
                self._grab(h, now)
            if fall and h.held is not None:
                self._release(h, now)
            if h.pinching and h.held is not None:
                if isinstance(h.held, Card):
                    c = h.held
                    c.vx = c.vy = 0.0
                    if not c.open:
                        tx, ty = h.pos[0] + h.grab_off[0], h.pos[1] + h.grab_off[1]
                        c.x += (tx - c.x) * 0.45
                        c.y += (ty - c.y) * 0.45
                elif h.held == "model" and len(h.hist) >= 2:
                    (t0, x0, y0), (t1, x1, y1) = h.hist[-2], h.hist[-1]
                    dt = max(1e-3, t1 - t0)
                    m.yaw += (x1 - x0) * 0.011
                    m.pitch += (y1 - y0) * 0.011
                    m.vyaw, m.vpitch = (x1 - x0) / dt * 0.011, (y1 - y0) / dt * 0.011
            # fist, then open the hand over the model → explode
            if h.open and h.fist_until > now and _d(h.palm, (m.cx, m.cy)) < m.radius * 1.9 and not mouse:
                m.boom(now)
                h.fist_until = 0.0

        # claw: pull every free card into an orbit around the palm
        claw = next((h for _, h in act if h.claw and not h.pinching), None)
        self._claw_n = 0
        if claw is not None:
            free = [c for c in self.cards if not c.held and not c.open]
            for j, c in enumerate(free):
                a = 2 * math.pi * j / max(1, len(free)) + now * 0.6
                r = 120 + 26 * (j // 8)
                c._target = (claw.palm[0] + math.cos(a) * r, claw.palm[1] + math.sin(a) * r)
            self._claw_n = len(free)
        else:
            for c in self.cards:
                c._target = None
        # open-palm swipe pushes nearby cards
        for _, h in act:
            if h.open and h.speed > 900 and not mouse:
                for c in self.cards:
                    if not c.held and not c.open and _d(h.palm, (c.x, c.y)) < 170:
                        d = max(1.0, _d(h.palm, (c.x, c.y)))
                        c.vx += (c.x - h.palm[0]) / d * min(h.speed, 2200) * 0.5
                        c.vy += (c.y - h.palm[1]) / d * min(h.speed, 2200) * 0.5

    # ── physics ──────────────────────────────────────────────────────────────────
    def step(self, dt: float, now: float | None = None):
        now = time.time() if now is None else now
        dt = min(dt, 0.05)
        self.model.step(dt, now)
        for c in self.cards:
            tgt_k = 1.0 if c.open else 0.0
            c.k += (tgt_k - c.k) * min(1.0, 9 * dt)
            c.lift += ((1.0 if c.held else 0.0) - c.lift) * min(1.0, 12 * dt)
            if c.open:                                           # glide to the middle of the screen
                c.x += (self.w / 2 - c.x) * min(1.0, 8 * dt)
                c.y += (self.h / 2 - c.y) * min(1.0, 8 * dt)
                c.angle *= math.exp(-9 * dt)
                c.vx = c.vy = c.spin = 0.0
                continue
            if c.held:
                c.angle += (max(-0.35, min(0.35, c.vx * 0.0)) - c.angle) * min(1.0, 8 * dt)
                continue
            tgt = c._target
            if tgt is not None:                                  # claw orbit: critically-damped spring
                c.vx += (tgt[0] - c.x) * 38 * dt
                c.vy += (tgt[1] - c.y) * 38 * dt
                damp = math.exp(-9 * dt)
                c.vx *= damp
                c.vy *= damp
            else:
                damp = math.exp(-1.25 * dt)
                c.vx *= damp
                c.vy *= damp
                c.phase += dt
                if math.hypot(c.vx, c.vy) < 40:                  # idle: gentle floating
                    c.y += math.sin(c.phase * 1.3) * 6 * dt
            c.x += c.vx * dt
            c.y += c.vy * dt
            hw, hh = c.w / 2, c.h / 2
            if c.x < hw:
                c.x, c.vx = hw, abs(c.vx) * 0.72
            elif c.x > self.w - hw:
                c.x, c.vx = self.w - hw, -abs(c.vx) * 0.72
            if c.y < hh:
                c.y, c.vy = hh, abs(c.vy) * 0.72
            elif c.y > self.h - hh:
                c.y, c.vy = self.h - hh, -abs(c.vy) * 0.72
            c.angle += c.spin * dt
            c.spin *= math.exp(-2.2 * dt)
            if abs(c.spin) < 0.4:                                # settle upright (nearest turn)
                c.angle = (c.angle + math.pi) % (2 * math.pi) - math.pi
                c.angle *= math.exp(-3.5 * dt)

    @property
    def hint(self) -> str:
        if self._opened():
            return "Pinch the card to close it"
        if self._claw_n:
            return "Claw: open your hand to release the cards"
        return "Pinch = grab · tap = open · throw · claw = pull · two hands = rotate the model · fist → open on the model = explode"
