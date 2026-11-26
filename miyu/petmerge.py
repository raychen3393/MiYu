"""
密语 3.7 · 「合成大萌宠」2.5D 物理合成小游戏 (合成大西瓜玩法)
  · 用密语 7 种 2.5D 黏土萌宠 + 至臻金豚王做 8 阶圆球物理碰撞合成
  · 鼠标移动瞄准 / 点击或空格下落 / 键盘 A/D 或左右方向键微调
  · 结算自动赢取宠物经验、心情、通行证积分，并写入局域网「合成大萌宠」高分排行榜
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from .dialogs import Dialog
from .fun import OUTLINE, PetGrowth
from .pet3d import clay_brush, contour_pen
from .sound import play_game_sfx
from .theme import T, is_dark
from .ui import button, label

# (等级 0..7, 种类键, 显示名, 半径, 合成得分, 主色, 辅色/腮红)
MERGE_TIERS: list[tuple[int, str, str, float, int, str, str]] = [
    (0, "cat", "奶团猫", 19.0, 2, "#FFE3B3", "#FFB3C6"),
    (1, "bunny", "糯米兔", 25.0, 6, "#FFFFFF", "#FFC2D1"),
    (2, "penguin", "胖企鹅", 31.0, 14, "#4A5A78", "#FFB703"),
    (3, "fox", "赤焰狐", 38.0, 28, "#F28B50", "#FFF3E0"),
    (4, "shiba", "柴犬君", 46.0, 56, "#E8A857", "#FFF8EC"),
    (5, "bear", "蜜糖熊", 55.0, 110, "#B8845A", "#F2D0A9"),
    (6, "capy", "水豚兄", 65.0, 220, "#B58D67", "#FF922B"),
    (7, "capy", "至臻金豚王", 76.0, 500, "#FFD43B", "#FFF3BF"),
]


def paint_merge_ball(p: QPainter, x: float, y: float, tier: int, angle: float = 0.0, scale: float = 1.0) -> None:
    """用 2.5D 黏土质感绘制指定阶数的萌宠圆球。"""
    _lv, sp, _name, r0, _pts, body_hex, accent_hex = MERGE_TIERS[min(tier, len(MERGE_TIERS) - 1)]
    r = r0 * scale
    body = QColor(body_hex)
    acc = QColor(accent_hex)
    p.save()
    p.translate(x, y)
    p.rotate(math.degrees(angle))

    # 软阴影底圈
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 24))
    p.drawEllipse(QPointF(0, r * 0.08), r * 1.02, r * 0.98)

    # 耳朵 / 头顶特色 (画在球体上方稍微探出圆廓内侧,避免碰撞穿模)
    pen = contour_pen(body, max(1.1, r * 0.042))
    p.setPen(pen)
    if sp == "cat":
        for s in (-1, 1):
            ear = QPainterPath(QPointF(s * r * 0.68, -r * 0.56))
            ear.lineTo(s * r * 0.86, -r * 0.96)
            ear.lineTo(s * r * 0.28, -r * 0.86)
            ear.closeSubpath()
            p.setBrush(clay_brush(s * r * 0.55, -r * 0.78, r * 0.3, r * 0.3, body))
            p.drawPath(ear)
    elif sp == "bunny":
        for s in (-1, 1):
            p.setBrush(clay_brush(s * r * 0.36, -r * 0.88, r * 0.24, r * 0.42, body))
            p.drawEllipse(QPointF(s * r * 0.36, -r * 0.85), r * 0.22, r * 0.36)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(acc)
            p.drawEllipse(QPointF(s * r * 0.36, -r * 0.84), r * 0.11, r * 0.22)
            p.setPen(pen)
    elif sp in ("fox", "shiba"):
        for s in (-1, 1):
            ear = QPainterPath(QPointF(s * r * 0.72, -r * 0.52))
            ear.lineTo(s * r * 0.88, -r * 0.98)
            ear.lineTo(s * r * 0.26, -r * 0.84)
            ear.closeSubpath()
            p.setBrush(clay_brush(s * r * 0.55, -r * 0.78, r * 0.3, r * 0.3, body))
            p.drawPath(ear)
    elif sp in ("bear", "capy"):
        for s in (-1, 1):
            p.setBrush(clay_brush(s * r * 0.62, -r * 0.72, r * 0.26, r * 0.26, body))
            p.drawEllipse(QPointF(s * r * 0.62, -r * 0.70), r * 0.24, r * 0.24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(acc if sp == "bear" else body.darker(118))
            p.drawEllipse(QPointF(s * r * 0.62, -r * 0.70), r * 0.12, r * 0.12)
            p.setPen(pen)

    # 主黏土球体
    p.setPen(pen)
    p.setBrush(clay_brush(0, 0, r, r, body))
    p.drawEllipse(QPointF(0, 0), r, r)

    # 企鹅 / 狐狸 / 柴犬浅色脸盘
    if sp == "penguin":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(0, r * 0.14), r * 0.72, r * 0.68)
    elif sp in ("fox", "shiba"):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(acc)
        p.drawEllipse(QPointF(0, r * 0.28), r * 0.68, r * 0.48)

    # 顶部高光点 (增强 2.5D Q弹糖果球质感)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 95))
    p.drawEllipse(QPointF(-r * 0.32, -r * 0.42), r * 0.22, r * 0.12)

    # 眼睛 + 腮红 + 嘴巴
    ey = -r * 0.04
    ex = r * 0.32
    p.setBrush(QColor("#232026"))
    if sp == "capy":
        p.setPen(QPen(QColor("#232026"), max(1.4, r * 0.055), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for s in (-1, 1):
            p.drawLine(QPointF(s * ex - r * 0.12, ey), QPointF(s * ex + r * 0.12, ey))
    else:
        er = max(1.8, r * 0.11)
        for s in (-1, 1):
            p.drawEllipse(QPointF(s * ex, ey), er, er * 1.08)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(s * ex - er * 0.28, ey - er * 0.28), er * 0.34, er * 0.34)
            p.setBrush(QColor("#232026"))

    # 腮红
    for s in (-1, 1):
        p.setBrush(QColor(255, 130, 155, 125))
        p.drawEllipse(QPointF(s * r * 0.48, ey + r * 0.22), r * 0.15, r * 0.09)

    # 嘴/喙
    if sp == "penguin":
        p.setPen(QPen(QColor("#C87D00"), max(1.0, r * 0.03)))
        p.setBrush(QColor("#FFB703"))
        p.drawPolygon([QPointF(-r * 0.16, ey + r * 0.14), QPointF(r * 0.16, ey + r * 0.14), QPointF(0, ey + r * 0.34)])
    else:
        p.setPen(QPen(QColor(OUTLINE), max(1.1, r * 0.045), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        my = ey + r * 0.20
        for s in (-1, 1):
            m = QPainterPath(QPointF(0, my))
            m.quadTo(s * r * 0.08, my + r * 0.12, s * r * 0.16, my)
            p.drawPath(m)

    # 卡皮巴拉小蜜橘 / 至臻金豚王金冠
    if tier == 6:
        p.setPen(QPen(QColor("#C85A00"), 1.1))
        p.setBrush(QColor("#FF922B"))
        p.drawEllipse(QPointF(0, -r * 0.68), r * 0.17, r * 0.13)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#51CF66"))
        p.drawEllipse(QPointF(r * 0.08, -r * 0.81), r * 0.08, r * 0.045)
    elif tier == 7:
        p.setPen(QPen(QColor("#D98200"), 1.3))
        p.setBrush(QColor("#FFE066"))
        cr = QPainterPath(QPointF(-r * 0.28, -r * 0.56))
        cr.lineTo(-r * 0.34, -r * 0.84)
        cr.lineTo(-r * 0.12, -r * 0.70)
        cr.lineTo(0, -r * 0.90)
        cr.lineTo(r * 0.12, -r * 0.70)
        cr.lineTo(r * 0.34, -r * 0.84)
        cr.lineTo(r * 0.28, -r * 0.56)
        cr.closeSubpath()
        p.drawPath(cr)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FF6B8A"))
        p.drawEllipse(QPointF(0, -r * 0.66), r * 0.07, r * 0.07)
    p.restore()


class _MergeBall:
    __slots__ = ("x", "y", "vx", "vy", "tier", "r", "angle", "av", "born", "pop")

    def __init__(self, x: float, y: float, tier: int, pop: float = 0.0) -> None:
        self.x, self.y = x, y
        self.vx, self.vy = 0.0, 0.0
        self.tier = tier
        self.r = MERGE_TIERS[tier][3]
        self.angle = 0.0
        self.av = 0.0
        self.born = time.monotonic()
        self.pop = pop


class _TierStrip(QWidget):
    """顶部 8 阶萌宠合成进化路线条。"""
    H = 38

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self.max_tier = 0

    def set_max_tier(self, t: int) -> None:
        if t != self.max_tier:
            self.max_tier = t
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        dark = is_dark()
        p.setPen(QPen(QColor(255, 255, 255, 36) if dark else QColor(120, 130, 170, 45), 1.0))
        p.setBrush(QColor(255, 255, 255, 16) if dark else QColor(255, 255, 255, 180))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, self.H - 1), 12, 12)
        n = len(MERGE_TIERS)
        step = (w - 28) / max(1, n)
        for i in range(n):
            cx = 14 + step * (i + 0.5)
            cy = self.H * 0.5
            r0 = MERGE_TIERS[i][3]
            sc = min(0.52, (9.5 + i * 0.55) / r0)
            p.save()
            if i > self.max_tier + 1:
                p.setOpacity(0.50)
            paint_merge_ball(p, cx, cy, i, 0.0, sc)
            p.restore()
            if i < n - 1:
                ax = cx + step * 0.5
                p.setPen(QPen(QColor(T["sub"]), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(ax - 3, cy - 2.5), QPointF(ax + 1.5, cy))
                p.drawLine(QPointF(ax - 3, cy + 2.5), QPointF(ax + 1.5, cy))
        p.end()


class _MergePetStage(QWidget):
    """合成大萌宠物理画布(3.8 升级:3 道具 + 连锁倍率 + 震屏 + 音效)。"""
    score_changed = Signal(int, int)       # (当前分, 最高合成阶数)
    finished = Signal(int, int)            # (最终分, 最高阶数)
    tools_changed = Signal()

    W, H = 400, 480
    LEFT, RIGHT, BOTTOM = 18.0, 382.0, 466.0
    DANGER_Y = 88.0
    DROP_Y = 44.0
    GRAVITY = 1080.0

    def __init__(self, parent=None, win=None) -> None:
        super().__init__(parent)
        self.win = win
        self.setFixedSize(self.W, self.H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.balls: list[_MergeBall] = []
        self.fx: list[list] = []           # [x, y, vx, vy, col, r, life, max_life, text, big]
        self.aim_x = self.W / 2.0
        self.cur_tier = 0
        self.next_tier = 1
        self.score = 0
        self.max_tier = 0
        self.combo = 0
        self._last_merge_t = 0.0
        self._last_drop_t = 0.0
        self._danger_since = 0.0
        self._shake_t = 0.0
        self._shake_amp = 0.0
        self.hammer_left = 1
        self.shake_left = 1
        self.swap_left = 1
        self.hammer_mode = False
        self.running = False
        self.game_over = False
        self._keys: set[int] = set()
        self._last_t = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)
        self.reset()

    def _pick_drop_tier(self) -> int:
        hi = 3 if self.max_tier >= 4 else 2
        return random.choices(range(hi + 1), weights=[38, 32, 20, 10][:hi + 1], k=1)[0]

    def reset(self) -> None:
        self.balls.clear()
        self.fx.clear()
        self.aim_x = self.W / 2.0
        self.cur_tier = random.randint(0, 1)
        self.next_tier = random.randint(0, 2)
        self.score = 0
        self.max_tier = 0
        self.combo = 0
        self._danger_since = 0.0
        self._last_drop_t = 0.0
        self._shake_t = 0.0
        self._shake_amp = 0.0
        self.hammer_left = 1
        self.shake_left = 1
        self.swap_left = 1
        self.hammer_mode = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.running = True
        self.game_over = False
        self._last_t = time.monotonic()
        self._timer.start()
        self.score_changed.emit(0, 0)
        self.tools_changed.emit()
        self.update()

    def toggle_hammer(self) -> None:
        if not self.running or self.game_over or self.hammer_left <= 0:
            return
        self.hammer_mode = not self.hammer_mode
        self.setCursor(Qt.CursorShape.CrossCursor if self.hammer_mode else Qt.CursorShape.ArrowCursor)
        play_game_sfx(self.win, "click", 0.65)
        self.tools_changed.emit()
        self.update()

    def use_shake(self) -> bool:
        if not self.running or self.game_over or self.shake_left <= 0 or not self.balls:
            return False
        self.shake_left -= 1
        self.hammer_mode = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._shake_t = 0.40
        self._shake_amp = 7.5
        for b in self.balls:
            b.vx += random.uniform(-220.0, 220.0)
            b.vy -= random.uniform(190.0, 320.0)
            b.av += random.uniform(-6.0, 6.0)
        self.fx.append([self.W / 2, self.H * 0.45, 0.0, -45.0, "#74C0FC", 0.0, 0.85, 0.85, "🌪️ 摇一摇!", True])
        play_game_sfx(self.win, "boost", 0.75)
        self.tools_changed.emit()
        self.update()
        return True

    def use_swap(self) -> bool:
        if not self.running or self.game_over or self.swap_left <= 0:
            return False
        self.swap_left -= 1
        self.hammer_mode = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        old = self.cur_tier
        hi = 3 if self.max_tier >= 4 else 2
        cands = [t for t in range(hi + 1) if t != old] or [0]
        self.cur_tier = random.choice(cands)
        self.fx.append([self.aim_x, self.DROP_Y + 12, 0.0, -35.0, "#B197FC", 0.0, 0.7, 0.7, "🔀 已换新!", False])
        play_game_sfx(self.win, "pop", 0.75)
        self.tools_changed.emit()
        self.update()
        return True

    def stop(self) -> None:
        self.running = False
        self._timer.stop()

    def drop(self) -> None:
        if not self.running or self.game_over:
            return
        now = time.monotonic()
        if now - self._last_drop_t < 0.34:
            return
        self._last_drop_t = now
        r = MERGE_TIERS[self.cur_tier][3]
        x = max(self.LEFT + r + 1, min(self.RIGHT - r - 1, self.aim_x))
        b = _MergeBall(x, self.DROP_Y, self.cur_tier)
        b.vx = random.uniform(-6.0, 6.0)
        self.balls.append(b)
        self.cur_tier = self.next_tier
        self.next_tier = self._pick_drop_tier()
        play_game_sfx(self.win, "pop", 0.6)
        self.update()

    def mouseMoveEvent(self, e) -> None:
        r = MERGE_TIERS[self.cur_tier][3]
        self.aim_x = max(self.LEFT + r + 1, min(self.RIGHT - r - 1, float(e.position().x())))
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        px, py = float(e.position().x()), float(e.position().y())
        if self.hammer_mode and self.hammer_left > 0 and self.running and not self.game_over:
            hit_idx = -1
            best_d = 1e9
            for idx, b in enumerate(self.balls):
                d = math.hypot(px - b.x, py - b.y)
                if d <= b.r + 8 and d < best_d:
                    best_d = d
                    hit_idx = idx
            if hit_idx >= 0:
                popped = self.balls.pop(hit_idx)
                self.hammer_left -= 1
                self.hammer_mode = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
                col = MERGE_TIERS[popped.tier][5]
                for i in range(14):
                    a = i / 14 * math.tau
                    sp = random.uniform(70, 180)
                    self.fx.append([popped.x, popped.y, math.cos(a) * sp, math.sin(a) * sp - 20, col, 4.5, 0.5, 0.5, "", False])
                self.fx.append([popped.x, popped.y - 8, 0.0, -50.0, "#FF922B", 0.0, 0.8, 0.8, "🪄 砰!", True])
                self._shake_t = 0.16
                self._shake_amp = 4.0
                play_game_sfx(self.win, "boom", 0.65)
                self.tools_changed.emit()
                self.update()
            return
        r = MERGE_TIERS[self.cur_tier][3]
        self.aim_x = max(self.LEFT + r + 1, min(self.RIGHT - r - 1, px))
        self.drop()

    def keyPressEvent(self, e) -> None:
        k = e.key()
        self._keys.add(k)
        if k in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Down, Qt.Key.Key_S):
            self.drop()
        elif k == Qt.Key.Key_Escape and self.hammer_mode:
            self.hammer_mode = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.tools_changed.emit()
            self.update()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:
        self._keys.discard(e.key())
        super().keyReleaseEvent(e)

    def _spawn_merge_fx(self, x: float, y: float, tier: int, pts: int) -> None:
        col = MERGE_TIERS[tier][5]
        cnt = 14 if self.combo >= 2 else 10
        for i in range(cnt):
            a = i / cnt * math.tau + random.uniform(-0.2, 0.2)
            sp = random.uniform(60, 165)
            self.fx.append([x, y, math.cos(a) * sp, math.sin(a) * sp - 25, col, random.uniform(3.2, 5.8), 0.48, 0.48, "", False])
        if self.combo >= 2:
            cols = ["#FF6B8A", "#FF922B", "#FFD43B", "#51CF66", "#339AF0", "#CC5DE8"]
            cc = cols[min(self.combo - 2, len(cols) - 1)]
            self.fx.append([x, y - 16, 0.0, -58.0, cc, 0.0, 0.92, 0.92, f"COMBO ×{self.combo}! +{pts}", True])
            self._shake_t = max(self._shake_t, 0.16)
            self._shake_amp = max(self._shake_amp, min(6.0, 2.2 + self.combo * 0.9))
            play_game_sfx(self.win, "combo", 0.8)
        else:
            self.fx.append([x, y - 10, 0.0, -50.0, "#FFD43B", 0.0, 0.72, 0.72, f"+{pts}", False])
            play_game_sfx(self.win, "merge", 0.72)

    def _step(self) -> None:
        now = time.monotonic()
        dt = min(0.032, max(0.004, now - self._last_t))
        self._last_t = now
        if not self.running:
            return
        if self._shake_t > 0:
            self._shake_t = max(0.0, self._shake_t - dt)

        r_cur = MERGE_TIERS[self.cur_tier][3]
        if Qt.Key.Key_Left in self._keys or Qt.Key.Key_A in self._keys:
            self.aim_x = max(self.LEFT + r_cur + 1, self.aim_x - 280.0 * dt)
        if Qt.Key.Key_Right in self._keys or Qt.Key.Key_D in self._keys:
            self.aim_x = min(self.RIGHT - r_cur - 1, self.aim_x + 280.0 * dt)

        # 1) 积分 + 墙壁/地板碰撞
        for b in self.balls:
            b.vy += self.GRAVITY * dt
            b.vx *= (1.0 - 0.35 * dt)
            b.vy *= (1.0 - 0.15 * dt)
            b.x += b.vx * dt
            b.y += b.vy * dt
            b.angle += b.av * dt
            b.av *= (1.0 - 2.0 * dt)
            if b.pop > 0:
                b.pop = max(0.0, b.pop - dt * 3.8)
            if b.x - b.r < self.LEFT:
                b.x = self.LEFT + b.r
                b.vx = abs(b.vx) * 0.32
            elif b.x + b.r > self.RIGHT:
                b.x = self.RIGHT - b.r
                b.vx = -abs(b.vx) * 0.32
            if b.y + b.r > self.BOTTOM:
                b.y = self.BOTTOM - b.r
                if abs(b.vy) > 35:
                    b.vy = -b.vy * 0.22
                else:
                    b.vy = 0.0
                b.vx *= 0.88
                b.av = b.vx / max(10.0, b.r) * 0.6

        # 2) 多轮圆-圆碰撞与同阶合成
        merged_idx: set[int] = set()
        new_balls: list[_MergeBall] = []
        n = len(self.balls)
        for _iter in range(4):
            for i in range(n):
                if i in merged_idx:
                    continue
                a = self.balls[i]
                for j in range(i + 1, n):
                    if j in merged_idx:
                        continue
                    b = self.balls[j]
                    dx, dy = b.x - a.x, b.y - a.y
                    dist2 = dx * dx + dy * dy
                    min_d = a.r + b.r
                    if dist2 < min_d * min_d:
                        dist = math.sqrt(dist2) if dist2 > 1e-6 else 0.01
                        if a.tier == b.tier and a.tier < len(MERGE_TIERS) - 1:
                            merged_idx.add(i)
                            merged_idx.add(j)
                            nt = a.tier + 1
                            mx = max(self.LEFT + MERGE_TIERS[nt][3] + 1,
                                     min(self.RIGHT - MERGE_TIERS[nt][3] - 1, (a.x + b.x) * 0.5))
                            my = min(self.BOTTOM - MERGE_TIERS[nt][3], (a.y + b.y) * 0.5)
                            nb = _MergeBall(mx, my, nt, pop=1.0)
                            nb.vx = (a.vx + b.vx) * 0.35
                            nb.vy = min(-40.0, (a.vy + b.vy) * 0.35)
                            new_balls.append(nb)
                            if now - self._last_merge_t < 1.35:
                                self.combo += 1
                            else:
                                self.combo = 1
                            self._last_merge_t = now
                            mult = 1.0 + 0.25 * (self.combo - 1)
                            pts = int(round(MERGE_TIERS[nt][4] * mult))
                            self.score += pts
                            self.max_tier = max(self.max_tier, nt)
                            self._spawn_merge_fx(mx, my, nt, pts)
                            self.score_changed.emit(self.score, self.max_tier)
                            break
                        nx, ny = dx / dist, dy / dist
                        overlap = (min_d - dist) * 0.52
                        wa = b.r / min_d
                        wb = a.r / min_d
                        a.x -= nx * overlap * wa
                        a.y -= ny * overlap * wa
                        b.x += nx * overlap * wb
                        b.y += ny * overlap * wb
                        rvx, rvy = b.vx - a.vx, b.vy - a.vy
                        vn = rvx * nx + rvy * ny
                        if vn < 0:
                            imp = -1.18 * vn
                            a.vx -= imp * nx * wa
                            a.vy -= imp * ny * wa
                            b.vx += imp * nx * wb
                            b.vy += imp * ny * wb
                            tx, ty = -ny, nx
                            vt = rvx * tx + rvy * ty
                            a.av += vt * 0.008
                            b.av -= vt * 0.008
            for idx, b in enumerate(self.balls):
                if idx in merged_idx:
                    continue
                b.x = max(self.LEFT + b.r, min(self.RIGHT - b.r, b.x))
                b.y = min(self.BOTTOM - b.r, b.y)

        if merged_idx or new_balls:
            self.balls = [b for idx, b in enumerate(self.balls) if idx not in merged_idx] + new_balls

        # 3) 粒子特效步进
        nxt_fx = []
        for f in self.fx:
            f[6] -= dt
            if f[6] <= 0:
                continue
            f[0] += f[2] * dt
            f[1] += f[3] * dt
            if not f[8]:
                f[3] += 260.0 * dt
            nxt_fx.append(f)
        self.fx = nxt_fx

        # 4) 溢出红线判定
        over = any(now - b.born > 0.95 and (b.y - b.r) < self.DANGER_Y for b in self.balls)
        if over:
            if self._danger_since <= 0:
                self._danger_since = now
            elif now - self._danger_since >= 2.2:
                self.game_over = True
                self.running = False
                self._timer.stop()
                play_game_sfx(self.win, "lose", 0.75)
                self.finished.emit(self.score, self.max_tier)
        else:
            self._danger_since = 0.0
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        dark = is_dark()

        if self._shake_t > 0:
            amp = self._shake_amp * min(1.0, self._shake_t / 0.25)
            p.translate(math.sin(self._shake_t * 62.0) * amp, math.cos(self._shake_t * 53.0) * amp * 0.5)

        bg = QLinearGradient(0, 0, 0, self.H)
        if dark:
            bg.setColorAt(0.0, QColor("#1D2234"))
            bg.setColorAt(1.0, QColor("#151927"))
        else:
            bg.setColorAt(0.0, QColor("#FFF9F2"))
            bg.setColorAt(1.0, QColor("#F3F6FF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), 16, 16)

        tank = QRectF(self.LEFT, self.DANGER_Y - 12, self.RIGHT - self.LEFT, self.BOTTOM - self.DANGER_Y + 12)
        border_col = QColor("#FF922B") if self.hammer_mode else (QColor(255, 255, 255, 45) if dark else QColor(120, 130, 170, 55))
        p.setPen(QPen(border_col, 2.4 if self.hammer_mode else 2.0))
        p.setBrush(QColor(255, 255, 255, 10) if dark else QColor(255, 255, 255, 135))
        p.drawRoundedRect(tank, 14, 14)

        now = time.monotonic()
        danger_blink = self._danger_since > 0
        line_col = QColor("#FF5C5C") if danger_blink else QColor(255, 130, 130, 120)
        pen = QPen(line_col, 2.0 if danger_blink else 1.3, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(self.LEFT + 6, self.DANGER_Y), QPointF(self.RIGHT - 6, self.DANGER_Y))
        if self.hammer_mode:
            p.setFont(QFont(self.font().family(), 9, QFont.Weight.Bold))
            p.setPen(QColor("#FF922B"))
            p.drawText(QRectF(self.LEFT, self.DANGER_Y - 22, self.RIGHT - self.LEFT, 18),
                       "🪄 魔法锤已就绪：点击任意萌宠球直接敲碎！(ESC取消)", QTextOption(Qt.AlignmentFlag.AlignCenter))
        elif danger_blink:
            left_s = max(0.0, 2.2 - (now - self._danger_since))
            p.setFont(QFont(self.font().family(), 9, QFont.Weight.Bold))
            p.setPen(QColor("#FF5C5C"))
            p.drawText(QRectF(self.LEFT, self.DANGER_Y - 22, self.RIGHT - self.LEFT, 18),
                       f"⚠ 快满啦! {left_s:.1f}s", QTextOption(Qt.AlignmentFlag.AlignCenter))

        if self.running and not self.game_over and not self.hammer_mode:
            r = MERGE_TIERS[self.cur_tier][3]
            ax = max(self.LEFT + r + 1, min(self.RIGHT - r - 1, self.aim_x))
            p.setPen(QPen(QColor(T["accent"]).lighter(120), 1.2, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(ax, self.DROP_Y + r), QPointF(ax, self.BOTTOM))
            if now - self._last_drop_t >= 0.30:
                paint_merge_ball(p, ax, self.DROP_Y, self.cur_tier, 0.0, 1.0)

        for b in self.balls:
            sc = 1.0 + 0.16 * math.sin(b.pop * math.pi) if b.pop > 0 else 1.0
            paint_merge_ball(p, b.x, b.y, b.tier, b.angle, sc)

        for fx_x, fx_y, _vx, _vy, col, r, life, max_l, txt, big in self.fx:
            alpha = max(0.0, min(1.0, life / max(0.01, max_l)))
            p.save()
            p.setOpacity(alpha)
            if txt:
                f = QFont(self.font())
                f.setPixelSize(16 if big else 13)
                f.setWeight(QFont.Weight.Black)
                p.setFont(f)
                rect = QRectF(fx_x - 76, fx_y - 12, 152, 26)
                p.setPen(QColor(OUTLINE))
                p.drawText(rect.translated(0, 1.2), txt, QTextOption(Qt.AlignmentFlag.AlignCenter))
                p.setPen(QColor(col))
                p.drawText(rect, txt, QTextOption(Qt.AlignmentFlag.AlignCenter))
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(fx_x, fx_y), r, r)
            p.restore()

        p.setPen(QPen(QColor(255, 255, 255, 55), 1.0))
        p.setBrush(QColor(24, 28, 42, 165) if dark else QColor(255, 255, 255, 210))
        p.drawRoundedRect(QRectF(self.W - 82, 8, 72, 48), 12, 12)
        f = QFont(self.font())
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(T["sub"]))
        p.drawText(QRectF(self.W - 80, 10, 42, 16), "下一个", QTextOption(Qt.AlignmentFlag.AlignCenter))
        nr = MERGE_TIERS[self.next_tier][3]
        paint_merge_ball(p, self.W - 32, 34, self.next_tier, 0.0, min(0.68, 14.0 / nr))

        if self.game_over:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(15, 18, 28, 165))
            p.drawRoundedRect(QRectF(0, 0, self.W, self.H), 16, 16)
            f2 = QFont(self.font())
            f2.setPixelSize(22)
            f2.setWeight(QFont.Weight.Black)
            p.setFont(f2)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QRectF(0, self.H * 0.36, self.W, 34), "🍉 本局结束!", QTextOption(Qt.AlignmentFlag.AlignCenter))
            f2.setPixelSize(16)
            p.setFont(f2)
            p.setPen(QColor("#FFD43B"))
            best_name = MERGE_TIERS[min(self.max_tier, len(MERGE_TIERS) - 1)][2]
            p.drawText(QRectF(0, self.H * 0.46, self.W, 28), f"得分 {self.score} · 最高合成「{best_name}」",
                       QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class MergePetDialog(Dialog):
    """合成大萌宠 2.5D 小游戏窗口(3.8 升级版)。"""

    def __init__(self, win) -> None:
        super().__init__(win, "合成大萌宠")
        self.win = win
        self.g: PetGrowth = win.pet_growth
        self._settled = False
        self.setFixedWidth(452)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(7)
        top = QHBoxLayout()
        top.addWidget(label("🍉 合成大萌宠 (2.5D)", "dialogTitle"))
        top.addStretch(1)
        self.score_lab = label(f"得分 0  ·  最高 {self.g.merge_best}", "cardTitle")
        top.addWidget(self.score_lab)
        lay.addLayout(top)

        self.strip = _TierStrip(self)
        lay.addWidget(self.strip)

        self.stage = _MergePetStage(self, win=win)
        self.stage.score_changed.connect(self._on_score)
        self.stage.finished.connect(self._on_finish)
        self.stage.tools_changed.connect(self._sync_tools)
        lay.addWidget(self.stage, 0, Qt.AlignmentFlag.AlignHCenter)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.btn_hammer = button("🪄 魔法锤 (1)", "", self.stage.toggle_hammer)
        self.btn_shake = button("🌪️ 摇一摇 (1)", "", self.stage.use_shake)
        self.btn_swap = button("🔀 换一颗 (1)", "", self.stage.use_swap)
        for b in (self.btn_hammer, self.btn_shake, self.btn_swap):
            b.setMinimumHeight(30)
            tools.addWidget(b, 1)
        lay.addLayout(tools)

        self.result_lab = label("鼠标瞄准点击/空格落球，每局送 3 种解压道具，连续合成触发 COMBO 倍率！", "faint", wrap=True)
        lay.addWidget(self.result_lab)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(button("🔄 重开", "", self._restart, 80))
        self.share_btn = button("📤 晒战绩", "", self._share, 94)
        row.addWidget(self.share_btn)
        row.addWidget(button("🏆 榜单", "", lambda: (self._settle_if_needed(), self.win.open_pet_rank()), 80))
        row.addStretch(1)
        row.addWidget(button("关闭", "primary", self.accept, 74))
        lay.addLayout(row)
        self._sync_tools()

    def _sync_tools(self) -> None:
        st = self.stage
        self.btn_hammer.setText(f"🪄 取消敲碎" if st.hammer_mode else f"🪄 魔法锤 ({st.hammer_left})")
        self.btn_hammer.setEnabled(st.running and not st.game_over and st.hammer_left > 0)
        self.btn_shake.setText(f"🌪️ 摇一摇 ({st.shake_left})")
        self.btn_shake.setEnabled(st.running and not st.game_over and st.shake_left > 0)
        self.btn_swap.setText(f"🔀 换一颗 ({st.swap_left})")
        self.btn_swap.setEnabled(st.running and not st.game_over and st.swap_left > 0)

    def _on_score(self, score: int, max_tier: int) -> None:
        best = max(self.g.merge_best, score)
        self.score_lab.setText(f"得分 {score}  ·  最高 {best}")
        self.strip.set_max_tier(max_tier)
        if max_tier == len(MERGE_TIERS) - 1:
            self.result_lab.setText("👑 哇！你合成了终极「至臻金豚王」！！")

    def _on_finish(self, score: int, max_tier: int) -> None:
        self._settle_if_needed(score)
        self._sync_tools()

    def _settle_if_needed(self, score: int | None = None) -> None:
        sc = self.stage.score if score is None else score
        if self._settled or sc <= 0:
            return
        self._settled = True
        gain, ups = self.g.record_merge_score(sc)
        first = self.g.claim_daily_game_bonus()
        self.score_lab.setText(f"得分 {sc}  ·  最高 {self.g.merge_best}")
        extra = " · 🌟今日首胜额外+30通行证分!" if first else ""
        self.result_lab.setText(f"🎉 结算：得分 {sc}，+{gain} 经验与通行证积分！"
                                + (f"（连升 {ups} 级！）" if ups > 0 else "") + extra)
        if ups > 0 and hasattr(self.win, "_pet_level_up"):
            self.win._pet_level_up()
        if hasattr(self.win, "pr_broadcast"):
            self.win.pr_broadcast()

    def _share(self) -> None:
        sc = max(self.stage.score, self.g.merge_best)
        best_name = MERGE_TIERS[min(self.stage.max_tier, len(MERGE_TIERS) - 1)][2]
        detail = f"最高合成「{best_name}」" if self.stage.score > 0 else "历史最高纪录"
        if hasattr(self.win, "share_game_score") and self.win.share_game_score("merge", sc, detail):
            self.result_lab.setText("📤 战绩挑战卡已发送到当前聊天，快喊群友来战！")

    def _restart(self) -> None:
        self._settle_if_needed()
        self._settled = False
        self.result_lab.setText("新的一局开始！冲刺「至臻金豚王」~")
        self.strip.set_max_tier(0)
        self.stage.reset()

    def closeEvent(self, e) -> None:
        self.stage.stop()
        self._settle_if_needed()
        super().closeEvent(e)

    def accept(self) -> None:
        self.stage.stop()
        self._settle_if_needed()
        super().accept()

    def reject(self) -> None:
        self.stage.stop()
        self._settle_if_needed()
        super().reject()
