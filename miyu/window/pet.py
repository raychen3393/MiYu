"""
密语 · 宠物:摸摸和成就、串门、小剧场、日记、成就墙、抽卡、朋友和合照、气泡皮肤 / 打字特效 / 音效主题。
"""
from __future__ import annotations

import math
import random
import threading
import time

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTextOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .. import imaging, sound as S, theme
from ..dialogs import Dialog, TextDialog, info
from ..fun import (
    ACC_BY_ID, BADGES, FRIEND_PHOTO, FX_THEMES, GACHA_PITY, GACHA_POOL, PET_MAX_LEVEL, PetGrowth, SPECIES, TypingPet,
    friend_level, xp_for_level,
)
from ..pet3d import COAT_BY_ID, EYE_BY_ID, clay_brush, contour_pen
from ..ui import button, label, make_menu
from ..widgets import Conv


VISIT_SECS = 90                   # 宠物串门待多久


class PetHit(QWidget):
    """盖在宠物身体上的透明小区域:只有这里能点,不挡住聊天内容。左键摸摸 / 拖拽捏脸,右键喂食 / 玩耍 / 换装。"""

    def __init__(self, parent, on_click, on_menu=None,
                 tip: str = "左键摸摸它 · 按住拖拽可 Q 弹捏脸 · 右键喂食、玩耍、换装",
                 pet_getter=None) -> None:
        super().__init__(parent)
        self.on_click = on_click
        self.on_menu = on_menu
        self.pet_getter = pet_getter
        self._down_pos = None
        self._dragged = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip)

    def _pet(self):
        return self.pet_getter() if self.pet_getter is not None else None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            pos = e.position() if hasattr(e, "position") else e.pos()
            self._down_pos = QPointF(pos.x(), pos.y())
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:
        if self._down_pos is None:
            return
        pos = e.position() if hasattr(e, "position") else e.pos()
        dx = pos.x() - self._down_pos.x()
        dy = pos.y() - self._down_pos.y()
        if math.hypot(dx, dy) > 4.0:
            pet = self._pet()
            if pet is not None and hasattr(pet, "pose3d"):
                if not self._dragged:
                    pet.pose3d.start_pinch()
                self._dragged = True
                pet.pose3d.move_pinch(dx, dy)
                pet._speed(16)
                pet.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            pet = self._pet()
            if self._dragged and pet is not None and hasattr(pet, "pose3d"):
                dist = pet.pose3d.end_pinch()
                if dist > 14.0:
                    pet.say(random.choice(("唔…脸要被捏扁啦!", "Q 弹年糕脸~", "轻点捏嘛 > <")), 2.2)
                pet.update()
            else:
                self.on_click()
            self._down_pos = None
            self._dragged = False

    def contextMenuEvent(self, e) -> None:
        if self.on_menu is not None:
            self.on_menu(e.globalPos())


RARITY_COLOR = {"N": "#8E8E93", "R": "#0A84FF", "SR": "#BF5AF2", "SSR": "#FF9F0A"}
SKIT_SECS = 8.0
SKITS = {
    "note": ("传纸条", [(0.6, "a", "嘘…有张小纸条给你"), (1.6, "prop", "✉️", "a2b"), (2.9, "b", "收到!让我看看~"),
                      (4.3, "b", "嘻嘻,是秘密!"), (5.6, "a", "不许告诉别人哦")]),
    "fish": ("抢鱼干", [(0.6, "a", "哇,一条小鱼干!"), (1.4, "prop", "🐟", "a2b"), (2.3, "b", "是我的!"),
                      (3.1, "prop", "🐟", "b2a"), (4.0, "a", "明明是我的!"), (5.2, "b", "那…一人一半?"),
                      (6.3, "both", "好耶!")]),
    "dance": ("一起跳舞", [(0.6, "a", "来跳舞吧!"), (1.5, "b", "好呀~"), (2.2, "dance", "🎵"), (3.2, "dance", "🎶"),
                        (4.2, "dance", "🎵"), (5.4, "both", "耶!")]),
}


class WallDialog(Dialog):
    """成就墙:所有称号,拿到的可以佩戴在名字旁边。"""

    def __init__(self, parent, growth: PetGrowth) -> None:
        super().__init__(parent, "成就墙")
        self.growth = growth
        self.setFixedWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(8)
        got = len(growth.badges)
        lay.addWidget(label(f"成就墙  ·  {got} / {len(BADGES)}", "dialogTitle"))
        self.cur = label("", "hint")
        lay.addWidget(self.cur)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 4, 0)
        bl.setSpacing(6)
        self.btns: dict[str, object] = {}
        for bid, title, desc, _ok in BADGES:
            card = QFrame()
            card.setObjectName("plainCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 8, 10, 8)
            col = QVBoxLayout()
            col.setSpacing(1)
            have = bid in growth.badges
            col.addWidget(label(("🏅 " if have else "🔒 ") + title, "cardTitle"))
            col.addWidget(label(desc + (f"  ·  {growth.badges[bid]} 达成" if have else ""), "fileSub"))
            row.addLayout(col, 1)
            if have:
                b = button("", "link", lambda _=False, i=bid: self.wear(i))
                row.addWidget(b)
                self.btns[bid] = b
            bl.addWidget(card)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(box)
        area.setFixedHeight(420)
        lay.addWidget(area)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("完成", "primary", self.accept, 90))
        lay.addLayout(row)
        self.refresh()

    def wear(self, bid: str) -> None:
        self.growth.title = "" if self.growth.title == bid else bid
        self.refresh()

    def refresh(self) -> None:
        t = self.growth.title_text()
        self.cur.setText(f"正在佩戴:「{t}」(别人在群里会看到)" if t else "还没佩戴称号。拿到的称号可以挂在名字旁边。")
        for bid, b in self.btns.items():
            b.setText("取下" if self.growth.title == bid else "佩戴")


