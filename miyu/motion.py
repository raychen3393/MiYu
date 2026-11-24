"""
密语 · 全局微动效(2.0)

  · 按钮悬停:颜色平滑过渡;主按钮亮起一圈主题色的光边,里面一团高光跟着鼠标走;按下时轻轻一暗
  · 弹窗:淡入(毛玻璃半透明窗口除外)
  · 切换会话、设置换页:旧画面淡出、新画面露出来(交叉淡化)
  · 头像在线状态变化:小圆点亮起时向外扩散一圈
  · Switch:设置里的开关,滑块平滑滑过去
设置里可以关掉「界面动效」(关掉后全部瞬间完成,和 1.x 一样)。

2.1.1 起这里不再用 Qt 的 QGraphicsEffect(透明度 / 阴影效果)和半透明弹出窗口的窗口透明度:
它们和滚动区域、正在被点击的控件叠在一起时,在 Windows 上偶尔会让程序直接崩掉(闪退)。
现在全部改成自己画:淡入淡出用一张截图盖在上面慢慢变透明,光晕直接画在按钮里面。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QMenu, QPushButton, QToolButton, QWidget

from .theme import T

ENABLED = True                 # 界面动效总开关


def set_enabled(on: bool) -> None:
    global ENABLED
    ENABLED = bool(on)
    if not ENABLED:
        status_changes.clear()


def animate(owner, start: float, end: float, ms: int, on_value, on_done=None,
            curve=QEasingCurve.Type.OutCubic, key: str = "_motion_anim") -> QVariantAnimation | None:
    """从 start 到 end 的一段动画,每一帧调用 on_value(v)。动效关掉时直接跳到终点。"""
    old = getattr(owner, key, None)
    if old is not None:
        try:
            old.stop()
        except RuntimeError:
            pass
    if not ENABLED or ms <= 0:
        on_value(end)
        if on_done is not None:
            on_done()
        return None
    anim = QVariantAnimation(owner)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(ms)
    anim.setEasingCurve(curve)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    if on_done is not None:
        anim.finished.connect(on_done)
    setattr(owner, key, anim)
    anim.start()
    return anim


def fade_window(w, ms: int = 150) -> None:
    """不透明的顶层窗口(弹窗)淡入。毛玻璃(半透明背景)的窗口不做:那种窗口改透明度在 Windows 上不稳定。"""
    if not ENABLED:
        return
    try:
        if w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            return
        w.setWindowOpacity(0.0)
    except RuntimeError:
        return
    animate(w, 0.0, 1.0, ms, lambda v: _safe(w.setWindowOpacity, v), key="_fade_win_anim")


def snapshot(w: QWidget) -> QPixmap | None:
    """换内容之前先拍一张(用于交叉淡化)。动效关掉、控件看不见时返回 None。"""
    if not ENABLED or w is None:
        return None
    try:
        if not w.isVisible() or w.width() <= 0 or w.height() <= 0:
            return None
        pm = w.grab()
        return None if pm.isNull() else pm
    except RuntimeError:
        return None


class _FadeShot(QWidget):
    """交叉淡化:把旧画面的截图盖在控件上面,慢慢变透明,下面的新内容就"淡入"了。
    只是一张图在自己画,不碰别的控件,也不挡鼠标。"""

    def __init__(self, target: QWidget, pm: QPixmap) -> None:
        super().__init__(target)
        self.pm = pm
        self.op = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(target.rect())
        self.show()
        self.raise_()

    def set_op(self, v: float) -> None:
        self.op = v
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setOpacity(max(0.0, min(1.0, self.op)))
        p.drawPixmap(self.rect(), self.pm)
        p.end()


def crossfade(target: QWidget, before: QPixmap | None, ms: int = 170) -> None:
    """target 的内容刚换过:把换之前拍的 before 盖上去,在 ms 毫秒内淡出。"""
    if not ENABLED or before is None or target is None:
        return
    old = getattr(target, "_fade_shot", None)
    if old is not None:
        try:
            old.deleteLater()
        except RuntimeError:
            pass
    try:
        shot = _FadeShot(target, before)
    except RuntimeError:
        return
    target._fade_shot = shot

    def done() -> None:
        try:
            shot.hide()
            shot.deleteLater()
        except RuntimeError:
            pass
    animate(shot, 1.0, 0.0, ms, lambda v: _safe(shot.set_op, v), done, curve=QEasingCurve.Type.OutCubic,
            key="_fade_anim")


def fade_widget(w: QWidget, ms: int = 170) -> None:
    """旧接口(2.0):现在什么也不做。需要淡入效果的地方改用 snapshot() + crossfade()。"""
    return


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except RuntimeError:                       # 控件已经被删了
        pass


# ====================================================================== 菜单
class FadeMenu(QMenu):
    """菜单。2.0 里它会淡入并往下滑;改窗口透明度对半透明的弹出菜单在 Windows 上不稳定,2.1.1 起直接显示。"""


# ====================================================================== 头像在线状态
status_changes: dict[str, tuple[float, bool]] = {}     # 谁的在线状态刚变了:(时间, 现在是否在线)
PULSE_SECS = 0.9


def note_status(pid: str, online: bool) -> None:
    if ENABLED:
        status_changes[pid] = (time.monotonic(), bool(online))


def pulse_of(pid: str, now: float | None = None) -> float:
    """0~1:状态变化动画进行到哪了;没在动返回 -1。"""
    v = status_changes.get(pid)
    if v is None:
        return -1.0
    k = ((time.monotonic() if now is None else now) - v[0]) / PULSE_SECS
    if k >= 1.0:
        status_changes.pop(pid, None)
        return -1.0
    return k


def any_pulse() -> bool:
    now = time.monotonic()
    for pid in list(status_changes):
        pulse_of(pid, now)
    return bool(status_changes)


def paint_status_dot(p: QPainter, center: QPointF, r: float, online: bool, pid: str, ring: QColor) -> None:
    """头像右下角的在线小圆点;状态刚变化时,圆点从小变大,外面扩散一圈淡淡的光环。"""
    k = pulse_of(pid)
    color = QColor(T["online"] if online else T["offline"])
    if k >= 0:
        ease = 1 - (1 - k) ** 3
        halo = QColor(color)
        halo.setAlphaF(0.55 * (1 - k))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(center, r + 2 + 7 * ease, r + 2 + 7 * ease)
        r = r * (0.55 + 0.45 * min(1.0, k * 2.2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ring)
    p.drawEllipse(center, r + 2, r + 2)
    p.setBrush(color)
    p.drawEllipse(center, r, r)


# ====================================================================== 按钮悬停
SKIP_NAMES = {"reactChip", "reactChipMine", "latestBtn", "hoverBtn", "tab", "selBox", "emojiCell", "stickerTile",
              "segBtn"}


class _Layer(QWidget):
    """盖在按钮上的一层透明画布:画悬停的颜色、跟着鼠标的高光、按下的暗影。"""

    def __init__(self, btn) -> None:
        super().__init__(btn)
        self.btn = btn
        self.hover = 0.0
        self.press = 0.0
        self.pos_x = 0.5
        self.pos_y = 0.6
        self.kind = _kind_of(btn)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(btn.rect())

    def radius(self) -> float:
        w, h = self.width(), self.height()
        name = self.btn.objectName()
        if isinstance(self.btn, QToolButton):
            return min(w, h) / 2 if name in ("round", "sendBtn") or w == h else 8
        return min(10.0, h / 2)

    def paintEvent(self, _e) -> None:
        if self.hover <= 0.001 and self.press <= 0.001:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        rad = self.radius()
        path.addRoundedRect(r, rad, rad)
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        k = self.kind
        if k in ("primary", "send"):
            c = QColor(255, 255, 255)
            c.setAlphaF(0.10 * self.hover)
            p.fillRect(r, c)
            ring = QColor(255, 255, 255)                     # 一圈亮边(代替 2.0 里按钮外面的阴影光晕)
            ring.setAlphaF(0.45 * self.hover)
            p.setPen(QPen(ring, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), max(0.0, rad - 1), max(0.0, rad - 1))
            p.setPen(Qt.PenStyle.NoPen)
            # 跟着鼠标的一团高光(图里按钮下半部分那团亮光)
            g = QRadialGradient(QPointF(r.width() * self.pos_x, r.height() * max(0.55, self.pos_y)),
                                max(r.height() * 1.4, r.width() * 0.45))
            hi = QColor(255, 255, 255)
            for stop, a in ((0.0, 0.30), (0.45, 0.12), (1.0, 0.0)):
                hc = QColor(hi)
                hc.setAlphaF(a * self.hover)
                g.setColorAt(stop, hc)
            p.fillRect(r, QBrush(g))
        else:
            base = {"danger": T["bad"], "link": T["accent"]}.get(k, T["text"])
            c = QColor(base)
            c.setAlphaF((0.09 if k in ("danger", "link") else 0.07) * self.hover)
            p.fillRect(r, c)
        if self.press > 0.001:
            d = QColor(0, 0, 0)
            d.setAlphaF(0.10 * self.press)
            p.fillRect(r, d)
        p.end()


def _kind_of(btn) -> str:
    name = btn.objectName()
    if name == "primary":
        return "primary"
    if name == "sendBtn":
        return "send"
    if name == "destructive":
        return "danger"
    if name == "link":
        return "link"
    return "plain"


class HoverFx(QObject):
    """装在整个程序上的事件过滤器:任何按钮被鼠标碰到时,自动给它加上悬停动效。"""

    def __init__(self, app) -> None:
        super().__init__(app)
        app.installEventFilter(self)

    @staticmethod
    def eligible(obj) -> bool:
        if not isinstance(obj, (QPushButton, QToolButton)) or obj.objectName() in SKIP_NAMES:
            return False
        if isinstance(obj, QPushButton) and obj.styleSheet() and "background" in obj.styleSheet():
            return False                                        # 自己定了颜色的(比如色板小圆点)
        return True

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t not in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                     QEvent.Type.MouseButtonRelease, QEvent.Type.Resize):
            return False
        if not ENABLED or not self.eligible(obj):
            return False
        layer = getattr(obj, "_fx_layer", None)
        if t == QEvent.Type.Resize:
            if layer is not None:
                layer.setGeometry(obj.rect())
            return False
        if layer is None:
            if t != QEvent.Type.Enter or not obj.isEnabled():
                return False
            layer = _Layer(obj)
            obj._fx_layer = layer
        layer.setGeometry(obj.rect())
        layer.raise_()
        layer.show()
        if t == QEvent.Type.Enter and obj.isEnabled():
            self._track(obj, layer, ev)
            animate(layer, layer.hover, 1.0, 160, lambda v: self._set(obj, layer, "hover", v), key="_hover_anim")
        elif t == QEvent.Type.Leave:
            animate(layer, layer.hover, 0.0, 220, lambda v: self._set(obj, layer, "hover", v), key="_hover_anim")
            animate(layer, layer.press, 0.0, 120, lambda v: self._set(obj, layer, "press", v), key="_press_anim")
        elif t == QEvent.Type.MouseMove:
            self._track(obj, layer, ev)
            layer.update()
        elif t == QEvent.Type.MouseButtonPress and obj.isEnabled():
            animate(layer, layer.press, 1.0, 70, lambda v: self._set(obj, layer, "press", v), key="_press_anim")
        elif t == QEvent.Type.MouseButtonRelease:
            animate(layer, layer.press, 0.0, 180, lambda v: self._set(obj, layer, "press", v), key="_press_anim")
        return False

    @staticmethod
    def _track(obj, layer, ev) -> None:
        try:
            pos = ev.position()
            w, h = max(1, obj.width()), max(1, obj.height())
            layer.pos_x = min(1.0, max(0.0, pos.x() / w))
            layer.pos_y = min(1.0, max(0.0, pos.y() / h))
        except (AttributeError, RuntimeError):
            pass

    @staticmethod
    def _set(obj, layer, attr: str, v: float) -> None:
        try:
            setattr(layer, attr, v)
            layer.update()
        except RuntimeError:
            pass


_fx: HoverFx | None = None


def install(app) -> None:
    """程序启动时调用一次。"""
    global _fx
    if _fx is None and app is not None:
        _fx = HoverFx(app)


# ====================================================================== 开关(设置窗口用)
class Switch(QAbstractButton):
    """iOS 风格的开关:点一下滑块平滑滑过去,底色渐变成主题色。"""

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 26)
        self._k = 1.0 if checked else 0.0
        self.toggled.connect(self._on_toggled)

    def sizeHint(self) -> QSize:
        return QSize(44, 26)

    def set_quiet(self, on: bool) -> None:
        """不触发信号地改状态(刷新界面时用)。"""
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._k = 1.0 if on else 0.0
        self.update()

    def _on_toggled(self, on: bool) -> None:
        animate(self, self._k, 1.0 if on else 0.0, 180, self._set_k, key="_switch_anim")

    def _set_k(self, v: float) -> None:
        self._k = v
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = QColor(T["offline"]), QColor(T["accent"])
        k = self._k
        track = QColor(int(off.red() + (on.red() - off.red()) * k), int(off.green() + (on.green() - off.green()) * k),
                       int(off.blue() + (on.blue() - off.blue()) * k))
        if not self.isEnabled():
            track.setAlphaF(0.4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 44, 26), 13, 13)
        x = 3 + 18 * k
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(x, 4, 20, 20))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 3, 20, 20))
        p.end()
