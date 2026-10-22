from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"
CONFIG_DIR = BASE_DIR / "config"
BACKUP_DIR = CONFIG_DIR / "update_backups"
MANIFEST = CONFIG_DIR / ".install_manifest.json"
DEFAULT_REPO = "ASDprogrammer521/Jarvis-ai"
OLD_DEFAULTS = {"asdcuber/jarvis-ai", "asdcuber521/jarvis-ai"}
PROTECTED_TOP = {"config", ".git", ".github", "__pycache__", ".venv", "venv", "build", "dist"}
PROTECTED_SUFFIXES = {".json", ".db", ".sqlite", ".log", ".env", ".pyc"}
LEGACY_FILES = ["ui.py", "ui_fx.py", "ui_geo.py", "ui_metrics.py", "ui_panels.py", "ui_theme.py", "ui_widgets.py"]


def get_local_version() -> str:
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:
        pass
    return "0.0.0"


def _clean_repo(repo: str) -> str:
    repo = (repo or "").strip()
    for p in ("https://github.com/", "http://github.com/", "github.com/"):
        if repo.lower().startswith(p):
            repo = repo[len(p):]
    repo = repo.strip("/").removesuffix(".git")
    return repo if repo.count("/") == 1 else ""


def get_repo() -> str:
    try:
        from memory.config_manager import load_api_keys
        repo = _clean_repo(load_api_keys().get("github_repo") or "")
        if repo and repo.lower() not in OLD_DEFAULTS:
            return repo
    except Exception:
        pass
    return DEFAULT_REPO


def save_repo(repo: str) -> None:
    from memory.config_manager import _patch_config
    clean = _clean_repo(repo)
    if not clean:
        raise ValueError("Use the form owner/name")
    _patch_config(github_repo=clean)


def _http_json(url: str, timeout: int = 15):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Jarvis-Updater"}
    try:
        from memory.config_manager import load_api_keys
        tok = (load_api_keys().get("github_token") or "").strip()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
    except Exception:
        pass
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_bytes(url: str, timeout: int = 180) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Jarvis-Updater"}), timeout=timeout) as resp:
        return resp.read()


def _is_semver(v: str) -> bool:
    parts = str(v).lstrip("vV").split(".")
    return len(parts) >= 2 and all(p.isdigit() for p in parts[:3] if p)


