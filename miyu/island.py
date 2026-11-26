"""
密语 3.5 · 灵动岛 (Dynamic Island) 与 3D 全息镭射卡片反光层 (HoloOverlay)。
纯 QPainter 矢量与物理弹簧插值，零 QGraphicsEffect，窗口隐藏时自动停止动画。
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient, QTextOption
from PySide6.QtWidgets import QWidget

from .theme import is_dark
from .version import VERSION


class DynamicIsland(QWidget):
    """窗口顶部中央的灵动岛胶囊:
    - 待机: 极简小胶囊(在线人数 / 密语状态)
    - 新消息: 横向弹性弹开显示发送者与摘要,点击直达该会话
    - 白噪音: 展开 5 根实时跳动的迷你声波条,点击一键静音/恢复
    - 定时提醒: 实时跳动剩余倒计时
    """
    clicked = Signal(str)                         # 传出目标会话 key(或 "__ambient__")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._w = 112.0
        self._h = 26.0
        self._tw = 112.0
        self._th = 26.0
        self._active = True
        self._online = 0
        self._ambient = ""
        self._msg_title = ""
        self._msg_body = ""
        self._msg_key = ""
        self._msg_until = 0.0
        self._remind_label = ""
        self._remind_end = 0.0
        self._focus_label = ""
        self._focus_end = 0.0
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.resize(int(self._w), int(self._h))

    def set_active(self, on: bool) -> None:
        """主窗口隐藏或最小化时暂停动画计时器,回到前台自动恢复。"""
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        if not on:
            self._timer.stop()
        elif self.isVisible() and (self.mode() != "idle" or abs(self._w - self._tw) > 0.6):
            self._ensure_timer()

    # ---- 状态更新接口
    def set_online(self, count: int) -> None:
        self._online = max(0, int(count))
        self._retarget()
        self.update()

    def set_ambient(self, name: str) -> None:
        self._ambient = (name or "").strip()
        self._retarget()
        self._ensure_timer()
        self.update()

    def show_message(self, conv_key: str, sender: str, preview: str, secs: float = 3.6) -> None:
        self._msg_key = conv_key
        self._msg_title = (sender or "")[:10]
        self._msg_body = (preview or "").replace("\n", " ")[:22]
        self._msg_until = time.monotonic() + secs
        self._retarget()
        self._ensure_timer()
        self.update()

    def set_reminder(self, note: str, end_mono: float) -> None:
        self._remind_label = (note or "提醒")[:12]
        self._remind_end = end_mono
        self._retarget()
        self._ensure_timer()
        self.update()

    def clear_reminder(self) -> None:
        self._remind_end = 0.0
        self._remind_label = ""
        self._retarget()
        self.update()

    def set_focus(self, label_txt: str, end_mono: float) -> None:
        self._focus_label = (label_txt or "专注中")[:10]
        self._focus_end = end_mono
        self._retarget()
        self._ensure_timer()
        self.update()

    def clear_focus(self) -> None:
        self._focus_end = 0.0
        self._focus_label = ""
        self._retarget()
        self.update()

    def mode(self) -> str:
        now = time.monotonic()
        if now < self._msg_until and self._msg_body:
            return "msg"
        if self._focus_end > now:
            return "focus"
        if self._remind_end > now:
            return "remind"
        if self._ambient:
            return "ambient"
        return "idle"

    def _retarget(self) -> None:
        m = self.mode()
        if m == "msg":
            tw, th = 268.0, 32.0
        elif m == "focus":
            tw, th = 204.0, 28.0
        elif m == "remind":
            tw, th = 188.0, 28.0
        elif m == "ambient":
            tw, th = 166.0, 28.0
        else:
            tw, th = 114.0, 25.0
        par = self.parentWidget()
        if par is not None and par.width() > 0:
            tw = min(tw, max(106.0, float(par.width() - 32)))
        self._tw, self._th = tw, th

    def _ensure_timer(self) -> None:
        if self._active and self.isVisible() and not self._timer.isActive():
            self._timer.start()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.mode() != "idle" or abs(self._w - self._tw) > 0.6:
            self._ensure_timer()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def _tick(self) -> None:
        self._retarget()
        self._w += (self._tw - self._w) * 0.24
        self._h += (self._th - self._h) * 0.24
        nw, nh = max(90, int(round(self._w))), max(22, int(round(self._h)))
        if nw != self.width() or nh != self.height():
            self.resize(nw, nh)
            self.place()
        if self.mode() == "idle" and abs(self._w - self._tw) < 0.6 and abs(self._h - self._th) < 0.6:
            self._w, self._h = self._tw, self._th
            self.resize(int(self._w), int(self._h))
            self.place()
            self._timer.stop()
        self.update()

    def place(self) -> None:
        par = self.parentWidget()
        if par is None:
            return
        w, h = self.width(), self.height()
        # 优先检测顶栏中间的实际空白区域(左侧标题文字终点 ~ 右侧首个可见按钮起点)
        # 只有空白宽度足够放下整个灵动岛时才嵌入顶栏,否则优雅停靠到顶栏正下方,绝不遮挡排行榜/搜索等任何按钮!
        gap_fn = getattr(self, "header_gap_fn", None)
        if callable(gap_fn):
            try:
                left_end, right_start, header_h, below_y = gap_fn()
                if right_start - left_end >= w + 20:
                    x = int((left_end + right_start - w) // 2)
                    y = max(4, int((header_h - h) // 2))
                    self.move(x, y)
                    return
                x = max(12, (par.width() - w) // 2)
                self.move(x, int(below_y))
                return
            except Exception:
                pass
        x = max(12, (par.width() - w) // 2)
        self.move(x, 66)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            m = self.mode()
            if m == "msg" and self._msg_key:
                self._msg_until = 0.0
                self.clicked.emit(self._msg_key)
            elif m == "focus":
                self.clicked.emit("__focus__")
            elif m == "ambient":
                self.clicked.emit("__ambient__")
            else:
                self.clicked.emit("")

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = float(self.width()), float(self.height())
        r = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
        rad = h / 2.0 - 1.0
        now = time.monotonic()

        # 液态深曜石毛玻璃胶囊机身 + 1px 顶部高光折射边
        bg = QLinearGradient(0, 0, 0, h)
        if is_dark():
            bg.setColorAt(0.0, QColor(28, 30, 42, 232))
            bg.setColorAt(1.0, QColor(14, 15, 22, 240))
        else:
            bg.setColorAt(0.0, QColor(32, 34, 46, 222))
            bg.setColorAt(1.0, QColor(18, 20, 28, 234))
        p.setPen(QPen(QColor(255, 255, 255, 58), 1.0))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(r, rad, rad)
        # 顶部 1px 镜面高光弧
        p.setPen(QPen(QColor(255, 255, 255, 90), 0.9))
        p.drawLine(QPointF(rad, 1.6), QPointF(w - rad, 1.6))

        m = self.mode()
        f = QFont(self.font())
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)

        if m == "msg":
            # 新消息提示圆点 + 发送者与摘要
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#51CF66"))
            p.drawEllipse(QPointF(14, h / 2), 4.0, 4.0)
            p.setPen(QColor("#FFFFFF"))
            txt = f"{self._msg_title}: {self._msg_body}" if self._msg_title else self._msg_body
            p.drawText(QRectF(24, 0, w - 34, h), txt, QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
        elif m == "focus":
            left = max(0, int(self._focus_end - now))
            mm, ss = divmod(left, 60)
            p.setPen(Qt.PenStyle.NoPen)
            pulse = 0.65 + 0.35 * math.sin(now * 3.2)
            dc = QColor("#FF6B6B")
            dc.setAlphaF(pulse)
            p.setBrush(dc)
            p.drawEllipse(QPointF(15, h / 2), 4.0, 4.0)
            p.setPen(QColor("#FFE3E3"))
            p.drawText(QRectF(24, 0, w - 34, h), f"🍅 {mm:02d}:{ss:02d}  {self._focus_label}",
                       QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
        elif m == "remind":
            left = max(0, int(self._remind_end - now))
            mm, ss = divmod(left, 60)
            p.setPen(QColor("#FFD43B"))
            p.drawText(QRectF(12, 0, w - 24, h), f"⏰ {mm:02d}:{ss:02d}  {self._remind_label}",
                       QTextOption(Qt.AlignmentFlag.AlignCenter))
        elif m == "ambient":
            # 5 根动态音频声波条
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(5):
                bar_h = 4.0 + 9.0 * (0.5 + 0.5 * math.sin(now * 6.5 + i * 1.15))
                col = QColor("#63E6BE" if i % 2 == 0 else "#74C0FC")
                p.setBrush(col)
                p.drawRoundedRect(QRectF(14 + i * 4.2, (h - bar_h) / 2, 2.6, bar_h), 1.3, 1.3)
            p.setPen(QColor("#F1F3F5"))
            p.drawText(QRectF(40, 0, w - 50, h), f"{self._ambient} · 点此静音",
                       QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
        else:
            # 极简待机胶囊
            p.setPen(Qt.PenStyle.NoPen)
            pulse = 0.6 + 0.4 * math.sin(now * 2.4)
            dot = QColor("#51CF66" if self._online > 0 else "#ADB5BD")
            dot.setAlphaF(pulse)
            p.setBrush(dot)
            p.drawEllipse(QPointF(15, h / 2), 3.4, 3.4)
            p.setPen(QColor(240, 242, 248, 225))
            txt = f"{self._online} 人在线" if self._online > 0 else f"✦ 密语 {VERSION}"
            p.drawText(QRectF(24, 0, w - 32, h), txt, QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
        p.end()


class HoloOverlay(QWidget):
    """空间 3D 视差全息镭射反光层:贴附在任意卡片上,鼠标移动时呈现彩虹镭射扫光与立体边缘压感。"""

    def __init__(self, target: QWidget, radius: float = 14.0) -> None:
        super().__init__(target)
        self.target = target
        self.radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._hover = False
        self._nx = 0.5
        self._ny = 0.5
        target.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        target.setMouseTracking(True)
        target.installEventFilter(self)
        self.setGeometry(target.rect())
        self.raise_()

    def eventFilter(self, obj, e) -> bool:
        if obj is self.target:
            et = e.type()
            if et in (QEvent.Type.Resize, QEvent.Type.Show):
                self.setGeometry(self.target.rect())
                self.raise_()
            elif et == QEvent.Type.ChildAdded:
                QTimer.singleShot(0, self.raise_)
            elif et in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                self._hover = True
                self.raise_()
                self.update()
            elif et in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                self._hover = False
                self.update()
            elif et in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                pos = e.position() if hasattr(e, "position") else e.pos()
                w, h = max(1.0, float(self.target.width())), max(1.0, float(self.target.height()))
                self._nx = max(0.0, min(1.0, float(pos.x()) / w))
                self._ny = max(0.0, min(1.0, float(pos.y()) / h))
                self._hover = True
                self.update()
        return False

    def paintEvent(self, _e) -> None:
        if not self._hover:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        r = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        clip = QPainterPath()
        clip.addRoundedRect(r, self.radius, self.radius)
        p.setClipPath(clip)

        # 1. 鼠标跟随 3D 镜面径向追光
        gx, gy = self._nx * w, self._ny * h
        rad = QRadialGradient(QPointF(gx, gy), max(w, h) * 0.65)
        rad.setColorAt(0.0, QColor(255, 255, 255, 58))
        rad.setColorAt(0.45, QColor(180, 210, 255, 22))
        rad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(r, QBrush(rad))

        # 2. 全息彩虹镭射斜向扫光带
        shift = (self._nx - 0.5) * w * 0.8 + (self._ny - 0.5) * h * 0.4
        holo = QLinearGradient(QPointF(shift - w * 0.2, 0), QPointF(shift + w * 0.6, h))
        holo.setColorAt(0.0, QColor(255, 107, 138, 0))
        holo.setColorAt(0.32, QColor(255, 107, 138, 34))
        holo.setColorAt(0.50, QColor(116, 192, 252, 42))
        holo.setColorAt(0.68, QColor(177, 151, 252, 34))
        holo.setColorAt(1.0, QColor(99, 230, 190, 0))
        p.fillRect(r, QBrush(holo))

        # 3. 3D 视差倾斜高光边(光偏向鼠标所在侧)
        edge = QLinearGradient(QPointF(gx, gy), QPointF(w - gx, h - gy))
        edge.setColorAt(0.0, QColor(255, 255, 255, 150))
        edge.setColorAt(0.5, QColor(168, 85, 247, 75))
        edge.setColorAt(1.0, QColor(255, 255, 255, 18))
        p.setPen(QPen(QBrush(edge), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self.radius, self.radius)
        p.end()
