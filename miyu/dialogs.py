"""
密语 · 通用对话框
基础 Dialog(毛玻璃、壁纸)、确认 / 提示 / 输入框、开关,以及启动、加入暗号群、安全码、文本、
注销、发图、看图、多行输入这些对话框。
"""
from __future__ import annotations

import os
import re
import time

from PySide6.QtCore import QPointF, QRectF, QSize, QStandardPaths, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from . import imaging, theme
from .core import MAX_NICK, clean_nick
from .icons import app_logo, icon
from .theme import T
from .ui import APP_NAME, button, fmt_secs, hline, label, repolish, tool
from .widgets import ClickLabel, Msg


class Dialog(QDialog):
    """所有对话框的基类:Windows 11 上同样使用毛玻璃,标题栏跟随深浅色。"""

    def __init__(self, parent=None, title: str = APP_NAME) -> None:
        super().__init__(parent)
        if theme.GLASS_SUPPORTED:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._glass_capable = True
        self.setWindowTitle(title)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        theme.style_titlebar(self)
        if not getattr(self, "_shown_once", False):          # 3.7: 第一次弹出时 150ms 轻弹淡入 + 微幅上滑
            self._shown_once = True
            from . import motion
            motion.fade_window(self, 150)
            if motion.ENABLED and not getattr(self, "_no_slide", False):
                try:
                    from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation
                    end_p = self.pos()
                    if end_p.x() != 0 or end_p.y() != 0:
                        anim = QPropertyAnimation(self, b"pos", self)
                        anim.setDuration(150)
                        anim.setStartValue(QPoint(end_p.x(), end_p.y() + 8))
                        anim.setEndValue(end_p)
                        anim.setEasingCurve(QEasingCurve.Type.OutBack)
                        anim.start()
                        self._enter_pos_anim = anim
                except Exception:
                    pass

    def paintEvent(self, e) -> None:
        if self.objectName() != "viewer":
            theme.paint_wallpaper(self, e)
            # 3.7 统一 1px 顶边液态玻璃高光折射边
            p = QPainter(self)
            p.setPen(QColor(255, 255, 255, 48 if theme.is_dark() else 140))
            p.drawLine(0, 0, self.width(), 0)
            p.end()


def _screen_max_h(parent, ratio: float = 0.78, fallback: int = 560) -> int:
    try:
        scr = parent.screen() if parent is not None and hasattr(parent, "screen") and parent.screen() is not None else QApplication.primaryScreen()
        if scr is not None and hasattr(scr, "availableGeometry"):
            h = int(scr.availableGeometry().height() * ratio)
            if h > 260:
                return h
    except Exception:
        pass
    return fallback


class AlertDialog(Dialog):
    def __init__(self, parent, title: str, text: str, buttons: list[tuple[str, str]]) -> None:
        super().__init__(parent)
        long_text = bool(text) and (len(text) > 180 or text.count("\n") >= 5)
        self.setFixedWidth(460 if long_text else 380)
        self.setMaximumHeight(_screen_max_h(parent, 0.78, 580))
        self.choice = -1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28 if long_text else 30, 24 if long_text else 26, 28 if long_text else 30, 20 if long_text else 22)
        lay.setSpacing(8)
        lay.addWidget(label(title, "dialogTitle", wrap=True, center=True))
        if text:
            if long_text:
                card = QFrame(self)
                card.setObjectName("plainCard")
                cl = QVBoxLayout(card)
                cl.setContentsMargins(14, 10, 10, 10)
                body = label(text, "hint", wrap=True, center=False)
                body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                area = QScrollArea(card)
                area.setWidgetResizable(True)
                area.setFrameShape(QFrame.Shape.NoFrame)
                area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                area.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
                area.setWidget(body)
                max_scroll = min(360, max(180, _screen_max_h(parent, 0.52, 340)))
                area.setMaximumHeight(max_scroll)
                area.setMinimumHeight(min(max_scroll, 200))
                cl.addWidget(area)
                lay.addWidget(card, 1)
            else:
                lay.addWidget(label(text, "hint", wrap=True, center=True))
        lay.addSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        for i, (text_, kind) in enumerate(buttons):
            b = button(text_, kind)
            b.clicked.connect(lambda _=False, i=i: self._pick(i))
            row.addWidget(b)
            if i == len(buttons) - 1:
                b.setDefault(True)
        lay.addLayout(row)

    def _pick(self, i: int) -> None:
        self.choice = i
        self.accept()


def ask(parent, title: str, text: str, yes: str = "确定", no: str = "取消", danger: bool = False) -> bool:
    d = AlertDialog(parent, title, text, [(no, ""), (yes, "destructive" if danger else "primary")])
    d.exec()
    return d.choice == 1


