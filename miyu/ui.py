"""
密语 · 界面基础
常量、头像和颜色、时间 / 大小格式化、常用小部件的工厂函数(label / button / tool / make_menu…)、
拖放和文件类型工具。不依赖其它界面模块,所有界面文件都可以从这里导入。
"""
from __future__ import annotations

import datetime
import html
import os
import re
import sys
import time

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPixmap, QTextOption
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QMenu, QPushButton, QToolButton

from . import imaging
from .icons import app_logo, avatar
from .theme import T


APP_NAME = "密语"
TIME_GAP = 300                 # 两条消息间隔超过 5 分钟,中间显示时间
GROUP_GAP = 120                # 同一个人两分钟内连续发的消息合成一组显示
HEADER_H = 64


# 聊天热度:越聊越热,聊天区背景泛起暖色光晕,不说话后慢慢冷却
HEAT_HALF_LIFE = 25.0          # 秒
HEAT_IN, HEAT_OUT, HEAT_KEY = 0.15, 0.10, 0.004
HEAT_COLORS = {
    "light": ("#FF8A50", "#FF6FA0", "#FFB547"),
    "dusk": ("#FF8040", "#FF4F86", "#FFC14D"),
    "dark": ("#FF5F38", "#FF3F86", "#FFAA33"),
}


HEAT_COLORS.update({
    "sakura": ("#FF8A8A", "#FF5FA2", "#FFB86B"),
    "violet": ("#FF6A9A", "#D946EF", "#FFB454"),
    "ocean": ("#38BDF8", "#F472B6", "#FBBF24"),
    "terminal": ("#2EA043", "#58A6FF", "#3FB950"),
    "black": ("#FF5F38", "#FF3F86", "#FFAA33"),
})
HEAT_ALPHA = {"light": 0.42, "sakura": 0.40, "dusk": 0.46, "violet": 0.40, "ocean": 0.36, "dark": 0.40,
              "terminal": 0.24, "black": 0.32}
HIT_BG, HIT_FG = "#FFE066", "#1D1D1F"
BURN_CHOICES = [("关闭", 0), ("10 秒", 10), ("30 秒", 30), ("1 分钟", 60), ("5 分钟", 300)]
AVATAR_COLORS = ["#6C8EBF", "#C9956B", "#7BA67A", "#9B87C4", "#C67D8F", "#64A6B0", "#B59E66", "#7E9C93"]
LOBBY_COLOR = "#7C8BA1"
ROOM_COLOR = "#8E86B4"


def resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


AVATARS: dict = {}                 # 自定义头像:用户 id → QImage(自己的和别人发来的)


_avatar_pm: dict = {}


def clear_avatar_cache() -> None:
    _avatar_pm.clear()


def peer_avatar(pid: str, nick: str, size: int) -> QPixmap:
    """某个人的头像:有自定义图片就裁成圆形,没有就用名字首字的渐变头像。"""
    img = AVATARS.get(pid)
    if img is None:
        return avatar(nick, color_for(pid), size)
    pm = _avatar_pm.get((pid, size))
    if pm is None:
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addEllipse(QRectF(0, 0, size, size))
        p.setClipPath(clip)
        p.drawImage(QRectF(0, 0, size, size), img)
        p.end()
        _avatar_pm[(pid, size)] = pm
    return pm


def color_for(pid: str) -> str:
    try:
        return AVATAR_COLORS[int(pid[:4], 16) % len(AVATAR_COLORS)]
    except (ValueError, TypeError):
        return AVATAR_COLORS[0]


_LONG_RUN = re.compile(r"[\x21-\x7e]{28,}")


def soft_wrap(text: str) -> str:
    """超长的英文/链接中间插入零宽空格,让气泡能换行。"""
    return _LONG_RUN.sub(lambda m: "​".join(m.group(0)[i:i + 28] for i in range(0, len(m.group(0)), 28)), text)


def fmt_secs(s: float) -> str:
    s = max(0, int(s + 0.999))
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s}s"


