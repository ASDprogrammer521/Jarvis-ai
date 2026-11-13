"""Hand Space — a floating, hand-controlled file workspace (camera + MediaPipe).

It starts on "This PC": your drives (C: first) float as glass cards. Open a drive or a folder and its contents float
in the air — sub-folders, pictures, notes and every other file — so you can walk through the whole disk with bare hands.

    pinch a card .......... grab it · move your hand to carry it
    quick pinch (tap) ..... folder / drive: go in · picture: open it BIG · note / file: open it
    tap the open card ..... close it (or tap the dark background)
    let go while moving ... throw it — it flies, spins and bounces off the screen edges
    claw (bent fingers) ... every card is pulled towards your palm; open the hand to release them
    fist, hold 1 s ........ back: close the open card, or go up one folder
    two hands pinching .... zoom the open picture · one hand drags to pan / scroll
    buttons ............... Home · Up · Explorer · Sort · Arrange · pages · prev / next · + / − · Open · Close · ✕

Keyboard / mouse also work: Esc, Backspace, ← →, PageUp/PageDown, wheel, right-click = back.

This module is pure logic (no Qt) so it can be tested without a camera; ui/hand_space.py draws it.
"""
from __future__ import annotations

import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

CARD_W, CARD_H = 220, 150
GAP = 26
TOP_MARGIN, BOTTOM_MARGIN, SIDE_MARGIN = 150, 130, 90      # the card grid lives between the top bar and the bottom bar
BTN_W, BTN_H, BTN_GAP = 76, 52, 12
PINCH_ON, PINCH_OFF, CONFIRM = 0.32, 0.50, 2
GAIN = 1.25                      # camera → screen: the central 80 % of the picture reaches every screen edge
MAX_THROW = 4200.0
TAP_SECONDS, TAP_PIXELS = 0.38, 42
FIST_SECONDS = 1.0
MAX_ENTRIES = 3000
TEXT_BYTES, TEXT_CHARS = 48000, 24000

TEXT_EXT = {".md", ".markdown", ".txt", ".log", ".json", ".csv", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".toml",
            ".xml", ".html", ".htm", ".css", ".js", ".ts", ".py", ".java", ".c", ".cpp", ".h", ".cs", ".sql", ".sh",
            ".bat", ".cmd", ".ps1", ".tex", ".srt"}
PLAIN_EXT = {".md", ".markdown", ".txt", ".log", ".tex", ".srt"}      # shown in the normal font; the rest is code (mono)
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico"}
MODEL_EXT = {".obj", ".stl", ".fbx", ".glb", ".gltf", ".usd", ".usda", ".usdc", ".usdz", ".step", ".stp"}   # 3D models: drawn on the GPU, turned with the hand
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg"}   # played by mpv on the GPU
SEEK_STEP = 10.0                                               # seconds skipped by the video's − / + buttons
# never launched from a gesture: a stray pinch must not start a program
NO_LAUNCH = {".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
             ".lnk", ".reg", ".dll", ".jar", ".hta", ".cpl", ".pif", ".msc", ".sh", ".py", ".pyw", ".appx", ".msix"}
SORTS = ("name", "date", "size", "type")
SORT_LABEL = {"name": "Name", "date": "Date", "size": "Size", "type": "Type"}


# ── formatting ───────────────────────────────────────────────────────────────────────
def human_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" or n >= 100 else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_date(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except (OSError, ValueError, OverflowError):
        return ""


def _nat(s: str) -> list:
    return [int(t) if i % 2 else t for i, t in enumerate(re.split(r"(\d+)", s.lower()))]


def _clean_md(text: str) -> str:
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)            # front matter
    text = re.sub(r"!\[\[.*?\]\]|!\[.*?\]\(.*?\)", "", text)             # embedded images
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)          # [[wiki|links]]
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)                  # [links](url)
    text = re.sub(r"^[#>\-\*\s]+", "", text, flags=re.M)
    text = re.sub(r"[*_`~]{1,3}", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ── the file system as cards ─────────────────────────────────────────────────────────
def _drive_letters() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetErrorMode(1)                                   # no "insert a disk" pop-ups for empty card readers
        mask = k.GetLogicalDrives()
        out = []
        for i in range(26):
            if mask & (1 << i):
                root = f"{chr(65 + i)}:\\"
                if k.GetDriveTypeW(root) in (2, 3):          # removable + fixed only: a dead network drive would freeze us
                    out.append(root)
        out.sort(key=lambda r: (r[0] != "C", r))
        return out
    except Exception:
        return []


def _volume_label(root: str) -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
        return buf.value if ok else ""
    except Exception:
        return ""


def _drive_entry(root: str, title: str) -> dict:
    sub, used = "Not ready", 0.0
    try:
        u = shutil.disk_usage(root)
        used = u.used / u.total if u.total else 0.0
        sub = f"{human_size(u.free)} free of {human_size(u.total)}"
    except OSError:
        pass
    return {"kind": "drive", "title": title, "sub": sub, "used": used, "path": root, "image": None, "text": "",
            "_dir": True, "_mt": 0.0, "_sz": 0, "_ext": ""}


def list_roots(pinned: str | None = None) -> list[dict]:
    """'This PC': every drive (C: first) and, if you pinned one on the Hand Space page, that folder."""
    items = []
    for root in _drive_letters():
        items.append(_drive_entry(root, f"{_volume_label(root) or 'Local Disk'} ({root[0]}:)"))
    if not items:                                           # not Windows (or no drives found): show something useful
        items.append(_drive_entry(os.path.abspath(os.sep), "Root"))
        home = str(Path.home())
        items.append({"kind": "folder", "title": "Home", "sub": "Your folder", "path": home, "image": None, "text": "",
                      "_dir": True, "_mt": 0.0, "_sz": 0, "_ext": ""})
    if pinned and Path(pinned).is_dir():
        items.append({"kind": "folder", "title": Path(pinned).name or str(pinned), "sub": "Pinned folder", "path": str(pinned),
                      "image": None, "text": "", "pinned": True, "_dir": True, "_mt": 0.0, "_sz": 0, "_ext": ""})
    return items


def _sort_key(sort: str):
    if sort == "date":
        return lambda e: (not e["_dir"], -e["_mt"], _nat(e["title"]))
    if sort == "size":
        return lambda e: (not e["_dir"], 0 if e["_dir"] else -e["_sz"], _nat(e["title"]))
    if sort == "type":
        return lambda e: (not e["_dir"], e["_ext"], _nat(e["title"]))
    return lambda e: (not e["_dir"], _nat(e["title"]))


def sort_entries(entries: list[dict], sort: str) -> None:
    entries.sort(key=_sort_key(sort))


def list_dir(path: str | Path, sort: str = "name") -> list[dict]:
    """Everything visible inside a folder. Raises OSError (PermissionError…) if it can't be read."""
    out: list[dict] = []
    with os.scandir(path) as it:
        for de in it:
            if len(out) >= MAX_ENTRIES:
                break
            name = de.name
            if name.startswith("."):
                continue
            try:
                st = de.stat(follow_symlinks=False)
                if getattr(st, "st_file_attributes", 0) & 0x6:          # hidden / system (Windows): $Recycle.Bin, pagefile…
                    continue
                is_dir = de.is_dir()
            except OSError:
                continue
            ext = "" if is_dir else os.path.splitext(name)[1].lower()
            e = {"title": name, "path": de.path, "_dir": is_dir, "_mt": st.st_mtime, "_sz": 0 if is_dir else st.st_size,
                 "_ext": ext, "image": None, "text": ""}
            if is_dir:
                e.update(kind="folder", sub=fmt_date(st.st_mtime))
            else:
                size = human_size(st.st_size)
                label = (ext[1:] or "file").upper()
                if ext in IMG_EXT:
                    e.update(kind="image", image=de.path, sub=f"{label} · {size}")
                elif ext in MODEL_EXT:
                    e.update(kind="model", sub=f"3D · {label} · {size}")
                elif ext in VIDEO_EXT:
                    e.update(kind="video", sub=f"Video · {label} · {size}")
                elif ext in TEXT_EXT:
                    e.update(kind="text", sub=f"{label} · {size}", mono=ext not in PLAIN_EXT)
                else:
                    e.update(kind="file", sub=f"{label} · {size}")
            e["date"] = fmt_date(st.st_mtime)
            out.append(e)
    sort_entries(out, sort)
    return out


def fill_text(e: dict) -> None:
    """Read the start of a note so its card can show a preview (only done for the cards on screen)."""
    if e.get("kind") != "text" or e.get("_filled"):
        return
    e["_filled"] = True
    try:
        with open(e["path"], "rb") as f:
            raw = f.read(TEXT_BYTES)
    except OSError:
        e["kind"] = "file"
        return
    if b"\x00" in raw[:2048]:
        e["kind"] = "file"
        return
    txt = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\t", "    ")
    if e["_ext"] in (".md", ".markdown"):
        txt = _clean_md(txt)
    e["full"] = txt[:TEXT_CHARS]
    e["text"] = "\n".join(txt.strip().splitlines()[:8])[:420]


def load_cards(folder: str | Path | None, limit: int = 40) -> list[dict]:
    """Compatibility helper (used by the Hand Space page preview): the cards of a folder, or the drives."""
    try:
        items = list_dir(folder) if folder and Path(folder).is_dir() else list_roots()
    except OSError:
        items = list_roots()
    for e in items[:limit]:
        fill_text(e)
        if not e.get("text"):
            e["text"] = e.get("sub", "") if not e.get("image") else ""
    return items[:limit]


def can_launch(e: dict) -> bool:
    return e.get("kind") in ("image", "text", "file", "model", "video") and e.get("_ext", "") not in NO_LAUNCH


def open_external(path: str) -> bool:
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)                                    # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


