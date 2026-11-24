"""
密语 · 聊天界面控件
消息和会话的数据结构(Msg / Conv)、输入框、气泡、文件卡片、表情面板、聊天面板、会话和成员列表的绘制。
"""
from __future__ import annotations

import math
import os
import time
import uuid
import weakref

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QImage, QLinearGradient, QMovie, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QStackedWidget, QStyle, QStyledItemDelegate, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from . import imaging, motion, theme
from .cards import make_card
from .icons import avatar, file_badge, icon, paint_icon, soft_shadow
from .theme import T, qcolor
from .ui import (
    DANGER_EXTS, EMOJI_GROUPS, HEADER_H, HEAT_ALPHA, HEAT_COLORS, VIDEO_EXTS, _text_opt, button, emoji_font,
    file_ext, file_paths, fmt_eta, fmt_list_time, fmt_secs, fmt_sep, fmt_speed, highlight_html, images_from_mime,
    label, local_paths, make_menu, peer_avatar, repolish, soft_wrap,
)


class Msg:
    __slots__ = ("mid", "sender", "nick", "tag", "text", "mine", "time", "burn", "deadline", "status", "system",
                 "img", "mime", "w", "h", "thumb", "gone", "reply", "at", "file", "mention", "sticker",
                 "delivered", "read", "receipt", "read_sent", "edited", "card", "skin", "anon", "fav", "reactions", "title",
                 "level", "vid")

    def __init__(self, text: str, *, mid: str | None = None, sender: str = "", nick: str = "", tag: str = "",
                 mine: bool = False, burn: int = 0, system: bool = False, img: bytes | None = None,
                 mime: str | None = None, w: int = 0, h: int = 0, reply: dict | None = None,
                 at: list | None = None, file: dict | None = None, sticker: bool = False, card: dict | None = None,
                 skin: str | None = None, anon: bool = False, fav: dict | None = None) -> None:
        self.mid = mid or uuid.uuid4().hex
        self.sender = sender
        self.nick = nick
        self.tag = tag
        self.text = text
        self.mine = mine
        self.time = time.time()
        self.burn = burn
        self.deadline: float | None = None
        self.status = ""
        self.system = system
        self.img = img
        self.mime = mime
        self.w = w
        self.h = h
        self.thumb = None          # 缓存的缩略图;False 表示解码失败
        self.gone = False          # 已焚毁 / 已撤回 / 已清空
        self.reply = reply         # 引用的消息 {"mid","nick","preview"}
        self.at = at or []
        self.file = file           # 文件 {"fid","name","size"}
        self.mention = False       # 这条消息 @ 了我
        self.sticker = sticker
        self.delivered = False     # 私聊:已送达
        self.read = False          # 私聊:对方已读
        self.receipt = ""          # 显示在最后一条自己消息下面的"已送达 / 已读"
        self.read_sent = False     # 已经给对方回过已读
        self.edited = False        # 被编辑过
        self.card = card           # 卡片消息:投票 / 抽签 / 骰子 / 游戏 / 画板
        self.skin = skin           # 气泡皮肤
        self.anon = anon           # 匿名纸条
        self.fav = fav             # 收藏来源 {"from","where","time","conv","mid"}
        self.reactions: dict = {}  # 表情回应:表情 → [回应的人的 id]
        self.title = ""            # 发送者佩戴的称号
        self.level = 0             # 发送者宠物的等级(名字旁边的等级标识),0 = 不显示
        self.vid: bytes | None = None   # 匿名纸条里的视频(内容直接带在消息里;普通视频走文件传输)


class Conv:
    def __init__(self, key: str, kind: str, title: str, target: str | None = None) -> None:
        self.key = key            # "lobby" | "room:<tag>" | "dm:<id>"
        self.kind = kind          # "lobby" | "room" | "dm"
        self.title = title
        self.target = target      # 群 tag 或 对方 id
        self.messages: list[Msg] = []
        self.unread = 0
        self.preview = ""
        self.last_active = time.time()
        self.last_time = 0.0
        self.verified = False
        self.muted = False        # 这个会话不响提示音
        self.at_me = False        # 有未读的 @我
        self.heat = 0.0           # 聊天热度 0~1
        self.heat_t = time.monotonic()
        self.notice: dict | None = None   # 群公告
        self.notice_t = 0.0
        self.pins: list[dict] = []        # 置顶消息
        self.pins_t = 0.0
        self.name_t = 0.0                 # 群名最后一次同步修改的时间(0 = 从没改过)
        self.pinned = False               # 会话置顶(排在列表最上面)
        self.db_more = False              # 数据库里还有更早的记录没读进来(往上翻时再读)


class Bridge(QObject):
    event = Signal(str, object)


class ChatInput(QPlainTextEdit):
    send = Signal()
    images = Signal(object)
    files = Signal(object)
    at_typed = Signal()
    keystroke = Signal(str)                  # "char" / "delete" / "enter",给打字宠物和火花用

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("composerInput")
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(2)
        self._hint = ""
        self._composing = False          # 输入法正在拼写(拼音还没上屏)
        self._last_pre = ""              # 上一次的拼音,用来判断这次是不是真的按了键
        self.textChanged.connect(self._fit)
        self._fit()

    def set_hint(self, text: str) -> None:
        """设置灰色提示文字。拼音输入期间不显示,否则会和拼音叠在一起(Qt 的已知问题)。"""
        self._hint = text
        self.setPlaceholderText("" if self._composing else text)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if not e.isAutoRepeat():
                self.keystroke.emit("enter")
            self.send.emit()
            return
        super().keyPressEvent(e)
        if e.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.keystroke.emit("delete")
        elif e.key() == Qt.Key.Key_Space or e.text() == " ":
            self.keystroke.emit("space")
        elif e.text() and e.text().isprintable():
            self.keystroke.emit("char")
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.keystroke.emit("enter")
        if e.text() in ("@", "＠"):
            self.at_typed.emit()

    def inputMethodEvent(self, e) -> None:
        composing = bool(e.preeditString())
        if composing != self._composing:
            self._composing = composing
            self.setPlaceholderText("" if composing else self._hint)
        super().inputMethodEvent(e)
        pre, commit = e.preeditString(), e.commitString()
        # 输入法有时一个按键会发好几次事件(比如只是光标变了),只有拼音真的变了才算一次按键
        if commit:
            self.keystroke.emit("space")                     # 选字上屏(通常是按空格或数字键)
        elif pre != self._last_pre:
            self.keystroke.emit("delete" if len(pre) < len(self._last_pre) else "char")
        self._last_pre = pre
        if e.commitString().endswith(("@", "＠")):          # 中文输入法打出的 @
            self.at_typed.emit()

    # 把文件 / 图片拖到输入框上:交给主窗口直接发送(和拖到聊天区一样);拖文字进来照常插入
    drop_handler = None

    def _handles(self, e) -> bool:
        h = self.drop_handler
        return h is not None and h.is_send_drop(e.mimeData())

    def dragEnterEvent(self, e) -> None:
        if self._handles(e):
            self.drop_handler.dragEnterEvent(e)
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        if self._handles(e):
            self.drop_handler.dragMoveEvent(e)
        else:
            super().dragMoveEvent(e)

    def dragLeaveEvent(self, e) -> None:
        if self.drop_handler is not None:
            self.drop_handler.dragLeaveEvent(e)
        super().dragLeaveEvent(e)

    def dropEvent(self, e) -> None:
        if self._handles(e):
            self.drop_handler.dropEvent(e)
        else:
            super().dropEvent(e)

    def _fit(self) -> None:
        lines = max(1, int(self.document().size().height()))
        h = min(lines, 6) * self.fontMetrics().lineSpacing() + 14
        self.setFixedHeight(max(30, h))

    def canInsertFromMimeData(self, source) -> bool:
        return bool(local_paths(source)) or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:
        files = file_paths(source)
        imgs = images_from_mime(source)
        if files:
            self.files.emit(files)
        if imgs is not None:
            self.images.emit(imgs)
        if files or imgs is not None:
            return
        super().insertFromMimeData(source)


