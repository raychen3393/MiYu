"""
密语 3.8 · 《🌻 萌宠大战捣蛋怪》2.5D 植物大战僵尸式 5 路草坪塔防小游戏
  · 经典 5 行 × 9 列 2.5D 黏土阳光草坪 + 左侧 5 台自动 🚜 萌宠小推车兜底救场
  · 飘落/向日水豚产出 ☀️ 阳光（点击或鼠标划过自动丝滑收取）
  · 6 种 2.5D 萌宠防线单位（向日水豚 / 豌豆小猫 / 寒冰企鹅 / 坚果大熊 / 爆爆樱桃狐 / 双发柴犬）+ 🧹铲子
  · 4 种捣蛋怪（普通怪 / 铁桶护甲怪 / 撑杆跳越过首格快怪 / 巨型大魔王 Boss）
  · 支持 1x/2x 倍速、暂停、10 波闯关 & 无尽冲榜，结算联动宠物经验、通行证与局域网排行榜
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .dialogs import Dialog
from .fun import OUTLINE, PetGrowth
from .pet3d import clay_brush, contour_pen
from .sound import play_game_sfx
from .theme import is_dark
from .ui import button, label

LANES, COLS = 5, 9
MOWER_W = 54
CELL_W, CELL_H = 70, 68
HUD_H = 38

PVZ_PLANTS: list[dict] = [
    {"id": "sun", "ico": "🍊", "name": "向日水豚", "cost": 50, "cd": 4.5, "hp": 120, "col": "#FFD43B", "desc": "定时吐阳光"},
    {"id": "pea", "ico": "🐱", "name": "豌豆小猫", "cost": 100, "cd": 4.5, "hp": 140, "col": "#8CE99A", "desc": "直线发射豆豆"},
    {"id": "ice", "ico": "🐧", "name": "寒冰企鹅", "cost": 150, "cd": 5.5, "hp": 140, "col": "#74C0FC", "desc": "冰豆减速整路"},
    {"id": "nut", "ico": "🐻", "name": "坚果大熊", "cost": 50, "cd": 10.0, "hp": 520, "col": "#D99B66", "desc": "高血量挡怪"},
    {"id": "shiba", "ico": "🐕", "name": "双发柴犬", "cost": 175, "cd": 6.0, "hp": 150, "col": "#FFB3C6", "desc": "每次连发两弹"},
    {"id": "bomb", "ico": "🦊", "name": "爆爆樱桃狐", "cost": 150, "cd": 13.0, "hp": 200, "col": "#FF6B6B", "desc": "3×3秒杀清场"},
]
PVZ_BY_ID = {p["id"]: p for p in PVZ_PLANTS}


def _cell_center(col: int, lane: int) -> tuple[float, float]:
    return MOWER_W + col * CELL_W + CELL_W * 0.5, HUD_H + lane * CELL_H + CELL_H * 0.5


def _build_pvz_wave(wave: int) -> list[dict]:
    scale = 1.0 + (wave - 1) * 0.24 + (max(0, wave - 10) ** 1.35) * 0.24
    cnt = 4 + wave * 2
    out: list[dict] = []
    for i in range(cnt):
        if wave >= 4 and i % 5 == 4:
            kind, hp, spd, pts = "vaulter", int(145 * scale), 35.0, 45
        elif wave >= 2 and i % 3 == 2:
            kind, hp, spd, pts = "bucket", int(240 * scale), 18.5, 40
        else:
            kind, hp, spd, pts = "normal", int(105 * scale), 20.0, 25
        out.append({"kind": kind, "hp": hp, "max_hp": hp, "spd": spd, "pts": pts,
                    "vaulted": False, "lane": random.randrange(LANES)})
    if wave % 5 == 0:
        bhp = int(680 * scale)
        out.append({"kind": "boss", "hp": bhp, "max_hp": bhp, "spd": 15.0, "pts": 260,
                    "vaulted": True, "lane": random.randrange(LANES)})
    return out


class _PvZStage(QWidget):
    """植物大战僵尸风 2.5D 5 路草坪塔防画布。"""
    state_changed = Signal()
    finished = Signal(bool, int, int)       # (是否通关, 分数, 波次)

    W = MOWER_W + COLS * CELL_W
    H = HUD_H + LANES * CELL_H

    def __init__(self, parent, win=None) -> None:
        super().__init__(parent)
        self.win = win
        self.setFixedSize(self.W, self.H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.endless = False
        self.selected_card: str | None = "sun"
        self.shovel_mode = False
        self.speed_mul = 1
        self.paused = False
        self.running = False
        self.game_over = False
        self.victory = False

        self.sun = 150
        self.score = 0
        self.wave = 0
        self.max_waves = 10
        self.kills = 0
        self.card_cds: dict[str, float] = {p["id"]: 0.0 for p in PVZ_PLANTS}
        self.plants: dict[tuple[int, int], dict] = {}   # (col, lane) -> plant
        self.zombies: list[dict] = []
        self.bullets: list[dict] = []
        self.suns: list[dict] = []
        self.mowers: list[dict] = []
        self.fx: list[dict] = []
        self._spawn_q: list[dict] = []
        self._spawn_cd = 0.0
        self._wave_gap = 2.8
        self._sky_sun_cd = 4.5
        self._hover_cell: tuple[int, int] | None = None

        self._last_t = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._step)
        self.reset(endless=False)

    def reset(self, endless: bool = False) -> None:
        self.endless = endless
        self.sun = 150
        self.score = 0
        self.wave = 0
        self.kills = 0
        self.card_cds = {p["id"]: 0.0 for p in PVZ_PLANTS}
        self.plants.clear()
        self.zombies.clear()
        self.bullets.clear()
        self.suns.clear()
        self.fx.clear()
        self._spawn_q.clear()
        self.mowers = [
            {"lane": r, "x": MOWER_W * 0.5, "y": HUD_H + r * CELL_H + CELL_H * 0.5, "active": False, "used": False}
            for r in range(LANES)
        ]
        self._spawn_cd = 0.0
        self._wave_gap = 2.6
        self._sky_sun_cd = 3.5
        self.shovel_mode = False
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

    def continue_endless(self) -> None:
        self.endless = True
        self.victory = False
        self.running = True
        self._wave_gap = 2.2
        self._last_t = time.monotonic()
        self._timer.start()
        self.state_changed.emit()
        self.update()

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

    def _cell_at(self, px: float, py: float) -> tuple[int, int] | None:
        if px < MOWER_W or py < HUD_H:
            return None
        c = int((px - MOWER_W) // CELL_W)
        r = int((py - HUD_H) // CELL_H)
        if 0 <= c < COLS and 0 <= r < LANES:
            return (c, r)
        return None

    def _collect_suns_near(self, px: float, py: float, radius: float = 34.0) -> bool:
        hit = False
        for s in self.suns:
            if not s["fly"] and math.hypot(px - s["x"], py - s["y"]) <= radius:
                s["fly"] = True
                self.sun += s["val"]
                self.fx.append({"type": "text", "x": s["x"], "y": s["y"] - 8, "t": f"+{s['val']}☀️", "col": "#FFD43B", "life": 0.75})
                play_game_sfx(self.win, "coin", 0.65)
                hit = True
        if hit:
            self.state_changed.emit()
        return hit

    def plant_at(self, col: int, lane: int, pid: str) -> bool:
        if not self.running or self.game_over or self.victory:
            return False
        if not (0 <= col < COLS and 0 <= lane < LANES) or (col, lane) in self.plants:
            return False
        spec = PVZ_BY_ID.get(pid)
        if spec is None or self.sun < spec["cost"] or self.card_cds.get(pid, 0.0) > 0:
            play_game_sfx(self.win, "hurt", 0.45)
            return False
        self.sun -= spec["cost"]
        self.card_cds[pid] = spec["cd"]
        x, y = _cell_center(col, lane)
        self.plants[(col, lane)] = {
            "id": pid, "col": col, "lane": lane, "x": x, "y": y,
            "hp": spec["hp"], "max_hp": spec["hp"],
            "cd": 0.45 if pid == "bomb" else (3.0 if pid == "sun" else 0.75),
            "recoil": 0.0,
        }
        self.fx.append({"type": "ring", "x": x, "y": y, "r": 10.0, "max_r": 32.0, "col": spec["col"], "life": 0.30})
        play_game_sfx(self.win, "build", 0.72)
        self.state_changed.emit()
        self.update()
        return True

    def mouseMoveEvent(self, e) -> None:
        px, py = float(e.position().x()), float(e.position().y())
        self._hover_cell = self._cell_at(px, py)
        if self.running and not self.paused:
            self._collect_suns_near(px, py, radius=28.0)
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self.running or self.game_over or self.victory:
            return
        px, py = float(e.position().x()), float(e.position().y())
        if self._collect_suns_near(px, py, radius=38.0):
            return
        cell = self._cell_at(px, py)
        if cell is None:
            return
        if self.shovel_mode:
            if cell in self.plants:
                pl = self.plants.pop(cell)
                self.fx.append({"type": "text", "x": pl["x"], "y": pl["y"] - 10, "t": "🧹 已铲除", "col": "#ADB5BD", "life": 0.7})
                self.shovel_mode = False
                play_game_sfx(self.win, "pop", 0.65)
                self.state_changed.emit()
                self.update()
            return
        if self.selected_card:
            self.plant_at(cell[0], cell[1], self.selected_card)

    def _start_wave(self) -> None:
        self.wave += 1
        self._spawn_q = _build_pvz_wave(self.wave)
        self._spawn_cd = 0.6
        self.fx.append({"type": "text", "x": self.W * 0.5, "y": HUD_H + 34,
                        "t": f"🧟 第 {self.wave} 波捣蛋怪逼近!" + (" 🚩大波警报!" if self.wave % 5 == 0 else ""),
                        "col": "#FF6B6B" if self.wave % 5 == 0 else "#FFFFFF", "life": 1.6})
        self.state_changed.emit()

    def _step(self) -> None:
        now = time.monotonic()
        raw_dt = min(0.05, max(0.005, now - self._last_t))
        self._last_t = now
        if not self.running or self.paused:
            return
        dt = raw_dt * self.speed_mul

        for k in self.card_cds:
            if self.card_cds[k] > 0:
                self.card_cds[k] = max(0.0, self.card_cds[k] - dt)

        # 1) 天降阳光
        self._sky_sun_cd -= dt
        if self._sky_sun_cd <= 0:
            self._sky_sun_cd = random.uniform(6.2, 8.2)
            self.suns.append({
                "x": random.uniform(MOWER_W + 40, self.W - 40), "y": HUD_H + 6.0,
                "target_y": random.uniform(HUD_H + 75, self.H - 40),
                "vy": 52.0, "val": 25, "life": 11.0, "fly": False,
            })

        # 2) 波次刷怪
        if self._spawn_q:
            self._spawn_cd -= dt
            if self._spawn_cd <= 0:
                self._spawn_cd = max(0.95, 2.2 - self.wave * 0.11)
                spec = self._spawn_q.pop(0)
                lane = spec["lane"]
                self.zombies.append({
                    **spec, "x": self.W + 16.0, "y": HUD_H + lane * CELL_H + CELL_H * 0.5,
                    "slow_t": 0.0, "eat_cd": 0.0, "wob": random.uniform(0, 6.28), "vault_t": 0.0,
                })
        elif not self.zombies:
            if not self.endless and self.wave >= self.max_waves:
                self.victory = True
                self.running = False
                self._timer.stop()
                unused_mowers = sum(1 for m in self.mowers if not m["used"])
                self.score += unused_mowers * 150 + self.sun
                play_game_sfx(self.win, "win", 0.85)
                self.state_changed.emit()
                self.finished.emit(True, self.score, self.wave)
                self.update()
                return
            self._wave_gap -= dt
            if self._wave_gap <= 0:
                self._wave_gap = 3.2
                self._start_wave()

        # 3) 萌宠防线行动
        dead_plants = []
        for key, pl in list(self.plants.items()):
            pl["recoil"] = max(0.0, pl["recoil"] - dt * 5.0)
            if pl["hp"] <= 0:
                dead_plants.append(key)
                continue
            pl["cd"] -= dt
            if pl["id"] == "sun":
                if pl["cd"] <= 0:
                    pl["cd"] = 7.4
                    pl["recoil"] = 1.0
                    self.suns.append({
                        "x": pl["x"] + random.uniform(-14, 14), "y": pl["y"] - 14,
                        "target_y": pl["y"] + 10, "vy": 38.0, "val": 25, "life": 11.0, "fly": False,
                    })
                    play_game_sfx(self.win, "pop", 0.45)
            elif pl["id"] == "bomb":
                if pl["cd"] <= 0:
                    dead_plants.append(key)
                    self.fx.append({"type": "ring", "x": pl["x"], "y": pl["y"], "r": 14.0, "max_r": 118.0, "col": "#FF6B6B", "life": 0.45})
                    self.fx.append({"type": "text", "x": pl["x"], "y": pl["y"] - 14, "t": "💥 樱桃核爆!", "col": "#FFD43B", "life": 1.0})
                    for z in self.zombies:
                        if abs(z["lane"] - pl["lane"]) <= 1 and abs(z["x"] - pl["x"]) <= CELL_W * 1.65:
                            z["hp"] -= 520
                    play_game_sfx(self.win, "boom", 0.9)
            elif pl["id"] in ("pea", "ice", "shiba"):
                has_z = any(z["lane"] == pl["lane"] and z["x"] > pl["x"] - 8 and z["hp"] > 0 for z in self.zombies)
                if has_z and pl["cd"] <= 0:
                    pl["recoil"] = 1.0
                    if pl["id"] == "pea":
                        pl["cd"] = 1.25
                        self.bullets.append({"x": pl["x"] + 16, "y": pl["y"] - 4, "lane": pl["lane"],
                                             "dmg": 26, "ice": False, "col": "#51CF66", "spd": 320.0})
                    elif pl["id"] == "ice":
                        pl["cd"] = 1.35
                        self.bullets.append({"x": pl["x"] + 16, "y": pl["y"] - 4, "lane": pl["lane"],
                                             "dmg": 22, "ice": True, "col": "#74C0FC", "spd": 310.0})
                    else:
                        pl["cd"] = 1.20
                        for dx_o in (12.0, 26.0):
                            self.bullets.append({"x": pl["x"] + dx_o, "y": pl["y"] - 4, "lane": pl["lane"],
                                                 "dmg": 25, "ice": False, "col": "#FFD43B", "spd": 350.0})
                    play_game_sfx(self.win, "freeze" if pl["id"] == "ice" else "shoot", 0.45)
        for key in dead_plants:
            self.plants.pop(key, None)

        # 4) 子弹飞行与命中
        kept_b = []
        for b in self.bullets:
            b["x"] += b["spd"] * dt
            if b["x"] > self.W + 20:
                continue
            hit = None
            for z in self.zombies:
                if z["lane"] == b["lane"] and z["hp"] > 0 and abs(z["x"] - b["x"]) <= 18:
                    hit = z
                    break
            if hit is not None:
                hit["hp"] -= b["dmg"]
                if b["ice"]:
                    hit["slow_t"] = 3.5
                self.fx.append({"type": "ring", "x": b["x"], "y": b["y"], "r": 4.0, "max_r": 16.0, "col": b["col"], "life": 0.18})
                continue
            kept_b.append(b)
        self.bullets = kept_b

        # 5) 捣蛋怪前进、撑杆跳、啃咬与触发小推车
        for z in self.zombies:
            if z["hp"] <= 0:
                continue
            if z["slow_t"] > 0:
                z["slow_t"] = max(0.0, z["slow_t"] - dt)
            if z["vault_t"] > 0:
                z["vault_t"] = max(0.0, z["vault_t"] - dt)
                z["x"] -= 145.0 * dt
                continue
            # 检查当前格是否有萌宠阻挡
            col = int((z["x"] - MOWER_W) // CELL_W)
            blocker = self.plants.get((col, z["lane"]))
            if blocker is not None and abs(z["x"] - blocker["x"]) <= 28:
                if z["kind"] == "vaulter" and not z["vaulted"]:
                    z["vaulted"] = True
                    z["vault_t"] = 0.48
                    z["spd"] = 21.0
                    self.fx.append({"type": "text", "x": z["x"], "y": z["y"] - 22, "t": "🤸 撑杆越过!", "col": "#FFD43B", "life": 0.85})
                    play_game_sfx(self.win, "jump", 0.7)
                    continue
                z["eat_cd"] -= dt
                if z["eat_cd"] <= 0:
                    z["eat_cd"] = 0.55
                    blocker["hp"] -= 26 if z["kind"] != "boss" else 60
                    play_game_sfx(self.win, "hurt", 0.35)
                    if blocker["hp"] <= 0:
                        self.plants.pop((col, z["lane"]), None)
            else:
                spd = z["spd"] * (0.55 if z["slow_t"] > 0 else 1.0)
                z["x"] -= spd * dt
            # 触碰左侧防线 → 启动该路自动小推车或失败
            if z["x"] <= MOWER_W + 6:
                mw = self.mowers[z["lane"]]
                if not mw["used"] and not mw["active"]:
                    mw["active"] = True
                    self.fx.append({"type": "text", "x": MOWER_W + 65, "y": mw["y"] - 14, "t": "🚜 小推车出动!", "col": "#FFD43B", "life": 1.1})
                    play_game_sfx(self.win, "boom", 0.85)
                elif mw["used"]:
                    self.game_over = True
                    self.running = False
                    self._timer.stop()
                    play_game_sfx(self.win, "lose", 0.8)
                    self.finished.emit(False, self.score, max(0, self.wave - 1))
                    self.update()
                    return

        # 6) 自动小推车横扫整路
        for mw in self.mowers:
            if not mw["active"]:
                continue
            mw["x"] += 420.0 * dt
            for z in self.zombies:
                if z["lane"] == mw["lane"] and z["hp"] > 0 and abs(z["x"] - mw["x"]) <= 34:
                    z["hp"] = 0
            if mw["x"] > self.W + 30:
                mw["active"] = False
                mw["used"] = True

        # 7) 清理击杀的捣蛋怪计分
        kept_z = []
        for z in self.zombies:
            if z["hp"] <= 0:
                self.kills += 1
                self.score += z["pts"]
                self.fx.append({"type": "text", "x": z["x"], "y": z["y"] - 10, "t": f"+{z['pts']}", "col": "#FFD43B", "life": 0.7})
                continue
            kept_z.append(z)
        self.zombies = kept_z

        # 8) 阳光飘落与飞向顶部槽
        kept_s = []
        for s in self.suns:
            if s["fly"]:
                dx, dy = 96.0 - s["x"], 18.0 - s["y"]
                d = math.hypot(dx, dy)
                if d < 18:
                    continue
                s["x"] += dx / d * 540.0 * raw_dt
                s["y"] += dy / d * 540.0 * raw_dt
                kept_s.append(s)
            else:
                s["life"] -= dt
                if s["life"] <= 0:
                    continue
                if s["y"] < s["target_y"]:
                    s["y"] = min(s["target_y"], s["y"] + s["vy"] * dt)
                kept_s.append(s)
        self.suns = kept_s

        # 9) 特效步进
        nxt_fx = []
        for f in self.fx:
            f["life"] -= raw_dt
            if f["life"] <= 0:
                continue
            if f["type"] == "text":
                f["y"] -= 24.0 * raw_dt
            elif f["type"] == "ring":
                f["r"] += (f["max_r"] - f["r"]) * min(1.0, raw_dt * 12.0)
            nxt_fx.append(f)
        self.fx = nxt_fx
        self.state_changed.emit()
        self.update()

    def _paint_plant(self, p: QPainter, pl: dict, now: float) -> None:
        spec = PVZ_BY_ID[pl["id"]]
        x, y = pl["x"], pl["y"]
        col = QColor(spec["col"])
        bob = math.sin(now * 4.5 + pl["col"]) * 2.0
        p.save()
        p.translate(x, y + bob)
        sc = 1.0 + pl["recoil"] * 0.14
        p.scale(sc, sc)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 38))
        p.drawEllipse(QPointF(0, 18), 20, 7)

        if pl["id"] == "nut":                           # 坚果大熊(3档表情)
            ratio = pl["hp"] / max(1, pl["max_hp"])
            p.setPen(contour_pen(col, 1.8))
            p.setBrush(clay_brush(0, 0, 20, 22, col))
            p.drawEllipse(QPointF(0, 0), 20, 21)
            for s in (-1, 1):
                p.drawEllipse(QPointF(s * 14, -15), 6, 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#232026"))
            for s in (-1, 1):
                p.drawEllipse(QPointF(s * 6, -4), 2.5, 2.5)
            p.setPen(QPen(QColor("#232026"), 1.6))
            if ratio > 0.55:
                p.drawArc(QRectF(-6, 0, 12, 8), 200 * 16, 140 * 16)
            elif ratio > 0.25:
                p.drawLine(QPointF(-5, 5), QPointF(5, 5))
            else:
                p.drawLine(QPointF(-6, 7), QPointF(6, 3))
                p.setBrush(QColor("#74C0FC"))
                p.drawEllipse(QPointF(12, -10), 2.5, 4.0)
        else:
            p.setPen(contour_pen(col, 1.5))
            p.setBrush(clay_brush(0, 0, 18, 16, col))
            p.drawEllipse(QPointF(0, 0), 17.5, 16)
            if pl["id"] == "sun":
                p.setBrush(QColor("#FF922B"))
                p.drawEllipse(QPointF(0, -16), 6.5, 5.0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#51CF66"))
                p.drawEllipse(QPointF(3, -21), 4, 2)
            elif pl["id"] in ("pea", "shiba", "bomb"):
                for s in (-1, 1):
                    ear = QPainterPath(QPointF(s * 10, -10))
                    ear.lineTo(s * 15, -21)
                    ear.lineTo(s * 3, -15)
                    ear.closeSubpath()
                    p.drawPath(ear)
            elif pl["id"] == "ice":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#FFFFFF"))
                p.drawEllipse(QPointF(0, 2), 11, 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#232026"))
            for s in (-1, 1):
                p.drawEllipse(QPointF(s * 5.5, -2), 2.2, 2.5)
            # 嘴巴/炮口
            if pl["id"] in ("pea", "ice", "shiba"):
                p.setBrush(col.darker(118))
                p.drawEllipse(QPointF(14, 1), 6, 4.5)
        if pl["hp"] < pl["max_hp"]:
            r = max(0.0, pl["hp"] / pl["max_hp"])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 110))
            p.drawRoundedRect(QRectF(-16, -24, 32, 4), 2, 2)
            p.setBrush(QColor("#51CF66") if r > 0.4 else QColor("#FF6B6B"))
            p.drawRoundedRect(QRectF(-16, -24, 32 * r, 4), 2, 2)
        p.restore()

    def _paint_zombie(self, p: QPainter, z: dict, now: float) -> None:
        x, y, kind = z["x"], z["y"], z["kind"]
        r = 22.0 if kind == "boss" else 16.5
        jump_y = -24.0 * math.sin(min(1.0, z["vault_t"] / 0.48) * math.pi) if z["vault_t"] > 0 else 0.0
        bob = math.sin(now * 6.5 + z["wob"]) * 2.5 + jump_y
        p.save()
        p.translate(x, y + bob)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 42))
        p.drawEllipse(QPointF(0, r + 2 - jump_y), r * 0.9, 6.5)

        col = QColor("#74C0FC") if z["slow_t"] > 0 else {
            "normal": QColor("#9775FA"),
            "bucket": QColor("#845EF7"),
            "vaulter": QColor("#FF922B"),
            "boss": QColor("#FA5252"),
        }[kind]
        p.setPen(contour_pen(col, 1.6))
        p.setBrush(clay_brush(0, 0, r, r, col))
        p.drawEllipse(QPointF(0, 0), r, r * 1.04)
        # 铁桶头盔(半血以上保留)
        if kind == "bucket" and z["hp"] > z["max_hp"] * 0.45:
            p.setPen(contour_pen(QColor("#868E96"), 1.3))
            p.setBrush(clay_brush(0, -14, 13, 9, QColor("#CED4DA")))
            p.drawRoundedRect(QRectF(-12, -23, 24, 15), 4, 4)
        elif kind == "vaulter" and not z["vaulted"]:
            p.setPen(QPen(QColor("#FFE066"), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(-20, 6), QPointF(16, -16))
        elif kind == "boss":
            p.setBrush(QColor("#FFD43B"))
            p.drawPolygon([QPointF(-11, -r + 2), QPointF(-13, -r - 10), QPointF(-4, -r - 4),
                           QPointF(0, -r - 13), QPointF(4, -r - 4), QPointF(13, -r - 10), QPointF(11, -r + 2)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#232026"))
        for s in (-1, 1):
            p.drawEllipse(QPointF(-3 + s * 5.2, -3), 2.4, 2.5)
        ratio = max(0.0, z["hp"] / max(1, z["max_hp"]))
        bw = r * 2.1
        p.setBrush(QColor(0, 0, 0, 115))
        p.drawRoundedRect(QRectF(-bw / 2, -r - 10, bw, 4.5), 2, 2)
        p.setBrush(QColor("#51CF66") if ratio > 0.45 else QColor("#FF6B6B"))
        p.drawRoundedRect(QRectF(-bw / 2, -r - 10, bw * ratio, 4.5), 2, 2)
        p.restore()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        now = time.monotonic()
        dark = is_dark()

        # 顶栏与底板
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1B2A20" if dark else "#8CE99A"))
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), 16, 16)

        # 顶部 HUD
        p.setBrush(QColor(20, 24, 34, 220) if dark else QColor(255, 255, 255, 232))
        p.drawRoundedRect(QRectF(0, 0, self.W, HUD_H), 14, 14)
        hf = QFont(self.font())
        hf.setPixelSize(12)
        hf.setWeight(QFont.Weight.Bold)
        p.setFont(hf)
        p.setPen(QColor("#F59F00"))
        p.drawText(QRectF(14, 0, 120, HUD_H), f"☀️ 阳光 {self.sun}", QTextOption(Qt.AlignmentFlag.AlignVCenter))
        p.setPen(QColor("#FFFFFF" if dark else "#1D1D1F"))
        w_txt = f"🧟 第 {self.wave} 波 (无尽)" if self.endless else f"🚩 波次 {self.wave}/{self.max_waves}"
        p.drawText(QRectF(145, 0, 165, HUD_H), w_txt, QTextOption(Qt.AlignmentFlag.AlignVCenter))
        # 迷你波次进度条
        prog = min(1.0, self.wave / max(1, self.max_waves)) if not self.endless else (self.wave % 10) / 10.0
        p.setBrush(QColor(128, 128, 128, 60))
        p.drawRoundedRect(QRectF(315, 13, 140, 12), 6, 6)
        p.setBrush(QColor("#51CF66"))
        p.drawRoundedRect(QRectF(315, 13, 140 * prog, 12), 6, 6)
        p.setPen(QColor("#7950F2" if not dark else "#B197FC"))
        p.drawText(QRectF(465, 0, 206, HUD_H), f"🏆 得分 {self.score:,}  ({self.speed_mul}×)",
                   QTextOption(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))

        # 左侧小推车区
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#243329" if dark else "#D8F5A2"))
        p.drawRect(QRectF(0, HUD_H, MOWER_W, self.H - HUD_H))

        # 5x9 交替绿格草坪
        for r in range(LANES):
            for c in range(COLS):
                rect = QRectF(MOWER_W + c * CELL_W, HUD_H + r * CELL_H, CELL_W, CELL_H)
                if dark:
                    col = QColor("#213829" if (r + c) % 2 == 0 else "#1B2E22")
                else:
                    col = QColor("#A9E34B" if (r + c) % 2 == 0 else "#94D82D")
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawRect(rect)
                if self._hover_cell == (c, r):
                    p.setPen(QPen(QColor("#FA5252" if self.shovel_mode else "#FFFFFF"), 2.0, Qt.PenStyle.DashLine))
                    p.setBrush(QColor(255, 255, 255, 45))
                    p.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 8, 8)

        # 5 台自动小推车
        for mw in self.mowers:
            if mw["used"]:
                continue
            p.save()
            p.translate(mw["x"], mw["y"])
            p.setPen(contour_pen(QColor("#FA5252"), 1.3))
            p.setBrush(clay_brush(0, 0, 16, 12, QColor("#FA5252")))
            p.drawRoundedRect(QRectF(-15, -10, 30, 18), 6, 6)
            p.setBrush(QColor("#343A40"))
            p.drawEllipse(QPointF(-8, 10), 5, 5)
            p.drawEllipse(QPointF(8, 10), 5, 5)
            p.setPen(QPen(QColor("#E9ECEF"), 2.2))
            p.drawLine(QPointF(-12, -10), QPointF(-18, -18))
            p.restore()

        for pl in self.plants.values():
            self._paint_plant(p, pl, now)
        for z in self.zombies:
            self._paint_zombie(p, z, now)
        for b in self.bullets:
            p.setPen(QPen(QColor("#FFFFFF"), 1.2))
            p.setBrush(QColor(b["col"]))
            p.drawEllipse(QPointF(b["x"], b["y"]), 6.5, 6.5)

        # 飘落阳光球
        for s in self.suns:
            pulse = 1.0 + 0.08 * math.sin(now * 6.0)
            p.save()
            p.translate(s["x"], s["y"])
            p.scale(pulse, pulse)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 224, 102, 95))
            p.drawEllipse(QPointF(0, 0), 21, 21)
            p.setPen(contour_pen(QColor("#F08C00"), 1.4))
            p.setBrush(clay_brush(0, 0, 14, 14, QColor("#FFD43B")))
            p.drawEllipse(QPointF(0, 0), 14, 14)
            p.restore()

        for f in self.fx:
            alpha = max(0.0, min(1.0, f["life"] * 2.0))
            p.save()
            p.setOpacity(alpha)
            if f["type"] == "ring":
                p.setPen(QPen(QColor(f["col"]), 3.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(f["x"], f["y"]), f["r"], f["r"])
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
                title = "🌻🏆 草坪守卫大胜利!"
                sub = f"得分 {self.score:,} · 击退 {self.kills} 只捣蛋怪 · 点「挑战无尽」冲榜!"
            elif self.game_over:
                title = "😱 捣蛋怪冲进小窝啦!"
                sub = f"守至第 {self.wave} 波 · 最终得分 {self.score:,}"
            else:
                title = "⏸ 已暂停布阵"
                sub = "点击「继续」恢复守卫"
            p.drawText(QRectF(0, self.H * 0.38, self.W, 38), title, QTextOption(Qt.AlignmentFlag.AlignCenter))
            bf.setPixelSize(14)
            p.setFont(bf)
            p.setPen(QColor("#F8F9FA"))
            p.drawText(QRectF(0, self.H * 0.50, self.W, 28), sub, QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class PetPvZDialog(Dialog):
    """《🌻 萌宠大战捣蛋怪》植物大战僵尸风 2.5D 草坪塔防窗口。"""

    def __init__(self, win) -> None:
        super().__init__(win, "萌宠大战捣蛋怪")
        self.win = win
        self.g: PetGrowth = win.pet_growth
        self._settled = False
        self.setFixedWidth(_PvZStage.W + 36)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 14)
        lay.setSpacing(7)

        top = QHBoxLayout()
        top.addWidget(label("🌻 萌宠大战捣蛋怪 (植物大战僵尸风)", "dialogTitle"))
        top.addStretch(1)
        self.best_lab = label(f"历史最高 {self.g.pvz_best:,} 分 ({self.g.pvz_waves} 波)", "cardTitle")
        top.addWidget(self.best_lab)
        lay.addLayout(top)

        self.stage = _PvZStage(self, win=win)
        self.stage.state_changed.connect(self._sync_ui)
        self.stage.finished.connect(self._on_finish)
        lay.addWidget(self.stage, 0, Qt.AlignmentFlag.AlignHCenter)

        # 植物卡槽 + 铲子
        dock = QHBoxLayout()
        dock.setSpacing(5)
        self.card_btns: dict[str, QPushButton] = {}
        card_qss = (
            "QPushButton { padding: 4px 4px; border-radius: 10px; font-size: 11px; font-weight: 600; }"
            "QPushButton:checked { border: 2px solid #40C057; }"
        )
        for pl in PVZ_PLANTS:
            b = QPushButton(f"{pl['ico']} {pl['name']}\n☀️{pl['cost']}", self)
            b.setCheckable(True)
            b.setChecked(pl["id"] == "sun")
            b.setFixedHeight(44)
            b.setStyleSheet(card_qss)
            b.setToolTip(f"{pl['name']}（{pl['cost']}阳光）：{pl['desc']}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, pid=pl["id"]: self._pick_card(pid))
            dock.addWidget(b, 1)
            self.card_btns[pl["id"]] = b
        self.shovel_btn = QPushButton("🧹 铲子\n移除单位", self)
        self.shovel_btn.setCheckable(True)
        self.shovel_btn.setFixedHeight(44)
        self.shovel_btn.setStyleSheet(card_qss)
        self.shovel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.shovel_btn.clicked.connect(self._toggle_shovel)
        dock.addWidget(self.shovel_btn)
        lay.addLayout(dock)

        self.info_lab = label("鼠标划过或点击自动收 ☀️阳光，点击草坪格放置萌宠守卫 5 条路，左侧小推车可兜底救场！", "faint", wrap=True)
        lay.addWidget(self.info_lab)

        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.spd_btn = button("⏩ 1×", "", self.stage.toggle_speed, 62)
        self.pause_btn = button("⏸ 暂停", "", self.stage.toggle_pause, 66)
        self.endless_btn = button("♾ 挑战无尽", "primary", self._go_endless, 92)
        self.endless_btn.setVisible(False)
        foot.addWidget(self.spd_btn)
        foot.addWidget(self.pause_btn)
        foot.addWidget(self.endless_btn)
        foot.addWidget(button("🔄 重开", "", lambda: self._restart(False), 74))
        foot.addWidget(button("♾ 无尽", "", lambda: self._restart(True), 74))
        foot.addWidget(button("📤 晒战绩", "", self._share, 88))
        foot.addWidget(button("🏆 榜单", "", lambda: (self._settle_if_needed(), self.win.open_pet_rank()), 78))
        foot.addStretch(1)
        foot.addWidget(button("关闭", "primary", self.accept, 70))
        lay.addLayout(foot)
        self._sync_ui()

    def _pick_card(self, pid: str) -> None:
        self.stage.shovel_mode = False
        self.stage.selected_card = pid
        self.shovel_btn.setChecked(False)
        for k, b in self.card_btns.items():
            b.setChecked(k == pid)

    def _toggle_shovel(self) -> None:
        self.stage.shovel_mode = not self.stage.shovel_mode
        self.shovel_btn.setChecked(self.stage.shovel_mode)
        if self.stage.shovel_mode:
            for b in self.card_btns.values():
                b.setChecked(False)
        play_game_sfx(self.win, "click", 0.6)

    def _go_endless(self) -> None:
        self._settle_if_needed()
        self._settled = False
        self.stage.continue_endless()

    def _restart(self, endless: bool) -> None:
        self._settle_if_needed()
        self._settled = False
        self.stage.reset(endless=endless)

    def _sync_ui(self) -> None:
        st = self.stage
        self.spd_btn.setText(f"⏩ {st.speed_mul}×")
        self.pause_btn.setText("▶️ 继续" if st.paused else "⏸ 暂停")
        self.endless_btn.setVisible(st.victory and not st.endless)
        self.shovel_btn.setChecked(st.shovel_mode)
        for pl in PVZ_PLANTS:
            pid = pl["id"]
            b = self.card_btns[pid]
            cd = st.card_cds.get(pid, 0.0)
            if cd > 0.1:
                b.setText(f"{pl['ico']} {pl['name']}\n⏳{cd:.1f}s")
                b.setEnabled(False)
            else:
                b.setText(f"{pl['ico']} {pl['name']}\n☀️{pl['cost']}")
                b.setEnabled(st.sun >= pl["cost"])

    def _on_finish(self, win_flag: bool, score: int, waves: int) -> None:
        self._settle_if_needed(score, waves)
        self._sync_ui()

    def _settle_if_needed(self, score: int | None = None, waves: int | None = None) -> None:
        sc = self.stage.score if score is None else score
        wv = self.stage.wave if waves is None else waves
        if self._settled or sc <= 0:
            return
        self._settled = True
        gain, ups = self.g.record_pvz_score(sc, wv)
        first = self.g.claim_daily_game_bonus()
        extra = " · 🌟今日首胜+30通行证分!" if first else ""
        self.best_lab.setText(f"历史最高 {self.g.pvz_best:,} 分 ({self.g.pvz_waves} 波)")
        self.info_lab.setText(f"🎉 结算：得分 {sc:,}（第 {wv} 波），+{gain} 经验与通行证积分！"
                              + (f"（升 {ups} 级!）" if ups > 0 else "") + extra)
        if ups > 0 and hasattr(self.win, "_pet_level_up"):
            self.win._pet_level_up()
        if hasattr(self.win, "pr_broadcast"):
            self.win.pr_broadcast()

    def _share(self) -> None:
        sc = max(self.stage.score, self.g.pvz_best)
        wv = max(self.stage.wave, self.g.pvz_waves)
        detail = "草坪大胜利" if self.stage.victory else f"守至第 {wv} 波"
        if hasattr(self.win, "share_game_score") and self.win.share_game_score("pvz", sc, detail):
            self.info_lab.setText("📤 「萌宠大战捣蛋怪」战绩挑战卡已发送到当前聊天！")

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
