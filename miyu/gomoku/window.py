"""
五子棋窗口:大厅(房间列表、在线好友、创建房间、人机练习)、对局、排行榜(总 / 今日 / 本周)、我的战绩。
窗口只负责显示和把操作转给主窗口(window/gomoku.py 里的 GomokuMixin,方法都以 gm_ 开头)。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QSlider, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..dialogs import Dialog
from ..ui import label, peer_avatar
from . import league
from .ai import LEVELS
from .widgets import BoardView, PlayerCard, ResultOverlay, Segmented, chip, elide, stone_pixmap

LIMIT_ITEMS = [("30", "30 秒"), ("60", "60 秒"), ("120", "2 分钟"), ("0", "不限时")]
COLOR_ITEMS = [("rand", "随机"), ("b", "我执黑"), ("w", "我执白")]
RESULT_TEXT = {"win": ("胜", "win"), "loss": ("负", "loss"), "draw": ("平", "draw")}


def btn(text: str, obj: str = "", slot=None, min_w: int = 0) -> QPushButton:
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    b.setMinimumHeight(34)
    if min_w:
        b.setMinimumWidth(min_w)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot is not None:
        b.clicked.connect(slot)
    return b


def clear_layout(lay) -> None:
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def scroll_list() -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setObjectName("gmScroll")
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    inner = QWidget()
    inner.setObjectName("gmInner")
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(0, 0, 4, 0)
    lay.setSpacing(6)
    lay.addStretch(1)
    area.setWidget(inner)
    return area, lay


def avatar_label(pid: str, nick: str, size: int = 36):
    from PySide6.QtWidgets import QLabel
    lab = QLabel()
    lab.setFixedSize(size, size)
    lab.setPixmap(peer_avatar(pid, nick or "?", size))
    return lab


def fmt_time(ms: int) -> str:
    t = time.localtime(ms / 1000)
    now = time.localtime()
    if t.tm_year == now.tm_year and t.tm_yday == now.tm_yday:
        return time.strftime("今天 %H:%M", t)
    return time.strftime("%m-%d %H:%M", t)


# ====================================================================== 对话框
class SetupDialog(Dialog):
    """创建房间 / 邀请好友:每步限时、执子颜色(创建房间时还有房间名)。"""

    def __init__(self, parent, title: str, ok: str, name: str | None = None, lim: int = 60) -> None:
        super().__init__(parent, title)
        self.setFixedWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(10)
        lay.addWidget(label(title, "dialogTitle"))
        self.name_edit = None
        if name is not None:
            lay.addWidget(label("房间名", "section"))
            self.name_edit = QLineEdit(name)
            self.name_edit.setMaxLength(20)
            lay.addWidget(self.name_edit)
        lay.addWidget(label("每步限时(时间到了算输)", "section"))
        self.lim = Segmented(LIMIT_ITEMS, str(lim))
        lay.addWidget(self.lim)
        lay.addWidget(label("执子(黑棋先下)", "section"))
        self.color = Segmented(COLOR_ITEMS, "rand")
        lay.addWidget(self.color)
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn("取消", "", self.reject, 80))
        row.addWidget(btn(ok, "primary", self.accept, 96))
        lay.addLayout(row)

    @property
    def values(self) -> tuple[str, int, str]:
        name = self.name_edit.text().strip() if self.name_edit is not None else ""
        return name, int(self.lim.current), self.color.current


class AIDialog(Dialog):
    def __init__(self, parent) -> None:
        super().__init__(parent, "人机练习")
        self.setFixedWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(10)
        lay.addWidget(label("人机练习", "dialogTitle"))
        lay.addWidget(label("和电脑下,不计入积分和排行榜,战绩里会单独记一笔。", "hint", wrap=True))
        lay.addWidget(label("难度", "section"))
        self.level = Segmented(list(LEVELS.items()), "normal")
        lay.addWidget(self.level)
        lay.addWidget(label("执子", "section"))
        self.color = Segmented([("b", "执黑(先手)"), ("w", "执白"), ("rand", "随机")], "b")
        lay.addWidget(self.color)
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn("取消", "", self.reject, 80))
        row.addWidget(btn("开始", "primary", self.accept, 96))
        lay.addLayout(row)


class InviteDialog(Dialog):
    """收到邀请:30 秒内接受或拒绝,超时自动拒绝。"""
    TIMEOUT = 30

    def __init__(self, parent, pid: str, nick: str, lim: int, color_text: str) -> None:
        super().__init__(parent, "五子棋邀请")
        self.setModal(False)
        self.setFixedWidth(380)
        self.choice: bool | None = None
        self.left = self.TIMEOUT
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(avatar_label(pid, nick, 48))
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(f"{nick} 邀请你下五子棋", "dialogTitle", wrap=True))
        lim_text = "不限时" if not lim else f"每步 {lim} 秒"
        col.addWidget(label(f"{lim_text}  ·  {color_text}  ·  计入排行榜", "hint", wrap=True))
        top.addLayout(col, 1)
        lay.addLayout(top)
        self.count = label("", "faint")
        lay.addWidget(self.count)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn("拒绝", "", lambda: self.answer(False), 80))
        row.addWidget(btn("接受", "primary", lambda: self.answer(True), 96))
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._tick(first=True)

    def _tick(self, first: bool = False) -> None:
        if not first:
            self.left -= 1
        self.count.setText(f"{self.left} 秒后自动拒绝")
        if self.left <= 0:
            self.answer(False)

    def answer(self, ok: bool) -> None:
        if self.choice is not None:
            return
        self.choice = ok
        self.timer.stop()
        self.done(1 if ok else 0)


# ====================================================================== 大厅
class LobbyPage(QWidget):
    def __init__(self, gw: "GomokuWindow") -> None:
        super().__init__()
        self.gw, self.w = gw, gw.w
        self._sig = None
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 14, 22, 18)
        root.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(10)
        self.hero = QFrame()
        self.hero.setObjectName("gmHero")
        hl = QVBoxLayout(self.hero)
        hl.setContentsMargins(22, 18, 22, 18)
        hl.setSpacing(4)
        self.hello = label("", "gmHello")
        self.stats = label("", "gmHeroSub", wrap=True)
        hl.addWidget(self.hello)
        hl.addWidget(self.stats)
        hl.addSpacing(8)
        hb = QHBoxLayout()
        hb.setSpacing(8)
        hb.addWidget(btn("＋ 创建房间", "primary", self.w.gm_create_room_dialog, 120))
        hb.addWidget(btn("🤖 人机练习", "", self.w.gm_ai_dialog, 110))
        hb.addWidget(btn("🏆 排行榜", "", lambda: gw.go("rank"), 96))
        hb.addStretch(1)
        hl.addLayout(hb)
        left.addWidget(self.hero)
        self.status_card = QFrame()                    # 我的房间 / 发出的邀请 / 正在进行的对局
        self.status_card.setObjectName("gmStatusCard")
        sl = QHBoxLayout(self.status_card)
        sl.setContentsMargins(16, 10, 10, 10)
        self.status_text = label("", "gmStatusText", wrap=True)
        sl.addWidget(self.status_text, 1)
        self.status_btn = btn("", "", self._status_action)
        sl.addWidget(self.status_btn)
        self.status_card.setVisible(False)
        left.addWidget(self.status_card)
        left.addWidget(label("房间列表", "section"))
        self.rooms_area, self.rooms = scroll_list()
        left.addWidget(self.rooms_area, 1)
        root.addLayout(left, 3)
        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(label("在线好友(点「邀请」直接约战)", "section"))
        self.friends_area, self.friends = scroll_list()
        right.addWidget(self.friends_area, 1)
        root.addLayout(right, 2)
        self._status_kind = ""

    def refresh(self, force: bool = False) -> None:
        w = self.w
        me = w.gm_my_id()
        games = w.gm_games()
        st = league.player_stats(games, me)
        rows = league.standings(games)
        rank, _r, _a = league.rank_of(rows, me)
        lo, hi = league.period_bounds("today")
        today = league.player_stats([g for g in games if lo <= g["end_ts"] < hi], me)
        self.hello.setText(f"你好,{w.me.get('nick', '')}")
        self.stats.setText(f"总积分 {st['pts']}  ·  " + (f"总榜第 {rank} 名" if rank else "还没上榜") +
                           f"  ·  {st['games']} 场 {st['wins']} 胜  ·  今日 +{today['pts']} 分")
        kind, text, action = w.gm_lobby_status()
        self._status_kind = action
        self.status_card.setVisible(bool(kind))
        self.status_text.setText(text)
        self.status_btn.setText({"cancel_room": "取消房间", "cancel_invite": "取消邀请", "back": "回到对局"}.get(action, ""))
        self.status_btn.setVisible(bool(action))
        rooms = w.gm_rooms_list()
        friends = w.gm_friends()
        sig = (tuple((r["rid"], r["nick"], r["name"], r["lim"]) for r in rooms),
               tuple((f["id"], f["nick"], f["busy"]) for f in friends), w.gm_busy())
        if sig == self._sig and not force:
            return
        self._sig = sig
        self._fill_rooms(rooms)
        self._fill_friends(friends)

    def _fill_rooms(self, rooms) -> None:
        clear_layout(self.rooms)
        if not rooms:
            e = label("还没有人开房间。点上面的「创建房间」,在线的人都能看到并加入。", "gmEmpty", wrap=True, center=True)
            self.rooms.addWidget(e)
        for r in rooms:
            row = QFrame()
            row.setObjectName("gmRow")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(12, 9, 10, 9)
            lay.setSpacing(10)
            lay.addWidget(avatar_label(r["host"], r["nick"], 36))
            col = QVBoxLayout()
            col.setSpacing(1)
            t = label("", "gmRowTitle")
            elide(t, r["name"] or f"{r['nick']}的房间", 260)
            col.addWidget(t)
            lim = "不限时" if not r["lim"] else f"每步 {r['lim']} 秒"
            col.addWidget(label(f"房主 {r['nick']}  ·  {lim}  ·  {dict(COLOR_ITEMS).get(r['color'], '随机').replace('我', '房主')}",
                                "gmRowSub"))
            lay.addLayout(col, 1)
            b = btn("加入", "primary", lambda _=False, rid=r["rid"]: self.w.gm_join(rid), 72)
            b.setEnabled(not self.w.gm_busy())
            lay.addWidget(b)
            self.rooms.addWidget(row)
        self.rooms.addStretch(1)

    def _fill_friends(self, friends) -> None:
        clear_layout(self.friends)
        if not friends:
            self.friends.addWidget(label("现在没有其他人在线。", "gmEmpty", wrap=True, center=True))
        for f in friends:
            row = QFrame()
            row.setObjectName("gmRow")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(12, 8, 10, 8)
            lay.setSpacing(10)
            lay.addWidget(avatar_label(f["id"], f["nick"], 34))
            col = QVBoxLayout()
            col.setSpacing(1)
            t = label("", "gmRowTitle")
            elide(t, f["nick"], 150)
            col.addWidget(t)
            col.addWidget(label("对局中" if f["busy"] else f"积分 {f['pts']}", "gmRowSub"))
            lay.addLayout(col, 1)
            b = btn("邀请", "", lambda _=False, pid=f["id"]: self.w.gm_invite_dialog(pid), 64)
            b.setEnabled(not self.w.gm_busy() and not f["busy"])
            lay.addWidget(b)
            self.friends.addWidget(row)
        self.friends.addStretch(1)

    def _status_action(self) -> None:
        a = self._status_kind
        if a == "cancel_room":
            self.w.gm_cancel_room()
        elif a == "cancel_invite":
            self.w.gm_cancel_invite()
        elif a == "back":
            self.gw.go("game")


# ====================================================================== 对局
class GamePage(QWidget):
    def __init__(self, gw: "GomokuWindow") -> None:
        super().__init__()
        self.gw, self.w = gw, gw.w
        self.replay: dict | None = None
        self._last_moves_n = -1
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(18, 10, 18, 16)
        self.box.setSpacing(16)
        self.board_host = QWidget()
        bl = QVBoxLayout(self.board_host)
        bl.setContentsMargins(0, 0, 0, 0)
        self.board = BoardView()
        self.board.cell_clicked.connect(self._clicked)
        bl.addWidget(self.board, 1)
        self.empty = QFrame()
        el = QVBoxLayout(self.empty)
        el.addStretch(1)
        el.addWidget(label("还没有对局", "gmEmptyTitle", center=True))
        el.addWidget(label("去大厅创建房间、邀请在线的好友,或者先和电脑练一局。", "gmEmpty", wrap=True, center=True))
        er = QHBoxLayout()
        er.addStretch(1)
        er.addWidget(btn("去大厅", "primary", lambda: gw.go("lobby"), 96))
        er.addWidget(btn("人机练习", "", self.w.gm_ai_dialog, 96))
        er.addStretch(1)
        el.addLayout(er)
        el.addStretch(1)
        bl.addWidget(self.empty, 1)
        self.overlay = ResultOverlay(self.board_host)
        self.overlay.action.connect(self._overlay_action)
        self.box.addWidget(self.board_host, 1)
        # 右边:玩家、状态、操作
        self.side = QFrame()
        self.side.setObjectName("gmSide")
        self.side.setFixedWidth(290)
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(14, 14, 14, 14)
        sl.setSpacing(10)
        self.title = label("", "gmSub")
        sl.addWidget(self.title)
        self.top_card = PlayerCard()
        sl.addWidget(self.top_card)
        self.status = label("", "gmStatus", wrap=True, center=True)
        sl.addWidget(self.status)
        self.info = label("", "gmSub", center=True)
        sl.addWidget(self.info)
        self.bottom_card = PlayerCard()
        sl.addWidget(self.bottom_card)
        self.banner = QFrame()                          # 对方的请求(悔棋 / 重新开始 / 再来一局)
        self.banner.setObjectName("gmBanner")
        bnl = QVBoxLayout(self.banner)
        bnl.setContentsMargins(12, 10, 12, 10)
        bnl.setSpacing(8)
        self.banner_text = label("", "gmBannerText", wrap=True)
        bnl.addWidget(self.banner_text)
        br = QHBoxLayout()
        br.addStretch(1)
        br.addWidget(btn("拒绝", "", lambda: self.w.gm_answer(False), 70))
        br.addWidget(btn("同意", "primary", lambda: self.w.gm_answer(True), 70))
        bnl.addLayout(br)
        self.banner.setVisible(False)
        sl.addWidget(self.banner)
        self.pause = QFrame()                           # 对方掉线 / 不响应
        self.pause.setObjectName("gmPause")
        pl = QVBoxLayout(self.pause)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.setSpacing(8)
        self.pause_text = label("", "gmBannerText", wrap=True)
        pl.addWidget(self.pause_text)
        self.claim_btn = btn("判对方掉线负", "destructive", self.w.gm_claim)
        pl.addWidget(self.claim_btn)
        self.pause.setVisible(False)
        sl.addWidget(self.pause)
        sl.addStretch(1)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.b_undo = btn("↶ 悔棋", "", lambda: self.w.gm_request("undo"))
        self.b_restart = btn("⟳ 重新开始", "", lambda: self.w.gm_request("restart"))
        self.b_resign = btn("🏳 认输", "destructive", self.w.gm_resign)
        self.b_leave = btn("退出对局", "", self.w.gm_leave)
        self.b_again = btn("再来一局", "primary", lambda: self.w.gm_request("rematch"))
        grid.addWidget(self.b_undo, 0, 0)
        grid.addWidget(self.b_restart, 0, 1)
        grid.addWidget(self.b_resign, 1, 0)
        grid.addWidget(self.b_leave, 1, 1)
        grid.addWidget(self.b_again, 2, 0, 1, 2)
        self.ctrl = QWidget()
        self.ctrl.setLayout(grid)
        sl.addWidget(self.ctrl)
        # 复盘
        self.rp = QWidget()
        rl = QVBoxLayout(self.rp)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.rp_label = label("", "gmSub", center=True)
        rl.addWidget(self.rp_label)
        self.rp_slider = QSlider(Qt.Orientation.Horizontal)
        self.rp_slider.valueChanged.connect(self._replay_seek)
        rl.addWidget(self.rp_slider)
        rr = QHBoxLayout()
        rr.addWidget(btn("⏮", "", lambda: self.rp_slider.setValue(0)))
        rr.addWidget(btn("◀", "", lambda: self.rp_slider.setValue(self.rp_slider.value() - 1)))
        rr.addWidget(btn("▶", "", lambda: self.rp_slider.setValue(self.rp_slider.value() + 1)))
        rr.addWidget(btn("⏭", "", lambda: self.rp_slider.setValue(self.rp_slider.maximum())))
        rl.addLayout(rr)
        rl.addWidget(btn("结束复盘", "", self.end_replay))
        self.rp.setVisible(False)
        sl.addWidget(self.rp)
        self.box.addWidget(self.side)

    # ---- 显示
    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        narrow = self.width() < 820                     # 窗口窄:操作区放到棋盘下面
        want = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        if self.box.direction() != want:
            self.box.setDirection(want)
            if narrow:
                self.side.setMinimumWidth(0)
                self.side.setMaximumWidth(16777215)
            else:
                self.side.setFixedWidth(290)
        self.overlay.setGeometry(self.board_host.rect())

    def refresh(self) -> None:
        if self.replay is not None:
            self._refresh_replay()
            return
        v = self.w.gm_view()
        has = v is not None
        self.board.setVisible(has)
        self.empty.setVisible(not has)
        self.side.setVisible(has)
        if not has:
            self.overlay.hide()
            return
        grew = len(v["moves"]) != self._last_moves_n
        self.board.show_numbers = False
        self.board.set_state(v["moves"], v["win_line"], v["can_play"], v["my_black"],
                             animate_last=grew and self._last_moves_n >= 0)
        self._last_moves_n = len(v["moves"])
        self.title.setText(v["title"])
        for card, pl in ((self.top_card, v["players"][0]), (self.bottom_card, v["players"][1])):
            card.set_player(pl.get("pm") or peer_avatar(pl["id"], pl["nick"], 56),
                            pl["nick"], pl["sub"], pl["black"], pl["online"])
        self.status.setText(v["status"])
        self.status.setProperty("kind", v.get("status_kind", ""))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.info.setText(v["info"])
        b = v["buttons"]
        self.b_undo.setEnabled(b.get("undo", False))
        self.b_restart.setEnabled(b.get("restart", False))
        self.b_resign.setEnabled(b.get("resign", False))
        self.b_again.setEnabled(b.get("rematch", False))
        self.b_again.setVisible(b.get("over", False))
        self.b_leave.setText("离开" if b.get("over") else "退出对局")
        ban = v.get("banner")
        self.banner.setVisible(bool(ban))
        if ban:
            self.banner_text.setText(ban)
        pause = v.get("pause")
        self.pause.setVisible(bool(pause))
        if pause:
            self.pause_text.setText(pause)
            self.claim_btn.setVisible(v.get("claim", False))
            self.claim_btn.setText(v.get("claim_text", "判对方掉线负"))
        self.tick()

    def tick(self) -> None:
        if self.replay is not None:
            return
        v = self.w.gm_clock_view()
        if v is None:
            return
        for card, c in ((self.top_card, v[0]), (self.bottom_card, v[1])):
            card.set_clock(c["text"], c["frac"], c["active"], c["total"])

    def _clicked(self, x: int, y: int) -> None:
        if self.replay is None:
            self.w.gm_play(x, y)

    def _overlay_action(self, a: str) -> None:
        self.overlay.hide()
        if a == "rematch":
            self.w.gm_request("rematch")
        elif a == "lobby":
            self.w.gm_leave(quiet=True)
            self.gw.go("lobby")

    # ---- 复盘
    def start_replay(self, moves, title: str, black: str, white: str, line=None) -> None:
        self.overlay.hide()
        self.replay = {"moves": [tuple(m) for m in moves], "title": title, "black": black, "white": white,
                       "line": line}
        self.rp_slider.blockSignals(True)
        self.rp_slider.setRange(0, len(moves))
        self.rp_slider.setValue(len(moves))
        self.rp_slider.blockSignals(False)
        self._refresh_replay()

    def end_replay(self) -> None:
        self.replay = None
        self.rp.setVisible(False)
        self.ctrl.setVisible(True)
        self._last_moves_n = -1
        self.refresh()

    def _replay_seek(self, _v: int) -> None:
        self._refresh_replay()

    def _refresh_replay(self) -> None:
        r = self.replay
        n = self.rp_slider.value()
        self.board.setVisible(True)
        self.empty.setVisible(False)
        self.side.setVisible(True)
        self.ctrl.setVisible(False)
        self.banner.setVisible(False)
        self.pause.setVisible(False)
        self.rp.setVisible(True)
        self.board.show_numbers = True
        full = n == len(r["moves"])
        self.board.set_state(r["moves"][:n], r["line"] if full else None, False, True)
        self.title.setText("复盘 · " + r["title"])
        self.top_card.set_player(stone_pixmap(False, 48), r["white"], "执白", False, True)
        self.bottom_card.set_player(stone_pixmap(True, 48), r["black"], "执黑", True, True)
        for card in (self.top_card, self.bottom_card):
            card.set_clock("", 0, False, "")
        self.status.setText(f"第 {n} / {len(r['moves'])} 手")
        self.info.setText("拖动下面的滑块,或者用 ◀ ▶ 一步一步看")
        self.rp_label.setText("复盘(棋子上的数字是第几手)")


# ====================================================================== 排行榜
class RankPage(QWidget):
    def __init__(self, gw: "GomokuWindow") -> None:
        super().__init__()
        self.gw, self.w = gw, gw.w
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 14, 22, 16)
        root.setSpacing(10)
        top = QHBoxLayout()
        self.tabs = Segmented([("total", "总榜"), ("today", "今日"), ("week", "本周")])
        self.tabs.changed.connect(lambda _k: self.refresh())
        top.addWidget(self.tabs)
        top.addStretch(1)
        root.addLayout(top)
        self.rule = label("", "faint", wrap=True)
        root.addWidget(self.rule)
        head = QFrame()
        head.setObjectName("gmRankHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 4, 18, 4)
        for text, width in (("名次", 56), ("玩家", 0), ("积分", 70), ("胜场", 60), ("场次", 60), ("胜率", 70)):
            lab = label(text, "gmSub")
            if width:
                lab.setFixedWidth(width)
                lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hl.addWidget(lab, 0 if width else 1)
        root.addWidget(head)
        self.area, self.list = scroll_list()
        root.addWidget(self.area, 1)
        self.me_bar = QFrame()
        self.me_bar.setObjectName("gmMeBar")
        ml = QHBoxLayout(self.me_bar)
        ml.setContentsMargins(16, 10, 16, 10)
        self.me_text = label("", "gmMeText", wrap=True)
        ml.addWidget(self.me_text, 1)
        root.addWidget(self.me_bar)
        self._sig = None

    def refresh(self, force: bool = False) -> None:
        kind = self.tabs.current
        lo, hi = league.period_bounds(kind)
        games = self.w.gm_games()
        rows = league.standings(games, lo, hi)
        me = self.w.gm_my_id()
        rules = {"total": "总榜:所有计分对局,永久保留。",
                 "today": "今日榜:本机时间今天 0:00 起结束的对局。",
                 "week": "本周榜:本机时间本周一 0:00 起结束的对局。"}[kind]
        self.rule.setText(rules + "胜 3 分、平 1 分、负 0 分;同分比胜场,再比胜率。"
                          "每盘棋双方都签了名,所有人的电脑独立验证、算出同样的榜。")
        sig = (kind, tuple((r["id"], r["pts"], r["wins"], r["games"], r["nick"]) for r in rows))
        if sig != self._sig or force:
            self._sig = sig
            clear_layout(self.list)
            if not rows:
                self.list.addWidget(label("这段时间还没有计分的对局。去大厅约一局吧!", "gmEmpty", wrap=True, center=True))
            for r in rows[:100]:
                self.list.addWidget(self._row(r, r["id"] == me))
            self.list.addStretch(1)
        rank, mine, above = league.rank_of(rows, me)
        if not mine:
            self.me_text.setText("你还没有上这个榜。下一盘计分的对局就能上榜!")
        elif above is None:
            self.me_text.setText(f"你排第 {rank} 名,积分 {mine['pts']},领先所有人!" if rank == 1 else
                                 f"你排第 {rank} 名,积分 {mine['pts']}")
        else:
            gap = above["pts"] - mine["pts"]
            extra = f"差 {gap} 分" if gap > 0 else "同分,比胜场 / 胜率"
            self.me_text.setText(f"你排第 {rank} 名,积分 {mine['pts']} · 距第 {above['rank']} 名「{above['nick']}」{extra}")

    def _row(self, r: dict, me: bool) -> QFrame:
        row = QFrame()
        row.setObjectName("gmRankMe" if me else "gmRankRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 7, 18, 7)
        lay.setSpacing(0)
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(r["rank"], str(r["rank"]))
        rk = label(medal, "gmRank")
        rk.setFixedWidth(56)
        rk.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(rk)
        who = QHBoxLayout()
        who.setSpacing(10)
        who.addWidget(avatar_label(r["id"], r["nick"], 32))
        name = label("", "gmRowTitle")
        elide(name, r["nick"] + ("(我)" if me else ""), 220)
        who.addWidget(name, 1)
        lay.addLayout(who, 1)
        for text, width in ((str(r["pts"]), 70), (str(r["wins"]), 60), (str(r["games"]), 60),
                            (f"{r['rate'] * 100:.0f}%", 70)):
            lab = label(text, "gmNum" if width == 70 and text == str(r["pts"]) else "gmCell")
            lab.setFixedWidth(width)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lab)
        return row


# ====================================================================== 我的战绩
class RecordPage(QWidget):
    def __init__(self, gw: "GomokuWindow") -> None:
        super().__init__()
        self.gw, self.w = gw, gw.w
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 14, 22, 16)
        root.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.cards = {}
        for i, (key, caption) in enumerate((("pts", "总积分"), ("games", "总场次"), ("wld", "胜 / 负 / 平"),
                                            ("rate", "胜率"), ("streak", "当前连胜"), ("best", "最高连胜"))):
            card = QFrame()
            card.setObjectName("gmStat")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(0)
            v = label("0", "gmStatValue")
            cl.addWidget(v)
            cl.addWidget(label(caption, "gmSub"))
            self.cards[key] = v
            grid.addWidget(card, i // 3, i % 3)
        root.addLayout(grid)
        top = QHBoxLayout()
        top.addWidget(label("历史对局", "section"))
        top.addStretch(1)
        self.filter = Segmented([("all", "全部"), ("pvp", "对战"), ("ai", "人机练习")])
        self.filter.changed.connect(lambda _k: self.refresh(force=True))
        top.addWidget(self.filter)
        root.addLayout(top)
        self.area, self.list = scroll_list()
        root.addWidget(self.area, 1)
        self._sig = None

    def refresh(self, force: bool = False) -> None:
        w = self.w
        me = w.gm_my_id()
        games = w.gm_games()
        st = league.player_stats(games, me)
        self.cards["pts"].setText(str(st["pts"]))
        self.cards["games"].setText(str(st["games"]))
        self.cards["wld"].setText(f"{st['wins']} / {st['losses']} / {st['draws']}")
        self.cards["rate"].setText(f"{st['rate'] * 100:.0f}%" if st["games"] else "—")
        self.cards["streak"].setText(str(st["streak"]))
        self.cards["best"].setText(str(st["best"]))
        items = []
        if self.filter.current in ("all", "pvp"):
            items += [("pvp", h) for h in league.history(games, me)]
        if self.filter.current in ("all", "ai"):
            items += [("ai", p) for p in w.gm_practice]
        items.sort(key=lambda it: -it[1]["end_ts"])
        sig = (self.filter.current, tuple((k, it.get("id", ""), it.get("end_ts"), it.get("result"), it.get("rated"))
                                          for k, it in items[:200]))
        if sig == self._sig and not force:
            return
        self._sig = sig
        clear_layout(self.list)
        if not items:
            self.list.addWidget(label("还没有对局记录。", "gmEmpty", center=True))
        for kind, it in items[:200]:
            self.list.addWidget(self._row(kind, it))
        self.list.addStretch(1)

    def _row(self, kind: str, it: dict) -> QFrame:
        row = QFrame()
        row.setObjectName("gmRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.setSpacing(10)
        if kind == "ai":
            lay.addWidget(avatar_label("ai", "🤖", 34))
            title = f"vs 电脑({LEVELS.get(it.get('level'), '')})"
            color = "执黑" if it.get("color") == "b" else "执白"
            sub = f"{color} · {it.get('moves', 0)} 手 · {fmt_time(it['end_ts'])}"
            res = it.get("result")
            chip_text, chip_kind = RESULT_TEXT.get(res, ("未下完", "none"))
            pts_text = "练习"
        else:
            lay.addWidget(avatar_label(it["opp"], it["opp_nick"], 34))
            title = f"vs {it['opp_nick']}"
            color = "执黑" if it["color"] == "b" else "执白"
            how = league.STATUS_TEXT.get(it["status"], "")
            sub = f"{color} · {it['moves']} 手 · {how} · {fmt_time(it['end_ts'])}"
            if it["result"]:
                chip_text, chip_kind = RESULT_TEXT[it["result"]]
            elif it["status"] == "abandon_pending":
                chip_text, chip_kind = "待确认", "none"
            elif it["status"] == "void":
                chip_text, chip_kind = "作废", "none"
            else:
                chip_text, chip_kind = "未下完", "none"
            pts_text = f"+{it['pts']}" if it["rated"] else "不计分"
            if it["why"]:
                sub += f" · {it['why']}"
        col = QVBoxLayout()
        col.setSpacing(1)
        t = label("", "gmRowTitle")
        elide(t, title, 260)
        col.addWidget(t)
        s = label("", "gmRowSub")
        elide(s, sub, 420)
        col.addWidget(s)
        lay.addLayout(col, 1)
        c = chip(chip_text, chip_kind)
        c.setFixedWidth(52)
        lay.addWidget(c)
        p = label(pts_text, "gmNum" if pts_text.startswith("+") else "gmSub")
        p.setFixedWidth(64)
        p.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(p)
        lay.addWidget(btn("复盘", "link", lambda _=False, k=kind, i=it: self.w.gm_replay(k, i), 56))
        return row


# ====================================================================== 窗口
class GomokuWindow(Dialog):
    PAGES = [("lobby", "大厅"), ("game", "对局"), ("rank", "排行榜"), ("me", "我的战绩")]

    def __init__(self, w) -> None:
        super().__init__(w, "五子棋 · 密语")
        self.w = w
        self.setObjectName("gomoku")
        self.setModal(False)
        self.resize(1080, 720)
        self.setMinimumSize(760, 560)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QFrame()
        head.setObjectName("gmHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 14, 22, 10)
        hl.setSpacing(14)
        hl.addWidget(label("⚫⚪ 五子棋", "dialogTitle"))
        self.nav = Segmented(self.PAGES)
        self.nav.changed.connect(self._nav)
        hl.addWidget(self.nav)
        hl.addStretch(1)
        self.me_chip = label("", "gmMeChip")
        hl.addWidget(self.me_chip)
        root.addWidget(head)
        self.stack = QStackedWidget()
        self.pages = {"lobby": LobbyPage(self), "game": GamePage(self), "rank": RankPage(self), "me": RecordPage(self)}
        for key, _t in self.PAGES:
            self.stack.addWidget(self.pages[key])
        root.addWidget(self.stack, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        self._toast = label("", "gmToast", wrap=True, center=True)
        self._toast.setParent(self)
        self._toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast.hide)
        self._last_pts = None
        self.refresh_all()

    def _nav(self, key: str) -> None:
        self.go(key, from_nav=True)

    def go(self, key: str, from_nav: bool = False) -> None:
        from .. import motion
        page = self.pages.get(key)
        if page is None:
            return
        if not from_nav:
            self.nav.select(key, emit=False)
        if self.stack.currentWidget() is not page:
            before = motion.snapshot(self.stack)
            self.stack.setCurrentWidget(page)
            motion.crossfade(self.stack, before, 150)
        page.refresh(force=True) if key != "game" else page.refresh()

    def current(self) -> str:
        for k, p in self.pages.items():
            if self.stack.currentWidget() is p:
                return k
        return "lobby"

    def refresh_all(self) -> None:
        cur = self.current()
        self.pages[cur].refresh()
        self._refresh_chip()

    def refresh_page(self, key: str) -> None:
        if self.current() == key:
            self.pages[key].refresh()
        self._refresh_chip()

    def _refresh_chip(self) -> None:
        games = self.w.gm_games()
        me = self.w.gm_my_id()
        st = league.player_stats(games, me)
        rank, _r, _a = league.rank_of(league.standings(games), me)
        self.me_chip.setText(f"{st['pts']} 分 · " + (f"第 {rank} 名" if rank else "未上榜"))
        if self._last_pts is not None and st["pts"] != self._last_pts:
            from .. import motion
            old = self._last_pts
            motion.animate(self.me_chip, float(old), float(st["pts"]), 900,
                           lambda v: self.me_chip.setText(f"{int(round(v))} 分 · " + (f"第 {rank} 名" if rank else "未上榜")),
                           key="_chip_anim")
        self._last_pts = st["pts"]

    def tick(self) -> None:
        cur = self.current()
        if cur == "game":
            self.pages["game"].tick()

    def toast(self, text: str, ms: int = 3200) -> None:
        """窗口顶上飘一句提示,几秒后自己消失(不用点)。"""
        t = self._toast
        t.setText(text)
        t.adjustSize()
        t.setFixedWidth(min(self.width() - 80, max(240, t.sizeHint().width() + 40)))
        t.adjustSize()
        t.move((self.width() - t.width()) // 2, 64)
        t.show()
        t.raise_()
        self._toast_timer.start(ms)

    def show_result(self, **kw) -> None:
        self.go("game")
        self.pages["game"].overlay.show_result(**kw)

    def closeEvent(self, e) -> None:
        if not self.w.gm_can_close():
            e.ignore()
            return
        self.timer.stop()
        super().closeEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:                 # ESC 只关这个窗口(对局中会先问)
            self.close()
            return
        super().keyPressEvent(e)


__all__ = ["GomokuWindow", "InviteDialog", "SetupDialog", "AIDialog", "QPoint"]
