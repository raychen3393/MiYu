"""
密语 3.8 · 「🎮 萌宠游乐厅」统一小游戏大厅
  · 集中展示全部 5 款 2.5D 萌宠单人小游戏（保卫萝卜塔防 / 植物大战僵尸塔防 / 合成大萌宠 / 接零食 / 云端跳跳乐）
  · 实时展示每款游戏的个人最高分、局域网当前榜首与「今日首胜双倍福利」状态
  · 底部一键直达多人派对游戏厅（五子棋大厅 / 谁是坏鸭 / 谁是卧底）、宠物全榜与签到通行证
"""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QTextOption
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from .dialogs import Dialog
from .fun import PetGrowth
from .pet3d import clay_brush, contour_pen
from .sound import play_game_sfx
from .theme import T, is_dark
from .ui import button, label

ARCADE_GAMES: list[dict] = [
    {"key": "td", "ico": "🥕", "title": "萌宠保卫战", "badge": "NEW", "col": "#FF922B",
     "sub": "保卫萝卜风 2.5D 路径塔防 · 3 图 / 5 炮塔 / 拆宝箱集火"},
    {"key": "pvz", "ico": "🌻", "title": "萌宠大战捣蛋怪", "badge": "NEW", "col": "#40C057",
     "sub": "植物大战僵尸风 5 路草坪 · 收阳光 / 小推车 / 樱桃核爆"},
    {"key": "merge", "ico": "🍉", "title": "合成大萌宠", "badge": "UP", "col": "#FA5252",
     "sub": "2.5D 物理合成大西瓜 · 3 种解压道具 + 连锁 COMBO 倍率"},
    {"key": "snack", "ico": "🐟", "title": "接零食大作战", "badge": "UP", "col": "#339AF0",
     "sub": "黄金零食雨冲刺 · ⏳续时沙漏 + 🎂彩虹蛋糕狂热"},
    {"key": "cloud", "ico": "☁️", "title": "云端跳跳乐", "badge": "UP", "col": "#7950F2",
     "sub": "🪽喷气背包冲天 · 💨碎裂云 + 晴空到星云动态变天"},
]


