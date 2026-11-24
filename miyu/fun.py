"""
密语 · 打字互动
- TypingPet:趴在输入框上的小动物(小猫 / 小兔 / 小熊,原创造型,全部用代码画)。
  每打一个字左右爪轮流拍一下;发送时跳起来;收到消息耳朵抖一抖;太久不打字会睡着;
  打得飞快时眼睛变成 > <,头顶出现连击数。
- EffectLayer:盖在聊天区上的透明特效层。打字火花、删除碎片、发送光点,
  以及关键词全屏特效(气球、彩带、烟花、雪、爱心、雨、星星、火苗、表情雨)。
- TypingBubble:私聊里对方正在输入时,聊天底部那个三个点跳动的小气泡。
所有动画只在需要时才跑,窗口隐藏时自动停。
"""
from __future__ import annotations

import math
import random
import re
import time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient,
    QTextOption,
)
from PySide6.QtWidgets import QWidget

from .petcare import (
    BORED, EXPR_BY_ID, FEED_XP, FEED_XP_DAILY, FOOD_BY_ID, FOOD_DECAY, FORMS, HUNGRY, JOY_DECAY, PLAY_XP, PLAY_XP_DAILY,
    TOY_BY_ID, clamp, form_of,
)
from .theme import T, qcolor

OUTLINE = "#4A3B32"
SPECIES = {
    "cat": {"label": "小猫", "body": "#FFE2C4", "inner": "#FFB8A8"},
    "bunny": {"label": "小兔", "body": "#FFFFFF", "inner": "#FFC2CF"},
    "bear": {"label": "小熊", "body": "#E2BC94", "inner": "#C99A70"},
}

# ---------------------------------------------------------------- 宠物养成
PET_MAX_LEVEL = 50
DEFAULT_PET_NAME = "团团"
XP_PER_KEY = 1
XP_PER_MESSAGE = 6
# (id, 名字, 解锁等级, 部位) —— 同一个部位一次只能戴一件
ACCESSORIES = [
    ("bow", "蝴蝶结", 2, "ear"),
    ("party", "派对帽", 3, "head"),
    ("bell", "铃铛项圈", 3, "neck"),
    ("scarf", "围巾", 4, "neck"),
    ("flower", "小花", 5, "ear"),
    ("beanie", "毛线帽", 6, "head"),
    ("strawhat", "草帽", 7, "head"),
    ("glasses", "墨镜", 8, "face"),
    ("bowtie", "领结", 9, "neck"),
    ("crown", "皇冠", 10, "head"),
    ("hoodie", "小卫衣", 11, "body"),
    ("headphones", "耳机", 12, "head"),
    ("sailor", "水手服", 14, "body"),
    ("halo", "天使光环", 15, "top"),
    ("cape", "小披风", 17, "body"),
    # 2.4 新增
    ("sprout", "头顶小芽", 4, "top"),
    ("blush", "腮红贴纸", 5, "face"),
    ("nerd", "圆框眼镜", 6, "face"),
    ("cherry", "樱桃发夹", 7, "ear"),
    ("starclip", "星星发卡", 10, "ear"),
    ("tie", "小领带", 12, "neck"),
    ("chef", "厨师帽", 13, "head"),
    ("raincoat", "小雨衣", 13, "body"),
    ("monocle", "单片眼镜", 16, "face"),
    ("witch", "魔法帽", 16, "head"),
    ("pearl", "珍珠项链", 18, "neck"),
    ("overalls", "背带裤", 19, "body"),
    ("santa", "圣诞帽", 21, "head"),
    ("cloud", "小雨云", 22, "top"),
    ("horns", "小龙角", 25, "head"),
    ("fairy", "精灵翅膀", 27, "body"),
    ("aurora", "极光星环", 30, "top"),
    # 2.5 新增:手持 / 特效两个新部位,以及套装
    ("balloon", "小气球", 3, "hand"),
    ("icecream", "冰淇淋", 6, "hand"),
    ("wand", "魔法棒", 8, "hand"),
    ("hearts", "爱心泡泡", 9, "fx"),
    ("apron", "小围裙", 11, "body"),
    ("spatula", "小锅铲", 14, "hand"),
    ("bubbles", "肥皂泡泡", 15, "fx"),
    ("giftbox", "礼物盒", 17, "hand"),
    ("snowfall", "小雪花", 21, "fx"),
    ("pirate", "海盗帽", 23, "head"),
    ("eyepatch", "海盗眼罩", 24, "face"),
    ("sword", "玩具剑", 26, "hand"),
    ("kanzashi", "樱花发簪", 27, "ear"),
    ("fan", "小团扇", 29, "hand"),
    ("kimono", "樱花和服", 31, "body"),
    ("petals", "樱花雨", 33, "fx"),
    ("fireflies", "萤火虫", 35, "fx"),
    ("astro", "宇航头盔", 38, "head"),
    ("jetpack", "喷气背包", 42, "body"),
    ("stardust", "星尘", 46, "fx"),
    ("sparkle", "魔法光点", 48, "fx"),
]
# 套装:(id, 名字, 部件, 集齐后的光效颜色)。一键穿上,集齐有一圈套装光效
OUTFITS = [
    ("mage", "魔法师", ("witch", "wand", "cape", "sparkle"), "#9775FA"),
    ("chef", "小厨师", ("chef", "apron", "spatula", "tie"), "#FFA94D"),
    ("xmas", "圣诞快乐", ("santa", "scarf", "giftbox", "snowfall"), "#FF6B6B"),
    ("pirate", "海盗船长", ("pirate", "eyepatch", "sword", "bowtie"), "#868E96"),
    ("astro", "宇航员", ("astro", "jetpack", "stardust"), "#4DABF7"),
    ("sakura", "樱花和服", ("kanzashi", "kimono", "fan", "petals"), "#F783AC"),
]
OUTFIT_BY_ID = {o[0]: o for o in OUTFITS}
SLOTS = [("head", "头饰"), ("ear", "耳边"), ("face", "脸上"), ("neck", "脖子"), ("body", "衣服"), ("top", "头顶"),
         ("hand", "手持"), ("fx", "特效")]
ACC_BY_ID = {a[0]: a for a in ACCESSORIES}


def xp_for_level(level: int) -> int:
    """升到第 level 级需要的累计经验。Lv2=300,Lv5≈4200,Lv10≈19500。"""
    return 0 if level <= 1 else int(round(300 * (level - 1) ** 1.9))


# 每日成就:(id, 名字, 统计项, 目标, 奖励经验)
DAILY_GOALS = [
    ("early", "今日打卡", "msgs", 1, 20),
    ("typist", "打字达人", "taps", 1000, 50),
    ("keyboard", "键盘侠", "taps", 5000, 150),
    ("chatty", "话痨", "msgs", 100, 80),
    ("petter", "撸宠达人", "pats", 20, 30),
]
STREAK_GOALS = [(3, "连续打卡 3 天", 100), (7, "连续打卡一周", 300), (30, "连续打卡一个月", 1000)]
PAT_XP, PAT_XP_DAILY = 2, 30            # 撸一下 +2 经验,每天最多算 30 下


def _today() -> str:
    return time.strftime("%Y-%m-%d")


MYTHIC_LEVEL = 40                       # 40 级第二次进化:神话期(发光大羽翼 + 星冠)
# 每 5 级学会一个新动作:(等级, id, 名字, 时长)。宠物闲着时偶尔自己表演,右键宠物 →「表演一个」可以点
TRICKS = [
    (5, "stretch", "伸懒腰", 1.6), (10, "spin", "转圈圈", 1.1), (15, "heart", "比心", 1.8), (20, "roll", "打滚", 1.8),
    (25, "wave", "挥手", 1.8), (30, "hop", "蹦蹦跳", 1.5), (35, "dance", "跳舞", 2.6), (40, "fly", "飞起来", 2.4),
    (45, "magic", "变魔术", 2.2), (50, "bow", "鞠躬谢幕", 2.0),
]
TRICK_BY_ID = {t[1]: t for t in TRICKS}
HURT_IMPACT = 0.38                      # 被揍:拳头飞过来到砸中用的时间
HURT_SECS = 5.0                         # 头上的包留多久
WEAPONS = [("fist", "拳头", "👊"), ("pillow", "枕头", "🛏"), ("hammer", "玩具锤", "🔨"), ("flick", "弹脑门", "👆")]
WEAPON_BY_ID = {w[0]: w for w in WEAPONS}
EVOLVE_LEVEL = 20                       # 到 20 级进化:长出小翅膀、额头多一颗宝石
# 打字特效主题:(id, 名字, 解锁等级)。也可以抽卡提前拿到
FX_THEMES = [("spark", "火花", 1), ("sakura", "樱花", 3), ("snow", "雪花", 6), ("star", "星星", 9), ("heart", "爱心", 12)]
FX_BY_ID = {f[0]: f for f in FX_THEMES}

# 抽卡池:(稀有度, 种类, id, 名字)。种类:acc 装扮 / skin 气泡皮肤 / fx 打字特效 / snd 音效主题
GACHA_POOL = [
    ("R", "acc", "bow", "蝴蝶结"), ("R", "acc", "scarf", "围巾"), ("R", "acc", "flower", "小花"),
    ("R", "skin", "jelly", "果冻气泡"), ("R", "skin", "mint", "薄荷气泡"),
    ("R", "fx", "sakura", "樱花特效"), ("R", "fx", "snow", "雪花特效"), ("R", "snd", "muyu", "木鱼音效"),
    ("SR", "acc", "beanie", "毛线帽"), ("SR", "acc", "glasses", "墨镜"), ("SR", "acc", "crown", "皇冠"),
    ("SR", "acc", "headphones", "耳机"), ("SR", "skin", "cloud", "云朵气泡"), ("SR", "skin", "candy", "糖果气泡"),
    ("SR", "skin", "galaxy", "星空气泡"), ("SR", "fx", "star", "星星特效"), ("SR", "fx", "heart", "爱心特效"),
    ("SR", "snd", "8bit", "游戏机音效"), ("SR", "snd", "cat", "猫叫音效"),
    ("SSR", "acc", "halo", "天使光环"), ("SSR", "skin", "gold", "鎏金气泡"), ("SSR", "skin", "rainbow", "彩虹气泡(抽卡限定)"),
    ("R", "acc", "party", "派对帽"), ("R", "acc", "bell", "铃铛项圈"), ("R", "acc", "strawhat", "草帽"),
    ("SR", "acc", "bowtie", "领结"), ("SR", "acc", "hoodie", "小卫衣"), ("SR", "acc", "sailor", "水手服"),
    ("SSR", "acc", "cape", "小披风"),
    ("R", "acc", "sprout", "头顶小芽"), ("R", "acc", "blush", "腮红贴纸"), ("R", "acc", "nerd", "圆框眼镜"),
    ("R", "acc", "cherry", "樱桃发夹"), ("SR", "acc", "starclip", "星星发卡"), ("SR", "acc", "tie", "小领带"),
    ("SR", "acc", "chef", "厨师帽"), ("SR", "acc", "raincoat", "小雨衣"), ("SR", "acc", "monocle", "单片眼镜"),
    ("SR", "acc", "witch", "魔法帽"), ("SR", "acc", "pearl", "珍珠项链"), ("SR", "acc", "overalls", "背带裤"),
    ("SR", "acc", "santa", "圣诞帽"), ("SSR", "acc", "cloud", "小雨云"), ("SSR", "acc", "horns", "小龙角"),
    ("SSR", "acc", "fairy", "精灵翅膀"),
    ("R", "acc", "balloon", "小气球"), ("R", "acc", "icecream", "冰淇淋"), ("SR", "acc", "wand", "魔法棒"),
    ("R", "acc", "hearts", "爱心泡泡"), ("R", "acc", "apron", "小围裙"), ("SR", "acc", "spatula", "小锅铲"),
    ("SR", "acc", "bubbles", "肥皂泡泡"), ("SR", "acc", "giftbox", "礼物盒"), ("SR", "acc", "snowfall", "小雪花"),
    ("SR", "acc", "pirate", "海盗帽"), ("SR", "acc", "eyepatch", "海盗眼罩"), ("SR", "acc", "sword", "玩具剑"),
    ("SR", "acc", "kanzashi", "樱花发簪"), ("SR", "acc", "fan", "小团扇"), ("SSR", "acc", "kimono", "樱花和服"),
    ("SSR", "acc", "petals", "樱花雨"), ("SSR", "acc", "fireflies", "萤火虫"), ("SSR", "acc", "astro", "宇航头盔"),
    ("SSR", "acc", "jetpack", "喷气背包"),
]
GACHA_WEIGHTS = (("N", 55), ("R", 32), ("SR", 11), ("SSR", 2))
GACHA_DUP_XP = {"R": 60, "SR": 150, "SSR": 500}
GACHA_PITY = 10                         # 连续 9 抽没有 SR 以上,第 10 抽必出

# 成就墙:(id, 称号, 怎么拿到, 判断)。拿到后可以把称号挂在名字旁边
BADGES = [
    ("k1k", "初出茅庐", "累计敲击 1,000 次", lambda g: g.taps >= 1000),
    ("k10k", "万字户", "累计敲击 1 万次", lambda g: g.taps >= 10000),
    ("k100k", "键盘大师", "累计敲击 10 万次", lambda g: g.taps >= 100000),
    ("k1m", "人形打字机", "累计敲击 100 万次", lambda g: g.taps >= 1000000),
    ("m100", "话匣子", "累计发送 100 条消息", lambda g: g.messages >= 100),
    ("m1k", "聊天达人", "累计发送 1,000 条消息", lambda g: g.messages >= 1000),
    ("m10k", "金牌话痨", "累计发送 1 万条消息", lambda g: g.messages >= 10000),
    ("lv5", "铲屎官", "宠物升到 Lv.5", lambda g: g.level >= 5),
    ("lv10", "资深铲屎官", "宠物升到 Lv.10", lambda g: g.level >= 10),
    ("lv20", "进化见证者", "宠物升到 Lv.20 并进化", lambda g: g.level >= 20),
    ("lv30", "传说降临", "宠物升到 Lv.30", lambda g: g.level >= 30),
    ("lv40", "神话之羽", "宠物升到 Lv.40,第二次进化", lambda g: g.level >= 40),
    ("lv50", "满级大佬", "宠物升到 Lv.50", lambda g: g.level >= 50),
    ("s3", "三日之约", "连续打卡 3 天", lambda g: g.streak >= 3),
    ("s7", "全勤一周", "连续打卡 7 天", lambda g: g.streak >= 7),
    ("s30", "风雨无阻", "连续打卡 30 天", lambda g: g.streak >= 30),
    ("pat100", "撸宠狂魔", "累计摸宠物 100 次", lambda g: g.counts["pats"] >= 100),
    ("visit1", "串门新手", "宠物去别人家串门 1 次", lambda g: g.counts["visits"] >= 1),
    ("visit10", "社交达人", "宠物去别人家串门 10 次", lambda g: g.counts["visits"] >= 10),
    ("skit1", "小演员", "演出 1 场宠物小剧场", lambda g: g.counts["skits"] >= 1),
    ("skit20", "影帝", "演出 20 场宠物小剧场", lambda g: g.counts["skits"] >= 20),
    ("gacha10", "抽卡爱好者", "抽卡 10 次", lambda g: g.counts["draws"] >= 10),
    ("ssr", "欧皇", "抽到一次 SSR", lambda g: g.counts["ssr"] >= 1),
    ("friend", "知己", "和一位朋友的宠物成为挚友", lambda g: any(f.get("v", 0) >= 100 for f in g.friends.values())),
    ("night", "夜猫子", "凌晨 0 点到 5 点发过消息", lambda g: g.counts["night"] >= 1),
    ("feed50", "美食家", "喂宠物 50 次", lambda g: g.counts["feeds"] >= 50),
    ("play50", "最佳玩伴", "陪宠物玩 50 次", lambda g: g.counts["plays"] >= 50),
    ("dress8", "时尚达人", "解锁 8 件装扮", lambda g: sum(g.is_unlocked(a[0]) for a in ACCESSORIES) >= 8),
    ("dress20", "衣橱满满", "解锁 20 件装扮", lambda g: sum(g.is_unlocked(a[0]) for a in ACCESSORIES) >= 20),
    ("outfit", "套装达人", "穿上一整套套装", lambda g: g.full_outfit() is not None),
    ("gpet10", "群宠之友", "和群友一起把群宠物养到 Lv.10", lambda g: g.counts["gpet"] >= 10),
]
BADGE_BY_ID = {b[0]: b for b in BADGES}
BADGE_XP = 30

FRIEND_LEVELS = [(0, "初识"), (10, "认识"), (30, "朋友"), (60, "好朋友"), (100, "挚友")]
FRIEND_PHOTO = 30                       # 友谊值到 30(朋友)解锁合照
FRIEND_MAX = 100


def friend_level(v: int) -> str:
    name = FRIEND_LEVELS[0][1]
    for need, n in FRIEND_LEVELS:
        if v >= need:
            name = n
    return name


def diary_text(day: dict) -> str:
    """宠物用自己的口气写一天的日记。day 是那一天的统计。"""
    taps, msgs, pats = day.get("taps", 0), day.get("msgs", 0), day.get("pats", 0)
    parts = []
    if taps == 0 and msgs == 0:
        parts.append("主人今天没怎么聊天,我趴着睡了一整天。")
    else:
        if taps >= 5000:
            parts.append(f"主人今天敲了 {taps:,} 下键盘,我的爪子都拍麻了!")
        elif taps >= 1000:
            parts.append(f"今天陪主人敲了 {taps:,} 下键盘,是充实的一天。")
        else:
            parts.append(f"今天只敲了 {taps:,} 下键盘,有点清闲。")
        if msgs:
            parts.append(f"一共发出去 {msgs} 条消息。")
    if pats >= 20:
        parts.append(f"被摸了 {pats} 次,毛都要秃了……不过很开心。")
    elif pats > 0:
        parts.append(f"被摸了 {pats} 下,嘿嘿。")
    else:
        parts.append("今天一下都没摸我,哼。")
    for who in day.get("visitors", [])[:3]:
        parts.append(f"{who}来我家做客了,我们玩得很开心。")
    for who in day.get("visited", [])[:3]:
        parts.append(f"我去{who}家串门了。")
    if day.get("skits"):
        parts.append(f"还演了 {day['skits']} 场小剧场,我觉得我演得最好。")
    if day.get("got_names"):
        parts.append("拿到了成就:" + "、".join(day["got_names"][:4]) + "。")
    if day.get("levelup"):
        parts.append(f"我升到 Lv.{day['levelup']} 了!")
    return "".join(parts)


