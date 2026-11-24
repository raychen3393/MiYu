"""
五子棋规则:15×15,黑棋先手,双方轮流落子;横、竖、斜任意方向连成五子(或更多)获胜;棋盘下满没人获胜算平局。
"""
from __future__ import annotations

N = 15
EMPTY, BLACK, WHITE = 0, 1, 2
COLOR = {"b": BLACK, "w": WHITE}
NAME = {BLACK: "b", WHITE: "w"}
DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))


def other(c: int) -> int:
    return WHITE if c == BLACK else BLACK


def on_board(x: int, y: int) -> bool:
    return 0 <= x < N and 0 <= y < N


class Board:
    """一盘棋的局面。moves 按顺序记着 (x, y);黑先,所以第 i 手(从 0 数)是黑棋当且仅当 i 是偶数。"""

    def __init__(self, moves=None) -> None:
        self.grid = [[EMPTY] * N for _ in range(N)]
        self.moves: list[tuple[int, int]] = []
        for x, y in moves or []:
            self.place(x, y)

    def copy(self) -> "Board":
        b = Board()
        b.grid = [row[:] for row in self.grid]
        b.moves = list(self.moves)
        return b

    @property
    def turn(self) -> int:
        return BLACK if len(self.moves) % 2 == 0 else WHITE

    def at(self, x: int, y: int) -> int:
        return self.grid[y][x]

    def can_place(self, x: int, y: int) -> bool:
        return type(x) is int and type(y) is int and on_board(x, y) and self.grid[y][x] == EMPTY

    def place(self, x: int, y: int) -> list[tuple[int, int]] | None:
        """落一子(轮到谁就是谁的)。连成五子返回那一串点,否则 None。不能落时抛 ValueError。"""
        if not self.can_place(x, y):
            raise ValueError("这里不能落子")
        self.grid[y][x] = self.turn
        self.moves.append((x, y))
        return self.five_at(x, y)

    def undo(self, n: int = 1) -> None:
        for _ in range(min(n, len(self.moves))):
            x, y = self.moves.pop()
            self.grid[y][x] = EMPTY

    def five_at(self, x: int, y: int) -> list[tuple[int, int]] | None:
        c = self.grid[y][x]
        if c == EMPTY:
            return None
        for dx, dy in DIRS:
            line = [(x, y)]
            for sgn in (1, -1):
                k = 1
                while on_board(x + sgn * dx * k, y + sgn * dy * k) and self.grid[y + sgn * dy * k][x + sgn * dx * k] == c:
                    line.append((x + sgn * dx * k, y + sgn * dy * k))
                    k += 1
            if len(line) >= 5:
                return sorted(line)
        return None

    @property
    def full(self) -> bool:
        return len(self.moves) >= N * N

    @property
    def last(self) -> tuple[int, int] | None:
        return self.moves[-1] if self.moves else None
