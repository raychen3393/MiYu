"""
密语 · 图片处理
- 发送前:按 EXIF 摆正方向、缩到最长边 2048、重新编码成 JPEG/PNG
  (重新编码会去掉照片里的 GPS 位置、拍摄设备等隐私信息)
- 动图(GIF)保留原样才能动:发送前逐块检查结构,去掉注释、XMP 之类的附加信息,只留画面和循环设置
- 接收后:先检查尺寸再解码,防止"解压炸弹"图片撑爆内存
"""
from __future__ import annotations

import os

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPainterPath, QPixmap, QTextOption

from .icons import paint_icon, soft_shadow

MAX_SIDE = 2048
MAX_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 50_000_000
THUMB = 260
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"

try:
    QImageReader.setAllocationLimit(256)     # MB,Qt 6 内置的解码内存上限
except Exception:
    pass


# ---------------------------------------------------------------- 动图(GIF)
GIF_MAX = 8 * 1024 * 1024        # 和网络层的图片上限一样
GIF_MAX_SIDE = 4096
GIF_MAX_FRAMES = 1500
GIF_KEEP_APPS = (b"NETSCAPE2.0", b"ANIMEXTS1.0")    # 只保留"循环播放"设置,其它应用扩展(XMP 等)去掉


def parse_gif(data: bytes, clean: bool = False):
    """逐块检查 GIF。返回 (宽, 高, 帧数, 清理后的字节或 None);格式不对返回 None。
    clean=True 时去掉注释、纯文本和除"循环设置"以外的应用扩展(里面可能有作者、软件、XMP 等信息)。"""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 14 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    n = len(data)
    w, h = data[6] | data[7] << 8, data[8] | data[9] << 8
    if not (0 < w <= GIF_MAX_SIDE and 0 < h <= GIF_MAX_SIDE):
        return None
    pos = 13
    if data[10] & 0x80:
        pos += 3 << ((data[10] & 7) + 1)
    if pos > n:
        return None
    out = [bytes(data[:pos])] if clean else None
    frames = 0

    def sub_blocks(i: int) -> int:
        """跳过一串数据子块,返回结束后的位置;越界返回 -1。"""
        while True:
            if i >= n:
                return -1
            size = data[i]
            i += 1
            if size == 0:
                return i
            i += size
            if i > n:
                return -1

    while pos < n:
        tag = data[pos]
        if tag == 0x3B:                                     # 结束
            if out is not None:
                out.append(b"\x3b")
            return w, h, frames, (b"".join(out) if out is not None else None)
        if tag == 0x2C:                                     # 一帧
            if pos + 10 > n:
                return None
            fw, fh = data[pos + 5] | data[pos + 6] << 8, data[pos + 7] | data[pos + 8] << 8
            if fw > GIF_MAX_SIDE or fh > GIF_MAX_SIDE:
                return None
            end = pos + 10
            if data[pos + 9] & 0x80:
                end += 3 << ((data[pos + 9] & 7) + 1)
            end += 1                                        # LZW 最小码长
            end = sub_blocks(end) if end <= n else -1
            if end < 0:
                return None
            frames += 1
            if frames > GIF_MAX_FRAMES:
                return None
            if out is not None:
                out.append(bytes(data[pos:end]))
            pos = end
        elif tag == 0x21:                                   # 扩展块
            if pos + 2 > n:
                return None
            label_ = data[pos + 1]
            end = sub_blocks(pos + 2)
            if end < 0:
                return None
            keep = label_ == 0xF9                           # 帧的显示时间 / 透明色
            if label_ == 0xFF and pos + 14 <= n and data[pos + 2] == 11:
                keep = bytes(data[pos + 3:pos + 14]) in GIF_KEEP_APPS
            if keep and out is not None:
                out.append(bytes(data[pos:end]))
            pos = end
        else:
            return None
    # 没有结束标记:很多软件导出的 GIF 会少这一个字节,能显示就补上
    if frames and out is not None:
        out.append(b"\x3b")
    return (w, h, frames, (b"".join(out) if out is not None else None)) if frames else None


_gif_meta_cache: dict = {}


def gif_meta(data: bytes):
    """收到的 GIF:(宽, 高, 帧数) 或 None(格式不对 / 太大 / 尺寸超限)。结果按内容缓存,重画时不用再解析。"""
    if not data or len(data) > GIF_MAX:
        return None
    key = (len(data), bytes(data[:48]), bytes(data[-48:]))
    if key in _gif_meta_cache:
        return _gif_meta_cache[key]
    info_ = parse_gif(data)
    v = info_[:3] if info_ else None
    if len(_gif_meta_cache) > 256:
        _gif_meta_cache.clear()
    _gif_meta_cache[key] = v
    return v


