"""
谁是坏鸭 · 游戏窗口:大厅(房间列表、创建房间、单人试玩、玩法说明)、房间(选颜色、房主改设置、邀请、开始)、
游戏(地图 + 任务清单 + 进度条 + 操作按钮 + 任务小游戏 + 开会投票 + 投票结果 + 结算)。
窗口只管显示和收集操作,联网和裁判在 window/duck.py(主窗口的 DuckMixin)。
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..dialogs import Dialog
from ..gomoku.widgets import Segmented, elide
from ..gomoku.window import clear_layout, scroll_list
from ..ui import button, label, make_menu, popup
from . import world as Wd
from .rules import DETECTIVE, DUCK, DODO, GOOSE, MAX_PLAYERS, MIN_PLAYERS, ROLE_NAME, SHERIFF, team_of
from .tasks import GH, GW, make_game
from .view import MapView, draw_bird, paint_minimap

ROLE_DESC = {
    GOOSE: "做完自己的任务,或者开会把坏鸭投出去。小心落单!",
    DUCK: "趁没人看见刀掉好鹅,关灯、锁门制造混乱。坏鸭数量追上其他人就赢。",
    DODO: "你是中立的呆呆鹅:想办法让大家把你投出去,你就单独获胜!",
    SHERIFF: "你是警长(好鹅阵营):可以执法淘汰坏鸭,但如果对方不是坏鸭,倒下的是你自己。",
    DETECTIVE: "你是侦探(好鹅阵营):这局可以查验一个人是不是坏鸭(按 C),结果只有你知道。",
}
ROLE_COLOR = {GOOSE: "#69DB7C", DUCK: "#FF6B6B", DODO: "#FFD43B", SHERIFF: "#74C0FC", DETECTIVE: "#B197FC"}
ROLE_COLOR_LIGHT = {GOOSE: "#2B8A3E", DUCK: "#C92A2A", DODO: "#B08800", SHERIFF: "#1864AB", DETECTIVE: "#5F3DC4"}


def role_color(role: str, on_light: bool = False) -> str:
    return (ROLE_COLOR_LIGHT if on_light else ROLE_COLOR).get(role, "#868E96" if on_light else "#FFFFFF")
HOW_TO = ("· 4~10 人。开局每个人只知道自己的身份:大多数是好鹅,有 1~2 只坏鸭,6 人以上可能有一只呆呆鹅。\n"
          "· WASD / 方向键走路;E 使用(做任务、修电闸、按紧急按钮);R 报告尸体;Q 刀人(坏鸭 / 警长);F 搞破坏(坏鸭);"
          "C 查验(侦探);M 小地图。\n"
          "· 5 人以上有警长(能执法,执法错了自己倒下),6 人以上有侦探(每局查验一个人)。\n"
          "· 发现尸体或者按紧急按钮就开会:先讨论,再投票,票最多的被投出去(平票没人出局)。\n"
          "· 好鹅做完所有任务或投出所有坏鸭获胜;坏鸭数量追上其他人时坏鸭获胜;呆呆鹅被投出去时呆呆鹅获胜。\n"
          "· 死了会变成幽灵:能穿墙,还可以继续做任务,只能和幽灵说话。")


def bird_icon(color: str, size: int = 40, ghost: bool = False) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_bird(p, size / 2 - 2, size / 2 + 4, color, 1, 0.0, False, ghost=ghost, scale=size / 48)
    p.end()
    return QIcon(pm)


def color_hex(cid: str) -> str:
    c = Wd.COLOR_BY_ID.get(cid)
    return c[2] if c else "#CCCCCC"


# ====================================================================== 大厅
class LobbyPage(QWidget):
    def __init__(self, dw: "DuckWindow") -> None:
        super().__init__()
        self.dw, self.w = dw, dw.w
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 14, 22, 18)
        root.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(10)
        hero = QFrame()
        hero.setObjectName("gmHero")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.addWidget(label("🦆 谁是坏鸭", "gmHello"))
        hl.addWidget(label("局域网多人推理小游戏 · 4~10 人 · 原创地图「鹅鸭庄园」", "gmHeroSub"))
        left.addWidget(hero)
        top = QHBoxLayout()
        top.addWidget(label("房间列表", "section"))
        top.addStretch(1)
        left.addLayout(top)
        self.area, self.list = scroll_list()
        left.addWidget(self.area, 1)
        root.addLayout(left, 3)
        side = QFrame()
        side.setObjectName("gmSide")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 16, 18, 16)
        sl.setSpacing(10)
        sl.addWidget(label("开一个房间", "cardTitle"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("房间名(可以不填)")
        self.name_edit.setMaxLength(16)
        sl.addWidget(self.name_edit)
        sl.addWidget(button("创建房间", "primary", self._create))
        sl.addWidget(button("单人试玩(熟悉地图和任务)", "", lambda: self.w.dk_practice()))
        sl.addSpacing(6)
        sl.addWidget(label("怎么玩", "cardTitle"))
        sl.addWidget(label(HOW_TO, "faint", wrap=True))
        sl.addStretch(1)
        root.addWidget(side, 2)
        self._sig = None

    def _create(self) -> None:
        self.w.dk_create_room(self.name_edit.text().strip())

    def refresh(self, force: bool = False) -> None:
        rooms = self.w.dk_rooms_list()
        sig = tuple((r["id"], r["n"], r["st"], r["name"]) for r in rooms)
        if sig == self._sig and not force:
            return
        self._sig = sig
        clear_layout(self.list)
        if not rooms:
            self.list.addWidget(label("现在没有人开房间。点右边「创建房间」开一个,然后邀请大家进来!", "gmEmpty",
                                      wrap=True, center=True))
        for r in rooms:
            self.list.addWidget(self._row(r))
        self.list.addStretch(1)

    def _row(self, r: dict) -> QFrame:
        row = QFrame()
        row.setObjectName("gmRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 10, 12, 10)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = label("", "gmRowTitle")
        elide(t, r["name"], 260)
        col.addWidget(t)
        st = "等人中" if r["st"] == "wait" else "游戏中"
        col.addWidget(label(f"房主 {r['host_nick']} · {r['n']} / {MAX_PLAYERS} 人 · {st}", "gmRowSub"))
        lay.addLayout(col, 1)
        ok = r["st"] == "wait" and r["n"] < MAX_PLAYERS
        b = button("加入" if ok else ("满了" if r["st"] == "wait" else "游戏中"), "primary" if ok else "",
                   lambda _=False, rid=r["id"]: self.w.dk_join(rid), 76)
        b.setEnabled(ok)
        lay.addWidget(b)
        return row


# ====================================================================== 房间(等人)
SETTING_ROWS = [
    ("ducks", "坏鸭数量", [(0, "自动"), (1, "1 只"), (2, "2 只"), (3, "3 只")]),
    ("dodo", "呆呆鹅", [(True, "有(6 人以上)"), (False, "没有")]),
    ("kill_cd", "刀的冷却", [(15, "15 秒"), (25, "25 秒"), (35, "35 秒")]),
    ("tasks", "每人任务", [(3, "3 个"), (5, "5 个"), (7, "7 个")]),
    ("discuss", "讨论时间", [(0, "不讨论"), (15, "15 秒"), (30, "30 秒")]),
    ("vote", "投票时间", [(30, "30 秒"), (45, "45 秒"), (60, "60 秒")]),
    ("reveal", "投出去公布身份", [(True, "公布"), (False, "不公布")]),
    ("sheriff", "警长(5 人以上)", [(True, "有"), (False, "没有")]),
    ("detective", "侦探(6 人以上)", [(True, "有"), (False, "没有")]),
]


class RoomPage(QWidget):
    def __init__(self, dw: "DuckWindow") -> None:
        super().__init__()
        self.dw, self.w = dw, dw.w
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 14, 22, 18)
        root.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(10)
        self.title = label("", "gmHello")
        left.addWidget(self.title)
        self.sub = label("", "gmHeroSub", wrap=True)
        left.addWidget(self.sub)
        self.grid_box = QWidget()
        self.grid = QGridLayout(self.grid_box)
        self.grid.setSpacing(10)
        self.grid.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.grid_box)
        left.addWidget(label("我的颜色", "section"))
        self.colors = QHBoxLayout()
        self.colors.setSpacing(6)
        self.color_btns: dict[str, QPushButton] = {}
        for cid, cname, hexc in Wd.COLORS:
            b = QPushButton("")
            b.setObjectName("dkColor")
            b.setFixedSize(34, 34)
            b.setToolTip(cname)
            b.setIcon(bird_icon(hexc, 30))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=cid: self.w.dk_set_color(c))
            self.colors.addWidget(b)
            self.color_btns[cid] = b
        self.colors.addStretch(1)
        left.addLayout(self.colors)
        left.addStretch(1)
        btns = QHBoxLayout()
        self.start_btn = button("开始游戏", "primary", lambda: self.w.dk_start(), 140)
        btns.addWidget(self.start_btn)
        btns.addWidget(button("离开房间", "", lambda: self.w.dk_leave_room(), 110))
        btns.addStretch(1)
        left.addLayout(btns)
        root.addLayout(left, 3)
        side = QFrame()
        side.setObjectName("gmSide")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 16, 18, 16)
        sl.setSpacing(8)
        sl.addWidget(label("游戏设置", "cardTitle"))
        self.set_hint = label("", "faint", wrap=True)
        sl.addWidget(self.set_hint)
        self.segs: dict[str, Segmented] = {}
        for key, title, opts in SETTING_ROWS:
            sl.addWidget(label(title, "gmSub"))
            seg = Segmented([(str(v), t) for v, t in opts])
            seg.changed.connect(lambda k, key=key, opts=opts: self._set(key, k, opts))
            sl.addWidget(seg)
            self.segs[key] = seg
        sl.addSpacing(6)
        sl.addWidget(label("邀请在线的人", "cardTitle"))
        self.inv_area, self.inv_list = scroll_list()
        sl.addWidget(self.inv_area, 1)
        root.addWidget(side, 2)
        self._sig = None

    def _set(self, key: str, k: str, opts) -> None:
        for v, _t in opts:
            if str(v) == k:
                self.w.dk_set_setting(key, v)
                return

    def refresh(self, force: bool = False) -> None:
        room = self.w.dk_room
        if room is None:
            return
        me = self.w.dk_my_id()
        host = room["host"] == me
        members = room["members"]
        self.title.setText(f"🦆 {room['name']}")
        n = len(members)
        need = max(0, MIN_PLAYERS - n)
        self.sub.setText((f"还差 {need} 个人才能开始" if need else "人够了,房主可以开始游戏") +
                         f" · {n} / {MAX_PLAYERS} 人 · 房主 {self.w.dk_nick(room['host'])}")
        sig = (tuple((m["id"], m["color"], m["nick"]) for m in members), room["host"], tuple(sorted(room["s"].items())))
        if sig != self._sig or force:
            self._sig = sig
            clear_layout(self.grid)
            for i, m in enumerate(members):
                self.grid.addWidget(self._card(m, m["id"] == room["host"], m["id"] == me), i // 5, i % 5)
            for j in range(len(members), MAX_PLAYERS):
                empty = QFrame()
                empty.setObjectName("dkSlot")
                empty.setFixedSize(110, 104)
                self.grid.addWidget(empty, j // 5, j % 5)
            taken = {m["color"] for m in members if m["id"] != me}
            mine = next((m["color"] for m in members if m["id"] == me), None)
            for cid, b in self.color_btns.items():
                b.setEnabled(cid not in taken)
                b.setProperty("sel", "true" if cid == mine else "false")
                b.style().unpolish(b)
                b.style().polish(b)
            for key, _t, _o in SETTING_ROWS:
                self.segs[key].select(str(room["s"].get(key)), emit=False)
                self.segs[key].setEnabled(host)
            self.set_hint.setText("你是房主,可以改设置。" if host else "只有房主能改设置。")
            self.start_btn.setVisible(host)
            self.start_btn.setEnabled(MIN_PLAYERS <= n <= MAX_PLAYERS)
            self._fill_invites(members)

    def _fill_invites(self, members) -> None:
        clear_layout(self.inv_list)
        inside = {m["id"] for m in members}
        friends = [f for f in self.w.dk_friends() if f["id"] not in inside]
        if not friends:
            self.inv_list.addWidget(label("没有其他在线的人", "gmEmpty", wrap=True, center=True))
        for f in friends[:30]:
            row = QHBoxLayout()
            t = label("", "gmRowTitle")
            elide(t, f["nick"], 120)
            row.addWidget(t, 1)
            b = button("邀请", "", lambda _=False, pid=f["id"]: self.w.dk_invite(pid), 60)
            b.setMinimumHeight(28)
            row.addWidget(b)
            box = QWidget()
            box.setLayout(row)
            self.inv_list.addWidget(box)
        self.inv_list.addStretch(1)

    def _card(self, m: dict, host: bool, me: bool) -> QFrame:
        card = QFrame()
        card.setObjectName("dkSlotMe" if me else "dkSlotOn")
        card.setFixedSize(110, 104)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(2)
        ic = QPushButton("")
        ic.setObjectName("dkBird")
        ic.setIcon(bird_icon(color_hex(m["color"]), 44))
        ic.setIconSize(QSize(44, 44))
        ic.setFixedSize(52, 52)
        ic.setFlat(True)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        t = label("", "gmRowTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elide(t, m["nick"] + (" 👑" if host else ""), 96)
        lay.addWidget(t)
        return card


# ====================================================================== 游戏中:画在地图上面的大字
class GameOverlay(QWidget):
    """身份揭晓、被刀、投票结果这些盖在地图上的大字。不挡鼠标。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.client = None
        self.reveal_t = -1e9
        self._dead_t = -1e9
        self._dead_for = None

    def paintEvent(self, _e) -> None:
        c = self.client
        if c is None:
            return
        now = time.monotonic()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        t = now - self.reveal_t
        if t < 4.0:
            a = min(1.0, t / 0.3, (4.0 - t) / 0.6)
            p.setOpacity(max(0.0, a))
            p.fillRect(QRectF(0, 0, w, h), QColor(12, 10, 20, 225))
            draw_bird(p, w / 2, h / 2 - 40, c.color(c.me), 1, now, False, scale=2.6)
            self._big(p, QRectF(0, h / 2 + 30, w, 60), f"你是 {ROLE_NAME.get(c.role, '')}", 40, role_color(c.role))
            self._big(p, QRectF(w * 0.15, h / 2 + 92, w * 0.7, 60), ROLE_DESC.get(c.role, ""), 16, "#DEE2E6")
            if c.role == DUCK and c.mates:
                self._big(p, QRectF(0, h / 2 + 150, w, 30), "你的同伴:" + "、".join(c.nick(m) for m in c.mates), 16,
                          "#FF8787")
            p.setOpacity(1.0)
        if c.dead_by and c.phase == "play":
            if self._dead_for != c.dead_by:
                self._dead_t, self._dead_for = now, c.dead_by
            dt = now - self._dead_t
            if dt < 3.2:
                a = min(1.0, dt / 0.25, (3.2 - dt) / 0.6)
                p.setOpacity(max(0.0, a))
                p.fillRect(QRectF(0, 0, w, h), QColor(60, 0, 0, 170))
                self._big(p, QRectF(0, h / 2 - 50, w, 60), "你被淘汰了", 42, "#FFFFFF")
                if c.misfire:
                    why = f"你执法的 {c.nick(c.misfire)} 不是坏鸭,倒下的是你自己。现在你是幽灵,可以穿墙、继续做任务。"
                else:
                    why = f"是 {c.nick(c.dead_by)} 干的!现在你是幽灵,可以穿墙、继续做任务。"
                self._big(p, QRectF(w * 0.1, h / 2 + 10, w * 0.8, 50), why, 16, "#FFC9C9")
                p.setOpacity(1.0)
        if c.phase not in ("over",) and c.host != c.me and now - c.last_snap > 3.0 and c.snaps:
            p.setOpacity(1.0)
            r = QRectF(w / 2 - 170, 70, 340, 40)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 190))
            p.drawRoundedRect(r, 20, 20)
            gone = int(now - c.last_snap)
            self._big(p, r, f"⏳ 和房主的连接不稳定,正在重连…({gone} 秒)", 14, "#FFE066")
        if c.phase == "eject" and c.eject:
            et = now - c.eject["t"]
            p.fillRect(QRectF(0, 0, w, h), QColor(12, 10, 20, 235))
            for k in range(60):                              # 星空
                x = (k * 137.5) % w
                y = (k * 91.3 + et * 20 * (1 + k % 3)) % h
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 60 + (k % 4) * 40))
                p.drawEllipse(QPointF(x, y), 1.2 + (k % 3) * 0.6, 1.2 + (k % 3) * 0.6)
            out = c.eject["out"]
            if out:
                x = -80 + (w + 160) * min(1.0, et / 3.2)
                p.save()
                p.translate(x, h / 2 - 30)
                p.rotate(et * 160)
                draw_bird(p, 0, 0, c.color(out), 1, now, False, scale=2.0)
                p.restore()
                if et > 1.0:
                    role = c.eject.get("role")
                    if role is None:
                        text = f"{c.nick(out)} 被投出去了。"
                    elif role == DUCK:
                        text = f"{c.nick(out)} 是坏鸭!"
                    elif role == DODO:
                        text = f"{c.nick(out)} 是呆呆鹅……它就想被投出去!"
                    elif role in (SHERIFF, DETECTIVE):
                        text = f"{c.nick(out)} 不是坏鸭,是{ROLE_NAME[role]}!"
                    else:
                        text = f"{c.nick(out)} 不是坏鸭。"
                    self._big(p, QRectF(0, h / 2 + 50, w, 60), text, 30, "#FFFFFF")
            else:
                self._big(p, QRectF(0, h / 2 - 30, w, 60), "没有人被投出去。", 30, "#FFFFFF")
            tally: dict = {}
            for v in c.eject["votes"].values():
                tally[v] = tally.get(v, 0) + 1
            parts = [f"{'弃票' if k == 'skip' else c.nick(k)} {n} 票" for k, n in sorted(tally.items(), key=lambda kv: -kv[1])]
            self._big(p, QRectF(0, h - 70, w, 30), "  ·  ".join(parts) if parts else "没有人投票", 14, "#ADB5BD")
        p.end()

    def _big(self, p: QPainter, r: QRectF, text: str, size: int, color: str) -> None:
        f = QFont(self.font())
        f.setPixelSize(size)
        f.setWeight(QFont.Weight.Black if size >= 28 else QFont.Weight.Bold)
        p.setFont(f)
        opt = QTextOption(Qt.AlignmentFlag.AlignCenter)
        opt.setWrapMode(QTextOption.WrapMode.WordWrap)
        p.setPen(QColor(0, 0, 0, 150))
        p.drawText(r.translated(0, 2), text, opt)
        p.setPen(QColor(color))
        p.drawText(r, text, opt)


