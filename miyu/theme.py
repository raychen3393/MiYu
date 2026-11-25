"""
密语 · 主题(Apple 风格)
七套主题:浅色 / 樱花 / 黄昏 / 紫夜 / 深海 / 深色 / 纯黑。每套都有一张渐变"壁纸":
大片柔和的光晕铺开(不挤在角落)、一两道斜着的环境光、四周轻微压暗,再撒一层极淡的颗粒,看起来像磨砂玻璃。
面板都是半透明的,壁纸透过来;Windows 11 上再叠加系统的亚克力模糊。

个性化(CUSTOM):主题色、我的气泡颜色、面板透明度、自定义背景图(可调暗、可模糊)。
套用主题时先取预设,再叠加个性化设置。

T 是当前主题的颜色表,切换时原地更新,界面各处直接读 T。
"""
from __future__ import annotations

import math
import re
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPalette, QPixmap, QRadialGradient,
)

LIGHT = {
    "name": "light", "label": "浅色", "dark_ui": False,
    "bg": "#F3F5FA",
    "chat": "rgba(255,255,255,0.20)", "side": "rgba(255,255,255,0.46)", "header": "rgba(255,255,255,0.62)",
    "ring": "#F4F6FB",
    "card": "#FFFFFF", "card_glass": "rgba(255,255,255,0.86)",
    "pill": "rgba(255,255,255,0.92)",
    "line": "rgba(0,0,0,0.08)", "line_strong": "rgba(0,0,0,0.14)",
    "hover": "rgba(255,255,255,0.55)", "select": "rgba(0,0,0,0.07)",
    "text": "#1D1D1F", "sub": "#5E5E66", "faint": "#8E8E96",
    "accent": "#007AFF", "accent_hover": "#0066D6", "on_accent": "#FFFFFF",
    "mine": "#007AFF", "other": "#FFFFFF",
    "system_bg": "rgba(255,255,255,0.62)",
    "good": "#34C759", "warn": "#FF9500", "bad": "#FF3B30",
    "burn": "#FF9500", "burn_line": "rgba(255,149,0,0.70)",
    "badge": "#007AFF", "online": "#34C759", "offline": "#C7C7CC",
    "scroll": "rgba(0,0,0,0.18)",
    "icon": "#5E5E66", "icon_active": "#1D1D1F",
    "btn2": "rgba(0,0,0,0.05)", "btn2_hover": "rgba(0,0,0,0.085)",
    "shadow": (40, 50, 80, 34),
    # 壁纸:底色渐变(从左上到右下)+ 几团光晕 (x, y, 半径, 颜色, 不透明度)
    "wall": {
        "stops": [(0.0, "#E5ECFB"), (0.5, "#F1EDF7"), (1.0, "#F9EEE7")],
        "blobs": [(0.10, 0.10, 0.78, "#9DB7FF", 0.46), (0.92, 0.12, 0.72, "#CDB6FF", 0.42),
                  (0.86, 0.95, 0.78, "#FFC2A0", 0.40), (0.10, 0.92, 0.66, "#A8E6CF", 0.34),
                  (0.50, 0.45, 0.58, "#E6D8FF", 0.30), (0.34, 0.72, 0.50, "#FFD9E8", 0.24)],
        "beams": [(-32, 0.55, 0.45, 0.24, "#FFFFFF", 0.32)],
        "grain": 0.022,
    },
}

DUSK = {
    "name": "dusk", "label": "黄昏", "dark_ui": True,
    "bg": "#2A1C33",
    "chat": "rgba(30,18,38,0.22)", "side": "rgba(30,18,38,0.42)", "header": "rgba(36,22,44,0.58)",
    "ring": "#36233F",
    "card": "#33233C", "card_glass": "rgba(51,35,60,0.88)",
    "pill": "rgba(255,255,255,0.10)",
    "line": "rgba(255,235,220,0.12)", "line_strong": "rgba(255,235,220,0.20)",
    "hover": "rgba(255,240,230,0.07)", "select": "rgba(255,240,230,0.14)",
    "text": "#FFF4EC", "sub": "#D9C3BC", "faint": "#A68E94",
    "accent": "#EE8466", "accent_hover": "#F59A7E", "on_accent": "#FFFFFF",
    "mine": "#E07A5F", "other": "rgba(255,245,238,0.15)",
    "system_bg": "rgba(40,22,48,0.45)",
    "good": "#8FD9A8", "warn": "#FFC078", "bad": "#FF8A7A",
    "burn": "#FFC078", "burn_line": "rgba(255,192,120,0.75)",
    "badge": "#EE8466", "online": "#8FD9A8", "offline": "#7A6370",
    "scroll": "rgba(255,235,220,0.25)",
    "icon": "#E3CEC6", "icon_active": "#FFF4EC",
    "btn2": "rgba(255,240,230,0.10)", "btn2_hover": "rgba(255,240,230,0.17)",
    "shadow": (20, 6, 20, 120),
    "wall": {
        "stops": [(0.0, "#1F1838"), (0.45, "#45285A"), (0.80, "#74405E"), (1.0, "#9E5852")],
        "blobs": [(0.85, 0.92, 0.78, "#FF9A5C", 0.36), (0.15, 0.72, 0.70, "#E2588C", 0.28),
                  (0.82, 0.12, 0.66, "#6A5BD6", 0.32), (0.50, 1.05, 0.62, "#FFC46B", 0.22),
                  (0.18, 0.08, 0.62, "#3A4596", 0.34), (0.50, 0.50, 0.56, "#B5607A", 0.20)],
        "beams": [(-35, 0.60, 0.40, 0.18, "#FFC9A8", 0.10)],
        "vignette": 0.22, "grain": 0.03,
    },
}

DARK = {
    "name": "dark", "label": "深色", "dark_ui": True,
    "bg": "#121419",
    "chat": "rgba(14,16,22,0.16)", "side": "rgba(16,18,24,0.42)", "header": "rgba(16,18,24,0.58)",
    "ring": "#181B22",
    "card": "#22252C", "card_glass": "rgba(34,37,44,0.88)",
    "pill": "rgba(255,255,255,0.08)",
    "line": "rgba(255,255,255,0.09)", "line_strong": "rgba(255,255,255,0.16)",
    "hover": "rgba(255,255,255,0.05)", "select": "rgba(255,255,255,0.10)",
    "text": "#F5F5F7", "sub": "#A1A1A8", "faint": "#6C6C74",
    "accent": "#0A84FF", "accent_hover": "#3395FF", "on_accent": "#FFFFFF",
    "mine": "#0A84FF", "other": "rgba(58,58,64,0.82)",
    "system_bg": "rgba(20,22,28,0.55)",
    "good": "#30D158", "warn": "#FF9F0A", "bad": "#FF453A",
    "burn": "#FF9F0A", "burn_line": "rgba(255,159,10,0.70)",
    "badge": "#0A84FF", "online": "#30D158", "offline": "#48484A",
    "scroll": "rgba(255,255,255,0.22)",
    "icon": "#A1A1A8", "icon_active": "#F5F5F7",
    "btn2": "rgba(255,255,255,0.08)", "btn2_hover": "rgba(255,255,255,0.13)",
    "shadow": (0, 0, 0, 130),
    "wall": {
        "stops": [(0.0, "#0C0E15"), (0.6, "#10162A"), (1.0, "#0C1A1E")],
        "blobs": [(0.12, 0.10, 0.78, "#2F5BD0", 0.38), (0.90, 0.15, 0.72, "#6A4BD0", 0.32),
                  (0.88, 0.95, 0.78, "#1F8A8F", 0.32), (0.10, 0.95, 0.62, "#8A3A7E", 0.24),
                  (0.50, 0.52, 0.62, "#24345E", 0.28)],
        "beams": [(-30, 0.55, 0.45, 0.20, "#7FA0FF", 0.07)],
        "vignette": 0.25, "grain": 0.03,
    },
}

SAKURA = {
    "name": "sakura", "label": "樱花", "dark_ui": False,
    "bg": "#FBF1F5",
    "chat": "rgba(255,255,255,0.22)", "side": "rgba(255,255,255,0.50)", "header": "rgba(255,255,255,0.64)",
    "ring": "#FBF2F6",
    "card": "#FFFFFF", "card_glass": "rgba(255,255,255,0.88)",
    "pill": "rgba(255,255,255,0.92)",
    "line": "rgba(80,0,40,0.08)", "line_strong": "rgba(80,0,40,0.14)",
    "hover": "rgba(255,255,255,0.55)", "select": "rgba(214,51,132,0.10)",
    "text": "#2A1720", "sub": "#6E5562", "faint": "#A08A95",
    "accent": "#D9407A", "accent_hover": "#C7336C", "on_accent": "#FFFFFF",
    "mine": "#E0457F", "other": "#FFFFFF",
    "system_bg": "rgba(255,255,255,0.62)",
    "good": "#2FB574", "warn": "#F08C1A", "bad": "#E5484D",
    "burn": "#F08C1A", "burn_line": "rgba(240,140,26,0.70)",
    "badge": "#D9407A", "online": "#2FB574", "offline": "#D3C3CB",
    "scroll": "rgba(80,0,40,0.18)",
    "icon": "#6E5562", "icon_active": "#2A1720",
    "btn2": "rgba(80,0,40,0.05)", "btn2_hover": "rgba(80,0,40,0.085)",
    "shadow": (90, 20, 50, 34),
    "wall": {
        "stops": [(0.0, "#FCEEF3"), (0.5, "#F8EEF6"), (1.0, "#F3EEFB")],
        "blobs": [(0.10, 0.10, 0.78, "#FFB3C8", 0.42), (0.90, 0.15, 0.72, "#E9B8FF", 0.36),
                  (0.85, 0.92, 0.78, "#FFD0B5", 0.36), (0.12, 0.90, 0.66, "#FFC9E0", 0.34),
                  (0.50, 0.50, 0.56, "#FFFFFF", 0.30)],
        "beams": [(-32, 0.50, 0.45, 0.24, "#FFFFFF", 0.34)],
        "grain": 0.022,
    },
}