class _CapsuleStage(QWidget):
    """3.0 扭蛋机动画舞台:玻璃球舱 + 10 颗滚动 2.5D 彩球 + 旋钮转动 + 稀有度光效破壳爆发。"""
    BALL_COLS = ["#FF6B6B", "#4DABF7", "#FFD43B", "#69DB7C", "#B197FC", "#FF922B", "#F783AC", "#20C997"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(210, 178)
        self._t0 = time.monotonic()
        self._spin_t = -1e9
        self._burst_rarity = ""
        self.timer = QTimer(self)
        self.timer.setInterval(24)
        self.timer.timeout.connect(self._tick)

    def spin(self, rarity: str) -> None:
        self._spin_t = time.monotonic()
        self._burst_rarity = rarity
        self.timer.start()
        self.update()

    def _tick(self) -> None:
        if time.monotonic() - self._spin_t > 1.35:
            self.timer.stop()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = time.monotonic()
        dt = now - self._spin_t
        spinning = 0 <= dt <= 0.52
        burst = 0.52 < dt <= 1.30
        cx, cy = 105.0, 74.0

        # 底座机身(潮玩红白/主题色渐变)
        base_col = QColor(theme.T["accent"])
        body_path = QPainterPath()
        body_path.moveTo(cx - 52, cy + 36)
        body_path.lineTo(cx + 52, cy + 36)
        body_path.lineTo(cx + 60, 168)
        body_path.lineTo(cx - 60, 168)
        body_path.closeSubpath()
        p.setPen(contour_pen(base_col, 1.4))
        p.setBrush(clay_brush(cx, 138, 62, 38, base_col))
        p.drawPath(body_path)

        # 出蛋口小门
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 30, 140))
        p.drawRoundedRect(QRectF(cx - 18, 144, 36, 20), 7, 7)

        # 玻璃球舱内的 3D 扭蛋球
        shake = math.sin(dt * 38) * 9.0 if spinning else math.sin((now - self._t0) * 1.2) * 1.0
        for i in range(9):
            ang = i * 0.72 + (dt * 9.5 if spinning else 0.0)
            bx = cx + math.cos(ang + i) * (28 - (i % 3) * 6) + shake * (1 if i % 2 else -1) * 0.45
            by = cy + 12 + math.sin(ang * 1.3 + i) * 16 - (i % 3) * 4
            col = QColor(self.BALL_COLS[i % len(self.BALL_COLS)])
            p.setPen(contour_pen(col, 1.0))
            p.setBrush(clay_brush(bx, by, 11, 11, col))
            p.drawEllipse(QPointF(bx, by), 10.5, 10.5)

        # 透明高光玻璃罩
        glass = QRadialGradient(QPointF(cx - 18, cy - 20), 66)
        glass.setColorAt(0.0, QColor(255, 255, 255, 115))
        glass.setColorAt(0.65, QColor(200, 225, 255, 32))
        glass.setColorAt(1.0, QColor(255, 255, 255, 68))
        p.setPen(QPen(QColor(255, 255, 255, 165), 2.0))
        p.setBrush(QBrush(glass))
        p.drawEllipse(QPointF(cx, cy), 56, 54)

        # 金属旋转把手
        p.save()
        p.translate(cx, 126)
        p.rotate(dt * 360 if spinning else 0.0)
        p.setPen(contour_pen(QColor("#FFF3BF"), 1.2))
        p.setBrush(clay_brush(0, 0, 14, 14, QColor("#FFD43B")))
        p.drawEllipse(QPointF(0, 0), 13, 13)
        p.setBrush(QColor("#FFF9DB"))
        p.drawRoundedRect(QRectF(-10, -3.2, 20, 6.4), 3, 3)
        p.restore()

        # 扭蛋破壳光环爆发(R 蓝光 / SR 紫电 / SSR 金虹爆闪)
        if burst:
            k = (dt - 0.52) / 0.78
            rc = QColor(RARITY_COLOR.get(self._burst_rarity, "#0A84FF"))
            rc.setAlphaF(max(0.0, 1.0 - k))
            r_ring = 18 + k * 78
            p.setPen(QPen(rc, max(1.5, 6.0 * (1 - k))))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, 150 - k * 42), r_ring, r_ring * 0.75)
            if self._burst_rarity in ("SR", "SSR"):
                for j in range(10 if self._burst_rarity == "SSR" else 6):
                    a = j / (10 if self._burst_rarity == "SSR" else 6) * math.tau + k * 2.2
                    sx = cx + math.cos(a) * (14 + k * 68)
                    sy = 135 - k * 36 + math.sin(a) * (12 + k * 50)
                    scol = QColor.fromHsv((j * 36 + int(k * 180)) % 360, 190, 255) if self._burst_rarity == "SSR" else rc
                    scol.setAlphaF(max(0.0, 1.0 - k))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(scol)
                    p.drawEllipse(QPointF(sx, sy), 4.2 * (1 - k * 0.5), 4.2 * (1 - k * 0.5))
        p.end()