def _norm(v: str):
    nums = []
    for p in str(v).lstrip("vV").split("+")[0].split("-")[0].split(".")[:3]:
        nums.append(int(p) if p.isdigit() else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _version_newer(remote: str, local: str) -> bool:
    if _is_semver(remote) and _is_semver(local):
        return _norm(remote) > _norm(local)
    return remote != local


def check_for_updates() -> dict:
    repo, local = get_repo(), get_local_version()
    base = {"ok": False, "update_available": False, "local_version": local, "remote_version": "?", "repo": repo,
            "html_url": f"https://github.com/{repo}/releases/latest", "frozen": FROZEN, "notes": ""}
    try:
        try:
            rel = _http_json(f"https://api.github.com/repos/{repo}/releases/latest")
            if isinstance(rel, dict) and rel.get("tag_name"):
                remote = str(rel["tag_name"]).lstrip("vV")
                avail = _version_newer(remote, local)
                return {**base, "ok": True, "update_available": avail, "remote_version": remote,
                        "branch": rel.get("target_commitish") or "main", "html_url": rel.get("html_url") or base["html_url"],
                        "notes": (rel.get("body") or "").strip()[:400],
                        "message": f"Update available: {local} → {remote}" if avail else f"Already up to date ({local}).",
                        "zip_url": rel.get("zipball_url") or f"https://api.github.com/repos/{repo}/zipball/{rel['tag_name']}"}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        info = _http_json(f"https://api.github.com/repos/{repo}")
        branch = info.get("default_branch") or "main"
        remote = local
        try:
            remote = _http_bytes(f"https://raw.githubusercontent.com/{repo}/{branch}/VERSION", 15).decode("utf-8").strip() or local
        except Exception:
            c = _http_json(f"https://api.github.com/repos/{repo}/commits/{branch}")
            if isinstance(c, dict):
                remote = (c.get("sha") or "")[:7] or local
        avail = _version_newer(remote, local)
        return {**base, "ok": True, "update_available": avail, "remote_version": remote, "branch": branch,
                "message": f"Update available: {local} → {remote}" if avail else f"Already up to date ({local}).",
                "zip_url": f"https://api.github.com/repos/{repo}/zipball/{branch}"}
    except urllib.error.HTTPError as e:
        why = "repository or release not found" if e.code == 404 else "rate limit reached, try later" if e.code == 403 else f"HTTP {e.code}"
        return {**base, "message": f"GitHub error: {why}. Repo: {repo}"}
    except Exception as e:
        return {**base, "message": f"Update check failed: {e}"}


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for m in zf.infolist():
        target = (dest / m.filename).resolve()
        if root != target and root not in target.parents:
            raise ValueError(f"unsafe path in update archive: {m.filename}")
    zf.extractall(dest)


def _find_root(extracted: Path) -> Path:
    for depth in (0, 1, 2):
        for p in sorted(extracted.glob("/".join(["*"] * depth) + ("/main.py" if depth else "main.py"))):
            return p.parent
    raise ValueError("this archive does not contain Jarvis (main.py not found)")


def _tracked_files(root: Path) -> list:
    out = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if rel.split("/")[0] in PROTECTED_TOP or "__pycache__" in rel.split("/"):
                continue
            out.append(rel)
    return sorted(out)


def _is_user_data(rel: str, dest_exists: bool) -> bool:
    if not dest_exists or rel == "VERSION":
        return False
    suffix, top = Path(rel).suffix.lower(), rel.split("/")[0]
    if suffix in {".db", ".sqlite", ".log", ".env", ".pyc"}:
        return True
    return suffix == ".json" and (top == "memory" or "/" not in rel)


def _hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest() if path.exists() else ""


def _make_backup(old_version: str, overwrite: list, delete: list, added: list) -> Path | None:
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        zp = BACKUP_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_v{old_version}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in overwrite + delete:
                f = BASE_DIR / rel
                if f.is_file():
                    z.write(f, rel)
            z.writestr("__added__.json", json.dumps(added))
        for old in sorted(BACKUP_DIR.glob("*.zip"))[:-3]:
            old.unlink(missing_ok=True)
        return zp
    except Exception:
        return None


def apply_update(zip_url: str | None = None, install_requirements: bool = True) -> dict:
    info = check_for_updates()
    if not info.get("ok"):
        return info
    if FROZEN:
        return {"ok": True, "manual": True, "open_url": info["html_url"], "remote_version": info.get("remote_version"),
                "message": f"This is the packaged app, so I can't patch it in place. Download {info.get('remote_version')} from the release page."}
    url = zip_url or info.get("zip_url")
    if not url:
        return {"ok": False, "message": "No download URL."}
    try:
        data = _http_bytes(url)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "update.zip").write_bytes(data)
            ex = tmp_path / "x"
            ex.mkdir()
            with zipfile.ZipFile(tmp_path / "update.zip") as zf:
                _safe_extract(zf, ex)
            src = _find_root(ex)
            new_files = _tracked_files(src)
            old = json.loads(MANIFEST.read_text(encoding="utf-8")).get("files", []) if MANIFEST.exists() else []
            req_before = _hash(BASE_DIR / "requirements.txt")
            to_write, added = [], []
            for rel in new_files:
                dest = BASE_DIR / rel
                if _is_user_data(rel, dest.exists()):
                    continue
                if not dest.exists():
                    added.append(rel)
                elif _hash(dest) == _hash(src / rel):
                    continue
                to_write.append(rel)
            gone = [r for r in old if r not in new_files and (BASE_DIR / r).is_file()
                    and Path(r).suffix.lower() not in PROTECTED_SUFFIXES and r.split("/")[0] not in PROTECTED_TOP]
            if (src / "ui" / "__init__.py").exists() or (BASE_DIR / "ui" / "__init__.py").exists():
                gone += [f for f in LEGACY_FILES if (BASE_DIR / f).is_file() and f not in new_files and f not in gone]
            backup = _make_backup(get_local_version(), [r for r in to_write if r not in added], gone, added)
            for rel in to_write:
                dest = BASE_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / rel, dest)
            for rel in gone:
                (BASE_DIR / rel).unlink(missing_ok=True)
            vsrc = src / "VERSION"
            if vsrc.exists():
                shutil.copy2(vsrc, VERSION_FILE)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps({"version": info.get("remote_version"), "files": new_files}), encoding="utf-8")
        note = ""
        if _hash(BASE_DIR / "requirements.txt") != req_before:
            note = _install_requirements() if install_requirements else " Dependencies changed — run: pip install -r requirements.txt"
        return {"ok": True, "remote_version": info.get("remote_version"), "files_changed": len(to_write), "files_removed": len(gone),
                "backup": str(backup) if backup else "", "message": f"Updated to {info.get('remote_version', '?')} ({len(to_write)} files changed). Restart Jarvis to apply.{note}"}
    except Exception as e:
        return {"ok": False, "message": f"Update failed: {e}"}


def _install_requirements() -> str:
    req = BASE_DIR / "requirements.txt"
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req), "--disable-pip-version-check", "-q"],
                           capture_output=True, text=True, timeout=900)
        if r.returncode == 0:
            return " New dependencies were installed."
        return " Some dependencies failed to install — run: pip install -r requirements.txt"
    except Exception:
        return " Dependencies changed — run: pip install -r requirements.txt"


def rollback_update() -> dict:
    zips = sorted(BACKUP_DIR.glob("*.zip")) if BACKUP_DIR.exists() else []
    if not zips:
        return {"ok": False, "message": "There is no update backup to restore."}
    zp = zips[-1]
    try:
        with zipfile.ZipFile(zp) as z:
            names = [n for n in z.namelist() if n != "__added__.json"]
            added = json.loads(z.read("__added__.json")) if "__added__.json" in z.namelist() else []
            for n in names:
                target = (BASE_DIR / n).resolve()
                if BASE_DIR.resolve() not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(n))
        for rel in added:
            if Path(rel).suffix.lower() not in PROTECTED_SUFFIXES:
                (BASE_DIR / rel).unlink(missing_ok=True)
        ver = zp.stem.split("_v")[-1]
        VERSION_FILE.write_text(ver, encoding="utf-8")
        zp.unlink(missing_ok=True)
        MANIFEST.unlink(missing_ok=True)
        return {"ok": True, "message": f"Restored version {ver}. Restart Jarvis to apply."}
    except Exception as e:
        return {"ok": False, "message": f"Rollback failed: {e}"}

# by ASDcuber521