# ── physics objects ──────────────────────────────────────────────────────────────────

# ── file operations (pure functions: copy, move, delete, rename, extract) ────────────────
ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".tar", ".zip", ".7z", ".rar")
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _err(e: BaseException) -> str:
    return (getattr(e, "strerror", None) or str(e) or e.__class__.__name__)[:90]


def is_archive(path) -> bool:
    return str(path).lower().endswith(ARCHIVE_SUFFIXES)


def archive_stem(name: str) -> str:
    low = name.lower()
    for suf in ARCHIVE_SUFFIXES:
        if low.endswith(suf):
            return name[:-len(suf)] or name
    return name


def unique_path(folder, name: str) -> Path:
    """folder/name, or folder/name (2), (3)… when that already exists."""
    folder = Path(folder)
    cand = folder / name
    if not cand.exists():
        return cand
    base = Path(name)
    n = 2
    while True:
        cand = folder / f"{base.stem} ({n}){base.suffix}"
        if not cand.exists():
            return cand
        n += 1


def check_name(name: str) -> str:
    """'' when the name is fine, otherwise what is wrong with it."""
    n = name.strip()
    if not n or n in (".", ".."):
        return "The name can't be empty"
    if _BAD_NAME.search(n):
        return 'A name can\'t contain  \\ / : * ? " < > |'
    if n != n.rstrip(". "):
        return "A name can't end with a dot or a space"
    if n.split(".")[0].lower() in _RESERVED:
        return "Windows reserves that name"
    if len(n) > 200:
        return "That name is too long"
    return ""


def _inside(child: Path, parent: Path) -> bool:
    try:
        c, p = child.resolve(), parent.resolve()
    except OSError:
        return False
    return c == p or p in c.parents


def copy_item(src, dst_dir) -> Path:
    src, dst_dir = Path(src), Path(dst_dir)
    if src.is_dir() and _inside(dst_dir, src):
        raise OSError("Can't copy a folder into itself")
    target = unique_path(dst_dir, src.name)
    if src.is_dir():
        shutil.copytree(src, target)
    else:
        shutil.copy2(src, target)
    return target


def move_item(src, dst_dir) -> Path:
    src, dst_dir = Path(src), Path(dst_dir)
    if src.parent.resolve() == dst_dir.resolve():
        return src                                              # already there
    if src.is_dir() and _inside(dst_dir, src):
        raise OSError("Can't move a folder into itself")
    target = unique_path(dst_dir, src.name)
    shutil.move(str(src), str(target))
    return target


def protected(path) -> bool:
    p = Path(path)
    try:
        r = p.resolve()
    except OSError:
        return True
    if r.parent == r or len(r.parts) <= 1:                      # a drive root
        return True
    home = Path.home().resolve()
    sysdirs = [os.environ.get(k) for k in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
    return r == home or home in r.parents and len(r.parts) - len(home.parts) < 1 or any(d and r == Path(d).resolve() for d in sysdirs)


def recycle(path) -> None:
    """Move to the Recycle Bin (never a permanent delete)."""
    p = Path(path)
    if protected(p):
        raise OSError("This is a protected folder")
    if not p.exists():
        raise OSError("It no longer exists")
    try:
        from send2trash import send2trash                       # optional: pip install send2trash
        send2trash(str(p))
        return
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]
        op = SHFILEOPSTRUCTW()
        op.wFunc = 3                                            # FO_DELETE
        op.pFrom = str(p.resolve()) + "\0\0"
        op.fFlags = 0x40 | 0x10 | 0x4 | 0x400                   # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if rc or op.fAnyOperationsAborted:
            raise OSError(f"Could not move it to the Recycle Bin (is it open in another program?) [{rc}]")
        return
    trash = Path.home() / ".jarvis_trash"
    trash.mkdir(exist_ok=True)
    shutil.move(str(p), str(unique_path(trash, p.name)))


