"""Helpers shared by the Developer Overlay (ui/dev_overlay.py) and the `dev_overlay` voice tool: safe git, system stats."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import psutil

# Only these git sub-commands can be run from the overlay or by voice. No shell is ever involved.
GIT_READ = {"status": ["status", "-sb"], "diff": ["diff", "--stat"], "log": ["log", "--oneline", "--graph", "-n", "12"],
            "branch": ["branch", "-vv"], "fetch": ["fetch", "--prune"], "stash list": ["stash", "list"]}
GIT_WRITE = {"pull": ["pull", "--ff-only"], "push": ["push"], "stash": ["stash", "push", "-u"], "stash pop": ["stash", "pop"]}
OUT_LIMIT = 6000


def get_repo() -> Path | None:
    from memory.config_manager import load_api_keys
    p = load_api_keys().get("dev_repo")
    return Path(p) if p and Path(p).is_dir() else None


def set_repo(path: str) -> str:
    p = Path(path).expanduser()
    if not p.is_dir():
        return f"'{path}' is not a folder."
    top = _git(p, ["rev-parse", "--show-toplevel"])
    if top[0] != 0:
        return f"'{path}' is not inside a git repository."
    from memory.config_manager import _patch_config
    _patch_config(dev_repo=top[1].strip())
    return f"Repository set to {top[1].strip()}."


def _git(repo: Path, args: list[str], timeout: float = 25.0) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    except FileNotFoundError:
        return 127, "git is not installed or not on PATH."
    except subprocess.TimeoutExpired:
        return 124, f"git {' '.join(args[:2])} timed out after {timeout:.0f}s."
    out = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()
    return r.returncode, out[:OUT_LIMIT] or "(no output)"


def run_git(command: str, message: str = "") -> str:
    repo = get_repo()
    if repo is None:
        return "No repository selected yet. Set one first."
    cmd = (command or "status").strip().lower()
    if cmd == "commit":
        msg = (message or "").strip()
        if not msg:
            return "A commit needs a message."
        code, out = _git(repo, ["add", "-A"])
        if code == 0:
            code, out = _git(repo, ["commit", "-m", msg[:200]])
        return out
    args = GIT_READ.get(cmd) or GIT_WRITE.get(cmd)
    if args is None:
        return "Allowed git commands: " + ", ".join([*GIT_READ, *GIT_WRITE, "commit"]) + "."
    return _git(repo, args, timeout=60.0 if cmd in ("pull", "push", "fetch") else 25.0)[1]


def branch_info() -> tuple[str, int]:
    """(branch name, number of changed files) — ('', 0) when there is no repository."""
    repo = get_repo()
    if repo is None:
        return "", 0
    code, br = _git(repo, ["symbolic-ref", "--short", "HEAD"], 5)          # works before the first commit too
    if code != 0:
        code, br = _git(repo, ["rev-parse", "--short", "HEAD"], 5)         # detached HEAD
        if code != 0:
            return "", 0
        br = "detached@" + br
    code, st = _git(repo, ["status", "--porcelain"], 5)
    n = 0 if code != 0 or st == "(no output)" else len([ln for ln in st.splitlines() if ln.strip()])
    return br.strip(), n


def system_stats() -> dict:
    gpu = -1.0
    try:
        from core.system_monitor import _nvml_gpu
        gpu = float(_nvml_gpu())
    except Exception:
        pass
    vm = psutil.virtual_memory()
    return {"cpu": psutil.cpu_percent(None), "ram": vm.percent, "ram_used_gb": vm.used / 2**30,
            "ram_total_gb": vm.total / 2**30, "gpu": gpu if gpu >= 0 else None}


def clipboard_text(limit: int = 4000) -> str:
    try:
        import pyperclip
        return (pyperclip.paste() or "")[:limit]
    except Exception:
        return ""
