"""
密语 · 外观和氛围:随时间变化的背景、深夜护眼、气泡弹出动画、白噪音、统计和聊天年报。
"""
from __future__ import annotations

import datetime
import random
import re
import time

from PySide6.QtCore import QEasingCurve, QRectF, QVariantAnimation, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QTextOption
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from .. import sound as S, theme
from ..dialogs import Dialog
from ..icons import avatar
from ..theme import T
from ..ui import button, color_for
from ..widgets import Conv, Msg


EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐❤]")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def new_stats() -> dict:
    return {"since": time.time(), "days": {}, "hours": [0] * 24, "contacts": {}, "emoji": {}, "pokes": 0,
            "wins": 0, "losses": 0, "files": 0, "images": 0}


class EyeCare(QWidget):
    """深夜护眼:盖在整个窗口上的一层很淡的暖色,不挡鼠标。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 140, 40, 26))      # 偏暖
        p.fillRect(self.rect(), QColor(0, 0, 0, 34))           # 调暗
        p.end()


def peak_title(hours: list) -> str:
    if not hours or not any(hours):
        return "刚刚开始"
    h = hours.index(max(hours))
    if 0 <= h < 5:
        return "夜猫子 🌙"
    if 5 <= h < 9:
        return "早起的鸟儿 🌅"
    if 9 <= h < 12:
        return "上午效率王 ☕"
    if 12 <= h < 14:
        return "午休话痨 🍱"
    if 14 <= h < 18:
        return "下午摸鱼达人 🐟"
    if 18 <= h < 22:
        return "晚间畅聊家 🌆"
    return "深夜诗人 ✨"


class ReportCard(QWidget):
    """画出来的年报卡片(方便直接存成图片)。data 由主窗口汇总。"""
    W, H = 520, 760

    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data
        self.setFixedSize(self.W, self.H)

    def set_data(self, data: dict) -> None:
        self.data = data
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        self.paint(p)
        p.end()

    def paint(self, p: QPainter) -> None:
        d = self.data
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        W, H = self.W, self.H
        dark = theme.is_dark()
        g = QLinearGradient(0, 0, W, H)
        if dark:
            g.setColorAt(0, QColor("#1B1F3A"))
            g.setColorAt(1, QColor("#3A1F45"))
        else:
            g.setColorAt(0, QColor("#E9EEFF"))
            g.setColorAt(1, QColor("#FFE9EF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(0, 0, W, H), 22, 22)
        txt = QColor("#F4F4F8") if dark else QColor("#1D1D1F")
        sub = QColor("#B9B9C6") if dark else QColor("#6E6E78")
        tile = QColor(255, 255, 255, 22) if dark else QColor(255, 255, 255, 190)
        accent = QColor(T["accent"])

        def text(x, y, w, h, s, size, color, bold=False, align=Qt.AlignmentFlag.AlignLeft):
            f = QFont(self.font())
            f.setPixelSize(size)
            f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
            p.setFont(f)
            p.setPen(color)
            p.drawText(QRectF(x, y, w, h), s, QTextOption(align | Qt.AlignmentFlag.AlignVCenter))

        text(32, 28, 460, 24, d.get("period_label", ""), 13, sub)
        text(32, 52, 460, 40, d.get("title", "我的聊天报告"), 28, txt, True)
        text(32, 94, 460, 22, f"{d.get('nick', '')}  ·  称号:{d.get('badge', '')}", 14, accent, True)

        tiles = [("发出消息", d.get("sent", 0)), ("收到消息", d.get("recv", 0)), ("敲击键盘", d.get("keys", 0)),
                 ("活跃天数", d.get("days", 0))]
        for i, (name, val) in enumerate(tiles):
            x = 32 + (i % 2) * 234
            y = 132 + (i // 2) * 92
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tile)
            p.drawRoundedRect(QRectF(x, y, 222, 80), 16, 16)
            text(x + 16, y + 10, 200, 20, name, 13, sub)
            text(x + 16, y + 32, 200, 38, f"{val:,}", 28, txt, True)

        # 24 小时活跃度
        y0 = 330
        text(32, y0, 460, 22, "一天里最爱聊天的时段", 15, txt, True)
        hours = d.get("hours") or [0] * 24
        top = max(hours) or 1
        bw = 456 / 24
        for h_, v in enumerate(hours):
            bh = 70 * v / top
            c = QColor(accent)
            c.setAlphaF(0.35 + 0.65 * (v / top))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(32 + h_ * bw + 2, y0 + 104 - bh, bw - 4, max(2.0, bh)), 3, 3)
        for h_ in (0, 6, 12, 18, 23):
            text(32 + h_ * bw - 6, y0 + 108, 30, 16, f"{h_}时", 10, sub)

        # 聊得最多的人
        y1 = 470
        text(32, y1, 460, 22, "聊得最多的人", 15, txt, True)
        tops = d.get("contacts") or []
        if not tops:
            text(32, y1 + 30, 460, 20, "还没有私聊记录", 13, sub)
        for i, (nick, n, pid) in enumerate(tops[:3]):
            x = 32 + i * 156
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tile)
            p.drawRoundedRect(QRectF(x, y1 + 30, 146, 64), 14, 14)
            p.drawPixmap(int(x + 10), int(y1 + 42), avatar(nick, color_for(pid), 40))
            text(x + 58, y1 + 38, 84, 22, nick, 13, txt, True)
            text(x + 58, y1 + 60, 84, 20, f"{n:,} 条", 12, sub)

        # 最爱用的表情
        y2 = 590
        text(32, y2, 460, 22, "最爱用的表情", 15, txt, True)
        emos = d.get("emojis") or []
        if not emos:
            text(32, y2 + 30, 460, 20, "还没用过表情", 13, sub)
        for i, (e, n) in enumerate(emos[:7]):
            x = 32 + i * 66
            text(x, y2 + 26, 60, 36, e, 26, txt, align=Qt.AlignmentFlag.AlignHCenter)
            text(x, y2 + 62, 60, 16, f"×{n}", 11, sub, align=Qt.AlignmentFlag.AlignHCenter)

        foot = (f"戳一戳 {d.get('pokes', 0)} 次  ·  游戏 {d.get('wins', 0)} 胜 {d.get('losses', 0)} 负  ·  "
                f"文件 {d.get('files', 0)}  ·  图片 {d.get('images', 0)}  ·  宠物 Lv.{d.get('pet_level', 1)}")
        text(32, 690, 460, 20, foot, 12, sub)
        text(32, 714, 460, 18, "密语 · 只统计数量,不包含任何聊天内容,数据只在你的电脑上", 11, sub)


class ReportDialog(Dialog):
    def __init__(self, parent, build) -> None:
        """build(period) -> data,period 为 month / year / all。"""
        super().__init__(parent, "聊天年报")
        self.build = build
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        tabs = QHBoxLayout()
        tabs.addStretch(1)
        self.tabs = {}
        for key, name in (("month", "本月"), ("year", "今年"), ("all", "全部")):
            b = button(name, "tab", lambda _=False, k=key: self.show_period(k))
            b.setCheckable(True)
            tabs.addWidget(b)
            self.tabs[key] = b
        tabs.addStretch(1)
        lay.addLayout(tabs)
        self.card = ReportCard(build("year"))
        lay.addWidget(self.card, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("保存为图片", "", self.save_png, 110))
        ok = button("完成", "primary", self.accept, 90)
        row.addWidget(ok)
        lay.addLayout(row)
        self.show_period("year")

    def show_period(self, key: str) -> None:
        for k, b in self.tabs.items():
            b.setChecked(k == key)
        self.card.set_data(self.build(key))

    def save_png(self) -> None:
        from PySide6.QtCore import QStandardPaths
        import os
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        path, _ = QFileDialog.getSaveFileName(self, "保存年报", os.path.join(folder, "密语年报.png"), "PNG 图片 (*.png)")
        if path:
            self.card.grab().save(path, "PNG")


class LookMixin:
    """外观、氛围、统计。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_look(self) -> None:
        self.follow_time = False                 # 外观随时间变化
        self._time_period = None
        self.eyecare = True                      # 深夜护眼(22 点到 6 点自动)
        self.stats = new_stats()                 # 年报用的统计(只有数量)
        self.ambient = S.Ambient()
        self.ambient_kind: str | None = None
        self.ambient_volume = 0.4
        self._ambient_paused = False
        self.eye_overlay = EyeCare(self.centralWidget())

    def _restore_look(self, acct: dict, st: dict) -> None:
        self.follow_time = bool(st.get("follow_time", False))
        self.eyecare = bool(st.get("eyecare", True))
        try:
            self.ambient_volume = max(0.1, min(1.0, float(st.get("ambient_volume", 0.4))))
        except (TypeError, ValueError):
            pass
        if isinstance(acct.get("stats"), dict):
            s = new_stats()
            s.update({k: v for k, v in acct["stats"].items() if k in s})
            if not (isinstance(s["hours"], list) and len(s["hours"]) == 24):
                s["hours"] = [0] * 24
            self.stats = s

    def _save_look(self) -> dict:
        days = self.stats.get("days", {})
        if len(days) > 400:
            for k in sorted(days)[:-400]:
                days.pop(k, None)
        return {"stats": self.stats}

    def _settings_look(self) -> dict:
        return {"follow_time": self.follow_time, "eyecare": self.eyecare, "ambient_volume": self.ambient_volume}

    def _tick_look(self, now: float) -> None:
        self._tick_sky()
        if self._save_tick % 60 == 1:
            self._tick_eyecare()

    # ---------------------------------------------------------------- 随时间变化的背景
    def set_follow_time(self, on: bool) -> None:
        self.follow_time = on
        if on:
            self.follow_system = False
            self._time_period = None
            self._apply_time_theme()
        else:
            theme.apply(QApplication.instance(), T["name"])
            self._after_theme()

    def _apply_time_theme(self, hour: float | None = None) -> None:
        if not self.follow_time:
            return
        if hour is None:
            t = time.localtime()
            hour = t.tm_hour + t.tm_min / 60
        name, variant, label_ = theme.period_for(hour)
        if (name, variant) == self._time_period:
            return
        self._time_period = (name, variant)
        theme.apply(QApplication.instance(), name, variant=variant)
        self._after_theme()

    def _tick_sky(self) -> None:
        if self.follow_time and self._save_tick % 60 == 0:
            self._apply_time_theme()
        if (T.get("variant") == "night" and self.fun.get("effects") and self.window_visible()
                and random.random() < 1 / 240):
            self.effects.play("meteor")                # 夜里偶尔划过一颗流星

    # ---------------------------------------------------------------- 深夜护眼
    def set_eyecare(self, on: bool) -> None:
        self.eyecare = on
        self._tick_eyecare()

    def _tick_eyecare(self, hour: int | None = None) -> None:
        hour = time.localtime().tm_hour if hour is None else hour
        on = self.eyecare and (hour >= 22 or hour < 6)
        if on:
            self.eye_overlay.setGeometry(self.centralWidget().rect())
            self.eye_overlay.show()
            self.eye_overlay.raise_()
            if self.lock_overlay.isVisible():
                self.lock_overlay.raise_()
        else:
            self.eye_overlay.hide()

    # ---------------------------------------------------------------- 白噪音
    def set_ambient(self, kind: str | None) -> None:
        self.ambient_kind = kind
        self._ambient_paused = False
        if kind:
            self.ambient.play(kind, self.ambient_volume)
        else:
            self.ambient.stop()
        if hasattr(self, "pet"):
            self.pet.ambient_fx = kind or ""
            self.pet.update()
        dw = getattr(self, "desktop_win", None)
        if dw is not None:
            dw.pet.ambient_fx = kind or ""
            dw.update()
        isl = getattr(self, "island", None)
        if isl is not None:
            aname = dict(S.AMBIENT).get(kind or "", "") if kind else ""
            isl.set_ambient(aname)

    def set_ambient_volume(self, v: float) -> None:
        self.ambient_volume = v
        if self.ambient_kind:
            self.ambient.play(self.ambient_kind, v)

    def ambient_pause(self) -> None:
        """窗口藏起来时一定要静音。"""
        if self.ambient_kind and not self._ambient_paused:
            self.ambient.stop()
            self._ambient_paused = True

    def ambient_resume(self) -> None:
        if self.ambient_kind and self._ambient_paused:
            self._ambient_paused = False
            self.ambient.play(self.ambient_kind, self.ambient_volume)

    # ---------------------------------------------------------------- 统计 / 聊天年报
    def _stat_day(self) -> dict:
        days = self.stats.setdefault("days", {})
        return days.setdefault(_today(), {"sent": 0, "recv": 0, "keys": 0})

    def record_message(self, conv: Conv, m: Msg) -> None:
        if m.system:
            return
        day = self._stat_day()
        day["sent" if m.mine else "recv"] += 1
        self.stats["hours"][time.localtime(m.time).tm_hour] += 1
        if m.img is not None and m.mine:
            self.stats["images"] += 1
        if conv.kind == "dm" and conv.target:
            c = self.stats["contacts"].setdefault(conv.target, {"nick": conv.title, "n": 0})
            c["n"] += 1
            c["nick"] = conv.title
            if len(self.stats["contacts"]) > 300:
                low = sorted(self.stats["contacts"].items(), key=lambda kv: kv[1]["n"])[:50]
                for k, _ in low:
                    self.stats["contacts"].pop(k, None)
        if m.mine and m.text:
            for e in EMOJI_RE.findall(m.text):
                self.stats["emoji"][e] = self.stats["emoji"].get(e, 0) + 1

    def record_key(self) -> None:
        self._stat_day()["keys"] += 1

    def report_data(self, period: str) -> dict:
        now = datetime.date.today()
        days = self.stats.get("days", {})
        if period == "month":
            keys = [k for k in days if k.startswith(now.strftime("%Y-%m"))]
            plabel, title = f"{now.year} 年 {now.month} 月", "本月聊天报告"
        elif period == "year":
            keys = [k for k in days if k.startswith(str(now.year))]
            plabel, title = f"{now.year} 年", f"{now.year} 聊天年报"
        else:
            keys = list(days)
            since = datetime.date.fromtimestamp(self.stats.get("since", time.time()))
            plabel, title = f"{since.year}.{since.month}.{since.day} 至今", "我的聊天报告"
        sent = sum(days[k].get("sent", 0) for k in keys)
        recv = sum(days[k].get("recv", 0) for k in keys)
        keyn = sum(days[k].get("keys", 0) for k in keys)
        active = sum(1 for k in keys if days[k].get("sent", 0) + days[k].get("recv", 0) > 0)
        contacts = sorted(((c.get("nick", "?"), c.get("n", 0), pid) for pid, c in self.stats["contacts"].items()),
                          key=lambda x: -x[1])[:3]
        emojis = sorted(self.stats["emoji"].items(), key=lambda kv: -kv[1])[:7]
        return {"period_label": plabel, "title": title, "nick": self.me.get("nick", ""),
                "badge": peak_title(self.stats["hours"]), "sent": sent, "recv": recv, "keys": keyn,
                "days": active, "hours": list(self.stats["hours"]), "contacts": contacts, "emojis": emojis,
                "pokes": self.stats["pokes"], "wins": self.stats["wins"], "losses": self.stats["losses"],
                "files": self.stats["files"], "images": self.stats["images"], "pet_level": self.pet_growth.level}

    def show_report(self) -> None:
        ReportDialog(self, self.report_data).exec()