def info(parent, title: str, text: str, warn: bool = False) -> None:
    AlertDialog(parent, title, text, [("好", "primary")]).exec()


class PromptDialog(Dialog):
    def __init__(self, parent, title: str, text: str, value: str, placeholder: str, ok: str, max_len: int) -> None:
        super().__init__(parent)
        self.setFixedWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label(title, "dialogTitle", wrap=True))
        if text:
            lay.addWidget(label(text, "hint", wrap=True))
        lay.addSpacing(6)
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText(placeholder)
        if max_len:
            self.edit.setMaxLength(max_len)
        self.edit.selectAll()
        lay.addWidget(self.edit)
        lay.addSpacing(12)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 88))
        okb = button(ok, "primary", self.accept, 88)
        okb.setDefault(True)
        row.addWidget(okb)
        lay.addLayout(row)


def prompt(parent, title: str, text: str = "", value: str = "", placeholder: str = "", ok: str = "确定",
           max_len: int = 0) -> str | None:
    d = PromptDialog(parent, title, text, value, placeholder, ok, max_len)
    return d.edit.text() if d.exec() else None


class Switch(QAbstractButton):
    """iOS 风格开关。"""

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 28)

    def sizeHint(self) -> QSize:
        return QSize(46, 28)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QColor(T["good"]) if on else QColor("#39393D" if theme.is_dark() else "#E5E5EA")
        if not self.isEnabled():
            track.setAlpha(120)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 46, 28), 14, 14)
        x = 20 if on else 2
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(QRectF(x, 3, 24, 24))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 2, 24, 24))
        p.end()


def _card_row(title: str, widget, title_w: int = 64) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    t = label(title)
    t.setFixedWidth(title_w)
    row.addWidget(t)
    row.addWidget(widget, 1)
    return row


def _feature_row(icon_name: str, text: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    ic = QLabel()
    ic.setPixmap(icon(icon_name, T["sub"], 16).pixmap(16, 16))
    ic.setFixedSize(18, 18)
    row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
    row.addWidget(label(text, "hint", wrap=True), 1)
    return row


class StartDialog(Dialog):
    def __init__(self, default_nick: str, app_icon: QIcon) -> None:
        super().__init__(None)
        self.setWindowIcon(app_icon)
        self.setFixedWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(38, 34, 38, 30)
        lay.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(app_logo(76))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)
        lay.addSpacing(6)
        lay.addWidget(label(APP_NAME, "bigTitle", center=True))
        lay.addWidget(label("局域网里的私密对话", "hint", center=True))
        lay.addSpacing(22)

        card = QFrame()
        card.setObjectName("plainCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 2, 14, 2)
        cl.setSpacing(0)
        self.nick = QLineEdit(default_nick)
        self.nick.setObjectName("cardEdit")
        self.nick.setMaxLength(MAX_NICK)
        self.nick.setPlaceholderText("随便起一个,不需要真名")
        self.nick.selectAll()
        cl.addLayout(_card_row("昵称", self.nick))
        cl.addWidget(hline())
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 8)
        row.addWidget(label("进入公开大厅"))
        row.addStretch(1)
        self.lobby = Switch(True)
        row.addWidget(self.lobby)
        cl.addLayout(row)
        cl.addWidget(hline())
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 8)
        row.addWidget(label("记住我(下次自动登录)"))
        row.addStretch(1)
        self.remember = Switch(True)
        row.addWidget(self.remember)
        cl.addLayout(row)
        cl.addWidget(hline())
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 8)
        row.addWidget(label("保存聊天记录"))
        row.addStretch(1)
        self.history = Switch(False)
        row.addWidget(self.history)
        cl.addLayout(row)
        lay.addWidget(card)
        self.remember.toggled.connect(lambda on: (self.history.setEnabled(on), on or self.history.setChecked(False)))
        tip = label("关闭大厅为隐身:只有和你使用同一暗号的人才能发现你。\n"
                    "账户和记录都加密保存在本机,随时可以在设置里「注销账户」彻底删除。", "faint", wrap=True)
        tip.setContentsMargins(6, 4, 6, 0)
        lay.addWidget(tip)
        lay.addSpacing(18)

        for name, text in (("lock", "点对点加密,不经过任何服务器"),
                           ("eye_off", "身份随机生成,不需要手机号或任何账号"),
                           ("shield", "按 ESC 让软件消失,Ctrl+Alt+H 叫回")):
            lay.addLayout(_feature_row(name, text))
            lay.addSpacing(2)
        lay.addSpacing(20)
        go = button("开始", "primary", self.accept)
        go.setMinimumHeight(42)
        go.setDefault(True)
        lay.addWidget(go)

    @property
    def nickname(self) -> str:
        return clean_nick(self.nick.text())

    @property
    def join_lobby(self) -> bool:
        return self.lobby.isChecked()

    @property
    def remember_me(self) -> bool:
        return self.remember.isChecked()

    @property
    def save_history(self) -> bool:
        return self.remember.isChecked() and self.history.isChecked()


