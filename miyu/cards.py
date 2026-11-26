"""
密语 · 聊天里的卡片
投票、抽签、骰子、五子棋、猜拳、一起画邀请的卡片控件,以及五子棋 / 猜拳的纯逻辑。
卡片只负责显示,点了什么通过 act 信号交给主窗口(window/games.py)处理。
"""
from __future__ import annotations

import hashlib
import math
import random
import secrets
import time

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QTextOption,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import T, qcolor
from .ui import button, label, peer_avatar, repolish


GOMOKU_N = 15
RPS = {"rock": "✊", "scissors": "✌️", "paper": "✋"}
RPS_NAME = {"rock": "石头", "scissors": "剪刀", "paper": "布"}
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}


def gomoku_winner(moves: list) -> list | None:
    """moves = [(x, y), ...],黑先。最后一手连成五个就返回那五(或更多)个点,否则 None。"""
    if not moves:
        return None
    n = len(moves) - 1
    me = n % 2
    stones = {tuple(m) for i, m in enumerate(moves) if i % 2 == me}
    x, y = moves[-1]
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        line = [(x, y)]
        for sgn in (1, -1):
            k = 1
            while (x + sgn * dx * k, y + sgn * dy * k) in stones:
                line.append((x + sgn * dx * k, y + sgn * dy * k))
                k += 1
        if len(line) >= 5:
            return line
    return None


def rps_hash(gid: str, choice: str, nonce: str) -> str:
    return hashlib.sha256(f"{gid}|{choice}|{nonce}".encode()).hexdigest()


def rps_result(mine: str, theirs: str) -> str:
    if mine == theirs:
        return "draw"
    return "win" if RPS_BEATS[mine] == theirs else "lose"


def new_nonce() -> str:
    return secrets.token_hex(12)


class CardBase(QFrame):
    """所有卡片的基类。act(动作, 数据) 交给主窗口处理;update_state(state) 刷新显示。"""
    act = Signal(str, object)
    W = 280

    def __init__(self, msg) -> None:
        super().__init__()
        self.msg = msg
        self.setObjectName("fileCardMine" if msg.mine else "fileCard")
        self.setFixedWidth(self.W)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(7)
        from .island import HoloOverlay
        self._holo = HoloOverlay(self, radius=16.0)

    def head(self, emoji: str, title: str) -> QLabel:
        lb = label(f"{emoji}  {title}", "cardTitle", wrap=True)
        self.lay.addWidget(lb)
        return lb

    def update_state(self, state: dict) -> None:
        pass


class PollOption(QWidget):
    clicked = Signal(int)

    def __init__(self, idx: int, text: str) -> None:
        super().__init__()
        self.idx, self.text = idx, text
        self.count, self.frac, self.mine, self.names = 0, 0.0, False, ""
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, count: int, frac: float, mine: bool, names: str) -> None:
        self.count, self.frac, self.mine, self.names = count, frac, mine, names
        self.setToolTip(names or "还没人选")
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.idx)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(qcolor(T["accent"]) if self.mine else qcolor(T["line_strong"]), 1.4 if self.mine else 1))
        p.setBrush(qcolor(T["btn2"]))
        p.drawRoundedRect(r, 10, 10)
        if self.frac > 0:
            fill = QColor(T["accent"])
            fill.setAlphaF(0.28 if self.mine else 0.16)
            clip = QPainterPath()
            clip.addRoundedRect(r, 10, 10)
            p.setClipPath(clip)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRect(QRectF(r.left(), r.top(), r.width() * self.frac, r.height()))
            p.setClipping(False)
        f = QFont(self.font())
        p.setFont(f)
        p.setPen(qcolor(T["text"]))
        text = ("✓ " if self.mine else "") + self.text
        p.drawText(r.adjusted(12, 0, -44, 0), text, QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
        p.setPen(qcolor(T["sub"]))
        p.drawText(r.adjusted(0, 0, -12, 0), str(self.count),
                   QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight))
        p.end()


