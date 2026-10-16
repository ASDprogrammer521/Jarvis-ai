from __future__ import annotations

import colorsys
import json
from pathlib import Path

from PyQt6.QtGui import QColor

DEFAULT_ACCENT = "#3d9bff"


class C:
    BG       = "#06070f"
    BG2      = "#0b0d1c"
    PANEL    = "#10132a"
    PANEL2   = "#161a38"
    BORDER   = "#262b52"
    BORDER_B = "#3a4180"
    PRI      = "#6ee7ff"
    PRI_DIM  = "#3fb6d6"
    PRI_GHO  = "#12303f"
    ACC      = "#b388ff"
    ACC2     = "#ff7ad9"
    GREEN    = "#5cffb0"
    AMBER    = "#ffc857"
    RED      = "#ff5c7a"
    TEXT     = "#eef2ff"
    TEXT_MED = "#aab3d9"
    TEXT_DIM = "#6b74a6"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(max(0, min(255, int(a))))
    return c


def rgba(h: str, a: float) -> str:
    c = QColor(h)
    return f"rgba({c.red()},{c.green()},{c.blue()},{max(0.0, min(1.0, a)):.3f})"


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(r * 255 + .5), int(g * 255 + .5), int(b * 255 + .5))


def _hsv(h: str):
    c = QColor(h)
    return colorsys.rgb_to_hsv(c.red() / 255, c.green() / 255, c.blue() / 255)


def apply_accent(hex_color: str) -> bool:
    hex_color = (hex_color or "").strip().lower()
    c = QColor(hex_color)
    if not c.isValid() or not hex_color.startswith("#") or len(hex_color) != 7:
        return False
    h, s, v = _hsv(hex_color)
    v = max(v, 0.75)
    s = max(s, 0.28) if s > 0.08 else s
    C.PRI = _hex(*colorsys.hsv_to_rgb(h, s, v))
    C.PRI_DIM = _hex(*colorsys.hsv_to_rgb(h, min(1, s + .1), v * .72))
    C.PRI_GHO = _hex(*colorsys.hsv_to_rgb(h, .7, .22))
    C.ACC = _hex(*colorsys.hsv_to_rgb((h + .17) % 1, max(.45, s * .8), 1.0))
    C.ACC2 = _hex(*colorsys.hsv_to_rgb((h - .13) % 1, max(.45, s * .8), 1.0))
    sat = 0.0 if s < 0.08 else 1.0
    C.BG = _hex(*colorsys.hsv_to_rgb(h, .35 * sat, .06))
    C.BG2 = _hex(*colorsys.hsv_to_rgb(h, .38 * sat, .10))
    C.PANEL = _hex(*colorsys.hsv_to_rgb(h, .40 * sat, .17))
    C.PANEL2 = _hex(*colorsys.hsv_to_rgb(h, .40 * sat, .23))
    C.BORDER = _hex(*colorsys.hsv_to_rgb(h, .38 * sat, .32))
    C.BORDER_B = _hex(*colorsys.hsv_to_rgb(h, .38 * sat, .48))
    C.TEXT_MED = _hex(*colorsys.hsv_to_rgb(h, .14 * sat, .86))
    C.TEXT_DIM = _hex(*colorsys.hsv_to_rgb(h, .24 * sat, .62))
    return True


def build_qss() -> str:
    return f"""
    QToolTip {{ background: {C.PANEL2}; color: {C.TEXT}; border: 1px solid {C.BORDER_B};
        border-radius: 8px; padding: 5px 9px; }}
    QLabel {{ background: transparent; color: {C.TEXT}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {rgba(C.TEXT_MED, .25)}; border-radius: 3px; min-height: 36px; }}
    QScrollBar::handle:vertical:hover {{ background: {rgba(C.PRI, .6)}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; }}
    QLineEdit {{ background: {rgba('#ffffff', .05)}; color: {C.TEXT}; border: 1px solid {rgba('#ffffff', .10)};
        border-radius: 12px; padding: 8px 12px; selection-background-color: {C.PRI_DIM}; }}
    QLineEdit:focus {{ border: 1px solid {C.PRI}; background: {rgba('#ffffff', .08)}; }}
    QComboBox {{ background: {rgba('#ffffff', .06)}; color: {C.TEXT}; border: 1px solid {rgba('#ffffff', .10)};
        border-radius: 10px; padding: 6px 12px; }}
    QComboBox:hover {{ border-color: {C.PRI}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER_B};
        selection-background-color: {C.PRI_GHO}; outline: none; padding: 4px; }}
    QSlider::groove:horizontal {{ height: 6px; background: {rgba('#ffffff', .10)}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {C.PRI}, stop:1 {C.ACC});
        border-radius: 3px; }}
    QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; background: {C.TEXT}; }}
    """


import sys

BUNDLE = Path(__file__).resolve().parent.parent
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else BUNDLE
ASSETS = BUNDLE / "assets"


def config_path() -> Path:
    return ROOT / "config" / "api_keys.json"


def read_cfg() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def patch_cfg(**fields) -> None:
    try:
        from memory.config_manager import _patch_config
        _patch_config(**fields)
        return
    except Exception:
        pass
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    d = read_cfg()
    d.update(fields)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")


apply_accent(DEFAULT_ACCENT)

# by ASDcuber521
