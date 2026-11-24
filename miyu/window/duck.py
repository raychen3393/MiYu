"""
密语 · 谁是坏鸭的联网(主窗口的功能模块,2.4)。规则在 duck/rules.py,界面在 duck/window.py。

全部走密语原有的加密私聊事件(dk_*),不需要服务器、不连外网:
  房间   房主每 5 秒告诉在线的人一次(dk_room);别人点「加入」发 dk_join,房主把名单(dk_roster)发给房间里所有人
  邀请   dk_inv:对方弹窗问要不要来,同意就加入
  开局   房主建好对局,给每个人单独发 dk_start(只含他自己的身份;坏鸭还有同伴名单)
  游戏中 每个人每秒 12 次把自己的位置发给房主(dk_in),做动作发 dk_act;
         房主每秒 12 次给每个人发他看得见的画面(dk_st),有事发生时发 dk_ev,动作不行时回 dk_err
  离开   dk_leave(玩家走了)/ dk_end(房主关了房间)。房主 35 秒没动静,大家这局就结束;
         玩家网络断了 30 秒内连回来可以接着玩(期间别人看到他头上「掉线中」)
"""
from __future__ import annotations

import random
import time
import uuid

from PySide6.QtCore import QTimer

from ..dialogs import ask
from ..duck import world as Wd
from ..duck.client import Client
from ..duck.rules import DEFAULTS, MAX_PLAYERS, MIN_PLAYERS, Game, clean_settings

ROOM_EVERY = 5.0
ROOM_TTL = 16.0
NET_DT = 1 / 12               # 位置、画面每秒 12 次
SNAP_TIMEOUT = 35.0           # 这么久收不到房主的画面才算断开(房主那边 30 秒才判出局)
HOST_GONE = 12.0              # 等人时房主下线这么久:房间没了
JOIN_TTL = 8.0
INVITE_TTL = 40.0
MAX_NAME = 16


