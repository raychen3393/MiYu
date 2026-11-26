"""
密语 3.8 · 《🥕 萌宠保卫战》2.5D 保卫萝卜式路径塔防小游戏
  · 3 张手绘 2.5D 黏土主题地图（阳光草坪 / 奶油海滩 / 星空花园）
  · 终点小窝趴着玩家自己穿好衣橱装扮的 2.5D 萌宠（10 颗心血量）
  · 5 种可升 3 级的 2.5D 萌宠炮塔（泡泡猫 / 冰霜企鹅 / 烈焰狐 / 水豚太阳 / 雷电柴犬）
  · 地图可破坏障碍物（大萝卜 / 饼干盒 / 藏宝箱，拆箱爆金币或送隐藏炮塔）+ 点击手动集火准星
  · 支持 1x/2x 倍速、暂停、❄️全局冰冻 & ⚡萌宠狂暴大招、10 波闯关拿金萝卜 & 无尽冲榜
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .dialogs import Dialog
from .fun import OUTLINE, PetGrowth, TypingPet
from .pet3d import clay_brush, contour_pen
from .sound import play_game_sfx
from .theme import is_dark
from .ui import button, label

TILE = 48
COLS, ROWS = 12, 7
HUD_H = 32

# 3 张 2.5D 地图定义: waypoints 为 (col, row) 路径折点, obstacles 为 [(col, row, kind)]
TD_MAPS: list[dict] = [
    {
        "id": "meadow",
        "name": "🌿 阳光草坪",
        "bg0": "#C6F6B2", "bg1": "#8CE99A", "dark0": "#1C2E24", "dark1": "#15231C",
        "path_col": "#F6DFB5", "path_edge": "#D4AE74",
        "waypoints": [(0, 1), (9, 1), (9, 3), (2, 3), (2, 5), (11, 5)],
        "obstacles": [
            (4, 2, "carrot"), (7, 2, "cookie"), (5, 4, "chest"), (8, 4, "carrot"),
            (1, 4, "cookie"), (10, 2, "chest"), (6, 0, "carrot"), (4, 6, "cookie"),
        ],
    },
    {
        "id": "beach",
        "name": "🏖️ 奶油海滩",
        "bg0": "#FFF3BF", "bg1": "#FFD8A8", "dark0": "#2D251C", "dark1": "#221C15",
        "path_col": "#A5D8FF", "path_edge": "#4DABF7",
        "waypoints": [(0, 5), (3, 5), (3, 1), (8, 1), (8, 5), (11, 5)],
        "obstacles": [
            (1, 2, "chest"), (5, 3, "carrot"), (6, 3, "chest"), (5, 5, "cookie"),
            (6, 5, "carrot"), (10, 2, "cookie"), (1, 3, "carrot"), (10, 3, "chest"),
        ],
    },
    {
        "id": "star",
        "name": "🌌 星空花园",
        "bg0": "#D0BFFF", "bg1": "#9775FA", "dark0": "#1A1833", "dark1": "#121024",
        "path_col": "#FFE066", "path_edge": "#F08C00",
        "waypoints": [(0, 3), (2, 3), (2, 1), (10, 1), (10, 5), (4, 5), (4, 3), (8, 3)],
        "obstacles": [
            (6, 2, "chest"), (7, 4, "chest"), (1, 1, "carrot"), (1, 5, "cookie"),
            (6, 0, "cookie"), (8, 6, "carrot"), (11, 3, "chest"), (3, 6, "cookie"),
        ],
    },
]

# 5 种 2.5D 萌宠炮塔:(id, 图标, 名称, 简介, 主色, 造价, 升级费[lv2, lv3], 射程[1..3], 攻击[1..3], 间隔[1..3])
TD_TOWERS: list[dict] = [
    {"id": "cat", "ico": "🐱", "name": "泡泡猫", "desc": "高速单体/满级双连发", "col": "#FFB3C6",
     "cost": 80, "up": (110, 160), "rng": (122, 140, 160), "dmg": (22, 38, 44), "cd": (0.46, 0.38, 0.34)},
    {"id": "penguin", "ico": "🐧", "name": "冰霜企鹅", "desc": "范围雪花减速控场", "col": "#74C0FC",
     "cost": 100, "up": (130, 180), "rng": (118, 136, 156), "dmg": (14, 24, 38), "cd": (0.95, 0.85, 0.75)},
    {"id": "fox", "ico": "🦊", "name": "烈焰狐", "desc": "范围火球爆炸溅射", "col": "#FF922B",
     "cost": 130, "up": (160, 220), "rng": (128, 146, 166), "dmg": (34, 56, 86), "cd": (1.15, 1.02, 0.90)},
    {"id": "capy", "ico": "🍊", "name": "水豚太阳", "desc": "全向光波+每波产金币", "col": "#FFD43B",
     "cost": 120, "up": (150, 210), "rng": (108, 124, 142), "dmg": (18, 30, 46), "cd": (1.10, 0.98, 0.86)},
    {"id": "shiba", "ico": "🐕", "name": "雷电柴犬", "desc": "超远射程连锁闪电", "col": "#B197FC",
     "cost": 150, "up": (190, 260), "rng": (168, 192, 220), "dmg": (30, 52, 82), "cd": (1.05, 0.92, 0.80)},
]
TD_TOWER_BY_ID = {t["id"]: t for t in TD_TOWERS}


def _tile_center(col: int, row: int) -> tuple[float, float]:
    return col * TILE + TILE * 0.5, HUD_H + row * TILE + TILE * 0.5


def _expand_path_tiles(waypoints: list[tuple[int, int]]) -> set[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    for i in range(len(waypoints) - 1):
        c0, r0 = waypoints[i]
        c1, r1 = waypoints[i + 1]
        dc = 0 if c0 == c1 else (1 if c1 > c0 else -1)
        dr = 0 if r0 == r1 else (1 if r1 > r0 else -1)
        c, r = c0, r0
        tiles.add((c, r))
        while (c, r) != (c1, r1):
            c += dc
            r += dr
            tiles.add((c, r))
    return tiles


def _build_wave(wave: int) -> list[dict]:
    """生成第 wave 波的捣蛋怪队列。"""
    scale = 1.0 + (wave - 1) * 0.28 + (max(0, wave - 10) ** 1.35) * 0.25
    out: list[dict] = []
    cnt = 6 + wave * 2
    for i in range(cnt):
        if wave >= 4 and i % 5 == 4:
            kind, hp, spd, gold, rad = "turtle", int(145 * scale), 36.0, 28, 16.0
        elif wave >= 3 and i % 4 == 3:
            kind, hp, spd, gold, rad = "ghost", int(72 * scale), 68.0, 22, 13.5
        elif wave >= 2 and i % 3 == 2:
            kind, hp, spd, gold, rad = "duck", int(82 * scale), 58.0, 20, 14.0
        else:
            kind, hp, spd, gold, rad = "slime", int(70 * scale), 46.0, 16, 13.5
        out.append({"kind": kind, "hp": hp, "max_hp": hp, "spd": spd, "gold": gold, "r": rad})
    if wave % 5 == 0:
        bhp = int(620 * scale)
        out.append({"kind": "boss", "hp": bhp, "max_hp": bhp, "spd": 32.0, "gold": 150, "r": 21.0})
    return out


class _TDStage(QWidget):
    """保卫萝卜风 2.5D 路径塔防核心画布。"""
    state_changed = Signal()
    finished = Signal(bool, int, int)       # (是否通关, 分数, 完成波次)

    W = COLS * TILE
    H = HUD_H + ROWS * TILE

    def __init__(self, parent, growth: PetGrowth, species: str, win=None) -> None:
        super().__init__(parent)
        self.growth = growth
        self.species = species
        self.win = win
        self.setFixedSize(self.W, self.H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.pet = TypingPet(None)
        self.pet.bare = True
        self.pet.centered = True
        self.pet.visitor = True
        self.pet.growth = growth
        self.pet.set_species(species)
        self.pet.resize(TypingPet.W, TypingPet.H)

        self.map_idx = 0
        self.endless = False
        self.armed_tower: str | None = "cat"
        self.selected_tile: tuple[int, int] | None = None
        self.focus_target: dict | None = None
        self.speed_mul = 1
        self.paused = False
        self.running = False
        self.game_over = False
        self.victory = False

        self.gold = 260
        self.hearts = 10
        self.max_hearts = 10
        self.score = 0
        self.wave = 0
        self.max_waves = 10
        self.kills = 0
        self.cleared_obs = 0

        self.path_pts: list[tuple[float, float]] = []
        self.path_tiles: set[tuple[int, int]] = set()
        self.towers: dict[tuple[int, int], dict] = {}
        self.obstacles: dict[tuple[int, int], dict] = {}
        self.enemies: list[dict] = []
        self.bullets: list[dict] = []
        self.fx: list[dict] = []
        self._spawn_q: list[dict] = []
        self._spawn_cd = 0.0
        self._wave_gap = 2.0
        self._pet_hurt_t = 0.0
        self.freeze_cd = 0.0
        self.freeze_left = 0.0
        self.rage_cd = 0.0
        self.rage_left = 0.0
        self._hover_tile: tuple[int, int] | None = None

        self._last_t = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._step)
        self.load_map(0, endless=False)

    def load_map(self, idx: int, endless: bool = False) -> None:
        self.map_idx = idx % len(TD_MAPS)
        self.endless = endless
        m = TD_MAPS[self.map_idx]
        self.path_pts = [_tile_center(c, r) for c, r in m["waypoints"]]
        self.path_tiles = _expand_path_tiles(m["waypoints"])
        self.towers.clear()
        self.obstacles.clear()
        for c, r, kind in m["obstacles"]:
            if (c, r) in self.path_tiles:
                continue
            hp = {"carrot": 130, "cookie": 170, "chest": 220}[kind]
            gold = {"carrot": 65, "cookie": 95, "chest": 140}[kind]
            x, y = _tile_center(c, r)
            self.obstacles[(c, r)] = {"col": c, "row": r, "kind": kind, "hp": hp, "max_hp": hp,
                                      "gold": gold, "x": x, "y": y, "is_obs": True}
        self.enemies.clear()
        self.bullets.clear()
        self.fx.clear()
        self._spawn_q.clear()
        self.focus_target = None
        self.selected_tile = None
        self.gold = 280
        self.hearts = self.max_hearts = 10
        self.score = 0
        self.wave = 0
        self.kills = 0
        self.cleared_obs = 0
        self.freeze_cd = self.freeze_left = 0.0
        self.rage_cd = self.rage_left = 0.0
        self._pet_hurt_t = 0.0
        self._wave_gap = 1.6
        self.paused = False
        self.game_over = False
        self.victory = False
        self.running = True
        self._last_t = time.monotonic()
        self._timer.start()
        self.state_changed.emit()
        self.update()

    def stop(self) -> None:
        self.running = False
        self._timer.stop()

    def toggle_speed(self) -> None:
        self.speed_mul = 2 if self.speed_mul == 1 else 1
        play_game_sfx(self.win, "click", 0.6)
        self.state_changed.emit()

    def toggle_pause(self) -> None:
        if self.game_over or self.victory:
            return
        self.paused = not self.paused
        self._last_t = time.monotonic()
        play_game_sfx(self.win, "click", 0.6)
        self.state_changed.emit()
        self.update()

    def cast_freeze(self) -> bool:
        if not self.running or self.paused or self.freeze_cd > 0:
            return False
        self.freeze_cd = 24.0
        self.freeze_left = 5.0
        for e in self.enemies:
            e["slow_t"] = max(e["slow_t"], 5.0)
            e["slow_f"] = min(e["slow_f"], 0.25)
        self.fx.append({"type": "text", "x": self.W * 0.5, "y": self.H * 0.45, "t": "❄️ 全局冰冻!", "col": "#74C0FC", "life": 1.2})
        play_game_sfx(self.win, "freeze", 0.85)
        self.state_changed.emit()
        return True

    def cast_rage(self) -> bool:
        if not self.running or self.paused or self.rage_cd > 0:
            return False
        self.rage_cd = 28.0
        self.rage_left = 7.0
        self.fx.append({"type": "text", "x": self.W * 0.5, "y": self.H * 0.45, "t": "⚡ 萌宠狂暴 2×攻速!", "col": "#FFD43B", "life": 1.2})
        play_game_sfx(self.win, "boost", 0.85)
        self.state_changed.emit()
        return True

    def continue_endless(self) -> None:
        self.endless = True
        self.victory = False
        self.running = True
        self._wave_gap = 2.0
        self._last_t = time.monotonic()
        self._timer.start()
        self.state_changed.emit()
        self.update()

    def build_at(self, tile: tuple[int, int], tid: str) -> bool:
        if not self.running or self.game_over or self.victory:
            return False
        if tile in self.path_tiles or tile in self.towers or tile in self.obstacles:
            return False
        c, r = tile
        if not (0 <= c < COLS and 0 <= r < ROWS):
            return False
        spec = TD_TOWER_BY_ID.get(tid)
        if spec is None or self.gold < spec["cost"]:
            play_game_sfx(self.win, "hurt", 0.5)
            return False
        self.gold -= spec["cost"]
        x, y = _tile_center(c, r)
        self.towers[tile] = {"id": tid, "lv": 1, "col": c, "row": r, "x": x, "y": y,
                             "cd": 0.0, "angle": 0.0, "spent": spec["cost"], "recoil": 0.0}
        self.selected_tile = tile
        self.fx.append({"type": "ring", "x": x, "y": y, "r": 12.0, "max_r": 38.0, "col": spec["col"], "life": 0.35})
        play_game_sfx(self.win, "build", 0.75)
        self.state_changed.emit()
        self.update()
        return True

    def upgrade_selected(self) -> bool:
        if self.selected_tile is None or self.selected_tile not in self.towers:
            return False
        tw = self.towers[self.selected_tile]
        if tw["lv"] >= 3:
            return False
        spec = TD_TOWER_BY_ID[tw["id"]]
        cost = spec["up"][tw["lv"] - 1]
        if self.gold < cost:
            play_game_sfx(self.win, "hurt", 0.5)
            return False
        self.gold -= cost
        tw["lv"] += 1
        tw["spent"] += cost
        self.fx.append({"type": "text", "x": tw["x"], "y": tw["y"] - 18, "t": f"⬆️ Lv.{tw['lv']}!", "col": "#FFD43B", "life": 0.9})
        self.fx.append({"type": "ring", "x": tw["x"], "y": tw["y"], "r": 10.0, "max_r": 46.0, "col": "#FFD43B", "life": 0.4})
        play_game_sfx(self.win, "combo", 0.75)
        self.state_changed.emit()
        self.update()
        return True

    def sell_selected(self) -> bool:
        if self.selected_tile is None or self.selected_tile not in self.towers:
            return False
        tw = self.towers.pop(self.selected_tile)
        refund = int(tw["spent"] * 0.75)
        self.gold += refund
        self.fx.append({"type": "text", "x": tw["x"], "y": tw["y"] - 14, "t": f"+{refund}💰", "col": "#FFD43B", "life": 0.85})
        self.selected_tile = None
        play_game_sfx(self.win, "coin", 0.7)
        self.state_changed.emit()
        self.update()
        return True

    def _tile_at(self, px: float, py: float) -> tuple[int, int] | None:
        if py < HUD_H:
            return None
        c = int(px // TILE)
        r = int((py - HUD_H) // TILE)
        if 0 <= c < COLS and 0 <= r < ROWS:
            return (c, r)
        return None

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        self._hover_tile = self._tile_at(float(pos.x()), float(pos.y()))
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self.running or self.game_over or self.victory:
            return
        px, py = float(e.position().x()), float(e.position().y())
        # 1) 优先检测是否点击敌人 → 设为集火目标
        for en in self.enemies:
            if math.hypot(px - en["x"], py - en["y"]) <= en["r"] + 10:
                self.focus_target = None if self.focus_target is en else en
                play_game_sfx(self.win, "click", 0.65)
                self.update()
                return
        tile = self._tile_at(px, py)
        if tile is None:
            return
        # 2) 点击障碍物 → 设为集火目标
        if tile in self.obstacles:
            ob = self.obstacles[tile]
            self.focus_target = None if self.focus_target is ob else ob
            play_game_sfx(self.win, "click", 0.65)
            self.update()
            return
        # 3) 点击已有炮塔 → 选中显示射程与升级/出售
        if tile in self.towers:
            self.selected_tile = None if self.selected_tile == tile else tile
            play_game_sfx(self.win, "click", 0.6)
            self.state_changed.emit()
            self.update()
            return
        # 4) 点击可建草地 → 若已选炮塔类型直接建造,否则选中格子
        if tile not in self.path_tiles:
            if self.armed_tower:
                if not self.build_at(tile, self.armed_tower):
                    self.selected_tile = tile
                    self.state_changed.emit()
            else:
                self.selected_tile = tile
                self.state_changed.emit()
            self.update()

    def _start_next_wave(self) -> None:
        self.wave += 1
        self._spawn_q = _build_wave(self.wave)
        self._spawn_cd = 0.25
        # 水豚太阳每波额外产金
        bonus_gold = 0
        for tw in self.towers.values():
            if tw["id"] == "capy":
                g = (25, 42, 65)[tw["lv"] - 1]
                bonus_gold += g
                self.fx.append({"type": "text", "x": tw["x"], "y": tw["y"] - 18, "t": f"+{g}☀️", "col": "#FFD43B", "life": 1.0})
        if bonus_gold > 0:
            self.gold += bonus_gold
            play_game_sfx(self.win, "coin", 0.65)
        self.fx.append({"type": "text", "x": self.W * 0.5, "y": HUD_H + 34,
                        "t": f"🌊 第 {self.wave} 波来袭!" + (" (BOSS!)" if self.wave % 5 == 0 else ""),
                        "col": "#FF922B" if self.wave % 5 == 0 else "#FFFFFF", "life": 1.4})
        self.state_changed.emit()

    def _damage_target(self, target: dict, dmg: float, slow: float = 0.0) -> None:
        if target["hp"] <= 0:
            return
        target["hp"] -= dmg
        if slow > 0 and not target.get("is_obs"):
            target["slow_t"] = max(target["slow_t"], 2.3)
            target["slow_f"] = min(target["slow_f"], 1.0 - slow)
        if target["hp"] <= 0:
            if self.focus_target is target:
                self.focus_target = None
            if target.get("is_obs"):
                tile = (target["col"], target["row"])
                self.obstacles.pop(tile, None)
                self.cleared_obs += 1
                self.gold += target["gold"]
                self.score += target["gold"]
                self.fx.append({"type": "text", "x": target["x"], "y": target["y"] - 10,
                                "t": f"+{target['gold']}💰", "col": "#FFD43B", "life": 0.95})
                # 宝箱有 38% 概率开出隐藏免费 Lv.1 炮塔!
                if target["kind"] == "chest" and random.random() < 0.38:
                    tid = random.choice(["cat", "penguin", "fox", "shiba"])
                    self.towers[tile] = {"id": tid, "lv": 1, "col": tile[0], "row": tile[1],
                                         "x": target["x"], "y": target["y"], "cd": 0.2,
                                         "angle": 0.0, "spent": TD_TOWER_BY_ID[tid]["cost"], "recoil": 0.0}
                    self.fx.append({"type": "text", "x": target["x"], "y": target["y"] - 26,
                                    "t": f"🎁 隐藏{TD_TOWER_BY_ID[tid]['name']}!", "col": "#51CF66", "life": 1.3})
                play_game_sfx(self.win, "coin", 0.75)
            else:
                self.kills += 1
                self.gold += target["gold"]
                pts = target["gold"] * 4 + (300 if target["kind"] == "boss" else 0)
                self.score += pts
                self.fx.append({"type": "text", "x": target["x"], "y": target["y"] - 10,
                                "t": f"+{target['gold']}💰", "col": "#FFD43B", "life": 0.75})
                play_game_sfx(self.win, "pop", 0.55)
            self.state_changed.emit()

    def _step(self) -> None:
        now = time.monotonic()
        raw_dt = min(0.05, max(0.005, now - self._last_t))
        self._last_t = now
        if not self.running or self.paused:
            return
        dt = raw_dt * self.speed_mul
        self.pet.pose3d.step(now, sleeping=False)
        self._pet_hurt_t = max(0.0, self._pet_hurt_t - raw_dt)
        self.freeze_cd = max(0.0, self.freeze_cd - dt)
        self.freeze_left = max(0.0, self.freeze_left - dt)
        self.rage_cd = max(0.0, self.rage_cd - dt)
        self.rage_left = max(0.0, self.rage_left - dt)

        # 1) 波次刷怪
        if self._spawn_q:
            self._spawn_cd -= dt
            if self._spawn_cd <= 0:
                self._spawn_cd = 0.78 if self.wave < 6 else 0.58
                spec = self._spawn_q.pop(0)
                sx, sy = self.path_pts[0]
                self.enemies.append({
                    **spec, "x": sx, "y": sy, "seg": 0, "prog": 0.0,
                    "slow_t": 0.0, "slow_f": 1.0, "is_obs": False, "wob": random.uniform(0, 6.28),
                })
        elif not self.enemies:
            if not self.endless and self.wave >= self.max_waves:
                self.victory = True
                self.running = False
                self._timer.stop()
                self.score += self.hearts * 120 + self.gold * 2
                play_game_sfx(self.win, "win", 0.85)
                self.state_changed.emit()
                self.finished.emit(True, self.score, self.wave)
                self.update()
                return
            self._wave_gap -= dt
            if self._wave_gap <= 0:
                self._wave_gap = 2.6
                self._start_next_wave()

        # 2) 怪物沿路径前进
        kept_e = []
        for en in self.enemies:
            if en["hp"] <= 0:
                continue
            if en["slow_t"] > 0:
                en["slow_t"] = max(0.0, en["slow_t"] - dt)
                if en["slow_t"] <= 0:
                    en["slow_f"] = 1.0
            spd = en["spd"] * (0.25 if self.freeze_left > 0 else en["slow_f"])
            rem = spd * dt
            reached = False
            while rem > 0 and en["seg"] < len(self.path_pts) - 1:
                x0, y0 = self.path_pts[en["seg"]]
                x1, y1 = self.path_pts[en["seg"] + 1]
                dx, dy = x1 - en["x"], y1 - en["y"]
                dist = math.hypot(dx, dy)
                if dist <= rem:
                    en["x"], en["y"] = x1, y1
                    en["seg"] += 1
                    rem -= dist
                    if en["seg"] >= len(self.path_pts) - 1:
                        reached = True
                        break
                else:
                    en["x"] += dx / dist * rem
                    en["y"] += dy / dist * rem
                    rem = 0.0
            en["prog"] = en["seg"] + 0.001 * math.hypot(
                en["x"] - self.path_pts[min(en["seg"], len(self.path_pts) - 1)][0],
                en["y"] - self.path_pts[min(en["seg"], len(self.path_pts) - 1)][1],
            )
            if reached:
                if self.focus_target is en:
                    self.focus_target = None
                dmg_h = 3 if en["kind"] == "boss" else 1
                self.hearts = max(0, self.hearts - dmg_h)
                self._pet_hurt_t = 0.65
                self.pet.pose3d.impulse(-0.30)
                ex, ey = self.path_pts[-1]
                self.fx.append({"type": "text", "x": ex, "y": ey - 24, "t": f"💔 -{dmg_h}", "col": "#FF6B6B", "life": 1.0})
                play_game_sfx(self.win, "hurt", 0.85)
                self.state_changed.emit()
                if self.hearts <= 0:
                    self.game_over = True
                    self.running = False
                    self._timer.stop()
                    play_game_sfx(self.win, "lose", 0.8)
                    self.finished.emit(False, self.score, max(0, self.wave - 1))
                    self.update()
                    return
                continue
            kept_e.append(en)
        self.enemies = kept_e

        # 3) 炮塔索敌与开火
        fire_rate = 2.0 if self.rage_left > 0 else 1.0
        for tw in self.towers.values():
            tw["recoil"] = max(0.0, tw["recoil"] - dt * 5.0)
            tw["cd"] -= dt * fire_rate
            if tw["cd"] > 0:
                continue
            spec = TD_TOWER_BY_ID[tw["id"]]
            lv_i = tw["lv"] - 1
            rng = spec["rng"][lv_i]
            dmg = spec["dmg"][lv_i]

            # 水豚太阳: 360度范围光波
            if tw["id"] == "capy":
                hits = [e for e in self.enemies if math.hypot(e["x"] - tw["x"], e["y"] - tw["y"]) <= rng]
                obs_hits = [o for o in self.obstacles.values() if math.hypot(o["x"] - tw["x"], o["y"] - tw["y"]) <= rng]
                if self.focus_target and math.hypot(self.focus_target["x"] - tw["x"], self.focus_target["y"] - tw["y"]) <= rng:
                    if self.focus_target.get("is_obs") and self.focus_target not in obs_hits:
                        obs_hits.append(self.focus_target)
                if hits or (self.focus_target and self.focus_target in obs_hits):
                    tw["cd"] = spec["cd"][lv_i]
                    tw["recoil"] = 1.0
                    for e in hits:
                        self._damage_target(e, dmg)
                    for o in obs_hits[:2]:
                        self._damage_target(o, dmg * 0.85)
                    self.fx.append({"type": "ring", "x": tw["x"], "y": tw["y"], "r": 14.0, "max_r": rng,
                                    "col": "#FFD43B", "life": 0.34})
                    play_game_sfx(self.win, "pop", 0.45)
                continue

            # 单体/溅射/冰冻/闪电索敌: 优先集火目标(在射程内) → 最靠后的路径怪物
            target = None
            if self.focus_target is not None and self.focus_target["hp"] > 0:
                if math.hypot(self.focus_target["x"] - tw["x"], self.focus_target["y"] - tw["y"]) <= rng:
                    target = self.focus_target
            if target is None:
                in_rng = [e for e in self.enemies if math.hypot(e["x"] - tw["x"], e["y"] - tw["y"]) <= rng]
                if in_rng:
                    target = max(in_rng, key=lambda e: e["prog"])
            if target is None:
                continue

            tw["cd"] = spec["cd"][lv_i]
            tw["recoil"] = 1.0
            tw["angle"] = math.atan2(target["y"] - tw["y"], target["x"] - tw["x"])

            if tw["id"] == "shiba":
                # 连锁闪电即时命中
                chain = [target]
                last = target
                jumps = 1 + tw["lv"]
                for _ in range(jumps - 1):
                    nxt = [e for e in self.enemies if e not in chain and e["hp"] > 0 and math.hypot(e["x"] - last["x"], e["y"] - last["y"]) <= 95]
                    if not nxt:
                        break
                    last = min(nxt, key=lambda e: math.hypot(e["x"] - last["x"], e["y"] - last["y"]))
                    chain.append(last)
                pts = [(tw["x"], tw["y"])] + [(c["x"], c["y"]) for c in chain]
                self.fx.append({"type": "bolt", "pts": pts, "col": "#D0BFFF", "life": 0.22})
                for idx_c, c in enumerate(chain):
                    self._damage_target(c, dmg * (0.8 ** idx_c))
                play_game_sfx(self.win, "shoot", 0.55)
            else:
                shots = 2 if (tw["id"] == "cat" and tw["lv"] == 3) else 1
                for s_i in range(shots):
                    off = (s_i - 0.5) * 8.0 if shots == 2 else 0.0
                    self.bullets.append({
                        "kind": tw["id"], "x": tw["x"] + off, "y": tw["y"] - 4,
                        "target": target, "dmg": dmg, "lv": tw["lv"],
                        "spd": 380.0 if tw["id"] == "cat" else 300.0,
                        "col": spec["col"],
                    })
                play_game_sfx(self.win, "freeze" if tw["id"] == "penguin" else "shoot", 0.48)

        # 4) 子弹飞行与命中
        kept_b = []
        for b in self.bullets:
            tg = b["target"]
            if tg is None or tg["hp"] <= 0:
                continue
            dx, dy = tg["x"] - b["x"], tg["y"] - b["y"]
            dist = math.hypot(dx, dy)
            step = b["spd"] * dt
            if dist <= step + 8:
                if b["kind"] == "fox":
                    rad = 48.0 + b["lv"] * 10.0
                    self.fx.append({"type": "ring", "x": tg["x"], "y": tg["y"], "r": 8.0, "max_r": rad, "col": "#FF922B", "life": 0.32})
                    for e in list(self.enemies):
                        if math.hypot(e["x"] - tg["x"], e["y"] - tg["y"]) <= rad:
                            self._damage_target(e, b["dmg"])
                    if tg.get("is_obs"):
                        self._damage_target(tg, b["dmg"])
                    play_game_sfx(self.win, "boom", 0.52)
                elif b["kind"] == "penguin":
                    rad = 46.0 + b["lv"] * 8.0
                    slow = 0.36 + b["lv"] * 0.07
                    self.fx.append({"type": "ring", "x": tg["x"], "y": tg["y"], "r": 8.0, "max_r": rad, "col": "#74C0FC", "life": 0.30})
                    for e in list(self.enemies):
                        if math.hypot(e["x"] - tg["x"], e["y"] - tg["y"]) <= rad:
                            self._damage_target(e, b["dmg"], slow=slow)
                    if tg.get("is_obs"):
                        self._damage_target(tg, b["dmg"])
                else:
                    self._damage_target(tg, b["dmg"])
                continue
            b["x"] += dx / dist * step
            b["y"] += dy / dist * step
            kept_b.append(b)
        self.bullets = kept_b

        # 5) 清理死亡障碍/敌人与步进特效
        self.enemies = [e for e in self.enemies if e["hp"] > 0]
        nxt_fx = []
        for f in self.fx:
            f["life"] -= raw_dt
            if f["life"] <= 0:
                continue
            if f["type"] == "text":
                f["y"] -= 26.0 * raw_dt
            elif f["type"] == "ring":
                f["r"] += (f["max_r"] - f["r"]) * min(1.0, raw_dt * 12.0)
            nxt_fx.append(f)
        self.fx = nxt_fx
        self.update()

    def _paint_tower(self, p: QPainter, tw: dict) -> None:
        spec = TD_TOWER_BY_ID[tw["id"]]
        x, y, lv = tw["x"], tw["y"], tw["lv"]
        col = QColor(spec["col"])
        p.save()
        p.translate(x, y)
        sc = 1.0 + 0.08 * (lv - 1) - tw["recoil"] * 0.08
        p.scale(sc, sc)
        # 2.5D 底座
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 42))
        p.drawEllipse(QPointF(0, 14), 20, 7)
        p.setPen(contour_pen(QColor("#F8F9FA"), 1.3))
        p.setBrush(clay_brush(0, 8, 19, 10, QColor("#FFF9DB") if lv == 3 else QColor("#F1F3F5")))
        p.drawRoundedRect(QRectF(-18, 2, 36, 14), 7, 7)
        # 萌宠炮塔本体
        p.setPen(contour_pen(col, 1.5))
        p.setBrush(clay_brush(0, -4, 15, 14, col))
        p.drawEllipse(QPointF(0, -4), 15, 13.5)
        # 耳朵特征
        if tw["id"] in ("cat", "fox", "shiba"):
            for s in (-1, 1):
                ear = QPainterPath(QPointF(s * 9, -12))
                ear.lineTo(s * 13, -21)
                ear.lineTo(s * 3, -16)
                ear.closeSubpath()
                p.drawPath(ear)
        elif tw["id"] == "capy":
            p.setBrush(QColor("#FF922B"))
            p.drawEllipse(QPointF(0, -18), 5.5, 4.2)
        elif tw["id"] == "penguin":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(0, -2), 10, 9)
        # 眼睛
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#232026"))
        for s in (-1, 1):
            p.drawEllipse(QPointF(s * 5.2, -5), 2.1, 2.3)
        # 等级星星
        for i in range(lv):
            sx = (i - (lv - 1) * 0.5) * 9.0
            p.setBrush(QColor("#FFD43B"))
            p.drawEllipse(QPointF(sx, 9.5), 3.0, 3.0)
        p.restore()

    def _paint_obstacle(self, p: QPainter, ob: dict) -> None:
        x, y, kind = ob["x"], ob["y"], ob["kind"]
        p.save()
        p.translate(x, y)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 36))
        p.drawEllipse(QPointF(0, 14), 18, 6.5)
        if kind == "carrot":
            p.setPen(contour_pen(QColor("#FF922B"), 1.4))
            p.setBrush(clay_brush(0, 2, 12, 14, QColor("#FF922B")))
            p.drawPolygon([QPointF(-10, -6), QPointF(10, -6), QPointF(0, 16)])
            p.setBrush(QColor("#51CF66"))
            p.drawEllipse(QPointF(-4, -12), 5, 6)
            p.drawEllipse(QPointF(4, -12), 5, 6)
        elif kind == "cookie":
            p.setPen(contour_pen(QColor("#D99B66"), 1.4))
            p.setBrush(clay_brush(0, 0, 15, 13, QColor("#E8B47E")))
            p.drawRoundedRect(QRectF(-15, -12, 30, 24), 7, 7)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#5C3D2E"))
            for dx, dy in ((-6, -4), (5, -2), (-2, 5), (6, 5)):
                p.drawEllipse(QPointF(dx, dy), 2.3, 2.3)
        else:                                           # chest 宝箱
            p.setPen(contour_pen(QColor("#C87D00"), 1.5))
            p.setBrush(clay_brush(0, 2, 16, 12, QColor("#E6A23C")))
            p.drawRoundedRect(QRectF(-16, -10, 32, 22), 5, 5)
            p.setBrush(QColor("#FFD43B"))
            p.drawRect(QRectF(-16, -2, 32, 4))
            p.drawRoundedRect(QRectF(-4, -4, 8, 8), 2, 2)
        if ob["hp"] < ob["max_hp"]:
            r = max(0.0, ob["hp"] / ob["max_hp"])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 110))
            p.drawRoundedRect(QRectF(-16, -22, 32, 5), 2, 2)
            p.setBrush(QColor("#FFD43B"))
            p.drawRoundedRect(QRectF(-16, -22, 32 * r, 5), 2, 2)
        p.restore()

    def _paint_enemy(self, p: QPainter, en: dict, now: float) -> None:
        x, y, r, kind = en["x"], en["y"], en["r"], en["kind"]
        bob = math.sin(now * 8.0 + en["wob"]) * 2.5
        p.save()
        p.translate(x, y + bob)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QPointF(0, r * 0.72), r * 0.9, r * 0.34)
        col = {
            "slime": QColor("#9775FA"),
            "duck": QColor("#FCC419"),
            "turtle": QColor("#37B24D"),
            "ghost": QColor("#66D9E8"),
            "boss": QColor("#FA5252"),
        }[kind]
        if en["slow_t"] > 0 or self.freeze_left > 0:
            col = QColor("#74C0FC")
        p.setPen(contour_pen(col, 1.5))
        p.setBrush(clay_brush(0, 0, r, r, col))
        p.drawEllipse(QPointF(0, 0), r, r * 0.92)
        if kind == "boss":
            p.setBrush(QColor("#FFD43B"))
            p.drawPolygon([QPointF(-10, -r + 2), QPointF(-12, -r - 10), QPointF(-4, -r - 4),
                           QPointF(0, -r - 12), QPointF(4, -r - 4), QPointF(12, -r - 10), QPointF(10, -r + 2)])
        # 调皮表情
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#232026"))
        for s in (-1, 1):
            p.drawEllipse(QPointF(s * r * 0.34, -r * 0.10), max(2.0, r * 0.14), max(2.0, r * 0.15))
        p.setPen(QPen(QColor("#232026"), 1.6))
        p.drawLine(QPointF(-r * 0.46, -r * 0.34), QPointF(-r * 0.15, -r * 0.22))
        p.drawLine(QPointF(r * 0.46, -r * 0.34), QPointF(r * 0.15, -r * 0.22))
        # 血条
        ratio = max(0.0, en["hp"] / max(1, en["max_hp"]))
        bw = r * 2.1
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(QRectF(-bw / 2, -r - 9, bw, 4.5), 2, 2)
        p.setBrush(QColor("#51CF66") if ratio > 0.45 else QColor("#FF6B6B"))
        p.drawRoundedRect(QRectF(-bw / 2, -r - 9, bw * ratio, 4.5), 2, 2)
        p.restore()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        now = time.monotonic()
        dark = is_dark()
        m = TD_MAPS[self.map_idx]

        # 背景草地
        bg = QLinearGradient(0, HUD_H, 0, self.H)
        bg.setColorAt(0, QColor(m["dark0"] if dark else m["bg0"]))
        bg.setColorAt(1, QColor(m["dark1"] if dark else m["bg1"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), 16, 16)

        # 顶部 HUD 玻璃条
        p.setBrush(QColor(18, 22, 34, 215) if dark else QColor(255, 255, 255, 225))
        p.drawRoundedRect(QRectF(0, 0, self.W, HUD_H), 14, 14)
        hud_f = QFont(self.font())
        hud_f.setPixelSize(12)
        hud_f.setWeight(QFont.Weight.Bold)
        p.setFont(hud_f)
        p.setPen(QColor("#FFFFFF" if dark else "#1D1D1F"))
        w_txt = f"🌊 第 {self.wave} 波 (无尽)" if self.endless else f"🌊 波次 {self.wave}/{self.max_waves}"
        p.drawText(QRectF(12, 0, 150, HUD_H), w_txt, QTextOption(Qt.AlignmentFlag.AlignVCenter))
        p.setPen(QColor("#F59F00"))
        p.drawText(QRectF(164, 0, 108, HUD_H), f"💰 {self.gold}", QTextOption(Qt.AlignmentFlag.AlignVCenter))
        p.setPen(QColor("#FA5252"))
        p.drawText(QRectF(274, 0, 114, HUD_H), f"❤️ {self.hearts}/{self.max_hearts}", QTextOption(Qt.AlignmentFlag.AlignVCenter))
        p.setPen(QColor("#7950F2" if not dark else "#B197FC"))
        p.drawText(QRectF(388, 0, self.W - 400, HUD_H), f"🏆 {self.score:,} ({self.speed_mul}×)",
                   QTextOption(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))

        # 浅格纹与悬停高亮
        for r in range(ROWS):
            for c in range(COLS):
                rect = QRectF(c * TILE + 2, HUD_H + r * TILE + 2, TILE - 4, TILE - 4)
                if (c, r) in self.path_tiles:
                    p.setPen(QPen(QColor(m["path_edge"]), 1.2))
                    p.setBrush(QColor(m["path_col"]))
                    p.drawRoundedRect(rect, 10, 10)
                else:
                    if (c + r) % 2 == 0:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor(255, 255, 255, 16 if dark else 34))
                        p.drawRoundedRect(rect, 8, 8)
                    if self._hover_tile == (c, r) and (c, r) not in self.obstacles:
                        p.setPen(QPen(QColor("#FFFFFF"), 1.8, Qt.PenStyle.DashLine))
                        p.setBrush(QColor(255, 255, 255, 42))
                        p.drawRoundedRect(rect, 10, 10)

        # 入口牌 & 终点萌宠小窝
        sx, sy = self.path_pts[0]
        p.setPen(QPen(QColor("#FA5252"), 1.5))
        p.setBrush(QColor("#FFE3E3"))
        p.drawRoundedRect(QRectF(sx - 20, sy - 14, 40, 28), 8, 8)
        p.setPen(QColor("#C92A2A"))
        p.drawText(QRectF(sx - 20, sy - 14, 40, 28), "入口", QTextOption(Qt.AlignmentFlag.AlignCenter))

        ex, ey = self.path_pts[-1]
        p.setPen(QPen(QColor("#FF6B6B" if self._pet_hurt_t > 0 else "#FFD43B"), 2.4))
        p.setBrush(QColor("#FFE3E3" if self._pet_hurt_t > 0 else "#FFF9DB"))
        p.drawEllipse(QPointF(ex, ey), 26, 20)
        p.save()
        p.translate(ex, ey + 6)
        p.scale(0.46, 0.46)
        p.translate(-TypingPet.W / 2, -TypingPet.EDGE)
        self.pet._paint_pet(p, now, "happy" if self.victory else "idle")
        p.restore()

        # 选中炮塔射程圈
        if self.selected_tile is not None and self.selected_tile in self.towers:
            tw = self.towers[self.selected_tile]
            rng = TD_TOWER_BY_ID[tw["id"]]["rng"][tw["lv"] - 1]
            p.setPen(QPen(QColor(255, 255, 255, 190), 1.6, Qt.PenStyle.DashLine))
            p.setBrush(QColor(116, 192, 252, 34))
            p.drawEllipse(QPointF(tw["x"], tw["y"]), rng, rng)

        # 障碍物、炮塔、怪物、子弹
        for ob in self.obstacles.values():
            self._paint_obstacle(p, ob)
        for tw in self.towers.values():
            self._paint_tower(p, tw)
        for en in self.enemies:
            self._paint_enemy(p, en, now)

        # 集火准星 🎯
        if self.focus_target is not None and self.focus_target["hp"] > 0:
            fx, fy = self.focus_target["x"], self.focus_target["y"]
            rad = 18.0 + 3.0 * math.sin(now * 10.0)
            p.setPen(QPen(QColor("#FA5252"), 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(fx, fy), rad, rad)
            p.drawLine(QPointF(fx - rad - 5, fy), QPointF(fx + rad + 5, fy))
            p.drawLine(QPointF(fx, fy - rad - 5), QPointF(fx, fy + rad + 5))

        for b in self.bullets:
            p.setPen(QPen(QColor("#FFFFFF"), 1.2))
            p.setBrush(QColor(b["col"]))
            p.drawEllipse(QPointF(b["x"], b["y"]), 5.5, 5.5)

        # 特效
        for f in self.fx:
            alpha = max(0.0, min(1.0, f["life"] * 2.0))
            p.save()
            p.setOpacity(alpha)
            if f["type"] == "ring":
                p.setPen(QPen(QColor(f["col"]), 2.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(f["x"], f["y"]), f["r"], f["r"])
            elif f["type"] == "bolt":
                p.setPen(QPen(QColor("#E5DBFF"), 3.0))
                pts = f["pts"]
                for i in range(len(pts) - 1):
                    p.drawLine(QPointF(*pts[i]), QPointF(*pts[i + 1]))
            elif f["type"] == "text":
                tf = QFont(self.font())
                tf.setPixelSize(13)
                tf.setWeight(QFont.Weight.Black)
                p.setFont(tf)
                r = QRectF(f["x"] - 95, f["y"] - 12, 190, 24)
                p.setPen(QColor(OUTLINE))
                p.drawText(r.translated(0, 1.1), f["t"], QTextOption(Qt.AlignmentFlag.AlignCenter))
                p.setPen(QColor(f["col"]))
                p.drawText(r, f["t"], QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.restore()

        if self.freeze_left > 0:
            p.setPen(QPen(QColor("#74C0FC"), 4.0))
            p.setBrush(QColor(116, 192, 252, 28))
            p.drawRoundedRect(QRectF(2, HUD_H + 2, self.W - 4, self.H - HUD_H - 4), 14, 14)

        if self.paused or self.game_over or self.victory:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(14, 18, 30, 165))
            p.drawRoundedRect(QRectF(0, HUD_H, self.W, self.H - HUD_H), 14, 14)
            bf = QFont(self.font())
            bf.setPixelSize(24)
            bf.setWeight(QFont.Weight.Black)
            p.setFont(bf)
            p.setPen(QColor("#FFD43B" if self.victory else "#FFFFFF"))
            if self.victory:
                medal = "🥕🏆 金萝卜完美通关!" if self.hearts >= self.max_hearts else "🥈 银萝卜防守成功!"
                sub = f"得分 {self.score:,} · 击退 {self.kills} 只捣蛋怪 · 点下方「挑战无尽」继续冲榜!"
            elif self.game_over:
                medal = "💔 防线失守啦!"
                sub = f"坚持到第 {self.wave} 波 · 最终得分 {self.score:,}"
            else:
                medal = "⏸ 已暂停布阵"
                sub = "点击「继续」恢复战斗"
            p.drawText(QRectF(0, self.H * 0.38, self.W, 38), medal, QTextOption(Qt.AlignmentFlag.AlignCenter))
            bf.setPixelSize(14)
            p.setFont(bf)
            p.setPen(QColor("#F8F9FA"))
            p.drawText(QRectF(0, self.H * 0.50, self.W, 28), sub, QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class PetTDDialog(Dialog):
    """《🥕 萌宠保卫战》保卫萝卜风 2.5D 塔防窗口。"""

    def __init__(self, win) -> None:
        super().__init__(win, "萌宠保卫战")
        self.win = win
        self.g: PetGrowth = win.pet_growth
        self._settled = False
        self.setFixedWidth(_TDStage.W + 36)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 14)
        lay.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(label("🥕 萌宠保卫战 (保卫萝卜风)", "dialogTitle"))
        top.addStretch(1)
        self.map_btns: list[QPushButton] = []
        for idx, mp in enumerate(TD_MAPS):
            b = QPushButton(mp["name"], self)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setChecked(idx == 0)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=idx: self._switch_map(i))
            top.addWidget(b)
            self.map_btns.append(b)
        lay.addLayout(top)

        self.stage = _TDStage(self, self.g, win.fun.get("pet") or "cat", win=win)
        self.stage.state_changed.connect(self._sync_ui)
        self.stage.finished.connect(self._on_finish)
        lay.addWidget(self.stage, 0, Qt.AlignmentFlag.AlignHCenter)

        # 炮塔选择栏
        dock = QHBoxLayout()
        dock.setSpacing(6)
        self.tower_btns: dict[str, QPushButton] = {}
        card_qss = (
            "QPushButton { padding: 4px 4px; border-radius: 10px; font-size: 11px; font-weight: 600; }"
            "QPushButton:checked { border: 2px solid #FF922B; }"
        )
        for tw in TD_TOWERS:
            b = QPushButton(f"{tw['ico']} {tw['name']}\n💰{tw['cost']}", self)
            b.setCheckable(True)
            b.setChecked(tw["id"] == "cat")
            b.setFixedHeight(44)
            b.setStyleSheet(card_qss)
            b.setToolTip(f"{tw['name']}（{tw['cost']}金币）：{tw['desc']}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, tid=tw["id"]: self._pick_tower(tid))
            dock.addWidget(b, 1)
            self.tower_btns[tw["id"]] = b
        lay.addLayout(dock)

        # 操作 & 技能栏
        ctrl = QHBoxLayout()
        ctrl.setSpacing(5)
        self.up_btn = button("⬆️ 升级", "primary", self.stage.upgrade_selected, 108)
        self.sell_btn = button("💰 出售", "", self.stage.sell_selected, 90)
        self.freeze_btn = button("❄️ 冰冻", "", self.stage.cast_freeze, 82)
        self.rage_btn = button("⚡ 狂暴", "", self.stage.cast_rage, 78)
        self.spd_btn = button("⏩ 1×", "", self.stage.toggle_speed, 54)
        self.pause_btn = button("⏸ 暂停", "", self.stage.toggle_pause, 62)
        self.endless_btn = button("♾ 无尽", "primary", self._go_endless, 76)
        self.endless_btn.setVisible(False)
        for b in (self.up_btn, self.sell_btn, self.freeze_btn, self.rage_btn, self.spd_btn, self.pause_btn, self.endless_btn):
            ctrl.addWidget(b)
        ctrl.addStretch(1)
        lay.addLayout(ctrl)

        self.info_lab = label(
            f"点空地建塔、点塔升级/出售、点怪或宝箱打 🎯集火！历史最高:{self.g.td_best:,} 分 ({self.g.td_waves} 波)",
            "faint", wrap=True,
        )
        lay.addWidget(self.info_lab)

        foot = QHBoxLayout()
        foot.setSpacing(6)
        foot.addWidget(button("🔄 重开闯关", "", lambda: self._restart(False), 94))
        foot.addWidget(button("♾ 无尽模式", "", lambda: self._restart(True), 94))
        foot.addWidget(button("📤 晒战绩", "", self._share, 90))
        foot.addWidget(button("🏆 排行榜", "", lambda: (self._settle_if_needed(), self.win.open_pet_rank()), 86))
        foot.addStretch(1)
        foot.addWidget(button("关闭", "primary", self.accept, 74))
        lay.addLayout(foot)
        self._sync_ui()

    def _switch_map(self, idx: int) -> None:
        self._settle_if_needed()
        self._settled = False
        for i, b in enumerate(self.map_btns):
            b.setChecked(i == idx)
        self.stage.load_map(idx, endless=self.stage.endless)

    def _pick_tower(self, tid: str) -> None:
        self.stage.armed_tower = tid
        for k, b in self.tower_btns.items():
            b.setChecked(k == tid)
        if self.stage.selected_tile is not None and self.stage.selected_tile not in self.stage.towers:
            self.stage.build_at(self.stage.selected_tile, tid)

    def _go_endless(self) -> None:
        self._settle_if_needed()
        self._settled = False
        self.stage.continue_endless()

    def _restart(self, endless: bool) -> None:
        self._settle_if_needed()
        self._settled = False
        self.stage.load_map(self.stage.map_idx, endless=endless)

    def _sync_ui(self) -> None:
        st = self.stage
        self.spd_btn.setText(f"⏩ {st.speed_mul}×")
        self.pause_btn.setText("▶️ 继续" if st.paused else "⏸ 暂停")
        self.endless_btn.setVisible(st.victory and not st.endless)
        self.freeze_btn.setEnabled(st.running and not st.paused and st.freeze_cd <= 0)
        self.freeze_btn.setText(f"❄️ {int(st.freeze_cd)}s" if st.freeze_cd > 0 else "❄️ 全局冰冻")
        self.rage_btn.setEnabled(st.running and not st.paused and st.rage_cd <= 0)
        self.rage_btn.setText(f"⚡ {int(st.rage_cd)}s" if st.rage_cd > 0 else "⚡ 狂暴2×")

        sel = st.selected_tile
        if sel is not None and sel in st.towers:
            tw = st.towers[sel]
            spec = TD_TOWER_BY_ID[tw["id"]]
            if tw["lv"] < 3:
                uc = spec["up"][tw["lv"] - 1]
                self.up_btn.setText(f"⬆️ 升Lv.{tw['lv'] + 1}(💰{uc})")
                self.up_btn.setEnabled(st.gold >= uc)
            else:
                self.up_btn.setText("⭐ 已满级")
                self.up_btn.setEnabled(False)
            self.sell_btn.setText(f"💰 出售(+{int(tw['spent'] * 0.75)})")
            self.sell_btn.setEnabled(True)
        else:
            self.up_btn.setText("⬆️ 升级")
            self.up_btn.setEnabled(False)
            self.sell_btn.setText("💰 出售")
            self.sell_btn.setEnabled(False)

    def _on_finish(self, win_flag: bool, score: int, waves: int) -> None:
        self._settle_if_needed(score, waves)
        self._sync_ui()

    def _settle_if_needed(self, score: int | None = None, waves: int | None = None) -> None:
        sc = self.stage.score if score is None else score
        wv = self.stage.wave if waves is None else waves
        if self._settled or sc <= 0:
            return
        self._settled = True
        gain, ups = self.g.record_td_score(sc, wv)
        first = self.g.claim_daily_game_bonus()
        extra = " · 🌟今日首胜+30通行证分!" if first else ""
        self.info_lab.setText(f"🎉 结算：得分 {sc:,}（第 {wv} 波），+{gain} 经验与通行证积分！"
                              + (f"（升 {ups} 级!）" if ups > 0 else "") + extra)
        if ups > 0 and hasattr(self.win, "_pet_level_up"):
            self.win._pet_level_up()
        if hasattr(self.win, "pr_broadcast"):
            self.win.pr_broadcast()

    def _share(self) -> None:
        sc = max(self.stage.score, self.g.td_best)
        wv = max(self.stage.wave, self.g.td_waves)
        medal = "金萝卜通关" if self.stage.victory and self.stage.hearts >= self.stage.max_hearts else f"守至第 {wv} 波"
        if hasattr(self.win, "share_game_score") and self.win.share_game_score("td", sc, medal):
            self.info_lab.setText("📤 「萌宠保卫战」战绩挑战卡已发送到当前聊天！")

    def closeEvent(self, e) -> None:
        self.stage.stop()
        self._settle_if_needed()
        super().closeEvent(e)

    def accept(self) -> None:
        self.stage.stop()
        self._settle_if_needed()
        super().accept()

    def reject(self) -> None:
        self.stage.stop()
        self._settle_if_needed()
        super().reject()
