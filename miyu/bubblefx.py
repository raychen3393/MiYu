"""
密语 · 气泡动效(2.5)
- 新消息出现:往上浮一点 + 从小到大 + 淡入。自己发的从右下角长出来,别人发的从左下角长出来。
  「细腻」轻轻的;「活泼」冲过头再弹回来,还带一点点歪头。
- 一下子来好几条(连发、刚连上补发):一条接一条错开出来,不会同时糊成一片。
- 撤回:气泡碎成小块掉下去。
- 有人 @我:气泡出来后左右晃两下,整行亮一下。
- 点回应(表情):那个表情放大弹一下,冒出一个 +1。
全部用"截图 + QPainter"做:动画期间先不画真气泡,在它上面放一张截图做动画,播完再换回真气泡。
不用 QGraphicsEffect —— 它和滚动区域叠在一起时在 Windows 上会让程序闪退(motion.py 里有说明)。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from . import motion

MODES = [("soft", "细腻"), ("lively", "活泼"), ("off", "关闭")]
MODE_IDS = {m for m, _ in MODES}
DUR = {"soft": 0.32, "lively": 0.48}
STAGGER = 0.07                 # 连着来的消息,每条晚这么多秒出来
STAGGER_MAX = 5
PAD = 34                       # 截图四周留的空间(放大 / 歪头时不被裁掉)


def _now() -> float:
    return time.monotonic()


def ease_out(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return 1 - (1 - k) ** 3


def back(k: float, c: float = 1.7) -> float:
    k = max(0.0, min(1.0, k))
    return 1 + (c + 1) * (k - 1) ** 3 + c * (k - 1) ** 2


def enter_pose(mode: str, k: float, mine: bool) -> tuple[float, float, float, float, float]:
    """3.5 升级发送消息「丝滑飞入成泡」:自己发的消息从底部输入框弹性飞入、柔和微回弹。"""
    side = 1 if mine else -1
    if mode == "lively":
        e = ease_out(k)
        dy = (1 - e) * (28 if mine else 16)
        return ((1 - e) * 26 * side, dy, 0.7 + 0.3 * back(k), (1 - e) * 3.5 * -side,
                min(1.0, k * 2.4))
    e = ease_out(k)
    b = back(k, 1.15) if mine else e
    return (1 - e) * 14 * side, (1 - e) * (24 if mine else 12), 0.88 + 0.12 * b, 0.0, min(1.0, k * 1.9)


class _Ghost(QWidget):
    """新气泡的截图,在真气泡的位置上做出场动画。"""

    def __init__(self, parent: QWidget, pm, rect: QRect, mine: bool, mode: str, delay: float, done) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pm, self.mine, self.mode, self.done_cb = pm, mine, mode, done
        self.bw, self.bh = rect.width(), rect.height()
        self.t0 = _now() + delay
        self.dur = DUR.get(mode, 0.32)
        self.setGeometry(rect.adjusted(-PAD, -PAD, PAD, PAD))
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.show()
        self.raise_()

    def progress(self) -> float:
        return (_now() - self.t0) / self.dur

    def _tick(self) -> None:
        if self.progress() >= 1.0:
            self.finish()
            return
        self.update()

    def finish(self) -> None:
        self.timer.stop()
        cb, self.done_cb = self.done_cb, None
        if cb is not None:
            cb()
        try:
            self.hide()
            self.deleteLater()
        except RuntimeError:
            pass

    def paintEvent(self, _e) -> None:
        k = self.progress()
        if k < 0:
            return                                          # 还在排队:先什么都不画
        dx, dy, s, rot, op = enter_pose(self.mode, k, self.mine)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(op)
        ox = PAD + (self.bw if self.mine else 0)           # 从自己那一侧的下角长出来
        oy = PAD + self.bh
        p.translate(ox + dx, oy + dy)
        p.rotate(rot)
        p.scale(s, s)
        p.translate(-(self.bw if self.mine else 0), -self.bh)
        p.drawPixmap(QRectF(0, 0, self.bw, self.bh), self.pm, QRectF(self.pm.rect()))
        p.end()


class _Shatter(QWidget):
    """撤回:截图切成小块,往两边散开、往下掉、转着淡掉。"""
    DUR = 0.75

    def __init__(self, parent: QWidget, pm, rect: QRect) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pm = pm
        self.bw, self.bh = max(1, rect.width()), max(1, rect.height())
        self.setGeometry(rect.adjusted(-60, -20, 60, 140))
        cols = max(3, min(9, self.bw // 46))
        rows = max(2, min(5, self.bh // 22))
        rng = random.Random()
        self.tiles = []
        tw, th = self.bw / cols, self.bh / rows
        sx, sy = pm.width() / self.bw, pm.height() / self.bh      # 截图可能是高清的(两倍像素)
        for r in range(rows):
            for c in range(cols):
                cx = (c + 0.5) / cols - 0.5
                self.tiles.append((QRectF(c * tw, r * th, tw + 0.6, th + 0.6),
                                   QRectF(c * tw * sx, r * th * sy, tw * sx, th * sy),
                                   cx * rng.uniform(80, 200) + rng.uniform(-30, 30), rng.uniform(-140, -40),
                                   rng.uniform(-360, 360), rng.uniform(0, 0.12)))
        self.t0 = _now()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.show()
        self.raise_()

    def _tick(self) -> None:
        if _now() - self.t0 > self.DUR + 0.15:
            self.timer.stop()
            self.hide()
            self.deleteLater()
            return
        self.update()

    def paintEvent(self, _e) -> None:
        t = _now() - self.t0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for dst, src, vx, vy, vr, delay in self.tiles:
            tt = max(0.0, t - delay)
            k = tt / self.DUR
            if k >= 1:
                continue
            x = vx * tt
            y = vy * tt + 0.5 * 900 * tt * tt
            p.save()
            p.setOpacity(max(0.0, 1 - k ** 1.6))
            p.translate(60 + dst.center().x() + x, 20 + dst.center().y() + y)
            p.rotate(vr * tt)
            sc = 1 - 0.35 * k
            p.scale(sc, sc)
            p.drawPixmap(QRectF(-dst.width() / 2, -dst.height() / 2, dst.width(), dst.height()), self.pm, src)
            p.restore()
        p.end()


class _ReactPop(QWidget):
    """点回应:表情放大弹一下,旁边冒出 +1 往上飘。"""
    DUR = 0.65

    def __init__(self, parent: QWidget, center: QPoint, emoji: str, dark: bool) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.emoji, self.dark = emoji, dark
        self.setGeometry(center.x() - 40, center.y() - 60, 80, 80)
        self.t0 = _now()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.show()
        self.raise_()

    def _tick(self) -> None:
        if _now() - self.t0 > self.DUR:
            self.timer.stop()
            self.hide()
            self.deleteLater()
            return
        self.update()

    def paintEvent(self, _e) -> None:
        k = (_now() - self.t0) / self.DUR
        if k >= 1:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = 1 + 0.9 * math.sin(math.pi * min(1.0, k * 1.6)) if k < 0.62 else 1.0
        op = 1.0 if k < 0.55 else max(0.0, 1 - (k - 0.55) / 0.45)
        p.setOpacity(op)
        f = QFont(self.font())
        f.setPointSizeF(13 * s)
        p.setFont(f)
        p.drawText(QRectF(0, 30, 80, 44), int(Qt.AlignmentFlag.AlignCenter), self.emoji)
        f2 = QFont(self.font())
        f2.setPointSizeF(9)
        f2.setBold(True)
        p.setFont(f2)
        p.setPen(QColor("#FFD43B") if self.dark else QColor("#E8590C"))
        p.drawText(QRectF(40, 30 - 34 * ease_out(k), 36, 18), int(Qt.AlignmentFlag.AlignLeft), "+1")
        p.end()


class BubbleFx:
    """主窗口用的气泡动效管理。mode: soft / lively / off。"""

    def __init__(self) -> None:
        self.mode = "soft"
        self.ghosts: list[_Ghost] = []
        self._last = -1e9
        self._streak = 0

    def enabled(self) -> bool:
        return self.mode in DUR and motion.ENABLED

    def clear(self) -> None:
        """换会话 / 重画消息时:正在播的全部停掉(真气泡马上显示)。"""
        for g in list(self.ghosts):
            try:
                g.finish()
            except RuntimeError:
                pass
        self.ghosts.clear()

    def enter(self, b, container: QWidget, on_done=None) -> bool:
        """新气泡出场。返回 True 表示播了动画(on_done 在播完时调用)。"""
        if not self.enabled() or b is None or container is None:
            return False
        try:
            lay = container.layout()
            if lay is not None:
                lay.activate()                              # 先排好位置才知道气泡在哪
            rect = QRect(b.mapTo(container, QPoint(0, 0)), b.size())
            if rect.width() <= 0 or rect.height() <= 0 or rect.height() > 1400:
                return False                                # 太高的(长图)直接显示
            pm = b.grab()
            if pm is None or pm.isNull():
                return False
        except RuntimeError:
            return False
        now = _now()
        self._streak = self._streak + 1 if now - self._last < 0.16 else 0
        self._last = now
        delay = min(self._streak, STAGGER_MAX) * STAGGER
        b.setUpdatesEnabled(False)                          # 动画期间先不画真气泡

        def done() -> None:
            try:
                b.setUpdatesEnabled(True)
                b.update()
            except RuntimeError:                            # 气泡已经被删了
                pass
            if g in self.ghosts:
                self.ghosts.remove(g)
            if on_done is not None:
                on_done()
        g = _Ghost(container, pm, rect, bool(getattr(b.msg, "mine", False)), self.mode, delay, done)
        self.ghosts.append(g)
        # 保险:不管动画出了什么事,过一会儿一定把真气泡放出来
        QTimer.singleShot(int((delay + DUR[self.mode]) * 1000) + 700, lambda: g.finish() if g.done_cb else None)
        return True

    def shatter(self, b, viewport: QWidget) -> bool:
        if not self.enabled() or b is None or viewport is None:
            return False
        try:
            if not b.isVisible():
                return False
            pm = b.grab()
            if pm is None or pm.isNull():
                return False
            rect = QRect(b.mapTo(viewport, QPoint(0, 0)), b.size())
        except RuntimeError:
            return False
        _Shatter(viewport, pm, rect)
        return True

    def wiggle(self, b) -> None:
        """@我:左右晃两下,整行亮一下。"""
        if not self.enabled() or b is None:
            return
        try:
            lay = b.layout()
            m = lay.contentsMargins()
        except RuntimeError:
            return
        left, top, right, bottom = m.left(), m.top(), m.right(), m.bottom()
        anim = QVariantAnimation(b)
        anim.setDuration(620)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.Linear)

        def step(v) -> None:
            off = int(round(math.sin(float(v) * math.pi * 4) * 7 * (1 - float(v))))
            try:
                lay.setContentsMargins(left + max(0, off), top, right + max(0, -off), bottom)
            except RuntimeError:
                pass
        anim.valueChanged.connect(step)
        anim.finished.connect(lambda: step(1.0))
        anim.start()
        b.wiggle_anim = anim
        try:
            b.flash()
        except RuntimeError:
            pass

    def react_pop(self, chip, emoji: str, container: QWidget, dark: bool) -> None:
        if not self.enabled() or chip is None or container is None:
            return
        try:
            c = chip.mapTo(container, chip.rect().center())
        except RuntimeError:
            return
        _ReactPop(container, c, emoji, dark)