class PetGrowth:
    """宠物养成数据:经验、等级、名字、装扮、累计敲击数。纯数据,方便保存和测试。"""

    def __init__(self, data: dict | None = None) -> None:
        d = data if isinstance(data, dict) else {}
        try:
            self.xp = max(0, int(d.get("xp", 0)))
            self.taps = max(0, int(d.get("taps", 0)))
            self.messages = max(0, int(d.get("messages", 0)))
        except (TypeError, ValueError):
            self.xp = self.taps = self.messages = 0
        name = d.get("name")
        self.name = name.strip()[:8] if isinstance(name, str) and name.strip() else DEFAULT_PET_NAME
        self.owned = {x for x in (d.get("owned") or []) if isinstance(x, str)}      # 抽卡得到的 "种类:id"
        self.wear: list[str] = []
        for a in d.get("wear") or []:
            if isinstance(a, str) and a in ACC_BY_ID:
                self.toggle(a)
        self.born = float(d.get("born") or time.time())
        daily = d.get("daily") if isinstance(d.get("daily"), dict) else {}
        self.daily = {"date": str(daily.get("date", "")), "got": [g for g in daily.get("got", []) if isinstance(g, str)]}
        for k in ("taps", "msgs", "pats", "skits", "levelup", "feeds", "plays"):
            try:
                self.daily[k] = max(0, int(daily.get(k, 0)))
            except (TypeError, ValueError):
                self.daily[k] = 0
        for k in ("visitors", "visited", "got_names"):
            self.daily[k] = [str(x)[:20] for x in (daily.get(k) or []) if isinstance(x, str)][:10]

        def _int(key: str, src=d) -> int:
            try:
                return max(0, int(src.get(key, 0)))
            except (TypeError, ValueError, AttributeError):
                return 0
        self.tickets = _int("tickets")                 # 抽卡券
        self.gacha_day = str(d.get("gacha_day", ""))
        self.pity = _int("pity")
        cnt = d.get("counts") if isinstance(d.get("counts"), dict) else {}
        self.counts = {k: _int(k, cnt) for k in ("pats", "visits", "skits", "draws", "ssr", "night", "feeds", "plays",
                                                  "gpet")}
        # 照料:饱腹度 / 心情(0~100),随时间慢慢下降
        try:
            self.food = clamp(float(d.get("food", 80)))
            self.joy = clamp(float(d.get("joy", 80)))
            self.care_t = float(d.get("care_t") or time.time())
        except (TypeError, ValueError):
            self.food, self.joy, self.care_t = 80.0, 80.0, time.time()
        self.expr = d.get("expr") if d.get("expr") in EXPR_BY_ID else "normal"
        self.badges = {k: str(v) for k, v in (d.get("badges") or {}).items() if k in BADGE_BY_ID} \
            if isinstance(d.get("badges"), dict) else {}
        self.title = d.get("title") if d.get("title") in self.badges else ""
        self.diary = [{"d": str(e.get("d", "")), "t": str(e.get("t", ""))[:400]}
                      for e in (d.get("diary") or []) if isinstance(e, dict)][-60:]
        self.friends: dict[str, dict] = {}
        for pid, f in (d.get("friends") or {}).items() if isinstance(d.get("friends"), dict) else []:
            if isinstance(pid, str) and isinstance(f, dict):
                self.friends[pid] = {"nick": str(f.get("nick", ""))[:20], "v": min(FRIEND_MAX, _int("v", f)),
                                     "pet": f.get("pet") if isinstance(f.get("pet"), dict) else None}
        try:
            self.streak = max(0, int(d.get("streak", 0)))
        except (TypeError, ValueError):
            self.streak = 0
        self.last_day = str(d.get("last_day", ""))
        self.streak_got = [x for x in (d.get("streak_got") or []) if type(x) is int]
        self.pending: list[tuple[str, int]] = []      # 刚达成、还没显示的成就 (名字, 奖励经验)

    @property
    def level(self) -> int:
        lv = 1
        while lv < PET_MAX_LEVEL and self.xp >= xp_for_level(lv + 1):
            lv += 1
        return lv

    def progress(self) -> tuple[int, int, float]:
        """(本级已获得, 本级总共需要, 比例)。满级时比例为 1。"""
        lv = self.level
        if lv >= PET_MAX_LEVEL:
            return 0, 0, 1.0
        lo, hi = xp_for_level(lv), xp_for_level(lv + 1)
        return self.xp - lo, hi - lo, (self.xp - lo) / max(1, hi - lo)

    def add(self, amount: int) -> int:
        """加经验,返回升了几级。"""
        before = self.level
        self.xp += max(0, int(amount))
        return self.level - before

    def _roll_day(self, today: str | None = None) -> None:
        today = today or _today()
        if self.daily["date"] == today:
            return
        old = self.daily
        if old.get("date") and (old.get("taps") or old.get("msgs") or old.get("pats") or old.get("visitors")
                                or old.get("visited") or old.get("skits")):
            self.diary = (self.diary + [{"d": old["date"], "t": diary_text(old)}])[-60:]
        self.daily = {"date": today, "taps": 0, "msgs": 0, "pats": 0, "got": [], "skits": 0, "levelup": 0,
                      "visitors": [], "visited": [], "got_names": [], "feeds": 0, "plays": 0}

    def _check(self, today: str | None = None) -> None:
        """检查今天的成就和连续打卡。达成的放进 pending,经验直接加上。"""
        for gid, name, key, goal, xp in DAILY_GOALS:
            if gid not in self.daily["got"] and self.daily[key] >= goal:
                self.daily["got"].append(gid)
                self.daily["got_names"].append(name)
                self.xp += xp
                self.pending.append((name, xp))
        today = today or _today()
        if self.daily["msgs"] >= 1 and self.last_day != today:
            import datetime as _dt
            try:
                yesterday = (_dt.date.fromisoformat(today) - _dt.timedelta(days=1)).isoformat()
            except ValueError:
                yesterday = ""
            self.streak = self.streak + 1 if self.last_day == yesterday else 1
            self.last_day = today
            for days, name, xp in STREAK_GOALS:
                if self.streak >= days and days not in self.streak_got:
                    self.streak_got.append(days)
                    self.xp += xp
                    self.pending.append((name, xp))
        self.check_badges(today)

    def check_badges(self, today: str | None = None) -> None:
        """成就墙:新达成的记下日期,送一点经验。"""
        for bid, title, _desc, ok in BADGES:
            if bid not in self.badges and ok(self):
                self.badges[bid] = today or _today()
                self.xp += BADGE_XP
                self.pending.append((f"新称号「{title}」", BADGE_XP))

    def title_text(self) -> str:
        b = BADGE_BY_ID.get(self.title or "")
        return b[1] if b and self.title in self.badges else ""

    @property
    def evolved(self) -> bool:
        return self.level >= EVOLVE_LEVEL

    # ---- 拥有的东西(等级解锁或抽卡得到)
    def has(self, kind: str, iid: str, need_level: int = 999) -> bool:
        return self.level >= need_level or f"{kind}:{iid}" in self.owned

    # ---- 抽卡
    def grant_daily(self, today: str | None = None) -> bool:
        """每天第一次打开送一张抽卡券。"""
        today = today or _today()
        if self.gacha_day == today:
            return False
        self.gacha_day = today
        self.tickets += 1
        return True

    def draw(self, rng=None) -> dict | None:
        if self.tickets <= 0:
            return None
        rng = rng or random.SystemRandom()
        self.tickets -= 1
        self.counts["draws"] += 1
        self.pity += 1
        roll, acc, rarity = rng.random() * 100, 0.0, "N"
        for name, wgt in GACHA_WEIGHTS:
            acc += wgt
            if roll < acc:
                rarity = name
                break
        if self.pity >= GACHA_PITY and rarity in ("N", "R"):
            rarity = "SR"
        if rarity in ("SR", "SSR"):
            self.pity = 0
        if rarity == "N":
            xp = rng.choice((30, 30, 50, 80))
            self.xp += xp
            res = {"rarity": "N", "kind": "xp", "id": "", "name": f"小鱼干(+{xp} 经验)", "new": False, "xp": xp}
        else:
            _r, kind, iid, name = rng.choice([it for it in GACHA_POOL if it[0] == rarity])
            key = f"{kind}:{iid}"
            if key in self.owned:
                xp = GACHA_DUP_XP[rarity]
                self.xp += xp
                res = {"rarity": rarity, "kind": kind, "id": iid, "name": name, "new": False, "xp": xp}
            else:
                self.owned.add(key)
                res = {"rarity": rarity, "kind": kind, "id": iid, "name": name, "new": True, "xp": 0}
            if rarity == "SSR":
                self.counts["ssr"] += 1
        self.check_badges()
        return res

    # ---- 友谊值
    def add_friend(self, pid: str, nick: str, amount: int, pet: dict | None = None) -> tuple[str, str]:
        """加友谊值。返回 (之前的关系, 现在的关系),两者不同就是升级了。"""
        f = self.friends.get(pid)
        if f is None:
            if len(self.friends) >= 100:
                low = min(self.friends, key=lambda k: self.friends[k]["v"])
                self.friends.pop(low, None)
            f = self.friends[pid] = {"nick": nick[:20], "v": 0, "pet": None}
        before = friend_level(f["v"])
        f["v"] = min(FRIEND_MAX, f["v"] + max(0, int(amount)))
        f["nick"] = nick[:20] or f["nick"]
        if pet:
            f["pet"] = pet
        self.check_badges()
        return before, friend_level(f["v"])

    def note_visit(self, kind: str, who: str) -> None:
        """记进今天的日记:kind = visitors(来做客)/ visited(去串门)/ skits(小剧场)。"""
        self._roll_day()
        if kind == "skits":
            self.daily["skits"] += 1
            self.counts["skits"] += 1
        else:
            if who and who not in self.daily[kind]:
                self.daily[kind].append(who[:20])
            if kind == "visited":
                self.counts["visits"] += 1
        self.check_badges()

    def today_diary(self) -> str:
        self._roll_day()
        return diary_text(self.daily)

    def tap(self, today: str | None = None) -> int:
        before = self.level
        self._roll_day(today)
        self.taps += 1
        self.daily["taps"] += 1
        self.xp += XP_PER_KEY
        self._check(today)
        return self.level - before

    def sent(self, today: str | None = None, hour: int | None = None) -> int:
        before = self.level
        self._roll_day(today)
        if (time.localtime().tm_hour if hour is None else hour) < 5:
            self.counts["night"] += 1
        self.messages += 1
        self.daily["msgs"] += 1
        self.xp += XP_PER_MESSAGE
        self._check(today)
        return self.level - before

    def pat(self, today: str | None = None) -> int:
        before = self.level
        self._roll_day(today)
        self.daily["pats"] += 1
        self.counts["pats"] += 1
        if self.daily["pats"] <= PAT_XP_DAILY:
            self.xp += PAT_XP
        self._check(today)
        return self.level - before

    # ---- 照料:喂食 / 玩耍 / 心情
    def care(self, now: float | None = None) -> None:
        """按经过的时间让饱腹度和心情慢慢下降(关着软件的时候也算,最多算 3 天)。"""
        now = time.time() if now is None else now
        hours = max(0.0, min(72.0, (now - self.care_t) / 3600))
        if hours > 0:
            self.food = clamp(self.food - FOOD_DECAY * hours)
            self.joy = clamp(self.joy - JOY_DECAY * hours)
        self.care_t = now

    def mood_word(self) -> str:
        if self.food < HUNGRY:
            return "饿了"
        if self.joy < BORED:
            return "有点无聊"
        if self.joy >= 70 and self.food >= 50:
            return "很开心"
        return "还不错"

    def can_use(self, kind: str, iid: str) -> bool:
        item = (FOOD_BY_ID if kind == "food" else TOY_BY_ID if kind == "toy" else EXPR_BY_ID).get(iid)
        return item is not None and self.level >= item[-1]

    def feed(self, fid: str, today: str | None = None, now: float | None = None) -> int:
        """喂一次。返回升了几级;-1 = 还没解锁这种食物。"""
        if not self.can_use("food", fid):
            return -1
        before = self.level
        self.care(now)
        self._roll_day(today)
        _id, _n, _e, food, joy, _lv = FOOD_BY_ID[fid]
        self.food = clamp(self.food + food)
        self.joy = clamp(self.joy + joy)
        self.daily["feeds"] += 1
        self.counts["feeds"] += 1
        if self.daily["feeds"] <= FEED_XP_DAILY:
            self.xp += FEED_XP
        self._check(today)
        return self.level - before

    def play(self, tid: str, today: str | None = None, now: float | None = None) -> int:
        if not self.can_use("toy", tid):
            return -1
        before = self.level
        self.care(now)
        self._roll_day(today)
        joy = TOY_BY_ID[tid][3]
        self.joy = clamp(self.joy + joy)
        self.food = clamp(self.food - 4)              # 玩累了会饿一点
        self.daily["plays"] += 1
        self.counts["plays"] += 1
        if self.daily["plays"] <= PLAY_XP_DAILY:
            self.xp += PLAY_XP
        self._check(today)
        return self.level - before

    def cheer(self, amount: float) -> None:
        """摸摸、聊天让心情好一点。"""
        self.care()
        self.joy = clamp(self.joy + amount)

    def set_expr(self, eid: str) -> bool:
        if not self.can_use("expr", eid):
            return False
        self.expr = eid
        return True

    @property
    def form(self) -> tuple[int, str, str]:
        return form_of(self.level)

    @property
    def legendary(self) -> bool:
        return self.level >= 30

    @property
    def mythic(self) -> bool:
        return self.level >= MYTHIC_LEVEL

    def full_outfit(self) -> tuple | None:
        """现在穿着的完整套装(全部部件都穿上了)。"""
        worn = set(self.wear)
        for o in OUTFITS:
            if all(x in worn for x in o[2]):
                return o
        return None

    def wear_outfit(self, oid: str) -> list[str]:
        """一键穿上套装里已经解锁的部件(换掉同部位的其它装扮)。返回还没解锁的部件名字。"""
        o = OUTFIT_BY_ID.get(oid)
        if o is None:
            return []
        missing = []
        for aid in o[2]:
            if self.is_unlocked(aid):
                if aid not in self.wear:
                    self.toggle(aid)
            else:
                missing.append(ACC_BY_ID[aid][1])
        return missing

    def tricks(self) -> list[tuple]:
        """已经学会的动作。"""
        return [t for t in TRICKS if self.level >= t[0]]

    def take_pending(self) -> list[tuple[str, int]]:
        out, self.pending = self.pending, []
        return out

    def is_unlocked(self, aid: str) -> bool:
        a = ACC_BY_ID.get(aid)
        return a is not None and self.has("acc", aid, a[2])

    def unlocked_at(self, level: int) -> list[tuple]:
        return [a for a in ACCESSORIES if a[2] == level]

    def toggle(self, aid: str) -> None:
        """戴上 / 摘下。戴上时自动摘掉同一部位的另一件。"""
        a = ACC_BY_ID.get(aid)
        if a is None:
            return
        if aid in self.wear:
            self.wear.remove(aid)
            return
        if not self.is_unlocked(aid):
            return
        self.wear = [w for w in self.wear if ACC_BY_ID[w][3] != a[3]] + [aid]

    def size(self) -> float:
        """宝宝时期小一点,10 级长到最大。"""
        return min(1.0, 0.80 + 0.02 * (self.level - 1))

    def to_dict(self) -> dict:
        return {"xp": self.xp, "taps": self.taps, "messages": self.messages, "name": self.name,
                "wear": list(self.wear), "born": self.born, "daily": dict(self.daily), "streak": self.streak,
                "last_day": self.last_day, "streak_got": list(self.streak_got), "owned": sorted(self.owned),
                "tickets": self.tickets, "gacha_day": self.gacha_day, "pity": self.pity, "counts": dict(self.counts),
                "badges": dict(self.badges), "title": self.title, "diary": list(self.diary),
                "friends": {k: dict(v) for k, v in self.friends.items()},
                "food": round(self.food, 1), "joy": round(self.joy, 1), "care_t": self.care_t, "expr": self.expr}


SPARK_COLORS = {
    "light": ["#7AA2FF", "#B794F6", "#FF9EBB", "#5CC8F0", "#FFC46B"],
    "dusk": ["#FFC078", "#FF9A7A", "#FFD6A5", "#F59AB8", "#FFE29A"],
    "sakura": ["#FF8FB5", "#FFB3C8", "#E9B8FF", "#FFC46B", "#FF9EBB"],
    "violet": ["#C084FC", "#E879F9", "#F0ABFC", "#A78BFA", "#FDA4AF"],
    "ocean": ["#7DD3FC", "#5EEAD4", "#93C5FD", "#A5F3FC", "#FDE68A"],
    "black": ["#FFFFFF", "#D4D4D8", "#A1A1AA", "#E4E4E7", "#F4F4F5"],
    "dark": ["#5EEAD4", "#7AA2FF", "#C4B5FD", "#93C5FD", "#F9A8D4"],
}
CONFETTI_COLORS = ["#FF6B6B", "#FFB454", "#FFE066", "#63E6BE", "#4DABF7", "#9775FA", "#F783AC"]
BALLOON_COLORS = ["#FF8787", "#FFC078", "#FFE066", "#8CE99A", "#74C0FC", "#B197FC", "#F783AC"]


def _now() -> float:
    return time.monotonic()


def _emoji_font(px: int) -> QFont:
    f = QFont()
    f.setFamilies(["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Segoe UI Symbol"])
    f.setPixelSize(max(6, int(px)))
    return f


_PET_PM: dict = {}


def pet_pixmap(species: str, level: int, wear=(), w: int = 150, h: int = 92):
    """画一张宠物的小图(群里的升级卡片、宠物排行榜用)。同样的种类 / 等级 / 装扮只画一次。"""
    from PySide6.QtGui import QPixmap
    key = (species, int(level), tuple(wear), w, h)
    pm = _PET_PM.get(key)
    if pm is not None:
        return pm
    pet = TypingPet(None)
    pet.set_species(species if species in SPECIES else "cat")
    pet.growth = PetGrowth({"xp": xp_for_level(max(1, min(PET_MAX_LEVEL, int(level))))})
    pet.growth.wear = [x for x in wear if x in ACC_BY_ID][:8]
    pet.show_combo = False
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sc = h / TypingPet.H
    p.scale(sc, sc)
    p.translate(w / sc / 2 - pet._cx(), 0)
    pet._paint_pet(p, pet._t0 + 0.5, "happy")
    p.end()
    pet.deleteLater()
    if len(_PET_PM) > 120:
        _PET_PM.clear()
    _PET_PM[key] = pm
    return pm


def draw_weapon(p: QPainter, weapon: str, s: float) -> None:
    """在原点画揍宠物用的道具(朝右):拳头 / 枕头 / 玩具锤 / 弹脑门的手指 / 宠物的小爪子。"""
    out = QPen(QColor(OUTLINE), max(1.0, s * 0.09))
    out.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    if weapon == "fist":
        p.setPen(out)
        p.setBrush(QColor("#E03131"))                                 # 拳击手套
        p.drawRoundedRect(QRectF(-s * 1.15, -s * 0.45, s * 0.55, s * 0.9), s * 0.15, s * 0.15)
        p.setBrush(QColor("#FA5252"))
        p.drawRoundedRect(QRectF(-s * 0.7, -s * 0.72, s * 1.5, s * 1.4), s * 0.6, s * 0.6)
        p.setBrush(QColor("#FF8787"))
        p.drawEllipse(QPointF(-s * 0.15, s * 0.35), s * 0.42, s * 0.3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 140))
        p.drawEllipse(QPointF(s * 0.25, -s * 0.4), s * 0.22, s * 0.12)
    elif weapon == "pillow":
        p.setPen(out)
        p.setBrush(QColor("#E7F5FF"))
        pil = QPainterPath(QPointF(-s * 1.1, -s * 0.8))
        pil.quadTo(0, -s * 0.55, s * 1.1, -s * 0.8)
        pil.quadTo(s * 0.85, 0, s * 1.1, s * 0.8)
        pil.quadTo(0, s * 0.55, -s * 1.1, s * 0.8)
        pil.quadTo(-s * 0.85, 0, -s * 1.1, -s * 0.8)
        p.drawPath(pil)
        p.setPen(QPen(QColor("#A5D8FF"), max(1.0, s * 0.08)))
        p.drawLine(QPointF(-s * 0.5, -s * 0.2), QPointF(s * 0.5, -s * 0.2))
        p.drawLine(QPointF(-s * 0.5, s * 0.2), QPointF(s * 0.5, s * 0.2))
    elif weapon == "hammer":                                           # 玩具锤:红色锤头、黄色锤面、手柄
        p.setPen(out)
        p.setBrush(QColor("#FFD43B"))
        p.drawRoundedRect(QRectF(-s * 1.4, -s * 0.12, s * 1.3, s * 0.24), s * 0.1, s * 0.1)
        p.setBrush(QColor("#F03E3E"))
        p.drawRoundedRect(QRectF(-s * 0.2, -s * 0.7, s * 0.9, s * 1.4), s * 0.25, s * 0.25)
        p.setBrush(QColor("#FFE066"))
        p.drawRoundedRect(QRectF(s * 0.62, -s * 0.62, s * 0.3, s * 1.24), s * 0.12, s * 0.12)
        p.drawRoundedRect(QRectF(-s * 0.42, -s * 0.62, s * 0.3, s * 1.24), s * 0.12, s * 0.12)
    elif weapon == "flick":                                            # 弹脑门:握拳伸出一根手指
        p.setPen(out)
        p.setBrush(QColor("#FFD8A8"))
        p.drawRoundedRect(QRectF(-s * 0.1, -s * 0.18, s * 1.05, s * 0.36), s * 0.18, s * 0.18)
        p.drawRoundedRect(QRectF(-s * 0.8, -s * 0.5, s * 0.85, s * 1.0), s * 0.35, s * 0.35)
        p.setPen(QPen(QColor(OUTLINE), max(0.8, s * 0.06)))
        for k in (-0.15, 0.15):
            p.drawLine(QPointF(-s * 0.55, s * k), QPointF(-s * 0.15, s * k))
    else:                                                             # paw:宠物的小爪子(反击)
        p.setPen(out)
        p.setBrush(QColor("#FFE2C4"))
        p.drawEllipse(QPointF(0, 0), s * 0.75, s * 0.68)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFB8A8"))
        p.drawEllipse(QPointF(-s * 0.05, s * 0.15), s * 0.32, s * 0.26)
        for dx, dy in ((-0.38, -0.32), (0.0, -0.45), (0.38, -0.32)):
            p.drawEllipse(QPointF(s * dx, s * dy), s * 0.13, s * 0.13)


