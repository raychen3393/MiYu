"""
谁是卧底 · 规则和房主裁判(纯逻辑,不依赖界面)。

开局  每个人拿到一个词。大多数人(平民)拿到同一个词,卧底拿到一个相近的词,白板(可选)什么都没拿到。
      没人知道自己是不是卧底 —— 只能从别人的描述里猜。
每一轮  1) 描述:按座位顺序,每人用一句话描述自己的词(不能直接说出这个词),有倒计时;
        2) 讨论:大家自由发言;
        3) 投票:投给最可疑的人(可以弃票),票最多的出局,平票没人出局;
        4) 揭晓:出局的人亮出身份。白板被投出去时有一次机会猜平民的词,猜中就单独获胜。
胜负  卧底全部出局 → 平民获胜;卧底人数 ≥ 其他活着的人,或者只剩 3 个人时卧底还在 → 卧底获胜。
房主的电脑当裁判,每个人只收到自己的词;房主的软件知道所有词(界面上不显示)。
"""
from __future__ import annotations

import random

from . import words as WB

CIV, SPY, BLANK = "civ", "spy", "blank"
ROLE_NAME = {CIV: "平民", SPY: "卧底", BLANK: "白板"}
MIN_PLAYERS, MAX_PLAYERS = 4, 10
DEFAULTS = {"spies": 0, "blank": True, "say": 40, "talk": 30, "vote": 30, "cat": "全部", "diff": 0}
LIMITS = {"spies": (0, 3), "say": (15, 90), "talk": (0, 120), "vote": (15, 90), "diff": (0, 3)}
REVEAL_SECS = 4.5
GUESS_SECS = 25.0
SAY_MAX = 30
CHAT_MAX = 80


def clean_settings(d) -> dict:
    out = dict(DEFAULTS)
    if isinstance(d, dict):
        for k, v in d.items():
            if k in LIMITS and type(v) is int:
                lo, hi = LIMITS[k]
                out[k] = max(lo, min(hi, v))
            elif k == "blank" and isinstance(v, bool):
                out[k] = v
            elif k == "cat" and (v == "全部" or v in WB.CATEGORIES):
                out[k] = v
    return out


