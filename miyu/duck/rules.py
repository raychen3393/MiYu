"""
谁是坏鸭 · 规则和房主裁判(纯逻辑,不依赖界面)。

身份  好鹅(大多数):做任务,任务全部做完或者把坏鸭全投出去就赢。
      坏鸭(1~3 只,按人数):可以刀人(有冷却)、搞破坏(关灯 / 锁门),坏鸭数量 ≥ 其他活着的人就赢。
      呆呆鹅(中立,6 人以上可选):被大家投票投出去就单独获胜。
流程  发现尸体可以报告、每人有一次紧急按钮 → 开会:先讨论一会儿,然后投票(可以弃票),
      票最多的被投出去(平票没人出局)。死了变幽灵:能穿墙、还能做任务,只能和幽灵说话。
房主的电脑当裁判:判定刀人的距离和冷却、任务进度、投票结果、胜负。每个人只收到自己该知道的东西
(自己的身份;坏鸭知道同伴;视野外的人不发位置)。房主的软件知道所有人的身份 —— 界面上不显示给房主,
但改过的客户端理论上能看到,所以这个游戏不计入任何排行榜。
"""
from __future__ import annotations

import random

from . import world as Wd

GOOSE, DUCK, DODO, SHERIFF, DETECTIVE = "goose", "duck", "dodo", "sheriff", "detective"
ROLE_NAME = {GOOSE: "好鹅", DUCK: "坏鸭", DODO: "呆呆鹅", SHERIFF: "警长", DETECTIVE: "侦探"}
TEAM_NAME = {GOOSE: "好鹅", DUCK: "坏鸭", DODO: "呆呆鹅"}
GOOSE_TEAM = {GOOSE, SHERIFF, DETECTIVE}       # 警长和侦探都是好鹅阵营


def team_of(role: str) -> str:
    return GOOSE if role in GOOSE_TEAM else role
MIN_PLAYERS, MAX_PLAYERS = 4, 10
DEFAULTS = {"ducks": 0, "dodo": True, "kill_cd": 25, "tasks": 5, "discuss": 15, "vote": 45, "reveal": True,
            "buttons": 1, "sabo_cd": 30, "sheriff": True, "detective": True}
BOOL_KEYS = ("dodo", "reveal", "sheriff", "detective")
LIMITS = {"ducks": (0, 3), "kill_cd": (10, 60), "tasks": (2, 8), "discuss": (0, 60), "vote": (15, 120),
          "buttons": (0, 3), "sabo_cd": (15, 90)}
START_KILL_CD = 12.0          # 开局 / 开完会后刀的冷却先短一点
MEETING_GAP = 10.0            # 开完会 10 秒内不能按紧急按钮
EJECT_SECS = 6.0              # 投票结果动画
LEFT_AFTER = 30.0             # 这么久没收到某人的位置才算他出局(30 秒内连回来可以接着玩)
LAG_AFTER = 4.0               # 这么久没收到位置:别人那边先显示「掉线中」
DOORS_SECS = 10.0
FIX_SECS = 1.2                # 拨电闸要按住多久(界面里是个小游戏,这里只是最短时间)
LIGHTS_FIX_RANGE = 80.0


def clean_settings(d) -> dict:
    out = dict(DEFAULTS)
    if isinstance(d, dict):
        for k, v in d.items():
            if k in LIMITS and type(v) is int:
                lo, hi = LIMITS[k]
                out[k] = max(lo, min(hi, v))
            elif k in BOOL_KEYS and isinstance(v, bool):
                out[k] = v
    return out


