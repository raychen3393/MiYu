"""
五子棋的控件:棋盘、带倒计时圈的玩家卡片、结算动画、分段按钮。全部自己画(不用 QGraphicsEffect)。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import motion, theme
from ..theme import T
from ..ui import label
from .rules import N

COLS = "ABCDEFGHJKLMNOP"                       # 棋盘横坐标(习惯上不用 I)
STARS = ((3, 3), (3, 11), (11, 3), (11, 11), (7, 7))


def _accent() -> QColor:
    return QColor(T["accent"]) if theme.valid_hex(T["accent"]) else QColor("#A855F7")


def paint_stone(p: QPainter, c: QPointF, r: float, black: bool, alpha: float = 1.0) -> None:
    """一颗有光泽的棋子:黑子深色带高光,白子珍珠白。"""
    p.save()
    p.setOpacity(p.opacity() * alpha)
    p.setPen(Qt.PenStyle.NoPen)
    shadow = QColor(0, 0, 0, 70)                             # 落在棋盘上的影子
    p.setBrush(shadow)
    p.drawEllipse(QPointF(c.x() + r * 0.10, c.y() + r * 0.16), r * 0.98, r * 0.98)
    g = QRadialGradient(QPointF(c.x() - r * 0.35, c.y() - r * 0.40), r * 1.45)
    if black:
        g.setColorAt(0.0, QColor("#6B6B78"))
        g.setColorAt(0.35, QColor("#26262E"))
        g.setColorAt(1.0, QColor("#0B0B10"))
    else:
        g.setColorAt(0.0, QColor("#FFFFFF"))
        g.setColorAt(0.55, QColor("#ECEAF4"))
        g.setColorAt(1.0, QColor("#B9B4C8"))
    p.setBrush(QBrush(g))
    p.drawEllipse(c, r, r)
    hi = QRadialGradient(QPointF(c.x() - r * 0.38, c.y() - r * 0.45), r * 0.55)
    hi.setColorAt(0.0, QColor(255, 255, 255, 120 if black else 200))
    hi.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(hi))
    p.drawEllipse(c, r, r)
    p.restore()


class BoardView(QWidget):
    """15×15 棋盘。点空位发 cell_clicked(x, y);轮到自己时鼠标处显示半透明的预览棋子。
    新落的子从稍大一点缩回来、淡入;赢了以后五子连线发光。"""
    cell_clicked = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(320, 320))
        self.moves: list[tuple[int, int]] = []
        self.win_line: list | None = None
        self.can_play = False
        self.my_black = True
        self.hover: tuple[int, int] | None = None
        self.drop_p = 1.0
        self.win_p = 0.0
        self.pulse_t0 = 0.0
        self.show_numbers = False
        self._pulse = QTimer(self)
        self._pulse.setInterval(40)
        self._pulse.timeout.connect(self.update)

    # ---- 数据
    def set_state(self, moves, win_line=None, can_play: bool = False, my_black: bool = True,
                  animate_last: bool = False) -> None:
        moves = [tuple(m) for m in moves]
        grew = len(moves) > len(self.moves) and moves[:len(self.moves)] == self.moves
        self.moves = moves
        self.can_play, self.my_black = can_play, my_black
        if animate_last and grew:
            motion.animate(self, 0.0, 1.0, 230, self._set_drop, key="_drop_anim",
                           curve=motion.QEasingCurve.Type.OutBack)
        else:
            self.drop_p = 1.0
        new_line = [tuple(x) for x in win_line] if win_line else None
        if new_line != self.win_line:
            self.win_line = new_line
            if new_line:
                self.pulse_t0 = time.monotonic()
                motion.animate(self, 0.0, 1.0, 700, self._set_win, key="_win_anim")
                self._pulse.start()
            else:
                self.win_p = 0.0
                self._pulse.stop()
        if not can_play:
            self.hover = None
        self.update()

    def _set_drop(self, v: float) -> None:
        self.drop_p = v
        self.update()

    def _set_win(self, v: float) -> None:
        self.win_p = v
        self.update()

    # ---- 几何
    def geom(self) -> tuple[float, float, float, float]:
        """(棋盘左上角 x, y, 边长, 格距)。四周留出一格的边,放坐标。"""
        side = min(self.width(), self.height()) - 8
        cell = side / (N + 1)
        x0 = (self.width() - side) / 2
        y0 = (self.height() - side) / 2
        return x0, y0, side, cell

    def point(self, x: int, y: int) -> QPointF:
        x0, y0, _side, cell = self.geom()
        return QPointF(x0 + cell * (x + 1), y0 + cell * (y + 1))

    def cell_at(self, pos) -> tuple[int, int] | None:
        x0, y0, _side, cell = self.geom()
        x = round((pos.x() - x0) / cell) - 1
        y = round((pos.y() - y0) / cell) - 1
        if 0 <= x < N and 0 <= y < N:
            c = self.point(x, y)
            if math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= cell * 0.55:
                return x, y
        return None

    # ---- 鼠标
    def mouseMoveEvent(self, e) -> None:
        cell = self.cell_at(e.position()) if self.can_play else None
        if cell is not None and cell in set(self.moves):
            cell = None
        if cell != self.hover:
            self.hover = cell
            self.setCursor(Qt.CursorShape.PointingHandCursor if cell else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e) -> None:
        self.hover = None
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        left = e.button() == Qt.MouseButton.LeftButton
        super().mouseReleaseEvent(e)
        if not left or not self.can_play:
            return
        cell = self.cell_at(e.position())
        if cell is not None and cell not in set(self.moves):
            self.cell_clicked.emit(*cell)

    # ---- 绘制
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0, y0, side, cell = self.geom()
        dark = theme.is_dark()
        acc = _accent()
        board = QRectF(x0, y0, side, side)
        g = QLinearGradient(board.topLeft(), board.bottomRight())     # 棋盘:和主题一致的半透明玻璃
        if dark:
            g.setColorAt(0.0, QColor(46, 32, 72, 225))
            g.setColorAt(1.0, QColor(24, 16, 40, 235))
        else:
            g.setColorAt(0.0, QColor(255, 248, 236, 240))
            g.setColorAt(1.0, QColor(240, 226, 204, 245))
        p.setPen(QPen(QColor(255, 255, 255, 40) if dark else QColor(120, 90, 50, 60), 1.2))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(board, 18, 18)
        glow = QRadialGradient(board.center(), side * 0.7)
        c1 = QColor(acc)
        c1.setAlpha(38 if dark else 18)
        glow.setColorAt(0.0, c1)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(board, 18, 18)
        line = QColor(230, 215, 255, 70) if dark else QColor(90, 60, 30, 95)
        p.setPen(QPen(line, 1.0))
        for i in range(N):
            a, b = self.point(i, 0), self.point(i, N - 1)
            p.drawLine(a, b)
            a, b = self.point(0, i), self.point(N - 1, i)
            p.drawLine(a, b)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(230, 215, 255, 150) if dark else QColor(90, 60, 30, 150))
        for sx, sy in STARS:
            p.drawEllipse(self.point(sx, sy), max(2.0, cell * 0.09), max(2.0, cell * 0.09))
        if cell >= 22:                                               # 坐标(格子太小就不画)
            f = QFont(self.font())
            f.setPointSizeF(max(6.5, cell * 0.22))
            p.setFont(f)
            p.setPen(QColor(230, 215, 255, 110) if dark else QColor(90, 60, 30, 130))
            for i in range(N):
                pt = self.point(i, 0)
                p.drawText(QRectF(pt.x() - cell / 2, y0 + 2, cell, cell * 0.6), int(Qt.AlignmentFlag.AlignCenter), COLS[i])
                pt = self.point(0, i)
                p.drawText(QRectF(x0 + 2, pt.y() - cell / 2, cell * 0.6, cell), int(Qt.AlignmentFlag.AlignCenter),
                           str(N - i))
        r = cell * 0.44
        last = len(self.moves) - 1
        for i, (x, y) in enumerate(self.moves):
            c = self.point(x, y)
            if i == last and self.drop_p < 1.0:
                k = 1.0 + 0.32 * (1.0 - self.drop_p)
                paint_stone(p, c, r * k, i % 2 == 0, max(0.0, min(1.0, self.drop_p * 1.4)))
            else:
                paint_stone(p, c, r, i % 2 == 0)
            if self.show_numbers:
                f = QFont(self.font())
                f.setPointSizeF(max(6.0, cell * 0.24))
                f.setBold(True)
                p.setFont(f)
                p.setPen(QColor(255, 255, 255) if i % 2 == 0 else QColor(30, 30, 40))
                p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), int(Qt.AlignmentFlag.AlignCenter), str(i + 1))
        if self.moves and not self.win_line and not self.show_numbers:   # 最后一手:中间一个主题色小点
            c = self.point(*self.moves[-1])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(acc)
            p.drawEllipse(c, r * 0.22, r * 0.22)
        if self.hover is not None and self.can_play:                 # 预览:半透明的自己的棋子
            paint_stone(p, self.point(*self.hover), r, self.my_black, 0.42)
        if self.win_line:                                            # 获胜连线:发光的线 + 棋子外一圈呼吸的光
            pts = sorted(self.win_line)
            a, b = self.point(*pts[0]), self.point(*pts[-1])
            end = QPointF(a.x() + (b.x() - a.x()) * self.win_p, a.y() + (b.y() - a.y()) * self.win_p)
            wide = QColor(acc)
            wide.setAlpha(90)
            p.setPen(QPen(wide, r * 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(a, end)
            p.setPen(QPen(QColor(255, 255, 255, 230), max(2.0, r * 0.16), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(a, end)
            t = time.monotonic() - self.pulse_t0
            k = 0.5 + 0.5 * math.sin(t * 5.0)
            ring = QColor(acc)
            ring.setAlpha(int(120 + 100 * k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ring, 2.2))
            for x, y in pts:
                p.drawEllipse(self.point(x, y), r * (1.12 + 0.12 * k), r * (1.12 + 0.12 * k))
            if t > 6:
                self._pulse.stop()
        p.end()


class AvatarRing(QWidget):
    """头像 + 外面一圈倒计时(轮到这个人时亮起,时间越少颜色越暖)。"""

    def __init__(self, size: int = 64) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.pm = None
        self.frac = 1.0
        self.active = False
        self.online = True
        self.stone_black: bool | None = None

    def set(self, pm=None, frac: float | None = None, active: bool | None = None, online: bool | None = None,
            black: bool | None = None) -> None:
        if pm is not None:
            self.pm = pm
        if frac is not None:
            self.frac = max(0.0, min(1.0, frac))
        if active is not None:
            self.active = active
        if online is not None:
            self.online = online
        if black is not None:
            self.stone_black = black
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        pad = 5
        if self.pm is not None:
            av = s - 2 * pad - 4
            p.drawPixmap(QRectF(pad + 2, pad + 2, av, av), self.pm, QRectF(self.pm.rect()))
        rect = QRectF(2.5, 2.5, s - 5, s - 5)
        base = QColor(T["text"])
        base.setAlpha(30)
        p.setPen(QPen(base, 3.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)
        if self.active:
            f = self.frac
            col = _accent() if f > 0.35 else QColor("#FBBF24") if f > 0.15 else QColor("#FB7185")
            p.setPen(QPen(col, 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, 90 * 16, int(-360 * 16 * f))
        if self.stone_black is not None:                             # 右下角:执什么子
            paint_stone(p, QPointF(s - 11, s - 11), 8, self.stone_black)
        dot = QColor(T["online"] if self.online else T["offline"])   # 左下角:在线状态
        p.setPen(QPen(QColor(T["ring"]), 2))
        p.setBrush(dot)
        p.drawEllipse(QPointF(10, s - 10), 5.5, 5.5)
        p.end()


class PlayerCard(QFrame):
    """对局里一边的玩家:头像(带倒计时圈)、昵称、执子和在线状态、这一步剩余时间、累计用时。"""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("gmPlayer")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(12)
        self.ring = AvatarRing(64)
        lay.addWidget(self.ring)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.name = label("", "gmName")
        self.sub = label("", "gmSub")
        col.addWidget(self.name)
        col.addWidget(self.sub)
        col.addStretch(1)
        lay.addLayout(col, 1)
        right = QVBoxLayout()
        right.setSpacing(0)
        self.clock = label("", "gmClock")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total = label("", "gmSub")
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.clock)
        right.addWidget(self.total)
        lay.addLayout(right)

    def set_player(self, pm, nick: str, sub: str, black: bool, online: bool) -> None:
        self.ring.set(pm=pm, black=black, online=online)
        self.name.setText(self.name.fontMetrics().elidedText(nick, Qt.TextElideMode.ElideRight, 150))
        self.sub.setText(sub)

    def set_clock(self, text: str, frac: float, active: bool, total: str = "") -> None:
        if self.clock.text() != text:
            self.clock.setText(text)
        if self.total.text() != total:
            self.total.setText(total)
        self.ring.set(frac=frac, active=active)
        if bool(self.property("active")) != bool(active):        # 轮到谁:卡片亮一点(只在变化时重新套样式)
            self.setProperty("active", bool(active))
            self.style().unpolish(self)
            self.style().polish(self)


class Segmented(QWidget):
    """一排互斥的按钮(总榜 / 今日 / 本周 之类)。选中变化时发 changed(键)。"""
    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str]], current: str | None = None) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.btns: dict[str, QPushButton] = {}
        for key, text in items:
            b = QPushButton(text)
            b.setObjectName("segBtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.select(k))
            self.group.addButton(b)
            lay.addWidget(b)
            self.btns[key] = b
        self.current = current or items[0][0]
        self.btns[self.current].setChecked(True)

    def select(self, key: str, emit: bool = True) -> None:
        if key not in self.btns:
            return
        self.btns[key].setChecked(True)
        changed = key != self.current
        self.current = key
        if changed and emit:
            self.changed.emit(key)


class ResultOverlay(QWidget):
    """结算:盖在棋盘上,背景渐暗;中间一张卡片:胜负、原因、本局积分(数字往上跳)、总积分和名次变化。赢了撒彩带。"""
    action = Signal(str)

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.op = 0.0
        self.confetti: list[list] = []
        self._t0 = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._step)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("gmResult")
        self.card.setFixedWidth(340)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(26, 22, 26, 20)
        cl.setSpacing(6)
        self.title = label("", "gmResultTitle", center=True)
        self.reason = label("", "hint", wrap=True, center=True)
        self.points = label("", "gmPoints", center=True)
        self.total = label("", "gmSub", center=True)
        self.rank = label("", "gmRankChange", center=True)
        self.note = label("", "faint", wrap=True, center=True)
        for w in (self.title, self.reason, self.points, self.total, self.rank, self.note):
            cl.addWidget(w)
        cl.addSpacing(8)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.again = QPushButton("再来一局")
        self.again.setObjectName("primary")
        self.again.setMinimumHeight(36)
        self.again.clicked.connect(lambda: self.action.emit("rematch"))
        self.review = QPushButton("看棋盘")
        self.review.setMinimumHeight(36)
        self.review.clicked.connect(lambda: self.action.emit("close"))
        self.lobby = QPushButton("回大厅")
        self.lobby.setMinimumHeight(36)
        self.lobby.clicked.connect(lambda: self.action.emit("lobby"))
        for b in (self.again, self.review, self.lobby):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            btns.addWidget(b)
        cl.addLayout(btns)
        row.addWidget(self.card)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.hide()

    def show_result(self, title: str, reason: str, gained: int | None, total_from: int, total_to: int,
                    rank_text: str, note: str, win: bool, can_rematch: bool) -> None:
        self.title.setText(title)
        self.reason.setText(reason)
        self.rank.setText(rank_text)
        self.rank.setVisible(bool(rank_text))
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.again.setVisible(can_rematch)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.op = 0.0
        motion.animate(self, 0.0, 1.0, 260, self._set_op, key="_op_anim")
        if gained is None:
            self.points.setText("练习赛 · 不计分")
            self.total.setText("")
        else:
            motion.animate(self, 0.0, float(gained), 900, lambda v: self.points.setText(f"+{int(round(v))} 分"),
                           key="_pts_anim")
            motion.animate(self, float(total_from), float(total_to), 1100,
                           lambda v: self.total.setText(f"总积分 {int(round(v))}"), key="_tot_anim")
            if not motion.ENABLED:
                self.points.setText(f"+{gained} 分")
                self.total.setText(f"总积分 {total_to}")
        self.confetti = []
        if win:
            rng = random.Random()
            w = max(1, self.width())
            cols = [QColor("#A855F7"), QColor("#F472B6"), QColor("#FBBF24"), QColor("#34D399"), QColor("#60A5FA")]
            self.confetti = [[rng.uniform(0, w), rng.uniform(-200, -10), rng.uniform(-40, 40), rng.uniform(90, 220),
                              rng.uniform(0, 360), rng.uniform(-300, 300), rng.choice(cols), rng.uniform(5, 9)]
                             for _ in range(70)]
            self._t0 = time.monotonic()
            self._tick.start()

    def _set_op(self, v: float) -> None:
        self.op = v
        self.update()

    def _step(self) -> None:
        if time.monotonic() - self._t0 > 3.0 or not self.isVisible():
            self._tick.stop()
            self.confetti = []
        self.update()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(8, 4, 18) if theme.is_dark() else QColor(40, 30, 60)
        bg.setAlphaF(0.45 * self.op)
        p.fillRect(self.rect(), bg)
        if self.confetti:
            t = time.monotonic() - self._t0
            for x, y, vx, vy, rot, vr, col, size in self.confetti:
                cx, cy = x + vx * t, y + vy * t + 60 * t * t
                if cy > self.height():
                    continue
                p.save()
                p.translate(cx, cy)
                p.rotate(rot + vr * t)
                c = QColor(col)
                c.setAlphaF(max(0.0, min(1.0, 1.6 - t / 2)))
                p.fillRect(QRectF(-size / 2, -size / 4, size, size / 2), c)
                p.restore()
        p.end()

    def mousePressEvent(self, e) -> None:            # 挡住下面的棋盘
        e.accept()


def fmt_clock(secs: float) -> str:
    s = max(0, int(math.ceil(secs)))
    return f"{s // 60}:{s % 60:02d}"


def chip(text: str, kind: str) -> QLabel:
    lab = label(text, "chip_" + kind)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lab


def elide(lab: QLabel, text: str, width: int) -> None:
    lab.setText(QFontMetrics(lab.font()).elidedText(text, Qt.TextElideMode.ElideRight, width))
    lab.setToolTip(text if lab.text() != text else "")


def stone_pixmap(black: bool, size: int = 18):
    from PySide6.QtGui import QPixmap
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_stone(p, QPointF(size / 2, size / 2), size / 2 - 1.5, black)
    p.end()
    return pm


__all__ = ["BoardView", "PlayerCard", "Segmented", "ResultOverlay", "AvatarRing", "fmt_clock", "chip", "elide",
           "paint_stone", "stone_pixmap", "QPainterPath"]
