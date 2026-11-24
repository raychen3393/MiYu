"""
密语 · 通用对话框
基础 Dialog(毛玻璃、壁纸)、确认 / 提示 / 输入框、开关,以及启动、加入暗号群、安全码、文本、
注销、发图、看图、多行输入这些对话框。
"""
from __future__ import annotations

import os
import re
import time

from PySide6.QtCore import QRectF, QSize, QStandardPaths, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QVBoxLayout, QWidget,
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
        if not getattr(self, "_shown_once", False):          # 第一次弹出时淡入
            self._shown_once = True
            from .motion import fade_window
            fade_window(self, 160)

    def paintEvent(self, e) -> None:
        if self.objectName() != "viewer":
            theme.paint_wallpaper(self, e)


class AlertDialog(Dialog):
    def __init__(self, parent, title: str, text: str, buttons: list[tuple[str, str]]) -> None:
        super().__init__(parent)
        self.setFixedWidth(380)
        self.choice = -1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 26, 30, 22)
        lay.setSpacing(8)
        lay.addWidget(label(title, "dialogTitle", wrap=True, center=True))
        if text:
            lay.addWidget(label(text, "hint", wrap=True, center=True))
        lay.addSpacing(12)
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
        for i, (name, value) in enumerate(rows):
            if i:
                cl.addSpacing(4)
                cl.addWidget(hline())
                cl.addSpacing(4)
            if name:
                cl.addWidget(label(name, "section"))
            v = label(value, "monoSmall" if name else "hint", wrap=True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(v)
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


class SendImageDialog(Dialog):
    def __init__(self, parent, preview: QPixmap, count: int, total: int, burn: int, target: str, bad: int) -> None:
        super().__init__(parent, "发送图片")
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label("发送图片" if count == 1 else f"发送 {count} 张图片", "dialogTitle", center=True))
        lay.addWidget(label(f"到「{target}」", "hint", center=True))
        lay.addSpacing(10)
        pic = QLabel()
        pic.setPixmap(preview)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pic, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(10)
        lay.addWidget(label(f"{imaging.human_size(total)} · 已压缩,并去掉了照片里的位置、设备等隐私信息",
                            "faint", wrap=True, center=True))
        if bad:
            lay.addWidget(label(f"另有 {bad} 张无法读取,已跳过", "warn", center=True))
        if burn:
            lay.addWidget(label(f"🔥 阅后即焚:对方打开后 {fmt_secs(burn)} 自动删除", "warn", center=True))
        lay.addSpacing(14)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("取消", "", self.reject))
        ok = button("发送", "primary", self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)


class ImageViewer(Dialog):
    """查看大图。阅后即焚的图片不能复制或保存,时间到自动关闭。"""

    def __init__(self, parent, msg: Msg) -> None:
        super().__init__(parent, "查看图片")
        self.setObjectName("viewer")
        self.msg = msg
        self.img = imaging.decode(msg.img)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.view = ClickLabel()
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.clicked.connect(self.reject)
        self.view.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gif = None
        gif_info = imaging.gif_meta(msg.img) if msg.mime == "image/gif" else None
        if self.img is not None and gif_info and gif_info[2] > 1:      # 动图:大图里也会动
            from .widgets import GifLabel
            scr = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
            maxw, maxh = int(scr.width() * 0.82), int(scr.height() * 0.80) - 60
            gw, gh = gif_info[0], gif_info[1]
            k = min(1.0, maxw / gw, maxh / gh) if gw and gh else 1.0
            if max(gw, gh) * k < 240:                       # 很小的动图放大一点再看
                k = min(maxw / gw, maxh / gh, 240 / max(gw, gh))
            self.gif = GifLabel(msg.img, max(1, int(gw * k)), max(1, int(gh * k)), radius=0, badge=False)
            self.gif.clicked.connect(self.reject)
            self.gif.setCursor(Qt.CursorShape.PointingHandCursor)
            self.gif.set_active(True)
            holder = QHBoxLayout(self.view)
            holder.setContentsMargins(0, 0, 0, 0)
            holder.addWidget(self.gif, 0, Qt.AlignmentFlag.AlignCenter)
            self.view.setMinimumSize(max(360, self.gif.width()), max(240, self.gif.height()))
        elif self.img is not None:
            scr = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
            maxw, maxh = int(scr.width() * 0.82), int(scr.height() * 0.80) - 60
            dpr = max(1.0, self.devicePixelRatioF())
            pm = QPixmap.fromImage(self.img)
            if pm.width() > maxw * dpr or pm.height() > maxh * dpr:
                pm = pm.scaled(int(maxw * dpr), int(maxh * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.view.setPixmap(pm)
            self.view.setMinimumSize(max(360, int(pm.width() / dpr)), max(240, int(pm.height() / dpr)))
        else:
            self.view.setText("图片无法显示")
            self.view.setObjectName("viewerText")
            self.view.setMinimumSize(360, 240)
        lay.addWidget(self.view, 1)

        bar = QFrame()
        bar.setObjectName("viewerBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 12, 10)
        bl.setSpacing(8)
        size = f"{msg.w}×{msg.h}" if msg.w and msg.h else (f"{gif_info[0]}×{gif_info[1]}" if gif_info else "")
        if gif_info and gif_info[2] > 1:
            size = f"动图 · {size} · {gif_info[2]} 帧"
        who = "我" if msg.mine else msg.nick
        info_text = "  ·  ".join(x for x in (who, size, imaging.human_size(len(msg.img or b""))) if x)
        bl.addWidget(label(info_text, "viewerInfo"))
        self.burn_label = label("", "viewerBurn")
        bl.addWidget(self.burn_label)
        bl.addStretch(1)
        self.copy_btn = button("复制", "", self.copy_image)
        self.save_btn = button("存储为…", "", self.save_image)
        if msg.burn or self.img is None:
            for b in (self.copy_btn, self.save_btn):
                b.setEnabled(False)
                b.setToolTip("阅后即焚的图片不能复制或保存" if msg.burn else "")
        bl.addWidget(self.copy_btn)
        bl.addWidget(self.save_btn)
        close = button("关闭", "primary", self.reject)
        close.setDefault(True)
        bl.addWidget(close)
        lay.addWidget(bar)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)
        self._tick()

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
