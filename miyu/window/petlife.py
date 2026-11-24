"""
密语 · 宠物照料和互动体系
  · 右键点宠物:喂食、玩耍、衣橱和形态
  · 饱腹度 / 心情随时间下降,饿了会撒娇
  · 跟随聊天:发消息举爪欢呼,别的会话来消息冒"!"招手
  · 衣橱:帽子、衣服、配饰、表情;形态:幼年 → 成长 → 进化 → 传说
  · 群宠物:每个暗号群一只,大家聊天、喂食一起养(没有服务器,用"每人一份计数取最大"同步)
  · 桌面陪伴(可选):窗口最小化时宠物趴在桌面角落,来消息会招手,点它回到密语
  · 等级标识:群聊里名字旁边显示宠物等级
"""
from __future__ import annotations

import random
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..dialogs import Dialog, TextDialog, info, prompt
from ..fun import ACC_BY_ID, ACCESSORIES, OUTFITS, SLOTS, SPECIES, TRICKS, PetGrowth, TypingPet
from ..petcare import (
    EXPRESSIONS, FOOD_BY_ID, FOODS, FORMS, GP_DAILY_FEEDS, GP_MSG_XP, GP_SPECIES, TOY_BY_ID, TOYS, GroupPet,
    form_of, next_form,
)
from ..theme import T
from ..ui import button, label, make_menu, popup
from ..widgets import Conv
from .pet import PetHit

GPET_RESEND = 10.0                # 群宠物状态有变化时,最快 10 秒同步一次
SAY_CD = 6.0                      # 宠物提醒"有新消息"的最短间隔
THANKS = ("好好吃!谢谢~", "嗷呜,超满足!", "还想要~", "最喜欢你啦!")
PLAY_SAY = ("好好玩!", "再来再来!", "哈哈哈~", "累了但是开心!")


