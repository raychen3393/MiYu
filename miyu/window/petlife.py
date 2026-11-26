"""
密语 · 宠物照料和互动体系
  · 右键点宠物:喂食、玩耍、衣橱和形态
  · 饱腹度 / 心情随时间下降,饿了会撒娇
  · 跟随聊天:发消息举爪欢呼,别的会话来消息冒"!"招手
  · 衣橱:帽子、衣服、配饰、表情;形态:幼年 → 成长 → 进化 → 传说
  · 群宠物:每个暗号群一只,大家聊天、喂食一起养(没有服务器,用"每人一份计数取最大"同步)
  · 桌面陪伴(可选):窗口最小化时宠物趴在桌面角落,来消息会招手,点它回到密语
  · 等级标识:群聊里名字旁边显示宠物等级
"""
from __future__ import annotations

import math
import random
import sys
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen, QRadialGradient, QTextOption
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..dialogs import Dialog, TextDialog, info, prompt
from ..fun import (
    ACC_BY_ID, ACCESSORIES, ANTI_HOLD_LEVEL, DYE_PRESETS, OUTFITS, SLOTS, SPECIAL_TRICKS, SPECIES, TRICKS, PetGrowth,
    TypingPet, star_path,
)
from ..pet3d import COATS, EYE_STYLES, ROOMS
from ..petcare import (
    EXPRESSIONS, FOOD_BY_ID, FOODS, FORMS, GP_DAILY_FEEDS, GP_MSG_XP, GP_SPECIES, TOY_BY_ID, TOYS, GroupPet,
    form_of, next_form,
)
from ..theme import T, is_dark
from ..ui import button, label, make_menu, popup
from ..widgets import Conv
from .pet import PetHit

GPET_RESEND = 10.0                # 群宠物状态有变化时,最快 10 秒同步一次
SAY_CD = 6.0                      # 宠物提醒"有新消息"的最短间隔
THANKS = ("好好吃!谢谢~", "嗷呜,超满足!", "还想要~", "最喜欢你啦!")
PLAY_SAY = ("好好玩!", "再来再来!", "哈哈哈~", "累了但是开心!")
DESKTOP_MODES = [("roam", "任务栏自由漫步"), ("peek", "趴在活动窗口顶边"), ("fixed", "固定位置")]
_GLOBAL_VKS = (0x08, 0x0D, 0x20, *range(0x30, 0x3A), *range(0x41, 0x5B), *range(0xBA, 0xC1), *range(0xDB, 0xE0))


def _active_window_rect(ignore_hwnd: int) -> tuple[int, int, int, int] | None:
    """Windows:获取当前前台活动窗口矩形(用于桌宠趴在窗口顶边偷看)。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import ctypes.wintypes
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        if not hwnd or hwnd == ignore_hwnd or u32.IsIconic(hwnd):
            return None
        r = ctypes.wintypes.RECT()
        if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        if r.right - r.left < 220 or r.bottom - r.top < 120 or r.top < 10:
            return None
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


class DesktopPet(QWidget):
    """3.1 进阶桌宠:支持任务栏自由漫步、趴在活动窗口顶边偷看、固定位置,并可在最小化时响应全局打字节拍。"""

    def __init__(self, win) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.win = win
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(TypingPet.W, TypingPet.H + 6)
        self.pet = TypingPet(self)
        self.pet.bare = True
        self.pet.visitor = True
        self.pet.show_room = True
        self.pet.growth = win.pet_growth
        self.pet.set_species(win.fun.get("pet") or "cat")
        self.pet.move(0, 0)
        self.setToolTip("点我回到密语 · 按住拖动 · 右键切换漫步/偷看模式、签到、小游戏")
        self._press: QPoint | None = None
        self._moved = False
        self._vx = 1.6
        self._pause_until = 0.0
        self._sprint_until = 0.0
        self._prev_down: set[int] = set()
        self._last_hold_t = 0.0
        self._roam_timer = QTimer(self)
        self._roam_timer.setInterval(36)
        self._roam_timer.timeout.connect(self._roam_step)
        self._key_timer = QTimer(self)
        self._key_timer.setInterval(40)
        self._key_timer.timeout.connect(self._poll_global_keys)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._prev_down.clear()
        self._roam_timer.start()
        if sys.platform == "win32" and getattr(self.win, "desktop_global_keys", True):
            self._key_timer.start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._roam_timer.stop()
        self._key_timer.stop()
        self._prev_down.clear()

    def sync_timers(self) -> None:
        if not self.isVisible():
            return
        if sys.platform == "win32" and getattr(self.win, "desktop_global_keys", True):
            if not self._key_timer.isActive():
                self._key_timer.start()
        else:
            self._key_timer.stop()

    def notify_msg(self) -> None:
        """有新消息时叼着信封冲刺提醒。"""
        self._sprint_until = time.monotonic() + 2.4
        self._pause_until = 0.0
        self.pet.alert()
        self.pet.say("✉️ 有新消息~", 3.2)

    def _screen_rect(self) -> tuple[int, int, int, int]:
        try:
            geo = QGuiApplication.primaryScreen().availableGeometry()
            return geo.x(), geo.y(), geo.width(), geo.height()
        except Exception:
            return 0, 0, 1280, 720

    def _roam_step(self) -> None:
        if not self.isVisible() or self._press is not None or getattr(self.win, "desktop_locked", False):
            return
        mode = getattr(self.win, "desktop_mode", "roam")
        if mode == "fixed":
            return
        gx, gy, gw, gh = self._screen_rect()
        now = time.monotonic()
        if mode == "peek":
            try:
                my_hwnd = int(self.winId())
            except Exception:
                my_hwnd = 0
            rect = _active_window_rect(my_hwnd)
            if rect is not None:
                l, t, r, _b = rect
                tx = max(gx, min(gx + gw - self.width(), r - self.width() - 48))
                ty = max(gy, t - TypingPet.EDGE + 2)
                nx = int(self.x() + (tx - self.x()) * 0.22)
                ny = int(self.y() + (ty - self.y()) * 0.22)
                self.move(nx, ny)
                return
        # 任务栏上方自由漫步
        base_y = gy + gh - TypingPet.H - 6
        if now < self._pause_until:
            return
        speed = 4.6 if now < self._sprint_until else 1.35
        nx = self.x() + (speed if self._vx >= 0 else -speed)
        lo, hi = gx + 12, gx + gw - self.width() - 12
        if nx <= lo:
            nx, self._vx = lo, abs(self._vx)
            self._pause_until = now + random.uniform(1.0, 2.8)
        elif nx >= hi:
            nx, self._vx = hi, -abs(self._vx)
            self._pause_until = now + random.uniform(1.0, 2.8)
        elif now > self._sprint_until and random.random() < 0.008:
            self._pause_until = now + random.uniform(1.6, 4.2)
            if random.random() < 0.35:
                self._vx = -self._vx
        self.pet.mirror = self._vx < 0
        ny = int(self.y() + (base_y - self.y()) * 0.18)
        self.move(int(nx), ny)

    def _poll_global_keys(self) -> None:
        """隐私友好:仅检测敲击节拍(不记录任何按键字符),30 级及以上拦截长按连发刷经验。"""
        if not self.isVisible() or not getattr(self.win, "desktop_global_keys", True):
            return
        try:
            import ctypes
            u32 = ctypes.windll.user32
            hit_kind = None
            is_repeat = False
            down_now: set[int] = set()
            for vk in _GLOBAL_VKS:
                if u32.GetAsyncKeyState(vk) & 0x8000:
                    down_now.add(vk)
                    if vk not in self._prev_down:
                        hit_kind = "delete" if vk == 0x08 else ("enter" if vk == 0x0D else ("space" if vk == 0x20 else "char"))
            now = time.monotonic()
            if hit_kind is None and down_now and self.win.pet_growth.level < ANTI_HOLD_LEVEL and now - self._last_hold_t >= 0.12:
                self._last_hold_t = now
                hit_kind = "char"
                is_repeat = True
            self._prev_down = down_now
            if hit_kind is not None:
                self.pet.tap(hit_kind)
                if hasattr(self.win, "on_desktop_keybeat"):
                    self.win.on_desktop_keybeat(hit_kind, is_repeat=is_repeat)
        except Exception:
            pass

    def paintEvent(self, _e) -> None:
        """宠物下面的小台子(如果开了 2.5D 小窝场景则由小窝自己渲染底座)。"""
        if getattr(self.pet.growth, "room", "none") != "none":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.pet._cx()
        r = QRectF(cx - 52, TypingPet.EDGE - 1, 104, 12)
        p.setPen(QColor(0, 0, 0, 40))
        c = QColor(T["card"])
        c.setAlphaF(0.96)
        p.setBrush(c)
        p.drawRoundedRect(r, 6, 6)
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, e) -> None:
        if self._press is not None and not getattr(self.win, "desktop_locked", False):
            pos = e.globalPosition().toPoint() - self._press
            if (pos - self.pos()).manhattanLength() > 3:
                self._moved = True
                self.move(pos)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            if self._moved:
                self.win.desktop_pos = [self.x(), self.y()]
            else:
                self.win.restore_from_desktop()
            self._press = None

    def contextMenuEvent(self, e) -> None:
        m = make_menu(self)
        m.addAction("🤚  摸摸", self.pet.pat)
        mode_menu = make_menu(m)
        mode_menu.setTitle("🚶  桌宠行为模式")
        cur_m = getattr(self.win, "desktop_mode", "roam")
        for mid, mlabel in DESKTOP_MODES:
            a = mode_menu.addAction(mlabel, lambda k=mid: self.win.set_desktop_mode(k))
            a.setCheckable(True)
            a.setChecked(cur_m == mid)
        m.addMenu(mode_menu)
        gk = m.addAction("⌨  响应全局打字节拍(不记录按键内容)")
        gk.setCheckable(True)
        gk.setChecked(bool(getattr(self.win, "desktop_global_keys", True)))
        gk.triggered.connect(self.win.set_desktop_global_keys)
        lk = m.addAction("🔒  锁定位置(防误触拖动)")
        lk.setCheckable(True)
        lk.setChecked(bool(getattr(self.win, "desktop_locked", False)))
        lk.triggered.connect(self.win.set_desktop_locked)
        m.addSeparator()
        m.addAction("🎮  萌宠游乐厅（双塔防/全部小游戏）…", lambda: (self.win.restore_from_desktop(), self.win.show_arcade_hub()))
        m.addAction("🥕  萌宠保卫战（保卫萝卜风）…", lambda: (self.win.restore_from_desktop(), self.win.show_td_game()))
        m.addAction("🌻  萌宠大战捣蛋怪（植物大战僵尸风）…", lambda: (self.win.restore_from_desktop(), self.win.show_pvz_game()))
        m.addAction("🎁  每日签到与通行证…", lambda: (self.win.restore_from_desktop(), self.win.show_pet_pass()))
        m.addAction("🍉  合成大萌宠…", lambda: (self.win.restore_from_desktop(), self.win.show_merge_game()))
        m.addAction("🐟  接零食小游戏…", lambda: (self.win.restore_from_desktop(), self.win.show_snack_game()))
        m.addAction("☁️  云端跳跳乐…", lambda: (self.win.restore_from_desktop(), self.win.show_cloud_game()))
        m.addAction("🍅  专注番茄钟 / 喝水提醒…", lambda: (self.win.restore_from_desktop(), self.win.show_focus_dialog()))
        m.addAction("📸  萌宠双人合拍大头贴…", lambda: (self.win.restore_from_desktop(), self.win.show_photobooth()))
        m.addAction("👗  2.5D 潮玩衣橱…", lambda: (self.win.restore_from_desktop(), self.win.show_wardrobe()))
        m.addAction("💬  自定义台词与下班倒计时…", lambda: (self.win.restore_from_desktop(), self.win.show_pet_custom()))
        m.addAction("回到密语", self.win.restore_from_desktop)
        m.addSeparator()
        m.addAction("关闭桌面陪伴", lambda: self.win.set_desktop_pet(False))
        m.exec(e.globalPos())


_SLOT_GLYPH = {
    "head": ("👑", "#748FFC"), "ear": ("🎀", "#FF8FAB"), "face": ("🕶", "#4DABF7"),
    "neck": ("🧣", "#FF922B"), "body": ("🧥", "#9775FA"), "top": ("✨", "#FFD43B"),
    "hand": ("🧋", "#20C997"), "fx": ("🌟", "#F783AC"),
}


class _ShowcaseStage(QFrame):
    """3.7 潮玩展柜聚光舞台:顶光渐变展台 + 换装闪光粒子特效。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sparks: list[list[float]] = []       # [x, y, vx, vy, r, life, max_life, hue]
        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._step)

    def burst(self) -> None:
        cx, cy = self.width() / 2.0, self.height() * 0.56
        for i in range(14):
            a = i / 14 * math.tau + random.uniform(-0.2, 0.2)
            sp = random.uniform(35, 95)
            self._sparks.append([cx, cy, math.cos(a) * sp, math.sin(a) * sp - 20, random.uniform(2.5, 4.6),
                                 0.55, 0.55, random.choice((45.0, 270.0, 340.0, 195.0))])
        if not self._timer.isActive():
            self._timer.start()

    def _step(self) -> None:
        dt = 0.024
        nxt = []
        for s in self._sparks:
            s[5] -= dt
            if s[5] <= 0:
                continue
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[3] += 110.0 * dt
            nxt.append(s)
        self._sparks = nxt
        if not nxt:
            self._timer.stop()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        r = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
        dark = is_dark()
        bg = QLinearGradient(0, 0, 0, h)
        if dark:
            bg.setColorAt(0.0, QColor(42, 46, 68, 200))
            bg.setColorAt(1.0, QColor(24, 27, 42, 215))
        else:
            bg.setColorAt(0.0, QColor(255, 252, 248, 225))
            bg.setColorAt(1.0, QColor(238, 242, 255, 220))
        p.setPen(QPen(QColor(255, 255, 255, 65 if dark else 190), 1.2))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(r, 16, 16)
        # 柔和顶光聚光灯圆晕
        spot = QRadialGradient(QPointF(w / 2.0, h * 0.22), w * 0.62)
        spot.setColorAt(0.0, QColor(255, 245, 210, 58 if dark else 115))
        spot.setColorAt(0.6, QColor(150, 175, 255, 24 if dark else 38))
        spot.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(spot))
        p.drawRoundedRect(r, 16, 16)
        # 底部玻璃托盘光椭圆
        p.setBrush(QColor(255, 255, 255, 24 if dark else 145))
        p.drawEllipse(QPointF(w / 2.0, h - 18.0), w * 0.36, 9.0)
        # 换装闪光粒子
        for sx, sy, _vx, _vy, sr, life, ml, hue in self._sparks:
            p.save()
            p.setOpacity(max(0.0, min(1.0, life / ml)))
            p.translate(sx, sy)
            p.setBrush(QColor.fromHsvF(hue / 360.0, 0.55, 1.0))
            p.drawPath(star_path(sr, 0.45))
            p.restore()
        p.end()