class GachaDialog(Dialog):
    def __init__(self, parent, growth: PetGrowth, on_draw) -> None:
        super().__init__(parent, "潮玩扭蛋机")
        self.win = parent
        self.growth, self.on_draw = growth, on_draw
        self.setFixedWidth(486)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(8)
        lay.addWidget(label("🎰 潮玩扭蛋机", "dialogTitle", center=True))
        self.sub = label("", "hint", center=True)
        lay.addWidget(self.sub)

        stage_row = QHBoxLayout()
        stage_row.setSpacing(10)
        self.machine = _CapsuleStage(self)
        stage_row.addWidget(self.machine)

        self.card = QFrame()
        self.card.setObjectName("plainCard")
        self.card.setMinimumHeight(178)
        from ..island import HoloOverlay
        self._card_holo = HoloOverlay(self.card, radius=14.0)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(4)
        self.rarity = label("?", "gachaRarity", center=True)
        self.preview = TypingPet(self.card)
        self.preview.bare = True
        self.preview.centered = True
        self.preview.visitor = True
        self.preview.setFixedSize(210, 88)
        if hasattr(parent, "pet"):
            self.preview.set_species(parent.pet.species)
        self.preview.growth = PetGrowth(growth.to_dict())
        self.preview.pose3d.yaw = -0.18
        self.name = label("扭动把手开启盲盒", "cardTitle", center=True, wrap=True)
        self.note = label("抽到新装扮可立即试穿预览", "fileSub", center=True, wrap=True)
        cl.addWidget(self.rarity)
        cl.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.name)
        cl.addWidget(self.note)
        stage_row.addWidget(self.card, 1)
        lay.addLayout(stage_row)

        lay.addWidget(label("每天首次打开送 1 张券,宠物每升一级送 1 张。概率:N 55% · R 32% · SR 11% · SSR 2%,"
                            f"{GACHA_PITY} 抽内必出 SR 以上;重复装扮自动转化为经验。",
                            "faint", wrap=True, center=True))
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.go = button("扭一次", "primary", self.draw)
        self.go.setMinimumHeight(40)
        self.go_ten = button("十连扭 ✨", "", self.draw_ten)
        self.go_ten.setMinimumHeight(40)
        btn_row.addWidget(self.go, 2)
        btn_row.addWidget(self.go_ten, 1)
        lay.addLayout(btn_row)
        lay.addWidget(button("关闭", "link", self.accept))
        self.refresh()

    def refresh(self) -> None:
        n = self.growth.tickets
        owned_n = sum(1 for _r, kind, iid, _nm in GACHA_POOL if self.growth.has(kind, iid))
        self.sub.setText(f"扭蛋券:{n} 张  ·  图鉴已收集 {owned_n} / {len(GACHA_POOL)}  ·  保底进度 {self.growth.pity}/{GACHA_PITY}")
        self.go.setEnabled(n > 0)
        self.go.setText("扭一次 (1 券)" if n > 0 else "今天的券用完了,明天再来")
        self.go_ten.setEnabled(n >= 2)
        self.go_ten.setText(f"连扭 {min(10, n)} 次" if n >= 2 else "连扭 (需≥2券)")

    def _show_single(self, res: dict) -> None:
        self.machine.spin(res["rarity"])
        self.rarity.setText(res["rarity"])
        self.rarity.setStyleSheet(f"color: {RARITY_COLOR[res['rarity']]};")
        self.name.setText(res["name"])
        pg = PetGrowth(self.growth.to_dict())
        if res["kind"] == "acc" and res["id"] in ACC_BY_ID:
            slot = ACC_BY_ID[res["id"]][3]
            pg.owned.add(f"acc:{res['id']}")
            pg.wear = [w for w in pg.wear if ACC_BY_ID[w][3] != slot] + [res["id"]]
        self.preview.growth = pg
        self.preview.celebrate()
        if res["kind"] == "xp":
            self.note.setText("🐟 美味加餐补给")
        elif res["new"]:
            self.note.setText("✨ 新解锁!已自动收入衣橱/主题库")
        else:
            self.note.setText(f"已拥有,自动转化为 +{res['xp']} 经验")

    def draw(self) -> None:
        res = self.on_draw()
        if res is None:
            return
        self._show_single(res)
        self.refresh()

    def draw_ten(self) -> None:
        count = min(10, self.growth.tickets)
        if count <= 0:
            return
        results = []
        for _ in range(count):
            r = self.on_draw()
            if r is not None:
                results.append(r)
        if not results:
            return
        order = {"N": 0, "R": 1, "SR": 2, "SSR": 3}
        best = max(results, key=lambda r: (order.get(r["rarity"], 0), r.get("new", False)))
        self._show_single(best)
        new_items = [f"[{r['rarity']}]{r['name']}" for r in results if r.get("new")]
        xp_sum = sum(r.get("xp", 0) for r in results)
        summary = f"连扭 {len(results)} 发! "
        if new_items:
            summary += "新获得: " + "、".join(new_items[:4]) + ("…" if len(new_items) > 4 else "")
        else:
            summary += f"累计转化 +{xp_sum} 经验"
        self.note.setText(summary)
        self.refresh()


