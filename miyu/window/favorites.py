"""
密语 · 我的收藏:自己的会话,随手记、收藏消息、存文件位置,只在本机。
"""
from __future__ import annotations

import os
import time
import uuid

from PySide6.QtCore import QTimer

from .. import storage
from ..core import MAX_TEXT
from ..dialogs import info
from ..widgets import Conv, Msg


class FavoritesMixin:
    """我的收藏。"""

    # ---------------------------------------------------------------- 我的收藏
    SELF_INTRO = "这是你自己的会话:随手记点东西、存文件,或者在别的会话里右键消息 →「收藏」,就会存到这里。\n内容只在这台电脑上,不会发给任何人。"

    def _init_self_conv(self) -> None:
        conv = Conv("self", "self", "我的收藏")
        self.convs["self"] = conv
        self._favs_dirty = False
        intro = self.SELF_INTRO
        if not self.remember:
            intro += "\n注意:没开「记住登录」,关掉软件后这里也会清空。"
        self._system(conv, intro)
        if self.remember and self.store is not None:
            for d in self.store.load_favs():
                kw = storage.msg_kwargs(d)
                if kw is None:
                    continue
                m = Msg(str(d.get("text", "")), **kw)
                m.mine = True
                m.time = float(d.get("time") or time.time())
                m.edited = bool(d.get("edited"))
                self._register_local_file(m)
                conv.messages.append(m)
            last = next((x for x in reversed(conv.messages) if not x.system), None)
            if last is not None:
                conv.last_time = last.time
                conv.preview = self._preview_of(last, conv)
        self._favs_dirty = False

    def _register_local_file(self, m: Msg) -> None:
        if m.file and m.file.get("local"):
            self.transfers[m.file["fid"]] = {"mine": True, "local": True, "path": m.file.get("path", ""),
                                             "up": {}, "up_done": 0}

    @property
    def self_conv(self) -> Conv:
        return self.convs["self"]

    def save_favs(self, force: bool = False) -> bool:
        if not self.remember or self.store is None or not (self._favs_dirty or force):
            return False
        items = [x for x in (storage.msg_to_dict(m, storage.FAV_IMAGE_MAX) for m in self.self_conv.messages) if x]
        if self.store.save_favs(items):
            self._favs_dirty = False
            return True
        return False

    def _self_add(self, m: Msg) -> None:
        m.mine = True
        m.sender = self.me.get("id", "")
        m.nick = self.me.get("nick", "")
        self._register_local_file(m)
        self._add_message(self.self_conv, m, count_unread=False)
        self._favs_dirty = True

    def self_note(self, text: str) -> None:
        skin = self.current_skin() if hasattr(self, "current_skin") else None
        aura = (self.pet_growth.aura or None) if hasattr(self, "pet_growth") else None
        self._self_add(Msg(text[:MAX_TEXT], skin=skin, aura=aura))
        self.input.clear()
        self.cancel_reply()
        if self.fun["pet"]:
            self.pet.celebrate()

    def self_image(self, data: bytes, mime: str, w: int, h: int, sticker: bool = False) -> None:
        self._self_add(Msg("", img=data, mime=mime, w=w, h=h, sticker=sticker))

    def self_files(self, paths: list[str]) -> None:
        """往收藏里存文件 / 文件夹:只记下位置,文件本身不复制、不上传。"""
        for path in paths[:20]:
            if not os.path.exists(path):
                continue
            is_dir = os.path.isdir(path)
            try:
                size = 0 if is_dir else os.path.getsize(path)
            except OSError:
                size = 0
            name = os.path.basename(os.path.normpath(path)) or path
            f = {"fid": uuid.uuid4().hex, "name": name, "size": size, "local": True, "path": path}
            if is_dir:
                f["dir"] = True
            self._self_add(Msg("", file=f))

    def favorite(self, m: Msg) -> None:
        """在别的会话里收藏一条消息。"""
        conv = self._conv_of(m)
        if conv is None or m.system or m.burn or m.gone:
            return
        where = {"lobby": "公开大厅", "dm": f"和{conv.title}的私聊"}.get(conv.kind, conv.title)
        fav = {"from": "我" if m.mine else m.nick, "where": where, "time": m.time, "conv": conv.key, "mid": m.mid}
        if m.file:
            tr = self.transfers.get(m.file["fid"], {})
            path = tr.get("path", "")
            if not path or not os.path.exists(path):
                info(self, "先下载再收藏", "收藏文件时记下的是它在你电脑上的位置。先把文件下载下来,再收藏。")
                return
            f = {"fid": uuid.uuid4().hex, "name": os.path.basename(os.path.normpath(path)),
                 "size": 0 if os.path.isdir(path) else os.path.getsize(path), "local": True, "path": path}
            if os.path.isdir(path):
                f["dir"] = True
            new = Msg("", file=f)
        elif m.img is not None:
            new = Msg("", img=m.img, mime=m.mime, w=m.w, h=m.h, sticker=m.sticker)
        elif m.card:
            new = Msg(self._body_of(m) or "[卡片]")
        else:
            new = Msg(m.text)
        new.fav = fav
        self._self_add(new)
        if self.pet_away is None and self.fun["pet"]:
            self.pet.say("收藏好啦 ⭐", 1.6)
        self.self_conv.unread += 1 if self.current_key != "self" else 0
        self.conv_list.viewport().update()

    def goto_original(self, m: Msg) -> None:
        fav = m.fav or {}
        conv = self.convs.get(fav.get("conv", ""))
        mid = fav.get("mid", "")
        if conv is None or not self.ensure_loaded(conv, mid):        # 很早的消息会从数据库读出来
            info(self, "原消息已经不在了", "可能被撤回、清空、超过了保留期限,或者软件重启过(没开保存聊天记录)。")
            return
        self.select_conv(conv.key)
        QTimer.singleShot(0, lambda: self.jump_to(mid))
