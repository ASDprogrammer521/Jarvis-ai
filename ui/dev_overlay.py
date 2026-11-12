"""Developer Productivity Overlay — Alt+Space pops up a holographic panel: live CPU/RAM/GPU, git, clipboard error explainer.

Big, well-spaced buttons so it can be driven with the hand cursor (pinch = click) as comfortably as with a mouse.
"""
from __future__ import annotations

import math
import threading

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                             QVBoxLayout, QWidget)

from core import dev_tools
from ui.theme import C, rgba

W, H = 560, 640
_CUBE = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
_EDGES = [(i, j) for i in range(8) for j in range(i + 1, 8) if sum(a != b for a, b in zip(_CUBE[i], _CUBE[j])) == 1]


class DevOverlay(QWidget):
    _out_sig = pyqtSignal(str)

    def __init__(self, win):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.win = win
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.stats = {"cpu": 0.0, "ram": 0.0, "gpu": None, "ram_used_gb": 0.0, "ram_total_gb": 0.0}
        self.branch, self.dirty = "", 0
        self._phase = 0.0
        self._drag = None
        self._build()
        self._out_sig.connect(self._show_out)
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._frame)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._refresh)

    # ── layout ───────────────────────────────────────────────────────────────────
    def _btn(self, text: str, slot, accent: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setMinimumHeight(40)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        col = C.PRI if accent else C.BORDER_B
        b.setStyleSheet(
            f"QPushButton{{background:{rgba(C.PRI, .16 if accent else .06)};color:{C.TEXT};border:1px solid {col};"
            f"border-radius:10px;font-weight:600;padding:0 10px;}}"
            f"QPushButton:hover{{background:{rgba(C.PRI, .32)};border-color:{C.PRI};}}"
            f"QPushButton:pressed{{background:{rgba(C.GREEN, .35)};}}")
        b.clicked.connect(slot)
        return b

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.addSpacing(70)                       # room for the rotating hologram
        titles = QVBoxLayout()
        t = QLabel("DEV OVERLAY")
        t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        t.setStyleSheet(f"color:{C.PRI};letter-spacing:3px;background:transparent;")
        self.repo_lbl = QLabel("")
        self.repo_lbl.setStyleSheet(f"color:{C.TEXT_MED};background:transparent;")
        titles.addWidget(t)
        titles.addWidget(self.repo_lbl)
        head.addLayout(titles, 1)
        close = self._btn("✕", self.hide)
        close.setFixedSize(40, 40)
        head.addWidget(close)
        lay.addLayout(head)

        lay.addSpacing(86)                        # gauges are painted in this band

        row = QHBoxLayout()
        row.addWidget(self._btn("Repo…", self._pick_repo))
        row.addWidget(self._btn("Status", lambda: self._git("status"), True))
        row.addWidget(self._btn("Diff", lambda: self._git("diff")))
        row.addWidget(self._btn("Log", lambda: self._git("log")))
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self._btn("Fetch", lambda: self._git("fetch")))
        row.addWidget(self._btn("Pull", lambda: self._git("pull", confirm=True)))
        row.addWidget(self._btn("Push", lambda: self._git("push", confirm=True)))
        row.addWidget(self._btn("Stash", lambda: self._git("stash", confirm=True)))
        lay.addLayout(row)

        row = QHBoxLayout()
        self.msg = QLineEdit()
        self.msg.setPlaceholderText("commit message…")
        self.msg.setMinimumHeight(40)
        self.msg.setStyleSheet(f"QLineEdit{{background:{rgba(C.BG, .6)};color:{C.TEXT};border:1px solid {C.BORDER_B};"
                               f"border-radius:10px;padding:0 10px;}}")
        self.msg.returnPressed.connect(self._commit)
        row.addWidget(self.msg, 1)
        row.addWidget(self._btn("Commit all", self._commit))
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._btn("🧠 Explain clipboard error", lambda: self._ask("error"), True))
        row.addWidget(self._btn("🔍 Review clipboard code", lambda: self._ask("code")))
        lay.addLayout(row)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QFont("Consolas", 9))
        self.out.setStyleSheet(f"QPlainTextEdit{{background:{rgba(C.BG, .72)};color:{C.GREEN};border:1px solid {C.BORDER};"
                               f"border-radius:10px;padding:8px;}}")
        self.out.setPlainText("Ready. Esc or ✕ closes · Alt+Space toggles.")
        lay.addWidget(self.out, 1)

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def show_overlay(self):
        scr = (QGuiApplication.screenAt(self.cursor().pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        self.move(scr.center().x() - W // 2, scr.center().y() - H // 2)
        self._refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self._anim.start(33)
        self._poll.start(1000)

    def hide(self):                               # noqa: A003
        self._anim.stop()
        self._poll.stop()
        super().hide()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    # ── data ─────────────────────────────────────────────────────────────────────
    def _refresh(self):
        self.stats = dev_tools.system_stats()
        repo = dev_tools.get_repo()
        self.repo_lbl.setText(f"{repo.name}" if repo else "no repository — press Repo…")
        threading.Thread(target=self._branch_worker, daemon=True).start()

    def _branch_worker(self):
        try:
            self.branch, self.dirty = dev_tools.branch_info()
        except Exception:
            pass

    def _show_out(self, text: str):
        self.out.setPlainText(text)

    def _run_async(self, fn):
        def work():
            try:
                self._out_sig.emit(fn())
            except Exception as e:
                self._out_sig.emit(f"error: {e}")
        self.out.setPlainText("…")
        threading.Thread(target=work, daemon=True).start()

    def _pick_repo(self):
        start = str(dev_tools.get_repo() or "")
        path = QFileDialog.getExistingDirectory(self, "Choose a git repository", start)
        if path:
            self.out.setPlainText(dev_tools.set_repo(path))
            self._refresh()

    def _confirm(self, what: str) -> bool:
        return QMessageBox.question(self, "Confirm", f"Run “{what}” in {dev_tools.get_repo() or 'the repository'}?") \
            == QMessageBox.StandardButton.Yes

    def _git(self, cmd: str, confirm: bool = False):
        if confirm and not self._confirm("git " + cmd):
            return
        self._run_async(lambda: dev_tools.run_git(cmd))

    def _commit(self):
        msg = self.msg.text().strip()
        if not msg:
            self.out.setPlainText("Type a commit message first.")
            return
        if self._confirm(f"git add -A && git commit -m \"{msg[:40]}\""):
            self.msg.clear()
            self._run_async(lambda: dev_tools.run_git("commit", msg))

    def _ask(self, kind: str):
        text = dev_tools.clipboard_text()
        if not text.strip():
            self.out.setPlainText("The clipboard is empty — copy the error or code first.")
            return
        prompt = ("[DevOverlay] Explain this terminal/compiler error in plain words: the cause and the most likely fix, briefly:\n"
                  if kind == "error" else
                  "[DevOverlay] Review this code snippet: say what it does and name the top issues, briefly:\n") + text
        cb = getattr(self.win, "on_text_command", None)
        if cb is None:
            self.out.setPlainText("Jarvis isn't connected yet.")
            return
        cb(prompt)
        self.out.setPlainText("Sent to Jarvis — listen for the answer.\n\n" + text[:600])

    # ── hologram painting ────────────────────────────────────────────────────────
    def _frame(self):
        self._phase = (self._phase + 0.035) % (2 * math.pi)
        self.update()

    def _gauge(self, p: QPainter, cx: float, cy: float, label: str, val, sub: str):
        r = 31
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(C.BORDER_B), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 225 * 16, -270 * 16)
        if val is not None:
            col = QColor(C.GREEN if val < 60 else C.AMBER if val < 85 else C.RED)
            p.setPen(QPen(col, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, 225 * 16, int(-270 * 16 * min(100, val) / 100))
        p.setPen(QColor(C.TEXT))
        f = QFont("Segoe UI", 11, QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "—" if val is None else f"{val:.0f}")
        f.setPointSize(8)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(C.PRI))
        p.drawText(QRectF(cx - 45, cy + r - 6, 90, 16), Qt.AlignmentFlag.AlignCenter, label)
        p.setPen(QColor(C.TEXT_DIM))
        p.drawText(QRectF(cx - 45, cy + r + 8, 90, 14), Qt.AlignmentFlag.AlignCenter, sub)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, W - 2, H - 2)
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor(8, 14, 32, 232))
        g.setColorAt(1, QColor(4, 6, 18, 238))
        p.setBrush(g)
        glow = QColor(C.PRI)
        for w, a in ((7, 28), (3.5, 70), (1.4, 215)):                 # layered edge glow
            glow.setAlpha(a)
            p.setPen(QPen(glow, w))
            p.drawRoundedRect(rect, 18, 18)
        p.setPen(QPen(QColor(110, 231, 255, 14), 1))                  # scanlines
        for y in range(6, H, 4):
            p.drawLine(10, y, W - 10, y)

        # rotating wireframe cube (the "hologram")
        cx, cy, s = 56.0, 52.0, 17.0
        a, b = self._phase, self._phase * 0.63
        pts = []
        for x, y, z in _CUBE:
            x1, z1 = x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)
            y1, z2 = y * math.cos(b) - z1 * math.sin(b), y * math.sin(b) + z1 * math.cos(b)
            k = 3.2 / (3.2 - z2 * 0.5)
            pts.append(QPointF(cx + x1 * s * k, cy + y1 * s * k))
        p.setPen(QPen(QColor(C.PRI), 1.4))
        for i, j in _EDGES:
            p.drawLine(pts[i], pts[j])
        p.setPen(QPen(QColor(C.ACC), 1))
        p.drawEllipse(QPointF(cx, cy), s * 1.9, s * 0.6 + 4 * math.sin(a))

        # gauges + branch line
        s_ = self.stats
        y0 = 148
        self._gauge(p, 90, y0, "CPU", s_["cpu"], "")
        self._gauge(p, 280, y0, "RAM", s_["ram"], f"{s_['ram_used_gb']:.1f}/{s_['ram_total_gb']:.0f} GB")
        self._gauge(p, 470, y0, "GPU", s_["gpu"], "" if s_["gpu"] is not None else "n/a")
        if self.branch:
            p.setPen(QColor(C.TEXT_MED))
            p.setFont(QFont("Consolas", 9))
            txt = f"⎇ {self.branch}   {'● ' + str(self.dirty) + ' changed' if self.dirty else '✔ clean'}"
            p.drawText(QRectF(110, 52, W - 180, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, txt)

    # drag by the header
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 100:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _):
        self._drag = None
