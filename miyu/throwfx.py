"""
密语 · 扔东西特效(2.4)
盖在主窗口上的一层透明画布:道具沿抛物线飞到某个人的头像上,命中时炸开、溅汁、留下痕迹,
痕迹跟着头像走(滚动、换位置都跟得上),几秒后慢慢淡掉。被扔的人是自己时,还有一块"砸在屏幕上"的大特效。
全部用 QPainter 手绘,不用 QGraphicsEffect(2.1.1 起为了稳定不再用)。
只在密语窗口里画,窗口隐藏时自动停。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient, QTextOption
from PySide6.QtWidgets import QWidget

# (id, 名字, 量词, 菜单图标, 命中音效, 命中字)
ITEMS = [
    ("slipper", "拖鞋", "只", "🩴", "whack", "啪!"),
    ("tomato", "番茄", "个", "🍅", "splat", "噗!"),
    ("egg", "鸡蛋", "个", "🥚", "splat", "啪叽!"),
    ("bomb", "炸弹", "颗", "💣", "boom", "砰!"),
    ("snow", "雪球", "个", "⛄", "puff", "噗!"),
    ("rose", "玫瑰", "朵", "🌹", "chime", ""),
    ("heart", "爱心", "颗", "❤️", "chime", ""),
    ("cake", "蛋糕", "块", "🎂", "splat", "噗叽!"),
]
ITEM_BY_ID = {it[0]: it for it in ITEMS}
FRIENDLY = {"rose", "heart"}           # 送花送心:不算"扔",系统消息换个说法
STAIN_SECS = {"tomato": 4.6, "egg": 4.6, "cake": 4.8, "bomb": 3.6, "snow": 3.6, "slipper": 2.4, "rose": 2.4, "heart": 2.4}
FLIGHT = 0.62


def _now() -> float:
    return time.monotonic()


def _heart_path(r: float) -> QPainterPath:
    path = QPainterPath(QPointF(0, r * 0.95))
    path.cubicTo(-r * 1.25, r * 0.15, -r * 0.95, -r * 0.95, 0, -r * 0.38)
    path.cubicTo(r * 0.95, -r * 0.95, r * 1.25, r * 0.15, 0, r * 0.95)
    return path


def _star_path(r: float, inner: float = 0.45, n: int = 5) -> QPainterPath:
    path = QPainterPath()
    for i in range(n * 2):
        a = -math.pi / 2 + i * math.pi / n
        rr = r if i % 2 == 0 else r * inner
        pt = QPointF(math.cos(a) * rr, math.sin(a) * rr)
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    return path


def _blob(r: float, seed: int, lobes: int = 9, wild: float = 0.28) -> QPainterPath:
    """不规则的一摊(番茄汁、蛋清、奶油)。同一个 seed 每帧形状一样。"""
    rng = random.Random(seed)
    pts = []
    for i in range(lobes):
        a = i / lobes * math.tau
        rr = r * (1 + rng.uniform(-wild, wild))
        pts.append((a, rr))
    path = QPainterPath()
    for i, (a, rr) in enumerate(pts):
        a2, r2 = pts[(i + 1) % lobes]
        if a2 < a:
            a2 += math.tau
        mid = (a + a2) / 2
        bulge = max(rr, r2) * 1.18
        p0 = QPointF(math.cos(a) * rr, math.sin(a) * rr)
        if i == 0:
            path.moveTo(p0)
        path.quadTo(QPointF(math.cos(mid) * bulge, math.sin(mid) * bulge), QPointF(math.cos(a2) * r2, math.sin(a2) * r2))
    path.closeSubpath()
    return path


def _outline(c: str = "#3B2E2A", w: float = 1.4) -> QPen:
    pen = QPen(QColor(c), w)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def draw_item(p: QPainter, item: str, s: float, t: float = 0.0) -> None:
    """在原点画一个道具,s ≈ 半径。"""
    out = _outline(w=max(1.0, s * 0.07))
    if item == "slipper":
        sole = QPainterPath(QPointF(0, -s * 1.0))
        sole.cubicTo(s * 0.62, -s * 1.0, s * 0.62, -s * 0.2, s * 0.48, s * 0.3)
        sole.cubicTo(s * 0.4, s * 0.9, s * 0.25, s * 1.05, 0, s * 1.05)
        sole.cubicTo(-s * 0.25, s * 1.05, -s * 0.4, s * 0.9, -s * 0.48, s * 0.3)
        sole.cubicTo(-s * 0.62, -s * 0.2, -s * 0.62, -s * 1.0, 0, -s * 1.0)
        p.setPen(out)
        p.setBrush(QColor("#4DABF7"))
        p.drawPath(sole)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#A5D8FF"))
        inner = QPainterPath()
        inner.addEllipse(QPointF(0, -s * 0.15), s * 0.34, s * 0.62)
        p.drawPath(inner)
        strap = QPen(QColor("#FF6B6B"), s * 0.2)
        strap.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(strap)
        p.drawLine(QPointF(0, -s * 0.62), QPointF(-s * 0.46, s * 0.05))
        p.drawLine(QPointF(0, -s * 0.62), QPointF(s * 0.46, s * 0.05))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFD43B"))
        p.drawEllipse(QPointF(0, -s * 0.62), s * 0.11, s * 0.11)
    elif item == "tomato":
        p.setPen(_outline("#A61E1E", max(1.0, s * 0.06)))
        p.setBrush(QColor("#FA5252"))
        p.drawEllipse(QPointF(0, s * 0.08), s * 0.86, s * 0.78)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawEllipse(QPointF(-s * 0.36, -s * 0.12), s * 0.18, s * 0.12)
        p.setPen(_outline("#2B8A3E", max(1.0, s * 0.05)))
        p.setBrush(QColor("#51CF66"))
        p.save()
        p.translate(0, -s * 0.62)
        p.drawPath(_star_path(s * 0.36, 0.4))
        p.restore()
        p.drawLine(QPointF(0, -s * 0.66), QPointF(s * 0.06, -s * 0.95))
    elif item == "egg":
        p.setPen(_outline("#B89B72", max(1.0, s * 0.06)))
        p.setBrush(QColor("#FFF8E7"))
        egg = QPainterPath(QPointF(0, -s * 0.95))
        egg.cubicTo(s * 0.62, -s * 0.95, s * 0.78, s * 0.2, s * 0.7, s * 0.45)
        egg.cubicTo(s * 0.58, s * 0.95, -s * 0.58, s * 0.95, -s * 0.7, s * 0.45)
        egg.cubicTo(-s * 0.78, s * 0.2, -s * 0.62, -s * 0.95, 0, -s * 0.95)
        p.drawPath(egg)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 200))
        p.drawEllipse(QPointF(-s * 0.25, -s * 0.35), s * 0.13, s * 0.22)
    elif item == "bomb":
        p.setPen(_outline("#111111", max(1.0, s * 0.06)))
        p.setBrush(QColor("#343A40"))
        p.drawEllipse(QPointF(0, s * 0.12), s * 0.78, s * 0.78)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 80))
        p.drawEllipse(QPointF(-s * 0.3, -s * 0.15), s * 0.2, s * 0.14)
        p.setBrush(QColor("#868E96"))
        p.drawRoundedRect(QRectF(-s * 0.2, -s * 0.8, s * 0.4, s * 0.26), s * 0.06, s * 0.06)
        fuse = QPainterPath(QPointF(0, -s * 0.8))
        fuse.quadTo(s * 0.1, -s * 1.15, s * 0.42, -s * 1.12)
        p.setPen(QPen(QColor("#C9A27A"), max(1.0, s * 0.08)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(fuse)
        flick = 0.75 + 0.25 * math.sin(t * 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.save()
        p.translate(s * 0.44, -s * 1.13)
        p.rotate(t * 500)
        p.setBrush(QColor("#FFA94D"))
        p.drawPath(_star_path(s * 0.3 * flick, 0.4, 6))
        p.setBrush(QColor("#FFF3BF"))
        p.drawPath(_star_path(s * 0.15 * flick, 0.45, 6))
        p.restore()
    elif item == "snow":
        g = QRadialGradient(QPointF(-s * 0.25, -s * 0.25), s * 1.1)
        g.setColorAt(0, QColor("#FFFFFF"))
        g.setColorAt(1, QColor("#C5DFF8"))
        p.setPen(_outline("#8DB3D9", max(1.0, s * 0.05)))
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), s * 0.8, s * 0.8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(173, 206, 237, 160))
        for dx, dy, r in ((0.3, 0.25, 0.1), (-0.2, 0.4, 0.07), (0.42, -0.15, 0.06)):
            p.drawEllipse(QPointF(s * dx, s * dy), s * r, s * r)
    elif item == "rose":
        stem = QPen(QColor("#2F9E44"), max(1.2, s * 0.1))
        stem.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(stem)
        p.drawLine(QPointF(0, s * 0.1), QPointF(s * 0.12, s * 1.1))
        p.setPen(_outline("#2B8A3E", max(1.0, s * 0.04)))
        p.setBrush(QColor("#51CF66"))
        leaf = QPainterPath(QPointF(s * 0.07, s * 0.62))
        leaf.quadTo(s * 0.55, s * 0.4, s * 0.6, s * 0.7)
        leaf.quadTo(s * 0.35, s * 0.82, s * 0.07, s * 0.62)
        p.drawPath(leaf)
        p.setPen(_outline("#A61E4D", max(1.0, s * 0.05)))
        p.setBrush(QColor("#E03131"))
        p.drawEllipse(QPointF(0, -s * 0.2), s * 0.55, s * 0.5)
        p.setBrush(QColor("#F03E3E"))
        for k in range(3):
            a = k * 2.1 + 0.4
            p.drawEllipse(QPointF(math.cos(a) * s * 0.18, -s * 0.24 + math.sin(a) * s * 0.14), s * 0.24, s * 0.2)
        p.setPen(QPen(QColor("#A61E4D"), max(1.0, s * 0.05)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        swirl = QPainterPath(QPointF(-s * 0.1, -s * 0.22))
        swirl.quadTo(0, -s * 0.38, s * 0.12, -s * 0.22)
        swirl.quadTo(s * 0.05, -s * 0.1, -s * 0.05, -s * 0.16)
        p.drawPath(swirl)
    elif item == "heart":
        p.setPen(_outline("#C2255C", max(1.0, s * 0.06)))
        p.setBrush(QColor("#FF6B8A"))
        p.drawPath(_heart_path(s * 0.9))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 150))
        p.drawEllipse(QPointF(-s * 0.38, -s * 0.3), s * 0.16, s * 0.11)
    elif item == "cake":                                    # 奶油派:一个圆盘子,上面堆满奶油
        p.setPen(_outline("#B07A3A", max(1.0, s * 0.06)))
        p.setBrush(QColor("#E8B97A"))
        p.drawEllipse(QPointF(0, s * 0.25), s * 0.95, s * 0.5)
        p.setPen(_outline("#D6C7B5", max(1.0, s * 0.05)))
        p.setBrush(QColor("#FFFDF7"))
        cream = QPainterPath(QPointF(-s * 0.85, s * 0.2))
        for k in range(6):
            x0 = -s * 0.85 + k * s * 0.34
            cream.quadTo(QPointF(x0 + s * 0.17, -s * 0.45 - (k % 2) * s * 0.15), QPointF(x0 + s * 0.34, s * 0.12))
        cream.quadTo(QPointF(0, s * 0.45), QPointF(-s * 0.85, s * 0.2))
        p.drawPath(cream)
        p.setPen(Qt.PenStyle.NoPen)
        for k, col in enumerate(("#FF8FAB", "#74C0FC", "#FFD43B", "#63E6BE", "#FF8FAB")):
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(-s * 0.55 + k * s * 0.26, -s * 0.05 - (k % 2) * s * 0.12, s * 0.14, s * 0.06), 1, 1)
        p.setPen(_outline("#A61E1E", max(1.0, s * 0.04)))
        p.setBrush(QColor("#E03131"))
        p.drawEllipse(QPointF(s * 0.05, -s * 0.5), s * 0.17, s * 0.17)


def paint_stain(p: QPainter, item: str, x: float, y: float, r: float, seed: int, t: float, a: float = 1.0) -> None:
    """头像上的痕迹:番茄汁、蛋黄、奶油、熏黑、雪帽、拖鞋印、粉色光晕。t = 命中后过了几秒,a = 不透明度。"""
    rng = random.Random(seed)
    pop = min(1.0, t / 0.12)
    p.save()
    p.setOpacity(a)
    p.translate(x, y)
    if item == "tomato":
        p.scale(pop, pop)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(224, 49, 49, 215))
        p.drawPath(_blob(r * 0.95, seed, 10, 0.32))
        p.setBrush(QColor(201, 42, 42, 230))
        p.drawPath(_blob(r * 0.5, seed + 1, 7, 0.3).translated(r * 0.1, -r * 0.05))
        p.setBrush(QColor(255, 232, 163, 230))
        for _ in range(5):
            p.drawEllipse(QPointF(rng.uniform(-r * 0.6, r * 0.6), rng.uniform(-r * 0.5, r * 0.5)), 1.6, 1.0)
        for i in range(4):                         # 往下流的番茄汁
            dx = rng.uniform(-r * 0.7, r * 0.7)
            ln = min(r * 1.3, t * rng.uniform(8, 20))
            p.setBrush(QColor(224, 49, 49, 210))
            p.drawRoundedRect(QRectF(dx - 2.2, r * 0.5, 4.4, r * 0.3 + ln), 2.2, 2.2)
            p.drawEllipse(QPointF(dx, r * 0.8 + ln), 3.0, 3.4)
    elif item == "egg":
        p.scale(pop, pop)
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.setBrush(QColor(255, 255, 255, 175))
        p.drawPath(_blob(r * 1.0, seed, 9, 0.3))
        slide = min(r * 0.5, t * 6)
        p.setPen(QPen(QColor("#E8A200"), 1))
        p.setBrush(QColor("#FFC72C"))
        p.drawEllipse(QPointF(-r * 0.1, -r * 0.1 + slide), r * 0.38, r * 0.34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 170))
        p.drawEllipse(QPointF(-r * 0.22, -r * 0.22 + slide), r * 0.1, r * 0.07)
        p.setBrush(QColor(255, 199, 44, 200))
        ln = min(r * 1.1, t * 10)
        p.drawRoundedRect(QRectF(-r * 0.1 - 2, slide + r * 0.2, 4, ln), 2, 2)
    elif item == "cake":
        slide = min(r * 0.4, t * 5)
        p.translate(0, slide)
        p.scale(pop, pop)
        p.setPen(QPen(QColor("#E9DCC9"), 1))
        p.setBrush(QColor(255, 253, 247, 240))
        p.drawPath(_blob(r * 1.08, seed, 11, 0.26))
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(9):
            p.setBrush(QColor(rng.choice(("#FF8FAB", "#74C0FC", "#FFD43B", "#63E6BE"))))
            p.save()
            p.translate(rng.uniform(-r * 0.7, r * 0.7), rng.uniform(-r * 0.6, r * 0.6))
            p.rotate(rng.uniform(0, 180))
            p.drawRoundedRect(QRectF(-3, -1, 6, 2), 1, 1)
            p.restore()
        p.setBrush(QColor("#E03131"))
        p.drawEllipse(QPointF(r * 0.15, -r * 0.55), 4.5, 4.5)
        p.setBrush(QColor(255, 255, 255, 160))
        p.drawEllipse(QPointF(r * 0.15 - 1.3, -r * 0.55 - 1.4), 1.3, 1.3)
    elif item == "bomb":                           # 熏黑:一团黑灰,眨两只白眼睛,头顶冒烟
        g = QRadialGradient(QPointF(0, 0), r * 1.15)
        g.setColorAt(0, QColor(30, 30, 30, 220))
        g.setColorAt(0.75, QColor(40, 40, 40, 170))
        g.setColorAt(1, QColor(40, 40, 40, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), r * 1.15, r * 1.15)
        blink = (t % 1.6) < 0.12
        p.setBrush(QColor("#FFFFFF"))
        for sx in (-1, 1):
            if blink:
                p.drawRoundedRect(QRectF(sx * r * 0.3 - 4, -r * 0.12, 8, 1.6), 0.8, 0.8)
            else:
                p.drawEllipse(QPointF(sx * r * 0.3, -r * 0.1), 3.4, 4.2)
        p.setBrush(QColor(110, 110, 110, 120))
        for i in range(3):
            ph = (t * 0.7 + i / 3) % 1.0
            p.drawEllipse(QPointF(math.sin(ph * 6 + i) * 4 + (i - 1) * 6, -r - ph * 26), 3 + ph * 5, 3 + ph * 5)
    elif item == "snow":                           # 头顶堆一顶小雪帽
        p.scale(pop, pop)
        p.setPen(QPen(QColor("#A5C8E8"), 1))
        p.setBrush(QColor("#FFFFFF"))
        cap = QPainterPath(QPointF(-r * 1.0, -r * 0.35))
        cap.cubicTo(-r * 0.9, -r * 1.2, r * 0.9, -r * 1.25, r * 1.0, -r * 0.35)
        for i in range(5):
            x0 = r * 1.0 - (i + 1) * r * 0.4
            cap.quadTo(QPointF(x0 + r * 0.2, -r * (0.05 if i % 2 else 0.2)), QPointF(x0, -r * 0.35))
        p.drawPath(cap)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(220, 236, 250, 220))
        for i in range(4):
            ph = (t * 0.5 + i / 4) % 1.0
            p.drawEllipse(QPointF((i - 1.5) * r * 0.5, -r * 0.3 + ph * r * 1.6), 1.8, 1.8)
    elif item == "slipper":                        # 脸上留一个拖鞋印,头顶转星星
        p.save()
        p.rotate(-25)
        p.setOpacity(a * 0.45)
        sole = QPainterPath()
        sole.addRoundedRect(QRectF(-r * 0.35, -r * 0.75, r * 0.7, r * 1.5), r * 0.35, r * 0.35)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FF6B6B"))
        p.drawPath(sole)
        p.restore()
        if t < 1.8:
            for i in range(3):
                ang = t * 5 + i * math.tau / 3
                p.save()
                p.translate(math.cos(ang) * r * 0.9, -r * 0.95 + math.sin(ang) * r * 0.25)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#FFD43B"))
                p.drawPath(_star_path(5, 0.45))
                p.restore()
    elif item in ("rose", "heart"):                # 被送花 / 送心:头像周围一圈粉色光晕,两颊冒小爱心
        g = QRadialGradient(QPointF(0, 0), r * 1.6)
        g.setColorAt(0.55, QColor(255, 143, 171, 0))
        g.setColorAt(0.75, QColor(255, 143, 171, int(110 * (0.6 + 0.4 * math.sin(t * 6)))))
        g.setColorAt(1, QColor(255, 143, 171, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), r * 1.6, r * 1.6)
        for i in range(2):
            ph = (t * 0.8 + i * 0.5) % 1.0
            p.save()
            p.setOpacity(a * (1 - ph))
            p.translate((i * 2 - 1) * r * 0.8, -r * 0.6 - ph * 18)
            p.setBrush(QColor("#FF6B8A"))
            p.drawPath(_heart_path(4.5))
            p.restore()
    p.restore()


class _Part:
    __slots__ = ("x", "y", "vx", "vy", "life", "ttl", "kind", "color", "size", "rot", "vr", "grav", "drag", "grow")

    def __init__(self, x, y, vx, vy, ttl, kind, color, size, rot=0.0, vr=0.0, grav=0.0, drag=0.0, grow=0.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.ttl = ttl
        self.kind, self.color, self.size = kind, color, size
        self.rot, self.vr, self.grav, self.drag, self.grow = rot, vr, grav, drag, grow


class ThrowLayer(QWidget):
    """anchor_fn(pid) -> (QPointF 中心, 半径) 或 None;screen_fn() -> 聊天区 QRectF(自己被砸时画大特效的地方)。
    ghost_fn(pid) -> 头像 QPixmap(找不到这个人的头像时,在聊天区上方临时浮出一个)。"""

    def __init__(self, parent, anchor_fn, screen_fn, ghost_fn=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.anchor_fn, self.screen_fn, self.ghost_fn = anchor_fn, screen_fn, ghost_fn
        self.flying: list[dict] = []
        self.stains: list[dict] = []
        self.parts: list[_Part] = []
        self.texts: list[dict] = []
        self.screens: list[dict] = []
        self.ghosts: dict[str, dict] = {}
        self.stages: list[dict] = []
        self._stage_n = 0
        self.on_hit = None                      # 命中时回调 (item, dst_pid, big)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._step)
        self._last = _now()
        self.frames = 0
        self.hits = 0
        self.hide()

    # ---------------------------------------------------------------- 外部调用
    def busy(self) -> bool:
        return bool(self.flying or self.stains or self.parts or self.texts or self.screens or self.ghosts or self.stages)

    def stage(self, item: str, frm_pm, to_pm, frm_name: str, to_name: str, combo: int = 1, big: bool = False) -> bool:
        """在聊天区正中间放大播放一遍:左边扔的人、右边被扔的人,道具飞过去砸中。"""
        if item not in ITEM_BY_ID:
            return False
        sr = self.screen_fn() if self.screen_fn else QRectF(self.rect())
        now = _now()
        self._stage_n += 1
        key = f"stage{self._stage_n}"
        gap = max(110.0, min(170.0, sr.width() * 0.26))
        cx, cy = sr.center().x(), sr.top() + sr.height() * 0.42
        a, b = key + ":a", key + ":b"
        self.ghosts[a] = {"pos": QPointF(cx - gap, cy), "r": 34.0, "pm": frm_pm, "t0": now, "until": now + 2.4,
                          "name": frm_name}
        self.ghosts[b] = {"pos": QPointF(cx + gap, cy), "r": 34.0, "pm": to_pm, "t0": now, "until": now + 2.4,
                          "name": to_name}
        self.stages.append({"key": key, "x": cx, "y": cy, "w": gap * 2 + 150, "h": 190, "t0": now, "item": item})
        self._wake()
        return self.launch(item, a, b, big=big, combo=combo, size=24, arc=62.0)

    def launch(self, item: str, src_pid: str | None, dst_pid: str, big: bool = False, combo: int = 1,
               from_bottom: bool = False, size: float | None = None, arc: float | None = None) -> bool:
        if item not in ITEM_BY_ID:
            return False
        dst = self._anchor(dst_pid, ghost=True)
        if dst is None:
            return False
        src = self._anchor(src_pid, ghost=False) if src_pid else None
        if src is None:
            r = self.rect()
            sr = self.screen_fn() if self.screen_fn else QRectF(r)
            if from_bottom:                           # 自己扔的:从输入框那边飞出去
                src = (QPointF(sr.center().x() + random.uniform(-60, 60), sr.bottom() - 30), 0)
            else:                                     # 别人扔的但看不到他的头像:从聊天区的一侧飞进来
                side = random.choice((-1, 1))
                x = sr.left() - 20 if side < 0 else sr.right() + 20
                src = (QPointF(x, sr.top() + sr.height() * random.uniform(0.25, 0.6)), 0)
        p0 = src[0]
        dist = math.hypot(dst[0].x() - p0.x(), dst[0].y() - p0.y())
        self.flying.append({"item": item, "src": QPointF(p0), "dst": dst_pid, "t0": _now(),
                            "dur": FLIGHT + min(0.35, dist / 2200), "big": big, "combo": max(1, int(combo)),
                            "last": QPointF(dst[0]), "arc": arc if arc is not None else min(160.0, 50 + dist * 0.28),
                            "spin": random.choice((-1, 1)) * random.uniform(540, 900), "size": size})
        self._wake()
        return True

    def clear(self) -> None:
        self.flying.clear()
        self.stains.clear()
        self.parts.clear()
        self.texts.clear()
        self.screens.clear()
        self.ghosts.clear()
        self.stages.clear()
        self.timer.stop()
        self.hide()

    # ---------------------------------------------------------------- 内部
    def _anchor(self, pid: str | None, ghost: bool) -> tuple[QPointF, float] | None:
        if not pid:
            return None
        g = self.ghosts.get(pid)
        if g is not None:
            return g["pos"], g["r"]
        try:
            a = self.anchor_fn(pid)
        except Exception:                               # noqa: BLE001
            a = None
        if a is not None:
            return a
        if not ghost or self.ghost_fn is None:
            return None
        sr = self.screen_fn() if self.screen_fn else QRectF(self.rect())
        n = len(self.ghosts)
        pos = QPointF(sr.center().x() + (n % 3 - 1) * 90, sr.top() + 120 + (n // 3) * 90)
        try:
            pm = self.ghost_fn(pid)
        except Exception:                               # noqa: BLE001
            pm = None
        self.ghosts[pid] = {"pos": pos, "r": 26.0, "pm": pm, "t0": _now(), "until": _now() + 1.5}
        return pos, 26.0

    def _wake(self) -> None:
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())
        self.show()
        self.raise_()
        self._last = _now()
        if not self.timer.isActive():
            self.timer.start()

    def _step(self) -> None:
        now = _now()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        self.frames += 1
        for f in list(self.flying):
            a = self._anchor(f["dst"], ghost=True)
            if a is not None:
                f["last"] = QPointF(a[0])
            if now - f["t0"] >= f["dur"]:
                self.flying.remove(f)
                self._hit(f, a[1] if a else 22.0)
        for s in self.stains:
            a = self._anchor(s["pid"], ghost=False) if s["pid"] not in self.ghosts else None
            if a is not None:
                s["pos"], s["r"] = QPointF(a[0]), a[1]
        self.stains = [s for s in self.stains if now - s["t0"] < s["ttl"]]
        alive = []
        for q in self.parts:
            q.life -= dt
            if q.life <= 0:
                continue
            q.vy += q.grav * dt
            if q.drag:
                k = max(0.0, 1 - q.drag * dt)
                q.vx *= k
                q.vy *= k
            q.x += q.vx * dt
            q.y += q.vy * dt
            q.rot += q.vr * dt
            q.size += q.grow * dt
            alive.append(q)
        self.parts = alive
        self.texts = [t for t in self.texts if now - t["t0"] < t["ttl"]]
        self.screens = [s for s in self.screens if now - s["t0"] < s["ttl"]]
        busy_pids = {f["dst"] for f in self.flying} | {s["pid"] for s in self.stains}
        for pid in list(self.ghosts):
            g = self.ghosts[pid]
            if pid in busy_pids:
                g["until"] = max(g["until"], now + 0.6)
            elif now > g["until"]:
                del self.ghosts[pid]
        for st in self.stages:                          # 舞台跟着两边的头像一起淡出
            a, b = self.ghosts.get(st["key"] + ":a"), self.ghosts.get(st["key"] + ":b")
            if a is not None and b is not None and b["until"] > a["until"]:
                a["until"] = b["until"]
        self.stages = [st for st in self.stages if (st["key"] + ":b") in self.ghosts or (st["key"] + ":a") in self.ghosts]
        if not self.busy():
            self.timer.stop()
            self.hide()
            return
        self.update()

    def _hit(self, f: dict, r: float) -> None:
        item, pos, big = f["item"], QPointF(f["last"]), f["big"]
        now = _now()
        self.hits += 1
        x, y = pos.x(), pos.y()
        seed = random.randrange(1 << 30)
        self.stains.append({"item": item, "pid": f["dst"], "pos": pos, "r": r, "t0": now,
                            "ttl": STAIN_SECS.get(item, 3.0), "seed": seed})
        rnd = random.uniform
        add = self.parts.append
        if item == "tomato":
            for _ in range(16):
                a = rnd(0, math.tau)
                sp = rnd(90, 260)
                add(_Part(x, y, math.cos(a) * sp, math.sin(a) * sp - 40, rnd(0.4, 0.8), "drop", "#F03E3E",
                          rnd(2.2, 4.5), grav=520, drag=1.5))
            for _ in range(5):
                add(_Part(x, y, rnd(-60, 60), rnd(-120, -40), rnd(0.5, 0.9), "seed", "#FFE8A3", rnd(1.4, 2.0), grav=420))
        elif item == "egg":
            for _ in range(9):
                a = rnd(-math.pi, 0)
                sp = rnd(100, 230)
                add(_Part(x, y, math.cos(a) * sp, math.sin(a) * sp, rnd(0.6, 1.0), "shell", "#FFF8E7", rnd(3.5, 6),
                          rot=rnd(0, 360), vr=rnd(-600, 600), grav=600))
            for _ in range(8):
                a = rnd(0, math.tau)
                add(_Part(x, y, math.cos(a) * rnd(60, 160), math.sin(a) * rnd(60, 160), rnd(0.4, 0.7), "drop",
                          "#FFC72C", rnd(2, 3.5), grav=500))
        elif item == "cake":
            for _ in range(12):
                a = rnd(0, math.tau)
                sp = rnd(80, 220)
                add(_Part(x, y, math.cos(a) * sp, math.sin(a) * sp - 30, rnd(0.5, 0.9), "drop", "#FFFDF7",
                          rnd(3, 5.5), grav=480, drag=1.2))
            for _ in range(10):
                a = rnd(0, math.tau)
                add(_Part(x, y, math.cos(a) * rnd(100, 220), math.sin(a) * rnd(100, 220), rnd(0.6, 1.0), "sprinkle",
                          random.choice(("#FF8FAB", "#74C0FC", "#FFD43B", "#63E6BE")), rnd(2.5, 3.5),
                          rot=rnd(0, 360), vr=rnd(-500, 500), grav=500))
        elif item == "bomb":
            add(_Part(x, y, 0, 0, 0.45, "ring", "#FFA94D", r * 0.6, grow=r * 7))
            add(_Part(x, y, 0, 0, 0.25, "flash", "#FFF3BF", r * 1.3, grow=r * 4))
            for _ in range(18):
                a = rnd(0, math.tau)
                sp = rnd(150, 380)
                add(_Part(x, y, math.cos(a) * sp, math.sin(a) * sp, rnd(0.3, 0.6), "spark",
                          random.choice(("#FFD43B", "#FFA94D", "#FF6B6B")), rnd(2, 3.5), drag=2.5))
            for _ in range(9):
                a = rnd(0, math.tau)
                add(_Part(x + math.cos(a) * r * 0.5, y + math.sin(a) * r * 0.5, math.cos(a) * rnd(20, 60),
                          math.sin(a) * rnd(20, 60) - 30, rnd(0.9, 1.5), "smoke", "#495057", rnd(8, 13), grow=18))
        elif item == "snow":
            for _ in range(20):
                a = rnd(0, math.tau)
                sp = rnd(80, 240)
                add(_Part(x, y, math.cos(a) * sp, math.sin(a) * sp - 30, rnd(0.5, 1.0), "drop", "#FFFFFF",
                          rnd(2, 4.2), grav=360, drag=1.4))
            for _ in range(6):
                add(_Part(x + rnd(-r, r), y - r, rnd(-20, 20), rnd(20, 50), rnd(1.2, 2.0), "flake", "#E7F5FF",
                          rnd(3, 4.5), rot=rnd(0, 60), vr=rnd(-90, 90)))
        elif item == "slipper":
            add(_Part(x, y, rnd(-120, -60) if f["src"].x() > x else rnd(60, 120), -260, 1.0, "item:slipper", "",
                      r * 0.62, rot=0, vr=-f["spin"] * 0.8, grav=900))
            add(_Part(x, y, 0, 0, 0.3, "burst", "#FFFFFF", r * 1.05, grow=r * 2.5))
            for _ in range(6):
                a = rnd(0, math.tau)
                add(_Part(x, y, math.cos(a) * 70, math.sin(a) * 70, rnd(0.4, 0.7), "smoke", "#CED4DA", rnd(5, 7),
                          grow=14))
        elif item == "rose":
            for _ in range(14):
                add(_Part(x + rnd(-r, r) * 0.5, y + rnd(-r, r) * 0.5, rnd(-90, 90), rnd(-160, -40), rnd(1.4, 2.2),
                          "petal", random.choice(("#E03131", "#F03E3E", "#FA5252", "#C92A2A")), rnd(3.5, 5.5),
                          rot=rnd(0, 360), vr=rnd(-200, 200), grav=110, drag=1.6))
        elif item == "heart":
            for k in range(10):
                a = k / 10 * math.tau
                add(_Part(x, y, math.cos(a) * 120, math.sin(a) * 120 - 20, rnd(0.9, 1.4), "heart",
                          random.choice(("#FF6B8A", "#FF8FAB", "#F06595")), rnd(4, 6.5), drag=2.2, grav=-60))
        word = ITEM_BY_ID[item][5]
        if word:
            self.texts.append({"text": word, "x": x + random.uniform(-6, 6), "y": y - r - 14, "t0": now, "ttl": 0.9,
                               "color": "#FFFFFF", "size": 17 + (5 if big else 0)})
        if f["combo"] > 1:
            self.texts.append({"text": f"×{f['combo']}", "x": x + r + 18, "y": y - r * 0.4, "t0": now, "ttl": 1.2,
                               "color": "#FFD43B", "size": 15 + min(f["combo"], 12)})
        if big:
            self._screen_hit(item)
        if self.on_hit is not None:
            try:
                self.on_hit(item, f["dst"], big)
            except Exception:                           # noqa: BLE001
                pass

    def _screen_hit(self, item: str) -> None:
        """砸到自己:聊天区上糊一大块(番茄、蛋、奶油、雪)、炸弹闪光 + 熏黑的边、拖鞋印、花瓣雨、爱心飘。"""
        sr = self.screen_fn() if self.screen_fn else QRectF(self.rect())
        now = _now()
        cx = sr.left() + sr.width() * random.uniform(0.3, 0.7)
        cy = sr.top() + sr.height() * random.uniform(0.3, 0.55)
        self.screens.append({"item": item, "x": cx, "y": cy, "t0": now, "ttl": 3.4 if item in ("rose", "heart") else 3.8,
                             "seed": random.randrange(1 << 30), "r": min(110.0, min(sr.width(), sr.height()) * 0.16)})
        if item == "rose":
            for _ in range(36):
                self.parts.append(_Part(random.uniform(sr.left(), sr.right()), sr.top() - random.uniform(0, 160),
                                        random.uniform(-30, 30), random.uniform(60, 130), random.uniform(2.6, 3.6),
                                        "petal", random.choice(("#E03131", "#F03E3E", "#FA5252")), random.uniform(4, 7),
                                        rot=random.uniform(0, 360), vr=random.uniform(-160, 160)))
        elif item == "heart":
            for _ in range(26):
                self.parts.append(_Part(random.uniform(sr.left(), sr.right()), sr.bottom() + random.uniform(0, 120),
                                        random.uniform(-20, 20), random.uniform(-150, -80), random.uniform(2.5, 3.5),
                                        "heart", random.choice(("#FF6B8A", "#FF8FAB", "#F06595")), random.uniform(6, 11)))

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, _e) -> None:
        if not self.busy():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        now = _now()
        for s in self.screens:
            self._paint_screen(p, s, now)
        for st in self.stages:
            self._paint_stage(p, st, now)
        for pid, g in self.ghosts.items():
            self._paint_ghost(p, g, now)
        for s in self.stains:
            self._paint_stain(p, s, now)
        for f in self.flying:
            self._paint_flying(p, f, now)
        for q in self.parts:
            self._paint_part(p, q)
        for t in self.texts:
            self._paint_text(p, t, now)
        p.end()

    def _paint_stage(self, p: QPainter, st: dict, now: float) -> None:
        g = self.ghosts.get(st["key"] + ":b") or self.ghosts.get(st["key"] + ":a")
        if g is None:
            return
        t = now - st["t0"]
        a = min(1.0, t / 0.2, max(0.0, (g["until"] - now) / 0.4))
        k = min(1.0, t / 0.3)
        sc = 0.9 + 0.1 * (1 - (1 - k) ** 3)
        p.save()
        p.setOpacity(max(0.0, a))
        p.translate(st["x"], st["y"])
        p.scale(sc, sc)
        r = QRectF(-st["w"] / 2, -st["h"] / 2 + 6, st["w"], st["h"])
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(18, 14, 28, 175))
        p.drawRoundedRect(r, 26, 26)
        p.restore()

    def _paint_ghost(self, p: QPainter, g: dict, now: float) -> None:
        t = now - g["t0"]
        a = min(1.0, t / 0.2, max(0.0, (g["until"] - now) / 0.4))
        k = min(1.0, t / 0.25)
        scale = 0.6 + 0.4 * (1 - (1 - k) ** 3)
        r = g["r"] * scale
        p.save()
        p.setOpacity(max(0.0, a))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QPointF(g["pos"].x(), g["pos"].y() + 3), r + 4, r + 4)
        pm = g.get("pm")
        if pm is not None:
            p.drawPixmap(QRectF(g["pos"].x() - r, g["pos"].y() - r, r * 2, r * 2), pm, QRectF(pm.rect()))
        else:
            p.setBrush(QColor("#7C5CFF"))
            p.drawEllipse(g["pos"], r, r)
        p.setPen(QPen(QColor(255, 255, 255, 220), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(g["pos"], r + 1, r + 1)
        if g.get("name"):
            f = QFont(self.font())
            f.setPixelSize(13)
            f.setWeight(QFont.Weight.Bold)
            p.setFont(f)
            nr = QRectF(g["pos"].x() - 80, g["pos"].y() + r + 8, 160, 20)
            p.setPen(QColor(0, 0, 0, 160))
            p.drawText(nr.translated(0, 1), g["name"], QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.setPen(QColor("#FFFFFF"))
            p.drawText(nr, g["name"], QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.restore()

    def _paint_flying(self, p: QPainter, f: dict, now: float) -> None:
        k = min(1.0, (now - f["t0"]) / f["dur"])
        e = k                                         # 匀速前进,高度走抛物线,看起来像真的扔过去
        x = f["src"].x() + (f["last"].x() - f["src"].x()) * e
        y = f["src"].y() + (f["last"].y() - f["src"].y()) * e - f["arc"] * 4 * k * (1 - k)
        size = (f.get("size") or (15 if not f["big"] else 18)) * (0.85 + 0.35 * math.sin(math.pi * k))
        p.save()
        p.setPen(Qt.PenStyle.NoPen)                   # 地上的影子(沿直线走)
        sx = f["src"].x() + (f["last"].x() - f["src"].x()) * e
        sy = f["src"].y() + (f["last"].y() - f["src"].y()) * e
        p.setBrush(QColor(0, 0, 0, int(50 * (1 - 0.6 * math.sin(math.pi * k)))))
        p.drawEllipse(QPointF(sx, sy + 6), size * 0.7, size * 0.22)
        if f["item"] in ("tomato", "egg", "snow", "cake", "bomb"):     # 速度线
            p.setPen(QPen(QColor(255, 255, 255, 70), 2))
            dx = f["last"].x() - f["src"].x()
            for i in range(3):
                off = (i - 1) * 5
                p.drawLine(QPointF(x - math.copysign(14 + i * 4, dx), y + off), QPointF(x - math.copysign(26 + i * 6, dx), y + off))
        p.translate(x, y)
        if f["item"] in ("slipper", "cake", "rose"):
            p.rotate(f["spin"] * (now - f["t0"]))
        elif f["item"] != "heart":
            p.rotate(f["spin"] * 0.35 * (now - f["t0"]))
        draw_item(p, f["item"], size, now - f["t0"])
        p.restore()

    def _paint_part(self, p: QPainter, q: _Part) -> None:
        a = max(0.0, min(1.0, q.life / q.ttl * 1.6))
        if q.kind in ("ring", "flash", "burst"):
            a = max(0.0, q.life / q.ttl)
        c = QColor(q.color) if q.color else QColor("#FFFFFF")
        p.save()
        p.setOpacity(a)
        p.translate(q.x, q.y)
        k = q.kind
        if k == "drop" or k == "seed":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(0, 0), q.size, q.size * (1.25 if k == "drop" else 0.7))
        elif k == "shell":
            p.rotate(q.rot)
            p.setPen(QPen(QColor("#B89B72"), 0.9))
            p.setBrush(c)
            p.drawPolygon(QPolygonF([QPointF(-q.size, q.size * 0.4), QPointF(0, -q.size), QPointF(q.size, q.size * 0.6),
                                     QPointF(q.size * 0.2, q.size * 0.1)]))
        elif k == "sprinkle":
            p.rotate(q.rot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(-q.size, -q.size * 0.3, q.size * 2, q.size * 0.6), 1, 1)
        elif k == "ring":
            p.setPen(QPen(c, 5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), q.size, q.size)
        elif k == "flash":
            g = QRadialGradient(QPointF(0, 0), max(1.0, q.size))
            g.setColorAt(0, QColor(255, 250, 220, 255))
            g.setColorAt(0.5, QColor(255, 190, 90, 180))
            g.setColorAt(1, QColor(255, 120, 40, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(0, 0), q.size, q.size)
        elif k == "burst":                             # 拍中时的一圈短线
            p.setPen(QPen(c, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for i in range(10):
                ang = i / 10 * math.tau
                p.drawLine(QPointF(math.cos(ang) * q.size * 0.75, math.sin(ang) * q.size * 0.75),
                           QPointF(math.cos(ang) * q.size, math.sin(ang) * q.size))
        elif k == "spark":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawPath(_star_path(q.size * 1.4, 0.4))
        elif k == "smoke":
            p.setPen(Qt.PenStyle.NoPen)
            c.setAlpha(int(140 * min(1.0, q.life / q.ttl)))
            p.setBrush(c)
            p.drawEllipse(QPointF(0, 0), q.size, q.size)
        elif k == "flake":
            p.rotate(q.rot)
            p.setPen(QPen(c, 1.3))
            for i in range(3):
                p.rotate(60)
                p.drawLine(QPointF(-q.size, 0), QPointF(q.size, 0))
        elif k == "petal":
            p.rotate(q.rot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(0, 0), q.size, q.size * 0.55)
        elif k == "heart":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawPath(_heart_path(q.size))
        elif k.startswith("item:"):
            p.rotate(q.rot)
            draw_item(p, k[5:], q.size)
        p.restore()

    def _paint_text(self, p: QPainter, t: dict, now: float) -> None:
        k = (now - t["t0"]) / t["ttl"]
        pop = 1.0 + 0.5 * max(0.0, 1 - k / 0.18)
        a = max(0.0, min(1.0, (1 - k) / 0.35))
        f = QFont(self.font())
        f.setPixelSize(int(t["size"] * pop))
        f.setWeight(QFont.Weight.Black)
        p.save()
        p.setOpacity(a)
        p.setFont(f)
        r = QRectF(t["x"] - 80, t["y"] - 20 - k * 16, 160, 40)
        opt = QTextOption(Qt.AlignmentFlag.AlignCenter)
        p.setPen(QColor(0, 0, 0, 150))
        for dx, dy in ((-1.5, 0), (1.5, 0), (0, -1.5), (0, 1.5), (0, 2.5)):
            p.drawText(r.translated(dx, dy), t["text"], opt)
        p.setPen(QColor(t["color"]))
        p.drawText(r, t["text"], opt)
        p.restore()

    def _paint_stain(self, p: QPainter, s: dict, now: float) -> None:
        t = now - s["t0"]
        a = max(0.0, min(1.0, (s["ttl"] - t) / 1.1))
        paint_stain(p, s["item"], s["pos"].x(), s["pos"].y(), s["r"], s["seed"], t, a)

    def _paint_screen(self, p: QPainter, s: dict, now: float) -> None:
        t = now - s["t0"]
        a = max(0.0, min(1.0, (s["ttl"] - t) / 1.2))
        item = s["item"]
        sr = self.screen_fn() if self.screen_fn else QRectF(self.rect())
        p.save()
        p.setClipRect(sr)
        if item == "bomb":
            if t < 0.45:
                p.fillRect(sr, QColor(255, 236, 200, int(200 * (1 - t / 0.45))))
            g = QRadialGradient(sr.center(), max(sr.width(), sr.height()) * 0.7)
            g.setColorAt(0.55, QColor(20, 20, 20, 0))
            g.setColorAt(1.0, QColor(20, 20, 20, int(200 * a)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRect(sr)
        elif item in ("tomato", "egg", "cake", "snow"):
            R = s["r"]
            pop = min(1.0, t / 0.1)
            p.translate(s["x"], s["y"])
            p.setOpacity(a)
            p.scale(pop, pop)
            col = {"tomato": QColor(224, 49, 49, 200), "egg": QColor(255, 255, 255, 150),
                   "cake": QColor(255, 253, 247, 225), "snow": QColor(255, 255, 255, 215)}[item]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPath(_blob(R, s["seed"], 13, 0.34))
            rng = random.Random(s["seed"])
            for _ in range(7):                         # 周围溅开的小点
                ang = rng.uniform(0, math.tau)
                d = R * rng.uniform(1.25, 1.8)
                p.drawEllipse(QPointF(math.cos(ang) * d, math.sin(ang) * d), R * rng.uniform(0.05, 0.12),
                              R * rng.uniform(0.05, 0.12))
            for i in range(5):                         # 顺着屏幕往下流
                dx = rng.uniform(-R * 0.7, R * 0.7)
                ln = min(R * 1.6, t * rng.uniform(25, 60))
                w = rng.uniform(5, 10)
                p.drawRoundedRect(QRectF(dx - w / 2, R * 0.4, w, R * 0.3 + ln), w / 2, w / 2)
                p.drawEllipse(QPointF(dx, R * 0.7 + ln), w * 0.7, w * 0.8)
            if item == "egg":
                p.setBrush(QColor("#FFC72C"))
                p.drawEllipse(QPointF(0, min(R * 0.6, t * 20)), R * 0.36, R * 0.32)
            elif item == "tomato":
                p.setBrush(QColor(255, 232, 163, 220))
                for _ in range(8):
                    p.drawEllipse(QPointF(rng.uniform(-R * 0.6, R * 0.6), rng.uniform(-R * 0.5, R * 0.5)), 3, 2)
            elif item == "cake":
                p.setBrush(QColor("#E03131"))
                p.drawEllipse(QPointF(R * 0.1, -R * 0.35), R * 0.12, R * 0.12)
        elif item == "slipper":
            R = s["r"]
            p.translate(s["x"], s["y"])
            p.rotate(-20)
            p.setOpacity(a * 0.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FF6B6B"))
            sole = QPainterPath()
            sole.addRoundedRect(QRectF(-R * 0.4, -R * 0.95, R * 0.8, R * 1.9), R * 0.4, R * 0.4)
            p.drawPath(sole)
            p.setOpacity(a * 0.35)
            p.setBrush(QColor("#C92A2A"))
            for i in range(5):
                p.drawEllipse(QPointF((i - 2) * R * 0.14, -R * 0.75), R * 0.07, R * 0.09)
        p.restore()