def highlight_html(text: str, query: str) -> str:
    """把 text 里所有 query(不分大小写)包上高亮,其余部分转义成安全的 HTML。"""
    low, q = text.lower(), query.lower()
    out, i = [], 0
    while q:
        j = low.find(q, i)
        if j < 0:
            break
        out.append(html.escape(soft_wrap(text[i:j])))
        out.append(f'<span style="background-color:{HIT_BG}; color:{HIT_FG};">{html.escape(text[j:j + len(q)])}</span>')
        i = j + len(q)
    out.append(html.escape(soft_wrap(text[i:])))
    return "".join(out).replace("\n", "<br>")


_FENCE_RE = re.compile(r"```([A-Za-z0-9_+#.-]{0,18})[ \t]*\r?\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\r\n]{1,180})`")
_CODE_TOKEN_RE = re.compile(
    r'(?P<comment>#[^\n]*|//[^\n]*|/\*[\s\S]*?\*/)'
    r'|(?P<string>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')'
    r'|(?P<deco>@[A-Za-z_]\w*)'
    r'|(?P<kw>\b(?:def|class|return|import|from|as|if|elif|else|for|while|break|continue|try|except|finally|with|'
    r'raise|yield|lambda|pass|async|await|in|not|and|or|is|global|nonlocal|const|let|var|function|export|default|'
    r'new|switch|case|struct|enum|impl|fn|pub|mut|match|use|package|func|go|defer|interface|type|public|private|'
    r'protected|static|void|int|float|double|bool|string|SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|JOIN|ORDER|GROUP|BY)\b)'
    r'|(?P<lit>\b(?:True|False|None|true|false|null|undefined|self|this|super)\b|\b\d+(?:\.\d+)?\b)'
)


def parse_markdown_blocks(text: str) -> list[tuple[str, str, str]]:
    """把含 ``` 代码块的消息拆成 [('text', '', 文本), ('code', 语言, 代码), ...]。全程纯解析不执行 HTML。"""
    if "```" not in text:
        return [("text", "", text)]
    out: list[tuple[str, str, str]] = []
    pos = 0
    for m in _FENCE_RE.finditer(text):
        if m.start() > pos:
            pre = text[pos:m.start()].strip("\r\n")
            if pre.strip():
                out.append(("text", "", pre))
        lang = (m.group(1) or "").strip().lower()
        body = m.group(2).rstrip("\r\n")
        out.append(("code", lang, body))
        pos = m.end()
    if not out:
        return [("text", "", text)]
    if pos < len(text):
        tail = text[pos:].strip("\r\n")
        if tail.strip():
            out.append(("text", "", tail))
    return out


def has_inline_code(text: str) -> bool:
    return "`" in text and bool(_INLINE_CODE_RE.search(text))


def inline_code_html(text: str, on_accent: bool = False) -> str:
    """把行内 `code` 安全转义为等宽底色标签,其余部分完全 HTML 转义。"""
    bg = "rgba(255,255,255,0.22)" if on_accent else "rgba(127,135,150,0.20)"
    parts: list[str] = []
    pos = 0
    for m in _INLINE_CODE_RE.finditer(text):
        if m.start() > pos:
            parts.append(html.escape(soft_wrap(text[pos:m.start()])))
        code_txt = html.escape(soft_wrap(m.group(1)))
        parts.append(
            f'<span style="font-family:\'Cascadia Mono\',Consolas,monospace; background-color:{bg}; '
            f'padding:1px 5px; border-radius:4px; font-size:9pt;">{code_txt}</span>'
        )
        pos = m.end()
    if pos < len(text):
        parts.append(html.escape(soft_wrap(text[pos:])))
    return "".join(parts).replace("\n", "<br>")


def _esc_code(seg: str) -> str:
    return html.escape(seg).replace("  ", "&nbsp; ").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")


