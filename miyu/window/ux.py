"""
密语 · 交互细节:消息快捷操作条、拖拽直接发送、会话置顶。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QToolTip

from .. import imaging
from ..dialogs import ask, info
from ..ui import HEADER_H, VIDEO_EXTS, drop_paths, file_ext, images_from_mime
from ..widgets import AURA_BUBBLES, GIF_LABELS, Conv, DropOverlay, HoverBar, Msg

MAX_DROP = 30                     # 一次最多拖多少个(图片 + 文件 + 文件夹)


def classify_paths(paths: list[str]) -> dict[str, list[str]]:
    """把拖进来的东西分成 图片 / 视频 / 文件 / 文件夹(保持原来的顺序)。"""
    out: dict[str, list[str]] = {"images": [], "videos": [], "files": [], "folders": []}
    for p in paths:
        if os.path.isdir(p):
            out["folders"].append(p)
        elif imaging.is_image_path(p):
            out["images"].append(p)
        elif file_ext(p) in VIDEO_EXTS:
            out["videos"].append(p)
        elif os.path.isfile(p):
            out["files"].append(p)
    return out


def drop_summary(paths: list[str], images: int = 0) -> str:
    """「3 张图片 · 1 个视频 · 2 个文件」"""
    c = classify_paths(paths)
    parts = []
    n_img = len(c["images"]) + images
    if n_img:
        parts.append(f"{n_img} 张图片")
    if c["videos"]:
        parts.append(f"{len(c['videos'])} 个视频")
    if c["files"]:
        parts.append(f"{len(c['files'])} 个文件")
    if c["folders"]:
        parts.append(f"{len(c['folders'])} 个文件夹(自动打包)")
    return " · ".join(parts)


class UxMixin:
    """快捷操作条、拖拽发送、置顶。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_ux(self) -> None:
        self.drop_confirm = False                # 拖进来的图片先弹预览确认(默认直接发)
        self.hover_bar = HoverBar(self.chat_panel)
        self.hover_bar.act.connect(self._hover_act)
        self.hover_bar.entered.connect(self._hover_keep)
        self.hover_bar.left.connect(self._hover_leave_soon)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(260)
        self._hover_timer.timeout.connect(self.hide_hover_bar)
        self.msg_area.verticalScrollBar().valueChanged.connect(lambda _v: self.hide_hover_bar())
        self.drop_overlay = DropOverlay(self.chat_panel)
        self.input.drop_handler = self
        # 动图:只让看得见的那几张动(滚动、切换会话、窗口藏起来时重新判断,最多每 80 毫秒一次)
        self._gif_timer = QTimer(self)
        self._gif_timer.setSingleShot(True)
        self._gif_timer.setInterval(80)
        self._gif_timer.timeout.connect(self.sync_gifs)
        self.msg_area.verticalScrollBar().valueChanged.connect(lambda _v: self.schedule_gif_sync())
        self.msg_area.resized.connect(self.schedule_gif_sync)

    def _restore_ux(self, acct: dict, st: dict) -> None:
        self.drop_confirm = bool(st.get("drop_confirm", False))
        self.act_drop_confirm.setChecked(self.drop_confirm)

    def _settings_ux(self) -> dict:
        return {"drop_confirm": self.drop_confirm}

    def _tick_ux(self, now: float) -> None:
        self.sync_gifs()                                    # 每秒兜底一次(比如窗口刚被藏起来)

    def _winstate_ux(self) -> None:
        self.sync_gifs()

    def schedule_gif_sync(self) -> None:
        if not self._gif_timer.isActive():
            self._gif_timer.start()

    def sync_gifs(self) -> None:
        """聊天区里的动图与气泡边缘特效:在视野里的播放,看不见的暂停;窗口最小化 / 藏起来时全部暂停。"""
        vp = self.msg_area.viewport()
        shown = self.window_visible() and not self.isMinimized()
        view = vp.rect()
        isl = getattr(self, "island", None)
        if isl is not None:
            isl.set_active(shown)
        for lab in list(GIF_LABELS):
            try:
                if not vp.isAncestorOf(lab):                # 大图窗口、匿名纸条预览里的:它们自己管
                    continue
                on = shown and lab.isVisible() and QRect(lab.mapTo(vp, QPoint(0, 0)), lab.size()).intersects(view)
                lab.set_active(on)
            except RuntimeError:                            # 气泡已经删掉了
                GIF_LABELS.discard(lab)
        for bub in list(AURA_BUBBLES):
            try:
                if not vp.isAncestorOf(bub):
                    continue
                on = shown and bub.isVisible() and QRect(bub.mapTo(vp, QPoint(0, 0)), bub.size()).intersects(view)
                bub.set_aura_active(on)
            except RuntimeError:
                AURA_BUBBLES.discard(bub)

    def _place_ux(self) -> None:
        if self.drop_overlay.isVisible():
            self.drop_overlay.setGeometry(self.chat_panel.rect())
            self.drop_overlay.raise_()
        if self.hover_bar.isVisible():
            self.hover_bar.raise_()
        if getattr(self, "jump_btn", None) is not None and self.jump_btn.isVisible():
            self._sync_jump_btn()
        isl = getattr(self, "island", None)
        if isl is not None:
            isl._retarget()
            isl.place()

    # ---------------------------------------------------------------- 快捷操作条
    def hover_actions(self, m: Msg) -> list[str]:
        """这条消息能用哪些快捷按钮。"""
        if m.system or m.gone:
            return []
        conv = self.current
        keys = ["react:👍", "react:❤️", "react:😂", "reply"]
        if m.img is None and not m.file and not m.card and m.text and not m.burn:
            keys.append("copy")
        if conv is not None and conv.kind != "self" and not m.burn:
            keys.append("fav")
        keys += ["delete", "more"]
        return keys

    def hover_bubble(self, b) -> None:
        """鼠标移到某条消息上:在气泡旁边(别人的在右边,自己的在左边)浮出操作条。"""
        if self.selecting is not None or getattr(self, "editing", None) is not None:
            return
        keys = self.hover_actions(b.msg)
        if not keys:
            return
        self._hover_timer.stop()
        bar = self.hover_bar
        w = bar.set_actions(keys)
        target = b.content_widget() or b
        try:
            tl = target.mapTo(self.chat_panel, QPoint(0, 0))
            tw = target.width()
        except Exception:                                  # noqa: BLE001  控件已经被删
            return
        x = tl.x() - w - 6 if b.msg.mine else tl.x() + tw + 6
        x = max(8, min(x, self.chat_panel.width() - w - 8))
        y = max(HEADER_H + 4, tl.y() - 2)
        bar.bubble = b
        bar.move(int(x), int(y))
        bar.show()                                        # 2.1.1:不再淡入(淡入用的透明度效果在点击时可能导致闪退)
        bar.raise_()

    def unhover_bubble(self, b) -> None:
        if self.hover_bar.bubble is b:
            self._hover_timer.start()

    def _hover_keep(self) -> None:
        self._hover_timer.stop()

    def _hover_leave_soon(self) -> None:
        self._hover_timer.start()

    def hide_hover_bar(self) -> None:
        self._hover_timer.stop()
        self.hover_bar.hide()
        self.hover_bar.bubble = None

    def _hover_act(self, key: str) -> None:
        b = self.hover_bar.bubble
        if b is None:
            return
        m = b.msg
        pos = self.hover_bar.mapToGlobal(QPoint(0, self.hover_bar.height() + 4))
        self.hide_hover_bar()
        self.quick_action(m, key, pos)

    def quick_action(self, m: Msg, key: str, pos=None) -> None:
        if m.gone:
            return
        if key.startswith("react:"):
            self.react(m, key[6:])
            return
        if key == "reply":
            self.start_reply(m)
        elif key == "copy":
            QApplication.clipboard().setText(m.text)
            if pos is not None:
                QToolTip.showText(pos, "已复制")
        elif key == "fav":
            self.favorite(m)
        elif key == "delete":
            conv = self._conv_of(m)
            if conv is None:
                return
            where = "从收藏中删除这条?" if conv.kind == "self" else "删除这条消息?"
            if ask(self, where, "只删除你这台电脑上的,对方那边不受影响。", "删除", danger=True):
                self.delete_local(m)
        elif key == "more":
            self.bubble_menu(m, pos if pos is not None else QCursor.pos())

    # ---------------------------------------------------------------- 拖拽直接发送
    @staticmethod
    def is_send_drop(mime) -> bool:
        """拖进来的是本机文件 / 文件夹,或者(从浏览器拖来的)图片。"""
        return bool(drop_paths(mime)) or (mime.hasImage() and not mime.hasUrls())

    def drop_target_info(self, mime) -> tuple[str, str, bool]:
        conv = self.current
        paths = drop_paths(mime)[:MAX_DROP]
        detail = drop_summary(paths, 0 if paths else 1)
        if conv is None or not self.input.isEnabled():
            return "现在不能发送", "当前会话无法发送消息(对方离线,或你已退出大厅)", False
        where = "我的收藏" if conv.kind == "self" else conv.title
        return f"松开发送到「{where}」", detail + ("" if conv.kind == "self" else "\n图片直接发图,视频和文件发文件卡片"), True

    def dragEnterEvent(self, e) -> None:
        mime = e.mimeData()
        if not self.is_send_drop(mime):
            e.ignore()
            return
        e.acceptProposedAction()
        title, detail, ok = self.drop_target_info(mime)
        self.drop_overlay.set_info(title, detail, ok)
        self.drop_overlay.setGeometry(self.chat_panel.rect())
        self.drop_overlay.show()
        self.drop_overlay.raise_()
        self.hide_hover_bar()

    def dragMoveEvent(self, e) -> None:
        if self.is_send_drop(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e) -> None:
        self.drop_overlay.hide()

    def dropEvent(self, e) -> None:
        self.drop_overlay.hide()
        mime = e.mimeData()
        paths = drop_paths(mime)[:MAX_DROP]
        imgs = None if paths else images_from_mime(mime)
        if not paths and not imgs:
            return
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.send_dropped(paths, imgs))

    def _load_drop_image(self, path: str):
        return imaging.load_image_path(path)              # 动图保持会动;超过 8MB 的动图返回 None,改当文件发

    def send_dropped(self, paths: list[str], images=None, conv: Conv | None = None) -> int:
        """拖进来的东西按顺序直接发出去:图片发图片,视频和其它文件发文件,文件夹打包发。返回发了几样。"""
        conv = conv or self.current
        if conv is None or not self.input.isEnabled():
            info(self, "现在不能发送", "当前会话无法发送消息(对方离线,或你已退出大厅)。")
            return 0
        paths = list(paths or [])[:MAX_DROP]
        if self.drop_confirm:                              # 用户选了"先确认":走原来的流程
            c = classify_paths(paths)
            for f in c["folders"][:5]:
                self.send_folder(f, conv)
            if c["videos"] or c["files"]:
                self.send_files(c["videos"] + c["files"])
            pics, big = [], []
            for p in c["images"]:
                it = self._load_drop_image(p)
                (pics if it is not None else big).append(it if it is not None else p)
            if big:
                self.send_files([p for p in big if os.path.isfile(p)])     # 超过 8MB 的动图当文件发
            pics += list(images or [])
            if pics:
                self.handle_images(pics)
            return len(paths) + len(images or [])
        sent = 0
        files: list[str] = []
        bad: list[str] = []

        def flush():
            nonlocal sent
            if files:
                self._send_paths(conv, list(files))
                sent += len(files)
                files.clear()

        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            for p in paths:
                if os.path.isdir(p):
                    flush()
                    self.send_folder(p, conv)
                    sent += 1
                elif imaging.is_image_path(p):
                    flush()
                    if self._send_one_image(conv, self._load_drop_image(p)):
                        sent += 1
                    elif os.path.isfile(p):
                        files.append(p)                    # 读不出来的图片:当普通文件发
                elif os.path.isfile(p):
                    files.append(p)
                else:
                    bad.append(os.path.basename(p))
            flush()
            for img in images or []:
                if self._send_one_image(conv, img):
                    sent += 1
        finally:
            QApplication.restoreOverrideCursor()
        if bad:
            self._system(conv, "这些没有发出去(找不到或无法读取):" + "、".join(bad[:5]))
        return sent

    def _send_one_image(self, conv: Conv, img) -> bool:
        if img is None or img.isNull():
            return False
        enc = imaging.encode_any(img)
        if not enc:
            return False
        data, mime, w, h = enc
        self.send_image_data(conv, data, mime, w, h)
        return True

    # ---------------------------------------------------------------- 会话置顶
    def set_pinned(self, conv: Conv, on: bool) -> None:
        conv.pinned = bool(on)
        if on:
            if conv.key in self.pinned_keys:
                self.pinned_keys.remove(conv.key)
            self.pinned_keys.insert(0, conv.key)          # 最新置顶的排最上面
        elif conv.key in self.pinned_keys:
            self.pinned_keys.remove(conv.key)
        self._refresh_conv_list()