# ====================================================================== 小地图 / 幽灵聊天
class MiniMap(QWidget):
    def __init__(self, gp: "GamePage") -> None:
        super().__init__(gp)
        self.gp = gp
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def paintEvent(self, _e) -> None:
        c = self.gp.w.dk_client
        if c is None:
            return
        p = QPainter(self)
        paint_minimap(p, QRectF(0, 0, self.width(), self.height()), c, time.monotonic())
        p.end()


class GhostChat(QFrame):
    """死了以后:平时也能和其他幽灵说话(活人看不到)。"""

    def __init__(self, gp: "GamePage") -> None:
        super().__init__(gp)
        self.gp, self.w = gp, gp.w
        self.setObjectName("dkCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(4)
        lay.addWidget(label("👻 幽灵频道(活人看不到)", "cardTitle"))
        self.text = label("", "dkTasks", wrap=True)
        lay.addWidget(self.text, 1)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("和其他幽灵说话……(回车发送)")
        self.edit.setMaxLength(120)
        self.edit.returnPressed.connect(self._send)
        lay.addWidget(self.edit)
        self._n = -1
        self.hide()

    def _send(self) -> None:
        t = self.edit.text().strip()
        if t:
            self.w.dk_chat(t)
            self.edit.clear()
        self.gp.map.setFocus()

    def refresh(self, c) -> None:
        msgs = [m for m in c.chat if m.get("ghost")]
        if len(msgs) == self._n:
            return
        self._n = len(msgs)
        self.text.setText("\n".join(f"{c.nick(m['by'])}:{m['text']}" for m in msgs[-6:]) or "还没有人说话")


# ====================================================================== 开会
class MeetingPanel(QFrame):
    def __init__(self, gp: "GamePage") -> None:
        super().__init__(gp)
        self.gp, self.w = gp, gp.w
        self.setObjectName("dkPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)
        head = QHBoxLayout()
        self.title = label("", "dialogTitle")
        head.addWidget(self.title, 1)
        self.timer = label("", "gmNum")
        head.addWidget(self.timer)
        root.addLayout(head)
        self.sub = label("", "faint", wrap=True)
        root.addWidget(self.sub)
        body = QHBoxLayout()
        body.setSpacing(14)
        gridw = QWidget()
        self.grid = QGridLayout(gridw)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 0, 0)
        body.addWidget(gridw, 3)
        chat = QVBoxLayout()
        self.chat_area, self.chat_list = scroll_list()
        chat.addWidget(self.chat_area, 1)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("说点什么……(回车发送)")
        self.edit.setMaxLength(120)
        self.edit.returnPressed.connect(self._send)
        row.addWidget(self.edit, 1)
        row.addWidget(button("发送", "", self._send, 60))
        chat.addLayout(row)
        body.addLayout(chat, 2)
        root.addLayout(body, 1)
        foot = QHBoxLayout()
        self.skip_btn = button("弃票", "", lambda: self.w.dk_vote("skip"), 90)
        foot.addWidget(self.skip_btn)
        self.vote_hint = label("", "faint")
        foot.addWidget(self.vote_hint, 1)
        root.addLayout(foot)
        self.vote_btns: dict[str, QPushButton] = {}
        self._sig = None
        self._chat_n = -1

    def _send(self) -> None:
        text = self.edit.text().strip()
        if text:
            self.w.dk_chat(text)
            self.edit.clear()

    def refresh(self, c, now: float) -> None:
        m = c.meeting or {}
        caller = m.get("caller")
        body = m.get("body")
        self.title.setText("🚨 发现尸体!" if body else "🔔 紧急会议")
        self.sub.setText((f"{c.nick(caller)} 发现了 {c.nick(body)} 的尸体。" if body else f"{c.nick(caller)} 按下了紧急按钮。")
                         + ("  你已经是幽灵了,只能看、只能和幽灵说话。" if not c.alive else ""))
        left = c.phase_left(now)
        self.timer.setText(f"{int(math.ceil(left))} 秒")
        voting = c.vote_in - (now - c.left_at) <= 0
        ids = list(c.roster)
        sig = (tuple(ids), tuple(sorted(c.voted)), c.alive, voting, c.my_vote, tuple(sorted(c.gone)),
               tuple(sorted(k for k, v in c.alive_of.items() if v)))
        if sig != self._sig:
            self._sig = sig
            clear_layout(self.grid)
            self.vote_btns.clear()
            for i, pid in enumerate(ids):
                alive = bool(c.alive_of.get(pid, 1)) and pid not in c.gone if pid != c.me else c.alive
                tag = "  ✅" if pid in c.voted else ""
                b = QPushButton(("" if alive else "👻 ") + c.nick(pid) + ("(我)" if pid == c.me else "") + tag)
                b.setObjectName("dkVote")
                b.setIcon(bird_icon(c.color(pid), 30, ghost=not alive))
                b.setMinimumHeight(44)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setEnabled(alive and c.alive and voting and c.my_vote is None)
                if c.my_vote == pid:
                    b.setProperty("sel", "true")
                b.clicked.connect(lambda _=False, t=pid: self.w.dk_vote(t))
                self.grid.addWidget(b, i // 2, i % 2)
                self.vote_btns[pid] = b
            self.skip_btn.setEnabled(c.alive and voting and c.my_vote is None)
        if not c.alive:
            self.vote_hint.setText("幽灵不能投票")
        elif c.my_vote is not None:
            self.vote_hint.setText("你投了:" + ("弃票" if c.my_vote == "skip" else c.nick(c.my_vote)))
        elif not voting:
            self.vote_hint.setText(f"先讨论,{int(math.ceil(c.vote_in - (now - c.left_at)))} 秒后开始投票")
        else:
            self.vote_hint.setText("点一个人投给 TA,或者弃票")
        if len(c.chat) != self._chat_n:
            self._chat_n = len(c.chat)
            clear_layout(self.chat_list)
            for msg in c.chat[-40:]:
                who = c.nick(msg["by"]) + ("(幽灵)" if msg.get("ghost") else "")
                lab = label(f"{who}:{msg['text']}", "dkChatGhost" if msg.get("ghost") else "dkChat", wrap=True)
                self.chat_list.addWidget(lab)
            self.chat_list.addStretch(1)
            QTimer.singleShot(0, lambda: self.chat_area.verticalScrollBar().setValue(
                self.chat_area.verticalScrollBar().maximum()))


# ====================================================================== 结算
class ResultPanel(QFrame):
    def __init__(self, gp: "GamePage") -> None:
        super().__init__(gp)
        self.gp, self.w = gp, gp.w
        self.setObjectName("dkPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(10)
        self.title = label("", "gmHello")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.title)
        self.why = label("", "faint", wrap=True, center=True)
        root.addWidget(self.why)
        body = QHBoxLayout()
        body.setSpacing(14)
        gw = QWidget()
        self.grid = QGridLayout(gw)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 0, 0)
        body.addWidget(gw, 3)
        tl = QVBoxLayout()
        tl.addWidget(label("这局发生了什么", "cardTitle"))
        self.log_area, self.log_list = scroll_list()
        tl.addWidget(self.log_area, 1)
        body.addLayout(tl, 2)
        root.addLayout(body, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.back_btn = button("回到房间", "primary", lambda: self.w.dk_back_to_room(), 140)
        row.addWidget(self.back_btn)
        row.addWidget(button("离开", "", lambda: self.w.dk_leave_room(), 100))
        row.addStretch(1)
        root.addLayout(row)
        self._shown = None

    def refresh(self, c) -> None:
        o = c.over or {}
        key = (o.get("win"), o.get("t"))
        if key == self._shown:
            return
        self._shown = key
        win = o.get("win")
        mine = win is not None and team_of(c.role) == win
        from ..theme import is_dark
        light = not is_dark()
        if win is None:
            self.title.setText("游戏中断了")
            self.why.setText(o.get("why", ""))
        else:
            self.title.setText(f"{ROLE_NAME.get(win, '')}获胜!" + ("  🎉" if mine else ""))
            self.why.setText(o.get("why", "") + ("  你赢了!" if mine else "  这局你输了。"))
        clear_layout(self.grid)
        roles = o.get("roles") or {}
        for i, (pid, role) in enumerate(roles.items()):
            box = QFrame()
            box.setObjectName("gmRow")
            bl = QHBoxLayout(box)
            bl.setContentsMargins(10, 6, 12, 6)
            ic = QPushButton("")
            ic.setFlat(True)
            ic.setIcon(bird_icon(c.color(pid), 30))
            bl.addWidget(ic)
            t = label("", "gmRowTitle")
            elide(t, c.nick(pid) + ("(我)" if pid == c.me else ""), 120)
            bl.addWidget(t, 1)
            r = label(ROLE_NAME.get(role, role), "gmRowSub")
            r.setStyleSheet(f"color: {role_color(role, light)}; font-weight: 700;")
            bl.addWidget(r)
            self.grid.addWidget(box, i, 0)
        clear_layout(self.log_list)
        lines = c.log_lines()
        if not lines:
            self.log_list.addWidget(label("没有记录", "gmEmpty", center=True))
        for line in lines:
            self.log_list.addWidget(label(line, "dkLog", wrap=True))
        self.log_list.addStretch(1)
        self.back_btn.setVisible(self.w.dk_room is not None and not self.w.dk_practice_on)


# ====================================================================== 任务框
class TaskHost(QFrame):
    def __init__(self, gp: "GamePage") -> None:
        super().__init__(gp)
        self.gp = gp
        self.setObjectName("dkPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(8)
        head = QHBoxLayout()
        self.title = label("", "cardTitle")
        head.addWidget(self.title, 1)
        head.addWidget(button("✕ 关闭(Esc)", "", self.close_task, 90))
        root.addLayout(head)
        self.slot = QVBoxLayout()
        root.addLayout(self.slot)
        self.game = None
        self.tid = None
        self.setFixedSize(GW + 32, GH + 84)
        self.hide()

    def open(self, kind: str, tid: str, title: str) -> None:
        self.close_task()
        self.tid = tid
        self.title.setText(title)
        g = make_game(kind, tid, self)
        g.done.connect(self._done)
        self.slot.addWidget(g)
        self.game = g
        self.show()
        self.raise_()
        g.setFocus()

    def _done(self) -> None:
        tid = self.tid
        self.close_task()
        self.gp.task_done(tid)

    def close_task(self) -> None:
        if self.game is not None:
            self.game.hide()
            self.game.deleteLater()
            self.game = None
        if self.tid == "__switch__":
            self.gp.switch_closed()
        self.tid = None
        self.hide()
        self.gp.map.setFocus()

    def busy(self) -> bool:
        return self.game is not None


# ====================================================================== 游戏页
class GamePage(QWidget):
    KEYS = {Qt.Key.Key_W: (0, -1), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_S: (0, 1), Qt.Key.Key_Down: (0, 1),
            Qt.Key.Key_A: (-1, 0), Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_D: (1, 0), Qt.Key.Key_Right: (1, 0)}

    def __init__(self, dw: "DuckWindow") -> None:
        super().__init__()
        self.dw, self.w = dw, dw.w
        self.map = MapView(self)
        self.overlay = GameOverlay(self)
        self.tasks_card = QFrame(self)
        self.tasks_card.setObjectName("dkCard")
        tl = QVBoxLayout(self.tasks_card)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(2)
        self.tasks_title = label("我的任务", "cardTitle")
        tl.addWidget(self.tasks_title)
        self.tasks_text = label("", "dkTasks", wrap=True)
        tl.addWidget(self.tasks_text)
        self.bar = QFrame(self)
        self.bar.setObjectName("dkCard")
        bl = QVBoxLayout(self.bar)
        bl.setContentsMargins(14, 8, 14, 8)
        self.bar_text = label("", "gmSub")
        bl.addWidget(self.bar_text)
        self.bar_fill = QFrame()
        self.bar_fill.setObjectName("dkBarFill")
        self.bar_fill.setFixedHeight(8)
        self.bar_track = QFrame()
        self.bar_track.setObjectName("dkBarTrack")
        self.bar_track.setFixedHeight(8)
        trk = QHBoxLayout(self.bar_track)
        trk.setContentsMargins(0, 0, 0, 0)
        trk.addWidget(self.bar_fill)
        trk.addStretch(1)
        bl.addWidget(self.bar_track)
        self.role_chip = label("", "dkRole")
        self.role_chip.setParent(self)
        self.leave_btn = button("退出游戏", "", self._leave, 90)
        self.leave_btn.setParent(self)
        self.hint = label("", "dkHint", wrap=True)
        self.hint.setParent(self)
        self.map_btn = button("🗺 地图 M", "", self.toggle_map, 90)
        self.map_btn.setParent(self)
        self.map_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.minimap = MiniMap(self)
        self.ghost_chat = GhostChat(self)
        self.acts: dict[str, QPushButton] = {}
        for key, text in (("use", "使用\nE"), ("report", "报告\nR"), ("kill", "刀\nQ"), ("sabo", "破坏\nF"),
                          ("check", "查验\nC")):
            b = QPushButton(text, self)
            b.setObjectName("dkAct_" + key)
            b.setFixedSize(84, 84)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, k=key: self.do(k))
            self.acts[key] = b
        self.meeting = MeetingPanel(self)
        self.meeting.hide()
        self.result = ResultPanel(self)
        self.result.hide()
        self.taskhost = TaskHost(self)
        self.keys: set = set()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.frame)
        self._last = time.monotonic()
        self._hud_t = 0.0
        self._phase = None
        self._act_state: dict[str, tuple] = {}
        self._was_lagging = False

    # ---- 布局
    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.layout_hud()

    def layout_hud(self) -> None:
        w, h = self.width(), self.height()
        self.map.setGeometry(0, 0, w, h)
        self.overlay.setGeometry(0, 0, w, h)
        self.tasks_card.setGeometry(14, 14, 250, 230)
        bw = min(420, max(220, w - 600))
        self.bar.setGeometry((w - bw) // 2, 14, bw, 52)
        self.role_chip.adjustSize()
        self.leave_btn.move(w - self.leave_btn.width() - 14, 14)
        self.map_btn.move(w - self.map_btn.width() - 14, 14 + self.leave_btn.height() + 8)
        self.role_chip.move(w - self.leave_btn.width() - self.role_chip.width() - 26, 20)
        mw, mh = min(640, w - 80), min(420, h - 160)
        self.minimap.setGeometry((w - mw) // 2, (h - mh) // 2, mw, mh)
        self.ghost_chat.setGeometry(14, max(260, h - 300), 300, 220)
        x = w - 14
        for key in ("use", "report", "kill", "check", "sabo"):
            b = self.acts[key]
            if b.isVisible():
                x -= b.width()
                b.move(x, h - b.height() - 14)
                x -= 10
        self.hint.setGeometry(14, h - 60, max(200, w - 520), 46)
        mw, mh = min(820, w - 40), min(560, h - 40)
        self.meeting.setGeometry((w - mw) // 2, (h - mh) // 2, mw, mh)
        rw, rh = min(860, w - 40), min(560, h - 40)
        self.result.setGeometry((w - rw) // 2, (h - rh) // 2, rw, rh)
        self.taskhost.move((w - self.taskhost.width()) // 2, (h - self.taskhost.height()) // 2)

    # ---- 开始 / 停止
    def start(self, c, reveal: bool = True) -> None:
        self.map.set_client(c)
        self.overlay.client = c
        self.overlay.reveal_t = time.monotonic() if reveal else -1e9
        self.taskhost.close_task()
        self.keys.clear()
        self._phase = None
        self._act_state.clear()
        self.result._shown = None
        duck = c.role == DUCK
        self.acts["kill"].setVisible(c.role in (DUCK, SHERIFF))
        self.acts["sabo"].setVisible(duck)
        self.acts["check"].setVisible(c.role == DETECTIVE)
        self.minimap.hide()
        self.ghost_chat.hide()
        self.ghost_chat._n = -1
        self.role_chip.setText(f"你是 {ROLE_NAME.get(c.role, '')}")
        self.role_chip.setStyleSheet(f"color: {ROLE_COLOR.get(c.role, '#FFFFFF')};")
        self.layout_hud()
        self._last = time.monotonic()
        self.timer.start()
        self.map.setFocus()

    def stop(self) -> None:
        self.timer.stop()
        self.taskhost.close_task()
        self.keys.clear()

    def _leave(self) -> None:
        self.w.dk_quit_game()

    # ---- 键盘(只在这个窗口里有效)
    def keyPressEvent(self, e) -> None:
        k = e.key()
        if (self.meeting.isVisible() and self.meeting.edit.hasFocus()) or self.ghost_chat.edit.hasFocus():
            return super().keyPressEvent(e)
        if k in self.KEYS and not e.isAutoRepeat():
            self.keys.add(k)
            return
        if e.isAutoRepeat():
            return
        if k == Qt.Key.Key_Escape and self.taskhost.busy():
            self.taskhost.close_task()
            return
        if k == Qt.Key.Key_Escape and self.minimap.isVisible():
            self.minimap.hide()
            return
        elif k == Qt.Key.Key_E:
            self.do("use")
        elif k == Qt.Key.Key_R:
            self.do("report")
        elif k == Qt.Key.Key_Q:
            self.do("kill")
        elif k == Qt.Key.Key_F:
            self.do("sabo")
        elif k == Qt.Key.Key_C:
            self.do("check")
        elif k == Qt.Key.Key_M:
            self.toggle_map()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:
        if e.key() in self.KEYS and not e.isAutoRepeat():
            self.keys.discard(e.key())
        else:
            super().keyReleaseEvent(e)

    def focusOutEvent(self, e) -> None:
        self.keys.clear()
        super().focusOutEvent(e)

    def axis(self) -> tuple[float, float]:
        ix = iy = 0
        for k in self.keys:
            dx, dy = self.KEYS[k]
            ix += dx
            iy += dy
        return max(-1, min(1, ix)), max(-1, min(1, iy))

    # ---- 每一帧
    def frame(self) -> None:
        c = self.w.dk_client
        if c is None:
            return
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        if not self.dw.isActiveWindow():
            self.keys.clear()
        ix, iy = self.axis()
        c.step(ix, iy, dt, busy=self.taskhost.busy() or now - self.overlay.reveal_t < 3.0)
        self.w.dk_frame(dt)
        self.map.update()
        lagging = c.host != c.me and now - c.last_snap > 3.0
        if c.phase in ("eject",) or now - self.overlay.reveal_t < 4.2 or (c.dead_by and c.phase == "play") or lagging \
                or getattr(self, "_was_lagging", False):
            self.overlay.update()
        self._was_lagging = lagging
        if self.minimap.isVisible():
            self.minimap.update()
        if c.phase != self._phase:
            self._phase = c.phase
            self.meeting.setVisible(c.phase == "meeting")
            self.result.setVisible(c.phase == "over")
            self.overlay.update()
            if c.phase != "play":
                self.taskhost.close_task()
                self.minimap.hide()
                self.keys.clear()
            else:
                self.map.setFocus()                          # 开完会回来:键盘重新控制走路
            if c.phase == "meeting":
                self.meeting.raise_()
                self.meeting._sig = None
                self.meeting._chat_n = -1
            if c.phase == "over":
                self.result.refresh(c)
                self.result.raise_()
        if c.phase == "meeting":
            self.meeting.refresh(c, now)
        if now - self._hud_t > 0.12:
            self._hud_t = now
            self.refresh_hud(c, now)

    def refresh_hud(self, c, now: float) -> None:
        lines = []
        for _tid, room, name, done in c.my_tasks():
            lines.append(("✔ " if done else "○ ") + f"{room}:{name}")
        if c.role == DUCK:
            self.tasks_title.setText("假任务(做做样子)")
        elif c.role == DODO:
            self.tasks_title.setText("假任务(呆呆鹅)")
        else:
            self.tasks_title.setText("我的任务")
        if c.lights_off and c.alive:
            lines.insert(0, "⚡ 关灯了!去配电室修电闸")
        self.tasks_text.setText("\n".join(lines))
        done, total = c.task_bar
        self.bar_text.setText(f"全体好鹅任务进度  {done} / {total}")
        self.bar_fill.setFixedWidth(int(max(0, self.bar_track.width()) * done / max(1, total)))
        use = c.use_action()
        use_text = {"switch": "修电闸\nE", "task": "做任务\nE", "button": "开会\nE"}.get(use[0] if use else "", "使用\nE")
        self._set_act("use", use is not None, use_text)
        self._set_act("report", c.near_body() is not None, "报告\nR")
        if c.role in (DUCK, SHERIFF):
            kc = c.kill_cd - (now - c.last_snap)
            ready = kc <= 0 and c.kill_target(now) is not None
            word = "刀" if c.role == DUCK else "执法"
            self._set_act("kill", ready and c.alive, f"{word}\nQ" if kc <= 0 else f"{int(math.ceil(kc))}\nQ")
        if c.role == DETECTIVE:
            self._set_act("check", c.check_target(now) is not None,
                          "查验\nC" if c.checks_left > 0 else "已用完\nC")
        if c.role == DUCK:
            sc = c.sabo_cd - (now - c.last_snap)
            self._set_act("sabo", sc <= 0 and c.alive and c.phase == "play",
                          "破坏\nF" if sc <= 0 else f"{int(math.ceil(sc))}\nF")
        ghost = not c.alive and c.phase == "play"
        if ghost != self.ghost_chat.isVisible():
            self.ghost_chat.setVisible(ghost)
            self.ghost_chat.raise_()
        if ghost:
            self.ghost_chat.refresh(c)
        if not c.alive and c.phase == "play":
            self.hint.setText("👻 你是幽灵:可以穿墙,还能继续做任务帮好鹅;左边是幽灵频道。")
        elif c.phase == "play" and use and use[0] == "button":
            self.hint.setText(f"紧急按钮还能按 {c.buttons} 次。")
        else:
            self.hint.setText("")

    def _set_act(self, key: str, on: bool, text: str) -> None:
        st = (on, text)
        if self._act_state.get(key) == st:
            return
        self._act_state[key] = st
        b = self.acts[key]
        b.setEnabled(on)
        b.setText(text)

    # ---- 操作
    def do(self, key: str) -> None:
        c = self.w.dk_client
        if c is None or c.phase != "play" or self.taskhost.busy():
            return
        now = time.monotonic()
        if key == "use":
            use = c.use_action()
            if use is None:
                return
            if use[0] == "task":
                t = Wd.TASK_BY_ID[use[1]]
                self.taskhost.open(t[1], t[0], f"{Wd.room_name(t[2])} · {t[5]}")
            elif use[0] == "switch":
                self.w.dk_action("fix", {})
                self.taskhost.open("switch", "__switch__", "配电室 · 修电闸")
            elif use[0] == "button":
                self.w.dk_action("button", {})
        elif key == "report":
            if c.near_body():
                self.w.dk_action("report", {})
        elif key == "kill":
            t = c.kill_target(now)
            if t:
                self.w.dk_action("kill", {"t": t})
        elif key == "check":
            t = c.check_target(now)
            if t:
                self.w.dk_action("check", {"t": t})
        elif key == "sabo":
            self._sabo_menu()

    def toggle_map(self) -> None:
        c = self.w.dk_client
        if c is None or c.phase != "play":
            return
        self.minimap.setVisible(not self.minimap.isVisible())
        self.minimap.raise_()

    def _sabo_menu(self) -> None:
        c = self.w.dk_client
        if c is None or c.role != DUCK or not c.alive:
            return
        m = make_menu(self)
        m.addAction("💡  关灯(好鹅视野变小)", lambda: self.w.dk_action("sabo", {"k": "lights"}))
        sub = make_menu(m)
        sub.setTitle("🚪  锁门(10 秒)")
        for rid, name, _r, _c in Wd.ROOMS:
            if Wd.DOORS.get(rid):
                sub.addAction(name, lambda r=rid: self.w.dk_action("sabo", {"k": "doors", "room": r}))
        m.addMenu(sub)
        b = self.acts["sabo"]
        popup(m, b.mapToGlobal(b.rect().topLeft()))

    def task_done(self, tid: str | None) -> None:
        if tid == "__switch__":
            self.w.dk_action("fix", {"done": True})
        elif tid:
            self.w.dk_action("task", {"t": tid})

    def switch_closed(self) -> None:
        pass


# ====================================================================== 窗口
class DuckWindow(Dialog):
    def __init__(self, w) -> None:
        super().__init__(w, "谁是坏鸭 · 密语")
        self.w = w
        self.setObjectName("duck")
        self.setModal(False)
        self.resize(1120, 760)
        self.setMinimumSize(860, 600)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QFrame()
        head.setObjectName("gmHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 12, 22, 10)
        hl.addWidget(label("🦆 谁是坏鸭", "dialogTitle"))
        hl.addStretch(1)
        self.status = label("", "gmMeChip")
        hl.addWidget(self.status)
        self.head = head
        root.addWidget(head)
        self.stack = QStackedWidget()
        self.pages = {"lobby": LobbyPage(self), "room": RoomPage(self), "game": GamePage(self)}
        for p in self.pages.values():
            self.stack.addWidget(p)
        root.addWidget(self.stack, 1)
        self._toast = label("", "gmToast", wrap=True, center=True)
        self._toast.setParent(self)
        self._toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast.hide)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        self.go("lobby")

    def current(self) -> str:
        for k, p in self.pages.items():
            if self.stack.currentWidget() is p:
                return k
        return "lobby"

    def go(self, key: str) -> None:
        page = self.pages[key]
        if self.stack.currentWidget() is not page:
            if self.current() == "game":
                self.pages["game"].stop()
            self.stack.setCurrentWidget(page)
        self.head.setVisible(key != "game")
        if key in ("lobby", "room"):
            page.refresh(force=True)

    def start_game(self, c, reveal: bool = True) -> None:
        self.go("game")
        self.pages["game"].start(c, reveal)

    def tick(self) -> None:
        cur = self.current()
        if cur in ("lobby", "room"):
            self.pages[cur].refresh()
        room = self.w.dk_room
        self.status.setText(f"在房间「{room['name']}」里" if room else "还没进房间")

    def toast(self, text: str, ms: int = 2600) -> None:
        self._toast.setText(text)
        self._toast.adjustSize()
        self._toast.setMaximumWidth(max(260, self.width() - 80))
        self._toast.adjustSize()
        self._toast.move((self.width() - self._toast.width()) // 2, 70)
        self._toast.show()
        self._toast.raise_()
        self._toast_timer.start(ms)

    def closeEvent(self, e) -> None:
        if not self.w.dk_can_close():
            e.ignore()
            return
        self.pages["game"].stop()
        super().closeEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:                 # ESC 只关这个窗口(游戏中会先问)
            self.close()
            return
        super().keyPressEvent(e)

    def reject(self) -> None:
        self.close()