def extract_archive(path) -> Path:
    """Unpack next to the archive, into a new folder named like it. Refuses entries that would escape that folder."""
    p = Path(path)
    dest = unique_path(p.parent, archive_stem(p.name))
    dest.mkdir()
    base = dest.resolve()

    def ok(name: str) -> bool:
        return _inside(base / name, base)
    low = p.name.lower()
    try:
        if low.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(p) as z:
                if not all(ok(m.filename) for m in z.infolist()):
                    raise OSError("The archive tries to write outside its folder")
                z.extractall(dest)
        elif low.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
            import tarfile
            with tarfile.open(p) as t:
                for m in t.getmembers():
                    if not ok(m.name) or m.issym() or m.islnk() or m.isdev():
                        raise OSError("The archive has unsafe entries")
                try:
                    t.extractall(dest, filter="data")
                except TypeError:                               # Python < 3.12
                    t.extractall(dest)
        elif low.endswith(".7z"):
            try:
                import py7zr
            except ImportError:
                raise OSError("7z needs:  pip install py7zr") from None
            with py7zr.SevenZipFile(p) as z:
                if not all(ok(n) for n in z.getnames()):
                    raise OSError("The archive tries to write outside its folder")
                z.extractall(dest)
        elif low.endswith(".rar"):
            try:
                import rarfile
            except ImportError:
                raise OSError("RAR needs:  pip install rarfile  (and UnRAR)") from None
            with rarfile.RarFile(p) as z:
                if not all(ok(n) for n in z.namelist()):
                    raise OSError("The archive tries to write outside its folder")
                z.extractall(dest)
        else:
            raise OSError("This isn't an archive")
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


