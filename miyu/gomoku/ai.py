"""
人机练习的电脑对手。按"棋形"打分:在一个空位落子后,四个方向上能形成五连、活四、冲四、活三……
进攻分(自己落在这里)和防守分(对手落在这里)加起来,挑分最高的点。
  简单:只看前几名里随机挑一个,偶尔看漏对方的活三
  普通:挑分最高的点
  困难:对前几名再往下想一步(对手最好的应对),选对自己最有利的
"""
from __future__ import annotations

import random

from .rules import BLACK, DIRS, EMPTY, N, Board, on_board, other

# 棋形 → 分数。x = 自己,_ = 空,o = 对手或棋盘边
PATTERNS = [
    ("xxxxx", 10_000_000),
    ("_xxxx_", 500_000),
    ("xxxx_", 60_000), ("_xxxx", 60_000), ("xxx_x", 60_000), ("x_xxx", 60_000), ("xx_xx", 60_000),
    ("__xxx_", 12_000), ("_xxx__", 12_000), ("_xx_x_", 11_000), ("_x_xx_", 11_000),
    ("xxx__", 1_500), ("__xxx", 1_500), ("xx_x_", 1_400), ("_x_xx", 1_400), ("x_xx_", 1_400), ("_xx_x", 1_400),
    ("xx__x", 1_200), ("x__xx", 1_200), ("x_x_x", 1_200),
    ("__xx__", 900), ("_x_x_", 600), ("_xx__", 500), ("__xx_", 500), ("_x__x_", 300),
    ("xx___", 120), ("___xx", 120), ("_x___", 40), ("___x_", 40),
]
LEVELS = {"easy": "简单", "normal": "普通", "hard": "困难"}


def _window(board: Board, x: int, y: int, dx: int, dy: int, me: int) -> str:
    """以 (x, y) 为中心、这个方向上前后各 4 格的样子(中心当作已经落了自己的子)。"""
    out = []
    for k in range(-4, 5):
        cx, cy = x + dx * k, y + dy * k
        if k == 0:
            out.append("x")
        elif not on_board(cx, cy):
            out.append("o")
        else:
            c = board.grid[cy][cx]
            out.append("_" if c == EMPTY else ("x" if c == me else "o"))
    return "".join(out)


def line_score(s: str) -> int:
    """一个方向上最好的棋形分(棋形必须经过中心那一格)。"""
    best = 0
    for pat, score in PATTERNS:
        if score <= best:
            break
        start = s.find(pat)
        while start != -1:
            if start <= 4 < start + len(pat):
                best = score
                break
            start = s.find(pat, start + 1)
    return best


def point_score(board: Board, x: int, y: int, me: int) -> int:
    """在 (x, y) 落 me 的子有多好。两个方向同时成型(双活三、四三)额外加分。"""
    scores = sorted((line_score(_window(board, x, y, dx, dy, me)) for dx, dy in DIRS), reverse=True)
    total = sum(scores)
    if scores[0] >= 60_000 and scores[1] >= 11_000:      # 冲四 + 活三 / 双四:基本必胜
        total += 400_000
    elif scores[0] >= 11_000 and scores[1] >= 11_000:    # 双活三
        total += 120_000
    return total


def candidates(board: Board, radius: int = 2) -> list[tuple[int, int]]:
    if not board.moves:
        return [(N // 2, N // 2)]
    seen = set()
    for mx, my in board.moves:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                x, y = mx + dx, my + dy
                if on_board(x, y) and board.grid[y][x] == EMPTY:
                    seen.add((x, y))
    return sorted(seen)


def ranked(board: Board, me: int, defense: float = 0.95) -> list[tuple[int, tuple[int, int]]]:
    """所有候选点按 进攻分 + 防守分 从高到低。"""
    opp = other(me)
    out = []
    center = N // 2
    for x, y in candidates(board):
        att = point_score(board, x, y, me)
        dfn = point_score(board, x, y, opp)
        bonus = 14 - abs(x - center) - abs(y - center)     # 同分时靠中间一点
        out.append((int(att * 1.05 + dfn * defense) + bonus, (x, y)))
    out.sort(reverse=True)
    return out


def choose(board: Board, level: str = "normal", rng: random.Random | None = None) -> tuple[int, int]:
    """电脑这一步下哪里。"""
    rng = rng or random.Random()
    me = board.turn
    if not board.moves:
        return (N // 2, N // 2)
    if len(board.moves) == 1 and me != BLACK:            # 白棋第一手:贴着黑棋斜着下
        x, y = board.moves[0]
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (0, 1)):
            if board.can_place(x + dx, y + dy):
                return (x + dx, y + dy)
    opp = other(me)
    cands = candidates(board)
    for x, y in cands:                                    # 自己能直接赢
        if line_score_max(board, x, y, me) >= 10_000_000:
            return (x, y)
    must = [(x, y) for x, y in cands if line_score_max(board, x, y, opp) >= 10_000_000]
    if must:                                              # 对方下一步就赢:必须堵
        return must[0]
    if level == "easy":
        top = ranked(board, me, defense=0.6)[:6]
        if rng.random() < 0.3:                            # 偶尔看漏
            top = ranked(board, me, defense=0.2)[:6]
        weights = [len(top) - i for i in range(len(top))]
        return rng.choices([p for _, p in top], weights=weights)[0]
    ranking = ranked(board, me)
    if level != "hard" or len(ranking) < 2:
        best = ranking[0][0]
        ties = [p for s, p in ranking if s >= best * 0.98]
        return rng.choice(ties[:3])
    # 困难:前几名各往下想一步 —— 假设对手用他最好的几种应对,看局面对自己是不是还好
    best_pt, best_val = ranking[0][1], None
    for score, (x, y) in ranking[:8]:
        if score >= 400_000:                              # 已经是必胜棋形,直接下
            return (x, y)
        b2 = board.copy()
        b2.place(x, y)
        worst = None
        for _s, (rx, ry) in ranked(b2, opp)[:5]:
            b3 = b2.copy()
            if b3.place(rx, ry):
                val = -1e12                               # 对手这样能直接赢
            else:
                val = position_value(b3, me)
            if worst is None or val < worst:
                worst = val
        worst = position_value(b2, me, mover=opp) if worst is None else worst
        if best_val is None or worst > best_val:
            best_val, best_pt = worst, (x, y)
    return best_pt


def top_attack(board: Board, color: int) -> int:
    return max((point_score(board, x, y, color) for x, y in candidates(board)), default=0)


def position_value(board: Board, me: int, mover: int | None = None) -> float:
    """局面对 me 有多好。轮到谁下很重要:轮到的一方的威胁先兑现。"""
    mover = board.turn if mover is None else mover
    mine, theirs = top_attack(board, me), top_attack(board, other(me))
    if mover == me:
        if mine >= 10_000_000:
            return 1e11
        if theirs >= 10_000_000:                          # 我得先堵
            return -theirs * 0.5 + mine * 0.2
        return mine * 1.2 - theirs * 0.8
    if theirs >= 10_000_000:
        return -1e11
    return mine * 0.8 - theirs * 1.2


def line_score_max(board: Board, x: int, y: int, me: int) -> int:
    return max(line_score(_window(board, x, y, dx, dy, me)) for dx, dy in DIRS)
