"""
密语 · 设置窗口(2.0)

左边是分类(账户、外观、聊天、通知、宠物、安全、更新、数据),右边直接调;顶部搜索框跨分类找设置。
每一项设置都写成一条"规格":标题、说明、搜索关键词、控件类型,以及怎么读当前值、怎么改。
改完一项,整页重新读一遍(有些设置互相影响,比如关掉「记住登录」后「保存聊天记录」也跟着变灰)。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import motion, sound as S, theme
from ..dialogs import Dialog
from ..enterfx import FX_CHOICES
from ..fun import FX_THEMES, SPECIES
from ..icons import icon
from ..petcare import form_of
from ..theme import T
from ..ui import hline, label, make_menu, popup
from ..version import VERSION
from .records import HISTORY_DAYS
from .system import UPDATE_MODES

CATEGORIES = [
    ("account", "账户", "user"), ("look", "外观", "palette"), ("chat", "聊天", "chat"),
    ("notify", "通知", "bell"), ("pet", "宠物", "paw"), ("security", "安全", "lock"),
    ("update", "更新", "refresh"), ("data", "数据", "folder"),
]


class Spec:
    """一项设置。kind: switch 开关 / choice 下拉选择 / menu 弹出菜单 / button 按钮 / buttons 一排按钮 / info 只显示。"""

    def __init__(self, cat: str, group: str, title: str, sub: str = "", kind: str = "button", get=None, set=None,
                 options=None, action: str = "", keys: str = "", enabled=None, danger: bool = False,
                 close_first: bool = False) -> None:
        self.cat, self.group, self.title, self.sub, self.kind = cat, group, title, sub, kind
        self.get, self.set, self.options, self.action = get, set, options, action
        self.keys, self.enabled, self.danger, self.close_first = keys, enabled, danger, close_first

    def text(self) -> str:
        return " ".join((self.title, self.sub, self.keys, self.group, dict((c, n) for c, n, _ in CATEGORIES)[self.cat]))

    def is_enabled(self) -> bool:
        try:
            return True if self.enabled is None else bool(self.enabled())
        except Exception:                                   # noqa: BLE001
            return False


def build_specs(w) -> list[Spec]:
    """所有设置项。w = 主窗口。"""
    g = w.pet_growth
    has_store = lambda: w.store is not None                                   # noqa: E731

    def theme_value():
        return "time" if w.follow_time else "system" if w.follow_system else T["name"]

    def pet_line():
        cur, need, _ = g.progress()
        exp = f"经验 {cur:,} / {need:,}" if need else "已满级"
        return f"{g.name} · Lv.{g.level} · {form_of(g.level)[1]} · {exp}"

    def history_line():
        if not w.save_history:
            return "没有开启保存"
        n, size = w.history_stats()
        return f"已保存 {n:,} 条 · 占用 {size / 1048576:.1f} MB"

    def update_line():
        u = w.update
        state = u.get("state")
        if state == "ready":
            return f"新版本 v{u['v']} 已下载好并通过签名验证"
        if state == "downloading":
            return f"正在下载 v{u['v']}…"
        if state == "offered":
            return f"发现新版本 v{u['v']}"
        return w.update_status()

    def update_label():
        return {"ready": "安装并重启", "offered": "下载"}.get(w.update.get("state"), "查看")

    def update_action():
        state = w.update.get("state")
        if state == "ready":
            w.install_update()
        elif state == "offered":
            w.download_update()
        else:
            w.show_update()

    def toggle_act(act):
        return lambda on: act.isChecked() != on and act.trigger()

    def locked(kind, items):
        def opts():
            out = []
            for iid, name, lv, *_ in items:
                ok = g.has(kind, iid, lv)
                hint = "抽卡限定" if lv >= 900 else f"宠物 Lv.{lv} 或抽卡"
                out.append((iid, name if ok else f"🔒 {name}  ·  {hint}", ok))
            return out
        return opts

    fx_opts = locked("fx", FX_THEMES)
    snd_opts = locked("snd", S.SOUND_THEMES)
    skin_base = locked("skin", theme.SKINS)
    skin_opts = lambda: [("", "经典", True)] + skin_base()                       # noqa: E731
    from ..fun import BUBBLE_AURAS
    aura_base = locked("aura", BUBBLE_AURAS)
    aura_opts = lambda: [("", "关闭边缘特效", True)] + aura_base()               # noqa: E731
    effects = [("balloons", "🎈 生日快乐"), ("confetti", "🎉 恭喜"), ("fireworks", "🎆 新年快乐"), ("hearts", "❤️ 爱你"),
               ("snow", "❄️ 下雪"), ("rain", "🌧 下雨"), ("stars", "🌙 晚安"), ("flames", "💪 加油"), ("laugh", "😂 哈哈哈")]

    def pick_locked(kind, setter):                       # 双保险:没解锁的就算被选中也不生效
        def f(v):
            item = next((x for x in {"fx": FX_THEMES, "snd": S.SOUND_THEMES}[kind] if x[0] == v), None)
            if item is not None and g.has(kind, v, item[2]):
                setter(v)
        return f

    def pick_skin(v):
        if not v:
            w.set_skin(None)
            return
        item = next((x for x in theme.SKINS if x[0] == v), None)
        if item is not None and g.has("skin", v, item[2]):
            w.set_skin(v)

    def pick_aura(v):
        g.set_aura(v or "")

    return [
        # ---------------------------------------------------------------- 账户
        Spec("account", "我", "昵称", kind="button", get=lambda: w.me.get("nick", ""), action="修改…",
             set=w.change_nick, keys="名字 改名"),
        Spec("account", "我", "我的身份与指纹", "核对指纹可以确认没人冒充你", action="查看", set=w.show_identity,
             keys="安全码 id"),
        Spec("account", "我", "头像", "别人列表和聊天里显示的头像", kind="buttons",
             options=[("选择图片…", w.choose_avatar), ("用宠物", w.use_pet_avatar), ("恢复默认", lambda: w.set_avatar(None))]),
        Spec("account", "可见性", "在公开大厅中显示我", "关掉后只有同暗号的人能发现你(隐身)", "switch",
             get=lambda: w.act_lobby.isChecked(), set=toggle_act(w.act_lobby), keys="隐身 大厅"),
        Spec("account", "跨网联机", "🌐 跨网联机（EasyTier 异地组网）", "", "button",
             get=w.easytier_status_line, action="配置…", set=w.show_easytier_dialog,
             keys="跨网 异地 组网 easytier 外网 远程 联机 虚拟局域网"),
        Spec("account", "登录", "记住登录", "下次打开直接进入,还是同一个身份", "switch",
             get=lambda: w.act_remember.isChecked(), set=toggle_act(w.act_remember), enabled=has_store,
             keys="自动登录 账户"),
        Spec("account", "登录", "注销账户", "删除这台电脑上的账户、聊天记录和收藏", action="注销…", set=w.logout,
             danger=True, close_first=True, keys="删除 退出"),
        Spec("account", "登录", "退出密语", action="退出", set=w.close, close_first=True, keys="关闭"),
        # ---------------------------------------------------------------- 外观
        Spec("look", "主题", "主题", "左上角的按钮也能快速切换", "choice", get=theme_value, set=w.set_theme,
             options=[(n, t["label"]) for n, t in theme.THEMES.items()]
             + [("system", "跟随系统(浅色 / 深色)"), ("time", "随时间变化(清晨 / 白天 / 黄昏 / 夜晚)")],
             keys="浅色 深色 樱花 紫夜 深海 纯黑 黄昏 颜色"),
        Spec("look", "主题", "个性化外观", "主题色、我的气泡颜色、面板透明度、自定义背景图", action="打开…",
             set=w.show_personalize, keys="颜色 透明 背景图 壁纸 气泡颜色"),
        Spec("look", "动效", "动态背景", "光斑在背景里漂移、隔一会儿有柔光扫过;静态最省电", "choice",
             get=lambda: theme.CUSTOM.get("ambient_level", 2) if theme.CUSTOM.get("ambient", True) else "off",
             set=lambda v: w.set_dynamic_bg(False) if v == "off" else w.set_dynamic_bg(True, v),
             options=[(2, "明显"), (1, "轻柔"), ("off", "静态(不动,最省电)")], keys="静态 光影 性能 省电 流动"),
        Spec("look", "动效", "界面动效", "按钮悬停、菜单弹窗淡入、切换过渡;关掉后瞬间完成", "switch",
             get=lambda: motion.ENABLED, set=w.set_motion, keys="动画 过渡 微动效 性能"),
        Spec("look", "动效", "气泡动效", "新消息浮上来、撤回时碎掉、有人 @你时晃一晃、点回应时弹一下", "choice",
             get=lambda: w.fun.get("bubble", "soft"), set=lambda v: w.set_fun("bubble", v),
             options=[("soft", "细腻"), ("lively", "活泼"), ("off", "关闭")], keys="气泡 弹出 动画 撤回 碎 晃"),
        Spec("look", "窗口", "无边框通顶窗口", "去掉传统白色标题栏,动态极光与毛玻璃直通窗口顶边", "switch",
             get=lambda: bool(getattr(w, "frameless", False)), set=w.set_frameless,
             enabled=lambda: theme.sys.platform == "win32", keys="无边框 标题栏 通顶 沉浸"),
        Spec("look", "窗口", "紧凑侧边栏", "左侧会话列表收成一列头像轨,省出更多屏幕空间并支持窄窗贴边办公", "switch",
             get=lambda: bool(getattr(w, "compact_side", False)), set=w.set_compact_side,
             keys="折叠 侧栏 紧凑 窄窗 摸鱼"),
        Spec("look", "窗口", "显示右侧成员栏", "收起后聊天视野更宽敞(顶栏右侧按钮也可随时开关)", "switch",
             get=lambda: bool(getattr(w, "members_open", True)), set=w.set_members_open,
             keys="成员栏 折叠 右侧 抽屉"),
        Spec("look", "窗口", "毛玻璃效果", "需要 Windows 11", "switch", get=lambda: w.act_glass.isChecked(),
             set=toggle_act(w.act_glass), enabled=lambda: theme.GLASS_SUPPORTED, keys="亚克力 透明"),
        Spec("look", "窗口", "深夜护眼", "22 点到 6 点,整个窗口自动变暖变暗一点", "switch",
             get=lambda: w.eyecare, set=w.set_eyecare, keys="夜间 护眼"),
        Spec("look", "窗口", "窗口标题伪装", "任务栏上显示成别的名字", action="设置…", set=w.disguise_title,
             keys="隐蔽 记事本"),
        # ---------------------------------------------------------------- 聊天
        Spec("chat", "聊天记录", "保存聊天记录", "加密保存在这台电脑上;阅后即焚的永远不保存", "switch",
             get=lambda: w.act_history.isChecked(), set=toggle_act(w.act_history), enabled=has_store,
             keys="历史 记录 数据库"),
        Spec("chat", "聊天记录", "保留多久", "超过期限的记录会自动删除", "choice",
             get=lambda: w.history_days, set=w.set_history_days, options=HISTORY_DAYS,
             enabled=lambda: w.save_history, keys="天 期限 清理"),
        Spec("chat", "聊天记录", "数据库", kind="button", get=history_line, action="整理", set=w.compact_history,
             enabled=lambda: w.db is not None, keys="压缩 空间 优化"),
        Spec("chat", "隐私", "私聊发送「已读」", "关掉后对方看不到你读没读", "switch",
             get=lambda: w.act_receipts.isChecked(), set=toggle_act(w.act_receipts), keys="已读回执"),
        Spec("chat", "隐私", "私聊发送「正在输入」", "", "switch",
             get=lambda: w.act_typing.isChecked(), set=toggle_act(w.act_typing), keys="输入中"),
        Spec("chat", "发送", "拖进来的文件先确认再发送", "默认松手就直接发出去", "switch",
             get=lambda: w.act_drop_confirm.isChecked(), set=toggle_act(w.act_drop_confirm), keys="拖拽 图片 视频"),
        Spec("chat", "发送", "清空表情包", "收藏的表情图片", action="清空…", set=w.clear_stickers, danger=True),
        Spec("chat", "特效", "聊天特效", "关键词全屏特效、表情雨(双方都能看到)", "switch",
             get=lambda: bool(w.fun["effects"]), set=lambda on: w.set_fun("effects", on), keys="烟花 彩带"),
        Spec("chat", "特效", "我的进群特效", "进群、打开软件进大厅时大家看到的登场效果(选了马上预览一次)", "choice",
             get=lambda: w.enter_fx, set=w.set_enter_fx, options=FX_CHOICES,
             keys="进群 登场 入场 烟花 花瓣 星光 闪电 宠物开路"),
        Spec("chat", "特效", "看别人的进群特效", "别人进群时顶部滑进一条横幅;同一个人 10 分钟最多一次", "switch",
             get=lambda: w.enter_see, set=w.set_enter_see, keys="进群 登场 入场 横幅"),
        Spec("chat", "特效", "被扔东西时的特效", "番茄、鸡蛋砸在头像上,砸中自己时糊在屏幕上(关掉只显示文字)", "switch",
             get=lambda: bool(w.fun.get("throw_fx", True)), set=lambda on: w.set_fun("throw_fx", on),
             keys="扔东西 拖鞋 番茄"),
        Spec("chat", "特效", "聊天热度背景", "聊得越热闹,背景越暖", "switch",
             get=lambda: bool(w.fun["heat"]), set=lambda on: w.set_fun("heat", on)),
        Spec("chat", "特效", "预览特效", "看看关键词特效长什么样(只有你自己看得到)", "menu", options=effects,
             set=lambda n: w.effects.play(n), action="播放 ▾", keys="烟花 气球 下雪 彩带"),
        Spec("chat", "特效", "发送动画", "", "switch", get=lambda: bool(w.fun["send_anim"]),
             set=lambda on: w.set_fun("send_anim", on)),
        Spec("chat", "特效", "打字火花", "", "switch", get=lambda: bool(w.fun["sparks"]),
             set=lambda on: w.set_fun("sparks", on)),
        Spec("chat", "特效", "打字特效主题", "火花 / 樱花 / 雪花 / 星星 / 爱心", "choice",
             get=lambda: w.fun.get("fx", "spark"), set=pick_locked("fx", w.set_fx), options=fx_opts),
        Spec("chat", "特效", "连击计数", "", "switch", get=lambda: bool(w.fun["combo"]),
             set=lambda on: w.set_fun("combo", on)),
        Spec("chat", "特效", "气泡皮肤", "对方看到的你的消息也是这个皮肤", "choice",
             get=lambda: w.fun.get("skin") or "", set=pick_skin, options=skin_opts),
        Spec("chat", "特效", "✨ 气泡边缘特效", "烈焰燃边、雷电电弧、赛博霓虹等 12 款动态边缘粒子(不遮挡文字,对方也看得到)",
             "choice", get=lambda: g.aura or "", set=pick_aura, options=aura_opts,
             keys="火焰 烈焰 雷电 霓虹 樱花 边缘 粒子 气泡特效"),
        Spec("chat", "其它", "聊天字号", "调整聊天消息文字大小", "choice",
             get=lambda: w.fun.get("font_px", 14), set=w.set_chat_font_size,
             options=[(13, "小 (13px)"), (14, "标准 (14px)"), (16, "大 (16px)")], keys="字体 字号 大小"),
        Spec("chat", "其它", "紧凑气泡间距", "缩小消息上下间距,一屏看更多聊天记录", "switch",
             get=lambda: bool(w.fun.get("compact_bubbles", False)), set=w.set_bubble_density, keys="密度 间距 紧凑"),
        Spec("chat", "其它", "群排行榜", "每周一在群里公布上周的话痨榜等", "switch",
             get=lambda: bool(w.fun.get("rank", True)), set=lambda on: w.set_fun("rank", on)),
        Spec("chat", "其它", "聊天年报", "只统计数量,不记录内容", action="查看…", set=w.show_report, keys="统计"),
        Spec("chat", "其它", "五子棋", "大厅、联网对战、人机练习、排行榜和我的战绩(左上角的棋盘按钮)", action="打开…",
             set=w.open_gomoku, close_first=True, keys="游戏 下棋 排行榜 积分 战绩"),
        Spec("chat", "其它", "谁是坏鸭", "4~10 人局域网推理小游戏(左上角的小鸭子按钮)", action="打开…",
             set=lambda: w.open_duck(), keys="鹅鸭杀 狼人杀 游戏 坏鸭", close_first=True),
        Spec("chat", "其它", "谁是卧底", "4~10 人派对游戏:每人一句话描述自己的词,找出卧底", action="打开…",
             set=lambda: w.open_spy(), keys="卧底 游戏 派对", close_first=True),
        # ---------------------------------------------------------------- 通知
        Spec("notify", "提示音", "消息提示音", "", "switch", get=lambda: w.act_sound.isChecked(),
             set=toggle_act(w.act_sound), keys="声音 铃声"),
        Spec("notify", "提示音", "窗口隐藏时也响", "默认关闭,免得藏起来时暴露", "switch",
             get=lambda: w.act_sound_hidden.isChecked(), set=toggle_act(w.act_sound_hidden)),
        Spec("notify", "提示音", "音效主题", "提示音和打字声一起换", "choice",
             get=lambda: w.fun.get("snd", "default"), set=pick_locked("snd", w.set_snd), options=snd_opts),
        Spec("notify", "提示音", "试听", action="播放", set=lambda: w.notifier.play(force=True)),
        Spec("notify", "提示音", "打字音效", "机械键盘的声音", "switch", get=lambda: bool(w.fun["keysound"]),
             set=lambda on: w.set_fun("keysound", on), keys="键盘声"),
        Spec("notify", "提醒", "新消息时闪烁任务栏", "", "switch", get=lambda: w.act_flash.isChecked(),
             set=toggle_act(w.act_flash)),
        Spec("notify", "白噪音", "白噪音", "藏起软件时会立刻静音", "choice",
             get=lambda: w.ambient_kind or "", set=lambda v: w.set_ambient(v or None),
             options=[("", "关闭")] + list(S.AMBIENT), keys="雨声 篝火 海浪"),
        Spec("notify", "白噪音", "音量", "", "choice", get=lambda: round(w.ambient_volume, 1),
             set=w.set_ambient_volume, options=[(0.2, "小"), (0.4, "中"), (0.7, "大")]),
        # ---------------------------------------------------------------- 宠物
        Spec("pet", "宠物", "打字宠物", "支持 2.5D 鼠标视线转头与按住捏脸", "choice", get=lambda: w.fun["pet"] or "",
             set=lambda v: w.set_fun("pet", v or None),
             options=[(k, sp["label"]) for k, sp in SPECIES.items()] + [("", "不显示")],
             keys="小猫 小兔 小熊 卡皮巴拉 水豚 柴犬 小狐狸 小企鹅"),
        Spec("pet", "宠物", "名字和等级", kind="button", get=pet_line, action="改名…", set=w.rename_pet),
        Spec("pet", "宠物", "衣橱、染色和形态", "帽子、衣服、一键穿搭方案、自由染色、毛色、瞳色、2.5D小窝", action="打开…", set=w.show_wardrobe,
             keys="装扮 换装 染色 穿搭 方案"),
        Spec("pet", "宠物", "每日签到与萌宠通行证", "每日签到和聊天活跃免费领经验、限定装扮和特殊动作", action="打开…",
             set=w.show_pet_pass, keys="签到 通行证 奖励 领奖"),
        Spec("pet", "宠物", "合成大萌宠", "2.5D 物理合成大西瓜玩法,冲击「至臻金豚王」排行榜", action="开始玩…",
             set=w.show_merge_game, keys="小游戏 合成 大西瓜 萌宠"),
        Spec("pet", "宠物", "接零食大作战", "25 秒轻互动小游戏,赢取宠物经验、心情与通行证积分", action="开始玩…",
             set=w.show_snack_game, keys="小游戏 接零食 互动"),
        Spec("pet", "宠物", "专注番茄钟与喝水提醒", "萌宠戴眼镜伴学 + 灵动岛倒计时 + 定时喝水久坐提醒", action="开启…",
             set=w.show_focus_dialog, keys="番茄钟 专注 喝水 久坐 倒计时"),
        Spec("pet", "宠物", "萌宠双人合拍大头贴", "与好友/群宠生成 2.5D 拍立得贴纸合影 PNG 并一键发送", action="拍照…",
             set=w.show_photobooth, keys="合影 大头贴 拍立得 照片"),
        Spec("pet", "宠物", "喂食和玩耍", "也可以直接右键点宠物", action="打开…",
             set=lambda: w.pet_menu(QCursor.pos()), keys="喂 饿"),
        Spec("pet", "收集", "成就墙和称号", "", action="查看…", set=w.show_wall,
             get=lambda: f"{len(g.badges)} 个成就" + (f" · 佩戴「{g.title_text()}」" if g.title_text() else "")),
        Spec("pet", "收集", "抽卡", "", action="抽卡…", set=w.show_gacha, get=lambda: f"{g.tickets} 张券"),
        Spec("pet", "收集", "宠物日记", "", action="查看…", set=w.show_diary),
        Spec("pet", "收集", "宠物排行榜", "群里大家的宠物等级、本周成长、群宠物贡献(群聊顶栏的奖杯按钮)",
             action="打开…", set=lambda: w.open_pet_rank(), keys="排行 等级榜", close_first=True),
        Spec("pet", "收集", "累计", kind="info",
             get=lambda: f"敲击 {g.taps:,} 次 · 发送 {g.messages:,} 条 · 本次最高连击 {w.pet.best_combo}",
             keys="统计 连击"),
        Spec("pet", "收集", "宠物的朋友", "", action="查看…", set=w.show_friends, get=lambda: f"{len(g.friends)} 个朋友"),
        Spec("pet", "互动", "允许别人的宠物来串门", "", "switch", get=lambda: w.allow_visits,
             set=lambda on: setattr(w, "allow_visits", on)),
        Spec("pet", "互动", "允许别人揍我的宠物", "只是闹着玩:会冒星星、鼓个包,不扣经验", "switch",
             get=lambda: bool(w.fun.get("pet_beat", True)), set=lambda on: w.set_fun("pet_beat", on), keys="揍 打"),
        Spec("pet", "互动", "宠物小剧场", "私聊时偶尔自动上演", "switch", get=lambda: bool(w.fun.get("skits", True)),
             set=lambda on: w.set_fun("skits", on)),
        Spec("pet", "互动", "群宠物", "暗号群里大家一起养", "switch", get=lambda: bool(w.fun.get("gpet", True)),
             set=lambda on: w.set_fun("gpet", on)),
        Spec("pet", "互动", "等级标识", "名字旁显示宠物等级(别人也看得到)", "switch",
             get=lambda: bool(w.fun.get("lv_badge", True)), set=w.set_level_badge),
        Spec("pet", "互动", "桌面陪伴", "窗口最小化时,宠物留在桌面上陪你", "switch", get=lambda: w.desktop_pet_on,
             set=w.set_desktop_pet, keys="桌面宠物"),
        Spec("pet", "互动", "桌宠行为模式", "任务栏自由漫步 / 趴在当前活动窗口顶边偷看 / 固定位置", "choice",
             get=lambda: getattr(w, "desktop_mode", "roam"), set=w.set_desktop_mode,
             options=[("roam", "任务栏自由漫步"), ("peek", "趴在活动窗口顶边"), ("fixed", "固定位置")],
             enabled=lambda: w.desktop_pet_on, keys="漫步 偷看 桌面"),
        Spec("pet", "互动", "桌面陪伴响应全局打字节拍", "最小化后在别的软件打字时桌宠也跟着拍爪攒经验(仅检测节拍,绝不记录任何按键内容)",
             "switch", get=lambda: bool(getattr(w, "desktop_global_keys", True)),
             set=w.set_desktop_global_keys, enabled=lambda: w.desktop_pet_on and theme.sys.platform == "win32",
             keys="全局打字 桌面 拍爪 键盘"),
        # ---------------------------------------------------------------- 安全
        Spec("security", "保护", "启动密码", "打开软件(和叫回窗口)时要先输入密码", action="设置…",
             set=w.set_password_dialog, enabled=has_store,
             get=lambda: "已设置" if w.store is not None and w.store.has_password else "未设置", keys="锁 解锁"),
        Spec("security", "保护", "防偷看模式", "离开窗口时把聊天内容模糊", "switch",
             get=lambda: w.act_privacy.isChecked(), set=toggle_act(w.act_privacy), keys="模糊 隐私"),
        Spec("security", "紧急", "隐藏窗口", "Ctrl+Alt+H,任务栏也看不到", action="隐藏", set=w.hide_window,
             close_first=True, keys="老板键"),
        Spec("security", "紧急", "清空记录并隐藏", "Ctrl+Alt+X,清空聊天记录、剪贴板,然后隐藏", action="清空…",
             set=w.panic, danger=True, close_first=True, keys="紧急 销毁"),
        Spec("security", "说明", "安全说明", "加密方式、能防什么、不能防什么", action="查看", set=w.show_security),
        # ---------------------------------------------------------------- 更新
        Spec("update", "版本", "当前版本", kind="info", get=lambda: f"v{VERSION}"),
        Spec("update", "版本", "更新状态", kind="button", get=update_line, set=update_action,
             action=update_label, keys="新版本 下载 安装 局域网"),
        Spec("update", "版本", "自动更新", "只在局域网里互相传,不连外网", "choice",
             get=lambda: w.update_mode, set=w.set_update_mode, options=UPDATE_MODES),
        Spec("update", "版本", "全部更新记录", "每个版本改了什么", action="查看…", set=w.show_changelog,
             keys="更新内容 changelog"),
        # ---------------------------------------------------------------- 数据
        Spec("data", "位置", "数据文件夹", kind="button", get=w.data_folder, action="打开", set=w.open_data_folder),
        Spec("data", "位置", "数据管理", "占用多少、单独清理、便携模式", action="打开…", set=w.show_data,
             keys="清理 占用 便携"),
        Spec("data", "诊断", "诊断信息和出错记录", "启动自检的结果、最近的出错", action="查看…",
             set=w.show_diagnostics, keys="出错 错误 自检"),
        Spec("data", "卸载", "卸载密语", "启动独立轻量卸载程序（可选保留或彻底清空本地聊天记录与跨网内核）", action="卸载…",
             set=w.launch_uninstaller, danger=True, close_first=True, keys="卸载 删除 移除 uninstall"),
    ]


class ChoiceButton(QPushButton):
    """下拉选择:点一下弹出(淡入的)菜单,当前值打勾。比原生下拉框更贴合整体风格。"""
    chosen = Signal(object)

    def __init__(self, options, fixed_text: str = "") -> None:
        super().__init__()
        self.setObjectName("choiceBtn")
        self.options = list(options or [])
        self.fixed_text = fixed_text                    # 有它 = 纯菜单按钮(比如「播放 ▾」),不显示当前值、不打勾
        self.value = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if fixed_text:
            self.setText(fixed_text)
        else:
            self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)     # 箭头在右边
            self.setIcon(icon("chevron_down", T["sub"], 14))
            self.setMinimumWidth(150)
        self.clicked.connect(self.open_menu)

    def set_value(self, value) -> None:
        self.value = value
        if self.fixed_text:
            return
        text = next((o[1] for o in self.options if o[0] == value), None)
        if text is None and self.options:
            text = self.options[0][1]
        self.setText(text or "")

    def open_menu(self) -> None:
        m = make_menu(self)
        for o in self.options:
            v, t = o[0], o[1]
            a = m.addAction(t)
            if len(o) > 2 and not o[2]:
                a.setEnabled(False)
                continue
            if not self.fixed_text:
                a.setCheckable(True)
                a.setChecked(v == self.value)
            a.triggered.connect(lambda _=False, v=v: self.chosen.emit(v))
        popup(m, self.mapToGlobal(QPoint(0, self.height() + 4)))


class Row(QFrame):
    """一行设置:左边标题和说明,右边控件。"""

    def __init__(self, spec: Spec, dlg: "SettingsDialog", show_cat: bool = False) -> None:
        super().__init__()
        self.spec, self.dlg = spec, dlg
        self.setObjectName("setRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 14, 10)
        lay.setSpacing(12)
        # 注意顺序:先把 col 挂到这一行上,再往里加标签。没有父窗口的控件一旦 setVisible(True)
        # 就会变成一个独立的小窗口在屏幕上闪一下(2.0.0 打开设置时左上角闪「MiYu」小窗口就是这个)
        col = QVBoxLayout()
        col.setSpacing(1)
        lay.addLayout(col, 1)
        title = spec.title
        if show_cat:
            title = f"{dict((c, n) for c, n, _ in CATEGORIES)[spec.cat]} › {title}"
        self.title = label(title, "rowTitle")
        col.addWidget(self.title)
        self.sub = label(spec.sub, "rowSub", wrap=True)
        col.addWidget(self.sub)
        self.ctrl = None
        k = spec.kind
        if k == "switch":
            self.ctrl = motion.Switch(False)
            self.ctrl.toggled.connect(self._on_switch)
        elif k in ("choice", "menu"):
            self.ctrl = ChoiceButton(self._options(), spec.action if k == "menu" else "")
            self.ctrl.chosen.connect(self._on_choice)
        elif k == "button":
            self.ctrl = QPushButton(spec.action if isinstance(spec.action, str) and spec.action else "打开")
            self.ctrl.setObjectName("destructive" if spec.danger else "")
            self.ctrl.setCursor(Qt.CursorShape.PointingHandCursor)
            self.ctrl.clicked.connect(self._on_button)
        elif k == "buttons":
            self.ctrl = QWidget()
            bl = QHBoxLayout(self.ctrl)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            for text, fn in spec.options or []:
                b = QPushButton(text)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _=False, fn=fn: self.dlg.run(fn, False))
                bl.addWidget(b)
        if self.ctrl is not None:
            lay.addWidget(self.ctrl, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh()

    def _options(self) -> list:
        o = self.spec.options
        try:
            return list(o() if callable(o) else o or [])
        except Exception:                                   # noqa: BLE001
            return []

    def refresh(self) -> None:
        s = self.spec
        on = s.is_enabled()
        if s.kind in ("button", "info") and s.get is not None:
            try:
                value = str(s.get())
            except Exception:                               # noqa: BLE001
                value = ""
            self.sub.setText(value + (f" · {s.sub}" if s.sub and value else s.sub if not value else ""))
        self.sub.setVisible(bool(self.sub.text()))
        if self.ctrl is None:
            return
        if s.kind == "button" and callable(s.action):
            try:
                self.ctrl.setText(s.action())
            except Exception:                               # noqa: BLE001
                pass
        self.ctrl.setEnabled(on)
        self.title.setEnabled(on)
        if s.kind == "switch":
            try:
                self.ctrl.set_quiet(bool(s.get()))
            except Exception:                               # noqa: BLE001
                pass
        elif s.kind == "choice":
            self.ctrl.setIcon(icon("chevron_down", T["sub"], 14))
            if callable(s.options):
                self.ctrl.options = self._options()
            try:
                cur = s.get()
            except Exception:                               # noqa: BLE001
                cur = None
            self.ctrl.set_value(cur)

    def _on_switch(self, on: bool) -> None:
        try:
            if bool(self.spec.get()) == on:                 # 状态本来就是这样(比如刷新时),不重复执行
                return
        except Exception:                                   # noqa: BLE001
            pass
        self.dlg.run(lambda: self.spec.set(on), False)

    def _on_choice(self, value) -> None:
        self.dlg.run(lambda: self.spec.set(value), False)

    def _on_button(self) -> None:
        self.dlg.run(self.spec.set, self.spec.close_first)


class SettingsDialog(Dialog):
    def __init__(self, win, cat: str = "account", query: str = "") -> None:
        super().__init__(win, "设置")
        self.win = win
        self.setObjectName("settings")
        self.resize(860, 620)
        self.setMinimumSize(720, 480)
        self.specs = build_specs(win)
        self.rows: list[Row] = []                          # 各分类页里的行(一直在)
        self.result_rows: list[Row] = []                   # 当前搜索结果页里的行(每次搜索重建)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # 左边:标题、搜索、分类
        side = QFrame()
        side.setObjectName("setSide")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 22, 12, 16)
        sl.setSpacing(10)
        sl.addWidget(label("设置", "dialogTitle"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索设置")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", T["faint"], 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._on_search)
        sl.addWidget(self.search)
        self.nav = QListWidget()
        self.nav.setObjectName("setNav")
        for key, name, ic in CATEGORIES:
            it = QListWidgetItem(icon(ic, T["icon"], 18), name)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(it)
        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.itemClicked.connect(lambda it: self._on_nav(self.nav.row(it), force=True))   # 搜索时点同一个分类也能回去
        sl.addWidget(self.nav, 1)
        sl.addWidget(label(f"密语 v{VERSION}", "faint"))
        root.addWidget(side)
        # 右边:每个分类一页 + 搜索结果页
        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        for key, name, _ic in CATEGORIES:
            page = self._page(name, [s for s in self.specs if s.cat == key])
            self.pages[key] = page
            self.stack.addWidget(page)
        self.result_page = QWidget()
        self.stack.addWidget(self.result_page)
        root.addWidget(self.stack, 1)
        keys = [c[0] for c in CATEGORIES]
        self.nav.setCurrentRow(keys.index(cat) if cat in keys else 0)
        if query:
            self.search.setText(query)

    # ---- 页面
    def _page(self, title: str, specs: list[Spec], show_cat: bool = False, empty: str = "",
              into: list | None = None) -> QScrollArea:
        area = QScrollArea()
        area.setObjectName("setPage")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("setInner")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(26, 24, 26, 24)
        lay.setSpacing(8)
        lay.addWidget(label(title, "pageTitle"))
        groups: list[tuple[str, list[Spec]]] = []
        for s in specs:
            key = f"{s.cat}/{s.group}" if show_cat else s.group
            if not groups or groups[-1][0] != key:
                groups.append((key, []))
            groups[-1][1].append(s)
        for key, items in groups:
            if not show_cat:
                lay.addSpacing(6)
                lay.addWidget(label(key, "section"))
            card = QFrame()
            card.setObjectName("plainCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 4, 0, 4)
            cl.setSpacing(0)
            for i, s in enumerate(items):
                if i:
                    cl.addWidget(hline())
                row = Row(s, self, show_cat)
                (self.rows if into is None else into).append(row)
                cl.addWidget(row)
            lay.addWidget(card)
        if not specs and empty:
            lay.addWidget(label(empty, "hint", wrap=True))
        lay.addStretch(1)
        area.setWidget(inner)
        return area

    def _on_nav(self, i: int, force: bool = False) -> None:
        if i < 0 or force and not self.search.text():
            return
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        key = CATEGORIES[i][0]
        self._show(self.pages[key])

    def _show(self, page: QWidget) -> None:
        if self.stack.currentWidget() is page:
            return
        before = motion.snapshot(self.stack)
        self.stack.setCurrentWidget(page)
        motion.crossfade(self.stack, before, 160)           # 换页:旧页淡出

    def matches(self, q: str) -> list[Spec]:
        q = q.strip().lower()
        if not q:
            return []
        words = q.split()
        return [s for s in self.specs if all(wd in s.text().lower() for wd in words)]

    def _on_search(self, text: str) -> None:
        q = text.strip()
        if not q:
            i = self.nav.currentRow()
            self._show(self.pages[CATEGORIES[max(0, i)][0]])
            return
        found = self.matches(q)
        old = self.result_page
        self.result_rows = []
        self.result_page = self._page(f"搜索「{q}」", found, show_cat=True,
                                      empty="没有找到相关的设置。试试别的词,比如「主题」「提示音」「密码」。",
                                      into=self.result_rows)
        idx = self.stack.indexOf(old)
        self.stack.insertWidget(idx, self.result_page)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.setCurrentWidget(self.result_page)

    # ---- 执行
    def run(self, fn, close_first: bool) -> None:
        """执行一项设置。会关掉窗口的(注销、隐藏…)先关设置窗口。之后整页重新读一遍状态。"""
        if close_first:
            self.accept()
            QTimer.singleShot(0, fn)
            return
        fn()
        QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        for i, (_key, _name, ic) in enumerate(CATEGORIES):         # 在这里换了主题,图标颜色跟着变
            it = self.nav.item(i)
            if it is not None:
                it.setIcon(icon(ic, T["icon"], 18))
        for rows in (self.rows, self.result_rows):
            for r in list(rows):
                try:
                    r.refresh()
                except RuntimeError:                        # 控件已被删掉
                    rows.remove(r)


class SettingsMixin:
    """左下角的齿轮:打开设置窗口。"""

    def show_settings(self, cat: str = "account", query: str = "") -> None:
        SettingsDialog(self, cat, query).exec()
        self.save_account()
