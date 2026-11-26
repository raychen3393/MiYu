"""
密语 · 宠物等级排行榜的数据(2.4)。纯数据,不依赖界面,方便测试。

每个人定期把自己的「宠物名片」用身份私钥签名后发到群里:
    {"v":1, "id":身份公钥, "n":昵称, "sp":种类, "pn":宠物名, "lv":等级, "xp":累计经验,
     "wk":本周编号, "w0":本周一开始时的经验, "wear":[装扮], "ts":毫秒时间}
别人收到后验签,存下最新的一张;有新人进群时把手上的名片转给他,所以不在线的人也会显示(标注多久前)。
签名保证名片是本人发的、内容没被别人改过,但经验是在本人电脑上涨的,改过的客户端可以虚报 ——
所以这里只做合理性检查:等级和经验要对得上、本周涨的不能是负数、和上一张比涨得离谱的标成「可疑」。
"""
from __future__ import annotations

import time

from . import crypto as C
from .fun import ACC_BY_ID, PET_MAX_LEVEL, SPECIES, xp_for_level
from .petcare import form_of

MAX_CARDS = 400
FUTURE_MS = 10 * 60 * 1000
MAX_XP_PER_DAY = 120_000          # 比一整天不停打字还多,超过就算可疑
SPECIES_ICON = {
    "cat": "🐱", "bunny": "🐰", "bear": "🐻",
    "capy": "🍊", "shiba": "🐕", "fox": "🦊", "penguin": "🐧",
}


def week_key(t: float | None = None) -> str:
    """本机时间的「第几周」(周一 0 点开始)。"""
    lt = time.localtime(time.time() if t is None else t)
    y, w, _ = __import__("datetime").date(lt.tm_year, lt.tm_mon, lt.tm_mday).isocalendar()
    return f"{y}-W{w:02d}"


def level_of(xp: int) -> int:
    lv = 1
    while lv < PET_MAX_LEVEL and xp >= xp_for_level(lv + 1):
        lv += 1
    return lv


def make_card(pid: str, nick: str, species: str, pet_name: str, xp: int, wk: str, w0: int, wear: list,
              ts_ms: int | None = None, snack_best: int = 0, cloud_best: int = 0, merge_best: int = 0,
              td_best: int = 0, pvz_best: int = 0) -> dict:
    xp = max(0, int(xp))
    card = {"v": 1, "id": pid, "n": str(nick)[:24], "sp": species if species in SPECIES else "cat",
            "pn": str(pet_name)[:8], "lv": level_of(xp), "xp": xp, "wk": wk, "w0": max(0, min(int(w0), xp)),
            "wear": [w for w in wear if w in ACC_BY_ID][:8], "ts": int(time.time() * 1000) if ts_ms is None else ts_ms}
    if snack_best > 0:
        card["sb"] = min(100_000, int(snack_best))
    if cloud_best > 0:
        card["cb"] = min(100_000, int(cloud_best))
    if merge_best > 0:
        card["mb"] = min(500_000, int(merge_best))
    if td_best > 0:
        card["tb"] = min(1_000_000, int(td_best))
    if pvz_best > 0:
        card["pb"] = min(1_000_000, int(pvz_best))
    return card


def _body(card: dict) -> bytes:
    return C.canonical({k: v for k, v in card.items() if k != "sig"})


def sign_card(card: dict, identity) -> dict:
    out = dict(card)
    out["sig"] = C.b64e(identity.sign(_body(card)))
    return out


def clean_card(raw, now_ms: int | None = None) -> dict | None:
    """检查格式、签名和数字是否对得上。不合格返回 None。"""
    if not isinstance(raw, dict) or raw.get("v") != 1:
        return None
    try:
        pid = raw["id"]
        pub = bytes.fromhex(pid)
        if len(pub) != 32 or pid != pub.hex():
            return None
        sig = C.b64d(raw["sig"])
        xp, lv, w0, ts = raw["xp"], raw["lv"], raw["w0"], raw["ts"]
        if not all(type(v) is int for v in (xp, lv, w0, ts)):
            return None
        n, pn, sp, wk, wear = raw["n"], raw["pn"], raw["sp"], raw["wk"], raw["wear"]
        if not (isinstance(n, str) and isinstance(pn, str) and isinstance(wk, str) and isinstance(wear, list)):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    if len(n) > 24 or len(pn) > 8 or len(wk) > 10 or len(wear) > 8 or sp not in SPECIES:
        return None
    if not all(isinstance(w, str) and w in ACC_BY_ID for w in wear):
        return None
    if xp < 0 or not (0 <= w0 <= xp) or lv != level_of(xp):
        return None
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if ts > now_ms + FUTURE_MS or ts <= 0:
        return None
    card = {"v": 1, "id": pid, "n": n, "sp": sp, "pn": pn, "lv": lv, "xp": xp, "wk": wk, "w0": w0,
            "wear": list(wear), "ts": ts}
    for gk, cap in (("sb", 100_000), ("cb", 100_000), ("mb", 500_000), ("tb", 1_000_000), ("pb", 1_000_000)):
        if gk in raw:
            gv = raw[gk]
            if type(gv) is not int or not (0 <= gv <= cap):
                return None
            card[gk] = gv
    if not C.verify(pub, sig, _body(card)):
        return None
    card["sig"] = raw["sig"]
    return card