VIOLET = {
    "name": "violet", "label": "紫夜", "dark_ui": True,
    "bg": "#1A1326",
    "chat": "rgba(24,16,38,0.20)", "side": "rgba(28,18,44,0.46)", "header": "rgba(32,20,50,0.56)",
    "ring": "#221830",
    "card": "#2A2038", "card_glass": "rgba(42,32,56,0.90)",
    "pill": "rgba(255,255,255,0.08)",
    "line": "rgba(230,210,255,0.10)", "line_strong": "rgba(230,210,255,0.18)",
    "hover": "rgba(240,225,255,0.06)", "select": "rgba(200,150,255,0.16)",
    "text": "#F6F0FF", "sub": "#C7B8DC", "faint": "#8E7FA6",
    "accent": "#A855F7", "accent_hover": "#B975FA", "on_accent": "#FFFFFF",
    "mine": "#9333EA", "other": "rgba(52,40,72,0.86)",
    "system_bg": "rgba(30,20,46,0.55)",
    "good": "#4ADE80", "warn": "#FBBF24", "bad": "#FB7185",
    "burn": "#FBBF24", "burn_line": "rgba(251,191,36,0.70)",
    "badge": "#A855F7", "online": "#4ADE80", "offline": "#5B4E6E",
    "scroll": "rgba(230,210,255,0.22)",
    "icon": "#C7B8DC", "icon_active": "#F6F0FF",
    "btn2": "rgba(255,255,255,0.08)", "btn2_hover": "rgba(255,255,255,0.13)",
    "shadow": (10, 0, 30, 140),
    "wall": {
        "stops": [(0.0, "#0D0818"), (0.5, "#1B0F33"), (1.0, "#100A1F")],
        "blobs": [(0.15, 0.85, 0.82, "#7E22CE", 0.40), (0.85, 0.15, 0.72, "#9333EA", 0.32),
                  (0.55, 0.55, 0.66, "#C026D3", 0.18), (0.92, 0.92, 0.62, "#4C1D95", 0.40),
                  (0.10, 0.10, 0.58, "#312E81", 0.34)],
        "beams": [(-38, 0.42, 0.50, 0.17, "#C084FC", 0.20), (-38, 0.64, 0.38, 0.07, "#E9D5FF", 0.14)],
        "vignette": 0.30, "grain": 0.035,
    },
}

OCEAN = {
    "name": "ocean", "label": "深海", "dark_ui": True,
    "bg": "#0B1626",
    "chat": "rgba(8,18,34,0.20)", "side": "rgba(10,22,40,0.46)", "header": "rgba(12,26,46,0.56)",
    "ring": "#0F1C2E",
    "card": "#152437", "card_glass": "rgba(21,36,55,0.90)",
    "pill": "rgba(255,255,255,0.08)",
    "line": "rgba(200,225,255,0.10)", "line_strong": "rgba(200,225,255,0.18)",
    "hover": "rgba(220,235,255,0.06)", "select": "rgba(96,165,250,0.18)",
    "text": "#EEF6FF", "sub": "#A9BED6", "faint": "#6F86A0",
    "accent": "#3B82F6", "accent_hover": "#5B97F8", "on_accent": "#FFFFFF",
    "mine": "#2563EB", "other": "rgba(30,48,72,0.86)",
    "system_bg": "rgba(10,22,40,0.55)",
    "good": "#34D399", "warn": "#FBBF24", "bad": "#F87171",
    "burn": "#FBBF24", "burn_line": "rgba(251,191,36,0.70)",
    "badge": "#3B82F6", "online": "#34D399", "offline": "#4A5D74",
    "scroll": "rgba(200,225,255,0.22)",
    "icon": "#A9BED6", "icon_active": "#EEF6FF",
    "btn2": "rgba(255,255,255,0.08)", "btn2_hover": "rgba(255,255,255,0.13)",
    "shadow": (0, 8, 24, 140),
    "wall": {
        "stops": [(0.0, "#04101F"), (0.55, "#0A1E38"), (1.0, "#062031")],
        "blobs": [(0.12, 0.12, 0.78, "#1D4ED8", 0.36), (0.88, 0.18, 0.66, "#0EA5E9", 0.26),
                  (0.85, 0.92, 0.78, "#0D9488", 0.30), (0.15, 0.90, 0.62, "#1E3A8A", 0.34),
                  (0.50, 0.50, 0.62, "#155E75", 0.22)],
        "beams": [(-28, 0.50, 0.45, 0.20, "#7DD3FC", 0.09)],
        "vignette": 0.28, "grain": 0.03,
    },
}

BLACK = {
    "name": "black", "label": "纯黑", "dark_ui": True,
    "bg": "#000000",
    "chat": "rgba(0,0,0,0.30)", "side": "rgba(10,10,12,0.72)", "header": "rgba(8,8,10,0.78)",
    "ring": "#0A0A0C",
    "card": "#141416", "card_glass": "rgba(20,20,22,0.94)",
    "pill": "rgba(255,255,255,0.07)",
    "line": "rgba(255,255,255,0.08)", "line_strong": "rgba(255,255,255,0.15)",
    "hover": "rgba(255,255,255,0.05)", "select": "rgba(255,255,255,0.11)",
    "text": "#F5F5F7", "sub": "#9A9AA2", "faint": "#606068",
    "accent": "#EDEDF0", "accent_hover": "#FFFFFF", "on_accent": "#000000",
    "mine": "#2C2C2E", "on_mine": "#FFFFFF", "other": "#161618",
    "system_bg": "rgba(22,22,24,0.80)",
    "good": "#30D158", "warn": "#FF9F0A", "bad": "#FF453A",
    "burn": "#FF9F0A", "burn_line": "rgba(255,159,10,0.70)",
    "badge": "#0A84FF", "online": "#30D158", "offline": "#3A3A3C",
    "scroll": "rgba(255,255,255,0.22)",
    "icon": "#9A9AA2", "icon_active": "#F5F5F7",
    "btn2": "rgba(255,255,255,0.08)", "btn2_hover": "rgba(255,255,255,0.13)",
    "shadow": (0, 0, 0, 160),
    "wall": {
        "stops": [(0.0, "#000000"), (1.0, "#050507")],
        "blobs": [(0.15, 0.10, 0.72, "#1C1C22", 0.55), (0.88, 0.92, 0.72, "#18181C", 0.50)],
        "beams": [(-30, 0.55, 0.45, 0.18, "#FFFFFF", 0.025)],
        "grain": 0.02,
    },
}

TERMINAL = {
    "name": "terminal", "label": "极客终端", "dark_ui": True,
    "bg": "#0D1117",
    "chat": "rgba(13,17,23,0.42)", "side": "rgba(10,14,20,0.76)", "header": "rgba(13,17,23,0.82)",
    "ring": "#0D1117",
    "card": "#161B22", "card_glass": "rgba(22,27,34,0.94)",
    "pill": "rgba(255,255,255,0.06)",
    "line": "rgba(48,54,61,0.70)", "line_strong": "rgba(88,166,255,0.28)",
    "hover": "rgba(177,186,196,0.08)", "select": "rgba(46,160,67,0.18)",
    "text": "#C9D1D9", "sub": "#8B949E", "faint": "#6E7681",
    "accent": "#2EA043", "accent_hover": "#3FB950", "on_accent": "#FFFFFF",
    "mine": "#1F6FEB", "on_mine": "#FFFFFF", "other": "#161B22",
    "system_bg": "rgba(22,27,34,0.82)",
    "good": "#3FB950", "warn": "#D29922", "bad": "#F85149",
    "burn": "#D29922", "burn_line": "rgba(210,153,34,0.72)",
    "badge": "#2EA043", "online": "#3FB950", "offline": "#484F58",
    "scroll": "rgba(139,148,158,0.28)",
    "icon": "#8B949E", "icon_active": "#E6EDF3",
    "btn2": "rgba(177,186,196,0.08)", "btn2_hover": "rgba(177,186,196,0.14)",
    "shadow": (0, 0, 0, 155),
    "wall": {
        "stops": [(0.0, "#090D12"), (0.55, "#0D1117"), (1.0, "#0B1519")],
        "blobs": [(0.14, 0.12, 0.70, "#1F6FEB", 0.16), (0.86, 0.90, 0.72, "#238636", 0.16),
                  (0.50, 0.50, 0.60, "#161B22", 0.30)],
        "beams": [(-28, 0.52, 0.45, 0.16, "#58A6FF", 0.04)],
        "vignette": 0.24, "grain": 0.025,
    },
}

THEMES = {"light": LIGHT, "sakura": SAKURA, "dusk": DUSK, "violet": VIOLET, "ocean": OCEAN, "dark": DARK,
          "terminal": TERMINAL, "black": BLACK}
# 主题选择器里的小圆点颜色 和 菜单图标
THEME_SWATCH = {"light": ("#9DB7FF", "sun"), "sakura": ("#FF8FB5", "sun"), "dusk": ("#E07A5F", "sunset"),
                "violet": ("#A855F7", "moon"), "ocean": ("#3B82F6", "moon"), "dark": ("#3A3F4B", "moon"),
                "terminal": ("#2EA043", "terminal"), "black": ("#000000", "moon")}

T: dict = dict(LIGHT)
GLASS = False                # 当前是否启用 Windows 11 亚克力
GLASS_SUPPORTED = False      # 系统是否支持(Windows 11 22H2 及以上)

_RGBA = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)")


def qcolor(value: str) -> QColor:
    """支持 '#RRGGBB' 和 'rgba(r,g,b,a)'。"""
    m = _RGBA.fullmatch(value.strip())
    if m:
        r, g, b, a = m.groups()
        return QColor(int(r), int(g), int(b), max(0, min(255, int(float(a) * 255))))
    return QColor(value)