def duck_count(n: int, wanted: int = 0) -> int:
    auto = 1 if n <= 6 else 2
    if wanted <= 0:
        return auto
    return max(1, min(wanted, (n - 1) // 3 if n >= 7 else 1, 3))


class Game:
    """房主那边的权威状态。时间都用 time.monotonic() 的秒数(由调用的人传进来,方便测试)。"""

    def __init__(self, roster: list[dict], settings: dict | None = None, seed: int | None = None,
                 now: float = 0.0, practice: bool = False) -> None:
        self.practice = practice                    # 单人试玩:只有自己,没有坏鸭,做完任务就结束
        if not (MIN_PLAYERS <= len(roster) <= MAX_PLAYERS) and not (practice and 1 <= len(roster) <= MAX_PLAYERS):
            raise ValueError("人数不对")
        self.rng = random.Random(seed)
        self.s = clean_settings(settings)
        self.gid = "%012x" % self.rng.getrandbits(48)
        ids = [r["id"] for r in roster]
        n = len(ids)
        order = ids[:]
        self.rng.shuffle(order)
        nd = 0 if practice else duck_count(n, self.s["ducks"])
        roles = {pid: GOOSE for pid in ids}
        for pid in order[:nd]:
            roles[pid] = DUCK
        rest = order[nd:]
        if self.s["dodo"] and n >= 6 and not practice:
            roles[rest.pop(0)] = DODO
        if self.s["sheriff"] and n >= 5 and not practice and rest:
            roles[rest.pop(0)] = SHERIFF
        if self.s["detective"] and n >= 6 and not practice and rest:
            roles[rest.pop(0)] = DETECTIVE
        spots = Wd.spawn_points(n)
        self.players: dict[str, dict] = {}
        task_ids = [t[0] for t in Wd.TASK_SPOTS]
        for i, r in enumerate(roster):
            pid = r["id"]
            tasks = self.rng.sample(task_ids, min(self.s["tasks"], len(task_ids)))
            self.players[pid] = {
                "id": pid, "nick": str(r.get("nick", "?"))[:20], "color": r.get("color", Wd.COLORS[i % 10][0]),
                "role": roles[pid], "alive": True, "left": False, "x": spots[i][0], "y": spots[i][1], "f": 1,
                "tasks": tasks, "done": set(), "buttons": self.s["buttons"], "kill_at": now + START_KILL_CD,
                "seen": now, "tp": 0, "voted": None, "fix_t": None, "checks": 1 if roles[pid] == DETECTIVE else 0,
            }
        self.phase = "play"
        self.phase_end = 0.0
        self.bodies: list[dict] = []
        self.meeting: dict | None = None
        self.last_meeting_end = now
        self.lights_off = False
        self.locked: dict[str, float] = {}          # 房间 → 锁到什么时候
        self.sabo_at = now + 15.0                   # 开局 15 秒后才能搞破坏
        self.winner: str | None = None
        self.win_reason = ""
        self.events: list[tuple] = []               # (发给谁 None=所有人 / 列表, 事件) 由调用的人取走发出去
        self.chat: list[dict] = []
        self.kills = 0
        self.t0 = now
        self.log: list[dict] = []                   # 结算时给大家看的时间线
        self.rounds = 0

    # ---------------------------------------------------------------- 查询
    def p(self, pid: str) -> dict | None:
        return self.players.get(pid)

    def alive(self, role: str | None = None) -> list[dict]:
        return [p for p in self.players.values() if p["alive"] and (role is None or p["role"] == role)]

    def locked_set(self) -> frozenset:
        return frozenset(self.locked)

    def task_progress(self) -> tuple[int, int]:
        total = done = 0
        for p in self.players.values():
            if p["role"] not in GOOSE_TEAM:
                continue
            total += len(p["tasks"])
            done += len(p["done"])
        return done, total

    def vision(self, p: dict) -> float:
        if not p["alive"]:
            return 99999.0
        if self.lights_off and p["role"] != DUCK:
            return Wd.VISION_DARK
        return Wd.VISION

    def can_see(self, viewer: dict, other: dict) -> bool:
        if viewer is other or not viewer["alive"]:
            return True
        if not other["alive"]:
            return False                             # 活人看不到幽灵
        if Wd.dist(viewer["x"], viewer["y"], other["x"], other["y"]) > self.vision(viewer) + 40:
            return False
        return Wd.line_of_sight(viewer["x"], viewer["y"], other["x"], other["y"], self.locked_set())

    # ---------------------------------------------------------------- 输入
    def emit(self, to, ev: dict) -> None:
        self.events.append((to, ev))

    def take_events(self) -> list[tuple]:
        ev, self.events = self.events, []
        return ev

    def on_input(self, pid: str, x, y, f, dt: float, now: float) -> bool:
        """玩家报告自己的位置。走得太快 / 穿墙的拉回去(tp+1 让他的软件跳回服务器认的位置)。"""
        p = self.players.get(pid)
        if p is None or p["left"] or self.phase != "play":
            if p is not None:
                p["seen"] = now
            return False
        p["seen"] = now
        try:
            x, y = float(x), float(y)
        except (TypeError, ValueError):
            return False
        if not (0 <= x <= Wd.W and 0 <= y <= Wd.H):
            return False
        limit = Wd.SPEED * max(0.05, min(dt, 1.0)) * 1.6 + 30
        ok = Wd.dist(x, y, p["x"], p["y"]) <= limit
        if ok and p["alive"]:
            locked = self.locked_set()
            stuck = not Wd.walkable(p["x"], p["y"], locked)      # 门刚锁上时正好站在门口:放他出来
            ok = stuck or (Wd.walkable(x, y, locked, inset=Wd.PLAYER_R - 6)
                           and Wd.path_clear(p["x"], p["y"], x, y, locked))
        if not ok:
            p["tp"] += 1
            return False
        p["x"], p["y"] = x, y
        p["f"] = 1 if f == 1 else -1 if f == -1 else p["f"]
        return True

    def act(self, pid: str, a: str, data: dict, now: float) -> str | None:
        """玩家的动作。成功返回 None,不行返回原因(给他自己看)。"""
        p = self.players.get(pid)
        if p is None or p["left"] or self.winner:
            return "不在游戏中"
        data = data if isinstance(data, dict) else {}
        fn = getattr(self, "_a_" + a, None) if isinstance(a, str) and a.isidentifier() else None
        if fn is None:
            return "不认识的操作"
        return fn(p, data, now)

    # ---- 刀人(坏鸭)/ 开枪(警长)
    def _a_kill(self, p: dict, data: dict, now: float) -> str | None:
        if self.phase != "play" or p["role"] not in (DUCK, SHERIFF) or not p["alive"]:
            return "现在不能刀"
        if now < p["kill_at"]:
            return "还在冷却"
        t = self.players.get(data.get("t"))
        if t is None or t is p or not t["alive"]:
            return "目标不对"
        if p["role"] == DUCK and t["role"] == DUCK:
            return "那是你的同伴"
        if Wd.dist(p["x"], p["y"], t["x"], t["y"]) > Wd.KILL_RANGE + 35:
            return "离得太远"
        if not Wd.line_of_sight(p["x"], p["y"], t["x"], t["y"], self.locked_set()):
            return "隔着墙"
        p["kill_at"] = now + self.s["kill_cd"]
        if p["role"] == SHERIFF and t["role"] != DUCK:      # 警长刀错了:自己倒下
            self._die(p, None, now, misfire=t["id"])
        else:
            if p["role"] == DUCK:
                p["x"], p["y"] = t["x"], t["y"]             # 坏鸭扑到尸体的位置
                p["tp"] += 1
            self._die(t, p, now)
        self.check_win(now)
        return None

    def _die(self, t: dict, killer: dict | None, now: float, misfire: str | None = None) -> None:
        t["alive"] = False
        t["fix_t"] = None
        self.kills += 1
        self.bodies.append({"id": t["id"], "x": t["x"], "y": t["y"], "color": t["color"], "t": now})
        rid = Wd.room_at(t["x"], t["y"])
        if misfire:
            self.emit([t["id"]], {"e": "dead", "by": t["id"], "misfire": misfire})
            self.log_add(now, "misfire", a=t["id"], b=misfire, room=rid)
        else:
            self.emit([t["id"]], {"e": "dead", "by": killer["id"], "sheriff": killer["role"] == SHERIFF})
            self.emit([killer["id"]], {"e": "killed", "t": t["id"]})
            self.log_add(now, "shot" if killer["role"] == SHERIFF else "kill", a=killer["id"], b=t["id"], room=rid)
        fx = {"e": "kill_fx", "x": round(t["x"]), "y": round(t["y"]), "t": t["id"]}
        seen = [q["id"] for q in self.players.values()
                if not q["left"] and (not q["alive"] or q is killer or self._sees_point(q, t["x"], t["y"]))]
        self.emit(seen, fx)                                  # 只有看得见那个位置的人才知道这里出事了

    def _sees_point(self, q: dict, x: float, y: float) -> bool:
        return (Wd.dist(q["x"], q["y"], x, y) <= self.vision(q) + 40
                and Wd.line_of_sight(q["x"], q["y"], x, y, self.locked_set()))

    # ---- 侦探:每局可以查验一个人是不是坏鸭(只有自己知道结果)
    def _a_check(self, p: dict, data: dict, now: float) -> str | None:
        if self.phase != "play" or p["role"] != DETECTIVE or not p["alive"]:
            return "现在不能查验"
        if p["checks"] <= 0:
            return "这局的查验次数用完了"
        t = self.players.get(data.get("t"))
        if t is None or t is p or not t["alive"]:
            return "目标不对"
        if Wd.dist(p["x"], p["y"], t["x"], t["y"]) > Wd.KILL_RANGE + 35:
            return "离得太远"
        p["checks"] -= 1
        self.emit([p["id"]], {"e": "checked", "t": t["id"], "duck": t["role"] == DUCK})
        return None

    def log_add(self, now: float, kind: str, **kw) -> None:
        self.log.append({"t": round(now - self.t0, 1), "k": kind, **kw})

    # ---- 报告 / 紧急按钮
    def _a_report(self, p: dict, data: dict, now: float) -> str | None:
        if self.phase != "play" or not p["alive"]:
            return "现在不能报告"
        b = next((b for b in self.bodies if Wd.dist(p["x"], p["y"], b["x"], b["y"]) <= Wd.REPORT_RANGE + 30), None)
        if b is None:
            return "附近没有尸体"
        self.start_meeting(p["id"], b["id"], now)
        return None

    def _a_button(self, p: dict, data: dict, now: float) -> str | None:
        if self.phase != "play" or not p["alive"]:
            return "现在不能开会"
        if p["buttons"] <= 0:
            return "你的紧急按钮次数用完了"
        if now - self.last_meeting_end < MEETING_GAP:
            return f"刚开完会,{int(MEETING_GAP - (now - self.last_meeting_end)) + 1} 秒后才能按"
        if self.lights_off:
            return "关灯时不能按紧急按钮,先去配电室修电闸"
        if Wd.dist(p["x"], p["y"], *Wd.BUTTON) > Wd.BUTTON_RANGE + 30:
            return "离按钮太远"
        p["buttons"] -= 1
        self.start_meeting(p["id"], None, now)
        return None

    def start_meeting(self, caller: str, body: str | None, now: float) -> None:
        self.phase = "meeting"
        self.phase_end = now + self.s["discuss"] + self.s["vote"]
        self.meeting = {"caller": caller, "body": body, "votes": {}, "vote_at": now + self.s["discuss"],
                        "start": now}
        self.rounds += 1
        self.log_add(now, "report" if body else "button", a=caller, b=body)
        self.bodies = []
        self.lights_off = False
        self.locked = {}
        for q in self.players.values():
            q["voted"] = None
            q["fix_t"] = None
        self.emit(None, {"e": "meeting", "caller": caller, "body": body})

    def _a_vote(self, p: dict, data: dict, now: float) -> str | None:
        m = self.meeting
        if self.phase != "meeting" or m is None or not p["alive"]:
            return "现在不能投票"
        if now < m["vote_at"]:
            return "还在讨论,等一下再投"
        if p["id"] in m["votes"]:
            return "已经投过了"
        t = data.get("t")
        if t != "skip":
            q = self.players.get(t)
            if q is None or not q["alive"]:
                return "不能投给这个人"
        m["votes"][p["id"]] = t
        self.emit(None, {"e": "voted", "by": p["id"]})
        if len(m["votes"]) >= len(self.alive()):
            self.end_meeting(now)
        return None

    def end_meeting(self, now: float) -> None:
        m = self.meeting
        if m is None:
            return
        tally: dict[str, int] = {}
        for t in m["votes"].values():
            tally[t] = tally.get(t, 0) + 1
        out = None
        if tally:
            best = max(tally.values())
            top = [k for k, v in tally.items() if v == best]
            if len(top) == 1 and top[0] != "skip":
                out = top[0]
        role = None
        if out is not None:
            q = self.players[out]
            q["alive"] = False
            role = q["role"]
        self.log_add(now, "eject", a=out, role=role)
        ev = {"e": "eject", "votes": dict(m["votes"]), "out": out}
        if out is not None and self.s["reveal"]:
            ev["role"] = role
        self.emit(None, ev)
        self.meeting = None
        self.phase = "eject"
        self.phase_end = now + EJECT_SECS
        if out is not None and role == DODO:
            self.finish(DODO, "呆呆鹅被投出去了,它赢了!", now)
            return
        self.check_win(now, after_eject=True)

    def _a_chat(self, p: dict, data: dict, now: float) -> str | None:
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            return "空消息"
        text = text.strip()[:120]
        if p["alive"] and self.phase not in ("meeting", "eject", "over"):
            return "只有开会的时候才能说话"
        msg = {"e": "chat", "by": p["id"], "text": text, "ghost": not p["alive"]}
        self.chat.append(msg)
        to = None if p["alive"] else [q["id"] for q in self.players.values() if not q["alive"]]
        self.emit(to, msg)
        return None

    # ---- 任务
    def _a_task(self, p: dict, data: dict, now: float) -> str | None:
        tid = data.get("t")
        if self.phase != "play" or tid not in p["tasks"] or tid in p["done"]:
            return "这个任务不用做"
        spot = Wd.TASK_BY_ID.get(tid)
        if spot is None or Wd.dist(p["x"], p["y"], spot[3], spot[4]) > Wd.USE_RANGE + 40:
            return "离任务点太远"
        p["done"].add(tid)
        if p["role"] in GOOSE_TEAM:
            self.check_win(now)
        return None

    # ---- 破坏 / 修
    def _a_sabo(self, p: dict, data: dict, now: float) -> str | None:
        if self.phase != "play" or p["role"] != DUCK or not p["alive"]:
            return "现在不能搞破坏"
        if now < self.sabo_at:
            return f"破坏还在冷却({int(self.sabo_at - now) + 1} 秒)"
        k = data.get("k")
        if k == "lights":
            if self.lights_off:
                return "已经关灯了"
            self.lights_off = True
            self.emit(None, {"e": "sabo", "k": "lights"})
            self.log_add(now, "lights", a=p["id"])
        elif k == "doors":
            room = data.get("room")
            if room not in Wd.DOORS or not Wd.DOORS[room] or room in self.locked:
                return "这个房间锁不了"
            self.locked[room] = now + DOORS_SECS
            self.emit(None, {"e": "sabo", "k": "doors", "room": room})
            self.log_add(now, "doors", a=p["id"], room=room)
        else:
            return "不认识的破坏"
        self.sabo_at = now + self.s["sabo_cd"]
        return None

    def _a_fix(self, p: dict, data: dict, now: float) -> str | None:
        """修电闸:先发 fix(开始),过 FIX_SECS 秒再发 fix done(界面上的小游戏做完)。"""
        if self.phase != "play" or not p["alive"] or not self.lights_off:
            return "不用修"
        _r, sx, sy = Wd.LIGHT_SWITCH
        if Wd.dist(p["x"], p["y"], sx, sy) > LIGHTS_FIX_RANGE + 40:
            return "离电闸太远"
        if not data.get("done"):
            p["fix_t"] = now
            return None
        if p["fix_t"] is None or now - p["fix_t"] < FIX_SECS:
            return "还没修好"
        self.lights_off = False
        p["fix_t"] = None
        self.emit(None, {"e": "fixed", "k": "lights", "by": p["id"]})
        self.log_add(now, "fixed", a=p["id"])
        return None

    # ---------------------------------------------------------------- 时间流逝
    def tick(self, now: float) -> None:
        if self.winner:
            return
        for room in [r for r, t in self.locked.items() if now >= t]:
            self.locked.pop(room, None)
            self.emit(None, {"e": "unlocked", "room": room})
        for p in self.players.values():                 # 掉线的人:当他出局(不留尸体)
            if not p["left"] and now - p["seen"] > LEFT_AFTER and not p.get("host") and not self.practice:
                self.leave(p["id"], now)
        if self.phase == "meeting" and now >= self.phase_end:
            self.end_meeting(now)
        elif self.phase == "eject" and now >= self.phase_end:
            self.phase = "play"
            self.last_meeting_end = now
            spots = Wd.spawn_points(len(self.players))
            for i, p in enumerate(self.players.values()):
                p["x"], p["y"] = spots[i]
                p["tp"] += 1
                if p["role"] == DUCK:
                    p["kill_at"] = now + max(START_KILL_CD, self.s["kill_cd"] * 0.6)
            self.sabo_at = max(self.sabo_at, now + 12.0)
            self.emit(None, {"e": "resume"})

    def leave(self, pid: str, now: float) -> None:
        p = self.players.get(pid)
        if p is None or p["left"]:
            return
        p["left"] = True
        was_alive = p["alive"]
        p["alive"] = False
        self.emit(None, {"e": "left", "id": pid})
        self.log_add(now, "left", a=pid)
        if self.meeting is not None:
            self.meeting["votes"].pop(pid, None)
            if was_alive and len(self.meeting["votes"]) >= len(self.alive()) and self.alive():
                self.end_meeting(now)
                return
        if was_alive:
            self.check_win(now)

    # ---------------------------------------------------------------- 胜负
    def check_win(self, now: float, after_eject: bool = False) -> str | None:
        if self.winner:
            return self.winner
        ducks = len(self.alive(DUCK))
        others = len(self.alive()) - ducks
        done, total = self.task_progress()
        if self.practice:
            if total and done >= total:
                return self.finish(GOOSE, "试玩完成:所有任务都做完了", now)
            return None
        if ducks == 0:
            return self.finish(GOOSE, "坏鸭全部被淘汰了", now)
        if ducks >= others:
            return self.finish(DUCK, "坏鸭的数量追上了其他人", now)
        if total and done >= total:
            return self.finish(GOOSE, "好鹅完成了所有任务", now)
        return None

    def finish(self, team: str, reason: str, now: float) -> str:
        self.winner = team
        self.win_reason = reason
        self.phase = "over"
        self.log_add(now, "over", role=team)
        self.emit(None, {"e": "over", "win": team, "why": reason, "log": self.log[-80:],
                         "roles": {pid: p["role"] for pid, p in self.players.items()}})
        return team

    # ---------------------------------------------------------------- 发给每个人的画面
    def snapshot_for(self, pid: str, now: float) -> dict:
        me = self.players.get(pid)
        if me is None:
            return {}
        others = []
        for q in self.players.values():
            if q["left"] and q["id"] != pid:
                continue
            if q is me or self.phase != "play" or self.can_see(me, q):
                lag = 1 if (not q["left"] and now - q["seen"] > LAG_AFTER and not q.get("host")) else 0
                others.append([q["id"], round(q["x"]), round(q["y"]), q["f"], 1 if q["alive"] else 0, lag])
        bodies = []
        if self.phase == "play":
            for b in self.bodies:
                if not me["alive"] or (Wd.dist(me["x"], me["y"], b["x"], b["y"]) <= self.vision(me) + 40
                                       and Wd.line_of_sight(me["x"], me["y"], b["x"], b["y"], self.locked_set())):
                    bodies.append([b["id"], round(b["x"]), round(b["y"])])
        done, total = self.task_progress()
        snap = {
            "ph": self.phase, "left": round(max(0.0, self.phase_end - now), 1) if self.phase in ("meeting", "eject") else 0,
            "p": others, "b": bodies, "tb": [done, total], "lo": 1 if self.lights_off else 0,
            "lk": sorted(self.locked), "me": [round(me["x"]), round(me["y"]), me["tp"], 1 if me["alive"] else 0],
            "dn": sorted(me["done"]), "bt": me["buttons"],
        }
        if self.phase == "meeting" and self.meeting is not None:
            snap["mv"] = round(max(0.0, self.meeting["vote_at"] - now), 1)
            snap["vd"] = sorted(self.meeting["votes"])
        if me["role"] in (DUCK, SHERIFF) and me["alive"]:
            snap["kc"] = round(max(0.0, me["kill_at"] - now), 1)
        if me["role"] == DUCK and me["alive"]:
            snap["sc"] = round(max(0.0, self.sabo_at - now), 1)
        if me["role"] == DETECTIVE:
            snap["ck"] = me["checks"]
        if me["fix_t"] is not None:
            snap["fx"] = 1
        return snap

    def start_info_for(self, pid: str) -> dict:
        """开局时发给每个人的:所有人的名字颜色、自己的身份和任务;坏鸭还知道同伴。"""
        me = self.players[pid]
        info = {"gid": self.gid, "s": self.s, "role": me["role"], "tasks": list(me["tasks"]),
                "roster": [{"id": q["id"], "nick": q["nick"], "color": q["color"]} for q in self.players.values()]}
        if me["role"] == DUCK:
            info["mates"] = [q["id"] for q in self.players.values() if q["role"] == DUCK and q["id"] != pid]
        return info
