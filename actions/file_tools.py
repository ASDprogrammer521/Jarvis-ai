from __future__ import annotations

import hashlib
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from actions._common import human_size, log, output_dir

CATS = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".tif", ".tiff"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".md", ".odt", ".rtf"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".iso"},
    "Installers": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".apk"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".cpp", ".c", ".cs", ".sql"},
}


def _folder(p: dict, default: str = "Downloads") -> Path:
    raw = str(p.get("path") or "").strip().strip('"')
    if not raw or raw.lower() == default.lower():
        return Path.home() / default
    low = raw.lower()
    for name in ("downloads", "documents", "desktop", "pictures", "videos", "music"):
        if low == name:
            return Path.home() / name.title()
    return Path(raw).expanduser()


def _hash(path: str, limit: int | None = None) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        if limit:
            h.update(f.read(limit))
        else:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def find_duplicates(root: Path, min_mb: float, budget: float) -> tuple:
    deadline = time.time() + budget
    by_size: dict = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            fp = os.path.join(dirpath, f)
            try:
                if os.path.islink(fp):
                    continue
                sz = os.path.getsize(fp)
            except OSError:
                continue
            if sz >= max(1, min_mb * 1024 * 1024):
                by_size.setdefault(sz, []).append(fp)
        if time.time() > deadline:
            break
    groups, partial = [], time.time() > deadline
    for sz, paths in by_size.items():
        if len(paths) < 2:
            continue
        pre: dict = {}
        for fp in paths:
            try:
                pre.setdefault(_hash(fp, 65536), []).append(fp)
            except OSError:
                pass
        for cand in pre.values():
            if len(cand) < 2:
                continue
            full: dict = {}
            for fp in cand:
                if time.time() > deadline + 20:
                    partial = True
                    break
                try:
                    full.setdefault(_hash(fp), []).append(fp)
                except OSError:
                    pass
            groups += [(sz, g) for g in full.values() if len(g) > 1]
    groups.sort(key=lambda x: x[0] * (len(x[1]) - 1), reverse=True)
    return groups, partial


def _report_dups(root: Path, groups: list, partial: bool) -> str:
    if not groups:
        return f"No duplicate files found in {root}."
    wasted = sum(sz * (len(g) - 1) for sz, g in groups)
    lines = [f"Found {len(groups)} sets of identical files in {root} — {human_size(wasted)} could be freed."]
    for sz, g in groups[:8]:
        lines.append(f"• {human_size(sz)} × {len(g)}: " + "  =  ".join(os.path.basename(x) for x in g[:3]))
    if partial:
        lines.append("The scan was cut short, there may be more.")
    lines.append("Say 'remove the duplicates' and I'll move the extra copies to a safe folder (you can undo).")
    return "\n".join(lines)


def remove_duplicates(root: Path, groups: list) -> str:
    from core.undo import push_undo
    dest = output_dir("Duplicates") / datetime.now().strftime("%Y%m%d_%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    moved: list = []
    freed = 0
    for sz, g in groups:
        keep = min(g, key=lambda x: os.path.getmtime(x))
        for fp in g:
            if fp == keep:
                continue
            target = dest / f"{len(moved):04d}_{os.path.basename(fp)}"
            try:
                shutil.move(fp, target)
                moved.append((str(target), fp))
                freed += sz
            except OSError:
                pass

    def undo():
        n = 0
        for src, orig in moved:
            try:
                shutil.move(src, orig)
                n += 1
            except OSError:
                pass
        return f"Restored {n} files."
    if moved:
        push_undo(f"removed {len(moved)} duplicate files", undo)
    return f"Moved {len(moved)} duplicate files ({human_size(freed)}) to {dest}. Say 'undo' to put them back."


def organize(root: Path, preview: bool) -> str:
    if not root.exists():
        return f"I can't find {root}."
    plan = []
    now = time.time()
    for f in root.iterdir():
        if not f.is_file() or f.name.startswith(".") or now - f.stat().st_mtime < 600:
            continue
        ext = f.suffix.lower()
        cat = next((c for c, e in CATS.items() if ext in e), "Other")
        plan.append((f, cat))
    if not plan:
        return f"Nothing to organize in {root}, sir."
    counts: dict = {}
    for _, c in plan:
        counts[c] = counts.get(c, 0) + 1
    summary = ", ".join(f"{c}: {n}" for c, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    if preview:
        return f"I would sort {len(plan)} files in {root} into folders — {summary}. Say 'organize it' to do it (you can undo)."
    from core.undo import push_undo
    moved = []
    for f, cat in plan:
        d = root / cat
        d.mkdir(exist_ok=True)
        t = d / f.name
        i = 1
        while t.exists():
            t = d / f"{f.stem} ({i}){f.suffix}"
            i += 1
        try:
            shutil.move(str(f), str(t))
            moved.append((str(t), str(f)))
        except OSError:
            pass

    def undo():
        n = 0
        for src, orig in moved:
            try:
                shutil.move(src, orig)
                n += 1
            except OSError:
                pass
        return f"Moved {n} files back."
    if moved:
        push_undo(f"organized {len(moved)} files in {root.name}", undo)
    return f"Organized {len(moved)} files in {root} — {summary}. Say 'undo' to restore them."


def file_tools(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "duplicates").lower().strip()
    try:
        if action in ("duplicates", "find_duplicates", "remove_duplicates"):
            root = _folder(p, "Downloads")
            if not root.exists():
                return f"I can't find {root}."
            log(f"[Files] Looking for duplicates in {root}…", player)
            groups, partial = find_duplicates(root, float(p.get("min_mb") or 1), float(p.get("seconds") or 30))
            if action == "remove_duplicates" or p.get("remove"):
                return remove_duplicates(root, groups) if groups else f"No duplicates in {root}."
            text = _report_dups(root, groups, partial)
            if player is not None and hasattr(player, "show_content"):
                player.show_content("DUPLICATE FILES", text)
            return text
        if action in ("organize", "sort", "tidy"):
            return organize(_folder(p, "Downloads"), bool(p.get("preview")))
    except Exception as e:
        return f"File tool failed: {e}"
    return "Unknown action. Available: duplicates, remove_duplicates, organize."


TOOL = {
    "name": "file_tools",
    "description": (
        "File housekeeping. Finds identical duplicate files in a folder and shows how much space they waste, moves the "
        "extra copies to a safe folder (undoable), and sorts a messy folder such as Downloads into Images, Videos, "
        "Documents, Archives, Installers… (undoable). Use for 'find duplicate files', 'clean up my downloads', 'organize my Downloads folder'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "duplicates | remove_duplicates | organize"},
            "path": {"type": "STRING", "description": "Folder (default Downloads); 'Documents', 'Desktop' or a full path also work"},
            "min_mb": {"type": "NUMBER", "description": "Ignore files smaller than this many MB (default 1)"},
            "preview": {"type": "BOOLEAN", "description": "organize: only show the plan, don't move anything"},
        },
    },
    "handler": file_tools,
}

# by ASDcuber521