def highlight_code_html(code: str, lang: str = "") -> str:
    """零依赖轻量语法高亮,所有字符严格经过 html.escape。"""
    code = soft_wrap(code.expandtabs(4))
    colors = {
        "comment": "#8B949E",
        "string": "#A5D6FF",
        "deco": "#D2A8FF",
        "kw": "#FF7B72",
        "lit": "#79C0FF",
    }
    out: list[str] = []
    pos = 0
    for m in _CODE_TOKEN_RE.finditer(code):
        if m.start() > pos:
            out.append(_esc_code(code[pos:m.start()]))
        kind = m.lastgroup or ""
        col = colors.get(kind, "#E6EDF3")
        tok = _esc_code(m.group(0))
        out.append(f'<span style="color:{col};">{tok}</span>')
        pos = m.end()
    if pos < len(code):
        out.append(_esc_code(code[pos:]))
    res = "".join(out).replace("\n", "<br>")
    return re.sub(r"(?:^|(?<=<br>))( +)", lambda m: "&nbsp;" * len(m.group(1)), res)


def fmt_eta(secs: float) -> str:
    secs = int(secs + 0.999)
    if secs < 60:
        return f"剩 {max(1, secs)} 秒"
    if secs < 3600:
        return f"剩 {secs // 60} 分 {secs % 60:02d} 秒" if secs < 600 else f"剩 {secs // 60} 分钟"
    return f"剩 {secs // 3600} 小时 {secs % 3600 // 60} 分"


def fmt_speed(bps: float) -> str:
    return imaging.human_size(int(bps)) + "/s"


def fmt_sep(ts: float) -> str:
    d = datetime.date.fromtimestamp(ts)
    today = datetime.date.today()
    hm = time.strftime("%H:%M", time.localtime(ts))
    if d == today:
        return f"今天 {hm}"
    if d == today - datetime.timedelta(days=1):
        return f"昨天 {hm}"
    return f"{d.month}月{d.day}日 {hm}"


def fmt_list_time(ts: float) -> str:
    if not ts:
        return ""
    d = datetime.date.fromtimestamp(ts)
    today = datetime.date.today()
    if d == today:
        return time.strftime("%H:%M", time.localtime(ts))
    if d == today - datetime.timedelta(days=1):
        return "昨天"
    return f"{d.month}/{d.day}"


def make_icon() -> QIcon:
    path = resource_path("assets", "icon.png")
    return QIcon(path) if os.path.exists(path) else QIcon(app_logo(256))


def make_menu(parent) -> QMenu:
    """圆角菜单:背景透明 + 去掉系统方形阴影,圆角才不会露出直角。弹出时淡入、轻轻滑下。"""
    from .motion import FadeMenu
    m = FadeMenu(parent)
    m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    return m


def popup(menu, pos) -> None:
    """弹出一次性的右键菜单,关掉后释放(不然每点一次右键就多留一个菜单在内存里)。"""
    try:
        menu.exec(pos)
    finally:
        menu.deleteLater()


def add_shadow(widget, blur: int = 28, dy: int = 6, strength: float = 1.0) -> QGraphicsDropShadowEffect:
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    r, g, b, a = T["shadow"]
    eff.setColor(QColor(r, g, b, int(a * strength)))
    widget.setGraphicsEffect(eff)
    return eff


def repolish(w) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("sep")
    return f


def label(text: str, obj: str = "", wrap: bool = False, center: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    if obj:
        lab.setObjectName(obj)
    if wrap:
        lab.setWordWrap(True)
    if center:
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lab


def button(text: str, obj: str = "", slot=None, min_w: int = 0) -> QPushButton:
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    b.setMinimumHeight(36)
    if min_w:
        b.setMinimumWidth(min_w)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot is not None:
        b.clicked.connect(slot)
    return b


def tool(icon_name: str = "", size: int = 34, obj: str = "round", tip: str = "") -> QToolButton:
    b = QToolButton()
    b.setObjectName(obj)
    b.setFixedSize(size, size)
    b.setIconSize(QSize(18, 18))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setProperty("iconName", icon_name)
    b.setStyleSheet(f"QToolButton {{ border-radius: {size // 2}px; }}")      # 圆形按钮
    if tip:
        b.setToolTip(tip)
    return b


def local_paths(mime) -> list[str]:
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]