def is_animated_gif(data: bytes) -> bool:
    info_ = parse_gif(data)
    return bool(info_ and info_[2] > 1)


class Gif:
    """一张要发出去的动图:清理过的原始字节 + 尺寸 + 第一帧(做预览)。"""

    def __init__(self, data: bytes, w: int, h: int, frames: int, first: QImage | None) -> None:
        self.data, self.w, self.h, self.frames, self.first = data, w, h, frames, first

    def isNull(self) -> bool:                                # 和 QImage 一样的判断方式,方便混在一起处理
        return not self.data


def load_gif_bytes(data: bytes) -> Gif | None:
    """动图字节 → Gif;不是动图、太大或格式不对返回 None。"""
    if not data or len(data) > GIF_MAX:
        return None
    info_ = parse_gif(data, clean=True)
    if not info_ or info_[2] < 2 or not info_[3] or len(info_[3]) > GIF_MAX:
        return None
    w, h, frames, clean = info_
    return Gif(clean, w, h, frames, decode(clean))


def load_image_path(path: str):
    """选图 / 拖进来 / 粘贴的图片文件:动图返回 Gif(保持会动),其它返回 QImage;读不了返回 None。
    超过 8MB 的动图返回 None(调用方会改成当文件发)。"""
    try:
        with open(path, "rb") as f:
            head = f.read(6)
            if head in (b"GIF87a", b"GIF89a"):
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size <= GIF_MAX:
                    f.seek(0)
                    gif = load_gif_bytes(f.read())
                    if gif is not None:
                        return gif
                elif size <= 64 * 1024 * 1024:
                    f.seek(0)
                    if is_animated_gif(f.read()):
                        return None                         # 动图太大:不压成一张静态图,让调用方当文件发
    except OSError:
        return None
    return load_file(path)


def preview_image(item) -> QImage | None:
    """QImage 或 Gif → 用来做预览的一张图。"""
    return item.first if isinstance(item, Gif) else item


def encode_any(item):
    """QImage / Gif → (字节, mime, 宽, 高);失败返回 None。"""
    if isinstance(item, Gif):
        return (item.data, "image/gif", item.w, item.h) if item.data else None
    return encode_for_send(item)


def is_image_path(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() in IMAGE_EXTS


def _read(reader: QImageReader) -> QImage | None:
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        if size.width() * size.height() > MAX_PIXELS or size.width() > 16000 or size.height() > 16000:
            return None
    img = reader.read()
    return None if img.isNull() else img


def load_file(path: str) -> QImage | None:
    return _read(QImageReader(path))


def decode_scaled(data: bytes, max_side: int) -> QImage | None:
    """按缩略图大小解码:大照片不用先解出几千万像素再缩小(JPEG 直接在解码时缩,快很多)。"""
    if not data:
        return None
    ba = QByteArray(data)
    buf = QBuffer(ba)
    if not buf.open(QIODevice.OpenModeFlag.ReadOnly):
        return None
    try:
        reader = QImageReader(buf)
        size = reader.size()
        if not size.isValid():
            return None
        if size.width() > max_side or size.height() > max_side:
            w, h = fit_size(size.width(), size.height(), max_side)
            reader.setScaledSize(QSize(max(1, w), max(1, h)))
        return _read(reader)
    finally:
        buf.close()


class ThumbCache:
    """最近用过的缩略图(按消息记住):翻页、重画、从数据库重新读出来时不用再解码。"""

    def __init__(self, cap: int = 48) -> None:
        self.cap = cap
        self._d: dict = {}

    def get(self, key):
        v = self._d.pop(key, None)
        if v is not None:
            self._d[key] = v
        return v

    def put(self, key, pm) -> None:
        self._d.pop(key, None)
        self._d[key] = pm
        while len(self._d) > self.cap:
            self._d.pop(next(iter(self._d)))

    def clear(self) -> None:
        self._d.clear()


thumb_cache = ThumbCache()


def decode(data: bytes) -> QImage | None:
    if not data:
        return None
    ba = QByteArray(data)
    buf = QBuffer(ba)
    if not buf.open(QIODevice.OpenModeFlag.ReadOnly):
        return None
    try:
        reader = QImageReader(buf)
        size = reader.size()
        if not size.isValid():
            return None
        return _read(reader)
    finally:
        buf.close()


def _save(img: QImage, fmt: str, quality: int = -1) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, fmt, quality)
    buf.close()
    return bytes(ba.data())


