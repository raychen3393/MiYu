"""
密语 · 个性化外观:主题(紫 / 蓝 / 黑 / 樱花…)、主题色、我的气泡颜色、面板透明度、自定义聊天背景图。
"""
from __future__ import annotations

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from .. import imaging, motion, storage, theme
from ..dialogs import Dialog, info
from ..theme import T
from ..ui import button, label

BG_MAX_SIDE = 2560                # 背景图最长边(存之前缩小,省空间)


def swatch_pixmap(color: str, size: int = 16, ring: str | None = None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if ring is None:                                   # 很深的颜色(纯黑主题)在深色菜单上加一圈浅色边
        ring = "#FFFFFF80" if theme.valid_hex(color) and theme.luminance(color) < 0.03 else "#00000030"
    p.setPen(QColor(ring))
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return pm


class PersonalizeDialog(Dialog):
    """个性化窗口。改动立刻生效(能直接看到效果),按「取消」恢复原样。"""

    def __init__(self, win) -> None:
        super().__init__(win, "个性化外观")
        self.win = win
        self.setFixedWidth(560)
        self._snapshot = (dict(theme.CUSTOM), T["name"], win.follow_system, win.follow_time)
        # 拖滑块时先只记下数值,停下来(或松手)再统一应用:每次应用都要重新套整个软件的样式,一格一套会很卡
        self._pending: dict = {}
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self.flush)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(8)
        lay.addWidget(label("个性化外观", "dialogTitle"))
        lay.addWidget(label("改动马上生效。主题色和气泡颜色只改你自己看到的样子。", "hint", wrap=True))

        lay.addWidget(label("主题", "section"))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.theme_btns: dict[str, QPushButton] = {}
        for i, (name, spec) in enumerate(theme.THEMES.items()):
            b = QPushButton(spec["label"])
            b.setObjectName("choice")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(QIcon(swatch_pixmap(theme.THEME_SWATCH[name][0], 16)))
            b.clicked.connect(lambda _=False, n=name: self.pick_theme(n))
            grid.addWidget(b, i // 4, i % 4)
            self.theme_btns[name] = b
        lay.addLayout(grid)

        self.accent_row = self._swatch_row("主题色(按钮、未读、链接)", "accent", "跟随主题")
        lay.addWidget(self.accent_row)
        self.bubble_row = self._swatch_row("我的气泡颜色", "bubble", "跟随主题")
        lay.addWidget(self.bubble_row)

        lay.addWidget(label("面板透明度", "section"))
        row = QHBoxLayout()
        row.addWidget(label("实心", "faint"))
        self.glass = QSlider(Qt.Orientation.Horizontal)
        self.glass.setRange(0, 100)
        self.glass.setValue(theme.CUSTOM.get("glass", 50))
        self.glass.valueChanged.connect(lambda v: self.queue("glass", v, 220))
        self.glass.sliderReleased.connect(self.flush)
        row.addWidget(self.glass, 1)
        row.addWidget(label("通透", "faint"))
        lay.addLayout(row)

        lay.addWidget(label("聊天背景", "section"))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(button("选择图片…", "", self.pick_background))
        self.clear_bg = button("恢复渐变壁纸", "", lambda: self.win.set_custom_background(None) or self.refresh())
        row.addWidget(self.clear_bg)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(label("遮罩暗度", "faint"))
        self.dim = QSlider(Qt.Orientation.Horizontal)
        self.dim.setRange(0, 80)
        self.dim.setValue(theme.CUSTOM.get(self.dim_key(), 0))
        self.dim.valueChanged.connect(self._on_dim_changed)
        self.dim.sliderReleased.connect(self.flush)
        row.addWidget(self.dim, 1)
        self.dim_val = label(f"{self.dim.value()}%", "faint")
        self.dim_val.setFixedWidth(36)
        row.addWidget(self.dim_val)
        lay.addLayout(row)

        brow = QHBoxLayout()
        brow.addWidget(label("壁纸模糊", "faint"))
        self.blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.blur_slider.setRange(0, 24)
        self.blur_slider.setValue(int(theme.CUSTOM.get("bg_blur_px", 12 if theme.CUSTOM.get("bg_blur", True) else 0)))
        self.blur_slider.valueChanged.connect(self._on_blur_changed)
        self.blur_slider.sliderReleased.connect(self.flush)
        brow.addWidget(self.blur_slider, 1)
        self.blur_val = label(f"{self.blur_slider.value()}px", "faint")
        self.blur_val.setFixedWidth(36)
        brow.addWidget(self.blur_val)
        lay.addLayout(brow)

        prev = QFrame()
        prev.setObjectName("plainCard")
        pl = QVBoxLayout(prev)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(6)
        a = label("今晚一起吃饭吗?", "previewOther")
        b2 = label("好呀,七点楼下见 🙌", "previewMine")
        for w in (a, b2):                                  # 和聊天里的气泡一样:够高才画得出圆角
            w.setMinimumHeight(2 * theme.BUBBLE_R)
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(a, 0, Qt.AlignmentFlag.AlignLeft)
        pl.addWidget(b2, 0, Qt.AlignmentFlag.AlignRight)
        lay.addWidget(prev)

        row = QHBoxLayout()
        row.addWidget(button("恢复默认", "link", self.reset))
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 80))
        ok = button("完成", "primary", self.accept, 90)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)
        self.refresh()

    # ---- 一排颜色小圆点
    def _swatch_row(self, title: str, key: str, follow_text: str) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 4, 0, 0)
        col.setSpacing(5)
        col.addWidget(label(title, "section"))
        row = QFrame()
        row.setObjectName("swatchRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(5)
        follow = QPushButton(follow_text)
        follow.setObjectName("choice")
        follow.setCheckable(True)
        follow.setCursor(Qt.CursorShape.PointingHandCursor)
        follow.setStyleSheet("QPushButton { padding: 3px 12px; border-radius: 13px; min-height: 20px; }")
        follow.setMinimumWidth(follow.fontMetrics().horizontalAdvance(follow_text) + 30)
        follow.clicked.connect(lambda: self.set_value(key, ""))
        rl.addWidget(follow)
        btns = []
        for c in theme.ACCENT_PRESETS:
            b = QPushButton("")
            b.setFixedSize(26, 26)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(c)
            b.clicked.connect(lambda _=False, c=c: self.set_value(key, c))
            rl.addWidget(b)
            btns.append((c, b))
        more = QPushButton("…")
        more.setFixedSize(26, 26)
        more.setToolTip("自定义颜色")
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.clicked.connect(lambda: self.pick_color(key))
        rl.addWidget(more)
        rl.addStretch(1)
        col.addWidget(row)
        w._follow, w._btns, w._key = follow, btns, key
        return w

    def refresh(self) -> None:
        for name, b in self.theme_btns.items():
            b.setChecked(T["name"] == name and not self.win.follow_time)
        for roww in (self.accent_row, self.bubble_row):
            cur = theme.CUSTOM.get(roww._key) or ""
            roww._follow.setChecked(not cur)
            for c, b in roww._btns:
                sel = cur.upper() == c.upper()
                b.setChecked(sel)
                ring = T["text"] if sel else "rgba(0,0,0,0.12)"
                b.setStyleSheet(f"QPushButton {{ background: {c}; border: {3 if sel else 1}px solid {ring}; "
                                f"border-radius: 13px; padding: 0; min-height: 0; }}")
        custom = theme.has_custom_bg()
        self.clear_bg.setEnabled(custom)
        self.dim.blockSignals(True)                         # 自己的背景图和渐变壁纸各记各的调暗程度
        self.dim.setValue(theme.CUSTOM.get(self.dim_key(), 0))
        self.dim.blockSignals(False)
        self.dim_val.setText(f"{self.dim.value()}%")
        self.dim.setToolTip("调暗你选的背景图(提高前景毛玻璃与文字对比度)" if custom else "调暗主题自带的渐变壁纸")
        self.blur_slider.setEnabled(custom)
        bpx = int(theme.CUSTOM.get("bg_blur_px", 12 if theme.CUSTOM.get("bg_blur", True) else 0))
        self.blur_slider.blockSignals(True)
        self.blur_slider.setValue(bpx)
        self.blur_slider.blockSignals(False)
        self.blur_val.setText(f"{bpx}px" if custom else "默认")
        self.blur_slider.setToolTip("调节自定义背景图模糊度(0=原图清晰, 24=奶油毛玻璃)" if custom else "只对自己选的背景图有效")

    def _on_dim_changed(self, v: int) -> None:
        self.dim_val.setText(f"{v}%")
        self.queue(self.dim_key(), v, 90)

    def _on_blur_changed(self, v: int) -> None:
        self.blur_val.setText(f"{v}px")
        self.queue("bg_blur_px", v, 110)

    @staticmethod
    def dim_key() -> str:
        return "bg_dim" if theme.has_custom_bg() else "wall_dim"

    # ---- 改动
    def pick_theme(self, name: str) -> None:
        self.win.set_theme(name)
        self.refresh()

    def set_value(self, key: str, value) -> None:
        self._pending.pop(key, None)
        self.win.apply_personalize({key: value}, rebuild=key in ("accent", "bubble", "glass"))
        self.refresh()

    def queue(self, key: str, value, delay: int) -> None:
        """滑块:先记下来,停手一小会儿再应用。"""
        self._pending[key] = value
        self._apply_timer.start(delay)

    def flush(self) -> None:
        self._apply_timer.stop()
        if not self._pending:
            return
        values, self._pending = self._pending, {}
        self.win.apply_personalize(values, rebuild="glass" in values)

    def pick_color(self, key: str) -> None:
        start = QColor(theme.CUSTOM.get(key) or T["accent"])
        c = QColorDialog.getColor(start, self, "选择颜色")
        if c.isValid():
            self.set_value(key, c.name().upper())

    def pick_background(self) -> None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        path, _ = QFileDialog.getOpenFileName(self, "选择背景图片", folder, imaging.IMAGE_FILTER)
        if not path:
            return
        img = imaging.load_file(path)
        if img is None or img.isNull():
            info(self, "无法读取图片", "图片格式不支持,或者图片太大。")
            return
        self.win.set_custom_background(img)
        self.refresh()

    def reset(self) -> None:
        self.win.apply_personalize({"accent": "", "bubble": "", "glass": 50, "bg_dim": 35, "bg_blur": True,
                                    "bg_blur_px": 12, "wall_dim": 0},
                                   rebuild=True)
        for w, v in ((self.glass, 50), (self.dim, theme.CUSTOM.get(self.dim_key(), 0)), (self.blur_slider, 12)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self._pending.clear()
        self.refresh()

    def accept(self) -> None:
        self.flush()
        super().accept()

    def reject(self) -> None:
        self._apply_timer.stop()
        self._pending.clear()
        custom, name, follow_system, follow_time = self._snapshot
        theme.CUSTOM.clear()
        theme.CUSTOM.update(custom)
        self.win.follow_system, self.win.follow_time = follow_system, follow_time
        theme.apply(QApplication.instance(), name)
        self.win._after_theme()
        if follow_time:
            self.win._time_period = None
            self.win._apply_time_theme()
        super().reject()


class StyleMixin:
    """个性化外观。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_style(self) -> None:
        self._bg_saved = True
        self.centralWidget().set_ambient(bool(theme.CUSTOM.get("ambient", True)))

    def _restore_style(self, acct: dict, st: dict) -> None:
        want = theme.clean_custom(st.get("custom"))
        if want != {k: theme.CUSTOM.get(k) for k in want}:      # 启动时 app.py 一般已经套用过了
            theme.set_custom(want)
            theme.apply(QApplication.instance(), T["name"], variant=T.get("variant"))
        if st.get("motion", True) != motion.ENABLED:
            self.set_motion(st.get("motion", True))
        self.centralWidget().set_ambient(bool(theme.CUSTOM.get("ambient", True)))
        if self.store is not None and self.remember:
            data = self.store.load_blob(storage.BG_FILE)
            img = imaging.decode(data) if data else None
            theme.set_custom_bg(img)

    def _settings_style(self) -> dict:
        return {"custom": dict(theme.CUSTOM), "motion": motion.ENABLED}

    # ---------------------------------------------------------------- 动态背景 / 界面动效
    def set_dynamic_bg(self, on: bool, level: int | None = None) -> None:
        """动态背景(光斑漂移、柔光扫过);关掉 = 静态背景,最省电。level:1 轻柔 / 2 明显。
        (白噪音是 look.py 里的 set_ambient)"""
        d = {"ambient": bool(on)}
        if level in theme.AMBIENT_LEVELS:
            d["ambient_level"] = level
        theme.set_custom(d)
        self.centralWidget().set_ambient(bool(on))

    def set_motion(self, on: bool) -> None:
        """界面动效总开关(按钮悬停、菜单弹窗淡入、切换过渡……)。"""
        motion.set_enabled(bool(on))
        theme.apply(QApplication.instance(), T["name"], variant=T.get("variant"))   # 悬停颜色改回样式表
        self._after_theme()

    def _tick_style(self, now: float) -> None:
        if not self._bg_saved and self._save_tick % 5 == 0:
            self._save_background()

    # ---------------------------------------------------------------- 外观
    @staticmethod
    def swatch_icon(color: str) -> QIcon:
        return QIcon(swatch_pixmap(color, 16))

    def show_personalize(self) -> None:
        PersonalizeDialog(self).exec()
        self.save_account()

    def apply_personalize(self, values: dict, rebuild: bool = True) -> None:
        """改个性化设置。颜色和透明度要重新生成样式表;背景调暗 / 模糊只要重画壁纸。"""
        theme.set_custom(values)
        if rebuild:
            theme.apply(QApplication.instance(), T["name"], variant=T.get("variant"))
            self._after_theme()
        else:
            self.centralWidget().update()

    def set_custom_background(self, img) -> None:
        """img = QImage(缩小后保存)或 None(恢复主题自带的渐变壁纸)。"""
        if img is not None and not img.isNull() and max(img.width(), img.height()) > BG_MAX_SIDE:
            img = img.scaled(BG_MAX_SIDE, BG_MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        theme.set_custom_bg(img)
        self._bg_saved = False
        self._save_background()
        self.centralWidget().update()

    def _save_background(self) -> None:
        """背景图单独加密存一个文件(没开「记住登录」时只在这次运行里有效)。"""
        if self.store is None or not self.remember:
            self._bg_saved = True
            return
        data = b""
        if theme._custom_bg is not None:
            data = imaging._save(theme._custom_bg, "JPG", 88)
        self._bg_saved = bool(self.store.save_blob(storage.BG_FILE, data or None))