def star_path(r: float, inner: float = 0.45) -> QPainterPath:
    path = QPainterPath()
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * inner
        pt = QPointF(math.cos(ang) * rr, math.sin(ang) * rr)
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    return path


def heart_path(s: float) -> QPainterPath:
    path = QPainterPath(QPointF(0, s * 0.38))
    path.cubicTo(-s * 0.95, -s * 0.22, -s * 0.48, -s * 0.98, 0, -s * 0.42)
    path.cubicTo(s * 0.48, -s * 0.98, s * 0.95, -s * 0.22, 0, s * 0.38)
    path.closeSubpath()
    return path


# ====================================================================== 关键词 → 特效
EFFECT_RULES = [
    ("balloons", ("生日快乐", "生快", "happy birthday", "🎂", "🎈")),
    ("fireworks", ("新年快乐", "过年好", "烟花", "🎆", "🎇", "happy new year")),
    ("confetti", ("恭喜", "祝贺", "太棒了", "congrat", "🎉", "🎊")),
    ("hearts", ("爱你", "喜欢你", "想你了", "么么哒", "love you", "❤️", "💕", "💖", "😘", "🥰")),
    ("snow", ("下雪", "雪花", "圣诞快乐", "merry christmas", "❄️", "☃️", "⛄")),
    ("rain", ("下雨", "🌧", "☔")),
    ("stars", ("晚安", "good night", "🌙", "✨", "🌟")),
    ("flames", ("加油", "冲冲冲", "冲鸭", "💪")),
]
_WORDY = re.compile(r"[0-9A-Za-z一-鿿]")
_LAUGH = re.compile(r"(哈){6,}|(h){6,}", re.IGNORECASE)        # 「哈哈哈」太常见,要连续 6 个以上才下表情雨


def detect_effect(text: str):
    """根据消息内容返回特效名;单发表情返回 ("emoji", 表情);没有就返回 None。"""
    t = (text or "").strip()
    if not t or len(t) > 300:
        return None
    low = t.lower()
    for name, words in EFFECT_RULES:
        if any(w in low for w in words):
            return name
    if _LAUGH.search(t):
        return "laugh"
    if len(t) <= 12 and not _WORDY.search(t) and any(ord(ch) > 0x2190 for ch in t):
        token = t.split()[0]
        return ("emoji", token if len(token) <= 4 else token[0])
    return None