class Card:
    def __init__(self, idx: int, data: dict, x: float, y: float):
        self.idx, self.data = idx, data
        self.x, self.y = x, y
        self.vx = self.vy = 0.0
        self.angle = random.uniform(-0.03, 0.03)
        self.spin = 0.0
        self.k = 0.0                 # 0 = small card … 1 = fully opened
        self.open = False
        self.held = False
        self.phase = random.uniform(0, 6.28)
        self.lift = 0.0              # 0..1, grows while held (shadow / scale)
        self.hov = 0.0               # 0..1, glows while a hand is over it
        self.a = 0.0                 # 0..1, "appear" animation after a folder change
        self.born = 0.0
        self.ow, self.oh = 560.0, 380.0       # size when opened (depends on the picture's shape / the screen)
        self.zoom, self.vcx, self.vcy = 1.0, 0.5, 0.5        # opened picture: zoom and the centre of the view
        self.scroll = 0.0                    # opened note: how far it is scrolled (px)
        self.yaw, self.pitch = 0.6, 0.3      # opened 3D model: its turn (radians); self.zoom scales it
        self.paused = False                  # opened video
        self.cmds: list = []                 # commands for the player: ("seek", seconds) / ("pause", bool)
        self.ret = (x, y)                    # where it sits in the grid, so it flies back after closing
        self.home = (x, y)
        self.homing = False
        self._target = None          # claw orbit target

    @property
    def w(self) -> float:
        return CARD_W + (self.ow - CARD_W) * self.k

    @property
    def h(self) -> float:
        return CARD_H + (self.oh - CARD_H) * self.k

    def hit(self, px: float, py: float, pad: float = 14.0) -> bool:
        return abs(px - self.x) <= self.w / 2 + pad and abs(py - self.y) <= self.h / 2 + pad


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Hand:
    """One tracked hand: screen-space points plus pinch / claw / fist / open classification."""

    def __init__(self):
        self.pts: list[tuple[float, float]] | None = None
        self.pinching = False
        self._pn = self._rn = 0
        self.pos = (0.0, 0.0)            # smoothed pinch point
        self.last = (0.0, 0.0)           # pinch point one frame ago (for dragging / panning)
        self.palm = (0.0, 0.0)
        self.claw = self.fist = self.open = False
        self.held = None                 # Card | "zoom" | None
        self.grab_off = (0.0, 0.0)
        self.down_t = 0.0
        self.down_pos = (0.0, 0.0)
        self.hist: deque = deque(maxlen=10)
        self.fist_since = 0.0
        self.fist_prog = 0.0             # 0..1 while a fist is held: at 1 → "back"
        self.fist_fired = False
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
        if self.fist and not self.pinching:
            self.fist_since = self.fist_since or now
            self.fist_prog = min(1.0, (now - self.fist_since) / FIST_SECONDS)
        else:
            self.fist_since, self.fist_prog, self.fist_fired = 0.0, 0.0, False
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
        self.entries: list[dict] = []
        self.path: Path | None = None            # None = "This PC" (the drives)
        self.pinned: str | None = None
        self.sort = "name"
        self.page, self.pages, self.per_page = 0, 1, 20
        self.summary = ""
        self.buttons: list[dict] = []
        self.hover_btn: str | None = None
        self.hover_card: Card | None = None
        self.mouse_hover: tuple[float, float] | None = None
        self.hands: list[Hand] = [Hand(), Hand()]
        self.visible = [False, False]
        self.close_requested = False
        self.now = time.time()
        self.flash: dict[str, float] = {}         # button id → time it was pressed (for the click animation)
        self._toast = ("", 0.0)
        self._two: dict | None = None
        self._claw_n = 0
        self._last_press = 0.0
        self._last_wheel = 0.0
        # file operations
        self.select = False                      # select mode: a tap marks a card instead of opening it
        self.sel: set[str] = set()
        self.clip: dict | None = None            # {"paths": [...], "cut": bool}
        self.confirm: tuple | None = None        # ("a_delete", until) — the second press within 4 s does it
        self.prompt: dict | None = None          # the rename box
        self.on_release = None                   # callable(paths): the UI lets go of files it holds open (a playing video)
        self._job: Future | None = None
        self._pool: ThreadPoolExecutor | None = None

    # ── small helpers ────────────────────────────────────────────────────────────
    def say(self, text: str, secs: float = 2.4):
        self._toast = (text, time.time() + secs)

    @property
    def toast(self) -> str:
        return self._toast[0] if time.time() < self._toast[1] else ""

    @property
    def crumb(self) -> str:
        if self.path is None:
            return "This PC"
        parts = [p for p in Path(self.path).parts if p not in ("\\", "/")]
        return "This PC  ›  " + "  ›  ".join(p.rstrip("\\/") for p in parts)

    @property
    def empty(self) -> bool:
        return not self.entries

    def _opened(self) -> Card | None:
        return next((c for c in self.cards if c.open), None)

    @property
    def opened(self) -> Card | None:
        return self._opened()

    def _open_center(self) -> tuple[float, float]:
        return self.w / 2, 100 + (self.h - 130 - 100 - 64) / 2

    def _open_dims(self, c: Card) -> tuple[float, float]:
        kind = c.data.get("kind")
        aw, ah = self.w * 0.90, self.h - 304
        if kind == "image":
            asp = c.data.get("aspect") or 1.6
            w = aw
            h = w / asp
            if h > ah:
                h = ah
                w = h * asp
            return max(w, CARD_W), max(h, CARD_H)
        if kind == "text":
            return min(self.w * 0.62, 1000.0), ah
        if kind == "video":
            asp = c.data.get("aspect") or 16 / 9
            w = aw
            h = w / asp
            if h > ah:
                h = ah
                w = h * asp
            return max(w, CARD_W), max(h, CARD_H)
        if kind == "model":
            side = min(self.w * 0.6, ah * 1.25)
            return max(side, CARD_W), ah
        return min(self.w * 0.42, 640.0), min(ah, 380.0)

    # ── navigation ───────────────────────────────────────────────────────────────
    def start(self, pinned: str | None = None):
        """Open Hand Space on 'This PC': the drives, C: first."""
        self.pinned = pinned if pinned and Path(pinned).is_dir() else None
        self.sort = "name"
        self.go_root()

    def go_root(self):
        self.path = None
        self.entries = list_roots(self.pinned)
        self.page = 0
        self.select, self.sel, self.confirm = False, set(), None
        self._build_page()

    def open_path(self, p: str | Path, keep_page: bool = False) -> bool:
        p = Path(p)
        try:
            entries = list_dir(p, self.sort)
        except PermissionError:
            self.say("Access denied — Windows keeps this folder private")
            return False
        except OSError:
            self.say("Can't open this folder")
            return False
        self.path, self.entries = p, entries
        self.page = self.page if keep_page else 0
        self._build_page()
        if not entries:
            self.say("This folder is empty")
        return True

    def go_up(self):
        if self.path is None:
            self.say("Already at the top")
            return
        parent = self.path.parent
        if parent == self.path or str(parent) in ("", "."):
            self.go_root()
        elif not self.open_path(parent):
            self.go_root()

    def back(self):
        """Fist / Backspace / right-click: close the open card, otherwise go up a folder."""
        if self.prompt is not None:
            self.prompt = None
            return
        op = self._opened()
        if op is not None:
            self._set_open(op, False)
        elif self.select:
            self._set_select(False)
        else:
            self.go_up()

    def set_sort(self, sort: str):
        self.sort = sort
        if self.path is not None:
            sort_entries(self.entries, sort)
            self.page = 0
            self._build_page()

    def change_page(self, step: int):
        if self.path is None and len(self.entries) <= self.per_page:
            return
        n = max(0, min(self.pages - 1, self.page + step))
        if n != self.page:
            self.page = n
            self._build_page()

    # ── layout ───────────────────────────────────────────────────────────────────
    def _grid(self) -> tuple[int, int]:
        usable_w = self.w - 2 * SIDE_MARGIN
        usable_h = self.h - TOP_MARGIN - BOTTOM_MARGIN
        cols = max(1, int((usable_w + GAP) // (CARD_W + GAP)))
        rows = max(1, int((usable_h + GAP) // (CARD_H + GAP)))
        return cols, rows

    def _slot(self, i: int, n: int, cols: int) -> tuple[float, float]:
        r, c = divmod(i, cols)
        ncols, nrows = min(cols, n), math.ceil(n / cols)
        gw = ncols * CARD_W + (ncols - 1) * GAP
        gh = nrows * CARD_H + (nrows - 1) * GAP
        usable_h = self.h - TOP_MARGIN - BOTTOM_MARGIN
        x0 = (self.w - gw) / 2 + CARD_W / 2
        y0 = TOP_MARGIN + max(0.0, (usable_h - gh) / 2) + CARD_H / 2
        return x0 + c * (CARD_W + GAP), y0 + r * (CARD_H + GAP)

    def _build_page(self):
        cols, rows = self._grid()
        self.per_page = cols * rows
        self.pages = max(1, math.ceil(len(self.entries) / self.per_page))
        self.page = max(0, min(self.page, self.pages - 1))
        chunk = self.entries[self.page * self.per_page:(self.page + 1) * self.per_page]
        now = time.time()
        self.cards = []
        for i, e in enumerate(chunk):
            fill_text(e)
            x, y = self._slot(i, len(chunk), cols)
            c = Card(i, e, x, y)
            c.born = now + min(0.03 * i, 0.45)
            self.cards.append(c)
        for h in self.hands:
            h.held = None
        self._two = None
        self._claw_n = 0
        nd = sum(1 for e in self.entries if e["kind"] in ("folder", "drive"))
        if self.path is None:
            self.summary = f"{nd} drive{'s' if nd != 1 else ''}" if nd == len(self.entries) else f"{len(self.entries)} places"
        else:
            nf = len(self.entries) - nd
            self.summary = f"{nd} folder{'s' if nd != 1 else ''} · {nf} file{'s' if nf != 1 else ''}"
        self._layout_buttons()

    def arrange(self):
        """Put the cards back on the tidy grid."""
        cols, _ = self._grid()
        for i, c in enumerate(self.cards):
            if not c.open:
                c.home, c.homing = self._slot(i, len(self.cards), cols), True
        self.say("Cards arranged")

    def resize(self, w: int, h: int):
        sx, sy = w / self.w, h / self.h
        self.w, self.h = w, h
        cols, rows = self._grid()
        if cols * rows != self.per_page:
            self._build_page()
            return
        for c in self.cards:
            c.x, c.y, c.vx, c.vy = c.x * sx, c.y * sy, 0.0, 0.0
            c.home, c.ret = (c.home[0] * sx, c.home[1] * sy), (c.ret[0] * sx, c.ret[1] * sy)
        self._layout_buttons()

    # ── open / close a card ──────────────────────────────────────────────────────
    def _set_open(self, c: Card, on: bool):
        if on:
            for o in self.cards:
                if o is not c and o.open:
                    self._set_open(o, False)
            c.ret = (c.x, c.y)
            c.open, c.zoom, c.vcx, c.vcy, c.scroll = True, 1.0, 0.5, 0.5, 0.0
            c.yaw, c.pitch, c.paused, c.cmds = 0.6, 0.3, False, []
            c.homing = False
        else:
            c.open = False
            c.home, c.homing = c.ret, True
            c.zoom, c.vcx, c.vcy = 1.0, 0.5, 0.5
        self._two = None
        self._layout_buttons()

    def _activate(self, c: Card):
        if self.prompt is not None:
            return
        kind = c.data.get("kind")
        if self.select and kind != "drive":
            self._toggle_sel(c)
            return
        if kind in ("drive", "folder"):
            self.open_path(c.data["path"])
        else:
            self._set_open(c, True)

    def _neighbor(self, step: int):
        c = self._opened()
        if c is None:
            return
        kind = c.data["kind"]
        idxs = [i for i, e in enumerate(self.entries) if e["kind"] == kind]
        cur = next((i for i, e in enumerate(self.entries) if e is c.data), None)
        if cur is None or len(idxs) < 2:
            return
        ti = idxs[(idxs.index(cur) + step) % len(idxs)]
        page = ti // self.per_page
        if page != self.page:
            self.page = page
            self._build_page()
        else:
            c.open, c.k = False, 0.0
            c.x, c.y = c.ret
        new = next((x for x in self.cards if x.data is self.entries[ti]), None)
        if new is not None:
            self._set_open(new, True)
            new.x, new.y = self._open_center()          # swap in place: no trip across the screen
            new.k, new.a = 0.8, 0.5

    def _zoom_by(self, c: Card, f: float):
        c.zoom = max(1.0, min(8.0, c.zoom * f))
        self._clamp_view(c)

    @staticmethod
    def _clamp_view(c: Card):
        if c.zoom <= 1.001:
            c.vcx = c.vcy = 0.5
            return
        lo, hi = 0.5 / c.zoom, 1 - 0.5 / c.zoom
        c.vcx, c.vcy = max(lo, min(hi, c.vcx)), max(lo, min(hi, c.vcy))

    # ── buttons ──────────────────────────────────────────────────────────────────
    def _layout_buttons(self):
        W, H = self.w, self.h
        bw, bh, g = BTN_W, BTN_H, BTN_GAP
        op = self._opened()
        out: list[dict] = []

        def add(bid, x, y, w=bw, h=bh, on=True, label="", active=False, danger=False):
            out.append({"id": bid, "x": x, "y": y, "w": w, "h": h, "on": on, "label": label, "active": active, "danger": danger})

        if self.prompt is not None:                                     # the rename box owns the screen
            by = H / 2 + 78
            add("p_cancel", W / 2 - 12 - 130, by, 130, bh, label="Cancel")
            add("p_ok", W / 2 + 12, by, 130, bh, label="OK", active=True)
            self.buttons = out
            return

        y = 34
        away = self.path is not None
        add("home", 40, y, on=away)
        add("up", 40 + bw + g, y, on=away)
        add("explorer", 40 + 2 * (bw + g), y, on=away)
        add("select", 40 + 3 * (bw + g), y, 108, bh, on=away and bool(self.cards) and op is None,
            label="Done" if self.select else "Select", active=self.select)
        add("close", W - 40 - 56, y - 2, 56, 56)
        add("sort", W - 96 - g - 130, y, 130, bh, label=SORT_LABEL[self.sort])
        add("arrange", W - 96 - g - 130 - g - bw, y, on=bool(self.cards) and op is None)
        yb = H - 112
        AW = 96
        deleting = self.confirm_active
        if op is None:
            acts: list = []
            if away and self.select:
                n = len(self.sel)
                acts = [("a_copy", "Copy", n > 0), ("a_cut", "Cut", n > 0), ("a_paste", "Paste", bool(self.clip)),
                        ("a_rename", "Rename", n == 1), ("a_extract", "Extract", any(is_archive(x) for x in self.sel)),
                        ("a_delete", "Sure?" if deleting else "Delete", n > 0), ("a_new", "New folder", True)]
            elif away and self.clip:
                acts = [("a_paste", "Paste", True), ("a_clipx", "Clear", True)]
            half = (len(acts) * (AW + g) - g) / 2 if acts else 0
            for i, (bid, label, on) in enumerate(acts):
                wide = AW + 30 if bid == "a_new" else AW
                add(bid, W / 2 - half + i * (AW + g), yb, wide, bh, on=on, label=label, danger=(bid == "a_delete" and deleting))
            if self.pages > 1:
                add("pg_prev", W / 2 - half - g - bw - (0 if acts else 78), yb, on=self.page > 0)
                add("pg_next", W / 2 + half + g + (0 if acts else 78), yb, on=self.page < self.pages - 1)
        else:
            if op.data["kind"] != "drive":                                # the file-operations row above the viewer's buttons
                fa = [("a_copy", "Copy"), ("a_cut", "Cut"), ("a_rename", "Rename")]
                if is_archive(op.data["path"]):
                    fa.append(("a_extract", "Extract"))
                fa.append(("a_delete", "Sure?" if deleting else "Delete"))
                half2 = (len(fa) * (AW + g) - g) / 2
                for i, (bid, label) in enumerate(fa):
                    add(bid, W / 2 - half2 + i * (AW + g), yb - bh - 12, AW, bh, label=label, danger=(bid == "a_delete" and deleting))
            kind = op.data["kind"]
            same = sum(1 for e in self.entries if e["kind"] == kind)
            specs = [("v_prev", same > 1)]
            if kind == "video":
                specs += [("v_minus", True), ("v_play", True), ("v_plus", True)]
            else:
                specs += [("v_minus", kind in ("image", "text", "model")), ("v_plus", kind in ("image", "text", "model"))]
            specs += [("v_open", can_launch(op.data)), ("v_close", True), ("v_next", same > 1)]
            total = len(specs) * bw + (len(specs) - 1) * g
            x0 = (W - total) / 2
            for i, (bid, on) in enumerate(specs):
                add(bid, x0 + i * (bw + g), yb, on=on)
        self.buttons = out

    def _btn_at(self, x: float, y: float, pad: float = 10.0) -> dict | None:
        for b in self.buttons:
            if b["x"] - pad <= x <= b["x"] + b["w"] + pad and b["y"] - pad <= y <= b["y"] + b["h"] + pad:
                return b
        return None

    def _press(self, bid: str, now: float):
        self.flash[bid] = now
        op = self._opened()
        if bid == "close":
            self.close_requested = True
        elif bid == "home":
            self.go_root()
        elif bid == "up":
            self.go_up()
        elif bid == "explorer":
            if self.path is not None and not open_external(str(self.path)):
                self.say("Could not open Explorer")
        elif bid == "sort":
            self.set_sort(SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)])
        elif bid == "arrange":
            self.arrange()
        elif bid == "select":
            self._set_select(not self.select)
        elif bid == "p_ok":
            self.prompt_submit()
        elif bid == "p_cancel":
            self.prompt = None
        elif bid.startswith("a_"):
            self._file_action(bid)
        elif bid == "pg_prev":
            self.change_page(-1)
        elif bid == "pg_next":
            self.change_page(1)
        elif op is None:
            return
        elif bid == "v_close":
            self._set_open(op, False)
        elif bid == "v_prev":
            self._neighbor(-1)
        elif bid == "v_next":
            self._neighbor(1)
        elif bid == "v_open":
            if can_launch(op.data):
                self.say("Opened in the default app" if open_external(op.data["path"]) else "Could not open it")
        elif bid == "v_play":
            if op.data["kind"] == "video":
                op.paused = not op.paused
                op.cmds.append(("pause", op.paused))
        elif bid in ("v_plus", "v_minus"):
            sign = 1 if bid == "v_plus" else -1
            if op.data["kind"] == "image":
                self._zoom_by(op, 1.4 if sign > 0 else 1 / 1.4)
            elif op.data["kind"] == "model":
                op.zoom = max(0.4, min(6.0, op.zoom * (1.25 if sign > 0 else 1 / 1.25)))
            elif op.data["kind"] == "video":
                op.cmds.append(("seek", SEEK_STEP * sign))
            elif op.data["kind"] == "text":
                op.scroll = max(0.0, op.scroll + (-sign) * 180.0)        # + = up, − = down, like a scroll bar's arrows

    # ── file operations ──────────────────────────────────────────────────────────
    @property
    def confirm_active(self) -> bool:
        return self.confirm is not None and time.time() < self.confirm[1]

    @property
    def clip_paths(self) -> set:
        return set(self.clip["paths"]) if self.clip and self.clip.get("cut") else set()

    def _set_select(self, on: bool):
        self.select = on
        self.sel.clear()
        self.confirm = None
        self._layout_buttons()

    def _toggle_sel(self, c: Card):
        path = c.data.get("path")
        if not path or c.data.get("kind") == "drive":
            return
        self.sel.symmetric_difference_update({path})
        self.confirm = None

    def select_all(self):
        if self.path is None:
            return
        self.select = True
        self.sel = {e["path"] for e in self.entries if e.get("kind") != "drive"}
        self.confirm = None

    def targets(self) -> list[str]:
        """What the file buttons act on: the open card, else the marked cards, else the one under the pointer."""
        op = self._opened()
        if op is not None:
            return [op.data["path"]]
        if self.select:
            return [e["path"] for e in self.entries if e["path"] in self.sel]
        hc = self.hover_card
        if hc is not None and self.path is not None and hc.data.get("kind") != "drive":
            return [hc.data["path"]]
        return []

    def _reload(self):
        if self.path is None:
            self.go_root()
            return
        if not self.open_path(self.path, keep_page=True):
            self.go_root()
        self.sel &= {e["path"] for e in self.entries}
        if self.clip:
            self.clip["paths"] = [x for x in self.clip["paths"] if os.path.exists(x)] or []
            if not self.clip["paths"]:
                self.clip = None

    def _let_go(self, paths):
        """Tell the UI to release these files first (a video that is playing keeps its file locked)."""
        if self.on_release is not None:
            try:
                self.on_release(list(paths))
            except Exception:
                pass

    def _run(self, label: str, fn, *args):
        if self._job is not None:
            self.say("Still busy with the last operation…")
            return
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hs-files")
        self.say(label + "…", 600.0)
        self._job = self._pool.submit(fn, *args)

    @staticmethod
    def _job_paste(paths, dst, cut) -> str:
        done, errs = 0, []
        for p in paths:
            try:
                (move_item if cut else copy_item)(p, dst)
                done += 1
            except Exception as e:                               # noqa: BLE001
                errs.append(f"{Path(p).name}: {_err(e)}")
        msg = f"{'Moved' if cut else 'Copied'} {done} item{'s' if done != 1 else ''}"
        return msg + (f" · {len(errs)} failed — {errs[0]}" if errs else "")

    @staticmethod
    def _job_delete(paths) -> str:
        done, errs = 0, []
        for p in paths:
            try:
                recycle(p)
                done += 1
            except Exception as e:                               # noqa: BLE001
                errs.append(f"{Path(p).name}: {_err(e)}")
        msg = f"{done} item{'s' if done != 1 else ''} moved to the Recycle Bin"
        return msg + (f" · {len(errs)} failed — {errs[0]}" if errs else "")

    @staticmethod
    def _job_extract(paths) -> str:
        done, errs, last = 0, [], ""
        for p in paths:
            try:
                last = extract_archive(p).name
                done += 1
            except Exception as e:                               # noqa: BLE001
                errs.append(f"{Path(p).name}: {_err(e)}")
        msg = f"Extracted to “{last}”" if done == 1 and not errs else f"Extracted {done} archive{'s' if done != 1 else ''}"
        return msg + (f" · {len(errs)} failed — {errs[0]}" if errs else "")

    def _file_action(self, bid: str):
        now = time.time()
        if self.prompt is not None:
            return
        if bid == "a_clipx":
            self.clip = None
            self.say("Clipboard cleared")
            return
        if bid == "a_new":
            if self.path is None:
                return
            try:
                d = unique_path(self.path, "New folder")
                d.mkdir()
            except OSError as e:
                self.say(f"Could not create the folder: {_err(e)}")
                return
            self._reload()
            self._start_rename(str(d), new=True)
            return
        if bid == "a_paste":
            if not self.clip:
                self.say("Nothing to paste — Copy or Cut something first")
            elif self.path is None:
                self.say("Open a folder to paste into")
            else:
                clip, self.clip = self.clip, None
                if clip["cut"]:
                    self._let_go(clip["paths"])
                self._run("Moving" if clip["cut"] else "Copying", self._job_paste, list(clip["paths"]), str(self.path), clip["cut"])
            return
        t = self.targets()
        if not t:
            self.say("Select something first — press Select, then tap cards")
            return
        n = len(t)
        if bid in ("a_copy", "a_cut"):
            cut = bid == "a_cut"
            self.clip = {"paths": t, "cut": cut}
            self.say(f"{n} item{'s' if n != 1 else ''} {'cut' if cut else 'copied'} — open a folder and press Paste", 3.2)
            self.sel.clear()
        elif bid == "a_rename":
            if n != 1:
                self.say("Rename works on one item at a time")
            else:
                self._start_rename(t[0])
        elif bid == "a_extract":
            arcs = [x for x in t if is_archive(x)]
            if not arcs:
                self.say("That isn't an archive (zip, tar, 7z, rar)")
            else:
                self._run("Extracting", self._job_extract, arcs)
                self.sel.clear()
        elif bid == "a_delete":
            if not self.confirm_active:
                self.confirm = (bid, now + 4.0)
                self.say(f"Press Delete again to move {n} item{'s' if n != 1 else ''} to the Recycle Bin", 4.0)
                return
            self.confirm = None
            op = self._opened()
            if op is not None and op.data.get("path") in t:
                self._set_open(op, False)
            self._let_go(t)
            self._run("Moving to the Recycle Bin", self._job_delete, t)
            self.sel.clear()

    def _start_rename(self, path: str, new: bool = False):
        name = Path(path).name
        stem = name if (Path(path).is_dir() or "." not in name.lstrip(".")) else name[:name.rfind(".")]
        self._let_go([path])
        self.prompt = {"title": "Name the new folder" if new else "Rename", "path": path, "text": name,
                       "cur": len(stem), "sel0": 0, "error": ""}

    def prompt_key(self, text: str, key: str = "") -> bool:
        """Keyboard input for the rename box. key: enter / esc / backspace / delete / left / right / home / end / all."""
        pr = self.prompt
        if pr is None:
            return False
        t, cur, s0 = pr["text"], pr["cur"], pr["sel0"]
        lo, hi = min(cur, s0), max(cur, s0)
        pr["error"] = ""
        if key == "enter":
            self.prompt_submit()
        elif key == "esc":
            self.prompt = None
        elif key == "all":
            pr["sel0"], pr["cur"] = 0, len(t)
        elif key == "backspace":
            if lo != hi:
                pr["text"], pr["cur"], pr["sel0"] = t[:lo] + t[hi:], lo, lo
            elif cur > 0:
                pr["text"], pr["cur"], pr["sel0"] = t[:cur - 1] + t[cur:], cur - 1, cur - 1
        elif key == "delete":
            if lo != hi:
                pr["text"], pr["cur"], pr["sel0"] = t[:lo] + t[hi:], lo, lo
            elif cur < len(t):
                pr["text"] = t[:cur] + t[cur + 1:]
        elif key in ("left", "right", "home", "end"):
            if key == "left":
                c = lo if lo != hi else max(0, cur - 1)
            elif key == "right":
                c = hi if lo != hi else min(len(t), cur + 1)
            else:
                c = 0 if key == "home" else len(t)
            pr["cur"] = pr["sel0"] = c
        else:
            text = "".join(ch for ch in text if ch.isprintable())
            if text:
                pr["text"] = (t[:lo] + text + t[hi:])[:200]
                pr["cur"] = pr["sel0"] = min(200, lo + len(text))
        return True

    def prompt_submit(self):
        pr = self.prompt
        if pr is None:
            return
        new = pr["text"].strip()
        path = Path(pr["path"])
        if new == path.name:
            self.prompt = None
            return
        err = check_name(new)
        target = path.with_name(new)
        if not err and target.exists() and target.name.lower() != path.name.lower():
            err = "Something with that name already exists here"
        if err:
            pr["error"] = err
            return
        self._let_go([str(path)])
        try:
            path.rename(target)
        except OSError as e:
            pr["error"] = _err(e)
            return
        self.prompt = None
        self.sel.clear()
        self._reload()
        self.say(f"Renamed to {new}")

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

    def hover_at(self, x: float, y: float):
        self.mouse_hover = (x, y)

    def wheel(self, dy: float, x: float = 0.0, y: float = 0.0):
        op = self._opened()
        if op is None:
            if time.time() - self._last_wheel > 0.25:
                self._last_wheel = time.time()
                self.change_page(1 if dy < 0 else -1)
        elif op.data["kind"] == "image":
            self._zoom_by(op, 1.18 if dy > 0 else 1 / 1.18)
        elif op.data["kind"] == "text":
            op.scroll = max(0.0, op.scroll - dy * 0.8)
        elif op.data["kind"] == "model":
            op.zoom = max(0.4, min(6.0, op.zoom * (1.12 if dy > 0 else 1 / 1.12)))
        elif op.data["kind"] == "video":
            op.cmds.append(("seek", 5.0 if dy > 0 else -5.0))

    def key_arrow(self, step: int):
        if self._opened() is not None:
            self._neighbor(step)
        else:
            self.change_page(step)

    # ── interaction ──────────────────────────────────────────────────────────────
    def _lost(self, hand: Hand, now: float):
        if hand.held is not None:
            self._release(hand, now)
        hand.pinching = False
        hand.pts = None
        hand.claw = hand.fist = hand.open = False
        hand.fist_since, hand.fist_prog, hand.fist_fired = 0.0, 0.0, False
        hand.hist.clear()
        hand.palm = (0.0, 0.0)

    def _card_at(self, x: float, y: float, pad: float = 14.0) -> Card | None:
        op = self._opened()
        pool = [op] if op is not None else self.cards
        best, bd = None, 1e18
        for c in pool:
            if c.hit(x, y, pad):
                d = ((x - c.x) / max(1.0, c.w)) ** 2 + ((y - c.y) / max(1.0, c.h)) ** 2          # nearest centre wins in the gaps
                if d < bd:
                    best, bd = c, d
        return best

    def _grab(self, hand: Hand, now: float):
        x, y = hand.pos
        b = self._btn_at(x, y)
        if b is not None:
            if b["on"] and now - self._last_press > 0.3:
                self._last_press = now
                self._press(b["id"], now)
            return
        if self.prompt is not None:
            return
        op = self._opened()
        c = self._card_at(x, y, 14.0 if op is None else 0.0)
        if c is not None:
            hand.held, hand.grab_off = c, (c.x - x, c.y - y)
            hand.down_t, hand.down_pos, hand.last = now, hand.palm, hand.pos
            c.held = not c.open
        elif op is not None:                                  # a pinch on the dark background closes the open card
            self._set_open(op, False)

    def _release(self, hand: Hand, now: float):
        h = hand.held
        hand.held = None
        if not isinstance(h, Card):
            return
        h.held = False
        moved = _d(hand.palm, hand.down_pos)
        if now - hand.down_t < TAP_SECONDS and moved < TAP_PIXELS:           # a tap: go in / open / close
            if h.open:
                self._set_open(h, False)
            else:
                self._activate(h)
            return
        if h.open:
            return
        vx, vy = hand.velocity()
        h.vx, h.vy = vx * 1.15, vy * 1.15
        h.spin = max(-9.0, min(9.0, vx * 0.0021))

    def _interact(self, now: float, mouse: bool = False):
        self._layout_buttons()
        act = [(i, h) for i, h in enumerate(self.hands) if self.visible[i]]
        op = self._opened()
        # two hands pinching while a picture is open: zoom it
        both = (op is not None and op.data["kind"] in ("image", "model") and len(act) == 2 and all(h.pinching for _, h in act))
        if both:
            a, b = act[0][1].pos, act[1][1].pos
            dist = max(40.0, _d(a, b))
            if self._two is None:
                self._two = {"dist": dist, "zoom": op.zoom}
                for _, h in act:
                    h.held = "zoom"
                    if isinstance(h.held, Card):
                        h.held.held = False
            op.zoom = max(0.4 if op.data["kind"] == "model" else 1.0, min(8.0, self._two["zoom"] * dist / self._two["dist"]))
            if op.data["kind"] == "image":
                self._clamp_view(op)
            return
        if self._two is not None:
            self._two = None
            for _, h in act:
                if h.held == "zoom":
                    h.held = None

        for i, h in act:
            rise, fall = h._edge
            if rise:
                self._grab(h, now)
            if fall and h.held is not None:
                self._release(h, now)
            if h.pinching and isinstance(h.held, Card):
                c = h.held
                c.vx = c.vy = 0.0
                if not c.open:
                    tx, ty = h.pos[0] + h.grab_off[0], h.pos[1] + h.grab_off[1]
                    c.x += (tx - c.x) * 0.45
                    c.y += (ty - c.y) * 0.45
                else:                                          # drag the open picture / scroll the open note
                    dx, dy = h.pos[0] - h.last[0], h.pos[1] - h.last[1]
                    if c.data["kind"] == "image" and c.zoom > 1.001:
                        c.vcx -= dx / (c.w * c.zoom)
                        c.vcy -= dy / (c.h * c.zoom)
                        self._clamp_view(c)
                    elif c.data["kind"] == "text":
                        c.scroll = max(0.0, c.scroll - dy)
                    elif c.data["kind"] == "model":                     # drag = turn the model in your hand
                        c.yaw += dx * 0.008
                        c.pitch = max(-1.5, min(1.5, c.pitch + dy * 0.008))
                    elif c.data["kind"] == "video" and dx:              # drag sideways = scrub
                        c.cmds.append(("seek", dx / max(200.0, c.w) * 90.0))
                h.last = h.pos
            # fist held for a second: back
            if h.fist_prog >= 1.0 and not h.fist_fired and h.held is None and not mouse:
                h.fist_fired = True
                self.back()
                return

        # claw: pull every free card into an orbit around the palm
        claw = next((h for _, h in act if h.claw and not h.pinching), None)
        self._claw_n = 0
        if claw is not None and self._opened() is None:
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
        if self._opened() is None:
            for _, h in act:
                if h.open and h.speed > 900 and not mouse:
                    for c in self.cards:
                        if not c.held and _d(h.palm, (c.x, c.y)) < 170:
                            d = max(1.0, _d(h.palm, (c.x, c.y)))
                            c.vx += (c.x - h.palm[0]) / d * min(h.speed, 2200) * 0.5
                            c.vy += (c.y - h.palm[1]) / d * min(h.speed, 2200) * 0.5
                            c.homing = False

    # ── physics ──────────────────────────────────────────────────────────────────
    def _update_hover(self):
        pts = [h.pos for i, h in enumerate(self.hands) if self.visible[i]]
        if not pts and self.mouse_hover is not None:
            pts = [self.mouse_hover]
        self.hover_btn, self.hover_card = None, None
        for x, y in pts:
            b = self._btn_at(x, y)
            if b is not None:
                self.hover_btn = b["id"]
                continue
            self.hover_card = self._card_at(x, y, 6.0) or self.hover_card

    def step(self, dt: float, now: float | None = None):
        now = time.time() if now is None else now
        dt = min(dt, 0.05)
        job = self._job
        if job is not None and job.done():                       # a copy / delete / extract finished in the background
            self._job = None
            try:
                msg = job.result()
            except Exception as e:                               # noqa: BLE001
                msg = f"Failed: {_err(e)}"
            self._reload()
            self.say(msg, 4.0)
        self._layout_buttons()
        self._update_hover()
        ocx, ocy = self._open_center()
        for c in self.cards:
            c.ow, c.oh = self._open_dims(c)
            c.k += ((1.0 if c.open else 0.0) - c.k) * min(1.0, 9 * dt)
            c.lift += ((1.0 if c.held else 0.0) - c.lift) * min(1.0, 12 * dt)
            c.hov += ((1.0 if c is self.hover_card and not c.open else 0.0) - c.hov) * min(1.0, 14 * dt)
            if now >= c.born:
                c.a += (1.0 - c.a) * min(1.0, 8 * dt)
            if c.open:                                           # glide to the middle of the screen
                c.x += (ocx - c.x) * min(1.0, 8 * dt)
                c.y += (ocy - c.y) * min(1.0, 8 * dt)
                c.angle *= math.exp(-9 * dt)
                c.vx = c.vy = c.spin = 0.0
                continue
            if c.held:
                c.angle += (0.0 - c.angle) * min(1.0, 8 * dt)
                continue
            tgt = c._target
            if tgt is not None:                                  # claw orbit: critically-damped spring
                c.vx += (tgt[0] - c.x) * 38 * dt
                c.vy += (tgt[1] - c.y) * 38 * dt
                damp = math.exp(-9 * dt)
                c.vx *= damp
                c.vy *= damp
            elif c.homing:                                       # fly back to the grid slot
                c.vx += (c.home[0] - c.x) * 42 * dt
                c.vy += (c.home[1] - c.y) * 42 * dt
                damp = math.exp(-10 * dt)
                c.vx *= damp
                c.vy *= damp
                if _d((c.x, c.y), c.home) < 1.5 and math.hypot(c.vx, c.vy) < 20:
                    c.x, c.y, c.vx, c.vy, c.homing = c.home[0], c.home[1], 0.0, 0.0, False
            else:
                damp = math.exp(-1.25 * dt)
                c.vx *= damp
                c.vy *= damp
                c.phase += dt
                if math.hypot(c.vx, c.vy) < 40:                  # idle: gentle floating
                    c.y += math.sin(c.phase * 1.3) * 5 * dt
            c.x += c.vx * dt
            c.y += c.vy * dt
            hw, hh = c.w / 2, c.h / 2
            top, bot = 96 + hh, self.h - 40 - hh
            if c.x < hw:
                c.x, c.vx = hw, abs(c.vx) * 0.72
            elif c.x > self.w - hw:
                c.x, c.vx = self.w - hw, -abs(c.vx) * 0.72
            if c.y < top:
                c.y, c.vy = top, abs(c.vy) * 0.72
            elif c.y > bot:
                c.y, c.vy = bot, -abs(c.vy) * 0.72
            c.angle += c.spin * dt
            c.spin *= math.exp(-2.2 * dt)
            if abs(c.spin) < 0.4:                                # settle upright (nearest turn)
                c.angle = (c.angle + math.pi) % (2 * math.pi) - math.pi
                c.angle *= math.exp(-3.5 * dt)

    @property
    def hint(self) -> str:
        op = self._opened()
        if op is not None:
            kind = op.data["kind"]
            if kind == "image":
                return "Tap or Close = back · drag = move the picture · two hands = zoom · fist (hold) = back"
            if kind == "text":
                return "Drag up / down to scroll · tap or Close = back · fist (hold) = back"
            if kind == "model":
                return "Drag = turn the model · two hands = zoom · tap or Close = back · fist (hold) = back"
            if kind == "video":
                return "Drag sideways = scrub · ▶ = play / pause · tap or Close = back · fist (hold) = back"
            return "Tap or Close = back"
        if self.prompt is not None:
            return "Type the new name · Enter = OK · Esc = cancel"
        if self.select:
            return "Tap cards to select them · Copy / Cut / Delete / Rename / Extract · Paste goes into this folder · Done = leave select mode"
        if self._claw_n:
            return "Claw: open your hand to release the cards"
        return "Pinch = grab · tap a folder to go in · tap a picture to enlarge · claw = pull cards · fist (hold) = up one folder"
