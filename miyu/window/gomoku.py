"""
密语 · 五子棋(主窗口的功能模块,2.2)

联网对战全部走密语原有的加密连接(私聊事件),不需要服务器、不连外网:
  房间   创建后每 6 秒告诉在线的人一次(gm_room);别人点「加入」发 gm_join,房主收到就开局
  邀请   gm_invite → 对方弹窗 30 秒 → gm_inv_ans;接受就由邀请的人开局
  开局   房主签好开局信息发 gm_start,对方核对后签名回 gm_start_ok。之后双方各自签自己的每一步(gm_act)
  同步   每一步带序号:重复的忽略;缺了就要整份记录(gm_sync → gm_state);同时操作时按 record.better 选同一份
  请求   悔棋 / 重新开始 / 再来一局:gm_req → gm_reply(悔棋由同意的一方签名)
  掉线   对方不在线时双方计时暂停,回来自动同步继续;超过 90 秒可以判对方掉线负,等对方的软件回来确认才计分
  记录   对局结束后发给所有在线的人(gm_recs);有人上线时互相对一下(gm_hi → gm_ids → gm_get / gm_recs)
积分和排行榜由 gomoku/league.py 从记录算出来;记录存在数据文件夹的 g.bin(和账户一样加密)。
"""
from __future__ import annotations

import hashlib
import json
import random
import time
import uuid

from PySide6.QtCore import QTimer

from ..dialogs import ask, info
from ..gomoku import ai, league, record as R
from ..gomoku.rules import BLACK, Board
from ..icons import avatar

ROOM_EVERY = 6.0
ROOM_TTL = 20.0
INVITE_TTL = 32.0
START_TTL = 25.0
REQ_TTL = 25.0
OFFLINE_CLAIM = 90.0
NO_RESPONSE_GRACE = 15.0
SYNC_EVERY = 120.0
SAVE_DELAY = 3.0
MAX_RECS = 20000
STALE_UNFINISHED_MS = 14 * 86400 * 1000
BATCH_BYTES = 380 * 1024
REQ_NAME = {"undo": "悔棋", "restart": "重新开始", "rematch": "再来一局"}
STATUS_REASON = {"five": "连成五子", "draw": "棋盘下满了", "resign": "认输", "timeout": "超时", "abandon": "掉线",
                 "void": "双方同意重新开始", "abandon_pending": "等待对方确认掉线"}


def _hex(n: int) -> str:
    return uuid.uuid4().hex[:n]


def now_ms() -> int:
    return int(time.time() * 1000)


