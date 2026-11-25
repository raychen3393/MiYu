"""
密语 · 宠物照料和群宠物(纯数据,方便保存和测试)

- 照料:饱腹度和心情会随时间慢慢下降;喂食、玩耍、摸摸、聊天都能让它开心。
- 形态:幼年期 → 成长期(Lv.10)→ 进化期(Lv.20)→ 传说期(Lv.30)。
- 表情:平时的脸可以换(默认 / 眯眼笑 / 星星眼 / 酷酷 / 困困)。
- 群宠物:每个暗号群一只,大家一起养。没有服务器,所以用"每人一份计数、合并时取最大"的办法同步:
  谁也改不了别人的贡献,断网后再合并也不会算重;名字和样子以最后一次修改为准。
"""
from __future__ import annotations

import time

# 食物:(id, 名字, 表情, 饱腹 +, 心情 +, 解锁等级)
FOODS = [
    ("fish", "小鱼干", "🐟", 25, 5, 1),
    ("milk", "牛奶", "🥛", 15, 8, 1),
    ("onigiri", "饭团", "🍙", 30, 4, 3),
    ("cake", "草莓蛋糕", "🍰", 20, 14, 6),
    ("candy", "糖果", "🍬", 8, 16, 9),
]
FOOD_BY_ID = {f[0]: f for f in FOODS}
# 玩具:(id, 名字, 表情, 心情 +, 解锁等级)
TOYS = [
    ("yarn", "毛线球", "🧶", 20, 1),
    ("ball", "小皮球", "⚽", 18, 1),
    ("feather", "逗猫棒", "🪶", 22, 5),
    ("bubble", "吹泡泡", "🫧", 26, 12),
]
TOY_BY_ID = {t[0]: t for t in TOYS}
# 平时的表情:(id, 名字, 解锁等级)
EXPRESSIONS = [("normal", "默认", 1), ("smile", "眯眼笑", 2), ("sleepy", "困困", 4), ("star", "星星眼", 8),
               ("cool", "酷酷", 13)]
EXPR_BY_ID = {e[0]: e for e in EXPRESSIONS}
# 形态:(从几级开始, 名字, 说明)
FORMS = [
    (1, "幼年期", "小小一只,慢慢长大"),
    (10, "成长期", "长到最大的个头"),
    (20, "进化期", "长出小翅膀,额头多一颗宝石"),
    (30, "传说期", "身后一圈金色光环,星星绕着转"),
    (40, "神话期", "翅膀变成会发光的大羽翼,头顶浮着一圈星冠"),
]

FEED_XP, PLAY_XP = 8, 6                  # 喂一次 / 玩一次的经验
FEED_XP_DAILY, PLAY_XP_DAILY = 10, 10    # 每天前 10 次有经验(之后照样能喂,只是不涨经验)
FOOD_DECAY, JOY_DECAY = 4.0, 3.0         # 每小时下降多少
HUNGRY, BORED = 25, 25                   # 低于这个数会撒娇提醒


def form_of(level: int) -> tuple[int, str, str]:
    """返回 (第几个形态, 名字, 说明)。"""
    idx = 0
    for i, (need, _n, _d) in enumerate(FORMS):
        if level >= need:
            idx = i
    return idx, FORMS[idx][1], FORMS[idx][2]


def next_form(level: int) -> tuple[int, str] | None:
    for need, name, _d in FORMS:
        if level < need:
            return need, name
    return None


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ====================================================================== 群宠物
GP_SPECIES = ("cat", "bunny", "bear", "capy", "shiba", "fox", "penguin")
GP_DAILY_XP = 300                        # 每人每天最多给群宠物攒多少经验(防刷)
GP_DAILY_FEEDS = 5                       # 每人每天最多喂几次
GP_MSG_XP, GP_FEED_XP = 4, 20
GP_MAX_MEMBERS = 200
GP_MAX_COUNT = 10_000_000                # 单人计数的上限(收到离谱的数直接截断)
DEFAULT_GP_NAME = "群宝"


def _int(v, hi: int = GP_MAX_COUNT) -> int:
    return max(0, min(hi, v)) if type(v) is int else 0


def _lww(v, ok) -> tuple | None:
    """"最后修改者胜"的寄存器:[值, 时间, 修改人]。"""
    if not isinstance(v, (list, tuple)) or len(v) < 2:
        return None
    val, ts = v[0], v[1]
    by = v[2] if len(v) > 2 and isinstance(v[2], str) else ""
    if not ok(val) or not isinstance(ts, (int, float)) or ts < 0:
        return None
    return val, float(ts), by[:20]


