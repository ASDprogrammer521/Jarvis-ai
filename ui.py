from __future__ import annotations
"""Bootstrap: assemble ui from ui_data/part_*.pytxt then exec as this module."""
from pathlib import Path
import sys

_here = Path(__file__).resolve().parent
_parts = sorted((_here / "ui_data").glob("part_*.pytxt"))
if not _parts:
    raise ImportError("Missing ui_data/part_*.pytxt")
_src = "".join(p.read_text(encoding="utf-8") for p in _parts)
_ns = globals()
_ns["__file__"] = str(_here / "ui.py")
exec(compile(_src, str(_here / "ui.py"), "exec"), _ns)
