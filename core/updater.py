"""
GitHub self-update for Jarvis.

Checks a public GitHub repository for a newer VERSION (or latest commit),
downloads the zipball, and replaces project files (keeps config/ and memory data).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"
DEFAULT_REPO = "ASDcuber/Jarvis-ai"  # owner/name — change in Settings / config


def get_local_version() -> str:
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:
        pass
    return "0.0.0"


def get_repo() -> str:
    """owner/repo from config, or DEFAULT_REPO."""
    try:
        from memory.config_manager import load_api_keys
        repo = (load_api_keys().get("github_repo") or "").strip()
        if repo:
            # accept full URL or owner/repo
            repo = repo.replace("https://github.com/", "").replace("http://github.com/", "")
            repo = repo.strip("/").removesuffix(".git")
            if repo.count("/") == 1:
                return repo
    except Exception:
        pass
    return DEFAULT_REPO


def save_repo(repo: str) -> None:
    from memory.config_manager import load_api_keys, ensure_config_dir, CONFIG_FILE
    ensure_config_dir()
    data = load_api_keys()
    clean = repo.replace("https://github.com/", "").replace("http://github.com/", "")
    clean = clean.strip("/").removesuffix(".git")
    data["github_repo"] = clean
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _http_json(url: str, timeout: int = 15) -> dict | list:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Jarvis-Updater",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check_for_updates() -> dict:
    """
    Returns:
      {
        ok, update_available, local_version, remote_version,
        repo, branch, message, commit_sha (optional)
      }
    """
    repo = get_repo()
    local = get_local_version()
    try:
        # Prefer releases
        try:
            rel = _http_json(f"https://api.github.com/repos/{repo}/releases/latest")
            if isinstance(rel, dict) and rel.get("tag_name"):
                remote = str(rel["tag_name"]).lstrip("v")
                available = _version_newer(remote, local)
                return {
                    "ok": True,
                    "update_available": available,
                    "local_version": local,
                    "remote_version": remote,
                    "repo": repo,
                    "branch": rel.get("target_commitish") or "main",
                    "message": (
                        f"Update available: {local} → {remote}"
                        if available else
                        f"Already up to date ({local})."
                    ),
                    "zip_url": rel.get("zipball_url")
                    or f"https://api.github.com/repos/{repo}/zipball/{rel.get('tag_name')}",
                }
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

        # Fallback: default branch latest commit + VERSION file on that branch
        repo_info = _http_json(f"https://api.github.com/repos/{repo}")
        branch = repo_info.get("default_branch") or "main"
        # VERSION file raw
        remote = local
        try:
            raw = _http_bytes(
                f"https://raw.githubusercontent.com/{repo}/{branch}/VERSION"
            )
            remote = raw.decode("utf-8").strip() or local
        except Exception:
            # use short commit sha as remote marker
            commits = _http_json(
                f"https://api.github.com/repos/{repo}/commits/{branch}"
            )
            if isinstance(commits, dict):
                remote = (commits.get("sha") or "")[:7] or local

        available = remote != local and _version_newer(remote, local) if _is_semver(remote) and _is_semver(local) else (remote != local)
        return {
            "ok": True,
            "update_available": available,
            "local_version": local,
            "remote_version": remote,
            "repo": repo,
            "branch": branch,
            "message": (
                f"Update available: {local} → {remote}"
                if available else
                f"Already up to date ({local})."
            ),
            "zip_url": f"https://api.github.com/repos/{repo}/zipball/{branch}",
        }
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "update_available": False,
            "local_version": local,
            "remote_version": "?",
            "repo": repo,
            "message": f"GitHub error HTTP {e.code}. Check repo name: {repo}",
        }
    except Exception as e:
        return {
            "ok": False,
            "update_available": False,
            "local_version": local,
            "remote_version": "?",
            "repo": repo,
            "message": f"Update check failed: {e}",
        }


def apply_update(zip_url: str | None = None) -> dict:
    """
    Download zipball and merge into BASE_DIR.
    Preserves: config/, user memory files, local .env-style secrets.
    """
    info = check_for_updates()
    if not info.get("ok"):
        return info
    url = zip_url or info.get("zip_url")
    if not url:
        return {"ok": False, "message": "No download URL."}

    preserve = {"config", "__pycache__", ".git"}
    preserve_files = {"api_keys.json"}

    try:
        data = _http_bytes(url)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zpath = tmp_path / "update.zip"
            zpath.write_bytes(data)
            extract_to = tmp_path / "extracted"
            extract_to.mkdir()
            with zipfile.ZipFile(zpath, "r") as zf:
                zf.extractall(extract_to)
            # GitHub zipball has a single top-level folder
            roots = [p for p in extract_to.iterdir() if p.is_dir()]
            src_root = roots[0] if len(roots) == 1 else extract_to

            for item in src_root.iterdir():
                name = item.name
                if name in preserve:
                    continue
                dest = BASE_DIR / name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    shutil.copytree(item, dest)
                else:
                    if name in preserve_files:
                        continue
                    shutil.copy2(item, dest)

            # Write VERSION if present in package
            vsrc = src_root / "VERSION"
            if vsrc.exists():
                shutil.copy2(vsrc, VERSION_FILE)

        return {
            "ok": True,
            "message": (
                f"Updated to {info.get('remote_version', '?')}. "
                "Restart Jarvis to apply."
            ),
            "remote_version": info.get("remote_version"),
        }
    except Exception as e:
        return {"ok": False, "message": f"Update failed: {e}"}


def _is_semver(v: str) -> bool:
    parts = v.lstrip("v").split(".")
    return len(parts) >= 2 and all(p.isdigit() for p in parts[:3] if p)


def _version_newer(remote: str, local: str) -> bool:
    def norm(v: str):
        v = v.lstrip("v").split("+")[0]
        nums = []
        for p in v.split(".")[:3]:
            try:
                nums.append(int(p))
            except ValueError:
                nums.append(0)
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums)

    if _is_semver(remote) and _is_semver(local):
        return norm(remote) > norm(local)
    return remote != local
