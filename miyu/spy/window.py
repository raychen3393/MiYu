"""
谁是卧底 · 游戏窗口:大厅(房间列表、创建房间、玩法)、房间(人员、房主改设置、邀请、开始)、
游戏(翻牌看词、座位卡片、描述和讨论记录、输入框、投票、揭晓、白板猜词、结算)。
联网和裁判在 window/spy.py(主窗口的 SpyMixin)。
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QTextOption
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from ..dialogs import Dialog
from ..gomoku.widgets import Segmented, elide
from ..gomoku.window import avatar_label, clear_layout, scroll_list
from ..pet3d import clay_brush, contour_pen
from ..theme import T, is_dark
from ..ui import button, label, peer_avatar
from . import words as WB
from .rules import BLANK, CIV, MAX_PLAYERS, MIN_PLAYERS, ROLE_NAME, SPY

PHASE_NAME = {"desc": "描述环节", "talk": "自由讨论", "vote": "投票", "reveal": "揭晓", "guess": "白板猜词", "over": "结束"}
HOW_TO = ("· 4~10 人。开局每人拿到一个词:大多数人(平民)的词一样,卧底的词和平民相近但不一样;"
          "5 人以上可能有一个白板(没有词)。没人知道自己是不是卧底。\n"
          "· 每轮按顺序用一句话描述自己的词(不能直接说出来),然后自由讨论、投票,票最多的人出局并亮出身份。\n"
          "· 卧底全部出局,平民获胜;卧底撑到人数和其他人一样多(或只剩 3 人时还在),卧底获胜。\n"
          "· 白板被投出去时可以猜平民的词,猜中就单独获胜。\n"
          "· 小技巧:描述得太具体会暴露给卧底,太模糊又会被当成卧底。")
ROLE_FG = {CIV: ("#2B8A3E", "#69DB7C"), SPY: ("#C92A2A", "#FF8787"), BLANK: ("#5F3DC4", "#B197FC")}


def role_fg(role: str) -> str:
    light, dark = ROLE_FG.get(role, ("#495057", "#DEE2E6"))
    return dark if is_dark() else light


# ====================================================================== 翻牌看词
class WordCard(QWidget):
    """自己的词。点一下翻面藏起来(防止旁边的人偷看),再点一下翻回来。翻面是画出来的横向缩放动画。"""
    flipped = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(300, 132)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.word = ""
        self.blank = False
        self.show_front = False
        self.anim_t = -1e9
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    def set_word(self, word: str, blank: bool) -> None:
        self.word, self.blank = word, blank
        self.show_front = False
        self.update()

    def flip(self) -> None:
        self.show_front = not self.show_front
        self.anim_t = time.monotonic()
        self.timer.start()
        self.flipped.emit(self.show_front)

    def _tick(self) -> None:
        if time.monotonic() - self.anim_t > 0.4:
            self.timer.stop()
        self.update()

    def mousePressEvent(self, _e) -> None:
        self.flip()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        k = min(1.0, (time.monotonic() - self.anim_t) / 0.36)
        sx = abs(math.cos(k * math.pi))                  # 0.5 处最窄:前一半显示旧的一面,后一半显示新的一面
        front = self.show_front if k >= 0.5 else not self.show_front
        w, h = self.width(), self.height()
        p.translate(w / 2, h / 2)
        p.scale(max(0.02, sx), 1.0)
        r = QRectF(-w / 2 + 4, -h / 2 + 4, w - 8, h - 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(r.translated(0, 3), 18, 18)
        if front:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor("#FFF9DB"))
            g.setColorAt(1, QColor("#FFE8CC"))
            p.setBrush(g)
            p.setPen(QPen(QColor("#E8A200"), 2))
            p.drawRoundedRect(r, 18, 18)
            self._text(p, QRectF(r.x(), r.y() + 10, r.width(), 22), "你的词(点一下藏起来)", 12, "#9C6B00")
            if self.blank:
                self._text(p, QRectF(r.x(), r.y() + 34, r.width(), 52), "你是白板 🤫", 30, "#5F3DC4", bold=True)
                self._text(p, QRectF(r.x(), r.bottom() - 34, r.width(), 22), "没有词。听听别人怎么说,别露馅!", 12, "#7A5C00")
            else:
                self._text(p, QRectF(r.x(), r.y() + 34, r.width(), 60), self.word, 38, "#3B2E2A", bold=True)
                self._text(p, QRectF(r.x(), r.bottom() - 30, r.width(), 20), "你可能是平民,也可能是卧底", 11, "#7A5C00")
        else:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor("#7048E8"))
            g.setColorAt(1, QColor("#C2255C"))
            p.setBrush(g)
            p.setPen(QPen(QColor(255, 255, 255, 120), 2))
            p.drawRoundedRect(r, 18, 18)
            p.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
            for i in range(-6, 8):                         # 斜纹
                x = r.x() + i * 28
                p.drawLine(QPointF(x, r.bottom()), QPointF(x + r.height(), r.top()))
            self._text(p, QRectF(r.x(), r.y() + 26, r.width(), 50), "🕵 谁是卧底", 26, "#FFFFFF", bold=True)
            self._text(p, QRectF(r.x(), r.bottom() - 40, r.width(), 24), "点一下翻开看你的词", 13, "#F3F0FF")
        p.end()

    def _text(self, p, r, s, size, color, bold=False) -> None:
        f = QFont(self.font())
        f.setPixelSize(size)
        if bold:
            f.setWeight(QFont.Weight.Black)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(r, s, QTextOption(Qt.AlignmentFlag.AlignCenter))


# ====================================================================== 倒计时圈
class TimerRing(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(54, 54)
        self.left = 0.0
        self.total = 1.0

    def set_value(self, left: float, total: float) -> None:
        self.left, self.total = max(0.0, left), max(1.0, total)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(5, 5, self.width() - 10, self.height() - 10)
        p.setPen(QPen(QColor(128, 128, 128, 70), 5))
        p.drawEllipse(r)
        k = self.left / self.total
        col = QColor("#51CF66") if k > 0.5 else QColor("#FCC419") if k > 0.2 else QColor("#FF6B6B")
        p.setPen(QPen(col, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, int(-360 * 16 * k))
        f = QFont(self.font())
        f.setPixelSize(15)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor(T.get("text", "#FFFFFF")))
        p.drawText(r, str(int(math.ceil(self.left))), QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


# ====================================================================== 座位卡片
class SeatCard(QFrame):
    clicked = Signal(str)

    def __init__(self, pid: str, nick: str, me: bool) -> None:
        super().__init__()
        self.pid = pid
        self.setObjectName("spSeat")
        self.setMinimumSize(150, 112)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(avatar_label(pid, nick, 32))
        self.name = label("", "gmRowTitle")
        elide(self.name, nick + ("(我)" if me else ""), 96)
        top.addWidget(self.name, 1)
        lay.addLayout(top)
        self.status = label("", "spSeatStatus")
        lay.addWidget(self.status)
        self.said = label("", "spSeatSaid", wrap=True)
        lay.addWidget(self.said, 1)
        self._state = None

    def set_state(self, state: str, status: str, said: str, clickable: bool) -> None:
        key = (state, status, said, clickable)
        if key == self._state:
            return
        self._state = key
        self.setProperty("st", state)                 # speaking / out / voted / pick / ""
        self.style().unpolish(self)
        self.style().polish(self)
        self.status.setText(status)
        self.said.setText(said)
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        self._clickable = clickable

    def mousePressEvent(self, _e) -> None:
        if getattr(self, "_clickable", False):
            self.clicked.emit(self.pid)


# ====================================================================== 揭晓(画出来的大字)
class RevealOverlay(QWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.info = None
        self.t0 = 0.0
        self.nick = lambda pid: "?"
        self.hide()

    def show_reveal(self, info: dict, nick_fn) -> None:
        self.info, self.nick, self.t0 = info, nick_fn, time.monotonic()
        self.show()
        self.raise_()

    def paintEvent(self, _e) -> None:
        if not self.info:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        t = time.monotonic() - self.t0
        w, h = self.width(), self.height()
        a = min(1.0, t / 0.25)
        p.setOpacity(a)
        p.fillRect(QRectF(0, 0, w, h), QColor(10, 8, 18, 215))
        out, role = self.info.get("id"), self.info.get("role")
        f = QFont(self.font())
        if out:
            pm = peer_avatar(out, self.nick(out), 120)
            pop = min(1.0, t / 0.35)
            s = 0.6 + 0.4 * (1 - (1 - pop) ** 3)
            p.save()
            p.translate(w / 2, h / 2 - 60)
            p.scale(s, s)
            p.drawPixmap(QRectF(-60, -60, 120, 120), pm, QRectF(pm.rect()))
            p.restore()
            f.setPixelSize(22)
            f.setWeight(QFont.Weight.Bold)
            p.setFont(f)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QRectF(0, h / 2 + 14, w, 34), f"{self.nick(out)} 出局了", QTextOption(Qt.AlignmentFlag.AlignCenter))
            if t > 0.9 and role:                            # 盖章:身份
                k = min(1.0, (t - 0.9) / 0.25)
                sc = 2.2 - 1.2 * k
                col = {SPY: "#FF6B6B", CIV: "#69DB7C", BLANK: "#B197FC"}.get(role, "#FFFFFF")
                p.save()
                p.translate(w / 2 + 110, h / 2 - 90)
                p.rotate(-14)
                p.scale(sc, sc)
                p.setOpacity(k)
                p.setPen(QPen(QColor(col), 5))
                p.setBrush(QColor(0, 0, 0, 90))
                p.drawRoundedRect(QRectF(-74, -32, 148, 64), 12, 12)
                f.setPixelSize(34)
                f.setWeight(QFont.Weight.Black)
                p.setFont(f)
                p.setPen(QColor(col))
                p.drawText(QRectF(-74, -32, 148, 64), ROLE_NAME.get(role, ""), QTextOption(Qt.AlignmentFlag.AlignCenter))
                p.restore()
                p.setOpacity(a)
                f.setPixelSize(16)
                f.setWeight(QFont.Weight.Normal)
                p.setFont(f)
                p.setPen(QColor("#DEE2E6"))
                tip = {SPY: "抓到一个卧底!", CIV: "冤枉了一个平民……", BLANK: "是白板!他还有一次猜词的机会"}.get(role, "")
                p.drawText(QRectF(0, h / 2 + 52, w, 28), tip, QTextOption(Qt.AlignmentFlag.AlignCenter))
        else:
            f.setPixelSize(28)
            f.setWeight(QFont.Weight.Black)
            p.setFont(f)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QRectF(0, h / 2 - 40, w, 50), "平票,没有人出局", QTextOption(Qt.AlignmentFlag.AlignCenter))
        votes = self.info.get("votes") or {}
        tally: dict[str, int] = {}
        for v in votes.values():
            tally[v] = tally.get(v, 0) + 1
        parts = [f"{'弃票' if k == 'skip' else self.nick(k)} {n} 票" for k, n in sorted(tally.items(), key=lambda kv: -kv[1])]
        f.setPixelSize(13)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor("#ADB5BD"))
        p.drawText(QRectF(0, h - 60, w, 24), "  ·  ".join(parts) or "没有人投票", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


# ====================================================================== 大厅 / 房间
class SpyLobby(QWidget):
    def __init__(self, sw: "SpyWindow") -> None:
        super().__init__()
        self.sw, self.w = sw, sw.w
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 14, 22, 18)
        root.setSpacing(16)
        left = QVBoxLayout()
        hero = QFrame()
        hero.setObjectName("gmHero")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.addWidget(label("🕵 谁是卧底", "gmHello"))
        hl.addWidget(label(f"4~10 人局域网派对游戏 · 词库 {WB.count()} 对", "gmHeroSub"))
        left.addWidget(hero)
        left.addWidget(label("房间列表", "section"))
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
        sl.addWidget(button("创建房间", "primary", lambda: self.w.sp_create_room(self.name_edit.text().strip())))
        sl.addSpacing(6)
        sl.addWidget(label("怎么玩", "cardTitle"))
        sl.addWidget(label(HOW_TO, "faint", wrap=True))
        sl.addStretch(1)
        root.addWidget(side, 2)
        self._sig = None

    def refresh(self, force: bool = False) -> None:
        rooms = self.w.sp_rooms_list()
        sig = tuple((r["id"], r["n"], r["st"], r["name"]) for r in rooms)
        if sig == self._sig and not force:
            return
        self._sig = sig
        clear_layout(self.list)
        if not rooms:
            self.list.addWidget(label("现在没有人开房间。点右边「创建房间」开一个,再邀请大家进来!", "gmEmpty",
                                      wrap=True, center=True))
        for r in rooms:
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
                       lambda _=False, rid=r["id"]: self.w.sp_join(rid), 76)
            b.setEnabled(ok)
            lay.addWidget(b)
            self.list.addWidget(row)
        self.list.addStretch(1)


SPY_SETTINGS = [
    ("spies", "卧底人数", [(0, "自动"), (1, "1 个"), (2, "2 个"), (3, "3 个")]),
    ("blank", "白板(5 人以上)", [(True, "有"), (False, "没有")]),
    ("say", "每人描述时间", [(25, "25 秒"), (40, "40 秒"), (60, "60 秒")]),
    ("talk", "自由讨论", [(0, "不讨论"), (30, "30 秒"), (60, "60 秒")]),
    ("vote", "投票时间", [(20, "20 秒"), (30, "30 秒"), (45, "45 秒")]),
    ("diff", "词语难度", [(0, "全部"), (1, "简单"), (2, "普通"), (3, "困难")]),
]


class SpyRoom(QWidget):
    def __init__(self, sw: "SpyWindow") -> None:
        super().__init__()
        self.sw, self.w = sw, sw.w
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 14, 22, 18)
        root.setSpacing(16)
        left = QVBoxLayout()
        self.title = label("", "gmHello")
        left.addWidget(self.title)
        self.sub = label("", "gmHeroSub", wrap=True)
        left.addWidget(self.sub)
        gw = QWidget()
        self.grid = QGridLayout(gw)
        self.grid.setSpacing(10)
        self.grid.setContentsMargins(0, 0, 0, 0)
        left.addWidget(gw)
        left.addStretch(1)
        btns = QHBoxLayout()
        self.start_btn = button("开始游戏", "primary", lambda: self.w.sp_start(), 140)
        btns.addWidget(self.start_btn)
        btns.addWidget(button("离开房间", "", lambda: self.w.sp_leave_room(), 110))
        btns.addStretch(1)
        left.addLayout(btns)
        root.addLayout(left, 3)
        side = QFrame()
        side.setObjectName("gmSide")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 16, 18, 16)
        sl.setSpacing(6)
        sl.addWidget(label("游戏设置", "cardTitle"))
        self.set_hint = label("", "faint", wrap=True)
        sl.addWidget(self.set_hint)
        self.segs: dict[str, Segmented] = {}
        for key, title, opts in SPY_SETTINGS:
            sl.addWidget(label(title, "gmSub"))
            seg = Segmented([(str(v), t) for v, t in opts])
            seg.changed.connect(lambda k, key=key, opts=opts: self._set(key, k, opts))
            sl.addWidget(seg)
            self.segs[key] = seg
        sl.addWidget(label("词库分类", "gmSub"))
        cats = [("全部", "全部")] + [(c, c) for c in WB.CATEGORIES]
        self.cat_seg1 = Segmented(cats[:5])
        self.cat_seg2 = Segmented(cats[5:])
        self.cat_seg1.changed.connect(lambda k: self.w.sp_set_setting("cat", k))
        self.cat_seg2.changed.connect(lambda k: self.w.sp_set_setting("cat", k))
        sl.addWidget(self.cat_seg1)
        sl.addWidget(self.cat_seg2)
        sl.addSpacing(4)
        sl.addWidget(label("邀请在线的人", "cardTitle"))
        self.inv_area, self.inv_list = scroll_list()
        sl.addWidget(self.inv_area, 1)
        root.addWidget(side, 2)
        self._sig = None

    def _set(self, key: str, k: str, opts) -> None:
        for v, _t in opts:
            if str(v) == k:
                self.w.sp_set_setting(key, v)
                return

    def refresh(self, force: bool = False) -> None:
        room = self.w.sp_room
        if room is None:
            return
        me = self.w.sp_my_id()
        host = room["host"] == me
        members = room["members"]
        n = len(members)
        self.title.setText(f"🕵 {room['name']}")
        need = max(0, MIN_PLAYERS - n)
        self.sub.setText((f"还差 {need} 个人才能开始" if need else "人够了,房主可以开始游戏") +
                         f" · {n} / {MAX_PLAYERS} 人 · 房主 {self.w.sp_nick(room['host'])}")
        sig = (tuple((m["id"], m["nick"]) for m in members), room["host"], tuple(sorted(room["s"].items())))
        if sig == self._sig and not force:
            return
        self._sig = sig
        clear_layout(self.grid)
        for i, m in enumerate(members):
            card = QFrame()
            card.setObjectName("dkSlotMe" if m["id"] == me else "dkSlotOn")
            card.setFixedSize(110, 100)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(6, 10, 6, 6)
            cl.addWidget(avatar_label(m["id"], m["nick"], 44), 0, Qt.AlignmentFlag.AlignHCenter)
            t = label("", "gmRowTitle")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            elide(t, m["nick"] + (" 👑" if m["id"] == room["host"] else ""), 96)
            cl.addWidget(t)
            self.grid.addWidget(card, i // 5, i % 5)
        for j in range(n, MAX_PLAYERS):
            empty = QFrame()
            empty.setObjectName("dkSlot")
            empty.setFixedSize(110, 100)
            self.grid.addWidget(empty, j // 5, j % 5)
        for key, _t, _o in SPY_SETTINGS:
            self.segs[key].select(str(room["s"].get(key)), emit=False)
            self.segs[key].setEnabled(host)
        cat = room["s"].get("cat", "全部")
        self.cat_seg1.select(cat, emit=False)
        self.cat_seg2.select(cat, emit=False)
        self.cat_seg1.setEnabled(host)
        self.cat_seg2.setEnabled(host)
        self.set_hint.setText("你是房主,可以改设置。" if host else "只有房主能改设置。")
        self.start_btn.setVisible(host)
        self.start_btn.setEnabled(MIN_PLAYERS <= n <= MAX_PLAYERS)
        clear_layout(self.inv_list)
        inside = {m["id"] for m in members}
        friends = [f for f in self.w.sp_friends() if f["id"] not in inside]
        if not friends:
            self.inv_list.addWidget(label("没有其他在线的人", "gmEmpty", wrap=True, center=True))
        for f in friends[:30]:
            row = QHBoxLayout()
            t = label("", "gmRowTitle")
            elide(t, f["nick"], 120)
            row.addWidget(t, 1)
            b = button("邀请", "", lambda _=False, pid=f["id"]: self.w.sp_invite(pid), 60)
            row.addWidget(b)
            box = QWidget()
            box.setLayout(row)
            self.inv_list.addWidget(box)
        self.inv_list.addStretch(1)


class _SpyRoundTable(QWidget):
    """3.2 「谁是卧底」2.5D 萌宠头像圆桌视图:展示玩家围坐 2.5D 圆桌、发言高亮光圈与出局状态。"""
    PALETTE = ("#FF8787", "#74C0FC", "#69DB7C", "#FFD43B", "#B197FC", "#FFA94D", "#F783AC", "#63E6BE", "#A5D8FF", "#E599F7")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(168)
        self._seats: list[dict] = []

    def set_seats(self, seats: list[dict]) -> None:
        self._seats = seats
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0 + 4.0
        rx, ry = min(w * 0.34, 155.0), 42.0
        # 2.5D 立体圆桌投影 + 桌沿厚度 + 暖木/暗夜桌面
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawEllipse(QPointF(cx, cy + 9), rx + 4, ry + 3)
        p.setBrush(QColor("#2E2246" if is_dark() else "#B88A5A"))
        p.drawEllipse(QPointF(cx, cy + 5), rx, ry)
        tcol = QColor("#4A3A70" if is_dark() else "#E9CFA8")
        p.setPen(contour_pen(tcol, 1.4))
        p.setBrush(clay_brush(cx, cy, rx, ry, tcol))
        p.drawEllipse(QPointF(cx, cy), rx, ry)

        n = len(self._seats)
        if n <= 0:
            p.end()
            return
        f = QFont(self.font())
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        for i, s in enumerate(self._seats):
            ang = -math.pi / 2 + i * (math.tau / n)
            sx = cx + math.cos(ang) * (rx + 26)
            sy = cy + math.sin(ang) * (ry + 24)
            col = QColor(self.PALETTE[i % len(self.PALETTE)])
            p.save()
            if s.get("out"):
                p.setOpacity(0.42)
            # 发言者发光金环
            if s.get("speaking"):
                p.setPen(QPen(QColor("#FFD43B"), 3.0))
                p.setBrush(QColor(255, 212, 59, 55))
                p.drawEllipse(QPointF(sx, sy), 19.5, 19.5)
            # 2.5D 黏土萌宠圆头头像(带小耳朵 + 高光 + 呆萌眼)
            p.setPen(contour_pen(col, 1.3))
            p.setBrush(clay_brush(sx, sy, 14, 14, col))
            for es in (-1, 1):
                p.drawEllipse(QPointF(sx + es * 8.5, sy - 10.5), 4.5, 5.2)
            p.drawEllipse(QPointF(sx, sy), 13.5, 12.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2B2D42"))
            p.drawEllipse(QPointF(sx - 4.2, sy - 1), 1.6, 1.9)
            p.drawEllipse(QPointF(sx + 4.2, sy - 1), 1.6, 1.9)
            p.setBrush(QColor("#FF8FAB"))
            p.drawEllipse(QPointF(sx - 6.8, sy + 2.5), 2.0, 1.2)
            p.drawEllipse(QPointF(sx + 6.8, sy + 2.5), 2.0, 1.2)
            # 昵称
            p.setPen(QColor("#FFFFFF" if is_dark() else "#2B2D42"))
            nick = str(s.get("nick", ""))[:5]
            p.drawText(QRectF(sx - 30, sy + 14, 60, 16), nick, QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.restore()
        p.end()


# ====================================================================== 游戏页
class SpyGame(QWidget):
    def __init__(self, sw: "SpyWindow") -> None:
        super().__init__()
        self.sw, self.w = sw, sw.w
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(10)
        top = QHBoxLayout()
        self.phase_lab = label("", "gmHello")
        top.addWidget(self.phase_lab)
        top.addStretch(1)
        self.ring = TimerRing()
        top.addWidget(self.ring)
        top.addSpacing(8)
        top.addWidget(button("退出游戏", "", lambda: self.w.sp_quit_game(), 90))
        root.addLayout(top)
        self.hint = label("", "faint", wrap=True)
        root.addWidget(self.hint)
        mid = QHBoxLayout()
        mid.setSpacing(14)
        leftcol = QVBoxLayout()
        leftcol.setSpacing(10)
        self.card = WordCard()
        leftcol.addWidget(self.card, 0, Qt.AlignmentFlag.AlignHCenter)
        self.round_table = _SpyRoundTable()
        leftcol.addWidget(self.round_table)
        gw = QWidget()
        self.grid = QGridLayout(gw)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 0, 0)
        leftcol.addWidget(gw, 1)
        mid.addLayout(leftcol, 3)
        feed = QFrame()
        feed.setObjectName("gmSide")
        fl = QVBoxLayout(feed)
        fl.setContentsMargins(14, 12, 14, 12)
        fl.addWidget(label("描述和讨论", "cardTitle"))
        self.feed_area, self.feed = scroll_list()
        fl.addWidget(self.feed_area, 1)
        mid.addWidget(feed, 2)
        root.addLayout(mid, 1)
        bottom = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setMaxLength(80)
        self.edit.returnPressed.connect(self._send)
        bottom.addWidget(self.edit, 1)
        self.send_btn = button("发送", "primary", self._send, 80)
        bottom.addWidget(self.send_btn)
        self.skip_btn = button("弃票", "", lambda: self.w.sp_vote("skip"), 80)
        bottom.addWidget(self.skip_btn)
        self.ready_btn = button("讨论完了", "", lambda: self.w.sp_action("skip_talk", {}), 96)
        bottom.addWidget(self.ready_btn)
        root.addLayout(bottom)
        self.reveal = RevealOverlay(self)
        self.result = QFrame(self)
        self.result.setObjectName("dkPanel")
        rl = QVBoxLayout(self.result)
        rl.setContentsMargins(24, 18, 24, 18)
        rl.setSpacing(10)
        self.res_title = label("", "gmHello")
        self.res_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.res_title)
        self.res_words = label("", "spWords", wrap=True, center=True)
        rl.addWidget(self.res_words)
        self.res_why = label("", "faint", wrap=True, center=True)
        rl.addWidget(self.res_why)
        rw = QWidget()
        self.res_grid = QGridLayout(rw)
        self.res_grid.setSpacing(8)
        rl.addWidget(rw, 1)
        rb = QHBoxLayout()
        rb.addStretch(1)
        self.back_btn = button("回到房间", "primary", lambda: self.w.sp_back_to_room(), 140)
        rb.addWidget(self.back_btn)
        rb.addWidget(button("离开", "", lambda: self.w.sp_leave_room(), 100))
        rb.addStretch(1)
        rl.addLayout(rb)
        self.result.hide()
        self.seats: dict[str, SeatCard] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.frame)
        self._feed_n = -1
        self._phase = None
        self._reveal_key = None
        self._over_key = None

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        w, h = self.width(), self.height()
        self.reveal.setGeometry(0, 0, w, h)
        rw, rh = min(720, w - 40), min(520, h - 40)
        self.result.setGeometry((w - rw) // 2, (h - rh) // 2, rw, rh)

    def start(self, c) -> None:
        self.card.set_word(c.word, c.blank)
        clear_layout(self.grid)
        self.seats.clear()
        for i, r in enumerate(c.roster):
            card = SeatCard(r["id"], r["nick"], r["id"] == c.me)
            card.clicked.connect(self.w.sp_vote)
            self.grid.addWidget(card, i // 5, i % 5)
            self.seats[r["id"]] = card
        self._feed_n = -1
        self._phase = None
        self._reveal_key = None
        self._over_key = None
        self.reveal.hide()
        self.result.hide()
        self.timer.start()
        self.frame()

    def stop(self) -> None:
        self.timer.stop()

    def _send(self) -> None:
        text = self.edit.text().strip()
        if not text:
            return
        c = self.w.sp_client
        if c is None:
            return
        if c.phase == "desc" and c.turn == c.me:
            self.w.sp_action("say", {"text": text})
        elif c.phase == "guess" and c.guesser == c.me:
            self.w.sp_action("guess", {"text": text})
        else:
            self.w.sp_action("chat", {"text": text})
        self.edit.clear()

    def frame(self) -> None:
        c = self.w.sp_client
        if c is None:
            return
        now = time.monotonic()
        left = c.phase_left(now)
        total = {"desc": c.s.get("say", 40), "talk": c.s.get("talk", 30), "vote": c.s.get("vote", 30),
                 "guess": 25, "reveal": 4.5}.get(c.phase, 1)
        self.ring.set_value(left, total)
        self.ring.setVisible(c.phase not in ("over",))
        alive = c.me in c.alive
        title = f"第 {c.round} 轮 · {PHASE_NAME.get(c.phase, '')}"
        self.phase_lab.setText(title)
        # 提示 + 输入框
        if c.phase == "desc":
            if c.turn == c.me:
                hint, ph, can = "轮到你了!用一句话描述你的词(不能直接说出来)。", "描述你的词……", True
            else:
                hint, ph, can = f"{c.nick(c.turn)} 正在描述……", "还没轮到你", not alive
        elif c.phase == "talk":
            hint, ph, can = "自由讨论:说说你怀疑谁。都讨论完了可以点「讨论完了」直接投票。", "说点什么……", True
        elif c.phase == "vote":
            if not alive:
                hint = "你已经出局了,看大家投票吧。"
            elif c.me in c.voted:
                hint = "你已经投过票了,等其他人。"
            else:
                hint = "点一个人的卡片投给 TA,或者弃票。"
            ph, can = "可以继续聊……", True
        elif c.phase == "guess":
            if c.guesser == c.me:
                hint, ph, can = "你是白板,被投出去了!猜猜平民的词是什么,猜中就单独获胜。", "输入你猜的词……", True
            else:
                hint, ph, can = f"白板 {c.nick(c.guesser)} 正在猜平民的词……", "等待中……", False
        else:
            hint, ph, can = "", "", False
        if not alive and c.phase not in ("over", "guess"):
            hint = "你已经出局了。你说的话只有出局的人看得到。" if c.phase != "vote" else hint
            ph, can = "和其他出局的人说话……", True
        self.hint.setText(hint)
        self.edit.setPlaceholderText(ph)
        self.edit.setEnabled(can)
        self.send_btn.setEnabled(can)
        self.skip_btn.setVisible(c.phase == "vote")
        self.skip_btn.setEnabled(alive and c.me not in c.voted)
        self.ready_btn.setVisible(c.phase == "talk" and alive)
        self.ready_btn.setEnabled(c.me not in c.ready)
        self.ready_btn.setText("等别人…" if c.me in c.ready else "讨论完了")
        # 座位
        outs = {o["id"]: o["role"] for o in c.out}
        if hasattr(self, "round_table"):
            self.round_table.set_seats([
                {"id": pid, "nick": c.nick(pid), "out": pid in outs,
                 "speaking": c.phase == "desc" and c.turn == pid}
                for pid in self.seats
            ])
        for pid, card in self.seats.items():
            mine_said = [s["text"] for s in c.said if s["by"] == pid and s["r"] == c.round]
            prev = [s["text"] for s in c.said if s["by"] == pid and s["r"] < c.round]
            if mine_said:
                said = "「" + (mine_said[-1] or "(超时没说)") + "」"
            elif prev:
                said = "上轮:「" + (prev[-1] or "(没说)") + "」"
            else:
                said = ""
            if pid in outs:
                card.set_state("out", f"出局 · {ROLE_NAME.get(outs[pid], '')}", said, False)
            elif c.phase == "desc" and c.turn == pid:
                card.set_state("speaking", "🎤 正在描述…", said, False)
            elif c.phase == "vote":
                pick = alive and c.me not in c.voted and pid != c.me
                card.set_state("pick" if pick else ("voted" if pid in c.voted else ""),
                               "✅ 已投票" if pid in c.voted else "投票中…", said, pick)
            elif c.phase == "talk" and pid in c.ready:
                card.set_state("", "👌 讨论完了", said, False)
            else:
                card.set_state("", "", said, False)
        # 记录
        n = len(c.said) + len(c.chat)
        if n != self._feed_n:
            self._feed_n = n
            clear_layout(self.feed)
            items = [(s["r"], 0, i, s) for i, s in enumerate(c.said)] + [(m["r"], 1, i, m) for i, m in enumerate(c.chat)]
            items.sort(key=lambda x: (x[0], x[1], x[2]))
            rd = None
            for r, kind, _i, it in items:
                if r != rd:
                    rd = r
                    self.feed.addWidget(label(f"—— 第 {r} 轮 ——", "spRound", center=True))
                if kind == 0:
                    text = it["text"] or "(超时没说)"
                    self.feed.addWidget(label(f"🎤 {c.nick(it['by'])}:{text}", "spSay", wrap=True))
                else:
                    tag = "(出局)" if it.get("dead") else ""
                    self.feed.addWidget(label(f"{c.nick(it['by'])}{tag}:{it['text']}",
                                              "spChatDead" if it.get("dead") else "spChat", wrap=True))
            self.feed.addStretch(1)
            QTimer.singleShot(0, lambda: self.feed_area.verticalScrollBar().setValue(
                self.feed_area.verticalScrollBar().maximum()))
        # 揭晓
        if c.phase in ("reveal", "guess") and c.last is not None:
            key = (c.round, c.last.get("id"))
            if key != self._reveal_key and c.phase == "reveal":
                self._reveal_key = key
                self.reveal.show_reveal(c.last, c.nick)
        if c.phase == "reveal" and self.reveal.isVisible():
            self.reveal.update()
        elif self.reveal.isVisible():
            self.reveal.hide()
        if c.phase != self._phase:
            self._phase = c.phase
            if c.phase == "desc" and c.turn == c.me:
                self.edit.setFocus()
        # 结算
        if c.phase == "over" and c.over:
            key = (c.over.get("win"), c.gid)
            if key != self._over_key:
                self._over_key = key
                self._show_result(c)
        elif self.result.isVisible():
            self.result.hide()

    def _show_result(self, c) -> None:
        o = c.over
        win = o.get("win")
        my_role = (o.get("roles") or {}).get(c.me)
        mine = win == my_role
        names = {CIV: "平民", SPY: "卧底", BLANK: "白板"}
        self.res_title.setText((f"{names.get(win, '')}获胜!" if win else "游戏中断了") + ("  🎉" if mine else ""))
        self.res_words.setText(f"平民的词:{o.get('civ', '')}    卧底的词:{o.get('spy', '')}")
        why = o.get("why", "")
        if o.get("guess"):
            why += f"(白板猜的是「{o['guess']}」)"
        self.res_why.setText(why + ("  你赢了!" if mine else "  这局你输了。" if win else ""))
        clear_layout(self.res_grid)
        for i, (pid, role) in enumerate((o.get("roles") or {}).items()):
            box = QFrame()
            box.setObjectName("gmRow")
            bl = QHBoxLayout(box)
            bl.setContentsMargins(10, 6, 12, 6)
            bl.addWidget(avatar_label(pid, c.nick(pid), 28))
            t = label("", "gmRowTitle")
            elide(t, c.nick(pid) + ("(我)" if pid == c.me else ""), 110)
            bl.addWidget(t, 1)
            r = label(names.get(role, role), "gmRowSub")
            r.setStyleSheet(f"color: {role_fg(role)}; font-weight: 700;")
            bl.addWidget(r)
            self.res_grid.addWidget(box, i // 2, i % 2)
        self.back_btn.setVisible(self.w.sp_room is not None)
        self.result.show()
        self.result.raise_()


class SpyWindow(Dialog):
    def __init__(self, w) -> None:
        super().__init__(w, "谁是卧底 · 密语")
        self.w = w
        self.setModal(False)
        self.resize(1080, 740)
        self.setMinimumSize(860, 600)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QFrame()
        head.setObjectName("gmHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 12, 22, 10)
        hl.addWidget(label("🕵 谁是卧底", "dialogTitle"))
        hl.addStretch(1)
        self.status = label("", "gmMeChip")
        hl.addWidget(self.status)
        self.head = head
        root.addWidget(head)
        self.stack = QStackedWidget()
        self.pages = {"lobby": SpyLobby(self), "room": SpyRoom(self), "game": SpyGame(self)}
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

    def start_game(self, c) -> None:
        self.go("game")
        self.pages["game"].start(c)

    def tick(self) -> None:
        cur = self.current()
        if cur in ("lobby", "room"):
            self.pages[cur].refresh()
        room = self.w.sp_room
        self.status.setText(f"在房间「{room['name']}」里" if room else "还没进房间")

    def toast(self, text: str, ms: int = 2600) -> None:
        self._toast.setText(text)
        self._toast.setMaximumWidth(max(260, self.width() - 80))
        self._toast.adjustSize()
        self._toast.move((self.width() - self._toast.width()) // 2, 70)
        self._toast.show()
        self._toast.raise_()
        self._toast_timer.start(ms)

    def closeEvent(self, e) -> None:
        if not self.w.sp_can_close():
            e.ignore()
            return
        self.pages["game"].stop()
        super().closeEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def reject(self) -> None:
        self.close()