def is_dark() -> bool:
    """深色和黄昏都算"深色界面"(文字是浅色的)。"""
    return bool(T.get("dark_ui"))


def system_prefers_dark() -> bool:
    """跟随 Windows 的深色/浅色设置(Qt 6.5+),读不到就用浅色。"""
    try:
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def detect_glass_support() -> bool:
    global GLASS_SUPPORTED
    GLASS_SUPPORTED = False
    if sys.platform == "win32":
        try:
            GLASS_SUPPORTED = sys.getwindowsversion().build >= 22621
        except Exception:
            GLASS_SUPPORTED = False
    return GLASS_SUPPORTED


def setup_font(app) -> None:
    f = QFont()
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei",
                   "PingFang SC", "Noto Sans CJK SC"])
    f.setPointSizeF(10)
    app.setFont(f)


def apply(app, name: str, glass: bool | None = None, variant: str | None = None) -> None:
    global GLASS
    if glass is not None:
        GLASS = bool(glass) and GLASS_SUPPORTED
    T.clear()
    T.update(THEMES.get(name, LIGHT))
    v = WALL_VARIANTS.get(variant or "")
    if v and v[0] == T["name"]:
        T["wall"] = v[1]
        T["variant"] = variant
    apply_custom()
    _wall_cache.clear()
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, T["bg"]), (QPalette.ColorRole.WindowText, T["text"]),
        (QPalette.ColorRole.Base, T["card"]), (QPalette.ColorRole.AlternateBase, T["bg"]),
        (QPalette.ColorRole.Text, T["text"]), (QPalette.ColorRole.Button, T["card"]),
        (QPalette.ColorRole.ButtonText, T["text"]), (QPalette.ColorRole.Highlight, T["accent"]),
        (QPalette.ColorRole.HighlightedText, T["on_accent"]), (QPalette.ColorRole.ToolTipBase, T["card"]),
        (QPalette.ColorRole.ToolTipText, T["text"]), (QPalette.ColorRole.PlaceholderText, T["faint"]),
    ):
        pal.setColor(role, qcolor(color))
    app.setPalette(pal)
    app.setStyleSheet(build_qss())


# ---------------------------------------------------------------- 个性化
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
# 主题色 / 气泡颜色的预设色板(个性化窗口里的小圆点)
ACCENT_PRESETS = ["#007AFF", "#5856D6", "#A855F7", "#E0457F", "#FF3B30", "#FF9500", "#F2B705", "#34C759",
                  "#14B8A6", "#0EA5E9", "#64748B", "#1D1D1F"]
CUSTOM: dict = {"accent": "", "bubble": "", "glass": 50, "bg_dim": 35, "bg_blur": True, "wall_dim": 0,
                "ambient": True, "ambient_level": 2}
_custom_bg = None            # 自定义背景图(QImage),None = 用主题自带的渐变壁纸
_custom_bg_id = 0


def valid_hex(v) -> bool:
    return isinstance(v, str) and bool(_HEX.fullmatch(v))


def clean_custom(d) -> dict:
    """从保存的设置里读个性化,不认识的值一律用默认。"""
    d = d if isinstance(d, dict) else {}
    out = {"accent": d.get("accent") if valid_hex(d.get("accent")) else "",
           "bubble": d.get("bubble") if valid_hex(d.get("bubble")) else ""}
    for key, default in (("glass", 50), ("bg_dim", 35), ("wall_dim", 0)):
        try:
            out[key] = max(0, min(100, int(d.get(key, default))))
        except (TypeError, ValueError):
            out[key] = default
    out["bg_blur"] = bool(d.get("bg_blur", True))
    out["ambient"] = bool(d.get("ambient", True))           # 动态背景(光斑慢慢漂);关掉 = 静态
    out["ambient_level"] = d.get("ambient_level") if d.get("ambient_level") in AMBIENT_LEVELS else 2
    return out


def set_custom(d: dict) -> None:
    CUSTOM.update(clean_custom({**CUSTOM, **(d or {})}))
    _wall_cache.clear()


def set_custom_bg(img) -> None:
    """img = QImage 或 None。"""
    global _custom_bg, _custom_bg_id
    _custom_bg = img if img is not None and not img.isNull() else None
    _custom_bg_id += 1
    _wall_cache.clear()


def has_custom_bg() -> bool:
    return _custom_bg is not None


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    h = hexcolor.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hexcolor: str) -> float:
    """相对亮度(WCAG),0 = 黑,1 = 白。"""
    def ch(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hexcolor)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def text_on(hexcolor: str) -> str:
    """放在这个颜色上的文字用白色还是深色(取对比度高的那个)。"""
    lum = luminance(hexcolor)
    on_white = 1.05 / (lum + 0.05)
    on_dark = (lum + 0.05) / (luminance("#1D1D1F") + 0.05)
    return "#FFFFFF" if on_white >= on_dark * 0.8 else "#1D1D1F"     # 稍微偏向白字,彩色气泡上白字更好看


def shade(hexcolor: str, amount: float) -> str:
    """amount > 0 变亮(向白色混),< 0 变暗(向黑色混)。"""
    r, g, b = _rgb(hexcolor)
    t = 255 if amount > 0 else 0
    k = min(1.0, abs(amount))
    return "#%02X%02X%02X" % tuple(int(round(c + (t - c) * k)) for c in (r, g, b))


def glass_factor(level: int) -> float:
    """面板透明度滑块(0 = 实心,50 = 默认,100 = 最通透)换算成不透明度倍数。"""
    level = max(0, min(100, int(level)))
    if level <= 50:
        return 1.0 + (50 - level) / 50 * 1.4
    return 1.0 - (level - 50) / 50 * 0.7


def scale_alpha(value: str, k: float, cap: float = 0.97) -> str:
    m = _RGBA.fullmatch(value.strip())
    if not m:
        return value
    r, g, b, a = m.groups()
    return f"rgba({r},{g},{b},{max(0.0, min(cap, float(a) * k)):.3f})"


def apply_custom() -> None:
    """在预设主题上叠加个性化:主题色、我的气泡颜色、面板透明度。"""
    T.setdefault("on_mine", T["on_accent"])
    acc = CUSTOM.get("accent")
    if valid_hex(acc):
        T["accent"] = acc
        T["accent_hover"] = shade(acc, 0.14 if is_dark() else -0.12)
        T["on_accent"] = text_on(acc)
        T["badge"] = acc
        T["mine"] = acc
        T["on_mine"] = T["on_accent"]
        r, g, b = _rgb(acc)
        T["select"] = f"rgba({r},{g},{b},{0.20 if is_dark() else 0.12})"
    bub = CUSTOM.get("bubble")
    if valid_hex(bub):
        T["mine"] = bub
        T["on_mine"] = text_on(bub)
    k = glass_factor(CUSTOM.get("glass", 50))
    if abs(k - 1.0) > 0.01:
        for key in ("chat", "side", "header"):
            T[key] = scale_alpha(T[key], k)
        T["other"] = scale_alpha(T["other"], max(1.0, k), 0.98)       # 再通透,别人的气泡也保持看得清


# ---------------------------------------------------------------- 随时间变化的壁纸
WALL_VARIANTS = {
    # 清晨:浅色主题 + 粉橙色的日出光晕
    "dawn": ("light", {
        "stops": [(0.0, "#FBE3E8"), (0.5, "#FDEBDD"), (1.0, "#E6E9FB")],
        "blobs": [(0.10, 0.95, 0.80, "#FFB38A", 0.48), (0.85, 0.90, 0.72, "#FF9EB5", 0.40),
                  (0.90, 0.08, 0.70, "#B9C6FF", 0.38), (0.15, 0.10, 0.62, "#FFE29A", 0.36),
                  (0.50, 0.55, 0.56, "#FFFFFF", 0.30)],
        "beams": [(-28, 0.30, 0.80, 0.26, "#FFF1D6", 0.36)],
        "grain": 0.022,
    }),
    # 深夜:深色主题 + 满天星星
    "night": ("dark", {
        "stops": [(0.0, "#070B1A"), (0.55, "#0D1430"), (1.0, "#1A1238")],
        "blobs": [(0.85, 0.10, 0.72, "#3B4FA8", 0.34), (0.10, 0.90, 0.76, "#4B2A7A", 0.30),
                  (0.55, 0.55, 0.60, "#1E3A6E", 0.24)],
        "beams": [(-34, 0.62, 0.30, 0.14, "#AFC3FF", 0.06)],
        "vignette": 0.28, "grain": 0.03,
        "stars": 140,
    }),
}


def period_for(hour: float) -> tuple[str, str | None, str]:
    """按钟点决定外观:(主题, 壁纸变体, 说明)。"""
    if 5 <= hour < 8:
        return "light", "dawn", "清晨"
    if 8 <= hour < 17:
        return "light", None, "白天"
    if 17 <= hour < 19.5:
        return "dusk", None, "黄昏"
    return "dark", "night", "夜晚"


# 气泡皮肤:随宠物等级解锁,对方也看得到。(id, 名字, 解锁等级, 背景, 文字颜色, 边框)
SKINS = [
    ("jelly", "果冻", 3, "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #B79CF2, stop:1 #FBC2EB)", "#3A2550", ""),
    ("mint", "薄荷", 5, "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #84FAB0, stop:1 #8FD3F4)", "#0F3A3A", ""),
    ("cloud", "云朵", 7, "#FFFFFF", "#2D3A4A", "2px solid #CFE0FF"),
    ("candy", "糖果", 9, "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF9A9E, stop:0.5 #FECFEF, stop:1 #FFD3A5)", "#5A2340", ""),
    ("galaxy", "星空", 14, "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2B1055, stop:0.6 #4B3CA7, stop:1 #7597DE)", "#FFFFFF", ""),
    ("gold", "鎏金", 20, "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FBE38E, stop:0.5 #F5C451, stop:1 #E3A13A)", "#4A3000", "1px solid #C68A1E"),
    # 等级 99 = 只能抽卡得到
    ("rainbow", "彩虹", 99, "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF9AA2, stop:0.25 #FFDAC1, stop:0.5 #E2F0CB, stop:0.75 #B5EAD7, stop:1 #C7CEEA)", "#3A3050", ""),
]
SKIN_BY_ID = {s[0]: s for s in SKINS}


