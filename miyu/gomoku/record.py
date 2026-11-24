"""
对局记录:防伪造、防篡改,任何一台电脑都能独立验证。

一盘棋 = 开局信息(双方都签名)+ 一串动作。每个动作由做这个动作的人用自己的身份私钥(Ed25519)签名,
签名里包含"上一个动作的哈希",所以动作串成一条链,不能删改、插队、调换顺序。玩家的 id 就是他的公钥。

动作(k):
  m  落子(x, y)              由落子的人签名;必须轮到他、位置是空的
  u  悔棋(n = 退回几手)      由"同意悔棋"的一方签名(他吃亏,所以要他点头)
  r  认输                    由认输的人签名
  t  超时                    由超时的人自己的软件签名(时间到了它自己认输)
  a  判对方掉线负            由等待的一方签名;还要等掉线的一方回来后由他的软件确认(k)才算数
  k  确认掉线负              由掉线的一方签名
  v  双方同意重新开始(作废)  由同意的一方签名

结果:连成五子由棋谱本身证明(每一步都有落子人的签名);认输 / 超时由输的人签名;掉线负要输的人确认。
所以谁也不能凭空给自己记一场胜利。
"""
from __future__ import annotations

import hashlib
import re

from ..crypto import canonical, verify
from .rules import COLOR, N, Board

