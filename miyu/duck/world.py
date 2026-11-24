"""
谁是坏鸭 · 地图「鹅鸭庄园」(原创)。
坐标单位是"像素"(按 1 倍缩放),整张地图 2400 × 1500。能走的地方 = 若干个矩形(房间 + 走廊)的并集。
角色是半径 PLAYER_R 的圆:圆心在"能走的矩形向里缩 PLAYER_R"的范围内就算没撞墙;撞墙时沿墙滑动。
门:锁门时门所在的一小块矩形暂时不能走。视线:两点之间每隔一小段检查一次是不是都在能走的范围里。
"""
from __future__ import annotations

import math

W, H = 2400, 1500
PLAYER_R = 18
SPEED = 230.0                 # 每秒走多少像素
VISION = 340.0
VISION_DARK = 135.0           # 关灯时好鹅只看得到这么远
KILL_RANGE = 80.0
REPORT_RANGE = 110.0
USE_RANGE = 70.0
BUTTON_RANGE = 90.0


class Rect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x: float, y: float, w: float, h: float) -> None:
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def r(self) -> float:
        return self.x + self.w

    @property
    def b(self) -> float:
        return self.y + self.h

    def contains(self, px: float, py: float, inset: float = 0.0) -> bool:
        return self.x + inset <= px <= self.r - inset and self.y + inset <= py <= self.b - inset

    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


# 房间:(id, 名字, 矩形, 地板颜色)
ROOMS = [
    ("kitchen", "厨房", Rect(100, 100, 520, 400), "#F6E7C8"),
    ("barn", "谷仓", Rect(850, 100, 700, 400), "#E9D3B4"),
    ("garden", "菜园", Rect(1780, 100, 520, 400), "#D8EFC4"),
    ("power", "配电室", Rect(100, 640, 460, 300), "#D9DEE8"),
    ("plaza", "中央广场", Rect(880, 600, 640, 380), "#F3EFE6"),
    ("clinic", "医务室", Rect(1840, 640, 460, 300), "#DDF0F2"),
    ("storage", "仓库", Rect(100, 1080, 520, 320), "#E2D6C8"),
    ("pond", "池塘", Rect(850, 1100, 700, 300), "#CFE8F5"),
    ("coop", "鸡舍", Rect(1780, 1080, 520, 320), "#F2DEC9"),
]
ROOM_BY_ID = {r[0]: r for r in ROOMS}

# 走廊(把房间连起来,两头各伸进房间一点,保证转角走得过去)
HALLS = [
    Rect(570, 240, 330, 120),     # 厨房 — 谷仓
    Rect(1500, 240, 330, 120),    # 谷仓 — 菜园
    Rect(300, 450, 120, 240),     # 厨房 — 配电室
    Rect(2000, 450, 120, 240),    # 菜园 — 医务室
    Rect(1140, 450, 120, 200),    # 谷仓 — 中央广场
    Rect(510, 730, 420, 120),     # 配电室 — 中央广场
    Rect(1470, 730, 420, 120),    # 中央广场 — 医务室
    Rect(300, 890, 120, 240),     # 配电室 — 仓库
    Rect(2000, 890, 120, 240),    # 医务室 — 鸡舍
    Rect(1140, 930, 120, 220),    # 中央广场 — 池塘
    Rect(570, 1180, 330, 120),    # 仓库 — 池塘
    Rect(1500, 1180, 330, 120),   # 池塘 — 鸡舍
]
WALKABLE = [r[2] for r in ROOMS] + HALLS

# 门:锁门时按房间锁(每个房间的门 = 走廊和房间交界处的一小块)
DOORS: dict[str, list[Rect]] = {}


def _make_doors() -> None:
    for rid, _name, room, _c in ROOMS:
        out = []
        for h in HALLS:
            ix = max(room.x, h.x)
            iy = max(room.y, h.y)
            ir = min(room.r, h.r)
            ib = min(room.b, h.b)
            if ir <= ix or ib <= iy:
                continue
            # 交界处:走廊伸进房间的那一段,门做成 26 像素厚的一条
            if h.w > h.h:                  # 横走廊:门是竖的
                x = room.x - 13 if h.x < room.x else room.r - 13
                out.append(Rect(x, h.y, 26, h.h))
            else:
                y = room.y - 13 if h.y < room.y else room.b - 13
                out.append(Rect(h.x, y, h.w, 26))
        DOORS[rid] = out


_make_doors()

# 紧急按钮在中央广场正中间;开会后大家围着它站
BUTTON = (1200.0, 790.0)
LIGHT_SWITCH = ("power", 180.0, 700.0)     # 关灯后去配电室修电闸

