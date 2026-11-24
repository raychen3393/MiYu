"""
密语 · 宠物升级仪式(2.5)。盖在聊天区上的一层透明画布(不挡鼠标):
  一道光柱从宠物身上升起 → 正中间弹出大大的「Lv.12」,一圈光环炸开、撒彩带 → 底部滑上来一张「解锁卡」,
  一行一行列出这次解锁的东西(新装扮、气泡皮肤、新动作、进化、抽卡券)→ 五秒后一起淡出。
全部用 QPainter 手绘,不用 QGraphicsEffect。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient, QTextOption
from PySide6.QtWidgets import QWidget

TOTAL = 5.6


def _now() -> float:
    return time.monotonic()


def _ease_out(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return 1 - (1 - k) ** 3


def _back(k: float) -> float:
    k = max(0.0, min(1.0, k))
    c = 1.70158
    return 1 + (c + 1) * (k - 1) ** 3 + c * (k - 1) ** 2


class LevelUpOverlay(QWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.t0 = -1e9
        self.level = 1
        self.title = ""
        self.subtitle = ""
        self.lines: list[tuple[str, str]] = []
        self.origin = QPointF(0, 0)
        self.big = False
        self.confetti: list[list] = []
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.frames = 0
        self.hide()

    def play(self, level: int, title: str, lines: list[tuple[str, str]], origin: QPointF | None = None,
             subtitle: str = "", big: bool = False) -> None:
        """lines = [(图标, 文字)];big = 进化这种大事件(光柱更粗、彩带更多)。"""
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())
        self.level, self.title, self.subtitle = level, title, subtitle
        self.lines = lines[:7]
        self.big = big
        w, h = max(1, self.width()), max(1, self.height())
        self.origin = origin if origin is not None else QPointF(w * 0.8, h - 40)
        self.t0 = _now()
        rng = random.Random()
        self.confetti = [[w / 2 + rng.uniform(-40, 40), h * 0.36, rng.uniform(-340, 340), rng.uniform(-520, -180),
                          rng.uniform(0, 360), rng.uniform(-500, 500),
                          rng.choice(("#FF6B6B", "#FFD43B", "#69DB7C", "#4DABF7", "#B197FC", "#FF8FAB")),
                          rng.uniform(4, 8)] for _ in range(70 if big else 46)]
        self.show()
        self.raise_()
        self.timer.start()

    def active(self) -> bool:
        return _now() - self.t0 < TOTAL

    def stop(self) -> None:
        self.timer.stop()
        self.t0 = -1e9
        self.hide()

    def _tick(self) -> None:
        if not self.active():
            self.stop()
            return
        self.frames += 1
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, _e) -> None:
        t = _now() - self.t0
        if t > TOTAL:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.paint_at(p, t)
        p.end()

    def paint_at(self, p: QPainter, t: float) -> None:
        w, h = self.width(), self.height()
        fade = min(1.0, (TOTAL - t) / 0.7)
        p.setOpacity(max(0.0, fade))
        p.fillRect(QRectF(0, 0, w, h), QColor(12, 8, 24, int(110 * min(1.0, t / 0.4))))
        self._pillar(p, t, w, h)
        self._number(p, t, w, h)
        self._confetti(p, t, w, h)
        self._card(p, t, w, h)

    def _pillar(self, p: QPainter, t: float, w: float, h: float) -> None:
        """从宠物身上升起的光柱。"""
        k = _ease_out(t / 0.7)
        if k <= 0:
            return
        bw = (90 if self.big else 64) * (1 + 0.08 * math.sin(t * 6))
        x, y0 = self.origin.x(), self.origin.y()
        top = y0 - (y0 + 40) * k
        a = min(1.0, t / 0.2) * max(0.0, min(1.0, (2.6 - t) / 0.8))
        if a <= 0:
            return
        g = QLinearGradient(QPointF(x - bw / 2, 0), QPointF(x + bw / 2, 0))
        g.setColorAt(0.0, QColor(255, 236, 153, 0))
        g.setColorAt(0.5, QColor(255, 248, 220, int(200 * a)))
        g.setColorAt(1.0, QColor(255, 236, 153, 0))
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRect(QRectF(x - bw / 2, top, bw, y0 - top + 10))
        core = QLinearGradient(QPointF(x - bw / 6, 0), QPointF(x + bw / 6, 0))
        core.setColorAt(0.0, QColor(255, 255, 255, 0))
        core.setColorAt(0.5, QColor(255, 255, 255, int(230 * a)))
        core.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(core)
        p.drawRect(QRectF(x - bw / 6, top, bw / 3, y0 - top + 10))
        for i in range(10):                                 # 往上飘的光点
            ph = (t * 0.9 + i / 10) % 1.0
            px = x + math.sin(i * 2.3 + t * 3) * bw * 0.4
            py = y0 - ph * (y0 - top)
            p.setBrush(QColor(255, 244, 200, int(220 * a * (1 - ph))))
            p.drawEllipse(QPointF(px, py), 2.2, 2.2)
        p.restore()

    def _number(self, p: QPainter, t: float, w: float, h: float) -> None:
        t2 = t - 0.45
        if t2 < 0:
            return
        cx, cy = w / 2, h * 0.36
        pop = _back(t2 / 0.45)
        p.save()
        ring = min(1.0, t2 / 0.7)                              # 炸开的光环
        if ring < 1:
            p.setPen(QPen(QColor(255, 212, 59, int(220 * (1 - ring))), 6 * (1 - ring) + 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 40 + 170 * ring, 40 + 170 * ring)
        g = QRadialGradient(QPointF(cx, cy), 160)
        g.setColorAt(0, QColor(255, 220, 120, int(120 * min(1.0, t2 / 0.3))))
        g.setColorAt(1, QColor(255, 220, 120, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), 160, 160)
        for i in range(12):                                    # 慢慢转的光芒
            a = i / 12 * math.tau + t * 0.4
            p.setBrush(QColor(255, 236, 153, int(60 * min(1.0, t2 / 0.4))))
            ray = [QPointF(cx + math.cos(a - 0.06) * 60, cy + math.sin(a - 0.06) * 60),
                   QPointF(cx + math.cos(a) * 190, cy + math.sin(a) * 190),
                   QPointF(cx + math.cos(a + 0.06) * 60, cy + math.sin(a + 0.06) * 60)]
            p.drawPolygon(QPolygonF(ray))
        p.translate(cx, cy)
        p.scale(pop, pop)
        f = QFont(self.font())
        f.setPixelSize(20)
        f.setWeight(QFont.Weight.Black)
        p.setFont(f)
        p.setPen(QColor("#FFE066"))
        p.drawText(QRectF(-200, -88, 400, 30), "LEVEL UP", QTextOption(Qt.AlignmentFlag.AlignCenter))
        f.setPixelSize(86)
        p.setFont(f)
        r = QRectF(-220, -64, 440, 110)
        p.setPen(QColor(120, 60, 0, 170))
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 4), (2, 4)):
            p.drawText(r.translated(dx, dy), f"Lv.{self.level}", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.setPen(QColor("#FFF3BF"))
        p.drawText(r.translated(0, -1), f"Lv.{self.level}", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.setPen(QColor("#FFD43B"))
        p.drawText(r.translated(0, 1), f"Lv.{self.level}", QTextOption(Qt.AlignmentFlag.AlignCenter))
        f.setPixelSize(18)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(-260, 48, 520, 28), self.title, QTextOption(Qt.AlignmentFlag.AlignCenter))
        if self.subtitle:
            f.setPixelSize(14)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            sr = QRectF(-260, 76, 520, 22)
            p.setPen(QColor(40, 20, 70, 150))                 # 一圈深色描边:浅色主题的灰底上也看得清
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(sr.translated(dx, dy), self.subtitle, QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.setPen(QColor("#FFF3BF"))
            p.drawText(sr, self.subtitle, QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.restore()

    def _confetti(self, p: QPainter, t: float, w: float, h: float) -> None:
        t2 = t - 0.5
        if t2 < 0:
            return
        p.save()
        for x, y, vx, vy, rot, vr, col, sz in self.confetti:
            px = x + vx * t2 * 0.9
            py = y + vy * t2 + 420 * t2 * t2
            if py > h + 20:
                continue
            p.save()
            p.translate(px, py)
            p.rotate(rot + vr * t2)
            p.scale(1.0, abs(math.cos(t2 * 6 + rot)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col))
            p.drawRect(QRectF(-sz / 2, -sz / 4, sz, sz / 2))
            p.restore()
        p.restore()

    def _card(self, p: QPainter, t: float, w: float, h: float) -> None:
        """底部滑上来的解锁卡。"""
        t2 = t - 1.3
        if t2 < 0 or not self.lines:
            return
        cw = min(400.0, w - 40)
        lh = 30
        ch = 54 + lh * len(self.lines)
        k = _back(t2 / 0.5)
        x = (w - cw) / 2
        y = h - 24 - ch * k + (1 - k) * 30
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawRoundedRect(QRectF(x, y + 6, cw, ch), 20, 20)
        g = QLinearGradient(QPointF(x, y), QPointF(x + cw, y + ch))
        g.setColorAt(0, QColor(44, 32, 70, 245))
        g.setColorAt(1, QColor(70, 40, 90, 245))
        p.setBrush(g)
        p.setPen(QPen(QColor(255, 212, 59, 170), 1.5))
        p.drawRoundedRect(QRectF(x, y, cw, ch), 20, 20)
        f = QFont(self.font())
        f.setPixelSize(15)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor("#FFE066"))
        p.drawText(QRectF(x, y + 12, cw, 24), "✨ 这次解锁了", QTextOption(Qt.AlignmentFlag.AlignCenter))
        f.setPixelSize(14)
        f.setWeight(QFont.Weight.Normal)
        for i, (icon, text) in enumerate(self.lines):
            a = max(0.0, min(1.0, (t2 - 0.35 - i * 0.14) / 0.25))
            if a <= 0:
                continue
            ly = y + 44 + i * lh + (1 - a) * 8
            p.setOpacity(p.opacity() * a if a < 1 else p.opacity())
            p.setFont(f)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QRectF(x + 24, ly, 30, lh), icon, QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.setPen(QColor("#F1F3F5"))
            opt = QTextOption(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            p.drawText(QRectF(x + 60, ly, cw - 80, lh), text, opt)
            p.setOpacity(max(0.0, min(1.0, (TOTAL - t) / 0.7)))
        p.restore()