class _AccCard(QPushButton):
    """3.7 潮玩展柜装扮卡片:2.5D 迷你徽标 + 稀有度边框(普通/高阶/扭蛋金边) + 已穿戴发光角标 + 磨砂锁层。"""

    def __init__(self, aid: str, name: str, lv: int, slot: str, parent=None) -> None:
        super().__init__(parent)
        self.aid, self.acc_name, self.lv, self.slot = aid, name, lv, slot
        self._unlocked = True
        self._worn = False
        self.setCheckable(True)
        self.setFixedHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, unlocked: bool, worn: bool) -> None:
        self._unlocked = unlocked
        self._worn = worn
        self.setEnabled(unlocked)
        self.setChecked(worn)
        self.update()

    def _rarity_color(self) -> QColor:
        if self.lv >= 999:
            return QColor("#FF8FAB")      # 扭蛋限定:粉金边框
        if self.lv >= 30:
            return QColor("#F5B301")      # 传说高阶:鎏金边框
        if self.lv >= 10:
            return QColor("#9775FA")      # 进阶:星紫边框
        return QColor("#4DABF7")          # 经典萌新:晴空蓝

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = float(self.width()), float(self.height())
        r = QRectF(1.5, 1.5, w - 3.0, h - 3.0)
        rc = self._rarity_color()
        dark = is_dark()
        hov = self.underMouse() and self._unlocked

        # 卡片底板
        if self._worn:
            bg = QColor(rc.red(), rc.green(), rc.blue(), 46 if dark else 34)
            border = QPen(rc, 2.0)
        elif hov:
            bg = QColor(255, 255, 255, 22 if dark else 190)
            border = QPen(QColor(rc.red(), rc.green(), rc.blue(), 170), 1.4)
        else:
            bg = QColor(255, 255, 255, 12 if dark else 135)
            border = QPen(QColor(rc.red(), rc.green(), rc.blue(), 85 if self._unlocked else 45), 1.1)
        p.setPen(border)
        p.setBrush(bg)
        p.drawRoundedRect(r, 12, 12)

        # 左侧 2.5D 迷你装扮徽标圆片
        glyph, sc = _SLOT_GLYPH.get(self.slot, ("✨", "#748FFC"))
        bx, by, br = 22.0, h / 2.0, 14.0
        bc = QColor(rc if self.lv >= 30 else sc)
        if not self._unlocked:
            bc = QColor("#868E96")
        bg_g = QRadialGradient(QPointF(bx - 4, by - 4), br * 1.4)
        bg_g.setColorAt(0.0, bc.lighter(135))
        bg_g.setColorAt(1.0, bc)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg_g))
        p.drawEllipse(QPointF(bx, by), br, br)
        ef = QFont()
        ef.setFamilies(["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji"])
        ef.setPixelSize(14)
        p.setFont(ef)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(bx - br, by - br, br * 2, br * 2), glyph, QTextOption(Qt.AlignmentFlag.AlignCenter))

        # 右侧名称 + 稀有度/解锁标签
        nf = QFont(self.font())
        nf.setPixelSize(11)
        nf.setWeight(QFont.Weight.DemiBold)
        p.setFont(nf)
        p.setPen(QColor(T["text"] if self._unlocked else T["faint"]))
        txt = p.fontMetrics().elidedText(self.acc_name, Qt.TextElideMode.ElideRight, max(24, int(w - 50)))
        p.drawText(QRectF(42, 8, w - 48, 19), txt, QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))

        sf = QFont(self.font())
        sf.setPixelSize(9)
        p.setFont(sf)
        sub = "扭蛋限定" if self.lv >= 999 else (f"Lv.{self.lv} 解锁" if not self._unlocked else ("已穿戴" if self._worn else f"Lv.{self.lv}"))
        p.setPen(rc if (self._worn or self.lv >= 30) and self._unlocked else QColor(T["faint"]))
        p.drawText(QRectF(42, 28, w - 48, 16), sub, QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))

        # 右上角状态角标 (已穿戴 ✓ / 未解锁 🔒)
        if self._worn:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rc)
            p.drawEllipse(QPointF(w - 12, 12), 7.5, 7.5)
            cf = QFont(self.font())
            cf.setPixelSize(9)
            cf.setWeight(QFont.Weight.Bold)
            p.setFont(cf)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QRectF(w - 19.5, 4.5, 15, 15), "✓", QTextOption(Qt.AlignmentFlag.AlignCenter))
        elif not self._unlocked:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 32 if dark else 18))
            p.drawRoundedRect(r, 12, 12)
            p.setFont(sf)
            p.setPen(QColor(T["faint"]))
            p.drawText(QRectF(w - 22, 4, 18, 16), "🔒", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class _DyeSwatchBtn(QPushButton):
    """3.7 马卡龙圆球染色钮:立体光泽色球 + 选中外光环 + 底部色名。"""

    def __init__(self, hex_c: str, cname: str, parent=None) -> None:
        super().__init__(parent)
        self.hex_c, self.cname = hex_c, cname
        self.setCheckable(True)
        self.setFixedSize(76, 54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = float(self.width()), float(self.height())
        sel = self.isChecked()
        hov = self.underMouse()
        cx, cy = w / 2.0, 20.0
        if sel or hov:
            p.setPen(QPen(QColor(self.hex_c or T["accent"]), 1.6 if sel else 1.0))
            p.setBrush(QColor(255, 255, 255, 28 if is_dark() else 160))
            p.drawRoundedRect(QRectF(1.5, 1.5, w - 3, h - 3), 12, 12)
        if self.hex_c:
            col = QColor(self.hex_c)
            if sel:
                p.setPen(QPen(QColor("#FFFFFF"), 2.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), 14.2, 14.2)
            g = QRadialGradient(QPointF(cx - 4, cy - 4), 16)
            g.setColorAt(0.0, col.lighter(135))
            g.setColorAt(0.75, col)
            g.setColorAt(1.0, col.darker(118))
            p.setPen(QPen(QColor(0, 0, 0, 35), 0.9))
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx, cy), 11.8, 11.8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 140))
            p.drawEllipse(QPointF(cx - 3.8, cy - 4.2), 3.2, 2.0)
        else:
            p.setPen(QPen(QColor(T["sub"]), 1.4, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 11.5, 11.5)
            p.setPen(QColor(T["text"]))
            p.drawText(QRectF(cx - 12, cy - 12, 24, 24), "↩", QTextOption(Qt.AlignmentFlag.AlignCenter))
        f = QFont(self.font())
        f.setPixelSize(10)
        f.setWeight(QFont.Weight.DemiBold if sel else QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(T["text"] if sel else T["sub"]))
        p.drawText(QRectF(2, 34, w - 4, 18), self.cname, QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class WardrobeDialog(Dialog):
    """衣橱和形态(3.7 潮玩展柜版):聚光展示台 + 装扮卡片 + 马卡龙染色球 + 6套一键穿搭方案。"""

    def __init__(self, win) -> None:
        super().__init__(win, "衣橱和形态")
        self.win = win
        g = self.g = win.pet_growth
        g.care()
        self.setFixedWidth(790)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 16)
        lay.setSpacing(10)
        head_row = QHBoxLayout()
        head_row.addWidget(label(f"{g.name} 的 2.5D 潮玩展柜衣橱", "dialogTitle"))
        head_row.addStretch(1)
        self.sp_btns: dict[str, QPushButton] = {}
        for skey, sspec in SPECIES.items():
            sb = QPushButton(sspec["label"])
            sb.setObjectName("tab")
            sb.setCheckable(True)
            sb.setChecked((win.fun.get("pet") or "cat") == skey)
            sb.setCursor(Qt.CursorShape.PointingHandCursor)
            sb.clicked.connect(lambda _=False, k=skey: self.pick_species(k))
            head_row.addWidget(sb)
            self.sp_btns[skey] = sb
        lay.addLayout(head_row)

        top = QHBoxLayout()
        stage = self.stage_frame = _ShowcaseStage(self)
        stage.setFixedSize(TypingPet.W + 18, TypingPet.H + 26)
        self.preview = TypingPet(stage)
        self.preview.bare = True
        self.preview.centered = True
        self.preview.visitor = True
        self.preview.show_room = True
        self.preview.growth = g
        self.preview.set_species(win.pet.species)
        self.preview.move(9, 14)
        self.preview_hit = PetHit(
            stage,
            lambda: (self.preview.pat(), g.cheer(4), self.mood.setText(f"现在:{g.mood_word()}")),
            tip="轻点摸摸 · 按住拖拽可 Q 弹捏脸!",
            pet_getter=lambda: self.preview,
        )
        self.preview_hit.setGeometry(stage.rect())
        self.preview_hit.raise_()
        top.addWidget(stage)
        col = QVBoxLayout()
        col.setSpacing(4)
        idx, fname, fdesc = form_of(g.level)
        nf = next_form(g.level)
        col.addWidget(label(f"Lv.{g.level}  ·  {fname}", "cardTitle"))
        col.addWidget(label(fdesc + (f"\n再升到 Lv.{nf[0]} 进入「{nf[1]}」" if nf else "\n已经是最终形态"), "fileSub",
                            wrap=True))
        self.food_bar, self.joy_bar = QProgressBar(), QProgressBar()
        for name, bar, v in (("饱腹", self.food_bar, g.food), ("心情", self.joy_bar, g.joy)):
            row = QHBoxLayout()
            row.addWidget(label(name, "faint"))
            bar.setObjectName("fileProgress")
            bar.setRange(0, 100)
            bar.setValue(int(v))
            bar.setTextVisible(False)
            row.addWidget(bar, 1)
            col.addLayout(row)
        self.mood = label(f"现在:{g.mood_word()}", "hint")
        col.addWidget(self.mood)
        col.addStretch(1)
        top.addLayout(col, 1)
        lay.addLayout(top)

        tabs = QHBoxLayout()
        tabs.setSpacing(2)
        self.stack = QStackedWidget()
        self.tab_btns: list[QPushButton] = []
        self.item_btns: dict[str, _AccCard] = {}
        self.expr_btns: dict[str, QPushButton] = {}
        self.coat_btns: dict[str, QPushButton] = {}
        self.eye_btns: dict[str, QPushButton] = {}
        self.room_btns: dict[str, QPushButton] = {}
        self.outfit_rows: dict[str, tuple] = {}
        self.preset_rows: dict[str, tuple] = {}
        self.trick_btns: dict[str, QPushButton] = {}
        pages = [(name, self._acc_page(slot)) for slot, name in SLOTS]
        pages += [("方案", self._preset_page()), ("套装", self._outfit_page()), ("染色", self._dye_page()),
                  ("毛色", self._coat_page()), ("瞳色", self._eye_page()), ("小窝", self._room_page()),
                  ("动作", self._trick_page()), ("表情", self._expr_page()), ("形态", self._form_page())]
        tabs2 = QHBoxLayout()
        tabs2.setSpacing(2)
        for i, (name, page) in enumerate(pages):
            b = QPushButton(name)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.show_tab(i))
            (tabs if i < len(SLOTS) else tabs2).addWidget(b)
            self.tab_btns.append(b)
            self.stack.addWidget(page)
        tabs.addStretch(1)
        tabs2.addStretch(1)
        lay.addLayout(tabs)
        lay.addLayout(tabs2)
        self.stack.setFixedHeight(236)
        lay.addWidget(self.stack)
        self.tip = label("", "faint", wrap=True)
        lay.addWidget(self.tip)
        self._only_unlocked = False
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(button("🎁 签到/通行证", "", self.win.show_pet_pass, 114))
        row.addWidget(button("🎮 萌宠游乐厅", "", self.win.show_arcade_hub, 108))
        row.addWidget(button("📸 合拍大头贴", "", self.win.show_photobooth, 108))
        row.addWidget(button("🎲 随机穿搭", "", self.random_outfit, 96))
        self.filter_btn = QPushButton("仅看已解锁")
        self.filter_btn.setObjectName("tab")
        self.filter_btn.setCheckable(True)
        self.filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_btn.clicked.connect(self._toggle_filter)
        row.addWidget(self.filter_btn)
        row.addStretch(1)
        row.addWidget(button("完成", "primary", self.accept, 80))
        lay.addLayout(row)
        self.show_tab(0)
        self.refresh()

    def _toggle_filter(self) -> None:
        self._only_unlocked = self.filter_btn.isChecked()
        self.refresh(keep_tip=True)

    def random_outfit(self) -> None:
        """从已解锁装扮里按部位随机混搭一套。"""
        self.g.wear.clear()
        for slot, _sname in SLOTS:
            pool = [a[0] for a in ACCESSORIES if a[3] == slot and self.g.is_unlocked(a[0])]
            if pool and random.random() < 0.72:
                self.g.toggle(random.choice(pool))
        self.preview.celebrate()
        self.stage_frame.burst()
        self.tip.setText("🎲 已为你随机混搭了一套新造型!")
        self.refresh(keep_tip=True)

    def _grid_page(self) -> tuple[QWidget, QGridLayout]:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setSpacing(6)
        return page, grid

    def _wrap_scroll(self, inner: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(inner)
        return area

    def _acc_page(self, slot: str) -> QWidget:
        page, grid = self._grid_page()
        items = [a for a in ACCESSORIES if a[3] == slot]
        for i, (aid, name, lv, _slot) in enumerate(items):
            b = _AccCard(aid, name, lv, slot, page)
            b.clicked.connect(lambda _=False, a=aid: self.toggle(a))
            grid.addWidget(b, i // 4, i % 4)
            self.item_btns[aid] = b
        grid.setRowStretch(len(items) // 4 + 1, 1)
        return self._wrap_scroll(page)

    def _preset_page(self) -> QWidget:
        """3.7 穿搭方案页:6 个独立槽位,一键保存/切换完整穿搭(含装扮+染色+毛色+瞳色+小窝+种类)。"""
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setSpacing(8)
        for i in range(6):
            sk = str(i + 1)
            box = QFrame()
            box.setObjectName("plainCard")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 8, 10, 8)
            bl.setSpacing(4)
            trow = QHBoxLayout()
            title_lab = label(f"方案 {sk}", "cardTitle")
            trow.addWidget(title_lab, 1)
            ren_btn = button("改名", "link", lambda _=False, s=sk: self._rename_preset(s), 40)
            clr_btn = button("清空", "link", lambda _=False, s=sk: self._clear_preset(s), 40)
            trow.addWidget(ren_btn)
            trow.addWidget(clr_btn)
            bl.addLayout(trow)
            sub_lab = label("空槽位 — 点击下方「保存当前」记录整套搭配", "fileSub", wrap=True)
            bl.addWidget(sub_lab)
            brow = QHBoxLayout()
            brow.setSpacing(6)
            save_btn = button("保存当前", "", lambda _=False, s=sk: self._save_preset(s), 86)
            save_btn.setMinimumHeight(28)
            apply_btn = button("一键换上", "primary", lambda _=False, s=sk: self._apply_preset(s), 86)
            apply_btn.setMinimumHeight(28)
            brow.addWidget(save_btn)
            brow.addWidget(apply_btn)
            brow.addStretch(1)
            bl.addLayout(brow)
            grid.addWidget(box, i // 2, i % 2)
            self.preset_rows[sk] = (title_lab, sub_lab, apply_btn, ren_btn, clr_btn)
        return self._wrap_scroll(page)

    def _save_preset(self, slot: str) -> None:
        cur = self.g.presets.get(slot, {})
        name = cur.get("name") or f"方案 {slot}"
        self.g.save_preset(slot, name, self.preview.species)
        self.stage_frame.burst()
        self.tip.setText(f"💾 已保存当前整套穿搭到「{name}」（含装扮、染色、毛色、瞳色与小窝）!")
        self.refresh(keep_tip=True)

    def _apply_preset(self, slot: str) -> None:
        if slot not in self.g.presets:
            return
        sp = self.g.apply_preset(slot)
        if sp and sp in SPECIES:
            self.win.set_fun("pet", sp)
            self.preview.set_species(sp)
            for k, b in self.sp_btns.items():
                b.setChecked(k == sp)
        self.preview.celebrate()
        self.stage_frame.burst()
        self.tip.setText(f"✨ 已一键换上「{self.g.presets[slot].get('name', '方案')}」!")
        self.refresh(keep_tip=True)

    def _rename_preset(self, slot: str) -> None:
        if slot not in self.g.presets:
            return
        cur = self.g.presets[slot].get("name", f"方案 {slot}")
        nv = prompt(self, "给穿搭方案起个名字", "最多 12 个字，例如：赛博酷猫 / 温泉浴鸭", cur, max_len=12, ok="保存")
        if nv is not None and nv.strip():
            self.g.presets[slot]["name"] = nv.strip()[:12]
            self.refresh(keep_tip=True)

    def _clear_preset(self, slot: str) -> None:
        if self.g.delete_preset(slot):
            self.tip.setText(f"已清空方案 {slot}。")
            self.refresh(keep_tip=True)

    def _outfit_page(self) -> QWidget:
        """套装:一键穿上;集齐全部部件身后会有一圈套装颜色的光。"""
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setSpacing(6)
        for i, (oid, name, parts, color) in enumerate(OUTFITS):
            box = QFrame()
            box.setObjectName("plainCard")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 6, 10, 6)
            bl.setSpacing(2)
            top = QHBoxLayout()
            dot = label("●", "")
            dot.setStyleSheet(f"color: {color};")
            top.addWidget(dot)
            top.addWidget(label(name, "cardTitle"), 1)
            btn = button("一键穿上", "", lambda _=False, o=oid: self.wear_outfit(o), 78)
            btn.setMinimumHeight(26)
            top.addWidget(btn)
            bl.addLayout(top)
            parts_lab = label("", "fileSub", wrap=True)
            bl.addWidget(parts_lab)
            grid.addWidget(box, i // 2, i % 2)
            self.outfit_rows[oid] = (btn, parts_lab, box)
        return self._wrap_scroll(page)

    def _trick_page(self) -> QWidget:
        page, grid = self._grid_page()
        all_items = [(need, tid, name, False) for need, tid, name, _d in TRICKS]
        all_items += [(0, tid, name, True) for tid, name, _d in SPECIAL_TRICKS]
        for i, (_need, tid, name, _sp) in enumerate(all_items):
            b = QPushButton(name)
            b.setObjectName("choice")
            b.setMinimumHeight(38)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=tid: self.play_trick(t))
            grid.addWidget(b, i // 5, i % 5)
            self.trick_btns[tid] = b
        grid.setRowStretch(4, 1)
        return page

    def _dye_page(self) -> QWidget:
        """3.7 马卡龙圆球调色盘:支持全部 8 个部位 + 自动高亮已穿戴部位 + 实时目标提示。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)
        self._dye_slot = "head"
        slot_row = QHBoxLayout()
        slot_row.setSpacing(3)
        self.dye_slot_btns: dict[str, QPushButton] = {}
        for sk, sname in SLOTS:
            sb = QPushButton(sname)
            sb.setObjectName("tab")
            sb.setCheckable(True)
            sb.setChecked(sk == self._dye_slot)
            sb.setCursor(Qt.CursorShape.PointingHandCursor)
            sb.clicked.connect(lambda _=False, s=sk: self._pick_dye_slot(s))
            slot_row.addWidget(sb)
            self.dye_slot_btns[sk] = sb
        slot_row.addStretch(1)
        lay.addLayout(slot_row)

        self.dye_target_lab = label("", "hint")
        lay.addWidget(self.dye_target_lab)

        grid = QGridLayout()
        grid.setSpacing(6)
        self.dye_color_btns: dict[str, _DyeSwatchBtn] = {}
        for i, (hex_c, cname) in enumerate(DYE_PRESETS):
            b = _DyeSwatchBtn(hex_c, cname, page)
            b.clicked.connect(lambda _=False, c=hex_c: self.set_dye(c))
            grid.addWidget(b, i // 6, i % 6, Qt.AlignmentFlag.AlignCenter)
            self.dye_color_btns[hex_c] = b
        lay.addLayout(grid)
        lay.addStretch(1)
        return page

    def _worn_in_slot(self, slot: str) -> str | None:
        return next((w for w in self.g.wear if ACC_BY_ID.get(w, ("", "", 0, ""))[3] == slot), None)

    def _pick_dye_slot(self, slot: str) -> None:
        self._dye_slot = slot
        for sk, b in self.dye_slot_btns.items():
            b.setChecked(sk == slot)
        self.refresh(keep_tip=True)

    def set_dye(self, color: str) -> None:
        self.g.set_dye(self._dye_slot, color)
        self.stage_frame.burst()
        self.refresh(keep_tip=True)

    def wear_outfit(self, oid: str) -> None:
        missing = self.g.wear_outfit(oid)
        self.stage_frame.burst()
        self.tip.setText(("还差没解锁的:" + "、".join(missing) + "(升级或抽卡获得)") if missing else "整套穿上了!身后有一圈套装光效。")
        self.refresh(keep_tip=True)

    def play_trick(self, tid: str) -> None:
        self.preview.trick(tid)
        self.win.pet.trick(tid)

    def _expr_page(self) -> QWidget:
        page, grid = self._grid_page()
        for i, (eid, name, lv) in enumerate(EXPRESSIONS):
            b = QPushButton(name)
            b.setObjectName("choice")
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, e=eid: self.set_expr(e))
            grid.addWidget(b, i // 4, i % 4)
            self.expr_btns[eid] = b
        grid.setRowStretch(2, 1)
        return page

    def _coat_page(self) -> QWidget:
        page, grid = self._grid_page()
        for i, (cid, name, _lv) in enumerate(COATS):
            b = QPushButton(name)
            b.setObjectName("choice")
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=cid: self.set_coat(c))
            grid.addWidget(b, i // 4, i % 4)
            self.coat_btns[cid] = b
        grid.setRowStretch(3, 1)
        return page

    def _eye_page(self) -> QWidget:
        page, grid = self._grid_page()
        for i, (eid, name, _lv, _cols) in enumerate(EYE_STYLES):
            b = QPushButton(name)
            b.setObjectName("choice")
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, e=eid: self.set_eyes(e))
            grid.addWidget(b, i // 4, i % 4)
            self.eye_btns[eid] = b
        grid.setRowStretch(2, 1)
        return page

    def _room_page(self) -> QWidget:
        page, grid = self._grid_page()
        for i, (rid, name, _lv) in enumerate(ROOMS):
            b = QPushButton(name)
            b.setObjectName("choice")
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, r=rid: self.set_room(r))
            grid.addWidget(b, i // 4, i % 4)
            self.room_btns[rid] = b
        grid.setRowStretch(2, 1)
        return page

    def _form_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(4, 6, 4, 0)
        col.setSpacing(4)
        cur = form_of(self.g.level)[0]
        for i, (need, name, desc) in enumerate(FORMS):
            mark = "▶ " if i == cur else ("✓ " if i < cur else "🔒 ")
            col.addWidget(label(f"{mark}{name}  ·  Lv.{need}  ·  {desc}", "cardTitle" if i == cur else "fileSub"))
        col.addStretch(1)
        return page

    TIPS = {"方案": "最多保存 6 套专属穿搭方案(含全部装扮、染色、毛色、瞳色、小窝与宠物种类),一键切换!",
            "套装": "一键穿上套装里已经解锁的部件;集齐整套,身后会有一圈套装颜色的光。",
            "染色": "支持全部 8 个部位、128 件装扮自由染色!带 ✓ 的部位表示已穿戴,点击马卡龙色球立即变色。",
            "毛色": "基因花色:暹罗挖煤脸、三花斑点、黑白奶牛、樱花奶霜等,串门和拍合照时朋友也能看到。",
            "瞳色": "更换 3D 虹膜颜色,Lv.12 解锁超人气的蓝金「鸳鸯异瞳」。",
            "小窝": "微缩 2.5D 景深小窝底座,在衣橱和「桌面陪伴」里生效(阳光软垫的窗外会随日夜变化)。",
            "动作": "每 5 级学会一个新动作。宠物闲着时会自己表演,在这里点一下马上表演。",
            "表情": "平时的表情。把鼠标移到上方预览区,TA 会跟着你的鼠标立体转头,按住脸颊还能捏脸!",
            "形态": "10 级长大,20 级第一次进化,30 级传说期,40 级第二次进化(神话期)。"}

    def pick_species(self, skey: str) -> None:
        if skey not in SPECIES:
            return
        self.win.set_fun("pet", skey)
        self.preview.set_species(skey)
        for k, b in self.sp_btns.items():
            b.setChecked(k == skey)
        self.refresh(keep_tip=True)

    def show_tab(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.tab_btns):
            b.setChecked(i == j)
        name = self.tab_btns[i].text()
        if name == "染色" and self._worn_in_slot(getattr(self, "_dye_slot", "head")) is None:
            for sk, _sn in SLOTS:
                if self._worn_in_slot(sk) is not None:
                    self._dye_slot = sk
                    break
            self.refresh(keep_tip=True)
        self.tip.setText(self.TIPS.get(name, "装扮随等级解锁,也能抽卡提前拿到。同一个部位一次戴一件,再点一下摘下。"))

    def toggle(self, aid: str) -> None:
        self.g.toggle(aid)
        self.stage_frame.burst()
        self.refresh()

    def set_expr(self, eid: str) -> None:
        self.g.set_expr(eid)
        self.refresh()

    def set_coat(self, cid: str) -> None:
        self.g.set_coat(cid)
        self.refresh()

    def set_eyes(self, eid: str) -> None:
        self.g.set_eyes(eid)
        self.refresh()

    def set_room(self, rid: str) -> None:
        self.g.set_room(rid)
        self.refresh()

    def refresh(self, keep_tip: bool = False) -> None:
        g = self.g
        for aid, b in self.item_btns.items():
            a = ACC_BY_ID[aid]
            ok = g.is_unlocked(aid)
            b.setVisible(ok or not getattr(self, "_only_unlocked", False))
            b.set_state(ok, aid in g.wear)
            sets = [o[1] for o in OUTFITS if aid in o[2]]
            tip_lock = "扭蛋限定(每日免费券/十连扭即可抽到)" if a[2] >= 999 else f"Lv.{a[2]} 解锁(也能抽卡提前抽到)"
            b.setToolTip((tip_lock if not ok else "点一下戴上 / 摘下")
                         + (f"\n属于套装:{'、'.join(sets)}" if sets else ""))
        for sk, (tlab, slab, abtn, rbtn, cbtn) in getattr(self, "preset_rows", {}).items():
            pr = g.presets.get(sk)
            if pr:
                sp_name = SPECIES.get(pr.get("species", ""), {}).get("label", "当前形态")
                tlab.setText(f"✨ {pr.get('name') or f'方案 {sk}'}")
                slab.setText(f"{sp_name} · {len(pr.get('wear') or [])} 件装扮 · {len(pr.get('dye') or {})} 处染色")
                abtn.setEnabled(True)
                rbtn.setVisible(True)
                cbtn.setVisible(True)
            else:
                tlab.setText(f"方案 {sk}")
                slab.setText("空槽位 — 点击「保存当前」记录当前整套搭配")
                abtn.setEnabled(False)
                rbtn.setVisible(False)
                cbtn.setVisible(False)
        full = g.full_outfit()
        for oid, (btn, parts_lab, box) in self.outfit_rows.items():
            o = next(x for x in OUTFITS if x[0] == oid)
            has_any = any(g.is_unlocked(aid) for aid in o[2])
            box.setVisible(has_any or not getattr(self, "_only_unlocked", False))
            bits = []
            for aid in o[2]:
                a = ACC_BY_ID[aid]
                mark = "✓" if aid in g.wear else ("○" if g.is_unlocked(aid) else "🔒")
                tag = "扭蛋" if a[2] >= 999 else f"Lv.{a[2]}"
                bits.append(f"{mark}{a[1]}" + ("" if g.is_unlocked(aid) else f"({tag})"))
            parts_lab.setText("  ".join(bits) + ("\n✨ 已集齐" if full is not None and full[0] == oid else ""))
            btn.setEnabled(has_any)
        for tid, b in self.trick_btns.items():
            if tid in {t[1] for t in TRICKS}:
                need, _t, name, _d = next(x for x in TRICKS if x[1] == tid)
                ok = g.level >= need
                b.setEnabled(ok)
                b.setText(f"🎭 {name}" if ok else f"🔒 {name} Lv.{need}")
            else:
                _tid, name, _d = next(x for x in SPECIAL_TRICKS if x[0] == tid)
                ok = g.has_trick(tid)
                b.setEnabled(ok)
                b.setText(f"✨ {name}" if ok else f"🔒 {name}(通行证)")
        cur_slot = getattr(self, "_dye_slot", "head")
        cur_dye = g.dye.get(cur_slot, "")
        for sk, sname in SLOTS:
            sb = getattr(self, "dye_slot_btns", {}).get(sk)
            if sb is not None:
                worn = self._worn_in_slot(sk) is not None
                sb.setText(f"{sname}✓" if worn else sname)
                sb.setChecked(sk == cur_slot)
        if getattr(self, "dye_target_lab", None) is not None:
            sn = dict(SLOTS).get(cur_slot, cur_slot)
            wid = self._worn_in_slot(cur_slot)
            if wid is not None:
                self.dye_target_lab.setText(f"🎨 正在染色：【{sn}】{ACC_BY_ID[wid][1]}（点击下方色块即时变色）")
            else:
                self.dye_target_lab.setText(f"⚠️ 当前【{sn}】未穿戴装扮，请切到上方带 ✓ 的部位或先穿一件「{sn}」")
        for hex_c, b in getattr(self, "dye_color_btns", {}).items():
            b.setChecked(hex_c == cur_dye)
        for eid, b in self.expr_btns.items():
            ok = g.can_use("expr", eid)
            name, lv = next((e[1], e[2]) for e in EXPRESSIONS if e[0] == eid)
            b.setEnabled(ok)
            b.setChecked(g.expr == eid)
            b.setText(name if ok else f"🔒 {name}  Lv.{lv}")
        for cid, b in self.coat_btns.items():
            ok = g.can_use("coat", cid)
            name, lv = next((c[1], c[2]) for c in COATS if c[0] == cid)
            b.setEnabled(ok)
            b.setChecked(g.coat == cid)
            b.setText(name if ok else f"🔒 {name}  Lv.{lv}")
        for eid, b in self.eye_btns.items():
            ok = g.can_use("eyes", eid)
            name, lv = next((e[1], e[2]) for e in EYE_STYLES if e[0] == eid)
            b.setEnabled(ok)
            b.setChecked(g.eyes == eid)
            b.setText(name if ok else f"🔒 {name}  Lv.{lv}")
        for rid, b in self.room_btns.items():
            ok = g.can_use("room", rid)
            name, lv = next((r[1], r[2]) for r in ROOMS if r[0] == rid)
            b.setEnabled(ok)
            b.setChecked(g.room == rid)
            b.setText(name if ok else f"🔒 {name}  Lv.{lv}")
        self.preview.update()
        self.win.pet.update()
        if self.win.desktop_win is not None:
            self.win.desktop_win.update()


class FocusPomodoroDialog(Dialog):
    """3.7 专注番茄钟与喝水/久坐提醒窗口(联动萌宠眼镜与灵动岛实时倒计时)。"""

    def __init__(self, win) -> None:
        super().__init__(win, "专注番茄钟与喝水提醒")
        self.win = win
        self.setFixedWidth(430)
        self.focus_mins = 25
        self.water_mins = 45
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("🍅 专注番茄钟 & 喝水久坐提醒", "dialogTitle"))
        lay.addWidget(label("专注时萌宠会自动戴上圆框学习镜安静陪伴，顶栏灵动岛同步跳动倒计时；完成可获 +40 宠物经验与 +18 心情！",
                            "hint", wrap=True))

        active = getattr(win, "_focus_end", 0.0) > time.monotonic()
        if active:
            left = max(0, int(win._focus_end - time.monotonic()))
            mm, ss = divmod(left, 60)
            st_card = QFrame(self)
            st_card.setObjectName("plainCard")
            sl = QHBoxLayout(st_card)
            sl.setContentsMargins(12, 8, 12, 8)
            sl.addWidget(label(f"🔥 正在专注「{getattr(win, '_focus_label', '专注')}」· 剩余 {mm:02d}:{ss:02d}", "cardTitle"), 1)
            sl.addWidget(button("提前结束", "destructive", self._stop_now, 88))
            lay.addWidget(st_card)

        lay.addWidget(label("专注时长：", "section"))
        frow = QHBoxLayout()
        frow.setSpacing(6)
        self._fbtns: list[tuple[int, QPushButton]] = []
        for m, txt in ((15, "15 分钟轻专注"), (25, "25 分钟番茄"), (45, "45 分钟深度")):
            b = QPushButton(txt, self)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setChecked(m == 25)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=m: self._pick_f(v))
            frow.addWidget(b)
            self._fbtns.append((m, b))
        lay.addLayout(frow)

        self.goal_edit = QLineEdit(self)
        self.goal_edit.setPlaceholderText("专注目标，例如：写周报 / 写代码 / 看书")
        self.goal_edit.setText(getattr(win, "_focus_label", "") or "番茄专注")
        self.goal_edit.setMaxLength(16)
        lay.addWidget(self.goal_edit)

        lay.addWidget(label("循环喝水 / 久坐起身提醒：", "section"))
        wrow = QHBoxLayout()
        wrow.setSpacing(6)
        self._wbtns: list[tuple[int, QPushButton]] = []
        cur_w = getattr(win, "_water_mins", 0)
        self.water_mins = cur_w
        for m, txt in ((0, "关闭"), (30, "每 30 分钟"), (45, "每 45 分钟"), (60, "每 60 分钟")):
            b = QPushButton(txt, self)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setChecked(m == cur_w)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=m: self._pick_w(v))
            wrow.addWidget(b)
            self._wbtns.append((m, b))
        lay.addLayout(wrow)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 76))
        row.addWidget(button("仅保存喝水提醒", "", self._save_water_only, 128))
        row.addWidget(button("🍅 开始专注", "primary", self._start_now, 108))
        lay.addLayout(row)

    def _pick_f(self, m: int) -> None:
        self.focus_mins = m
        for v, b in self._fbtns:
            b.setChecked(v == m)

    def _pick_w(self, m: int) -> None:
        self.water_mins = m
        for v, b in self._wbtns:
            b.setChecked(v == m)

    def _stop_now(self) -> None:
        self.win.stop_focus(completed=False)
        self.accept()

    def _save_water_only(self) -> None:
        self.win.set_water_reminder(self.water_mins)
        self.accept()

    def _start_now(self) -> None:
        self.win.set_water_reminder(self.water_mins)
        self.win.start_focus(self.focus_mins, self.goal_edit.text().strip() or "番茄专注")
        self.accept()


class PetCustomDialog(Dialog):
    """3.2 宠物自定义台词与下班倒计时设置窗口。"""

    def __init__(self, win) -> None:
        super().__init__(win, "宠物台词与下班倒计时")
        self.g: PetGrowth = win.pet_growth
        self.setFixedWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(8)
        lay.addWidget(label(f"💬 {self.g.name} 的专属台词 & 下班倒计时", "dialogTitle"))
        lay.addWidget(label("下班时间（24 小时制，例如 18:00，留空关闭）：", "hint"))
        self.ow_edit = QLineEdit(self)
        self.ow_edit.setPlaceholderText("18:00")
        self.ow_edit.setText(self.g.off_work)
        self.ow_edit.setMaxLength(5)
        lay.addWidget(self.ow_edit)
        lay.addWidget(label("专属口头禅（每行一句，最多 10 句，摸摸或闲聊时随机冒出）：", "hint"))
        self.lines_edit = QPlainTextEdit(self)
        self.lines_edit.setPlaceholderText("老板来啦注意屏幕 👀\n喝口水休息一下吧 ☕\n今天也是元气满满的一天!")
        self.lines_edit.setPlainText("\n".join(self.g.custom_lines))
        self.lines_edit.setFixedHeight(140)
        lay.addWidget(self.lines_edit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 80))
        row.addWidget(button("保存", "primary", self._save, 86))
        lay.addLayout(row)

    def _save(self) -> None:
        import re as _re
        ow = self.ow_edit.text().strip()
        if ow and not _re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", ow):
            info(self, "时间格式不正确", "请填写 24 小时制时间，例如 18:00 或 17:30（留空则关闭）。")
            return
        self.g.off_work = ow
        self.g.custom_lines = [ln.strip()[:40] for ln in self.lines_edit.toPlainText().splitlines() if ln.strip()][:10]
        self.accept()


class PetLifeMixin:
    """宠物照料、衣橱、跟随聊天的动作、群宠物、桌面陪伴、等级标识。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_petlife(self) -> None:
        self.gpets: dict[str, GroupPet] = {}
        self._gpet_sent: dict[str, float] = {}
        self._say_t = 0.0
        self._care_said = time.monotonic()
        self._last_lv = 0
        self.desktop_pet_on = False
        self.desktop_mode = "roam"                   # roam(任务栏漫步) / peek(趴在活动窗口顶边) / fixed(固定)
        self.desktop_global_keys = True              # 最小化桌面陪伴时响应全局打字节拍(不记录字符)
        self.desktop_pos: list[int] | None = None
        self.desktop_win: DesktopPet | None = None
        self.pet_hit.on_menu = self.pet_menu
        self.gpet = TypingPet(self.chat_panel)
        self.gpet.mirror = True
        self.gpet.visitor = True
        self.gpet.show_combo = False
        self.gpet.hide()
        self.gpet_hit = PetHit(self.chat_panel, self.pat_gpet, self.gpet_menu,
                               "群宠物:左键摸摸 · 按住捏脸 · 右键喂它、改名、贡献榜", pet_getter=lambda: self.gpet)
        self.gpet_hit.hide()
        self.pet_growth.care()
        self._sync_level()

    def _restore_petlife(self, acct: dict, st: dict) -> None:
        self.desktop_pet_on = bool(st.get("desktop_pet", False))
        dm = st.get("desktop_mode")
        if dm in ("roam", "peek", "fixed"):
            self.desktop_mode = dm
        if "desktop_global_keys" in st:
            self.desktop_global_keys = bool(st.get("desktop_global_keys", True))
        self.desktop_locked = bool(st.get("desktop_locked", False))
        self._offwork_fired: set[str] = set()
        pos = st.get("desktop_pos")
        if isinstance(pos, list) and len(pos) == 2 and all(type(v) is int for v in pos):
            self.desktop_pos = pos
        gp = acct.get("gpets")
        if isinstance(gp, dict):
            for tag, d in list(gp.items())[:50]:
                if isinstance(tag, str) and isinstance(d, dict):
                    self.gpets[tag] = GroupPet(d)
        self._sync_level()

    def _save_petlife(self) -> dict:
        return {"gpets": {tag: gp.to_dict() for tag, gp in self.gpets.items() if tag in self.room_keys}}

    def _settings_petlife(self) -> dict:
        return {"desktop_pet": self.desktop_pet_on, "desktop_pos": self.desktop_pos,
                "desktop_mode": self.desktop_mode, "desktop_global_keys": self.desktop_global_keys,
                "desktop_locked": bool(getattr(self, "desktop_locked", False))}

    def _tick_petlife(self, now: float) -> None:
        if self._save_tick % 5 == 0:
            self._sync_level()
        if self._save_tick % 30 == 0:
            self._check_off_work()
        if self._save_tick % 60 == 0:
            self._care_tick(now)
        for tag, gp in self.gpets.items():
            if gp.dirty and now - self._gpet_sent.get(tag, -1e9) >= GPET_RESEND:
                self.send_gpet(tag)
        self.desktop_pet_sync()

    def _check_off_work(self) -> None:
        """3.2 下班倒计时自动冒泡播报(15 分钟 / 5 分钟 / 到点撒花)。"""
        ow = getattr(self.pet_growth, "off_work", "")
        if not ow:
            return
        try:
            hh, mm = (int(x) for x in ow.split(":"))
        except Exception:
            return
        lt = time.localtime()
        now_m = lt.tm_hour * 60 + lt.tm_min
        left = hh * 60 + mm - now_m
        day = time.strftime("%Y-%m-%d", lt)
        fired = getattr(self, "_offwork_fired", None)
        if fired is None:
            fired = self._offwork_fired = set()
        for mark, msg in ((15, "⏰ 还有 15 分钟就下班啦，坚持一下~"), (5, "🎉 还有 5 分钟下班！收拾准备冲！"),
                          (0, "🎊 下班时间到啦！快去享受自由时光吧~")):
            key = f"{day}:{mark}"
            if left == mark and key not in fired:
                fired.add(key)
                self.pet.say(msg, 5.0)
                if mark == 0:
                    self.pet.celebrate()
                    if self.fun.get("effects"):
                        self.effects.play("confetti")
                if self.desktop_win is not None and self.desktop_win.isVisible():
                    self.desktop_win.pet.say(msg, 5.0)
                    if mark == 0:
                        self.desktop_win.pet.celebrate()

    def show_pet_custom(self) -> None:
        if PetCustomDialog(self).exec():
            if self.pet_growth.custom_lines:
                self.pet.say(random.choice(self.pet_growth.custom_lines), 3.0)
            elif self.pet_growth.off_work:
                self.pet.say(f"记好啦！{self.pet_growth.off_work} 准时提醒你下班~", 3.0)

    def _place_petlife(self) -> None:
        self._place_gpet()

    def _switch_petlife(self, conv: Conv) -> None:
        self.refresh_gpet()

    def _winstate_petlife(self) -> None:
        self.desktop_pet_sync()

    def _peer_online_petlife(self, pid: str) -> None:
        """有群友上线:把群宠物的状态发一份(合并后大家一致)。"""
        rooms = self.peers.get(pid, {}).get("rooms", [])
        for tag in rooms:
            if tag in self.gpets:
                self.gpets[tag].dirty = True

    def _message_petlife(self, conv: Conv, m) -> None:
        g = self.pet_growth
        if m.mine:
            g.cheer(0.5)
            if conv.kind == "room" and self.fun.get("gpet", True):
                gp = self.gpet_for(conv.target)
                before = gp.level
                if gp.contribute(self.me["id"], self.me.get("nick", ""), GP_MSG_XP) and gp.level > before:
                    self._gpet_level_up(conv, gp)
            return
        self.pet_notice(conv, m)

    # ---------------------------------------------------------------- 等级标识
    def _sync_level(self) -> None:
        lv = self.pet_growth.level
        self.core.level = lv if self.fun.get("lv_badge", True) else 0
        if lv != self._last_lv:
            self._last_lv = lv
            self._refresh_self()

    def set_level_badge(self, on: bool) -> None:
        self.set_fun("lv_badge", bool(on))
        self._sync_level()

    # ---------------------------------------------------------------- 跟随聊天
    def pet_notice(self, conv: Conv, m) -> None:
        """收到消息时宠物提醒:别的会话来消息冒"!"招手;被 @ 了跳起来喊。正在看的会话只抖耳朵(原来就有)。"""
        if conv.kind == "self" or m.system:
            return
        now = time.monotonic()
        if not self.window_visible():
            if self.desktop_win is not None and self.desktop_win.isVisible() and not conv.muted:
                if now - self._say_t >= SAY_CD:
                    self._say_t = now
                    self.desktop_win.notify_msg()
                else:
                    self.desktop_win.pet.alert()
            return
        if not self.fun.get("pet") or self.pet_away:
            return
        is_current = conv.key == self.current_key
        covered = getattr(self, "cover", None) is not None and self.cover.isVisible()
        if m.mention:
            self.pet.alert()
            if now - self._say_t >= SAY_CD / 2:
                self._say_t = now
                self.pet.say("有人@你啦!" if covered else f"{m.nick[:6]} @了你!", 3)
        elif not is_current and not conv.muted:
            self.pet.alert()
            if now - self._say_t >= SAY_CD and not covered:
                self._say_t = now
                where = f"{m.nick[:6]}发来消息~" if conv.kind == "dm" else f"「{conv.title[:6]}」有新消息"
                self.pet.say(where, 2.8)

    # ---------------------------------------------------------------- 照料:喂食 / 玩耍
    def _care_tick(self, now: float) -> None:
        g = self.pet_growth
        g.care()
        if (not self.fun.get("pet") or self.pet_away or not self.window_visible()
                or now - self._care_said < 1800):
            return
        if g.food < 25:
            self._care_said = now
            self.pet.say(random.choice(("肚子饿了…右键喂我点吃的吧 🐟", "咕噜咕噜…好饿", "想吃小鱼干~")), 4)
        elif g.joy < 25:
            self._care_said = now
            self.pet.say(random.choice(("好无聊…陪我玩一会儿嘛", "右键点我,一起玩吧 🧶")), 4)

    def pet_menu(self, pos) -> None:
        g = self.pet_growth
        g.care()
        m = make_menu(self)
        head = m.addAction(f"{g.name}  ·  Lv.{g.level}  ·  {g.form[1]}  ·  {g.mood_word()}")
        head.setEnabled(False)
        st = m.addAction(f"饱腹 {int(g.food)} / 100   心情 {int(g.joy)} / 100")
        st.setEnabled(False)
        m.addSeparator()
        m.addAction("🤚  摸摸头", self.pat_pet)
        feed = make_menu(m)
        feed.setTitle("🍽  喂食")
        for fid, name, emo, food, joy, lv in FOODS:
            if g.can_use("food", fid):
                feed.addAction(f"{emo}  {name}   饱腹 +{food}", lambda f=fid: self.feed_pet(f))
            else:
                feed.addAction(f"🔒 {name}  ·  Lv.{lv} 解锁").setEnabled(False)
        m.addMenu(feed)
        play = make_menu(m)
        play.setTitle("🎾  玩耍")
        for tid, name, emo, joy, lv in TOYS:
            if g.can_use("toy", tid):
                play.addAction(f"{emo}  {name}   心情 +{joy}", lambda t=tid: self.play_pet(t))
            else:
                play.addAction(f"🔒 {name}  ·  Lv.{lv} 解锁").setEnabled(False)
        m.addMenu(play)
        show = make_menu(m)
        show.setTitle("🎭  表演一个")
        for need, tid, name, _dur in TRICKS:
            if g.level >= need:
                show.addAction(name, lambda t=tid: self.pet.trick(t))
            else:
                show.addAction(f"🔒 {name}  ·  Lv.{need} 学会").setEnabled(False)
        show.addSeparator()
        for tid, name, _dur in SPECIAL_TRICKS:
            if g.has_trick(tid):
                show.addAction(f"✨ {name}", lambda t=tid: self.pet.trick(t))
            else:
                show.addAction(f"🔒 {name}  ·  签到/通行证解锁").setEnabled(False)
        m.addMenu(show)
        m.addSeparator()
        from ..petpass import can_checkin
        ci_tag = "  🔴 可签到" if can_checkin(g) else ""
        m.addAction("🎮  萌宠游乐厅（双塔防/全部 5 款）…", self.show_arcade_hub)
        m.addAction("🥕  萌宠保卫战（保卫萝卜风塔防）…", self.show_td_game)
        m.addAction("🌻  萌宠大战捣蛋怪（植物大战僵尸风）…", self.show_pvz_game)
        m.addAction(f"🎁  每日签到与萌宠通行证…{ci_tag}", self.show_pet_pass)
        m.addAction("🍉  合成大萌宠（含道具/连击）…", self.show_merge_game)
        m.addAction("🐟  接零食大作战（黄金雨版）…", self.show_snack_game)
        m.addAction("☁️  云端跳跳乐（喷气背包/变天）…", self.show_cloud_game)
        m.addAction("🍅  专注番茄钟与喝水提醒…", self.show_focus_dialog)
        m.addAction("📸  萌宠双人合拍大头贴…", self.show_photobooth)
        m.addAction("👗  2.5D 潮玩展柜衣橱与穿搭方案…", self.show_wardrobe)
        from ..fun import BUBBLE_AURAS
        am = make_menu(m)
        am.setTitle("✨  气泡边缘特效(12 款)")
        a0 = am.addAction("关闭边缘特效", lambda: g.set_aura(""))
        a0.setCheckable(True)
        a0.setChecked(not g.aura)
        for aid, aname, lv, _col in BUBBLE_AURAS:
            if g.has_aura(aid):
                act = am.addAction(aname, lambda _=False, i=aid: g.set_aura(i))
                act.setCheckable(True)
                act.setChecked(g.aura == aid)
            else:
                tag = "扭蛋限定" if lv >= 999 else f"Lv.{lv} 或抽卡"
                am.addAction(f"🔒 {aname}  ·  {tag}").setEnabled(False)
        m.addMenu(am)
        m.addAction("💬  自定义台词与下班倒计时…", self.show_pet_custom)
        m.addAction("📔  宠物日记", self.show_diary)
        act = m.addAction("🖥  桌面陪伴(最小化时在桌面漫步陪你打字)")
        act.setCheckable(True)
        act.setChecked(self.desktop_pet_on)
        act.triggered.connect(self.set_desktop_pet)
        popup(m, pos)

    def feed_pet(self, fid: str) -> bool:
        if self.pet_away:
            info(self, f"{self.pet_growth.name} 出门了", "等它回来再喂吧。")
            return False
        food = FOOD_BY_ID.get(fid)
        up = self.pet_growth.feed(fid)
        if food is None or up < 0:
            return False
        self.pet.act("eat", food[2], 2.2)
        QTimer.singleShot(2300, lambda: self.pet.say(random.choice(THANKS), 2.2))
        if up > 0:
            self._pet_level_up()
        self._show_achievements()
        return True

    def play_pet(self, tid: str) -> bool:
        if self.pet_away:
            info(self, f"{self.pet_growth.name} 出门了", "等它回来再一起玩吧。")
            return False
        toy = TOY_BY_ID.get(tid)
        up = self.pet_growth.play(tid)
        if toy is None or up < 0:
            return False
        self.pet.act("play", toy[2], 2.6)
        QTimer.singleShot(2700, lambda: self.pet.say(random.choice(PLAY_SAY), 2))
        if up > 0:
            self._pet_level_up()
        self._show_achievements()
        return True

    def show_wardrobe(self) -> None:
        WardrobeDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.pet.update()
        self.save_account()

    # ---------------------------------------------------------------- 群宠物
    def gpet_for(self, tag: str) -> GroupPet:
        gp = self.gpets.get(tag)
        if gp is None:
            gp = self.gpets[tag] = GroupPet()
        return gp

    def refresh_gpet(self) -> None:
        conv = self.current
        show = (conv is not None and conv.kind == "room" and bool(self.fun.get("gpet", True))
                and bool(self.fun.get("pet")) and self.input.isEnabled())
        if not show:
            self.gpet.hide()
            self.gpet_hit.hide()
            return
        gp = self.gpet_for(conv.target)
        g = PetGrowth({"xp": gp.total})
        g.owned = {f"acc:{w}" for w in gp.wear[0] if w in ACC_BY_ID}
        g.wear = [w for w in gp.wear[0] if w in ACC_BY_ID]
        self.gpet.growth = g
        self.gpet.set_species(gp.species[0])
        wide = self._pill.width() >= 560
        self.gpet.label = f"群宠 {gp.name[0]} Lv.{gp.level}" if wide else ""
        self.gpet.bare = not wide
        self.gpet.show()
        self._place_gpet()
        self.gpet.update()

    def _place_gpet(self) -> None:
        if not self.gpet.isVisible():
            self.gpet_hit.hide()
            return
        tl = self._pill.mapTo(self.chat_panel, QPoint(0, 0))
        self.gpet.move(tl.x() + 4, tl.y() - self.gpet.EDGE + 1)
        self.gpet.raise_()
        cx = self.gpet.x() + self.gpet._cx()
        self.gpet_hit.setGeometry(int(cx - 32), self.gpet.y() + self.gpet.EDGE - 46, 64, 46)
        self.gpet_hit.show()
        self.gpet_hit.raise_()

    def pat_gpet(self) -> None:
        self.gpet.pat()

    def gpet_menu(self, pos) -> None:
        conv = self.current
        if conv is None or conv.kind != "room":
            return
        gp = self.gpet_for(conv.target)
        m = make_menu(self)
        head = m.addAction(f"群宠物 {gp.name[0]}  ·  Lv.{gp.level}  ·  {form_of(gp.level)[1]}")
        head.setEnabled(False)
        sub = m.addAction(f"大家一共攒了 {gp.total:,} 经验  ·  今天你还能喂 {gp.feeds_left()} 次")
        sub.setEnabled(False)
        m.addSeparator()
        feed = make_menu(m)
        feed.setTitle("🍽  喂它")
        for fid, name, emo, *_rest in FOODS:
            a = feed.addAction(f"{emo}  {name}", lambda f=fid: self.feed_gpet(f))
            a.setEnabled(gp.feeds_left() > 0)
        m.addMenu(feed)
        m.addAction("✏️  改名…", lambda: self.rename_gpet(conv))
        sp = make_menu(m)
        sp.setTitle("换个样子")
        for key in GP_SPECIES:
            a = sp.addAction(SPECIES[key]["label"], lambda k=key: self.set_gpet_species(conv, k))
            a.setCheckable(True)
            a.setChecked(gp.species[0] == key)
        m.addMenu(sp)
        m.addAction("🏅  贡献榜…", lambda: self.show_gpet_rank(conv))
        m.addSeparator()
        m.addAction("不显示群宠物", lambda: (self.set_fun("gpet", False), self.refresh_gpet()))
        popup(m, pos)

    def feed_gpet(self, fid: str, conv: Conv | None = None) -> bool:
        conv = conv or self.current
        if conv is None or conv.kind != "room" or fid not in FOOD_BY_ID:
            return False
        gp = self.gpet_for(conv.target)
        before = gp.level
        if not gp.feed(self.me["id"], self.me.get("nick", ""), fid):
            info(self, "今天喂饱啦", f"每人每天最多喂 {GP_DAILY_FEEDS} 次,明天再来。")
            return False
        if conv.key == self.current_key:
            self.gpet.act("eat", FOOD_BY_ID[fid][2], 2.2)
            QTimer.singleShot(2300, lambda: self.gpet.say(random.choice(THANKS), 2))
        self.send_gpet(conv.target)
        if gp.level > before:
            self._gpet_level_up(conv, gp)
        self.refresh_gpet()
        return True

    def rename_gpet(self, conv: Conv) -> None:
        gp = self.gpet_for(conv.target)
        text = prompt(self, "给群宠物起名字", "最多 8 个字,群里所有人都会看到。", gp.name[0], max_len=8, ok="好")
        if text is not None and gp.rename(text, self.me.get("nick", "")):
            self._system(conv, f"你把群宠物改名为「{gp.name[0]}」")
            self.send_gpet(conv.target)
            self.refresh_gpet()

    def set_gpet_species(self, conv: Conv, sp: str) -> None:
        gp = self.gpet_for(conv.target)
        if gp.set_species(sp, self.me.get("nick", "")):
            self.send_gpet(conv.target)
            self.refresh_gpet()

    def show_gpet_rank(self, conv: Conv) -> None:
        gp = self.gpet_for(conv.target)
        rows = [(f"{i + 1}. {nick}", f"经验 {xp:,}  ·  喂过 {feeds} 次") for i, (nick, xp, feeds) in enumerate(gp.top(10))]
        if not rows:
            rows = [("", "还没有人照顾过它。在群里聊天、喂它,都会给它攒经验。")]
        TextDialog(self, f"群宠物 {gp.name[0]} 的贡献榜", rows,
                   f"在群里每发一条消息 +{GP_MSG_XP}(每天最多 300),喂一次 +20(每天 {GP_DAILY_FEEDS} 次)。", width=440).exec()

    def send_gpet(self, tag: str) -> bool:
        gp = self.gpets.get(tag)
        if gp is None or tag not in self.core.rooms:
            return False
        self._gpet_sent[tag] = time.monotonic()
        gp.dirty = False
        return bool(self.core.send_event("room", tag, "gpet", gp.to_wire()))

    def _ev_gpet(self, conv: Conv, d: dict, data: dict) -> None:
        if conv.kind != "room" or not isinstance(data, dict):
            return
        gp = self.gpet_for(conv.target)
        before_lv, before_act, before_name = gp.level, gp.act.get("t", 0), gp.name
        gp.merge(data)
        theirs = data.get("x") if isinstance(data.get("x"), dict) else {}
        if any(v > (theirs.get(pid) if type(theirs.get(pid)) is int else 0) for pid, v in gp.xp.items()):
            gp.dirty = True                              # 对方落后了:过一会儿把完整的发回去
        here = conv.key == self.current_key and self.window_visible()
        if gp.act.get("t", 0) > before_act and gp.act.get("by") and here:
            food = FOOD_BY_ID.get(gp.act.get("food", ""))
            self.gpet.act("eat", food[2] if food else "🍙", 2.2)
            who = gp.act["by"][:6]
            QTimer.singleShot(2300, lambda: self.gpet.say(f"谢谢{who}的{food[1] if food else '好吃的'}!", 2.5))
        if gp.name[0] != before_name[0] and gp.name[2]:
            self._system(conv, f"{gp.name[2]} 把群宠物改名为「{gp.name[0]}」")
        if gp.level > before_lv:
            self._gpet_level_up(conv, gp)
        if conv.key == self.current_key:
            self.refresh_gpet()

    def _gpet_level_up(self, conv: Conv, gp: GroupPet) -> None:
        lv = gp.level
        g = self.pet_growth
        if lv > g.counts["gpet"]:
            g.counts["gpet"] = lv
            g.check_badges()
            self._show_achievements()
        if conv.key == self.current_key:
            self.gpet.level_up(lv)
        idx, fname, _d = form_of(lv)
        extra = f",进入「{fname}」!" if FORMS[idx][0] == lv and lv > 1 else ""
        self._system(conv, f"🎉 群宠物 {gp.name[0]} 升到 Lv.{lv} 了{extra}")

    # ---------------------------------------------------------------- 桌面陪伴 / 签到与小游戏(按需懒加载)
    def show_pet_pass(self) -> None:
        from ..petpass import PassDialog
        PassDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.update()

    def show_snack_game(self) -> None:
        from ..petpass import SnackCatchDialog
        SnackCatchDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.update()

    def show_cloud_game(self) -> None:
        from ..petpass import CloudJumpDialog
        CloudJumpDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.update()

    def show_arcade_hub(self) -> None:
        from ..arcade import ArcadeHubDialog
        ArcadeHubDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.update()

    def show_td_game(self) -> None:
        from ..pettd import PetTDDialog
        PetTDDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.update()

    def show_pvz_game(self) -> None:
        from ..petpvz import PetPvZDialog
        PetPvZDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.update()

    def show_merge_game(self) -> None:
        from ..petmerge import MergePetDialog
        MergePetDialog(self).exec()
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.update()

    def show_photobooth(self, peer_id: str | None = None) -> None:
        from ..petphoto import PhotoBoothDialog
        PhotoBoothDialog(self, initial_peer_id=peer_id).exec()

    def show_focus_dialog(self) -> None:
        FocusPomodoroDialog(self).exec()

    def start_focus(self, minutes: int = 25, goal: str = "番茄专注") -> None:
        minutes = max(1, min(120, int(minutes)))
        self._focus_label = (goal or "番茄专注")[:16]
        self._focus_end = time.monotonic() + minutes * 60
        self.pet._focus_mode = True
        self.pet.say(f"🍅 进入 {minutes} 分钟专注，我戴上眼镜陪你~", 3.2)
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.pet._focus_mode = True
            self.desktop_win.pet.update()
        if getattr(self, "island", None) is not None:
            self.island.set_focus(self._focus_label, self._focus_end)
        old = getattr(self, "_focus_timer", None)
        if old is not None:
            old.stop()
            old.deleteLater()
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda: self.stop_focus(completed=True))
        t.start(minutes * 60 * 1000)
        self._focus_timer = t

    def stop_focus(self, completed: bool = False) -> None:
        old = getattr(self, "_focus_timer", None)
        if old is not None:
            old.stop()
            old.deleteLater()
            self._focus_timer = None
        self._focus_end = 0.0
        self.pet._focus_mode = False
        self.pet.update()
        if self.desktop_win is not None:
            self.desktop_win.pet._focus_mode = False
            self.desktop_win.pet.update()
        if getattr(self, "island", None) is not None:
            self.island.clear_focus()
        if completed:
            g = self.pet_growth
            before = g.level
            g.xp += 40
            g.cheer(18)
            self.pet.celebrate()
            self.pet.say("🔔 专注完成! +40 经验，起来喝口水活动一下吧 💧", 5.0)
            if g.level > before and hasattr(self, "_pet_level_up"):
                self._pet_level_up()
            if getattr(self, "notifier", None) is not None:
                self.notifier.play(force=True)
            if self.isVisible() and not self.isMinimized():
                info(self, "🍅 专注完成！", f"太棒啦！完成了「{getattr(self, '_focus_label', '番茄专注')}」\n已奖励宠物 +40 经验、+18 心情，快起身喝口水休息 5 分钟吧 💧")
        else:
            self.pet.say("番茄钟已暂停，休息一下吧~", 2.2)

    def set_water_reminder(self, minutes: int) -> None:
        self._water_mins = max(0, int(minutes))
        old = getattr(self, "_water_timer", None)
        if old is not None:
            old.stop()
            old.deleteLater()
            self._water_timer = None
        if self._water_mins <= 0:
            return
        t = QTimer(self)
        t.setInterval(self._water_mins * 60 * 1000)
        def _ping() -> None:
            if not self.isVisible() or self.isMinimized():
                return
            self.pet.alert()
            self.pet.say("💧 喝口水、伸个懒腰活动一下肩颈吧~", 5.5)
        t.timeout.connect(_ping)
        t.start()
        self._water_timer = t
        self.pet.say(f"💧 记好啦！每 {self._water_mins} 分钟提醒你喝水伸懒腰~", 2.6)

    def set_desktop_locked(self, on: bool) -> None:
        self.desktop_locked = bool(on)
        if self.desktop_win is not None and self.desktop_win.isVisible():
            self.desktop_win.pet.say("位置已锁定 🔒" if self.desktop_locked else "已解锁，可以自由拖动啦~", 2.0)

    def set_desktop_mode(self, mode: str) -> None:
        if mode in ("roam", "peek", "fixed"):
            self.desktop_mode = mode
            if self.desktop_win is not None and self.desktop_win.isVisible():
                self.desktop_win.pet.say({"roam": "我去任务栏散步啦~", "peek": "趴在窗口边偷看你!", "fixed": "我乖乖待在这里~"}[mode], 2.2)

    def set_desktop_global_keys(self, on: bool) -> None:
        self.desktop_global_keys = bool(on)
        if self.desktop_win is not None:
            self.desktop_win.sync_timers()

    def on_desktop_keybeat(self, kind: str, is_repeat: bool = False) -> None:
        """桌面陪伴期间收到全局打字节拍:增加宠物经验与敲击数。"""
        if self.pet_growth.tap(is_repeat=is_repeat):
            self._pet_level_up()
            if self.desktop_win is not None:
                self.desktop_win.pet.celebrate()
                self.desktop_win.pet.say(f"升到 Lv.{self.pet_growth.level} 啦! 🎉", 3.0)

    def set_desktop_pet(self, on: bool) -> None:
        self.desktop_pet_on = bool(on)
        if on and not self.isMinimized():
            self.pet.say("最小化窗口时,我会在任务栏散步并陪你打字~", 3.5)
        self.desktop_pet_sync()

    def desktop_pet_sync(self) -> None:
        """只在「窗口最小化」时显示;老板键藏起来、锁屏、关掉宠物时都不显示。"""
        locked = getattr(self, "lock_overlay", None) is not None and self.lock_overlay.isVisible()
        want = (self.desktop_pet_on and bool(self.fun.get("pet")) and self.isVisible() and self.isMinimized()
                and not locked)
        if not want:
            if self.desktop_win is not None and self.desktop_win.isVisible():
                self.desktop_win.hide()
            return
        if self.desktop_win is None:
            self.desktop_win = DesktopPet(self)
        w = self.desktop_win
        w.pet.set_species(self.fun.get("pet") or "cat")
        w.pet.growth = self.pet_growth
        if not w.isVisible():
            x, y = self._desktop_place()
            w.move(x, y)
            w.show()
            w.pet.say(random.choice(("我在这儿陪你~", "有消息我会叫你哦")), 2.5)

    def _desktop_place(self) -> tuple[int, int]:
        try:
            geo = QGuiApplication.primaryScreen().availableGeometry()
            gx, gy, gw, gh = geo.x(), geo.y(), geo.width(), geo.height()
        except Exception:                                 # noqa: BLE001
            gx, gy, gw, gh = 0, 0, 1280, 720
        if self.desktop_pos:
            x, y = self.desktop_pos
            if gx - 100 <= x <= gx + gw - 60 and gy - 20 <= y <= gy + gh - 40:
                return x, y
        return gx + gw - TypingPet.W - 16, gy + gh - TypingPet.H - 18

    def restore_from_desktop(self) -> None:
        if self.desktop_win is not None:
            self.desktop_win.hide()
        self.show_window()