class PetMixin:
    """宠物养成和互动。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_pet(self) -> None:
        self.allow_visits = True                 # 允许别人的宠物来串门
        self.visitor: TypingPet | None = None    # 正在我家的客人宠物(串门或小剧场)
        self.visit: dict | None = None
        self.pet_away: dict | None = None        # 我的宠物出门了
        self._visit_back: dict[str, float] = {}
        self._skit_wait: tuple | None = None
        self._skit_id = 0
        self._friend_cd: dict[str, float] = {}
        self.pet_hit = PetHit(self.chat_panel, self.pat_pet, pet_getter=lambda: self.pet)
        self.chat_panel.pet_hit = self.pet_hit
        if self.pet_growth.grant_daily():
            QTimer.singleShot(3000, lambda: self.pet.say("今天的抽卡券到啦 🎟️", 4))
        self.core.title = self.pet_growth.title_text()
        self._apply_fx_sound()

    def _restore_pet(self, acct: dict, st: dict) -> None:
        self.allow_visits = bool(st.get("allow_visits", True))
        self.core.title = self.pet_growth.title_text()
        self._apply_fx_sound()

    def _settings_pet(self) -> dict:
        return {"allow_visits": self.allow_visits}

    def _tick_pet(self, now: float) -> None:
        self._tick_pets(now)
        conv = self.current
        if (self.fun.get("skits") and self.fun.get("pet") and conv is not None and conv.kind == "dm"
                and self.visitor is None and not self.pet_away and self.window_visible() and self.isActiveWindow()
                and self.peers.get(conv.target or "", {}).get("online") and random.random() < 1 / 900):
            self.start_skit(conv.target, quiet=True)      # 私聊时偶尔自动演一场

    def _place_pet(self) -> None:
        self.place_pet_extras()

    # ---------------------------------------------------------------- 摸摸 / 成就
    def pat_pet(self) -> None:
        if self.pet_away:
            return
        self.pet.pat()
        self.pet_growth.cheer(3)
        if self.pet_growth.custom_lines and random.random() < 0.45:
            self.pet.say(random.choice(self.pet_growth.custom_lines), 2.8)
        if self.pet_growth.pat():
            self._pet_level_up()
        self._show_achievements()
        if self.visitor is not None:
            self.visitor.pat()

    def _show_achievements(self) -> None:
        for name, xp in self.pet_growth.take_pending():
            self.pet.say(f"🏅 {name}!+{xp} 经验", 3.5)
            conv = self.current
            if conv is not None:
                self._system(conv, f"🏅 成就「{name}」达成,{self.pet_growth.name} 获得 {xp} 经验"
                                   + (f"(已连续打卡 {self.pet_growth.streak} 天)" if "连续" in name else ""))

    def place_pet_extras(self) -> None:
        """宠物身上的点击区、来做客的宠物,跟着宠物一起摆放。"""
        pet = self.pet
        if not pet.isVisible() or self.pet_away:
            self.pet_hit.hide()
        else:
            cx = pet.x() + pet.W - pet.BOX + 55
            self.pet_hit.setGeometry(int(cx - 32), pet.y() + pet.EDGE - 46, 64, 46)
            self.pet_hit.show()
            self.pet_hit.raise_()
        if self.visitor is not None:
            self.visitor.move(pet.x() - 205, pet.y())        # 站在我家宠物计数牌的左边,不挡住它
            self.visitor.raise_()

    # ---------------------------------------------------------------- 串门
    def send_pet_visit(self, pid: str) -> None:
        peer = self.peers.get(pid, {})
        g = self.pet_growth
        if self.pet_away:
            info(self, f"{g.name} 已经出门了", "等它回来再去别人家玩吧。")
            return
        if not peer.get("online"):
            info(self, "对方不在线", "对方在线时才能去串门。")
            return
        conv = self.open_dm(pid, select=False)
        ok = self.core.send_event("dm", pid, "pet_visit", {
            "species": self.pet.species, "name": g.name, "level": g.level, "wear": list(g.wear),
            "coat": g.coat, "eyes": g.eyes, "owner": self.me.get("nick", "")})
        if not ok:
            return
        self.pet_away = {"peer": pid, "nick": peer.get("nick", ""), "until": time.monotonic() + VISIT_SECS + 30}
        self.pet.away = f"去{peer.get('nick', '')[:6]}家玩啦"
        self.pet.say(f"去 {peer.get('nick', '')} 家玩一会儿~", 2.5)
        self._system(conv, f"你让 {g.name} 去 {peer.get('nick', '')} 家串门了,大约 {VISIT_SECS} 秒后回来")
        self.place_pet_extras()
        self.pet.update()

    def _ev_pet_visit(self, conv: Conv, d: dict, data: dict) -> None:
        pid = d["peer"]
        if not self.allow_visits or self.visitor is not None:
            reason = "对方现在不接待客人" if not self.allow_visits else "对方家里已经有客人了"
            self.core.send_event("dm", pid, "pet_back", {"refused": reason})
            return
        species = data.get("species") if data.get("species") in SPECIES else "cat"
        try:
            level = max(1, min(PET_MAX_LEVEL, int(data.get("level", 1))))
        except (TypeError, ValueError):
            level = 1
        name = str(data.get("name") or "团团")[:8]
        wear = [w for w in (data.get("wear") or []) if isinstance(w, str) and w in ACC_BY_ID][:8]
        owner = d["nick"]
        coat = data.get("coat") if data.get("coat") in COAT_BY_ID else "classic"
        eyes = data.get("eyes") if data.get("eyes") in EYE_BY_ID else "obsidian"
        v = TypingPet(self.chat_panel)
        v.visitor = True
        v.set_species(species)
        v.growth = PetGrowth({"xp": xp_for_level(level), "coat": coat, "eyes": eyes})
        v.growth.wear = wear
        v.label = f"{owner[:6]}家的{name} Lv.{level}"
        v.show_combo = False
        v.show()
        self.visitor = v
        self.visit = {"peer": pid, "owner": owner, "name": name, "until": time.monotonic() + VISIT_SECS,
                      "taps": 0, "msgs": 0}
        self.place_pet_extras()
        self.chat_panel.place_overlays()
        v.say("你好呀~ 来玩啦!", 3)
        self.pet_growth.note_visit("visitors", f"{owner}家的{name}")
        self.friend_bonus(pid, owner, 10, {"species": species, "name": name, "level": level, "wear": wear})
        if not self.pet_away:
            QTimer.singleShot(900, lambda: self.pet.say(f"欢迎{name}~", 2.5))
        self._system(conv, f"🐾 {owner} 的 {name} 来你家串门了,会待 {VISIT_SECS} 秒")
        if self.current is not None and self.current is not conv:
            self._system(self.current, f"🐾 {owner} 的 {name} 来串门了")

    def _end_visit(self) -> None:
        v, visit = self.visitor, self.visit
        self.visitor, self.visit = None, None
        if v is not None:
            v.hide()
            v.deleteLater()
        if visit and visit.get("skit"):
            return                                   # 小剧场演完:悄悄散场
        if visit:
            self.core.send_event("dm", visit["peer"], "pet_back",
                                 {"taps": visit["taps"], "msgs": visit["msgs"], "host": self.me.get("nick", "")})
            if not self.pet_away:
                self.pet.say(f"{visit['name']}回家啦,拜拜~", 2.5)

    def _ev_pet_back(self, conv: Conv, d: dict, data: dict) -> None:
        if not self.pet_away or self.pet_away.get("peer") != d["peer"]:
            return
        self.pet_away = None
        self.pet.away = ""
        g = self.pet_growth
        refused = data.get("refused")
        if isinstance(refused, str) and refused:
            self.pet.say(f"白跑一趟…{refused[:20]}", 3)
            self._system(conv, f"{g.name} 没去成:{refused[:40]}")
        else:
            taps = data.get("taps") if type(data.get("taps")) is int else 0
            self.pet.say(f"我回来啦!在{d['nick'][:6]}家玩得超开心~", 3.5)
            g.note_visit("visited", d["nick"])
            self.friend_bonus(d["peer"], d["nick"], 10)
            text = f"{g.name} 从 {d['nick']} 家回来了"
            if taps > 0:
                text += f",那边一共打了 {taps} 个字给它看"
            now = time.monotonic()
            if now - self._visit_back.get(d["peer"], -1e9) > 600:        # 同一家 10 分钟内只加一次经验
                self._visit_back[d["peer"]] = now
                if g.add(30):
                    self._pet_level_up()
                text += ",获得 30 经验"
            self._system(conv, text)
        self.place_pet_extras()
        self.pet.update()

    def _tick_pets(self, now: float) -> None:
        if self.visit and now >= self.visit["until"]:
            self._end_visit()
        if self.pet_away and now >= self.pet_away["until"]:          # 对方一直没回应:自己回来
            self.pet_away = None
            self.pet.away = ""
            self.pet.say("我回来啦~", 2)
            self.place_pet_extras()

    # ---------------------------------------------------------------- 皮肤 / 打字特效 / 音效主题
    def current_skin(self) -> str | None:
        sid = self.fun.get("skin")
        s = theme.SKIN_BY_ID.get(sid or "")
        return sid if s and self.pet_growth.has("skin", sid, s[2]) else None

    def set_skin(self, sid: str | None) -> None:
        self.fun["skin"] = sid

    def _fill_skin_menu(self, menu) -> None:
        menu.clear()
        cur = self.fun.get("skin")
        act = menu.addAction("经典")
        act.setCheckable(True)
        act.setChecked(not cur)
        act.triggered.connect(lambda: self.set_skin(None))
        for sid, name, lv, *_ in theme.SKINS:
            if self.pet_growth.has("skin", sid, lv):
                act = menu.addAction(name)
                act.setCheckable(True)
                act.setChecked(cur == sid)
                act.triggered.connect(lambda _=False, s=sid: self.set_skin(s))
            else:
                act = menu.addAction(f"🔒 {name}  ·  " + ("抽卡限定" if lv >= 99 else f"宠物 Lv.{lv} 或抽卡"))
                act.setEnabled(False)

    def _apply_fx_sound(self) -> None:
        g = self.pet_growth
        fx = self.fun.get("fx", "spark")
        need = next((f[2] for f in FX_THEMES if f[0] == fx), 1)
        self.effects.fx_theme = fx if g.has("fx", fx, need) else "spark"
        snd = self.fun.get("snd", "default")
        need = next((t[2] for t in S.SOUND_THEMES if t[0] == snd), 1)
        snd = snd if g.has("snd", snd, need) else "default"
        self.notifier.set_theme(snd)
        self.keysound.set_theme(snd)

    def set_fx(self, fid: str) -> None:
        self.fun["fx"] = fid
        self._apply_fx_sound()

    def set_snd(self, sid: str) -> None:
        self.fun["snd"] = sid
        self._apply_fx_sound()
        if self.fun.get("keysound"):
            threading.Thread(target=self.keysound.prepare, name="miyu-keyprep", daemon=True).start()
        self.notifier.play(force=True)                         # 换完试听一下

    # ---------------------------------------------------------------- 「趣味互动」菜单的养成部分
    def _fill_more_fun(self, fm) -> None:
        g = self.pet_growth
        fm.addSeparator()
        fm.addAction("📔  宠物日记", self.show_diary)
        t = g.title_text()
        fm.addAction(f"🏆  成就墙和称号({len(g.badges)}/{len(BADGES)}" + (f" · 「{t}」" if t else "") + ")", self.show_wall)
        fm.addAction(f"🎰  抽卡({g.tickets} 张券)", self.show_gacha)
        fm.addAction(f"💞  宠物的朋友({len(g.friends)})", self.show_friends)
        from ..fun import BUBBLE_AURAS
        aura_m = make_menu(fm)
        aura_m.setTitle("✨ 气泡边缘特效(12 款)")
        a0 = aura_m.addAction("关闭边缘特效")
        a0.setCheckable(True)
        a0.setChecked(not g.aura)
        a0.triggered.connect(lambda: g.set_aura(""))
        for aid, aname, lv, _col in BUBBLE_AURAS:
            if g.has_aura(aid):
                act = aura_m.addAction(aname)
                act.setCheckable(True)
                act.setChecked(g.aura == aid)
                act.triggered.connect(lambda _=False, i=aid: g.set_aura(i))
            else:
                tag = "扭蛋限定" if lv >= 999 else f"宠物 Lv.{lv} 或抽卡"
                aura_m.addAction(f"🔒 {aname}  ·  {tag}").setEnabled(False)
        fm.addMenu(aura_m)
        disp_m = make_menu(fm)
        disp_m.setTitle("🔤 聊天字号与间距")
        for px, dname in ((13, "字号:小 (13px)"), (14, "字号:标准 (14px)"), (16, "字号:大 (16px)")):
            act = disp_m.addAction(dname)
            act.setCheckable(True)
            act.setChecked(self.fun.get("font_px", 14) == px)
            act.triggered.connect(lambda _=False, v=px: self.set_chat_font_size(v))
        disp_m.addSeparator()
        for cmp, dname in ((False, "气泡间距:舒适"), (True, "气泡间距:紧凑")):
            act = disp_m.addAction(dname)
            act.setCheckable(True)
            act.setChecked(bool(self.fun.get("compact_bubbles", False)) == cmp)
            act.triggered.connect(lambda _=False, v=cmp: self.set_bubble_density(v))
        fm.addMenu(disp_m)
        fx = make_menu(fm)
        fx.setTitle("打字特效")
        for fid, name, lv in FX_THEMES:
            if g.has("fx", fid, lv):
                a = fx.addAction(name)
                a.setCheckable(True)
                a.setChecked(self.fun.get("fx", "spark") == fid)
                a.triggered.connect(lambda _=False, f=fid: self.set_fx(f))
            else:
                fx.addAction(f"🔒 {name}  ·  宠物 Lv.{lv} 或抽卡").setEnabled(False)
        fm.addMenu(fx)
        snd = make_menu(fm)
        snd.setTitle("音效主题(提示音和打字声)")
        for sid, name, lv in S.SOUND_THEMES:
            if g.has("snd", sid, lv):
                a = snd.addAction(name)
                a.setCheckable(True)
                a.setChecked(self.fun.get("snd", "default") == sid)
                a.triggered.connect(lambda _=False, s=sid: self.set_snd(s))
            else:
                snd.addAction(f"🔒 {name}  ·  宠物 Lv.{lv} 或抽卡").setEnabled(False)
        fm.addMenu(snd)
        amb = make_menu(fm)
        amb.setTitle("白噪音")
        a = amb.addAction("关闭")
        a.setCheckable(True)
        a.setChecked(not self.ambient_kind)
        a.triggered.connect(lambda: self.set_ambient(None))
        for kind, name in S.AMBIENT:
            a = amb.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.ambient_kind == kind)
            a.triggered.connect(lambda _=False, k=kind: self.set_ambient(k))
        amb.addSeparator()
        for v, name in ((0.2, "音量:小"), (0.4, "音量:中"), (0.7, "音量:大")):
            a = amb.addAction(name)
            a.setCheckable(True)
            a.setChecked(abs(self.ambient_volume - v) < 0.05)
            a.triggered.connect(lambda _=False, v=v: self.set_ambient_volume(v))
        fm.addMenu(amb)
        bub = make_menu(fm)
        bub.setTitle("气泡动效")
        for v, name in (("soft", "细腻"), ("lively", "活泼"), ("off", "关闭")):
            a = bub.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.fun.get("bubble", "soft") == v)
            a.triggered.connect(lambda _=False, v=v: self.set_fun("bubble", v))
        fm.addMenu(bub)
        for key, text in (("skits", "宠物小剧场(私聊时偶尔自动演)"), ("rank", "群排行榜(每周一公布)"),
                          ("gpet", "群宠物(暗号群里大家一起养)"), ("lv_badge", "等级标识(名字旁显示宠物等级,别人也看得到)")):
            a = fm.addAction(text)
            a.setCheckable(True)
            a.setChecked(bool(self.fun.get(key, True)))
            a.triggered.connect(lambda on, k=key: self.set_fun(k, on))

    # ---------------------------------------------------------------- 日记 / 成就墙 / 抽卡 / 朋友
    def show_diary(self) -> None:
        g = self.pet_growth
        rows = [("今天(还在写)", g.today_diary())]
        rows += [(e["d"], e["t"]) for e in reversed(g.diary)]
        TextDialog(self, f"{g.name}的日记", rows[:31], f"{g.name}每天写一篇,保留最近 60 天。", width=500).exec()

    def show_wall(self) -> None:
        WallDialog(self, self.pet_growth).exec()
        self.core.title = self.pet_growth.title_text()

    def show_gacha(self) -> None:
        GachaDialog(self, self.pet_growth, self.gacha_draw).exec()

    def gacha_draw(self, rng=None) -> dict | None:
        g = self.pet_growth
        lv = g.level
        res = g.draw(rng)
        if res is None:
            return None
        if res["new"] and res["kind"] == "acc":
            slot = ACC_BY_ID[res["id"]][3]
            if not any(ACC_BY_ID[w][3] == slot for w in g.wear):
                g.toggle(res["id"])
        if g.level > lv:
            self._pet_level_up()
        if res["rarity"] in ("SR", "SSR") and self.fun.get("effects"):
            self.effects.play("confetti")
        self._show_achievements()
        self.pet.update()
        return res

    def show_friends(self) -> None:
        g = self.pet_growth
        rows = []
        for pid, f in sorted(g.friends.items(), key=lambda kv: -kv[1]["v"]):
            pet = f.get("pet") or {}
            who = f"{f['nick']}家的{pet.get('name', '宠物')}" if pet else f["nick"]
            rows.append((who, f"{friend_level(f['v'])}  ·  友谊值 {f['v']} / 100"
                         + ("  ·  可以拍合照(私聊里点 ＋)" if f["v"] >= FRIEND_PHOTO else "")))
        if not rows:
            rows = [("", "还没有朋友。让宠物去别人家串门,或者一起演小剧场,友谊值就会涨。")]
        TextDialog(self, f"{g.name}的朋友", rows, "串门 +10,小剧场 +5。到「朋友」可以拍合照,到「挚友」有称号。", width=480).exec()

    def my_pet_info(self) -> dict:
        g = self.pet_growth
        return {"species": self.pet.species, "name": g.name, "level": g.level, "wear": list(g.wear),
                "coat": g.coat, "eyes": g.eyes}

    @staticmethod
    def clean_pet_info(data) -> dict:
        d = data if isinstance(data, dict) else {}
        try:
            level = max(1, min(PET_MAX_LEVEL, int(d.get("level", 1))))
        except (TypeError, ValueError):
            level = 1
        return {"species": d.get("species") if d.get("species") in SPECIES else "cat",
                "name": str(d.get("name") or "团团")[:8], "level": level,
                "coat": d.get("coat") if d.get("coat") in COAT_BY_ID else "classic",
                "eyes": d.get("eyes") if d.get("eyes") in EYE_BY_ID else "obsidian",
                "wear": [w for w in (d.get("wear") or []) if isinstance(w, str) and w in ACC_BY_ID][:8]}

    def friend_bonus(self, pid: str, nick: str, amount: int, pet: dict | None = None) -> None:
        """加友谊值(同一个人 10 分钟内只加一次),升级时宠物说一声。"""
        g = self.pet_growth
        now = time.monotonic()
        if now - self._friend_cd.get(pid, -1e9) < 600:
            if pet and pid in g.friends:
                g.friends[pid]["pet"] = pet
            return
        self._friend_cd[pid] = now
        before, after = g.add_friend(pid, nick, amount, pet)
        if after != before:
            name = (pet or g.friends[pid].get("pet") or {}).get("name", "对方的宠物")
            conv = self.convs.get("dm:" + pid)
            if conv is not None:
                self._system(conv, f"💞 {g.name} 和 {nick} 家的 {name} 现在是「{after}」了"
                                   + ("!可以在 ＋ 菜单里拍合照了" if after == "朋友" else ""))
        self._show_achievements()

    def _make_pet(self, info_: dict, parent=None) -> TypingPet:
        v = TypingPet(parent)
        v.visitor = True
        v.set_species(info_["species"])
        v.growth = PetGrowth({"xp": xp_for_level(info_["level"]),
                              "coat": info_.get("coat", "classic"), "eyes": info_.get("eyes", "obsidian")})
        v.growth.owned = {f"acc:{w}" for w in info_["wear"]}
        v.growth.wear = list(info_["wear"])
        v.show_combo = False
        return v

    def take_photo(self, pid: str) -> None:
        g = self.pet_growth
        f = g.friends.get(pid)
        conv = self.convs.get("dm:" + pid)
        if f is None or f["v"] < FRIEND_PHOTO or not f.get("pet") or conv is None:
            info(self, "还不能拍合照", "友谊值到 30(朋友)才能拍。让宠物多去串门、多演小剧场。")
            return
        if not self._can_send_to(conv):
            info(self, "对方不在线", "对方在线时才能把合照发过去。")
            return
        pm = QPixmap(480, 300)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, 0, 300)
        grad.setColorAt(0, QColor("#CFE8FF"))
        grad.setColorAt(1, QColor("#FFE6EF"))
        p.fillRect(QRectF(0, 0, 480, 300), QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(40, 212, 400, 120), 20, 20)
        now = time.monotonic()
        mine = self._make_pet(self.my_pet_info())
        other = self._make_pet(self.clean_pet_info(f["pet"]))
        for pet, cx in ((mine, 165), (other, 315)):
            p.save()
            p.translate(cx, 212)
            p.scale(1.7, 1.7)
            p.translate(-(pet.W - pet.BOX + 55), -pet.EDGE)
            pet._paint_pet(p, now, "happy")
            p.restore()
            pet.deleteLater()
        font = QFont(self.font())
        font.setPixelSize(17)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor("#3A3A46"))
        other_name = self.clean_pet_info(f["pet"])["name"]
        p.drawText(QRectF(0, 18, 480, 28), f"{g.name} ♥ {other_name}", QTextOption(Qt.AlignmentFlag.AlignCenter))
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor("#6E6E78"))
        p.drawText(QRectF(0, 44, 480, 20), f"{friend_level(f['v'])} · 友谊值 {f['v']} · {time.strftime('%Y.%m.%d')}",
                   QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()
        res = imaging.encode_for_send(pm.toImage())
        if res:
            data, mime, w, h = res
            self.send_image_data(conv, data, mime, w, h)

    # ---------------------------------------------------------------- 小剧场
    def start_skit(self, pid: str, kind: str | None = None, quiet: bool = False) -> bool:
        if not self.fun.get("pet") or self.visitor is not None or self.pet_away:
            if not quiet:
                info(self, "现在演不了", "要先有宠物,而且它不能在外面串门,家里也不能有客人。")
            return False
        if not self.peers.get(pid, {}).get("online"):
            if not quiet:
                info(self, "对方不在线", "对方在线时才能一起演。")
            return False
        kind = kind if kind in SKITS else random.choice(list(SKITS))
        self._skit_wait = (pid, kind, time.monotonic())
        return bool(self.core.send_event("dm", pid, "skit", {"kind": kind, "pet": self.my_pet_info()}))

    def _ev_skit(self, d: dict, name: str, data: dict) -> None:
        pid, kind = d["peer"], data.get("kind")
        if kind not in SKITS:
            return
        pet = self.clean_pet_info(data.get("pet"))
        if name == "skit":
            if (not self.fun.get("skits") or not self.fun.get("pet") or self.visitor is not None or self.pet_away
                    or not self.window_visible()):
                return
            self.core.send_event("dm", pid, "skit_ok", {"kind": kind, "pet": self.my_pet_info()})
            self.play_skit(pid, d["nick"], kind, pet, i_am_a=False)
        elif self._skit_wait and self._skit_wait[0] == pid and self._skit_wait[1] == kind \
                and time.monotonic() - self._skit_wait[2] < 15:
            self._skit_wait = None
            if self.visitor is None and not self.pet_away:
                self.play_skit(pid, d["nick"], kind, pet, i_am_a=True)

    def play_skit(self, pid: str, nick: str, kind: str, pet: dict, i_am_a: bool) -> None:
        title, script = SKITS[kind]
        v = self._make_pet(pet, self.chat_panel)
        v.label = f"{nick[:6]}家的{pet['name']}"
        v.show()
        self.visitor = v
        self.visit = {"skit": True, "peer": pid, "owner": nick, "name": pet["name"],
                      "until": time.monotonic() + SKIT_SECS, "taps": 0, "msgs": 0}
        self.place_pet_extras()
        self._skit_id += 1
        sid = self._skit_id
        actors = {"a": self.pet if i_am_a else v, "b": v if i_am_a else self.pet}

        def pos(w) -> tuple[float, float]:
            return w.x() + w.W - w.BOX + 55, w.y() + w.EDGE - 34

        def step(item) -> None:
            if sid != self._skit_id or self.visitor is not v:
                return
            what = item[1]
            if what in ("a", "b"):
                actors[what].say(item[2], 1.6)
            elif what == "both":
                for w in actors.values():
                    w.say(item[2], 1.6)
                    w.celebrate()
            elif what == "dance":
                for w in actors.values():
                    w.celebrate()
                x, y = pos(self.pet)
                self.effects.fly_emoji(item[2], x - 60, y, x - 60, y - 50, 0.9)
            elif what == "prop":
                src, dst = (actors["a"], actors["b"]) if item[3] == "a2b" else (actors["b"], actors["a"])
                (x0, y0), (x1, y1) = pos(src), pos(dst)
                self.effects.fly_emoji(item[2], x0, y0, x1, y1, 0.8)
        for item in script:
            QTimer.singleShot(int(item[0] * 1000), lambda it=item: step(it))
        self.pet_growth.note_visit("skits", "")
        self.friend_bonus(pid, nick, 5, pet)
        conv = self.convs.get("dm:" + pid)
        if conv is not None and conv.key == self.current_key:
            self._system(conv, f"🎭 {self.pet_growth.name} 和 {nick} 家的 {pet['name']} 演了一场《{title}》")