class SearchEdit(QLineEdit):
    """搜索框:Enter 往前(更早)找,Shift+Enter 往后找,Esc 关闭。"""
    prev_hit = Signal()
    next_hit = Signal()
    closed = Signal()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ShortcutOverride and e.key() == Qt.Key.Key_Escape:
            e.accept()                     # 不让主窗口的 ESC(隐藏软件)抢走
            return True
        return super().event(e)

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            (self.next_hit if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else self.prev_hit).emit()
        elif k == Qt.Key.Key_Up:
            self.prev_hit.emit()
        elif k == Qt.Key.Key_Down:
            self.next_hit.emit()
        elif k == Qt.Key.Key_Escape:
            self.closed.emit()
        else:
            super().keyPressEvent(e)


# 可点击的小控件:先让 Qt 处理完这次点击,最后再发"被点了"的信号。
# 收到信号的地方可能会重画整个聊天区、把这个控件删掉;删掉之后就不能再碰它了。
class ClickLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, e) -> None:
        left = e.button() == Qt.MouseButton.LeftButton
        super().mouseReleaseEvent(e)
        if left:
            self.clicked.emit()


GIF_LABELS: "weakref.WeakSet[GifLabel]" = weakref.WeakSet()     # 聊天里所有会动的图(看不见时暂停)


class GifLabel(ClickLabel):
    """会动的图片(GIF):圆角显示,左上角一个小小的「GIF」角标。
    一开始停在第一帧;窗口按可见性调用 set_active(),滚出视野或窗口藏起来时暂停,不费电。"""

    def __init__(self, data: bytes, w: int, h: int, radius: float = 14.0, badge: bool = True) -> None:
        super().__init__()
        self.radius, self.badge = radius, badge
        self._active = False
        self._ba = QByteArray(bytes(data))
        self._buf = QBuffer(self._ba, self)
        self._buf.open(QIODevice.OpenModeFlag.ReadOnly)
        self.movie = QMovie(self._buf, QByteArray(b"gif"), self)
        self.movie.setCacheMode(QMovie.CacheMode.CacheNone)
        try:
            dpr = max(1.0, float(self.devicePixelRatioF()))
        except (TypeError, ValueError):
            dpr = 1.0
        self.movie.setScaledSize(QSize(max(1, int(w * dpr)), max(1, int(h * dpr))))
        self.movie.frameChanged.connect(lambda _i: self.update())
        self.movie.jumpToFrame(0)
        self.setFixedSize(w, h)
        GIF_LABELS.add(self)

    def set_active(self, on: bool) -> None:
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        state = self.movie.state()
        if on:
            if state == QMovie.MovieState.Paused:
                self.movie.setPaused(False)
            elif state == QMovie.MovieState.NotRunning:
                self.movie.start()
        elif state == QMovie.MovieState.Running:
            self.movie.setPaused(True)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.setClipPath(path)
        pm = self.movie.currentPixmap()
        if pm.isNull():
            p.fillRect(r, QColor(128, 128, 128, 40))
        else:
            p.drawPixmap(self.rect(), pm)
        if self.badge:
            f = QFont(self.font())
            f.setPointSizeF(7.5)
            f.setBold(True)
            p.setFont(f)
            tag = QRectF(8, 8, 30, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawRoundedRect(tag, 8, 8)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(tag, int(Qt.AlignmentFlag.AlignCenter), "GIF")
        p.end()


class DblLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, e) -> None:
        left = e.button() == Qt.MouseButton.LeftButton
        super().mouseDoubleClickEvent(e)
        if left:
            self.double_clicked.emit()


class ClickFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, e) -> None:
        left = e.button() == Qt.MouseButton.LeftButton
        super().mouseReleaseEvent(e)
        if left:
            self.clicked.emit()


class TimeSep(QWidget):
    def __init__(self, ts: float) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 4)
        lay.addWidget(label(fmt_sep(ts), "timeSep", center=True), 0, Qt.AlignmentFlag.AlignHCenter)


class FileCard(QFrame):
    """文件卡片:图标、文件名、大小/状态、进度条和操作按钮。"""
    action = Signal(str)

    def __init__(self, msg: Msg, transfer: dict) -> None:
        super().__init__()
        self.msg = msg
        self.setObjectName("fileCardMine" if msg.mine else "fileCard")
        self.setFixedWidth(296)
        name = msg.file.get("name", "文件")
        self.is_dir = bool(msg.file.get("dir"))
        if self.is_dir and name.lower().endswith(".zip"):
            name = name[:-4]
        ext = "folder" if self.is_dir else file_ext(name)
        self.is_video = not self.is_dir and file_ext(name) in VIDEO_EXTS       # 视频:可以直接在软件里看
        self.open_btn = ("播放", "play") if self.is_video else ("打开", "open")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 11, 12, 9)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(11)
        ic = QLabel()
        ic.setPixmap(file_badge(ext, 40))
        ic.setFixedSize(40, 40)
        top.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.name = label("", "fileName")
        self.name.setText(self.name.fontMetrics().elidedText(name, Qt.TextElideMode.ElideMiddle, 212))
        self.name.setToolTip(name)
        self.sub = label("", "fileSub")
        col.addWidget(self.name)
        col.addWidget(self.sub)
        top.addLayout(col, 1)
        lay.addLayout(top)
        if ext in DANGER_EXTS and not msg.mine:
            lay.addWidget(label("可执行文件,请确认来源可信再打开", "fileWarn"))
        self.bar = QProgressBar()
        self.bar.setObjectName("fileProgress")
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addStretch(1)
        self.btn_b = button("", "link")
        self.btn_a = button("", "link")
        for b in (self.btn_b, self.btn_a):
            b.setMinimumHeight(28)
            row.addWidget(b)
        self.btn_a.clicked.connect(lambda: self.action.emit(self._act_a))
        self.btn_b.clicked.connect(lambda: self.action.emit(self._act_b))
        lay.addLayout(row)
        self._act_a = self._act_b = ""
        self.update_state(transfer)

    def _buttons(self, a: tuple[str, str] | None, b: tuple[str, str] | None = None) -> None:
        for btn, spec, attr in ((self.btn_a, a, "_act_a"), (self.btn_b, b, "_act_b")):
            btn.setVisible(spec is not None)
            if spec:
                btn.setText(spec[0])
                setattr(self, attr, spec[1])

    def update_state(self, tr: dict) -> None:
        size = int(self.msg.file.get("size", 0))
        hs = ("文件夹 · " if self.is_dir else "") + imaging.human_size(size)
        if self.msg.file.get("local"):             # 收藏夹里的本机文件:只是记着位置
            self.bar.setVisible(False)
            exists = os.path.exists(self.msg.file.get("path", ""))
            self.sub.setText(f"{hs}  ·  " + ("本机" if exists else "文件已被移动或删除"))
            self._buttons(self.open_btn if exists else None, ("所在文件夹", "folder") if exists else None)
            return
        if self.msg.mine:
            active = tr.get("up") or {}
            if active:
                done = sum(d for d, _ in active.values())
                total = max(1, sum(t for _, t in active.values()))
                spd = tr.get("speed", 0)
                self.sub.setText(f"{hs}  ·  发送中 {int(done * 100 / total)}%" + (f"  ·  {fmt_speed(spd)}" if spd else ""))
                self.bar.setValue(int(done * 1000 / total))
                self.bar.setVisible(True)
            else:
                n = tr.get("up_done", 0)
                self.sub.setText(f"{hs}  ·  " + (f"已被下载 {n} 次" if n else "等待对方下载"))
                self.bar.setVisible(False)
            if self.is_video and tr.get("path"):
                self._buttons(self.open_btn, ("所在文件夹", "folder"))
            else:
                self._buttons(("所在文件夹", "folder") if tr.get("path") else None)
            return
        state = tr.get("state", "offer")
        self.bar.setVisible(state in ("downloading", "paused"))
        if state == "downloading":
            done = int(tr.get("done", 0))
            spd = tr.get("speed", 0)
            extra = f"  ·  {fmt_speed(spd)}  ·  {fmt_eta((size - done) / spd)}" if spd > 0 else ""
            self.sub.setText(f"{imaging.human_size(done)} / {hs}{extra}")
            self.bar.setValue(int(done * 1000 / max(1, size)))
            self._buttons(("暂停", "pause"), ("取消", "cancel"))
        elif state == "paused":
            done = int(tr.get("done", 0))
            why = "对方上线后自动继续" if tr.get("auto") else "已暂停"
            self.sub.setText(f"{imaging.human_size(done)} / {hs}  ·  {why}")
            self.bar.setValue(int(done * 1000 / max(1, size)))
            self._buttons(("继续", "resume"), ("取消", "cancel"))
        elif state == "extracting":
            self.bar.setVisible(False)
            self.sub.setText(f"{hs}  ·  正在解压…")
            self._buttons(None)
        elif state == "done":
            self.sub.setText(f"{hs}  ·  " + (tr.get("note") or ("已解压" if tr.get("folder") else "已保存")))
            if tr.get("folder"):
                self._buttons(("打开文件夹", "open"), ("所在位置", "folder"))
            else:
                self._buttons(self.open_btn, ("所在文件夹", "folder"))
        elif state == "error":
            self.sub.setText(f"{hs}  ·  {tr.get('error', '下载失败')}")
            self._buttons(("重新下载", "download"))
        else:
            self.sub.setText(hs)
            self._buttons(("下载", "download"))


