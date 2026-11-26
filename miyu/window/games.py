"""
密语 · 投票、抽签、骰子、五子棋、猜拳、一起画,以及输入框旁 ＋ 的工具菜单。
"""
from __future__ import annotations

import random
import re
import secrets
import time
import uuid

from PySide6.QtCore import QPoint, QPointF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..cards import GOMOKU_N, RPS, gomoku_winner, new_nonce, rps_hash, rps_result
from ..dialogs import Dialog, Switch, ask, info
from ..fun import FRIEND_PHOTO
from ..theme import T, qcolor
from ..ui import button, label
from ..widgets import Conv, Msg


BOARD_W, BOARD_H = 1000, 700                  # 画板的逻辑坐标
BOARD_COLORS = ["#1D1D1F", "#FF453A", "#FF9F0A", "#FFD60A", "#30D158", "#0A84FF", "#BF5AF2", "#FF6FAE"]
BOARD_WIDTHS = [3, 7, 14]
ERASER = "#FFFFFF"
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def clean_stroke(d: dict) -> dict | None:
    """校验收到的笔迹。"""
    pts = d.get("pts")
    c, w = d.get("c"), d.get("w")
    if not (isinstance(pts, list) and len(pts) % 2 == 0 and len(pts) <= 8000):
        return None
    if not (isinstance(c, str) and _HEX.match(c)) or type(w) not in (int, float) or not (1 <= w <= 40):
        return None
    out = []
    for i, v in enumerate(pts):
        if type(v) is not int:
            return None
        out.append(max(0, min(BOARD_W if i % 2 == 0 else BOARD_H, v)))
    return {"c": c, "w": float(w), "pts": out}


DEFAULT_QUICK_PHRASES = [
    "收到 👌", "稍等，马上回~", "开会中，晚点聊", "没问题！",
    "摸鱼中勿扰 🐟", "太强了 👍", "辛苦啦 ☕", "下班走起！",
]


class QuickPhraseDialog(Dialog):
    """3.2 快捷常用语面板:一键发送常用短语,支持自由增删。"""

    def __init__(self, parent, phrases: list[str], on_send) -> None:
        super().__init__(parent, "快捷常用语")
        self.phrases = phrases
        self.on_send = on_send
        self.setFixedWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(8)
        lay.addWidget(label("⚡ 快捷常用语（点击即发送）", "dialogTitle"))
        self.list_box = QWidget(self)
        self.list_lay = QVBoxLayout(self.list_box)
        self.list_lay.setContentsMargins(0, 0, 4, 0)
        self.list_lay.setSpacing(6)
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(self.list_box)
        area.setFixedHeight(260)
        lay.addWidget(area)
        add_row = QHBoxLayout()
        self.new_edit = QLineEdit(self)
        self.new_edit.setPlaceholderText("添加新常用语，按回车保存…")
        self.new_edit.setMaxLength(80)
        self.new_edit.returnPressed.connect(self._add)
        add_row.addWidget(self.new_edit, 1)
        add_row.addWidget(button("添加", "primary", self._add, 70))
        lay.addLayout(add_row)
        lay.addWidget(button("关闭", "link", self.accept))
        self._rebuild()

    def _rebuild(self) -> None:
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for idx, text in enumerate(self.phrases):
            row = QHBoxLayout()
            row.setSpacing(6)
            w = QWidget(self.list_box)
            w.setLayout(row)
            b = button(text, "", lambda _=False, t=text: self._pick(t))
            b.setMinimumHeight(34)
            row.addWidget(b, 1)
            del_b = button("×", "link", lambda _=False, i=idx: self._del(i), 28)
            row.addWidget(del_b)
            self.list_lay.addWidget(w)
        self.list_lay.addStretch(1)

    def _pick(self, text: str) -> None:
        self.accept()
        if callable(self.on_send):
            self.on_send(text)

    def _add(self) -> None:
        t = self.new_edit.text().strip()[:80]
        if t and t not in self.phrases and len(self.phrases) < 30:
            self.phrases.append(t)
            self.new_edit.clear()
            self._rebuild()

    def _del(self, idx: int) -> None:
        if 0 <= idx < len(self.phrases):
            self.phrases.pop(idx)
            self._rebuild()


class ReminderDialog(Dialog):
    """3.2 定时提醒 / 倒计时小纸条。"""

    def __init__(self, parent) -> None:
        super().__init__(parent, "定时提醒小纸条")
        self.setFixedWidth(390)
        self.minutes = 15
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("⏰ 定时提醒 / 倒计时小纸条", "dialogTitle"))
        lay.addWidget(label("快捷选择倒计时时长:", "hint"))
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self._pbtns: list[QPushButton] = []
        for m in (1, 5, 15, 30, 60):
            b = QPushButton(f"{m} 分钟", self)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setChecked(m == 15)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=m: self._set_m(v))
            prow.addWidget(b)
            self._pbtns.append(b)
        lay.addLayout(prow)
        self.note_edit = QLineEdit(self)
        self.note_edit.setPlaceholderText("提醒内容，例如：喝水休息一下 ☕ / 开会提醒")
        self.note_edit.setText("喝水休息一下 ☕")
        self.note_edit.setMaxLength(80)
        lay.addWidget(self.note_edit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 80))
        row.addWidget(button("开始倒计时", "primary", self.accept, 110))
        lay.addLayout(row)

    def _set_m(self, m: int) -> None:
        self.minutes = m
        for b, v in zip(self._pbtns, (1, 5, 15, 30, 60)):
            b.setChecked(v == m)