class JoinRoomDialog(Dialog):
    def __init__(self, parent) -> None:
        super().__init__(parent, "暗号群")
        self.setFixedWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label("加入或创建暗号群", "dialogTitle"))
        lay.addWidget(label("输入同一个暗号的人会进入同一个群。第一个使用这个暗号的人,就是建群的人。", "hint", wrap=True))
        lay.addSpacing(10)

        card = QFrame()
        card.setObjectName("plainCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 2, 8, 2)
        cl.setSpacing(0)
        pw_row = QHBoxLayout()
        self.pw = QLineEdit()
        self.pw.setObjectName("cardEdit")
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.setPlaceholderText("至少 6 个字,越长越安全")
        self.pw.textChanged.connect(self._check)
        pw_row.addWidget(self.pw, 1)
        self.eye = tool("eye_off", 30, "round", "显示 / 隐藏暗号")
        self.eye.setIcon(icon("eye_off", T["icon"], 18))
        self.eye.setCheckable(True)
        self.eye.toggled.connect(lambda on: self.pw.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        pw_row.addWidget(self.eye)
        wrap = QWidget()
        wrap.setLayout(pw_row)
        pw_row.setContentsMargins(0, 0, 0, 0)
        cl.addLayout(_card_row("暗号", wrap))
        cl.addWidget(hline())
        self.name = QLineEdit()
        self.name.setObjectName("cardEdit")
        self.name.setMaxLength(MAX_NICK)
        self.name.setPlaceholderText("仅自己可见,可不填")
        cl.addLayout(_card_row("群名称", self.name))
        lay.addWidget(card)

        self.strength = label(" ", "faint")
        self.strength.setContentsMargins(6, 2, 0, 0)
        lay.addWidget(self.strength)
        tip = label("别人抓到加密的广播后,可以离线慢慢猜暗号。建议 12 个字以上,或几个不相关的词拼起来,"
                    "例如「晴天-猫爪-火锅-0917」。", "faint", wrap=True)
        tip.setContentsMargins(6, 0, 6, 0)
        lay.addWidget(tip)
        lay.addSpacing(14)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 88))
        self.ok = button("加入", "primary", self.accept, 88)
        self.ok.setDefault(True)
        self.ok.setEnabled(False)
        row.addWidget(self.ok)
        lay.addLayout(row)

    def _check(self, text: str) -> None:
        t = text.strip()
        n = len(t)
        kinds = sum(bool(re.search(p, t)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]", r"[一-鿿]"))
        score = n + len(re.findall(r"[一-鿿]", t))     # 汉字可能性多,按 2 个字符算
        if n == 0:
            msg, obj = " ", "faint"
        elif n < 6:
            msg, obj = "太短,至少 6 个字", "bad"
        elif score < 10 or kinds < 2:
            msg, obj = "强度:弱,容易被猜中", "warn"
        elif score < 14:
            msg, obj = "强度:一般", "warn"
        else:
            msg, obj = "强度:强", "good"
        self.strength.setText(msg)
        self.strength.setObjectName(obj)
        repolish(self.strength)
        self.ok.setEnabled(n >= 6)

    @property
    def passphrase(self) -> str:
        return self.pw.text()

    @property
    def room_name(self) -> str:
        return clean_nick(self.name.text())


class SafetyDialog(Dialog):
    def __init__(self, parent, peer_label: str, number: str, verified: bool) -> None:
        super().__init__(parent, "验证安全码")
        self.setFixedWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 26, 30, 22)
        lay.setSpacing(8)
        lay.addWidget(label("安全码", "dialogTitle", center=True))
        lay.addWidget(label(f"你和 {peer_label}", "hint", center=True))
        lay.addSpacing(12)
        card = QFrame()
        card.setObjectName("plainCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 18, 18, 18)
        groups = number.split()
        num = label("   ".join(groups[:4]) + "\n" + "   ".join(groups[4:]), "mono", center=True)
        num.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(num)
        lay.addWidget(card)
        lay.addSpacing(10)
        lay.addWidget(label("当面或打电话和对方核对这串数字,不要用本软件发送。\n"
                            "两边完全一样,说明没有人在中间冒充或偷听。", "hint", wrap=True, center=True))
        lay.addWidget(label("身份每次启动都会重新生成,对方重启后需要重新核对。", "faint", wrap=True, center=True))
        lay.addSpacing(14)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("关闭", "", self.reject))
        if not verified:
            ok = button("核对一致", "primary", self.accept)
            ok.setDefault(True)
            row.addWidget(ok)
        lay.addLayout(row)