class _Text:
    """只记文字、不显示的"标签":视频卡片把状态文字画在封面上,但沿用文件卡片的状态逻辑。"""

    def __init__(self) -> None:
        self._t = ""

    def setText(self, t: str) -> None:
        self._t = t

    def text(self) -> str:
        return self._t


class VideoPoster(QWidget):
    """视频封面:画面铺满、底部渐暗写着文件名和大小、右上角时长、中间一个播放按钮(下载中显示百分比)。"""
    clicked = Signal()
    W = 300

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(self.W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.pm: QPixmap | None = None
        self.name = ""
        self.sub = ""
        self.dur = 0
        self.center = "play"                  # play / pct / none
        self.pct = 0
        self.hover = False
        self.set_size(0, 0)

    def set_poster(self, thumb: bytes | None, vw: int, vh: int, dur: int) -> None:
        self.pm = None
        if thumb:
            img = QImage.fromData(thumb)
            if not img.isNull() and img.width() <= 2048 and img.height() <= 2048:
                self.pm = QPixmap.fromImage(img)
                vw, vh = vw or img.width(), vh or img.height()
        self.dur = max(0, int(dur or 0))
        self.set_size(vw, vh)
        self.update()

    def set_size(self, vw: int, vh: int) -> None:
        if vw > 0 and vh > 0:
            h = int(self.W * vh / vw)
            self.setFixedHeight(max(150, min(340, h)))       # 竖屏视频最高 340,超出的上下裁掉
        else:
            self.setFixedHeight(170)

    def set_text(self, name: str, sub: str, center: str, pct: int = 0) -> None:
        if (name, sub, center, pct) != (self.name, self.sub, self.center, self.pct):
            self.name, self.sub, self.center, self.pct = name, sub, center, pct
            self.update()

    def enterEvent(self, e) -> None:
        self.hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        left = e.button() == Qt.MouseButton.LeftButton
        super().mouseReleaseEvent(e)
        if left and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        r = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.setClipPath(path)
        if self.pm is not None and not self.pm.isNull():
            pw, ph = self.pm.width(), self.pm.height()
            k = max(w / pw, h / ph)                          # 铺满,多出来的裁掉
            sw, sh = w / k, h / k
            p.drawPixmap(r, self.pm, QRectF((pw - sw) / 2, (ph - sh) / 2, sw, sh))
        else:                                                # 还没有封面:深色渐变 + 胶片图标
            g = QLinearGradient(0, 0, w, h)
            g.setColorAt(0, QColor("#3A3550"))
            g.setColorAt(1, QColor("#1E1B2C"))
            p.fillRect(r, QBrush(g))
            p.drawPixmap(int(w / 2 - 22), int(h / 2 - 66), file_badge("mp4", 44))
        shade = QLinearGradient(0, h - 74, 0, h)             # 底部渐暗,文字看得清
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(1, QColor(0, 0, 0, 175))
        p.fillRect(QRectF(0, h - 74, w, 74), QBrush(shade))
        if self.dur:
            f = QFont(self.font())
            f.setPointSizeF(8)
            f.setBold(True)
            p.setFont(f)
            txt = _fmt_dur(self.dur)
            tw = QFontMetrics(f).horizontalAdvance(txt) + 14
            pill = QRectF(w - tw - 8, 8, tw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 130))
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), txt)
        if self.center != "none":                            # 中间的圆形按钮
            cr = QRectF(w / 2 - 27, h / 2 - 27, 54, 54)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.6))
            p.setBrush(QColor(0, 0, 0, 120 if self.hover else 90))
            p.drawEllipse(cr)
            if self.center == "pct":
                f = QFont(self.font())
                f.setPointSizeF(9.5)
                f.setBold(True)
                p.setFont(f)
                p.setPen(QColor(255, 255, 255))
                p.drawText(cr, int(Qt.AlignmentFlag.AlignCenter), f"{self.pct}%")
            else:
                tri = QPainterPath(QPointF(cr.center().x() - 7, cr.center().y() - 11))
                tri.lineTo(cr.center().x() + 12, cr.center().y())
                tri.lineTo(cr.center().x() - 7, cr.center().y() + 11)
                tri.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 240))
                p.drawPath(tri)
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setBold(True)
        fm = QFontMetrics(f)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(12, h - 44, w - 24, 20), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   fm.elidedText(self.name, Qt.TextElideMode.ElideMiddle, w - 24))
        f2 = QFont(self.font())
        f2.setPointSizeF(8.5)
        p.setFont(f2)
        p.setPen(QColor(255, 255, 255, 215))
        p.drawText(QRectF(12, h - 25, w - 24, 18), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   QFontMetrics(f2).elidedText(self.sub, Qt.TextElideMode.ElideRight, w - 24))
        p.end()


