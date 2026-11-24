"""
密语 · 进群特效(2.5)。盖在聊天区上的一层透明画布(不挡鼠标):
  顶部滑进来一条横幅「小明 进群了」,头像"啵"地弹出来并炸开一圈光环;再配上进群的人自己选的登场效果:
  🎆 烟花 / 🌸 花瓣雨 / ✨ 星光 / ⚡ 闪电 / 🐾 宠物开路。
烟花、花瓣、星星这些满屏的粒子交给 EffectLayer;横幅、闪电、宠物开路在这里画。全部 QPainter 手绘。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import theme

TOTAL = 3.8
# 登场效果:id → (名字, 横幅渐变色 左, 右, 小图标)
FX = {
    "fireworks": ("烟花", "#FF8A3D", "#FF4F8B", "🎆"),
    "petals": ("花瓣雨", "#FF8FB1", "#C86DD7", "🌸"),
    "stars": ("星光", "#5B5BD6", "#9B6CFF", "✨"),
    "lightning": ("闪电", "#2A6CF0", "#18B5D8", "⚡"),
    "pet": ("宠物开路", "#F59F00", "#F76707", "🐾"),
}
FX_ORDER = ["fireworks", "petals", "stars", "lightning", "pet"]
FX_CHOICES = [(k, f"{FX[k][3]} {FX[k][0]}") for k in FX_ORDER] + [("off", "不放(安安静静进群)")]
BANNER_Y = 64                 # 横幅在聊天区里的高度(标题栏下面一点)


def _now() -> float:
    return time.monotonic()


def _ease_out(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return 1 - (1 - k) ** 3


def _back(k: float) -> float:
    k = max(0.0, min(1.0, k))
    c = 1.9
    return 1 + (c + 1) * (k - 1) ** 3 + c * (k - 1) ** 2


def bolt_points(x0: float, y0: float, x1: float, y1: float, rng: random.Random, n: int = 9) -> list[QPointF]:
    """一道闪电:从 (x0, y0) 折到 (x1, y1),中间每段左右乱偏。"""
    pts = [QPointF(x0, y0)]
    for i in range(1, n):
        k = i / n
        jitter = 26 * (1 - abs(0.5 - k))
        pts.append(QPointF(x0 + (x1 - x0) * k + rng.uniform(-jitter, jitter), y0 + (y1 - y0) * k))
    pts.append(QPointF(x1, y1))
    return pts


class EnterOverlay(QWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.t0 = -1e9
        self.fx = "stars"
        self.text = ""
        self.avatar = None             # QPixmap
        self.pet = None                # 宠物开路用的宠物图
        self.rng = random.Random()
        self.bolts: list[list[QPointF]] = []
        self.paws: list[tuple[float, float, float]] = []
        self.queue: list[tuple] = []    # 好几个人同时进群:一个一个来
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.hide()

    # ---- 对外
    def play(self, fx: str, text: str, avatar=None, pet=None) -> None:
        if self.active():
            if len(self.queue) < 4:
                self.queue.append((fx, text, avatar, pet))
            return
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())
        self.fx = fx if fx in FX else "stars"
        self.text, self.avatar, self.pet = text, avatar, pet
        self.t0 = _now()
        self.bolts, self.paws = [], []
        self.show()
        self.raise_()
        self.timer.start()

    def active(self) -> bool:
        return _now() - self.t0 < TOTAL

    def stop(self) -> None:
        self.queue.clear()
        self.timer.stop()
        self.t0 = -1e9
        self.hide()

    def _tick(self) -> None:
        if not self.active():
            if self.queue:
                self.t0 = -1e9
                self.play(*self.queue.pop(0))
                return
            self.stop()
            return
        t = _now() - self.t0
        if self.fx == "lightning" and 0.25 < t < 1.3 and (not self.bolts or self.rng.random() < 0.18):
            self._new_bolts()
        self.update()

    # ---- 横幅的位置
    def banner_rect(self, t: float) -> QRectF:
        f = self._font(11, True)
        tw = QFontMetrics(f).horizontalAdvance(self.text) + 28
        w = 52 + tw + 64
        h = 52.0
        cx = self.width() / 2
        if t < 0.5:                                          # 从左边滑进来,稍微冲过头再回来
            x = -w + (cx - w / 2 + w) * _back(t / 0.5)
        elif t > TOTAL - 0.5:                                # 往右滑出去
            x = cx - w / 2 + (self.width() - cx + w) * _ease_out((t - (TOTAL - 0.5)) / 0.5) ** 2
        else:
            x = cx - w / 2
        return QRectF(x, BANNER_Y, w, h)

    def _font(self, pt: float, bold: bool = False) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(pt)
        f.setBold(bold)
        return f

    def _new_bolts(self) -> None:
        r = self.banner_rect(0.6)
        self.bolts = []
        for _ in range(self.rng.choice((1, 2, 2, 3))):
            x0 = self.rng.uniform(r.left() - 80, r.right() + 80)
            self.bolts.append(bolt_points(x0, -10, self.rng.uniform(r.left() + 20, r.right() - 20), r.top() + 4,
                                          self.rng))

    # ---- 画
    def paintEvent(self, _e) -> None:
        t = _now() - self.t0
        if t < 0 or t > TOTAL:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.fx == "lightning":
            self._paint_lightning(p, t)
        if self.fx == "pet":
            self._paint_pet_run(p, t)
        r = self.banner_rect(t)
        fade = 1.0 if t < TOTAL - 0.35 else max(0.0, (TOTAL - t) / 0.35)
        p.setOpacity(fade)
        self._paint_banner(p, r, t)
        if self.fx == "stars":
            self._paint_twinkles(p, r, t)
        p.setOpacity(1.0)
        p.end()

    def _paint_banner(self, p: QPainter, r: QRectF, t: float) -> None:
        name, c1, c2, icon = FX[self.fx]
        # 影子(不用阴影特效:画两层半透明的圆角矩形)
        for i, a in ((6, 26), (3, 40)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(r.adjusted(-i / 2, i / 2 + 1, i / 2, i + 1), 26 + i / 2, 26 + i / 2)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, QColor(c1))
        g.setColorAt(1, QColor(c2))
        p.setBrush(g)
        p.drawRoundedRect(r, 26, 26)
        # 一道光从左扫到右
        k = (t - 0.55) / 0.9
        if 0 < k < 1:
            path = QPainterPath()
            path.addRoundedRect(r, 26, 26)
            p.save()
            p.setClipPath(path)
            sx = r.left() + (r.width() + 80) * k - 40
            sh = QLinearGradient(sx - 30, 0, sx + 30, 0)
            sh.setColorAt(0, QColor(255, 255, 255, 0))
            sh.setColorAt(0.5, QColor(255, 255, 255, 110))
            sh.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(sx - 30, r.top(), 60, r.height()), sh)
            p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 26, 26)
        # 头像:晚一点"啵"地弹出来
        ac = QPointF(r.left() + 30, r.center().y())
        s = _back((t - 0.2) / 0.45) if t > 0.2 else 0.0
        ring = (t - 0.35) / 0.6
        if 0 < ring < 1:                                     # 光环炸开
            p.setPen(QPen(QColor(255, 255, 255, int(200 * (1 - ring))), 3 * (1 - ring) + 0.5))
            rr = 20 + 26 * _ease_out(ring)
            p.drawEllipse(ac, rr, rr)
        if s > 0.01:
            d = 38 * s
            p.setPen(QPen(QColor(255, 255, 255), 2.5))
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawEllipse(ac, d / 2 + 1.5, d / 2 + 1.5)
            if self.avatar is not None and not self.avatar.isNull():
                clip = QPainterPath()
                clip.addEllipse(ac, d / 2, d / 2)
                p.save()
                p.setClipPath(clip)
                p.drawPixmap(QRectF(ac.x() - d / 2, ac.y() - d / 2, d, d), self.avatar,
                             QRectF(self.avatar.rect()))
                p.restore()
        # 文字
        p.setPen(QColor("#FFFFFF"))
        p.setFont(self._font(11, True))
        tx = r.left() + 58
        p.drawText(QRectF(tx, r.top() + 6, r.width() - 58 - 60, 24), int(Qt.AlignmentFlag.AlignVCenter), self.text)
        p.setFont(self._font(8.5))
        p.setPen(QColor(255, 255, 255, 215))
        p.drawText(QRectF(tx, r.top() + 27, r.width() - 58 - 60, 18), int(Qt.AlignmentFlag.AlignVCenter),
                   f"{name}登场")
        # 右边的小图标轻轻跳
        bob = math.sin(t * 7) * 2.5
        p.setFont(self._font(17))
        p.drawText(QRectF(r.right() - 54, r.top() + bob, 44, r.height()), int(Qt.AlignmentFlag.AlignCenter), icon)

    def _paint_twinkles(self, p: QPainter, r: QRectF, t: float) -> None:
        rng = random.Random(7)
        for i in range(14):
            ang = rng.uniform(0, math.tau)
            dist = rng.uniform(0.62, 1.1)
            x = r.center().x() + math.cos(ang) * r.width() * 0.62 * dist
            y = r.center().y() + math.sin(ang) * 46 * dist
            ph = rng.uniform(0, math.tau)
            a = max(0.0, math.sin(t * 5 + ph)) * min(1.0, t / 0.6)
            if a < 0.05:
                continue
            sz = rng.uniform(3, 6) * (0.6 + a * 0.6)
            pal = ("#FFE066", "#FFFFFF", "#D0BFFF") if theme.is_dark() else ("#F59F00", "#7950F2", "#FAB005")
            col = QColor(rng.choice(pal))
            col.setAlphaF(a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            star = QPainterPath()
            for j in range(8):
                rad = sz if j % 2 == 0 else sz * 0.32
                aa = j * math.pi / 4
                pt = QPointF(x + math.cos(aa) * rad, y + math.sin(aa) * rad)
                if j == 0:
                    star.moveTo(pt)
                else:
                    star.lineTo(pt)
            star.closeSubpath()
            p.drawPath(star)

    def _paint_lightning(self, p: QPainter, t: float) -> None:
        if 0.25 < t < 0.75:                                 # 一闪:整块区域亮一下
            a = int(70 * (1 - (t - 0.25) / 0.5))
            p.fillRect(self.rect(), QColor(200, 225, 255, a))
        if not (0.25 < t < 1.35) or not self.bolts:
            return
        fade = 1.0 if t < 1.1 else max(0.0, (1.35 - t) / 0.25)
        dark = theme.is_dark()
        layers = ((14, QColor(120, 190, 255, int(50 * fade))), (6, QColor(160, 215, 255, int(140 * fade))),
                  (2, QColor(255, 255, 255, int(255 * fade)))) if dark else \
            ((14, QColor(70, 130, 245, int(60 * fade))), (6, QColor(40, 110, 250, int(200 * fade))),
             (2, QColor(255, 255, 255, int(255 * fade))))
        for pts in self.bolts:
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            for width, col in layers:
                p.setPen(QPen(col, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)

    def _paint_pet_run(self, p: QPainter, t: float) -> None:
        """宠物从左边跑到右边,身后留下一串小脚印,横幅跟在后面。"""
        w = self.width()
        top = BANNER_Y + 62                                  # 在横幅下面跑,不被挡住
        size = 72.0
        feet = top + size - 4
        k = (t - 0.1) / 2.6
        if 0 <= k <= 1.05:
            x = -40 + (w + 80) * min(1.0, k)
            if not self.paws or x - self.paws[-1][0] > 36:
                self.paws.append((x - 14, feet + (5 if len(self.paws) % 2 else -1), t))
        for px, py, pt in self.paws:                        # 脚印慢慢淡掉
            a = max(0.0, 1 - (t - pt) / 1.4)
            if a <= 0:
                continue
            col = QColor("#C8873A")
            col.setAlphaF(0.55 * a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(px, py), 4.2, 3.4)
            for dx, dy in ((-4.5, -4.5), (0, -6.2), (4.5, -4.5)):
                p.drawEllipse(QPointF(px + dx, py + dy), 1.6, 1.6)
        if 0 <= k <= 1.0 and self.pet is not None and not self.pet.isNull():
            x = -40 + (w + 80) * k
            hop = abs(math.sin(t * 13)) * 7
            p.drawPixmap(QRectF(x - size / 2, top - hop, size, size), self.pet, QRectF(self.pet.rect()))
