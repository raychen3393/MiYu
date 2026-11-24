"""
密语 · 宠物:摸摸和成就、串门、小剧场、日记、成就墙、抽卡、朋友和合照、气泡皮肤 / 打字特效 / 音效主题。
"""
from __future__ import annotations

import random
import threading
import time

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPixmap, QTextOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .. import imaging, sound as S, theme
from ..dialogs import Dialog, TextDialog, info
from ..fun import (
    ACC_BY_ID, BADGES, FRIEND_PHOTO, FX_THEMES, GACHA_PITY, PetGrowth, SPECIES, TypingPet, friend_level,
    xp_for_level,
)
from ..ui import button, label, make_menu
from ..widgets import Conv


VISIT_SECS = 90                   # 宠物串门待多久


class PetHit(QWidget):
    """盖在宠物身体上的透明小区域:只有这里能点,不挡住聊天内容。左键摸摸,右键喂食 / 玩耍 / 换装。"""

    def __init__(self, parent, on_click, on_menu=None, tip: str = "左键摸摸它 · 右键喂食、玩耍、换装") -> None:
        super().__init__(parent)
        self.on_click = on_click
        self.on_menu = on_menu
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.on_click()

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


class GachaDialog(Dialog):
    def __init__(self, parent, growth: PetGrowth, on_draw) -> None:
        super().__init__(parent, "抽卡")
        self.growth, self.on_draw = growth, on_draw
        self.setFixedWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(8)
        lay.addWidget(label("🎰 抽卡", "dialogTitle", center=True))
        self.sub = label("", "hint", center=True)
        lay.addWidget(self.sub)
        self.card = QFrame()
        self.card.setObjectName("plainCard")
        self.card.setMinimumHeight(130)
        cl = QVBoxLayout(self.card)
        self.rarity = label("?", "gachaRarity", center=True)
        self.name = label("点下面的按钮抽一张", "cardTitle", center=True)
        self.note = label("", "fileSub", center=True)
        for w in (self.rarity, self.name, self.note):
            cl.addWidget(w)
        lay.addWidget(self.card)
        lay.addWidget(label("每天第一次打开送 1 张券,宠物每升一级再送 1 张。\n能抽到:帽子衣服等装扮、气泡皮肤、打字特效、音效主题;"
                            f"重复的换成经验。\n概率:N 55% · R 32% · SR 11% · SSR 2%,{GACHA_PITY} 抽之内必出 SR 以上。",
                            "faint", wrap=True, center=True))
        self.go = button("抽一次", "primary", self.draw)
        self.go.setMinimumHeight(40)
        lay.addWidget(self.go)
        lay.addWidget(button("关闭", "link", self.accept))
        self.refresh()

    def refresh(self) -> None:
        n = self.growth.tickets
        self.sub.setText(f"抽卡券:{n} 张")
        self.go.setEnabled(n > 0)
        self.go.setText("抽一次" if n > 0 else "今天的券用完了,明天再来")

    def draw(self) -> None:
        res = self.on_draw()
        if res is None:
            return
        self.rarity.setText(res["rarity"])
        self.rarity.setStyleSheet(f"color: {RARITY_COLOR[res['rarity']]};")
        self.name.setText(res["name"])
        if res["kind"] == "xp":
            self.note.setText("安慰奖")
        elif res["new"]:
            self.note.setText("✨ 新获得!已经可以在「趣味互动」里使用")
        else:
            self.note.setText(f"已经有了,换成 {res['xp']} 经验")
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
        self.pet_hit = PetHit(self.chat_panel, self.pat_pet)
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
            "owner": self.me.get("nick", "")})
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
            level = max(1, min(30, int(data.get("level", 1))))
        except (TypeError, ValueError):
            level = 1
        name = str(data.get("name") or "团团")[:8]
        wear = [w for w in (data.get("wear") or []) if isinstance(w, str) and w in ACC_BY_ID][:8]
        owner = d["nick"]
        v = TypingPet(self.chat_panel)
        v.visitor = True
        v.set_species(species)
        v.growth = PetGrowth({"xp": xp_for_level(level)})
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
        return {"species": self.pet.species, "name": g.name, "level": g.level, "wear": list(g.wear)}

    @staticmethod
    def clean_pet_info(data) -> dict:
        d = data if isinstance(data, dict) else {}
        try:
            level = max(1, min(30, int(d.get("level", 1))))
        except (TypeError, ValueError):
            level = 1
        return {"species": d.get("species") if d.get("species") in SPECIES else "cat",
                "name": str(d.get("name") or "团团")[:8], "level": level,
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
        v.growth = PetGrowth({"xp": xp_for_level(info_["level"])})
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