class TextDialog(Dialog):
    def __init__(self, parent, title: str, rows: list[tuple[str, str]], note: str = "", width: int = 460,
                 extra: tuple[str, str] | None = None) -> None:
        super().__init__(parent, title)
        self.extra_clicked = False
        self.setFixedWidth(width)
        self.setMaximumHeight(_screen_max_h(parent, 0.80, 620))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label(title, "dialogTitle"))
        lay.addSpacing(6)
        card = QFrame()
        card.setObjectName("plainCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(6)
        total_chars = 0
        total_lines = 0
        for i, (name, value) in enumerate(rows):
            total_chars += len(name) + len(value)
            total_lines += 1 + value.count("\n")
            if i:
                cl.addSpacing(4)
                cl.addWidget(hline())
                cl.addSpacing(4)
            if name:
                cl.addWidget(label(name, "section"))
            v = label(value, "monoSmall" if name else "hint", wrap=True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(v)
        if total_chars > 260 or total_lines >= 8 or len(rows) >= 5:
            area = QScrollArea(self)
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
            area.setWidget(card)
            max_h = min(420, max(200, _screen_max_h(parent, 0.56, 380)))
            area.setMaximumHeight(max_h)
            area.setMinimumHeight(min(max_h, 220))
            lay.addWidget(area, 1)
        else:
            lay.addWidget(card)
        if note:
            n = label(note, "faint", wrap=True)
            n.setContentsMargins(6, 4, 6, 0)
            lay.addWidget(n)
        lay.addSpacing(12)
        row = QHBoxLayout()
        if extra:
            xb = button(extra[0], extra[1], self._on_extra)
            xb.setObjectName("extraBtn")
            row.addWidget(xb)
        row.addStretch(1)
        ok = button("完成", "primary", self.accept, 96)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)

    def _on_extra(self) -> None:
        self.extra_clicked = True
        self.accept()


class LogoutDialog(Dialog):
    """注销账户确认:可以选择是否同时删除表情包。"""

    def __init__(self, parent, remember: bool) -> None:
        super().__init__(parent, "注销账户")
        self.setFixedWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 26, 30, 22)
        lay.setSpacing(8)
        lay.addWidget(label("注销账户?", "dialogTitle", center=True))
        what = ("这台电脑上保存的身份、暗号群、设置、宠物成长和聊天记录都会被彻底删除。" if remember
                else "当前的身份、暗号群和聊天记录都会被销毁。")
        lay.addWidget(label(what + "\n软件会以一个全新的身份重新启动,别人那里看到的你会变成另一个人,"
                                  "之前的安全码验证也会失效。", "hint", wrap=True, center=True))
        lay.addSpacing(8)
        card = QFrame()
        card.setObjectName("plainCard")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(16, 8, 14, 8)
        cl.addWidget(label("同时删除表情包"))
        cl.addStretch(1)
        self.stickers = Switch(False)
        cl.addWidget(self.stickers)
        lay.addWidget(card)
        lay.addSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("取消", "", self.reject))
        go = button("注销并重新启动", "destructive", self.accept)
        row.addWidget(go)
        lay.addLayout(row)

    @property
    def delete_stickers(self) -> bool:
        return self.stickers.isChecked()


