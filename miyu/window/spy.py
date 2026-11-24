"""
密语 · 谁是卧底的联网(主窗口的功能模块,2.5)。规则在 spy/rules.py,界面在 spy/window.py。

全部走密语原有的加密私聊事件(sp_*),房主当裁判:
  房间   房主每 5 秒告诉在线的人一次(sp_room);点「加入」发 sp_join,房主把名单(sp_roster)发给房间里所有人
  邀请   sp_inv:对方弹窗问要不要来
  开局   房主给每个人单独发 sp_start(只含他自己的词)
  游戏中 每个人的操作发 sp_act(描述、聊天、投票、白板猜词);局面一变,房主就把每个人能看到的局面发过去(sp_st),
         平时每 2 秒补发一次(防丢)。出局的人说的话只发给出局的人
"""
from __future__ import annotations

import random
import time
import uuid

from PySide6.QtCore import QTimer

from ..dialogs import ask
from ..spy.client import SpyClient
from ..spy.rules import DEFAULTS, MAX_PLAYERS, MIN_PLAYERS, Game, clean_settings

ROOM_EVERY = 5.0
ROOM_TTL = 16.0
STATE_EVERY = 2.0
HOST_GONE = 15.0
STATE_TIMEOUT = 25.0
JOIN_TTL = 8.0
INVITE_TTL = 40.0
MAX_NAME = 16
RECENT_WORDS = 30