class PollCard(CardBase):
    def __init__(self, msg, state: dict) -> None:
        super().__init__(msg)
        c = msg.card
        self.head("📊", str(c.get("q", "投票")))
        self.sub = label("", "fileSub")
        self.lay.addWidget(self.sub)
        self.opts = []
        for i, text in enumerate(c.get("opts") or []):
            o = PollOption(i, str(text))
            o.clicked.connect(lambda idx: self.act.emit("vote", idx))
            self.lay.addWidget(o)
            self.opts.append(o)
        self.update_state(state)

    def update_state(self, state: dict) -> None:
        counts = state.get("counts") or [0] * len(self.opts)
        names = state.get("names") or [[] for _ in self.opts]
        mine = state.get("mine") or set()
        voters = state.get("voters", 0)
        top = max(counts) if counts else 0
        for i, o in enumerate(self.opts):
            n = counts[i] if i < len(counts) else 0
            o.set_data(n, n / max(1, voters), i in mine, "、".join(names[i]) if i < len(names) else "")
        kind = "多选" if self.msg.card.get("multi") else "单选"
        self.sub.setText(f"{kind}  ·  {voters} 人参与" + ("  ·  点选项投票,再点一次取消" if not mine else "")
                         + (f"  ·  领先:{self.opts[counts.index(top)].text}" if top and counts.count(top) == 1 else ""))


class LotteryCard(CardBase):
    """抽签结果:到达时名字滚动一会儿再停在中签的人身上。"""

    def __init__(self, msg, state: dict) -> None:
        super().__init__(msg)
        c = msg.card
        self.head("🎲", str(c.get("title", "抽签")))
        self.cands = [x for x in (c.get("cands") or []) if isinstance(x, dict)][:30]
        self.win = c.get("win")
        self.big = label("", "lotteryName", center=True)
        self.big.setMinimumHeight(44)
        self.lay.addWidget(self.big)
        self.sub = label(f"从 {len(self.cands)} 人里抽 1 个", "fileSub", center=True)
        self.lay.addWidget(self.sub)
        self._i = 0
        self._left = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._spin)
        if state.get("fresh") and len(self.cands) > 1:
            self._left = 18
            self.timer.start(70)
        self._show_final(self._left == 0)

    def _spin(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self.timer.stop()
            self._show_final(True)
            return
        self._i = (self._i + 1) % len(self.cands)
        self.big.setText(str(self.cands[self._i].get("nick", "")))
        if self._left < 6:
            self.timer.setInterval(70 + (6 - self._left) * 45)

    def _show_final(self, final: bool) -> None:
        if not final:
            return
        w = next((x for x in self.cands if x.get("id") == self.win), None)
        self.big.setText(f"🎉 {w.get('nick', '')}" if w else "?")
        self.big.setProperty("won", True)
        repolish(self.big)


class DiceFace(QWidget):
    PIPS = {1: [(1, 1)], 2: [(0, 0), (2, 2)], 3: [(0, 0), (1, 1), (2, 2)], 4: [(0, 0), (2, 0), (0, 2), (2, 2)],
            5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)], 6: [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)]}

    def __init__(self, value: int) -> None:
        super().__init__()
        self.value = value
        self.rot = 0.0
        self.setFixedSize(72, 72)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(36, 36)
        p.rotate(self.rot)
        r = QRectF(-27, -27, 54, 54)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor("#FFFFFF"))
        g.setColorAt(1, QColor("#E9ECF2"))
        p.setPen(QPen(QColor("#C9CED8"), 1.2))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, 11, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E5484D") if self.value == 1 else QColor("#2D2D33"))
        rad = 6.5 if self.value == 1 else 5
        for gx, gy in self.PIPS.get(self.value, []):
            p.drawEllipse(QPointF((gx - 1) * 15, (gy - 1) * 15), rad, rad)
        p.end()


