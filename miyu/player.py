"""
密语 · 软件内看视频(2.5 重做)
- 画面比例:原始 / 16:9 / 4:3 / 21:9 / 1:1 / 铺满(裁掉多余的边)/ 拉伸填满
- 透明度:20%~100%,整个播放窗口半透明,能透过视频看到后面的东西;配合「置顶」「鼠标穿透」边干活边看。
  鼠标移到窗口上时自动变清楚(可以关)。
- 边下边看:视频还在下载时也能播放(见 stream.py),播放条上显示下载进度,没下载到的地方会显示"缓冲中"。

为什么这样画:
- 透明度用窗口整体透明度实现。毛玻璃(半透明背景)的窗口改透明度在 Windows 上会崩,所以播放器窗口
  自己不用毛玻璃背景(本来就是黑底)。
- 透明度不是 100% 时,画面改成自己一帧一帧画(QVideoSink → QPainter):系统的视频控件用显卡直接出图,
  放进半透明窗口里会黑屏。100% 时仍用系统控件,省电。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QRectF, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from .dialogs import Dialog, info
from .ui import button, label, make_menu, popup

RATIOS = [
    ("keep", "原始比例", 0.0),
    ("16:9", "16 : 9", 16 / 9),
    ("4:3", "4 : 3", 4 / 3),
    ("21:9", "21 : 9 宽银幕", 21 / 9),
    ("1:1", "1 : 1", 1.0),
    ("fill", "铺满(裁掉多余的边)", 0.0),
    ("stretch", "拉伸填满", 0.0),
]
RATIO_BY_ID = {r[0]: r for r in RATIOS}
OPACITY_MIN = 0.2
DEFAULT_PREFS = {"op": 1.0, "ratio": "keep", "top": False, "hover": True}


def clean_prefs(d) -> dict:
    """存下来的播放器设置 → 合法的设置(乱填的值换回默认)。"""
    out = dict(DEFAULT_PREFS)
    if not isinstance(d, dict):
        return out
    try:
        out["op"] = max(OPACITY_MIN, min(1.0, float(d.get("op", 1.0))))
    except (TypeError, ValueError):
        pass
    if d.get("ratio") in RATIO_BY_ID:
        out["ratio"] = d["ratio"]
    for k in ("top", "hover"):
        if isinstance(d.get(k), bool):
            out[k] = d[k]
    return out


def ratio_rect(mode: str, vw: float, vh: float, aw: float, ah: float):
    """画面放在播放区的哪里、取原画面的哪一块。
    返回 ((x, y, w, h) 目标位置, (sx, sy, sw, sh) 原画面里取的部分)。"""
    if vw <= 0 or vh <= 0:
        vw, vh = 16.0, 9.0
    src = (0.0, 0.0, float(vw), float(vh))
    if aw <= 0 or ah <= 0:
        return (0.0, 0.0, 0.0, 0.0), src
    if mode == "stretch":
        return (0.0, 0.0, float(aw), float(ah)), src
    if mode == "fill":                                      # 铺满:多出来的裁掉
        k = max(aw / vw, ah / vh)
        sw, sh = aw / k, ah / k
        return (0.0, 0.0, float(aw), float(ah)), ((vw - sw) / 2, (vh - sh) / 2, sw, sh)
    r = RATIO_BY_ID.get(mode, RATIOS[0])[2] or vw / vh
    if aw / ah > r:
        h = float(ah)
        w = h * r
    else:
        w = float(aw)
        h = w / r
    return ((aw - w) / 2, (ah - h) / 2, w, h), src


def fmt_ms(ms: int) -> str:
    s = max(0, int(ms or 0)) // 1000
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class VideoCanvas(QWidget):
    """自己画画面(透明度不是 100% 时用):按选好的比例摆放,黑边填黑。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.img: QImage | None = None
        self.mode = "keep"

    def set_image(self, img) -> None:
        self.img = img
        self.update()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        img = self.img
        if img is None or img.isNull():
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        (x, y, w, h), (sx, sy, sw, sh) = ratio_rect(self.mode, img.width(), img.height(), self.width(), self.height())
        p.drawImage(QRectF(x, y, w, h), img, QRectF(sx, sy, sw, sh))


