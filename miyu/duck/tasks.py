"""
谁是坏鸭 · 任务小游戏。每个小游戏是一块自己画的画布,做完发 done 信号。
    wires   接电线:左边四根线,拖到右边颜色一样的接口上
    swipe   刷卡:把卡从左拖到右,不能太快也不能太慢
    seq     按顺序点:1 到 8 按顺序点,点错从头来
    drag    拖进去:把东西一个个拖进目标框(喂鱼、拔萝卜、叉干草、搬箱子)
    memory  记号码:看 2.5 秒,然后凭记忆按出来
    switch  拨电闸:把五个开关都拨上去(关灯后修电闸用)
    dial    调频率:拖旋钮把信号调到满格,停住 1 秒
    clean   擦干净:按住鼠标来回擦,把污渍擦掉
鼠标逻辑写成 press / move / release(x, y) 这样的普通方法,测试里可以直接调用。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import QWidget


GW, GH = 440, 300
# 小游戏用自己固定的一套深色配色,不跟着主题变(浅色主题下白字落在白底上会看不见)
BG, PANEL, TEXT, SUB, ACCENT = "#2A2438", "#3A3350", "#FFFFFF", "#C7B8DC", "#9775FA"


def _now() -> float:
    return time.monotonic()


def _pos(e) -> tuple[float, float]:
    p = e.position()
    return p.x(), p.y()


class MiniGame(QWidget):
    done = Signal()
    TITLE = ""
    HINT = ""

    def __init__(self, parent=None, rng=None) -> None:
        super().__init__(parent)
        self.setFixedSize(GW, GH)
        self.setMouseTracking(True)
        self.rng = rng or random.Random()
        self.finished = False
        self.msg = ""
        self.msg_t = -1e9
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.setup()

    def setup(self) -> None:
        pass

    def _tick(self) -> None:
        if self.isVisible():
            self.update()

    def say(self, text: str) -> None:
        self.msg, self.msg_t = text, _now()

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.say("完成!")
        QTimer.singleShot(450, self.done.emit)

    # 鼠标:子类重写 press / move / release
    def press(self, x: float, y: float) -> None: ...
    def move(self, x: float, y: float) -> None: ...
    def release(self, x: float, y: float) -> None: ...

    def mousePressEvent(self, e) -> None:
        if not self.finished:
            self.press(*_pos(e))
            self.update()

    def mouseMoveEvent(self, e) -> None:
        if not self.finished:
            self.move(*_pos(e))
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if not self.finished:
            self.release(*_pos(e))
            self.update()

    # ---- 绘制
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bg = QColor(BG)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, GW, GH), 16, 16)
        self.draw(p)
        if self.msg and _now() - self.msg_t < 1.4:
            a = max(0.0, min(1.0, (1.4 - (_now() - self.msg_t)) / 0.3))
            p.setOpacity(a)
            f = QFont(self.font())
            f.setPixelSize(18)
            f.setWeight(QFont.Weight.Bold)
            p.setFont(f)
            r = QRectF(0, GH - 44, GW, 34)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawRoundedRect(QRectF(GW / 2 - 90, GH - 44, 180, 32), 16, 16)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(r.adjusted(0, -2, 0, -2), self.msg, QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()

    def draw(self, p: QPainter) -> None: ...

    def text(self, p: QPainter, rect: QRectF, s: str, size: int = 13, color: str | None = None, bold=False) -> None:
        f = QFont(self.font())
        f.setPixelSize(size)
        if bold:
            f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor(color or TEXT))
        p.drawText(rect, s, QTextOption(Qt.AlignmentFlag.AlignCenter))


# ---------------------------------------------------------------------- 接电线
class Wires(MiniGame):
    TITLE = "接电线"
    HINT = "把左边的电线拖到右边同样颜色的接口"
    COLS = ["#FF6B6B", "#4DABF7", "#FFD43B", "#69DB7C"]

    def setup(self) -> None:
        self.left = list(range(4))
        self.right = list(range(4))
        self.rng.shuffle(self.left)
        self.rng.shuffle(self.right)
        self.links: dict[int, int] = {}              # 左边第几根 → 右边第几个
        self.drag: tuple[int, float, float] | None = None

    def node(self, side: str, i: int) -> tuple[float, float]:
        return (46.0 if side == "l" else GW - 46.0), 70.0 + i * 52

    def _hit(self, side: str, x: float, y: float) -> int | None:
        for i in range(4):
            nx, ny = self.node(side, i)
            if math.hypot(x - nx, y - ny) < 24:
                return i
        return None

    def press(self, x, y) -> None:
        i = self._hit("l", x, y)
        if i is not None and i not in self.links:
            self.drag = (i, x, y)

    def move(self, x, y) -> None:
        if self.drag:
            self.drag = (self.drag[0], x, y)

    def release(self, x, y) -> None:
        if not self.drag:
            return
        i = self.drag[0]
        self.drag = None
        j = self._hit("r", x, y)
        if j is None:
            return
        if self.left[i] == self.right[j] and j not in self.links.values():
            self.links[i] = j
            if len(self.links) == 4:
                self.finish()
        else:
            self.say("颜色不对")

    def draw(self, p) -> None:
        self.text(p, QRectF(0, 10, GW, 30), self.HINT, 13, SUB)
        for side, order in (("l", self.left), ("r", self.right)):
            for i, c in enumerate(order):
                x, y = self.node(side, i)
                p.setPen(QPen(QColor(0, 0, 0, 96), 1))
                p.setBrush(QColor("#3A3350"))
                p.drawRoundedRect(QRectF(x - (40 if side == "l" else -10) - 6, y - 12, 36, 24), 6, 6)
                p.setBrush(QColor(self.COLS[c]))
                p.drawEllipse(QPointF(x, y), 11, 11)
        for i, j in self.links.items():
            self._wire(p, self.node("l", i), self.node("r", j), self.COLS[self.left[i]])
        if self.drag:
            i, x, y = self.drag
            self._wire(p, self.node("l", i), (x, y), self.COLS[self.left[i]])

    def _wire(self, p, a, b, col) -> None:
        path = QPainterPath(QPointF(*a))
        mx = (a[0] + b[0]) / 2
        path.cubicTo(QPointF(mx, a[1]), QPointF(mx, b[1]), QPointF(*b))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 90), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(QColor(col), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)


# ---------------------------------------------------------------------- 刷卡
class Swipe(MiniGame):
    TITLE = "刷卡"
    HINT = "按住卡片从左往右刷过去(别太快也别太慢)"
    X0, X1, Y = 70.0, GW - 70.0, 170.0

    def setup(self) -> None:
        self.cx = self.X0
        self.t0: float | None = None
        self.holding = False
        self.light = 0                                # 0 灰 / 1 绿 / -1 红

    def press(self, x, y) -> None:
        if abs(x - self.cx) < 50 and abs(y - self.Y) < 36:
            self.holding = True
            self.t0 = _now()
            self.light = 0

    def move(self, x, y) -> None:
        if self.holding:
            self.cx = max(self.X0, min(self.X1, x))

    def release(self, x, y, now: float | None = None) -> None:
        if not self.holding:
            return
        self.holding = False
        now = _now() if now is None else now
        if self.cx >= self.X1 - 4 and self.t0 is not None:
            dt = now - self.t0
            if dt < 0.45:
                self.say("太快了,再来")
                self.light = -1
            elif dt > 1.6:
                self.say("太慢了,再来")
                self.light = -1
            else:
                self.light = 1
                self.finish()
                return
        else:
            self.say("没刷完")
            self.light = -1
        self.cx = self.X0

    def draw(self, p) -> None:
        self.text(p, QRectF(0, 10, GW, 30), self.HINT, 13, SUB)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1F1A2C"))
        p.drawRoundedRect(QRectF(30, self.Y - 10, GW - 60, 20), 10, 10)
        col = {0: "#868E96", 1: "#51CF66", -1: "#FF6B6B"}[self.light]
        p.setBrush(QColor(col))
        p.drawEllipse(QPointF(GW - 40, 80), 9, 9)
        p.setPen(QPen(QColor(0, 0, 0, 128), 1))
        p.setBrush(QColor("#F8F9FA"))
        card = QRectF(self.cx - 46, self.Y - 30, 92, 60)
        p.drawRoundedRect(card, 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4DABF7"))
        p.drawRoundedRect(QRectF(card.x() + 8, card.y() + 10, 30, 22), 4, 4)
        p.setBrush(QColor("#CED4DA"))
        for k in range(3):
            p.drawRoundedRect(QRectF(card.x() + 44, card.y() + 12 + k * 9, 38 - k * 8, 4), 2, 2)


# ---------------------------------------------------------------------- 按顺序点
class Seq(MiniGame):
    TITLE = "按顺序点"
    HINT = "从 1 到 8 按顺序点,点错从头来"

    def setup(self) -> None:
        nums = list(range(1, 9))
        self.rng.shuffle(nums)
        self.cells = nums                              # 4×2 格子里的数字
        self.next = 1
        self.wrong_t = -1e9

    def cell_rect(self, i: int) -> QRectF:
        return QRectF(40 + (i % 4) * 92, 70 + (i // 4) * 96, 80, 84)

    def cell_at(self, x, y) -> int | None:
        for i in range(8):
            r = self.cell_rect(i)
            if r.left() <= x <= r.right() and r.top() <= y <= r.bottom():
                return i
        return None

    def press(self, x, y) -> None:
        i = self.cell_at(x, y)
        if i is None:
            return
        if self.cells[i] == self.next:
            self.next += 1
            if self.next > 8:
                self.finish()
        elif self.cells[i] >= self.next:
            self.next = 1
            self.wrong_t = _now()
            self.say("点错了,从 1 开始")

    def draw(self, p) -> None:
        self.text(p, QRectF(0, 10, GW, 30), self.HINT, 13, SUB)
        flash = _now() - self.wrong_t < 0.35
        for i, n in enumerate(self.cells):
            r = self.cell_rect(i)
            lit = n < self.next
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FF6B6B" if flash else ("#51CF66" if lit else "#3A3350")))
            p.drawRoundedRect(r, 12, 12)
            self.text(p, r, str(n), 26, "#FFFFFF", bold=True)


# ---------------------------------------------------------------------- 拖进去
class Drag(MiniGame):
    TITLE = "拖进去"
    KINDS = {"f_fish": ("喂鱼:把鱼食拖进池塘", "#C08552", "#4DABF7", "池塘"),
             "g_carrot": ("拔萝卜:拖进篮子", "#FF922B", "#B08968", "篮子"),
             "b_hay": ("把干草叉进槽里", "#FFD43B", "#8D6E63", "草槽"),
             "s_box": ("把箱子搬上架子", "#C99A70", "#868E96", "货架")}

    def __init__(self, parent=None, rng=None, tid: str = "f_fish") -> None:
        self.tid = tid if tid in self.KINDS else "f_fish"
        super().__init__(parent, rng)

    def setup(self) -> None:
        self.items = [[self.rng.uniform(40, 170), self.rng.uniform(70, 250), False] for _ in range(5)]
        self.target = QRectF(GW - 170, 80, 130, 160)
        self.hold: int | None = None
        self.off = (0.0, 0.0)

    @property
    def HINT(self) -> str:                             # noqa: N802
        return self.KINDS[self.tid][0]

    def press(self, x, y) -> None:
        for i in range(len(self.items) - 1, -1, -1):
            ix, iy, inside = self.items[i]
            if not inside and math.hypot(x - ix, y - iy) < 22:
                self.hold = i
                self.off = (ix - x, iy - y)
                return

    def move(self, x, y) -> None:
        if self.hold is not None:
            it = self.items[self.hold]
            it[0] = max(16, min(GW - 16, x + self.off[0]))
            it[1] = max(46, min(GH - 16, y + self.off[1]))

    def release(self, x, y) -> None:
        if self.hold is None:
            return
        it = self.items[self.hold]
        self.hold = None
        r = self.target
        if r.left() <= it[0] <= r.right() and r.top() <= it[1] <= r.bottom():
            it[2] = True
            if all(i[2] for i in self.items):
                self.finish()

    def draw(self, p) -> None:
        hint, item_col, box_col, box_name = self.KINDS[self.tid]
        self.text(p, QRectF(0, 10, GW, 30), hint, 13, SUB)
        p.setPen(QPen(QColor(255, 255, 255, 96), 2, Qt.PenStyle.DashLine))
        p.setBrush(QColor(box_col))
        p.drawRoundedRect(self.target, 16, 16)
        self.text(p, QRectF(self.target.x(), self.target.bottom() + 4, self.target.width(), 20), box_name, 12,
                  SUB)
        n_in = sum(1 for i in self.items if i[2])
        self.text(p, self.target, f"{n_in} / {len(self.items)}", 20, "#FFFFFF", bold=True)
        for ix, iy, inside in self.items:
            if inside:
                continue
            p.setPen(QPen(QColor(0, 0, 0, 112), 1.2))
            p.setBrush(QColor(item_col))
            if self.tid == "g_carrot":
                path = QPainterPath(QPointF(ix, iy + 18))
                path.lineTo(ix - 9, iy - 8)
                path.quadTo(ix, iy - 14, ix + 9, iy - 8)
                path.closeSubpath()
                p.drawPath(path)
                p.setBrush(QColor("#51CF66"))
                p.drawEllipse(QPointF(ix, iy - 15), 5, 7)
            elif self.tid == "s_box":
                p.drawRect(QRectF(ix - 15, iy - 13, 30, 26))
                p.drawLine(QPointF(ix - 15, iy - 4), QPointF(ix + 15, iy - 4))
            elif self.tid == "b_hay":
                p.drawRoundedRect(QRectF(ix - 18, iy - 10, 36, 20), 8, 8)
                p.setPen(QPen(QColor("#E8A200"), 1))
                for k in (-8, 0, 8):
                    p.drawLine(QPointF(ix + k, iy - 8), QPointF(ix + k + 3, iy + 8))
            else:
                p.drawEllipse(QPointF(ix, iy), 13, 10)
                p.setBrush(QColor("#8B5E34"))
                for dx, dy in ((-4, -2), (3, 2), (1, -4)):
                    p.drawEllipse(QPointF(ix + dx, iy + dy), 2, 2)


# ---------------------------------------------------------------------- 记号码
class Memory(MiniGame):
    TITLE = "记号码"
    HINT = "记住这串号码"
    SHOW = 2.5

    def setup(self) -> None:
        self.code = "".join(str(self.rng.randint(0, 9)) for _ in range(5))
        self.shown_at = _now()
        self.typed = ""

    def showing(self, now: float | None = None) -> bool:
        return ((_now() if now is None else now) - self.shown_at) < self.SHOW

    def key_rect(self, i: int) -> QRectF:                # 0~9 + 删除:两行
        return QRectF(28 + (i % 6) * 66, 160 + (i // 6) * 60, 58, 50)

    KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "删", "看"]

    def press(self, x, y) -> None:
        if self.showing():
            return
        for i, k in enumerate(self.KEYS):
            r = self.key_rect(i)
            if r.left() <= x <= r.right() and r.top() <= y <= r.bottom():
                self.key(k)
                return

    def key(self, k: str) -> None:
        if k == "删":
            self.typed = self.typed[:-1]
        elif k == "看":
            self.shown_at = _now()
            self.typed = ""
        elif len(self.typed) < 5:
            self.typed += k
            if len(self.typed) == 5:
                if self.typed == self.code:
                    self.finish()
                else:
                    self.say("不对,再看一次")
                    self.typed = ""
                    self.shown_at = _now()

    def draw(self, p) -> None:
        if self.showing():
            self.text(p, QRectF(0, 10, GW, 30), self.HINT, 13, SUB)
            self.text(p, QRectF(0, 70, GW, 80), " ".join(self.code), 44, "#FFFFFF", bold=True)
            left = self.SHOW - (_now() - self.shown_at)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(60, 190, (GW - 120) * max(0.0, left / self.SHOW), 8), 4, 4)
            return
        self.text(p, QRectF(0, 10, GW, 30), "凭记忆按出刚才的号码", 13, SUB)
        shown = " ".join(self.typed.ljust(5, "_"))
        self.text(p, QRectF(0, 60, GW, 80), shown, 40, "#FFFFFF", bold=True)
        for i, k in enumerate(self.KEYS):
            r = self.key_rect(i)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3A3350"))
            p.drawRoundedRect(r, 10, 10)
            self.text(p, r, k, 20, "#FFFFFF", bold=True)


# ---------------------------------------------------------------------- 拨电闸
class Switches(MiniGame):
    TITLE = "修电闸"
    HINT = "把五个开关全部拨上去"

    def setup(self) -> None:
        self.on = [False] * 5
        self.on[self.rng.randrange(5)] = True

    def sw_rect(self, i: int) -> QRectF:
        return QRectF(52 + i * 72, 90, 52, 120)

    def press(self, x, y) -> None:
        for i in range(5):
            r = self.sw_rect(i)
            if r.left() <= x <= r.right() and r.top() <= y <= r.bottom():
                self.on[i] = not self.on[i]
                if all(self.on):
                    self.finish()
                return

    def draw(self, p) -> None:
        self.text(p, QRectF(0, 10, GW, 30), self.HINT, 13, SUB)
        for i, on in enumerate(self.on):
            r = self.sw_rect(i)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#1F1A2C"))
            p.drawRoundedRect(r, 12, 12)
            knob = QRectF(r.x() + 6, r.y() + (8 if on else r.height() - 52), r.width() - 12, 44)
            p.setBrush(QColor("#51CF66" if on else "#FF6B6B"))
            p.drawRoundedRect(knob, 10, 10)
            self.text(p, QRectF(r.x(), r.bottom() + 6, r.width(), 20), "开" if on else "关", 12, SUB)


# ---------------------------------------------------------------------- 调频率
class Dial(MiniGame):
    TITLE = "调频率"
    HINT = "拖动旋钮,把信号调到满格,停住 1 秒"
    X0, X1, Y = 50.0, GW - 50.0, 220.0
    HOLD = 1.0

    def setup(self) -> None:
        self.target = self.rng.uniform(0.15, 0.85)
        self.v = 0.0 if self.target > 0.5 else 1.0
        self.hold = False
        self.good_since: float | None = None

    def strength(self) -> float:
        return max(0.0, 1.0 - abs(self.v - self.target) * 6)

    def press(self, x, y) -> None:
        if abs(y - self.Y) < 30:
            self.hold = True
            self.move(x, y)

    def move(self, x, y) -> None:
        if self.hold:
            self.v = max(0.0, min(1.0, (x - self.X0) / (self.X1 - self.X0)))

    def release(self, x, y) -> None:
        self.hold = False

    def check(self, now: float | None = None) -> None:
        now = _now() if now is None else now
        if self.strength() >= 0.92:
            if self.good_since is None:
                self.good_since = now
            elif now - self.good_since >= self.HOLD:
                self.finish()
        else:
            self.good_since = None

    def _tick(self) -> None:
        if not self.finished:
            self.check()
        super()._tick()

    def draw(self, p) -> None:
        self.text(p, QRectF(0, 10, GW, 30), self.HINT, 13, SUB)
        st = self.strength()
        for i in range(5):                                # 信号格
            h = 18 + i * 14
            on = st >= (i + 1) / 5 - 0.02
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#51CF66" if on else PANEL))
            p.drawRoundedRect(QRectF(GW / 2 - 70 + i * 30, 150 - h, 20, h), 4, 4)
        wave = QPainterPath()                             # 杂音波形:越准越平滑
        noise = 1 - st
        for i in range(0, 361, 6):
            x = 40 + i / 360 * (GW - 80)
            y = 175 + math.sin(i / 18 + _now() * 6) * (4 + 10 * noise) + (self.rng.random() - 0.5) * 14 * noise
            if i == 0:
                wave.moveTo(QPointF(x, y))
            else:
                wave.lineTo(QPointF(x, y))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawPath(wave)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1F1A2C"))
        p.drawRoundedRect(QRectF(self.X0 - 10, self.Y - 6, self.X1 - self.X0 + 20, 12), 6, 6)
        for k in range(11):
            x = self.X0 + (self.X1 - self.X0) * k / 10
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawRect(QRectF(x - 0.5, self.Y + 10, 1, 8))
        kx = self.X0 + (self.X1 - self.X0) * self.v
        p.setBrush(QColor("#FFD43B" if st >= 0.92 else "#F8F9FA"))
        p.setPen(QPen(QColor(0, 0, 0, 120), 1.5))
        p.drawEllipse(QPointF(kx, self.Y), 15, 15)
        if self.good_since is not None and not self.finished:
            k = min(1.0, (_now() - self.good_since) / self.HOLD)
            p.setPen(QPen(QColor("#51CF66"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(kx - 22, self.Y - 22, 44, 44), 90 * 16, int(-360 * 16 * k))


# ---------------------------------------------------------------------- 擦干净
class Clean(MiniGame):
    TITLE = "擦干净"
    HINT = "按住鼠标来回擦,把污渍全擦掉"
    CX, CY, R = GW / 2, 152.0, 104.0

    def setup(self) -> None:
        self.spots = []
        for _ in range(6):
            a = self.rng.uniform(0, math.tau)
            d = self.rng.uniform(0, self.R - 30)
            self.spots.append([self.CX + math.cos(a) * d, self.CY + math.sin(a) * d, self.rng.uniform(16, 24), 1.0])
        self.holding = False
        self.last: tuple[float, float] | None = None
        self.mouse = (self.CX, self.CY)

    def press(self, x, y) -> None:
        self.holding = True
        self.last = (x, y)

    def move(self, x, y) -> None:
        self.mouse = (x, y)
        if not self.holding or self.last is None:
            return
        moved = math.hypot(x - self.last[0], y - self.last[1])
        self.last = (x, y)
        for sp in self.spots:
            if sp[3] > 0 and math.hypot(x - sp[0], y - sp[1]) < sp[2] + 16:
                sp[3] = max(0.0, sp[3] - moved / 260)
        if all(sp[3] <= 0.02 for sp in self.spots):
            self.finish()

    def release(self, x, y) -> None:
        self.holding = False
        self.last = None

    def draw(self, p) -> None:
        self.text(p, QRectF(0, 10, GW, 30), self.HINT, 13, SUB)
        p.setPen(QPen(QColor("#ADB5BD"), 3))
        p.setBrush(QColor("#F8F9FA"))
        p.drawEllipse(QPointF(self.CX, self.CY), self.R, self.R)
        p.setPen(QPen(QColor("#DEE2E6"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(self.CX, self.CY), self.R - 18, self.R - 18)
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, r, dirt in self.spots:
            if dirt <= 0.02:
                continue
            p.setBrush(QColor(139, 94, 52, int(220 * dirt)))
            p.drawEllipse(QPointF(x, y), r, r * 0.8)
            p.setBrush(QColor(110, 70, 40, int(160 * dirt)))
            p.drawEllipse(QPointF(x + r * 0.3, y - r * 0.2), r * 0.4, r * 0.35)
        left = sum(1 for sp in self.spots if sp[3] > 0.02)
        self.text(p, QRectF(0, GH - 30, GW, 22), f"还剩 {left} 块污渍", 12, SUB)
        mx, my = self.mouse                                # 海绵
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(QColor("#FFD43B"))
        p.drawRoundedRect(QRectF(mx - 16, my - 11, 32, 22), 6, 6)
        p.setBrush(QColor("#69DB7C"))
        p.drawRoundedRect(QRectF(mx - 16, my - 11, 32, 7), 3, 3)
        if self.holding:
            p.setBrush(QColor(255, 255, 255, 170))
            for k in range(3):
                p.drawEllipse(QPointF(mx - 20 + k * 18, my + 16 + (k % 2) * 4), 4, 4)


KIND_CLASS = {"wires": Wires, "swipe": Swipe, "seq": Seq, "drag": Drag, "memory": Memory, "switch": Switches,
              "dial": Dial, "clean": Clean}


def make_game(kind: str, tid: str = "", parent=None, rng=None) -> MiniGame:
    cls = KIND_CLASS.get(kind, Seq)
    if cls is Drag:
        return Drag(parent, rng, tid)
    return cls(parent, rng)
