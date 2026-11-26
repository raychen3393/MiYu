"""
密语 · 扔东西 / 揍宠物(主窗口的功能模块,2.4)

扔东西  右键成员(成员列表或消息上的头像)→「扔东西」→ 拖鞋、番茄、鸡蛋、炸弹、雪球、玫瑰、爱心、蛋糕。
        发一个 throw 事件给这个会话(群里大家都看得到),每台电脑自己画:聊天区正中间先放大播一遍
        (两边是两个人的头像,道具飞过去砸中、炸开、留下痕迹),然后聊天记录里留下一张动画卡片,点一下重播。
        被扔的是自己时聊天区上还会糊一大块,并且可以「扔回去」。连着扔同一样东西合并成一张卡片 ×N。
揍宠物  右键成员 →「揍 TA 的宠物」→ 拳头 / 枕头 / 玩具锤 / 弹脑门。
        结果由宠物主人的软件决定(它知道自己宠物的真实等级):被揍中、躲开,或者反击回来。
        主人那边宠物被揍得冒星星、头上鼓包;揍的人那边会冒出对方的宠物挨揍(或者躲开、反击你的宠物)。
        只是闹着玩:被揍只让宠物心情稍微差一点,不扣经验、不降级。
都有冷却和次数上限,设置里可以关掉「被扔时的特效」和「允许别人揍我的宠物」。
"""
from __future__ import annotations

import random
import time
import uuid

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QToolTip

from ..fun import ACC_BY_ID, SPECIES, WEAPON_BY_ID, WEAPONS, PetGrowth, TypingPet, xp_for_level
from ..throwfx import FRIENDLY, ITEM_BY_ID, ITEMS, ThrowLayer
from ..ui import label, make_menu, peer_avatar
from ..widgets import Conv, Msg

THROW_GAP = 1.5              # 自己连着扔:最短间隔(秒)
THROW_PER_MIN = 12           # 自己一分钟最多扔几次
RECV_GAP = 0.8               # 同一个人扔过来的,间隔太短的不显示(防刷屏)
RECV_PER_MIN = 15
COMBO_WINDOW = 4.0           # 这么久内连着扔同一样东西算连击
LINE_MERGE = 8.0             # 系统消息合并成一条的时间窗
BEAT_GAP = 6.0               # 揍同一只宠物的冷却
BEAT_PER_MIN = 6
BEAT_RECV_GAP = 3.0
BEAT_TIMEOUT = 5.0
BEAT_JOY = 3.0               # 被揍中一次心情 -3
BEAT_JOY_DAILY = 24          # 一天因为挨揍最多掉这么多心情
GUEST_SECS = 3.6
PILL_SECS = 6.0


