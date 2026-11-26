"""
密语 · 矢量图标和头像(全部用代码画,随主题变色,高分屏清晰)
图标按 24×24 的网格绘制,风格接近 Feather 线条图标。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QTextOption,
)


def _dpr() -> float:
    try:
        return max(2.0, float(QGuiApplication.primaryScreen().devicePixelRatio()))
    except Exception:
        return 2.0


def _canvas(w: float, h: float | None = None) -> QPixmap:
    h = w if h is None else h
    dpr = _dpr()
    pm = QPixmap(int(math.ceil(w * dpr)), int(math.ceil(h * dpr)))
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    return pm


def _line(p: QPainter, *pts) -> None:
    for a, b in zip(pts, pts[1:]):
        p.drawLine(QPointF(*a), QPointF(*b))


def _dot(p: QPainter, color: QColor, x: float, y: float, r: float) -> None:
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


# ---------------------------------------------------------------- 各个图标
def _menu(p, c):
    for x in (5, 12, 19):
        _dot(p, c, x, 12, 1.7)


def _sun(p, c):
    p.drawEllipse(QPointF(12, 12), 4.2, 4.2)
    for k in range(8):
        a = k * math.pi / 4
        _line(p, (12 + 7.2 * math.cos(a), 12 + 7.2 * math.sin(a)), (12 + 9.6 * math.cos(a), 12 + 9.6 * math.sin(a)))


def _moon(p, c):
    a = QPainterPath()
    a.addEllipse(QPointF(11.5, 12.5), 8.5, 8.5)
    b = QPainterPath()
    b.addEllipse(QPointF(17.5, 7.0), 7.0, 7.0)
    p.drawPath(a.subtracted(b))


def _plus(p, c):
    _line(p, (12, 5), (12, 19))
    _line(p, (5, 12), (19, 12))


def _image(p, c):
    p.drawRoundedRect(QRectF(3, 3, 18, 18), 3, 3)
    p.drawEllipse(QPointF(8.5, 8.5), 1.6, 1.6)
    _line(p, (21, 15), (16, 10), (5, 21))


def _flame(p, c):
    path = QPainterPath(QPointF(12, 2.5))
    path.cubicTo(13.2, 6.8, 18.5, 8.8, 18.5, 14.2)
    path.cubicTo(18.5, 18.6, 15.6, 21.5, 12, 21.5)
    path.cubicTo(8.4, 21.5, 5.5, 18.8, 5.5, 15)
    path.cubicTo(5.5, 11.6, 8, 9.6, 9.3, 7.4)
    path.cubicTo(9.8, 9.6, 10.6, 11, 12.1, 11.6)
    path.cubicTo(12.8, 8.6, 12.7, 5.6, 12, 2.5)
    p.drawPath(path)


def _send(p, c):
    path = QPainterPath(QPointF(21.5, 2.5))
    path.lineTo(14.8, 21.5)
    path.lineTo(11, 13)
    path.lineTo(2.5, 9.2)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, (21.5, 2.5), (11, 13))


def _shield_path() -> QPainterPath:
    path = QPainterPath(QPointF(12, 22))
    path.cubicTo(12, 22, 20, 18, 20, 12)
    path.lineTo(20, 5)
    path.lineTo(12, 2)
    path.lineTo(4, 5)
    path.lineTo(4, 12)
    path.cubicTo(4, 18, 12, 22, 12, 22)
    return path


def _shield(p, c):
    p.drawPath(_shield_path())


def _shield_check(p, c):
    p.drawPath(_shield_path())
    _line(p, (8.5, 12), (11, 14.5), (15.5, 9.5))


def _trash(p, c):
    _line(p, (3, 6), (21, 6))
    path = QPainterPath(QPointF(19, 6))
    path.lineTo(18.2, 20)
    path.quadTo(18, 22, 16, 22)
    path.lineTo(8, 22)
    path.quadTo(6, 22, 5.8, 20)
    path.lineTo(5, 6)
    p.drawPath(path)
    lid = QPainterPath(QPointF(9, 6))
    lid.lineTo(9, 4)
    lid.quadTo(9, 3, 10, 3)
    lid.lineTo(14, 3)
    lid.quadTo(15, 3, 15, 4)
    lid.lineTo(15, 6)
    p.drawPath(lid)


def _lock(p, c):
    p.drawRoundedRect(QRectF(5, 11, 14, 10), 2.5, 2.5)
    path = QPainterPath(QPointF(8, 11))
    path.lineTo(8, 7.5)
    path.arcTo(QRectF(8, 3.5, 8, 8), 180, -180)
    path.lineTo(16, 11)
    p.drawPath(path)


def _hash(p, c):
    _line(p, (4.5, 9), (20, 9))
    _line(p, (4, 15), (19.5, 15))
    _line(p, (10.5, 3.5), (8.5, 20.5))
    _line(p, (15.5, 3.5), (13.5, 20.5))


def _close(p, c):
    _line(p, (6, 6), (18, 18))
    _line(p, (18, 6), (6, 18))


def _download(p, c):
    _line(p, (12, 3.5), (12, 15))
    _line(p, (7, 10), (12, 15), (17, 10))
    _line(p, (5, 20.5), (19, 20.5))


def _copy(p, c):
    p.drawRoundedRect(QRectF(9, 9, 12, 12), 2, 2)
    path = QPainterPath(QPointF(5, 15))
    path.lineTo(4.5, 15)
    path.quadTo(3, 15, 3, 13.5)
    path.lineTo(3, 4.5)
    path.quadTo(3, 3, 4.5, 3)
    path.lineTo(13.5, 3)
    path.quadTo(15, 3, 15, 4.5)
    path.lineTo(15, 5)
    p.drawPath(path)


def _eye_off(p, c):
    path = QPainterPath(QPointF(2, 12))
    path.cubicTo(5, 6, 9, 5, 12, 5)
    path.cubicTo(15, 5, 19, 6, 22, 12)
    path.cubicTo(19, 18, 15, 19, 12, 19)
    path.cubicTo(9, 19, 5, 18, 2, 12)
    p.drawPath(path)
    p.drawEllipse(QPointF(12, 12), 3, 3)
    _line(p, (3, 3), (21, 21))


def _user(p, c):
    p.drawEllipse(QPointF(12, 8), 4, 4)
    path = QPainterPath(QPointF(4, 21))
    path.cubicTo(4, 16.5, 7.5, 14, 12, 14)
    path.cubicTo(16.5, 14, 20, 16.5, 20, 21)
    p.drawPath(path)


def _arrow_up(p, c):
    _line(p, (12, 19), (12, 5.5))
    _line(p, (6.5, 11), (12, 5.5), (17.5, 11))


def _sliders(p, c):
    _line(p, (4, 7), (20, 7))
    _line(p, (4, 17), (20, 17))
    p.save()
    p.setBrush(QColor(c))
    p.drawEllipse(QPointF(15, 7), 2.4, 2.4)
    p.drawEllipse(QPointF(9, 17), 2.4, 2.4)
    p.restore()


def _pencil(p, c):
    path = QPainterPath(QPointF(16.5, 3.5))
    path.lineTo(20.5, 7.5)
    path.lineTo(8, 20)
    path.lineTo(3.8, 20.2)
    path.lineTo(4, 16)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, (14, 6), (18, 10))


def _wifi(p, c):
    for r in (4.5, 9, 13.5):
        path = QPainterPath()
        rect = QRectF(12 - r, 20 - r, 2 * r, 2 * r)
        path.arcMoveTo(rect, 45)
        path.arcTo(rect, 45, 90)
        p.drawPath(path)
    _dot(p, c, 12, 20, 1.4)


def _info(p, c):
    p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
    _line(p, (12, 11), (12, 16.5))
    _dot(p, c, 12, 7.8, 1.2)


def _power(p, c):
    path = QPainterPath()
    rect = QRectF(4.5, 4.5, 15, 15)
    path.arcMoveTo(rect, 120)
    path.arcTo(rect, 120, 300)
    p.drawPath(path)
    _line(p, (12, 3), (12, 11))


def _chevron_down(p, c):
    _line(p, (6.5, 9.5), (12, 15), (17.5, 9.5))


def _chevron_up(p, c):
    _line(p, (6.5, 14.5), (12, 9), (17.5, 14.5))


def _search(p, c):
    p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
    _line(p, (15, 15), (20, 20))


def _logout(p, c):
    path = QPainterPath(QPointF(10, 4.5))
    path.lineTo(6.5, 4.5)
    path.cubicTo(5.4, 4.5, 4.5, 5.4, 4.5, 6.5)
    path.lineTo(4.5, 17.5)
    path.cubicTo(4.5, 18.6, 5.4, 19.5, 6.5, 19.5)
    path.lineTo(10, 19.5)
    p.drawPath(path)
    _line(p, (10, 12), (20, 12))
    _line(p, (16.5, 8.5), (20, 12), (16.5, 15.5))


def _star(p, c):
    path = QPainterPath()
    for i in range(10):
        a = math.radians(-90 + i * 36)
        r = 8.6 if i % 2 == 0 else 3.8
        pt = QPointF(12 + r * math.cos(a), 12.6 + r * math.sin(a))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    p.drawPath(path)


def _gomoku(p, c):
    """五子棋:几条棋盘线,一颗实心(黑子)一颗空心(白子)。"""
    for v in (5.5, 12, 18.5):
        _line(p, (3.5, v), (20.5, v))
        _line(p, (v, 3.5), (v, 20.5))
    p.save()
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 12), 3.6, 3.6)
    p.restore()
    p.drawEllipse(QPointF(18.5, 5.5), 3.0, 3.0)


def _trophy(p, c):
    """奖杯:杯身、两个把手、底座。"""
    cup = QPainterPath(QPointF(7, 4.5))
    cup.lineTo(17, 4.5)
    cup.lineTo(17, 9)
    cup.cubicTo(17, 12.5, 14.8, 14.5, 12, 14.5)
    cup.cubicTo(9.2, 14.5, 7, 12.5, 7, 9)
    cup.closeSubpath()
    p.drawPath(cup)
    for s in (-1, 1):
        h = QPainterPath(QPointF(12 + s * 5, 6.5))
        h.cubicTo(12 + s * 8.5, 6.5, 12 + s * 8.5, 11, 12 + s * 5, 11)
        p.drawPath(h)
    _line(p, (12, 14.5), (12, 17.5))
    _line(p, (8, 19.5), (16, 19.5))
    _line(p, (9.5, 17.5), (14.5, 17.5))


def _duck(p, c):
    """小鸭子(谁是坏鸭):圆脑袋、扁嘴、身子。"""
    p.drawEllipse(QPointF(10, 8), 4, 4)
    beak = QPainterPath(QPointF(13.6, 7.6))
    beak.lineTo(17.5, 8.4)
    beak.lineTo(13.6, 9.6)
    p.drawPath(beak)
    body = QPainterPath(QPointF(6.5, 11.5))
    body.cubicTo(3.5, 13, 3.5, 19.5, 10, 19.5)
    body.lineTo(15, 19.5)
    body.cubicTo(19.5, 19.5, 20.5, 15, 19.5, 12.5)
    body.cubicTo(17.5, 14.5, 15, 14.5, 13, 12.5)
    p.drawPath(body)
    p.save()
    p.setBrush(c)
    p.drawEllipse(QPointF(10.6, 7.2), 0.9, 0.9)
    p.restore()


def _bell_path() -> QPainterPath:
    path = QPainterPath(QPointF(6, 16.5))
    path.lineTo(6, 10.5)
    path.cubicTo(6, 7, 8.7, 4.5, 12, 4.5)
    path.cubicTo(15.3, 4.5, 18, 7, 18, 10.5)
    path.lineTo(18, 16.5)
    path.lineTo(19.5, 18)
    path.lineTo(4.5, 18)
    path.closeSubpath()
    return path


def _bell(p, c):
    p.drawPath(_bell_path())
    path = QPainterPath(QPointF(10, 20.5))
    path.quadTo(12, 22.3, 14, 20.5)
    p.drawPath(path)
    _line(p, (12, 2.5), (12, 4.5))


def _bell_off(p, c):
    _bell(p, c)
    _line(p, (3.5, 3.5), (20.5, 20.5))


def _paperclip(p, c):
    path = QPainterPath(QPointF(20, 11.5))
    path.lineTo(12.2, 19.3)
    path.cubicTo(10, 21.5, 6.5, 21.5, 4.6, 19.4)
    path.cubicTo(2.6, 17.4, 2.6, 14.1, 4.7, 12)
    path.lineTo(12.5, 4.2)
    path.cubicTo(13.9, 2.8, 16.1, 2.8, 17.4, 4.2)
    path.cubicTo(18.8, 5.6, 18.8, 7.8, 17.4, 9.2)
    path.lineTo(9.7, 16.9)
    path.cubicTo(9, 17.6, 7.9, 17.6, 7.2, 16.9)
    path.cubicTo(6.5, 16.2, 6.5, 15.1, 7.2, 14.4)
    path.lineTo(14.3, 7.3)
    p.drawPath(path)


def _smile(p, c):
    p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
    path = QPainterPath(QPointF(8, 14))
    path.cubicTo(9, 16, 10.5, 16.8, 12, 16.8)
    path.cubicTo(13.5, 16.8, 15, 16, 16, 14)
    p.drawPath(path)
    _dot(p, c, 9, 9.8, 1.2)
    _dot(p, c, 15, 9.8, 1.2)


def _reply(p, c):
    path = QPainterPath(QPointF(20, 19))
    path.cubicTo(20, 13, 16.5, 10, 10, 10)
    path.lineTo(4.5, 10)
    p.drawPath(path)
    _line(p, (9, 5), (4, 10), (9, 15))


def _file(p, c):
    path = QPainterPath(QPointF(14, 2.5))
    path.lineTo(6.5, 2.5)
    path.quadTo(4.5, 2.5, 4.5, 4.5)
    path.lineTo(4.5, 19.5)
    path.quadTo(4.5, 21.5, 6.5, 21.5)
    path.lineTo(17.5, 21.5)
    path.quadTo(19.5, 21.5, 19.5, 19.5)
    path.lineTo(19.5, 8)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, (14, 2.5), (14, 8), (19.5, 8))


def _at(p, c):
    p.drawEllipse(QPointF(12, 12), 3.6, 3.6)
    path = QPainterPath(QPointF(15.6, 8.5))
    path.lineTo(15.6, 13.2)
    path.cubicTo(15.6, 15.2, 17, 16, 18.3, 16)
    path.cubicTo(19.8, 16, 21, 14.6, 21, 12)
    path.cubicTo(21, 7, 17, 3, 12, 3)
    path.cubicTo(7, 3, 3, 7, 3, 12)
    path.cubicTo(3, 17, 7, 21, 12, 21)
    path.cubicTo(13.8, 21, 15.5, 20.5, 16.8, 19.6)
    p.drawPath(path)


def _undo(p, c):
    path = QPainterPath(QPointF(4.5, 9))
    path.lineTo(15, 9)
    path.cubicTo(18.3, 9, 20.5, 11.4, 20.5, 14.2)
    path.cubicTo(20.5, 17, 18.3, 19.5, 15, 19.5)
    path.lineTo(9, 19.5)
    p.drawPath(path)
    _line(p, (8.5, 5), (4.5, 9), (8.5, 13))


def _chat(p, c):
    path = QPainterPath(QPointF(12, 4))
    path.cubicTo(16.9, 4, 20.5, 7.2, 20.5, 11.2)
    path.cubicTo(20.5, 15.2, 16.9, 18.4, 12, 18.4)
    path.cubicTo(11, 18.4, 10.1, 18.3, 9.2, 18)
    path.lineTo(5, 20)
    path.lineTo(5.8, 16.3)
    path.cubicTo(4.3, 15, 3.5, 13.2, 3.5, 11.2)
    path.cubicTo(3.5, 7.2, 7.1, 4, 12, 4)
    path.closeSubpath()
    p.drawPath(path)


def _refresh(p, c):
    path = QPainterPath(QPointF(19.5, 12))
    path.cubicTo(19.5, 16.1, 16.1, 19.5, 12, 19.5)
    path.cubicTo(9.6, 19.5, 7.5, 18.4, 6.1, 16.6)
    p.drawPath(path)
    path = QPainterPath(QPointF(4.5, 12))
    path.cubicTo(4.5, 7.9, 7.9, 4.5, 12, 4.5)
    path.cubicTo(14.4, 4.5, 16.5, 5.6, 17.9, 7.4)
    p.drawPath(path)
    _line(p, (18.2, 3.6), (18.2, 7.6), (14.2, 7.6))
    _line(p, (5.8, 20.4), (5.8, 16.4), (9.8, 16.4))


def _folder(p, c):
    path = QPainterPath(QPointF(3, 7))
    path.quadTo(3, 5, 5, 5)
    path.lineTo(9.5, 5)
    path.lineTo(11.5, 7.5)
    path.lineTo(19, 7.5)
    path.quadTo(21, 7.5, 21, 9.5)
    path.lineTo(21, 17.5)
    path.quadTo(21, 19.5, 19, 19.5)
    path.lineTo(5, 19.5)
    path.quadTo(3, 19.5, 3, 17.5)
    path.closeSubpath()
    p.drawPath(path)


def _sunset(p, c):
    _line(p, (2.5, 18), (21.5, 18))
    path = QPainterPath()
    rect = QRectF(7, 9.5, 10, 10)
    path.arcMoveTo(rect, 0)
    path.arcTo(rect, 0, 180)
    p.drawPath(path)
    for ang in (180, 135, 90, 45, 0):
        a = math.radians(ang)
        _line(p, (12 + 7.3 * math.cos(a), 14.5 - 7.3 * math.sin(a)), (12 + 9.3 * math.cos(a), 14.5 - 9.3 * math.sin(a)))
    _line(p, (7, 21.5), (17, 21.5))


def _pin(p, c):
    """图钉:置顶。"""
    head = QPainterPath(QPointF(9, 3.5))
    head.lineTo(15, 3.5)
    head.lineTo(14, 9.5)
    head.lineTo(17.5, 13.5)
    head.lineTo(6.5, 13.5)
    head.lineTo(10, 9.5)
    head.closeSubpath()
    p.drawPath(head)
    _line(p, (12, 13.5), (12, 21))


def _palette(p, c):
    """调色板:个性化外观。"""
    path = QPainterPath(QPointF(12, 3))
    path.cubicTo(6.5, 3, 3, 7, 3, 12)
    path.cubicTo(3, 17, 7, 21, 12, 21)
    path.cubicTo(13.6, 21, 14, 19.8, 13.2, 18.6)
    path.cubicTo(12.3, 17.3, 13, 15.6, 14.8, 15.6)
    path.lineTo(17, 15.6)
    path.cubicTo(19.4, 15.6, 21, 14, 21, 11.6)
    path.cubicTo(21, 6.8, 17, 3, 12, 3)
    p.drawPath(path)
    for x, y in ((8, 10.5), (11.5, 7.5), (15.8, 8.6)):
        _dot(p, c, x, y, 1.4)


def _paw(p, c):
    """小爪印:宠物。"""
    p.drawEllipse(QRectF(7, 12, 10, 8.5))
    for x, y, r in ((5.2, 9.5, 1.9), (9, 5.8, 2.0), (15, 5.8, 2.0), (18.8, 9.5, 1.9)):
        p.drawEllipse(QPointF(x, y), r, r * 1.15)


def _more(p, c):
    """横着的三个点。"""
    for x in (6, 12, 18):
        _dot(p, c, x, 12, 1.6)


def _heart(p, c):
    path = QPainterPath(QPointF(12, 20))
    path.cubicTo(5, 15.5, 3, 12, 3, 8.8)
    path.cubicTo(3, 6, 5.2, 4, 7.8, 4)
    path.cubicTo(9.6, 4, 11.1, 5, 12, 6.6)
    path.cubicTo(12.9, 5, 14.4, 4, 16.2, 4)
    path.cubicTo(18.8, 4, 21, 6, 21, 8.8)
    path.cubicTo(21, 12, 19, 15.5, 12, 20)
    p.drawPath(path)


def _minimize(p, c):
    _line(p, (5.5, 12), (18.5, 12))


def _maximize(p, c):
    p.drawRoundedRect(QRectF(5.5, 5.5, 13, 13), 2.4, 2.4)


def _restore(p, c):
    p.drawRoundedRect(QRectF(5, 8, 10.5, 10.5), 2.0, 2.0)
    path = QPainterPath(QPointF(8.5, 8))
    path.lineTo(8.5, 6.5)
    path.quadTo(8.5, 5, 10, 5)
    path.lineTo(17.5, 5)
    path.quadTo(19, 5, 19, 6.5)
    path.lineTo(19, 14)
    path.quadTo(19, 15.5, 17.5, 15.5)
    path.lineTo(15.5, 15.5)
    p.drawPath(path)


def _sidebar(p, c):
    p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 3.0, 3.0)
    _line(p, (9.5, 4.5), (9.5, 19.5))


def _users(p, c):
    p.drawEllipse(QPointF(9.5, 8.5), 3.2, 3.2)
    path = QPainterPath(QPointF(3.8, 19))
    path.cubicTo(3.8, 15.2, 6.2, 13.5, 9.5, 13.5)
    path.cubicTo(12.8, 13.5, 15.2, 15.2, 15.2, 19)
    p.drawPath(path)
    arc = QPainterPath(QPointF(15, 5.8))
    arc.cubicTo(17.5, 6.2, 18.2, 9.8, 15.5, 11.2)
    p.drawPath(arc)
    sh = QPainterPath(QPointF(16.5, 13.8))
    sh.cubicTo(19.0, 14.4, 20.4, 16.2, 20.4, 19)
    p.drawPath(sh)


def _terminal(p, c):
    p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 3.0, 3.0)
    _line(p, (7.2, 9.5), (10.5, 12), (7.2, 14.5))
    _line(p, (12.2, 15), (16.5, 15))


def _code(p, c):
    _line(p, (8.5, 8), (4.2, 12), (8.5, 16))
    _line(p, (15.5, 8), (19.8, 12), (15.5, 16))
    _line(p, (13.6, 6.5), (10.4, 17.5))


def _grid(p, c):
    for x, y in ((4.2, 4.2), (13.3, 4.2), (4.2, 13.3), (13.3, 13.3)):
        p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.8, 1.8)


DRAW = {
    "menu": _menu, "sun": _sun, "moon": _moon, "plus": _plus, "image": _image, "flame": _flame,
    "send": _send, "shield": _shield, "shield_check": _shield_check, "trash": _trash, "lock": _lock,
    "hash": _hash, "close": _close, "download": _download, "copy": _copy, "eye_off": _eye_off, "user": _user,
    "arrow_up": _arrow_up, "sliders": _sliders, "pencil": _pencil, "wifi": _wifi, "info": _info, "power": _power,
    "chevron_down": _chevron_down, "chevron_up": _chevron_up, "search": _search, "logout": _logout, "star": _star, "bell": _bell, "gomoku": _gomoku, "trophy": _trophy, "duck": _duck, "chat": _chat, "refresh": _refresh, "bell_off": _bell_off, "paperclip": _paperclip,
    "smile": _smile, "reply": _reply, "file": _file, "at": _at, "undo": _undo, "folder": _folder,
    "sunset": _sunset, "pin": _pin, "palette": _palette, "paw": _paw, "more": _more, "heart": _heart,
    "minimize": _minimize, "maximize": _maximize, "restore": _restore, "sidebar": _sidebar,
    "users": _users, "terminal": _terminal, "code": _code, "grid": _grid,
}


_FILE_COLORS = {
    "doc": "#4E7BD6", "docx": "#4E7BD6", "pdf": "#E05252", "xls": "#2F9E66", "xlsx": "#2F9E66", "csv": "#2F9E66",
    "ppt": "#E87A3E", "pptx": "#E87A3E", "zip": "#D49B2A", "rar": "#D49B2A", "7z": "#D49B2A",
    "mp4": "#8B6CC9", "mov": "#8B6CC9", "mkv": "#8B6CC9", "mp3": "#D65A92", "wav": "#D65A92", "flac": "#D65A92",
    "txt": "#6C7A89", "md": "#5C6BC0", "py": "#7950F2", "js": "#E6A817", "ts": "#3178C6", "json": "#20A486",
    "exe": "#C95454", "msi": "#C95454", "bat": "#C95454", "folder": "#4A90E2",
    "png": "#22A6C9", "jpg": "#22A6C9", "jpeg": "#22A6C9", "gif": "#22A6C9", "webp": "#22A6C9", "psd": "#3E7FC9",
}


def file_badge(ext: str, size: int = 42) -> QPixmap:
    """文件图标:圆角卡片 + 折角 + 扩展名,不同类型不同颜色(低饱和)。"""
    ext = (ext or "").lower().lstrip(".")[:4]
    key = ("file", ext, size)
    pm = _avatar_cache.get(key)
    if pm is not None:
        return pm
    pm = _canvas(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(_FILE_COLORS.get(ext, "#8A93A3"))
    w, h = size * 0.78, size
    x0 = (size - w) / 2
    fold = size * 0.26
    path = QPainterPath(QPointF(x0 + 4, 0))
    path.lineTo(x0 + w - fold, 0)
    path.lineTo(x0 + w, fold)
    path.lineTo(x0 + w, h - 4)
    path.quadTo(x0 + w, h, x0 + w - 4, h)
    path.lineTo(x0 + 4, h)
    path.quadTo(x0, h, x0, h - 4)
    path.lineTo(x0, 4)
    path.quadTo(x0, 0, x0 + 4, 0)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, color.lighter(115))
    g.setColorAt(1, color)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawPath(path)
    corner = QPainterPath(QPointF(x0 + w - fold, 0))
    corner.lineTo(x0 + w - fold, fold - 3)
    corner.quadTo(x0 + w - fold, fold, x0 + w - fold + 3, fold)
    corner.lineTo(x0 + w, fold)
    corner.closeSubpath()
    p.setBrush(QColor(255, 255, 255, 90))
    p.drawPath(corner)
    if ext:
        f = QFont()
        f.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI"])
        f.setWeight(QFont.Weight.Bold)
        f.setPixelSize(max(7, int(size * (0.22 if len(ext) <= 3 else 0.18))))
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(x0, h * 0.48, w, h * 0.4), ext.upper(), QTextOption(Qt.AlignmentFlag.AlignCenter))
    p.end()
    _avatar_cache[key] = pm
    return pm


def paint_icon(p: QPainter, name: str, color: str, x: float, y: float, size: float, width: float = 1.6) -> None:
    """在 painter 上 (x, y) 处画一个 size 大小的统一 1.6px 圆头矢量图标。"""
    p.save()
    p.translate(x, y)
    p.scale(size / 24.0, size / 24.0)
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    DRAW[name](p, QColor(color))
    p.restore()


def soft_shadow(p: QPainter, rect: QRectF, radius: float, alpha: int = 28, spread: int = 6, dy: float = 2.0) -> None:
    """用几层半透明圆角矩形模拟柔和阴影(比 QGraphicsEffect 便宜得多,也不会让文字发虚)。"""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    step = max(1, alpha // spread)
    for i in range(spread, 0, -1):
        p.setBrush(QColor(0, 0, 0, step))
        p.drawRoundedRect(rect.adjusted(-i, -i + dy, i, i + dy), radius + i, radius + i)
    p.restore()


def icon(name: str, color: str, size: int = 20, width: float = 1.6) -> QIcon:
    pm = _canvas(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_icon(p, name, color, 0, 0, size, width)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- 头像
_avatar_cache: dict = {}


def initial(text: str) -> str:
    text = (text or "").strip()
    return text[:1].upper() if text else "?"


def avatar(text: str, color: str, size: int, glyph: str | None = None) -> QPixmap:
    """渐变圆形头像:显示名字首字,或者一个图标(大厅 #、暗号群 🔒)。"""
    key = (text, color, size, glyph)
    pm = _avatar_cache.get(key)
    if pm is not None:
        return pm
    pm = _canvas(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    base = QColor(color)
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0, base.lighter(122))
    g.setColorAt(1, base.darker(108))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(QRectF(0, 0, size, size))
    if glyph:
        s = size * 0.5
        paint_icon(p, glyph, "#ffffff", (size - s) / 2, (size - s) / 2, s, 2.0)
    else:
        f = QFont()
        f.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", "Noto Sans CJK SC"])
        f.setWeight(QFont.Weight.DemiBold)
        f.setPixelSize(max(8, int(size * 0.40)))
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(0, 0, size, size), initial(text), QTextOption(Qt.AlignmentFlag.AlignCenter))
    p.end()
    if len(_avatar_cache) > 600:
        _avatar_cache.clear()
    _avatar_cache[key] = pm
    return pm


def app_logo(size: int) -> QPixmap:
    """程序图标:渐变圆角方块 + 白色对话气泡 + 锁孔。"""
    pm = _canvas(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    k = size / 256.0
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#4f8cff"))
    g.setColorAt(1, QColor("#7b5cff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(QRectF(8 * k, 8 * k, 240 * k, 240 * k), 56 * k, 56 * k)
    p.setBrush(QColor("#ffffff"))
    bubble = QPainterPath()
    bubble.addRoundedRect(QRectF(52 * k, 60 * k, 152 * k, 112 * k), 40 * k, 40 * k)
    tail = QPainterPath(QPointF(92 * k, 160 * k))
    tail.lineTo(78 * k, 206 * k)
    tail.lineTo(132 * k, 168 * k)
    tail.closeSubpath()
    p.drawPath(bubble.united(tail))
    p.setBrush(QColor("#3d5fd6"))
    p.drawEllipse(QRectF(115 * k, 86 * k, 26 * k, 26 * k))
    p.drawRoundedRect(QRectF(121 * k, 102 * k, 14 * k, 38 * k), 4 * k, 4 * k)
    p.end()
    return pm