class GomokuMixin:
    """五子棋:大厅、房间、邀请、联网对战、人机练习、排行榜和战绩。"""

    # ---------------------------------------------------------------- 钩子
    def _init_gomoku(self) -> None:
        self.gm_recs: dict[str, dict] = {}          # 所有对局记录(按对局 id)
        self.gm_practice: list[dict] = []           # 人机练习(只在本机)
        self.gm_rooms: dict[str, dict] = {}         # 别人开的房间
        self.gm_busy_peers: dict[str, float] = {}   # 别人说自己在对局中(到这个时间为止)
        self.gm_my_room: dict | None = None
        self.gm_out_inv: dict | None = None
        self.gm_expect: dict[str, float] = {}       # 等谁发 gm_start 过来(加入房间 / 接受邀请之后)
        self.gm_pending: dict[str, dict] = {}       # 我发了 gm_start,等对方签名
        self.gm_live: dict | None = None            # 正在进行(或刚结束)的联网对局
        self.gm_ai: dict | None = None              # 正在进行的人机练习
        self.gm_win = None
        self.gm_inv_dialogs: dict[str, object] = {}
        self._gm_dirty = False
        self._gm_dirty_t = 0.0
        self._gm_games: list | None = None
        self._gm_room_t = 0.0
        self._gm_sync_t: dict[str, float] = {}
        self._gm_stone = None
        self._gm_last_busy = False
        self.gm_load()

    def _tick_gomoku(self, now: float) -> None:
        mono = time.monotonic()
        if self.gm_my_room is not None and mono - self._gm_room_t >= ROOM_EVERY:
            self._gm_broadcast_room()
        for rid in [k for k, r in self.gm_rooms.items() if mono - r["seen"] > ROOM_TTL]:
            self.gm_rooms.pop(rid, None)
        if self.gm_out_inv and mono > self.gm_out_inv["deadline"]:
            nick = self._gm_nick(self.gm_out_inv["pid"])
            self.gm_out_inv = None
            self._gm_notice(f"{nick} 没有回应邀请。")
        for mid in [k for k, p in self.gm_pending.items() if mono > p["deadline"]]:
            self.gm_pending.pop(mid, None)
            self._gm_notice("对方没有接受开局。")
        for pid in [k for k, t in self.gm_expect.items() if mono > t]:
            self.gm_expect.pop(pid, None)
        self._gm_live_tick(mono)
        busy = self.gm_busy()
        if busy != self._gm_last_busy:                 # 告诉在线的人我是不是在对局中(好友列表里显示)
            self._gm_last_busy = busy
            for pid in self._gm_online_peers():
                self._gm_send(pid, "gm_st", {"busy": busy})
        for pid in self._gm_online_peers():            # 隔一段时间和每个人对一次记录
            if mono - self._gm_sync_t.get(pid, 0) >= SYNC_EVERY:
                self._gm_sync_t[pid] = mono + random.uniform(0, 20)
                self._gm_send_hi(pid)
        if self._gm_dirty and mono - self._gm_dirty_t >= SAVE_DELAY:
            self.gm_save()
        if self.gm_win is not None and self._gm_win_alive():
            self.gm_win.refresh_page("lobby")

    def _peer_online_gomoku(self, pid: str) -> None:
        self._gm_sync_t[pid] = time.monotonic()
        self._gm_send_hi(pid)
        if self.gm_my_room is not None:
            self._gm_broadcast_room(only=pid)
        if self.gm_busy():
            self._gm_send(pid, "gm_st", {"busy": True})

    # ---------------------------------------------------------------- 存取
    def gm_load(self) -> None:
        if self.store is None:
            return
        try:
            d = self.store.load_games()
        except Exception:                              # noqa: BLE001
            d = {}
        for raw in d.get("recs") or []:
            rec = R.clean_record(raw)
            if rec is not None:
                self.gm_recs[rec["id"]] = rec
        self.gm_practice = [p for p in (d.get("practice") or []) if isinstance(p, dict) and isinstance(p.get("moves"), list)]
        live = d.get("live")
        if isinstance(live, dict):                     # 上次关软件时还没下完的对局:对方在线就接着下
            rec = self.gm_recs.get(live.get("id"))
            me = self.gm_my_id()
            if rec is not None and me in (rec["b"], rec["w"]) and R.evaluate(rec)["end_i"] is None:
                self._gm_set_live(rec, resumed=True)

    def gm_save(self) -> None:
        self._gm_dirty = False
        if self.store is None or not self.remember:
            return
        recs = list(self.gm_recs.values())
        if len(recs) > MAX_RECS:
            recs.sort(key=lambda r: r["t0"])
            recs = recs[-MAX_RECS:]
        live = None
        L = self.gm_live
        if L is not None and not L["over"]:
            live = {"id": L["id"]}
        try:
            self.store.save_games({"recs": recs, "practice": self.gm_practice[-300:], "live": live})
        except Exception:                              # noqa: BLE001
            pass

    def _gm_changed(self) -> None:
        self._gm_dirty = True
        self._gm_dirty_t = time.monotonic()
        self._gm_games = None

    # ---------------------------------------------------------------- 给窗口用的数据
    def gm_my_id(self) -> str:
        return self.core.id_hex

    def gm_games(self) -> list:
        if self._gm_games is None:
            self._gm_games = league.games_from(self.gm_recs)
        return self._gm_games

    def _gm_nick(self, pid: str) -> str:
        p = self.peers.get(pid)
        if p and p.get("nick"):
            return p["nick"]
        for rec in self.gm_recs.values():
            if rec["b"] == pid:
                return rec["nb"]
            if rec["w"] == pid:
                return rec["nw"]
        return "对手"

    def _gm_online(self, pid: str) -> bool:
        return bool(self.peers.get(pid, {}).get("online"))

    def _gm_online_peers(self) -> list[str]:
        me = self.gm_my_id()
        return [pid for pid, p in self.peers.items() if p.get("online") and pid != me]

    def gm_busy(self) -> bool:
        L = self.gm_live
        return bool((L is not None and not L["over"]) or self.gm_pending)

    def gm_rooms_list(self) -> list[dict]:
        me = self.gm_my_id()
        out = [dict(r) for r in self.gm_rooms.values() if r["host"] != me and self._gm_online(r["host"])]
        out.sort(key=lambda r: -r["ts"])
        return out

    def gm_friends(self) -> list[dict]:
        rows = {r["id"]: r for r in league.standings(self.gm_games())}
        mono = time.monotonic()
        out = []
        for pid in self._gm_online_peers():
            out.append({"id": pid, "nick": self._gm_nick(pid), "busy": self.gm_busy_peers.get(pid, 0) > mono,
                        "pts": rows.get(pid, {}).get("pts", 0)})
        out.sort(key=lambda f: (f["busy"], f["nick"]))
        return out

    def gm_lobby_status(self) -> tuple[str, str, str]:
        L = self.gm_live
        if L is not None and not L["over"]:
            return "live", f"你正在和 {self._gm_nick(L['opp'])} 对局", "back"
        if self.gm_ai is not None and not self.gm_ai["over"]:
            return "live", f"人机练习进行中(电脑 · {ai.LEVELS[self.gm_ai['level']]})", "back"
        if self.gm_my_room is not None:
            r = self.gm_my_room
            lim = "不限时" if not r["lim"] else f"每步 {r['lim']} 秒"
            return "room", f"你的房间「{r['name']}」已开 · {lim} · 等待对手加入…", "cancel_room"
        if self.gm_out_inv is not None:
            left = max(0, int(self.gm_out_inv["deadline"] - time.monotonic()))
            return "inv", f"已邀请 {self._gm_nick(self.gm_out_inv['pid'])},等待回应… {left} 秒", "cancel_invite"
        if self.gm_expect or self.gm_pending:
            return "join", "正在开局…", ""
        return "", "", ""

    # ---------------------------------------------------------------- 窗口
    def _gm_win_alive(self) -> bool:
        try:
            return self.gm_win is not None and self.gm_win.isVisible()
        except RuntimeError:
            self.gm_win = None
            return False

    def open_gomoku(self, page: str = "lobby") -> None:
        from ..gomoku.window import GomokuWindow
        win = self.gm_win
        if win is not None:
            try:
                win.isVisible()                        # 关掉只是藏起来,下次直接再显示
            except RuntimeError:
                win = None
        if win is None:
            win = GomokuWindow(self)
            self.gm_win = win
        win.show()
        win.raise_()
        win.activateWindow()
        win.go(page)

    def _gm_refresh(self, pages=("game", "lobby", "rank", "me")) -> None:
        if not self._gm_win_alive():
            return
        for p in pages:
            self.gm_win.refresh_page(p)

    def _gm_notice(self, text: str) -> None:
        """一句提示:五子棋窗口开着就在窗口顶上飘一下,否则写在当前会话里。"""
        if self._gm_win_alive():
            self.gm_win.toast(text)
        elif self.window_visible():
            self._system(self.current or self.convs["lobby"], f"♟ 五子棋:{text}")

    def gm_can_close(self) -> bool:
        L = self.gm_live
        if L is not None and not L["over"]:
            return ask(self.gm_win, "对局还没结束", "关掉窗口后对局继续进行,计时不会停。\n"
                       "可以点左上角的五子棋按钮回来。确定关闭?", "关闭")
        return True

    def _gm_play_stone(self) -> None:
        if not self._gm_win_alive():
            return
        try:
            from .. import sound
            if self._gm_stone is None:
                self._gm_stone = [sound.stone_pcm(i) for i in range(3)]
            self.keysound.play_pcm(random.choice(self._gm_stone), 0.9)
        except Exception:                              # noqa: BLE001
            pass

    # ---------------------------------------------------------------- 发事件
    def _gm_send(self, pid: str, name: str, data: dict) -> bool:
        try:
            return bool(self.core.send_event("dm", pid, name, data))
        except Exception:                              # noqa: BLE001
            return False

    def _ev_gm(self, d: dict, name: str, data: dict) -> None:
        fn = getattr(self, "_gm_ev_" + name[3:], None)
        if fn is not None:
            fn(d, data)

    # ---------------------------------------------------------------- 房间
    def gm_create_room_dialog(self) -> None:
        from ..gomoku.window import SetupDialog
        if self.gm_busy():
            info(self.gm_win or self, "正在对局", "先把这盘下完再开房间吧。")
            return
        dlg = SetupDialog(self.gm_win or self, "创建房间", "创建", name=f"{self.me.get('nick', '')}的房间")
        if dlg.exec():
            name, lim, color = dlg.values
            self.gm_create_room(name, lim, color)

    def gm_create_room(self, name: str, lim: int, color: str) -> None:
        self.gm_cancel_invite()
        self.gm_my_room = {"rid": _hex(16), "name": (name or f"{self.me.get('nick', '')}的房间")[:20],
                           "lim": lim if lim in R.LIMITS else 60, "color": color if color in ("rand", "b", "w") else "rand",
                           "ts": now_ms()}
        self._gm_broadcast_room()
        self._gm_refresh(("lobby",))

    def gm_cancel_room(self) -> None:
        if self.gm_my_room is not None:
            self._gm_broadcast_room(closed=True)
            self.gm_my_room = None
        self._gm_refresh(("lobby",))

    def _gm_broadcast_room(self, closed: bool = False, only: str | None = None) -> None:
        r = self.gm_my_room
        if r is None:
            return
        self._gm_room_t = time.monotonic()
        data = {"rid": r["rid"], "name": r["name"], "lim": r["lim"], "color": r["color"], "ts": r["ts"], "open": not closed}
        for pid in ([only] if only else self._gm_online_peers()):
            self._gm_send(pid, "gm_room", data)

    def _gm_ev_room(self, d: dict, data: dict) -> None:
        rid, name, lim, color = data.get("rid"), data.get("name"), data.get("lim"), data.get("color")
        if not (isinstance(rid, str) and 0 < len(rid) <= 32 and isinstance(name, str) and lim in R.LIMITS
                and color in ("rand", "b", "w")):
            return
        if data.get("open"):
            ts = data.get("ts") if type(data.get("ts")) is int else now_ms()
            self.gm_rooms[rid] = {"rid": rid, "name": name[:20], "lim": lim, "color": color, "host": d["peer"],
                                  "nick": self._gm_nick(d["peer"]), "ts": ts, "seen": time.monotonic()}
        else:
            r = self.gm_rooms.get(rid)
            if r is not None and r["host"] == d["peer"]:
                self.gm_rooms.pop(rid, None)
        self._gm_refresh(("lobby",))

    def _gm_ev_st(self, d: dict, data: dict) -> None:
        self.gm_busy_peers[d["peer"]] = time.monotonic() + 3600 if data.get("busy") is True else 0
        self._gm_refresh(("lobby",))

    def gm_join(self, rid: str) -> None:
        r = self.gm_rooms.get(rid)
        if r is None or not self._gm_online(r["host"]):
            info(self.gm_win or self, "房间不在了", "这个房间已经关闭了。")
            return
        if self.gm_busy():
            info(self.gm_win or self, "正在对局", "先把这盘下完吧。")
            return
        self.gm_cancel_room()
        self.gm_cancel_invite()
        self.gm_expect[r["host"]] = time.monotonic() + START_TTL
        self._gm_send(r["host"], "gm_join", {"rid": rid})
        self._gm_refresh(("lobby",))

    def _gm_ev_join(self, d: dict, data: dict) -> None:
        r = self.gm_my_room
        if r is None or data.get("rid") != r["rid"] or self.gm_busy():
            self._gm_send(d["peer"], "gm_busy", {"why": "房间已经关闭或者有人先加入了"})
            return
        self.gm_cancel_room()
        self._gm_host_start(d["peer"], r["lim"], r["color"])

    def _gm_ev_busy(self, d: dict, data: dict) -> None:
        self.gm_expect.pop(d["peer"], None)
        for mid in [k for k, p in self.gm_pending.items() if p["opp"] == d["peer"]]:
            self.gm_pending.pop(mid, None)
        why = data.get("why") if isinstance(data.get("why"), str) else "对方现在不能开局"
        self._gm_notice(f"没能开局:{why[:60]}")
        self._gm_refresh(("lobby",))

    # ---------------------------------------------------------------- 邀请
    def gm_invite_dialog(self, pid: str) -> None:
        from ..gomoku.window import SetupDialog
        if self.gm_busy():
            info(self.gm_win or self, "正在对局", "先把这盘下完再邀请别人吧。")
            return
        if not self._gm_online(pid):
            info(self.gm_win or self, "对方不在线", "对方在线时才能邀请。")
            return
        dlg = SetupDialog(self.gm_win or self, f"邀请 {self._gm_nick(pid)} 下五子棋", "发出邀请")
        if dlg.exec():
            _n, lim, color = dlg.values
            self.gm_invite(pid, lim, color)

    def gm_invite(self, pid: str, lim: int, color: str) -> None:
        self.gm_cancel_room()
        iid = _hex(16)
        self.gm_out_inv = {"iid": iid, "pid": pid, "lim": lim, "color": color, "deadline": time.monotonic() + INVITE_TTL}
        self._gm_send(pid, "gm_invite", {"iid": iid, "lim": lim, "color": color})
        if not self._gm_win_alive():
            self.open_gomoku("lobby")
        self._gm_refresh(("lobby",))

    def gm_cancel_invite(self) -> None:
        inv, self.gm_out_inv = self.gm_out_inv, None
        if inv is not None:
            self._gm_send(inv["pid"], "gm_inv_cancel", {"iid": inv["iid"]})
        self._gm_refresh(("lobby",))

    def _gm_ev_invite(self, d: dict, data: dict) -> None:
        from ..gomoku.window import InviteDialog
        iid, lim, color = data.get("iid"), data.get("lim"), data.get("color")
        pid = d["peer"]
        if not (isinstance(iid, str) and 0 < len(iid) <= 32 and lim in R.LIMITS and color in ("rand", "b", "w")):
            return
        if self.gm_busy() or len(self.gm_inv_dialogs) >= 3:
            self._gm_send(pid, "gm_inv_ans", {"iid": iid, "ok": False, "why": "对方正在对局"})
            return
        text = {"rand": "随机执子", "b": "对方执黑、你执白", "w": "你执黑(先手)"}[color]
        dlg = InviteDialog(self.gm_win if self._gm_win_alive() else self, pid, self._gm_nick(pid), lim, text)
        self.gm_inv_dialogs[iid] = dlg
        dlg.finished.connect(lambda _r, iid=iid, pid=pid, dlg=dlg: self._gm_inv_done(iid, pid, dlg))
        dlg.show()
        dlg.raise_()
        try:
            self.notifier.play(force=True)
            if self.flash_enabled:
                from PySide6.QtWidgets import QApplication
                QApplication.alert(self, 0)
        except Exception:                              # noqa: BLE001
            pass

    def _gm_inv_done(self, iid: str, pid: str, dlg) -> None:
        if self.gm_inv_dialogs.pop(iid, None) is None:
            return
        ok = dlg.choice is True and not self.gm_busy() and self._gm_online(pid)
        if ok:
            self.gm_cancel_room()
            self.gm_expect[pid] = time.monotonic() + START_TTL
        self._gm_send(pid, "gm_inv_ans", {"iid": iid, "ok": ok})
        if ok:
            self.open_gomoku("lobby")

    def _gm_ev_inv_cancel(self, d: dict, data: dict) -> None:
        dlg = self.gm_inv_dialogs.pop(data.get("iid"), None)
        if dlg is not None:
            try:
                dlg.choice = False
                dlg.close()
            except RuntimeError:
                pass

    def _gm_ev_inv_ans(self, d: dict, data: dict) -> None:
        inv = self.gm_out_inv
        if inv is None or data.get("iid") != inv["iid"] or d["peer"] != inv["pid"]:
            return
        self.gm_out_inv = None
        if data.get("ok") is True and not self.gm_busy():
            self._gm_host_start(inv["pid"], inv["lim"], inv["color"])
        else:
            why = data.get("why") if isinstance(data.get("why"), str) else "对方拒绝了邀请"
            self._gm_notice(f"{self._gm_nick(inv['pid'])}:{why[:40]}")
        self._gm_refresh(("lobby",))

    # ---------------------------------------------------------------- 开局
    def _gm_host_start(self, opp: str, lim: int, color: str) -> None:
        """我当房主开一盘:定好谁执黑,签好开局信息发给对方。color 是我自己的(rand / b / w)。"""
        me = self.gm_my_id()
        mine_black = random.random() < 0.5 if color == "rand" else color == "b"
        black, white = (me, opp) if mine_black else (opp, me)
        rec = R.new_record(uuid.uuid4().hex, black, white, lim, now_ms(), self._gm_name(black), self._gm_name(white))
        R.sign_start(rec, self.core.identity, "b" if mine_black else "w")
        self.gm_pending[rec["id"]] = {"rec": rec, "opp": opp, "deadline": time.monotonic() + START_TTL}
        self._gm_send(opp, "gm_start", {"rec": rec})
        self._gm_refresh(("lobby",))

    def _gm_name(self, pid: str) -> str:
        return (self.me.get("nick", "") if pid == self.gm_my_id() else self._gm_nick(pid))[:R.NICK_MAX]

    def _gm_ev_start(self, d: dict, data: dict) -> None:
        rec = R.clean_record(data.get("rec"))
        pid, me = d["peer"], self.gm_my_id()
        if rec is None or rec["acts"] or me not in (rec["b"], rec["w"]) or pid not in (rec["b"], rec["w"]):
            return
        host = R.color_of(rec, pid)
        if not R._sig_ok(pid, rec["s" + host], R.start_payload(rec)):
            return
        exp = self.gm_expect.pop(pid, None)
        if exp is None or time.monotonic() > exp or self.gm_busy():
            self._gm_send(pid, "gm_busy", {"why": "对方现在不能开局"})
            return
        mine = "w" if host == "b" else "b"
        R.sign_start(rec, self.core.identity, mine)
        self._gm_send(pid, "gm_start_ok", {"id": rec["id"], "sig": rec["s" + mine]})
        self._gm_set_live(rec)

    def _gm_ev_start_ok(self, d: dict, data: dict) -> None:
        p = self.gm_pending.pop(data.get("id"), None)
        if p is None or p["opp"] != d["peer"] or not isinstance(data.get("sig"), str):
            return
        rec = p["rec"]
        color = R.color_of(rec, d["peer"])
        if not R._sig_ok(d["peer"], data["sig"], R.start_payload(rec)):
            return
        rec["s" + color] = data["sig"]
        self._gm_set_live(rec)

    def _gm_set_live(self, rec: dict, resumed: bool = False) -> None:
        me = self.gm_my_id()
        color = R.color_of(rec, me)
        if color is None:
            return
        if self.gm_ai is not None and not self.gm_ai["over"]:
            self._gm_ai_end(None)                      # 练习到一半来了正式对局:练习就算了
        self.gm_ai = None
        mono = time.monotonic()
        self.gm_live = {"id": rec["id"], "rec": rec, "me": color, "opp": rec["w" if color == "b" else "b"],
                        "turn_t": mono, "off_t": None, "last_off": 0.0, "req_out": None, "req_in": None,
                        "over": False, "left": False, "used": {"b": 0.0, "w": 0.0}, "noresp": False,
                        "res": R.evaluate(rec), "started": mono}
        self.gm_recs[rec["id"]] = rec
        self._gm_changed()
        if not resumed:
            self.open_gomoku("game")
            try:
                self.notifier.play(force=True)
            except Exception:                          # noqa: BLE001
                pass
        self._gm_refresh(("game", "lobby"))

    # ---------------------------------------------------------------- 下棋
    def gm_play(self, x: int, y: int) -> None:
        if self.gm_ai is not None:
            self._gm_ai_play(x, y)
            return
        L = self.gm_live
        if L is None or L["over"] or L["off_t"] is not None:
            return
        res = L["res"]
        turn = "b" if len(res["moves"]) % 2 == 0 else "w"
        if turn != L["me"] or (x, y) in set(res["moves"]):
            return
        if L["req_out"] is not None and L["req_out"]["what"] in ("undo", "restart"):
            return                                     # 等对方回应时不能下(不然请求就对不上了)
        self._gm_append(L, "m", x=x, y=y)

    def _gm_append(self, L: dict, kind: str, **kw) -> bool:
        rec = L["rec"]
        before = L["res"]
        a = R.make_action(rec, self.core.identity, kind, L["me"], now_ms(), **kw)
        rec["acts"].append(a)
        res = R.evaluate(rec)
        if res["n_acts"] != len(rec["acts"]):          # 不符合规则(正常不会发生)
            rec["acts"].pop()
            return False
        self._gm_send(L["opp"], "gm_act", {"id": rec["id"], "i": len(rec["acts"]) - 1, "a": a})
        self._gm_after_change(L, before, res)
        return True

    def _gm_after_change(self, L: dict, before: dict, res: dict) -> None:
        mono = time.monotonic()
        turn_before = "b" if len(before["moves"]) % 2 == 0 else "w"
        if L["off_t"] is None:
            L["used"][turn_before] += max(0.0, mono - L["turn_t"])
        if res["moves"] != before["moves"]:
            L["turn_t"] = mono
            L["noresp"] = False
            if L["req_out"] is not None and L["req_out"]["what"] == "undo" and len(res["moves"]) > len(before["moves"]):
                L["req_out"] = None
            if L["req_in"] is not None and L["req_in"]["what"] == "undo":
                L["req_in"] = None
            if len(res["moves"]) > len(before["moves"]):
                self._gm_play_stone()
        if res["status"] == "abandon_pending" and res["claimant"] != L["me"] and not L["over"]:
            if self._gm_should_ack_live(L, res):       # 我确实掉线了 / 超时了:我的软件签名确认
                a = R.make_action(L["rec"], self.core.identity, "k", L["me"], now_ms())
                L["rec"]["acts"].append(a)
                res2 = R.evaluate(L["rec"])
                if res2["status"] == "abandon":
                    res = res2
                    self._gm_send(L["opp"], "gm_act", {"id": L["id"], "i": len(L["rec"]["acts"]) - 1, "a": a})
                else:
                    L["rec"]["acts"].pop()
            else:
                L["disputed"] = True                   # 我一直在线:不认,这局就不计分
        L["res"] = res
        self.gm_recs[L["id"]] = L["rec"]
        self._gm_changed()
        if res["end_i"] is not None or res["status"] == "abandon_pending":
            self._gm_finish(L)
        self._gm_refresh(("game",))

    def _gm_should_ack_live(self, L: dict, res: dict) -> bool:
        lim = L["rec"]["lim"]
        turn = "b" if len(res["moves"]) % 2 == 0 else "w"
        my_time_out = bool(lim) and turn == L["me"] and time.monotonic() - L["turn_t"] >= lim
        return L["off_t"] is not None or L["last_off"] >= OFFLINE_CLAIM - 10 or my_time_out

    def _gm_ev_act(self, d: dict, data: dict) -> None:
        L = self.gm_live
        mid = data.get("id")
        if L is None or L["id"] != mid or d["peer"] != L["opp"]:
            if isinstance(mid, str) and mid in self.gm_recs:
                self._gm_send(d["peer"], "gm_state", {"rec": self.gm_recs[mid]})
            return
        a, i = R.clean_action(data.get("a")), data.get("i")
        if a is None or type(i) is not int or i < 0:
            return
        rec = L["rec"]
        n = len(rec["acts"])
        if i < n:
            if rec["acts"][i] == a:
                return                                 # 重复收到
            cand = dict(rec, acts=rec["acts"][:i] + [a])   # 同时操作:两边按同一个规则选同一份
            self._gm_merge_live(L, cand)
            self._gm_send(L["opp"], "gm_state", {"rec": L["rec"]})
            return
        if i > n:                                      # 中间漏了:要整份
            self._gm_send(L["opp"], "gm_sync", {"id": mid, "n": n})
            return
        before = L["res"]
        rec["acts"].append(a)
        res = R.evaluate(rec)
        if res["n_acts"] != len(rec["acts"]):
            rec["acts"].pop()
            self._gm_send(L["opp"], "gm_sync", {"id": mid, "n": n})
            return
        self._gm_after_change(L, before, res)

    def _gm_merge_live(self, L: dict, other: dict) -> bool:
        best = R.better(L["rec"], other)
        if best is L["rec"]:
            return False
        new = json.loads(json.dumps(best))
        res = R.evaluate(new)
        before = L["res"]
        L["rec"] = new
        if L["over"]:                                  # 已经结束了(比如等确认的掉线负,后来确认了):只更新记录
            L["res"] = res
            self.gm_recs[L["id"]] = new
            self._gm_changed()
            self._gm_refresh(("game", "rank", "me"))
            return True
        self._gm_after_change(L, before, res)
        return True

    def _gm_ev_sync(self, d: dict, data: dict) -> None:
        rec = self.gm_recs.get(data.get("id"))
        if rec is not None and d["peer"] in (rec["b"], rec["w"]):
            self._gm_send(d["peer"], "gm_state", {"rec": rec})

    def _gm_ev_state(self, d: dict, data: dict) -> None:
        rec = R.clean_record(data.get("rec"))
        if rec is None or d["peer"] not in (rec["b"], rec["w"]):
            return
        L = self.gm_live
        if L is not None and L["id"] == rec["id"]:
            mine_before = L["rec"]
            self._gm_merge_live(L, rec)
            if R.better(mine_before, rec) is mine_before and mine_before["acts"] != rec["acts"]:
                self._gm_send(d["peer"], "gm_state", {"rec": L["rec"]})     # 我的更新:发回去让对方也换成这份
        else:
            self._gm_accept_record(rec)

    # ---------------------------------------------------------------- 计时 / 掉线
    def _gm_live_tick(self, mono: float) -> None:
        L = self.gm_live
        if L is None or L["over"]:
            return
        if L["req_out"] is not None and mono - L["req_out"]["t"] > REQ_TTL:
            L["req_out"] = None
            self._gm_refresh(("game",))
        if L["req_in"] is not None and mono - L["req_in"]["t"] > REQ_TTL:
            self.gm_answer(False)
        if not self._gm_online(L["opp"]):
            if L["off_t"] is None:                     # 对方掉线:双方计时都停
                L["off_t"] = mono
                self._gm_refresh(("game",))
            return
        if L["off_t"] is not None:                     # 回来了:补上暂停的时间,同步一下继续
            L["last_off"] = mono - L["off_t"]
            L["turn_t"] += L["last_off"]
            L["off_t"] = None
            self._gm_send(L["opp"], "gm_state", {"rec": L["rec"]})
            self._gm_refresh(("game",))
        lim = L["rec"]["lim"]
        if not lim:
            return
        turn = "b" if len(L["res"]["moves"]) % 2 == 0 else "w"
        elapsed = mono - L["turn_t"]
        if turn == L["me"] and elapsed >= lim:
            self._gm_append(L, "t")                    # 我的时间到了:我的软件自己认输(签名的是我自己)
        elif turn != L["me"] and elapsed >= lim + NO_RESPONSE_GRACE and not L["noresp"]:
            L["noresp"] = True                         # 对方超时还没认:可能网络有问题
            self._gm_refresh(("game",))

    def gm_claim(self) -> None:
        """对方掉线超过 90 秒(或超时不响应):判对方负。要等对方的软件回来确认才计分。"""
        L = self.gm_live
        if L is None or L["over"]:
            return
        mono = time.monotonic()
        offline_long = L["off_t"] is not None and mono - L["off_t"] >= OFFLINE_CLAIM
        if not (offline_long or L["noresp"]):
            return
        if not ask(self.gm_win or self, "判对方负?", "对方掉线或长时间没有响应。判负以后,要等对方的软件重新上线确认,"
                   "这局才会计分。", "判对方负"):
            return
        self._gm_append(L, "a")

    def _gm_check_ack(self, rec: dict, prev: dict | None = None) -> None:
        """不在进行中的对局(重新上线后才收到):对方判我掉线负,而我这边没有对方没看到的棋步,
        说明我确实是掉线了,我的软件签名确认。正在进行的对局在 _gm_after_change 里判断。"""
        res = R.evaluate(rec)
        mine = R.color_of(rec, self.gm_my_id())
        if res["status"] != "abandon_pending" or mine is None or res["claimant"] == mine:
            return
        L = self.gm_live
        if L is not None and L["id"] == rec["id"]:
            return
        if prev is not None and prev["acts"] != rec["acts"][:len(prev["acts"])]:
            return                                     # 我这边还有后来下的棋:不认
        new = json.loads(json.dumps(rec))
        new["acts"].append(R.make_action(new, self.core.identity, "k", mine, now_ms()))
        if R.evaluate(new)["status"] != "abandon":
            return
        self.gm_recs[new["id"]] = new
        self._gm_changed()
        self._gm_push(new)
        self._gm_notice(f"你在和 {self._gm_nick(rec[res['claimant']])} 的对局里掉线超过 90 秒,已确认判负。")
        self._gm_refresh(("rank", "me", "lobby"))

    # ---------------------------------------------------------------- 请求:悔棋 / 重新开始 / 再来一局
    def _gm_undo_n(self, res: dict, requester: str) -> int:
        """requester 想悔棋要退几手:最后一手是自己的退 1 手;最后一手是对方的(轮到自己)退 2 手。0 = 不能悔。"""
        moves = res["moves"]
        if not moves:
            return 0
        last = "b" if (len(moves) - 1) % 2 == 0 else "w"
        if last == requester:
            return 1
        return 2 if len(moves) >= 2 else 0

    def gm_request(self, what: str) -> None:
        if self.gm_ai is not None:
            self._gm_ai_request(what)
            return
        L = self.gm_live
        if L is None or what not in REQ_NAME:
            return
        if what == "rematch":
            if not L["over"] or L["left"] or not self._gm_online(L["opp"]):
                if L["left"] or not self._gm_online(L["opp"]):
                    info(self.gm_win or self, "对方已经离开", "对方不在了,回大厅约下一局吧。")
                return
            if L["req_in"] is not None and L["req_in"]["what"] == "rematch":
                self.gm_answer(True)
                return
        elif L["over"]:
            return
        if what == "undo" and not self._gm_undo_n(L["res"], L["me"]):
            info(self.gm_win or self, "没有可以悔的棋", "你还没有落子。")
            return
        if L["req_out"] is not None:
            return
        rid = _hex(12)
        L["req_out"] = {"what": what, "rid": rid, "base": len(L["rec"]["acts"]), "t": time.monotonic()}
        if what in ("restart", "rematch"):
            self.gm_expect[L["opp"]] = time.monotonic() + REQ_TTL + START_TTL
        self._gm_send(L["opp"], "gm_req", {"id": L["id"], "what": what, "rid": rid, "base": len(L["rec"]["acts"])})
        self._gm_refresh(("game",))

    def _gm_ev_req(self, d: dict, data: dict) -> None:
        L = self.gm_live
        what, rid, base = data.get("what"), data.get("rid"), data.get("base")
        if (L is None or L["id"] != data.get("id") or d["peer"] != L["opp"] or what not in REQ_NAME
                or not isinstance(rid, str) or type(base) is not int):
            return
        if what == "rematch" and L["req_out"] is not None and L["req_out"]["what"] == "rematch":
            if self.gm_my_id() < L["opp"]:              # 两边同时点了"再来一局":id 小的那边开局
                L["req_in"] = {"what": what, "rid": rid, "base": base, "t": time.monotonic()}
                self.gm_answer(True)
            return
        if what != "rematch" and L["over"]:
            return
        L["req_in"] = {"what": what, "rid": rid, "base": base, "t": time.monotonic()}
        self._gm_play_stone()
        self._gm_refresh(("game",))
        if not self._gm_win_alive():
            self.open_gomoku("game")

    def gm_answer(self, ok: bool) -> None:
        L = self.gm_live
        if L is None or L["req_in"] is None:
            return
        q, L["req_in"] = L["req_in"], None
        what = q["what"]
        if ok and what == "undo":
            n = self._gm_undo_n(L["res"], L["opp"])
            ok = q["base"] == len(L["rec"]["acts"]) and n > 0 and not L["over"]
        if ok and what == "restart":
            ok = not L["over"]
        if ok and what == "rematch":
            ok = L["over"] and self._gm_online(L["opp"]) and not self.gm_busy()
        self._gm_send(L["opp"], "gm_reply", {"id": L["id"], "rid": q["rid"], "what": what, "ok": bool(ok)})
        if ok and what == "undo":
            self._gm_append(L, "u", n=self._gm_undo_n(L["res"], L["opp"]))
        elif ok and what == "restart":
            lim, my = L["rec"]["lim"], L["me"]
            self._gm_append(L, "v")
            self._gm_host_start(L["opp"], lim, my)     # 颜色不变,重新开始
        elif ok and what == "rematch":
            lim, my = L["rec"]["lim"], L["me"]
            self._gm_host_start(L["opp"], lim, "w" if my == "b" else "b")   # 再来一局:交换先后手
        self._gm_refresh(("game",))

    def _gm_ev_reply(self, d: dict, data: dict) -> None:
        L = self.gm_live
        if L is None or L["id"] != data.get("id") or d["peer"] != L["opp"]:
            return
        q = L["req_out"]
        if q is None or q["rid"] != data.get("rid"):
            return
        L["req_out"] = None
        if data.get("ok") is not True:
            self.gm_expect.pop(L["opp"], None)
            self._gm_notice(f"对方拒绝了{REQ_NAME.get(q['what'], '请求')}。")
        self._gm_refresh(("game",))

    # ---------------------------------------------------------------- 认输 / 离开
    def gm_resign(self) -> None:
        if self.gm_ai is not None:
            if not self.gm_ai["over"] and ask(self.gm_win or self, "认输?", "这盘练习算你输。", "认输", danger=True):
                self._gm_ai_end("loss", reason="你认输了")
            return
        L = self.gm_live
        if L is None or L["over"]:
            return
        if ask(self.gm_win or self, "认输?", "这盘算你输,对方得 3 分(下满 10 手才计分)。", "认输", danger=True):
            self._gm_append(L, "r")

    def gm_leave(self, quiet: bool = False) -> None:
        if self.gm_ai is not None:
            if not self.gm_ai["over"] and not quiet and not ask(self.gm_win or self, "结束练习?", "这盘练习不会记成绩。", "结束"):
                return
            if not self.gm_ai["over"]:
                self._gm_ai_end(None)
            self.gm_ai = None
            self._gm_refresh()
            if self._gm_win_alive():
                self.gm_win.go("lobby")
            return
        L = self.gm_live
        if L is None:
            return
        if not L["over"]:
            if not ask(self.gm_win or self, "退出对局?", "对局还没结束,现在退出算你认输。", "认输并退出", danger=True):
                return
            self._gm_append(L, "r")
        self._gm_send(L["opp"], "gm_bye", {"id": L["id"]})
        self.gm_live = None
        self._gm_changed()
        self._gm_refresh()
        if self._gm_win_alive():
            self.gm_win.go("lobby")

    def _gm_ev_bye(self, d: dict, data: dict) -> None:
        L = self.gm_live
        if L is not None and L["id"] == data.get("id") and d["peer"] == L["opp"]:
            L["left"] = True
            L["req_in"] = None
            self._gm_refresh(("game",))

    # ---------------------------------------------------------------- 结束 / 结算
    def _gm_finish(self, L: dict) -> None:
        if L["over"]:
            return
        L["over"] = True
        L["req_out"] = L["req_in"] = None
        rec = L["rec"]
        self.gm_recs[rec["id"]] = rec
        self._gm_changed()
        self._gm_push(rec)
        self.gm_save()
        me = self.gm_my_id()
        res = L["res"]
        others = [g for g in self.gm_games() if g["id"] != rec["id"]]
        before = league.player_stats(others, me)
        rank_before, _r, _a = league.rank_of(league.standings(others), me)
        games = self.gm_games()
        after = league.player_stats(games, me)
        rank_after, _r, _a = league.rank_of(league.standings(games), me)
        g = next((x for x in games if x["id"] == rec["id"]), None)
        mine = L["me"]
        st = res["status"]
        result = g["res"].get(me) if g else None
        if st == "void":
            title, reason = "对局作废", "双方同意重新开始,这盘不计分"
        elif st == "abandon_pending":
            title = "等待确认"
            reason = "已判对方掉线负,等对方的软件回来确认后计分" if res["claimant"] == mine else "对方判你掉线负,等你确认"
        elif result == "draw":
            title, reason = "平局", "棋盘下满了,没人连成五子"
        else:
            win = res["winner"] == mine
            title = "胜利!" if win else "惜败"
            if st == "five":
                reason = "你连成了五子" if win else "对方连成了五子"
            else:
                how = {"resign": "认输", "timeout": "超时", "abandon": "掉线"}.get(st, "输")
                reason = f"对方{how}了" if win else f"你{how}了"
        rated = bool(g and g["rated"])
        note = "" if rated else ((g or {}).get("why") or "这局不计分")
        if L.get("disputed"):
            note = "对方判你掉线负,但你一直在线,你的软件没有确认,这局不计分。"
        rank_text = ""
        if rated and rank_after:
            if rank_before and rank_after < rank_before:
                rank_text = f"排名 第 {rank_before} → 第 {rank_after} 名  ↑{rank_before - rank_after}"
            elif not rank_before:
                rank_text = f"上榜了!总榜第 {rank_after} 名"
            else:
                rank_text = f"总榜第 {rank_after} 名"
        gained = (g["pts"].get(me, 0) if rated else 0) if g else 0
        if self._gm_win_alive() or self.window_visible():
            if not self._gm_win_alive():
                self.open_gomoku("game")
            self.gm_win.show_result(title=title, reason=reason, gained=gained, total_from=before["pts"],
                                    total_to=after["pts"], rank_text=rank_text, note=note,
                                    win=result == "win", can_rematch=st not in ("abandon_pending",) and not L["left"])
        if result == "win":
            try:
                self.notifier.play(force=True)
            except Exception:                          # noqa: BLE001
                pass

    # ---------------------------------------------------------------- 记录同步
    def _gm_push(self, rec: dict) -> None:
        for pid in self._gm_online_peers():
            self._gm_send(pid, "gm_recs", {"recs": [rec]})

    def _gm_hashes(self) -> dict[str, str]:
        """每盘棋的"指纹"(链上最后一个哈希的前 12 位),用来比较两边的记录是不是一样。"""
        return {mid: R.evaluate(rec)["hash"][:12] for mid, rec in self.gm_recs.items()}

    def _gm_digest(self, hashes: dict | None = None) -> str:
        hashes = self._gm_hashes() if hashes is None else hashes
        text = "\n".join(f"{k}:{v}" for k, v in sorted(hashes.items()))
        return hashlib.sha256(text.encode()).hexdigest()[:24]

    def _gm_send_hi(self, pid: str) -> None:
        self._gm_send(pid, "gm_hi", {"h": self._gm_digest(), "n": len(self.gm_recs)})

    def _gm_ev_hi(self, d: dict, data: dict) -> None:
        hashes = self._gm_hashes()
        if data.get("h") == self._gm_digest(hashes):
            return
        recent = sorted(hashes, key=lambda k: -self.gm_recs[k]["t0"])[:8000]
        self._gm_send(d["peer"], "gm_ids", {"ids": {k: hashes[k] for k in recent}})

    def _gm_ev_ids(self, d: dict, data: dict) -> None:
        theirs = data.get("ids")
        if not isinstance(theirs, dict):
            return
        mine = self._gm_hashes()
        want = [k for k, h in theirs.items() if isinstance(k, str) and len(k) == 32 and mine.get(k) != h][:3000]
        if want:
            self._gm_send(d["peer"], "gm_get", {"ids": want})
        give = [k for k, h in mine.items() if theirs.get(k) != h]
        self._gm_send_recs(d["peer"], give)

    def _gm_ev_get(self, d: dict, data: dict) -> None:
        ids = data.get("ids")
        if isinstance(ids, list):
            self._gm_send_recs(d["peer"], [k for k in ids[:3000] if isinstance(k, str) and k in self.gm_recs])

    def _gm_send_recs(self, pid: str, ids: list[str]) -> None:
        batch, size = [], 0
        for k in ids:
            rec = self.gm_recs.get(k)
            if rec is None:
                continue
            n = len(json.dumps(rec, ensure_ascii=False)) + 2
            if batch and size + n > BATCH_BYTES:
                self._gm_send(pid, "gm_recs", {"recs": batch})
                batch, size = [], 0
            batch.append(rec)
            size += n
        if batch:
            self._gm_send(pid, "gm_recs", {"recs": batch})

    def _gm_ev_recs(self, d: dict, data: dict) -> None:
        recs = data.get("recs")
        if not isinstance(recs, list):
            return
        changed = False
        for raw in recs[:600]:
            rec = R.clean_record(raw)
            if rec is not None and self._gm_accept_record(rec, refresh=False):
                changed = True
        if changed:
            self._gm_refresh(("rank", "me", "lobby"))

    def _gm_accept_record(self, rec: dict, refresh: bool = True) -> bool:
        """别人发来的一份记录:验证通过而且比我手上的"更好"才换。返回有没有变化。"""
        res = R.evaluate(rec)
        if not res["ok"]:
            return False
        finished = res["end_i"] is not None or res["status"] == "abandon_pending"
        if not finished and rec["t0"] < now_ms() - STALE_UNFINISHED_MS:
            return False
        old = self.gm_recs.get(rec["id"])
        best = R.better(old, rec)
        if best is old:
            return False
        L = self.gm_live
        if L is not None and L["id"] == rec["id"]:
            self._gm_merge_live(L, best)
            return True
        self.gm_recs[rec["id"]] = best
        self._gm_changed()
        self._gm_check_ack(best, old)
        if refresh:
            self._gm_refresh(("rank", "me", "lobby"))
        return True

    # ---------------------------------------------------------------- 人机练习
    def gm_ai_dialog(self) -> None:
        from ..gomoku.window import AIDialog
        L = self.gm_live
        if L is not None and not L["over"]:
            info(self.gm_win or self, "正在对局", "先把这盘下完再练习吧。")
            return
        dlg = AIDialog(self.gm_win or self)
        if dlg.exec():
            color = dlg.color.current
            if color == "rand":
                color = random.choice("bw")
            self.gm_start_ai(dlg.level.current, color)

    def gm_start_ai(self, level: str, color: str) -> None:
        if self.gm_live is not None and self.gm_live["over"]:
            self.gm_leave(quiet=True)
        self.gm_ai = {"board": Board(), "me": color, "level": level if level in ai.LEVELS else "normal",
                      "t0": now_ms(), "over": False, "result": None, "line": None, "id": uuid.uuid4().hex,
                      "thinking": False, "turn_t": time.monotonic(), "used": {"b": 0.0, "w": 0.0}}
        self.open_gomoku("game")
        if color != "b":
            self._gm_ai_think()
        self._gm_refresh(("game", "lobby"))

    def _gm_ai_play(self, x: int, y: int) -> None:
        A = self.gm_ai
        b = A["board"]
        mine = BLACK if A["me"] == "b" else 2
        if A["over"] or A["thinking"] or b.turn != mine or not b.can_place(x, y):
            return
        self._gm_ai_place(x, y)
        if not A["over"]:
            self._gm_ai_think()

    def _gm_ai_place(self, x: int, y: int) -> None:
        A = self.gm_ai
        b = A["board"]
        mono = time.monotonic()
        A["used"]["b" if b.turn == BLACK else "w"] += mono - A["turn_t"]
        A["turn_t"] = mono
        line = b.place(x, y)
        self._gm_play_stone()
        if line:
            A["line"] = line
            winner = "b" if len(b.moves) % 2 == 1 else "w"
            self._gm_ai_end("win" if winner == A["me"] else "loss",
                            reason="你连成了五子" if winner == A["me"] else "电脑连成了五子")
        elif b.full:
            self._gm_ai_end("draw", reason="棋盘下满了")
        self._gm_refresh(("game",))

    def _gm_ai_think(self) -> None:
        A = self.gm_ai
        A["thinking"] = True
        self._gm_refresh(("game",))
        aid = A["id"]

        def go() -> None:
            B = self.gm_ai
            if B is None or B["id"] != aid or B["over"]:
                return
            x, y = ai.choose(B["board"], B["level"])
            B["thinking"] = False
            self._gm_ai_place(x, y)
        QTimer.singleShot(random.randint(350, 700), go)

    def _gm_ai_request(self, what: str) -> None:
        A = self.gm_ai
        if what == "undo":
            if A["over"] or A["thinking"]:
                return
            b = A["board"]
            mine = BLACK if A["me"] == "b" else 2
            n = 2 if b.turn == mine else 1
            if len(b.moves) - n < (0 if A["me"] == "b" else 1):
                return
            b.undo(n)
            A["turn_t"] = time.monotonic()
        elif what == "restart":
            if not A["over"]:
                self._gm_ai_end(None)
            self.gm_start_ai(A["level"], A["me"])
            return
        elif what == "rematch":
            self.gm_start_ai(A["level"], "w" if A["me"] == "b" else "b")
            return
        self._gm_refresh(("game",))

    def _gm_ai_end(self, result: str | None, reason: str = "") -> None:
        A = self.gm_ai
        if A is None or A["over"]:
            return
        A["over"] = True
        A["result"] = result
        if result is not None:
            self.gm_practice.append({"id": A["id"], "level": A["level"], "color": A["me"], "moves": list(A["board"].moves),
                                     "result": result, "t0": A["t0"], "end_ts": now_ms(), "line": A["line"]})
            self.gm_practice = self.gm_practice[-300:]
            self._gm_changed()
            if self._gm_win_alive():
                title = {"win": "胜利!", "loss": "惜败", "draw": "平局"}[result]
                self.gm_win.show_result(title=title, reason=reason, gained=None, total_from=0, total_to=0,
                                        rank_text="", note="人机练习不计入积分和排行榜", win=result == "win",
                                        can_rematch=True)

    # ---------------------------------------------------------------- 给对局页面的显示数据
    def gm_view(self) -> dict | None:
        if self.gm_ai is not None:
            return self._gm_ai_view()
        L = self.gm_live
        if L is None:
            return None
        res = L["res"]
        rec = L["rec"]
        me, opp = self.gm_my_id(), L["opp"]
        mine = L["me"]
        n = len(res["moves"])
        turn = "b" if n % 2 == 0 else "w"
        online = self._gm_online(opp)
        lim = rec["lim"]

        def player(pid: str, color: str, is_me: bool) -> dict:
            nick = self.me.get("nick", "") if is_me else self._gm_nick(pid)
            on = True if is_me else online
            sub = ("执黑" if color == "b" else "执白") + (" · 我" if is_me else (" · 在线" if on else " · 离线"))
            return {"id": pid, "nick": nick, "black": color == "b", "online": on, "sub": sub}
        players = [player(opp, "w" if mine == "b" else "b", False), player(me, mine, True)]
        kind, status = "", ""
        if L["over"]:
            st = res["status"]
            if st == "void":
                status = "对局作废(重新开始)"
            elif st == "abandon_pending":
                status = "已判掉线负,等待确认" if res["claimant"] == mine else "对方判你掉线负"
            elif st == "draw":
                status, kind = "平局", "draw"
            else:
                win = res["winner"] == mine
                status = ("你赢了 · " if win else "你输了 · ") + STATUS_REASON.get(st, "")
                kind = "win" if win else "loss"
        elif L["off_t"] is not None:
            status, kind = "对方掉线了,计时暂停", "warn"
        elif L["req_out"] is not None:
            status = f"已请求{REQ_NAME[L['req_out']['what']]},等待对方回应…"
        elif turn == mine:
            status, kind = "轮到你落子", "mine"
        else:
            status = "等待对方落子…"
        banner = None
        if L["req_in"] is not None:
            what = L["req_in"]["what"]
            banner = {"undo": "对方请求悔棋,同意吗?", "restart": "对方请求重新开始(这盘作废,不计分),同意吗?",
                      "rematch": "对方想再来一局(交换先后手),同意吗?"}[what]
        pause, claim, claim_text = None, False, "判对方掉线负"
        if not L["over"] and L["off_t"] is not None:
            gone = time.monotonic() - L["off_t"]
            left = max(0, int(OFFLINE_CLAIM - gone))
            pause = (f"对方掉线了,计时已暂停。等他回来会自动接着下。" +
                     (f"\n{left} 秒后可以判对方掉线负。" if left else "\n已经超过 90 秒,可以判对方掉线负(要等对方回来确认才计分)。"))
            claim = left == 0
        elif not L["over"] and L["noresp"]:
            pause = "对方超时还没有落子,可能网络有问题。"
            claim, claim_text = True, "判对方超时负"
        elif L["over"] and L["left"]:
            pause = "对方已经离开了。"
        title = ("每步 " + (f"{lim} 秒" if lim else "不限时")) + f" · 第 {n} 手"
        undo_ok = not L["over"] and L["req_out"] is None and L["off_t"] is None and bool(self._gm_undo_n(res, mine))
        return {"moves": res["moves"], "win_line": res["line"], "my_black": mine == "b",
                "can_play": (not L["over"] and turn == mine and L["off_t"] is None
                             and (L["req_out"] is None or L["req_out"]["what"] == "rematch")),
                "players": players, "status": status, "status_kind": kind, "banner": banner, "pause": pause,
                "claim": claim, "claim_text": claim_text, "title": "联网对战 · 计入排行榜",
                "info": title,
                "buttons": {"undo": undo_ok, "restart": not L["over"] and L["req_out"] is None and L["off_t"] is None,
                            "resign": not L["over"], "rematch": L["over"] and not L["left"] and online
                            and L["req_out"] is None, "over": L["over"]}}

    def _gm_ai_view(self) -> dict:
        A = self.gm_ai
        b = A["board"]
        mine = A["me"]
        n = len(b.moves)
        turn = "b" if n % 2 == 0 else "w"
        ai_color = "w" if mine == "b" else "b"
        players = [{"id": "ai", "nick": f"电脑 · {ai.LEVELS[A['level']]}", "black": ai_color == "b", "online": True,
                    "sub": "执黑" if ai_color == "b" else "执白", "pm": avatar("🤖", "#7C3AED", 56)},
                   {"id": self.gm_my_id(), "nick": self.me.get("nick", ""), "black": mine == "b", "online": True,
                    "sub": ("执黑" if mine == "b" else "执白") + " · 我"}]
        if A["over"]:
            r = A["result"]
            status = {"win": "你赢了!", "loss": "电脑赢了", "draw": "平局", None: "练习已结束"}[r]
            kind = {"win": "win", "loss": "loss", "draw": "draw"}.get(r, "")
        elif A["thinking"] or turn != mine:
            status, kind = "电脑思考中…", ""
        else:
            status, kind = "轮到你落子", "mine"
        my_moves = (n + (1 if mine == "b" else 0)) // 2 if mine == "b" else n // 2
        return {"moves": list(b.moves), "win_line": A["line"], "my_black": mine == "b",
                "can_play": not A["over"] and not A["thinking"] and turn == mine, "players": players,
                "status": status, "status_kind": kind, "banner": None, "pause": None, "claim": False,
                "title": "人机练习 · 不计分", "info": f"第 {n} 手 · 悔棋不限次数",
                "buttons": {"undo": not A["over"] and not A["thinking"] and my_moves > 0, "restart": True,
                            "resign": not A["over"], "rematch": A["over"], "over": A["over"]}}

    def gm_clock_view(self) -> list | None:
        from ..gomoku.widgets import fmt_clock
        mono = time.monotonic()
        if self.gm_ai is not None:
            A = self.gm_ai
            turn = "b" if len(A["board"].moves) % 2 == 0 else "w"
            out = []
            for color in ("w" if A["me"] == "b" else "b", A["me"]):
                used = A["used"][color] + (mono - A["turn_t"] if color == turn and not A["over"] else 0)
                out.append({"text": "", "frac": 1.0, "active": color == turn and not A["over"],
                            "total": f"用时 {fmt_clock(used)}"})
            return out
        L = self.gm_live
        if L is None:
            return None
        lim = L["rec"]["lim"]
        turn = "b" if len(L["res"]["moves"]) % 2 == 0 else "w"
        now = L["off_t"] if L["off_t"] is not None else mono
        out = []
        for color in ("w" if L["me"] == "b" else "b", L["me"]):
            active = color == turn and not L["over"]
            elapsed = max(0.0, now - L["turn_t"]) if active else 0.0
            used = L["used"][color] + elapsed
            if lim:
                left = max(0.0, lim - elapsed) if active else float(lim)
                text, frac = fmt_clock(left), left / lim
            else:
                text, frac = ("思考中" if active else ""), 1.0
            out.append({"text": text, "frac": frac, "active": active, "total": f"共用时 {fmt_clock(used)}"})
        return out

    def gm_replay(self, kind: str, item: dict) -> None:
        if not self._gm_win_alive():
            return
        if kind == "ai":
            black = self.me.get("nick", "") if item.get("color") == "b" else f"电脑({ai.LEVELS.get(item.get('level'), '')})"
            white = f"电脑({ai.LEVELS.get(item.get('level'), '')})" if item.get("color") == "b" else self.me.get("nick", "")
            moves, line, title = item.get("moves") or [], item.get("line"), "人机练习"
        else:
            rec = self.gm_recs.get(item["id"])
            if rec is None:
                return
            res = R.evaluate(rec)
            moves, line, black, white = res["moves"], res["line"], rec["nb"], rec["nw"]
            title = f"{rec['nb']} vs {rec['nw']}"
        self.gm_win.go("game")
        self.gm_win.pages["game"].start_replay(moves, title, black, white, line)