def drop_paths(mime) -> list[str]:
    """拖进来的本地文件和文件夹。"""
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and os.path.exists(u.toLocalFile())]


def image_paths(mime) -> list[str]:
    return [p for p in local_paths(mime) if imaging.is_image_path(p)][:9]


def file_paths(mime) -> list[str]:
    return [p for p in local_paths(mime) if not imaging.is_image_path(p)][:20]


def images_from_mime(mime):
    """剪贴板/拖放里有图片就返回 [QImage...],否则返回 None。带文字时优先当文字处理。"""
    paths = image_paths(mime)
    if paths:
        return [imaging.load_image_path(p) for p in paths]     # 动图返回 Gif,保持会动
    if mime.hasImage() and not mime.hasUrls() and not (mime.hasText() and mime.text().strip()):
        data = mime.imageData()
        if isinstance(data, QPixmap):
            data = data.toImage()
        if isinstance(data, QImage) and not data.isNull():
            return [data]
    return None


VIDEO_EXTS = {"mp4", "mkv", "mov", "avi", "webm", "m4v", "wmv", "flv", "ts", "mpg", "mpeg", "3gp"}
DANGER_EXTS = {"exe", "bat", "cmd", "com", "scr", "msi", "ps1", "vbs", "vbe", "js", "jse", "jar", "lnk", "reg",
               "hta", "cpl", "pif", "wsf", "dll", "sys"}


def file_ext(name: str) -> str:
    return os.path.splitext(name or "")[1].lower().lstrip(".")


EMOJI_GROUPS = [
    ("常用", "😀 😂 🤣 😊 😍 🥰 😘 😎 🤔 😅 😭 😡 👍 👏 🙏 ❤️ 🎉 🔥 ✨ 💯 👌 😴 🤗 🙈".split()),
    ("表情", ("😃 😄 😁 😆 🙂 🙃 😉 😇 🤩 😋 😛 😜 🤪 😝 🤑 🤭 🤫 🤐 🤨 😐 😑 😶 😏 😒 🙄 😬 😌 😔 😪 🤤 "
            "😷 🤒 🤕 🤢 🤮 🥵 🥶 🥴 😵 🤯 🤠 🥳 🤓 🧐 😕 😟 🙁 😮 😯 😲 😳 🥺 😦 😧 😨 😰 😥 😢 😱 😖 "
            "😣 😞 😓 😩 😫 🥱 😤 😠 🤬 😈 💀 💩 🤡 👻 👽 🤖").split()),
    ("手势", "👋 🤚 🖐️ ✋ 🖖 👌 🤌 🤏 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👎 ✊ 👊 🤛 🤜 🙌 👐 🤲 🤝 ✍️ 💪".split()),
    ("心情", "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💋 💌 💤 💢 💥 💦 💨 💬 👀".split()),
    ("物品", ("🎉 🎊 🎁 🎂 🍰 ☕ 🍵 🍺 🍻 🥂 🍷 🍕 🍔 🍟 🍜 🍣 🍉 🍓 🌹 🌸 🌻 🍀 ⭐ 🌙 ☀️ 🌈 ⚡ ❄️ "
            "☔ 🎵 🎮 ⚽ 🏀 🚗 ✈️ 🏠 📱 💻 📷 💡 💰 📌 ✅ ❌ ❓ ❗ ⭕ 🆗 🐶 🐱 🐼 🐷 🐸 🐵 🦊 🐰").split()),
]


def emoji_font(px: int = 22) -> QFont:
    f = QFont()
    f.setFamilies(["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Segoe UI Symbol"])
    f.setPixelSize(px)
    return f


def _text_opt(align, wrap: bool = False) -> QTextOption:
    opt = QTextOption(align)
    opt.setWrapMode(QTextOption.WrapMode.WordWrap if wrap else QTextOption.WrapMode.NoWrap)
    return opt