VERSION = 1
LIMITS = (0, 30, 60, 120)                 # 每步限时(秒),0 = 不限时
MAX_ACTS = 700
NICK_MAX = 20
KINDS = {"m", "u", "r", "t", "a", "k", "v"}
TERMINAL = {"five", "draw", "resign", "timeout", "abandon", "void"}
FINAL_WITH_RESULT = {"five", "draw", "resign", "timeout", "abandon"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


def start_payload(rec: dict) -> bytes:
    return canonical(["gm1-start", rec["id"], rec["b"], rec["w"], rec["lim"], rec["t0"], rec["nb"], rec["nw"]])


def start_hash(rec: dict) -> str:
    return _sha(start_payload(rec))


def act_payload(mid: str, i: int, prev: str, a: dict) -> bytes:
    return canonical(["gm1-act", mid, i, prev, a["k"], a["p"], a["ts"], a.get("x", -1), a.get("y", -1), a.get("n", 0)])


def next_hash(prev: str, a: dict) -> str:
    return _sha(f"{prev}|{a['s']}".encode())


def chain_hash(rec: dict, upto: int | None = None) -> str:
    """前 upto 个动作之后的链哈希(不验证签名)。"""
    h = start_hash(rec)
    for a in rec["acts"][:len(rec["acts"]) if upto is None else upto]:
        h = next_hash(h, a)
    return h


def new_record(mid: str, black: str, white: str, lim: int, t0: int, nb: str, nw: str) -> dict:
    return {"v": VERSION, "id": mid, "b": black, "w": white, "lim": lim, "t0": int(t0),
            "nb": str(nb)[:NICK_MAX], "nw": str(nw)[:NICK_MAX], "sb": "", "sw": "", "acts": []}


def sign_start(rec: dict, identity, color: str) -> str:
    sig = identity.sign(start_payload(rec)).hex()
    rec["s" + color] = sig
    return sig


def make_action(rec: dict, identity, kind: str, color: str, ts: int, **kw) -> dict:
    """在记录末尾签一个新动作(不检查规则,调用方先用 evaluate 判断能不能做)。"""
    a = {"k": kind, "p": color, "ts": int(ts)}
    for key in ("x", "y", "n"):
        if key in kw:
            a[key] = int(kw[key])
    i = len(rec["acts"])
    a["s"] = identity.sign(act_payload(rec["id"], i, chain_hash(rec), a)).hex()
    return a


# ---------------------------------------------------------------- 检查格式
def clean_record(obj) -> dict | None:
    """别人发来的记录:先检查格式(类型、长度),格式不对整份不要。签名和规则在 evaluate 里查。"""
    if not isinstance(obj, dict) or obj.get("v") != VERSION:
        return None
    try:
        mid, b, w = obj["id"], obj["b"], obj["w"]
        if not (isinstance(mid, str) and _HEX32.match(mid) and isinstance(b, str) and _HEX64.match(b)
                and isinstance(w, str) and _HEX64.match(w) and b != w):
            return None
        lim, t0 = obj["lim"], obj["t0"]
        if lim not in LIMITS or type(t0) is not int or not (0 < t0 < 10 ** 14):
            return None
        nb, nw = obj["nb"], obj["nw"]
        if not (isinstance(nb, str) and isinstance(nw, str) and len(nb) <= NICK_MAX and len(nw) <= NICK_MAX):
            return None
        sb, sw = obj.get("sb", ""), obj.get("sw", "")
        if not (isinstance(sb, str) and isinstance(sw, str) and len(sb) <= 128 and len(sw) <= 128):
            return None
        acts = obj.get("acts")
        if not isinstance(acts, list) or len(acts) > MAX_ACTS:
            return None
        clean = []
        for a in acts:
            ca = clean_action(a)
            if ca is None:
                return None
            clean.append(ca)
    except (KeyError, TypeError):
        return None
    return {"v": VERSION, "id": mid, "b": b, "w": w, "lim": lim, "t0": t0, "nb": nb, "nw": nw,
            "sb": sb, "sw": sw, "acts": clean}


def clean_action(a) -> dict | None:
    if not isinstance(a, dict):
        return None
    k, p, ts, s = a.get("k"), a.get("p"), a.get("ts"), a.get("s")
    if k not in KINDS or p not in ("b", "w") or type(ts) is not int or not (0 < ts < 10 ** 14):
        return None
    if not (isinstance(s, str) and len(s) == 128):
        return None
    out = {"k": k, "p": p, "ts": ts}
    for key in ("x", "y", "n"):
        if key in a:
            v = a[key]
            if type(v) is not int or not (0 <= v < 256):
                return None
            out[key] = v
    out["s"] = s
    return out


# ---------------------------------------------------------------- 验证 + 复盘
def _sig_ok(pub_hex: str, sig_hex: str, data: bytes) -> bool:
    try:
        return verify(bytes.fromhex(pub_hex), bytes.fromhex(sig_hex), data)
    except ValueError:
        return False


_eval_cache: dict = {}


def evaluate(rec: dict, need_start: bool = True) -> dict:
    """带缓存的 _evaluate:按整份记录的内容哈希缓存(内容改了一个字就是另一份,不会用错缓存)。"""
    key = (hashlib.sha256(canonical(rec)).digest(), need_start)
    hit = _eval_cache.get(key)
    if hit is not None:
        return dict(hit, moves=list(hit["moves"]))
    res = _evaluate(rec, need_start)
    if len(_eval_cache) > 4000:
        _eval_cache.clear()
    _eval_cache[key] = res
    return dict(res, moves=list(res["moves"]))


def _evaluate(rec: dict, need_start: bool = True) -> dict:
    """验证签名并按规则复盘。遇到第一个不合法的动作就停(只认它前面的部分)。
    返回 {ok, status, winner, line, moves, n_acts, end_i, end_ts, hash, claimant, undos}。
    status: playing / five / draw / resign / timeout / abandon_pending / abandon / void。"""
    res = {"ok": False, "status": "playing", "winner": None, "line": None, "moves": [], "n_acts": 0,
           "end_i": None, "end_ts": rec.get("t0", 0), "hash": "", "claimant": None, "undos": 0}
    if need_start:
        sp = start_payload(rec)
        if not (_sig_ok(rec["b"], rec.get("sb", ""), sp) and _sig_ok(rec["w"], rec.get("sw", ""), sp)):
            return res
    res["ok"] = True
    board = Board()
    who = {"b": rec["b"], "w": rec["w"]}
    h = start_hash(rec)
    res["hash"] = h
    status = "playing"
    for i, a in enumerate(rec["acts"]):
        if not _sig_ok(who[a["p"]], a["s"], act_payload(rec["id"], i, h, a)):
            break
        k, p = a["k"], a["p"]
        turn = "b" if board.turn == COLOR["b"] else "w"
        if status == "abandon_pending":
            if k != "k" or p == res["claimant"]:
                break
            status = "abandon"
            res["winner"] = res["claimant"]
        elif status != "playing":
            break
        elif k == "m":
            x, y = a.get("x", -1), a.get("y", -1)
            if p != turn or not board.can_place(x, y):
                break
            line = board.place(x, y)
            if line:
                status, res["winner"], res["line"] = "five", p, line
            elif board.full:
                status = "draw"
        elif k == "u":
            n = a.get("n", 0)
            if n not in (1, 2) or n > len(board.moves):
                break
            last = "b" if (len(board.moves) - 1) % 2 == 0 else "w"
            if (n == 1 and p == last) or (n == 2 and p != last):    # 必须是"吃亏"的一方签的
                break
            board.undo(n)
            res["undos"] += 1
        elif k == "r":
            status, res["winner"] = "resign", ("w" if p == "b" else "b")
        elif k == "t":
            if p != turn:                                   # 只有轮到自己时才会超时
                break
            status, res["winner"] = "timeout", ("w" if p == "b" else "b")
        elif k == "a":
            status, res["claimant"] = "abandon_pending", p
        elif k == "v":
            status = "void"
        else:
            break
        h = next_hash(h, a)
        res["hash"] = h
        res["n_acts"] = i + 1
        res["end_ts"] = max(res["end_ts"], a["ts"])
        if status in TERMINAL and res["end_i"] is None:
            res["end_i"] = i
    res["status"] = status
    res["moves"] = list(board.moves)
    return res


def merge_key(res: dict) -> tuple:
    """同一盘棋有两份不同的记录时(网络不好、同时操作),大家按同一个规则选同一份:
    已经结束的 > 没结束的;都结束了选结束得早的;都没结束选更长的;最后按哈希。"""
    if not res["ok"]:
        return (0, 0, 0, "")
    if res["end_i"] is not None:
        return (2, -res["end_i"], 0, res["hash"])
    return (1, res["n_acts"], 0, res["hash"])


def better(a: dict | None, b: dict | None) -> dict | None:
    """两份同一盘棋的记录里选"更好"的那份(顺序无关:better(a,b) 和 better(b,a) 一样)。"""
    if a is None:
        return b
    if b is None:
        return a
    ka, kb = merge_key(evaluate(a)), merge_key(evaluate(b))
    return a if ka >= kb else b


def color_of(rec: dict, pid: str) -> str | None:
    return "b" if rec["b"] == pid else "w" if rec["w"] == pid else None


def board_size() -> int:
    return N