class DesktopPet(QWidget):
    """桌面陪伴:窗口最小化时,宠物趴在屏幕角落一个小台子上。左键点它回到密语,按住可以拖动,右键有菜单。"""

    def __init__(self, win) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.win = win
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(TypingPet.W, TypingPet.H + 6)
        self.pet = TypingPet(self)
        self.pet.bare = True
        self.pet.visitor = True
        self.pet.growth = win.pet_growth
        self.pet.set_species(win.fun.get("pet") or "cat")
        self.pet.move(0, 0)
        self.setToolTip("点我回到密语 · 按住拖动 · 右键更多")
        self._press: QPoint | None = None
        self._moved = False

    def paintEvent(self, _e) -> None:
        """宠物下面的小台子(代替聊天窗口里的输入框边缘)。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.pet._cx()
        r = QRectF(cx - 52, TypingPet.EDGE - 1, 104, 12)
        p.setPen(QColor(0, 0, 0, 40))
        c = QColor(T["card"])
        c.setAlphaF(0.96)
        p.setBrush(c)
        p.drawRoundedRect(r, 6, 6)
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, e) -> None:
        if self._press is not None:
            pos = e.globalPosition().toPoint() - self._press
            if (pos - self.pos()).manhattanLength() > 3:
                self._moved = True
                self.move(pos)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            if self._moved:
                self.win.desktop_pos = [self.x(), self.y()]
            else:
                self.win.restore_from_desktop()
            self._press = None

    def contextMenuEvent(self, e) -> None:
        m = make_menu(self)
        m.addAction("🤚  摸摸", self.pet.pat)
        m.addAction("回到密语", self.win.restore_from_desktop)
        m.addSeparator()
        m.addAction("关闭桌面陪伴", lambda: self.win.set_desktop_pet(False))
        m.exec(e.globalPos())


class WardrobeDialog(Dialog):
    """衣橱和形态:上面是宠物预览和状态,下面按部位分页换装扮、换表情,最后一页看形态。"""

    def __init__(self, win) -> None:
        super().__init__(win, "衣橱和形态")
        self.win = win
        g = self.g = win.pet_growth
        g.care()
        self.setFixedWidth(720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label(f"{g.name} 的衣橱", "dialogTitle"))

        top = QHBoxLayout()
        stage = QFrame()
        stage.setObjectName("plainCard")
        stage.setFixedSize(TypingPet.W + 8, TypingPet.H + 18)
        self.preview = TypingPet(stage)
        self.preview.bare = True
        self.preview.centered = True
        self.preview.visitor = True
        self.preview.growth = g
        self.preview.set_species(win.pet.species)
        self.preview.move(4, 4)
        top.addWidget(stage)
        col = QVBoxLayout()
        col.setSpacing(4)
        idx, fname, fdesc = form_of(g.level)
        nf = next_form(g.level)
        col.addWidget(label(f"Lv.{g.level}  ·  {fname}", "cardTitle"))
        col.addWidget(label(fdesc + (f"\n再升到 Lv.{nf[0]} 进入「{nf[1]}」" if nf else "\n已经是最终形态"), "fileSub",
                            wrap=True))
        self.food_bar, self.joy_bar = QProgressBar(), QProgressBar()
        for name, bar, v in (("饱腹", self.food_bar, g.food), ("心情", self.joy_bar, g.joy)):
            row = QHBoxLayout()
            row.addWidget(label(name, "faint"))
            bar.setObjectName("fileProgress")
            bar.setRange(0, 100)
            bar.setValue(int(v))
            bar.setTextVisible(False)
            row.addWidget(bar, 1)
            col.addLayout(row)
        self.mood = label(f"现在:{g.mood_word()}", "hint")
        col.addWidget(self.mood)
        col.addStretch(1)
        top.addLayout(col, 1)
        lay.addLayout(top)

        tabs = QHBoxLayout()
        tabs.setSpacing(2)
        self.stack = QStackedWidget()
        self.tab_btns: list[QPushButton] = []
        self.item_btns: dict[str, QPushButton] = {}
        self.expr_btns: dict[str, QPushButton] = {}
        self.outfit_rows: dict[str, tuple] = {}
        self.trick_btns: dict[str, QPushButton] = {}
        pages = [(name, self._acc_page(slot)) for slot, name in SLOTS]
        pages += [("套装", self._outfit_page()), ("动作", self._trick_page()), ("表情", self._expr_page()),
                  ("形态", self._form_page())]
        tabs2 = QHBoxLayout()
        tabs2.setSpacing(2)
        for i, (name, page) in enumerate(pages):
            b = QPushButton(name)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.show_tab(i))
            (tabs if i < len(SLOTS) else tabs2).addWidget(b)
            self.tab_btns.append(b)
            self.stack.addWidget(page)
        tabs.addStretch(1)
        tabs2.addStretch(1)
        lay.addLayout(tabs)
        lay.addLayout(tabs2)
        self.stack.setFixedHeight(214)
        lay.addWidget(self.stack)
        self.tip = label("", "faint", wrap=True)
        lay.addWidget(self.tip)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("完成", "primary", self.accept, 90))
        lay.addLayout(row)
        self.show_tab(0)
        self.refresh()

    def _grid_page(self) -> tuple[QWidget, QGridLayout]:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setSpacing(6)
        return page, grid

    def _acc_page(self, slot: str) -> QWidget:
        page, grid = self._grid_page()
        items = [a for a in ACCESSORIES if a[3] == slot]
        for i, (aid, name, lv, _slot) in enumerate(items):
            b = QPushButton(name)
            b.setObjectName("choice")
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, a=aid: self.toggle(a))
            grid.addWidget(b, i // 4, i % 4)
            self.item_btns[aid] = b
        grid.setRowStretch(len(items) // 4 + 1, 1)
        return page

    def _outfit_page(self) -> QWidget:
        """套装:一键穿上;集齐全部部件身后会有一圈套装颜色的光。"""
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setSpacing(6)
        for i, (oid, name, parts, color) in enumerate(OUTFITS):
            box = QFrame()
            box.setObjectName("plainCard")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 6, 10, 6)
            bl.setSpacing(2)
            top = QHBoxLayout()
            dot = label("●", "")
            dot.setStyleSheet(f"color: {color};")
            top.addWidget(dot)
            top.addWidget(label(name, "cardTitle"), 1)
            btn = button("一键穿上", "", lambda _=False, o=oid: self.wear_outfit(o), 78)
            btn.setMinimumHeight(26)
            top.addWidget(btn)
            bl.addLayout(top)
            parts_lab = label("", "fileSub", wrap=True)
            bl.addWidget(parts_lab)
            grid.addWidget(box, i // 2, i % 2)
            self.outfit_rows[oid] = (btn, parts_lab, box)
        return page

    def _trick_page(self) -> QWidget:
        page, grid = self._grid_page()
        for i, (need, tid, name, _dur) in enumerate(TRICKS):
            b = QPushButton(name)
            b.setObjectName("choice")
            b.setMinimumHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=tid: self.play_trick(t))
            grid.addWidget(b, i // 5, i % 5)
            self.trick_btns[tid] = b
        grid.setRowStretch(3, 1)
        return page

    def wear_outfit(self, oid: str) -> None:
        missing = self.g.wear_outfit(oid)
        self.tip.setText(("还差没解锁的:" + "、".join(missing) + "(升级或抽卡获得)") if missing else "整套穿上了!身后有一圈套装光效。")
        self.refresh(keep_tip=True)

    def play_trick(self, tid: str) -> None:
        self.preview.trick(tid)
        self.win.pet.trick(tid)

    def _expr_page(self) -> QWidget:
        page, grid = self._grid_page()
        for i, (eid, name, lv) in enumerate(EXPRESSIONS):
            b = QPushButton(name)
            b.setObjectName("choice")
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, e=eid: self.set_expr(e))
            grid.addWidget(b, i // 4, i % 4)
            self.expr_btns[eid] = b
        grid.setRowStretch(2, 1)
        return page

    def _form_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(4, 6, 4, 0)
        col.setSpacing(4)
        cur = form_of(self.g.level)[0]
        for i, (need, name, desc) in enumerate(FORMS):
            mark = "▶ " if i == cur else ("✓ " if i < cur else "🔒 ")
            col.addWidget(label(f"{mark}{name}  ·  Lv.{need}  ·  {desc}", "cardTitle" if i == cur else "fileSub"))
        col.addStretch(1)
        return page

    TIPS = {"套装": "一键穿上套装里已经解锁的部件;集齐整套,身后会有一圈套装颜色的光。",
            "动作": "每 5 级学会一个新动作。宠物闲着时会自己表演,在这里点一下马上表演。",
            "表情": "平时的表情。", "形态": "10 级长大,20 级第一次进化,30 级传说期,40 级第二次进化(神话期)。"}

    def show_tab(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.tab_btns):
            b.setChecked(i == j)
        name = self.tab_btns[i].text()
        self.tip.setText(self.TIPS.get(name, "装扮随等级解锁,也能抽卡提前拿到。同一个部位一次戴一件,再点一下摘下。"))

    def toggle(self, aid: str) -> None:
        self.g.toggle(aid)
        self.refresh()

    def set_expr(self, eid: str) -> None:
        self.g.set_expr(eid)
        self.refresh()

    def refresh(self, keep_tip: bool = False) -> None:
        g = self.g
        for aid, b in self.item_btns.items():
            a = ACC_BY_ID[aid]
            ok = g.is_unlocked(aid)
            b.setEnabled(ok)
            b.setChecked(aid in g.wear)
            b.setText(a[1] if ok else f"🔒 {a[1]}  Lv.{a[2]}")
            sets = [o[1] for o in OUTFITS if aid in o[2]]
            b.setToolTip((f"Lv.{a[2]} 解锁(也能抽卡提前抽到)" if not ok else "点一下戴上 / 摘下")
                         + (f"\n属于套装:{'、'.join(sets)}" if sets else ""))
        full = g.full_outfit()
        for oid, (btn, parts_lab, box) in self.outfit_rows.items():
            o = next(x for x in OUTFITS if x[0] == oid)
            bits = []
            for aid in o[2]:
                a = ACC_BY_ID[aid]
                mark = "✓" if aid in g.wear else ("○" if g.is_unlocked(aid) else "🔒")
                bits.append(f"{mark}{a[1]}" + ("" if g.is_unlocked(aid) else f"(Lv.{a[2]})"))
            parts_lab.setText("  ".join(bits) + ("\n✨ 已集齐" if full is not None and full[0] == oid else ""))
            btn.setEnabled(any(g.is_unlocked(aid) for aid in o[2]))
        for tid, b in self.trick_btns.items():
            need, _t, name, _d = next(x for x in TRICKS if x[1] == tid)
            ok = g.level >= need
            b.setEnabled(ok)
            b.setText(f"🎭 {name}" if ok else f"🔒 {name}  Lv.{need}")
        for eid, b in self.expr_btns.items():
            ok = g.can_use("expr", eid)
            name, lv = next((e[1], e[2]) for e in EXPRESSIONS if e[0] == eid)
            b.setEnabled(ok)
            b.setChecked(g.expr == eid)
            b.setText(name if ok else f"🔒 {name}  Lv.{lv}")
        self.preview.update()
        self.win.pet.update()


class PetLifeMixin:
    """宠物照料、衣橱、跟随聊天的动作、群宠物、桌面陪伴、等级标识。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_petlife(self) -> None:
        self.gpets: dict[str, GroupPet] = {}
        self._gpet_sent: dict[str, float] = {}
        self._say_t = 0.0
        self._care_said = time.monotonic()
        self._last_lv = 0
        self.desktop_pet_on = False
        self.desktop_pos: list[int] | None = None
        self.desktop_win: DesktopPet | None = None
        self.pet_hit.on_menu = self.pet_menu
        self.gpet = TypingPet(self.chat_panel)
        self.gpet.mirror = True
        self.gpet.visitor = True
        self.gpet.show_combo = False
        self.gpet.hide()
        self.gpet_hit = PetHit(self.chat_panel, self.pat_gpet, self.gpet_menu, "群宠物:左键摸摸 · 右键喂它、改名、贡献榜")
        self.gpet_hit.hide()
        self.pet_growth.care()
        self._sync_level()

    def _restore_petlife(self, acct: dict, st: dict) -> None:
        self.desktop_pet_on = bool(st.get("desktop_pet", False))
        pos = st.get("desktop_pos")
        if isinstance(pos, list) and len(pos) == 2 and all(type(v) is int for v in pos):
            self.desktop_pos = pos
        gp = acct.get("gpets")
        if isinstance(gp, dict):
            for tag, d in list(gp.items())[:50]:
                if isinstance(tag, str) and isinstance(d, dict):
                    self.gpets[tag] = GroupPet(d)
        self._sync_level()

    def _save_petlife(self) -> dict:
        return {"gpets": {tag: gp.to_dict() for tag, gp in self.gpets.items() if tag in self.room_keys}}

    def _settings_petlife(self) -> dict:
        return {"desktop_pet": self.desktop_pet_on, "desktop_pos": self.desktop_pos}

    def _tick_petlife(self, now: float) -> None:
        if self._save_tick % 5 == 0:
            self._sync_level()
        if self._save_tick % 60 == 0:
            self._care_tick(now)
        for tag, gp in self.gpets.items():
            if gp.dirty and now - self._gpet_sent.get(tag, -1e9) >= GPET_RESEND:
                self.send_gpet(tag)
        self.desktop_pet_sync()

    def _place_petlife(self) -> None:
        self._place_gpet()

    def _switch_petlife(self, conv: Conv) -> None:
        self.refresh_gpet()

    def _winstate_petlife(self) -> None:
        self.desktop_pet_sync()

    def _peer_online_petlife(self, pid: str) -> None:
        """有群友上线:把群宠物的状态发一份(合并后大家一致)。"""
        rooms = self.peers.get(pid, {}).get("rooms", [])
        for tag in rooms:
            if tag in self.gpets:
                self.gpets[tag].dirty = True

    def _message_petlife(self, conv: Conv, m) -> None:
        g = self.pet_growth
        if m.mine:
            g.cheer(0.5)
            if conv.kind == "room" and self.fun.get("gpet", True):
                gp = self.gpet_for(conv.target)
                before = gp.level
                if gp.contribute(self.me["id"], self.me.get("nick", ""), GP_MSG_XP) and gp.level > before:
                    self._gpet_level_up(conv, gp)
            return
        self.pet_notice(conv, m)

    # ---------------------------------------------------------------- 等级标识
    def _sync_level(self) -> None:
        lv = self.pet_growth.level
        self.core.level = lv if self.fun.get("lv_badge", True) else 0
        if lv != self._last_lv:
            self._last_lv = lv
            self._refresh_self()

    def set_level_badge(self, on: bool) -> None:
        self.set_fun("lv_badge", bool(on))
        self._sync_level()

    # ---------------------------------------------------------------- 跟随聊天
    def pet_notice(self, conv: Conv, m) -> None:
        """收到消息时宠物提醒:别的会话来消息冒"!"招手;被 @ 了跳起来喊。正在看的会话只抖耳朵(原来就有)。"""
        if conv.kind == "self" or m.system:
            return
        now = time.monotonic()
        if not self.window_visible():
            if self.desktop_win is not None and self.desktop_win.isVisible() and not conv.muted:
                self.desktop_win.pet.alert()
                if now - self._say_t >= SAY_CD:
                    self._say_t = now
                    self.desktop_win.pet.say("有新消息~", 3)      # 桌面上不显示是谁发的,免得被旁人看到
            return
        if not self.fun.get("pet") or self.pet_away:
            return
        is_current = conv.key == self.current_key
        covered = getattr(self, "cover", None) is not None and self.cover.isVisible()
        if m.mention:
            self.pet.alert()
            if now - self._say_t >= SAY_CD / 2:
                self._say_t = now
                self.pet.say("有人@你啦!" if covered else f"{m.nick[:6]} @了你!", 3)
        elif not is_current and not conv.muted:
            self.pet.alert()
            if now - self._say_t >= SAY_CD and not covered:
                self._say_t = now
                where = f"{m.nick[:6]}发来消息~" if conv.kind == "dm" else f"「{conv.title[:6]}」有新消息"
                self.pet.say(where, 2.8)

    # ---------------------------------------------------------------- 照料:喂食 / 玩耍
    def _care_tick(self, now: float) -> None:
        g = self.pet_growth
        g.care()
        if (not self.fun.get("pet") or self.pet_away or not self.window_visible()
                or now - self._care_said < 1800):
            return
        if g.food < 25:
            self._care_said = now
            self.pet.say(random.choice(("肚子饿了…右键喂我点吃的吧 🐟", "咕噜咕噜…好饿", "想吃小鱼干~")), 4)
        elif g.joy < 25:
            self._care_said = now
            self.pet.say(random.choice(("好无聊…陪我玩一会儿嘛", "右键点我,一起玩吧 🧶")), 4)

    def pet_menu(self, pos) -> None:
        g = self.pet_growth
        g.care()
        m = make_menu(self)
        head = m.addAction(f"{g.name}  ·  Lv.{g.level}  ·  {g.form[1]}  ·  {g.mood_word()}")
        head.setEnabled(False)
        st = m.addAction(f"饱腹 {int(g.food)} / 100   心情 {int(g.joy)} / 100")
        st.setEnabled(False)
        m.addSeparator()
        m.addAction("🤚  摸摸头", self.pat_pet)
        feed = make_menu(m)
        feed.setTitle("🍽  喂食")
        for fid, name, emo, food, joy, lv in FOODS:
            if g.can_use("food", fid):
                feed.addAction(f"{emo}  {name}   饱腹 +{food}", lambda f=fid: self.feed_pet(f))
            else:
                feed.addAction(f"🔒 {name}  ·  Lv.{lv} 解锁").setEnabled(False)
        m.addMenu(feed)
        play = make_menu(m)
        play.setTitle("🎾  玩耍")
        for tid, name, emo, joy, lv in TOYS:
            if g.can_use("toy", tid):
                play.addAction(f"{emo}  {name}   心情 +{joy}", lambda t=tid: self.play_pet(t))
            else:
                play.addAction(f"🔒 {name}  ·  Lv.{lv} 解锁").setEnabled(False)
        m.addMenu(play)
        show = make_menu(m)
        show.setTitle("🎭  表演一个")
        for need, tid, name, _dur in TRICKS:
            if g.level >= need:
                show.addAction(name, lambda t=tid: self.pet.trick(t))
            else:
                show.addAction(f"🔒 {name}  ·  Lv.{need} 学会").setEnabled(False)
        m.addMenu(show)
        m.addSeparator()
        m.addAction("👗  衣橱和形态…", self.show_wardrobe)
        m.addAction("📔  宠物日记", self.show_diary)
        act = m.addAction("🖥  桌面陪伴(窗口最小化时宠物留在桌面角落)")
        act.setCheckable(True)
        act.setChecked(self.desktop_pet_on)
        act.triggered.connect(self.set_desktop_pet)
        popup(m, pos)

    def feed_pet(self, fid: str) -> bool:
        if self.pet_away:
            info(self, f"{self.pet_growth.name} 出门了", "等它回来再喂吧。")
            return False
        food = FOOD_BY_ID.get(fid)
        up = self.pet_growth.feed(fid)
        if food is None or up < 0:
            return False
        self.pet.act("eat", food[2], 2.2)
        QTimer.singleShot(2300, lambda: self.pet.say(random.choice(THANKS), 2.2))
        if up > 0:
            self._pet_level_up()
        self._show_achievements()
        return True

    def play_pet(self, tid: str) -> bool:
        if self.pet_away:
            info(self, f"{self.pet_growth.name} 出门了", "等它回来再一起玩吧。")
            return False
        toy = TOY_BY_ID.get(tid)
        up = self.pet_growth.play(tid)
        if toy is None or up < 0:
            return False
        self.pet.act("play", toy[2], 2.6)
        QTimer.singleShot(2700, lambda: self.pet.say(random.choice(PLAY_SAY), 2))
        if up > 0:
            self._pet_level_up()
        self._show_achievements()
        return True

    def show_wardrobe(self) -> None:
        WardrobeDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.pet.update()
        self.save_account()

    # ---------------------------------------------------------------- 群宠物
    def gpet_for(self, tag: str) -> GroupPet:
        gp = self.gpets.get(tag)
        if gp is None:
            gp = self.gpets[tag] = GroupPet()
        return gp

    def refresh_gpet(self) -> None:
        conv = self.current
        show = (conv is not None and conv.kind == "room" and bool(self.fun.get("gpet", True))
                and bool(self.fun.get("pet")) and self.input.isEnabled())
        if not show:
            self.gpet.hide()
            self.gpet_hit.hide()
            return
        gp = self.gpet_for(conv.target)
        g = PetGrowth({"xp": gp.total})
        g.owned = {f"acc:{w}" for w in gp.wear[0] if w in ACC_BY_ID}
        g.wear = [w for w in gp.wear[0] if w in ACC_BY_ID]
        self.gpet.growth = g
        self.gpet.set_species(gp.species[0])
        wide = self._pill.width() >= 560
        self.gpet.label = f"群宠 {gp.name[0]} Lv.{gp.level}" if wide else ""
        self.gpet.bare = not wide
        self.gpet.show()
        self._place_gpet()
        self.gpet.update()

    def _place_gpet(self) -> None:
        if not self.gpet.isVisible():
            self.gpet_hit.hide()
            return
        tl = self._pill.mapTo(self.chat_panel, QPoint(0, 0))
        self.gpet.move(tl.x() + 4, tl.y() - self.gpet.EDGE + 1)
        self.gpet.raise_()
        cx = self.gpet.x() + self.gpet._cx()
        self.gpet_hit.setGeometry(int(cx - 32), self.gpet.y() + self.gpet.EDGE - 46, 64, 46)
        self.gpet_hit.show()
        self.gpet_hit.raise_()

    def pat_gpet(self) -> None:
        self.gpet.pat()

    def gpet_menu(self, pos) -> None:
        conv = self.current
        if conv is None or conv.kind != "room":
            return
        gp = self.gpet_for(conv.target)
        m = make_menu(self)
        head = m.addAction(f"群宠物 {gp.name[0]}  ·  Lv.{gp.level}  ·  {form_of(gp.level)[1]}")
        head.setEnabled(False)
        sub = m.addAction(f"大家一共攒了 {gp.total:,} 经验  ·  今天你还能喂 {gp.feeds_left()} 次")
        sub.setEnabled(False)
        m.addSeparator()
        feed = make_menu(m)
        feed.setTitle("🍽  喂它")
        for fid, name, emo, *_rest in FOODS:
            a = feed.addAction(f"{emo}  {name}", lambda f=fid: self.feed_gpet(f))
            a.setEnabled(gp.feeds_left() > 0)
        m.addMenu(feed)
        m.addAction("✏️  改名…", lambda: self.rename_gpet(conv))
        sp = make_menu(m)
        sp.setTitle("换个样子")
        for key in GP_SPECIES:
            a = sp.addAction(SPECIES[key]["label"], lambda k=key: self.set_gpet_species(conv, k))
            a.setCheckable(True)
            a.setChecked(gp.species[0] == key)
        m.addMenu(sp)
        m.addAction("🏅  贡献榜…", lambda: self.show_gpet_rank(conv))
        m.addSeparator()
        m.addAction("不显示群宠物", lambda: (self.set_fun("gpet", False), self.refresh_gpet()))
        popup(m, pos)

    def feed_gpet(self, fid: str, conv: Conv | None = None) -> bool:
        conv = conv or self.current
        if conv is None or conv.kind != "room" or fid not in FOOD_BY_ID:
            return False
        gp = self.gpet_for(conv.target)
        before = gp.level
        if not gp.feed(self.me["id"], self.me.get("nick", ""), fid):
            info(self, "今天喂饱啦", f"每人每天最多喂 {GP_DAILY_FEEDS} 次,明天再来。")
            return False
        if conv.key == self.current_key:
            self.gpet.act("eat", FOOD_BY_ID[fid][2], 2.2)
            QTimer.singleShot(2300, lambda: self.gpet.say(random.choice(THANKS), 2))
        self.send_gpet(conv.target)
        if gp.level > before:
            self._gpet_level_up(conv, gp)
        self.refresh_gpet()
        return True

    def rename_gpet(self, conv: Conv) -> None:
        gp = self.gpet_for(conv.target)
        text = prompt(self, "给群宠物起名字", "最多 8 个字,群里所有人都会看到。", gp.name[0], max_len=8, ok="好")
        if text is not None and gp.rename(text, self.me.get("nick", "")):
            self._system(conv, f"你把群宠物改名为「{gp.name[0]}」")
            self.send_gpet(conv.target)
            self.refresh_gpet()

    def set_gpet_species(self, conv: Conv, sp: str) -> None:
        gp = self.gpet_for(conv.target)
        if gp.set_species(sp, self.me.get("nick", "")):
            self.send_gpet(conv.target)
            self.refresh_gpet()

    def show_gpet_rank(self, conv: Conv) -> None:
        gp = self.gpet_for(conv.target)
        rows = [(f"{i + 1}. {nick}", f"经验 {xp:,}  ·  喂过 {feeds} 次") for i, (nick, xp, feeds) in enumerate(gp.top(10))]
        if not rows:
            rows = [("", "还没有人照顾过它。在群里聊天、喂它,都会给它攒经验。")]
        TextDialog(self, f"群宠物 {gp.name[0]} 的贡献榜", rows,
                   f"在群里每发一条消息 +{GP_MSG_XP}(每天最多 300),喂一次 +20(每天 {GP_DAILY_FEEDS} 次)。", width=440).exec()

    def send_gpet(self, tag: str) -> bool:
        gp = self.gpets.get(tag)
        if gp is None or tag not in self.core.rooms:
            return False
        self._gpet_sent[tag] = time.monotonic()
        gp.dirty = False
        return bool(self.core.send_event("room", tag, "gpet", gp.to_wire()))

    def _ev_gpet(self, conv: Conv, d: dict, data: dict) -> None:
        if conv.kind != "room" or not isinstance(data, dict):
            return
        gp = self.gpet_for(conv.target)
        before_lv, before_act, before_name = gp.level, gp.act.get("t", 0), gp.name
        gp.merge(data)
        theirs = data.get("x") if isinstance(data.get("x"), dict) else {}
        if any(v > (theirs.get(pid) if type(theirs.get(pid)) is int else 0) for pid, v in gp.xp.items()):
            gp.dirty = True                              # 对方落后了:过一会儿把完整的发回去
        here = conv.key == self.current_key and self.window_visible()
        if gp.act.get("t", 0) > before_act and gp.act.get("by") and here:
            food = FOOD_BY_ID.get(gp.act.get("food", ""))
            self.gpet.act("eat", food[2] if food else "🍙", 2.2)
            who = gp.act["by"][:6]
            QTimer.singleShot(2300, lambda: self.gpet.say(f"谢谢{who}的{food[1] if food else '好吃的'}!", 2.5))
        if gp.name[0] != before_name[0] and gp.name[2]:
            self._system(conv, f"{gp.name[2]} 把群宠物改名为「{gp.name[0]}」")
        if gp.level > before_lv:
            self._gpet_level_up(conv, gp)
        if conv.key == self.current_key:
            self.refresh_gpet()

    def _gpet_level_up(self, conv: Conv, gp: GroupPet) -> None:
        lv = gp.level
        g = self.pet_growth
        if lv > g.counts["gpet"]:
            g.counts["gpet"] = lv
            g.check_badges()
            self._show_achievements()
        if conv.key == self.current_key:
            self.gpet.level_up(lv)
        idx, fname, _d = form_of(lv)
        extra = f",进入「{fname}」!" if FORMS[idx][0] == lv and lv > 1 else ""
        self._system(conv, f"🎉 群宠物 {gp.name[0]} 升到 Lv.{lv} 了{extra}")

    # ---------------------------------------------------------------- 桌面陪伴
    def set_desktop_pet(self, on: bool) -> None:
        self.desktop_pet_on = bool(on)
        if on and not self.isMinimized():
            self.pet.say("最小化窗口时,我会趴到桌面角落陪你~", 3.5)
        self.desktop_pet_sync()

    def desktop_pet_sync(self) -> None:
        """只在「窗口最小化」时显示;老板键藏起来、锁屏、关掉宠物时都不显示。"""
        locked = getattr(self, "lock_overlay", None) is not None and self.lock_overlay.isVisible()
        want = (self.desktop_pet_on and bool(self.fun.get("pet")) and self.isVisible() and self.isMinimized()
                and not locked)
        if not want:
            if self.desktop_win is not None and self.desktop_win.isVisible():
                self.desktop_win.hide()
            return
        if self.desktop_win is None:
            self.desktop_win = DesktopPet(self)
        w = self.desktop_win
        w.pet.set_species(self.fun.get("pet") or "cat")
        w.pet.growth = self.pet_growth
        if not w.isVisible():
            x, y = self._desktop_place()
            w.move(x, y)
            w.show()
            w.pet.say(random.choice(("我在这儿陪你~", "有消息我会叫你哦")), 2.5)

    def _desktop_place(self) -> tuple[int, int]:
        try:
            geo = QGuiApplication.primaryScreen().availableGeometry()
            gx, gy, gw, gh = geo.x(), geo.y(), geo.width(), geo.height()
        except Exception:                                 # noqa: BLE001
            gx, gy, gw, gh = 0, 0, 1280, 720
        if self.desktop_pos:
            x, y = self.desktop_pos
            if gx - 100 <= x <= gx + gw - 60 and gy - 20 <= y <= gy + gh - 40:
                return x, y
        return gx + gw - TypingPet.W - 16, gy + gh - TypingPet.H - 18

    def restore_from_desktop(self) -> None:
        if self.desktop_win is not None:
            self.desktop_win.hide()
        self.show_window()