def compose_collage(images: list[QImage], canvas_w: int = 1080) -> QImage | None:
    """把 2~9 张静态图合成一张圆角九宫格相册图。"""
    imgs = [im for im in images if im is not None and not im.isNull()][:9]
    if not imgs:
        return None
    if len(imgs) == 1:
        return imgs[0]
    cols = 2 if len(imgs) <= 4 else 3
    rows = (len(imgs) + cols - 1) // cols
    gap = 12
    pad = 16
    cell = (canvas_w - 2 * pad - (cols - 1) * gap) // cols
    canvas_h = 2 * pad + rows * cell + (rows - 1) * gap
    out = QImage(canvas_w, canvas_h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(QColor("#161922" if theme.is_dark() else "#F4F6FB"))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for idx, im in enumerate(imgs):
        r, c = idx // cols, idx % cols
        x = pad + c * (cell + gap)
        y = pad + r * (cell + gap)
        # 最后一行若只有 1 张且 2 列时铺满整行更美观
        w = cell
        if len(imgs) == 3 and idx == 2:
            w = cell * 2 + gap
        scaled = im.scaled(w, cell, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
        sx = max(0, (scaled.width() - w) // 2)
        sy = max(0, (scaled.height() - cell) // 2)
        cropped = scaled.copy(sx, sy, w, cell)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(x, y, w, cell), 18, 18)
        p.save()
        p.setClipPath(clip)
        p.drawImage(QRectF(x, y, w, cell), cropped)
        p.restore()
    p.end()
    return out


class _MosaicPreview(QLabel):
    """3.2 截图发送前预览 + 鼠标涂抹打马赛克控件(防发错图 & 快速遮挡敏感信息)。"""

    def __init__(self, img: QImage, parent=None) -> None:
        super().__init__(parent)
        self._orig = img.convertToFormat(QImage.Format.Format_ARGB32)
        self._work = self._orig.copy()
        self.mosaic_on = False
        self.dirty = False
        self._down = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh()

    def set_mosaic(self, on: bool) -> None:
        self.mosaic_on = bool(on)
        self.setCursor(Qt.CursorShape.CrossCursor if self.mosaic_on else Qt.CursorShape.ArrowCursor)

    def reset(self) -> None:
        self._work = self._orig.copy()
        self.dirty = False
        self._refresh()

    def _refresh(self, fast: bool = False) -> None:
        mode = Qt.TransformationMode.FastTransformation if fast else Qt.TransformationMode.SmoothTransformation
        pm = QPixmap.fromImage(self._work).scaled(
            340, 240, Qt.AspectRatioMode.KeepAspectRatio, mode
        )
        self.setPixmap(pm)
        self.setFixedSize(pm.size())

    def _paint_mosaic_at(self, pos) -> None:
        if not self.mosaic_on or self.width() <= 0 or self.height() <= 0:
            return
        w, h = self._work.width(), self._work.height()
        ix = int(pos.x() * w / self.width())
        iy = int(pos.y() * h / self.height())
        bs = max(8, min(w, h) // 28)
        rad = bs * 2
        x0 = max(0, ((ix - rad) // bs) * bs)
        y0 = max(0, ((iy - rad) // bs) * bs)
        x1 = min(w, ix + rad)
        y1 = min(h, iy + rad)
        p = QPainter(self._work)
        p.setPen(Qt.PenStyle.NoPen)
        for bx in range(x0, x1, bs):
            for by in range(y0, y1, bs):
                cx = min(w - 1, bx + bs // 2)
                cy = min(h - 1, by + bs // 2)
                p.setBrush(self._orig.pixelColor(cx, cy))
                p.drawRect(bx, by, bs, bs)
        p.end()
        self.dirty = True
        self._refresh(fast=True)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.mosaic_on:
            self._down = True
            self._paint_mosaic_at(e.position() if hasattr(e, "position") else e.pos())

    def mouseMoveEvent(self, e) -> None:
        if self._down and self.mosaic_on:
            self._paint_mosaic_at(e.position() if hasattr(e, "position") else e.pos())

    def mouseReleaseEvent(self, e) -> None:
        if self._down:
            self._down = False
            self._refresh(fast=False)


class SendImageDialog(Dialog):
    def __init__(self, parent, preview: QPixmap, count: int, total: int, burn: int, target: str, bad: int,
                 thumbs: list[QPixmap] | None = None, can_collage: bool = False,
                 raw_image: QImage | None = None) -> None:
        super().__init__(parent, "发送图片")
        self.setMinimumWidth(420)
        self.collage_sw: Switch | None = None
        self._mosaic: _MosaicPreview | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label("发送图片" if count == 1 else f"发送 {count} 张图片", "dialogTitle", center=True))
        lay.addWidget(label(f"到「{target}」", "hint", center=True))
        lay.addSpacing(8)
        if thumbs and len(thumbs) >= 2:
            grid_wrap = QFrame(self)
            grid_wrap.setObjectName("albumGrid")
            gl = QGridLayout(grid_wrap)
            gl.setContentsMargins(4, 4, 4, 4)
            gl.setSpacing(6)
            cols = 2 if len(thumbs) <= 4 else 3
            for idx, pm in enumerate(thumbs[:9]):
                cell = QLabel(grid_wrap)
                cell.setPixmap(pm)
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                gl.addWidget(cell, idx // cols, idx % cols)
            lay.addWidget(grid_wrap, 0, Qt.AlignmentFlag.AlignHCenter)
        elif raw_image is not None and not raw_image.isNull() and count == 1:
            self._mosaic = _MosaicPreview(raw_image, self)
            lay.addWidget(self._mosaic, 0, Qt.AlignmentFlag.AlignHCenter)
            mrow = QHBoxLayout()
            mrow.addStretch(1)
            mbtn = QPushButton("🎨 涂抹马赛克", self)
            mbtn.setObjectName("tab")
            mbtn.setCheckable(True)
            mbtn.setCursor(Qt.CursorShape.PointingHandCursor)
            mbtn.toggled.connect(self._mosaic.set_mosaic)
            mrow.addWidget(mbtn)
            mrow.addWidget(button("↩ 还原", "link", self._mosaic.reset, 64))
            mrow.addStretch(1)
            lay.addLayout(mrow)
        else:
            pic = QLabel(self)
            pic.setPixmap(preview)
            pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(pic, 0, Qt.AlignmentFlag.AlignHCenter)
        if can_collage and count >= 2:
            card = QFrame(self)
            card.setObjectName("plainCard")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 7, 12, 7)
            cl.addWidget(label("合并为九宫格相册拼图(单条发出)"))
            cl.addStretch(1)
            self.collage_sw = Switch(False, card)
            cl.addWidget(self.collage_sw)
            lay.addWidget(card)
        lay.addSpacing(6)
        lay.addWidget(label(f"{imaging.human_size(total)} · 已压缩,并去掉了照片里的位置、设备等隐私信息",
                            "faint", wrap=True, center=True))
        if bad:
            lay.addWidget(label(f"另有 {bad} 张无法读取,已跳过", "warn", center=True))
        if burn:
            lay.addWidget(label(f"🔥 阅后即焚:对方打开后 {fmt_secs(burn)} 自动删除", "warn", center=True))
        lay.addSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("取消", "", self.reject))
        ok = button("发送", "primary", self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)

    @property
    def merge_collage(self) -> bool:
        return bool(self.collage_sw is not None and self.collage_sw.isChecked())

    @property
    def edited_image(self) -> QImage | None:
        return self._mosaic._work if (self._mosaic is not None and self._mosaic.dirty) else None


class _ZoomCanvas(QWidget):
    """支持滚轮缩放(25%~500%)、拖拽平移、双击切换 1:1/适应窗口的看图画布。"""
    clicked = Signal()
    zoom_changed = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.img: QImage | None = None
        self.zoom = 1.0
        self.pan = QPointF(0.0, 0.0)
        self._down: QPointF | None = None
        self._pan_start = QPointF(0.0, 0.0)
        self._dragged = False
        self.setMinimumSize(420, 300)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_image(self, img: QImage | None) -> None:
        self.img = img
        self.zoom = 1.0
        self.pan = QPointF(0.0, 0.0)
        self.zoom_changed.emit(self.zoom)
        self.update()

    def set_zoom(self, z: float, anchor: QPointF | None = None) -> None:
        old = self.zoom
        new = max(0.25, min(5.0, z))
        if abs(new - old) < 1e-3:
            return
        if anchor is not None and old > 0:
            c = QPointF(self.width() / 2, self.height() / 2)
            rel = anchor - c - self.pan
            self.pan = anchor - c - rel * (new / old)
        if new <= 1.02:
            self.pan = QPointF(0.0, 0.0)
        self.zoom = new
        self.zoom_changed.emit(self.zoom)
        self.update()

    def _base_scale(self) -> float:
        if self.img is None or self.img.isNull() or self.width() <= 0 or self.height() <= 0:
            return 1.0
        return min(1.0, (self.width() - 24) / max(1, self.img.width()),
                   (self.height() - 24) / max(1, self.img.height()))

    def wheelEvent(self, e) -> None:
        dy = e.angleDelta().y()
        if dy:
            pos = e.position() if hasattr(e, "position") else QPointF(self.width() / 2, self.height() / 2)
            self.set_zoom(self.zoom * (1.18 if dy > 0 else 1 / 1.18), pos)
            e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            pos = e.position() if hasattr(e, "position") else QPointF(self.width() / 2, self.height() / 2)
            self.set_zoom(1.0 if self.zoom > 1.08 else 2.0, pos)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = e.position() if hasattr(e, "position") else QPointF(e.pos())
            self._pan_start = QPointF(self.pan)
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:
        if self._down is None:
            return
        pos = e.position() if hasattr(e, "position") else QPointF(e.pos())
        delta = pos - self._down
        if abs(delta.x()) + abs(delta.y()) > 4:
            self._dragged = True
            self.pan = self._pan_start + delta
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            was_drag = self._dragged
            self._down = None
            self._dragged = False
            if not was_drag and self.zoom <= 1.02:
                self.clicked.emit()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#0B0B0C"))
        if self.img is None or self.img.isNull():
            p.setPen(QColor("#98989D"))
            p.drawText(QRectF(self.rect()), int(Qt.AlignmentFlag.AlignCenter), "图片无法显示")
            p.end()
            return
        k = self._base_scale() * self.zoom
        dw, dh = self.img.width() * k, self.img.height() * k
        cx = self.width() / 2 + self.pan.x()
        cy = self.height() / 2 + self.pan.y()
        p.drawImage(QRectF(cx - dw / 2, cy - dh / 2, dw, dh), self.img)
        p.end()


class ImageViewer(Dialog):
    """画廊大图查看器:支持滚轮缩放、拖拽平移、左右切换会话内图片;阅后即焚禁止复制保存且到期关闭。"""

    def __init__(self, parent, msg: Msg, gallery: list[Msg] | None = None) -> None:
        super().__init__(parent, "查看图片")
        self.setObjectName("viewer")
        items = [m for m in (gallery or [msg]) if not m.gone and m.img is not None]
        if msg not in items:
            items = [msg]
        self.gallery = [msg] if msg.burn else items
        self.idx = self.gallery.index(msg) if msg in self.gallery else 0
        self.msg = self.gallery[self.idx]
        self.img: QImage | None = None
        self.gif = None

        scr = (parent.screen() if parent is not None and hasattr(parent, "screen") and parent.screen() is not None
               else QApplication.primaryScreen())
        avail = scr.availableGeometry() if scr is not None and hasattr(scr, "availableGeometry") else None
        self._maxw = int(avail.width() * 0.82) if avail is not None and avail.width() else 960
        self._maxh = int(avail.height() * 0.80) - 64 if avail is not None and avail.height() else 640

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.stage = QStackedWidget(self)
        self.canvas = _ZoomCanvas(self.stage)
        self.canvas.clicked.connect(self.reject)
        self.canvas.zoom_changed.connect(self._on_zoom_changed)
        self.gif_page = ClickLabel(self.stage)
        self.gif_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gif_page.clicked.connect(self.reject)
        self.gif_holder = QHBoxLayout(self.gif_page)
        self.gif_holder.setContentsMargins(0, 0, 0, 0)
        self.stage.addWidget(self.canvas)
        self.stage.addWidget(self.gif_page)
        lay.addWidget(self.stage, 1)

        bar = QFrame(self)
        bar.setObjectName("viewerBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 10, 12, 10)
        bl.setSpacing(6)
        self.prev_btn = button("‹", "", lambda: self.step_gallery(-1), 36)
        self.count_label = label("", "viewerInfo")
        self.next_btn = button("›", "", lambda: self.step_gallery(1), 36)
        for w in (self.prev_btn, self.count_label, self.next_btn):
            bl.addWidget(w)
        self.info_label = label("", "viewerInfo")
        bl.addWidget(self.info_label)
        self.burn_label = label("", "viewerBurn")
        bl.addWidget(self.burn_label)
        bl.addStretch(1)
        self.zout_btn = button("－", "", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.25), 36)
        self.zreset_btn = button("100%", "", lambda: self.canvas.set_image(self.img), 58)
        self.zin_btn = button("＋", "", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.25), 36)
        for w in (self.zout_btn, self.zreset_btn, self.zin_btn):
            bl.addWidget(w)
        self.copy_btn = button("复制", "", self.copy_image)
        self.save_btn = button("存储为…", "", self.save_image)
        bl.addWidget(self.copy_btn)
        bl.addWidget(self.save_btn)
        close = button("关闭", "primary", self.reject)
        close.setDefault(True)
        bl.addWidget(close)
        lay.addWidget(bar)

        self._load_current(initial=True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)
        self._tick()

    def _on_zoom_changed(self, z: float) -> None:
        self.zreset_btn.setText(f"{int(round(z * 100))}%")

    def step_gallery(self, delta: int) -> None:
        if len(self.gallery) <= 1:
            return
        self.idx = (self.idx + delta) % len(self.gallery)
        self.msg = self.gallery[self.idx]
        self._load_current(initial=False)

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k == Qt.Key.Key_Left and len(self.gallery) > 1:
            self.step_gallery(-1)
        elif k == Qt.Key.Key_Right and len(self.gallery) > 1:
            self.step_gallery(1)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.canvas.set_zoom(self.canvas.zoom * 1.25)
        elif k == Qt.Key.Key_Minus:
            self.canvas.set_zoom(self.canvas.zoom / 1.25)
        elif k == Qt.Key.Key_0:
            self.canvas.set_image(self.img)
        else:
            super().keyPressEvent(e)

    def _load_current(self, initial: bool = False) -> None:
        msg = self.msg
        if self.gif is not None:
            self.gif.set_active(False)
            self.gif_holder.removeWidget(self.gif)
            self.gif.deleteLater()
            self.gif = None
        self.img = imaging.decode(msg.img)
        gif_info = imaging.gif_meta(msg.img) if msg.mime == "image/gif" else None
        is_anim_gif = bool(self.img is not None and gif_info and gif_info[2] > 1)
        if is_anim_gif:
            from .widgets import GifLabel
            gw, gh = gif_info[0], gif_info[1]
            k = min(1.0, self._maxw / gw, self._maxh / gh) if gw and gh else 1.0
            if max(gw, gh) * k < 240:
                k = min(self._maxw / gw, self._maxh / gh, 240 / max(gw, gh))
            self.gif = GifLabel(msg.img, max(1, int(gw * k)), max(1, int(gh * k)), radius=0, badge=False)
            self.gif.clicked.connect(self.reject)
            self.gif.setCursor(Qt.CursorShape.PointingHandCursor)
            self.gif.set_active(True)
            self.gif_holder.addWidget(self.gif, 0, Qt.AlignmentFlag.AlignCenter)
            self.stage.setCurrentIndex(1)
            if initial:
                self.resize(max(520, self.gif.width() + 40), max(340, self.gif.height() + 80))
        else:
            self.canvas.set_image(self.img)
            self.stage.setCurrentIndex(0)
            if initial and self.img is not None:
                k = min(1.0, self._maxw / max(1, self.img.width()), self._maxh / max(1, self.img.height()))
                self.resize(max(560, int(self.img.width() * k) + 48), max(380, int(self.img.height() * k) + 90))
        for b in (self.zout_btn, self.zreset_btn, self.zin_btn):
            b.setVisible(not is_anim_gif and self.img is not None)
        multi = len(self.gallery) > 1
        for w in (self.prev_btn, self.count_label, self.next_btn):
            w.setVisible(multi)
        if multi:
            self.count_label.setText(f"{self.idx + 1} / {len(self.gallery)}")
        size = f"{msg.w}×{msg.h}" if msg.w and msg.h else (f"{gif_info[0]}×{gif_info[1]}" if gif_info else "")
        if is_anim_gif:
            size = f"动图 · {size} · {gif_info[2]} 帧"
        who = "我" if msg.mine else msg.nick
        info_text = "  ·  ".join(x for x in (who, size, imaging.human_size(len(msg.img or b""))) if x)
        self.info_label.setText(info_text)
        can_save = not msg.burn and self.img is not None
        for b in (self.copy_btn, self.save_btn):
            b.setEnabled(can_save)
            b.setToolTip("阅后即焚的图片不能复制或保存" if msg.burn else "")
        self.burn_label.setText("")

    def _tick(self) -> None:
        m = self.msg
        if m.gone:
            self.reject()
            return
        if m.burn and m.deadline:
            left = m.deadline - time.monotonic()
            if left <= 0:
                self.reject()
                return
            self.burn_label.setText(f"🔥 {fmt_secs(left)} 后焚毁")

    def copy_image(self) -> None:
        if self.img is not None and not self.msg.burn:
            QApplication.clipboard().setImage(self.img)

    def save_image(self) -> None:
        if self.msg.burn or not self.msg.img:
            return
        ext = {"image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}.get(self.msg.mime, ".jpg")
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        default = os.path.join(folder, f"图片_{time.strftime('%Y%m%d_%H%M%S')}{ext}")
        path, _ = QFileDialog.getSaveFileName(self, "存储图片", default, f"图片 (*{ext})")
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(self.msg.img)
            except OSError as e:
                info(self, "保存失败", str(e))


class MultiPromptDialog(Dialog):
    """多行文字输入(群公告、匿名纸条)。"""

    def __init__(self, parent, title: str, text: str, value: str = "", placeholder: str = "", ok: str = "发送",
                 max_len: int = 500, extra: str = "") -> None:
        super().__init__(parent, title)
        self.setFixedWidth(440)
        self.max_len = max_len
        self.extra_clicked = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label(title, "dialogTitle"))
        if text:
            lay.addWidget(label(text, "hint", wrap=True))
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(value)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFixedHeight(120)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        if extra:
            row.addWidget(button(extra, "destructive", self._extra))
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 80))
        okb = button(ok, "primary", self.accept, 80)
        row.addWidget(okb)
        lay.addLayout(row)

    def _extra(self) -> None:
        self.extra_clicked = True
        self.accept()

    @property
    def value(self) -> str:
        return self.edit.toPlainText().strip()[: self.max_len]