class GroupPet:
    """一个暗号群的群宠物。xp / feeds 是每个人自己的计数,合并时每人取最大值。"""

    def __init__(self, d: dict | None = None) -> None:
        d = d if isinstance(d, dict) else {}
        self.xp: dict[str, int] = {}
        self.feeds: dict[str, int] = {}
        self.nicks: dict[str, str] = {}
        self.name: tuple = (DEFAULT_GP_NAME, 0.0, "")
        self.species: tuple = ("bunny", 0.0, "")
        self.wear: tuple = ((), 0.0, "")
        self.act: dict = {}                  # 最近一次互动(喂食),用来在别人屏幕上播动画
        self.day = {"date": "", "xp": 0, "feeds": 0}     # 我自己今天贡献了多少(只存本机)
        self.merge(d)
        day = d.get("day") if isinstance(d.get("day"), dict) else {}
        self.day = {"date": str(day.get("date", "")), "xp": _int(day.get("xp")), "feeds": _int(day.get("feeds"))}
        self.dirty = False

    # ---- 读
    @property
    def total(self) -> int:
        return sum(self.xp.values())

    @property
    def level(self) -> int:
        from .fun import PET_MAX_LEVEL, xp_for_level
        lv, t = 1, self.total
        while lv < PET_MAX_LEVEL and t >= xp_for_level(lv + 1):
            lv += 1
        return lv

    def top(self, n: int = 10) -> list[tuple[str, int, int]]:
        """贡献榜:(昵称, 经验, 喂食次数),经验多的在前。"""
        rows = [(self.nicks.get(pid, "?"), x, self.feeds.get(pid, 0)) for pid, x in self.xp.items() if x > 0]
        return sorted(rows, key=lambda r: (-r[1], -r[2], r[0]))[:n]

    # ---- 合并(收到别人发来的状态)
    def merge(self, d) -> bool:
        if not isinstance(d, dict):
            return False
        changed = False
        for field, store in (("x", self.xp), ("f", self.feeds)):
            src = d.get(field)
            if not isinstance(src, dict):
                continue
            for pid, v in list(src.items())[:GP_MAX_MEMBERS * 2]:
                if not isinstance(pid, str) or len(pid) > 64:
                    continue
                v = _int(v)
                if v > store.get(pid, 0):
                    if pid not in store and len(store) >= GP_MAX_MEMBERS:
                        continue
                    store[pid] = v
                    changed = True
        nicks = d.get("k")
        if isinstance(nicks, dict):
            for pid, nick in list(nicks.items())[:GP_MAX_MEMBERS * 2]:
                if isinstance(pid, str) and isinstance(nick, str) and pid in self.xp and nick:
                    self.nicks[pid] = " ".join(nick.split())[:20]
        for field, attr, ok in (
            ("n", "name", lambda v: isinstance(v, str) and 0 < len(v.strip()) <= 8),
            ("s", "species", lambda v: v in GP_SPECIES),
            ("w", "wear", lambda v: isinstance(v, (list, tuple)) and len(v) <= 4 and all(isinstance(x, str) for x in v)),
        ):
            new = _lww(d.get(field), ok)
            if new is None:
                continue
            if field == "n":
                new = (" ".join(new[0].split())[:8], new[1], new[2])
            if field == "w":
                new = (tuple(new[0]), new[1], new[2])
            cur = getattr(self, attr)
            if (new[1], str(new[0])) > (cur[1], str(cur[0])):
                setattr(self, attr, new)
                changed = True
        act = d.get("a")
        if (isinstance(act, dict) and isinstance(act.get("t"), (int, float))
                and act["t"] > self.act.get("t", 0) and isinstance(act.get("by"), str)):
            self.act = {"t": float(act["t"]), "by": act["by"][:20], "food": str(act.get("food", ""))[:12]}
        return changed

    # ---- 我的贡献
    def _roll(self, today: str | None = None) -> None:
        today = today or time.strftime("%Y-%m-%d")
        if self.day["date"] != today:
            self.day = {"date": today, "xp": 0, "feeds": 0}

    def contribute(self, me: str, nick: str, amount: int, today: str | None = None) -> int:
        """我在群里聊天:给群宠物攒经验(每天有上限)。返回实际加了多少。"""
        self._roll(today)
        amount = max(0, min(int(amount), GP_DAILY_XP - self.day["xp"]))
        if amount <= 0 or (me not in self.xp and len(self.xp) >= GP_MAX_MEMBERS):
            return 0
        self.day["xp"] += amount
        self.xp[me] = min(GP_MAX_COUNT, self.xp.get(me, 0) + amount)
        self.nicks[me] = nick[:20]
        self.dirty = True
        return amount

    def feed(self, me: str, nick: str, food: str, today: str | None = None) -> bool:
        self._roll(today)
        if self.day["feeds"] >= GP_DAILY_FEEDS:
            return False
        if me not in self.xp and len(self.xp) >= GP_MAX_MEMBERS:
            return False
        self.day["feeds"] += 1
        self.feeds[me] = self.feeds.get(me, 0) + 1
        self.xp[me] = min(GP_MAX_COUNT, self.xp.get(me, 0) + GP_FEED_XP)      # 喂食的经验不占聊天的额度
        self.nicks[me] = nick[:20]
        self.act = {"t": time.time(), "by": nick[:20], "food": food}
        self.dirty = True
        return True

    def feeds_left(self, today: str | None = None) -> int:
        self._roll(today)
        return GP_DAILY_FEEDS - self.day["feeds"]

    def rename(self, name: str, by: str) -> bool:
        name = " ".join((name or "").split())[:8]
        if not name:
            return False
        self.name = (name, max(time.time(), self.name[1] + 0.001), by[:20])
        self.dirty = True
        return True

    def set_species(self, sp: str, by: str) -> bool:
        if sp not in GP_SPECIES:
            return False
        self.species = (sp, max(time.time(), self.species[1] + 0.001), by[:20])
        self.dirty = True
        return True

    # ---- 发出去 / 存起来
    def to_wire(self) -> dict:
        return {"x": dict(self.xp), "f": dict(self.feeds), "k": {p: self.nicks[p] for p in self.xp if p in self.nicks},
                "n": list(self.name), "s": list(self.species), "w": [list(self.wear[0]), self.wear[1], self.wear[2]],
                "a": dict(self.act)}

    def to_dict(self) -> dict:
        return {**self.to_wire(), "day": dict(self.day)}
