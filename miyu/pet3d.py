"""
密语 3.0 · 2.5D 潮玩粘土宠物渲染引擎、视线跟随、Q弹捏脸物理与微缩景深小窝(Diorama)

核心原理:
  · 纯 QPainter 程序化三维球体 / 椭球投影 + 体积次表面散射光影(Claymorphism 盲盒潮玩质感),零 OpenGL / WebEngine 依赖
  · 真实三维偏航角 / 俯仰角(yaw / pitch):鼠标移动或打字时,耳朵、后脑尾巴、立体口鼻垫、瞳孔高光与 50+ 件装扮按深度产生真实视差
  · 二阶弹簧阻尼物理(Spring-Damper):敲键、跳跃落地产生体积守恒挤压回弹(Squash & Stretch);支持按住宠物直接"拉年糕"捏脸
  · 基因花色(暹罗 / 三花 / 奶牛 / 樱花 / 雪白 / 摩卡)、异瞳系统与 2.5D 景深小窝底座
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

COATS = [
    ("classic", "经典原色", 1),
    ("siamese", "暹罗重点色", 3),
    ("calico", "三花斑点", 5),
    ("tuxedo", "黑白奶牛", 7),
    ("sakura", "樱花奶霜", 11),
    ("snow", "极地雪绒", 15),
    ("mocha", "焦糖摩卡", 19),
]
COAT_BY_ID = {c[0]: c for c in COATS}

EYE_STYLES = [
    ("obsidian", "黑曜石", 1, ("#2C221E", "#2C221E")),
    ("amber", "琥珀金", 2, ("#D97706", "#D97706")),
    ("sapphire", "星空蓝", 4, ("#2563EB", "#2563EB")),
    ("emerald", "薄荷绿", 6, ("#059669", "#059669")),
    ("ruby", "蜜桃粉", 9, ("#E11D48", "#E11D48")),
    ("hetero", "鸳鸯异瞳", 12, ("#2563EB", "#D97706")),
]
EYE_BY_ID = {e[0]: e for e in EYE_STYLES}

ROOMS = [
    ("none", "简约透明", 1),
    ("cushion", "阳光软垫", 1),
    ("desk", "极客桌搭", 4),
    ("onsen", "柚子温泉", 8),
    ("garden", "森系花房", 14),
]
ROOM_BY_ID = {r[0]: r for r in ROOMS}

COAT_PALETTE = {
    "sakura": ("#FFD6E5", "#FFACC7"),
    "snow": ("#F8FAFC", "#CBD5E1"),
    "mocha": ("#B08968", "#7F5539"),
}


def shade_color(c: QColor, factor: float) -> QColor:
    """factor > 0 往暖白提亮, < 0 往深色压暗(带一点暖紫环境色偏,更有潮玩手办感)。"""
    r, g, b, a = c.red(), c.green(), c.blue(), c.alpha()
    if factor >= 0:
        k = min(1.0, factor)
        return QColor(int(r + (255 - r) * k), int(g + (252 - g) * k * 0.98), int(b + (248 - b) * k * 0.95), a)
    k = min(1.0, -factor)
    return QColor(int(r * (1 - k * 0.78)), int(g * (1 - k * 0.84)), int(b * (1 - k * 0.72)), a)


def clay_brush(cx: float, cy: float, rx: float, ry: float, base: QColor, yaw: float = 0.0,
               pitch: float = 0.0) -> QBrush:
    """生成 2.5D 软萌粘土球体材质渐变:左上柔光高光 + 饱满中间调 + 右下体积暗部 + 微弱边缘反光。"""
    r = max(rx, ry, 4.0)
    fx = cx - rx * 0.34 + yaw * rx * 0.28
    fy = cy - ry * 0.38 + pitch * ry * 0.24
    grad = QRadialGradient(QPointF(cx, cy), r * 1.12, QPointF(fx, fy))
    grad.setColorAt(0.0, shade_color(base, 0.34))
    grad.setColorAt(0.42, base)
    grad.setColorAt(0.84, shade_color(base, -0.20))
    grad.setColorAt(1.0, shade_color(base, -0.10))       # 边缘一圈轻微漫反射回光(Rim Bounce)
    return QBrush(grad)


def contour_pen(base: QColor, width: float = 1.35) -> QPen:
    """柔和同色系深色轮廓线(替代生硬纯黑描边,白色/浅色动物依然清晰但更软糯)。"""
    c = shade_color(base, -0.52)
    c.setAlpha(215)
    pen = QPen(c, width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


class Pose3D:
    """管理宠物的三维朝向(yaw / pitch)与二阶弹簧果冻物理(挤压回弹 + 鼠标拖拽捏脸)。"""

    def __init__(self) -> None:
        self.yaw = 0.0             # 左右转头弧度 [-0.46, +0.46]
        self.pitch = 0.0           # 上下抬头弧度 [-0.28, +0.28]
        self.target_yaw = 0.0
        self.target_pitch = 0.0
        self.squash = 0.0          # >0 压扁变宽, <0 拉高变瘦
        self.squash_v = 0.0
        self.pinching = False
        self.pinch_x = 0.0         # 捏脸横向拉拽偏移 [-28, +28]
        self.pinch_y = 0.0         # 捏脸纵向拉拽偏移 [-20, +20]
        self.rebound_x = 0.0
        self.rebound_vx = 0.0
        self.rebound_y = 0.0
        self.rebound_vy = 0.0
        self._last_t = time.monotonic()

    def impulse(self, amount: float = 0.14) -> None:
        """敲键盘 / 跳跃 / 摸头时给一个软体果冻脉冲。"""
        self.squash_v = max(-2.6, min(2.6, self.squash_v + amount * 8.5))

    def start_pinch(self) -> None:
        self.pinching = True
        self.pinch_x = self.pinch_y = 0.0

    def move_pinch(self, dx: float, dy: float) -> None:
        if not self.pinching:
            return
        # 阻尼非线性限幅:越往外拉阻力越大,像捏糯米团子
        self.pinch_x = math.copysign(min(28.0, abs(dx) ** 0.82 * 1.5), dx)
        self.pinch_y = math.copysign(min(18.0, abs(dy) ** 0.82 * 1.2), dy)
        self.target_yaw = max(-0.46, min(0.46, self.pinch_x / 52.0))
        self.target_pitch = max(-0.28, min(0.28, self.pinch_y / 52.0))

    def end_pinch(self) -> float:
        """松手回弹,返回刚才拉拽的幅度(够大时触发害羞/抗议台词)。"""
        if not self.pinching:
            return 0.0
        self.pinching = False
        dist = math.hypot(self.pinch_x, self.pinch_y)
        self.rebound_x, self.rebound_y = self.pinch_x, self.pinch_y
        self.rebound_vx, self.rebound_vy = -self.pinch_x * 9.0, -self.pinch_y * 9.0
        self.pinch_x = self.pinch_y = 0.0
        self.impulse(min(0.24, dist * 0.008))
        return dist

    def look_at(self, rel_x: float, rel_y: float) -> None:
        """根据鼠标相对宠物中心的偏移计算目标 3D 视线角。"""
        if self.pinching:
            return
        self.target_yaw = max(-0.44, min(0.44, math.atan2(rel_x, 190.0)))
        self.target_pitch = max(-0.25, min(0.25, math.atan2(rel_y, 210.0)))

    def step(self, now: float, sleeping: bool = False) -> bool:
        """推进一帧物理。返回是否仍在明显运动(用于动态调高帧率)。"""
        dt = max(0.004, min(0.08, now - self._last_t))
        self._last_t = now
        if sleeping and not self.pinching:
            ty, tp = math.sin(now * 0.5) * 0.06, 0.12
        else:
            ty, tp = self.target_yaw, self.target_pitch
        k_rot = min(1.0, dt * 10.5)
        self.yaw += (ty - self.yaw) * k_rot
        self.pitch += (tp - self.pitch) * k_rot

        # 二阶欠阻尼弹簧:挤压拉伸
        acc = -150.0 * self.squash - 12.5 * self.squash_v
        self.squash_v += acc * dt
        self.squash = max(-0.26, min(0.28, self.squash + self.squash_v * dt))
        if abs(self.squash) < 0.002 and abs(self.squash_v) < 0.01:
            self.squash = self.squash_v = 0.0

        # 捏脸松手后的 Q 弹回震
        if not self.pinching and (abs(self.rebound_x) > 0.08 or abs(self.rebound_vx) > 0.4
                                  or abs(self.rebound_y) > 0.08 or abs(self.rebound_vy) > 0.4):
            ax = -185.0 * self.rebound_x - 11.5 * self.rebound_vx
            ay = -185.0 * self.rebound_y - 11.5 * self.rebound_vy
            self.rebound_vx += ax * dt
            self.rebound_vy += ay * dt
            self.rebound_x += self.rebound_vx * dt
            self.rebound_y += self.rebound_vy * dt
        elif not self.pinching:
            self.rebound_x = self.rebound_y = self.rebound_vx = self.rebound_vy = 0.0

        moving = (self.pinching or abs(self.squash) > 0.005 or abs(self.rebound_x) > 0.15
                  or abs(ty - self.yaw) > 0.015 or abs(tp - self.pitch) > 0.015)
        return moving

    def stretch_offset(self) -> tuple[float, float]:
        return (self.pinch_x + self.rebound_x, self.pinch_y + self.rebound_y)


def resolve_colors(species_spec: dict, coat: str) -> tuple[QColor, QColor]:
    if coat in COAT_PALETTE:
        b, i = COAT_PALETTE[coat]
        return QColor(b), QColor(i)
    if coat == "tuxedo":
        return QColor("#2B2D35"), QColor("#F8FAFC")
    if coat == "siamese":
        return QColor("#F6EAD7"), QColor("#6C4A3A")
    return QColor(species_spec["body"]), QColor(species_spec["inner"])


def paint_ao_shadow(p: QPainter, cx: float, edge_y: float, radius: float = 34.0) -> None:
    """宠物趴在输入框/底座边缘时的柔和环境光接触阴影(AO)。"""
    g = QRadialGradient(QPointF(cx, edge_y + 1.0), radius)
    g.setColorAt(0.0, QColor(20, 15, 30, 68))
    g.setColorAt(0.65, QColor(20, 15, 30, 26))
    g.setColorAt(1.0, QColor(20, 15, 30, 0))
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(QPointF(cx, edge_y + 1.0), radius, 5.5)
    p.restore()


def paint_3d_tail(p: QPainter, species: str, body: QColor, inner: QColor, now: float,
                  cx: float, cy: float, yaw: float) -> None:
    """身后的 3D 小尾巴:转头时按负视差露出更多,平时轻轻摇晃。"""
    wag = math.sin(now * 3.8) * 6.0
    # 转头向右(yaw>0)时,后脑勺尾巴往左露出来;接近正脸时在右侧轻轻探头
    side = -1.0 if yaw > 0.08 else 1.0
    tx = cx + side * 26.0 - yaw * 14.0
    ty = cy + 12.0
    pen = contour_pen(body, 1.25)
    p.save()
    p.setPen(pen)
    if species in ("fox", "shiba"):
        path = QPainterPath(QPointF(tx - side * 4, ty + 6))
        path.cubicTo(tx + side * 14, ty - 6 + wag * 0.5, tx + side * 22, ty - 18 + wag, tx + side * 14, ty - 24 + wag)
        path.cubicTo(tx + side * 6, ty - 22 + wag * 0.6, tx + side * 2, ty - 8, tx - side * 4, ty + 6)
        p.setBrush(clay_brush(tx + side * 10, ty - 10, 14, 14, body, yaw))
        p.drawPath(path)
        if species == "fox":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFF8F0"))
            p.drawEllipse(QPointF(tx + side * 13, ty - 20 + wag), 5.0, 4.2)
    elif species == "cat":
        path = QPainterPath(QPointF(tx, ty + 6))
        path.cubicTo(tx + side * 16, ty + 2, tx + side * 20, ty - 14 + wag, tx + side * 12, ty - 20 + wag)
        tpen = QPen(shade_color(body, -0.08), 5.2)
        tpen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(tpen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
    elif species in ("bunny", "bear", "capy"):
        p.setBrush(clay_brush(tx + side * 5, ty, 6.5, 6.5, inner if species == "bunny" else body, yaw))
        p.drawEllipse(QPointF(tx + side * 5, ty + wag * 0.2), 6.0, 5.6)
    p.restore()


def paint_3d_ears(p: QPainter, species: str, coat: str, body: QColor, inner: QColor,
                  cx: float, cy: float, yaw: float, pitch: float, wiggle: float) -> None:
    """按 3D 深度顺序绘制双耳:远侧耳缩小后退,近侧耳放大前移。"""
    ear_body = QColor("#5C3D2E") if coat == "siamese" else body
    pen = contour_pen(ear_body, 1.35)
    # 深度排序:yaw > 0 时左耳(-1)更远先画,右耳(+1)更近后画
    order = (-1, 1) if yaw >= 0 else (1, -1)
    for s in order:
        depth = s * yaw                                    # >0 近侧, <0 远侧
        sc = 1.0 + depth * 0.16
        ex = cx + s * 15.5 + yaw * 4.5 - depth * s * 1.8
        ey = cy - 18.5 + pitch * 3.5
        p.save()
        p.translate(ex, ey)
        p.scale(sc, sc)
        p.rotate(s * wiggle + yaw * 8.0)
        p.setPen(pen)
        if species in ("cat", "fox", "shiba"):
            h_top = -20.0 if species == "fox" else (-17.5 if species == "shiba" else -16.5)
            w_out = 12.5 if species == "fox" else 11.0
            ear = QPainterPath(QPointF(-s * 3.5, -2))
            ear.quadTo(s * 3.0, h_top - 2, s * 8.5, h_top)
            ear.quadTo(s * (w_out + 2), -6, s * w_out, 4)
            ear.closeSubpath()
            p.setBrush(clay_brush(s * 4, h_top * 0.45, 11, 12, ear_body, yaw, pitch))
            p.drawPath(ear)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3D251E") if species == "fox" else inner)
            ear_in = QPainterPath(QPointF(0, -3))
            ear_in.lineTo(s * 7.2, h_top + 4.5)
            ear_in.lineTo(s * (w_out - 2.2), 1.5)
            ear_in.closeSubpath()
            p.drawPath(ear_in)
        elif species == "bunny":
            p.rotate(s * 11)
            p.setBrush(clay_brush(0, -14, 7.5, 17, ear_body, yaw, pitch))
            p.drawEllipse(QPointF(0, -14), 7.2, 17.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(inner)
            p.drawEllipse(QPointF(0, -13), 3.6, 11.8)
        elif species == "capy":
            # 卡皮巴拉标志性的向后抿的小圆豆耳
            p.rotate(s * 28)
            p.setBrush(clay_brush(s * 4, -5, 6.5, 5.0, shade_color(ear_body, -0.18), yaw, pitch))
            p.drawEllipse(QPointF(s * 4, -5), 6.2, 4.6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(shade_color(ear_body, -0.35))
            p.drawEllipse(QPointF(s * 4, -5), 3.0, 2.2)
        elif species == "penguin":
            # 小企鹅没有外耳廓,两侧有圆润的小鳍翅微动
            pass
        else:                                              # 小熊
            p.setBrush(clay_brush(s * 5, -3, 9.2, 9.2, ear_body, yaw, pitch))
            p.drawEllipse(QPointF(s * 5, -3), 9.2, 9.2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(inner)
            p.drawEllipse(QPointF(s * 5, -3), 4.6, 4.6)
        p.restore()


def paint_3d_head_coat(p: QPainter, species: str, coat: str, body: QColor, inner: QColor,
                       cx: float, cy: float, yaw: float, pitch: float, stretch_x: float = 0.0,
                       stretch_y: float = 0.0) -> None:
    """绘制 3D 潮玩粘土圆润头部、脸颊高光与品种/基因花纹(暹罗脸、三花斑、柴犬白脸、企鹅白肚、卡皮巴拉宽吻)。"""
    hx = cx + yaw * 3.2 + stretch_x * 0.48
    hy = cy + 6.0 + pitch * 2.2 + stretch_y * 0.38
    rx = 31.5 + abs(stretch_x) * 0.28 + (2.0 if species == "capy" else 0.0)
    ry = 28.2 + stretch_y * 0.16
    pen = contour_pen(body, 1.4)
    p.save()
    p.setPen(pen)
    p.setBrush(clay_brush(hx, hy, rx, ry, body, yaw, pitch))
    if species == "fox":
        # 小狐狸两侧蓬松的腮毛轮廓
        path = QPainterPath()
        path.addEllipse(QPointF(hx, hy), rx, ry)
        for s in (-1, 1):
            tuft = QPainterPath()
            tuft.addEllipse(QPointF(hx + s * (rx - 4) + yaw * 3, hy + 5), 8.5, 6.0)
            path = path.united(tuft)
        p.drawPath(path)
    else:
        p.drawEllipse(QPointF(hx, hy), rx, ry)

    # 裁剪在头部球面内部画花纹与柔光高光
    clip = QPainterPath()
    clip.addEllipse(QPointF(hx, hy), rx - 0.8, ry - 0.8)
    p.setClipPath(clip)
    p.setPen(Qt.PenStyle.NoPen)

    fx = cx + yaw * 9.5 + stretch_x * 0.72
    fy = cy + pitch * 5.5 + stretch_y * 0.55

    if species in ("shiba", "fox"):
        # 柴犬 / 小狐狸奶油白下半脸 + 豆豆眉
        p.setBrush(QColor("#FFF7EB"))
        p.drawEllipse(QPointF(fx - 11, fy + 10), 15, 14)
        p.drawEllipse(QPointF(fx + 11, fy + 10), 15, 14)
        p.drawEllipse(QPointF(fx, fy + 14), 16, 13)
        for s in (-1, 1):
            p.drawEllipse(QPointF(fx + s * 8.5, fy - 13.5), 3.0, 2.0)
    elif species == "penguin":
        # 小企鹅心形雪白脸庞 + 肚皮
        p.setBrush(QColor("#F8FAFC"))
        p.drawEllipse(QPointF(fx - 9, fy + 1), 13.5, 16)
        p.drawEllipse(QPointF(fx + 9, fy + 1), 13.5, 16)
        p.drawEllipse(QPointF(fx, fy + 12), 21, 17)
    elif coat == "siamese":
        # 暹罗挖煤重点色柔和渐变面罩
        mg = QRadialGradient(QPointF(fx, fy - 1), 19.0)
        mg.setColorAt(0.0, QColor(92, 61, 46, 210))
        mg.setColorAt(0.65, QColor(115, 78, 60, 120))
        mg.setColorAt(1.0, QColor(115, 78, 60, 0))
        p.setBrush(QBrush(mg))
        p.drawEllipse(QPointF(fx, fy - 1), 19.5, 15.5)
    elif coat == "calico":
        # 三花猫:左额暖橘斑 + 右耳根深咖斑
        p.setBrush(QColor(245, 159, 67, 195))
        p.drawEllipse(QPointF(hx - 18 + yaw * 4, hy - 18), 14, 11)
        p.setBrush(QColor(74, 58, 52, 185))
        p.drawEllipse(QPointF(hx + 19 + yaw * 4, hy - 16), 13, 10)
    elif coat == "tuxedo":
        # 奶牛黑白:鼻梁到嘴边雪白倒 V
        tri = QPainterPath(QPointF(fx, fy - 10))
        tri.lineTo(fx - 18, hy + 26)
        tri.lineTo(fx + 18, hy + 26)
        tri.closeSubpath()
        p.setBrush(QColor("#F8FAFC"))
        p.drawPath(tri)

    # 3D 潮玩左上高光月牙(让球体瞬间立体水润)
    hl = QRadialGradient(QPointF(hx - rx * 0.38 + yaw * 4, hy - ry * 0.44 + pitch * 3), 14)
    hl.setColorAt(0.0, QColor(255, 255, 255, 105))
    hl.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(hl))
    p.drawEllipse(QPointF(hx - rx * 0.36 + yaw * 4, hy - ry * 0.42 + pitch * 3), 13, 8.5)
    p.restore()


def paint_3d_muzzle(p: QPainter, species: str, body: QColor, fx: float, my: float, yaw: float,
                    pitch: float) -> None:
    """立体凸出的口鼻小肉垫(比眼睛平面更靠前,随 yaw 产生更强正视差)。"""
    mx = fx + yaw * 2.6
    p.save()
    if species == "capy":
        # 卡皮巴拉宽敦敦的焦糖大鼻子 + 两个小鼻孔
        snout = shade_color(body, -0.22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(clay_brush(mx, my - 2.0, 9.5, 7.5, snout, yaw, pitch))
        p.drawRoundedRect(QRectF(mx - 8.5, my - 7.5, 17.0, 12.0), 6.5, 6.5)
        p.setBrush(shade_color(body, -0.58))
        for s in (-1, 1):
            p.drawEllipse(QPointF(mx + s * 3.8, my - 3.6), 1.4, 1.9)
    elif species == "penguin":
        # 小企鹅圆鼓鼓的金黄立体鸟喙
        beak = QColor("#FFB703")
        p.setPen(contour_pen(beak, 1.0))
        p.setBrush(clay_brush(mx, my - 1.5, 6.5, 4.2, beak, yaw, pitch))
        p.drawEllipse(QPointF(mx, my - 1.5), 6.0, 3.8)
    else:
        # 猫 / 兔 / 熊 / 柴犬 / 狐狸:微微鼓起的浅奶油立体吻垫 + 小三角鼻头
        pad = QColor("#FFFDF9") if species in ("shiba", "fox", "bunny") else shade_color(body, 0.28)
        pad.setAlpha(185)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pad)
        p.drawEllipse(QPointF(mx, my - 0.3), 7.6, 5.2)
        nose_col = QColor("#FF8FA3") if species in ("cat", "bunny") else QColor("#3D2B24")
        p.setBrush(nose_col)
        p.drawEllipse(QPointF(mx, my - 2.6), 2.3, 1.6)
    p.restore()


def paint_3d_eye(p: QPainter, x: float, y: float, side_idx: int, eye_style: str,
                 yaw: float, pitch: float, capy: bool = False) -> None:
    """水汪汪的 3D 潮玩眼睛:虹膜渐变 + 视线追踪瞳孔 + 双层星星高光;卡皮巴拉自带半眯松弛眼睑。"""
    spec = EYE_BY_ID.get(eye_style, EYE_STYLES[0])[3]
    col = QColor(spec[0 if side_idx == 0 else 1])
    gx, gy = yaw * 1.9, pitch * 1.5
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    # 眼眶柔和立体浅影
    p.setBrush(QColor(0, 0, 0, 26))
    p.drawEllipse(QPointF(x, y + 0.6), 3.6, 3.9)
    # 饱满深邃底色 + 下半虹膜透光渐变
    iris = QRadialGradient(QPointF(x + gx, y + gy + 1.4), 3.6)
    iris.setColorAt(0.0, shade_color(col, 0.36))
    iris.setColorAt(0.55, col)
    iris.setColorAt(1.0, shade_color(col, -0.55))
    p.setBrush(QBrush(iris))
    p.drawEllipse(QPointF(x + gx * 0.55, y + gy * 0.55), 3.15, 3.5)
    # 瞳孔中心
    p.setBrush(shade_color(col, -0.68))
    p.drawEllipse(QPointF(x + gx * 0.85, y + gy * 0.85), 1.45, 1.65)
    # 主高光 + 副高光
    p.setBrush(QColor(255, 255, 255, 242))
    p.drawEllipse(QPointF(x - 0.95 + gx * 0.3, y - 1.2 + gy * 0.3), 1.1, 1.1)
    p.setBrush(QColor(255, 255, 255, 165))
    p.drawEllipse(QPointF(x + 1.0 + gx * 0.3, y + 1.1 + gy * 0.3), 0.55, 0.55)
    if capy:
        # 卡皮巴拉灵魂半耷拉松弛上眼皮
        p.setPen(QPen(QColor("#5C3D28"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x - 3.6, y - 1.2), QPointF(x + 3.6, y - 1.2))
    p.restore()


def paint_capy_tangerine(p: QPainter, cx: float, top_y: float, now: float, yaw: float) -> None:
    """卡皮巴拉(或头顶蜜橘装扮):头顶稳稳顶着一颗立体小蜜橘,带绿叶晃动。"""
    tx = cx + yaw * 6.8
    ty = top_y - 3.5 + math.sin(now * 2.0) * 0.5
    org = QColor("#FF922B")
    p.save()
    p.setPen(contour_pen(org, 1.1))
    p.setBrush(clay_brush(tx, ty, 7.5, 6.2, org, yaw))
    p.drawEllipse(QPointF(tx, ty), 7.2, 5.8)
    # 小绿叶
    leaf = QPainterPath(QPointF(tx, ty - 5.5))
    leaf.quadTo(tx + 5.5, ty - 10.5, tx + 7.5, ty - 5.2)
    leaf.quadTo(tx + 3.5, ty - 3.5, tx, ty - 5.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#51CF66"))
    p.drawPath(leaf)
    p.setBrush(QColor(255, 255, 255, 130))
    p.drawEllipse(QPointF(tx - 2.4, ty - 2.0), 1.8, 1.2)
    p.restore()


def paint_diorama(p: QPainter, room: str, w: float, h: float, edge_y: float, now: float,
                  dark: bool = False) -> None:
    """在衣橱预览、桌面陪伴或好友合照里绘制 2.5D 微缩宠物小窝景深场景。"""
    if not room or room == "none":
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    box = QRectF(2, 2, w - 4, h - 4)
    clip = QPainterPath()
    clip.addRoundedRect(box, 14, 14)
    p.setClipPath(clip)

    hour = time.localtime().tm_hour
    night = hour >= 19 or hour < 6

    if room == "cushion":
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor("#1E2436" if night or dark else "#FFF6EC"))
        bg.setColorAt(1, QColor("#2B3147" if night or dark else "#FDE8D7"))
        p.fillRect(box, QBrush(bg))
        # 背景小窗:白天蓝天云朵,夜晚弯月星辰
        win = QRectF(22, 10, 56, 44)
        p.setPen(QPen(QColor("#D8B49A" if not dark else "#5C647D"), 2.0))
        p.setBrush(QColor("#151C33" if night else "#BDE0FE"))
        p.drawRoundedRect(win, 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        if night:
            p.setBrush(QColor("#FFE066"))
            p.drawEllipse(QPointF(40, 24), 5.5, 5.5)
            p.setBrush(QColor("#151C33"))
            p.drawEllipse(QPointF(42.5, 22.5), 4.8, 4.8)
            p.setBrush(QColor("#FFFFFF"))
            for sx, sy in ((58, 20), (66, 32), (34, 38)):
                p.drawEllipse(QPointF(sx, sy), 1.1, 1.1)
        else:
            p.setBrush(QColor(255, 255, 255, 220))
            cx_ = 36 + math.sin(now * 0.4) * 5
            p.drawEllipse(QPointF(cx_, 32), 10, 5.5)
            p.drawEllipse(QPointF(cx_ + 7, 30), 7, 5)
        # 窗格十字线
        p.setPen(QPen(QColor("#D8B49A" if not dark else "#5C647D"), 1.5))
        p.drawLine(QPointF(50, 10), QPointF(50, 54))
        p.drawLine(QPointF(22, 32), QPointF(78, 32))
        # 蓬松针织软垫底座
        cush = QRectF(w * 0.5 - 78, edge_y - 6, 156, 22)
        p.setPen(contour_pen(QColor("#FFADAD"), 1.2))
        p.setBrush(clay_brush(w * 0.5, edge_y + 4, 80, 16, QColor("#FFCAD4")))
        p.drawRoundedRect(cush, 11, 11)

    elif room == "desk":
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor("#161925"))
        bg.setColorAt(1, QColor("#23293D"))
        p.fillRect(box, QBrush(bg))
        # 氛围霓虹灯带
        glow = QLinearGradient(0, edge_y - 24, w, edge_y - 24)
        glow.setColorAt(0, QColor(94, 234, 212, 50))
        glow.setColorAt(0.5, QColor(168, 85, 247, 65))
        glow.setColorAt(1, QColor(59, 130, 246, 50))
        p.fillRect(QRectF(0, edge_y - 36, w, 36), QBrush(glow))
        # 胡桃木桌面 + 迷你 RGB 键盘 + 冒热气的咖啡杯
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4A3525"))
        p.drawRect(QRectF(0, edge_y - 1, w, h - edge_y + 2))
        kb = QRectF(w * 0.5 - 64, edge_y + 1, 108, 12)
        p.setBrush(QColor("#2B3040"))
        p.drawRoundedRect(kb, 3, 3)
        for i in range(9):
            hue = int((i * 36 + now * 80) % 360)
            p.setBrush(QColor.fromHsv(hue, 180, 255))
            p.drawRoundedRect(QRectF(kb.left() + 5 + i * 11, kb.top() + 3, 8, 5), 1.2, 1.2)
        # 左边小马克杯与袅袅热气
        mug = QRectF(32, edge_y - 17, 16, 18)
        p.setBrush(QColor("#F8FAFC"))
        p.drawRoundedRect(mug, 3, 3)
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.3))
        for k in (-3, 3):
            sy = (now * 12 + (k + 3) * 4) % 14
            p.drawLine(QPointF(40 + k, edge_y - 20 - sy), QPointF(41 + k + math.sin(now * 3 + k) * 2, edge_y - 26 - sy))

    elif room == "onsen":
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor("#2C3E35" if dark else "#E6F2EA"))
        bg.setColorAt(1, QColor("#3A5246" if dark else "#CFE5D6"))
        p.fillRect(box, QBrush(bg))
        # 桧木温泉池边 + 碧蓝温泉水波 + 漂浮小柚子
        water = QRectF(14, edge_y - 5, w - 28, h - edge_y + 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#74C0FC" if not dark else "#3B82A6"))
        p.drawRoundedRect(water, 8, 8)
        p.setPen(QPen(QColor("#B07D4F"), 3.0))
        p.drawLine(QPointF(12, edge_y - 4), QPointF(w - 12, edge_y - 4))
        # 漂浮柚子
        yx = 44 + math.sin(now * 1.4) * 5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFD43B"))
        p.drawEllipse(QPointF(yx, edge_y + 4), 6.5, 5.0)
        # 温泉蒸汽云团
        for i in range(4):
            ph = (now * 0.35 + i * 0.25) % 1.0
            p.setBrush(QColor(255, 255, 255, int(95 * math.sin(math.pi * ph))))
            p.drawEllipse(QPointF(42 + i * 62 + math.sin(now + i) * 6, edge_y - 12 - ph * 38), 14, 8)

    elif room == "garden":
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor("#1C2E24" if dark else "#E9F7EF"))
        bg.setColorAt(1, QColor("#264032" if dark else "#D4EFDF"))
        p.fillRect(box, QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#74C69D" if not dark else "#40916C"))
        p.drawEllipse(QPointF(w * 0.5, edge_y + 10), w * 0.58, 20)
        # 两朵小蘑菇 + 浮动花粉光尘
        for mx, col in ((38, "#FF6B6B"), (w - 42, "#FFA94D")):
            p.setBrush(QColor("#FFF3E0"))
            p.drawRoundedRect(QRectF(mx - 2.5, edge_y - 9, 5, 10), 2, 2)
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(mx, edge_y - 10), 8, 5.5)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(mx - 3, edge_y - 11), 1.4, 1.4)
            p.drawEllipse(QPointF(mx + 2.5, edge_y - 9.5), 1.2, 1.2)
    p.restore()
