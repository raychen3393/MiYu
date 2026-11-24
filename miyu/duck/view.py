"""
谁是坏鸭 · 地图画面。镜头跟着自己走;地板、墙、房间里的摆设、任务点、紧急按钮、尸体、角色、视野迷雾。
角色是圆滚滚的小鹅(大家长得一样,只有颜色不同 —— 看外表分不出谁是坏鸭)。全部用 QPainter 画。
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient, QTextOption
from PySide6.QtWidgets import QWidget

from . import world as Wd
from .rules import DUCK

OUTLINE = "#3B2E2A"


def _now() -> float:
    return time.monotonic()


def draw_bird(p: QPainter, x: float, y: float, color: str, face: int = 1, t: float = 0.0, walking: bool = False,
              ghost: bool = False, scale: float = 1.0) -> None:
    """一只圆滚滚的小鹅:身子、白肚皮、橙色扁嘴、眼睛、小翅膀、两只脚。幽灵半透明、飘着、头顶光环。"""
    p.save()
    bob = math.sin(t * 12) * 2.2 if walking else math.sin(t * 2.4) * 0.8
    if ghost:
        bob = math.sin(t * 2.5) * 4
        p.setOpacity(p.opacity() * 0.55)
    p.translate(x, y + bob)
    p.scale(scale * face, scale)
    out = QPen(QColor(OUTLINE), 2)
    out.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    body = QColor(color)
    if not ghost:                                     # 影子 + 脚
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(QPointF(0, 19 - bob), 15, 4.5)
        p.setPen(QPen(QColor("#E8590C"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        step = math.sin(t * 12) * 4 if walking else 0
        p.drawLine(QPointF(-5, 12), QPointF(-6 + step, 18 - bob))
        p.drawLine(QPointF(5, 12), QPointF(6 - step, 18 - bob))
    p.setPen(out)
    p.setBrush(body)
    p.drawEllipse(QPointF(0, 2), 17, 15)                  # 身子
    p.drawEllipse(QPointF(5, -12), 10, 10)                # 脑袋
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 170))
    p.drawEllipse(QPointF(-1, 6), 10, 7.5)                # 肚皮
    p.setPen(out)
    wing = QPainterPath(QPointF(-12, -2))
    wing.quadTo(-20, 6, -10, 11)
    wing.quadTo(-6, 4, -12, -2)
    p.setBrush(body.darker(112))
    p.drawPath(wing)
    beak = QPainterPath(QPointF(13, -14))
    beak.quadTo(22, -12, 21, -9)
    beak.quadTo(16, -7, 12, -9)
    beak.closeSubpath()
    p.setBrush(QColor("#FF922B"))
    p.drawPath(beak)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(OUTLINE))
    p.drawEllipse(QPointF(8, -14), 1.9, 2.3)
    p.setBrush(QColor(255, 255, 255, 220))
    p.drawEllipse(QPointF(8.6, -14.8), 0.7, 0.7)
    p.setBrush(QColor(255, 140, 160, 120))
    p.drawEllipse(QPointF(3, -8), 3, 1.8)
    if ghost:
        p.setPen(QPen(QColor("#FFE066"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(5, -27), 8, 2.5)
    p.restore()


def draw_body(p: QPainter, x: float, y: float, color: str) -> None:
    """尸体:小鹅仰面躺着,眼睛是 ×,旁边掉了几根羽毛。"""
    p.save()
    p.translate(x, y)
    out = QPen(QColor(OUTLINE), 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawEllipse(QPointF(0, 10), 24, 6)
    p.setPen(out)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(0, 2), 20, 11)
    p.drawEllipse(QPointF(18, -2), 8, 8)
    p.setPen(QPen(QColor(OUTLINE), 1.8))
    for dx in (16, 21):
        p.drawLine(QPointF(dx - 2, -4), QPointF(dx + 2, 0))
        p.drawLine(QPointF(dx - 2, 0), QPointF(dx + 2, -4))
    p.setPen(QPen(QColor("#E8590C"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(-6, -7), QPointF(-9, -16))
    p.drawLine(QPointF(4, -7), QPointF(6, -16))
    p.setPen(QPen(QColor("#ADB5BD"), 1))
    p.setBrush(QColor("#FFFFFF"))
    for fx, fy, a in ((-26, 4, 20), (-18, 14, -30), (28, 12, 50)):
        p.save()
        p.translate(fx, fy)
        p.rotate(a)
        p.drawEllipse(QPointF(0, 0), 6, 2.2)
        p.restore()
    p.restore()


class MapView(QWidget):
    """client = duck.client.Client;每帧由窗口调用 update()。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.client = None
        self.setMinimumSize(480, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scale = 1.0
        self.frames = 0
        self._room_name = ("", -1e9)

    def set_client(self, client) -> None:
        self.client = client

    # ---------------------------------------------------------------- 坐标
    def camera(self) -> tuple[float, float, float]:
        c = self.client
        w, h = max(1, self.width()), max(1, self.height())
        s = max(0.6, min(1.7, min(w, h) / (Wd.VISION * 1.95)))
        cx, cy = (c.x, c.y) if c else Wd.BUTTON
        return cx, cy, s

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        cx, cy, s = self.camera()
        return (x - cx) * s + self.width() / 2, (y - cy) * s + self.height() / 2

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.paint_scene(p, _now())
        p.end()

    def paint_scene(self, p: QPainter, now: float) -> None:
        self.frames += 1
        c = self.client
        w, h = self.width(), self.height()
        p.fillRect(QRectF(0, 0, w, h), QColor("#1E1A2B"))
        cx, cy, s = self.camera()
        self.scale = s
        p.save()
        p.translate(w / 2, h / 2)
        p.scale(s, s)
        p.translate(-cx, -cy)
        self._paint_floor(p, now)
        if c is not None:
            self._paint_markers(p, c, now)
            for b in c.bodies:
                draw_body(p, b[1], b[2], c.color(b[0]))
            self._paint_players(p, c, now)
            self._paint_fx(p, c, now)
        p.restore()
        if c is not None and c.alive and c.phase == "play":
            self._paint_fog(p, c, now)
        if c is not None and c.phase == "play":
            self._paint_room_toast(p, c, now)

    def _paint_floor(self, p: QPainter, now: float) -> None:
        wall = QColor("#5B4B6E")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(wall)
        for r in Wd.WALKABLE:                            # 先铺一圈墙(每块往外扩一点),再盖地板,拼起来只剩外轮廓
            p.drawRoundedRect(QRectF(r.x - 10, r.y - 10, r.w + 20, r.h + 20), 14, 14)
        p.setBrush(QColor("#E6DED2"))
        for r in Wd.HALLS:
            p.drawRect(QRectF(r.x, r.y, r.w, r.h))
        for rid, name, r, col in Wd.ROOMS:
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(r.x, r.y, r.w, r.h), 8, 8)
            self._paint_props(p, rid, r, now)
        f = QFont(self.font())
        f.setPixelSize(30)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        for rid, name, r, col in Wd.ROOMS:
            p.setPen(QColor(0, 0, 0, 38))
            p.drawText(QRectF(r.x, r.y + 14, r.w, 40), name, QTextOption(Qt.AlignmentFlag.AlignCenter))
        locked = self.client.locked if self.client else set()
        for rid in locked:
            for d in Wd.DOORS.get(rid, ()):
                p.setPen(QPen(QColor("#C92A2A"), 2))
                p.setBrush(QColor("#FA5252"))
                p.drawRoundedRect(QRectF(d.x, d.y, d.w, d.h), 4, 4)
                p.setPen(QPen(QColor(255, 255, 255, 160), 3))
                if d.w < d.h:
                    for k in range(3):
                        y = d.y + d.h * (k + 1) / 4
                        p.drawLine(QPointF(d.x + 4, y), QPointF(d.r - 4, y))
                else:
                    for k in range(3):
                        x = d.x + d.w * (k + 1) / 4
                        p.drawLine(QPointF(x, d.y + 4), QPointF(x, d.b - 4))

    def _paint_props(self, p: QPainter, rid: str, r, now: float) -> None:
        """房间里的摆设(只是装饰,不挡路)。"""
        p.save()
        out = QPen(QColor(0, 0, 0, 60), 2)
        if rid == "kitchen":
            p.setPen(out)
            p.setBrush(QColor("#CED4DA"))
            p.drawRoundedRect(QRectF(r.x + 30, r.y + 70, 150, 60), 8, 8)              # 灶台
            p.setBrush(QColor("#495057"))
            for k in range(3):
                p.drawEllipse(QPointF(r.x + 60 + k * 45, r.y + 100), 13, 13)
            p.setBrush(QColor("#C08552"))
            p.drawEllipse(QPointF(r.center()[0] + 60, r.center()[1] + 40), 70, 46)    # 餐桌
        elif rid == "barn":
            p.setPen(out)
            p.setBrush(QColor("#FFD43B"))
            for k in range(4):
                p.drawRoundedRect(QRectF(r.x + 60 + k * 120, r.y + 250, 90, 60), 14, 14)   # 干草垛
            p.setPen(QPen(QColor("#E8A200"), 2))
            for k in range(4):
                for j in range(3):
                    x = r.x + 75 + k * 120 + j * 22
                    p.drawLine(QPointF(x, r.y + 258), QPointF(x + 8, r.y + 302))
        elif rid == "garden":
            p.setPen(Qt.PenStyle.NoPen)
            for row in range(3):
                p.setBrush(QColor("#A97C50"))
                p.drawRoundedRect(QRectF(r.x + 60, r.y + 110 + row * 90, r.w - 120, 36), 18, 18)
                p.setBrush(QColor("#51CF66"))
                for k in range(7):
                    x = r.x + 90 + k * 52
                    p.drawEllipse(QPointF(x, r.y + 118 + row * 90), 9, 12)
        elif rid == "power":
            p.setPen(out)
            for k in range(4):
                p.setBrush(QColor("#ADB5BD"))
                p.drawRoundedRect(QRectF(r.x + 120 + k * 70, r.y + 30, 54, 80), 6, 6)
                blink = int(now * 2 + k) % 2 == 0
                p.setBrush(QColor("#51CF66" if blink else "#2B8A3E"))
                p.drawEllipse(QPointF(r.x + 147 + k * 70, r.y + 50), 5, 5)
        elif rid == "plaza":                             # 中央:一张大圆桌,中间是红色紧急按钮
            bx, by = Wd.BUTTON
            p.setPen(out)
            p.setBrush(QColor("#B08968"))
            p.drawEllipse(QPointF(bx, by), 70, 56)
            p.setBrush(QColor("#8D6E63"))
            p.drawEllipse(QPointF(bx, by + 6), 34, 26)
            pulse = 0.5 + 0.5 * math.sin(now * 3)
            p.setBrush(QColor(255, 80, 80, int(110 + 80 * pulse)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(bx, by - 2), 30, 22)
            p.setPen(QPen(QColor("#A61E1E"), 2))
            p.setBrush(QColor("#FA5252"))
            p.drawEllipse(QPointF(bx, by - 4), 22, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 140))
            p.drawEllipse(QPointF(bx - 7, by - 9), 6, 3)
            p.setBrush(QColor("#74C0FC"))                 # 四角的小花坛
            for dx, dy in ((-260, -140), (260, -140), (-260, 140), (260, 140)):
                p.drawEllipse(QPointF(bx + dx, by + dy), 26, 26)
        elif rid == "clinic":
            p.setPen(out)
            for k in range(3):
                p.setBrush(QColor("#FFFFFF"))
                p.drawRoundedRect(QRectF(r.x + 40 + k * 130, r.y + 120, 90, 140), 10, 10)
                p.setBrush(QColor("#A5D8FF"))
                p.drawRoundedRect(QRectF(r.x + 50 + k * 130, r.y + 128, 70, 30), 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FA5252"))
            p.drawRect(QRectF(r.r - 60, r.y + 30, 12, 36))
            p.drawRect(QRectF(r.r - 72, r.y + 42, 36, 12))
        elif rid == "storage":
            p.setPen(out)
            for k in range(5):
                p.setBrush(QColor("#C99A70" if k % 2 else "#B08968"))
                p.drawRect(QRectF(r.x + 60 + k * 70, r.y + 150 + (k % 2) * 30, 56, 56))
                p.drawLine(QPointF(r.x + 60 + k * 70, r.y + 170 + (k % 2) * 30),
                           QPointF(r.x + 116 + k * 70, r.y + 170 + (k % 2) * 30))
        elif rid == "pond":
            cx, cy = r.center()
            p.setPen(QPen(QColor("#4DABF7"), 3))
            p.setBrush(QColor("#74C0FC"))
            p.drawEllipse(QPointF(cx, cy + 10), 230, 90)
            p.setPen(QPen(QColor(255, 255, 255, 120), 2))
            for k in range(3):
                ph = (now * 0.4 + k / 3) % 1.0
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx - 60 + k * 70, cy + 10), 20 + ph * 30, 8 + ph * 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#51CF66"))
            for dx, dy in ((-150, 30), (130, -20), (60, 50)):
                p.drawEllipse(QPointF(cx + dx, cy + dy), 16, 10)
        elif rid == "coop":
            p.setPen(out)
            for k in range(4):
                p.setBrush(QColor("#E9D3B4"))
                p.drawEllipse(QPointF(r.x + 90 + k * 110, r.y + 220), 40, 22)
                p.setBrush(QColor("#FFF8E7"))
                p.drawEllipse(QPointF(r.x + 84 + k * 110, r.y + 214), 8, 10)
                p.drawEllipse(QPointF(r.x + 98 + k * 110, r.y + 216), 7, 9)
        p.restore()

    def _paint_markers(self, p: QPainter, c, now: float) -> None:
        for tid in c.tasks:                              # 还没做的任务:一个上下跳的黄色感叹号
            if tid in c.done or c.phase != "play":
                continue
            t = Wd.TASK_BY_ID[tid]
            bob = math.sin(now * 4 + hash(tid) % 7) * 4
            x, y = t[3], t[4]
            p.setPen(QPen(QColor("#E8A200"), 2))
            p.setBrush(QColor(255, 212, 59, 70))
            p.drawEllipse(QPointF(x, y), 26, 26)
            p.setBrush(QColor("#FFD43B"))
            p.drawRoundedRect(QRectF(x - 11, y - 40 + bob, 22, 26), 8, 8)
            f = QFont(self.font())
            f.setPixelSize(18)
            f.setWeight(QFont.Weight.Black)
            p.setFont(f)
            p.setPen(QColor(OUTLINE))
            p.drawText(QRectF(x - 11, y - 40 + bob, 22, 26), "!", QTextOption(Qt.AlignmentFlag.AlignCenter))
        if c.lights_off and c.phase == "play":           # 关灯了:配电室的电闸一闪一闪
            _r, sx, sy = Wd.LIGHT_SWITCH
            a = 0.5 + 0.5 * math.sin(now * 8)
            p.setPen(QPen(QColor("#FFD43B"), 3))
            p.setBrush(QColor(255, 212, 59, int(80 + 120 * a)))
            p.drawRoundedRect(QRectF(sx - 22, sy - 30, 44, 60), 8, 8)

    def _paint_players(self, p: QPainter, c, now: float) -> None:
        ids = c.visible_ids() + [c.me]
        rows = []
        for pid in ids:
            pos = c.pos_of(pid, now)
            if pos is None or pid in c.gone:
                continue
            alive = c.alive if pid == c.me else bool(c.alive_of.get(pid, 1))
            rows.append((pos[1], pid, pos, alive))
        rows.sort()                                      # 下面的人画在上面
        f = QFont(self.font())
        f.setPixelSize(14)
        f.setWeight(QFont.Weight.Bold)
        for _y, pid, (x, y, face), alive in rows:
            if not alive and c.alive and pid != c.me:
                continue
            draw_bird(p, x, y, c.color(pid), face, now + hash(pid) % 10, c.moving(pid), ghost=not alive, scale=1.15)
            name = c.nick(pid)
            p.setFont(f)
            r = QRectF(x - 80, y - 64, 160, 20)
            mate = c.role == DUCK and (pid in c.mates or pid == c.me)
            p.setPen(QColor(0, 0, 0, 160))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(r.translated(dx, dy), name, QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.setPen(QColor("#FF6B6B" if mate else "#FFFFFF"))
            p.drawText(r, name, QTextOption(Qt.AlignmentFlag.AlignCenter))
            if pid != c.me and c.lag_of.get(pid):             # 掉线中:头顶一个转圈的小标记
                self._lag_badge(p, x, y - 82, now)
            if pid in c.checked:                              # 侦探查过的人:头顶标出结果(只有侦探看得到)
                duck = c.checked[pid]
                tag = QRectF(x - 34, y - 86, 68, 18)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#E03131" if duck else "#2B8A3E"))
                p.drawRoundedRect(tag, 9, 9)
                f2 = QFont(f)
                f2.setPixelSize(11)
                p.setFont(f2)
                p.setPen(QColor("#FFFFFF"))
                p.drawText(tag, "坏鸭!" if duck else "不是坏鸭", QTextOption(Qt.AlignmentFlag.AlignCenter))
                p.setFont(f)

    def _lag_badge(self, p: QPainter, x: float, y: float, now: float) -> None:
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(QRectF(x - 34, y - 9, 68, 18), 9, 9)
        p.setPen(QPen(QColor("#FFD43B"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(x - 29, y - 5, 10, 10), int(-now * 360 * 16) % (360 * 16), 270 * 16)
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(x - 16, y - 9, 48, 18), "掉线中", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.restore()

    def _paint_fx(self, p: QPainter, c, now: float) -> None:
        keep = []
        for fx in c.fx:
            t = now - fx["t"]
            if t > 1.4:
                continue
            keep.append(fx)
            if t < 0.35:                                      # 一道斜着的白光 + 一圈冲击波
                k = t / 0.35
                p.save()
                p.setOpacity(1 - k)
                p.translate(fx["x"], fx["y"])
                p.rotate(-30)
                p.setPen(QPen(QColor("#FFFFFF"), 6 * (1 - k) + 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(-50 * k - 10, 0), QPointF(50 * k + 10, 0))
                p.rotate(60)
                p.drawLine(QPointF(-40 * k - 8, 0), QPointF(40 * k + 8, 0))
                p.setPen(QPen(QColor(255, 107, 107), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(0, 0), 20 + 60 * k, 20 + 60 * k)
                p.restore()
            for k in range(10):
                a = k / 10 * math.tau
                d = 20 + t * 70
                p.save()
                p.setOpacity(max(0.0, 1 - t / 1.4))
                p.translate(fx["x"] + math.cos(a) * d, fx["y"] + math.sin(a) * d * 0.6 + t * t * 30)
                p.rotate(t * 200 + k * 30)
                p.setPen(QPen(QColor("#ADB5BD"), 1))
                p.setBrush(QColor(fx["c"]) if k % 2 else QColor("#FFFFFF"))
                p.drawEllipse(QPointF(0, 0), 7, 2.6)
                p.restore()
        c.fx = keep

    def _paint_fog(self, p: QPainter, c, now: float) -> None:
        """视野之外是黑的:中间一个圆看得清,边缘慢慢变暗。关灯时(好鹅)圆一下子变小。"""
        w, h = self.width(), self.height()
        sx, sy = self.to_screen(c.x, c.y)
        v = (Wd.VISION_DARK if (c.lights_off and c.role != DUCK) else Wd.VISION) * self.scale
        g = QRadialGradient(QPointF(sx, sy), v * 1.15)
        g.setColorAt(0.0, QColor(10, 8, 18, 0))
        g.setColorAt(0.78, QColor(10, 8, 18, 0))
        g.setColorAt(0.92, QColor(10, 8, 18, 170))
        g.setColorAt(1.0, QColor(10, 8, 18, 235))
        path = QPainterPath()
        path.addRect(QRectF(0, 0, w, h))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRect(QRectF(0, 0, w, h))

    def _paint_room_toast(self, p: QPainter, c, now: float) -> None:
        rid = Wd.room_at(c.x, c.y)
        name = Wd.room_name(rid)
        if name != self._room_name[0]:
            self._room_name = (name, now)
        t = now - self._room_name[1]
        if t > 2.2 or rid is None:
            return
        a = min(1.0, t / 0.2, (2.2 - t) / 0.5)
        f = QFont(self.font())
        f.setPixelSize(22)
        f.setWeight(QFont.Weight.Bold)
        p.save()
        p.setOpacity(max(0.0, a))
        p.setFont(f)
        r = QRectF(0, self.height() * 0.2 - 20, self.width(), 40)
        p.setPen(QColor(0, 0, 0, 150))
        p.drawText(r.translated(0, 2), name, QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r, name, QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.restore()


def paint_minimap(p: QPainter, rect: QRectF, c, now: float) -> None:
    """小地图(M 键):房间轮廓、自己的位置、没做的任务、关灯时的电闸、锁着的门。幽灵还能看到所有人。"""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 50), 1))
    p.setBrush(QColor(20, 16, 30, 225))
    p.drawRoundedRect(rect, 16, 16)
    pad = 16
    s = min((rect.width() - pad * 2) / Wd.W, (rect.height() - pad * 2 - 18) / Wd.H)
    ox = rect.x() + (rect.width() - Wd.W * s) / 2
    oy = rect.y() + 26 + (rect.height() - 26 - Wd.H * s) / 2
    f = QFont()
    f.setPixelSize(12)
    f.setWeight(QFont.Weight.Bold)
    p.setFont(f)
    p.setPen(QColor("#DEE2E6"))
    p.drawText(QRectF(rect.x(), rect.y() + 6, rect.width(), 18), "地图(M 关闭)", QTextOption(Qt.AlignmentFlag.AlignCenter))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#5B4B6E"))
    for r in Wd.WALKABLE:
        p.drawRoundedRect(QRectF(ox + (r.x - 8) * s, oy + (r.y - 8) * s, (r.w + 16) * s, (r.h + 16) * s), 4, 4)
    p.setBrush(QColor("#CFC6DA"))
    for r in Wd.HALLS:
        p.drawRect(QRectF(ox + r.x * s, oy + r.y * s, r.w * s, r.h * s))
    f.setPixelSize(10)
    p.setFont(f)
    here = Wd.room_at(c.x, c.y)
    for rid, name, r, col in Wd.ROOMS:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col).darker(108) if rid == here else QColor(col))
        p.drawRoundedRect(QRectF(ox + r.x * s, oy + r.y * s, r.w * s, r.h * s), 3, 3)
        p.setPen(QColor(60, 50, 70))
        p.drawText(QRectF(ox + r.x * s, oy + r.y * s, r.w * s, r.h * s), name, QTextOption(Qt.AlignmentFlag.AlignCenter))
    for rid in c.locked:
        for d in Wd.DOORS.get(rid, ()):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FA5252"))
            p.drawRect(QRectF(ox + d.x * s, oy + d.y * s, max(3, d.w * s), max(3, d.h * s)))
    for tid in c.tasks:
        if tid in c.done:
            continue
        t = Wd.TASK_BY_ID[tid]
        p.setPen(QPen(QColor("#E8A200"), 1))
        p.setBrush(QColor("#FFD43B"))
        p.drawEllipse(QPointF(ox + t[3] * s, oy + t[4] * s), 4.5, 4.5)
    if c.lights_off:
        _r, sx, sy = Wd.LIGHT_SWITCH
        a = 0.5 + 0.5 * math.sin(now * 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 212, 59, int(120 + 120 * a)))
        p.drawEllipse(QPointF(ox + sx * s, oy + sy * s), 7, 7)
    bx, by = Wd.BUTTON
    p.setBrush(QColor("#FA5252"))
    p.drawEllipse(QPointF(ox + bx * s, oy + by * s), 4, 4)
    if not c.alive:                                          # 幽灵:所有人的位置
        for pid in c.visible_ids():
            pos = c.pos_of(pid, now)
            if pos is not None:
                p.setPen(QPen(QColor(0, 0, 0, 120), 1))
                p.setBrush(QColor(c.color(pid)))
                p.drawEllipse(QPointF(ox + pos[0] * s, oy + pos[1] * s), 4, 4)
    pulse = 1 + 0.25 * math.sin(now * 6)
    p.setPen(QPen(QColor("#FFFFFF"), 2))
    p.setBrush(QColor(c.color(c.me)))
    p.drawEllipse(QPointF(ox + c.x * s, oy + c.y * s), 5.5 * pulse, 5.5 * pulse)
    p.restore()
