"""
密语 · 网络事件总表:Core 收到的 "ev" 事件按名字交给对应的方法。新增事件在 EVENTS 里登记一行。
"""
from __future__ import annotations

from ..widgets import Conv


# 事件名: (只接受私聊, 处理方式, 方法名)
#   处理方式  "peer"       handler(d, data)               不需要会话
#             "peer+name"  handler(d, name, data)
#             "conv"       handler(conv, d, data)         d 是哪个会话发来的,就交给那个会话
#             "conv+name"  handler(conv, d, name, data)
EVENTS = {
    # 系统
    "ver": (True, "peer", "_ev_ver"),                    # 版本号 / 可分发的更新包(system.py)
    # 聊天(chat.py)
    "edit": (False, "conv", "_ev_edit"),
    "react": (False, "conv", "_ev_react"),
    "poke": (False, "conv", "_ev_poke"),
    "notice": (False, "conv", "_ev_notice"),
    "pins": (False, "conv", "_ev_pins"),
    "room_name": (False, "conv", "_ev_room_name"),
    "avatar": (True, "peer", "_ev_avatar"),
    # 文件(files.py)
    "fthumb": (False, "conv", "_ev_fthumb"),             # 视频的封面和时长(跟在视频消息后面)
    # 进群特效(enter.py)
    "enter": (False, "conv", "_ev_enter"),
    # 卡片类玩法(games.py)
    "vote": (False, "conv", "_ev_vote"),
    "g_move": (False, "conv+name", "_ev_game"),
    "g_resign": (False, "conv+name", "_ev_game"),
    "g_commit": (False, "conv+name", "_ev_game"),
    "g_reveal": (False, "conv+name", "_ev_game"),
    "b_stroke": (False, "conv+name", "_ev_board"),
    "b_undo": (False, "conv+name", "_ev_board"),
    "b_clear": (False, "conv+name", "_ev_board"),
    "b_join": (False, "conv+name", "_ev_board"),
    "b_leave": (False, "conv+name", "_ev_board"),
    "b_sync_req": (False, "conv+name", "_ev_board"),
    "b_sync": (False, "conv+name", "_ev_board"),
    # 宠物(pet.py)
    "pet_visit": (True, "conv", "_ev_pet_visit"),
    "pet_back": (True, "conv", "_ev_pet_back"),
    "skit": (True, "peer+name", "_ev_skit"),
    "skit_ok": (True, "peer+name", "_ev_skit"),
    # 扔东西 / 揍宠物(throws.py)
    "throw": (False, "conv", "_ev_throw"),
    "pbeat": (False, "conv", "_ev_pbeat"),
    "pbeat_r": (False, "conv", "_ev_pbeat_r"),
    # 宠物排行榜(petrank.py)
    "pcard": (False, "conv", "_ev_pcard"),
    "pcards": (False, "conv", "_ev_pcards"),
    "pet_lv": (False, "conv", "_ev_pet_lv"),
    # 群宠物(petlife.py)
    "gpet": (False, "conv", "_ev_gpet"),
    # 五子棋大厅 / 联网对战 / 排行榜同步(gomoku.py),都是点对点私聊加密
    **{name: (True, "peer+name", "_ev_gm") for name in (
        "gm_room", "gm_st", "gm_join", "gm_busy", "gm_invite", "gm_inv_cancel", "gm_inv_ans", "gm_start",
        "gm_start_ok", "gm_act", "gm_sync", "gm_state", "gm_req", "gm_reply", "gm_bye", "gm_hi", "gm_ids", "gm_get",
        "gm_recs")},
    # 谁是坏鸭(duck.py),都是点对点私聊加密,房主当裁判
    **{name: (True, "peer+name", "_ev_dk") for name in (
        "dk_room", "dk_join", "dk_roster", "dk_leave", "dk_end", "dk_color", "dk_inv", "dk_err", "dk_start", "dk_st",
        "dk_ev", "dk_in", "dk_act")},
    # 谁是卧底(spy.py),同样点对点私聊加密
    **{name: (True, "peer+name", "_ev_sp") for name in (
        "sp_room", "sp_join", "sp_roster", "sp_leave", "sp_end", "sp_inv", "sp_err", "sp_start", "sp_st", "sp_act")},
}
# 这些事件来自还没打开私聊的人时,自动建一个私聊会话
OPEN_DM = {"poke", "pet_visit", "pet_back", "throw", "pbeat", "pbeat_r"}


class EventsMixin:
    """把网络事件分给各功能模块。"""

    def _ev_ev(self, d: dict) -> None:
        name = d.get("ev")
        entry = EVENTS.get(name)
        if entry is None:
            return                                   # 不认识的事件(比如对方版本更新):忽略
        dm_only, how, method = entry
        scope = d.get("scope")
        if dm_only and scope != "dm":
            return
        handler = getattr(self, method)
        data = d["d"]
        if how == "peer":
            handler(d, data)
            return
        if how == "peer+name":
            handler(d, name, data)
            return
        conv = self._conv_for_event(d, create_dm=name in OPEN_DM)
        if conv is None:
            return
        if how == "conv":
            handler(conv, d, data)
        else:
            handler(conv, d, name, data)

    def _conv_for_event(self, d: dict, create_dm: bool = False) -> Conv | None:
        scope = d.get("scope")
        if scope == "lobby":
            return self.convs.get("lobby")
        if scope == "room":
            return self.convs.get("room:" + (d.get("room") or ""))
        if scope == "dm":
            conv = self.convs.get("dm:" + d["peer"])
            if conv is None and create_dm:
                conv = self.open_dm(d["peer"], select=False)
            return conv
        return None