class BentoToolsPopup(QFrame):
    """Bento 磁贴工具抽屉:半透明毛玻璃分类网格,取代传统长菜单。"""

    def __init__(self, parent, sections: list[tuple[str, list[tuple[str, str, str, object]]]]) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedWidth(448)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self)
        card.setObjectName("bentoPopup")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(8)
        for sec_title, tiles in sections:
            if not tiles:
                continue
            lay.addWidget(label(sec_title, "section"))
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 2)
            grid.setSpacing(7)
            for idx, (emoji, title, sub, cb) in enumerate(tiles):
                btn = QPushButton(f"{emoji}  {title}\n     {sub}", card)
                btn.setObjectName("bentoTile")
                btn.setMinimumHeight(48)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _=False, fn=cb: self._pick(fn))
                grid.addWidget(btn, idx // 2, idx % 2)
            lay.addLayout(grid)

    def _pick(self, fn) -> None:
        self.close()
        if callable(fn):
            fn()


class PollDialog(Dialog):
    def __init__(self, parent) -> None:
        super().__init__(parent, "发起投票")
        self.setFixedWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label("发起投票", "dialogTitle"))
        self.q = QLineEdit()
        self.q.setPlaceholderText("投票主题,例如:周五吃什么?")
        self.q.setMaxLength(80)
        lay.addWidget(self.q)
        lay.addWidget(label("选项(每行一个,2 到 8 个)", "section"))
        self.opts = QPlainTextEdit()
        self.opts.setPlaceholderText("火锅\n烧烤\n日料")
        self.opts.setFixedHeight(130)
        lay.addWidget(self.opts)
        card = QFrame()
        card.setObjectName("plainCard")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(14, 6, 12, 6)
        cl.addWidget(label("可以多选"))
        cl.addStretch(1)
        self.multi = Switch(False)
        cl.addWidget(self.multi)
        lay.addWidget(card)
        self.err = label("", "errorText")
        lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 80))
        row.addWidget(button("发起", "primary", self._ok, 80))
        lay.addLayout(row)

    def options(self) -> list[str]:
        seen, out = set(), []
        for line in self.opts.toPlainText().splitlines():
            t = line.strip()[:40]
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out[:8]

    def _ok(self) -> None:
        if not self.q.text().strip():
            self.err.setText("写一个投票主题")
            return
        if len(self.options()) < 2:
            self.err.setText("至少要 2 个选项")
            return
        self.accept()

    def card(self) -> dict:
        return {"type": "poll", "q": self.q.text().strip()[:80], "opts": self.options(), "multi": self.multi.isChecked()}


class LotteryDialog(Dialog):
    """抽签:从在线成员里随机抽人。members = [(id, 昵称), ...]"""

    def __init__(self, parent, members: list[tuple[str, str]]) -> None:
        super().__init__(parent, "抽签")
        self.setFixedWidth(400)
        self.members = members
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label("抽签", "dialogTitle"))
        self.title = QLineEdit()
        self.title.setPlaceholderText("抽什么?例如:谁去拿外卖")
        self.title.setMaxLength(40)
        lay.addWidget(self.title)
        lay.addWidget(label(f"参加的人({len(members)} 人在线)", "section"))
        card = QFrame()
        card.setObjectName("plainCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 4, 12, 4)
        self.switches = []
        for pid, nick in members[:30]:
            row = QHBoxLayout()
            row.addWidget(label(nick))
            row.addStretch(1)
            sw = Switch(True)
            row.addWidget(sw)
            cl.addLayout(row)
            self.switches.append((pid, nick, sw))
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(card)
        area.setFixedHeight(min(240, 40 * len(members) + 12))
        lay.addWidget(area)
        self.err = label("", "errorText")
        lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 80))
        row.addWidget(button("开抽", "primary", self._ok, 80))
        lay.addLayout(row)

    def chosen(self) -> list[tuple[str, str]]:
        return [(pid, nick) for pid, nick, sw in self.switches if sw.isChecked()]

    def _ok(self) -> None:
        if len(self.chosen()) < 2:
            self.err.setText("至少要 2 个人参加")
            return
        self.accept()

    def card(self) -> dict:
        cands = self.chosen()
        win = secrets.choice(cands)
        return {"type": "draw", "title": self.title.text().strip()[:40] or "抽签",
                "cands": [{"id": pid, "nick": nick[:20]} for pid, nick in cands], "win": win[0]}


