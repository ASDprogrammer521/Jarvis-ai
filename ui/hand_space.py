"""Hand Space window: a full-screen, hand-controlled file workspace (drives → folders → pictures and notes).

Logic and physics live in core/hand_space.py; this file only draws them. The mouse works too (handy without a camera).
Pictures are decoded in background threads, so browsing a big photo folder never stalls the screen.
"""
from __future__ import annotations

import math
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap, QRadialGradient, QTextOption)
from PyQt6.QtWidgets import QWidget

from core.hand_space import Card, Space, human_size
from ui.hand_overlay import BONES
from ui.overlay_utils import force_topmost
from ui.theme import C

THUMB_SIDE, LARGE_SIDE = 480, 3200
_AL = Qt.AlignmentFlag


def _decode(path: str, side: int):
    """Runs in a worker thread: returns (QImage, width, height). PIL is fast (JPEG draft mode) and honours EXIF rotation."""
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            ow, oh = im.size
            try:
                im.draft("RGB", (side, side))
            except Exception:
                pass
            im = ImageOps.exif_transpose(im)
            im.thumbnail((side, side), Image.BILINEAR)
            im = im.convert("RGBA")
            w, h = im.size
            qi = QImage(im.tobytes("raw", "RGBA"), w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
            real = (max(ow, oh), min(ow, oh)) if w >= h else (min(ow, oh), max(ow, oh))
            return qi, w, h, real
    except Exception:
        qi = QImage(path)
        if qi.isNull():
            return None
        if max(qi.width(), qi.height()) > side:
            qi = qi.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return qi, qi.width(), qi.height(), (qi.width(), qi.height())


class HandSpaceOverlay(QWidget):
    closed = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.space = Space(1920, 1080)
        self._thumbs: OrderedDict[str, QPixmap] = OrderedDict()
        self._large: OrderedDict[str, QPixmap] = OrderedDict()
        self._jobs: dict[tuple, Future] = {}
        self._failed: set[str] = set()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._bg: QPixmap | None = None
        self._idle = 0
        self._last = time.time()
        self._t = QTimer(self)
        self._t.timeout.connect(self._frame)

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def show_overlay(self, pinned: str | None = None):
        scr = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(scr)
        self.space.resize(scr.width(), scr.height())
        self.space.start(pinned)                       # always begins on "This PC": the drives, C: first
        self.space.close_requested = False
        self._bg = None
        self.show()
        force_topmost(self, click_through=False)
        self.activateWindow()
        self.setFocus()
        self._last = time.time()
        self._t.start(20)

    def hide(self):                           # noqa: A003
        self._t.stop()
        super().hide()

    def hideEvent(self, e):
        self._t.stop()
        for f in self._jobs.values():
            f.cancel()
        self._jobs.clear()
        self._thumbs.clear()                  # give the memory back
        self._large.clear()
        self._failed.clear()
        super().hideEvent(e)
        self.closed.emit()

    def set_hands(self, all_lm):
        if not self.isVisible():
            return
        self.space.update_hands(all_lm)
        if self.space.close_requested:
            self.hide()

    def _frame(self):
        now = time.time()
        self.space.step(now - self._last, now)
        self._last = now
        self._poll_images()
        sp = self.space
        busy = (any(sp.visible) or sp.opened is not None or sp.toast or self._jobs
                or any(c.a < 0.99 or c.homing or c.k > 0.01 or abs(c.vx) + abs(c.vy) > 2.0 for c in sp.cards))
        self._idle += 0 if busy else 1
        if busy or self._idle % 3 == 0:            # nothing is moving: repaint at a third of the rate (cards only float gently)
            self.update()

    # ── pictures (background decode) ────────────────────────────────────────────────
    def _want(self, path: str, side: int, cache: OrderedDict, limit: int):
        if path in cache or path in self._failed:
            if path in cache:
                cache.move_to_end(path)
            return
        key = (path, side)
        if key not in self._jobs and len(self._jobs) < 12:
            self._jobs[key] = self._pool.submit(_decode, path, side)

    def _poll_images(self):
        sp = self.space
        op = sp.opened
        for c in sp.cards:
            if c.data.get("image") and c.a > 0.02:
                self._want(c.data["image"], THUMB_SIDE, self._thumbs, 150)
        if op is not None and op.data.get("image") and op.k > 0.3:
            self._want(op.data["image"], LARGE_SIDE, self._large, 3)
        for key, fut in list(self._jobs.items()):
            if not fut.done():
                continue
            del self._jobs[key]
            path, side = key
            try:
                res = fut.result()
            except Exception:
                res = None
            if res is None:
                self._failed.add(path)
                continue
            qi, w, h, real = res
            for c in sp.cards:
                if c.data.get("image") == path and w > 0 and h > 0:
                    c.data["aspect"], c.data["dims"] = w / h, real
            if side == THUMB_SIDE:
                self._thumbs[path] = QPixmap.fromImage(qi)
                while len(self._thumbs) > 150:
                    self._thumbs.popitem(last=False)
            else:
                self._large[path] = QPixmap.fromImage(qi)
                while len(self._large) > 3:
                    self._large.popitem(last=False)

    # ── input fallback: mouse / keyboard ─────────────────────────────────────────────
    def keyPressEvent(self, e):
        k, sp = e.key(), self.space
        if k == Qt.Key.Key_Escape:
            if sp.opened is not None:
                sp.back()
            else:
                self.hide()
        elif k == Qt.Key.Key_Backspace:
            sp.back()
        elif k == Qt.Key.Key_Home:
            sp.go_root()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            sp.key_arrow(-1)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            sp.key_arrow(1)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            sp._press("v_plus", time.time())
        elif k == Qt.Key.Key_Minus:
            sp._press("v_minus", time.time())
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), True)
            if self.space.close_requested:
                self.hide()
        elif e.button() == Qt.MouseButton.RightButton:
            self.space.back()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), True)
        else:
            self.space.hover_at(e.position().x(), e.position().y())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), False)
            self.space.visible[0] = False

    def wheelEvent(self, e):
        self.space.wheel(e.angleDelta().y(), e.position().x(), e.position().y())

    def leaveEvent(self, e):
        self.space.mouse_hover = None
        super().leaveEvent(e)

    # ── drawing: backdrop ────────────────────────────────────────────────────────────
    def _background(self) -> QPixmap:
        W, H = self.width(), self.height()
        if self._bg is None or self._bg.width() != W or self._bg.height() != H:
            bg = QPixmap(W, H)
            bg.fill(Qt.GlobalColor.transparent)
            p = QPainter(bg)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            g = QRadialGradient(QPointF(W / 2, H * 0.55), max(W, H) * 0.8)
            g.setColorAt(0, QColor(10, 24, 46, 222))
            g.setColorAt(1, QColor(2, 4, 12, 242))
            p.fillRect(QRectF(0, 0, W, H), QBrush(g))
            p.setPen(Qt.PenStyle.NoPen)                                       # faint dot grid
            p.setBrush(QColor(110, 231, 255, 22))
            for x in range(40, W, 48):
                for y in range(40, H, 48):
                    p.drawEllipse(QPointF(x, y), 1.1, 1.1)
            top = QLinearGradient(0, 0, 0, 130)                                # top and bottom bars sit on a darker band
            top.setColorAt(0, QColor(0, 6, 16, 190))
            top.setColorAt(1, QColor(0, 6, 16, 0))
            p.fillRect(QRectF(0, 0, W, 130), QBrush(top))
            bot = QLinearGradient(0, H - 150, 0, H)
            bot.setColorAt(0, QColor(0, 6, 16, 0))
            bot.setColorAt(1, QColor(0, 6, 16, 190))
            p.fillRect(QRectF(0, H - 150, W, 150), QBrush(bot))
            p.end()
            self._bg = bg
        return self._bg

    def paintEvent(self, _):
        sp = self.space
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        p.drawPixmap(0, 0, self._background())

        op = sp.opened
        dim = max((c.k for c in sp.cards), default=0.0)
        for c in sorted(sp.cards, key=lambda c: (c.open, c.k, c.held, c.lift)):
            if c.open or c.k > 0.02:
                p.fillRect(QRectF(0, 0, W, H), QColor(0, 4, 12, int(170 * dim)))       # dark scrim behind the open card
                dim = 0.0
            self._draw_card(p, c, faded=op is not None and not c.open and c.k < 0.02)
        if sp.empty:
            p.setFont(QFont("Segoe UI", 16))
            p.setPen(QColor(C.TEXT_DIM))
            p.drawText(QRectF(0, H / 2 - 20, W, 40), _AL.AlignCenter, "This folder is empty")
        self._draw_topbar(p, W)
        for b in sp.buttons:
            self._draw_button(p, b)
        if sp.pages > 1 and op is None:
            p.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
            p.setPen(QColor(C.TEXT_MED))
            p.drawText(QRectF(W / 2 - 70, H - 112, 140, 52), _AL.AlignCenter, f"Page {sp.page + 1} / {sp.pages}")
        t = sp.toast
        p.setFont(QFont("Segoe UI", 11))
        if t:
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(t) + 44
            r = QRectF((W - tw) / 2, H - 172, tw, 38)
            p.setBrush(QColor(10, 24, 46, 230))
            p.setPen(QPen(QColor(C.PRI), 1))
            p.drawRoundedRect(r, 19, 19)
            p.setPen(QColor(C.TEXT))
            p.drawText(r, _AL.AlignCenter, t)
        p.setFont(QFont("Segoe UI", 10))
        p.setPen(QColor(C.TEXT_DIM))
        p.drawText(QRectF(0, H - 50, W, 30), _AL.AlignHCenter | _AL.AlignVCenter, sp.hint + "      ·      Esc / ✕ to leave")
        for i, h in enumerate(sp.hands):
            if sp.visible[i] and h.pts:
                self._draw_hand(p, h)

    # ── top bar ──────────────────────────────────────────────────────────────────────
    def _draw_topbar(self, p: QPainter, W: int):
        sp = self.space
        left = 40 + 3 * (76 + 12) + 14
        right = min(b["x"] for b in sp.buttons if b["id"] in ("arrange", "sort", "close")) - 18
        r = QRectF(left, 30, max(100, right - left), 34)
        p.setFont(QFont("Segoe UI", 15, QFont.Weight.DemiBold))
        p.setPen(QColor(C.TEXT))
        fm = QFontMetrics(p.font())
        p.drawText(r, _AL.AlignLeft | _AL.AlignVCenter, fm.elidedText(sp.crumb, Qt.TextElideMode.ElideLeft, int(r.width())))
        p.setFont(QFont("Segoe UI", 10))
        p.setPen(QColor(C.TEXT_DIM))
        p.drawText(QRectF(left, 64, r.width(), 24), _AL.AlignLeft | _AL.AlignVCenter, sp.summary)

    # ── buttons ──────────────────────────────────────────────────────────────────────
    def _draw_button(self, p: QPainter, b: dict):
        sp = self.space
        r = QRectF(b["x"], b["y"], b["w"], b["h"])
        hot = sp.hover_btn == b["id"] and b["on"]
        age = time.time() - sp.flash.get(b["id"], 0.0)
        pulse = max(0.0, 1.0 - age / 0.35)
        pri = QColor(C.PRI)
        a = 1.0 if b["on"] else 0.32
        fill = QColor(150, 210, 255, int((26 + 44 * hot + 90 * pulse) * (1 if b["on"] else 0.6)))
        p.setBrush(fill)
        edge = QColor(pri)
        edge.setAlpha(int((130 + 110 * hot) * a))
        p.setPen(QPen(edge, 1.6 if hot else 1.1))
        rr = QRectF(r).adjusted(-3 * pulse, -3 * pulse, 3 * pulse, 3 * pulse)
        p.drawRoundedRect(rr, 14, 14)
        col = QColor(C.TEXT if b["on"] else C.TEXT_DIM)
        col.setAlpha(int(255 * a))
        icon_rect = QRectF(r.center().x() - 11 - (22 if b["label"] else 0), r.center().y() - 11, 22, 22)
        if not b["label"]:
            icon_rect = QRectF(r.center().x() - 11, r.center().y() - 11, 22, 22)
        self._icon(p, {"v_prev": "left", "v_next": "right", "pg_prev": "left", "pg_next": "right", "v_plus": "plus",
                       "v_minus": "minus", "v_open": "ext", "v_close": "close", "close": "close", "home": "home", "up": "up",
                       "explorer": "folder", "sort": "sort", "arrange": "grid"}[b["id"]], icon_rect, col)
        if b["label"]:
            p.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
            p.setPen(col)
            p.drawText(QRectF(r.left() + 46, r.top(), r.width() - 52, r.height()), _AL.AlignLeft | _AL.AlignVCenter, b["label"])

    @staticmethod
    def _icon(p: QPainter, kind: str, r: QRectF, col: QColor):
        pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        cx, cy = r.center().x(), r.center().y()
        L = lambda a, b, c, d: p.drawLine(QPointF(a, b), QPointF(c, d))       # noqa: E731
        if kind == "close":
            L(x + 3, y + 3, x + w - 3, y + h - 3)
            L(x + 3, y + h - 3, x + w - 3, y + 3)
        elif kind in ("left", "right"):
            s = -1 if kind == "left" else 1
            L(cx - 4 * s, y + 2, cx + 4 * s, cy)
            L(cx + 4 * s, cy, cx - 4 * s, y + h - 2)
        elif kind == "plus":
            L(x + 2, cy, x + w - 2, cy)
            L(cx, y + 2, cx, y + h - 2)
        elif kind == "minus":
            L(x + 2, cy, x + w - 2, cy)
        elif kind == "up":
            L(cx, y + h - 2, cx, y + 3)
            L(cx - 6, y + 9, cx, y + 3)
            L(cx + 6, y + 9, cx, y + 3)
        elif kind == "home":
            path = QPainterPath()
            path.moveTo(x + 1, cy)
            path.lineTo(cx, y + 2)
            path.lineTo(x + w - 1, cy)
            p.drawPath(path)
            p.drawRect(QRectF(x + 4, cy, w - 8, h / 2 - 2))
        elif kind == "ext":
            p.drawRect(QRectF(x + 2, y + 6, w - 8, h - 8))
            L(cx - 1, cy + 1, x + w - 2, y + 2)
            L(x + w - 9, y + 2, x + w - 2, y + 2)
            L(x + w - 2, y + 2, x + w - 2, y + 9)
        elif kind == "folder":
            p.drawRoundedRect(QRectF(x + 1, y + 5, w - 2, h - 8), 3, 3)
            L(x + 2, y + 5, x + 6, y + 2)
            L(x + 6, y + 2, x + 11, y + 2)
        elif kind == "sort":
            for i, ln in enumerate((w - 2, w - 8, w - 14)):
                L(x + 1, y + 4 + i * 7, x + 1 + ln, y + 4 + i * 7)
        elif kind == "grid":
            for i in range(2):
                for j in range(2):
                    p.drawRoundedRect(QRectF(x + 2 + i * 10, y + 2 + j * 10, 8, 8), 2, 2)

    # ── cards ────────────────────────────────────────────────────────────────────────
    def _draw_card(self, p: QPainter, c: Card, faded: bool = False):
        if c.a < 0.01:
            return
        w, h = c.w, c.h
        appear = c.a
        sc = (0.82 + 0.18 * appear) * (1.0 + 0.07 * c.lift + 0.04 * c.hov)
        kind = c.data.get("kind", "file")
        accent = QColor({"drive": C.PRI, "folder": C.AMBER, "image": C.PRI, "text": C.ACC}.get(kind, C.TEXT_MED))
        p.save()
        p.setOpacity(appear * (0.35 if faded else 1.0))
        p.translate(c.x, c.y)
        p.rotate(math.degrees(c.angle))
        p.scale(sc, sc)
        rect = QRectF(-w / 2, -h / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(2):                                              # soft shadow
            p.setBrush(QColor(0, 0, 0, 34 + int(20 * c.lift)))
            p.drawRoundedRect(rect.adjusted(-k * 5, -k * 5 + 8 + 8 * c.lift, k * 5, k * 5 + 8 + 8 * c.lift), 18 + k * 4, 18 + k * 4)
        gr = QLinearGradient(rect.topLeft(), rect.bottomRight())            # glass body
        gr.setColorAt(0, QColor(150, 210, 255, 66 + int(40 * c.hov) if not c.open else 128))
        gr.setColorAt(1, QColor(40, 90, 160, 44 if not c.open else 120))
        p.setBrush(gr)
        edge = QColor(C.GREEN if c.held else accent)
        edge.setAlpha(240 if c.held else int(130 + 110 * c.hov))
        p.setPen(QPen(edge, 1.8 if (c.held or c.hov > 0.5) else 1.2))
        p.drawRoundedRect(rect, 16, 16)
        hl = QPainterPath()
        hl.addRoundedRect(rect.adjusted(2, 2, -2, -h * 0.55), 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawPath(hl)
        if kind == "image":
            self._card_image(p, c, rect)
        elif kind == "text":
            self._card_text(p, c, rect)
        elif kind in ("drive", "folder"):
            self._card_place(p, c, rect, accent)
        else:
            self._card_file(p, c, rect)
        p.restore()

    @staticmethod
    def _title(p: QPainter, rect: QRectF, text: str, size: int = 11, color: str | None = None, align=_AL.AlignLeft):
        f = QFont("Segoe UI", size, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(color or C.TEXT))
        el = QFontMetrics(f).elidedText(text, Qt.TextElideMode.ElideMiddle, int(rect.width()))
        p.drawText(rect, align | _AL.AlignVCenter, el)

    # drives and folders
    def _card_place(self, p: QPainter, c: Card, rect: QRectF, accent: QColor):
        d = c.data
        inner = rect.adjusted(16, 12, -16, -12)
        cx = inner.left() + 46
        cy = inner.top() + 42
        if d["kind"] == "folder":
            tab = QPainterPath()
            tab.addRoundedRect(QRectF(cx - 32, cy - 26, 30, 14), 4, 4)
            body = QPainterPath()
            body.addRoundedRect(QRectF(cx - 32, cy - 18, 64, 46), 7, 7)
            g = QLinearGradient(cx, cy - 18, cx, cy + 28)
            top = QColor(accent)
            top.setAlpha(235)
            bot = QColor(accent).darker(150)
            bot.setAlpha(235)
            g.setColorAt(0, top)
            g.setColorAt(1, bot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(accent).darker(135))
            p.drawPath(tab)
            p.setBrush(g)
            p.drawPath(body)
        else:
            body = QRectF(cx - 36, cy - 16, 72, 36)
            g = QLinearGradient(body.topLeft(), body.bottomLeft())
            g.setColorAt(0, QColor(190, 230, 255, 230))
            g.setColorAt(1, QColor(80, 140, 200, 230))
            p.setPen(QPen(QColor(C.PRI), 1.4))
            p.setBrush(g)
            p.drawRoundedRect(body, 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C.GREEN))
            p.drawEllipse(QPointF(body.right() - 10, body.bottom() - 9), 3.2, 3.2)
            p.setBrush(QColor(20, 50, 90, 150))
            p.drawRoundedRect(QRectF(body.left() + 8, body.bottom() - 11, 26, 4), 2, 2)
        tx = inner.left() + 100
        if d["kind"] == "drive":
            self._title(p, QRectF(tx - 10, inner.top() + 14, inner.right() - tx + 10, 24), d["title"], 11)
        else:
            self._title(p, QRectF(inner.left(), inner.bottom() - 52, inner.width(), 26), d["title"], 12)
        p.setFont(QFont("Segoe UI", 9))
        p.setPen(QColor(C.TEXT_DIM))
        if d["kind"] == "drive":
            bar = QRectF(inner.left(), inner.bottom() - 34, inner.width(), 8)
            p.setBrush(QColor(255, 255, 255, 30))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bar, 4, 4)
            used = max(0.0, min(1.0, d.get("used", 0.0)))
            p.setBrush(QColor(C.RED if used > 0.9 else C.AMBER if used > 0.75 else C.PRI))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(8.0, bar.width() * used), bar.height()), 4, 4)
            p.setPen(QColor(C.TEXT_DIM))
            p.drawText(QRectF(inner.left(), inner.bottom() - 22, inner.width(), 20), _AL.AlignLeft | _AL.AlignVCenter, d.get("sub", ""))
        else:
            p.drawText(QRectF(inner.left(), inner.bottom() - 26, inner.width(), 20), _AL.AlignLeft | _AL.AlignVCenter, d.get("sub", ""))

    # generic files (zip, pdf, exe …)
    def _card_file(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        if c.k > 0.5:
            self._open_file(p, c, rect)
            return
        inner = rect.adjusted(16, 12, -16, -12)
        pg = QRectF(inner.left() + 6, inner.top() + 2, 40, 52)
        path = QPainterPath()
        path.moveTo(pg.left(), pg.top())
        path.lineTo(pg.right() - 12, pg.top())
        path.lineTo(pg.right(), pg.top() + 12)
        path.lineTo(pg.right(), pg.bottom())
        path.lineTo(pg.left(), pg.bottom())
        path.closeSubpath()
        p.setPen(QPen(QColor(C.TEXT_MED), 1.3))
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawPath(path)
        ext = (d.get("_ext") or "").lstrip(".").upper()[:4] or "FILE"
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.setPen(QColor(C.PRI))
        p.drawText(QRectF(pg.left(), pg.top() + 22, pg.width(), 20), _AL.AlignCenter, ext)
        self._title(p, QRectF(inner.left(), inner.bottom() - 52, inner.width(), 26), d["title"], 11)
        p.setFont(QFont("Segoe UI", 9))
        p.setPen(QColor(C.TEXT_DIM))
        p.drawText(QRectF(inner.left(), inner.bottom() - 26, inner.width(), 20), _AL.AlignLeft | _AL.AlignVCenter, d.get("sub", ""))

    def _open_file(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        inner = rect.adjusted(34, 28, -34, -28)
        self._title(p, QRectF(inner.left(), inner.top(), inner.width(), 44), d["title"], 18, C.PRI)
        p.setPen(QPen(QColor(C.PRI), 1))
        p.drawLine(QPointF(inner.left(), inner.top() + 50), QPointF(inner.left() + 50, inner.top() + 50))
        rows = [("Type", (d.get("_ext") or "").lstrip(".").upper() or "File"), ("Size", human_size(d.get("_sz", 0))),
                ("Modified", d.get("date", "")), ("Location", d.get("path", ""))]
        p.setFont(QFont("Segoe UI", 12))
        for i, (k, v) in enumerate(rows):
            y = inner.top() + 66 + i * 34
            p.setPen(QColor(C.TEXT_DIM))
            p.drawText(QRectF(inner.left(), y, 100, 28), _AL.AlignLeft | _AL.AlignVCenter, k)
            p.setPen(QColor(C.TEXT))
            fm = QFontMetrics(p.font())
            p.drawText(QRectF(inner.left() + 100, y, inner.width() - 100, 28), _AL.AlignLeft | _AL.AlignVCenter,
                       fm.elidedText(v, Qt.TextElideMode.ElideMiddle, int(inner.width() - 100)))
        from core.hand_space import can_launch
        if not can_launch(d):
            p.setFont(QFont("Segoe UI", 10))
            p.setPen(QColor(C.AMBER))
            p.drawText(QRectF(inner.left(), inner.bottom() - 30, inner.width(), 26), _AL.AlignLeft | _AL.AlignVCenter,
                       "Programs and scripts are never started from a gesture.")

    # notes
    def _card_text(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        mono = bool(d.get("mono"))
        if c.k > 0.5:
            inner = rect.adjusted(34, 26, -34, -26)
            self._title(p, QRectF(inner.left(), inner.top(), inner.width(), 44), d["title"], 18, C.PRI)
            p.setPen(QPen(QColor(C.PRI), 1))
            p.drawLine(QPointF(inner.left(), inner.top() + 48), QPointF(inner.left() + 50, inner.top() + 48))
            view = QRectF(inner.left(), inner.top() + 60, inner.width(), inner.height() - 60)
            f = QFont("Cascadia Mono" if mono else "Segoe UI", 11 if mono else 13)
            p.setFont(f)
            p.setPen(QColor(C.TEXT))
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if mono else QTextOption.WrapMode.WordWrap)
            text = d.get("full") or d.get("text") or ""
            full_h = QFontMetrics(f).boundingRect(QRectF(0, 0, view.width() - 14, 10 ** 6).toRect(),
                                                  int(Qt.TextFlag.TextWordWrap), text).height()
            c.scroll = max(0.0, min(c.scroll, max(0.0, full_h - view.height() + 10)))
            p.save()
            p.setClipRect(view)
            p.drawText(QRectF(view.left(), view.top() - c.scroll, view.width() - 14, full_h + 40), text, opt)
            p.restore()
            if full_h > view.height():                                    # scroll bar
                tr = QRectF(view.right() - 5, view.top(), 4, view.height())
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 30))
                p.drawRoundedRect(tr, 2, 2)
                th = max(30.0, view.height() * view.height() / full_h)
                ty = tr.top() + (tr.height() - th) * (c.scroll / max(1.0, full_h - view.height()))
                p.setBrush(QColor(C.PRI))
                p.drawRoundedRect(QRectF(tr.left(), ty, 4, th), 2, 2)
            return
        inner = rect.adjusted(14, 10, -14, -10)
        self._title(p, QRectF(inner.left(), inner.top(), inner.width(), 26), d["title"], 11, C.PRI)
        p.setPen(QPen(QColor(C.PRI), 1))
        p.drawLine(QPointF(inner.left(), inner.top() + 29), QPointF(inner.left() + 34, inner.top() + 29))
        p.setFont(QFont("Cascadia Mono" if mono else "Segoe UI", 8 if mono else 9))
        p.setPen(QColor(C.TEXT))
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        p.save()
        p.setClipRect(QRectF(inner.left(), inner.top() + 34, inner.width(), inner.height() - 34))
        p.drawText(QRectF(inner.left(), inner.top() + 34, inner.width(), inner.height() - 34), d.get("text", "") or "(empty)", opt)
        p.restore()

    # pictures
    def _card_image(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        path = d["image"]
        big = self._large.get(path) if c.k > 0.3 else None
        px = big or self._thumbs.get(path)
        clip = QPainterPath()
        clip.addRoundedRect(rect.adjusted(4, 4, -4, -4), 12, 12)
        p.save()
        p.setClipPath(clip)
        tr = rect.adjusted(4, 4, -4, -4)
        if px is None:
            p.setBrush(QColor(255, 255, 255, 14 + int(10 * math.sin(time.time() * 4))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(tr)
            if path in self._failed:
                p.setPen(QColor(C.TEXT_DIM))
                p.setFont(QFont("Segoe UI", 10))
                p.drawText(tr, _AL.AlignCenter, "Can't show this picture")
        else:
            iw, ih = px.width(), px.height()
            if c.k > 0.3:                                                     # opened: the whole picture, zoomable
                z = max(1.0, c.zoom)
                sw, sh = iw / z, ih / z
                sx = max(0.0, min(iw - sw, c.vcx * iw - sw / 2))
                sy = max(0.0, min(ih - sh, c.vcy * ih - sh / 2))
                p.drawPixmap(tr, px, QRectF(sx, sy, sw, sh))
            else:                                                             # small card: fill it, crop the overflow
                k = max(tr.width() / iw, tr.height() / ih)
                sw, sh = tr.width() / k, tr.height() / k
                p.drawPixmap(tr, px, QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh))
        strip = QLinearGradient(0, tr.bottom() - 46, 0, tr.bottom())
        strip.setColorAt(0, QColor(0, 0, 0, 0))
        strip.setColorAt(1, QColor(0, 0, 0, 190))
        p.fillRect(QRectF(tr.left(), tr.bottom() - 46, tr.width(), 46), QBrush(strip))
        p.restore()
        title = d["title"] if c.k < 0.5 else d["title"] + (f"   ·   {d['dims'][0]}×{d['dims'][1]}" if d.get("dims") else "")
        self._title(p, QRectF(rect.left() + 16, rect.bottom() - 34, rect.width() - 100, 26), title, 10 if c.k < 0.5 else 12, "#ffffff")
        if c.k > 0.5 and c.zoom > 1.01:
            p.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(QRectF(rect.right() - 100, rect.bottom() - 34, 84, 26), _AL.AlignRight | _AL.AlignVCenter, f"{int(c.zoom * 100)}%")

    # ── hands ────────────────────────────────────────────────────────────────────────
    def _skeleton(self) -> bool:
        if time.time() - getattr(self, "_skel_t", 0.0) > 1.0:
            self._skel_t = time.time()
            try:
                from core import hand_cursor
                self._skel = hand_cursor.show_skeleton()
            except Exception:
                self._skel = False
        return getattr(self, "_skel", False)

    def _draw_hand(self, p: QPainter, h):
        pts = [QPointF(x, y) for x, y in h.pts]
        col = QColor(C.GREEN if h.pinching else C.AMBER if h.claw else C.RED if h.fist else C.PRI)
        if self._skeleton():                                   # optional thin outline, never joint dots
            path = QPainterPath()
            for a, b in BONES:
                path.moveTo(pts[a])
                path.lineTo(pts[b])
            c = QColor(col)
            c.setAlpha(70)
            p.setPen(QPen(c, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        mid = QPointF(h.pos[0], h.pos[1])
        ring = QColor(col)
        ring.setAlpha(230)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ring, 2))
        p.drawEllipse(mid, 10 if h.pinching else 20, 10 if h.pinching else 20)
        if h.claw:
            p.drawEllipse(QPointF(*h.palm), 120, 120)
        if h.fist_prog > 0.05:                                 # fist held: a ring fills up, then "back"
            pc = QPointF(*h.palm)
            p.setPen(QPen(QColor(C.AMBER), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(pc.x() - 46, pc.y() - 46, 92, 92), 90 * 16, int(-360 * 16 * h.fist_prog))
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            p.setPen(QColor(C.AMBER))
            p.drawText(QRectF(pc.x() - 50, pc.y() + 52, 100, 22), _AL.AlignCenter, "Back")