# 气泡统一尺寸:圆角 18,内边距 8 × 14(有边框的扣掉边框宽度,外面看起来一样大)。
# 连续发的几条合成一组:靠发送者那一侧的拐角变小,读起来像一段话。
BUBBLE_R, GROUP_R = 18, 6
PAD_V, PAD_H = 8, 14


def _pad(border_px: int) -> str:
    return f"padding: {PAD_V - border_px}px {PAD_H - border_px}px;"


def _border_px(border: str) -> int:
    m = re.match(r"\s*(\d+)px", border or "")
    return int(m.group(1)) if m else 0


def skins_qss() -> str:
    out = []
    for sid, _name, _lv, bg, fg, border in SKINS:
        b = (f"border: {border}; " if border else "") + _pad(_border_px(border))
        out.append(f"QLabel#skin_{sid} {{ background: {bg}; color: {fg}; border-radius: {BUBBLE_R}px; {b} "
                   f"selection-background-color: rgba(255,255,255,0.4); }}")
    return "\n".join(out)


BUBBLE_NAMES = ["bubbleMine", "bubbleMineBurn", "bubbleOther", "bubbleOtherBurn", "bubbleOtherAt"]


def group_qss() -> str:
    """连续消息的拐角:grp = first / mid / last,side = r(我)/ l(别人)。"""
    names = BUBBLE_NAMES + [f"skin_{s[0]}" for s in SKINS]
    big, small = BUBBLE_R, GROUP_R
    out = []
    for side in ("l", "r"):
        for grp in ("first", "mid", "last"):
            top_small = grp in ("mid", "last")
            bot_small = grp in ("first", "mid")
            if side == "r":
                tl, tr, br, bl = big, (small if top_small else big), (small if bot_small else big), big
            else:
                tl, tr, br, bl = (small if top_small else big), big, big, (small if bot_small else big)
            corners = (f"border-top-left-radius: {tl}px; border-top-right-radius: {tr}px; "
                       f"border-bottom-right-radius: {br}px; border-bottom-left-radius: {bl}px;")
            sel = ", ".join(f'QLabel#{n}[grp="{grp}"][side="{side}"]' for n in names)
            out.append(f"{sel} {{ {corners} }}")
    return "\n".join(out)


# 等级标识:Lv.1~9 萌新 / 10~19 达人 / 20~29 进化 / 30~39 传说 / 40~50 神话
LEVEL_TIERS = [(1, "萌新", "#8E8E93", "#FFFFFF"), (10, "达人", "#0A84FF", "#FFFFFF"),
               (20, "进化", "#AF52DE", "#FFFFFF"), (30, "传说", "#F5B301", "#3A2600"),
               (40, "神话", "#FF6B9D", "#FFFFFF")]


def level_tier(level: int) -> int:
    tier = 0
    for i, (need, *_rest) in enumerate(LEVEL_TIERS):
        if level >= need:
            tier = i
    return tier


def badges_qss() -> str:
    out = []
    for i, (_need, _name, bg, fg) in enumerate(LEVEL_TIERS):
        out.append(f'QLabel#lvBadge[tier="{i}"] {{ background: {bg}; color: {fg}; }}')
    out.append('QLabel#lvBadge[tier="3"] { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, '
               'stop:0 #FFE27A, stop:0.5 #F5B301, stop:1 #FF9F43); }')
    out.append('QLabel#lvBadge[tier="4"] { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, '
               'stop:0 #FF7EB3, stop:0.5 #9775FA, stop:1 #4DABF7); color: #FFFFFF; }')
    return "\n".join(out)


# ---------------------------------------------------------------- 壁纸
_wall_cache: dict = {}


def render_wallpaper(w: int, h: int, spec: dict | None = None) -> QPixmap:
    """按主题画渐变壁纸。先在小画布上画(光晕本来就是模糊的,不需要高分辨率),再平滑放大。
    光晕半径大、中心不太浓、衰减更平缓,颜色铺满整张图而不是挤在几个角上;
    再加一两道斜着的环境光,四周轻轻压暗一点,让画面有层次。"""
    spec = spec or T["wall"]
    sw, sh = max(8, w // 3), max(8, h // 3)
    small = QPixmap(sw, sh)
    small.fill(QColor(spec["stops"][0][1]))
    p = QPainter(small)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, sw, sh)
    for pos, color in spec["stops"]:
        g.setColorAt(pos, QColor(color))
    p.fillRect(QRectF(0, 0, sw, sh), QBrush(g))
    big = max(sw, sh)
    for fx, fy, fr, color, alpha in spec["blobs"]:
        rg = QRadialGradient(QPointF(fx * sw, fy * sh), fr * big)
        for stop, mult in ((0.0, 1.0), (0.30, 0.68), (0.60, 0.26), (0.85, 0.06), (1.0, 0.0)):
            c = QColor(color)
            c.setAlphaF(alpha * mult)
            rg.setColorAt(stop, c)
        p.fillRect(QRectF(0, 0, sw, sh), QBrush(rg))
    diag = math.hypot(sw, sh) * 1.3
    for ang, fx, fy, wf, color, alpha in spec.get("beams", []):           # 斜着的环境光
        bw = max(2.0, wf * big)
        p.save()
        p.translate(fx * sw, fy * sh)
        p.rotate(ang)
        lg = QLinearGradient(0, -bw / 2, 0, bw / 2)
        for stop, mult in ((0.0, 0.0), (0.28, 0.30), (0.5, 1.0), (0.72, 0.30), (1.0, 0.0)):
            c = QColor(color)
            c.setAlphaF(alpha * mult)
            lg.setColorAt(stop, c)
        p.fillRect(QRectF(-diag / 2, -bw / 2, diag, bw), QBrush(lg))
        p.restore()
    vig = spec.get("vignette", 0.0)
    if vig:                                                                # 四周轻轻压暗
        rg = QRadialGradient(QPointF(sw / 2, sh / 2), big * 0.78)
        for stop, mult in ((0.0, 0.0), (0.55, 0.0), (0.85, 0.55), (1.0, 1.0)):
            rg.setColorAt(stop, QColor(0, 0, 0, int(255 * vig * mult)))
        p.fillRect(QRectF(0, 0, sw, sh), QBrush(rg))
    p.end()
    return small


_noise_cache: dict = {}


def noise_tile(strength: float, size: int = 96) -> QPixmap:
    """磨砂颗粒:一小块随机的浅点和深点,平铺在壁纸上。强度很低,只是让大片渐变不那么"塑料"。"""
    key = (round(strength, 3), size)
    pm = _noise_cache.get(key)
    if pm is None:
        import random as _r
        rnd = _r.Random(17)
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        top = max(1, int(255 * strength * 2.2))
        for y in range(size):
            for x in range(size):
                a = rnd.randint(0, top)
                if a > top * 0.35:
                    v = 255 if rnd.random() < 0.5 else 0
                    img.setPixelColor(x, y, QColor(v, v, v, a))
        pm = QPixmap.fromImage(img)
        _noise_cache[key] = pm
    return pm