class VideoPlayer(Dialog):
    """软件内看视频。用 Qt 自带的多媒体模块;创建失败(缺模块)时调用方会改用系统播放器。
    source:本地文件路径,或边下边看时本机小服务器的地址(http://127.0.0.1…)。
    path:视频最后保存的位置(用系统播放器打开、判断是不是同一个视频时用)。
    dl_info:边下边看时返回 (已下载比例 0~1, 状态 down/done/fail) 的函数。"""

    def __init__(self, parent, path: str, source: str = "", prefs: dict | None = None, dl_info=None,
                 title: str = "") -> None:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        super().__init__(parent, title or os.path.basename(path))
        if self.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)   # 要改整体透明度,不能用毛玻璃
        self._glass_capable = False
        self._shown_once = True                   # 不做淡入:淡入会把透明度改回 100%
        self.path = path
        self.source = source or path
        self.streaming = self.source.startswith("http://")
        self.prefs = prefs if prefs is not None else dict(DEFAULT_PREFS)
        self.prefs.update(clean_prefs(self.prefs))
        self.dl_info = dl_info
        self.passthrough = False
        self.vsize = (0, 0)                       # 视频原始尺寸(知道了才能按比例摆)
        self._hovering = False
        self._QMP = QMediaPlayer
        self.setModal(False)
        self.setObjectName("viewer")
        self.resize(960, 640)
        self._playing_state = QMediaPlayer.PlaybackState.PlayingState
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # 播放区:系统视频控件 / 自己画的画面,按比例手动摆放
        self.stage = QWidget()
        self.stage.setObjectName("videoStage")
        self.stage.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.stage.installEventFilter(self)
        lay.addWidget(self.stage, 1)
        self.video = QVideoWidget(self.stage)
        self.canvas: VideoCanvas | None = None
        self.sink = None
        self.buffer_tip = label("", "videoBuffer", center=True)
        self.buffer_tip.setParent(self.stage)
        self.buffer_tip.setVisible(False)
        self.error = label("", "errorText", center=True, wrap=True)
        self.error.setVisible(False)
        lay.addWidget(self.error)
        # 播放条
        bar = QFrame()
        bar.setObjectName("playerBar")
        bv = QVBoxLayout(bar)
        bv.setContentsMargins(12, 6, 12, 6)
        bv.setSpacing(4)
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        self.play_btn = button("暂停", "", self.toggle, 64)
        r1.addWidget(self.play_btn)
        self.pos_label = QLabel("0:00")
        r1.addWidget(self.pos_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(lambda v: self.player.setPosition(v))
        self.slider.sliderReleased.connect(lambda: self.player.setPosition(self.slider.value()))
        r1.addWidget(self.slider, 1)
        self.dur_label = QLabel("0:00")
        r1.addWidget(self.dur_label)
        r1.addWidget(QLabel("🔊"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(90)
        r1.addWidget(self.volume)
        self.speed_btn = button("1x", "", self.cycle_speed, 48)
        r1.addWidget(self.speed_btn)
        r1.addWidget(button("全屏", "", self.toggle_full, 56))
        bv.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        self.ratio_btn = button("", "", self.ratio_menu)
        self.ratio_btn.setToolTip("画面比例(R 键切换)")
        r2.addWidget(self.ratio_btn)
        r2.addWidget(QLabel("◐ 透明度"))
        self.op_slider = QSlider(Qt.Orientation.Horizontal)
        self.op_slider.setRange(int(OPACITY_MIN * 100), 100)
        self.op_slider.setFixedWidth(130)
        self.op_slider.setToolTip("整个窗口的透明度([ 和 ] 键调节)。调低后能透过视频看到后面的东西")
        r2.addWidget(self.op_slider)
        self.op_label = label("100%", "viewerInfo")
        self.op_label.setFixedWidth(36)
        r2.addWidget(self.op_label)
        self.top_btn = button("📌 置顶", "", self.toggle_top)
        self.top_btn.setCheckable(True)
        self.top_btn.setToolTip("一直显示在其它窗口上面(T 键)")
        r2.addWidget(self.top_btn)
        self.pass_btn = button("🖱 鼠标穿透", "", self.toggle_passthrough)
        self.pass_btn.setCheckable(True)
        self.pass_btn.setToolTip("鼠标直接点到视频后面的窗口。恢复:在密语里点 ＋ →「视频窗口:取消鼠标穿透」,或再点一次视频封面")
        r2.addWidget(self.pass_btn)
        r2.addStretch(1)
        self.dl_label = label("", "viewerInfo")
        self.dl_label.setVisible(self.streaming)
        r2.addWidget(self.dl_label)
        self.ext_btn = button("用系统播放器", "link", self.open_external)
        r2.addWidget(self.ext_btn)
        bv.addLayout(r2)
        lay.addWidget(bar)
        self.bar = bar

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.volume.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(self._on_error)
        self._speed = 1.0
        # 设置:比例、透明度、置顶
        self._set_ratio(self.prefs["ratio"], save=False)
        self.op_slider.setValue(int(round(self.prefs["op"] * 100)))
        self.op_slider.valueChanged.connect(self._on_op_slider)
        self._apply_opacity(self.prefs["op"])
        if self.prefs["top"]:
            self.top_btn.setChecked(True)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.dl_timer = QTimer(self)
        self.dl_timer.setInterval(500)
        self.dl_timer.timeout.connect(self._update_dl)
        if self.streaming:
            self.dl_timer.start()
            self._update_dl()
        self.player.setSource(QUrl(self.source) if self.streaming else QUrl.fromLocalFile(self.source))
        self.player.play()

    # ---------------------------------------------------------------- 播放
    def _on_pos(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.pos_label.setText(fmt_ms(ms))

    def _on_dur(self, ms: int) -> None:
        self.slider.setRange(0, ms)
        self.dur_label.setText(fmt_ms(ms))

    def _on_state(self, state) -> None:
        self.play_btn.setText("暂停" if state == self._playing_state else "播放")

    def _on_status(self, st) -> None:
        S = self._QMP.MediaStatus
        if st in (S.LoadingMedia, S.BufferingMedia, S.StalledMedia):
            self._buffer_text("缓冲中…这一段还在下载" if self.streaming and st != S.LoadingMedia else "正在打开…")
        else:
            self.buffer_tip.setVisible(False)
        if st in (S.LoadedMedia, S.BufferedMedia):
            self._read_size()

    def _buffer_text(self, text: str) -> None:
        self.buffer_tip.setText(text)
        self.buffer_tip.setVisible(True)
        self._layout_stage()

    def _read_size(self) -> None:
        try:
            from PySide6.QtMultimedia import QMediaMetaData
            sz = self.player.metaData().value(QMediaMetaData.Key.Resolution)
            w, h = int(sz.width()), int(sz.height())
        except Exception:                                    # noqa: BLE001
            return
        if w > 0 and h > 0:
            self.vsize = (w, h)
            self._layout_stage()

    def _on_error(self, *_a) -> None:
        if self.streaming:
            self.error.setText("边下边看没成功(这个视频可能要整个下完才能放)。下载完成后再点封面播放就行。")
        else:
            self.error.setText("这个视频播放不了(可能是格式不支持)。可以点右下角「用系统播放器」。")
        self.error.setVisible(True)

    def toggle(self) -> None:
        if self.player.playbackState() == self._playing_state:
            self.player.pause()
        else:
            self.player.play()

    def cycle_speed(self) -> None:
        speeds = [1.0, 1.25, 1.5, 2.0, 0.5]
        self._speed = speeds[(speeds.index(self._speed) + 1) % len(speeds)] if self._speed in speeds else 1.0
        self.player.setPlaybackRate(self._speed)
        self.speed_btn.setText(f"{self._speed:g}x")

    def toggle_full(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def open_external(self) -> None:
        if self.streaming and not (self.dl_info is not None and self.dl_info()[1] == "done"):
            info(self, "还在下载", "视频下载完以后才能用系统播放器打开。现在可以先在这里边下边看。")
            return
        self.player.pause()
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    # ---------------------------------------------------------------- 边下边看
    def _update_dl(self) -> None:
        if self.dl_info is None:
            return
        try:
            frac, state = self.dl_info()
        except Exception:                                    # noqa: BLE001
            return
        if state == "done":
            self.dl_label.setText("✓ 已下载完")
            self.dl_timer.stop()
        elif state == "fail":
            self.dl_label.setText("下载停了,后面的部分看不了")
            self.dl_timer.stop()
        else:
            self.dl_label.setText(f"⬇ 已下载 {int(frac * 100)}%")

    # ---------------------------------------------------------------- 画面比例
    def ratio_menu(self) -> None:
        m = make_menu(self)
        for rid, name, _r in RATIOS:
            a = m.addAction(name, lambda r=rid: self._set_ratio(r))
            a.setCheckable(True)
            a.setChecked(rid == self.prefs["ratio"])
        m.addSeparator()
        a = m.addAction("鼠标移上去时变清楚", self._toggle_hover)
        a.setCheckable(True)
        a.setChecked(bool(self.prefs["hover"]))
        popup(m, self.ratio_btn.mapToGlobal(self.ratio_btn.rect().topLeft()))

    def _set_ratio(self, rid: str, save: bool = True) -> None:
        if rid not in RATIO_BY_ID:
            rid = "keep"
        self.prefs["ratio"] = rid
        name = RATIO_BY_ID[rid][1].split("(")[0]
        self.ratio_btn.setText(f"画面:{name} ▾")
        if self.canvas is not None:
            self.canvas.set_mode(rid)
        self._layout_stage()

    def cycle_ratio(self) -> None:
        ids = [r[0] for r in RATIOS]
        self._set_ratio(ids[(ids.index(self.prefs["ratio"]) + 1) % len(ids)])

    def _toggle_hover(self) -> None:
        self.prefs["hover"] = not self.prefs["hover"]
        self._apply_opacity(self.prefs["op"])

    def _layout_stage(self) -> None:
        w, h = self.stage.width(), self.stage.height()
        if self.canvas is not None:
            self.canvas.setGeometry(0, 0, w, h)
        else:
            mode = self.prefs["ratio"]
            AR = Qt.AspectRatioMode
            if mode in ("keep", "fill", "stretch"):         # 系统控件自己就会这三种
                self.video.setAspectRatioMode({"keep": AR.KeepAspectRatio, "fill": AR.KeepAspectRatioByExpanding,
                                               "stretch": AR.IgnoreAspectRatio}[mode])
                self.video.setGeometry(0, 0, w, h)
            else:                                           # 固定比例:把控件摆成那个比例,画面拉满控件
                (x, y, rw, rh), _src = ratio_rect(mode, self.vsize[0], self.vsize[1], w, h)
                self.video.setAspectRatioMode(AR.IgnoreAspectRatio)
                self.video.setGeometry(int(x), int(y), int(rw), int(rh))
        tw = min(w - 20, max(220, self.buffer_tip.sizeHint().width() + 8))
        self.buffer_tip.setGeometry((w - tw) // 2, h // 2 - 18, tw, 36)
        self.buffer_tip.raise_()

    def eventFilter(self, obj, e) -> bool:
        if obj is self.stage and e.type() == QEvent.Type.Resize:
            self._layout_stage()
        return super().eventFilter(obj, e)

    # ---------------------------------------------------------------- 透明度 / 置顶 / 穿透
    def _on_op_slider(self, v: int) -> None:
        self.prefs["op"] = max(OPACITY_MIN, min(1.0, v / 100))
        self._apply_opacity(self.prefs["op"])

    def _apply_opacity(self, op: float) -> None:
        op = max(OPACITY_MIN, min(1.0, op))
        self.op_label.setText(f"{int(round(op * 100))}%")
        if op < 0.999:
            self._use_canvas()
        shown = 1.0 if (self._hovering and self.prefs["hover"] and not self.passthrough) else op
        if self.canvas is None and shown >= 0.999:
            return                                           # 一直是 100%:不碰窗口透明度
        if not self.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            self.setWindowOpacity(shown)

    def _use_canvas(self) -> None:
        """改成自己画画面(半透明窗口里系统视频控件会黑屏)。换过去就不再换回来。"""
        if self.canvas is not None:
            return
        from PySide6.QtMultimedia import QVideoSink
        self.canvas = VideoCanvas(self.stage)
        self.canvas.set_mode(self.prefs["ratio"])
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self.player.setVideoOutput(self.sink)
        self.video.hide()
        self.canvas.show()
        self._layout_stage()

    def _on_frame(self, frame) -> None:
        try:
            img = frame.toImage()
        except Exception:                                    # noqa: BLE001
            return
        if img is not None and not img.isNull() and self.canvas is not None:
            if self.vsize == (0, 0):
                self.vsize = (img.width(), img.height())
            self.canvas.set_image(img)

    def enterEvent(self, e) -> None:
        self._hovering = True
        self._apply_opacity(self.prefs["op"])
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hovering = False
        self._apply_opacity(self.prefs["op"])
        super().leaveEvent(e)

    def _set_flag(self, flag, on: bool) -> None:
        geo = self.geometry()
        self.setWindowFlag(flag, on)                         # 改窗口属性会把窗口藏起来,重新显示
        self.setGeometry(geo)
        self.show()
        self._apply_opacity(self.prefs["op"])

    def toggle_top(self) -> None:
        on = not self.prefs["top"]
        self.prefs["top"] = on
        self.top_btn.setChecked(on)
        self._set_flag(Qt.WindowType.WindowStaysOnTopHint, on)

    def toggle_passthrough(self) -> None:
        self.set_passthrough(not self.passthrough)

    def set_passthrough(self, on: bool) -> None:
        if on == self.passthrough:
            self.pass_btn.setChecked(on)
            return
        if on and not info_ok(self):
            self.pass_btn.setChecked(False)
            return
        self.passthrough = on
        self.pass_btn.setChecked(on)
        if on and not self.prefs["top"]:                     # 穿透一般是想边干活边看:顺便置顶
            self.prefs["top"] = True
            self.top_btn.setChecked(True)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if on and self.prefs["op"] > 0.9:                    # 完全不透明时穿透会以为窗口点不动:先调到 70%
            self.op_slider.setValue(70)
        self._set_flag(Qt.WindowType.WindowTransparentForInput, on)

    # ---------------------------------------------------------------- 键盘 / 关闭
    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k == Qt.Key.Key_Space:
            self.toggle()
        elif k == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
        elif k == Qt.Key.Key_Right:
            self.player.setPosition(self.player.position() + 5000)
        elif k == Qt.Key.Key_Left:
            self.player.setPosition(max(0, self.player.position() - 5000))
        elif k == Qt.Key.Key_F:
            self.toggle_full()
        elif k == Qt.Key.Key_R:
            self.cycle_ratio()
        elif k == Qt.Key.Key_T:
            self.toggle_top()
        elif k == Qt.Key.Key_BracketLeft:
            self.op_slider.setValue(max(int(OPACITY_MIN * 100), self.op_slider.value() - 10))
        elif k == Qt.Key.Key_BracketRight:
            self.op_slider.setValue(min(100, self.op_slider.value() + 10))
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        self.toggle_full()

    def stop(self) -> None:
        try:
            self.dl_timer.stop()
            self.player.stop()
        except Exception:                                    # noqa: BLE001
            pass
        if self.streaming:
            from . import stream
            stream.server().remove(self.source)

    def closeEvent(self, e) -> None:
        self.stop()
        super().closeEvent(e)


_told_passthrough = False


def info_ok(parent) -> bool:
    """第一次开鼠标穿透时说明怎么恢复(穿透以后这个窗口就点不到了)。"""
    global _told_passthrough
    if _told_passthrough:
        return True
    from .dialogs import ask
    ok = ask(parent, "开启鼠标穿透?", "开启后鼠标会直接点到视频后面的窗口,这个播放窗口就点不到了。\n"
             "想恢复:在密语里点输入框左边的 ＋ →「视频窗口:取消鼠标穿透」,或者再点一次聊天里的视频封面。", "开启")
    if ok:
        _told_passthrough = True
    return bool(ok)