def _fmt_dur(ms: int) -> str:
    s = max(0, int(ms or 0) // 1000)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class VideoCard(FileCard):
    """视频卡片(参考微信):封面 + 播放按钮,点封面直接播放;还没下载时点封面 = 下载完自动播放。
    状态逻辑和文件卡片一样,只是文字画在封面上,操作按钮(暂停 / 取消 / 所在文件夹…)放在下面一行。"""

    def __init__(self, msg: Msg, transfer: dict) -> None:
        QFrame.__init__(self)
        self.msg = msg
        self.setObjectName("videoCardMine" if msg.mine else "videoCard")
        self.setFixedWidth(VideoPoster.W)
        self.is_dir = False
        self.is_video = True
        self.open_btn = ("播放", "play")
        self.full_name = msg.file.get("name", "视频")
        self.name = _Text()
        self.sub = _Text()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.poster = VideoPoster()
        self.poster.setToolTip(self.full_name)
        self.poster.clicked.connect(self._poster_click)
        lay.addWidget(self.poster)
        self.foot = QWidget()
        fl = QVBoxLayout(self.foot)
        fl.setContentsMargins(10, 0, 6, 2)
        fl.setSpacing(2)
        self.bar = QProgressBar()
        self.bar.setObjectName("fileProgress")
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        fl.addWidget(self.bar)
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addStretch(1)
        self.btn_b = button("", "link")
        self.btn_a = button("", "link")
        for b in (self.btn_b, self.btn_a):
            b.setMinimumHeight(26)
            row.addWidget(b)
        self.btn_a.clicked.connect(lambda: self.action.emit(self._act_a))
        self.btn_b.clicked.connect(lambda: self.action.emit(self._act_b))
        fl.addLayout(row)
        lay.addWidget(self.foot)
        self._act_a = self._act_b = ""
        self._poster_act = ""
        self._tr: dict = {}
        self.refresh_poster()
        self.update_state(transfer)

    def refresh_poster(self) -> None:
        f = self.msg.file or {}
        thumb = None
        if isinstance(f.get("thumb"), str):
            try:
                import base64
                thumb = base64.b64decode(f["thumb"])
            except (ValueError, TypeError):
                thumb = None
        self.poster.set_poster(thumb, int(f.get("vw") or 0), int(f.get("vh") or 0), int(f.get("dur") or 0))

    def _buttons(self, a, b=None) -> None:
        keep = [x for x in (a, b) if x is not None and x[1] != "play"]     # 播放:点封面就行
        super()._buttons(keep[0] if keep else None, keep[1] if len(keep) > 1 else None)
        self.foot.setVisible(bool(keep) or not self.bar.isHidden())

    def update_state(self, tr: dict) -> None:
        self._tr = tr
        m = self.msg
        size = imaging.human_size(int(m.file.get("size", 0)))
        if getattr(m, "vid", None) is not None:              # 匿名纸条里的视频:内容就在消息里
            self.bar.setVisible(False)
            self._buttons(("另存为…", "save"))
            self._poster_act = "play"
            self.poster.set_text(self.full_name, f"{size}  ·  匿名视频", "play")
            return
        super().update_state(tr)
        sub = self.sub.text()
        state = tr.get("state", "offer")
        if m.mine or m.file.get("local"):
            ok = bool(tr.get("path") or m.file.get("path"))
            self._poster_act = "play" if ok else ""
            self.poster.set_text(self.full_name, sub, "play" if ok else "none")
        elif state == "done":
            self._poster_act = "play"
            self.poster.set_text(self.full_name, sub, "play")
        elif state == "downloading":
            done = int(tr.get("done", 0))
            pct = int(done * 100 / max(1, int(m.file.get("size", 1))))
            if tr.get("stream"):                             # 2.5:索引在开头的视频,下了一点就能先看
                self._poster_act = "stream"
                self.poster.set_text(self.full_name, f"已下载 {min(99, pct)}%  ·  点击边下边看", "play")
            else:
                self._poster_act = ""
                if tr.get("stream") is False:
                    sub = f"{sub}  ·  这个视频要下完才能看"
                self.poster.set_text(self.full_name, sub, "pct", min(99, pct))
        elif state == "paused":
            self._poster_act = "resume"
            self.poster.set_text(self.full_name, sub, "play")
        elif state == "extracting":
            self._poster_act = ""
            self.poster.set_text(self.full_name, sub, "none")
        else:                                                # 还没下载 / 下载失败
            self._poster_act = "dlplay"
            self.poster.set_text(self.full_name, f"{size}  ·  点击下载并播放" if state == "offer" else sub, "play")
        self.foot.setVisible(not self.bar.isHidden() or self.btn_a.isVisibleTo(self) or self.btn_b.isVisibleTo(self))

    def _poster_click(self) -> None:
        if self._poster_act:
            self.action.emit(self._poster_act)


class Bubble(QWidget):
    open_image = Signal(object)
    menu_requested = Signal(object, object)       # (消息, 全局坐标)
    jump = Signal(str)                             # 点引用 → 跳到原消息
    file_action = Signal(object, str)
    card_action = Signal(object, str, object)
    poke = Signal(object)
    react = Signal(object, str)                    # 点了某个回应
    select_toggled = Signal(object)                # 多选时点了勾选框
    hovered = Signal(object)                       # 鼠标移进 / 移出这条消息(显示快捷操作条)
    unhovered = Signal(object)
    AV = 30

    def __init__(self, msg: Msg, show_head: bool, group: bool, maxw: int, transfer: dict | None = None,
                 card_state: dict | None = None, grp: str = "single") -> None:
        super().__init__()
        self.msg = msg
        self.grp = grp                             # 连续消息分组:single / first / mid / last
        self.body = None
        self.meta = None
        self.pill = None
        self.av = None                             # 头像(群里别人的消息才有;扔东西时道具飞到这里)
        self.card = None
        self.card_w = None
        self.sel_btn = None
        self.react_row = None
        self.react_chips: list = []
        if msg.system:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(28, 6, 28, 6)
            self.pill = label(msg.text, "system", wrap=True, center=True)
            lay.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignHCenter)
            self.fit(maxw)
            return
        mine = msg.mine
        align = Qt.AlignmentFlag.AlignRight if mine else Qt.AlignmentFlag.AlignLeft
        row = QHBoxLayout(self)
        self._row = row
        row.setContentsMargins(18, self.top_gap(grp, show_head), 18, 1)
        row.setSpacing(8)
        self.setToolTip(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(msg.time)))
        self.sel_btn = QPushButton("")
        self.sel_btn.setObjectName("selBox")
        self.sel_btn.setCheckable(True)
        self.sel_btn.setFixedSize(20, 20)
        self.sel_btn.setVisible(False)
        self.sel_btn.clicked.connect(lambda: self.select_toggled.emit(self.msg))
        row.addWidget(self.sel_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        if group and not mine:
            av = DblLabel()
            av.setFixedSize(self.AV, self.AV)
            if show_head:
                if msg.anon:
                    av.setPixmap(avatar("?", "#C9A227", self.AV))
                    av.setToolTip("匿名纸条:谁也不知道是谁发的")
                else:
                    av.setPixmap(peer_avatar(msg.sender, msg.nick, self.AV))
                    av.setToolTip(f"{msg.nick}  #{msg.tag}\n双击戳一戳")
                    av.double_clicked.connect(lambda: self.poke.emit(self.msg))
                    self.av = av
            row.addWidget(av, 0, Qt.AlignmentFlag.AlignBottom)
        if mine:
            row.addStretch(1)
        row.addLayout(col)
        if not mine:
            row.addStretch(1)
        if show_head and group and not mine:
            col.addWidget(self._name_row(msg), 0, align)
        if msg.fav:
            f = msg.fav
            when = time.strftime("%m-%d %H:%M", time.localtime(f.get("time") or msg.time))
            src = label(f"⭐ 来自 {f.get('from', '')}  ·  {f.get('where', '')}  ·  {when}", "favSource")
            src.setContentsMargins(6, 0, 6, 0)
            col.addWidget(src, 0, align)
        if msg.reply:
            q = ClickLabel()
            q.setObjectName("quote")
            q.setTextFormat(Qt.TextFormat.PlainText)
            text = f"{msg.reply.get('nick', '')}:{msg.reply.get('preview', '')}"
            q.setText(q.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(80, maxw - 40)))
            q.setCursor(Qt.CursorShape.PointingHandCursor)
            q.setToolTip("点击跳到原消息")
            rmid = msg.reply.get("mid", "")
            q.clicked.connect(lambda: self.jump.emit(rmid))
            col.addWidget(q, 0, align)
        if msg.anon and msg.text.strip() and (msg.img is not None or msg.vid is not None):
            note = QLabel(soft_wrap(msg.text))              # 带图片 / 视频的匿名纸条:文字写在上面
            note.setObjectName("noteBubble")
            note.setTextFormat(Qt.TextFormat.PlainText)
            note.setWordWrap(True)
            note.setMaximumWidth(max(120, maxw))
            note.setMinimumHeight(2 * theme.BUBBLE_R)
            note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            note.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            col.addWidget(note, 0, align)
        if msg.card:
            self.card_w = make_card(msg, card_state or {})
        if self.card_w is not None:
            self.card_w.act.connect(lambda a, d: self.card_action.emit(self.msg, a, d))
            if msg.text and (msg.card or {}).get("type") != "throw":      # 扔东西的卡片自己有说明
                tip = label(msg.text, "fileSub")
                tip.setContentsMargins(6, 0, 6, 0)
                col.addWidget(tip, 0, align)
            col.addWidget(self.card_w, 0, align)
        elif msg.file:
            name = str(msg.file.get("name", ""))
            is_video = not msg.file.get("dir") and file_ext(name) in VIDEO_EXTS
            self.card = (VideoCard if is_video else FileCard)(msg, transfer or {})
            self.card.action.connect(lambda a: self.file_action.emit(self.msg, a))
            col.addWidget(self.card, 0, align)
        elif msg.img is not None:
            self._build_image(col, align)
        else:
            self.body = QLabel(soft_wrap(msg.text))
            if msg.anon:
                kind = "noteBubble"
            elif msg.mention and not mine:
                kind = "bubbleOtherAt"
            elif msg.skin and not msg.burn and msg.skin in theme.SKIN_BY_ID:
                kind = "skin_" + msg.skin
            elif mine:
                kind = "bubbleMine" + ("Burn" if msg.burn else "")
            else:
                kind = "bubbleOther" + ("Burn" if msg.burn else "")
            self.body.setObjectName(kind)
            self.body.setProperty("side", "r" if mine else "l")
            if grp != "single" and kind != "noteBubble":
                self.body.setProperty("grp", grp)
            self.body.setTextFormat(Qt.TextFormat.PlainText)      # 纯文本,杜绝 HTML 注入
            # 至少两个圆角那么高:Qt 发现同一侧上下两个圆角加起来比气泡还高,会把两个角都画成直角
            self.body.setMinimumHeight(2 * theme.BUBBLE_R)
            self.body.setIndent(0)
            self.body.setWordWrap(True)
            self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.body.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            col.addWidget(self.body, 0, align)
        self.meta = QLabel()
        self.meta.setObjectName("meta")
        self.meta.setContentsMargins(6, 0, 6, 0)
        col.addWidget(self.meta, 0, align)
        self._col, self._align = col, align
        self.update_meta(time.monotonic())
        self.fit(maxw)

    @staticmethod
    def top_gap(grp: str, show_head: bool = False) -> int:
        """新的一组消息上面空 10,组内连续的只空 2(看起来是一段话)。"""
        return 10 if grp in ("single", "first") or show_head else 2

    def set_group(self, grp: str) -> None:
        """后面又来了一条同一个人的消息:改变自己在组里的位置(拐角 / 间距)。"""
        if grp == self.grp or self.pill is not None:
            return
        self.grp = grp
        if self.body is not None and self.body.objectName() != "noteBubble":
            self.body.setProperty("grp", grp if grp != "single" else None)
            repolish(self.body)
        m = self._row.contentsMargins()
        self._row.setContentsMargins(m.left(), self.top_gap(grp), m.right(), m.bottom())

    def _name_row(self, msg: Msg) -> QWidget:
        """群聊里名字那一行:昵称 · #标签,后面是等级标识和佩戴的称号。"""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(5)
        if msg.anon:
            lay.addWidget(label("📝 匿名纸条", "name"))
            return w
        lay.addWidget(label(f"{msg.nick}  ·  #{msg.tag}", "name"))
        if msg.level > 0:
            tier = theme.level_tier(msg.level)
            lv = label(f"Lv.{msg.level}", "lvBadge")
            lv.setProperty("tier", str(tier))
            lv.setToolTip(f"宠物等级 {msg.level} · {theme.LEVEL_TIERS[tier][1]}")
            lay.addWidget(lv)
        if msg.title:
            t = label(msg.title, "titleBadge")
            t.setToolTip("佩戴的称号(成就墙里拿到的)")
            lay.addWidget(t)
        return w

    def enterEvent(self, e) -> None:
        super().enterEvent(e)
        if not self.msg.system:
            self.hovered.emit(self)

    def leaveEvent(self, e) -> None:
        super().leaveEvent(e)
        self.unhovered.emit(self)

    def content_widget(self):
        """消息主体(文字气泡 / 图片 / 文件卡片 / 卡片),快捷操作条贴着它摆。"""
        return self.body or self.card or self.card_w or getattr(self, "_img", None)

    def set_select(self, mode: bool, checked: bool) -> None:
        if self.sel_btn is not None:
            self.sel_btn.setVisible(mode)
            self.sel_btn.setChecked(checked)
            self.sel_btn.setText("✓" if checked else "")

    react_hook = None              # 2.5:回应变多时让那个表情弹一下(主窗口设置)

    def set_reactions(self, items: list) -> None:
        """items = [(表情, 人数, 我有没有点, 谁点的)]。在气泡下面显示一排小标签,点一下跟着点 / 取消。"""
        if self.pill is not None:
            return
        prev = getattr(self, "_react_prev", None)
        self._react_prev = {e: n for e, n, _m, _names in items}
        if self.react_row is not None:
            self._col.removeWidget(self.react_row)
            self.react_row.deleteLater()
            self.react_row = None
        self.react_chips = [(e, n, mine) for e, n, mine, _names in items]
        if not items:
            return
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)
        for e, n, mine, names in items:
            chip = QPushButton(f"{e} {n}")
            chip.setObjectName("reactChipMine" if mine else "reactChip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(names)
            chip.clicked.connect(lambda _=False, e=e: self.react.emit(self.msg, e))
            lay.addWidget(chip)
            if prev is not None and n > prev.get(e, 0) and Bubble.react_hook is not None:
                QTimer.singleShot(0, lambda c=chip, e=e: Bubble.react_hook(c, e))     # 等排好位置再弹
        self._col.addWidget(w, 0, self._align)
        self.react_row = w

    def contextMenuEvent(self, e) -> None:
        if not self.msg.system:
            self.menu_requested.emit(self.msg, e.globalPos())

    def flash(self) -> None:
        """跳到这条消息时,整行亮一下再慢慢恢复。"""
        if self.property("searchHit"):
            return
        self._flashing = True
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("searchHit", True)
        repolish(self)
        QTimer.singleShot(1400, self._unflash)

    def _unflash(self) -> None:
        try:
            if getattr(self, "_flashing", False):
                self._flashing = False
                self.setProperty("searchHit", False)
                repolish(self)
        except RuntimeError:                       # 这一行已经被删掉了(换了会话、重画)
            pass

    def set_search(self, query: str, current: bool) -> None:
        self._flashing = False
        """搜索时:关键词涂上黄色记号;当前这条整行再加一层底色。"""
        if self.body is not None:
            text = self.msg.text
            if query and query.lower() in text.lower():
                self.body.setTextFormat(Qt.TextFormat.RichText)
                self.body.setText(highlight_html(text, query))
                self._hl = True
            elif getattr(self, "_hl", False):
                self.body.setTextFormat(Qt.TextFormat.PlainText)
                self.body.setText(soft_wrap(text))
                self._hl = False
        if bool(self.property("searchHit")) != current:
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setProperty("searchHit", current)
            repolish(self)

    def _build_image(self, col, align) -> None:
        m = self.msg
        hidden = bool(m.burn and not m.mine)
        if m.mime == "image/gif" and not hidden:
            info_ = imaging.gif_meta(m.img)
            if info_ and info_[2] > 1:                       # 会动的图:用 GifLabel 播放
                gw, gh = info_[0], info_[1]
                side = 140 if m.sticker else imaging.THUMB
                tw, th = imaging.fit_size(gw, gh, side)
                lab = GifLabel(m.img, tw, th, 12 if m.sticker else 14, badge=not m.sticker)
                lab.setObjectName("imageBubble")
                lab.setCursor(Qt.CursorShape.PointingHandCursor)
                lab.setToolTip("动图 · 点击查看大图 · 右键更多")
                lab.clicked.connect(lambda: self.open_image.emit(self.msg))
                self._img = lab
                col.addWidget(lab, 0, align)
                return
        key = (m.mid, bool(m.sticker), hidden, len(m.img or b""))
        if m.thumb is None and not m.burn:
            m.thumb = imaging.thumb_cache.get(key)
        if m.thumb is None:
            side = 140 if m.sticker else imaging.THUMB
            img = imaging.decode_scaled(m.img, side * 2)        # 只按缩略图大小解码;点开看大图时才解原图
            if img is None:
                m.thumb = False
            elif m.sticker:
                m.thumb = imaging.thumbnail(img, 140, 12, hidden=hidden, label="点击查看", shadow=False)
            else:
                m.thumb = imaging.thumbnail(img, hidden=hidden, label="点击查看 · 阅后即焚")
            if m.thumb is not False and not m.burn:
                imaging.thumb_cache.put(key, m.thumb)
        if m.thumb is False:
            lab = label("图片无法显示", "imageBroken")
        else:
            lab = ClickLabel()
            lab.setObjectName("imageBubble")
            lab.setPixmap(m.thumb)
            lab.setCursor(Qt.CursorShape.PointingHandCursor)
            lab.setToolTip("点击查看大图 · 右键更多")
            lab.clicked.connect(lambda: self.open_image.emit(self.msg))
        self._img = lab
        col.addWidget(lab, 0, align)

    def fit(self, maxw: int) -> None:
        target = self.body or self.pill
        if target is None:
            return
        fm = target.fontMetrics()
        lines = target.text().split("\n")
        # 左右内边距 28,再多留几像素:中文字宽带小数,宽度刚好卡住时 Qt 会把一行算成两行(气泡莫名变高)
        natural = max((fm.horizontalAdvance(line) for line in lines), default=0) + 36
        target.setFixedWidth(max(2 * theme.BUBBLE_R + 8, min(natural, maxw)))
        if target is self.body and self.body.objectName() != "noteBubble":
            one_line = len(lines) == 1 and natural <= maxw            # 一行放得下:文字居中,左右留白一样
            h = Qt.AlignmentFlag.AlignHCenter if one_line else Qt.AlignmentFlag.AlignLeft
            target.setAlignment(h | Qt.AlignmentFlag.AlignVCenter)

    def update_meta(self, now: float) -> None:
        if self.meta is None:
            return
        m = self.msg
        parts, kind = [], "meta"
        if m.edited:
            parts.append("已编辑")
        if m.anon and m.mine:
            parts.append("匿名发出 · 只有你知道是你")
        if m.burn:
            if m.deadline:
                parts.append(f"🔥 {fmt_secs(m.deadline - now)}")
                kind = "metaBurn"
            elif m.img is not None and not m.mine:
                parts.append(f"阅后即焚 · 打开后 {fmt_secs(m.burn)} 焚毁")
            else:
                parts.append(f"阅后即焚 · {fmt_secs(m.burn)}")
        if m.status:
            parts.append(m.status)
            if m.status.startswith("未"):
                kind = "metaWarn"
        elif m.receipt:
            parts.append(m.receipt)
        text = "  ·  ".join(parts)
        self.meta.setText(text)
        self.meta.setVisible(bool(text))
        if self.meta.objectName() != kind:
            self.meta.setObjectName(kind)
            repolish(self.meta)

    def update_transfer(self, tr: dict) -> None:
        if self.card is not None:
            self.card.update_state(tr)


class EmojiPanel(QFrame):
    """表情面板:系统表情 + 表情包收藏。弹出式,点外面自动关闭。"""
    picked = Signal(str)
    sticker_picked = Signal(object)
    add_sticker = Signal()
    remove_sticker = Signal(str)

    def __init__(self, parent, recent: list[str], stickers: list[dict], tab: int = 0) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(392, 360)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("emojiPanel")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(6)
        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self.tab_btns = []
        for i, text in enumerate(("表情", "表情包")):
            b = QPushButton(text)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.show_tab(i))
            tabs.addWidget(b)
            self.tab_btns.append(b)
        tabs.addStretch(1)
        lay.addLayout(tabs)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._scroll(self._emoji_page(recent)))
        self.sticker_grid = QGridLayout()
        self.stack.addWidget(self._scroll(self._sticker_page(stickers)))
        lay.addWidget(self.stack, 1)
        self.show_tab(tab)

    def show_tab(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.tab_btns):
            b.setChecked(i == j)

    @staticmethod
    def _scroll(widget) -> QScrollArea:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        sc.setWidget(widget)
        return sc

    def _emoji_page(self, recent: list[str]) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setSpacing(2)
        groups = ([("最近使用", recent)] if recent else []) + EMOJI_GROUPS
        row = 0
        font = emoji_font(22)
        for title, items in groups:
            grid.addWidget(label(title, "section"), row, 0, 1, 8)
            row += 1
            for i, e in enumerate(items):
                b = QToolButton()
                b.setObjectName("emoji")
                b.setText(e)
                b.setFont(font)
                b.setFixedSize(42, 42)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _=False, e=e: self.picked.emit(e))
                grid.addWidget(b, row + i // 8, i % 8)
            row += (len(items) + 7) // 8
        grid.setRowStretch(row, 1)
        return page

    def _sticker_page(self, stickers: list[dict]) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(2, 4, 2, 2)
        grid.setSpacing(6)
        add = ClickLabel()
        add.setFixedSize(80, 80)
        add.setAlignment(Qt.AlignmentFlag.AlignCenter)
        add.setObjectName("imageBroken")
        add.setPixmap(icon("plus", T["sub"], 26).pixmap(26, 26))
        add.setToolTip("从电脑导入图片作为表情包")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self._on_add)
        grid.addWidget(add, 0, 0)
        for n, st in enumerate(stickers, start=1):
            if st.get("thumb") is None:
                img = imaging.decode(st["data"])
                st["thumb"] = imaging.thumbnail(img, 76, 10, shadow=False) if img is not None else False
            if st["thumb"] is False:
                continue
            tile = ClickLabel()
            tile.setFixedSize(80, 80)
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setPixmap(st["thumb"])
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setToolTip("点击发送 · 右键删除")
            tile.clicked.connect(lambda st=st: self._on_sticker(st))
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda pos, st=st, tile=tile: self._sticker_menu(st, tile, pos))
            grid.addWidget(tile, n // 4, n % 4)
        rows = (len(stickers) + 1 + 3) // 4
        if not stickers:
            grid.addWidget(label("还没有表情包。\n在聊天里右键图片 →「添加到表情」,\n或点左边的 ＋ 从电脑导入。", "faint", wrap=True),
                           0, 1, 1, 3)
        grid.setRowStretch(rows, 1)
        grid.setColumnStretch(4, 1)
        return page

    def _on_add(self) -> None:
        self.close()
        self.add_sticker.emit()

    def _on_sticker(self, st: dict) -> None:
        self.close()
        self.sticker_picked.emit(st)

    def _sticker_menu(self, st: dict, tile, pos) -> None:
        m = make_menu(self)
        act = m.addAction("从表情包中删除")
        act.triggered.connect(lambda: (self.remove_sticker.emit(st["id"]), tile.hide()))
        m.exec(tile.mapToGlobal(pos))


class Wallpaper(QWidget):
    """主窗口的背景:按主题画的渐变壁纸,所有半透明面板都叠在它上面。
    动态背景:壁纸上再叠几团缓慢漂移、呼吸的柔光斑,和一道偶尔斜着扫过的柔光。为了不费电:
      · 窗口在前台时每秒约 20 帧;在后台(但看得见)时每秒 4 帧,慢慢动
      · 最小化、藏起来时完全停下(画面定在当时的样子,回来时接着动,不会跳)
      · 设置 → 外观 里可以换成静态背景"""
    FRAME_MS = 50
    IDLE_FRAME_S = 0.25

    def __init__(self) -> None:
        super().__init__()
        self.ambient = False
        self._t = 0.0                      # 动画时间:只在真正动的时候往前走
        self._last_tick = time.monotonic()
        self._last_paint = 0.0
        self.frames = 0                    # 画了多少帧动态背景(诊断信息里看得到,用来确认它真的在动)
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._step)

    def set_ambient(self, on: bool) -> None:
        self.ambient = bool(on)
        if self.ambient:
            self._last_tick = time.monotonic()
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def state(self) -> int:
        """0 = 停下,1 = 在后台慢慢动,2 = 在前台正常动。"""
        w = self.window()
        if not self.ambient or not w.isVisible() or w.isMinimized():
            return 0
        return 2 if w.isActiveWindow() else 1

    def running(self) -> bool:
        return self.state() > 0

    def _step(self) -> None:
        now = time.monotonic()
        dt, self._last_tick = now - self._last_tick, now
        st = self.state()
        if st == 0:
            return
        self._t += min(dt, 0.5)
        if st == 1 and now - self._last_paint < self.IDLE_FRAME_S:
            return
        self._last_paint = now
        self.update()

    def paintEvent(self, e) -> None:
        if self.ambient:
            self.frames += 1
        theme.paint_wallpaper(self, e, self._t if self.ambient else None)

    def status_text(self) -> str:
        if not self.ambient:
            return "关(静态背景)"
        level = {1: "轻柔", 2: "明显"}.get(theme.CUSTOM.get("ambient_level"), "明显")
        st = {0: "暂停(窗口最小化或藏起来了)", 1: "后台慢速", 2: "正在动"}[self.state()]
        return (f"开({level}) · {st} · 计时器{'在跑' if self._timer.isActive() else '没在跑'} · "
                f"动画 {self._t:.0f} 秒 · 已画 {self.frames} 帧")