def _custom_wallpaper(w: int, h: int, dpr: float) -> QPixmap:
    """自定义背景图:铺满(多余的裁掉),可以模糊,再盖一层主题底色调暗,保证文字看得清。"""
    pw, ph = max(1, int(w * dpr)), max(1, int(h * dpr))
    img = _custom_bg.scaled(pw, ph, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
    x, y = max(0, (img.width() - pw) // 2), max(0, (img.height() - ph) // 2)
    img = img.copy(x, y, pw, ph)
    if CUSTOM.get("bg_blur", True):                     # 缩小再放大两次 ≈ 高斯模糊,很便宜
        for div in (14, 6):
            tiny = img.scaled(max(1, pw // div), max(1, ph // div), Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            img = tiny.scaled(pw, ph, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    pm = QPixmap.fromImage(img)
    dim = CUSTOM.get("bg_dim", 35) / 100
    if dim > 0:
        p = QPainter(pm)
        c = QColor(T["bg"])
        c.setAlphaF(min(0.92, dim))
        p.fillRect(QRectF(0, 0, pw, ph), c)
        p.end()
    return pm


def wallpaper(w: int, h: int, dpr: float = 1.0) -> QPixmap:
    """取当前主题、当前尺寸的壁纸(有缓存,窗口大小或主题变了才重画)。"""
    key = (T["name"], T.get("variant"), w, h, round(dpr, 2), _custom_bg_id if _custom_bg is not None else 0,
           CUSTOM.get("bg_dim"), CUSTOM.get("bg_blur"), CUSTOM.get("wall_dim"))
    pm = _wall_cache.get(key)
    if pm is None:
        if len(_wall_cache) > 6:
            _wall_cache.clear()
        if _custom_bg is not None:
            pm = _custom_wallpaper(w, h, dpr)
        else:
            small = render_wallpaper(w, h)
            pm = small.scaled(max(1, int(w * dpr)), max(1, int(h * dpr)), Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            dim = CUSTOM.get("wall_dim", 0) / 100              # 渐变壁纸也能调暗(盖一层主题底色)
            if dim > 0:
                p = QPainter(pm)
                c = QColor(T["bg"])
                c.setAlphaF(min(0.9, dim))
                p.fillRect(QRectF(0, 0, pm.width(), pm.height()), c)
                p.end()
        pm.setDevicePixelRatio(dpr)
        if _custom_bg is None:
            stars = T["wall"].get("stars", 0)
            if stars:
                paint_stars(pm, w, h, stars)
        grain = T["wall"].get("grain", 0.0)
        if grain:
            p = QPainter(pm)
            p.drawTiledPixmap(QRectF(0, 0, w, h), noise_tile(grain))
            p.end()
        _wall_cache[key] = pm
    return pm


def paint_stars(pm, w: int, h: int, n: int) -> None:
    """夜晚壁纸上的星星:位置固定(同一窗口大小每次都一样),大小亮度各不相同,上半部分多一些。"""
    import random as _r
    rnd = _r.Random(20261117)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(n):
        x = rnd.random() * w
        y = (rnd.random() ** 1.6) * h
        r = rnd.choice((0.6, 0.7, 0.8, 1.0, 1.0, 1.3, 1.7))
        c = QColor(rnd.choice(("#FFFFFF", "#FFFFFF", "#DDE6FF", "#FFF2D6")))
        c.setAlphaF(rnd.uniform(0.35, 0.95))
        p.setBrush(c)
        p.drawEllipse(QPointF(x, y), r, r)
        if r >= 1.3:                                # 亮星加一圈光
            c.setAlphaF(0.12)
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), r * 3.2, r * 3.2)
    p.end()


def paint_wallpaper(widget, event=None, ambient_t: float | None = None) -> None:
    """在 widget 上画壁纸(paintEvent 里调用)。毛玻璃开启时壁纸半透明,透出系统模糊。
    ambient_t 不为空时,再叠一层缓慢漂移的柔光斑(动态背景)。"""
    p = QPainter(widget)
    if GLASS:
        p.setOpacity(0.80)
    try:
        dpr = widget.devicePixelRatioF()
    except Exception:
        dpr = 1.0
    p.drawPixmap(0, 0, wallpaper(widget.width(), widget.height(), dpr))
    if ambient_t is not None:
        paint_ambient(p, widget.width(), widget.height(), ambient_t)
    p.end()


# ---------------------------------------------------------------- 动态背景:缓慢漂移、呼吸的柔光斑
_spot_cache: dict = {}


def _spot_pixmap(color: str) -> QPixmap:
    """一团柔光(中间亮、边缘渐渐透明),小尺寸预先画好,用时放大(本来就是模糊的,放大看不出来)。"""
    pm = _spot_cache.get(color)
    if pm is None:
        size = 160
        pm = QPixmap(size, size)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        g = QRadialGradient(QPointF(size / 2, size / 2), size / 2)
        for stop, a in ((0.0, 1.0), (0.32, 0.62), (0.62, 0.22), (0.85, 0.05), (1.0, 0.0)):
            c = QColor(color)
            c.setAlphaF(a)
            g.setColorAt(stop, c)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRect(0, 0, size, size)
        p.end()
        if len(_spot_cache) > 24:
            _spot_cache.clear()
        _spot_cache[color] = pm
    return pm


# 动态背景的两档:1 = 轻柔(很慢,几乎察觉不到),2 = 明显(默认:看得出光在流动,但不晃眼)
#   amp 轨迹幅度 / period 绕一圈的秒数 / radius 光斑大小 / breathe 呼吸周期和深浅 / alpha 深色、浅色主题的亮度 / beam 柔光
AMBIENT_LEVELS = {
    1: {"amp": (0.38, 0.32), "period": (34, 5.5, 41, 3.7), "radius": (0.25, 0.05), "breathe": (9, 2.1, 0.32),
        "alpha": (0.40, 0.36), "beam": (28.0, 0.22, 0.12, 0.16)},
    2: {"amp": (0.40, 0.34), "period": (24, 3.1, 29, 2.3), "radius": (0.19, 0.04), "breathe": (6, 1.3, 0.45),
        "alpha": (0.58, 0.46), "beam": (14.0, 0.17, 0.18, 0.24)},
}


def _ambient_cfg() -> dict:
    return AMBIENT_LEVELS.get(CUSTOM.get("ambient_level"), AMBIENT_LEVELS[2])


def ambient_spots(w: int, h: int, t: float) -> list[tuple[float, float, float, str, float]]:
    """t 秒时的几团光斑:(x, y, 半径, 颜色, 透明度)。每团沿自己的椭圆轨迹漂,大小和亮度也在呼吸。"""
    cfg = _ambient_cfg()
    cols = [b[3] for b in T["wall"].get("blobs", []) if valid_hex(b[3])][:3]
    if valid_hex(T["accent"]):
        cols.append(T["accent"])
    if _custom_bg is not None:
        cols = [T["accent"], T["accent"]] if valid_hex(T["accent"]) else cols[:2]
    cols = cols or ["#8899FF"]
    dark = is_dark()
    big = max(w, h)
    ax, ay = cfg["amp"]
    px, pxi, py, pyi = cfg["period"]
    r0, rv = cfg["radius"]
    bp, bpi, depth = cfg["breathe"]
    amax = cfg["alpha"][0 if dark else 1]
    out = []
    for i, c in enumerate(cols[:4]):
        ph = i * 1.93
        x = w * (0.5 + ax * math.sin(t / (px + i * pxi) * math.tau + ph))
        y = h * (0.5 + ay * math.cos(t / (py + i * pyi) * math.tau + ph * 1.4))
        r = big * (r0 + rv * math.sin(t / (13 + i * 2.3) * math.tau + ph))
        breathe = 1.0 - depth + depth * math.sin(t / (bp + i * bpi) * math.tau + ph)
        a = amax * breathe
        if _custom_bg is not None:
            a *= 0.6
        out.append((x, y, r, shade(c, 0.22 if dark else 0.04), a))
    return out


def ambient_beam(w: int, h: int, t: float) -> tuple[float, float, float, float, float]:
    """那道柔光此刻的位置:(起点 x, 起点 y, 终点 x, 终点 y, 透明度)。沿 25° 方向从左上扫到右下。"""
    period, width, a_dark, a_light = _ambient_cfg()["beam"]
    ang = math.radians(25)
    dx, dy = math.cos(ang), math.sin(ang)
    length = w * dx + h * dy                          # 窗口在这个方向上的跨度
    k = (t % period) / period
    center = -0.35 * length + k * 1.7 * length          # 从窗口外进来,再从另一边出去,中间有一段空档
    half = width * length
    a = a_dark if is_dark() else a_light
    if _custom_bg is not None:
        a *= 0.6
    return (dx * (center - half), dy * (center - half), dx * (center + half), dy * (center + half), a)


def paint_ambient(p: QPainter, w: int, h: int, t: float) -> None:
    """动态背景:光斑 + 扫过的柔光。深色主题用"滤色"叠加,看起来像光;浅色主题正常叠加。"""
    base = p.opacity()
    dark = is_dark()
    if dark:
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
    for x, y, r, color, a in ambient_spots(w, h, t):
        p.setOpacity(base * a)
        p.drawPixmap(QRectF(x - r, y - r, 2 * r, 2 * r), _spot_pixmap(color), QRectF(0, 0, 160, 160))
    x1, y1, x2, y2, a = ambient_beam(w, h, t)
    g = QLinearGradient(QPointF(x1, y1), QPointF(x2, y2))
    tint = QColor(shade(T["accent"], 0.55) if dark and valid_hex(T["accent"]) else "#FFFFFF")   # 深色主题带一点主题色,不发灰
    for stop, k in ((0.0, 0.0), (0.35, 0.45), (0.5, 1.0), (0.65, 0.45), (1.0, 0.0)):
        c = QColor(tint)
        c.setAlphaF(k)
        g.setColorAt(stop, c)
    p.setOpacity(base * a)
    p.fillRect(QRectF(0, 0, w, h), QBrush(g))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    p.setOpacity(base)


# ---------------------------------------------------------------- Windows 原生效果
def _dwm_set(hwnd: int, attr: int, value: int) -> bool:
    import ctypes
    v = ctypes.c_int(value)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0


def style_titlebar(widget) -> None:
    """标题栏跟随深浅色;启用毛玻璃时同时打开系统亚克力背景。"""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        if not _dwm_set(hwnd, 20, 1 if is_dark() else 0):        # DWMWA_USE_IMMERSIVE_DARK_MODE
            _dwm_set(hwnd, 19, 1 if is_dark() else 0)
        _dwm_set(hwnd, 33, 2)                                      # DWMWA_WINDOW_CORNER_PREFERENCE = 圆角
        if GLASS_SUPPORTED and getattr(widget, "_glass_capable", False):
            set_backdrop(widget, GLASS)
    except Exception:
        pass


def set_backdrop(widget, on: bool) -> bool:
    """Windows 11:窗口背景用系统亚克力毛玻璃(3),关闭时为无(1)。"""
    if sys.platform != "win32" or not GLASS_SUPPORTED:
        return False
    try:
        import ctypes

        class MARGINS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]

        hwnd = int(widget.winId())
        frameless = bool(getattr(widget, "frameless", False))
        m = MARGINS(-1, -1, -1, -1) if on else (MARGINS(1, 1, 1, 1) if frameless else MARGINS(0, 0, 0, 0))
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
        return _dwm_set(hwnd, 38, 3 if on else 1)                  # DWMWA_SYSTEMBACKDROP_TYPE
    except Exception:
        return False


def apply_frameless_dwm(widget) -> None:
    """Windows 无边框窗口保留原生圆角与阴影。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        class MARGINS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]

        hwnd = int(widget.winId())
        _dwm_set(hwnd, 33, 2)                                      # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
        if not GLASS:
            m = MARGINS(1, 1, 1, 1) if getattr(widget, "frameless", False) else MARGINS(0, 0, 0, 0)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
    except Exception:
        pass


# ---------------------------------------------------------------- 样式表
def _h(sel: str, bg: str, on: bool) -> str:
    """悬停 / 按下的背景色规则(界面动效关掉时才用样式表)。"""
    return f"{sel} {{ background: {bg}; }}" if on else ""


def _rgba(hexcolor: str, a: float) -> str:
    try:
        r, g, b = _rgb(hexcolor)
    except Exception:                                       # noqa: BLE001  不是十六进制颜色
        return hexcolor
    return f"rgba({r},{g},{b},{a})"


def gomoku_qss(t: dict, side: str) -> str:
    """五子棋窗口的样式:和主题一致的半透明卡片、主题色高亮。"""
    acc = t["accent"]
    return f"""
QFrame#gmHeader {{ background: transparent; border: none; border-bottom: 1px solid {t['line']}; }}
QPushButton#segBtn {{ background: {t['btn2']}; border: none; border-radius: 14px; padding: 6px 14px; color: {t['sub']}; min-height: 16px; }}
QPushButton#segBtn:hover:!checked {{ background: {t['btn2_hover']}; color: {t['text']}; }}
QPushButton#segBtn:checked {{ background: {acc}; color: {t['on_accent']}; font-weight: 600; }}
QFrame#gmHero {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_rgba(acc, 0.38)}, stop:1 {_rgba(acc, 0.08)});
    border: 1px solid {t['line']}; border-radius: 18px; }}
