"""谁是卧底 · 每个玩家自己这边的状态(纯逻辑)。房主每次有变化就把公开的局面发过来(只含自己该知道的)。"""
from __future__ import annotations


class SpyClient:
    def __init__(self, info: dict, me: str, host: str, now: float = 0.0) -> None:
        self.me, self.host = me, host
        self.gid = info.get("gid", "")
        self.s = info.get("s") or {}
        self.word = str(info.get("word") or "")[:12]
        self.blank = bool(info.get("blank"))
        self.roster: list[dict] = []
        for r in info.get("roster") or []:
            if isinstance(r, dict) and isinstance(r.get("id"), str):
                self.roster.append({"id": r["id"], "nick": str(r.get("nick", "?"))[:20]})
        self.nicks = {r["id"]: r["nick"] for r in self.roster}
        self.phase = "desc"
        self.round = 1
        self.left = 0.0
        self.recv_at = now
        self.turn: str | None = None
        self.order: list[str] = []
        self.alive: set[str] = {r["id"] for r in self.roster}
        self.said: list[dict] = []
        self.chat: list[dict] = []
        self.voted: set[str] = set()
        self.ready: set[str] = set()
        self.out: list[dict] = []
        self.gone: set[str] = set()
        self.last: dict | None = None
        self.guesser: str | None = None
        self.over: dict | None = None
        self.version = -1
        self.last_state = now
        self.states = 0
        self.my_vote: str | None = None

    def nick(self, pid) -> str:
        return self.nicks.get(pid, "?") if pid else "?"

    def apply_state(self, st: dict, now: float) -> bool:
        if not isinstance(st, dict):
            return False
        v = st.get("v")
        self.last_state = now
        if type(v) is not int or v < self.version:
            return False
        self.states += 1
        self.version = v
        ph = st.get("ph")
        if ph in ("desc", "talk", "vote", "reveal", "guess", "over"):
            if ph != self.phase and ph == "vote":
                self.my_vote = None
            self.phase = ph
        self.round = int(st.get("rd") or 1)
        self.left = float(st.get("left") or 0)
        self.recv_at = now
        self.turn = st.get("turn") if isinstance(st.get("turn"), str) else None
        self.order = [p for p in st.get("order") or [] if isinstance(p, str)]
        self.alive = {p for p in st.get("alive") or [] if isinstance(p, str)}
        self.said = [s for s in st.get("said") or [] if isinstance(s, dict) and isinstance(s.get("by"), str)]
        self.chat = [c for c in st.get("chat") or [] if isinstance(c, dict) and isinstance(c.get("by"), str)]
        self.voted = set(st.get("voted") or [])
        self.ready = set(st.get("ready") or [])
        self.out = [o for o in st.get("out") or [] if isinstance(o, dict)]
        self.gone = set(st.get("gone") or [])
        self.last = st.get("last") if isinstance(st.get("last"), dict) else None
        self.guesser = st.get("guesser") if isinstance(st.get("guesser"), str) else None
        if isinstance(st.get("over"), dict):
            self.over = st["over"]
        return True

    def phase_left(self, now: float) -> float:
        return max(0.0, self.left - (now - self.recv_at))
