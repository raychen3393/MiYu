"""
密语 · 匿名纸条窗口(2.1):除了文字,还能夹一张表情包、图片、动图或一段短视频。
附件跟着纸条一起在群成员之间随机转交几手再发出(见 core.send_anon),谁也不知道是谁发的。
- 图片重新编码(去掉照片里的位置、设备信息);动图去掉注释 / XMP
- 视频只收 MP4 / MOV / M4V,最大 20MB,发出前去掉里面的拍摄位置、手机型号、拍摄时间
- 2.5:截图 / 复制的图片可以直接 Ctrl+V 粘贴进来;在资源管理器里复制的图片、视频文件也能粘贴或直接拖进窗口
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QStandardPaths, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from .. import imaging, video
from ..core import ANON_VIDEO_MAX
from ..dialogs import Dialog, info
from ..ui import button, file_ext, images_from_mime, label, local_paths
from ..widgets import EmojiPanel, GifLabel

VIDEO_FILTER = "视频 (*.mp4 *.mov *.m4v)"
VIDEO_OK = {"mp4", "mov", "m4v"}


def mime_has_media(mime) -> bool:
    """剪贴板 / 拖进来的东西里有没有能夹进纸条的图片或视频。"""
    if any(imaging.is_image_path(p) or file_ext(p) in VIDEO_OK for p in local_paths(mime)):
        return True
    return mime.hasImage() and not mime.hasUrls()


class NoteEdit(QPlainTextEdit):
    """纸条的输入框:粘贴图片 / 视频时交给窗口当附件,粘贴文字照常插入。"""
    media = Signal(object)            # QMimeData

    def canInsertFromMimeData(self, source) -> bool:
        return mime_has_media(source) or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:
        if mime_has_media(source):
            self.media.emit(source)
            return
        super().insertFromMimeData(source)


class AnonNoteDialog(Dialog):
    """写纸条:文字 + 最多一个附件。确定后 self.text、self.media 就是要发的内容。"""

    def __init__(self, win, max_len: int = 500) -> None:
        super().__init__(win, "匿名纸条")
        self.win = win
        self.max_len = max_len
        self.media: dict | None = None        # {"k": img/stk/vid, "data": 字节, ...}
        self._video_path = ""
        self.setFixedWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label("匿名纸条", "dialogTitle"))
        lay.addWidget(label("群里的人看不到是谁发的。纸条会先在群成员之间随机传几手再发出,连收到的人的电脑都分辨不出作者。"
                            "至少要 3 个人在线。\n可以夹一张表情包、图片、动图,或一段 20MB 以内的视频。", "hint", wrap=True))
        self.setAcceptDrops(True)
        self.edit = NoteEdit()
        self.edit.media.connect(self.use_mime)
        self.edit.setPlaceholderText("想说点什么…(只发图片 / 视频也行,截图可以直接 Ctrl+V 粘贴)")
        self.edit.setFixedHeight(96)
        lay.addWidget(self.edit)
        # 附件预览
        self.att = QFrame()
        self.att.setObjectName("plainCard")
        al = QHBoxLayout(self.att)
        al.setContentsMargins(10, 8, 8, 8)
        al.setSpacing(10)
        self.att_pic = QLabel()
        self.att_pic.setFixedSize(72, 72)
        self.att_pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        al.addWidget(self.att_pic)
        self.att_gif: GifLabel | None = None
        col = QVBoxLayout()
        col.setSpacing(2)
        self.att_title = label("", "fileName")
        self.att_sub = label("", "fileSub", wrap=True)
        col.addWidget(self.att_title)
        col.addWidget(self.att_sub)
        col.addStretch(1)
        al.addLayout(col, 1)
        al.addWidget(button("移除", "link", self.clear_media), 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.att)
        self.att.setVisible(False)
        # 按钮
        row = QHBoxLayout()
        row.setSpacing(6)
        self.emoji_btn = button("😊 表情", "", self.open_emoji)
        row.addWidget(self.emoji_btn)
        row.addWidget(button("🖼 图片 / 动图", "", self.pick_image))
        paste = button("📋 粘贴", "", self.paste_clipboard)
        paste.setToolTip("把剪贴板里的截图、图片或复制的视频文件夹进纸条(也可以直接按 Ctrl+V)")
        row.addWidget(paste)
        row.addWidget(button("🎬 视频", "", self.pick_video))
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 72))
        self.ok_btn = button("扔出去", "primary", self.accept, 80)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)

    # ---- 内容
    @property
    def text(self) -> str:
        return self.edit.toPlainText().strip()[: self.max_len]

    def accept(self) -> None:
        if not self.text and self.media is None:
            info(self, "纸条是空的", "写点什么,或者夹一张图片 / 一段视频。")
            return
        super().accept()

    # ---- 表情 / 表情包
    def open_emoji(self) -> None:
        w = self.win
        w.stickers.ensure()
        panel = EmojiPanel(self, w.recent_emojis, w.stickers.items, 0)
        panel.picked.connect(self.edit.insertPlainText)
        panel.sticker_picked.connect(self.use_sticker)
        panel.add_sticker.connect(lambda: None)
        panel.remove_sticker.connect(w.stickers.remove)
        pos = self.emoji_btn.mapToGlobal(QPoint(0, 0))
        panel.move(pos.x() - 8, pos.y() - panel.height() - 8)
        panel.show()

    def use_sticker(self, st: dict) -> None:
        data, mime = st.get("data"), st.get("mime")
        if not data or not mime:
            return
        self.media = {"k": "stk", "data": data, "mime": mime, "w": 0, "h": 0}
        self._show(data, mime, "表情包", imaging.human_size(len(data)))

    # ---- 粘贴 / 拖进来
    def keyPressEvent(self, e) -> None:
        # 焦点不在输入框(比如刚点过按钮)时按 Ctrl+V 也能粘贴;在输入框里由 NoteEdit 自己处理
        if e.matches(QKeySequence.StandardKey.Paste) and not self.edit.hasFocus():
            self.paste_clipboard()
            return
        super().keyPressEvent(e)

    def paste_clipboard(self) -> None:
        mime = QGuiApplication.clipboard().mimeData()
        if mime is None or not mime_has_media(mime):
            text = mime.text().strip() if mime is not None and mime.hasText() else ""
            if text:
                self.edit.insertPlainText(text)
                self.edit.setFocus()
            else:
                info(self, "剪贴板里没有图片", "先截图(Win + Shift + S)或复制一张图片 / 一个视频文件,再粘贴。")
            return
        self.use_mime(mime)

    def dragEnterEvent(self, e) -> None:
        if mime_has_media(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        if mime_has_media(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if mime_has_media(e.mimeData()):
            e.acceptProposedAction()
            self.use_mime(e.mimeData())
        else:
            super().dropEvent(e)

    def use_mime(self, mime) -> bool:
        """剪贴板 / 拖放 → 附件。纸条只夹一个附件:有多个文件时按顺序取第一个能用的图片 / 视频。"""
        for p in local_paths(mime):
            if file_ext(p) in VIDEO_OK:
                return self.use_video_path(p)
            if imaging.is_image_path(p):
                return self.use_image_path(p)
        imgs = images_from_mime(mime)
        if imgs:
            return self.use_image_item(imgs[0], "粘贴的图片")
        return False

    # ---- 图片 / 动图
    def pick_image(self) -> None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        path, _ = QFileDialog.getOpenFileName(self, "选择图片或动图", folder, imaging.IMAGE_FILTER)
        if path:
            self.use_image_path(path)

    def use_image_path(self, path: str) -> bool:
        it = imaging.load_image_path(path)
        if it is None:
            big = os.path.isfile(path) and os.path.getsize(path) > imaging.GIF_MAX
            info(self, "这张图片不能夹进纸条", "动图最大 8MB。" if big else "图片格式不支持,或者图片太大。")
            return False
        return self.use_image_item(it)

    def use_image_item(self, it, title: str = "") -> bool:
        if it is None:
            info(self, "这张图片不能夹进纸条", "图片格式不支持,或者图片太大。")
            return False
        enc = imaging.encode_any(it)                       # 普通图片重新编码(去掉位置等信息),动图去掉注释 / XMP
        if not enc:
            info(self, "图片处理失败", "这张图片无法压缩到可以发送的大小。")
            return False
        data, mime, w, h = enc
        self.media = {"k": "img", "data": data, "mime": mime, "w": w, "h": h}
        kind = title or ("动图" if mime == "image/gif" else "图片")
        self._show(data, mime, kind, f"{w}×{h}  ·  {imaging.human_size(len(data))}")
        return True

    # ---- 视频
    def pick_video(self) -> None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
        path, _ = QFileDialog.getOpenFileName(self, "选择视频(20MB 以内)", folder, VIDEO_FILTER)
        if path:
            self.use_video_path(path)

    def use_video_path(self, path: str) -> bool:
        try:
            size = os.path.getsize(path)
        except OSError:
            info(self, "读不到这个视频", "文件可能已被移动或删除。")
            return False
        if size > ANON_VIDEO_MAX:
            info(self, "视频太大", f"匿名纸条要经过别人转交,视频最大 {ANON_VIDEO_MAX // (1024 * 1024)}MB。"
                                 f"这个有 {imaging.human_size(size)},可以剪短一点再发,或者不匿名直接发文件。")
            return False
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            info(self, "读不到这个视频", str(e))
            return False
        clean = video.scrub_mp4(raw)                        # 去掉拍摄位置、手机型号、拍摄时间
        if clean is None:
            info(self, "这个视频格式不支持", "匿名纸条只能夹 MP4 / MOV / M4V 格式的视频。")
            return False
        name = os.path.basename(path)
        self.media = {"k": "vid", "data": clean, "name": name, "thumb": None, "dur": 0, "w": 0, "h": 0}
        self._video_path = path
        self._show(None, None, name, f"{imaging.human_size(len(clean))}  ·  正在生成封面…  ·  已去掉拍摄位置和设备信息")
        self.win.probe_video(path, lambda res, p=path: self._video_probed(p, res))
        return True

    def _video_probed(self, path: str, res) -> None:
        m = self.media
        if m is None or m.get("k") != "vid" or self._video_path != path:
            return                                          # 已经换成别的附件了
        try:
            if res:
                m.update({"thumb": res.get("thumb"), "dur": int(res.get("dur") or 0),
                          "w": int(res.get("w") or 0), "h": int(res.get("h") or 0)})
            dur = f"  ·  {video.fmt_dur(m['dur'])}" if m.get("dur") else ""
            self._show(m.get("thumb"), "image/jpeg" if m.get("thumb") else None, m["name"],
                       f"{imaging.human_size(len(m['data']))}{dur}  ·  已去掉拍摄位置和设备信息")
        except RuntimeError:                                # 窗口已经关了
            pass

    # ---- 预览
    def _show(self, data: bytes | None, mime: str | None, title: str, sub: str) -> None:
        if self.att_gif is not None:
            self.att_gif.setParent(None)
            self.att_gif.deleteLater()
            self.att_gif = None
        self.att_pic.clear()
        self.att_pic.setVisible(True)
        meta = imaging.gif_meta(data) if mime == "image/gif" else None
        if meta and meta[2] > 1:
            tw, th = imaging.fit_size(meta[0], meta[1], 72, 24)
            self.att_gif = GifLabel(data, min(72, tw), min(72, th), 8, badge=False)
            self.att.layout().insertWidget(0, self.att_gif)
            self.att_pic.setVisible(False)
            self.att_gif.set_active(True)
        elif data:
            img = imaging.decode_scaled(data, 144)
            if img is not None:
                self.att_pic.setPixmap(imaging.thumbnail(img, 72, 8, shadow=False))
        else:
            self.att_pic.setPixmap(QPixmap(icon_badge()))
        self.att_title.setText(title)
        self.att_sub.setText(sub)
        self.att.setVisible(True)

    def clear_media(self) -> None:
        self.media = None
        self._video_path = ""
        if self.att_gif is not None:
            self.att_gif.setParent(None)
            self.att_gif.deleteLater()
            self.att_gif = None
        self.att.setVisible(False)


def icon_badge():
    from ..icons import file_badge
    return file_badge("mp4", 56)