def suspicious(old: dict | None, new: dict) -> bool:
    """和上一张名片比,经验涨得比"一整天不停打字"还快,就标成可疑。"""
    if old is None or new["ts"] <= old["ts"]:
        return False
    days = max(1.0, (new["ts"] - old["ts"]) / 86_400_000)
    return new["xp"] - old["xp"] > MAX_XP_PER_DAY * days


def accept(cards: dict[str, dict], flags: dict[str, bool], raw, now_ms: int | None = None) -> dict | None:
    """收下一张名片(比手上的新才换)。返回收下的名片,没收下返回 None。"""
    card = clean_card(raw, now_ms)
    if card is None:
        return None
    old = cards.get(card["id"])
    if old is not None and card["ts"] <= old["ts"]:
        return None
    if suspicious(old, card):
        flags[card["id"]] = True
    elif old is not None and card["xp"] >= old["xp"]:
        flags.pop(card["id"], None)
    cards[card["id"]] = card
    if len(cards) > MAX_CARDS:
        for pid in sorted(cards, key=lambda k: cards[k]["ts"])[:len(cards) - MAX_CARDS]:
            cards.pop(pid, None)
            flags.pop(pid, None)
    return card


def week_gain(card: dict, wk: str | None = None) -> int:
    wk = week_key() if wk is None else wk
    return card["xp"] - card["w0"] if card["wk"] == wk else 0


def standings(cards: dict[str, dict], members, kind: str = "level", wk: str | None = None,
              flags: dict | None = None) -> list[dict]:
    """排行榜。kind = level 等级榜(等级 → 经验) / week 本周成长榜(本周涨的经验 → 等级)。
    同样的数字并列同一名。members = 这个群的成员 id(None 表示所有人)。"""
    wk = week_key() if wk is None else wk
    flags = flags or {}
    rows = []
    for pid, c in cards.items():
        if members is not None and pid not in members:
            continue
        gain = week_gain(c, wk)
        sb, cb, mb = int(c.get("sb", 0)), int(c.get("cb", 0)), int(c.get("mb", 0))
        tb, pb = int(c.get("tb", 0)), int(c.get("pb", 0))
        if kind == "week" and gain <= 0:
            continue
        if kind == "snack" and sb <= 0:
            continue
        if kind == "cloud" and cb <= 0:
            continue
        if kind == "merge" and mb <= 0:
            continue
        if kind == "td" and tb <= 0:
            continue
        if kind == "pvz" and pb <= 0:
            continue
        idx, form, _d = form_of(c["lv"])
        rows.append({"id": pid, "nick": c["n"], "pet": c["pn"], "species": c["sp"], "lv": c["lv"], "xp": c["xp"],
                     "gain": gain, "sb": sb, "cb": cb, "mb": mb, "tb": tb, "pb": pb,
                     "form": form, "wear": c["wear"], "ts": c["ts"], "sus": bool(flags.get(pid))})
    if kind == "week":
        key = lambda r: (-r["gain"], -r["lv"], -r["xp"], r["id"])         # noqa: E731
        score = lambda r: (r["gain"],)                                     # noqa: E731
    elif kind == "snack":
        key = lambda r: (-r["sb"], -r["lv"], r["id"])                      # noqa: E731
        score = lambda r: (r["sb"],)                                       # noqa: E731
    elif kind == "cloud":
        key = lambda r: (-r["cb"], -r["lv"], r["id"])                      # noqa: E731
        score = lambda r: (r["cb"],)                                       # noqa: E731
    elif kind == "merge":
        key = lambda r: (-r["mb"], -r["lv"], r["id"])                      # noqa: E731
        score = lambda r: (r["mb"],)                                       # noqa: E731
    elif kind == "td":
        key = lambda r: (-r["tb"], -r["lv"], r["id"])                      # noqa: E731
        score = lambda r: (r["tb"],)                                       # noqa: E731
    elif kind == "pvz":
        key = lambda r: (-r["pb"], -r["lv"], r["id"])                      # noqa: E731
        score = lambda r: (r["pb"],)                                       # noqa: E731
    else:
        key = lambda r: (-r["lv"], -r["xp"], r["id"])                      # noqa: E731
        score = lambda r: (r["lv"], r["xp"])                               # noqa: E731
    rows.sort(key=key)
    prev, rank = None, 0
    for i, r in enumerate(rows):
        s = score(r)
        if s != prev:
            rank = i + 1
            prev = s
        r["rank"] = rank
    return rows


def rank_of(rows: list[dict], pid: str) -> tuple[int, dict | None, dict | None]:
    """(名次, 我的那一行, 排在我前面最近的不同名次的那一行)。"""
    for i, r in enumerate(rows):
        if r["id"] == pid:
            above = next((x for x in reversed(rows[:i]) if x["rank"] < r["rank"]), None)
            return r["rank"], r, above
    return 0, None, None


def ago(ts_ms: int, now: float | None = None) -> str:
    sec = max(0, (time.time() if now is None else now) - ts_ms / 1000)
    if sec < 600:
        return "刚刚"
    if sec < 3600:
        return f"{int(sec // 60)} 分钟前"
    if sec < 86400:
        return f"{int(sec // 3600)} 小时前"
    return f"{int(sec // 86400)} 天前"
