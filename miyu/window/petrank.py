"""
密语 · 群里的宠物等级排行榜(主窗口的功能模块,2.4)

名片  每个人把自己宠物的等级、经验签好名发到群里(pcard):上线时、升级时、隔 10 分钟。
      有人进群 / 上线时,把我手上这个群成员的名片一起转给他(pcards),所以不在线的人也上榜(标注多久前)。
榜单  等级榜(等级 → 经验)、本周成长榜(本机时间周一 0 点起涨的经验)、群宠物贡献榜(暗号群里一起养的群宠物)。
      自己那一行高亮,底下一条告诉你排第几、离上一名还差多少经验。
数据格式、验签和合理性检查见 miyu/petrank.py。
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from .. import petrank as PR
from ..dialogs import Dialog
from ..fun import SPECIES
from ..gomoku.widgets import Segmented, elide
from ..gomoku.window import avatar_label, clear_layout, scroll_list
from ..ui import label
from ..widgets import Conv

CARD_EVERY = 600.0           # 10 分钟发一次名片(升级、改名、换装时马上发)
CHECK_EVERY = 20.0
MEMBER_DAYS = 30             # 30 天内在群里见过的人才算这个群的成员
STALE_DAYS = 14              # 不在线、超过 14 天没更新的名片不上榜(多半是旧身份)
BATCH = 80


class PetRankMixin:
    """群里的宠物等级排行榜。"""

    # ---------------------------------------------------------------- 钩子
    def _init_petrank(self) -> None:
        self.pr_cards: dict[str, dict] = {}
        self.pr_flags: dict[str, bool] = {}
        self.pr_groups: dict[str, dict[str, int]] = {}     # 会话 key → {成员 id: 最后一次见到(毫秒)}
        self.pr_week: tuple[str, int] = ("", 0)            # (本周编号, 本周开始时的经验)
        self._pr_sig = None
        self._pr_sent_t = -1e9
        self._pr_check_t = 0.0
        self.pr_win = None

    def _restore_petrank(self, acct: dict, st: dict) -> None:
        d = acct.get("prank")
        if not isinstance(d, dict):
            return
        now_ms = int(time.time() * 1000)
        for raw in (d.get("cards") or [])[:PR.MAX_CARDS]:
            PR.accept(self.pr_cards, self.pr_flags, raw, now_ms)
        for pid in d.get("sus") or []:
            if isinstance(pid, str) and pid in self.pr_cards:
                self.pr_flags[pid] = True
        groups = d.get("groups")
        if isinstance(groups, dict):
            for key, mem in list(groups.items())[:100]:
                if isinstance(key, str) and isinstance(mem, dict):
                    self.pr_groups[key] = {k: v for k, v in list(mem.items())[:500]
                                           if isinstance(k, str) and type(v) is int}
        wk = d.get("week")
        if isinstance(wk, list) and len(wk) == 2 and isinstance(wk[0], str) and type(wk[1]) is int:
            self.pr_week = (wk[0], wk[1])

    def _save_petrank(self) -> dict:
        me = self.me.get("id", "")
        return {"prank": {"cards": [c for pid, c in self.pr_cards.items() if pid != me],
                          "sus": [pid for pid, v in self.pr_flags.items() if v],
                          "groups": self.pr_groups, "week": list(self.pr_week)}}

    def _tick_petrank(self, now: float) -> None:
        if now - self._pr_check_t < CHECK_EVERY:
            return
        self._pr_check_t = now
        card = self.pr_my_card(sign=False)
        sig = (card["lv"], card["xp"] // 500, card["n"], card["pn"], card["sp"], tuple(card["wear"]), card["wk"])
        if sig != self._pr_sig or now - self._pr_sent_t >= CARD_EVERY:
            self._pr_sig = sig
            self._pr_sent_t = now
            self.pr_broadcast()
        if self.pr_win is not None and self._pr_win_alive():
            self.pr_win.refresh()

    def _group_sync_petrank(self, conv: Conv, pid: str) -> None:
        """有人进群 / 上线:把我的名片和我知道的这个群成员的名片发给他。"""
        if not self.fun.get("pet"):
            return
        scope, target = self.scope_target(conv)
        cards = [self.pr_my_card()]
        members = self.pr_member_ids(conv)
        others = sorted((c for k, c in self.pr_cards.items() if k in members and k != pid),
                        key=lambda c: -c["ts"])[:BATCH]
        self.core.send_event(scope, target, "pcards", {"cs": cards + others}, to=pid)

    # ---------------------------------------------------------------- 我的名片
    def pr_my_card(self, sign: bool = True) -> dict:
        g = self.pet_growth
        wk = PR.week_key()
        if self.pr_week[0] != wk:                       # 新的一周:从现在的经验开始算本周成长
            self.pr_week = (wk, g.xp)
        card = PR.make_card(self.me.get("id", ""), self.me.get("nick", ""), self.pet.species, g.name, g.xp, wk,
                            self.pr_week[1], list(g.wear))
        if sign:
            try:
                card = PR.sign_card(card, self.core.identity)
            except Exception:                           # noqa: BLE001
                pass
        return card

    def pr_broadcast(self) -> None:
        if not self.fun.get("pet") or not self.me.get("id"):
            return
        card = self.pr_my_card()
        for conv in self.convs.values():
            if conv.kind not in ("lobby", "room"):
                continue
            if conv.kind == "lobby" and not self.me.get("lobby", True):
                continue
            scope, target = self.scope_target(conv)
            try:
                self.core.send_event(scope, target, "pcard", {"c": card})
            except Exception:                           # noqa: BLE001
                pass

    # ---------------------------------------------------------------- 收名片
    def _pr_seen(self, conv: Conv, pid: str) -> None:
        mem = self.pr_groups.setdefault(conv.key, {})
        mem[pid] = int(time.time() * 1000)
        if len(mem) > 500:
            for k in sorted(mem, key=mem.get)[:len(mem) - 500]:
                mem.pop(k, None)

    def _ev_pcard(self, conv: Conv, d: dict, data: dict) -> None:
        if conv.kind not in ("lobby", "room"):
            return
        raw = data.get("c")
        if not isinstance(raw, dict) or raw.get("id") != d["peer"]:
            return                                      # 直接发来的只收本人的
        card = PR.accept(self.pr_cards, self.pr_flags, raw)
        if card is not None or d["peer"] in self.pr_cards:
            self._pr_seen(conv, d["peer"])

    def _ev_pcards(self, conv: Conv, d: dict, data: dict) -> None:
        if conv.kind not in ("lobby", "room"):
            return
        cs = data.get("cs")
        if not isinstance(cs, list):
            return
        me = self.me.get("id", "")
        for raw in cs[:BATCH + 1]:
            if not isinstance(raw, dict) or raw.get("id") == me:
                continue
            card = PR.accept(self.pr_cards, self.pr_flags, raw)
            pid = raw.get("id")
            if (card is not None or pid in self.pr_cards) and isinstance(pid, str):
                if pid == d["peer"] or pid not in self.pr_groups.get(conv.key, {}):
                    self._pr_seen(conv, pid)

    # ---------------------------------------------------------------- 别人的宠物升级了
    def _ev_pet_lv(self, conv: Conv, d: dict, data: dict) -> None:
        if conv.kind not in ("lobby", "room"):
            return
        pid = d["peer"]
        now = time.monotonic()
        last = getattr(self, "_pr_lv_seen", {})
        if now - last.get(pid, -1e9) < 20:
            return                                      # 同一个人 20 秒内只显示一次(防刷屏)
        last[pid] = now
        self._pr_lv_seen = last
        from ..fun import ACC_BY_ID, PET_MAX_LEVEL, SPECIES
        lv = data.get("lv")
        if type(lv) is not int or not (2 <= lv <= PET_MAX_LEVEL):
            return
        clean = {"lv": lv, "name": str(data.get("name") or "宠物")[:8],
                 "sp": data.get("sp") if data.get("sp") in SPECIES else "cat",
                 "wear": [w for w in (data.get("wear") or []) if isinstance(w, str) and w in ACC_BY_ID][:8],
                 "form": str(data.get("form") or "")[:6]}
        self._add_level_card(conv, pid, d.get("nick") or self.peers.get(pid, {}).get("nick", "?"), clean)

    # ---------------------------------------------------------------- 榜单
    def pr_member_ids(self, conv: Conv) -> set[str]:
        """这个群的成员:现在在线的 + 30 天内在这个群见过的 + 我自己。"""
        if conv.kind == "lobby":
            online = {p["id"] for p in self.lobby_members()}
        elif conv.kind == "room":
            online = {p["id"] for p in self.room_members(conv.target)}
        else:
            online = {conv.target} if conv.target else set()
        cut = int((time.time() - MEMBER_DAYS * 86400) * 1000)
        seen = {k for k, t in self.pr_groups.get(conv.key, {}).items() if t >= cut}
        return online | seen | {self.me.get("id", "")}

    def pr_rows(self, conv: Conv, kind: str) -> list[dict]:
        me = self.me.get("id", "")
        cards = dict(self.pr_cards)
        if self.fun.get("pet"):
            mine = self.pr_my_card(sign=False)
            cards[me] = mine
        members = self.pr_member_ids(conv)
        online = {pid for pid, p in self.peers.items() if p.get("online")} | {me}
        cut = int((time.time() - STALE_DAYS * 86400) * 1000)
        live = {(c["n"], c["pn"], c["sp"]) for pid, c in cards.items() if pid in online and pid in members}
        keep = {}
        for pid, c in cards.items():
            if pid not in members:
                continue
            if pid not in online:
                if c["ts"] < cut or (c["n"], c["pn"], c["sp"]) in live:
                    continue                            # 很久没更新 / 同一个人换了身份:不重复上榜
            keep[pid] = c
        rows = PR.standings(keep, None, kind, flags=self.pr_flags)
        for r in rows:
            r["online"] = r["id"] in online
            r["me"] = r["id"] == me
        return rows

    def pr_gpet_rows(self, conv: Conv) -> list[dict]:
        if conv.kind != "room":
            return []
        gp = self.gpets.get(conv.target) if hasattr(self, "gpets") else None
        if gp is None:
            return []
        rows = []
        prev, rank = None, 0
        for i, (nick, xp, feeds) in enumerate(gp.top(100)):
            if (xp, feeds) != prev:
                rank, prev = i + 1, (xp, feeds)
            rows.append({"rank": rank, "nick": nick, "xp": xp, "feeds": feeds, "me": nick == self.me.get("nick")})
        return rows

    def _pr_win_alive(self) -> bool:
        try:
            return self.pr_win is not None and self.pr_win.isVisible()
        except RuntimeError:
            self.pr_win = None
            return False

    def open_pet_rank(self, conv: Conv | None = None) -> None:
        conv = conv or self.current
        if conv is None or conv.kind not in ("lobby", "room"):
            conv = self.convs.get("lobby")
        if conv is None:
            return
        if not self.fun.get("pet"):
            self._system(conv, "你还没有养宠物(设置 → 宠物 里打开),先养一只再来上榜吧。")
        self.pr_broadcast()
        win = self.pr_win
        if win is not None:
            try:
                win.isVisible()
            except RuntimeError:
                win = None
        if win is None:
            win = PetRankWindow(self)
            self.pr_win = win
        win.set_conv(conv)
        win.show()
        win.raise_()
        win.activateWindow()


# ====================================================================== 窗口
class PetRankWindow(Dialog):
    def __init__(self, w) -> None:
        super().__init__(w, "宠物排行榜")
        self.w = w
        self.conv: Conv | None = None
        self.setModal(False)
        self.resize(560, 640)
        self.setMinimumSize(440, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        self.title = label("", "dialogTitle")
        root.addWidget(self.title)
        self.tabs = Segmented([("level", "等级榜"), ("week", "本周成长"), ("gpet", "群宠物贡献")])
        self.tabs.changed.connect(lambda _k: self.refresh(force=True))
        root.addWidget(self.tabs)
        self.rule = label("", "faint", wrap=True)
        root.addWidget(self.rule)
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

    def set_conv(self, conv: Conv) -> None:
        self.conv = conv
        self.title.setText(f"🏆 宠物排行榜 · {conv.title}")
        gb = self.tabs.btns.get("gpet")
        if gb is not None:
            gb.setVisible(conv.kind == "room")
        if conv.kind != "room" and self.tabs.current == "gpet":
            self.tabs.select("level", emit=False)
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        conv = self.conv
        if conv is None:
            return
        kind = self.tabs.current
        if kind == "gpet":
            self._refresh_gpet(force)
            return
        rows = self.w.pr_rows(conv, kind)
        self.rule.setText({
            "level": "按宠物等级排,同级比累计经验。每个人的名片都用自己的身份签过名,别人冒充不了、也改不了;"
                     "不在线的人显示最后一次的数据。",
            "week": "按本周(本机时间周一 0:00 起)涨的经验排。每周一重新开始。"}[kind]
            + "  ⚠ = 经验涨得太快,可能用了改过的软件。")
        sig = (kind, tuple((r["id"], r["lv"], r["xp"], r["gain"], r["online"], r["nick"], r["sus"]) for r in rows))
        if sig != self._sig or force:
            self._sig = sig
            clear_layout(self.list)
            if not rows:
                empty = "这周还没有人的宠物长经验。" if kind == "week" else "群里还没有人的宠物名片。等大家上线一会儿就有了。"
                self.list.addWidget(label(empty, "gmEmpty", wrap=True, center=True))
            for r in rows[:100]:
                self.list.addWidget(self._row(r, kind))
            self.list.addStretch(1)
        rank, mine, above = PR.rank_of(rows, self.w.me.get("id", ""))
        if mine is None:
            self.me_text.setText("你还没上这个榜。" + ("这周多聊聊天、喂喂宠物就能上!" if kind == "week" else "打开宠物就能上榜。"))
        elif above is None:
            self.me_text.setText(f"你排第 {rank} 名,{self._score(mine, kind)} —— 全群第一!" if rank == 1 else
                                 f"你排第 {rank} 名,{self._score(mine, kind)}")
        else:
            if kind == "week":
                gap = f"还差 {above['gain'] - mine['gain']:,} 经验"
            elif above["lv"] > mine["lv"]:
                gap = f"还差 {above['lv'] - mine['lv']} 级(约 {above['xp'] - mine['xp']:,} 经验)"
            else:
                gap = f"还差 {above['xp'] - mine['xp']:,} 经验"
            self.me_text.setText(f"你排第 {rank} 名,{self._score(mine, kind)} · 距第 {above['rank']} 名「{above['nick']}」{gap}")

    @staticmethod
    def _score(r: dict, kind: str) -> str:
        return f"本周 +{r['gain']:,} 经验" if kind == "week" else f"{r['pet']} Lv.{r['lv']}"

    def _refresh_gpet(self, force: bool) -> None:
        conv = self.conv
        rows = self.w.pr_gpet_rows(conv)
        self.rule.setText("暗号群里大家一起养的群宠物:谁贡献的经验最多(聊天、喂食都算)。")
        sig = ("gpet", tuple((r["nick"], r["xp"], r["feeds"]) for r in rows))
        if sig != self._sig or force:
            self._sig = sig
            clear_layout(self.list)
            if not rows:
                self.list.addWidget(label("群宠物还没有人喂过。在群里聊聊天、右键群宠物喂它吧。", "gmEmpty",
                                          wrap=True, center=True))
            for r in rows:
                self.list.addWidget(self._gpet_row(r))
            self.list.addStretch(1)
        mine = next((r for r in rows if r["me"]), None)
        if mine is None:
            self.me_text.setText("你还没给群宠物贡献过经验。")
        else:
            above = next((r for r in reversed(rows[:rows.index(mine)]) if r["rank"] < mine["rank"]), None)
            text = f"你排第 {mine['rank']} 名,贡献了 {mine['xp']:,} 经验、喂了 {mine['feeds']} 次"
            if above is not None:
                text += f" · 距第 {above['rank']} 名还差 {above['xp'] - mine['xp']:,} 经验"
            self.me_text.setText(text)

    def _medal(self, rank: int) -> QWidget:
        rk = label({1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, str(rank)), "gmRank")
        rk.setFixedWidth(44)
        rk.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return rk

    def _row(self, r: dict, kind: str) -> QFrame:
        row = QFrame()
        row.setObjectName("gmRankMe" if r["me"] else "gmRankRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 7, 16, 7)
        lay.setSpacing(10)
        lay.addWidget(self._medal(r["rank"]))
        lay.addWidget(avatar_label(r["id"], r["nick"], 34))
        col = QVBoxLayout()
        col.setSpacing(0)
        name = label("", "gmRowTitle")
        elide(name, r["nick"] + ("(我)" if r["me"] else "") + ("  ⚠" if r["sus"] else ""), 200)
        col.addWidget(name)
        sp = SPECIES.get(r["species"], SPECIES["cat"])["label"]
        sub = f"{PR.SPECIES_ICON.get(r['species'], '🐾')} {r['pet']} · {sp} · {r['form']}"
        if not r["online"]:
            sub += f" · {PR.ago(r['ts'])}"
        subl = label("", "gmRowSub")
        elide(subl, sub, 230)
        col.addWidget(subl)
        lay.addLayout(col, 1)
        if kind == "week":
            big, small = f"+{r['gain']:,}", f"Lv.{r['lv']}"
        else:
            big, small = f"Lv.{r['lv']}", f"{r['xp']:,} 经验"
        right = QVBoxLayout()
        right.setSpacing(0)
        b = label(big, "gmNum")
        b.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        s = label(small, "gmRowSub")
        s.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(b)
        right.addWidget(s)
        lay.addLayout(right)
        if r["sus"]:
            row.setToolTip("这只宠物的经验涨得比一整天不停打字还快,可能用了改过的软件。")
        return row

    def _gpet_row(self, r: dict) -> QFrame:
        row = QFrame()
        row.setObjectName("gmRankMe" if r["me"] else "gmRankRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 9, 16, 9)
        lay.setSpacing(10)
        lay.addWidget(self._medal(r["rank"]))
        name = label("", "gmRowTitle")
        elide(name, r["nick"] + ("(我)" if r["me"] else ""), 220)
        lay.addWidget(name, 1)
        lay.addWidget(label(f"喂了 {r['feeds']} 次", "gmRowSub"))
        n = label(f"{r['xp']:,}", "gmNum")
        n.setMinimumWidth(70)
        n.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(n)
        return row
