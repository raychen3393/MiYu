"""
密语 · 视频
- 封面和时长:用 Qt 自带的多媒体模块(和软件内播放器是同一套)悄悄打开视频,取一帧不黑的画面当封面
- 去掉 MP4 / MOV 里的拍摄信息:手机拍的视频里常带 GPS 位置、手机型号、拍摄时间。
  匿名纸条发视频前,把这些块原地改成"空白块"(free)并清零,不改变任何块的大小和位置,播放器照常能放
"""
from __future__ import annotations

import base64
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage

POSTER_SIDE = 480                     # 封面最长边
POSTER_MAX_BYTES = 60 * 1024          # 封面最大 60KB(跟着消息发出去,不能太大)
POSTER_RECV_MAX = 96 * 1024           # 收到的封面最大(再大就不认)
PROBE_TIMEOUT = 8.0                   # 最多等几秒
MP4_EXTS = {"mp4", "mov", "m4v"}
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf", b"mvex", b"moof", b"traf"}
_BLANK = {b"udta", b"meta", b"uuid", b"XMP_"}  # 用户数据 / 元数据 / XMP:位置、设备、软件、作者都在这里
_TIMES = {b"mvhd", b"tkhd", b"mdhd"}          # 这几个块里记着创建 / 修改时间


def fmt_dur(ms: int) -> str:
    s = max(0, int(ms or 0) // 1000)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ---------------------------------------------------------------- MP4 拍摄信息
def is_mp4(data: bytes) -> bool:
    return isinstance(data, (bytes, bytearray)) and len(data) >= 16 and data[4:8] == b"ftyp"


def scrub_mp4(data: bytes) -> bytes | None:
    """返回去掉拍摄信息的副本;不是 MP4 / MOV 或结构不对返回 None。"""
    if not is_mp4(data):
        return None
    buf = bytearray(data)
    n = len(buf)

    def walk(start: int, end: int, depth: int) -> bool:
        pos = start
        while pos + 8 <= end:
            size = int.from_bytes(buf[pos:pos + 4], "big")
            kind = bytes(buf[pos + 4:pos + 8])
            hdr = 8
            if size == 1:
                if pos + 16 > end:
                    return False
                size = int.from_bytes(buf[pos + 8:pos + 16], "big")
                hdr = 16
            elif size == 0:                                 # 一直到文件末尾
                size = end - pos
            if size < hdr or pos + size > end:
                return False
            body, stop = pos + hdr, pos + size
            if kind in _BLANK:
                buf[pos + 4:pos + 8] = b"free"
                buf[body:stop] = bytes(stop - body)
            elif kind in _CONTAINERS:
                if depth > 12 or not walk(body, stop, depth + 1):
                    return False
            elif kind in _TIMES and body + 4 <= stop:
                width = 8 if buf[body] == 1 else 4          # 版本 1 用 64 位时间
                a, b = body + 4, min(stop, body + 4 + 2 * width)
                buf[a:b] = bytes(b - a)
            pos = stop
        return pos == end or end - pos < 8

    return bytes(buf) if walk(0, n, 0) else None


# ---------------------------------------------------------------- 封面
def encode_poster(img: QImage) -> bytes | None:
    """一帧画面 → 小 JPEG(最长边 480,最大 60KB)。"""
    if img is None or img.isNull():
        return None
    for side, quality in ((POSTER_SIDE, 74), (POSTER_SIDE, 58), (360, 60), (280, 55)):
        im = img
        if max(im.width(), im.height()) > side:
            im = im.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        ba = QByteArray()
        b = QBuffer(ba)
        b.open(QIODevice.OpenModeFlag.WriteOnly)
        im.convertToFormat(QImage.Format.Format_RGB32).save(b, "JPG", quality)
        b.close()
        data = bytes(ba.data())
        if 0 < len(data) <= POSTER_MAX_BYTES:
            return data
    return None


def clean_poster(v) -> bytes | None:
    """收到的封面(base64 字符串):只认小于 96KB 的 JPEG。"""
    if not isinstance(v, str) or len(v) > POSTER_RECV_MAX * 4 // 3 + 8:
        return None
    try:
        data = base64.b64decode(v, validate=True)
    except (ValueError, TypeError):
        return None
    return data if 0 < len(data) <= POSTER_RECV_MAX and data.startswith(b"\xff\xd8\xff") else None


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _brightness(img: QImage) -> float:
    """整张图大概有多亮(0~255),用来跳过开头的黑屏。"""
    small = img.scaled(8, 8, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    total = 0.0
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            total += 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return total / max(1, small.width() * small.height())


class VideoProbe(QObject):
    """打开一个视频,取封面和时长。完成时发 done({"thumb": JPEG 字节或 None, "dur": 毫秒, "w", "h"}),
    完全打不开发 done(None)。没有声音输出,不会发出声音;最多等 8 秒。"""
    done = Signal(object)

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self._finished = False
        self._best: tuple[float, QImage] | None = None
        self._frames = 0
        self._dur = 0
        self._target = 0
        self._t0 = time.monotonic()
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
        except Exception:                                   # 没有多媒体模块
            QTimer.singleShot(0, lambda: self._finish(None))
            return
        self._loaded = QMediaPlayer.MediaStatus.LoadedMedia
        self._bad = (QMediaPlayer.MediaStatus.InvalidMedia,)
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(lambda *_a: self._finish(self._result()))
        self.player.durationChanged.connect(lambda ms: setattr(self, "_dur", int(ms or 0)))
        QTimer.singleShot(int(PROBE_TIMEOUT * 1000), lambda: self._finish(self._result()))
        self.player.setSource(QUrl.fromLocalFile(path))

    def _on_status(self, st) -> None:
        if st in self._bad:
            self._finish(None)
        elif st == self._loaded:
            self._dur = int(self.player.duration() or 0)
            self._target = min(1500, self._dur // 10) if self._dur > 0 else 0
            if self._target and self.player.isSeekable():
                self.player.setPosition(self._target)
            self.player.play()

    def _on_frame(self, frame) -> None:
        if self._finished or not frame.isValid():
            return
        img = frame.toImage()
        if img.isNull():
            return
        self._frames += 1
        lum = _brightness(img)
        if self._best is None or lum > self._best[0]:
            self._best = (lum, img.copy())
        reached = self.player.position() >= self._target * 0.8 or self._frames >= 8
        if (lum >= 28 and reached) or self._frames >= 40 or time.monotonic() - self._t0 > PROBE_TIMEOUT / 2:
            self._finish(self._result())

    def _result(self) -> dict | None:
        if self._best is None and not self._dur:
            return None
        img = self._best[1] if self._best is not None else None
        return {"thumb": encode_poster(img) if img is not None else None, "dur": max(0, self._dur),
                "w": img.width() if img is not None else 0, "h": img.height() if img is not None else 0}

    def _finish(self, res) -> None:
        if self._finished:
            return
        self._finished = True
        player = getattr(self, "player", None)
        if player is not None:
            try:
                player.stop()
                player.setSource(QUrl())
            except RuntimeError:
                pass
        self.done.emit(res)
        self.deleteLater()
