"""Game HUD overlay — no panel, no background: just glowing, outlined text floating over the game.

It never takes the mouse or focus, stays above every window (re-asserted every second, because games fight for the top
spot) and is readable on any picture thanks to a dark outline + soft glow around every glyph. Exclusive-fullscreen games
cannot be overlaid by any normal window; use borderless / windowed-fullscreen for them.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ui.overlay_utils import force_topmost
from ui.theme import C

W = 330
PAD = 6
MARGIN = 22
FONT = "Segoe UI"


def _clock(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 60:d}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _font(size: float, weight=QFont.Weight.DemiBold) -> QFont:
    f = QFont(FONT)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


class GameHudOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.snap: dict = {}
        self._phase = 0.0
        self._top_t = 0.0
        self._t = QTimer(self)
        self._t.timeout.connect(self._refresh)

    def show_overlay(self):
        from core.game_hud import get_hud
        get_hud().sync_fps()
        self._refresh()
        self.show()
        force_topmost(self)
        self._t.start(200)

    def hide(self):                       # noqa: A003 — Qt override, also stops polling
        self._t.stop()
        super().hide()

    # ── layout: measured first, so the window is exactly as tall as its content ──────────
    def _height(self, s: dict) -> int:
        h = 2 * PAD
        if s["show_fps"] or s["show_clock"]:
            h += 52
        elif s["show_session"] or s["game"]:
            h += 22
        h += len(s["timers"]) * 36 + (34 if s["routine"] else 0) + len(s["tips"]) * 26
        if s["binds"]:
            h += 14 + ((len(s["binds"]) + 1) // 2) * 24
        return max(40, h)

    def _refresh(self):
        from core.game_hud import get_hud
        self.snap = get_hud().snapshot()
        s = self.snap
        self.setFixedSize(W, self._height(s))
        scr = (self.screen() or QGuiApplication.primaryScreen()).geometry()
        right = s["corner"].endswith("right")
        x = scr.right() - W - MARGIN if right else scr.left() + MARGIN
        y = scr.top() + MARGIN if s["corner"].startswith("top") else scr.bottom() - self.height() - MARGIN
        self.move(x, y)
        self._phase = (self._phase + 0.4) % 6.2832
        if time.time() - self._top_t > 1.0:                    # keep winning the "always on top" fight
            self._top_t = time.time()
            force_topmost(self)
        self.update()

    # ── drawing ──────────────────────────────────────────────────────────────────────
    def _text(self, p: QPainter, x: float, base: float, txt: str, font: QFont, col: QColor, right: bool = False,
              glow: bool = True, op: float = 1.0):
        """Outlined text with a soft coloured glow — readable on bright and dark scenes without any backdrop."""
        fm = QFontMetricsF(font)
        if right:
            x -= fm.horizontalAdvance(txt)
        path = QPainterPath()
        path.addText(QPointF(x, base), font, txt)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if glow:
            g = QColor(col)
            g.setAlpha(int(46 * op))
            p.setPen(QPen(g, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
        o = QColor(0, 0, 0, int(215 * op))
        p.setPen(QPen(o, 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        c = QColor(col)
        c.setAlpha(int(255 * op))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPath(path)

    def _bar(self, p: QPainter, x0: float, x1: float, y: float, frac: float, col: QColor, op: float):
        track = QColor(0, 0, 0, int(150 * op))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(x0 - 1, y - 1, x1 - x0 + 2, 5), 2.5, 2.5)
        glow = QColor(col)
        glow.setAlpha(int(70 * op))
        p.setBrush(glow)
        p.drawRoundedRect(QRectF(x0 - 1, y - 2, (x1 - x0 + 2) * frac, 7), 3.5, 3.5)
        c = QColor(col)
        c.setAlpha(int(240 * op))
        p.setBrush(c)
        p.drawRoundedRect(QRectF(x0, y, max(2.0, (x1 - x0) * frac), 3), 1.5, 1.5)

    def paintEvent(self, _):
        s = self.snap
        if not s:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        op = max(0.35, min(1.0, s["opacity"]))
        right = s["corner"].endswith("right")
        x0, x1 = PAD, W - PAD
        ax = x1 if right else x0                     # anchor edge for the big numbers
        pri, txt, dim = QColor(C.PRI), QColor(C.TEXT), QColor(C.TEXT_MED)
        y = PAD

        # ── header: FPS and clock, big ──
        if s["show_fps"] or s["show_clock"]:
            fps = s["fps"]
            parts: list[tuple[str, QFont, QColor]] = []
            if s["show_fps"]:
                if fps:
                    v = fps["fps"]
                    col = QColor(C.GREEN if v >= 55 else C.AMBER if v >= 30 else C.RED)
                    parts += [(f"{v:.0f}", _font(25, QFont.Weight.Bold), col), (" FPS", _font(9.5), dim),
                              (f"  {fps['ms']:.1f} ms", _font(9.5), dim)]
                else:
                    why = {"missing": "needs PresentMon"}.get(s["fps_state"],
                                                              "needs Administrator" if s["fps_state"].startswith("error") else "")
                    parts += [("— ", _font(25, QFont.Weight.Bold), dim), ("FPS", _font(9.5), dim)]
                    if why:
                        parts.append((f"  {why}", _font(8.5), dim))
            base = y + 31
            if s["show_clock"]:
                self._text(p, ax, base, s["wall"], _font(17, QFont.Weight.Bold), txt, right=right)
            # FPS group sits on the opposite edge from the clock when both are shown
            if parts:
                total = sum(QFontMetricsF(f).horizontalAdvance(t) for t, f, _ in parts)
                px = (x0 if right else x1 - total) if s["show_clock"] else (x1 - total if right else x0)
                for t, f, c in parts:
                    self._text(p, px, base, t, f, c, op=op)
                    px += QFontMetricsF(f).horizontalAdvance(t)
            y += 36
            sub = []
            if s["game"]:
                sub.append(s["game"].upper())
            if s["show_session"]:
                sub.append("⏱ " + _clock(s["session"]))
            if sub:
                self._text(p, ax, y + 11, "   ·   ".join(sub), _font(8.5), pri, right=right, glow=False, op=op)
            y += 16
        elif s["show_session"] or s["game"]:
            sub = ([s["game"].upper()] if s["game"] else []) + (["⏱ " + _clock(s["session"])] if s["show_session"] else [])
            self._text(p, ax, y + 14, "   ·   ".join(sub), _font(9), pri, right=right, op=op)
            y += 22

        # ── timers ──
        for t in s["timers"]:
            soon = t["left"] <= 10
            col = QColor(C.RED if soon and int(self._phase * 1.3) % 2 else C.AMBER if soon else C.PRI)
            self._text(p, x0, y + 17, ("↻ " if t["repeat"] else "") + t["name"], _font(10.5), txt, op=op)
            self._text(p, x1, y + 17, _clock(t["left"]), _font(12, QFont.Weight.Bold), col, right=True, op=op)
            self._bar(p, x0, x1, y + 24, 1.0 - t["left"] / max(1.0, t["total"]), col, op)
            y += 36

        # ── training routine ──
        r = s["routine"]
        if r:
            g = QColor(C.GREEN)
            self._text(p, x0, y + 16, f"▶ {r['step']}/{r['of']}  {r['text']}"[:40], _font(10), g, op=op)
            self._text(p, x1, y + 16, _clock(r["left"]), _font(11, QFont.Weight.Bold), g, right=True, op=op)
            self._bar(p, x0, x1, y + 24, 1.0 - r["left"] / max(1.0, r["total"]), g, op)
            y += 34

        # ── tips ──
        for tip in s["tips"]:
            self._text(p, x0, y + 16, "◆ " + tip[:44], _font(10.5), QColor(C.AMBER), op=op)
            y += 26

        # ── key binds: key caps + action ──
        if s["binds"]:
            y += 8
            half = (W - 2 * PAD) // 2
            for i, b in enumerate(s["binds"]):
                bx = x0 + (i % 2) * half
                by = y + (i // 2) * 24
                key = b["key"][:6]
                kf = _font(8.5, QFont.Weight.Bold)
                kw = QFontMetricsF(kf).horizontalAdvance(key) + 12
                p.setBrush(QColor(0, 0, 0, int(120 * op)))
                edge = QColor(C.PRI)
                edge.setAlpha(int(200 * op))
                p.setPen(QPen(edge, 1.1))
                p.drawRoundedRect(QRectF(bx, by + 2, kw, 18), 5, 5)
                self._text(p, bx + 6, by + 15, key, kf, pri, glow=False, op=op)
                self._text(p, bx + kw + 7, by + 15, b["action"][:16], _font(9.5), txt, glow=False, op=op)