def encode_for_send(img: QImage):
    """返回 (字节, mime, 宽, 高);失败返回 None。"""
    if img is None or img.isNull():
        return None
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    if img.hasAlphaChannel():
        data = _save(img, "PNG")
        if 0 < len(data) <= 1536 * 1024:
            return data, "image/png", img.width(), img.height()
    flat = QImage(img.size(), QImage.Format.Format_RGB32)
    flat.fill(QColor("#ffffff"))
    p = QPainter(flat)
    p.drawImage(0, 0, img)
    p.end()
    for quality in (86, 76, 62):
        data = _save(flat, "JPG", quality)
        if 0 < len(data) <= MAX_BYTES:
            return data, "image/jpeg", flat.width(), flat.height()
    small = flat.scaled(1280, 1280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    data = _save(small, "JPG", 70)
    if 0 < len(data) <= MAX_BYTES:
        return data, "image/jpeg", small.width(), small.height()
    return None


def encode_sticker(img: QImage):
    """表情包:缩到最长边 320,有透明的存 PNG,否则 JPEG。返回 (字节, mime) 或 None。"""
    if img is None or img.isNull():
        return None
    if max(img.width(), img.height()) > 320:
        img = img.scaled(320, 320, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if img.hasAlphaChannel():
        data = _save(img, "PNG")
        if 0 < len(data) <= 1024 * 1024:
            return data, "image/png"
    flat = QImage(img.size(), QImage.Format.Format_RGB32)
    flat.fill(QColor("#ffffff"))
    p = QPainter(flat)
    p.drawImage(0, 0, img)
    p.end()
    data = _save(flat, "JPG", 88)
    return (data, "image/jpeg") if data else None


def encode_avatar(img: QImage, side: int = 96):
    """头像:居中裁成正方形,缩到 96 像素,存成 JPEG。返回 (字节, mime) 或 None。"""
    if img is None or img.isNull():
        return None
    w, h = img.width(), img.height()
    s = min(w, h)
    if s <= 0:
        return None
    img = img.copy((w - s) // 2, (h - s) // 2, s, s).scaled(
        side, side, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    flat = QImage(img.size(), QImage.Format.Format_RGB32)
    flat.fill(QColor("#ffffff"))
    p = QPainter(flat)
    p.drawImage(0, 0, img)
    p.end()
    data = _save(flat, "JPG", 88)
    return (data, "image/jpeg") if data else None


def fit_size(w: int, h: int, max_side: int, min_side: int = 60) -> tuple[int, int]:
    if w <= 0 or h <= 0:
        return max_side, max_side
    scale = min(1.0, max_side / max(w, h))
    tw, th = max(1, int(w * scale)), max(1, int(h * scale))
    if min(tw, th) < min_side:                    # 特别细长的图,至少给一点高度/宽度
        k = min_side / min(tw, th)
        tw, th = min(int(tw * k), max_side * 2), min(int(th * k), max_side * 2)
    return tw, th


def thumbnail(img: QImage, max_side: int = THUMB, radius: float = 16.0, hidden: bool = False,
              label: str = "", shadow: bool = True) -> QPixmap:
    """圆角缩略图(带柔和阴影)。hidden=True 时打马赛克并盖上"点击查看"(阅后即焚图片)。"""
    tw, th = fit_size(img.width(), img.height(), max_side)
    if hidden:
        tw, th = max(tw, 140), max(th, 100)
    pad = 7 if shadow else 0
    dpr = 2.0
    pm = QPixmap(int((tw + 2 * pad) * dpr), int((th + 2 * pad) * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    box = QRectF(pad, pad, tw, th)
    if shadow:
        soft_shadow(p, box, radius, 34, 6, 2.0)
    clip = QPainterPath()
    clip.addRoundedRect(box, radius, radius)
    p.setClipPath(clip)
    if hidden:
        tiny = img.scaled(max(1, tw // 14), max(1, th // 14), Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        p.drawImage(box, tiny)
        p.fillRect(box, QColor(0, 0, 0, 110))
        paint_icon(p, "flame", "#ffffff", pad + tw / 2 - 13, pad + th / 2 - 26, 26, 1.8)
        f = QFont()
        f.setPixelSize(13)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(pad, pad + th / 2 + 6, tw, 22), label or "点击查看", QTextOption(Qt.AlignmentFlag.AlignCenter))
    else:
        scaled = img.scaled(int(tw * dpr), int(th * dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        sw, sh = scaled.width(), scaled.height()       # 居中裁切,保证不变形
        ratio = tw / th
        if sw / max(1, sh) > ratio:
            cw = sh * ratio
            src = QRectF((sw - cw) / 2, 0, cw, sh)
        else:
            ch = sw / ratio
            src = QRectF(0, (sh - ch) / 2, sw, ch)
        p.drawImage(box, scaled, src)
    p.end()
    return pm


def human_size(n: int) -> str:
    if n >= 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024 / 1024:.2f} GB"
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{max(1, n // 1024)} KB"