# 任务点:(id, 种类, 房间, x, y, 名字)
TASK_SPOTS = [
    ("k_code", "memory", "kitchen", 210, 170, "记下冰箱密码"),
    ("k_swipe", "swipe", "kitchen", 520, 420, "刷饭卡"),
    ("b_wire", "wires", "barn", 920, 160, "接谷仓电线"),
    ("b_hay", "drag", "barn", 1450, 420, "把干草叉进槽"),
    ("g_carrot", "drag", "garden", 1880, 200, "拔萝卜"),
    ("g_seq", "seq", "garden", 2200, 420, "按顺序浇水"),
    ("p_wire", "wires", "power", 480, 880, "接配电室电线"),
    ("c_seq", "seq", "clinic", 2220, 700, "按顺序体检"),
    ("c_swipe", "swipe", "clinic", 1920, 880, "刷医保卡"),
    ("s_code", "memory", "storage", 180, 1340, "核对货架编号"),
    ("s_box", "drag", "storage", 540, 1140, "把箱子搬上架"),
    ("f_fish", "drag", "pond", 1000, 1340, "喂鱼"),
    ("f_wire", "wires", "pond", 1480, 1160, "接水泵电线"),
    ("h_seq", "seq", "coop", 1860, 1140, "按顺序捡鸡蛋"),
    ("h_code", "memory", "coop", 2220, 1340, "记下鸡舍号码"),
    ("b_radio", "dial", "barn", 1200, 170, "调收音机频率"),
    ("k_dish", "clean", "kitchen", 380, 440, "刷盘子"),
    ("c_dial", "dial", "clinic", 2220, 880, "调体温计"),
    ("s_clean", "clean", "storage", 300, 1350, "擦干净货箱"),
]
TASK_BY_ID = {t[0]: t for t in TASK_SPOTS}
TASK_KINDS = {"wires": "接电线", "swipe": "刷卡", "seq": "按顺序点", "drag": "拖进去", "memory": "记号码",
              "dial": "调频率", "clean": "擦干净"}

COLORS = [
    ("red", "红", "#FF6B6B"), ("orange", "橙", "#FFA94D"), ("yellow", "黄", "#FFD43B"), ("green", "绿", "#69DB7C"),
    ("cyan", "青", "#3BC9DB"), ("blue", "蓝", "#4DABF7"), ("purple", "紫", "#9775FA"), ("pink", "粉", "#F783AC"),
    ("white", "白", "#F1F3F5"), ("brown", "棕", "#B08968"),
]
COLOR_BY_ID = {c[0]: c for c in COLORS}


def in_doors(x: float, y: float, locked: set | frozenset, pad: float = PLAYER_R) -> bool:
    for rid in locked:
        for d in DOORS.get(rid, ()):
            if d.x - pad <= x <= d.r + pad and d.y - pad <= y <= d.b + pad:
                return True
    return False


def walkable(x: float, y: float, locked=frozenset(), inset: float = PLAYER_R) -> bool:
    if not any(r.contains(x, y, inset) for r in WALKABLE):
        return False
    return not (locked and in_doors(x, y, locked))


def move(x: float, y: float, dx: float, dy: float, locked=frozenset(), ghost: bool = False) -> tuple[float, float]:
    """从 (x, y) 走 (dx, dy):撞墙就沿墙滑。幽灵可以穿墙(但出不了地图)。"""
    if ghost:
        return min(W - 20.0, max(20.0, x + dx)), min(H - 20.0, max(20.0, y + dy))
    nx, ny = x + dx, y + dy
    if walkable(nx, ny, locked):
        return nx, ny
    if walkable(nx, y, locked):
        return nx, y
    if walkable(x, ny, locked):
        return x, ny
    # 卡在门口(门刚锁上):允许往外挪
    if not walkable(x, y, locked) and walkable(x, y):
        return nx, ny
    return x, y


def path_clear(x0: float, y0: float, x1: float, y1: float, locked=frozenset()) -> bool:
    """从 (x0, y0) 走到 (x1, y1) 的一路上没穿墙、没穿过锁着的门(房主检查玩家报来的位置用)。"""
    d = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int(d / 12))
    for i in range(1, n + 1):
        t = i / n
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        if not any(r.contains(x, y, 4) for r in WALKABLE):
            return False
        if locked and in_doors(x, y, locked, pad=PLAYER_R - 6):
            return False
    return True


def line_of_sight(x0: float, y0: float, x1: float, y1: float, locked=frozenset()) -> bool:
    """两点之间有没有被墙(或锁着的门)挡住。"""
    d = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int(d / 22))
    for i in range(1, n):
        t = i / n
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        if not any(r.contains(x, y) for r in WALKABLE):
            return False
        if locked and in_doors(x, y, locked, pad=0):
            return False
    return True


def room_at(x: float, y: float) -> str | None:
    for rid, _n, r, _c in ROOMS:
        if r.contains(x, y):
            return rid
    return None


def room_name(rid: str | None) -> str:
    return ROOM_BY_ID[rid][1] if rid in ROOM_BY_ID else "走廊"


def spawn_points(n: int) -> list[tuple[float, float]]:
    """开局 / 开完会:围着紧急按钮站一圈。"""
    out = []
    for i in range(n):
        a = -math.pi / 2 + i / max(1, n) * math.tau
        out.append((BUTTON[0] + math.cos(a) * 130, BUTTON[1] + math.sin(a) * 105))
    return out


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)