class DiceCard(CardBase):
    W = 150

    def __init__(self, msg, state: dict) -> None:
        super().__init__(msg)
        self.final = max(1, min(6, int(msg.card.get("v", 1) or 1)))
        self.face = DiceFace(self.final)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.face)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.sub = label("", "fileSub", center=True)
        self.lay.addWidget(self.sub)
        self._left = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._roll)
        if state.get("fresh"):
            self._left = 12
            self.timer.start(60)
            self.sub.setText("骰子转动中…")
        else:
            self.sub.setText(f"掷出了 {self.final} 点")

    def _roll(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self.timer.stop()
            self.face.value, self.face.rot = self.final, 0
            self.sub.setText(f"掷出了 {self.final} 点")
        else:
            self.face.value = random.randint(1, 6)
            self.face.rot = random.uniform(-25, 25)
        self.face.update()


class GomokuBoard(QWidget):
    clicked = Signal(int, int)
    CELL, PAD = 17, 12

    def __init__(self) -> None:
        super().__init__()
        size = self.PAD * 2 + self.CELL * (GOMOKU_N - 1)
        self.setFixedSize(size, size)
        self.moves: list = []
        self.win_line: list | None = None
        self.can_play = False
        self.hover: tuple | None = None
        self.setMouseTracking(True)

    def _cell(self, pos) -> tuple | None:
        x = round((pos.x() - self.PAD) / self.CELL)
        y = round((pos.y() - self.PAD) / self.CELL)
        if 0 <= x < GOMOKU_N and 0 <= y < GOMOKU_N:
            return x, y
        return None

    def mouseMoveEvent(self, e) -> None:
        h = self._cell(e.position()) if self.can_play else None
        if h != self.hover:
            self.hover = h
            self.update()

    def leaveEvent(self, e) -> None:
        self.hover = None
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        c = self._cell(e.position())
        if c is not None and self.can_play and c not in {tuple(m) for m in self.moves}:
            self.clicked.emit(*c)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        g = QLinearGradient(0, 0, w, w)
        g.setColorAt(0, QColor("#F3D9A4"))
        g.setColorAt(1, QColor("#E2B877"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(0, 0, w, w), 10, 10)
        p.setPen(QPen(QColor(110, 72, 30, 150), 1))
        a, b = self.PAD, self.PAD + self.CELL * (GOMOKU_N - 1)
        for i in range(GOMOKU_N):
            v = self.PAD + i * self.CELL
            p.drawLine(QPointF(a, v), QPointF(b, v))
            p.drawLine(QPointF(v, a), QPointF(v, b))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(110, 72, 30, 200))
        for sx, sy in ((3, 3), (11, 3), (7, 7), (3, 11), (11, 11)):
            p.drawEllipse(QPointF(self.PAD + sx * self.CELL, self.PAD + sy * self.CELL), 2.2, 2.2)
        r = self.CELL * 0.44
        for i, (x, y) in enumerate(self.moves):
            cx, cy = self.PAD + x * self.CELL, self.PAD + y * self.CELL
            sg = QLinearGradient(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            if i % 2 == 0:
                sg.setColorAt(0, QColor("#5A5A62"))
                sg.setColorAt(1, QColor("#0E0E12"))
            else:
                sg.setColorAt(0, QColor("#FFFFFF"))
                sg.setColorAt(1, QColor("#D8D8DE"))
            p.setPen(QPen(QColor(0, 0, 0, 70), 0.8))
            p.setBrush(QBrush(sg))
            p.drawEllipse(QPointF(cx, cy), r, r)
        if self.moves:                               # 最后一手:小红点
            x, y = self.moves[-1]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FF453A"))
            p.drawEllipse(QPointF(self.PAD + x * self.CELL, self.PAD + y * self.CELL), 2.4, 2.4)
        if self.win_line:
            pts = sorted(self.win_line)
            p.setPen(QPen(QColor(255, 69, 58, 200), 2.6))
            p.drawLine(QPointF(self.PAD + pts[0][0] * self.CELL, self.PAD + pts[0][1] * self.CELL),
                       QPointF(self.PAD + pts[-1][0] * self.CELL, self.PAD + pts[-1][1] * self.CELL))
        if self.hover is not None and self.can_play:
            x, y = self.hover
            c = QColor(0, 0, 0, 70) if len(self.moves) % 2 == 0 else QColor(255, 255, 255, 140)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(self.PAD + x * self.CELL, self.PAD + y * self.CELL), r, r)
        p.end()


class GomokuCard(CardBase):
    W = 296

    def __init__(self, msg, state: dict) -> None:
        super().__init__(msg)
        self.lay.setContentsMargins(12, 10, 12, 10)
        self.title = self.head("⚫", "五子棋")
        self.board = GomokuBoard()
        self.board.clicked.connect(lambda x, y: self.act.emit("move", (x, y)))
        self.lay.addWidget(self.board, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        self.status = label("", "fileSub")
        row.addWidget(self.status, 1)
        self.btn = button("认输", "link", lambda: self.act.emit(self._btn_act, None))
        self._btn_act = "resign"
        row.addWidget(self.btn)
        self.lay.addLayout(row)
        self.update_state(state)

    def update_state(self, st: dict) -> None:
        self.board.moves = list(st.get("moves") or [])
        self.board.win_line = st.get("line")
        self.board.can_play = bool(st.get("my_turn")) and not st.get("over")
        me_black = st.get("me_black")
        self.title.setText(f"⚫  五子棋  ·  我执{'黑' if me_black else '白'}")
        over = st.get("over")
        if over:
            self.status.setText({"win": "🎉 你赢了!", "lose": "你输了,再来一局?", "resign_me": "你认输了",
                                 "resign_them": "🎉 对方认输了", "lost": "对局已结束"}.get(over, "对局结束"))
            self.btn.setText("再来一局")
            self._btn_act = "again"
            self.btn.setVisible(over != "lost")
        else:
            n = len(self.board.moves)
            self.status.setText(("轮到你了" if st.get("my_turn") else "等对方落子…") + f"  ·  第 {n + 1} 手")
            self.btn.setText("认输")
            self._btn_act = "resign"
            self.btn.setVisible(n > 0)
        self.board.update()


class RpsCard(CardBase):
    W = 270

    def __init__(self, msg, state: dict) -> None:
        super().__init__(msg)
        self.head("✊", "猜拳")
        self.row = QHBoxLayout()
        self.btns = {}
        for key, emo in RPS.items():
            b = button(emo, "rpsBtn", lambda _=False, k=key: self.act.emit("pick", k))
            b.setFixedSize(64, 52)
            b.setToolTip(RPS_NAME[key])
            self.row.addWidget(b)
            self.btns[key] = b
        self.lay.addLayout(self.row)
        self.result = label("", "rpsResult", center=True)
        self.lay.addWidget(self.result)
        self.status = label("", "fileSub", center=True)
        self.lay.addWidget(self.status)
        self.again = button("再来一局", "link", lambda: self.act.emit("again", None))
        self.lay.addWidget(self.again, 0, Qt.AlignmentFlag.AlignHCenter)
        self.update_state(state)

    def update_state(self, st: dict) -> None:
        mine, theirs, res = st.get("mine"), st.get("theirs"), st.get("result")
        picking = not mine and not st.get("over")
        for k, b in self.btns.items():
            b.setVisible(picking)
        self.again.setVisible(bool(res))
        if res:
            self.result.setText(f"我 {RPS[mine]}  vs  {RPS[theirs]} 对方")
            self.status.setText({"win": "🎉 你赢了!", "lose": "你输了", "draw": "平局"}[res])
        elif mine:
            self.result.setText(f"我出了 {RPS[mine]}")
            self.status.setText("等对方出拳…(双方都出完才会揭晓,谁也偷看不到)")
        elif st.get("over"):
            self.result.setText("")
            self.status.setText("这局已结束")
        else:
            self.result.setText("")
            self.status.setText("对方已出拳,该你了" if st.get("their_ready") else "选一个出拳")


class BoardCard(CardBase):
    def __init__(self, msg, state: dict) -> None:
        super().__init__(msg)
        self.head("🎨", str(msg.card.get("title") or "一起画"))
        self.sub = label("", "fileSub")
        self.lay.addWidget(self.sub)
        b = button("打开画板", "primary", lambda: self.act.emit("open", None))
        self.lay.addWidget(b)
        self.update_state(state)

    def update_state(self, st: dict) -> None:
        n, people = st.get("strokes", 0), st.get("people", 0)
        self.sub.setText((f"已经画了 {n} 笔" if n else "空白画板") + (f"  ·  {people} 人正在画" if people else "")
                         + "\n所有人一起画,实时同步")


class ThrowStage(QWidget):
    """扔东西卡片里的小舞台:左边扔的人、右边被扔的人,道具沿抛物线飞过去砸中,痕迹留在头像上。点一下重播。"""
    W, H = 272, 112
    FLY = 0.62

    def __init__(self, card) -> None:
        super().__init__()
        from .throwfx import ITEM_BY_ID
        self.card = card
        c = card.msg.card or {}
        self.item = c.get("item") if c.get("item") in ITEM_BY_ID else "tomato"
        self.frm, self.to = str(c.get("from", "")), str(c.get("to", ""))
        self.fn, self.tn = str(c.get("fn", "?"))[:10], str(c.get("tn", "?"))[:10]
        self.n = max(1, int(c.get("n", 1) or 1))
        self.seed = int(c.get("seed", 7) or 7)
        self.pa = peer_avatar(self.frm, self.fn, 48)
        self.pb = peer_avatar(self.to, self.tn, 48)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点一下重播")
        self.t0 = -1e9
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    def play(self) -> None:
        self.t0 = time.monotonic()
        self.timer.start()
        self.update()

    def _tick(self) -> None:
        if time.monotonic() - self.t0 > self.FLY + 1.4:
            self.timer.stop()
        self.update()

    def mousePressEvent(self, _e) -> None:
        self.play()
        self.card.act.emit("replay", None)

    def paintEvent(self, _e) -> None:
        from .throwfx import draw_item, paint_stain
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        t = time.monotonic() - self.t0
        ax, bx, ay = 44.0, self.W - 44.0, 46.0
        r = 22.0
        p.setPen(QPen(QColor(T["faint"]), 1.4, Qt.PenStyle.DashLine))  # 虚线轨迹
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc = QPainterPath(QPointF(ax + r, ay - 6))
        arc.quadTo(QPointF((ax + bx) / 2, ay - 52), QPointF(bx - r, ay - 6))
        p.drawPath(arc)
        for x, pm in ((ax, self.pa), (bx, self.pb)):
            p.drawPixmap(QRectF(x - r, ay - r, r * 2, r * 2), pm, QRectF(pm.rect()))
        flying = 0 <= t < self.FLY
        if flying:                                         # 飞行中
            k = t / self.FLY
            x = ax + (bx - ax) * k
            y = ay - 6 - 4 * 23 * k * (1 - k)               # 和虚线轨迹一样高
            p.save()
            p.translate(x, y)
            p.rotate(540 * k)
            draw_item(p, self.item, 12, t)
            p.restore()
        else:                                              # 砸中之后(或者静止的样子):痕迹留在右边头像上
            th = t - self.FLY if t >= self.FLY else 1.3
            paint_stain(p, self.item, bx, ay, r, self.seed, min(th, 1.3), 1.0)
            if 0 <= t - self.FLY < 0.35:                   # 冲击的一圈短线
                k = (t - self.FLY) / 0.35
                p.save()
                p.setOpacity(1 - k)
                p.setPen(QPen(QColor(T["accent"]), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                for i in range(10):
                    a = i / 10 * 6.2832
                    p.drawLine(QPointF(bx + math.cos(a) * (r + 4 + 10 * k), ay + math.sin(a) * (r + 4 + 10 * k)),
                               QPointF(bx + math.cos(a) * (r + 10 + 14 * k), ay + math.sin(a) * (r + 10 + 14 * k)))
                p.restore()
            if not (0 <= t < self.FLY + 1.4):              # 中间放一个小小的道具图标
                p.save()
                p.translate((ax + bx) / 2, ay - 22)
                draw_item(p, self.item, 11, 0)
                p.restore()
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor(T["sub"]))
        fm = QFontMetrics(f)
        for x, name in ((ax, self.fn), (bx, self.tn)):
            p.drawText(QRectF(x - 50, ay + r + 6, 100, 18), fm.elidedText(name, Qt.TextElideMode.ElideRight, 96),
                       QTextOption(Qt.AlignmentFlag.AlignCenter))
        if self.n > 1:                                     # 连击
            f.setPixelSize(15)
            f.setWeight(QFont.Weight.Black)
            p.setFont(f)
            badge = QRectF(bx + 2, ay - r - 14, 40, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFD43B"))
            p.drawRoundedRect(badge, 10, 10)
            p.setPen(QColor("#3B2E2A"))
            p.drawText(badge, f"×{self.n}", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class ThrowCard(CardBase):
    """扔东西 / 送花的动画卡片(2.5):新收到的会自己播一遍,点一下重播(聊天区中间也会再放大播一次)。"""
    W = 300

    def __init__(self, msg, state: dict) -> None:
        super().__init__(msg)
        self.lay.setContentsMargins(14, 10, 14, 10)
        self.lay.setSpacing(4)
        self.stage = ThrowStage(self)
        self.lay.addWidget(self.stage, 0, Qt.AlignmentFlag.AlignHCenter)
        self.sub = label(self._caption(), "fileSub", wrap=True, center=True)
        self.lay.addWidget(self.sub)
        if state.get("fresh"):
            QTimer.singleShot(60, self.stage.play)

    def _caption(self) -> str:
        return (self.msg.text or "").split(" ", 1)[-1] if self.msg.text else ""

    def update_state(self, state: dict) -> None:
        n = state.get("n")
        if isinstance(n, int) and n != self.stage.n:
            self.stage.n = n
            self.sub.setText(self._caption())
            self.stage.play()


class LevelCard(CardBase):
    """群里别人(或自己)的宠物升级了:宠物小图 + 等级徽章 + 形态,新收到的会闪一下。"""
    W = 250

    def __init__(self, msg, state: dict) -> None:
        super().__init__(msg)
        self.lay.setContentsMargins(12, 10, 12, 10)
        self.view = _LevelView(msg.card or {})
        self.lay.addWidget(self.view, 0, Qt.AlignmentFlag.AlignHCenter)
        c = msg.card or {}
        sub = f"{c.get('name', '宠物')} · {c.get('form', '')}" if c.get("form") else str(c.get("name", "宠物"))
        self.lay.addWidget(label(sub, "fileSub", center=True))
        if state.get("fresh"):
            QTimer.singleShot(50, self.view.play)


class _LevelView(QWidget):
    W, H = 222, 104

    def __init__(self, c: dict) -> None:
        super().__init__()
        from .fun import pet_pixmap
        self.lv = max(1, min(99, int(c.get("lv", 1) or 1)))
        wear = [w for w in (c.get("wear") or []) if isinstance(w, str)]
        self.pm = pet_pixmap(str(c.get("sp", "cat")), self.lv, wear, 150, 92)
        self.setFixedSize(self.W, self.H)
        self.t0 = -1e9
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    def play(self) -> None:
        self.t0 = time.monotonic()
        self.timer.start()

    def _tick(self) -> None:
        if time.monotonic() - self.t0 > 1.8:
            self.timer.stop()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        t = time.monotonic() - self.t0
        cx = self.W / 2 - 18
        if 0 <= t < 1.8:                                   # 新收到:身后一圈光芒
            k = t / 1.8
            p.save()
            p.setOpacity(1 - k)
            p.setPen(QPen(QColor("#FFD43B"), 3 * (1 - k) + 0.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, 54), 30 + 50 * k, 22 + 36 * k)
            p.restore()
        p.drawPixmap(QRectF(cx - 75, 6, 150, 92), self.pm, QRectF(self.pm.rect()))
        badge = QRectF(self.W - 74, 24, 66, 34)
        g = QLinearGradient(badge.topLeft(), badge.bottomRight())
        g.setColorAt(0, QColor("#FFE066"))
        g.setColorAt(1, QColor("#F59F00"))
        p.setPen(QPen(QColor("#E8590C"), 1.2))
        p.setBrush(QBrush(g))
        pop = 1.0 + (0.25 * math.sin(min(1.0, t / 0.5) * math.pi) if 0 <= t < 0.5 else 0.0)
        p.save()
        p.translate(badge.center())
        p.scale(pop, pop)
        p.translate(-badge.center())
        p.drawRoundedRect(badge, 17, 17)
        f = QFont(self.font())
        f.setPixelSize(17)
        f.setWeight(QFont.Weight.Black)
        p.setFont(f)
        p.setPen(QColor("#5C3200"))
        p.drawText(badge, f"Lv.{self.lv}", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.restore()
        p.end()


def make_card(msg, state: dict) -> CardBase | None:
    c = msg.card or {}
    t = c.get("type")
    if t == "poll":
        return PollCard(msg, state)
    if t == "draw":
        return LotteryCard(msg, state)
    if t == "dice":
        return DiceCard(msg, state)
    if t == "game":
        return GomokuCard(msg, state) if c.get("game") == "gomoku" else RpsCard(msg, state)
    if t == "board":
        return BoardCard(msg, state)
    if t == "throw":
        return ThrowCard(msg, state)
    if t == "petlv":
        return LevelCard(msg, state)
    return None
