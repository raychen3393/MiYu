"""
密语 3.1 · 宠物每日签到、萌宠成长通行证与「接零食大作战」小游戏。
低等级玩家也能通过每日签到、日常聊天与小游戏轻松获得限定服装、特殊动作与大量经验。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QTextOption
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .dialogs import Dialog
from .fun import ACC_BY_ID, PetGrowth, SPECIAL_TRICK_BY_ID, TypingPet, _today
from .theme import T, is_dark
from .ui import button, emoji_font, label


# 7 日循环签到奖励:[(天数, 标题, [(奖励类型, 值, 展示名), ...])]
CHECKIN_REWARDS: list[tuple[int, str, list[tuple[str, object, str]]]] = [
    (1, "第 1 天", [("xp", 120, "经验 +120"), ("acc", "beret", "装扮·画家贝雷帽")]),
    (2, "第 2 天", [("ticket", 2, "扭蛋券 ×2"), ("xp", 100, "经验 +100")]),
    (3, "第 3 天", [("trick", "backflip", "特殊动作·后空翻"), ("xp", 150, "经验 +150")]),
    (4, "第 4 天", [("acc", "pixel_shades", "限定·像素墨镜"), ("ticket", 1, "扭蛋券 ×1")]),
    (5, "第 5 天", [("ticket", 3, "扭蛋券 ×3"), ("xp", 220, "经验 +220")]),
    (6, "第 6 天", [("trick", "moonwalk", "特殊动作·太空步"), ("xp", 200, "经验 +200")]),
    (7, "第 7 天", [("acc", "king_robe", "限定·星穹披风"), ("ticket", 5, "扭蛋券 ×5"), ("xp", 350, "经验 +350")]),
]

# 15 阶免费萌宠成长通行证:[(阶数, 所需积分, 奖励类型, 值, 展示名)]
PASS_TIERS: list[tuple[int, int, str, object, str]] = [
    (1, 30, "xp", 120, "元气经验包 (+120 XP)"),
    (2, 70, "acc", "coffee", "装扮 · 冰美式"),
    (3, 115, "ticket", 2, "扭蛋券 ×2"),
    (4, 165, "trick", "backflip", "特殊动作 · 后空翻"),
    (5, 220, "acc", "gamepad", "装扮 · 复古掌机"),
    (6, 280, "coat", "siamese", "毛色基因 · 暹罗重点色"),
    (7, 345, "ticket", 3, "扭蛋券 ×3"),
    (8, 415, "acc", "pixel_shades", "通行证限定 · 像素墨镜"),
    (9, 490, "eyes", "hetero", "稀有瞳色 · 鸳鸯异瞳"),
    (10, 570, "trick", "moonwalk", "特殊动作 · 太空步"),
    (11, 655, "acc", "guitar", "装扮 · 迷你吉他"),
    (12, 745, "room", "onsen", "2.5D 小窝 · 柚子温泉"),
    (13, 840, "ticket", 4, "扭蛋券 ×4"),
    (14, 940, "trick", "rainbow", "特殊动作 · 吐彩虹"),
    (15, 1050, "acc", "king_robe", "终极限定 · 星穹披风"),
]


def _grant_reward(g: PetGrowth, kind: str, val: object) -> tuple[str, int]:
    """发放单个奖励,返回 (获得说明, 升了几级)。"""
    before = g.level
    if kind == "xp":
        g.xp += int(val)
        desc = f"+{int(val)} 经验"
    elif kind == "ticket":
        g.tickets += int(val)
        desc = f"扭蛋券 ×{int(val)}"
    elif kind == "acc":
        aid = str(val)
        key = f"acc:{aid}"
        name = ACC_BY_ID[aid][1] if aid in ACC_BY_ID else aid
        if key in g.owned:
            g.xp += 120
            desc = f"{name}(已拥有→+120经验)"
        else:
            g.owned.add(key)
            desc = f"装扮「{name}」"
    elif kind == "trick":
        tid = str(val)
        key = f"trick:{tid}"
        name = SPECIAL_TRICK_BY_ID[tid][1] if tid in SPECIAL_TRICK_BY_ID else tid
        if key in g.owned:
            g.xp += 120
            desc = f"动作「{name}」(已拥有→+120经验)"
        else:
            g.owned.add(key)
            desc = f"特殊动作「{name}」"
    elif kind in ("coat", "eyes", "room"):
        key = f"{kind}:{val}"
        if key in g.owned:
            g.xp += 120
            desc = f"{val}(已拥有→+120经验)"
        else:
            g.owned.add(key)
            desc = f"解锁 {val}"
    else:
        desc = ""
    g.check_badges()
    return desc, g.level - before


def can_checkin(g: PetGrowth, today: str | None = None) -> bool:
    return g.checkin_last != (today or _today())


def do_checkin(g: PetGrowth, today: str | None = None) -> tuple[int, list[str], int] | None:
    """每日签到:返回 (第几天 1~7, 奖励文本列表, 升了几级);今天已签过返回 None。"""
    today = today or _today()
    if g.checkin_last == today:
        return None
    day = (g.checkin_days % 7) + 1
    g.checkin_days = day
    g.checkin_last = today
    g.pass_pts += 35                               # 签到自带 +35 通行证活跃分
    _, _, items = CHECKIN_REWARDS[day - 1]
    got: list[str] = []
    ups = 0
    for kind, val, _label in items:
        desc, lv_up = _grant_reward(g, kind, val)
        if desc:
            got.append(desc)
        ups += lv_up
    return day, got, ups


def pass_tier_of(pts: int) -> int:
    tier = 0
    for t, need, *_ in PASS_TIERS:
        if pts >= need:
            tier = t
    return tier


def claim_pass_tier(g: PetGrowth, tier: int) -> tuple[str, int] | None:
    """领取某一阶通行证奖励,返回 (奖励描述, 升了几级) 或 None。"""
    item = next((x for x in PASS_TIERS if x[0] == tier), None)
    if item is None or g.pass_pts < item[1] or tier in g.pass_claimed:
        return None
    g.pass_claimed.add(tier)
    return _grant_reward(g, item[2], item[3])


def claim_all_pass(g: PetGrowth) -> tuple[list[str], int]:
    got: list[str] = []
    ups = 0
    for tier, need, *_ in PASS_TIERS:
        if g.pass_pts >= need and tier not in g.pass_claimed:
            res = claim_pass_tier(g, tier)
            if res:
                got.append(res[0])
                ups += res[1]
    return got, ups


class PassDialog(Dialog):
    """每日签到 + 萌宠成长通行证窗口。"""

    def __init__(self, win) -> None:
        super().__init__(win, "每日签到与萌宠通行证")
        self.win = win
        self.g: PetGrowth = win.pet_growth
        self.setFixedWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label("🎁 每日签到 & 萌宠成长通行证", "dialogTitle"))
        head.addStretch(1)
        self.pts_lab = label("", "hint")
        head.addWidget(self.pts_lab)
        lay.addLayout(head)

        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self.tab_btns: list[QPushButton] = []
        self.stack = QStackedWidget(self)
        for i, title in enumerate(("📅 7 日循环签到", "🎫 15 阶成长通行证")):
            b = QPushButton(title, self)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.show_tab(idx))
            tabs.addWidget(b)
            self.tab_btns.append(b)
        tabs.addStretch(1)
        lay.addLayout(tabs)

        self.stack.addWidget(self._build_checkin_page())
        self.stack.addWidget(self._build_pass_page())
        lay.addWidget(self.stack, 1)

        self.msg_lab = label("打字、发消息、摸宠物、喂食和玩接零食小游戏都能涨通行证积分!", "faint", wrap=True)
        lay.addWidget(self.msg_lab)

        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("完成", "primary", self.accept, 90))
        lay.addLayout(foot)
        self.show_tab(0)
        self.refresh()

    def _build_checkin_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.day_cards: list[tuple[QFrame, object]] = []
        for idx, (day, title, rewards) in enumerate(CHECKIN_REWARDS):
            card = QFrame(page)
            card.setObjectName("plainCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 8, 10, 8)
            cl.setSpacing(3)
            cl.addWidget(label(title, "cardTitle"))
            cl.addWidget(label("\n".join(r[2] for r in rewards), "fileSub", wrap=True))
            st = label("", "faint")
            cl.addWidget(st)
            row, col = (0, idx) if idx < 4 else (1, idx - 4)
            colspan = 2 if idx == 6 else 1
            grid.addWidget(card, row, col, 1, colspan)
            self.day_cards.append((card, st))
        lay.addLayout(grid)

        row = QHBoxLayout()
        self.ci_btn = button("✨ 立即签到领取今日好礼 (+35 通行证积分)", "primary", self._on_checkin)
        self.ci_btn.setMinimumHeight(40)
        row.addWidget(self.ci_btn)
        lay.addLayout(row)
        return page

    def _build_pass_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self.pass_bar = QProgressBar(page)
        self.pass_bar.setObjectName("fileProgress")
        self.pass_bar.setRange(0, PASS_TIERS[-1][1])
        self.pass_bar.setTextVisible(False)
        top.addWidget(self.pass_bar, 1)
        self.claim_all_btn = button("一键领取全部", "primary", self._on_claim_all, 120)
        top.addWidget(self.claim_all_btn)
        lay.addLayout(top)

        area = QScrollArea(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setFixedHeight(285)
        inner = QWidget(area)
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 2, 4, 2)
        il.setSpacing(6)
        self.tier_btns: dict[int, QPushButton] = {}
        for tier, need, _k, _v, desc in PASS_TIERS:
            card = QFrame(inner)
            card.setObjectName("plainCard")
            rl = QHBoxLayout(card)
            rl.setContentsMargins(12, 7, 10, 7)
            rl.setSpacing(8)
            rl.addWidget(label(f"Tier {tier:02d}", "cardTitle"))
            rl.addWidget(label(f"({need} 分)  {desc}", "hint"), 1)
            btn = button("领取", "", lambda _=False, t=tier: self._on_claim(t), 74)
            btn.setMinimumHeight(28)
            rl.addWidget(btn)
            il.addWidget(card)
            self.tier_btns[tier] = btn
        il.addStretch(1)
        area.setWidget(inner)
        lay.addWidget(area)
        return page

    def show_tab(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.tab_btns):
            b.setChecked(i == idx)

    def _on_checkin(self) -> None:
        res = do_checkin(self.g)
        if res is None:
            return
        day, got, ups = res
        self.msg_lab.setText(f"🎉 第 {day} 天签到成功!获得:{'、'.join(got)}")
        if ups and hasattr(self.win, "_pet_level_up"):
            self.win._pet_level_up()
        if hasattr(self.win, "pet"):
            self.win.pet.celebrate()
            self.win.pet.say("签到领礼物啦~ 🎁", 2.6)
        self.refresh()

    def _on_claim(self, tier: int) -> None:
        res = claim_pass_tier(self.g, tier)
        if res is None:
            return
        desc, ups = res
        self.msg_lab.setText(f"✨ 领取 Tier {tier} 奖励:{desc}")
        if ups and hasattr(self.win, "_pet_level_up"):
            self.win._pet_level_up()
        self.refresh()

    def _on_claim_all(self) -> None:
        got, ups = claim_all_pass(self.g)
        if not got:
            return
        self.msg_lab.setText("🎉 已全部领取:" + "、".join(got[:6]) + ("…" if len(got) > 6 else ""))
        if ups and hasattr(self.win, "_pet_level_up"):
            self.win._pet_level_up()
        self.refresh()

    def refresh(self) -> None:
        g = self.g
        cur_t = pass_tier_of(g.pass_pts)
        self.pts_lab.setText(f"通行证 Tier.{cur_t}  ·  积分 {g.pass_pts}")
        self.pass_bar.setValue(min(PASS_TIERS[-1][1], g.pass_pts))
        can = can_checkin(g)
        self.ci_btn.setEnabled(can)
        self.ci_btn.setText("✨ 立即签到领取今日好礼 (+35 通行证积分)" if can else "✅ 今日已签到,明天再来继续领!")
        done_days = g.checkin_days if not can else (0 if g.checkin_days >= 7 else g.checkin_days)
        for idx, (_card, st) in enumerate(self.day_cards, start=1):
            if idx <= done_days:
                st.setText("✅ 已领取")
            elif idx == done_days + 1 and can:
                st.setText("👉 今日可领")
            else:
                st.setText("待解锁")
        claimable = 0
        for tier, need, *_ in PASS_TIERS:
            btn = self.tier_btns[tier]
            if tier in g.pass_claimed:
                btn.setText("已领")
                btn.setEnabled(False)
            elif g.pass_pts >= need:
                btn.setText("领取")
                btn.setEnabled(True)
                claimable += 1
            else:
                btn.setText("未达成")
                btn.setEnabled(False)
        self.claim_all_btn.setEnabled(claimable > 0)
        self.claim_all_btn.setText(f"一键领取 ({claimable})" if claimable else "暂无可领")


class _SnackStage(QWidget):
    """「接零食大作战」25 秒轻互动游戏画布。"""
    W, H = 480, 340
    ITEMS = [
        ("🐟", 10, 125.0, False),
        ("🍙", 15, 140.0, False),
        ("🍓", 25, 165.0, False),
        ("⭐", 40, 195.0, False),
        ("💣", -15, 175.0, True),
    ]

    def __init__(self, parent, growth: PetGrowth, species: str, on_finish) -> None:
        super().__init__(parent)
        self.growth = growth
        self.species = species
        self.on_finish = on_finish
        self.setFixedSize(self.W, self.H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pet = TypingPet(None)
        self.pet.bare = True
        self.pet.centered = True
        self.pet.visitor = True
        self.pet.growth = growth
        self.pet.set_species(species)
        self.pet.resize(TypingPet.W, TypingPet.H)

        self.px = self.W / 2.0
        self.target_x = self.px
        self.keys: set[int] = set()
        self.running = False
        self.score = 0
        self.combo = 0
        self.left_s = 25.0
        self.drops: list[dict] = []
        self.pops: list[dict] = []
        self._spawn_cd = 0.0
        self._last = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._step)

    def start_game(self) -> None:
        self.score = 0
        self.combo = 0
        self.left_s = 25.0
        self.drops.clear()
        self.pops.clear()
        self.px = self.target_x = self.W / 2.0
        self.running = True
        self._last = time.monotonic()
        self.timer.start()
        self.setFocus()
        self.update()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position() if hasattr(e, "position") else e.pos()
        self.target_x = max(42.0, min(self.W - 42.0, float(pos.x())))

    def keyPressEvent(self, e) -> None:
        self.keys.add(e.key())

    def keyReleaseEvent(self, e) -> None:
        self.keys.discard(e.key())

    def _step(self) -> None:
        now = time.monotonic()
        dt = min(0.05, max(0.005, now - self._last))
        self._last = now
        if not self.running:
            return
        self.left_s -= dt
        if self.left_s <= 0:
            self.left_s = 0.0
            self.running = False
            self.timer.stop()
            self.update()
            self.on_finish(self.score)
            return

        if Qt.Key.Key_Left in self.keys or Qt.Key.Key_A in self.keys:
            self.target_x = max(42.0, self.target_x - 360 * dt)
        if Qt.Key.Key_Right in self.keys or Qt.Key.Key_D in self.keys:
            self.target_x = min(self.W - 42.0, self.target_x + 360 * dt)
        dx = self.target_x - self.px
        self.px += dx * min(1.0, dt * 16.0)
        self.pet.pose3d.yaw = max(-0.42, min(0.42, dx * 0.012))
        self.pet.pose3d.step(now, sleeping=False)

        self._spawn_cd -= dt
        if self._spawn_cd <= 0:
            self._spawn_cd = random.uniform(0.32, 0.58)
            emo, pts, spd, bomb = random.choices(self.ITEMS, weights=(36, 26, 18, 8, 12))[0]
            self.drops.append({"e": emo, "pts": pts, "v": spd * random.uniform(0.9, 1.15),
                               "bomb": bomb, "x": random.uniform(32, self.W - 32), "y": -16.0})

        kept = []
        catch_y = self.H - 54
        for it in self.drops:
            it["y"] += it["v"] * dt
            if abs(it["x"] - self.px) < 36 and catch_y - 24 <= it["y"] <= catch_y + 22:
                if it["bomb"]:
                    self.score = max(0, self.score + it["pts"])
                    self.combo = 0
                    self.pops.append({"t": "💥 -15", "x": it["x"], "y": it["y"], "life": 0.9, "col": "#FF6B6B"})
                    self.pet.pose3d.impulse(-0.22)
                else:
                    self.combo += 1
                    bonus = it["pts"] + (5 if self.combo >= 5 else 0)
                    self.score += bonus
                    self.pops.append({"t": f"+{bonus}", "x": it["x"], "y": it["y"], "life": 0.85, "col": "#FFD43B"})
                    self.pet.pose3d.impulse(0.20)
                continue
            if it["y"] < self.H + 20:
                kept.append(it)
        self.drops = kept
        for pop in self.pops:
            pop["y"] -= 34 * dt
            pop["life"] -= dt
        self.pops = [pop for pop in self.pops if pop["life"] > 0]
        self.update()

    def _paint_drop(self, p: QPainter, it: dict) -> None:
        """手绘 2.5D 风格零食与炸弹(不依赖系统 Emoji 字体,浅色/深色主题都清晰可爱)。"""
        x, y, emo = it["x"], it["y"], it["e"]
        p.save()
        p.translate(x, y)
        # 柔和底晕
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 107, 107, 70) if it["bomb"] else QColor(255, 224, 102, 75))
        p.drawEllipse(QPointF(0, 0), 17, 17)
        out = QPen(QColor("#4A3B32"), 1.5)
        p.setPen(out)
        if emo == "🐟":                                        # 蓝银色小鱼干
            p.setBrush(QColor("#74C0FC"))
            p.drawEllipse(QPointF(-2, 0), 10, 6)
            tail = [QPointF(6, 0), QPointF(13, -5.5), QPointF(13, 5.5)]
            p.drawPolygon(tail)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#1D1D1F"))
            p.drawEllipse(QPointF(-6, -1.5), 1.4, 1.4)
        elif emo == "🍙":                                      # 海苔饭团
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(QRectF(-10, -9, 20, 18), 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2B2D42"))
            p.drawRoundedRect(QRectF(-6, 1, 12, 8), 2, 2)
        elif emo == "🍓":                                      # 草莓小蛋糕
            p.setBrush(QColor("#FFF0F6"))
            p.drawRoundedRect(QRectF(-10, -3, 20, 12), 4, 4)
            p.setBrush(QColor("#FF6B8A"))
            p.drawEllipse(QPointF(0, -6), 6.5, 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#51CF66"))
            p.drawEllipse(QPointF(0, -11), 4.5, 2.2)
        elif emo == "⭐":                                      # 金色星星
            p.setBrush(QColor("#FFD43B"))
            pts = []
            for i in range(10):
                a = math.radians(-90 + i * 36)
                r = 12.0 if i % 2 == 0 else 5.4
                pts.append(QPointF(math.cos(a) * r, math.sin(a) * r))
            p.drawPolygon(pts)
        else:                                                  # 炸弹 + 火星引信
            p.setBrush(QColor("#2B2D42"))
            p.drawEllipse(QPointF(0, 2), 10.5, 10.5)
            p.setPen(QPen(QColor("#ADB5BD"), 2.0))
            p.drawLine(QPointF(4, -7), QPointF(9, -13))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FF6B6B"))
            p.drawEllipse(QPointF(10, -14), 3.6, 3.6)
            p.setBrush(QColor("#FFD43B"))
            p.drawEllipse(QPointF(10, -14), 1.8, 1.8)
        p.restore()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bg = QLinearGradient(0, 0, 0, self.H)
        if is_dark():
            bg.setColorAt(0, QColor("#1B1D30"))
            bg.setColorAt(1, QColor("#26223D"))
        else:
            bg.setColorAt(0, QColor("#E7F5FF"))
            bg.setColorAt(1, QColor("#FFF0F6"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), 16, 16)

        # 地面草坪/桌面
        p.setBrush(QColor(255, 255, 255, 26) if is_dark() else QColor(255, 255, 255, 160))
        p.drawRoundedRect(QRectF(0, self.H - 36, self.W, 36), 12, 12)

        # 掉落零食(矢量绘制,100% 可见)
        for it in self.drops:
            self._paint_drop(p, it)

        # 2.5D 宠物本体
        p.save()
        p.translate(self.px - TypingPet.W / 2, self.H - TypingPet.EDGE - 22)
        self.pet._paint_pet(p, time.monotonic(), "happy" if self.combo >= 3 else "idle")
        p.restore()

        # 飘字得分
        pf = QFont(self.font())
        pf.setPointSizeF(11)
        pf.setBold(True)
        p.setFont(pf)
        for pop in self.pops:
            c = QColor(pop["col"])
            c.setAlphaF(max(0.0, min(1.0, pop["life"])))
            p.setPen(c)
            p.drawText(QRectF(pop["x"] - 32, pop["y"] - 12, 64, 24), pop["t"],
                       QTextOption(Qt.AlignmentFlag.AlignCenter))

        # 顶部 HUD
        hud_f = QFont(self.font())
        hud_f.setPointSizeF(10.5)
        hud_f.setBold(True)
        p.setFont(hud_f)
        p.setPen(QColor("#FFFFFF" if is_dark() else "#1D1D1F"))
        p.drawText(QRectF(14, 10, 220, 24), f"得分:{self.score}   连击:×{self.combo}")
        p.drawText(QRectF(self.W - 140, 10, 126, 24), f"⏱ {self.left_s:0.1f}s",
                   QTextOption(Qt.AlignmentFlag.AlignRight))
        p.end()


class SnackCatchDialog(Dialog):
    """宠物轻互动小游戏:移动宠物接住掉落的零食,赢取经验、心情与通行证积分!"""

    def __init__(self, win) -> None:
        super().__init__(win, "接零食大作战")
        self.win = win
        self.g: PetGrowth = win.pet_growth
        self.setFixedWidth(530)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("🎮 接零食大作战", "dialogTitle", center=True))
        self.sub = label(f"移动鼠标或按 A / D 控制 {self.g.name} 接住零食,躲开 💣!历史最高:{self.g.snack_best} 分",
                         "hint", center=True)
        lay.addWidget(self.sub)

        self.stage = _SnackStage(self, self.g, win.fun.get("pet") or "cat", self._on_finish)
        lay.addWidget(self.stage, 0, Qt.AlignmentFlag.AlignHCenter)

        row = QHBoxLayout()
        self.start_btn = button("开始游戏", "primary", self._start, 110)
        row.addWidget(self.start_btn)
        row.addStretch(1)
        row.addWidget(button("关闭", "", self.accept, 84))
        lay.addLayout(row)

    def closeEvent(self, e) -> None:
        self.stage.running = False
        self.stage.timer.stop()
        super().closeEvent(e)

    def reject(self) -> None:
        self.stage.running = False
        self.stage.timer.stop()
        super().reject()

    def accept(self) -> None:
        self.stage.running = False
        self.stage.timer.stop()
        super().accept()

    def _start(self) -> None:
        self.start_btn.setEnabled(False)
        self.start_btn.setText("进行中…")
        self.stage.start_game()

    def _on_finish(self, score: int) -> None:
        gain, ups = self.g.record_snack_score(score)
        self.sub.setText(f"本局得分 {score} 分!获得 +{gain} 经验、心情 +15,历史最高:{self.g.snack_best} 分")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("再来一局")
        if ups and hasattr(self.win, "_pet_level_up"):
            self.win._pet_level_up()
        if hasattr(self.win, "pet"):
            self.win.pet.celebrate()
            self.win.pet.say(f"接了 {score} 分零食,超满足~", 2.8)
