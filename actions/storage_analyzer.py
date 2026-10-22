from __future__ import annotations

import heapq
import os
import platform
import tempfile
import time
from datetime import datetime
from pathlib import Path

from actions._common import human_size, log

_OS = platform.system()
TYPES = {
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff", ".raw", ".psd", ".svg"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt", ".csv", ".md"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
    "Installers & disk images": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".appimage", ".img"},
    "Code & data": {".py", ".js", ".ts", ".java", ".cpp", ".c", ".cs", ".json", ".xml", ".sql", ".db", ".sqlite", ".log"},
}


def _reparse(e) -> bool:
    try:
        return bool(getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _walk(root: str, deadline: float, state: dict):
    stack = [root]
    while stack:
        if time.time() > deadline:
            state["partial"] = True
            return
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            if not _reparse(e):
                                stack.append(e.path)
                        else:
                            st = e.stat(follow_symlinks=False)
                            yield e.path, st.st_size, st.st_mtime
                    except OSError:
                        continue
        except OSError:
            continue


def _size(path: str, deadline: float, state: dict) -> int:
    return sum(s for _, s, _ in _walk(path, deadline, state))


def _start(p: dict) -> Path:
    raw = str(p.get("path") or "").strip().strip('"')
    if raw.lower() in ("", "home", "user", "my files"):
        return Path.home()
    if raw.lower() in ("drive", "disk", "system", "everything", "c", "c:", "c:\\"):
        return Path("C:\\") if _OS == "Windows" else Path("/")
    if len(raw) == 1 and raw.isalpha() and _OS == "Windows":
        return Path(raw.upper() + ":\\")
    return Path(raw).expanduser()


def overview() -> str:
    import psutil
    lines = ["Drives:"]
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype or part.mountpoint.startswith(("/snap", "/boot", "/var/lib")):
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        if u.total < 2 * 1024 ** 3:
            continue
        warn = "  ⚠ almost full" if u.percent >= 90 else ""
        lines.append(f"• {part.mountpoint}  {human_size(u.used)} used of {human_size(u.total)} ({u.percent:.0f}%) — {human_size(u.free)} free{warn}")
    return "\n".join(lines) if len(lines) > 1 else "I couldn't read the drives."


def top_folders(root: Path, n: int, budget: float):
    if not root.exists():
        return None, f"I can't find {root}."
    t0 = time.time()
    end = t0 + budget
    items: list = []
    loose = 0
    try:
        kids = list(os.scandir(root))
    except OSError as e:
        return None, f"I can't read {root}: {e}"
    dirs = [k for k in kids if _is_dir(k)]
    for k in kids:
        if k not in dirs:
            try:
                loose += k.stat(follow_symlinks=False).st_size
            except OSError:
                pass
    partial = False
    for i, k in enumerate(dirs):
        slot = max(1.0, (end - time.time()) / max(1, len(dirs) - i))
        st = {"partial": False}
        sz = _size(k.path, time.time() + slot, st)
        partial |= st["partial"]
        items.append((sz, k.name, st["partial"]))
    items.sort(reverse=True)
    if loose:
        items.append((loose, "(files directly in this folder)", False))
        items.sort(reverse=True)
    total = sum(s for s, _, _ in items)
    lines = [f"Biggest folders in {root}:"]
    for sz, name, part in items[: max(1, n)]:
        lines.append(f"• {name} — {'≥ ' if part else ''}{human_size(sz)}" + (f"  ({sz / total * 100:.0f}%)" if total else ""))
    lines.append(f"Total scanned: {human_size(total)} in {time.time() - t0:.0f}s" + (" — some folders were only partly scanned, sizes are minimums." if partial else "."))
    return items, "\n".join(lines)


def _is_dir(e) -> bool:
    try:
        return e.is_dir(follow_symlinks=False) and not _reparse(e)
    except OSError:
        return False


def big_files(root: Path, n: int, min_mb: float, budget: float) -> str:
    if not root.exists():
        return f"I can't find {root}."
    st = {"partial": False}
    heap: list = []
    seen = 0
    for path, size, mt in _walk(str(root), time.time() + budget, st):
        seen += 1
        if size >= min_mb * 1024 * 1024:
            item = (size, path, mt)
            if len(heap) < n:
                heapq.heappush(heap, item)
            elif size > heap[0][0]:
                heapq.heapreplace(heap, item)
    if not heap:
        return f"No files over {min_mb:g} MB found in {root} ({seen:,} files checked)."
    lines = [f"Largest files in {root}:"]
    for size, path, mt in sorted(heap, reverse=True):
        lines.append(f"• {human_size(size)} — {path}  (modified {datetime.fromtimestamp(mt):%Y-%m-%d})")
    lines.append(f"{seen:,} files checked" + (" — scan stopped early, there may be bigger ones." if st["partial"] else "."))
    return "\n".join(lines)


def by_type(root: Path, budget: float) -> str:
    if not root.exists():
        return f"I can't find {root}."
    st = {"partial": False}
    agg: dict = {}
    for path, size, _ in _walk(str(root), time.time() + budget, st):
        ext = os.path.splitext(path)[1].lower()
        cat = next((c for c, exts in TYPES.items() if ext in exts), "Other")
        a = agg.setdefault(cat, [0, 0])
        a[0] += size
        a[1] += 1
    total = sum(v[0] for v in agg.values()) or 1
    lines = [f"Space by file type in {root}:"]
    for cat, (sz, cnt) in sorted(agg.items(), key=lambda kv: kv[1][0], reverse=True):
        lines.append(f"• {cat} — {human_size(sz)} ({sz / total * 100:.0f}%), {cnt:,} files")
    if st["partial"]:
        lines.append("Scan stopped early, so these are minimums.")
    return "\n".join(lines)


def _junk_places() -> list:
    home = Path.home()
    if _OS == "Windows":
        la = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        return [("User temp files", Path(tempfile.gettempdir())), ("Windows temp", Path("C:/Windows/Temp")),
                ("Chrome cache", la / "Google/Chrome/User Data/Default/Cache"), ("Edge cache", la / "Microsoft/Edge/User Data/Default/Cache"),
                ("Windows Update downloads", Path("C:/Windows/SoftwareDistribution/Download")), ("pip cache", la / "pip/Cache")]
    if _OS == "Darwin":
        return [("App caches", home / "Library/Caches"), ("Trash", home / ".Trash"), ("Logs", home / "Library/Logs")]
    return [("User cache", home / ".cache"), ("Trash", home / ".local/share/Trash"), ("Temp files", Path(tempfile.gettempdir()))]


def junk() -> str:
    lines = ["Junk and cache I could clean:"]
    total = 0
    for label, path in _junk_places():
        if path.exists():
            st = {"partial": False}
            sz = _size(str(path), time.time() + 6, st)
            total += sz
            lines.append(f"• {label} — {'≥ ' if st['partial'] else ''}{human_size(sz)}")
    lines.append(f"Roughly {human_size(total)} in total. Say 'clean my temp files' and I'll ask you to confirm.")
    return "\n".join(lines)


def _clean_temp() -> str:
    cutoff = time.time() - 86400
    freed = removed = 0
    root = tempfile.gettempdir()
    for path, size, mt in list(_walk(root, time.time() + 40, {"partial": False})):
        if mt < cutoff:
            try:
                os.remove(path)
                freed += size
                removed += 1
            except OSError:
                pass
    for dirpath, dirs, files in os.walk(root, topdown=False):
        for d in dirs:
            try:
                os.rmdir(os.path.join(dirpath, d))
            except OSError:
                pass
    return f"Removed {removed:,} old temp files and freed {human_size(freed)}."


def storage_analyzer(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "analyze").lower().strip()
    budget = max(5.0, min(90.0, float(p.get("seconds") or 25)))
    n = max(1, min(30, int(p.get("count") or 8)))
    try:
        if action in ("overview", "drives", "free", "free_space"):
            text = overview()
        elif action in ("analyze", "what_is_using", "summary"):
            root = _start(p)
            log(f"[Storage] Scanning {root}…", player)
            _, tf = top_folders(root, n, budget)
            text = overview() + "\n\n" + tf
        elif action in ("top_folders", "folders"):
            log("[Storage] Scanning folders…", player)
            _, text = top_folders(_start(p), n, budget)
        elif action in ("big_files", "largest", "files"):
            text = big_files(_start(p), n, float(p.get("min_mb") or 100), budget)
        elif action in ("by_type", "types"):
            text = by_type(_start(p), budget)
        elif action in ("junk", "cache", "temp"):
            text = junk()
        elif action in ("clean", "clean_temp"):
            from core import confirm
            return confirm.request("clean_temp", "Delete old temporary files",
                                   f"Removes temp files older than 1 day from {tempfile.gettempdir()}. Nothing else is touched.", _clean_temp)
        else:
            return "Unknown action. Available: analyze, overview, top_folders, big_files, by_type, junk, clean."
    except ImportError as e:
        return f"Sir, I need the '{e.name}' package: pip install {e.name}"
    except Exception as e:
        return f"Storage check failed: {e}"
    if player is not None and hasattr(player, "show_content"):
        try:
            player.show_content("STORAGE", text)
        except Exception:
            pass
    return text


TOOL = {
    "name": "storage_analyzer",
    "description": (
        "Checks disk storage. Shows free/used space per drive, finds which folders, files or file types take the most "
        "space, estimates junk and cache, and can clean old temp files (asks for confirmation on screen). "
        "Use when the user asks what is using their storage/disk space, how much space is left, what the biggest "
        "files are, or wants to free up space. Runs only when asked."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "analyze | overview | top_folders | big_files | by_type | junk | clean"},
            "path": {"type": "STRING", "description": "Folder or drive to scan (default: the user's home folder; 'drive' = whole system drive)"},
            "count": {"type": "INTEGER", "description": "How many results (default 8)"},
            "min_mb": {"type": "NUMBER", "description": "Minimum file size in MB for big_files (default 100)"},
            "seconds": {"type": "NUMBER", "description": "Scan time limit, 5-90 s (default 25)"},
        },
    },
    "handler": storage_analyzer,
}

# by ASDcuber521