def spy_count(n: int, wanted: int = 0) -> int:
    auto = 1 if n <= 6 else 2
    if wanted <= 0:
        return auto
    return max(1, min(wanted, (n - 1) // 3 if n >= 7 else 1, 3))


def norm(text: str) -> str:
    return "".join(str(text).split()).lower()


class Game:
    def __init__(self, roster: list[dict], settings: dict | None = None, seed: int | None = None, now: float = 0.0,
                 avoid: set | None = None) -> None:
        if not (MIN_PLAYERS <= len(roster) <= MAX_PLAYERS):
            raise ValueError("人数不对")
        self.rng = random.Random(seed)
        self.s = clean_settings(settings)
        self.gid = "%012x" % self.rng.getrandbits(48)
        self.civ_word, self.spy_word = WB.pick(self.s["cat"], self.s["diff"], self.rng, avoid)
        ids = [r["id"] for r in roster]
        n = len(ids)
        order = ids[:]
        self.rng.shuffle(order)
        ns = spy_count(n, self.s["spies"])
        self.roles = {pid: CIV for pid in ids}
        for pid in order[:ns]:
            self.roles[pid] = SPY
        if self.s["blank"] and n >= 5:
            self.roles[order[ns]] = BLANK
        self.seats = ids[:]                              # 座位顺序 = 进房间的顺序
        self.nick = {r["id"]: str(r.get("nick", "?"))[:20] for r in roster}
        self.alive = set(ids)
        self.left: set[str] = set()
        self.out: list[dict] = []                        # 出局顺序 [{id, role, round}]
        self.said: list[dict] = []                       # [{r, by, text}] text="" 表示超时没说
        self.chat: list[dict] = []
        self.votes: dict[str, str] = {}
        self.round = 0
        self.starter = self.rng.randrange(n)
        self.phase = ""
        self.phase_end = 0.0
        self.turn_list: list[str] = []
        self.turn_i = 0
        self.last: dict | None = None                    # 刚出局的人(揭晓用)
        self.guesser: str | None = None
        self.guess_text: str | None = None
        self.winner: str | None = None
        self.win_reason = ""
        self.version = 0
        self.new_round(now)

    # ---------------------------------------------------------------- 查询
    def word_for(self, pid: str) -> str:
        r = self.roles.get(pid)
        return self.civ_word if r == CIV else self.spy_word if r == SPY else ""

    def alive_count(self, role: str | None = None) -> int:
        return sum(1 for p in self.alive if role is None or self.roles[p] == role)

    def turn(self) -> str | None:
        if self.phase != "desc" or self.turn_i >= len(self.turn_list):
            return None
        return self.turn_list[self.turn_i]

    def bump(self) -> None:
        self.version += 1

    # ---------------------------------------------------------------- 阶段
    def new_round(self, now: float) -> None:
        self.round += 1
        self.votes = {}
        self.last = None
        n = len(self.seats)
        start = self.starter % n
        ring = self.seats[start:] + self.seats[:start]
        self.turn_list = [p for p in ring if p in self.alive]
        self.starter += 1
        self.turn_i = 0
        self.phase = "desc"
        self.phase_end = now + self.s["say"]
        self.bump()

    def _next_turn(self, now: float) -> None:
        self.turn_i += 1
        while self.turn_i < len(self.turn_list) and self.turn_list[self.turn_i] not in self.alive:
            self.turn_i += 1
        if self.turn_i >= len(self.turn_list):
            if self.s["talk"] > 0:
                self.phase = "talk"
                self.phase_end = now + self.s["talk"]
            else:
                self._start_vote(now)
        else:
            self.phase_end = now + self.s["say"]
        self.bump()

    def _start_vote(self, now: float) -> None:
        self.phase = "vote"
        self.phase_end = now + self.s["vote"]
        self.votes = {}
        self.bump()

    def _resolve_vote(self, now: float) -> None:
        tally: dict[str, int] = {}
        for t in self.votes.values():
            tally[t] = tally.get(t, 0) + 1
        out = None
        if tally:
            best = max(tally.values())
            top = [k for k, v in tally.items() if v == best]
            if len(top) == 1 and top[0] != "skip":
                out = top[0]
        self.last = {"id": out, "votes": dict(self.votes), "role": self.roles.get(out) if out else None}
        if out is not None:
            self.alive.discard(out)
            self.out.append({"id": out, "role": self.roles[out], "round": self.round})
        self.phase = "reveal"
        self.phase_end = now + REVEAL_SECS
        self.bump()

    def _after_reveal(self, now: float) -> None:
        last = self.last or {}
        if last.get("role") == BLANK and self.guess_text is None and self.guesser is None:
            self.guesser = last["id"]
            self.phase = "guess"
            self.phase_end = now + GUESS_SECS
            self.bump()
            return
        if self.check_win():
            return
        self.new_round(now)

    def check_win(self) -> str | None:
        if self.winner:
            return self.winner
        spies = self.alive_count(SPY)
        others = len(self.alive) - spies
        if spies == 0:
            return self.finish(CIV, "卧底全部出局了")
        if spies >= others or (len(self.alive) <= 3 and spies > 0):
            return self.finish(SPY, "卧底撑到了最后")
        return None

    def finish(self, team: str, reason: str) -> str:
        self.winner = team
        self.win_reason = reason
        self.phase = "over"
        self.phase_end = 0.0
        self.bump()
        return team

    # ---------------------------------------------------------------- 操作
    def act(self, pid: str, a: str, data: dict, now: float) -> str | None:
        if pid not in self.roles or pid in self.left or self.winner:
            return "不在游戏中"
        data = data if isinstance(data, dict) else {}
        if a == "say":
            return self._say(pid, data.get("text"), now)
        if a == "chat":
            return self._chat(pid, data.get("text"))
        if a == "vote":
            return self._vote(pid, data.get("t"), now)
        if a == "guess":
            return self._guess(pid, data.get("text"), now)
        if a == "skip_talk":
            return self._skip_talk(pid, now)
        return "不认识的操作"

    def _say(self, pid: str, text, now: float) -> str | None:
        if self.turn() != pid:
            return "还没轮到你"
        if not isinstance(text, str) or not text.strip():
            return "说点什么吧"
        text = text.strip()[:SAY_MAX]
        word = self.word_for(pid)
        if word and norm(word) in norm(text):
            return "不能直接说出你的词"
        self.said.append({"r": self.round, "by": pid, "text": text})
        self._next_turn(now)
        return None

    def _chat(self, pid: str, text) -> str | None:
        if not isinstance(text, str) or not text.strip():
            return "空消息"
        dead = pid not in self.alive
        if not dead and self.phase not in ("talk", "vote", "reveal"):
            return "现在是描述环节,轮到你时再说"
        text = text.strip()[:CHAT_MAX]
        word = self.word_for(pid)
        if not dead and word and norm(word) in norm(text):
            return "不能直接说出你的词"
        self.chat.append({"by": pid, "text": text, "dead": dead, "r": self.round})
        self.chat = self.chat[-120:]
        self.bump()
        return None

    def _skip_talk(self, pid: str, now: float) -> str | None:
        """讨论阶段:所有活着的人都点了「讨论完了」就直接开始投票。"""
        if self.phase != "talk" or pid not in self.alive:
            return "现在不是讨论环节"
        self.votes[pid] = "__ready__"
        if all(self.votes.get(p) == "__ready__" for p in self.alive):
            self._start_vote(now)
        else:
            self.bump()
        return None

    def _vote(self, pid: str, t, now: float) -> str | None:
        if self.phase != "vote" or pid not in self.alive:
            return "现在不能投票"
        if pid in self.votes:
            return "已经投过了"
        if t != "skip" and (t not in self.alive or t == pid):
            return "不能投给这个人"
        self.votes[pid] = t
        self.bump()
        if all(p in self.votes for p in self.alive):
            self._resolve_vote(now)
        return None

    def _guess(self, pid: str, text, now: float) -> str | None:
        if self.phase != "guess" or pid != self.guesser:
            return "现在不能猜"
        if not isinstance(text, str) or not text.strip():
            return "写一个词"
        self.guess_text = text.strip()[:12]
        if norm(self.guess_text) == norm(self.civ_word):
            self.finish(BLANK, f"白板猜中了平民的词「{self.civ_word}」")
            return None
        self.guesser = None
        if not self.check_win():
            self.new_round(now)
        return None

    # ---------------------------------------------------------------- 时间流逝
    def tick(self, now: float) -> None:
        if self.winner or now < self.phase_end:
            return
        if self.phase == "desc":
            p = self.turn()
            if p is not None:
                self.said.append({"r": self.round, "by": p, "text": ""})
            self._next_turn(now)
        elif self.phase == "talk":
            self._start_vote(now)
        elif self.phase == "vote":
            self._resolve_vote(now)
        elif self.phase == "reveal":
            self._after_reveal(now)
        elif self.phase == "guess":
            self.guess_text = ""
            self.guesser = None
            if not self.check_win():
                self.new_round(now)

    def leave(self, pid: str, now: float) -> None:
        if pid not in self.roles or pid in self.left:
            return
        self.left.add(pid)
        was = pid in self.alive
        self.alive.discard(pid)
        if was:
            self.out.append({"id": pid, "role": self.roles[pid], "round": self.round, "left": True})
        self.votes.pop(pid, None)
        if self.phase == "desc" and self.turn() == pid:
            self._next_turn(now)
        elif self.phase == "vote" and self.alive and all(p in self.votes for p in self.alive):
            self._resolve_vote(now)
        elif self.phase == "guess" and self.guesser == pid:
            self.guesser = None
            self.guess_text = ""
            if not self.check_win():
                self.new_round(now)
            return
        if was and self.phase not in ("reveal", "guess"):
            self.check_win()
        self.bump()

    # ---------------------------------------------------------------- 发给每个人的画面
    def start_info_for(self, pid: str) -> dict:
        return {"gid": self.gid, "s": self.s, "word": self.word_for(pid), "blank": self.roles[pid] == BLANK,
                "roster": [{"id": p, "nick": self.nick[p]} for p in self.seats]}

    def state_for(self, pid: str, now: float) -> dict:
        dead = pid not in self.alive
        st = {
            "v": self.version, "ph": self.phase, "rd": self.round,
            "left": round(max(0.0, self.phase_end - now), 1) if self.phase_end else 0,
            "turn": self.turn(), "order": list(self.turn_list), "alive": sorted(self.alive),
            "said": self.said[-200:],
            "chat": [c for c in self.chat if not c["dead"] or dead][-60:],
            "voted": sorted(p for p, v in self.votes.items() if v != "__ready__") if self.phase == "vote" else [],
            "ready": sorted(p for p, v in self.votes.items() if v == "__ready__") if self.phase == "talk" else [],
            "out": [{"id": o["id"], "role": o["role"], "round": o["round"]} for o in self.out],
            "gone": sorted(self.left),
        }
        if self.phase in ("reveal", "guess") and self.last is not None:
            st["last"] = self.last
        if self.phase == "guess":
            st["guesser"] = self.guesser
        if self.phase == "over":
            st["over"] = {"win": self.winner, "why": self.win_reason, "roles": dict(self.roles),
                          "civ": self.civ_word, "spy": self.spy_word, "guess": self.guess_text}
        return st