class MsgArea(QScrollArea):
    resized = Signal()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.resized.emit()


class ChatPanel(QWidget):
    """聊天区。顶栏浮在消息上方(半透明),消息可以从顶栏下面滚过去。"""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("chatPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header = None
        self.pet = None
        self.effects = None
        self.pill = None
        self.search = None
        self.notice = None
        self.pet_hit = None
        self.extras_cb = None
        self.heat = 0.0
        self._t0 = time.monotonic()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.place_overlays()

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if self.heat > 0.02:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.paint_heat(p, self.width(), self.height(), time.monotonic() - self._t0)
            p.end()

    def paint_heat(self, p: QPainter, w: int, h: int, t: float) -> None:
        """三团慢慢漂动的暖色光晕。热度越高越亮,最热时中间再升起一团。"""
        name = T.get("name", "light")
        cols = HEAT_COLORS.get(name, HEAT_COLORS["light"])
        amax = HEAT_ALPHA.get(name, 0.4) * min(1.0, self.heat) ** 0.7     # 中等热度也看得出来
        size = max(w, h)
        blobs = (
            (0.16 + 0.08 * math.sin(t * 0.21), 0.95 + 0.04 * math.sin(t * 0.33), 0.62, cols[0], 1.0),
            (0.84 + 0.07 * math.sin(t * 0.17 + 1.3), 0.90 + 0.05 * math.sin(t * 0.29 + 0.7), 0.56, cols[1], 0.9),
            (0.50 + 0.16 * math.sin(t * 0.13 + 2.1), 0.62 + 0.08 * math.sin(t * 0.23 + 0.4), 0.48, cols[2],
             max(0.0, self.heat - 0.4) / 0.6),
        )
        for fx, fy, fr, col, k in blobs:
            a = amax * k
            if a < 0.01:
                continue
            cx, cy, r = fx * w, fy * h, fr * size
            g = QRadialGradient(QPointF(cx, cy), r)
            for stop, mult in ((0.0, 1.0), (0.4, 0.5), (0.75, 0.15), (1.0, 0.0)):
                c = QColor(col)
                c.setAlphaF(a * mult)
                g.setColorAt(stop, c)
            p.fillRect(QRectF(cx - r, cy - r, 2 * r, 2 * r).intersected(QRectF(0, 0, w, h)), QBrush(g))

    def place_overlays(self) -> None:
        """顶栏贴顶;宠物趴在输入框的上边缘(靠右,让开发送键);特效层盖住整个聊天区。"""
        if self.header is not None:
            self.header.setGeometry(0, 0, self.width(), HEADER_H)
            self.header.raise_()
        if self.pet is not None and self.pill is not None:
            tl = self.pill.mapTo(self, QPoint(0, 0))
            self.pet.move(tl.x() + self.pill.width() - self.pet.W - 44, tl.y() - self.pet.EDGE + 1)
            self.pet.raise_()
        top = HEADER_H + 6
        if self.notice is not None and self.notice.isVisible():
            self.notice.setGeometry(16, top, self.width() - 32, 38)
            self.notice.raise_()
            top += 44
        if self.search is not None:
            sw = min(400, self.width() - 32)
            self.search.setGeometry(self.width() - sw - 16, top, sw, 42)
            self.search.raise_()
        if self.extras_cb is not None:
            self.extras_cb()
        if self.effects is not None:
            self.effects.setGeometry(0, 0, self.width(), self.height())
            self.effects.raise_()


class HoverBar(QFrame):
    """鼠标停在一条消息上时,旁边浮出的一排快捷按钮:回复 / 复制 / 收藏 / 删除 / 更多。"""
    act = Signal(str)
    entered = Signal()
    left = Signal()
    BTN = 26
    ACTIONS = (("reply", "reply", "回复"), ("copy", "copy", "复制"), ("fav", "star", "收藏"),
               ("delete", "trash", "删除(只删本机)"), ("more", "more", "更多…"))

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setObjectName("hoverBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 2, 3, 2)
        lay.setSpacing(1)
        self.btns: dict[str, QToolButton] = {}
        for key, _ic, tip in self.ACTIONS:
            b = QToolButton()
            b.setObjectName("hoverBtn")
            b.setFixedSize(self.BTN, self.BTN)
            b.setIconSize(QSize(15, 15))
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.act.emit(k))
            lay.addWidget(b)
            self.btns[key] = b
        self.bubble = None
        self.refresh_icons()
        self.hide()

    def refresh_icons(self) -> None:
        for key, ic, _tip in self.ACTIONS:
            self.btns[key].setIcon(icon(ic, T["icon"], 15))

    def set_actions(self, keys) -> int:
        """只显示这条消息能用的按钮,返回整条的宽度。"""
        n = 0
        for key, b in self.btns.items():
            on = key in keys
            b.setVisible(on)
            n += on
        w = n * (self.BTN + 1) + 6
        self.setFixedSize(w, self.BTN + 4)
        return w

    def enterEvent(self, e) -> None:
        super().enterEvent(e)
        self.entered.emit()

    def leaveEvent(self, e) -> None:
        super().leaveEvent(e)
        self.left.emit()


class DropOverlay(QWidget):
    """把文件拖进窗口时盖在聊天区上的提示:松开就直接发送。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title = ""
        self.detail = ""
        self.ok = True
        self.hide()

    def set_info(self, title: str, detail: str, ok: bool = True) -> None:
        self.title, self.detail, self.ok = title, detail, ok
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bg = QColor(T["bg"])
        bg.setAlphaF(0.62)
        p.fillRect(self.rect(), bg)
        accent = QColor(T["accent"] if self.ok else T["bad"])
        r = QRectF(self.rect()).adjusted(22, HEADER_H + 14, -22, -22)
        fill = QColor(accent)
        fill.setAlphaF(0.08)
        pen = QPen(accent, 2.0, Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 4])
        p.setPen(pen)
        p.setBrush(fill)
        p.drawRoundedRect(r, 22, 22)
        c = r.center()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawEllipse(QPointF(c.x(), c.y() - 34), 28, 28)
        paint_icon(p, "arrow_up" if self.ok else "close", T["on_accent"] if self.ok else "#FFFFFF",
                   c.x() - 13, c.y() - 47, 26, 2.4)
        f = QFont(self.font())
        f.setPointSizeF(14)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(T["text"]))
        p.drawText(QRectF(r.left() + 20, c.y() + 6, r.width() - 40, 30), self.title,
                   _text_opt(Qt.AlignmentFlag.AlignCenter))
        f.setPointSizeF(10)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(T["sub"]))
        p.drawText(QRectF(r.left() + 20, c.y() + 38, r.width() - 40, 44), self.detail,
                   _text_opt(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, wrap=True))
        p.end()


class ConvDelegate(QStyledItemDelegate):
    H = 64

    def __init__(self, win: "MainWindow") -> None:
        super().__init__(win)
        self.win = win
        self._elided: dict[str, bool] = {}          # 哪些会话名字太长被省略了(悬停时显示完整名字)

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(option.rect.width(), 200), self.H)

    def helpEvent(self, event, view, option, index) -> bool:
        """名字被省略时,鼠标停上去显示完整名字。"""
        if event is not None and event.type() == QEvent.Type.ToolTip:
            conv = self.win.convs.get(index.data(Qt.ItemDataRole.UserRole))
            if conv is not None:
                tip = conv.title if self._elided.get(conv.key) else ""
                if conv.pinned:
                    tip = (tip + "\n" if tip else "") + "已置顶"
                if conv.muted:
                    tip = (tip + "\n" if tip else "") + "消息免打扰"
                if tip:
                    QToolTip.showText(event.globalPos(), tip, view)
                    return True
            QToolTip.hideText()
            event.ignore()
            return True
        return super().helpEvent(event, view, option, index)

    def paint(self, painter: QPainter, option, index) -> None:
        conv = self.win.convs.get(index.data(Qt.ItemDataRole.UserRole))
        if conv is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(option.rect).adjusted(6, 3, -6, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected and not theme.is_dark():          # 浅色:选中项是一张带柔和阴影的白色卡片
            soft_shadow(painter, r, 11, 26, 6, 1.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRoundedRect(r, 11, 11)
        elif selected or hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qcolor(T["select"] if selected else T["hover"]))
            painter.drawRoundedRect(r, 11, 11)
        elif conv.pinned:                              # 置顶的会话:淡淡的底色
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qcolor(T["btn2"]))
            painter.drawRoundedRect(r, 11, 11)

        av = 42
        ax, ay = int(r.left() + 10), int(r.center().y() - av / 2)
        painter.drawPixmap(ax, ay, self.win.conv_avatar(conv, av))
        if conv.kind == "dm":
            online = bool(self.win.peers.get(conv.target or "", {}).get("online"))
            motion.paint_status_dot(painter, QPointF(ax + av - 5.5, ay + av - 5.5), 5, online, conv.target or "",
                                    QColor(T["ring"]))

        left = ax + av + 12
        right = r.right() - 12
        base = QFont(option.font)
        tf = QFont(base)
        tf.setPointSizeF(8)
        when = fmt_list_time(conv.last_time)
        tw = QFontMetrics(tf).horizontalAdvance(when) if when else 0
        if when:
            painter.setFont(tf)
            painter.setPen(QColor(T["faint"]))
            painter.drawText(QRectF(right - tw, r.top() + 12, tw, 18), when,
                             _text_opt(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        if conv.pinned:                                # 时间左边一个小图钉
            tw += 16
            paint_icon(painter, "pin", T["faint"], right - tw, r.top() + 14, 13, 1.6)

        nf = QFont(base)
        nf.setPointSizeF(10)
        nf.setWeight(QFont.Weight.DemiBold)
        painter.setFont(nf)
        painter.setPen(QColor(T["text"]))
        title_rect = QRectF(left, r.top() + 11, max(10, right - left - tw - 8), 20)
        if conv.muted:
            title_rect.setWidth(max(10, title_rect.width() - 18))
        title = QFontMetrics(nf).elidedText(conv.title, Qt.TextElideMode.ElideRight, int(title_rect.width()))
        self._elided[conv.key] = title != conv.title
        painter.drawText(title_rect, title, _text_opt(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
        if conv.muted:
            x = left + QFontMetrics(nf).horizontalAdvance(title) + 5
            paint_icon(painter, "bell_off", T["faint"], x, r.top() + 14, 13, 1.6)

        badge_w = 0
        if conv.unread and conv.muted and not conv.at_me:      # 免打扰:只显示一个灰色小圆点,不显示数字
            badge_w = 10
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(T["faint"]))
            painter.drawEllipse(QRectF(right - 9, r.top() + 39, 8, 8))
        elif conv.unread:
            bf = QFont(base)
            bf.setPointSizeF(7.5)
            bf.setWeight(QFont.Weight.DemiBold)
            txt = str(conv.unread) if conv.unread < 100 else "99+"
            badge_w = max(18, QFontMetrics(bf).horizontalAdvance(txt) + 11)
            br = QRectF(right - badge_w, r.top() + 34, badge_w, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(T["faint"] if conv.muted else T["badge"]))
            painter.drawRoundedRect(br, 9, 9)
            painter.setFont(bf)
            painter.setPen(QColor(theme.text_on(T["badge"]) if not conv.muted and theme.valid_hex(T["badge"]) else "#FFFFFF"))
            painter.drawText(br, txt, _text_opt(Qt.AlignmentFlag.AlignCenter))

        pf = QFont(base)
        pf.setPointSizeF(9)
        painter.setFont(pf)
        painter.setPen(QColor(T["sub"]))
        pr = QRectF(left, r.top() + 33, max(10, right - left - (badge_w + 8 if badge_w else 0)), 19)
        typing = conv.kind == "dm" and self.win.is_typing(conv.target)
        preview = "正在输入…" if typing else (conv.preview or self.win.default_preview(conv))
        opt = _text_opt(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if conv.at_me and not typing:
            tag_txt = "[有人@我] "
            tw2 = QFontMetrics(pf).horizontalAdvance(tag_txt)
            painter.setPen(QColor(T["accent"]))
            painter.drawText(QRectF(pr.left(), pr.top(), tw2 + 2, pr.height()), tag_txt, opt)
            pr.setLeft(pr.left() + tw2)
            painter.setPen(QColor(T["sub"]))
        if typing:
            painter.setPen(QColor(T["accent"]))
        painter.drawText(pr, QFontMetrics(pf).elidedText(preview, Qt.TextElideMode.ElideRight, int(max(10, pr.width()))),
                         opt)
        painter.restore()


class MemberDelegate(QStyledItemDelegate):
    H = 46

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(option.rect.width(), 160), self.H)

    def paint(self, painter: QPainter, option, index) -> None:
        d = index.data(Qt.ItemDataRole.UserRole) or {}
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(option.rect).adjusted(2, 1, -2, -1)
        if (option.state & QStyle.StateFlag.State_MouseOver) and not d.get("me"):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qcolor(T["hover"]))
            painter.drawRoundedRect(r, 9, 9)
        av = 30
        ax, ay = int(r.left() + 8), int(r.center().y() - av / 2)
        painter.drawPixmap(ax, ay, peer_avatar(d.get("id", ""), d.get("nick", ""), av))
        if not d.get("me"):
            motion.paint_status_dot(painter, QPointF(ax + av - 4, ay + av - 4), 4, bool(d.get("online")),
                                    d.get("id", ""), QColor(T["ring"]))
        left = ax + av + 10
        base = QFont(option.font)
        nf = QFont(base)
        nf.setPointSizeF(9.5)
        nf.setWeight(QFont.Weight.Medium)
        tag = f"#{d.get('tag', '')}" + ("  我" if d.get("me") else "")
        tf = QFont(base)
        tf.setPointSizeF(8)
        tag_w = QFontMetrics(tf).horizontalAdvance(tag)
        avail = r.right() - 8 - left - tag_w - 6
        name = QFontMetrics(nf).elidedText(d.get("nick", ""), Qt.TextElideMode.ElideRight, int(max(20, avail)))
        name_w = QFontMetrics(nf).horizontalAdvance(name)
        painter.setFont(nf)
        painter.setPen(QColor(T["text"]))
        painter.drawText(QRectF(left, r.top(), name_w + 2, r.height()), name,
                         _text_opt(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
        painter.setFont(tf)
        painter.setPen(QColor(T["faint"]))
        painter.drawText(QRectF(left + name_w + 6, r.top(), tag_w + 2, r.height()), tag,
                         _text_opt(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
        painter.restore()