# ====================================================================== 打字宠物
class TypingPet(QWidget):
    W, H, EDGE = 280, 104, 86         # EDGE = 输入框上边缘在本控件里的 y 坐标(上面留出说话气泡的位置)
    BOX = 110                          # 宠物本体宽度(右侧),左侧放计数

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(self.W, self.H)
        self.species = "cat"
        self.show_combo = True
        self.growth = PetGrowth()
        self._levelup_t = -1e9
        self._levelup_lv = 1
        self._say: tuple[str, float, float] | None = None     # (文字, 开始, 结束)
        self._hearts: list[tuple[float, float]] = []          # 撸的时候飘起来的小爱心 (开始时间, 横向偏移)
        self._pats: list[float] = []
        self._annoyed_t = -1e9
        self._last_miss = _now()
        self.away = ""                     # 出门串门时显示的牌子文字
        self.label = ""                    # 当客人时代替计数器显示的名牌
        self.visitor = False
        self.mirror = False                # 镜像布局:宠物在左边,名牌在右边(群宠物趴在输入框左侧)
        self.bare = False                  # 只画宠物本身(桌面陪伴用,不要计数牌)
        self.centered = False              # 宠物画在正中间(衣橱里的预览)
        self._act: tuple | None = None     # 正在做的动作 (种类, 开始, 结束, 道具表情):eat / play / love
        self._alert_t = -1e9               # 有新消息:头顶冒个"!",举爪招手
        self._cheer_t = -1e9               # 发消息:举起双爪欢呼
        self._hurt: tuple | None = None    # 被揍 (武器, 开始, 结果 hit / dodge / counter)
        self._trick: tuple | None = None   # 正在表演的动作 (id, 开始, 时长)
        self._next_trick = _now() + random.uniform(50, 110)
        self.count = 0
        self.combo = 0
        self.best_combo = 0
        now = _now()
        self._t0 = now
        self._last_key = now - 3.0
        self._paw = 0
        self._press_t = -1e9
        self._both_t = -1e9              # 空格:两只爪子一起拍
        self._happy_t = -1e9
        self._ear_t = -1e9
        self._surprise_t = -1e9
        self._combo_t = -1e9
        self._blink_until = 0.0
        self._next_blink = now + random.uniform(2.0, 5.0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(90)

    # ---- 外部调用
    def tap(self, kind: str = "char") -> None:
        now = _now()
        gap = now - self._last_key
        self.combo = self.combo + 1 if gap < 0.7 else 1
        self.best_combo = max(self.best_combo, self.combo)
        if self.combo >= 5:
            self._combo_t = now
        if kind == "delete":
            self._surprise_t = now
        if kind in ("space", "enter"):
            self._both_t = now
        self._last_key = now
        self._paw ^= 1
        self._press_t = now
        self.count += 1
        self._speed(33)
        self.update()

    def celebrate(self) -> None:
        self._happy_t = _now()
        self._speed(33)
        self.update()

    def act(self, kind: str, glyph: str = "", secs: float = 2.0) -> None:
        """做一个动作:eat(抱着食物啃)/ play(看着玩具蹦)/ love(爱心眼)。"""
        now = _now()
        self._act = (kind, now, now + secs, glyph)
        self._last_key = max(self._last_key, now - 2.0)        # 醒过来
        self._speed(33)
        self.update()

    def acting(self, now: float | None = None) -> str:
        now = _now() if now is None else now
        return self._act[0] if self._act and now < self._act[2] else ""

    def alert(self) -> None:
        """收到别的会话的消息:头顶冒"!",耳朵竖起来,举爪招手。"""
        now = _now()
        self._alert_t = now
        self._ear_t = now
        self._last_key = max(self._last_key, now - 2.0)
        self._speed(33)
        self.update()

    def cheer(self) -> None:
        """发消息时:跳一下,举起双爪,飘一颗小爱心。"""
        now = _now()
        self._cheer_t = now
        self._happy_t = now
        self._hearts.append((now + 0.1, random.uniform(-10, 10)))
        self._speed(33)
        self.update()

    def perk(self) -> None:
        self._ear_t = _now()
        self._speed(33)
        self.update()

    def say(self, text: str, secs: float = 3.5) -> None:
        now = _now()
        self._say = (text, now, now + secs)
        self._speed(33)
        self.update()

    def pat(self) -> str:
        """被点了一下。返回这次的反应:heart / purr / wiggle / annoyed。"""
        now = _now()
        self._pats = [t for t in self._pats if now - t < 2.5] + [now]
        self._last_key = max(self._last_key, now - 2.0)        # 醒过来
        if len(self._pats) >= 6:
            self._annoyed_t = now
            self._pats = []
            self.say(random.choice(("别戳啦!", "再戳要生气了 >_<", "痒死啦!")), 1.8)
            return "annoyed"
        kind = random.choice(("heart", "heart", "purr", "wiggle"))
        if kind == "heart":
            self._happy_t = now
            for _ in range(3):
                self._hearts.append((now + random.uniform(0, 0.25), random.uniform(-14, 14)))
        elif kind == "purr":
            self._happy_t = now
            self.say(random.choice(("呼噜呼噜~", "嘿嘿~", "最喜欢你啦", "再摸摸~")), 1.8)
        else:
            self._ear_t = now
            self._happy_t = now
        self._speed(33)
        self.update()
        return kind

    def touch(self) -> None:
        """有动静(发了消息等):别睡了。"""
        self._last_key = max(self._last_key, _now() - 2.0)

    def level_up(self, level: int) -> None:
        self._levelup_t = _now()
        self._levelup_lv = level
        self.celebrate()
        self._happy_t = _now() + 0.8          # 升级时开心得久一点

    def set_species(self, name: str) -> None:
        if name in SPECIES:
            self.species = name
            self.update()

    # ---- 状态
    def mood(self, now: float | None = None) -> str:
        now = _now() if now is None else now
        h = self._hurt
        if h is not None:
            t = now - h[1]
            if h[2] == "hit" and HURT_IMPACT < t < HURT_IMPACT + (1.2 if h[0] in ("pillow", "flick") else 2.2):
                return "dizzy"
            if h[2] in ("dodge", "counter") and t < 1.4:
                return "focus"
        if now - self._annoyed_t < 1.4:
            return "annoyed"
        kind = self.acting(now)
        if kind in ("eat", "play"):
            return "happy"
        if kind == "love":
            return "love"
        if now - self._happy_t < 1.1:
            return "happy"
        if now - self._surprise_t < 0.3:
            return "surprise"
        if self.combo >= 15 and now - self._last_key < 0.8:
            return "focus"
        if now - self._last_key > 25 and now - self._ear_t > 1.5:
            return "sleep"
        if now < self._blink_until:
            return "blink"
        return "idle"

    def combo_visible(self, now: float | None = None) -> bool:
        now = _now() if now is None else now
        return self.show_combo and self.combo >= 5 and now - self._last_key < 1.2

    def _speed(self, ms: int) -> None:
        if self.timer.interval() != ms:
            self.timer.setInterval(ms)

    def _tick(self) -> None:
        if not self.isVisible():
            return
        now = _now()
        if now >= self._next_blink:
            self._blink_until = now + 0.13
            self._next_blink = now + random.uniform(2.5, 6.0)
        if now - self._last_key > 1.2:
            self.combo = 0
        if (not self.visitor and not self.away and now - self._last_key > 600 and now - self._last_miss > 900):
            self._last_miss = now                   # 十分钟没动静:想你了
            self.say("梦到你了…💭" if self.mood(now) == "sleep" else random.choice(("想你了…💭", "你在干嘛呀?", "陪我聊聊天嘛")), 6)
        if self._say and now > self._say[2]:
            self._say = None
        self._hearts = [h for h in self._hearts if now - h[0] < 1.4]
        if self._act and now > self._act[2]:
            self._act = None
        if self._trick and now > self._trick[1] + self._trick[2]:
            self._trick = None
        if (now >= self._next_trick and not self.visitor and not self.away and self._trick is None
                and now - self._last_key > 8 and self.growth.tricks() and self.mood(now) != "sleep"):
            self._next_trick = now + random.uniform(70, 150)       # 闲着时偶尔自己表演一个学会的动作
            self.trick(random.choice(self.growth.tricks())[1])
        active = (now - self._last_key < 1.0 or now - self._happy_t < 1.2 or now - self._ear_t < 0.9
                  or now < self._blink_until + 0.05 or now - self._surprise_t < 0.4 or now - self._levelup_t < 2.2
                  or "halo" in self.growth.wear or self._hearts or now - self._annoyed_t < 1.5
                  or self.growth.evolved or self._act is not None or now - self._alert_t < 1.8
                  or now - self._cheer_t < 0.8
                  or (self._hurt is not None and now - self._hurt[1] < HURT_SECS)
                  or self._trick is not None
                  or any(ACC_BY_ID.get(w, ("", "", 0, ""))[3] == "fx" for w in self.growth.wear)
                  or self.growth.full_outfit() is not None)
        self._speed(33 if active else (240 if self.mood(now) == "sleep" else 90))
        self.update()

    # ---- 绘制
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        now = _now()
        mood = self.mood(now)
        if self.bare:
            pass
        elif self.label:
            self._paint_label(p)
        else:
            self._paint_counter(p, now)
        if self.away:
            self._paint_away(p)
        else:
            self._paint_pet(p, now, mood)
            self._paint_hearts(p, now)
        self._paint_say(p, now)
        p.end()

    def _cx(self) -> float:
        if self.centered:
            return self.W / 2
        return 55.0 if self.mirror else self.W - self.BOX + 55

    def _tag_rect(self, w: float) -> QRectF:
        """名牌 / 计数牌的位置:平时在宠物左边,镜像时在右边。"""
        if self.mirror:
            return QRectF(self.BOX - 6, self.EDGE - 23, w, 20)
        right = self.W - self.BOX + 6
        return QRectF(right - w, self.EDGE - 23, w, 20)

    def _paint_label(self, p: QPainter) -> None:
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(self.label) + 20
        rect = self._tag_rect(w)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFE8A3"))
        p.drawRoundedRect(rect, 10, 10)
        p.setFont(f)
        p.setPen(QColor("#6B4E00"))
        p.drawText(rect, self.label, QTextOption(Qt.AlignmentFlag.AlignCenter))

    def _paint_away(self, p: QPainter) -> None:
        """出门串门:原地立一块小木牌。"""
        cx = self._cx()
        f = QFont(self.font())
        f.setPixelSize(10)
        f.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(f)
        w = max(64, fm.horizontalAdvance(self.away) + 18)
        p.setPen(QPen(QColor("#8B5A2B"), 2.2))
        p.drawLine(QPointF(cx, self.EDGE - 14), QPointF(cx, self.EDGE + 1))
        board = QRectF(cx - w / 2, self.EDGE - 34, w, 21)
        p.setPen(QPen(QColor("#8B5A2B"), 1.4))
        p.setBrush(QColor("#E9C088"))
        p.drawRoundedRect(board, 4, 4)
        p.setFont(f)
        p.setPen(QColor("#5A3A16"))
        p.drawText(board, self.away, QTextOption(Qt.AlignmentFlag.AlignCenter))

    def _paint_hearts(self, p: QPainter, now: float) -> None:
        cx = self._cx()
        for t0, dx in self._hearts:
            t = now - t0
            if t < 0:
                continue
            a = max(0.0, 1.0 - t / 1.4)
            c = QColor("#FF6B8A")
            c.setAlphaF(a)
            p.save()
            p.translate(cx + dx + math.sin(t * 6 + dx) * 3, self.EDGE - 40 - t * 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawPath(heart_path(7 + t * 2))
            p.restore()

    def _paint_say(self, p: QPainter, now: float) -> None:
        """说话气泡:在宠物头的左上方,小尾巴指向宠物。"""
        if not self._say:
            return
        text, t0, t1 = self._say
        a = min(1.0, (now - t0) / 0.15, max(0.0, (t1 - now) / 0.3))
        if a <= 0:
            return
        f = QFont(self.font())
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.Medium)
        fm = QFontMetrics(f)
        maxw = 190
        lines, cur = [], ""
        for ch in text:
            if fm.horizontalAdvance(cur + ch) > maxw - 18:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
        lines = lines[:2]
        tw = max(fm.horizontalAdvance(x) for x in lines)
        lh = fm.height()
        top = self.EDGE - 36 - lh * len(lines) - 10
        if self.mirror:                                   # 镜像:气泡在宠物右上方
            rect = QRectF(self._cx() + 24, top, tw + 18, lh * len(lines) + 10)
        else:
            rect = QRectF(self._cx() - 24 - tw - 18, top, tw + 18, lh * len(lines) + 10)
        p.save()
        p.setOpacity(a)
        bg = QColor("#FFFFFF")
        path = QPainterPath()
        path.addRoundedRect(rect, 11, 11)
        if self.mirror:
            tail = QPainterPath(QPointF(rect.left() + 16, rect.bottom() - 1))
            tail.lineTo(rect.left() - 6, rect.bottom() + 7)
            tail.lineTo(rect.left() + 6, rect.bottom() - 1)
        else:
            tail = QPainterPath(QPointF(rect.right() - 16, rect.bottom() - 1))
            tail.lineTo(rect.right() + 6, rect.bottom() + 7)
            tail.lineTo(rect.right() - 6, rect.bottom() - 1)
        tail.closeSubpath()
        path = path.united(tail)
        p.setPen(QPen(QColor(0, 0, 0, 40), 1))
        p.setBrush(bg)
        p.drawPath(path)
        p.setFont(f)
        p.setPen(QColor("#2D2D33"))
        for i, line in enumerate(lines):
            p.drawText(QRectF(rect.left() + 9, rect.top() + 5 + i * lh, tw + 2, lh), line,
                       QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
        p.restore()

    def _paint_counter(self, p: QPainter, now: float) -> None:
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setWeight(QFont.Weight.DemiBold)
        g = self.growth
        lv_text = f"Lv.{g.level}"
        text = f"{lv_text}  {g.taps:,}"
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(text) + 20
        rect = self._tag_rect(w)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(T["system_bg"]))
        p.drawRoundedRect(rect, 10, 10)
        frac = g.progress()[2]                     # 经验进度:药丸里一条细细的进度条
        track = QRectF(rect.left() + 9, rect.bottom() - 3.6, rect.width() - 18, 1.8)
        p.setBrush(qcolor(T["line"]))
        p.drawRoundedRect(track, 0.9, 0.9)
        if frac > 0:
            c = QColor(T["accent"])
            c.setAlphaF(0.9)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(track.left(), track.top(), max(1.8, track.width() * frac), track.height()), 0.9, 0.9)
        p.setFont(f)
        x = rect.left() + 10
        rect = rect.adjusted(0, -1.5, 0, -1.5)          # 文字略往上,给进度条留位置
        p.setPen(QColor(T["accent"]))
        p.drawText(QRectF(x, rect.top(), w, rect.height()), lv_text,
                   QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
        p.setPen(QColor(T["sub"]))
        p.drawText(QRectF(x + fm.horizontalAdvance(lv_text + "  "), rect.top(), w, rect.height()), f"{g.taps:,}",
                   QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
        if self.combo_visible(now):
            c = self.combo
            color = (T["accent"] if c < 10 else "#FFB454" if c < 20 else "#FF8A3D" if c < 40 else "#FF5C5C")
            pop = 1.0 + 0.35 * max(0.0, 1.0 - (now - self._combo_t) / 0.15)
            cf = QFont(self.font())
            cf.setWeight(QFont.Weight.Black)
            cf.setPixelSize(int((15 + min(c, 60) * 0.12) * pop))
            p.setFont(cf)
            label = f"×{c}"
            cr = QRectF(rect.left() - 20, rect.top() - 30, rect.width() + 40, 28)
            p.setPen(QColor(0, 0, 0, 60))
            p.drawText(cr.translated(0, 1.2), label, QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.setPen(QColor(color))
            p.drawText(cr, label, QTextOption(Qt.AlignmentFlag.AlignCenter))

    def _paint_pet(self, p: QPainter, now: float, mood: str) -> None:
        sp = SPECIES.get(self.species, SPECIES["cat"])
        body, inner = QColor(sp["body"]), QColor(sp["inner"])
        out = QPen(QColor(OUTLINE), 1.7)
        out.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        out.setCapStyle(Qt.PenCapStyle.RoundCap)
        jump = 0.0
        if mood == "happy":
            t = (now - self._happy_t) / 0.45
            jump = -7.0 * math.sin(math.pi * min(1.0, t)) if t < 1 else 0.0
        breath = math.sin((now - self._t0) * 2.2) * 0.6 if mood in ("idle", "blink", "sleep") else 0.0
        if now - self._cheer_t < 0.5:
            jump = min(jump, -6.0 * math.sin(math.pi * (now - self._cheer_t) / 0.5))
        if self.acting(now) == "play":                 # 跟着玩具一蹦一蹦
            jump = -abs(math.sin((now - self._act[1]) * 7.0)) * 5.0
        tk = self._trick_motion(now)
        cx = self._cx() + self._hurt_dx(now) + tk["dx"]
        jump += self._hurt_jump(now) + tk["dy"]
        cy = self.EDGE - 8 + jump + breath
        scale = self.growth.size()
        p.save()
        p.translate(cx, self.EDGE)                 # 以趴着的位置为中心缩放:小时候小一点,慢慢长大
        p.scale(scale, scale)
        sq = self._hurt_squash(now)
        if sq:                                     # 挨揍的一瞬间被压扁
            p.scale(1 + sq * 0.14, 1 - sq * 0.2)
        if tk["sx"] != 1.0 or tk["sy"] != 1.0:
            p.scale(tk["sx"], tk["sy"])
        if tk["rot"]:
            p.translate(0, cy - self.EDGE)
            p.rotate(tk["rot"])
            p.translate(0, self.EDGE - cy)
        p.translate(-cx, -self.EDGE)
        wear = set(self.growth.wear)
        wiggle = 0.0
        if now - self._ear_t < 0.8:
            wiggle = math.sin((now - self._ear_t) * 30) * 10 * (1 - (now - self._ear_t) / 0.8)

        if self.growth.legendary:                       # 传说期:身后一圈慢慢呼吸的金色光晕
            self._paint_aura(p, now, cx, cy)
        outfit = self.growth.full_outfit()
        if outfit is not None:                          # 集齐套装:身后一圈套装颜色的光
            self._paint_outfit_glow(p, now, cx, cy, outfit[3])
        # 耳朵 + 身体:只画输入框边缘以上的部分,看起来像趴在后面
        p.save()
        p.setClipRect(QRectF(0, 0, self.W, self.EDGE + 0.5))
        if "cape" in wear:                               # 披风在身体后面,两侧露出来
            self._acc_cape(p, cx, cy, out)
        if "fairy" in wear:
            self._acc_fairy(p, now, cx, cy)
        if "jetpack" in wear:
            self._acc_jetpack(p, now, cx, cy)
        p.setPen(out)
        for s in (-1, 1):
            p.save()
            pivot = QPointF(cx + s * 14, cy - 18)
            p.translate(pivot)
            p.rotate(s * wiggle)
            p.translate(-pivot)
            if self.species == "cat":
                ear = QPainterPath(QPointF(cx + s * 12, cy - 22))
                ear.lineTo(cx + s * 24, cy - 37)
                ear.lineTo(cx + s * 28, cy - 15)
                ear.closeSubpath()
                p.setBrush(body)
                p.drawPath(ear)
                ear_in = QPainterPath(QPointF(cx + s * 15.5, cy - 22))
                ear_in.lineTo(cx + s * 23, cy - 32)
                ear_in.lineTo(cx + s * 25, cy - 19)
                ear_in.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(inner)
                p.drawPath(ear_in)
                p.setPen(out)
            elif self.species == "bunny":
                p.translate(cx + s * 12, cy - 24)
                p.rotate(s * 12)
                p.setBrush(body)
                p.drawEllipse(QPointF(0, -14), 7, 17)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(inner)
                p.drawEllipse(QPointF(0, -13), 3.5, 12)
                p.setPen(out)
            else:
                p.setBrush(body)
                p.drawEllipse(QPointF(cx + s * 21, cy - 21), 9, 9)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(inner)
                p.drawEllipse(QPointF(cx + s * 21, cy - 21), 4.5, 4.5)
                p.setPen(out)
            p.restore()
        if self.growth.mythic:                          # 神话期:一对会发光的大羽翼
            self._paint_mythic_wings(p, now, cx, cy, tk)
        elif self.growth.evolved:                       # 进化:背后一对向上扬起的小翅膀
            flap = math.sin((now - self._t0) * 3.0) * 2.0
            p.setPen(QPen(QColor("#8FA4E0"), 1.4))
            for sgn in (-1, 1):
                wing = QPainterPath(QPointF(cx + sgn * 20, cy))
                wing.cubicTo(cx + sgn * 30, cy - 22 - flap, cx + sgn * 40, cy - 32 - flap, cx + sgn * 47, cy - 28 - flap)
                wing.cubicTo(cx + sgn * 46, cy - 16, cx + sgn * 42, cy - 2, cx + sgn * 28, cy + 8)
                wing.closeSubpath()
                p.setBrush(QColor("#E3EAFF"))
                p.drawPath(wing)
                p.drawLine(QPointF(cx + sgn * 30, cy - 4), QPointF(cx + sgn * 41, cy - 20 - flap * 0.6))
                p.drawLine(QPointF(cx + sgn * 32, cy + 1), QPointF(cx + sgn * 42, cy - 10 - flap * 0.3))
            p.setPen(out)
        if "hoodie" in wear:                             # 卫衣的帽子:脸周围一圈
            p.setBrush(QColor("#9AA8F0"))
            p.drawEllipse(QPointF(cx, cy + 5), 35, 32)
        p.setBrush(body)
        p.drawEllipse(QPointF(cx, cy + 6), 31, 28)
        if "hoodie" in wear:
            self._acc_hoodie(p, cx, out)
        if "sailor" in wear:
            self._acc_sailor(p, cx, out)
        if "raincoat" in wear:
            self._acc_raincoat(p, cx, out)
        if "overalls" in wear:
            self._acc_overalls(p, cx, out)
        if "apron" in wear:
            self._acc_apron(p, cx, out)
        if "kimono" in wear:
            self._acc_kimono(p, cx, out)
        p.restore()
        if "scarf" in wear:
            self._acc_scarf(p, cx, out)
        if "bell" in wear:
            self._acc_bell(p, cx, out)
        if "bowtie" in wear:
            self._acc_bowtie(p, cx, out)
        if "tie" in wear:
            self._acc_tie(p, cx, out)
        if "pearl" in wear:
            self._acc_pearl(p, cx)

        # 脸
        ey = cy - 7
        p.setPen(out)
        for s in (-1, 1):
            x = cx + s * 10
            if mood == "sleep":
                path = QPainterPath(QPointF(x - 4, ey))
                path.quadTo(x, ey + 3.5, x + 4, ey)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            elif mood == "happy":
                path = QPainterPath(QPointF(x - 4, ey + 1.5))
                path.quadTo(x, ey - 3.5, x + 4, ey + 1.5)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            elif mood in ("focus", "annoyed"):
                p.drawLine(QPointF(x - 3.5 * s, ey - 3), QPointF(x + 2 * s, ey))
                p.drawLine(QPointF(x + 2 * s, ey), QPointF(x - 3.5 * s, ey + 3))
            elif mood == "blink":
                p.drawLine(QPointF(x - 3, ey), QPointF(x + 3, ey))
            elif mood == "dizzy":                         # 被揍晕:眼睛变成 ×
                p.drawLine(QPointF(x - 3.2, ey - 3.2), QPointF(x + 3.2, ey + 3.2))
                p.drawLine(QPointF(x - 3.2, ey + 3.2), QPointF(x + 3.2, ey - 3.2))
            elif mood == "surprise":
                p.setBrush(QColor("#FFFFFF"))
                p.drawEllipse(QPointF(x, ey), 3.2, 3.6)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(OUTLINE))
                p.drawEllipse(QPointF(x, ey), 1.4, 1.6)
                p.setPen(out)
            elif mood == "love":                          # 爱心眼
                p.save()
                p.translate(x, ey - 2.4)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#FF4D7A"))
                p.drawPath(heart_path(5.4 + 0.6 * math.sin((now - self._t0) * 9)))
                p.restore()
            elif self.growth.expr != "normal" and mood == "idle":
                self._paint_expr_eye(p, x, ey, s, out)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(OUTLINE))
                p.drawEllipse(QPointF(x, ey), 2.6, 3.0)
                p.setBrush(QColor("#FFFFFF"))
                p.drawEllipse(QPointF(x + 0.9, ey - 1.1), 0.9, 0.9)
                p.setPen(out)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 140, 150, 120))
        for s in (-1, 1):
            p.drawEllipse(QPointF(cx + s * 18, ey + 5), 4.5, 2.6)
        my = ey + 6
        mouth = QPen(QColor(OUTLINE), 1.3)
        mouth.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(mouth)
        p.setBrush(Qt.BrushStyle.NoBrush)
        chomp = self.acting(now) == "eat" and math.sin((now - self._act[1]) * 16) > 0
        if chomp:                                        # 啃东西:嘴巴一张一合
            p.setBrush(QColor("#E8706F"))
            p.drawEllipse(QPointF(cx, my + 1.2), 3.0, 2.6)
        elif mood in ("happy", "love") or (mood == "idle" and self.growth.expr in ("smile", "star")):
            path = QPainterPath(QPointF(cx - 3.5, my - 0.5))
            path.quadTo(cx, my + 5, cx + 3.5, my - 0.5)
            path.closeSubpath()
            p.setBrush(QColor("#E8706F"))
            p.drawPath(path)
        elif mood == "surprise":
            p.drawEllipse(QPointF(cx, my + 0.8), 1.8, 2.2)
        else:
            for s in (-1, 1):
                path = QPainterPath(QPointF(cx + s * 4.4, my - 0.4))
                path.quadTo(cx + s * 2.2, my + 2.6, cx, my - 0.4)
                p.drawPath(path)
        if self.species == "bear":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(OUTLINE))
            p.drawEllipse(QPointF(cx, my - 2.6), 2.0, 1.4)
        if mood == "annoyed":                           # 一滴汗
            drop = QPainterPath(QPointF(cx + 24, ey - 11))
            drop.quadTo(cx + 28.5, ey - 4, cx + 24, ey - 2.5)
            drop.quadTo(cx + 19.5, ey - 4, cx + 24, ey - 11)
            p.setPen(QPen(QColor("#4D8FD6"), 1))
            p.setBrush(QColor("#9CD3FF"))
            p.drawPath(drop)
        self._paint_wear(p, now, cx, cy, ey, wear, out)
        self._paint_wear2(p, now, cx, cy, ey, wear, out)
        self._paint_wear3(p, now, cx, cy, ey, wear, out)

        # 爪子
        pressed = self._paw if now - self._press_t < 0.14 else -1
        both = now - self._both_t < 0.14
        waving = now - self._alert_t < 1.6
        cheering = now - self._cheer_t < 0.6
        eating = self.acting(now) == "eat"
        for idx, s in ((0, -1), (1, 1)):
            px, py, ry = cx + s * 16, float(self.EDGE), 5.5
            if both or pressed == idx:
                py, ry = py + 2.5, 4.6
            elif pressed != -1:
                py -= 4
            if mood == "happy":
                py -= 3
            if eating:                                   # 两只爪子捧着食物
                px, py = cx + s * 8, self.EDGE - 5 + math.sin((now - self._act[1]) * 16) * 0.8
            elif cheering:
                py -= 12 * math.sin(math.pi * min(1.0, (now - self._cheer_t) / 0.6))
            elif waving and idx == 1:                    # 右爪举起来招手
                t = now - self._alert_t
                px += 6 + math.sin(t * 14) * 4
                py -= 16 * min(1.0, t / 0.2) * (1 - max(0.0, t - 1.3) / 0.3)
            p.setPen(out)
            p.setBrush(body)
            p.drawEllipse(QPointF(px, py), 7.5, ry)
            p.setPen(QPen(QColor(OUTLINE), 1.0))
            for k in (-1, 0, 1):
                p.drawLine(QPointF(px + k * 2.8, py + ry - 2.8), QPointF(px + k * 2.8, py + ry - 1.2))
            if both or pressed == idx:                 # 拍下去的冲击小线
                a = 1.0 - (now - self._press_t) / 0.14
                pen = QPen(QColor(T["accent"]), 1.4)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                c = pen.color()
                c.setAlphaF(max(0.0, a))
                pen.setColor(c)
                p.setPen(pen)
                for dx in (-9, 9):
                    p.drawLine(QPointF(px + dx, py + 1), QPointF(px + dx * 1.45, py + 3))
                p.drawLine(QPointF(px, py + ry + 1.5), QPointF(px, py + ry + 4.5))

        self._paint_props(p, now, cx, cy)
        self._paint_hurt_body(p, now, cx, cy)
        if self.growth.mythic:
            self._paint_crown(p, now, cx, cy)
        p.restore()                                    # 结束缩放
        self._paint_hurt_fx(p, now, cx, cy)
        self._paint_trick_fx(p, now, cx, cy)
        self._paint_alert(p, now, cx, cy)
        self._paint_levelup(p, now, cx)
        if mood == "sleep":                            # 飘起来的 z
            f = QFont(self.font())
            f.setWeight(QFont.Weight.Bold)
            for i, (dx, size) in enumerate(((26, 9), (32, 12))):
                phase = ((now - self._t0) * 0.6 + i * 0.5) % 1.0
                f.setPixelSize(size)
                p.setFont(f)
                c = QColor(T["sub"])
                c.setAlphaF(max(0.0, 1.0 - phase))
                p.setPen(c)
                p.drawText(QPointF(cx + dx, cy - 30 - i * 8 - phase * 10), "z" if i == 0 else "Z")


    # ---- 装扮
    def _paint_wear(self, p: QPainter, now: float, cx: float, cy: float, ey: float, wear: set, out: QPen) -> None:
        thin = QPen(QColor(OUTLINE), 1.3)
        thin.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        top = cy - 22                                   # 头顶
        if self.growth.evolved:                         # 进化:额头一颗会闪的宝石
            gy = ey - 9.5
            gem = QPainterPath(QPointF(cx, gy - 4))
            gem.lineTo(cx + 3.2, gy)
            gem.lineTo(cx, gy + 4)
            gem.lineTo(cx - 3.2, gy)
            gem.closeSubpath()
            p.setPen(QPen(QColor("#3B8FD9"), 0.9))
            p.setBrush(QColor("#7FD4FF"))
            p.drawPath(gem)
            tw = 0.5 + 0.5 * math.sin((now - self._t0) * 4.0)
            c = QColor(255, 255, 255, int(120 + 120 * tw))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(cx - 0.9, gy - 1.2), 1.0, 1.0)
        if "glasses" in wear:
            p.setPen(thin)
            p.setBrush(QColor(40, 36, 48, 235))
            for s in (-1, 1):
                p.drawRoundedRect(QRectF(cx + s * 10 - 6.2, ey - 4.2, 12.4, 8.6), 3.4, 3.4)
            p.drawLine(QPointF(cx - 3.8, ey - 1.6), QPointF(cx + 3.8, ey - 1.6))
            for s in (-1, 1):
                p.drawLine(QPointF(cx + s * 16.2, ey - 2.2), QPointF(cx + s * 22, ey - 4))
            p.setPen(QPen(QColor(255, 255, 255, 170), 1.2))
            for s in (-1, 1):
                p.drawLine(QPointF(cx + s * 10 - 3.4, ey - 1.8), QPointF(cx + s * 10 - 1.4, ey - 3.2))
        if "beanie" in wear:
            cap = QPainterPath(QPointF(cx - 26, top + 11))
            cap.cubicTo(cx - 25, top - 13, cx + 25, top - 13, cx + 26, top + 11)
            cap.closeSubpath()
            p.setPen(out)
            p.setBrush(QColor("#7FA7E8"))
            p.drawPath(cap)
            p.setBrush(QColor("#5C86D1"))
            p.drawRoundedRect(QRectF(cx - 27.5, top + 6.5, 55, 8), 4, 4)
            p.setPen(QPen(QColor(255, 255, 255, 110), 1.1))
            for k in range(-4, 5):
                p.drawLine(QPointF(cx + k * 5.6, top + 8), QPointF(cx + k * 5.6, top + 13))
            p.setPen(out)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(cx, top - 6.5), 5.2, 5.2)
        if "crown" in wear:
            y0 = top + 1.5
            path = QPainterPath(QPointF(cx - 11, y0))
            for x, y in ((-12.5, y0 - 11), (-6, y0 - 5), (0, y0 - 14), (6, y0 - 5), (12.5, y0 - 11), (11, y0)):
                path.lineTo(cx + x, y)
            path.closeSubpath()
            p.setPen(QPen(QColor("#B8860B"), 1.3))
            p.setBrush(QColor("#FFD43B"))
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            for x, col in ((-6.5, "#FF6B6B"), (0, "#4DABF7"), (6.5, "#63E6BE")):
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(cx + x, y0 - 3), 1.6, 1.6)
            p.setBrush(QColor("#FFF3BF"))
            p.drawEllipse(QPointF(cx, y0 - 14), 1.7, 1.7)
        if "party" in wear:
            hat = QPainterPath(QPointF(cx - 12, top + 3))
            hat.lineTo(cx + 4, top - 22)
            hat.lineTo(cx + 13, top + 3)
            hat.closeSubpath()
            p.setPen(thin)
            p.setBrush(QColor("#7C5CFF"))
            p.drawPath(hat)
            p.setPen(Qt.PenStyle.NoPen)
            for k, col in ((0.3, "#FFD43B"), (0.6, "#63E6BE")):            # 斜条纹
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(cx - 12 + 16 * k + 9 * k, top + 3 - 25 * k), 2.0, 2.0)
            p.setBrush(QColor("#FF8FAB"))
            p.drawEllipse(QPointF(cx + 4, top - 23), 3.0, 3.0)
        if "strawhat" in wear:
            p.setPen(QPen(QColor("#B08A3E"), 1.2))
            p.setBrush(QColor("#F2D58A"))
            p.drawEllipse(QPointF(cx, top + 5), 34, 6.5)                   # 帽檐
            crown = QPainterPath(QPointF(cx - 16, top + 5))
            crown.cubicTo(cx - 16, top - 12, cx + 16, top - 12, cx + 16, top + 5)
            crown.closeSubpath()
            p.drawPath(crown)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#E5383B"))
            p.drawRect(QRectF(cx - 16, top - 0.5, 32, 4))
        if "headphones" in wear:
            band = QPainterPath(QPointF(cx - 28, cy - 4))
            band.cubicTo(cx - 29, top - 16, cx + 29, top - 16, cx + 28, cy - 4)
            pen = QPen(QColor("#495057"), 3.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(band)
            p.setPen(out)
            for s in (-1, 1):
                p.setBrush(QColor("#FF8FAB"))
                p.drawRoundedRect(QRectF(cx + s * 29 - 5, cy - 11, 10, 15), 4.5, 4.5)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 120))
                p.drawEllipse(QPointF(cx + s * 29 - 1.2, cy - 6.5), 1.5, 2.6)
                p.setPen(out)
        if "bow" in wear:
            bx, by = cx + 19, top + 5
            p.setPen(thin)
            p.setBrush(QColor("#FF6B8A"))
            for s in (-1, 1):
                wing = QPainterPath(QPointF(bx, by))
                wing.lineTo(bx + s * 8.5, by - 5.5)
                wing.quadTo(bx + s * 10.5, by, bx + s * 8.5, by + 5.5)
                wing.closeSubpath()
                p.drawPath(wing)
            p.setBrush(QColor("#E64980"))
            p.drawEllipse(QPointF(bx, by), 2.6, 2.6)
        if "flower" in wear:
            fx, fy = cx - 19, top + 6
            p.setPen(QPen(QColor("#E8A0B4"), 0.9))
            p.setBrush(QColor("#FFF0F6"))
            for k in range(5):
                a = k / 5 * math.tau - math.pi / 2
                p.drawEllipse(QPointF(fx + math.cos(a) * 4, fy + math.sin(a) * 4), 3.2, 3.2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFC94D"))
            p.drawEllipse(QPointF(fx, fy), 2.4, 2.4)
        if "halo" in wear:
            bob = math.sin((now - self._t0) * 2.4) * 1.6
            hy = top - 13 + bob
            glow = QColor("#FFE066")
            glow.setAlphaF(0.35)
            p.setPen(QPen(glow, 5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, hy), 13, 3.6)
            p.setPen(QPen(QColor("#FFC107"), 2.2))
            p.drawEllipse(QPointF(cx, hy), 13, 3.6)

    def _paint_expr_eye(self, p: QPainter, x: float, ey: float, s: int, out: QPen) -> None:
        """平时的表情(衣橱里换):眯眼笑 / 困困 / 星星眼 / 酷酷。"""
        e = self.growth.expr
        p.setBrush(Qt.BrushStyle.NoBrush)
        if e == "smile":
            path = QPainterPath(QPointF(x - 4, ey + 1.5))
            path.quadTo(x, ey - 3.5, x + 4, ey + 1.5)
            p.drawPath(path)
        elif e == "sleepy":
            p.drawLine(QPointF(x - 3.5, ey + 0.5), QPointF(x + 3.5, ey + 0.5))
            p.setPen(QPen(QColor(OUTLINE), 1.0))
            p.drawLine(QPointF(x - 2.5, ey + 2.6), QPointF(x + 2.5, ey + 2.6))
            p.setPen(out)
        elif e == "star":
            p.save()
            p.translate(x, ey)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFC93C"))
            p.drawPath(star_path(4.2, 0.45))
            p.setBrush(QColor(OUTLINE))
            p.drawEllipse(QPointF(0, 0), 1.0, 1.0)
            p.restore()
        elif e == "cool":
            p.drawLine(QPointF(x - 4, ey), QPointF(x + 4, ey))
            p.drawLine(QPointF(x - 4 * s, ey - 4.5), QPointF(x + 3 * s, ey - 3))     # 挑眉

    def _paint_aura(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        pulse = 0.5 + 0.5 * math.sin((now - self._t0) * 1.8)
        g = QRadialGradient(QPointF(cx, cy), 46)
        for stop, a in ((0.0, 0.0), (0.55, 0.0), (0.72, 0.30 + 0.15 * pulse), (1.0, 0.0)):
            c = QColor("#FFD54A")
            c.setAlphaF(a)
            g.setColorAt(stop, c)
        p.save()
        p.setClipRect(QRectF(0, 0, self.W, self.EDGE + 0.5))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), 46, 46)
        p.restore()
        for k in range(3):                                # 三颗绕着转的小星星
            a = (now - self._t0) * 1.4 + k * math.tau / 3
            sx, sy = cx + math.cos(a) * 40, cy - 6 + math.sin(a) * 12
            if sy > self.EDGE:
                continue
            p.save()
            p.translate(sx, sy)
            p.rotate((now - self._t0) * 90)
            c = QColor(["#FFD43B", "#FFF3BF", "#FFB000"][k])
            c.setAlphaF(0.95 if math.sin(a) < 0 else 0.6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawPath(star_path(3.6, 0.45))
            p.restore()

    def _paint_props(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        """动作的道具:抱在爪子里的食物、在头顶蹦的玩具。"""
        kind = self.acting(now)
        if not kind or not self._act[3]:
            return
        t = now - self._act[1]
        f = _emoji_font(16)
        p.setFont(f)
        p.setPen(QColor("#000000"))
        if kind == "eat":
            shrink = max(0.45, 1.0 - t / (self._act[2] - self._act[1]) * 0.55)       # 越啃越小
            p.save()
            p.translate(cx, self.EDGE - 9)
            p.scale(shrink, shrink)
            p.drawText(QRectF(-12, -12, 24, 24), self._act[3], QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.restore()
            if int(t * 8) % 3 == 0:                        # 掉渣
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(200, 150, 90, 180))
                for k in (-1, 1):
                    p.drawEllipse(QPointF(cx + k * (6 + t * 3 % 4), self.EDGE - 1 + (t * 9 % 4)), 1.1, 1.1)
        elif kind == "play":
            y = cy - 44 - abs(math.sin(t * 7.0)) * 14
            x = cx + math.sin(t * 3.5) * 10
            p.save()
            p.translate(x, y)
            p.rotate(t * 260)
            p.drawText(QRectF(-12, -12, 24, 24), self._act[3], QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.restore()

    def _paint_alert(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        t = now - self._alert_t
        if t > 1.6:
            return
        a = min(1.0, t / 0.12, (1.6 - t) / 0.3)
        bounce = -abs(math.sin(t * 9)) * 4 * (1 - t / 1.6)
        r = QRectF(cx + (-34 if self.mirror else 20), cy - 44 + bounce, 15, 17)
        p.save()
        p.setOpacity(max(0.0, a))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T["accent"]))
        p.drawRoundedRect(r, 7.5, 7.5)
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.Black)
        p.setFont(f)
        p.setPen(QColor(T.get("on_accent", "#FFFFFF")))
        p.drawText(r, "!", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.restore()

    # ---- 2.5 新装扮
    def _paint_outfit_glow(self, p: QPainter, now: float, cx: float, cy: float, color: str) -> None:
        pulse = 0.5 + 0.5 * math.sin((now - self._t0) * 2.4)
        g = QRadialGradient(QPointF(cx, cy), 52)
        c0 = QColor(color)
        for stop, a in ((0.0, 0.0), (0.6, 0.0), (0.78, 0.28 + 0.18 * pulse), (1.0, 0.0)):
            c = QColor(c0)
            c.setAlphaF(a)
            g.setColorAt(stop, c)
        p.save()
        p.setClipRect(QRectF(0, 0, self.W, self.EDGE + 0.5))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), 52, 52)
        p.restore()

    def _acc_jetpack(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        out = QPen(QColor(OUTLINE), 1.3)
        for s_ in (-1, 1):
            r = QRectF(cx + s_ * 30 - 7, cy - 12, 14, 26)
            p.setPen(out)
            p.setBrush(QColor("#CED4DA"))
            p.drawRoundedRect(r, 6, 6)
            p.setBrush(QColor("#FA5252"))
            p.drawRoundedRect(QRectF(r.x() + 2, r.y() + 3, 10, 5), 2, 2)
        t = now - self._t0                                  # 喷火(在输入框边缘上方一点点)
        for s_ in (-1, 1):
            fl = 6 + 3 * math.sin(t * 30 + s_)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 169, 77, 200))
            flame = QPainterPath(QPointF(cx + s_ * 30 - 5, cy + 14))
            flame.quadTo(cx + s_ * 30, cy + 14 + fl * 2, cx + s_ * 30 + 5, cy + 14)
            p.drawPath(flame)

    def _acc_apron(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 8                                   # 只露出输入框上面一点点(上面是脸)
        p.setPen(QPen(QColor("#FFA94D"), 1.4))
        p.drawLine(QPointF(cx - 11, y + 1), QPointF(cx - 21, y - 3))
        p.drawLine(QPointF(cx + 11, y + 1), QPointF(cx + 21, y - 3))
        p.setPen(out)
        p.setBrush(QColor("#FFFFFF"))
        ap = QPainterPath(QPointF(cx - 11, y))
        ap.lineTo(cx + 11, y)
        ap.quadTo(cx + 15, y + 5, cx + 16, self.EDGE + 2)
        ap.lineTo(cx - 16, self.EDGE + 2)
        ap.quadTo(cx - 15, y + 5, cx - 11, y)
        p.drawPath(ap)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFD8A8"))
        p.drawRoundedRect(QRectF(cx - 6, y + 3, 12, 5), 2, 2)

    def _acc_kimono(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 12
        p.setPen(out)
        p.setBrush(QColor("#F783AC"))
        k = QPainterPath(QPointF(cx - 30, y + 4))
        k.quadTo(cx, y - 2, cx + 30, y + 4)
        k.lineTo(cx + 33, self.EDGE + 2)
        k.lineTo(cx - 33, self.EDGE + 2)
        k.closeSubpath()
        p.drawPath(k)
        p.setPen(QPen(QColor("#FFFFFF"), 2.2))                  # 交领
        p.drawLine(QPointF(cx - 9, y), QPointF(cx + 4, self.EDGE + 1))
        p.drawLine(QPointF(cx + 9, y), QPointF(cx - 2, self.EDGE - 4))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#7048E8"))                          # 腰带
        p.drawRect(QRectF(cx - 31, self.EDGE - 4, 62, 5))
        p.setBrush(QColor(255, 255, 255, 200))                  # 小樱花纹
        for dx in (-20, 18):
            for i in range(5):
                a = i / 5 * math.tau
                p.drawEllipse(QPointF(cx + dx + math.cos(a) * 2.4, y + 6 + math.sin(a) * 2.4), 1.5, 1.5)

    def _paint_wear3(self, p: QPainter, now: float, cx: float, cy: float, ey: float, wear: set, out: QPen) -> None:
        t = now - self._t0
        top = cy - 22
        thin = QPen(QColor(OUTLINE), 1.3)
        if "eyepatch" in wear:
            p.setPen(QPen(QColor("#212529"), 1.4))
            p.drawLine(QPointF(cx - 22, ey - 9), QPointF(cx + 20, ey - 3))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#212529"))
            p.drawEllipse(QPointF(cx + 10, ey), 6.5, 6)
        if "kanzashi" in wear:                                  # 耳边一支樱花发簪,垂两颗小坠子
            bx, by = cx - 19, top + 4
            p.setPen(QPen(QColor("#B08968"), 1.6))
            p.drawLine(QPointF(bx - 8, by + 8), QPointF(bx + 6, by - 4))
            for i in range(5):
                a = i / 5 * math.tau - math.pi / 2
                p.setPen(QPen(QColor("#E64980"), 0.8))
                p.setBrush(QColor("#FFC9DE"))
                p.drawEllipse(QPointF(bx + math.cos(a) * 3.6, by + math.sin(a) * 3.6), 2.8, 2.8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFD43B"))
            p.drawEllipse(QPointF(bx, by), 1.6, 1.6)
            sway = math.sin(t * 2.6) * 2
            p.setPen(QPen(QColor("#E64980"), 0.8))
            p.drawLine(QPointF(bx - 2, by + 4), QPointF(bx - 3 + sway, by + 13))
            p.setBrush(QColor("#F783AC"))
            p.drawEllipse(QPointF(bx - 3 + sway, by + 14), 1.8, 1.8)
        if "pirate" in wear:                                    # 黑色三角海盗帽 + 白骷髅
            p.setPen(thin)
            p.setBrush(QColor("#343A40"))
            hat = QPainterPath(QPointF(cx - 30, top + 2))
            hat.quadTo(cx - 18, top - 20, cx, top - 18)
            hat.quadTo(cx + 18, top - 20, cx + 30, top + 2)
            hat.quadTo(cx, top - 4, cx - 30, top + 2)
            p.drawPath(hat)
            p.setPen(QPen(QColor("#FAB005"), 1.4))
            p.drawLine(QPointF(cx - 24, top - 2), QPointF(cx + 24, top - 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(cx, top - 10), 3.6, 3.2)
            p.setPen(QPen(QColor("#FFFFFF"), 1.2))
            p.drawLine(QPointF(cx - 5, top - 4), QPointF(cx + 5, top - 7))
            p.drawLine(QPointF(cx - 5, top - 7), QPointF(cx + 5, top - 4))
        if "astro" in wear:                                     # 透明的宇航头盔罩住整个脑袋
            p.setPen(QPen(QColor(255, 255, 255, 220), 2.2))
            p.setBrush(QColor(165, 216, 255, 55))
            p.drawEllipse(QPointF(cx, cy - 4), 36, 32)
            p.setPen(QPen(QColor(255, 255, 255, 160), 2))
            hl = QPainterPath(QPointF(cx - 24, cy - 18))
            hl.quadTo(cx - 18, cy - 30, cx - 4, cy - 33)
            p.drawPath(hl)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ADB5BD"))
            p.drawRoundedRect(QRectF(cx + 26, cy - 26, 4, 12), 2, 2)
            blink = int(t * 2) % 2 == 0
            p.setBrush(QColor("#FA5252" if blink else "#C92A2A"))
            p.drawEllipse(QPointF(cx + 28, cy - 28), 2.4, 2.4)
        hand = next((w for w in wear if ACC_BY_ID.get(w, ("", "", 0, ""))[3] == "hand"), None)
        if hand:
            self._paint_hand(p, hand, t, cx + 28, self.EDGE - 4)
        for w in wear:
            if ACC_BY_ID.get(w, ("", "", 0, ""))[3] == "fx":
                self._paint_fx_item(p, w, t, cx, cy)

    def _paint_hand(self, p: QPainter, item: str, t: float, x: float, y: float) -> None:
        """抱在右爪边上的小东西。(x, y) 是爪子的位置,东西往上竖着。"""
        out = QPen(QColor(OUTLINE), 1.2)
        p.save()
        p.translate(x, y)
        p.rotate(10 + math.sin(t * 2) * 4)
        if item == "balloon":
            sway = math.sin(t * 1.6) * 3
            p.setPen(QPen(QColor("#868E96"), 0.9))
            string = QPainterPath(QPointF(0, 0))
            string.cubicTo(3, -10, -3 + sway, -20, sway, -30)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(string)
            p.setPen(QPen(QColor("#C92A2A"), 1))
            p.setBrush(QColor("#FF6B6B"))
            p.drawEllipse(QPointF(sway, -40), 9, 11)
            p.setBrush(QColor(255, 255, 255, 150))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(sway - 3, -44), 2.4, 3.4)
        elif item == "icecream":
            p.setPen(out)
            p.setBrush(QColor("#E8B97A"))
            cone = QPainterPath(QPointF(-6, -14))
            cone.lineTo(6, -14)
            cone.lineTo(0, 2)
            cone.closeSubpath()
            p.drawPath(cone)
            p.setBrush(QColor("#FFC9DE"))
            p.drawEllipse(QPointF(0, -18), 7.5, 6.5)
            p.setBrush(QColor("#B2F2BB"))
            p.drawEllipse(QPointF(0, -25), 6, 5.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#E03131"))
            p.drawEllipse(QPointF(1, -31), 2.2, 2.2)
        elif item == "wand":
            p.setPen(QPen(QColor("#495057"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(0, 0), QPointF(0, -24))
            p.translate(0, -28)
            p.rotate(t * 60)
            p.setPen(QPen(QColor("#E8A200"), 0.8))
            p.setBrush(QColor("#FFD43B"))
            p.drawPath(star_path(6.0, 0.45))
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                a = t * 3 + i * 2.1
                p.setBrush(QColor(255, 255, 255, int(120 + 120 * math.sin(t * 6 + i))))
                p.drawEllipse(QPointF(math.cos(a) * 10, math.sin(a) * 10), 1.4, 1.4)
        elif item == "spatula":
            p.setPen(QPen(QColor("#8D6E63"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(0, 0), QPointF(0, -18))
            p.setPen(out)
            p.setBrush(QColor("#CED4DA"))
            p.drawRoundedRect(QRectF(-6, -30, 12, 12), 2, 2)
        elif item == "giftbox":
            p.setPen(out)
            p.setBrush(QColor("#FF6B6B"))
            p.drawRect(QRectF(-8, -16, 16, 14))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFD43B"))
            p.drawRect(QRectF(-1.6, -16, 3.2, 14))
            p.drawRect(QRectF(-8, -11, 16, 3))
            p.drawEllipse(QPointF(-3, -18), 3, 2)
            p.drawEllipse(QPointF(3, -18), 3, 2)
        elif item == "sword":
            p.setPen(out)
            p.setBrush(QColor("#E9ECEF"))
            blade = QPainterPath(QPointF(-2.4, -6))
            blade.lineTo(-2.4, -30)
            blade.lineTo(0, -34)
            blade.lineTo(2.4, -30)
            blade.lineTo(2.4, -6)
            blade.closeSubpath()
            p.drawPath(blade)
            p.setBrush(QColor("#FAB005"))
            p.drawRoundedRect(QRectF(-7, -7, 14, 3.5), 1.5, 1.5)
            p.setBrush(QColor("#8D6E63"))
            p.drawRect(QRectF(-1.8, -4, 3.6, 6))
        elif item == "fan":
            p.setPen(QPen(QColor("#8D6E63"), 2))
            p.drawLine(QPointF(0, 0), QPointF(0, -14))
            p.setPen(out)
            p.setBrush(QColor("#FFF0F6"))
            p.drawEllipse(QPointF(0, -24), 10, 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#F783AC"))
            for i in range(5):
                a = i / 5 * math.tau - math.pi / 2
                p.drawEllipse(QPointF(math.cos(a) * 3, -24 + math.sin(a) * 3), 2.4, 2.4)
        p.restore()

    def _paint_fx_item(self, p: QPainter, fx: str, t: float, cx: float, cy: float) -> None:
        """特效类装扮:绕着宠物飘的小东西。"""
        p.save()
        rnd = random.Random(hash(fx) & 0xFFFF)
        n = {"hearts": 4, "bubbles": 5, "snowfall": 8, "petals": 7, "fireflies": 5, "stardust": 9, "sparkle": 6}.get(fx, 5)
        for i in range(n):
            seed_x = rnd.uniform(-48, 48)
            speed = rnd.uniform(0.18, 0.32)
            ph = (t * speed + i / n) % 1.0
            if fx in ("hearts", "bubbles"):                       # 往上冒
                x = cx + seed_x * 0.8 + math.sin(t * 2 + i) * 4
                y = self.EDGE - 4 - ph * 70
                a = math.sin(math.pi * ph)
                p.setOpacity(a)
                if fx == "hearts":
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor("#FF8FAB"))
                    hp = QPainterPath(QPointF(x, y + 3))
                    hp.cubicTo(x - 4.5, y, x - 3.5, y - 3.8, x, y - 1.4)
                    hp.cubicTo(x + 3.5, y - 3.8, x + 4.5, y, x, y + 3)
                    p.drawPath(hp)
                else:
                    p.setPen(QPen(QColor(165, 216, 255, 220), 1))
                    p.setBrush(QColor(255, 255, 255, 40))
                    r = 3 + 2.5 * (i % 3)
                    p.drawEllipse(QPointF(x, y), r, r)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255, 180))
                    p.drawEllipse(QPointF(x - r * 0.35, y - r * 0.35), r * 0.25, r * 0.25)
            elif fx in ("snowfall", "petals"):                    # 往下飘
                x = cx + seed_x + math.sin(t * 1.5 + i * 1.7) * 8
                y = cy - 70 + ph * 80
                p.setOpacity(math.sin(math.pi * ph))
                p.translate(x, y)
                p.rotate(t * 60 + i * 40)
                p.setPen(Qt.PenStyle.NoPen)
                if fx == "snowfall":
                    p.setBrush(QColor("#FFFFFF"))
                    p.drawEllipse(QPointF(0, 0), 1.8, 1.8)
                    p.setPen(QPen(QColor(255, 255, 255, 200), 0.8))
                    for k in range(3):
                        p.rotate(60)
                        p.drawLine(QPointF(-3.4, 0), QPointF(3.4, 0))
                else:
                    p.setBrush(QColor("#FFC9DE"))
                    p.drawEllipse(QPointF(0, 0), 3.6, 2.2)
                p.rotate(-(t * 60 + i * 40))
                p.translate(-x, -y)
            elif fx == "fireflies":                               # 慢慢游的小光点
                x = cx + math.sin(t * 0.7 + i * 2.1) * 46
                y = cy - 18 + math.sin(t * 0.9 + i * 1.3) * 22
                glow = 0.5 + 0.5 * math.sin(t * 3 + i)
                g = QRadialGradient(QPointF(x, y), 6)
                g.setColorAt(0, QColor(255, 236, 120, int(240 * glow)))
                g.setColorAt(1, QColor(255, 236, 120, 0))
                p.setOpacity(1.0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(g))
                p.drawEllipse(QPointF(x, y), 6, 6)
            elif fx == "stardust":                                # 一闪一闪的小星星
                x = cx + seed_x * 1.1
                y = cy - 8 + rnd.uniform(-36, 12)
                tw = max(0.0, math.sin(t * 2.2 + i * 1.9))
                p.setOpacity(tw)
                p.translate(x, y)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(["#FFF3BF", "#D0EBFF", "#E5DBFF"][i % 3]))
                p.drawPath(star_path(2.2 + 1.6 * tw, 0.4))
                p.translate(-x, -y)
            elif fx == "sparkle":                                 # 绕着身子转的一圈魔法光点
                a = t * 1.3 + i / n * math.tau
                x, y = cx + math.cos(a) * 40, cy - 6 + math.sin(a) * 14
                if y > self.EDGE:
                    continue
                p.setOpacity(0.9 if math.sin(a) > 0 else 0.5)
                p.translate(x, y)
                p.rotate(t * 120)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(["#B197FC", "#FFD43B", "#FFFFFF"][i % 3]))
                p.drawPath(star_path(3.2, 0.35))
                p.rotate(-t * 120)
                p.translate(-x, -y)
        p.restore()

    # ---- 动作(2.5):每 5 级学会一个
    def trick(self, tid: str) -> bool:
        t = TRICK_BY_ID.get(tid)
        if t is None or self.growth.level < t[0]:
            return False
        self._trick = (tid, _now(), t[3])
        self._speed(33)
        if tid == "bow":
            self.say("谢谢大家!", 1.8)
        elif tid == "magic":
            self.say("变变变~", 1.4)
        self.update()
        return True

    def _trick_motion(self, now: float) -> dict:
        m = {"dx": 0.0, "dy": 0.0, "rot": 0.0, "sx": 1.0, "sy": 1.0}
        tr = self._trick
        if tr is None:
            return m
        tid, t0, dur = tr
        k = (now - t0) / dur
        if k < 0 or k > 1:
            return m
        ease = math.sin(math.pi * k)
        if tid == "stretch":
            m["sx"], m["sy"] = 1 - 0.07 * ease, 1 + 0.13 * ease
        elif tid == "spin":                               # 原地转一圈(左右翻转,下半身藏在输入框后面,不能整只倒过来)
            e = k * k * (3 - 2 * k)
            m["sx"] = math.cos(e * math.tau * 2) if abs(math.cos(e * math.tau * 2)) > 0.08 else 0.08
            m["dy"] = -8 * ease
        elif tid == "roll":
            m["rot"] = math.sin(k * math.tau * 2) * 28 * (1 - k * 0.3)
            m["dx"] = math.sin(k * math.tau * 2) * 6
        elif tid == "hop":
            m["dy"] = -abs(math.sin(k * math.pi * 3)) * 11
            m["sy"] = 1 + 0.06 * math.sin(k * math.pi * 6)
        elif tid == "dance":
            m["rot"] = math.sin(k * math.tau * 3) * 12
            m["dx"] = math.sin(k * math.tau * 1.5) * 8
            m["dy"] = -abs(math.sin(k * math.tau * 3)) * 4
        elif tid == "fly":
            up = min(1.0, k / 0.25, (1 - k) / 0.25)
            m["dy"] = -18 * up + math.sin(k * math.tau * 3) * 2 * up
        elif tid == "bow":
            m["sy"] = 1 - 0.14 * ease
            m["rot"] = 8 * ease
        elif tid in ("heart", "wave", "magic"):
            m["dy"] = -3 * ease
        return m

    def _paint_trick_fx(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        tr = self._trick
        if tr is None:
            return
        tid, t0, dur = tr
        t = now - t0
        k = t / dur
        if k < 0 or k > 1:
            return
        top = cy - 26
        p.save()
        if tid == "heart":                                # 头顶比一颗大大的心,四周冒小心
            pop = min(1.0, t / 0.3)
            s = 0.4 + 0.6 * (1 - (1 - pop) ** 3) + 0.06 * math.sin(t * 10)
            p.setOpacity(min(1.0, (1 - k) / 0.25))
            p.translate(cx, top - 14)
            p.scale(s, s)
            p.setPen(QPen(QColor("#C2255C"), 1.4))
            p.setBrush(QColor("#FF6B8A"))
            heart = QPainterPath(QPointF(0, 9))
            heart.cubicTo(-13, 1, -10, -10, 0, -4)
            heart.cubicTo(10, -10, 13, 1, 0, 9)
            p.drawPath(heart)
            p.resetTransform()
            for i in range(5):
                a = i / 5 * math.tau + t * 2
                d = 16 + t * 14
                p.save()
                p.translate(cx + math.cos(a) * d, top - 14 + math.sin(a) * d * 0.5)
                p.scale(0.35, 0.35)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#FF8FAB"))
                p.drawPath(heart)
                p.restore()
        elif tid == "wave":                               # 一只小爪子在旁边挥
            side = -1 if self.mirror else 1
            a = math.sin(t * 14) * 25
            p.translate(cx + side * 30, cy - 6)
            p.rotate(-side * 30 + a)
            sp = SPECIES.get(self.species, SPECIES["cat"])
            p.setPen(QPen(QColor(OUTLINE), 1.5))
            p.setBrush(QColor(sp["body"]))
            p.drawEllipse(QPointF(0, -10), 7, 9)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(sp["inner"]))
            p.drawEllipse(QPointF(0, -12), 3, 3.2)
        elif tid == "dance":                              # 飘出来的音符
            f = QFont(self.font())
            f.setPixelSize(15)
            f.setWeight(QFont.Weight.Bold)
            p.setFont(f)
            for i in range(3):
                ph = (t * 0.9 + i / 3) % 1.0
                p.setOpacity(1 - ph)
                p.setPen(QColor(["#9775FA", "#FF6B8A", "#4DABF7"][i]))
                x = cx + (i - 1) * 22 + math.sin(ph * 6 + i) * 6
                p.drawText(QRectF(x - 10, top - 10 - ph * 34, 20, 20), "♪" if i % 2 else "♫",
                           QTextOption(Qt.AlignmentFlag.AlignCenter))
        elif tid in ("fly", "magic", "spin"):             # 闪闪的星星
            n = 8 if tid == "magic" else 5
            for i in range(n):
                a = i / n * math.tau + t * (3 if tid == "magic" else 1.5)
                d = (26 + 10 * math.sin(t * 4 + i)) if tid == "magic" else 30
                p.save()
                p.setOpacity(min(1.0, (1 - k) / 0.3) * (0.6 + 0.4 * math.sin(t * 8 + i)))
                p.translate(cx + math.cos(a) * d, cy - 8 + math.sin(a) * d * 0.55)
                p.rotate(t * 200)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(["#FFD43B", "#FFF3BF", "#B197FC", "#74C0FC"][i % 4]))
                p.drawPath(star_path(4.2 if tid == "magic" else 3.2, 0.42))
                p.restore()
        elif tid == "bow" and k > 0.35:                    # 谢幕:撒一点小彩带
            for i in range(10):
                rnd = random.Random(i * 31 + int(t0))
                x = cx + rnd.uniform(-50, 50)
                y = top - 30 + (t - dur * 0.35) * rnd.uniform(30, 60)
                p.save()
                p.translate(x, y)
                p.rotate(t * rnd.uniform(-300, 300))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(rnd.choice(["#FF6B6B", "#FFD43B", "#69DB7C", "#4DABF7", "#B197FC"])))
                p.drawRect(QRectF(-3, -1.5, 6, 3))
                p.restore()
        p.restore()

    # ---- 神话期(40 级):发光大羽翼 + 星冠
    def _paint_mythic_wings(self, p: QPainter, now: float, cx: float, cy: float, tk: dict) -> None:
        t = now - self._t0
        flying = self._trick is not None and self._trick[0] == "fly"
        flap = math.sin(t * (9.0 if flying else 2.2)) * (7.0 if flying else 3.0)
        p.save()
        for sgn in (-1, 1):
            for layer, (spread, lift, col, alpha) in enumerate(((48, 40, "#B197FC", 0.55), (42, 34, "#E5DBFF", 0.9),
                                                                (34, 24, "#FFFFFF", 0.95))):
                wing = QPainterPath(QPointF(cx + sgn * 16, cy - 2))
                wing.cubicTo(cx + sgn * (spread * 0.5), cy - lift - flap, cx + sgn * spread, cy - lift - 6 - flap,
                             cx + sgn * (spread + 6), cy - lift + 4 - flap)
                wing.cubicTo(cx + sgn * (spread - 2), cy - lift * 0.4, cx + sgn * (spread * 0.75), cy + 6,
                             cx + sgn * 22, cy + 12)
                wing.closeSubpath()
                c = QColor(col)
                c.setAlphaF(alpha)
                p.setPen(QPen(QColor(151, 117, 250, 160), 1.1) if layer == 0 else Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawPath(wing)
            p.setPen(QPen(QColor(151, 117, 250, 150), 1))     # 羽毛纹
            for k in range(4):
                x0 = cx + sgn * (24 + k * 8)
                p.drawLine(QPointF(x0, cy + 6 - k * 2), QPointF(x0 + sgn * 10, cy - 20 - k * 5 - flap * 0.7))
        glow = 0.5 + 0.5 * math.sin(t * 2.6)                   # 翼尖的光点
        for sgn in (-1, 1):
            g = QRadialGradient(QPointF(cx + sgn * 50, cy - 36 - flap), 9)
            g.setColorAt(0, QColor(255, 255, 255, int(200 * glow)))
            g.setColorAt(1, QColor(177, 151, 252, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx + sgn * 50, cy - 36 - flap), 9, 9)
        p.restore()

    def _paint_crown(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        """头顶浮着一圈慢慢转的星冠(前半圈画在头前面,后半圈淡一点)。"""
        t = now - self._t0
        top = cy - 22 - 16 + math.sin(t * 2) * 1.5
        p.save()
        p.setPen(QPen(QColor(255, 212, 59, 120), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, top), 18, 4.5)
        for i in range(5):
            a = t * 1.2 + i / 5 * math.tau
            x, y = cx + math.cos(a) * 18, top + math.sin(a) * 4.5
            front = math.sin(a) > 0
            p.save()
            p.translate(x, y)
            p.setOpacity(1.0 if front else 0.45)
            p.setPen(QPen(QColor("#E8A200"), 0.7))
            p.setBrush(QColor("#FFD43B" if i % 2 == 0 else "#FFF3BF"))
            p.drawPath(star_path(3.8 if front else 3.0, 0.45))
            p.restore()
        p.restore()

    # ---- 被揍(2.4):别人用拳头 / 枕头 / 玩具锤 / 弹脑门揍我的宠物,或者它躲开、反击
    def hurt(self, weapon: str, outcome: str = "hit") -> None:
        if weapon not in WEAPON_BY_ID and weapon != "paw":
            weapon = "fist"
        self._hurt = (weapon, _now(), outcome if outcome in ("hit", "dodge", "counter") else "hit")
        self._speed(33)
        self.update()

    def hurting(self, now: float | None = None) -> bool:
        now = _now() if now is None else now
        return self._hurt is not None and now - self._hurt[1] < HURT_SECS

    def _dodge_dir(self) -> int:
        return 1 if self.mirror else -1            # 拳头从外侧(靠窗口边那边)来,往里躲

    def _hurt_dx(self, now: float) -> float:
        h = self._hurt
        if h is None or h[2] == "hit":
            return 0.0
        t = now - h[1]
        d = self._dodge_dir() * 34
        if t < 0.2:
            return 0.0
        if t < 0.42:
            k = (t - 0.2) / 0.22
            return d * (1 - (1 - k) ** 3)
        if h[2] == "counter":
            if t < 0.6:
                return d
            if t < 0.8:                            # 反击:冲回去踢一脚
                return d * (1 - (t - 0.6) / 0.2) - self._dodge_dir() * 12 * ((t - 0.6) / 0.2)
            if t < 1.2:
                return -self._dodge_dir() * 12 * (1 - (t - 0.8) / 0.4)
            return 0.0
        if t < 0.95:
            return d
        if t < 1.35:
            return d * (1 - (t - 0.95) / 0.4)
        return 0.0

    def _hurt_jump(self, now: float) -> float:
        h = self._hurt
        if h is None:
            return 0.0
        t = now - h[1]
        if h[2] == "counter" and 0.6 <= t < 1.0:
            return -12 * math.sin(math.pi * (t - 0.6) / 0.4)
        if h[2] == "dodge" and 0.2 <= t < 0.5:
            return -6 * math.sin(math.pi * (t - 0.2) / 0.3)
        return 0.0

    def _hurt_squash(self, now: float) -> float:
        h = self._hurt
        if h is None or h[2] != "hit":
            return 0.0
        t = now - h[1] - HURT_IMPACT
        if t < 0 or t > 0.45:
            return 0.0
        strong = 1.0 if h[0] == "hammer" else 0.6 if h[0] in ("fist", "paw") else 0.35
        return strong * math.exp(-t * 7) * abs(math.cos(t * 18))

    def _paint_hurt_body(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        """跟着身体一起缩放的部分:头上的包、额头的红印、眼泪。"""
        h = self._hurt
        if h is None or h[2] != "hit":
            return
        t = now - h[1] - HURT_IMPACT
        if t < 0 or t > HURT_SECS - HURT_IMPACT:
            return
        fade = max(0.0, min(1.0, (HURT_SECS - HURT_IMPACT - t) / 0.8))
        top = cy - 22
        p.save()
        p.setOpacity(fade)
        if h[0] in ("fist", "hammer", "paw"):                    # 鼓起一个包
            grow = min(1.0, t / 0.18)
            r = (6.5 if h[0] == "hammer" else 5.2) * (0.4 + 0.6 * grow) * (1 + 0.1 * math.exp(-t * 6) * math.sin(t * 30))
            bx = cx + 7 * (-self._dodge_dir())
            p.setPen(QPen(QColor("#C2255C"), 1.1))
            p.setBrush(QColor("#FF8FA3"))
            p.drawEllipse(QPointF(bx, top + 2 - r * 0.55), r, r * 0.85)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 170))
            p.drawEllipse(QPointF(bx - r * 0.35, top + 2 - r * 0.85), r * 0.28, r * 0.2)
        if h[0] == "flick":                                      # 弹脑门:额头一个红印 + 眼泪
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 80, 100, 150))
            p.drawEllipse(QPointF(cx, cy - 15), 4.2, 3.2)
            if t < 2.6:
                ey = cy - 7
                for s_ in (-1, 1):
                    ph = (t * 1.4 + (0.5 if s_ > 0 else 0)) % 1.0
                    p.setBrush(QColor(116, 192, 252, int(220 * (1 - ph))))
                    drop = QPainterPath(QPointF(cx + s_ * 13, ey + 2 + ph * 12))
                    drop.quadTo(cx + s_ * 13 + 2.6, ey + 6 + ph * 12, cx + s_ * 13, ey + 7.5 + ph * 12)
                    drop.quadTo(cx + s_ * 13 - 2.6, ey + 6 + ph * 12, cx + s_ * 13, ey + 2 + ph * 12)
                    p.drawPath(drop)
        p.restore()

    def _paint_hurt_fx(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        """不跟着缩放的部分:飞过来的武器、转圈的星星、羽毛、"咚!"。"""
        h = self._hurt
        if h is None:
            return
        weapon, t0, outcome = h
        t = now - t0
        if t > HURT_SECS:
            self._hurt = None
            return
        d = self._dodge_dir()
        side = -d                                                # 武器从这一侧来
        hx, hy = self._cx() + side * 6, cy - 26                  # 砸中的位置(头顶偏外侧)
        sx, sy = self._cx() + side * 78, cy - 70
        # 武器
        if outcome == "hit":
            if t < HURT_IMPACT:
                k = t / HURT_IMPACT
                e = k * k
                wx, wy = sx + (hx - sx) * e, sy + (hy - sy) * e
                rot = side * (-60 + 80 * e)
                self._draw_weapon(p, weapon, wx, wy, rot, 1.0, side)
            elif t < HURT_IMPACT + 0.55:
                k = (t - HURT_IMPACT) / 0.55
                wx, wy = hx + side * 18 * k, hy - 22 * k
                self._draw_weapon(p, weapon, wx, wy, side * (20 + 30 * k), 1 - k, side)
        else:
            if t < 0.62:                                         # 扑空:一路飞过去
                k = t / 0.62
                ex, ey2 = self._cx() + side * 2, cy - 18             # 扑到它原来的位置,它已经躲开了
                wx, wy = sx + (ex - sx) * k, sy + (ey2 - sy) * k
                fade = 1.0 if outcome == "dodge" or t < 0.55 else 0.0
                if outcome == "counter" and t > 0.55:
                    fade = 0.0
                self._draw_weapon(p, weapon, wx, wy, side * (-60 + 90 * k), fade if k < 0.85 else (1 - k) / 0.15 * fade, side)
                p.save()
                p.setPen(QPen(QColor(255, 255, 255, 120), 1.6))
                for i in range(3):
                    off = (i - 1) * 6
                    p.drawLine(QPointF(wx + side * 12, wy + off), QPointF(wx + side * 26, wy + off - 4))
                p.restore()
            if outcome == "counter" and 0.7 <= t < 1.5:          # 被一脚踢飞,转着圈飞出去
                k = (t - 0.7) / 0.8
                wx = self._cx() + side * (10 + 120 * k)
                wy = cy - 30 - 90 * math.sin(math.pi * min(1.0, k * 0.7))
                self._draw_weapon(p, weapon, wx, wy, side * 720 * k, 1 - k, side)
        # 命中后的效果
        if outcome == "hit" and t >= HURT_IMPACT:
            tt = t - HURT_IMPACT
            dizzy = 1.2 if weapon in ("pillow", "flick") else 2.2
            if tt < dizzy:                                        # 头顶转圈的星星
                fade = min(1.0, (dizzy - tt) / 0.4)
                for i in range(3):
                    a = tt * 6 + i * math.tau / 3
                    p.save()
                    p.setOpacity(fade)
                    p.translate(self._cx() + math.cos(a) * 18, cy - 34 + math.sin(a) * 5)
                    p.setPen(QPen(QColor("#E8A200"), 0.8))
                    p.setBrush(QColor("#FFD43B"))
                    p.drawPath(star_path(4.6, 0.45))
                    p.restore()
            if weapon == "pillow" and tt < 1.3:                   # 枕头:羽毛飘落
                rng = random.Random(int(t0 * 1000))
                for i in range(7):
                    fx = hx + rng.uniform(-30, 30) + math.sin(tt * 4 + i) * 6
                    fy = hy - 10 + rng.uniform(-8, 4) + tt * rng.uniform(18, 34)
                    p.save()
                    p.setOpacity(max(0.0, 1 - tt / 1.3))
                    p.translate(fx, fy)
                    p.rotate(math.sin(tt * 5 + i) * 40)
                    p.setPen(QPen(QColor("#ADB5BD"), 0.6))
                    p.setBrush(QColor("#FFFFFF"))
                    p.drawEllipse(QPointF(0, 0), 4.2, 1.6)
                    p.restore()
            if tt < 0.7:
                word = {"fist": "咚!", "hammer": "咚!", "paw": "啪!", "pillow": "噗!", "flick": "嘣!"}.get(weapon, "咚!")
                self._pop_word(p, word, hx + side * 10, hy - 16 - tt * 14, tt / 0.7)
        elif outcome in ("dodge", "counter") and 0.3 < t < 1.0:
            self._pop_word(p, "嗖~" if outcome == "dodge" else "看招!", self._cx() + d * 30, cy - 46 - (t - 0.3) * 12,
                           (t - 0.3) / 0.7)
        if outcome == "counter" and 0.75 < t < 1.1:              # 反击踢中的一圈短线
            k = (t - 0.75) / 0.35
            p.save()
            p.setOpacity(1 - k)
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            bx, by = self._cx() + side * 22, cy - 26
            for i in range(8):
                a = i / 8 * math.tau
                p.drawLine(QPointF(bx + math.cos(a) * (6 + 8 * k), by + math.sin(a) * (6 + 8 * k)),
                           QPointF(bx + math.cos(a) * (11 + 10 * k), by + math.sin(a) * (11 + 10 * k)))
            p.restore()

    def _pop_word(self, p: QPainter, word: str, x: float, y: float, k: float) -> None:
        f = QFont(self.font())
        f.setPixelSize(int(14 * (1 + 0.4 * max(0.0, 1 - k / 0.2))))
        f.setWeight(QFont.Weight.Black)
        p.save()
        p.setOpacity(max(0.0, min(1.0, (1 - k) / 0.3)))
        p.setFont(f)
        r = QRectF(x - 40, y - 12, 80, 24)
        opt = QTextOption(Qt.AlignmentFlag.AlignCenter)
        p.setPen(QColor(OUTLINE))
        for dx, dy in ((-1.2, 0), (1.2, 0), (0, -1.2), (0, 1.6)):
            p.drawText(r.translated(dx, dy), word, opt)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r, word, opt)
        p.restore()

    def _draw_weapon(self, p: QPainter, weapon: str, x: float, y: float, rot: float, alpha: float, side: int) -> None:
        if alpha <= 0.01:
            return
        p.save()
        p.setOpacity(max(0.0, min(1.0, alpha)))
        p.translate(x, y)
        p.rotate(rot)
        if side < 0:
            p.scale(-1, 1)
        draw_weapon(p, weapon, 13)
        p.restore()

    # ---- 2.4 新装扮
    def _paint_wear2(self, p: QPainter, now: float, cx: float, cy: float, ey: float, wear: set, out: QPen) -> None:
        thin = QPen(QColor(OUTLINE), 1.3)
        thin.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        top = cy - 22
        t = now - self._t0
        if "blush" in wear:                                 # 两团粉粉的腮红,带三道小斜线
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 120, 150, 120))
            for s in (-1, 1):
                p.drawEllipse(QPointF(cx + s * 17, ey + 6), 5.2, 3.2)
            p.setPen(QPen(QColor(230, 80, 120, 170), 0.9))
            for s in (-1, 1):
                for k in (-2, 0, 2):
                    p.drawLine(QPointF(cx + s * 17 + k - 1, ey + 7.2), QPointF(cx + s * 17 + k + 1, ey + 4.8))
        if "nerd" in wear:                                  # 圆框眼镜:透明镜片
            p.setPen(QPen(QColor("#5C4033"), 1.5))
            p.setBrush(QColor(255, 255, 255, 50))
            for s in (-1, 1):
                p.drawEllipse(QPointF(cx + s * 10, ey), 6.4, 6.4)
            p.drawLine(QPointF(cx - 3.6, ey - 0.6), QPointF(cx + 3.6, ey - 0.6))
            p.setPen(QPen(QColor(255, 255, 255, 190), 1.1))
            for s in (-1, 1):
                p.drawLine(QPointF(cx + s * 10 - 3.4, ey - 2.4), QPointF(cx + s * 10 - 1.6, ey - 4))
        if "monocle" in wear:                               # 单片眼镜 + 一条金链子
            p.setPen(QPen(QColor("#B8860B"), 1.6))
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawEllipse(QPointF(cx + 10, ey), 6.6, 6.6)
            chain = QPainterPath(QPointF(cx + 15.5, ey + 4))
            chain.cubicTo(cx + 20, ey + 12, cx + 24, ey + 14, cx + 25, ey + 22)
            p.setPen(QPen(QColor("#DAA520"), 0.9, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(chain)
        if "cherry" in wear:                                # 耳边:一对樱桃
            fx, fy = cx - 20, top + 6
            p.setPen(QPen(QColor("#2F9E44"), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            stem = QPainterPath(QPointF(fx - 3, fy + 2))
            stem.quadTo(fx, fy - 7, fx + 2, fy - 8)
            stem.quadTo(fx + 2, fy - 2, fx + 4, fy + 2)
            p.drawPath(stem)
            p.setPen(QPen(QColor("#A61E4D"), 1))
            p.setBrush(QColor("#F03E3E"))
            for dx in (-3, 4):
                p.drawEllipse(QPointF(fx + dx, fy + 4), 3.4, 3.4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 170))
            for dx in (-3, 4):
                p.drawEllipse(QPointF(fx + dx - 1.1, fy + 2.8), 0.9, 0.9)
        if "starclip" in wear:                              # 耳边:一颗会闪的星星发卡
            p.save()
            p.translate(cx + 20, top + 5)
            p.rotate(15)
            p.setPen(QPen(QColor("#E8A200"), 1))
            p.setBrush(QColor("#FFD43B"))
            p.drawPath(star_path(6.0, 0.45))
            tw = 0.5 + 0.5 * math.sin(t * 5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, int(90 + 140 * tw)))
            p.drawEllipse(QPointF(-1.2, -1.4), 1.2, 1.2)
            p.restore()
        if "chef" in wear:                                  # 白色高高的厨师帽
            p.setPen(thin)
            p.setBrush(QColor("#FFFFFF"))
            for dx, dy, r in ((-9, -10, 8.5), (9, -10, 8.5), (0, -16, 9.5)):
                p.drawEllipse(QPointF(cx + dx, top + dy), r, r)
            p.drawRoundedRect(QRectF(cx - 14, top - 9, 28, 14), 3, 3)
            p.setPen(QPen(QColor(200, 200, 210), 0.9))
            for dx in (-6, 0, 6):
                p.drawLine(QPointF(cx + dx, top - 5), QPointF(cx + dx, top + 3))
        if "witch" in wear:                                 # 尖尖的魔法帽,帽尖歪一下,带金色星星
            p.setPen(thin)
            p.setBrush(QColor("#5F3DC4"))
            p.drawEllipse(QPointF(cx, top + 4), 30, 5.5)
            cone = QPainterPath(QPointF(cx - 15, top + 3))
            cone.cubicTo(cx - 10, top - 14, cx - 2, top - 26, cx + 14, top - 30)
            cone.cubicTo(cx + 6, top - 20, cx + 10, top - 8, cx + 15, top + 3)
            cone.closeSubpath()
            p.drawPath(cone)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FAB005"))
            p.drawRect(QRectF(cx - 14.5, top - 2, 29.5, 3.6))
            p.save()
            p.translate(cx + 2, top - 12)
            p.drawPath(star_path(3.4, 0.45))
            p.restore()
        if "santa" in wear:                                 # 圣诞帽:红帽子、白毛边、垂下来的小球
            p.setPen(thin)
            p.setBrush(QColor("#E03131"))
            hat = QPainterPath(QPointF(cx - 24, top + 5))
            hat.cubicTo(cx - 20, top - 16, cx + 8, top - 22, cx + 26, top - 6)
            hat.lineTo(cx + 24, top + 5)
            hat.closeSubpath()
            p.drawPath(hat)
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(QRectF(cx - 27, top + 1, 54, 8.5), 4.2, 4.2)
            sway = math.sin(t * 2.2) * 1.5
            p.drawEllipse(QPointF(cx + 28 + sway, top - 4), 4.4, 4.4)
        if "horns" in wear:                                 # 一对小龙角
            p.setPen(QPen(QColor("#8C6D1F"), 1.2))
            p.setBrush(QColor("#F5D57A"))
            for s in (-1, 1):
                horn = QPainterPath(QPointF(cx + s * 8, top + 4))
                horn.cubicTo(cx + s * 9, top - 6, cx + s * 14, top - 12, cx + s * 18, top - 13)
                horn.cubicTo(cx + s * 16, top - 7, cx + s * 16, top - 1, cx + s * 15, top + 5)
                horn.closeSubpath()
                p.drawPath(horn)
                p.setPen(QPen(QColor(140, 109, 31, 140), 0.9))
                for k in (0.35, 0.6):
                    p.drawLine(QPointF(cx + s * (9 + 6 * k), top + 3 - 12 * k),
                               QPointF(cx + s * (14 + 2 * k), top + 3 - 11 * k))
                p.setPen(QPen(QColor("#8C6D1F"), 1.2))
        if "sprout" in wear:                                # 头顶一棵左右摇的小芽
            sway = math.sin(t * 2.6) * 3
            p.setPen(QPen(QColor("#2F9E44"), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            stem = QPainterPath(QPointF(cx, top + 3))
            stem.quadTo(cx, top - 6, cx + sway, top - 11)
            p.drawPath(stem)
            p.setPen(QPen(QColor("#2B8A3E"), 1))
            p.setBrush(QColor("#69DB7C"))
            for s in (-1, 1):
                leaf = QPainterPath(QPointF(cx + sway, top - 11))
                leaf.quadTo(cx + sway + s * 7, top - 18, cx + sway + s * 10, top - 11)
                leaf.quadTo(cx + sway + s * 5, top - 8, cx + sway, top - 11)
                p.drawPath(leaf)
        if "cloud" in wear:                                 # 头顶一朵飘着的小雨云,往下滴雨
            bob = math.sin(t * 1.8) * 1.5
            cy2 = top - 18 + bob
            p.setPen(QPen(QColor("#868E96"), 1))
            p.setBrush(QColor("#DEE2E6"))
            for dx, dy, r in ((-8, 1, 6), (0, -3, 8), (8, 1, 6)):
                p.drawEllipse(QPointF(cx + dx, cy2 + dy), r, r)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(cx - 13, cy2, 26, 7), 3.5, 3.5)
            p.setBrush(QColor(77, 171, 247, 200))
            for k, dx in enumerate((-7, 0, 7)):
                ph = (t * 1.6 + k * 0.33) % 1.0
                p.drawEllipse(QPointF(cx + dx, cy2 + 8 + ph * 12), 1.1, 2.0)
        if "aurora" in wear:                                # 满级:绕着头转的极光星环,颜色慢慢变
            p.save()
            p.setBrush(Qt.BrushStyle.NoBrush)
            for k in range(3):
                c = QColor.fromHsvF(((t * 0.08) + k * 0.12) % 1.0, 0.55, 1.0, 0.55 - k * 0.12)
                p.setPen(QPen(c, 2.4 - k * 0.6))
                p.drawEllipse(QPointF(cx, top - 12 + k * 1.2), 17 + k * 3, 4.2 + k * 0.8)
            for k in range(4):
                a = t * 1.6 + k * math.tau / 4
                sx, sy = cx + math.cos(a) * 18, top - 12 + math.sin(a) * 4.5
                p.save()
                p.translate(sx, sy)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor.fromHsvF(((t * 0.08) + k * 0.2) % 1.0, 0.35, 1.0, 0.95))
                p.drawPath(star_path(2.6, 0.45))
                p.restore()
            p.restore()

    def _acc_fairy(self, p: QPainter, now: float, cx: float, cy: float) -> None:
        flap = math.sin((now - self._t0) * 6) * 4
        for s in (-1, 1):
            for big, (dy, rx, ry, a) in enumerate(((-6, 18, 11, 0.55), (6, 12, 8, 0.45))):
                wing = QPainterPath()
                wing.addEllipse(QPointF(cx + s * (34 + flap * 0.4), cy + dy - flap * 0.6 * (1 - big)), rx, ry)
                g = QLinearGradient(cx, cy - 20, cx + s * 50, cy + 10)
                g.setColorAt(0, QColor.fromHsvF(0.55, 0.35, 1.0, a))
                g.setColorAt(1, QColor.fromHsvF(0.85, 0.35, 1.0, a))
                p.setPen(QPen(QColor(255, 255, 255, 200), 1))
                p.setBrush(QBrush(g))
                p.drawPath(wing)

    def _acc_raincoat(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 8
        coat = QPainterPath(QPointF(cx - 33, y - 1))
        coat.quadTo(cx, y + 3, cx + 33, y - 1)
        coat.lineTo(cx + 36, self.EDGE + 1)
        coat.lineTo(cx - 36, self.EDGE + 1)
        coat.closeSubpath()
        p.setPen(out)
        p.setBrush(QColor("#FFD43B"))
        p.drawPath(coat)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E8A200"))
        for k in (-3, 3):
            p.drawEllipse(QPointF(cx + k, y + 5), 1.4, 1.4)

    def _acc_overalls(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 7
        p.setPen(out)
        p.setBrush(QColor("#4C6EF5"))
        p.drawRoundedRect(QRectF(cx - 15, y, 30, 12), 3, 3)
        for s in (-1, 1):
            strap = QPainterPath(QPointF(cx + s * 11, y + 1))
            strap.lineTo(cx + s * 22, y - 9)
            strap.lineTo(cx + s * 26, y - 6)
            strap.lineTo(cx + s * 15, y + 3)
            strap.closeSubpath()
            p.drawPath(strap)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFD43B"))
        for s in (-1, 1):
            p.drawEllipse(QPointF(cx + s * 11, y + 3), 1.6, 1.6)
        p.setBrush(QColor(255, 255, 255, 90))
        p.drawRoundedRect(QRectF(cx - 5, y + 4, 10, 5), 1.5, 1.5)

    def _acc_tie(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 6
        p.setPen(QPen(QColor(OUTLINE), 1.1))
        p.setBrush(QColor("#1971C2"))
        p.drawPolygon(QPolygonF([QPointF(cx - 3.5, y - 2), QPointF(cx + 3.5, y - 2), QPointF(cx + 2, y + 2),
                                 QPointF(cx - 2, y + 2)]))
        body = QPainterPath(QPointF(cx - 2, y + 2))
        body.lineTo(cx + 2, y + 2)
        body.lineTo(cx + 4.5, y + 11)
        body.lineTo(cx, y + 14)
        body.lineTo(cx - 4.5, y + 11)
        body.closeSubpath()
        p.drawPath(body)
        p.setPen(QPen(QColor(255, 255, 255, 120), 1))
        p.drawLine(QPointF(cx - 2.5, y + 6), QPointF(cx + 3, y + 4))
        p.drawLine(QPointF(cx - 3.5, y + 10), QPointF(cx + 3.8, y + 7.5))

    def _acc_pearl(self, p: QPainter, cx: float) -> None:
        y = self.EDGE - 5
        p.setPen(QPen(QColor(200, 190, 180), 0.8))
        p.setBrush(QColor("#FFF8F0"))
        for k in range(-5, 6):
            x = cx + k * 5.2
            yy = y - 2 + (1 - (k / 5.5) ** 2) * 4.5
            p.drawEllipse(QPointF(x, yy), 2.4, 2.4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 220))
        for k in range(-5, 6):
            p.drawEllipse(QPointF(cx + k * 5.2 - 0.7, y - 2 + (1 - (k / 5.5) ** 2) * 4.5 - 0.8), 0.7, 0.7)

    def _acc_cape(self, p: QPainter, cx: float, cy: float, out: QPen) -> None:
        cape = QPainterPath(QPointF(cx - 24, cy - 4))
        cape.cubicTo(cx - 38, cy + 6, cx - 42, cy + 18, cx - 44, self.EDGE + 2)
        cape.lineTo(cx + 44, self.EDGE + 2)
        cape.cubicTo(cx + 42, cy + 18, cx + 38, cy + 6, cx + 24, cy - 4)
        cape.closeSubpath()
        p.setPen(out)
        p.setBrush(QColor("#D9363E"))
        p.drawPath(cape)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1.2))
        for k in (-34, 34):
            p.drawLine(QPointF(cx + k * 0.75, cy + 2), QPointF(cx + k, self.EDGE - 2))

    def _acc_hoodie(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 6
        band = QPainterPath(QPointF(cx - 32, y - 1))
        band.quadTo(cx, y + 4, cx + 32, y - 1)
        band.lineTo(cx + 34, self.EDGE + 1)
        band.lineTo(cx - 34, self.EDGE + 1)
        band.closeSubpath()
        p.setPen(out)
        p.setBrush(QColor("#9AA8F0"))
        p.drawPath(band)
        p.setPen(QPen(QColor("#FFFFFF"), 1.3))                  # 两根帽绳
        for k in (-6, 6):
            p.drawLine(QPointF(cx + k, y + 2.5), QPointF(cx + k * 1.1, self.EDGE + 0.5))
        p.setPen(out)

    def _acc_sailor(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 7
        p.setPen(out)
        p.setBrush(QColor("#2F4A8A"))
        for s in (-1, 1):
            collar = QPainterPath(QPointF(cx, y + 6))
            collar.lineTo(cx + s * 30, y - 2)
            collar.lineTo(cx + s * 33, self.EDGE + 1)
            collar.lineTo(cx + s * 6, self.EDGE + 1)
            collar.closeSubpath()
            p.drawPath(collar)
        p.setPen(QPen(QColor("#FFFFFF"), 1.1))
        for s in (-1, 1):
            p.drawLine(QPointF(cx + s * 8, self.EDGE - 1.5), QPointF(cx + s * 28, y + 0.5))
        p.setPen(QPen(QColor("#B8202A"), 1))
        p.setBrush(QColor("#E5383B"))
        for s in (-1, 1):
            knot = QPainterPath(QPointF(cx, y + 6))
            knot.lineTo(cx + s * 6, y + 3)
            knot.lineTo(cx + s * 6, y + 9)
            knot.closeSubpath()
            p.drawPath(knot)
        p.drawEllipse(QPointF(cx, y + 6), 1.8, 1.8)

    def _acc_bell(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 5
        band = QPainterPath(QPointF(cx - 29, y - 2))
        band.quadTo(cx, y + 3, cx + 29, y - 2)
        pen = QPen(QColor("#E5383B"), 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(band)
        swing = math.sin((_now() - self._t0) * 5) * 1.2
        p.setPen(QPen(QColor("#B8860B"), 1.0))
        p.setBrush(QColor("#FFD43B"))
        p.drawEllipse(QPointF(cx + swing, y + 3.5), 4.2, 4.2)
        p.setPen(QPen(QColor("#8B6508"), 1.0))
        p.drawLine(QPointF(cx + swing - 2.6, y + 3.4), QPointF(cx + swing + 2.6, y + 3.4))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#8B6508"))
        p.drawEllipse(QPointF(cx + swing, y + 5.4), 1.0, 1.0)

    def _acc_bowtie(self, p: QPainter, cx: float, out: QPen) -> None:
        y = self.EDGE - 3.5
        p.setPen(QPen(QColor(OUTLINE), 1.1))
        p.setBrush(QColor("#3D3D4E"))
        for s in (-1, 1):
            wing = QPainterPath(QPointF(cx, y))
            wing.lineTo(cx + s * 8, y - 4.5)
            wing.lineTo(cx + s * 8, y + 4.5)
            wing.closeSubpath()
            p.drawPath(wing)
        p.setBrush(QColor("#5A5A70"))
        p.drawRoundedRect(QRectF(cx - 2.2, y - 2.6, 4.4, 5.2), 1.2, 1.2)

    def _acc_scarf(self, p: QPainter, cx: float, out: QPen) -> None:
        """围巾:围在输入框边缘上方,一条小尾巴垂在一侧。"""
        y = self.EDGE - 6
        p.setPen(out)
        tail = QPainterPath(QPointF(cx + 12, y + 4))          # 垂下来的围巾尾巴,搭在输入框边上
        tail.lineTo(cx + 22, y + 4)
        tail.lineTo(cx + 24, y + 15)
        tail.lineTo(cx + 13, y + 15.5)
        tail.closeSubpath()
        p.setBrush(QColor("#F03E3E"))
        p.drawPath(tail)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.2))
        for k in (0, 4, 8):
            p.drawLine(QPointF(cx + 14 + k * 0.2, y + 15.5), QPointF(cx + 14 + k + 0.2, y + 18))
        p.setPen(out)
        p.setBrush(QColor("#FF6B6B"))
        band = QPainterPath(QPointF(cx - 31, y - 1))
        band.quadTo(cx, y + 5, cx + 31, y - 1)
        band.lineTo(cx + 30, y + 7.5)
        band.quadTo(cx, y + 13, cx - 30, y + 7.5)
        band.closeSubpath()
        p.drawPath(band)
        p.setPen(QPen(QColor(255, 255, 255, 160), 1.8))
        for k in (-21, -9, 3, 15):
            p.drawLine(QPointF(cx + k, y + 2.2 + abs(k) * -0.06), QPointF(cx + k, y + 9 + abs(k) * -0.1))

    def _paint_levelup(self, p: QPainter, now: float, cx: float) -> None:
        t = now - self._levelup_t
        if t > 2.0:
            return
        f = QFont(self.font())
        f.setWeight(QFont.Weight.Black)
        f.setPixelSize(12)
        p.setFont(f)
        c = QColor("#FFB000")
        c.setAlphaF(max(0.0, min(1.0, 2.0 - t)))
        rect = QRectF(cx - 40, self.EDGE - 56 - min(t, 1.0) * 4, 80, 16)
        sh = QColor(0, 0, 0, int(70 * c.alphaF()))
        p.setPen(sh)
        p.drawText(rect.translated(0, 1), f"Lv.{self._levelup_lv}!", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.setPen(c)
        p.drawText(rect, f"Lv.{self._levelup_lv}!", QTextOption(Qt.AlignmentFlag.AlignCenter))
        for k in range(6):                          # 围着转的小星星
            a = k / 6 * math.tau + t * 3
            r = 30 + t * 6
            sx, sy = cx + math.cos(a) * r, self.EDGE - 24 + math.sin(a) * r * 0.45
            s = QColor(["#FFD43B", "#FF8FAB", "#74C0FC"][k % 3])
            s.setAlphaF(c.alphaF())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(s)
            p.drawEllipse(QPointF(sx, sy), 1.8, 1.8)


# ====================================================================== 特效层
class _P:
    __slots__ = ("x", "y", "vx", "vy", "life", "ttl", "size", "color", "kind", "rot", "vr", "glyph", "grav",
                 "drag", "phase", "boom")

    def __init__(self, x, y, vx, vy, ttl, size, color, kind, grav=0.0, drag=0.0, glyph="", vr=0.0) -> None:
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.ttl = ttl
        self.size, self.color, self.kind = size, color, kind
        self.rot, self.vr = random.uniform(0, 360), vr
        self.glyph, self.grav, self.drag = glyph, grav, drag
        self.phase = random.uniform(0, math.tau)
        self.boom = False


FULL_KINDS = {"confetti", "balloon", "snow", "rain", "heart", "twinkle", "ember", "rocket", "fw", "emoji", "meteor",
              "prop"}
MAX_PARTICLES = 450


class EffectLayer(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.parts: list[_P] = []
        self.spawners: list[list] = []        # [结束时间, 每秒数量, 生成函数, 累计]
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._step)
        self._last = _now()
        self._dirty = QRect()

    # ---- 小特效
    def _palette(self) -> list[str]:
        return SPARK_COLORS.get(T.get("name", "light"), SPARK_COLORS["light"])

    FX_STYLE = {      # 主题 → (形状, 颜色, 重力, 存活时间倍数, 大小倍数)
        "sakura": (("petal",), ("#FFB7C5", "#FF9EB5", "#FFD1DC", "#F8A5C2"), 110, 1.7, 1.5),
        "snow": (("flake",), ("#FFFFFF", "#EAF4FF", "#D6E9FF"), 70, 1.9, 1.1),
        "star": (("star",), ("#FFD43B", "#FFE066", "#FFA94D", "#FFF3BF"), 200, 1.2, 1.25),
        "heart": (("heart",), ("#FF6B8A", "#FF8FAB", "#F06595", "#FFA8C0"), 120, 1.5, 1.5),
    }

    def sparks(self, x: float, y: float, combo: int = 1) -> None:
        n = 3 + min(combo // 6, 7)
        pal = self._palette()
        style = self.FX_STYLE.get(getattr(self, "fx_theme", "spark"))
        if style:
            kinds, cols, grav, life, size = style
            for _ in range(min(n, 6)):
                ang = random.uniform(-math.pi * 0.9, -math.pi * 0.1)
                sp = random.uniform(40, 110 + min(combo, 50))
                self._add(_P(x, y, math.cos(ang) * sp, math.sin(ang) * sp, random.uniform(0.45, 0.8) * life,
                             random.uniform(2.2, 3.6) * size, random.choice(cols), random.choice(kinds),
                             grav=grav, drag=1.8, vr=random.uniform(-220, 220)))
            return
        for _ in range(n):
            ang = random.uniform(-math.pi * 0.95, -math.pi * 0.05)
            sp = random.uniform(50, 140 + min(combo, 50) * 2)
            self._add(_P(x, y, math.cos(ang) * sp, math.sin(ang) * sp, random.uniform(0.35, 0.7),
                         random.uniform(1.8, 3.6), random.choice(pal), random.choice(("dot", "star", "dot")),
                         grav=260, drag=1.6))

    def fly_emoji(self, glyph: str, x0: float, y0: float, x1: float, y1: float, secs: float = 0.9) -> None:
        """一个表情从一点飞到另一点(小剧场里递东西用)。"""
        secs = max(0.2, secs)
        self._add(_P(x0, y0, (x1 - x0) / secs, (y1 - y0) / secs - 60, secs, 22, "", "prop", grav=120 / secs,
                     glyph=glyph))

    def fragments(self, x: float, y: float) -> None:
        for _ in range(3):
            self._add(_P(x, y, random.uniform(-40, 40), random.uniform(-80, -20), random.uniform(0.5, 0.8),
                         random.uniform(2.5, 4), T.get("faint", "#999999"), "frag", grav=700,
                         vr=random.uniform(-400, 400)))

    def send_burst(self, x: float, y: float) -> None:
        pal = self._palette()
        for i in range(18):
            ang = i / 18 * math.tau + random.uniform(-0.15, 0.15)
            sp = random.uniform(90, 190)
            self._add(_P(x, y, math.cos(ang) * sp, math.sin(ang) * sp, random.uniform(0.45, 0.8),
                         random.uniform(2.5, 4.5), random.choice(pal), random.choice(("star", "dot", "heart")),
                         grav=120, drag=2.2))

    # ---- 全屏特效
    def play(self, effect) -> None:
        if not effect or self.width() < 50:
            return
        name, glyph = (effect if isinstance(effect, tuple) else (effect, ""))
        w, h = self.width(), self.height()
        now = _now()
        if name == "confetti":
            for _ in range(130):
                self._add(_P(random.uniform(0, w), random.uniform(-h * 0.6, -10), random.uniform(-40, 40),
                             random.uniform(60, 180), random.uniform(3.0, 4.2), random.uniform(5, 9),
                             random.choice(CONFETTI_COLORS), "confetti", grav=60, drag=0.3,
                             vr=random.uniform(-260, 260)))
        elif name == "balloons":
            for i in range(11):
                self._add(_P(random.uniform(w * 0.05, w * 0.95), h + random.uniform(20, 260),
                             random.uniform(-10, 10), random.uniform(-150, -95), 6.0, random.uniform(17, 25),
                             random.choice(BALLOON_COLORS), "balloon"))
            for _ in range(50):
                self._add(_P(random.uniform(0, w), random.uniform(-h * 0.5, -10), random.uniform(-30, 30),
                             random.uniform(60, 140), 3.5, random.uniform(4, 7), random.choice(CONFETTI_COLORS),
                             "confetti", grav=50, drag=0.3, vr=random.uniform(-200, 200)))
        elif name == "fireworks":
            for i in range(6):
                self.spawners.append([now + 0.35 * i + 0.05, 0, self._rocket, 0.0, now + 0.35 * i])
        elif name == "snow":
            self.spawners.append([now + 3.8, 32, self._snowflake, 0.0, now])
        elif name == "petals":                       # 2.5 进群特效:花瓣雨
            self.spawners.append([now + 3.0, 30, self._petal, 0.0, now])
        elif name == "rain":
            self.spawners.append([now + 2.6, 110, self._raindrop, 0.0, now])
        elif name == "hearts":
            for _ in range(28):
                self._add(_P(random.uniform(w * 0.05, w * 0.95), h + random.uniform(0, 180), random.uniform(-15, 15),
                             random.uniform(-150, -80), random.uniform(3.2, 4.5), random.uniform(10, 20),
                             random.choice(("#FF6B8A", "#FF8FA3", "#FFB3C1", "#F06595")), "heart"))
        elif name == "stars":
            for _ in range(46):
                self._add(_P(random.uniform(0, w), random.uniform(60, h - 60), 0, 0, random.uniform(1.4, 3.2),
                             random.uniform(3, 7), random.choice(("#FFF3BF", "#FFE066", "#FFFFFF", "#D0BFFF")),
                             "twinkle"))
        elif name == "flames":
            self.spawners.append([now + 2.4, 70, self._ember, 0.0, now])
        elif name == "meteor":                       # 夜晚偶尔划过的流星
            x0 = random.uniform(w * 0.3, w * 1.0)
            sp = random.uniform(520, 760)
            ang = math.radians(random.uniform(145, 160))
            self._add(_P(x0, random.uniform(-20, h * 0.25), math.cos(ang) * sp, -math.sin(ang) * sp * -1,
                         1.4, 2.2, "#FFFFFF", "meteor"))
        elif name == "laugh":
            self._emoji_rain("😂")
        elif name == "emoji":
            self._emoji_rain(glyph or "✨")
        self._kick()

    def _emoji_rain(self, glyph: str) -> None:
        w, h = self.width(), self.height()
        for _ in range(30):
            self._add(_P(random.uniform(10, w - 10), random.uniform(-h * 0.7, -30), random.uniform(-15, 15),
                         random.uniform(110, 210), random.uniform(3.0, 4.0), random.uniform(20, 34), "", "emoji",
                         grav=90, glyph=glyph, vr=random.uniform(-60, 60)))

    def _rocket(self) -> None:
        w, h = self.width(), self.height()
        self._add(_P(random.uniform(w * 0.15, w * 0.85), h + 10, random.uniform(-30, 30),
                     random.uniform(-680, -520), 2.0, 2.6, "#FFF3BF", "rocket", grav=320))

    def _explode(self, x: float, y: float) -> None:
        pal = random.choice((CONFETTI_COLORS, self._palette(), ["#FFD43B", "#FF922B", "#FFF3BF"],
                             ["#74C0FC", "#B197FC", "#FFFFFF"]))
        for i in range(56):
            ang = i / 56 * math.tau
            sp = random.uniform(110, 230)
            self._add(_P(x, y, math.cos(ang) * sp, math.sin(ang) * sp, random.uniform(1.0, 1.6),
                         random.uniform(1.8, 3.0), random.choice(pal), "fw", grav=110, drag=1.1))

    def _snowflake(self) -> None:
        self._add(_P(random.uniform(0, self.width()), -10, random.uniform(-15, 15), random.uniform(40, 95),
                     6.0, random.uniform(2, 5), "#FFFFFF", "snow"))

    def _petal(self) -> None:
        self._add(_P(random.uniform(-30, self.width()), -14, random.uniform(15, 55), random.uniform(60, 120), 6.5,
                     random.uniform(4.2, 6.5), random.choice(("#FFB7C5", "#FF9EB5", "#FFD1DC", "#F8A5C2", "#FFC9DE")),
                     "petal", vr=random.uniform(-140, 140)))

    def _raindrop(self) -> None:
        self._add(_P(random.uniform(0, self.width() + 80), -20, -90, random.uniform(650, 850), 2.0,
                     random.uniform(10, 16), "#8AB4F8", "rain"))

    def _ember(self) -> None:
        self._add(_P(random.uniform(0, self.width()), self.height() + 5, random.uniform(-20, 20),
                     random.uniform(-160, -70), random.uniform(1.6, 2.6), random.uniform(2, 4.5),
                     random.choice(("#FFD43B", "#FF922B", "#FF6B6B", "#FFC078")), "ember", grav=-15))

    def clear(self) -> None:
        self.parts.clear()
        self.spawners.clear()
        self.timer.stop()
        self.update()

    def active(self) -> bool:
        return bool(self.parts or self.spawners)

    # ---- 引擎
    def _add(self, part: _P) -> None:
        if len(self.parts) < MAX_PARTICLES:
            self.parts.append(part)
        self._kick()

    def _kick(self) -> None:
        if not self.timer.isActive():
            self._last = _now()
            self.timer.start()

    def step(self, dt: float) -> None:
        """推进 dt 秒(测试里可以直接调用)。"""
        now = _now()
        for sp in list(self.spawners):
            end, rate, fn, acc, start = sp
            if now < start:
                continue
            if rate == 0:                                  # 一次性的定时生成(烟花)
                fn()
                self.spawners.remove(sp)
                continue
            acc += rate * dt
            while acc >= 1:
                fn()
                acc -= 1
            sp[3] = acc
            if now >= end:
                self.spawners.remove(sp)
        h = self.height()
        alive = []
        current, self.parts = self.parts, []           # 循环中新产生的粒子(烟花爆开)进新列表
        for p in current:
            p.life -= dt
            if p.kind in ("confetti", "snow", "heart", "balloon", "ember", "emoji"):
                p.x += math.sin(p.phase + (p.ttl - p.life) * (2.2 if p.kind != "balloon" else 1.2)) * 22 * dt
            p.vy += p.grav * dt
            if p.drag:
                k = max(0.0, 1.0 - p.drag * dt)
                p.vx *= k
                p.vy *= k
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.rot += p.vr * dt
            if p.kind == "rocket" and p.vy > -60 and not p.boom:
                p.boom = True
                self._explode(p.x, p.y)
                continue
            off = (p.y > h + 60 and p.vy > 0) or (p.y < -80 and p.vy < 0 and p.kind in ("balloon", "heart", "ember"))
            if p.life > 0 and not off:
                alive.append(p)
        self.parts = (alive + self.parts)[:MAX_PARTICLES]

    def _step(self) -> None:
        now = _now()
        dt = min(0.05, now - self._last)
        self._last = now
        if not self.isVisible():
            return
        self.step(dt)
        if not self.parts and not self.spawners:
            self.timer.stop()
            self.update()
            self._dirty = QRect()
            return
        if any(p.kind in FULL_KINDS for p in self.parts) or self.spawners:
            self.update()
            self._dirty = QRect()
        else:
            xs = [p.x for p in self.parts]
            ys = [p.y for p in self.parts]
            r = QRect(int(min(xs)) - 12, int(min(ys)) - 12, int(max(xs) - min(xs)) + 24, int(max(ys) - min(ys)) + 24)
            self.update(r.united(self._dirty))
            self._dirty = r

    def paintEvent(self, _e) -> None:
        if not self.parts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for part in self.parts:
            a = max(0.0, min(1.0, part.life / part.ttl))
            if part.kind in ("confetti", "balloon", "heart", "emoji", "snow"):
                a = min(1.0, part.life / 0.6)              # 这些只在最后淡出
            elif part.kind == "twinkle":
                a = math.sin(math.pi * (1 - part.life / part.ttl))
            if a <= 0.01:
                continue
            p.setOpacity(a)
            self._draw(p, part)
        p.end()

    def _draw(self, p: QPainter, q: _P) -> None:
        k = q.kind
        if k == "meteor":
            sp = math.hypot(q.vx, q.vy) or 1
            tx, ty = q.x - q.vx / sp * 120, q.y - q.vy / sp * 120
            g = QLinearGradient(QPointF(q.x, q.y), QPointF(tx, ty))
            g.setColorAt(0, QColor(255, 255, 255, 230))
            g.setColorAt(0.3, QColor(200, 220, 255, 120))
            g.setColorAt(1, QColor(200, 220, 255, 0))
            pen = QPen(QBrush(g), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(q.x, q.y), QPointF(tx, ty))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(q.x, q.y), 1.8, 1.8)
            return
        if k in ("dot", "fw", "ember", "snow"):
            p.setPen(Qt.PenStyle.NoPen)
            if k == "snow":
                p.setBrush(QColor(140, 160, 200, 90))
                p.drawEllipse(QPointF(q.x, q.y + 0.6), q.size + 0.8, q.size + 0.8)
            p.setBrush(QColor(q.color))
            p.drawEllipse(QPointF(q.x, q.y), q.size, q.size)
        elif k == "petal":                           # 樱花花瓣:一头尖的小椭圆,边飘边转
            p.save()
            p.translate(q.x, q.y)
            p.rotate(q.rot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(q.color))
            petal = QPainterPath(QPointF(0, -q.size))
            petal.cubicTo(q.size * 0.9, -q.size * 0.5, q.size * 0.7, q.size * 0.8, 0, q.size)
            petal.cubicTo(-q.size * 0.7, q.size * 0.8, -q.size * 0.9, -q.size * 0.5, 0, -q.size)
            petal.closeSubpath()
            p.drawPath(petal)
            p.restore()
        elif k == "flake":                           # 雪花:白点外面一圈淡蓝,浅色背景上也看得见
            p.setPen(QPen(QColor(120, 160, 220, 150), 0.9))
            p.setBrush(QColor(q.color))
            p.drawEllipse(QPointF(q.x, q.y), q.size, q.size)
        elif k in ("star", "twinkle"):
            p.save()
            p.translate(q.x, q.y)
            p.rotate(q.rot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(q.color))
            p.drawPath(star_path(q.size * 1.5))
            p.restore()
        elif k == "heart":
            p.save()
            p.translate(q.x, q.y)
            p.scale(1 + 0.08 * math.sin(q.phase + q.life * 8), 1 + 0.08 * math.sin(q.phase + q.life * 8))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(q.color))
            p.drawPath(heart_path(q.size))
            p.restore()
        elif k == "frag":
            p.save()
            p.translate(q.x, q.y)
            p.rotate(q.rot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(q.color))
            p.drawRoundedRect(QRectF(-q.size / 2, -q.size / 2, q.size, q.size), 1, 1)
            p.restore()
        elif k == "confetti":
            p.save()
            p.translate(q.x, q.y)
            p.rotate(q.rot)
            p.scale(max(0.15, abs(math.cos(q.phase + q.life * 6))), 1.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(q.color))
            p.drawRect(QRectF(-q.size / 2, -q.size / 4, q.size, q.size / 2))
            p.restore()
        elif k == "balloon":
            r = q.size
            string = QPainterPath(QPointF(q.x, q.y + r * 1.15))
            string.cubicTo(q.x - 6, q.y + r * 1.7, q.x + 6, q.y + r * 2.2, q.x - 2, q.y + r * 2.9)
            p.setPen(QPen(QColor(120, 120, 130, 160), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(string)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(q.color))
            p.drawEllipse(QPointF(q.x, q.y), r * 0.85, r)
            knot = QPainterPath(QPointF(q.x - 3, q.y + r * 1.15))
            knot.lineTo(q.x + 3, q.y + r * 1.15)
            knot.lineTo(q.x, q.y + r * 0.95)
            knot.closeSubpath()
            p.drawPath(knot)
            p.setBrush(QColor(255, 255, 255, 120))
            p.drawEllipse(QPointF(q.x - r * 0.3, q.y - r * 0.35), r * 0.18, r * 0.3)
        elif k == "rain":
            pen = QPen(QColor(q.color), 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(q.x, q.y), QPointF(q.x + q.vx * 0.02, q.y - q.size))
        elif k == "rocket":
            pen = QPen(QColor(255, 230, 180, 180), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(q.x, q.y), QPointF(q.x - q.vx * 0.04, q.y - q.vy * 0.04))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(q.color))
            p.drawEllipse(QPointF(q.x, q.y), q.size, q.size)
        elif k in ("emoji", "prop"):
            p.save()
            p.translate(q.x, q.y)
            p.rotate(q.rot)
            p.setFont(_emoji_font(q.size))
            p.setPen(QColor("#000000"))
            p.drawText(QRectF(-q.size, -q.size, q.size * 2, q.size * 2), q.glyph,
                       QTextOption(Qt.AlignmentFlag.AlignCenter))
            p.restore()


# ====================================================================== 对方正在输入
class TypingBubble(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(46)
        self._t0 = _now()
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.update)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.timer.start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.timer.stop()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(18, 6, 66, 34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(T["other"]))
        p.drawRoundedRect(rect, 17, 17)
        t = _now() - self._t0
        for i in range(3):
            lift = max(0.0, math.sin(t * 6.5 - i * 0.75))
            c = QColor(T["sub"])
            c.setAlphaF(0.45 + 0.5 * lift)
            p.setBrush(c)
            p.drawEllipse(QPointF(rect.left() + 19 + i * 14, rect.center().y() - 4 * lift), 3.6, 3.6)
        p.end()