class DuckMixin:
    """谁是坏鸭:房间、邀请、开局、房主裁判、每个人的画面同步。"""

    # ---------------------------------------------------------------- 钩子
    def _init_duck(self) -> None:
        self.dk_rooms: dict[str, dict] = {}
        self.dk_room: dict | None = None
        self.dk_game: Game | None = None
        self.dk_client: Client | None = None
        self.dk_practice_on = False
        self.dk_win = None
        self._dk_host_timer: QTimer | None = None
        self._dk_net_acc = 0.0
        self._dk_last_in: dict[str, float] = {}
        self._dk_room_t = 0.0
        self._dk_joining: tuple[str, float] | None = None
        self._dk_invites: dict[str, float] = {}
        self._dk_host_seen = 0.0
        self._dk_over_t: float | None = None
        self.dk_stats = {"snaps_sent": 0, "inputs": 0}

    def _tick_duck(self, now: float) -> None:
        mono = time.monotonic()
        room = self.dk_room
        me = self.dk_my_id()
        if room is not None and room["host"] == me:
            if mono - self._dk_room_t >= ROOM_EVERY:
                self._dk_broadcast_room()
            if room["st"] == "wait":                      # 等人时:下线的人移出房间
                gone = [m for m in room["members"] if m["id"] != me and not self._dk_online(m["id"])]
                if gone:
                    room["members"] = [m for m in room["members"] if m not in gone]
                    self._dk_send_roster()
        elif room is not None:
            if self._dk_online(room["host"]):
                self._dk_host_seen = mono
            elif mono - self._dk_host_seen > HOST_GONE and self.dk_client is None:
                self._dk_drop_room("房主下线了,房间没了。")
        for rid in [k for k, r in self.dk_rooms.items() if mono - r["seen"] > ROOM_TTL]:
            self.dk_rooms.pop(rid, None)
        if self._dk_joining and mono > self._dk_joining[1]:
            self._dk_joining = None
            self._dk_toast("房主没有回应,没加进去。")

    def _peer_online_duck(self, pid: str) -> None:
        room = self.dk_room
        if room is not None and room["host"] == self.dk_my_id():
            self._dk_broadcast_room(only=pid)

    def _winstate_duck(self) -> None:
        pass

    # ---------------------------------------------------------------- 小工具
    def dk_my_id(self) -> str:
        return self.me.get("id", "")

    def dk_nick(self, pid: str) -> str:
        if pid == self.dk_my_id():
            return self.me.get("nick", "我")
        return (self.peers.get(pid) or {}).get("nick") or "?"

    def _dk_online(self, pid: str) -> bool:
        return pid == self.dk_my_id() or bool((self.peers.get(pid) or {}).get("online"))

    def _dk_send(self, pid: str, name: str, data: dict) -> bool:
        if pid == self.dk_my_id():
            return False
        try:
            return bool(self.core.send_event("dm", pid, name, data))
        except Exception:                                # noqa: BLE001
            return False

    def _dk_toast(self, text: str) -> None:
        if self._dk_win_alive():
            self.dk_win.toast(text)
        elif self.window_visible() and self.current is not None:
            self._system(self.current, f"🦆 谁是坏鸭:{text}")

    def _dk_win_alive(self) -> bool:
        try:
            return self.dk_win is not None and self.dk_win.isVisible()
        except RuntimeError:
            self.dk_win = None
            return False

    def dk_friends(self) -> list[dict]:
        me = self.dk_my_id()
        return [{"id": pid, "nick": p.get("nick", "?")} for pid, p in self.peers.items()
                if p.get("online") and pid != me]

    def dk_rooms_list(self) -> list[dict]:
        out = [dict(r) for r in self.dk_rooms.values() if self._dk_online(r["host"])]
        return sorted(out, key=lambda r: (r["st"] != "wait", -r["n"], r["name"]))

    def dk_is_host(self) -> bool:
        return self.dk_room is not None and self.dk_room["host"] == self.dk_my_id()

    def open_duck(self) -> None:
        from ..duck.window import DuckWindow
        win = self.dk_win
        if win is not None:
            try:
                win.isVisible()
            except RuntimeError:
                win = None
        if win is None:
            win = DuckWindow(self)
            self.dk_win = win
        if self.dk_client is not None and self.dk_client.phase != "over":
            win.go("game")
        elif self.dk_room is not None:
            win.go("room")
        else:
            win.go("lobby")
        win.show()
        win.raise_()
        win.activateWindow()

    def _dk_go(self, page: str) -> None:
        if self._dk_win_alive():
            self.dk_win.go(page)

    # ---------------------------------------------------------------- 房间
    def _dk_room_public(self) -> dict:
        r = self.dk_room
        return {"id": r["id"], "name": r["name"], "n": len(r["members"]), "st": r["st"],
                "host_nick": self.me.get("nick", "")}

    def _dk_broadcast_room(self, only: str | None = None, closed: bool = False) -> None:
        r = self.dk_room
        if r is None:
            return
        self._dk_room_t = time.monotonic()
        data = {"id": r["id"], "closed": True} if closed else self._dk_room_public()
        for pid in ([only] if only else [p["id"] for p in self.dk_friends()]):
            self._dk_send(pid, "dk_room", data)

    def _dk_send_roster(self) -> None:
        r = self.dk_room
        if r is None:
            return
        data = {"id": r["id"], "name": r["name"], "host": r["host"], "members": r["members"], "s": r["s"], "st": r["st"]}
        for m in r["members"]:
            self._dk_send(m["id"], "dk_roster", data)
        self._dk_broadcast_room()
        if self._dk_win_alive():
            self.dk_win.tick()

    def _dk_free_color(self, members: list[dict]) -> str:
        used = {m["color"] for m in members}
        return next((c[0] for c in Wd.COLORS if c[0] not in used), Wd.COLORS[0][0])

    def dk_create_room(self, name: str = "") -> bool:
        if self.dk_client is not None and self.dk_client.phase != "over":
            self._dk_toast("先退出正在进行的游戏。")
            return False
        if self.dk_room is not None:
            self.dk_leave_room(quiet=True)
        me = self.dk_my_id()
        name = (name or f"{self.me.get('nick', '我')}的房间")[:MAX_NAME]
        self.dk_room = {"id": uuid.uuid4().hex[:12], "name": name, "host": me,
                        "members": [{"id": me, "nick": self.me.get("nick", ""), "color": Wd.COLORS[0][0]}],
                        "s": dict(DEFAULTS), "st": "wait"}
        self._dk_broadcast_room()
        self._dk_go("room")
        return True

    def dk_join(self, rid: str) -> bool:
        info = self.dk_rooms.get(rid)
        if info is None or not self._dk_online(info["host"]):
            self._dk_toast("这个房间已经没了。")
            return False
        if self.dk_room is not None:
            if self.dk_room["id"] == rid:
                self._dk_go("room")
                return True
            self.dk_leave_room(quiet=True)
        self._dk_joining = (rid, time.monotonic() + JOIN_TTL)
        return self._dk_send(info["host"], "dk_join", {"id": rid, "nick": self.me.get("nick", "")})

    def dk_leave_room(self, quiet: bool = False) -> None:
        r = self.dk_room
        me = self.dk_my_id()
        if self.dk_practice_on:
            self._dk_end_game()
            self._dk_go("lobby")
            return
        if r is None:
            self._dk_end_game()
            self._dk_go("lobby")
            return
        if r["host"] == me:
            for m in r["members"]:
                self._dk_send(m["id"], "dk_end", {"id": r["id"]})
            self._dk_broadcast_room(closed=True)
        else:
            self._dk_send(r["host"], "dk_leave", {"id": r["id"]})
        self.dk_room = None
        self._dk_end_game()
        self._dk_go("lobby")
        if not quiet:
            self._dk_toast("已离开房间。")

    def _dk_drop_room(self, why: str) -> None:
        self.dk_room = None
        self._dk_end_game()
        self._dk_go("lobby")
        self._dk_toast(why)

    def dk_set_color(self, color: str) -> None:
        r = self.dk_room
        if r is None or color not in Wd.COLOR_BY_ID or r["st"] != "wait":
            return
        if r["host"] == self.dk_my_id():
            self._dk_apply_color(self.dk_my_id(), color)
        else:
            self._dk_send(r["host"], "dk_color", {"id": r["id"], "c": color})

    def _dk_apply_color(self, pid: str, color: str) -> None:
        r = self.dk_room
        if any(m["color"] == color and m["id"] != pid for m in r["members"]):
            return
        for m in r["members"]:
            if m["id"] == pid:
                m["color"] = color
        self._dk_send_roster()

    def dk_set_setting(self, key: str, value) -> None:
        r = self.dk_room
        if r is None or r["host"] != self.dk_my_id() or r["st"] != "wait":
            return
        r["s"] = clean_settings({**r["s"], key: value})
        self._dk_send_roster()

    def dk_invite(self, pid: str) -> None:
        r = self.dk_room
        if r is None:
            self._dk_toast("先创建或加入一个房间,再邀请别人。")
            return
        if self._dk_send(pid, "dk_inv", {"id": r["id"], "name": r["name"], "host": r["host"]}):
            self._dk_toast(f"已邀请 {self.dk_nick(pid)}。")

    # ---------------------------------------------------------------- 开局
    def dk_start(self) -> bool:
        r = self.dk_room
        me = self.dk_my_id()
        if r is None or r["host"] != me or r["st"] != "wait":
            return False
        r["members"] = [m for m in r["members"] if self._dk_online(m["id"])]
        if not (MIN_PLAYERS <= len(r["members"]) <= MAX_PLAYERS):
            self._dk_toast(f"要 {MIN_PLAYERS}~{MAX_PLAYERS} 个人才能开始。")
            self._dk_send_roster()
            return False
        now = time.monotonic()
        g = Game(r["members"], r["s"], seed=random.randrange(1 << 30), now=now)
        g.players[me]["host"] = True
        self.dk_game = g
        r["st"] = "play"
        self._dk_last_in = {pid: now for pid in g.players}
        for m in r["members"]:
            info = g.start_info_for(m["id"])
            if m["id"] == me:
                self._dk_begin(info, me)
            else:
                self._dk_send(m["id"], "dk_start", {"rid": r["id"], "info": info})
        self._dk_send_roster()
        self._dk_start_host_timer()
        self._dk_host_step()
        return True

    def dk_practice(self) -> None:
        if self.dk_client is not None and self.dk_client.phase != "over":
            self._dk_toast("先退出正在进行的游戏。")
            return
        if self.dk_room is not None:
            self.dk_leave_room(quiet=True)
        me = self.dk_my_id()
        now = time.monotonic()
        g = Game([{"id": me, "nick": self.me.get("nick", ""), "color": "purple"}], {"tasks": 5}, now=now,
                 practice=True)
        g.players[me]["host"] = True
        self.dk_game = g
        self.dk_practice_on = True
        self._dk_begin(g.start_info_for(me), me)
        self._dk_start_host_timer()
        self._dk_host_step()

    def _dk_begin(self, info: dict, host: str) -> None:
        now = time.monotonic()
        self.dk_client = Client(info, self.dk_my_id(), host, now)
        self._dk_host_seen = now
        self._dk_net_acc = 0.0
        if not self._dk_win_alive():
            self.open_duck()
        self.dk_win.start_game(self.dk_client, reveal=not self.dk_practice_on)

    def _dk_start_host_timer(self) -> None:
        if self._dk_host_timer is None:
            self._dk_host_timer = QTimer(self)
            self._dk_host_timer.setInterval(int(NET_DT * 1000))
            self._dk_host_timer.timeout.connect(self._dk_host_step)
        self._dk_host_timer.start()

    def _dk_end_game(self) -> None:
        if self._dk_host_timer is not None:
            self._dk_host_timer.stop()
        self.dk_game = None
        self.dk_client = None
        self.dk_practice_on = False
        if self._dk_win_alive():
            self.dk_win.pages["game"].stop()

    # ---------------------------------------------------------------- 房主:每一拍
    def _dk_host_step(self) -> None:
        g = self.dk_game
        if g is None:
            return
        now = time.monotonic()
        me = self.dk_my_id()
        g.tick(now)
        self._dk_flush_events(g, now)
        for pid, p in g.players.items():
            if p["left"]:
                continue
            snap = g.snapshot_for(pid, now)
            if pid == me:
                if self.dk_client is not None:
                    self.dk_client.apply_snapshot(snap, now)
            else:
                self._dk_send(pid, "dk_st", snap)
                self.dk_stats["snaps_sent"] += 1
        if g.winner:                                     # 结算画面发出去 2 秒后,房间回到等人状态
            if self._dk_over_t is None:
                self._dk_over_t = now
            elif now - self._dk_over_t > 2.0:
                self._dk_finish_host()

    def _dk_flush_events(self, g: Game, now: float) -> None:
        me = self.dk_my_id()
        per: dict[str, list] = {}
        for to, ev in g.take_events():
            targets = to if to is not None else [pid for pid, p in g.players.items() if not p["left"] or ev.get("e") in ("over", "left")]
            for pid in targets:
                per.setdefault(pid, []).append(ev)
        for pid, evs in per.items():
            if pid == me:
                for ev in evs:
                    self._dk_client_event(ev, now)
            else:
                self._dk_send(pid, "dk_ev", {"evs": evs})

    def _dk_finish_host(self) -> None:
        """这局结束了:房间回到等人状态(大家看完结算点「回到房间」就能再来一局)。"""
        if self._dk_host_timer is not None:
            self._dk_host_timer.stop()
        self._dk_over_t = None
        self.dk_game = None
        r = self.dk_room
        if r is not None and r["host"] == self.dk_my_id():
            r["st"] = "wait"
            r["members"] = [m for m in r["members"] if self._dk_online(m["id"])]
            self._dk_send_roster()

    # ---------------------------------------------------------------- 自己:每一帧
    def dk_frame(self, dt: float) -> None:
        c = self.dk_client
        if c is None:
            return
        now = time.monotonic()
        self._dk_net_acc += dt
        if self._dk_net_acc < NET_DT:
            return
        sent_dt, self._dk_net_acc = self._dk_net_acc, 0.0
        g = self.dk_game
        if g is not None:
            g.on_input(self.dk_my_id(), c.x, c.y, c.f, sent_dt, now)
        elif c.phase != "over":
            self._dk_send(c.host, "dk_in", {"x": round(c.x, 1), "y": round(c.y, 1), "f": c.f})
            if now - c.last_snap > SNAP_TIMEOUT:
                self._dk_toast("和房主断开了,这局结束。")
                c.over = {"win": None, "why": "和房主断开了", "roles": {}, "t": now}
                c.phase = "over"

    def dk_action(self, a: str, data: dict) -> None:
        c = self.dk_client
        if c is None:
            return
        g = self.dk_game
        if g is not None:
            err = g.act(self.dk_my_id(), a, data, time.monotonic())
            if err:
                self._dk_on_error(a, err)
            self._dk_flush_events(g, time.monotonic())
        else:
            self._dk_send(c.host, "dk_act", {"a": a, "d": data})

    def dk_vote(self, target: str) -> None:
        c = self.dk_client
        if c is None or c.phase != "meeting" or c.my_vote is not None or not c.alive:
            return
        c.my_vote = target
        self.dk_action("vote", {"t": target})

    def dk_chat(self, text: str) -> None:
        self.dk_action("chat", {"text": text[:120]})

    def _dk_on_error(self, a: str, err: str) -> None:
        c = self.dk_client
        if a == "vote" and c is not None and err != "已经投过了":
            c.my_vote = None
        if a != "fix" or err not in ("不用修",):
            self._dk_toast(err)

    def _dk_client_event(self, ev: dict, now: float) -> None:
        c = self.dk_client
        if c is None:
            return
        c.apply_event(ev, now)
        e = ev.get("e")
        if e == "sabo":
            if ev.get("k") == "lights":
                self._dk_toast("💡 有人关灯了!好鹅快去配电室修电闸。")
            else:
                self._dk_toast(f"🚪 {Wd.room_name(ev.get('room'))}的门被锁上了(10 秒)。")
        elif e == "fixed":
            self._dk_toast(f"⚡ {c.nick(ev.get('by', ''))} 修好了电闸。")
        elif e == "left":
            self._dk_toast(f"{c.nick(ev.get('id', ''))} 离开了游戏。")
        elif e in ("killed", "dead", "kill_fx"):
            self._fx_sound_safe("bonk")
        elif e == "checked":
            who = c.nick(ev.get("t", ""))
            self._dk_toast(f"🔍 查验结果:{who} " + ("是坏鸭!" if ev.get("duck") else "不是坏鸭。"))
        elif e == "meeting":
            self._fx_sound_safe("chime")

    def _fx_sound_safe(self, kind: str) -> None:
        try:
            from .. import sound
            if self.fun.get("effects", True):
                self.keysound.play_pcm(sound.fx_pcm(kind), 0.6)
        except Exception:                                # noqa: BLE001
            pass

    def dk_back_to_room(self) -> None:
        self._dk_end_game()
        self._dk_go("room" if self.dk_room is not None else "lobby")

    def dk_quit_game(self) -> None:
        c = self.dk_client
        if c is None:
            self._dk_go("room" if self.dk_room else "lobby")
            return
        if self.dk_practice_on:
            self._dk_end_game()
            self._dk_go("lobby")
            return
        if c.phase == "over":
            self.dk_back_to_room()
            return
        host = self.dk_is_host()
        text = "你是房主,退出会让这局结束、房间解散。" if host else "退出后你就离开这局了(算出局)。"
        if not ask(self.dk_win, "退出游戏?", text, "退出", "继续玩"):
            return
        self.dk_leave_room()

    def dk_can_close(self) -> bool:
        c = self.dk_client
        if c is not None and c.phase != "over" and not self.dk_practice_on:
            if not ask(self.dk_win, "游戏还在进行", "关掉窗口会退出这局。确定吗?", "退出", "继续玩"):
                return False
            self.dk_leave_room(quiet=True)
            return True
        if self.dk_practice_on:
            self._dk_end_game()
        if self.dk_room is not None:
            self.dk_leave_room(quiet=True)
        return True

    # ---------------------------------------------------------------- 收事件
    def _ev_dk(self, d: dict, name: str, data: dict) -> None:
        fn = getattr(self, "_dk_ev_" + name[3:], None)
        if fn is not None and isinstance(data, dict):
            fn(d["peer"], data)

    def _dk_ev_room(self, pid: str, data: dict) -> None:
        rid = data.get("id")
        if not isinstance(rid, str) or len(rid) > 16:
            return
        if data.get("closed"):
            self.dk_rooms.pop(rid, None)
            return
        n, st, name = data.get("n"), data.get("st"), data.get("name")
        if type(n) is not int or st not in ("wait", "play") or not isinstance(name, str):
            return
        self.dk_rooms[rid] = {"id": rid, "name": name[:MAX_NAME], "host": pid, "n": max(1, min(MAX_PLAYERS, n)),
                              "st": st, "host_nick": self.dk_nick(pid), "seen": time.monotonic()}

    def _dk_ev_join(self, pid: str, data: dict) -> None:
        r = self.dk_room
        if r is None or r["host"] != self.dk_my_id() or data.get("id") != r["id"]:
            self._dk_send(pid, "dk_err", {"text": "这个房间已经没了。", "join": True})
            return
        if any(m["id"] == pid for m in r["members"]):
            self._dk_send_roster()
            return
        if r["st"] != "wait":
            self._dk_send(pid, "dk_err", {"text": "这个房间已经开始游戏了。", "join": True})
            return
        if len(r["members"]) >= MAX_PLAYERS:
            self._dk_send(pid, "dk_err", {"text": "房间满了。", "join": True})
            return
        r["members"].append({"id": pid, "nick": self.dk_nick(pid)[:20], "color": self._dk_free_color(r["members"])})
        self._dk_send_roster()
        self._dk_toast(f"{self.dk_nick(pid)} 进房间了。")

    def _dk_ev_roster(self, pid: str, data: dict) -> None:
        me = self.dk_my_id()
        rid, members = data.get("id"), data.get("members")
        if data.get("host") != pid or not isinstance(members, list) or not isinstance(rid, str):
            return
        joining = self._dk_joining is not None and self._dk_joining[0] == rid
        if self.dk_room is not None and self.dk_room["id"] != rid:
            return
        if self.dk_room is None and not joining:
            return
        clean = []
        for m in members[:MAX_PLAYERS]:
            if isinstance(m, dict) and isinstance(m.get("id"), str) and m.get("color") in Wd.COLOR_BY_ID:
                clean.append({"id": m["id"], "nick": str(m.get("nick", "?"))[:20], "color": m["color"]})
        if not any(m["id"] == me for m in clean):
            if self.dk_room is not None:
                self._dk_drop_room("你已经不在这个房间里了。")
            return
        first = self.dk_room is None
        self.dk_room = {"id": rid, "name": str(data.get("name", "房间"))[:MAX_NAME], "host": pid, "members": clean,
                        "s": clean_settings(data.get("s")), "st": "play" if data.get("st") == "play" else "wait"}
        self._dk_joining = None
        self._dk_host_seen = time.monotonic()
        if first:
            if not self._dk_win_alive():
                self.open_duck()
            self._dk_go("room")
        elif self._dk_win_alive() and self.dk_win.current() == "room":
            self.dk_win.pages["room"].refresh()

    def _dk_ev_leave(self, pid: str, data: dict) -> None:
        r = self.dk_room
        if r is None or r["host"] != self.dk_my_id() or data.get("id") != r["id"]:
            return
        if not any(m["id"] == pid for m in r["members"]):
            return
        r["members"] = [m for m in r["members"] if m["id"] != pid]
        if self.dk_game is not None:
            self.dk_game.leave(pid, time.monotonic())
        self._dk_send_roster()
        self._dk_toast(f"{self.dk_nick(pid)} 离开了房间。")

    def _dk_ev_end(self, pid: str, data: dict) -> None:
        r = self.dk_room
        if r is not None and r["host"] == pid and data.get("id") == r["id"]:
            self._dk_drop_room("房主解散了房间。")

    def _dk_ev_color(self, pid: str, data: dict) -> None:
        r = self.dk_room
        if r is None or r["host"] != self.dk_my_id() or data.get("id") != r["id"] or r["st"] != "wait":
            return
        if data.get("c") in Wd.COLOR_BY_ID and any(m["id"] == pid for m in r["members"]):
            self._dk_apply_color(pid, data["c"])

    def _dk_ev_inv(self, pid: str, data: dict) -> None:
        rid, host = data.get("id"), data.get("host")
        if not isinstance(rid, str) or not isinstance(host, str) or len(rid) > 16:
            return
        if self.dk_room is not None and self.dk_room["id"] == rid:
            return
        now = time.monotonic()
        if now - self._dk_invites.get(pid, -1e9) < 10:
            return
        self._dk_invites[pid] = now
        name = str(data.get("name", "房间"))[:MAX_NAME]
        if rid not in self.dk_rooms and self._dk_online(host):
            self.dk_rooms[rid] = {"id": rid, "name": name, "host": host, "n": 1, "st": "wait",
                                  "host_nick": self.dk_nick(host), "seen": now}
        QTimer.singleShot(0, lambda: self._dk_ask_invite(pid, rid, name, now))

    def _dk_ask_invite(self, pid: str, rid: str, name: str, t: float) -> None:
        if time.monotonic() - t > INVITE_TTL:
            return
        if self.dk_client is not None and self.dk_client.phase != "over":
            return
        parent = self.dk_win if self._dk_win_alive() else self
        if ask(parent, "🦆 谁是坏鸭", f"{self.dk_nick(pid)} 邀请你来玩谁是坏鸭(房间「{name}」),去吗?", "去!", "不了"):
            if not self._dk_win_alive():
                self.open_duck()
            self.dk_join(rid)

    def _dk_ev_err(self, pid: str, data: dict) -> None:
        text = data.get("text")
        if not isinstance(text, str):
            return
        if data.get("join"):
            if self._dk_joining is not None:
                self._dk_joining = None
                self._dk_toast(text[:60])
            return
        c = self.dk_client
        if c is not None and pid == c.host:
            self._dk_on_error(str(data.get("a", "")), text[:60])

    def _dk_ev_start(self, pid: str, data: dict) -> None:
        r = self.dk_room
        info = data.get("info")
        if r is None or r["host"] != pid or data.get("rid") != r["id"] or not isinstance(info, dict):
            return
        if info.get("role") not in ("goose", "duck", "dodo"):
            return
        r["st"] = "play"
        self._dk_begin(info, pid)

    def _dk_ev_st(self, pid: str, data: dict) -> None:
        c = self.dk_client
        if c is not None and pid == c.host and self.dk_game is None:
            c.apply_snapshot(data, time.monotonic())

    def _dk_ev_ev(self, pid: str, data: dict) -> None:
        c = self.dk_client
        evs = data.get("evs")
        if c is None or pid != c.host or not isinstance(evs, list):
            return
        now = time.monotonic()
        for ev in evs[:40]:
            if isinstance(ev, dict):
                self._dk_client_event(ev, now)

    def _dk_ev_in(self, pid: str, data: dict) -> None:
        g = self.dk_game
        if g is None or pid not in g.players:
            return
        now = time.monotonic()
        dt = now - self._dk_last_in.get(pid, now - NET_DT)
        self._dk_last_in[pid] = now
        self.dk_stats["inputs"] += 1
        g.on_input(pid, data.get("x"), data.get("y"), data.get("f"), dt, now)

    def _dk_ev_act(self, pid: str, data: dict) -> None:
        g = self.dk_game
        if g is None or pid not in g.players:
            return
        a = data.get("a")
        d = data.get("d") if isinstance(data.get("d"), dict) else {}
        err = g.act(pid, a if isinstance(a, str) else "", d, time.monotonic())
        if err:
            self._dk_send(pid, "dk_err", {"text": err, "a": a if isinstance(a, str) else ""})
        self._dk_flush_events(g, time.monotonic())