class _ArcadeCard(QWidget):
    """2.5D 液态玻璃游乐厅游戏卡片。"""
    clicked = Signal(str)

    def __init__(self, spec: dict, my_best: str, lan_top: str, parent=None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.my_best = my_best
        self.lan_top = lan_top
        self._hover = False
        self.setFixedHeight(114)
        self.setMinimumWidth(298)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_stats(self, my_best: str, lan_top: str) -> None:
        self.my_best = my_best
        self.lan_top = lan_top
        self.update()

    def enterEvent(self, _e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.spec["key"])

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        dark = is_dark()
        accent = QColor(self.spec["col"])

        bg = QLinearGradient(0, 0, w, h)
        if dark:
            bg.setColorAt(0, QColor(38, 44, 66, 235 if self._hover else 205))
            bg.setColorAt(1, QColor(28, 32, 48, 235 if self._hover else 205))
        else:
            bg.setColorAt(0, QColor(255, 255, 255, 248 if self._hover else 228))
            bg.setColorAt(1, QColor(246, 249, 255, 245 if self._hover else 220))
        border = accent if self._hover else (QColor(255, 255, 255, 38) if dark else QColor(120, 130, 170, 50))
        p.setPen(QPen(border, 2.0 if self._hover else 1.2))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 16, 16)

        # 左侧 2.5D 黏土徽章球
        p.setPen(contour_pen(accent, 1.4))
        p.setBrush(clay_brush(38, h * 0.5, 24, 24, accent))
        p.drawRoundedRect(QRectF(14, h * 0.5 - 24, 48, 48), 15, 15)
        f_ico = QFont(self.font())
        f_ico.setPixelSize(24)
        p.setFont(f_ico)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(14, h * 0.5 - 24, 48, 48), self.spec["ico"], QTextOption(Qt.AlignmentFlag.AlignCenter))

        # 标题 + NEW/UP 徽标
        ft = QFont(self.font())
        ft.setPixelSize(14)
        ft.setWeight(QFont.Weight.Bold)
        p.setFont(ft)
        p.setPen(QColor("#FFFFFF" if dark else "#1D1D1F"))
        p.drawText(QRectF(72, 12, w - 134, 22), self.spec["title"])

        badge = self.spec.get("badge")
        if badge:
            br = QRectF(w - 56, 12, 44, 19)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawRoundedRect(br, 9, 9)
            fb = QFont(self.font())
            fb.setPixelSize(10)
            fb.setWeight(QFont.Weight.Black)
            p.setFont(fb)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(br, badge, QTextOption(Qt.AlignmentFlag.AlignCenter))

        # 副标题
        fs = QFont(self.font())
        fs.setPixelSize(11)
        p.setFont(fs)
        p.setPen(QColor(T["sub"]))
        opt = QTextOption(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        opt.setWrapMode(QTextOption.WrapMode.WordWrap)
        p.drawText(QRectF(72, 36, w - 84, 34), self.spec["sub"], opt)

        # 底部个人最高分 + 群榜首
        fm = QFont(self.font())
        fm.setPixelSize(11)
        fm.setWeight(QFont.Weight.DemiBold)
        p.setFont(fm)
        p.setPen(accent)
        p.drawText(QRectF(72, h - 25, (w - 84) * 0.58, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                   self.my_best)
        p.setPen(QColor(T["sub"]))
        p.drawText(QRectF(72 + (w - 84) * 0.56, h - 25, (w - 84) * 0.44, 20),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                   self.lan_top)
        p.end()


class ArcadeHubDialog(Dialog):
    """「🎮 萌宠游乐厅」统一小游戏大厅窗口。"""

    def __init__(self, win) -> None:
        super().__init__(win, "萌宠游乐厅")
        self.win = win
        self.g: PetGrowth = win.pet_growth
        self.setFixedWidth(668)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label("🎮 萌宠游乐厅 · 2.5D 全系小游戏", "dialogTitle"))
        head.addStretch(1)
        head.addWidget(button("🏆 宠物全榜", "", lambda: self.win.open_pet_rank(), 98))
        head.addWidget(button("🎁 签到/通行证", "", lambda: self._open_after(self.win.show_pet_pass), 112))
        lay.addLayout(head)

        self.bonus_bar = QFrame(self)
        self.bonus_bar.setObjectName("plainCard")
        bl = QHBoxLayout(self.bonus_bar)
        bl.setContentsMargins(14, 8, 14, 8)
        self.bonus_lab = label("", "cardTitle", wrap=True)
        bl.addWidget(self.bonus_lab, 1)
        lay.addWidget(self.bonus_bar)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.cards: dict[str, _ArcadeCard] = {}
        for idx, spec in enumerate(ARCADE_GAMES):
            c = _ArcadeCard(spec, "", "", self)
            c.clicked.connect(self._launch)
            self.cards[spec["key"]] = c
            if idx == len(ARCADE_GAMES) - 1 and len(ARCADE_GAMES) % 2 == 1:
                grid.addWidget(c, idx // 2, 0, 1, 2)
            else:
                grid.addWidget(c, idx // 2, idx % 2)
        lay.addLayout(grid)

        party_row = QHBoxLayout()
        party_row.setSpacing(8)
        party_row.addWidget(label("多人派对厅：", "section"))
        party_row.addWidget(button("🏆 五子棋大厅", "", lambda: self._open_after(self.win.open_gomoku), 112))
        party_row.addWidget(button("🦆 谁是坏鸭", "", lambda: self._open_after(self.win.open_duck), 102))
        party_row.addWidget(button("🕵 谁是卧底", "", lambda: self._open_after(self.win.open_spy), 102))
        party_row.addStretch(1)
        party_row.addWidget(button("关闭", "primary", self.accept, 78))
        lay.addLayout(party_row)

        self.refresh()

    def _lan_leader(self, kind: str) -> str:
        try:
            conv = getattr(self.win, "current", None)
            if conv is None or conv.kind not in ("lobby", "room"):
                conv = self.win.convs.get("lobby")
            if conv is None or not hasattr(self.win, "pr_rows"):
                return "群榜待开荒"
            rows = self.win.pr_rows(conv, kind)
            if not rows:
                return "群榜虚位以待"
            top = rows[0]
            fk = {"td": "tb", "pvz": "pb", "merge": "mb", "snack": "sb", "cloud": "cb"}[kind]
            return f"👑 {top['nick'][:6]} {top.get(fk, 0):,}"
        except Exception:
            return ""

    def refresh(self) -> None:
        g = self.g
        today = time.strftime("%Y-%m-%d")
        if getattr(g, "game_first_day", "") == today:
            self.bonus_lab.setText("✅ 今日首胜双倍福利已领取！继续冲分可赚取每日宠物经验、心情与局域网榜一荣耀~")
        else:
            self.bonus_lab.setText("🌟 今日首胜双倍待领取：任玩一局游乐厅小游戏即额外送 +30 通行证积分 & +25 宠物经验！")
        bests = {
            "td": f"最高 {g.td_best:,} 分 ({g.td_waves}波)" if g.td_best else "尚未开战",
            "pvz": f"最高 {g.pvz_best:,} 分 ({g.pvz_waves}波)" if g.pvz_best else "尚未开战",
            "merge": f"最高 {g.merge_best:,} 分" if g.merge_best else "尚未开战",
            "snack": f"最高 {g.snack_best:,} 分" if g.snack_best else "尚未开战",
            "cloud": f"最高 {g.cloud_best:,} 分" if g.cloud_best else "尚未开战",
        }
        for key, card in self.cards.items():
            card.set_stats(bests[key], self._lan_leader(key))

    def _launch(self, key: str) -> None:
        play_game_sfx(self.win, "click", 0.7)
        if hasattr(self.win, "launch_arcade_game"):
            self.win.launch_arcade_game(key)
        self.refresh()

    def _open_after(self, fn) -> None:
        play_game_sfx(self.win, "click", 0.65)
        if callable(fn):
            fn()
        self.refresh()