class Canvas(QWidget):
    """画板画布。strokes: {sid: {"c","w","pts","by","open"}};已画完的笔画缓存在一张图里。"""
    stroke_points = Signal(str, list, bool)            # (笔画 id, 新增的点, 是否结束)

    def __init__(self, strokes: dict) -> None:
        super().__init__()
        self.strokes = strokes
        self.color = BOARD_COLORS[0]
        self.width_ = BOARD_WIDTHS[1]
        self.eraser = False
        self.cur: str | None = None
        self._pending: list = []
        self._cache: QPixmap | None = None
        self._cache_n = -1
        self.setMinimumSize(500, 350)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(50)
        self.flush_timer.timeout.connect(self._flush)

    # 坐标换算:逻辑坐标 1000x700 等比缩放居中
    def _geom(self) -> tuple[float, float, float]:
        s = min(self.width() / BOARD_W, self.height() / BOARD_H)
        return s, (self.width() - BOARD_W * s) / 2, (self.height() - BOARD_H * s) / 2

    def _to_logic(self, pos) -> tuple[int, int]:
        s, ox, oy = self._geom()
        return (max(0, min(BOARD_W, int((pos.x() - ox) / s))), max(0, min(BOARD_H, int((pos.y() - oy) / s))))

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.cur = secrets.token_hex(6)
        x, y = self._to_logic(e.position())
        self.strokes[self.cur] = {"c": ERASER if self.eraser else self.color,
                                  "w": 26.0 if self.eraser else float(self.width_), "pts": [x, y], "by": "me",
                                  "open": True}
        self._pending = [x, y]
        self.flush_timer.start()
        self.update()

    def mouseMoveEvent(self, e) -> None:
        if self.cur is None:
            return
        x, y = self._to_logic(e.position())
        st = self.strokes.get(self.cur)
        if st is None:
            return
        if abs(st["pts"][-2] - x) + abs(st["pts"][-1] - y) < 2:
            return
        st["pts"] += [x, y]
        self._pending += [x, y]
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self.cur is None:
            return
        st = self.strokes.get(self.cur)
        if st is not None:
            st["open"] = False
        self._flush(end=True)
        self.cur = None
        self.flush_timer.stop()
        self.update()

    def _flush(self, end: bool = False) -> None:
        if self.cur is None:
            return
        if self._pending or end:
            self.stroke_points.emit(self.cur, self._pending, end)
            self._pending = []

    def invalidate(self) -> None:
        self._cache = None
        self.update()

    def resizeEvent(self, e) -> None:
        self._cache = None
        super().resizeEvent(e)

    @staticmethod
    def _draw_stroke(p: QPainter, st: dict) -> None:
        pts = st["pts"]
        pen = QPen(QColor(st["c"]), st["w"])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if len(pts) == 2:
            p.drawPoint(QPointF(pts[0], pts[1]))
            return
        path = QPainterPath(QPointF(pts[0], pts[1]))
        for i in range(2, len(pts), 2):
            path.lineTo(pts[i], pts[i + 1])
        p.drawPath(path)

    def render_image(self, scale: float = 1.0) -> QPixmap:
        pm = QPixmap(int(BOARD_W * scale), int(BOARD_H * scale))
        pm.fill(QColor("#FFFFFF"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(scale, scale)
        for st in list(self.strokes.values()):
            self._draw_stroke(p, st)
        p.end()
        return pm

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s, ox, oy = self._geom()
        done = [st for st in self.strokes.values() if not st.get("open")]
        dpr = self.devicePixelRatioF()
        if self._cache is None or self._cache_n != len(done):
            pm = QPixmap(max(1, int(BOARD_W * s * dpr)), max(1, int(BOARD_H * s * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(QColor("#FFFFFF"))
            cp = QPainter(pm)
            cp.setRenderHint(QPainter.RenderHint.Antialiasing)
            cp.scale(s, s)
            for st in done:
                self._draw_stroke(cp, st)
            cp.end()
            self._cache, self._cache_n = pm, len(done)
        p.fillRect(self.rect(), qcolor(T["btn2"]))
        p.drawPixmap(QPointF(ox, oy), self._cache)
        p.translate(ox, oy)
        p.scale(s, s)
        for st in self.strokes.values():
            if st.get("open"):
                self._draw_stroke(p, st)
        p.end()


class Whiteboard(Dialog):
    """一起画的画板窗口(不阻塞主窗口)。"""
    stroke = Signal(str, str, float, list, bool)       # (笔画 id, 颜色, 粗细, 新增点, 结束)
    undo = Signal(str)
    clear_all = Signal()
    closed = Signal()

    def __init__(self, parent, title: str, strokes: dict) -> None:
        super().__init__(parent, f"一起画 · {title}")
        self.setModal(False)
        self.resize(900, 700)
        self.setObjectName("whiteboard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.title = label(title, "dialogTitle")
        bar.addWidget(self.title)
        self.people = label("", "fileSub")
        bar.addWidget(self.people)
        bar.addStretch(1)
        self.swatches = []
        for c in BOARD_COLORS:
            b = button("", "swatch", lambda _=False, c=c: self.pick_color(c))
            b.setFixedSize(24, 24)
            b.setStyleSheet(f"QPushButton {{ background: {c}; border-radius: 12px; border: 2px solid rgba(0,0,0,0.12); }}")
            bar.addWidget(b)
            self.swatches.append((c, b))
        bar.addSpacing(8)
        self.width_btns = []
        for w, name in zip(BOARD_WIDTHS, ("细", "中", "粗")):
            b = button(name, "tab", lambda _=False, w=w: self.pick_width(w))
            b.setCheckable(True)
            bar.addWidget(b)
            self.width_btns.append((w, b))
        self.eraser_btn = button("橡皮", "tab", self.toggle_eraser)
        self.eraser_btn.setCheckable(True)
        bar.addWidget(self.eraser_btn)
        bar.addSpacing(8)
        bar.addWidget(button("撤销", "", self.undo_mine))
        bar.addWidget(button("清空", "destructive", self._clear))
        bar.addWidget(button("保存图片", "", self.save_png))
        lay.addLayout(bar)
        self.canvas = Canvas(strokes)
        self.canvas.stroke_points.connect(self._on_points)
        lay.addWidget(self.canvas, 1)
        self.mine: list[str] = []
        self.pick_width(BOARD_WIDTHS[1])
        self.pick_color(BOARD_COLORS[0])

    def pick_color(self, c: str) -> None:
        self.canvas.color = c
        self.canvas.eraser = False
        self.eraser_btn.setChecked(False)
        for cc, b in self.swatches:
            b.setStyleSheet(f"QPushButton {{ background: {cc}; border-radius: 12px; "
                            f"border: {'3px solid ' + T['accent'] if cc == c else '2px solid rgba(0,0,0,0.12)'}; }}")

    def pick_width(self, w: int) -> None:
        self.canvas.width_ = w
        for ww, b in self.width_btns:
            b.setChecked(ww == w)

    def toggle_eraser(self) -> None:
        self.canvas.eraser = not self.canvas.eraser
        self.eraser_btn.setChecked(self.canvas.eraser)

    def _on_points(self, sid: str, pts: list, end: bool) -> None:
        st = self.canvas.strokes.get(sid)
        if st is None:
            return
        if sid not in self.mine:
            self.mine.append(sid)
        self.stroke.emit(sid, st["c"], st["w"], list(pts), end)

    def undo_mine(self) -> None:
        while self.mine:
            sid = self.mine.pop()
            if sid in self.canvas.strokes:
                self.canvas.strokes.pop(sid, None)
                self.canvas.invalidate()
                self.undo.emit(sid)
                return

    def _clear(self) -> None:
        if ask(self, "清空画板?", "所有人画的内容都会被清空。", "清空", danger=True):
            self.canvas.strokes.clear()
            self.canvas.invalidate()
            self.clear_all.emit()

    def save_png(self) -> None:
        from PySide6.QtCore import QStandardPaths
        import os
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        path, _ = QFileDialog.getSaveFileName(self, "保存画板", os.path.join(folder, "一起画.png"), "PNG 图片 (*.png)")
        if path:
            self.canvas.render_image(1.5).save(path, "PNG")

    def set_people(self, n: int) -> None:
        self.people.setText(f"  ·  {n} 人在画" if n > 1 else "  ·  只有你在画")

    def closeEvent(self, e) -> None:
        self.closed.emit()
        super().closeEvent(e)


class GamesMixin:
    """卡片类玩法和 ＋ 菜单。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_games(self) -> None:
        self.votes: dict[str, dict[str, list]] = {}       # 投票 mid → {投票人 id: [选项]}
        self.games: dict[str, dict] = {}
        self.boards: dict[str, dict] = {}
        self.whiteboards: dict[str, Whiteboard] = {}
        self.fresh_cards: set[str] = set()                 # 刚收到、要播放动画的卡片

    # ---------------------------------------------------------------- 发卡片
    def _can_send(self) -> Conv | None:
        conv = self.current
        if conv is None or not self.input.isEnabled():
            info(self, "现在不能发送", "当前会话无法发送消息(对方离线,或你已退出大厅)。")
            return None
        return conv

    def _send_card(self, conv: Conv, card: dict, text: str = "") -> Msg | None:
        scope, target = self.scope_target(conv)
        mid = self.core.send_card(scope, target, card, text)
        if mid is None:
            return None
        m = Msg(text, mid=mid, sender=self.me["id"], nick=self.me.get("nick", ""), tag=self.me.get("tag", ""),
                mine=True, card=card)
        self.fresh_cards.add(mid)
        self._add_message(conv, m)
        self._sent_fx()
        return m


    def fill_tools_menu(self) -> None:
        """输入框左边 ＋ 的菜单。"""
        m = self.tools_menu
        m.clear()
        conv = self.current
        if conv is None:
            return
        if conv.kind == "self":
            act = m.addAction("收藏夹里没有工具,随手记就好 ✍️")
            act.setEnabled(False)
            return
        group = conv.kind != "dm"
        if group:
            m.addAction("📊  发起投票", self.start_poll)
            m.addAction("🎲  抽签", self.start_lottery)
        m.addAction("🎯  掷骰子", self.roll_dice)
        if not group:
            m.addAction("⚫  五子棋", lambda: self.start_game("gomoku"))
            m.addAction("✊  猜拳", lambda: self.start_game("rps"))
        m.addAction("🎨  一起画", self.start_board)
        m.addAction("🏆  五子棋大厅(排行榜对战)…", lambda: self.open_gomoku())
        m.addAction("🦆  谁是坏鸭(多人推理)…", lambda: self.open_duck())
        m.addAction("🕵  谁是卧底(说一句话猜身份)…", lambda: self.open_spy())
        if conv.kind in ("lobby", "room"):
            m.addAction("🐾  宠物等级排行榜…", lambda: self.open_pet_rank(conv))
        w = getattr(self, "video_win", None)
        if w is not None and getattr(w, "passthrough", False):
            m.addSeparator()
            m.addAction("🎬  视频窗口:取消鼠标穿透", self.video_passthrough_off)
        m.addSeparator()
        if group:
            if conv.kind == "room":
                m.addAction("✏️  修改群名…", lambda: self.rename_room(conv))
            m.addAction("📢  群公告…", self.edit_notice)
            m.addAction("📝  匿名纸条…", self.send_anon_note)
            m.addAction("🏆  本周排行榜", self.show_rank)
        else:
            m.addAction("👉  戳一戳", lambda: self.poke(conv.target, conv))
            m.addAction(f"🐾  让{self.pet_growth.name}去 TA 家串门", lambda: self.send_pet_visit(conv.target))
            m.addAction("🎭  宠物小剧场", lambda: self.start_skit(conv.target))
            f = self.pet_growth.friends.get(conv.target or "")
            if f and f["v"] >= FRIEND_PHOTO and f.get("pet"):
                m.addAction("📸  宠物合照", lambda: self.take_photo(conv.target))

    def _bento_sections(self) -> list[tuple[str, list[tuple[str, str, str, object]]]]:
        """构造 Bento 磁贴抽屉的分类与按钮:(分类标题, [(emoji, 标题, 副标题, 回调), ...])。"""
        conv = self.current
        if conv is None or conv.kind == "self":
            return []
        group = conv.kind != "dm"
        fun_tiles: list[tuple[str, str, str, object]] = []
        if group:
            fun_tiles.append(("📊", "发起投票", "单选或多选表决", self.start_poll))
            fun_tiles.append(("🎲", "幸运抽签", "在线成员随机抽人", self.start_lottery))
        else:
            fun_tiles.append(("⚫", "五子棋对战", "聊天卡片实时对弈", lambda: self.start_game("gomoku")))
            fun_tiles.append(("✊", "加密猜拳", "承诺防作弊出拳", lambda: self.start_game("rps")))
        fun_tiles.append(("🎯", "掷骰子", "1~6 点手气比拼", self.roll_dice))
        fun_tiles.append(("🎨", "一起画", "多人实时同步白板", self.start_board))
        fun_tiles.append(("⚡", "快捷常用语", "摸鱼一键回复短语", self.open_quick_phrases))
        fun_tiles.append(("🍅", "专注番茄钟", "萌宠伴学 + 喝水提醒", self.show_focus_dialog))
        fun_tiles.append(("⏰", "定时提醒", "喝水/开会倒计时提醒", self.open_reminder_dialog))

        party_tiles: list[tuple[str, str, str, object]] = [
            ("🏆", "五子棋大厅", "2.5D 立体棋盘对弈", lambda: self.open_gomoku()),
            ("🦆", "谁是坏鸭", "2.5D 潮玩跑图推理", lambda: self.open_duck()),
            ("🕵", "谁是卧底", "一句话描述找卧底", lambda: self.open_spy()),
        ]
        if conv.kind in ("lobby", "room"):
            party_tiles.append(("🐾", "宠物等级榜", "看看谁家萌宠最强", lambda c=conv: self.open_pet_rank(c)))
        party_tiles.append(("🍉", "合成大萌宠", "2.5D 物理合成大西瓜", self.show_merge_game))
        party_tiles.append(("🎮", "接零食大作战", "2.5D 道具与狂热双倍", self.show_snack_game))
        party_tiles.append(("☁️", "云端跳跳乐", "2.5D 萌宠蹦云冲高分", self.show_cloud_game))
        party_tiles.append(("🎁", "签到与通行证", "每日领限定装扮动作", self.show_pet_pass))

        social_tiles: list[tuple[str, str, str, object]] = []
        if group:
            social_tiles.append(("📸", "萌宠合拍大头贴", "2.5D 拍立得贴纸合影", lambda: self.show_photobooth()))
            social_tiles.append(("📢", "群公告", "置顶通知全员可见", self.edit_notice))
            social_tiles.append(("📝", "匿名纸条", "多跳混淆隐藏作者", self.send_anon_note))
            social_tiles.append(("🔥", "本周排行榜", "话痨与活跃之星", self.show_rank))
            if conv.kind == "room":
                social_tiles.append(("✏️", "修改群名", "同步更新暗号群名", lambda c=conv: self.rename_room(c)))
        else:
            social_tiles.append(("📸", "双人萌宠大头贴", "生成拍立得合影直发", lambda c=conv: self.show_photobooth(c.target)))
            social_tiles.append(("👉", "戳一戳", "轻轻拍拍对方窗口", lambda c=conv: self.poke(c.target, c)))
            social_tiles.append(("🐾", f"让{self.pet_growth.name}串门", "派萌宠去对方桌边玩",
                                 lambda c=conv: self.send_pet_visit(c.target)))
            social_tiles.append(("🎭", "宠物小剧场", "两只萌宠同台飙戏", lambda c=conv: self.start_skit(c.target)))
            f = self.pet_growth.friends.get(conv.target or "")
            if f and f["v"] >= FRIEND_PHOTO and f.get("pet"):
                social_tiles.append(("📸", "宠物合照", "纪念两小只的友谊", lambda c=conv: self.take_photo(c.target)))
        w = getattr(self, "video_win", None)
        if w is not None and getattr(w, "passthrough", False):
            social_tiles.append(("🎬", "恢复视频点击", "关闭画中画鼠标穿透", self.video_passthrough_off))
        return [("互动小工具", fun_tiles), ("派对游戏厅", party_tiles), ("群组与萌宠" if group else "私聊与萌宠", social_tiles)]

    def open_tools_drawer(self) -> None:
        """点输入框旁 ＋ 弹出 Bento 磁贴工具箱。"""
        conv = self.current
        if conv is None:
            return
        if conv.kind == "self":
            self.fill_tools_menu()
            pos = self.tools_btn.mapToGlobal(QPoint(0, 0))
            self.tools_menu.exec(QPoint(pos.x(), pos.y() - 44))
            return
        sections = self._bento_sections()
        pop = BentoToolsPopup(self, sections)
        pos = self.tools_btn.mapToGlobal(QPoint(0, 0))
        pop.adjustSize()
        pw, ph = pop.width(), pop.sizeHint().height()
        x = pos.x() - 16
        y = pos.y() - ph - 10
        scr = self.screen()
        if scr is not None:
            geo = scr.availableGeometry()
            x = max(geo.left() + 8, min(x, geo.right() - pw - 8))
            y = max(geo.top() + 8, min(y, geo.bottom() - ph - 8))
        else:
            x, y = max(8, x), max(8, y)
        pop.move(x, y)
        pop.show()

    def open_quick_phrases(self) -> None:
        phrases = getattr(self, "quick_phrases", None)
        if not isinstance(phrases, list):
            phrases = list(DEFAULT_QUICK_PHRASES)
            self.quick_phrases = phrases

        def _send(text: str) -> None:
            if self.input.isEnabled():
                self.input.setPlainText(text)
                self.send_current()

        QuickPhraseDialog(self, phrases, _send).exec()

    def open_reminder_dialog(self) -> None:
        dlg = ReminderDialog(self)
        if not dlg.exec():
            return
        mins = dlg.minutes
        note = dlg.note_edit.text().strip() or "时间到啦!"
        conv = self.current
        if conv is not None:
            self._system(conv, f"⏰ 已设置 {mins} 分钟提醒：「{note}」")
        if hasattr(self, "pet"):
            self.pet.say(f"记好啦! {mins} 分钟后提醒你~", 2.5)
        seq = getattr(self, "_remind_seq", 0) + 1
        self._remind_seq = seq
        isl = getattr(self, "island", None)
        if isl is not None:
            isl.set_reminder(note, time.monotonic() + mins * 60)

        t = QTimer(self)
        t.setSingleShot(True)

        def _fire() -> None:
            if getattr(self, "_remind_seq", 0) == seq and getattr(self, "island", None) is not None:
                self.island.clear_reminder()
            if hasattr(self, "pet"):
                self.pet.celebrate()
                self.pet.say(f"⏰ {note}", 5.0)
            if self.current is not None:
                self._system(self.current, f"⏰ 定时提醒到点啦：{note}")
            # 老板键隐藏窗口时不弹出模态框,避免暴露隐藏状态
            if self.isVisible() and not self.isMinimized():
                info(self, "⏰ 定时提醒", note)
            t.deleteLater()

        t.timeout.connect(_fire)
        t.start(mins * 60 * 1000)

    # ---------------------------------------------------------------- 投票 / 抽签 / 骰子
    def start_poll(self) -> None:
        conv = self._can_send()
        if conv is None:
            return
        dlg = PollDialog(self)
        if dlg.exec():
            self._send_card(conv, dlg.card())

    def poll_state(self, m: Msg) -> dict:
        opts = m.card.get("opts") or []
        votes = self.votes.get(m.mid, {})
        counts = [0] * len(opts)
        names: list[list[str]] = [[] for _ in opts]
        for voter, chosen in votes.items():
            nick = self.me.get("nick", "我") if voter == self.me.get("id") else self.peers.get(voter, {}).get("nick", "?")
            for i in chosen:
                if 0 <= i < len(opts):
                    counts[i] += 1
                    names[i].append(nick)
        mine = set(votes.get(self.me.get("id"), []))
        return {"counts": counts, "names": names, "mine": mine, "voters": len([v for v in votes.values() if v])}

    def vote(self, m: Msg, idx: int) -> None:
        conv = self._conv_of(m)
        if conv is None:
            return
        me = self.me.get("id")
        cur = list(self.votes.setdefault(m.mid, {}).get(me, []))
        if idx in cur:
            cur.remove(idx)
        elif m.card.get("multi"):
            cur.append(idx)
        else:
            cur = [idx]
        self.votes[m.mid][me] = sorted(cur)
        scope, target = self.scope_target(conv)
        self.core.send_event(scope, target, "vote", {"poll": m.mid, "c": sorted(cur)})
        self._update_card(m.mid)

    def _ev_vote(self, conv: Conv, d: dict, data: dict) -> None:
        poll, chosen = data.get("poll"), data.get("c")
        if not isinstance(poll, str) or not isinstance(chosen, list):
            return
        m = next((x for x in conv.messages if x.mid == poll and x.card and x.card.get("type") == "poll"), None)
        if m is None:
            return
        n = len(m.card.get("opts") or [])
        clean = sorted({i for i in chosen if type(i) is int and 0 <= i < n})
        if not m.card.get("multi"):
            clean = clean[:1]
        self.votes.setdefault(poll, {})[d["peer"]] = clean
        self._update_card(poll)

    def start_lottery(self) -> None:
        conv = self._can_send()
        if conv is None:
            return
        members = [(self.me["id"], self.me.get("nick", "我"))]
        pool = self.lobby_members() if conv.kind == "lobby" else self.room_members(conv.target)
        members += [(p["id"], p["nick"]) for p in pool if p["id"] != self.me.get("id")]
        if len(members) < 2:
            info(self, "人太少了", "至少要有 2 个人在线才能抽签。")
            return
        dlg = LotteryDialog(self, members)
        if dlg.exec():
            self._send_card(conv, dlg.card())

    def roll_dice(self) -> None:
        conv = self._can_send()
        if conv is not None:
            self._send_card(conv, {"type": "dice", "v": random.SystemRandom().randint(1, 6)})

    # ---------------------------------------------------------------- 五子棋 / 猜拳
    def start_game(self, game: str) -> None:
        conv = self._can_send()
        if conv is None or conv.kind != "dm":
            return
        gid = uuid.uuid4().hex
        card = {"type": "game", "game": game, "gid": gid, "black": self.me.get("id")}
        self.games[gid] = {"game": game, "peer": conv.target, "black": self.me.get("id"), "moves": [], "over": None}
        self._send_card(conv, card, "来一局五子棋?" if game == "gomoku" else "来猜拳!")

    def _game_for(self, m: Msg) -> dict:
        c = m.card
        gid = c.get("gid")
        g = self.games.get(gid)
        if g is None:
            g = {"game": c.get("game"), "peer": m.sender if not m.mine else (self._conv_of(m).target if self._conv_of(m) else ""),
                 "black": c.get("black"), "moves": [], "over": None}
            self.games[gid] = g
        return g

    def game_state(self, m: Msg) -> dict:
        g = self._game_for(m)
        me = self.me.get("id")
        if g["game"] == "gomoku":
            me_black = g.get("black") == me
            n = len(g["moves"])
            my_turn = (n % 2 == 0) == me_black
            return {"moves": g["moves"], "me_black": me_black, "my_turn": my_turn, "over": g.get("over"),
                    "line": g.get("line")}
        res = None
        if g.get("mine") and g.get("theirs"):
            res = rps_result(g["mine"], g["theirs"])
        return {"mine": g.get("mine"), "theirs": g.get("theirs"), "result": res, "their_ready": bool(g.get("their_h")),
                "over": g.get("over")}

    def game_action(self, m: Msg, action: str, data) -> None:
        conv = self._conv_of(m)
        if conv is None or conv.kind != "dm":
            return
        g = self._game_for(m)
        gid = m.card.get("gid")
        if action == "again":
            self.select_conv(conv.key)
            self.start_game(g["game"])
            return
        if not self.peers.get(conv.target, {}).get("online"):
            info(self, "对方不在线", "对方在线时才能继续游戏。")
            return
        if g["game"] == "gomoku":
            if action == "move":
                st = self.game_state(m)
                x, y = data
                if not st["my_turn"] or g.get("over") or [x, y] in g["moves"] or (x, y) in [tuple(v) for v in g["moves"]]:
                    return
                n = len(g["moves"])
                g["moves"].append((x, y))
                self.core.send_event("dm", conv.target, "g_move", {"gid": gid, "n": n, "x": x, "y": y})
                self._gomoku_check(g, mine_moved=True)
            elif action == "resign" and not g.get("over"):
                g["over"] = "resign_me"
                self.stats["losses"] += 1
                self.core.send_event("dm", conv.target, "g_resign", {"gid": gid})
        else:
            if action == "pick" and not g.get("mine") and data in RPS:
                g["mine"], g["nonce"] = data, new_nonce()
                g["my_h"] = rps_hash(gid, data, g["nonce"])
                self.core.send_event("dm", conv.target, "g_commit", {"gid": gid, "h": g["my_h"]})
                self._rps_maybe_reveal(gid, g, conv.target)
        self._hist_dirty = True
        self._update_card(m.mid)

    def _gomoku_check(self, g: dict, mine_moved: bool) -> None:
        line = gomoku_winner(g["moves"])
        if line:
            g["line"] = line
            g["over"] = "win" if mine_moved else "lose"
            self.stats["wins" if mine_moved else "losses"] += 1
            if mine_moved and self.fun.get("effects") and self.window_visible():
                self.effects.play("confetti")
        elif len(g["moves"]) >= GOMOKU_N ** 2:
            g["over"] = "lost"

    def _rps_maybe_reveal(self, gid: str, g: dict, peer: str) -> None:
        """双方都已出拳(交了承诺)才揭晓,谁也没法看了对方再出。"""
        if g.get("my_h") and g.get("their_h") and not g.get("revealed"):
            g["revealed"] = True
            self.core.send_event("dm", peer, "g_reveal", {"gid": gid, "c": g["mine"], "n": g["nonce"]})

    def _ev_game(self, conv: Conv, d: dict, name: str, data: dict) -> None:
        gid = data.get("gid")
        if conv.kind != "dm" or not isinstance(gid, str):
            return
        m = next((x for x in conv.messages if x.card and x.card.get("gid") == gid), None)
        if m is None:
            return
        g = self._game_for(m)
        me = self.me.get("id")
        if name == "g_move" and g["game"] == "gomoku" and not g.get("over"):
            n, x, y = data.get("n"), data.get("x"), data.get("y")
            if not all(type(v) is int for v in (n, x, y)) or n != len(g["moves"]):
                return
            if not (0 <= x < GOMOKU_N and 0 <= y < GOMOKU_N) or (x, y) in [tuple(v) for v in g["moves"]]:
                return
            their_black = g.get("black") != me
            if (n % 2 == 0) != their_black:                 # 不是对方的回合
                return
            g["moves"].append((x, y))
            self._gomoku_check(g, mine_moved=False)
            if not g.get("over") and conv.key != self.current_key:
                conv.unread += 1
        elif name == "g_resign" and not g.get("over"):
            g["over"] = "resign_them"
            self.stats["wins"] += 1
        elif name == "g_commit" and g["game"] == "rps" and not g.get("their_h"):
            h = data.get("h")
            if isinstance(h, str) and len(h) == 64:
                g["their_h"] = h
                self._rps_maybe_reveal(gid, g, conv.target)
        elif name == "g_reveal" and g["game"] == "rps" and g.get("their_h") and not g.get("theirs"):
            c, n = data.get("c"), data.get("n")
            if c in RPS and isinstance(n, str) and rps_hash(gid, c, n) == g["their_h"]:
                g["theirs"] = c
                if g.get("mine"):
                    r = rps_result(g["mine"], c)
                    if r == "win":
                        self.stats["wins"] += 1
                    elif r == "lose":
                        self.stats["losses"] += 1
        self._hist_dirty = True
        self._update_card(m.mid)
        self.conv_list.viewport().update()

    # ---------------------------------------------------------------- 一起画
    def start_board(self) -> None:
        conv = self._can_send()
        if conv is None:
            return
        bid = uuid.uuid4().hex
        self.boards[bid] = {"conv": conv.key, "title": "一起画", "strokes": {}, "people": set()}
        m = self._send_card(conv, {"type": "board", "bid": bid, "title": f"{self.me.get('nick', '')} 的画板"})
        if m is not None:
            self.open_board(m)

    def _board_for(self, m: Msg) -> dict:
        bid = m.card.get("bid")
        b = self.boards.get(bid)
        if b is None:
            conv = self._conv_of(m)
            b = {"conv": conv.key if conv else "", "title": str(m.card.get("title", "一起画")), "strokes": {},
                 "people": set()}
            self.boards[bid] = b
        return b

    def board_state(self, m: Msg) -> dict:
        b = self._board_for(m)
        return {"strokes": len(b["strokes"]), "people": len(b["people"]) + (1 if m.card.get("bid") in self.whiteboards else 0)}

    def open_board(self, m: Msg) -> None:
        bid = m.card.get("bid")
        b = self._board_for(m)
        conv = self.convs.get(b["conv"])
        if conv is None:
            return
        wb = self.whiteboards.get(bid)
        if wb is not None:
            wb.show()
            wb.raise_()
            return
        wb = Whiteboard(self, b["title"], b["strokes"])
        scope, target = self.scope_target(conv)
        wb.stroke.connect(lambda sid, c, w, pts, end: self.core.send_event(
            scope, target, "b_stroke", {"bid": bid, "sid": sid, "c": c, "w": w, "pts": pts, "end": end}))
        wb.undo.connect(lambda sid: self.core.send_event(scope, target, "b_undo", {"bid": bid, "sid": sid}))
        wb.clear_all.connect(lambda: self.core.send_event(scope, target, "b_clear", {"bid": bid}))
        wb.closed.connect(lambda: self._board_closed(bid, scope, target))
        self.whiteboards[bid] = wb
        wb.set_people(len(b["people"]) + 1)
        wb.show()
        self.core.send_event(scope, target, "b_join", {"bid": bid})
        if not b["strokes"]:
            self.core.send_event(scope, target, "b_sync_req", {"bid": bid})
        self._update_card(m.mid)

    def _board_closed(self, bid: str, scope: str, target) -> None:
        self.whiteboards.pop(bid, None)
        self.core.send_event(scope, target, "b_leave", {"bid": bid})
        self._update_board_cards(bid)

    def _ev_board(self, conv: Conv, d: dict, name: str, data: dict) -> None:
        bid = data.get("bid")
        if not isinstance(bid, str):
            return
        m = next((x for x in conv.messages if x.card and x.card.get("bid") == bid), None)
        b = self.boards.get(bid)
        if b is None:
            if m is None:
                return
            b = self._board_for(m)
        if b["conv"] != conv.key:
            return
        pid = d["peer"]
        wb = self.whiteboards.get(bid)
        changed = False
        if name == "b_stroke":
            sid = data.get("sid")
            st = clean_stroke(data)
            if not isinstance(sid, str) or st is None or len(b["strokes"]) > 5000:
                return
            key = f"{pid[:8]}:{sid[:16]}"
            cur = b["strokes"].get(key)
            if cur is None:
                cur = {"c": st["c"], "w": st["w"], "pts": [], "by": pid, "open": True}
                b["strokes"][key] = cur
                changed = True
            cur["pts"] += st["pts"]
            if data.get("end"):
                cur["open"] = False
            b["people"].add(pid)
        elif name == "b_undo":
            sid = data.get("sid")
            if isinstance(sid, str) and b["strokes"].pop(f"{pid[:8]}:{sid[:16]}", None) is not None:
                changed = True
        elif name == "b_clear":
            b["strokes"].clear()
            changed = True
            self._system(conv, f"{d['nick']} 清空了画板")
        elif name == "b_join":
            b["people"].add(pid)
        elif name == "b_leave":
            b["people"].discard(pid)
        elif name == "b_sync_req":
            if b["strokes"]:
                scope, target = self.scope_target(conv)
                items = [{"sid": k, "c": s["c"], "w": s["w"], "pts": s["pts"], "by": s.get("by", "")}
                         for k, s in list(b["strokes"].items())[-3000:] if not s.get("open")]
                self.core.send_event(scope, target, "b_sync", {"bid": bid, "strokes": items}, to=pid)
        elif name == "b_sync":
            for it in (data.get("strokes") or [])[:3000]:
                if not isinstance(it, dict) or not isinstance(it.get("sid"), str):
                    continue
                st = clean_stroke(it)
                if st is not None and it["sid"] not in b["strokes"]:
                    by = it.get("by") if isinstance(it.get("by"), str) else pid
                    b["strokes"][it["sid"][:40]] = {**st, "by": "me" if by == "me" and pid == self.me.get("id") else by,
                                                    "open": False}
                    changed = True
        if wb is not None:
            wb.set_people(len(b["people"]) + 1)
            if changed or name == "b_stroke":
                if name in ("b_undo", "b_clear", "b_sync"):
                    wb.canvas.invalidate()
                else:
                    wb.canvas.update()
        if name in ("b_join", "b_leave", "b_clear", "b_sync") or (name == "b_stroke" and data.get("end")):
            self._update_board_cards(bid)

    def _update_board_cards(self, bid: str) -> None:
        for mid, bub in self.bubbles.items():
            if bub.msg.card and bub.msg.card.get("bid") == bid:
                self._update_card(mid)

    # ---------------------------------------------------------------- 卡片分发
    def card_state(self, m: Msg) -> dict:
        t = (m.card or {}).get("type")
        fresh = m.mid in self.fresh_cards
        self.fresh_cards.discard(m.mid)
        if t == "poll":
            return self.poll_state(m)
        if t == "game":
            return self.game_state(m)
        if t == "board":
            return self.board_state(m)
        return {"fresh": fresh}

    def on_card_action(self, m: Msg, action: str, data) -> None:
        t = (m.card or {}).get("type")
        if t == "throw" and action == "replay":
            self.replay_throw(m)
            return
        if t == "poll" and action == "vote":
            self.vote(m, data)
        elif t == "game":
            self.game_action(m, action, data)
        elif t == "board" and action == "open":
            self.open_board(m)

    def _update_card(self, mid: str) -> None:
        b = self.bubbles.get(mid)
        if b is not None and b.card_w is not None:
            b.card_w.update_state(self.card_state(b.msg))

    # ---------------------------------------------------------------- 聊天记录里的游戏和投票
    def games_history(self, mids: set) -> dict:
        games = {}
        for gid, g in self.games.items():
            if g.get("game") == "gomoku":
                games[gid] = {k: g.get(k) for k in ("game", "peer", "black", "moves", "over", "line")}
            else:
                games[gid] = {k: g.get(k) for k in ("game", "peer", "mine", "theirs", "over")}
        votes = {pid: v for pid, v in self.votes.items() if pid in mids}
        return {"games": games, "votes": votes}

    def restore_games_history(self, h: dict) -> None:
        for gid, g in (h.get("games") or {}).items():
            if isinstance(g, dict) and isinstance(gid, str):
                g = dict(g)
                g["moves"] = [tuple(v) for v in (g.get("moves") or []) if isinstance(v, list) and len(v) == 2]
                if g.get("game") == "rps" and not (g.get("mine") and g.get("theirs")):
                    g["over"] = "lost"                       # 猜拳没出完的局:重启后作废
                elif g.get("game") == "gomoku" and not g.get("over"):
                    pass
                self.games[gid] = g
        for poll, v in (h.get("votes") or {}).items():
            if isinstance(v, dict):
                self.votes[poll] = {k: [i for i in c if type(i) is int] for k, c in v.items() if isinstance(c, list)}
