"""
积分和排行榜。全部从对局记录算出来,规则固定,所以每台电脑拿到同样的记录就算出同样的榜。

计分:胜 3 分、平 1 分、负 0 分。一盘棋要同时满足下面几条才计分(防刷分):
  · 记录完整、双方签名都对,结果能被验证(连五看棋谱;认输 / 超时有输家签名;掉线负有输家确认)
  · 认输 / 超时 / 掉线结束的,至少下满 10 手(连五和下满平局本身就够长)
  · 同一对玩家 24 小时内最多 5 局计分(按对局结束时间先后,超出的照样记在战绩里,只是不计分)
  · 结束时间不能比现在晚 10 分钟以上(时钟明显不对的,等时间到了再算)
排名:总积分高的在前;积分相同比胜场;再相同比胜率。三项都一样的并列同一名次。
今日榜:本机时间今天 0 点起;本周榜:本机时间本周一 0 点起。总榜永久保留。
"""
from __future__ import annotations

import datetime
import time
from collections import defaultdict, deque

from .record import FINAL_WITH_RESULT, evaluate

POINTS = {"win": 3, "draw": 1, "loss": 0}
MIN_MOVES = 10
PAIR_CAP = 5
PAIR_WINDOW_MS = 24 * 3600 * 1000
FUTURE_SLACK_MS = 10 * 60 * 1000
STATUS_TEXT = {"five": "连成五子", "draw": "下满平局", "resign": "认输", "timeout": "超时", "abandon": "掉线判负",
               "abandon_pending": "等待对方确认掉线", "void": "双方同意重新开始", "playing": "未下完"}


def now_ms() -> int:
    return int(time.time() * 1000)


def games_from(records: dict, now: int | None = None) -> list[dict]:
    """所有对局(按结束时间从早到晚),每盘带上:是否计分、不计分的原因、双方结果和得分。"""
    now = now_ms() if now is None else now
    out = []
    for rec in records.values():
        res = evaluate(rec)
        if not res["ok"]:
            continue
        g = {"id": rec["id"], "b": rec["b"], "w": rec["w"], "nb": rec["nb"], "nw": rec["nw"], "lim": rec["lim"],
             "t0": rec["t0"], "end_ts": res["end_ts"], "status": res["status"], "winner": res["winner"],
             "moves": len(res["moves"]), "line": res["line"], "rated": False, "why": "", "res": {}, "pts": {},
             "undos": res["undos"]}
        st = res["status"]
        if st in FINAL_WITH_RESULT:
            if st == "draw":
                g["res"] = {rec["b"]: "draw", rec["w"]: "draw"}
            else:
                win = rec[res["winner"]]
                lose = rec["w"] if win == rec["b"] else rec["b"]
                g["res"] = {win: "win", lose: "loss"}
            if res["end_ts"] > now + FUTURE_SLACK_MS:
                g["why"] = "对局时间异常(比现在还晚),暂不计分"
            elif st in ("resign", "timeout", "abandon") and g["moves"] < MIN_MOVES:
                g["why"] = f"不到 {MIN_MOVES} 手就结束了,不计分"
            else:
                g["rated"] = True                           # 先当作计分,下面再按"每天上限"筛一遍
        else:
            g["why"] = STATUS_TEXT.get(st, "") + (",不计分" if st in ("void", "abandon_pending") else "")
        out.append(g)
    out.sort(key=lambda g: (g["end_ts"], g["id"]))
    recent: dict = defaultdict(deque)
    for g in out:
        if not g["rated"]:
            continue
        pair = tuple(sorted((g["b"], g["w"])))
        q = recent[pair]
        while q and q[0] <= g["end_ts"] - PAIR_WINDOW_MS:
            q.popleft()
        if len(q) >= PAIR_CAP:
            g["rated"] = False
            g["why"] = f"同一对玩家 24 小时内超过 {PAIR_CAP} 局,这局不计分"
            continue
        q.append(g["end_ts"])
    for g in out:
        g["pts"] = {pid: (POINTS[r] if g["rated"] else 0) for pid, r in g["res"].items()}
    return out


def _empty_row(pid: str) -> dict:
    return {"id": pid, "nick": "", "pts": 0, "games": 0, "wins": 0, "losses": 0, "draws": 0, "rate": 0.0,
            "streak": 0, "best": 0, "last": 0, "rank": 0}


def standings(games: list[dict], lo: int | None = None, hi: int | None = None) -> list[dict]:
    """排行榜(只算计分的对局;lo / hi 是时间范围,毫秒)。已经排好序、标好名次。"""
    rows: dict[str, dict] = {}
    for g in games:                                         # games 已按结束时间排好
        if not g["rated"] or (lo is not None and g["end_ts"] < lo) or (hi is not None and g["end_ts"] >= hi):
            continue
        for color in ("b", "w"):
            pid = g[color]
            r = rows.setdefault(pid, _empty_row(pid))
            r["nick"] = g["n" + color] or r["nick"]
            result = g["res"][pid]
            r["games"] += 1
            r["pts"] += POINTS[result]
            r["last"] = g["end_ts"]
            if result == "win":
                r["wins"] += 1
                r["streak"] += 1
                r["best"] = max(r["best"], r["streak"])
            else:
                r["streak"] = 0
                r["losses" if result == "loss" else "draws"] += 1
    out = list(rows.values())
    for r in out:
        r["rate"] = r["wins"] / r["games"] if r["games"] else 0.0
    out.sort(key=lambda r: (-r["pts"], -r["wins"], -r["rate"], r["id"]))
    prev, rank = None, 0
    for i, r in enumerate(out):
        key = (r["pts"], r["wins"], round(r["rate"], 9))
        if key != prev:
            rank, prev = i + 1, key
        r["rank"] = rank
    return out


def player_stats(games: list[dict], pid: str) -> dict:
    """个人数据:总积分、场次、胜负平、胜率、当前连胜、最高连胜(都只算计分的对局)。"""
    for r in standings(games):
        if r["id"] == pid:
            return r
    return _empty_row(pid)


def history(games: list[dict], pid: str) -> list[dict]:
    """和我有关的每一盘(新的在前):对手、结果、得分、时间、手数、是否计分。"""
    out = []
    for g in reversed(games):
        if pid not in (g["b"], g["w"]):
            continue
        me = "b" if g["b"] == pid else "w"
        opp = "w" if me == "b" else "b"
        out.append({"id": g["id"], "opp": g[opp], "opp_nick": g["n" + opp], "color": me, "result": g["res"].get(pid),
                    "pts": g["pts"].get(pid, 0), "rated": g["rated"], "why": g["why"], "status": g["status"],
                    "end_ts": g["end_ts"], "t0": g["t0"], "moves": g["moves"]})
    return out


def period_bounds(kind: str, now: datetime.datetime | None = None) -> tuple[int | None, int | None]:
    """today:本机时间今天 0 点到明天 0 点;week:本周一 0 点到下周一 0 点;total:不限。"""
    if kind not in ("today", "week"):
        return None, None
    now = now or datetime.datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "week":
        start -= datetime.timedelta(days=now.weekday())
        end = start + datetime.timedelta(days=7)
    else:
        end = start + datetime.timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def rank_of(rows: list[dict], pid: str) -> tuple[int, dict | None, dict | None]:
    """(我的名次, 我的那一行, 比我高一名的那一行);不在榜上名次是 0。"""
    for i, r in enumerate(rows):
        if r["id"] == pid:
            above = next((x for x in reversed(rows[:i]) if x["rank"] < r["rank"]), None)
            return r["rank"], r, above
    return 0, None, None