QLabel#gmHello {{ font-size: 17pt; font-weight: 700; }}
QLabel#gmHeroSub {{ color: {t['sub']}; font-size: 9.5pt; }}
QFrame#gmStatusCard {{ background: {t['select']}; border: 1px solid {_rgba(acc, 0.45)}; border-radius: 12px; }}
QLabel#gmStatusText {{ font-weight: 600; }}
QScrollArea#gmScroll, QWidget#gmInner {{ background: transparent; border: none; }}
QFrame#gmRow {{ background: {t['btn2']}; border: none; border-radius: 12px; }}
QFrame#gmRow:hover {{ background: {t['btn2_hover']}; }}
QLabel#gmRowTitle {{ font-weight: 600; }}
QLabel#gmRowSub, QLabel#gmSub {{ color: {t['sub']}; font-size: 8.5pt; }}
QLabel#gmEmpty {{ color: {t['faint']}; padding: 22px; }}
QLabel#gmEmptyTitle {{ font-size: 15pt; font-weight: 700; }}
QFrame#gmSide {{ background: {side}; border: 1px solid {t['line']}; border-radius: 18px; }}
QFrame#gmPlayer {{ background: {t['btn2']}; border: 1px solid transparent; border-radius: 14px; }}
QFrame#gmPlayer[active="true"] {{ background: {t['select']}; border: 1px solid {_rgba(acc, 0.7)}; }}
QLabel#gmName {{ font-size: 11pt; font-weight: 700; }}
QLabel#gmClock {{ font-size: 17pt; font-weight: 700; }}
QLabel#gmStatus {{ font-size: 12pt; font-weight: 700; padding: 8px; border-radius: 12px; background: {t['btn2']}; }}
QLabel#gmStatus[kind="mine"] {{ background: {acc}; color: {t['on_accent']}; }}
QLabel#gmStatus[kind="win"] {{ background: {_rgba(t['good'], 0.22)}; color: {t['good']}; }}
QLabel#gmStatus[kind="loss"] {{ background: {_rgba(t['bad'], 0.18)}; color: {t['bad']}; }}
QLabel#gmStatus[kind="draw"], QLabel#gmStatus[kind="warn"] {{ background: {_rgba(t['warn'], 0.18)}; color: {t['warn']}; }}
QFrame#gmBanner {{ background: {t['select']}; border: 1px solid {acc}; border-radius: 12px; }}
QFrame#gmPause {{ background: {_rgba(t['warn'], 0.14)}; border: 1px solid {_rgba(t['warn'], 0.6)}; border-radius: 12px; }}
QLabel#gmBannerText {{ font-weight: 600; }}
QFrame#gmResult {{ background: {t['card']}; border: 1px solid {t['line_strong']}; border-radius: 20px; }}
QLabel#gmResultTitle {{ font-size: 22pt; font-weight: 800; }}
QLabel#gmPoints {{ font-size: 26pt; font-weight: 800; color: {acc}; }}
QLabel#gmRankChange {{ color: {t['good']}; font-weight: 600; }}
QFrame#gmRankHead {{ background: transparent; border: none; }}
QFrame#gmRankRow {{ background: {t['btn2']}; border: none; border-radius: 12px; }}
QFrame#gmRankMe {{ background: {t['select']}; border: 2px solid {acc}; border-radius: 12px; }}
QLabel#gmRank {{ font-size: 13pt; font-weight: 700; }}
QLabel#gmNum {{ font-size: 11pt; font-weight: 700; color: {acc}; }}
QFrame#gmMeBar {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {acc}, stop:1 {_rgba(acc, 0.7)}); border: none; border-radius: 14px; }}
QLabel#gmMeText {{ color: {t['on_accent']}; font-weight: 600; }}
QFrame#gmStat {{ background: {t['btn2']}; border: none; border-radius: 14px; }}
QLabel#gmStatValue {{ font-size: 18pt; font-weight: 800; }}
QLabel#chip_win {{ background: {t['good']}; color: #FFFFFF; border-radius: 9px; padding: 2px 6px; font-weight: 700; }}
QLabel#chip_loss {{ background: {t['bad']}; color: #FFFFFF; border-radius: 9px; padding: 2px 6px; font-weight: 700; }}
QLabel#chip_draw {{ background: {t['warn']}; color: #FFFFFF; border-radius: 9px; padding: 2px 6px; font-weight: 700; }}
QLabel#chip_none {{ background: {t['btn2']}; color: {t['sub']}; border-radius: 9px; padding: 2px 6px; }}
QLabel#gmMeChip {{ background: {t['select']}; border-radius: 13px; padding: 4px 12px; font-weight: 600; }}
QFrame#dkPanel {{ background: {t['card']}; border: 1px solid {t['line_strong']}; border-radius: 18px; }}
QFrame#dkCard {{ background: {_rgba('#1E1A2B', 0.78)}; border: 1px solid {_rgba('#FFFFFF', 0.12)}; border-radius: 14px; }}
QFrame#dkCard QLabel {{ color: #F1F3F5; }}
QLabel#dkTasks {{ font-size: 9pt; color: #DEE2E6; }}
QFrame#dkBarTrack {{ background: {_rgba('#FFFFFF', 0.15)}; border: none; border-radius: 4px; }}
QFrame#dkBarFill {{ background: #69DB7C; border: none; border-radius: 4px; }}
QLabel#dkRole {{ background: {_rgba('#1E1A2B', 0.8)}; border-radius: 13px; padding: 6px 14px; font-weight: 700; }}
QLabel#dkHint {{ color: #F1F3F5; font-weight: 600; }}
QPushButton#dkAct_use, QPushButton#dkAct_report, QPushButton#dkAct_kill, QPushButton#dkAct_sabo {{
    border-radius: 42px; font-size: 12pt; font-weight: 800; color: #FFFFFF; border: 2px solid {_rgba('#FFFFFF', 0.35)}; }}
QPushButton#dkAct_use {{ background: {acc}; }}
QPushButton#dkAct_report {{ background: #F08C00; }}
QPushButton#dkAct_kill {{ background: #E03131; }}
QPushButton#dkAct_sabo {{ background: #5F3DC4; }}
QPushButton#dkAct_use:disabled, QPushButton#dkAct_report:disabled, QPushButton#dkAct_kill:disabled,
QPushButton#dkAct_sabo:disabled {{ background: {_rgba('#495057', 0.75)}; color: {_rgba('#FFFFFF', 0.55)}; }}
QPushButton#dkColor {{ background: {t['btn2']}; border: 2px solid transparent; border-radius: 17px; }}
QPushButton#dkColor[sel="true"] {{ border: 2px solid {acc}; background: {t['select']}; }}
QPushButton#dkColor:disabled {{ background: transparent; }}
QFrame#dkSlot {{ background: transparent; border: 2px dashed {t['line']}; border-radius: 14px; }}
QFrame#dkSlotOn {{ background: {t['btn2']}; border: 1px solid {t['line']}; border-radius: 14px; }}
QFrame#dkSlotMe {{ background: {t['select']}; border: 1px solid {_rgba(acc, 0.7)}; border-radius: 14px; }}
QPushButton#dkBird {{ background: transparent; border: none; }}
QPushButton#dkVote {{ background: {t['btn2']}; border: 1px solid transparent; border-radius: 12px; text-align: left; padding: 4px 10px; }}
QPushButton#dkVote:hover:enabled {{ background: {t['btn2_hover']}; border: 1px solid {_rgba(acc, 0.6)}; }}
QPushButton#dkVote[sel="true"] {{ background: {t['select']}; border: 1px solid {acc}; }}
QLabel#dkChat {{ padding: 2px 0; }}
QLabel#dkLog {{ padding: 3px 0; font-size: 9pt; }}
QPushButton#dkAct_check {{ border-radius: 42px; font-size: 12pt; font-weight: 800; color: #FFFFFF;
    border: 2px solid {_rgba('#FFFFFF', 0.35)}; background: #7048E8; }}
