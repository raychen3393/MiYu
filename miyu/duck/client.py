"""
谁是坏鸭 · 每个玩家自己这边的状态(纯逻辑)。
房主每秒发十几次「画面」(snapshot):视野里的人在哪、尸体、任务进度、开会倒计时……
自己的位置在本地先走(按键立刻有反应),房主不认可时(穿墙、走太快、开完会集合)才跳回房主给的位置。
别人的位置往回放 0.12 秒、在两次画面之间插值,看起来是顺滑地走,不是一格一格地跳。
"""
from __future__ import annotations

import collections

from . import world as Wd
from .rules import DETECTIVE, DUCK, GOOSE, LIGHTS_FIX_RANGE, ROLE_NAME as ROLE_NAMES, SHERIFF

INTERP_DELAY = 0.12


class Client:
    def __init__(self, info: dict, me: str, host: str, now: float = 0.0) -> None:
        self.me, self.host = me, host
        self.gid = info.get("gid", "")
        self.s = info.get("s") or {}
        self.role = info.get("role", GOOSE)
        self.tasks: list[str] = [t for t in info.get("tasks") or [] if t in Wd.TASK_BY_ID]
        self.mates: set[str] = set(info.get("mates") or [])
        self.roster: dict[str, dict] = {}
        for r in info.get("roster") or []:
            if isinstance(r, dict) and isinstance(r.get("id"), str):
                self.roster[r["id"]] = {"nick": str(r.get("nick", "?"))[:20], "color": r.get("color", "red")}
        self.x, self.y = Wd.BUTTON
        self.f = 1
        self.tp = -1
        self.alive = True
        self.phase = "play"
        self.left = 0.0
        self.left_at = now
        self.bufs: dict[str, collections.deque] = {}
        self.alive_of: dict[str, int] = {}
        self.bodies: list[list] = []
        self.done: set[str] = set()
        self.task_bar = (0, 1)
        self.lights_off = False
        self.locked: set[str] = set()
        self.kill_cd = 0.0
        self.sabo_cd = 0.0
        self.vote_in = 0.0
        self.voted: set[str] = set()
        self.buttons = 0
        self.fixing = False
        self.chat: list[dict] = []
        self.meeting: dict | None = None
        self.eject: dict | None = None
        self.over: dict | None = None
        self.dead_by: str | None = None
        self.gone: set[str] = set()
        self.fx: list[dict] = []                   # 刀人的羽毛之类,界面上播一下
        self.last_snap = now
        self.walking = False
        self.my_vote: str | None = None
        self.snaps = 0
        self.lag_of: dict[str, int] = {}           # 掉线中(还没出局)的人
        self.checks_left = 0                       # 侦探还能查验几次
        self.checked: dict[str, bool] = {}         # 侦探查过的人 → 是不是坏鸭
        self.misfire: str | None = None            # 警长刀错了谁
        self.log: list[dict] = []

    # ---------------------------------------------------------------- 名字颜色
    def nick(self, pid: str) -> str:
        return self.roster.get(pid, {}).get("nick", "?")

    def color(self, pid: str) -> str:
        c = Wd.COLOR_BY_ID.get(self.roster.get(pid, {}).get("color", ""))
        return c[2] if c else "#CCCCCC"

    # ---------------------------------------------------------------- 收房主的画面
    def apply_snapshot(self, snap: dict, now: float) -> None:
        if not isinstance(snap, dict) or not snap:
            return
        self.snaps += 1
        self.last_snap = now
        ph = snap.get("ph")
        if ph in ("play", "meeting", "eject", "over"):
            self.phase = ph
        self.left = float(snap.get("left") or 0)
        self.left_at = now
        me = snap.get("me")
        if isinstance(me, list) and len(me) == 4:
            if me[2] != self.tp:                       # 房主让我跳过去(刚开局、开完会、被拉回)
                self.tp = me[2]
                self.x, self.y = float(me[0]), float(me[1])
            self.alive = bool(me[3])
        seen = set()
        for row in snap.get("p") or []:
            if not (isinstance(row, list) and len(row) in (5, 6) and isinstance(row[0], str)):
                continue
            pid, x, y, f, alive = row[:5]
            self.alive_of[pid] = alive
            self.lag_of[pid] = row[5] if len(row) == 6 else 0
            if pid == self.me:
                continue
            seen.add(pid)
            buf = self.bufs.setdefault(pid, collections.deque(maxlen=12))
            buf.append((now, float(x), float(y), 1 if f == 1 else -1))
        for pid in list(self.bufs):                    # 看不见的人:从画面上拿掉
            if pid not in seen:
                del self.bufs[pid]
        self.bodies = [b for b in (snap.get("b") or []) if isinstance(b, list) and len(b) == 3]
        tb = snap.get("tb")
        if isinstance(tb, list) and len(tb) == 2:
            self.task_bar = (int(tb[0]), max(1, int(tb[1])))
        self.lights_off = bool(snap.get("lo"))
        self.locked = set(snap.get("lk") or [])
        self.done = set(snap.get("dn") or [])
        self.buttons = int(snap.get("bt") or 0)
        self.kill_cd = float(snap.get("kc") or 0)
        self.sabo_cd = float(snap.get("sc") or 0)
        self.vote_in = float(snap.get("mv") or 0)
        self.voted = set(snap.get("vd") or [])
        self.fixing = bool(snap.get("fx"))
        self.checks_left = int(snap.get("ck") or 0)

    def apply_event(self, ev: dict, now: float) -> None:
        e = ev.get("e") if isinstance(ev, dict) else None
        if e == "dead":
            self.alive = False
            self.dead_by = ev.get("by")
            self.misfire = ev.get("misfire")
        elif e == "checked":
            if isinstance(ev.get("t"), str):
                self.checked[ev["t"]] = bool(ev.get("duck"))
        elif e == "kill_fx":
            self.fx.append({"k": "feathers", "x": ev.get("x", 0), "y": ev.get("y", 0), "t": now,
                            "c": self.color(ev.get("t", ""))})
        elif e == "meeting":
            self.meeting = {"caller": ev.get("caller"), "body": ev.get("body"), "t": now}
            self.phase = "meeting"
            self.my_vote = None
            self.chat = [c for c in self.chat if c.get("ghost")][-30:]
        elif e == "voted":
            self.voted.add(ev.get("by"))
        elif e == "eject":
            self.eject = {"out": ev.get("out"), "role": ev.get("role"), "votes": ev.get("votes") or {}, "t": now}
            self.phase = "eject"
            self.meeting = None
            if ev.get("out") == self.me:
                self.alive = False
        elif e == "chat":
            self.chat.append({"by": ev.get("by"), "text": str(ev.get("text", ""))[:120], "ghost": bool(ev.get("ghost")),
                              "t": now})
            self.chat = self.chat[-80:]
        elif e == "over":
            self.over = {"win": ev.get("win"), "why": ev.get("why", ""), "roles": ev.get("roles") or {}, "t": now}
            self.log = [x for x in (ev.get("log") or []) if isinstance(x, dict)][-80:]
            self.phase = "over"
        elif e == "left":
            self.gone.add(ev.get("id"))
        elif e == "resume":
            self.eject = None
            self.phase = "play"

    # ---------------------------------------------------------------- 自己走
    def step(self, ix: float, iy: float, dt: float, busy: bool = False) -> bool:
        """按键方向 (ix, iy) 走 dt 秒。返回有没有动。"""
        self.walking = False
        if self.phase != "play" or busy or (ix == 0 and iy == 0):
            return False
        n = (ix * ix + iy * iy) ** 0.5
        sp = Wd.SPEED * (1.15 if not self.alive else 1.0)
        dx, dy = ix / n * sp * dt, iy / n * sp * dt
        nx, ny = Wd.move(self.x, self.y, dx, dy, frozenset(self.locked), ghost=not self.alive)
        moved = (nx, ny) != (self.x, self.y)
        if ix:
            self.f = 1 if ix > 0 else -1
        self.x, self.y = nx, ny
        self.walking = moved
        return moved

    def pos_of(self, pid: str, now: float) -> tuple[float, float, int] | None:
        if pid == self.me:
            return self.x, self.y, self.f
        buf = self.bufs.get(pid)
        if not buf:
            return None
        t = now - INTERP_DELAY
        if t <= buf[0][0]:
            return buf[0][1], buf[0][2], buf[0][3]
        for a, b in zip(buf, list(buf)[1:]):
            if a[0] <= t <= b[0]:
                k = (t - a[0]) / max(1e-6, b[0] - a[0])
                return a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, b[3]
        last = buf[-1]
        return last[1], last[2], last[3]

    def moving(self, pid: str) -> bool:
        if pid == self.me:
            return self.walking
        buf = self.bufs.get(pid)
        if not buf or len(buf) < 2:
            return False
        a, b = buf[-2], buf[-1]
        return abs(a[1] - b[1]) + abs(a[2] - b[2]) > 1.5

    def visible_ids(self) -> list[str]:
        return list(self.bufs)

    def phase_left(self, now: float) -> float:
        return max(0.0, self.left - (now - self.left_at))

    # ---------------------------------------------------------------- 附近能做什么
    def near_task(self) -> str | None:
        if self.phase != "play":
            return None
        best, bd = None, Wd.USE_RANGE
        for tid in self.tasks:
            if tid in self.done:
                continue
            t = Wd.TASK_BY_ID[tid]
            d = Wd.dist(self.x, self.y, t[3], t[4])
            if d <= bd:
                best, bd = tid, d
        return best

    def near_switch(self) -> bool:
        if self.phase != "play" or not self.alive or not self.lights_off:
            return False
        _r, sx, sy = Wd.LIGHT_SWITCH
        return Wd.dist(self.x, self.y, sx, sy) <= LIGHTS_FIX_RANGE

    def near_button(self) -> bool:
        return self.phase == "play" and self.alive and Wd.dist(self.x, self.y, *Wd.BUTTON) <= Wd.BUTTON_RANGE

    def near_body(self) -> str | None:
        if self.phase != "play" or not self.alive:
            return None
        for b in self.bodies:
            if Wd.dist(self.x, self.y, b[1], b[2]) <= Wd.REPORT_RANGE:
                return b[0]
        return None

    def kill_target(self, now: float) -> str | None:
        """坏鸭能刀的人 / 警长能执法的人(离得够近、看得见的活人)。"""
        if self.phase != "play" or self.role not in (DUCK, SHERIFF) or not self.alive:
            return None
        return self._nearest(now, skip_mates=self.role == DUCK)

    def check_target(self, now: float) -> str | None:
        if self.phase != "play" or self.role != DETECTIVE or not self.alive or self.checks_left <= 0:
            return None
        return self._nearest(now, skip_mates=False)

    def _nearest(self, now: float, skip_mates: bool) -> str | None:
        best, bd = None, Wd.KILL_RANGE
        for pid in self.bufs:
            if (skip_mates and pid in self.mates) or not self.alive_of.get(pid):
                continue
            pos = self.pos_of(pid, now)
            if pos is None:
                continue
            d = Wd.dist(self.x, self.y, pos[0], pos[1])
            if d <= bd:
                best, bd = pid, d
        return best

    def use_action(self) -> tuple[str, str | None] | None:
        """「使用」键现在会做什么:修电闸 / 做任务 / 按紧急按钮。"""
        if self.near_switch():
            return ("switch", None)
        t = self.near_task()
        if t is not None:
            return ("task", t)
        if self.near_button():
            return ("button", None)
        return None

    def log_lines(self) -> list[str]:
        """结算时间线:「02:13 小明在厨房刀了阿花」。"""
        out = []
        for e in self.log:
            t = float(e.get("t") or 0)
            stamp = f"{int(t // 60):02d}:{int(t % 60):02d}"
            a, b = self.nick(e.get("a") or ""), self.nick(e.get("b") or "")
            room = Wd.room_name(e.get("room")) if e.get("room") else ""
            k = e.get("k")
            text = {
                "kill": f"🔪 {a} 在{room}刀了 {b}",
                "shot": f"🔫 警长 {a} 在{room}执法,淘汰了坏鸭 {b}",
                "misfire": f"💥 警长 {a} 执法 {b} 失误,自己倒下了",
                "report": f"🚨 {a} 发现了 {b} 的尸体",
                "button": f"🔔 {a} 按下了紧急按钮",
                "eject": (f"🗳 {a} 被投出去了" + (f"(是{ROLE_NAMES.get(e.get('role'), '')})" if e.get("role") else ""))
                         if e.get("a") else "🗳 投票没有结果,没人出局",
                "lights": f"💡 {a} 关了灯", "fixed": f"⚡ {a} 修好了电闸",
                "doors": f"🚪 {a} 锁了{room}的门", "left": f"🚶 {a} 离开了游戏",
                "over": f"🏁 {ROLE_NAMES.get(e.get('role'), '')}获胜",
            }.get(k)
            if text:
                out.append(f"{stamp}  {text}")
        return out

    def my_tasks(self) -> list[tuple[str, str, str, bool]]:
        """任务清单:(id, 房间名, 任务名, 做完没)。"""
        out = []
        for tid in self.tasks:
            t = Wd.TASK_BY_ID[tid]
            out.append((tid, Wd.room_name(t[2]), t[5], tid in self.done))
        return out