class SpyMixin:
    """谁是卧底:房间、邀请、开局、房主裁判、局面同步。"""

    def _init_spy(self) -> None:
        self.sp_rooms: dict[str, dict] = {}
        self.sp_room: dict | None = None
        self.sp_game: Game | None = None
        self.sp_client: SpyClient | None = None
        self.sp_win = None
        self._sp_timer: QTimer | None = None
        self._sp_sent: dict[str, tuple[int, float]] = {}
        self._sp_room_t = 0.0
        self._sp_joining: tuple[str, float] | None = None
        self._sp_invites: dict[str, float] = {}
        self._sp_host_seen = 0.0
        self._sp_recent: list[tuple[str, str]] = []
        self._sp_over_t: float | None = None

    def _tick_spy(self, now: float) -> None:
        mono = time.monotonic()
        room = self.sp_room
        me = self.sp_my_id()
        if room is not None and room["host"] == me:
            if mono - self._sp_room_t >= ROOM_EVERY:
                self._sp_broadcast_room()
            if room["st"] == "wait":
                gone = [m for m in room["members"] if m["id"] != me and not self._sp_online(m["id"])]
                if gone:
                    room["members"] = [m for m in room["members"] if m not in gone]
                    self._sp_send_roster()
            if self.sp_game is not None:                   # 游戏中下线的人:当他离开
                for pid in list(self.sp_game.roles):
                    if pid != me and pid not in self.sp_game.left and not self._sp_online(pid):
                        self.sp_game.leave(pid, mono)
        elif room is not None:
            if self._sp_online(room["host"]):
                self._sp_host_seen = mono
            elif mono - self._sp_host_seen > HOST_GONE:
                self._sp_drop_room("房主下线了,房间没了。")
        c = self.sp_client
        if c is not None and self.sp_game is None and c.phase != "over" and mono - c.last_state > STATE_TIMEOUT:
            c.over = {"win": None, "why": "和房主断开了", "roles": {}}
            c.phase = "over"
        for rid in [k for k, r in self.sp_rooms.items() if mono - r["seen"] > ROOM_TTL]:
            self.sp_rooms.pop(rid, None)
        if self._sp_joining and mono > self._sp_joining[1]:
            self._sp_joining = None
            self._sp_toast("房主没有回应,没加进去。")

    def _peer_online_spy(self, pid: str) -> None:
        room = self.sp_room
        if room is not None and room["host"] == self.sp_my_id():
            self._sp_broadcast_room(only=pid)

    # ---------------------------------------------------------------- 小工具
    def sp_my_id(self) -> str:
        return self.me.get("id", "")

    def sp_nick(self, pid: str) -> str:
        if pid == self.sp_my_id():
            return self.me.get("nick", "我")
        return (self.peers.get(pid) or {}).get("nick") or "?"

    def _sp_online(self, pid: str) -> bool:
        return pid == self.sp_my_id() or bool((self.peers.get(pid) or {}).get("online"))

    def _sp_send(self, pid: str, name: str, data: dict) -> bool:
        if pid == self.sp_my_id():
            return False
        try:
            return bool(self.core.send_event("dm", pid, name, data))
        except Exception:                                # noqa: BLE001
            return False

    def _sp_win_alive(self) -> bool:
        try:
            return self.sp_win is not None and self.sp_win.isVisible()
        except RuntimeError:
            self.sp_win = None
            return False

    def _sp_toast(self, text: str) -> None:
        if self._sp_win_alive():
            self.sp_win.toast(text)
        elif self.window_visible() and self.current is not None:
            self._system(self.current, f"🕵 谁是卧底:{text}")

    def _sp_go(self, page: str) -> None:
        if self._sp_win_alive():
            self.sp_win.go(page)

    def sp_friends(self) -> list[dict]:
        me = self.sp_my_id()
        return [{"id": pid, "nick": p.get("nick", "?")} for pid, p in self.peers.items() if p.get("online") and pid != me]

    def sp_rooms_list(self) -> list[dict]:
        out = [dict(r) for r in self.sp_rooms.values() if self._sp_online(r["host"])]
        return sorted(out, key=lambda r: (r["st"] != "wait", -r["n"], r["name"]))

    def open_spy(self) -> None:
        from ..spy.window import SpyWindow
        win = self.sp_win
        if win is not None:
            try:
                win.isVisible()
            except RuntimeError:
                win = None
        if win is None:
            win = SpyWindow(self)
            self.sp_win = win
        if self.sp_client is not None and self.sp_client.phase != "over":
            win.go("game")
        elif self.sp_room is not None:
            win.go("room")
        else:
            win.go("lobby")
        win.show()
        win.raise_()
        win.activateWindow()

    # ---------------------------------------------------------------- 房间
    def _sp_broadcast_room(self, only: str | None = None, closed: bool = False) -> None:
        r = self.sp_room
        if r is None:
            return
        self._sp_room_t = time.monotonic()
        data = {"id": r["id"], "closed": True} if closed else {
            "id": r["id"], "name": r["name"], "n": len(r["members"]), "st": r["st"], "host_nick": self.me.get("nick", "")}
        for pid in ([only] if only else [p["id"] for p in self.sp_friends()]):
            self._sp_send(pid, "sp_room", data)

    def _sp_send_roster(self) -> None:
        r = self.sp_room
        if r is None:
            return
        data = {"id": r["id"], "name": r["name"], "host": r["host"], "members": r["members"], "s": r["s"], "st": r["st"]}
        for m in r["members"]:
            self._sp_send(m["id"], "sp_roster", data)
        self._sp_broadcast_room()
        if self._sp_win_alive():
            self.sp_win.tick()

    def sp_create_room(self, name: str = "") -> bool:
        if self.sp_client is not None and self.sp_client.phase != "over":
            self._sp_toast("先退出正在进行的游戏。")
            return False
        if self.sp_room is not None:
            self.sp_leave_room(quiet=True)
        me = self.sp_my_id()
        self.sp_room = {"id": uuid.uuid4().hex[:12], "name": (name or f"{self.me.get('nick', '我')}的房间")[:MAX_NAME],
                        "host": me, "members": [{"id": me, "nick": self.me.get("nick", "")}], "s": dict(DEFAULTS),
                        "st": "wait"}
        self._sp_broadcast_room()
        self._sp_go("room")
        return True

    def sp_join(self, rid: str) -> bool:
        info = self.sp_rooms.get(rid)
        if info is None or not self._sp_online(info["host"]):
            self._sp_toast("这个房间已经没了。")
            return False
        if self.sp_room is not None:
            if self.sp_room["id"] == rid:
                self._sp_go("room")
                return True
            self.sp_leave_room(quiet=True)
        self._sp_joining = (rid, time.monotonic() + JOIN_TTL)
        return self._sp_send(info["host"], "sp_join", {"id": rid})

    def sp_leave_room(self, quiet: bool = False) -> None:
        r = self.sp_room
        if r is not None:
            if r["host"] == self.sp_my_id():
                for m in r["members"]:
                    self._sp_send(m["id"], "sp_end", {"id": r["id"]})
                self._sp_broadcast_room(closed=True)
            else:
                self._sp_send(r["host"], "sp_leave", {"id": r["id"]})
        self.sp_room = None
        self._sp_end_game()
        self._sp_go("lobby")
        if not quiet and r is not None:
            self._sp_toast("已离开房间。")

    def _sp_drop_room(self, why: str) -> None:
        self.sp_room = None
        self._sp_end_game()
        self._sp_go("lobby")
        self._sp_toast(why)

    def sp_set_setting(self, key: str, value) -> None:
        r = self.sp_room
        if r is None or r["host"] != self.sp_my_id() or r["st"] != "wait":
            return
        r["s"] = clean_settings({**r["s"], key: value})
        self._sp_send_roster()

    def sp_invite(self, pid: str) -> None:
        r = self.sp_room
        if r is None:
            self._sp_toast("先创建或加入一个房间,再邀请别人。")
            return
        if self._sp_send(pid, "sp_inv", {"id": r["id"], "name": r["name"], "host": r["host"]}):
            self._sp_toast(f"已邀请 {self.sp_nick(pid)}。")

    # ---------------------------------------------------------------- 开局 / 裁判
    def sp_start(self) -> bool:
        r = self.sp_room
        me = self.sp_my_id()
        if r is None or r["host"] != me or r["st"] != "wait":
            return False
        r["members"] = [m for m in r["members"] if self._sp_online(m["id"])]
        if not (MIN_PLAYERS <= len(r["members"]) <= MAX_PLAYERS):
            self._sp_toast(f"要 {MIN_PLAYERS}~{MAX_PLAYERS} 个人才能开始。")
            self._sp_send_roster()
            return False
        now = time.monotonic()
        g = Game(r["members"], r["s"], seed=random.randrange(1 << 30), now=now, avoid=set(self._sp_recent))
        self._sp_recent = (self._sp_recent + [(g.civ_word, g.spy_word), (g.spy_word, g.civ_word)])[-RECENT_WORDS * 2:]
        self.sp_game = g
        self._sp_sent = {}
        r["st"] = "play"
        for m in r["members"]:
            info = g.start_info_for(m["id"])
            if m["id"] == me:
                self._sp_begin(info, me)
            else:
                self._sp_send(m["id"], "sp_start", {"rid": r["id"], "info": info})
        self._sp_send_roster()
        if self._sp_timer is None:
            self._sp_timer = QTimer(self)
            self._sp_timer.setInterval(250)
            self._sp_timer.timeout.connect(self._sp_host_step)
        self._sp_timer.start()
        self._sp_host_step()
        return True

    def _sp_begin(self, info: dict, host: str) -> None:
        self.sp_client = SpyClient(info, self.sp_my_id(), host, time.monotonic())
        self._sp_host_seen = time.monotonic()
        if not self._sp_win_alive():
            self.open_spy()
        self.sp_win.start_game(self.sp_client)

    def _sp_host_step(self, force: bool = False) -> None:
        g = self.sp_game
        if g is None:
            return
        now = time.monotonic()
        g.tick(now)
        me = self.sp_my_id()
        for pid in g.roles:
            if pid in g.left:
                continue
            last = self._sp_sent.get(pid)
            if not force and last is not None and last[0] == g.version and now - last[1] < STATE_EVERY:
                continue
            st = g.state_for(pid, now)
            self._sp_sent[pid] = (g.version, now)
            if pid == me:
                if self.sp_client is not None:
                    self.sp_client.apply_state(st, now)
            else:
                self._sp_send(pid, "sp_st", st)
        if g.winner:
            if self._sp_over_t is None:
                self._sp_over_t = now
            elif now - self._sp_over_t > 2.5:
                self._sp_finish_host()

    def _sp_finish_host(self) -> None:
        if self._sp_timer is not None:
            self._sp_timer.stop()
        self._sp_over_t = None
        self.sp_game = None
        r = self.sp_room
        if r is not None and r["host"] == self.sp_my_id():
            r["st"] = "wait"
            r["members"] = [m for m in r["members"] if self._sp_online(m["id"])]
            self._sp_send_roster()

    def _sp_end_game(self) -> None:
        if self._sp_timer is not None:
            self._sp_timer.stop()
        self.sp_game = None
        self.sp_client = None
        self._sp_over_t = None
        if self._sp_win_alive():
            self.sp_win.pages["game"].stop()

    def sp_action(self, a: str, data: dict) -> None:
        c = self.sp_client
        if c is None:
            return
        g = self.sp_game
        if g is not None:
            err = g.act(self.sp_my_id(), a, data, time.monotonic())
            if err:
                self._sp_on_error(a, err)
            self._sp_host_step()
        else:
            self._sp_send(c.host, "sp_act", {"a": a, "d": data})

    def sp_vote(self, target: str) -> None:
        c = self.sp_client
        if c is None or c.phase != "vote" or c.me not in c.alive or c.me in c.voted or target == c.me:
            return
        self.sp_action("vote", {"t": target})

    def _sp_on_error(self, a: str, err: str) -> None:
        self._sp_toast(err)

    def sp_back_to_room(self) -> None:
        self._sp_end_game()
        self._sp_go("room" if self.sp_room is not None else "lobby")

    def sp_quit_game(self) -> None:
        c = self.sp_client
        if c is None or c.phase == "over":
            self.sp_back_to_room()
            return
        host = self.sp_room is not None and self.sp_room["host"] == self.sp_my_id()
        text = "你是房主,退出会让这局结束、房间解散。" if host else "退出后你就离开这局了(算出局)。"
        if not ask(self.sp_win, "退出游戏?", text, "退出", "继续玩"):
            return
        self.sp_leave_room()

    def sp_can_close(self) -> bool:
        c = self.sp_client
        if c is not None and c.phase != "over":
            if not ask(self.sp_win, "游戏还在进行", "关掉窗口会退出这局。确定吗?", "退出", "继续玩"):
                return False
        if self.sp_room is not None or self.sp_client is not None:
            self.sp_leave_room(quiet=True)
        return True

    # ---------------------------------------------------------------- 收事件
    def _ev_sp(self, d: dict, name: str, data: dict) -> None:
        fn = getattr(self, "_sp_ev_" + name[3:], None)
        if fn is not None and isinstance(data, dict):
            fn(d["peer"], data)

    def _sp_ev_room(self, pid: str, data: dict) -> None:
        rid = data.get("id")
        if not isinstance(rid, str) or len(rid) > 16:
            return
        if data.get("closed"):
            self.sp_rooms.pop(rid, None)
            return
        n, st, name = data.get("n"), data.get("st"), data.get("name")
        if type(n) is not int or st not in ("wait", "play") or not isinstance(name, str):
            return
        self.sp_rooms[rid] = {"id": rid, "name": name[:MAX_NAME], "host": pid, "n": max(1, min(MAX_PLAYERS, n)),
                              "st": st, "host_nick": self.sp_nick(pid), "seen": time.monotonic()}

    def _sp_ev_join(self, pid: str, data: dict) -> None:
        r = self.sp_room
        if r is None or r["host"] != self.sp_my_id() or data.get("id") != r["id"]:
            self._sp_send(pid, "sp_err", {"text": "这个房间已经没了。", "join": True})
            return
        if any(m["id"] == pid for m in r["members"]):
            self._sp_send_roster()
            return
        if r["st"] != "wait":
            self._sp_send(pid, "sp_err", {"text": "这个房间已经开始游戏了。", "join": True})
            return
        if len(r["members"]) >= MAX_PLAYERS:
            self._sp_send(pid, "sp_err", {"text": "房间满了。", "join": True})
            return
        r["members"].append({"id": pid, "nick": self.sp_nick(pid)[:20]})
        self._sp_send_roster()
        self._sp_toast(f"{self.sp_nick(pid)} 进房间了。")

    def _sp_ev_roster(self, pid: str, data: dict) -> None:
        me = self.sp_my_id()
        rid, members = data.get("id"), data.get("members")
        if data.get("host") != pid or not isinstance(members, list) or not isinstance(rid, str):
            return
        joining = self._sp_joining is not None and self._sp_joining[0] == rid
        if self.sp_room is not None and self.sp_room["id"] != rid:
            return
        if self.sp_room is None and not joining:
            return
        clean = [{"id": m["id"], "nick": str(m.get("nick", "?"))[:20]} for m in members[:MAX_PLAYERS]
                 if isinstance(m, dict) and isinstance(m.get("id"), str)]
        if not any(m["id"] == me for m in clean):
            if self.sp_room is not None:
                self._sp_drop_room("你已经不在这个房间里了。")
            return
        first = self.sp_room is None
        self.sp_room = {"id": rid, "name": str(data.get("name", "房间"))[:MAX_NAME], "host": pid, "members": clean,
                        "s": clean_settings(data.get("s")), "st": "play" if data.get("st") == "play" else "wait"}
        self._sp_joining = None
        self._sp_host_seen = time.monotonic()
        if first:
            if not self._sp_win_alive():
                self.open_spy()
            self._sp_go("room")
        elif self._sp_win_alive() and self.sp_win.current() == "room":
            self.sp_win.pages["room"].refresh()

    def _sp_ev_leave(self, pid: str, data: dict) -> None:
        r = self.sp_room
        if r is None or r["host"] != self.sp_my_id() or data.get("id") != r["id"]:
            return
        if not any(m["id"] == pid for m in r["members"]):
            return
        r["members"] = [m for m in r["members"] if m["id"] != pid]
        if self.sp_game is not None:
            self.sp_game.leave(pid, time.monotonic())
            self._sp_host_step()
        self._sp_send_roster()
        self._sp_toast(f"{self.sp_nick(pid)} 离开了房间。")

    def _sp_ev_end(self, pid: str, data: dict) -> None:
        r = self.sp_room
        if r is not None and r["host"] == pid and data.get("id") == r["id"]:
            self._sp_drop_room("房主解散了房间。")

    def _sp_ev_inv(self, pid: str, data: dict) -> None:
        rid, host = data.get("id"), data.get("host")
        if not isinstance(rid, str) or not isinstance(host, str) or len(rid) > 16:
            return
        if self.sp_room is not None and self.sp_room["id"] == rid:
            return
        now = time.monotonic()
        if now - self._sp_invites.get(pid, -1e9) < 10:
            return
        self._sp_invites[pid] = now
        name = str(data.get("name", "房间"))[:MAX_NAME]
        if rid not in self.sp_rooms and self._sp_online(host):
            self.sp_rooms[rid] = {"id": rid, "name": name, "host": host, "n": 1, "st": "wait",
                                  "host_nick": self.sp_nick(host), "seen": now}
        QTimer.singleShot(0, lambda: self._sp_ask_invite(pid, rid, name, now))

    def _sp_ask_invite(self, pid: str, rid: str, name: str, t: float) -> None:
        if time.monotonic() - t > INVITE_TTL:
            return
        if self.sp_client is not None and self.sp_client.phase != "over":
            return
        parent = self.sp_win if self._sp_win_alive() else self
        if ask(parent, "🕵 谁是卧底", f"{self.sp_nick(pid)} 邀请你来玩谁是卧底(房间「{name}」),去吗?", "去!", "不了"):
            if not self._sp_win_alive():
                self.open_spy()
            self.sp_join(rid)

    def _sp_ev_err(self, pid: str, data: dict) -> None:
        text = data.get("text")
        if not isinstance(text, str):
            return
        if data.get("join"):
            if self._sp_joining is not None:
                self._sp_joining = None
                self._sp_toast(text[:60])
            return
        c = self.sp_client
        if c is not None and pid == c.host:
            self._sp_on_error(str(data.get("a", "")), text[:60])

    def _sp_ev_start(self, pid: str, data: dict) -> None:
        r = self.sp_room
        info = data.get("info")
        if r is None or r["host"] != pid or data.get("rid") != r["id"] or not isinstance(info, dict):
            return
        r["st"] = "play"
        self._sp_begin(info, pid)

    def _sp_ev_st(self, pid: str, data: dict) -> None:
        c = self.sp_client
        if c is not None and pid == c.host and self.sp_game is None:
            c.apply_state(data, time.monotonic())

    def _sp_ev_act(self, pid: str, data: dict) -> None:
        g = self.sp_game
        if g is None or pid not in g.roles:
            return
        a = data.get("a")
        d = data.get("d") if isinstance(data.get("d"), dict) else {}
        err = g.act(pid, a if isinstance(a, str) else "", d, time.monotonic())
        if err:
            self._sp_send(pid, "sp_err", {"text": err, "a": a if isinstance(a, str) else ""})
        self._sp_host_step()
