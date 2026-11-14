"""Disk cache for Hand Space: parsed 3D meshes (so a big model opens at once the second time) and their card thumbnails.

Safety (the cache is read back into the app, so it is treated as untrusted input):
  * numpy's own formats only, always `allow_pickle=False` — a cache file can never run code;
  * a file name is a SHA-256 of (path, size, mtime), never a piece of the model's path, so nothing can escape the folder;
  * size / dtype / shape / finiteness are checked before anything is used; a bad file is deleted and the model re-read;
  * symlinks (the folder or a file) are refused; writes are atomic (temp file + rename) and never overwrite through a link;
  * the folder lives in the user's own profile (LOCALAPPDATA) and is capped (CACHE_LIMIT), oldest files evicted first;
  * only files whose name matches our pattern are ever listed or deleted.
Nothing here touches the network. `clear()` removes everything (a model's geometry is private data).
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

VERSION = 1
MAX_MESH_VERTS = 4_500_000                         # = 1.5 M triangles (hs_gpu.MAX_TRIS * 3)
MAX_FILE = 80 * 1024 * 1024                        # one entry: 4.5 M vertices × 12 B = 54 MB, plus headroom
CACHE_LIMIT = 2 * 1024 ** 3                        # all entries together; trimmed to 80 % when exceeded
THUMB_SIDE = 192

_NAME = re.compile(r"^[0-9a-f]{40}\.(mesh\.npz|thumb\.npy)$")
_TMP = re.compile(r"^\.[0-9a-f]{40}\.\d+\.\d+\.tmp$")
_dir: Path | bool | None = None                    # None: not resolved yet · False: cache unavailable
_lock = threading.Lock()
_last_trim = 0.0
_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hs-cache")


def cache_dir() -> Path | None:
    global _dir
    if _dir is None:
        with _lock:
            if _dir is None:
                base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
                d = Path(base) / "Jarvis" / "hand_space"
                try:
                    d.mkdir(parents=True, exist_ok=True, mode=0o700)
                    _dir = d if (d.is_dir() and not d.is_symlink()) else False
                except OSError:
                    _dir = False
    return _dir or None


def key_for(path: str, kind: str) -> str | None:
    """Cache key of a source file: changes whenever the file (or this format) changes. None if it can't be stat'ed."""
    try:
        rp = os.path.realpath(path)
        st = os.stat(rp)
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    raw = f"{VERSION}|{kind}|{os.path.normcase(rp)}|{st.st_size}|{st.st_mtime_ns}|{MAX_MESH_VERTS}"
    return hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()[:40]


def _file(key: str | None, suffix: str) -> Path | None:
    d = cache_dir()
    if d is None or not key or not re.fullmatch(r"[0-9a-f]{40}", key):
        return None
    return d / f"{key}.{suffix}"


def _drop(f: Path) -> None:
    try:
        f.unlink()
    except OSError:
        pass


def _regular(f: Path) -> bool:
    try:
        st = f.lstat()                              # lstat: a symlink is not a regular file
        return stat.S_ISREG(st.st_mode) and st.st_size <= MAX_FILE
    except OSError:
        return False


# ── meshes ──────────────────────────────────────────────────────────────────────────────
def get_mesh(key: str | None):
    """→ (float32 (n, 3) positions, triangle count, (cx, cy, cz, 1/radius)) or None."""
    f = _file(key, "mesh.npz")
    if f is None or not f.exists():
        return None
    if not _regular(f):
        _drop(f) if not f.is_symlink() else None
        return None
    try:
        with np.load(f, allow_pickle=False) as z:
            if set(z.files) != {"v", "m"}:
                raise ValueError("unexpected members")
            for name in ("v", "m"):                  # sizes are known from the zip index before anything is read
                if z.zip.getinfo(name + ".npy").file_size > MAX_FILE:
                    raise ValueError("member too large")
            v, m = z["v"], z["m"]
        if (v.dtype != np.float32 or v.ndim != 2 or v.shape[1] != 3 or not (3 <= len(v) <= MAX_MESH_VERTS)
                or len(v) % 3 or m.dtype != np.float64 or m.shape != (4,)):
            raise ValueError("bad shape / dtype")
        if not np.isfinite(m).all() or m[3] <= 0 or not np.isfinite(v).all():
            raise ValueError("non-finite values")
        v = np.ascontiguousarray(v)
        os.utime(f, None)                            # recently used → evicted last
        return v, len(v) // 3, (float(m[0]), float(m[1]), float(m[2]), float(m[3]))
    except Exception:
        _drop(f)
        return None


def _atomic_write(final: Path, writer) -> bool:
    d = final.parent
    tmp = d / f".{final.name.split('.')[0]}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "xb") as fh:                  # "x": never writes through an existing file or link
            writer(fh)
        if tmp.stat().st_size > MAX_FILE:
            raise OSError("entry too large")
        os.replace(tmp, final)
        return True
    except Exception:
        _drop(tmp)
        return False


def put_mesh(key: str | None, v: np.ndarray, meta: tuple) -> bool:
    f = _file(key, "mesh.npz")
    if f is None or v.dtype != np.float32 or v.ndim != 2 or v.shape[1] != 3 or not (3 <= len(v) <= MAX_MESH_VERTS):
        return False
    m = np.asarray(meta, dtype=np.float64)
    ok = _atomic_write(f, lambda fh: np.savez(fh, v=v, m=m))
    if ok:
        _trim()
    return ok


def put_mesh_async(key: str | None, v: np.ndarray, meta: tuple) -> None:
    """Writes in the background so opening the model is never delayed by the disk."""
    if key:
        _writer.submit(put_mesh, key, v, meta)


# ── thumbnails ──────────────────────────────────────────────────────────────────────────
def get_thumb(key: str | None):
    f = _file(key, "thumb.npy")
    if f is None or not f.exists():
        return None
    if not _regular(f):
        _drop(f) if not f.is_symlink() else None
        return None
    try:
        a = np.load(f, allow_pickle=False)
        if a.dtype != np.uint8 or a.shape != (THUMB_SIDE, THUMB_SIDE, 4):
            raise ValueError("bad thumbnail")
        os.utime(f, None)
        return a
    except Exception:
        _drop(f)
        return None


def put_thumb(key: str | None, arr: np.ndarray) -> bool:
    f = _file(key, "thumb.npy")
    if f is None or arr.dtype != np.uint8 or arr.shape != (THUMB_SIDE, THUMB_SIDE, 4):
        return False
    ok = _atomic_write(f, lambda fh: np.save(fh, arr, allow_pickle=False))
    if ok:
        _trim()
    return ok


# ── housekeeping ────────────────────────────────────────────────────────────────────────
def _entries():
    d = cache_dir()
    out = []
    if d is None:
        return out
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.is_symlink() or not e.is_file(follow_symlinks=False):
                    continue
                if _NAME.match(e.name) or _TMP.match(e.name):
                    st = e.stat(follow_symlinks=False)
                    out.append((e.name, st.st_size, st.st_mtime, e.path))
    except OSError:
        pass
    return out


def _trim(force: bool = False, limit: int = CACHE_LIMIT) -> None:
    """Keeps the folder under `limit`: oldest entries go first (at most one scan every 20 s)."""
    global _last_trim
    now = time.time()
    with _lock:
        if not force and now - _last_trim < 20.0:
            return
        _last_trim = now
    items = _entries()
    for name, _sz, mt, p in items:                   # leftovers of an interrupted write
        if _TMP.match(name) and now - mt > 3600:
            _drop(Path(p))
    items = [i for i in items if _NAME.match(i[0])]
    total = sum(i[1] for i in items)
    if total <= limit:
        return
    for name, sz, _mt, p in sorted(items, key=lambda i: i[2]):
        if total <= limit * 0.8:
            break
        _drop(Path(p))
        total -= sz


def clear() -> int:
    """Removes every cache entry; returns how many files were deleted."""
    n = 0
    for name, _sz, _mt, p in _entries():
        _drop(Path(p))
        n += 1
    return n
