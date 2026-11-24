"""
密语 · 进群特效(2.5)
- 每个人在设置里选自己的登场效果(烟花 / 花瓣雨 / 星光 / 闪电 / 宠物开路 / 不放)。
- 刚进群(加入暗号群、打开软件进大厅、重新进入大厅)的 90 秒内,碰到群里的每个人时把自己的登场效果
  发给对方(复用"给新来的人同步群信息"那个时机,不需要改在场信息的格式)。
- 收到的人:正在看这个群、窗口开着、没锁屏时才放;同一个人 10 分钟内只放一次;可以在设置里关掉别人的特效。
"""
from __future__ import annotations

import time

from ..enterfx import FX, FX_CHOICES, EnterOverlay
from ..ui import peer_avatar
from ..widgets import Conv

ENTER_WINDOW = 90.0           # 进群后多久之内算"刚进来"
SHOW_EVERY = 600.0            # 同一个人 10 分钟最多放一次
FX_IDS = set(FX) | {"off"}


class EnterMixin:
    # ---------------------------------------------------------------- 钩子
    def _init_enter(self) -> None:
        self.enter_fx = "stars"            # 我的登场效果
        self.enter_see = True              # 看别人的进群特效
        self._enter_t: dict[str, float] = {}
        self._enter_start = time.monotonic()
        self._enter_shown: dict[str, float] = {}
        self.enter_overlay: EnterOverlay | None = None

    def _restore_enter(self, acct: dict, st: dict) -> None:
        if st.get("enter_fx") in FX_IDS:
            self.enter_fx = st["enter_fx"]
        if isinstance(st.get("enter_see"), bool):
            self.enter_see = st["enter_see"]

    def _settings_enter(self) -> dict:
        return {"enter_fx": self.enter_fx, "enter_see": self.enter_see}

    def _group_sync_enter(self, conv: Conv, pid: str) -> None:
        """碰到群里的人:如果我是刚进来的,把我的登场效果发给他。"""
        if self.enter_fx == "off" or conv.kind not in ("lobby", "room"):
            return
        since = self._enter_t.get(conv.key, self._enter_start)
        if time.monotonic() - since > ENTER_WINDOW:
            return
        scope, target = self.scope_target(conv)
        try:
            self.core.send_event(scope, target, "enter", self._enter_payload(), to=pid)
        except Exception:                                   # noqa: BLE001
            pass

    def _enter_payload(self) -> dict:
        g = self.pet_growth
        return {"fx": self.enter_fx, "sp": self.pet.species, "lv": g.level, "wear": list(g.wear)[:8]}

    # ---------------------------------------------------------------- 我进群了
    def note_entered(self, key: str, show_mine: bool = True) -> None:
        """我刚进了某个群(加入暗号群 / 重新进入大厅):开始 90 秒的"刚进来"窗口,自己也看一眼自己的登场。"""
        self._enter_t[key] = time.monotonic()
        if show_mine and self.enter_fx != "off" and self.current_key == key:
            conv = self.convs.get(key)
            if conv is not None:
                self._enter_show(self.me["id"], "我", self._enter_payload(), conv)

    def preview_enter(self, fx: str | None = None) -> None:
        """设置里预览登场效果(只有自己看得到)。"""
        data = dict(self._enter_payload(), fx=fx or self.enter_fx)
        if data["fx"] == "off":
            return
        conv = self.current
        if conv is not None:
            self._enter_show(self.me["id"], "我", data, conv, force=True)

    def set_enter_fx(self, fx: str) -> None:
        if fx in FX_IDS:
            self.enter_fx = fx
            self.preview_enter(fx)

    def set_enter_see(self, on: bool) -> None:
        self.enter_see = bool(on)

    # ---------------------------------------------------------------- 别人进群了
    def _ev_enter(self, conv: Conv, d: dict, data: dict) -> None:
        if conv.kind not in ("lobby", "room") or not self.enter_see:
            return
        pid = d.get("peer", "")
        fx = data.get("fx")
        if fx not in FX or not pid:
            return
        now = time.monotonic()
        if now - self._enter_shown.get(pid, -1e9) < SHOW_EVERY:
            return
        if conv.key != self.current_key or not self.window_visible() or self.locked:
            return                                          # 没在看这个群:不放(别打扰)
        self._enter_shown[pid] = now
        nick = d.get("nick") or (self.peers.get(pid) or {}).get("nick", "?")
        self._enter_show(pid, nick, data, conv)

    def _enter_show(self, pid: str, nick: str, data: dict, conv: Conv, force: bool = False) -> None:
        from ..fun import ACC_BY_ID, PET_MAX_LEVEL, SPECIES, pet_pixmap
        if not force and not self.fun.get("effects", True):
            return
        fx = data.get("fx") if data.get("fx") in FX else "stars"
        verb = "来了" if conv.kind == "lobby" else "进群了"
        text = f"{nick[:12]} {verb}"
        pet = None
        if fx == "pet":
            sp = data.get("sp") if data.get("sp") in SPECIES else "cat"
            lv = data.get("lv") if type(data.get("lv")) is int else 1
            wear = [w for w in (data.get("wear") or []) if isinstance(w, str) and w in ACC_BY_ID][:8]
            pet = pet_pixmap(sp, max(1, min(PET_MAX_LEVEL, lv)), tuple(wear), 120, 120)
        ov = self.enter_overlay
        if ov is None:
            ov = EnterOverlay(self.chat_panel)
            self.enter_overlay = ov
        ov.play(fx, text, peer_avatar(pid, nick, 96), pet)
        if fx in ("fireworks", "petals", "stars"):
            self.effects.play(fx)


__all__ = ["EnterMixin", "FX_CHOICES"]