QPushButton#dkAct_check:disabled {{ background: {_rgba('#495057', 0.75)}; color: {_rgba('#FFFFFF', 0.55)}; }}
QLabel#dkChatGhost {{ padding: 2px 0; color: {t['faint']}; font-style: italic; }}
QFrame#spSeat {{ background: {t['btn2']}; border: 1px solid {t['line']}; border-radius: 14px; }}
QFrame#spSeat[st="speaking"] {{ border: 2px solid {acc}; background: {t['select']}; }}
QFrame#spSeat[st="pick"] {{ border: 1px dashed {_rgba(acc, 0.8)}; }}
QFrame#spSeat[st="pick"]:hover {{ background: {t['btn2_hover']}; border: 2px solid {acc}; }}
QFrame#spSeat[st="voted"] {{ border: 1px solid {_rgba('#51CF66', 0.7)}; }}
QFrame#spSeat[st="out"] {{ background: transparent; border: 1px dashed {t['line']}; }}
QLabel#spSeatStatus {{ color: {t['sub']}; font-size: 8.5pt; }}
QLabel#spSeatSaid {{ font-size: 9.5pt; }}
QLabel#spWords {{ font-size: 13pt; font-weight: 700; }}
QLabel#spRound {{ color: {t['faint']}; font-size: 8.5pt; padding: 6px 0 2px 0; }}
QLabel#spSay {{ padding: 2px 0; font-weight: 600; }}
QLabel#spChat {{ padding: 1px 0; color: {t['sub']}; }}
QLabel#spChatDead {{ padding: 1px 0; color: {t['faint']}; font-style: italic; }}
QFrame#throwPill {{ background: {t['card']}; border: 1px solid {t['line_strong']}; border-radius: 18px; }}
QLabel#throwPillText {{ font-weight: 600; }}
QLabel#gmToast {{ background: {t['card']}; border: 1px solid {t['line_strong']}; border-radius: 14px; padding: 10px 16px; font-weight: 600; }}
"""


def build_qss() -> str:
    t = T
    g = GLASS
    R = BUBBLE_R
    from . import motion
    # 开着界面动效时,按钮的悬停 / 按下颜色由 motion.py 平滑地画出来;关掉时用样式表(瞬间变色)
    hov = not motion.ENABLED
    win_bg = "transparent" if g else t["bg"]
    chat, side, header = t["chat"], t["side"], t["header"]
    card = t["card_glass"] if g else t["card"]
    dialog_bg = card
    return f"""
QMainWindow {{ background: {win_bg}; }}
QDialog {{ background: {dialog_bg}; }}
QWidget {{ color: {t['text']}; }}
QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['line']}; padding: 5px 9px; }}

QWidget#central {{ background: transparent; }}
QFrame#sidebar {{ background: {side}; border: none; border-right: 1px solid {t['line']}; }}
QFrame#members {{ background: {side}; border: none; border-left: 1px solid {t['line']}; }}
QWidget#chatPanel {{ background: {chat}; }}
QFrame#chatHeader {{ background: {header}; border: none; border-bottom: 1px solid {t['line']}; }}
QFrame#composer {{ background: transparent; }}
QFrame#composerPill {{ background: {t['pill']}; border: 1px solid {t['line_strong']}; border-radius: 19px; }}
QFrame#meCard {{ background: transparent; border-radius: 12px; }}
QFrame#meCard:hover {{ background: {t['hover']}; }}
QFrame#card {{ background: {card}; border: 1px solid {t['line']}; border-radius: 14px; }}
QFrame#plainCard {{ background: {t['btn2']}; border: none; border-radius: 14px; }}
QScrollArea#msgArea, QWidget#msgContainer {{ background: transparent; border: none; }}
QDialog#viewer {{ background: #0B0B0C; }}
QFrame#viewerBar {{ background: rgba(28,28,30,0.92); border-top: 1px solid rgba(255,255,255,0.08); }}
QFrame#playerBar {{ background: #1C1C1E; border-top: 1px solid rgba(255,255,255,0.08); }}
QFrame#playerBar QLabel {{ color: #EDEDF2; background: transparent; }}
QFrame#playerBar QLabel#viewerInfo {{ color: #A1A1AA; }}
QFrame#playerBar QPushButton {{ background: rgba(255,255,255,0.10); color: #F2F2F7; border: none; border-radius: 8px; padding: 4px 10px; }}
QFrame#playerBar QPushButton:hover {{ background: rgba(255,255,255,0.18); }}
QFrame#playerBar QPushButton:checked {{ background: #0A84FF; color: #FFFFFF; }}
QFrame#playerBar QPushButton#link {{ background: transparent; color: #64D2FF; padding: 4px 4px; }}
QWidget#videoStage {{ background: #000000; }}
QLabel#videoBuffer {{ color: #FFFFFF; background: rgba(0,0,0,0.6); border-radius: 14px; padding: 6px 16px; font-size: 10pt; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QFrame#setSide {{ background: {side}; border: none; border-right: 1px solid {t['line']}; }}
QListWidget#setNav::item {{ padding: 8px 10px; margin: 1px 0; border-radius: 10px; color: {t['text']}; }}
QListWidget#setNav::item:hover {{ background: {t['hover']}; }}
QListWidget#setNav::item:selected {{ background: {t['select']}; color: {t['text']}; font-weight: 600; }}
QScrollArea#setPage, QWidget#setInner {{ background: transparent; border: none; }}
QFrame#setRow {{ background: transparent; border: none; }}
QLabel#pageTitle {{ font-size: 16pt; font-weight: 700; padding-bottom: 2px; }}
QLabel#rowTitle {{ font-size: 10pt; }}
QLabel#rowTitle:disabled {{ color: {t['faint']}; }}
QLabel#rowSub {{ color: {t['sub']}; font-size: 8.5pt; }}
QPushButton#choiceBtn {{ padding: 6px 12px; }}
QFrame#sep {{ background: {t['line']}; border: none; min-height: 1px; max-height: 1px; }}
QLineEdit#cardEdit {{ background: transparent; border: none; border-radius: 0; padding: 10px 0; }}
QLineEdit#cardEdit:focus {{ border: none; }}

QLineEdit {{
    background: {t['pill']}; border: 1px solid {t['line_strong']}; border-radius: 10px; padding: 8px 12px;
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; color: {t['text']};
}}
QLineEdit:focus {{ border: 1px solid {t['accent']}; }}
QPlainTextEdit {{
    background: transparent; border: none; padding: 5px 2px; color: {t['text']};
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
}}
QPlainTextEdit:disabled, QLineEdit:disabled {{ color: {t['faint']}; }}

QPushButton {{
    background: {t['btn2']}; border: none; border-radius: 10px; padding: 8px 18px; color: {t['text']}; font-weight: 500;
}}
{_h('QPushButton:hover', t['btn2_hover'], hov)}
QPushButton:disabled {{ color: {t['faint']}; }}
QPushButton#primary {{ background: {t['accent']}; color: {t['on_accent']}; font-weight: 600; }}
{_h('QPushButton#primary:hover', t['accent_hover'], hov)}
QPushButton#primary:disabled {{ background: {t['btn2']}; color: {t['faint']}; }}
QPushButton#destructive {{ background: {t['btn2']}; color: {t['bad']}; font-weight: 600; }}
{_h('QPushButton#destructive:hover', t['btn2_hover'], hov)}
QPushButton#link {{ background: transparent; color: {t['accent']}; padding: 4px 6px; }}
{_h('QPushButton#link:hover', t['hover'], hov)}

QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; color: {t['sub']}; }}
QToolButton:hover {{ color: {t['text']}; }}
{_h('QToolButton:hover', t['hover'], hov)}
{_h('QToolButton:pressed', t['select'], hov)}
QToolButton:disabled {{ color: {t['faint']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#round {{ padding: 0; }}
QToolButton#burnOn {{ padding: 0 10px 0 6px; color: {t['burn']}; font-weight: 600; background: {t['hover']}; }}
QToolButton#sendBtn {{ background: {t['accent']}; padding: 0; }}
{_h('QToolButton#sendBtn:hover', t['accent_hover'], hov)}
QToolButton#sendBtn:disabled {{ background: {t['btn2']}; }}
QToolButton#verified {{ color: {t['good']}; }}
QToolButton#textBtn {{ padding: 6px 10px; }}

QMenu {{ background: {t['card']}; border: 1px solid {t['line']}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 7px; color: {t['text']}; background: transparent; }}
QMenu::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
QMenu::item:disabled {{ color: {t['faint']}; }}
QMenu::separator {{ height: 1px; background: {t['line']}; margin: 5px 10px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
QMenu::icon {{ left: 8px; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px 2px 3px 0; }}
QScrollBar::handle:vertical {{ background: {t['scroll']}; border-radius: 3px; min-height: 40px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QCheckBox {{ spacing: 8px; color: {t['text']}; }}

QLabel {{ background: transparent; }}
QLabel#bubbleMine {{ background: {t['mine']}; color: {t['on_mine']}; border-radius: {R}px; {_pad(0)} }}
QLabel#bubbleOther {{ background: {t['other']}; color: {t['text']}; border-radius: {R}px; {_pad(0)} }}
QLabel#bubbleMine, QLabel#bubbleMineBurn {{ selection-background-color: rgba(255,255,255,0.35); }}
QLabel#bubbleMineBurn {{
    background: {t['mine']}; color: {t['on_mine']}; border: 1px solid {t['burn_line']}; border-radius: {R}px; {_pad(1)}
}}
QLabel#bubbleOtherBurn {{
    background: {t['other']}; color: {t['text']}; border: 1px solid {t['burn_line']}; border-radius: {R}px; {_pad(1)}
}}
QLabel#bubbleOtherAt {{
    background: {t['other']}; color: {t['text']}; border: 2px solid {t['accent']}; border-radius: {R}px; {_pad(2)}
}}
{skins_qss()}
{group_qss()}
QLabel#lvBadge {{ border-radius: 7px; padding: 0px 6px; font-size: 7.5pt; font-weight: 700; min-height: 14px; }}
{badges_qss()}
QLabel#titleBadge {{ background: {t['btn2']}; color: {t['sub']}; border: 1px solid {t['line']}; border-radius: 7px; padding: 0px 6px; font-size: 7.5pt; min-height: 14px; }}
QFrame#hoverBar {{ background: {t['card']}; border: 1px solid {t['line_strong']}; border-radius: 15px; }}
QToolButton#hoverBtn {{ border-radius: 12px; padding: 0; background: transparent; }}
QToolButton#hoverBtn:hover {{ background: {t['btn2_hover']}; }}
QFrame#swatchRow QPushButton {{ border-radius: 13px; padding: 0; min-height: 0; }}
QPushButton#choice {{ padding: 6px 10px; border: 1px solid transparent; }}
QPushButton#latestBtn {{ background: {t['card']}; color: {t['accent']}; border: 1px solid {t['line_strong']}; border-radius: 15px; padding: 5px 16px; font-weight: 600; min-height: 20px; }}
QPushButton#latestBtn:hover {{ background: {t['select']}; }}
QPushButton#choice:checked {{ background: {t['select']}; border: 1px solid {t['accent']}; color: {t['text']}; font-weight: 600; }}
QPushButton#choice:disabled {{ color: {t['faint']}; }}
QLabel#previewMine {{ background: {t['mine']}; color: {t['on_mine']}; border-radius: {R}px; {_pad(0)} }}
QLabel#previewOther {{ background: {t['other']}; color: {t['text']}; border-radius: {R}px; {_pad(0)} }}
QLabel#noteBubble {{ background: #FFF4B8; color: #4A3B1A; border: 1px dashed #D9B44A; border-radius: 6px; padding: 9px 14px; }}
QLabel#quote {{ background: {t['btn2']}; color: {t['sub']}; border-radius: 10px; padding: 5px 11px; font-size: 8.5pt; }}
QLabel#quote:hover {{ background: {t['btn2_hover']}; }}
QFrame#fileCard {{ background: {t['other']}; border: 1px solid {t['line']}; border-radius: 16px; }}
QFrame#fileCardMine {{ background: {t['other']}; border: 1px solid {t['line']}; border-radius: 16px; }}
QFrame#videoCard, QFrame#videoCardMine {{ background: transparent; border: none; }}
QLabel#fileName {{ font-weight: 600; }}
QLabel#fileSub {{ color: {t['sub']}; font-size: 8.5pt; }}
QLabel#fileWarn {{ color: {t['warn']}; font-size: 8pt; }}
QProgressBar#fileProgress {{ background: {t['btn2']}; border: none; border-radius: 2px; min-height: 4px; max-height: 4px; }}
QProgressBar#fileProgress::chunk {{ background: {t['accent']}; border-radius: 2px; }}
QFrame#replyBar {{ background: {t['btn2']}; border: none; border-radius: 12px; }}
QFrame#noticeBar {{ background: {t['card']}; border: 1px solid {t['line_strong']}; border-radius: 19px; }}
QLabel#noticeText {{ color: {t['text']}; font-size: 9pt; }}
QPushButton#reactChip {{ background: {t['btn2']}; border: 1px solid {t['line']}; border-radius: 11px; padding: 1px 8px; font-size: 9pt; min-height: 20px; }}
QPushButton#reactChip:hover {{ background: {t['btn2_hover']}; }}
QPushButton#reactChipMine {{ background: {t['select']}; border: 1px solid {t['accent']}; border-radius: 11px; padding: 1px 8px; font-size: 9pt; min-height: 20px; }}
QPushButton#selBox {{ background: transparent; border: 2px solid {t['line_strong']}; border-radius: 10px; padding: 0; }}
QPushButton#selBox:checked {{ background: {t['accent']}; border-color: {t['accent']}; color: {t['on_accent']}; }}
QLabel#gachaRarity {{ font-size: 26pt; font-weight: 800; color: {t['sub']}; }}
QLabel#favSource {{ color: {t['sub']}; font-size: 8pt; }}
QLabel#cardTitle {{ font-weight: 600; font-size: 10.5pt; }}
QLabel#lotteryName {{ font-size: 17pt; font-weight: 700; color: {t['sub']}; }}
QLabel#lotteryName[won="true"] {{ color: {t['accent']}; }}
QLabel#rpsResult {{ font-size: 15pt; font-weight: 600; }}
QLabel#errorText {{ color: {t['bad']}; font-size: 8.5pt; }}
QPushButton#rpsBtn {{ font-size: 20pt; background: {t['btn2']}; border: none; border-radius: 14px; padding: 0; }}
QPushButton#rpsBtn:hover {{ background: {t['btn2_hover']}; }}
QFrame#searchBar {{ background: {t['card']}; border: 1px solid {t['line_strong']}; border-radius: 21px; }}
QLineEdit#searchEdit {{ background: transparent; border: none; padding: 4px 2px; }}
QLineEdit#searchEdit:focus {{ border: none; }}
QLabel#searchCount {{ color: {t['sub']}; font-size: 8.5pt; padding: 0 4px; }}
QLabel#searchCount[empty="true"] {{ color: {t['bad']}; }}
QWidget[searchHit="true"] {{ background: {t['select']}; border-radius: 14px; }}
QLabel#replyText {{ color: {t['sub']}; font-size: 8.5pt; }}
QPushButton#tab {{ background: transparent; padding: 5px 14px; border-radius: 8px; color: {t['sub']}; min-height: 0; }}
QPushButton#tab:checked {{ background: {t['btn2']}; color: {t['text']}; font-weight: 600; }}
QFrame#emojiPanel {{ background: {t['card']}; border: 1px solid {t['line']}; border-radius: 16px; }}
QToolButton#emoji {{ border-radius: 8px; padding: 0; }}
QToolButton#emoji:hover {{ background: {t['hover']}; }}
QLabel#subtitleAccent {{ color: {t['accent']}; font-size: 8.5pt; }}
QLabel#imageBubble {{ background: transparent; border: none; }}
QLabel#imageBroken {{ background: {t['other']}; color: {t['sub']}; border-radius: 16px; padding: 18px 22px; }}
QLabel#meta {{ color: {t['faint']}; font-size: 8pt; }}
QLabel#metaWarn {{ color: {t['bad']}; font-size: 8pt; }}
QLabel#metaBurn {{ color: {t['burn']}; font-size: 8pt; font-weight: 600; }}
QLabel#name {{ color: {t['sub']}; font-size: 8.5pt; font-weight: 600; }}
QLabel#system {{ background: {t['system_bg']}; color: {t['sub']}; font-size: 8.5pt; border-radius: 11px; padding: 4px 12px; }}
QLabel#timeSep {{ background: {t['system_bg']}; color: {t['sub']}; font-size: 8pt; font-weight: 600; border-radius: 9px; padding: 2px 10px; }}
QLabel#title {{ font-size: 11.5pt; font-weight: 600; }}
QLabel#largeTitle {{ font-size: 19pt; font-weight: 700; }}
QLabel#bigTitle {{ font-size: 24pt; font-weight: 700; }}
QLabel#dialogTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#subtitle {{ color: {t['sub']}; font-size: 8.5pt; }}
QLabel#section {{ color: {t['sub']}; font-size: 8.5pt; font-weight: 600; }}
QLabel#hint {{ color: {t['sub']}; font-size: 9pt; }}
QLabel#faint {{ color: {t['faint']}; font-size: 8.5pt; }}
QLabel#meName {{ font-size: 10pt; font-weight: 600; }}
QLabel#mono {{ font-family: "Cascadia Mono", Consolas, "SF Mono", monospace; font-size: 16pt; color: {t['text']}; }}
QLabel#monoSmall {{ font-family: "Cascadia Mono", Consolas, "SF Mono", monospace; font-size: 10pt; color: {t['text']}; }}
QLabel#good {{ color: {t['good']}; font-size: 9pt; }}
QLabel#warn {{ color: {t['warn']}; font-size: 9pt; }}
QLabel#bad {{ color: {t['bad']}; font-size: 9pt; }}
QLabel#viewerInfo {{ color: #98989D; font-size: 9pt; }}
QLabel#viewerBurn {{ color: #FF9F0A; font-size: 9pt; font-weight: 600; }}
QLabel#viewerText {{ color: #98989D; font-size: 11pt; }}
QToolButton#winBtn {{ border-radius: 7px; padding: 0; background: transparent; }}
QToolButton#winBtn:hover {{ background: {t['btn2_hover']}; }}
QToolButton#winClose {{ border-radius: 7px; padding: 0; background: transparent; }}
QToolButton#winClose:hover {{ background: #E81123; color: #FFFFFF; }}
QFrame#bentoPopup {{ background: {card}; border: 1px solid {t['line_strong']}; border-radius: 18px; }}
QPushButton#bentoTile {{ background: {t['btn2']}; border: 1px solid {t['line']}; border-radius: 13px; text-align: left; padding: 8px 11px; font-weight: 600; }}
QPushButton#bentoTile:hover {{ background: {t['select']}; border: 1px solid {t['accent']}; }}
QFrame#codeCard {{ background: {'#0D1117' if is_dark() else '#1E222A'}; border: 1px solid {t['line_strong']}; border-radius: 13px; }}
QFrame#codeHead {{ background: rgba(255,255,255,0.05); border: none; border-bottom: 1px solid rgba(255,255,255,0.08); border-top-left-radius: 12px; border-top-right-radius: 12px; }}
QLabel#codeLang {{ color: #9CA3AF; font-family: "Cascadia Mono", Consolas, monospace; font-size: 8pt; font-weight: 700; }}
QPushButton#codeCopy {{ background: rgba(255,255,255,0.08); color: #E5E7EB; border: none; border-radius: 6px; padding: 2px 9px; font-size: 8pt; min-height: 20px; }}
QPushButton#codeCopy:hover {{ background: rgba(255,255,255,0.18); }}
QLabel#codeBody {{ color: #E6EDF3; font-family: "Cascadia Mono", Consolas, "SF Mono", monospace; font-size: 9.2pt; padding: 8px 12px; selection-background-color: rgba(88,166,255,0.35); }}
QFrame#albumGrid {{ background: transparent; border: none; }}
""" + gomoku_qss(t, side)