class ThrowsMixin:
    """扔东西到头像上 + 揍别人的宠物。"""

    # ---------------------------------------------------------------- 钩子
    def _init_throws(self) -> None:
        self.throw_layer: ThrowLayer | None = None
        self._throw_sent: list[float] = []
        self._throw_recv: dict[str, list[float]] = {}
        self._throw_combo: dict[tuple, tuple[int, float]] = {}
        self._throw_lines: dict[str, dict] = {}
        self._beat_sent: dict[str, float] = {}
        self._beat_times: list[float] = []
        self._beat_recv: dict[str, float] = {}
        self._beat_pending: dict[str, dict] = {}
        self._beat_joy: tuple[str, float] = ("", 0.0)
        self.beat_guest: TypingPet | None = None
        self._beat_guest_until = 0.0
        self._throw_pill: QFrame | None = None
        self._pill_target: tuple | None = None
        self._throw_pill_until = 0.0
        self.throw_stats = {"thrown": 0, "hit_me": 0, "beat": 0, "beaten": 0}

    def _tick_throws(self, now: float) -> None:
        for nid in [k for k, v in self._beat_pending.items() if now > v["deadline"]]:
            v = self._beat_pending.pop(nid)
            conv = self.convs.get(v["conv"])
            if conv is not None:
                self._system(conv, f"{self._nick_of(v['to'])} 那边没有反应,这一下没揍成")
        if self.beat_guest is not None and now > self._beat_guest_until:
            self._drop_guest()
        if self._throw_pill is not None and self._throw_pill.isVisible() and now > self._throw_pill_until:
            self._throw_pill.hide()

    def _winstate_throws(self) -> None:
        if not self.window_visible() and self.throw_layer is not None:
            self.throw_layer.clear()

    def _place_throws(self) -> None:
        if self.beat_guest is not None:
            self._place_guest()
        if self._throw_pill is not None and self._throw_pill.isVisible():
            self._place_pill()

    # ---------------------------------------------------------------- 小工具
    def _my_id(self) -> str:
        return self.me.get("id", "")

    def _nick_of(self, pid: str, fallback: str = "某人") -> str:
        if pid == self._my_id():
            return "你"
        return (self.peers.get(pid) or {}).get("nick") or fallback

    def _fx_blocked(self) -> bool:
        """锁着屏、或者防偷看把窗口遮住了:特效一律不画。"""
        try:
            if self.locked:
                return True
            eye = getattr(self, "eye_overlay", None)
            return bool(eye is not None and eye.isVisible())
        except RuntimeError:
            return True

    def _hint(self, text: str) -> None:
        try:
            QToolTip.showText(QCursor.pos(), text, self)
        except Exception:                               # noqa: BLE001
            pass

    def _fx_sound(self, kind: str, gain: float = 0.8) -> None:
        if not self.fun.get("effects", True) or not self.window_visible():
            return
        try:
            from .. import sound
            self.keysound.play_pcm(sound.fx_pcm(kind), gain)
        except Exception:                               # noqa: BLE001
            pass

    def _interact_conv(self, pid: str, conv: Conv | None) -> Conv | None:
        """在哪个会话里扔:当前是群就在群里(大家都看得到),否则在私聊里。"""
        if conv is not None and conv.kind in ("lobby", "room"):
            return conv
        if conv is not None and conv.kind == "dm" and conv.target == pid:
            return conv
        return self.open_dm(pid, select=False)

    # ---------------------------------------------------------------- 菜单
    def add_fun_menus(self, menu, pid: str, conv: Conv | None) -> None:
        """右键菜单里加「扔东西」和「揍 TA 的宠物」两个子菜单。"""
        throw = make_menu(menu)
        throw.setTitle("🍅  扔东西")
        for iid, name, _unit, emo, _snd, _word in ITEMS:
            throw.addAction(f"{emo}  {name}", lambda i=iid: self.throw_at(pid, i, conv))
        menu.addMenu(throw)
        beat = make_menu(menu)
        beat.setTitle("👊  揍 TA 的宠物")
        for wid, name, emo in WEAPONS:
            beat.addAction(f"{emo}  {name}", lambda w=wid: self.beat_pet(pid, w, conv))
        menu.addMenu(beat)

    # ---------------------------------------------------------------- 特效层
    def _layer(self) -> ThrowLayer | None:
        if self.throw_layer is None:
            central = self.centralWidget()
            if central is None:
                return None
            self.throw_layer = ThrowLayer(central, lambda _pid: None, self._throw_screen, self._throw_ghost)
            self.throw_layer.on_hit = self._on_throw_hit
        return self.throw_layer

    def _throw_screen(self) -> QRectF:
        central = self.centralWidget()
        vp = self.msg_area.viewport()
        tl = vp.mapTo(central, QPoint(0, 0))
        return QRectF(tl.x(), tl.y(), vp.width(), vp.height())

    def _throw_ghost(self, pid: str):
        if pid == self._my_id():
            return peer_avatar(pid, self.me.get("nick", ""), 52)
        return peer_avatar(pid, self._nick_of(pid, "?"), 52)

    def _on_throw_hit(self, item: str, dst: str, big: bool) -> None:
        self._fx_sound(ITEM_BY_ID[item][4], 0.9 if big else 0.6)
        if big and item in ("slipper", "bomb"):
            self.shake()

    # ---------------------------------------------------------------- 扔东西
    def _next_combo(self, frm: str, to: str, item: str) -> int:
        now = time.monotonic()
        n, t = self._throw_combo.get((frm, to, item), (0, -1e9))
        n = n + 1 if now - t < COMBO_WINDOW else 1
        self._throw_combo[(frm, to, item)] = (n, now)
        if len(self._throw_combo) > 200:
            self._throw_combo = {k: v for k, v in self._throw_combo.items() if now - v[1] < COMBO_WINDOW}
        return n

    def throw_at(self, pid: str, item: str, conv: Conv | None = None) -> bool:
        me = self._my_id()
        if not pid or pid == me or item not in ITEM_BY_ID:
            return False
        if not (self.peers.get(pid) or {}).get("online"):
            self._hint("对方不在线")
            return False
        now = time.monotonic()
        self._throw_sent = [t for t in self._throw_sent if now - t < 60]
        if self._throw_sent and now - self._throw_sent[-1] < THROW_GAP:
            self._hint("手酸了,歇一下再扔~")
            return False
        if len(self._throw_sent) >= THROW_PER_MIN:
            self._hint("扔太多啦,过一会儿再来")
            return False
        conv = self._interact_conv(pid, conv)
        if conv is None:
            return False
        combo = self._next_combo(me, pid, item)
        scope, target = self.scope_target(conv)
        if not self.core.send_event(scope, target, "throw", {"to": pid, "it": item, "c": combo}):
            self._hint("没扔出去")
            return False
        self._throw_sent.append(now)
        self.throw_stats["thrown"] += 1
        self._play_throw(conv, me, pid, item, combo)
        return True

    def _ev_throw(self, conv: Conv, d: dict, data: dict) -> None:
        me = self._my_id()
        frm = d["peer"]
        item = data.get("it")
        to = me if conv.kind == "dm" else data.get("to")
        if item not in ITEM_BY_ID or not isinstance(to, str) or to == frm:
            return
        now = time.monotonic()
        times = [t for t in self._throw_recv.get(frm, []) if now - t < 60]
        if (times and now - times[-1] < RECV_GAP) or len(times) >= RECV_PER_MIN:
            return
        times.append(now)
        self._throw_recv[frm] = times
        combo = data.get("c")
        combo = max(1, min(99, combo)) if type(combo) is int else 1
        if to == me:
            self.throw_stats["hit_me"] += 1
        self._play_throw(conv, frm, to, item, combo)

    def _throw_text(self, frm: str, to: str, item: str, n: int) -> str:
        _id, name, unit, emo, _s, _w = ITEM_BY_ID[item]
        a, b = self._nick_of(frm), self._nick_of(to)
        count = f" {n} {unit}" if n > 1 else f"一{unit}"       # 「扔了一个番茄」/「扔了 3 个番茄」
        if item == "rose":
            return f"{emo} {a} 送给 {b} {count.strip()}玫瑰"
        if item == "heart":
            return f"{emo} {a} 给 {b} 比了{count}爱心"
        return f"{emo} {a} 向 {b} 扔了{count}{name}"

    def _play_throw(self, conv: Conv, frm: str, to: str, item: str, combo: int) -> None:
        """聊天记录里出一张动画卡片(连着扔同一样东西合并成一张 ×N);聊天区中间再放大播一遍。"""
        me = self._my_id()
        now = time.monotonic()
        key = (frm, to, item)
        line = self._throw_lines.get(conv.key)
        visible = conv.key == self.current_key and self.window_visible()
        if (line is not None and line["key"] == key and now - line["t"] < LINE_MERGE and conv.messages
                and conv.messages[-1] is line["msg"]):
            line["n"] += 1
            line["t"] = now
            m = line["msg"]
            m.text = self._throw_text(frm, to, item, line["n"])
            m.card["n"] = line["n"]
            b = self.bubbles.get(m.mid) if visible else None
            if b is not None and getattr(b, "card_w", None) is not None:
                b.card_w.update_state({"n": line["n"]})
        else:
            fp = self.peers.get(frm) or {}
            card = {"type": "throw", "item": item, "from": frm, "to": to, "fn": self._plain_nick(frm),
                    "tn": self._plain_nick(to), "n": 1, "seed": random.randrange(1, 1 << 30)}
            m = Msg(self._throw_text(frm, to, item, 1), sender=frm, nick=self._plain_nick(frm),
                    tag=self.me.get("tag", "") if frm == me else fp.get("tag", ""), mine=frm == me, card=card)
            self.fresh_cards.add(m.mid)
            self._add_message(conv, m, count_unread=False)
            self._throw_lines[conv.key] = {"key": key, "msg": m, "n": 1, "t": now}
        if not visible or self._fx_blocked():
            return                                       # 锁屏 / 防偷看遮住时不画(免得盖在上面露出是谁扔的)
        mine_target = to == me
        if self.fun.get("throw_fx", True):
            self._stage(item, frm, to, combo, big=mine_target)
        if mine_target and frm != me:
            if item in FRIENDLY:
                self.pet.say(random.choice(("哇,好浪漫~", "嘿嘿,收到啦", "脸红了…")), 2.2)
            else:
                self.pet.perk()
                self.pet.say(random.choice(("哎哟!", "谁扔的!", "呜…", "可恶!")), 1.6)
            self._show_pill(frm, item, conv)

    def _plain_nick(self, pid: str) -> str:
        if pid == self._my_id():
            return self.me.get("nick", "我")
        return (self.peers.get(pid) or {}).get("nick") or "某人"

    def _stage(self, item: str, frm: str, to: str, combo: int = 1, big: bool = False) -> None:
        layer = self._layer()
        if layer is None:
            return
        fa = peer_avatar(frm, self._plain_nick(frm), 72)
        ta = peer_avatar(to, self._plain_nick(to), 72)
        layer.stage(item, fa, ta, self._plain_nick(frm), self._plain_nick(to), combo, big)

    def replay_throw(self, m: Msg) -> None:
        """点了聊天里的卡片:中间再放大播一次(不会再糊屏幕)。"""
        c = m.card or {}
        if c.get("item") not in ITEM_BY_ID or self._fx_blocked():
            return
        self._stage(c["item"], str(c.get("from", "")), str(c.get("to", "")), int(c.get("n", 1) or 1), big=False)

    # ---------------------------------------------------------------- 「扔回去」
    def _show_pill(self, frm: str, item: str, conv: Conv) -> None:
        if self._throw_pill is None:
            pill = QFrame(self.chat_panel)
            pill.setObjectName("throwPill")
            lay = QHBoxLayout(pill)
            lay.setContentsMargins(14, 6, 6, 6)
            lay.setSpacing(10)
            pill.text = label("", "throwPillText")
            lay.addWidget(pill.text)
            pill.btn = QPushButton("")
            pill.btn.setObjectName("primary")
            pill.btn.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.btn.clicked.connect(self._pill_clicked)
            lay.addWidget(pill.btn)
            self._throw_pill = pill
        pill = self._throw_pill
        _id, name, _unit, emo, _s, _w = ITEM_BY_ID[item]
        verb = "送了你" if item in FRIENDLY else "向你扔了"
        pill.text.setText(f"{emo} {self._nick_of(frm)} {verb}{name}")
        pill.btn.setText("回送一个" if item in FRIENDLY else "扔回去")
        self._pill_target = (frm, item, conv)
        pill.adjustSize()
        pill.show()
        pill.raise_()
        self._place_pill()
        self._throw_pill_until = time.monotonic() + PILL_SECS

    def _pill_clicked(self) -> None:
        if self._pill_target is not None:
            self._throw_back(*self._pill_target)

    def _place_pill(self) -> None:
        pill = self._throw_pill
        if pill is None:
            return
        panel = self.chat_panel
        pill.adjustSize()
        pill.move(max(8, (panel.width() - pill.width()) // 2), 64)
        pill.raise_()

    def _throw_back(self, frm: str, item: str, conv: Conv) -> None:
        if self._throw_pill is not None:
            self._throw_pill.hide()
        self.throw_at(frm, item, conv if conv.kind != "dm" else None)

    # ---------------------------------------------------------------- 揍宠物
    def beat_pet(self, pid: str, weapon: str, conv: Conv | None = None) -> bool:
        me = self._my_id()
        if not pid or pid == me or weapon not in WEAPON_BY_ID:
            return False
        if not (self.peers.get(pid) or {}).get("online"):
            self._hint("对方不在线")
            return False
        now = time.monotonic()
        if now - self._beat_sent.get(pid, -1e9) < BEAT_GAP:
            self._hint("刚揍过,让它缓一缓~")
            return False
        self._beat_times = [t for t in self._beat_times if now - t < 60]
        if len(self._beat_times) >= BEAT_PER_MIN:
            self._hint("揍太多啦,歇一会儿")
            return False
        conv = self._interact_conv(pid, conv)
        if conv is None:
            return False
        nid = uuid.uuid4().hex[:12]
        scope, target = self.scope_target(conv)
        if not self.core.send_event(scope, target, "pbeat", {"to": pid, "w": weapon, "id": nid}):
            self._hint("没揍着")
            return False
        self._beat_sent[pid] = now
        self._beat_times.append(now)
        self._beat_pending[nid] = {"to": pid, "w": weapon, "conv": conv.key, "deadline": now + BEAT_TIMEOUT}
        return True

    def _pet_card_brief(self) -> dict:
        g = self.pet_growth
        return {"species": self.pet.species, "name": g.name, "level": g.level, "wear": list(g.wear)[:8]}

    def _beat_outcome(self, rng=random) -> str:
        lv = self.pet_growth.level
        dodge = min(0.30, 0.06 + lv * 0.008)
        counter = 0.0 if lv < 8 else min(0.18, 0.03 + (lv - 8) * 0.007)
        r = rng.random()
        if r < counter:
            return "counter"
        if r < counter + dodge:
            return "dodge"
        return "hit"

    def _ev_pbeat(self, conv: Conv, d: dict, data: dict) -> None:
        me = self._my_id()
        frm = d["peer"]
        to = me if conv.kind == "dm" else data.get("to")
        weapon, nid = data.get("w"), data.get("id")
        if to != me or weapon not in WEAPON_BY_ID or not isinstance(nid, str) or not (0 < len(nid) <= 16):
            return
        now = time.monotonic()
        if now - self._beat_recv.get(frm, -1e9) < BEAT_RECV_GAP:
            return
        self._beat_recv[frm] = now
        scope, target = self.scope_target(conv)
        reply = {"id": nid, "by": frm, "to": me, "w": weapon}
        if not self.fun.get("pet_beat", True):
            reply["o"] = "off"
        elif not self.fun.get("pet"):
            reply["o"] = "nopet"
        elif self.pet_away:
            reply["o"] = "away"
        else:
            reply["o"] = self._beat_outcome()
            reply["pet"] = self._pet_card_brief()
        only = frm if reply["o"] in ("off", "nopet", "away") else None
        self.core.send_event(scope, target, "pbeat_r", reply, to=only)
        self._apply_beat(conv, frm, me, weapon, reply["o"], reply.get("pet"), nid)

    def _ev_pbeat_r(self, conv: Conv, d: dict, data: dict) -> None:
        owner = d["peer"]
        if conv.kind != "dm" and data.get("to") != owner:
            return                                       # 只有宠物主人才能说结果
        by, weapon, outcome = data.get("by"), data.get("w"), data.get("o")
        if not isinstance(by, str) or weapon not in WEAPON_BY_ID:
            return
        if outcome not in ("hit", "dodge", "counter", "off", "nopet", "away"):
            return
        pet = data.get("pet") if isinstance(data.get("pet"), dict) else None
        self._apply_beat(conv, by, owner, weapon, outcome, pet, data.get("id"))

    def _apply_beat(self, conv: Conv, by: str, owner: str, weapon: str, outcome: str, pet: dict | None,
                    nid) -> None:
        me = self._my_id()
        if by == me:
            if not isinstance(nid, str) or self._beat_pending.pop(nid, None) is None:
                return                                   # 不是我发起的(或者已经超时了)
        info_ = self._clean_pet(pet)
        wname, wemo = WEAPON_BY_ID[weapon][1], WEAPON_BY_ID[weapon][2]
        a, b = self._nick_of(by), self._nick_of(owner)
        pname = info_["name"] if info_ else "宠物"
        whose = "你的" if owner == me else f"{b} 的"
        if outcome == "off":
            if by == me:
                self._system(conv, f"{b} 关掉了宠物互动,揍不了 TA 的宠物")
            return
        if outcome == "nopet":
            if by == me:
                self._system(conv, f"{b} 没有养宠物")
            return
        if outcome == "away":
            if by == me:
                self._system(conv, f"{b} 的宠物出门串门了,不在家")
            return
        if outcome == "hit":
            text = f"{wemo} {a} 用{wname}揍了{whose}{pname}"
        elif outcome == "dodge":
            text = f"{wemo} {a} 想用{wname}揍{whose}{pname},被它灵巧地躲开了"
        else:
            text = f"{wemo} {a} 想用{wname}揍{whose}{pname},反被它揍了回去!"
        self._system(conv, text)
        if by == me:
            self.throw_stats["beat"] += 1
        visible = conv.key == self.current_key and self.window_visible() and not self._fx_blocked()
        if owner == me:
            self.throw_stats["beaten"] += 1
            if outcome == "hit":
                self._beat_mood()
            if visible and self.pet.isVisible():
                self.pet.hurt(weapon, outcome)
                self._beat_sounds(weapon, outcome)
                lines = {"hit": ("呜呜…好疼", "你给我等着!", "哼,记住你了", "眼冒金星…"),
                         "dodge": ("略略略~", "打不着~", "太慢啦!"),
                         "counter": ("看招!", "吃我一爪!", "哼,不好惹吧")}[outcome]
                QTimer.singleShot(int(900 if outcome == "hit" else 600),
                                  lambda: self.pet.say(random.choice(lines), 2.2))
        elif by == me and visible:
            self._show_guest(owner, info_, weapon, outcome)
            self._beat_sounds(weapon, outcome)
            if outcome == "counter" and self.pet.isVisible() and not self.pet_away:
                QTimer.singleShot(780, lambda: self._counter_me())

    def _counter_me(self) -> None:
        self.pet.hurt("paw", "hit")
        self._fx_sound("bonk", 0.6)
        QTimer.singleShot(900, lambda: self.pet.say("呜…它好凶", 2))

    def _beat_sounds(self, weapon: str, outcome: str) -> None:
        if outcome == "hit":
            snd = {"fist": "bonk", "hammer": "bonk", "pillow": "puff", "flick": "flick"}.get(weapon, "bonk")
            QTimer.singleShot(380, lambda: self._fx_sound(snd, 0.7))
        else:
            QTimer.singleShot(300, lambda: self._fx_sound("swish", 0.6))
            if outcome == "counter":
                QTimer.singleShot(760, lambda: self._fx_sound("whack", 0.6))

    def _beat_mood(self) -> None:
        """挨揍只让心情稍微差一点(一天最多掉 BEAT_JOY_DAILY),不扣经验。"""
        today = time.strftime("%Y-%m-%d")
        day, lost = self._beat_joy
        if day != today:
            day, lost = today, 0.0
        if lost < BEAT_JOY_DAILY:
            amount = min(BEAT_JOY, BEAT_JOY_DAILY - lost)
            self.pet_growth.cheer(-amount)
            lost += amount
        self._beat_joy = (day, lost)

    @staticmethod
    def _clean_pet(pet: dict | None) -> dict | None:
        if not isinstance(pet, dict):
            return None
        species = pet.get("species") if pet.get("species") in SPECIES else "cat"
        try:
            level = max(1, min(30, int(pet.get("level", 1))))
        except (TypeError, ValueError):
            level = 1
        name = str(pet.get("name") or "团团")[:8]
        wear = [w for w in (pet.get("wear") or []) if isinstance(w, str) and w in ACC_BY_ID][:8]
        return {"species": species, "name": name, "level": level, "wear": wear}

    # ---- 揍的人这边:对方的宠物临时冒出来挨揍
    def _show_guest(self, owner: str, pet: dict | None, weapon: str, outcome: str) -> None:
        self._drop_guest()
        pet = pet or {"species": "cat", "name": "宠物", "level": 1, "wear": []}
        g = TypingPet(self.chat_panel)
        g.visitor = True
        g.set_species(pet["species"])
        g.growth = PetGrowth({"xp": xp_for_level(pet["level"])})
        g.growth.wear = list(pet["wear"])
        g.label = f"{self._nick_of(owner)[:6]}家的{pet['name']} Lv.{pet['level']}"
        g.show_combo = False
        g.show()
        self.beat_guest = g
        self._beat_guest_until = time.monotonic() + GUEST_SECS
        self._place_guest()
        g.hurt(weapon, outcome)
        lines = {"hit": ("呜哇!", "好疼!", "你等着!"), "dodge": ("略略略~", "打不着~"), "counter": ("看招!", "吃我一爪!")}
        QTimer.singleShot(700, lambda: self._guest_say(random.choice(lines[outcome])))

    def _guest_say(self, text: str) -> None:
        if self.beat_guest is not None:
            try:
                self.beat_guest.say(text, 1.8)
            except RuntimeError:
                self.beat_guest = None

    def _place_guest(self) -> None:
        g, pet = self.beat_guest, self.pet
        if g is None:
            return
        try:
            shift = 410 if self.visitor is not None else 205
            g.move(pet.x() - shift, pet.y())
            g.raise_()
        except RuntimeError:
            self.beat_guest = None

    def _drop_guest(self) -> None:
        g, self.beat_guest = self.beat_guest, None
        if g is not None:
            try:
                g.hide()
                g.deleteLater()
            except RuntimeError:
                pass
