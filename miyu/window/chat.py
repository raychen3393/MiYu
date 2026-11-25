"""
密语 · 聊天功能
编辑消息、表情回应、多选和转发、戳一戳、群公告和置顶、群改名、匿名纸条、自定义头像、群排行榜。
"""
from __future__ import annotations

import base64
import datetime
import os
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QStandardPaths, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .. import imaging, theme, video
from ..core import MAX_NICK, MAX_TEXT, clean_nick
from ..dialogs import Dialog, MultiPromptDialog, TextDialog, ask, info, prompt
from ..icons import icon
from ..theme import T
from ..ui import AVATARS, HEADER_H, button, clear_avatar_cache, label, make_menu, popup
from ..widgets import ClickLabel, Conv, Msg
from .anon import AnonNoteDialog


POKE_GAP = 3.0                    # 同一个人 3 秒内的戳一戳只算一次
MAX_PINS = 5
REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🎉", "🔥", "👏"]
AVATAR_MAX = 64 * 1024


def week_id(day: datetime.date | None = None) -> str:
    y, w, _ = (day or datetime.date.today()).isocalendar()
    return f"{y}-W{w:02d}"


class ForwardDialog(Dialog):
    """选择转发到哪个会话。items = [(key, 标题, 说明)]"""

    def __init__(self, parent, items: list, count: int) -> None:
        super().__init__(parent, "转发")
        self.setFixedWidth(360)
        self.chosen: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(8)
        lay.addWidget(label(f"转发 {count} 条消息到…", "dialogTitle"))
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        for key, title, sub in items:
            b = button(f"{title}    {sub}", "", lambda _=False, k=key: self._pick(k))
            b.setMinimumHeight(38)
            bl.addWidget(b)
        bl.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(box)
        area.setFixedHeight(min(360, 46 * len(items) + 10))
        lay.addWidget(area)
        lay.addWidget(button("取消", "link", self.reject))

    def _pick(self, key: str) -> None:
        self.chosen = key
        self.accept()


class ChatMixin:
    """编辑、回应、转发、戳一戳、公告置顶、群改名、匿名纸条、头像、排行榜。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_chat(self) -> None:
        self.editing: Msg | None = None
        self.selecting: set | None = None
        self._poke_last: dict[str, float] = {}
        self._poke_sent = 0.0
        self.rank: dict[str, dict] = {}          # 群排行榜:会话 → 周 → 人 → 计数
        self.my_avatar: tuple[bytes, str] | None = None
        self.avatar_from: set[str] = set()       # 收到过谁的头像
        self._saved_groups: dict = {}
        # 群公告 / 置顶 条
        bar = QFrame(self.chat_panel)
        bar.setObjectName("noticeBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 4, 6, 4)
        bl.setSpacing(6)
        self.notice_label = ClickLabel()
        self.notice_label.setObjectName("noticeText")
        self.notice_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.notice_label.clicked.connect(self.show_notice)
        bl.addWidget(self.notice_label, 1)
        self.pins_btn = button("", "link", self.show_pins_menu)
        bl.addWidget(self.pins_btn)
        bar.setVisible(False)
        self.notice_bar = bar
        self.chat_panel.notice = bar
        # 多选栏
        bar = QFrame(self.chat_panel)
        bar.setObjectName("noticeBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 4, 8, 4)
        bl.setSpacing(6)
        self.select_label = label("", "noticeText")
        bl.addWidget(self.select_label, 1)
        bl.addWidget(button("转发", "link", self.forward_selected))
        bl.addWidget(button("收藏", "link", self.fav_selected))
        bl.addWidget(button("删除", "link", self.delete_selected))
        bl.addWidget(button("取消", "link", self.exit_select))
        bar.setVisible(False)
        self.select_bar = bar

    def _restore_chat(self, acct: dict, st: dict) -> None:
        groups = acct.get("groups")
        self._saved_groups = groups if isinstance(groups, dict) else {}
        if isinstance(acct.get("rank"), dict):
            self.rank = {k: v for k, v in acct["rank"].items() if isinstance(v, dict)}
        av = acct.get("avatar")
        if isinstance(av, dict) and isinstance(av.get("img"), str):
            try:
                data = base64.b64decode(av["img"])
            except Exception:
                data = b""
            if 0 < len(data) <= AVATAR_MAX:
                self.my_avatar = (data, str(av.get("mime", "image/jpeg")))
        qp = acct.get("quick_phrases")
        if isinstance(qp, list):
            self.quick_phrases = [str(x).strip()[:80] for x in qp if isinstance(x, str) and x.strip()][:30]

    def _save_chat(self) -> dict:
        groups = {}
        for key, conv in self.convs.items():
            if conv.kind in ("lobby", "room") and (conv.notice or conv.pins or conv.name_t):
                groups[key] = {"notice": conv.notice, "pins": conv.pins, "pins_t": conv.pins_t, "name_t": conv.name_t}
        d = {"groups": groups, "rank": self.rank}
        if isinstance(getattr(self, "quick_phrases", None), list):
            d["quick_phrases"] = list(self.quick_phrases)[:30]
        if self.my_avatar:
            d["avatar"] = {"img": base64.b64encode(self.my_avatar[0]).decode("ascii"), "mime": self.my_avatar[1]}
        return d

    def _tick_chat(self, now: float) -> None:
        if self._save_tick % 60 == 1:
            self._tick_rank()

    def _peer_online_chat(self, pid: str) -> None:
        if self.my_avatar:                       # 有人上线:把我的头像发给他
            self._send_avatar(pid)

    def _place_chat(self) -> None:
        if self.select_bar.isVisible():
            top = HEADER_H + 6 + (44 if self.notice_bar.isVisible() else 0) + (48 if self.search_bar.isVisible() else 0)
            self.select_bar.setGeometry(16, top, self.chat_panel.width() - 32, 40)
            self.select_bar.raise_()

    # ---------------------------------------------------------------- 编辑消息
    def start_edit(self, m: Msg) -> None:
        self.cancel_reply()
        self.editing = m
        self.reply_text.setText("编辑消息(Enter 保存,Esc 取消)")
        self.reply_icon.setPixmap(self._icon_pm("pencil"))
        self.reply_bar.setVisible(True)
        self.input.setPlainText(m.text)
        self.input.setFocus()

    def _icon_pm(self, name: str):
        return icon(name, T["accent"], 16).pixmap(16, 16)

    def cancel_edit(self) -> None:
        if self.editing is None:
            return
        self.editing = None
        self.reply_bar.setVisible(False)
        self.reply_icon.setPixmap(self._icon_pm("reply"))
        self.input.clear()

    def finish_edit(self, text: str) -> bool:
        m = self.editing
        conv = self._conv_of(m) if m is not None else None
        self.editing = None
        self.reply_bar.setVisible(False)
        self.reply_icon.setPixmap(self._icon_pm("reply"))
        if m is None or conv is None or m.gone:
            return False
        text = text[:MAX_TEXT]
        if text == m.text:
            self.input.clear()
            return True
        if conv.kind == "self":
            self._apply_edit(conv, m, text)
            self.input.clear()
            return True
        scope, target = self.scope_target(conv)
        self.core.send_event(scope, target, "edit", {"target": m.mid, "text": text})
        self._apply_edit(conv, m, text)
        self.input.clear()
        return True

    def _apply_edit(self, conv: Conv, m: Msg, text: str) -> None:
        m.text = text
        m.edited = True
        self._hist_dirty = True
        if conv.kind == "self":
            self._favs_dirty = True
        last = next((x for x in reversed(conv.messages) if not x.system), None)
        if last is m:
            conv.preview = self._preview_of(m, conv)
        if conv.key == self.current_key:
            self._render_messages(keep_scroll=True)
        self.conv_list.viewport().update()

    def _ev_edit(self, conv: Conv, d: dict, data: dict) -> None:
        mid, text = data.get("target"), data.get("text")
        if not isinstance(mid, str) or not isinstance(text, str) or not text.strip():
            return
        m = next((x for x in conv.messages if x.mid == mid and x.sender == d["peer"] and not x.system
                  and not x.burn and x.img is None and not x.file and not x.card), None)
        if m is not None:
            self._apply_edit(conv, m, text[:MAX_TEXT])

    # ---------------------------------------------------------------- 表情回应
    def react(self, m: Msg, emoji: str) -> None:
        conv = self._conv_of(m)
        if conv is None or emoji not in REACTIONS or m.system or m.gone:
            return
        me = self.me.get("id", "")
        who = m.reactions.setdefault(emoji, [])
        on = me not in who
        (who.append if on else who.remove)(me)
        if not who:
            m.reactions.pop(emoji, None)
        if conv.kind != "self":
            scope, target = self.scope_target(conv)
            self.core.send_event(scope, target, "react", {"target": m.mid, "e": emoji, "on": on})
        else:
            self._favs_dirty = True
        self._hist_dirty = True
        self._update_reactions(m)

    def _ev_react(self, conv: Conv, d: dict, data: dict) -> None:
        mid, emoji, on = data.get("target"), data.get("e"), data.get("on")
        if not isinstance(mid, str) or emoji not in REACTIONS:
            return
        m = next((x for x in conv.messages if x.mid == mid and not x.system), None)
        if m is None:
            return
        who = m.reactions.setdefault(emoji, [])
        pid = d["peer"]
        if on and pid not in who and len(who) < 200:
            who.append(pid)
        elif not on and pid in who:
            who.remove(pid)
        if not who:
            m.reactions.pop(emoji, None)
        self._hist_dirty = True
        self._update_reactions(m)

    def _reaction_names(self, pids: list) -> str:
        me = self.me.get("id", "")
        return "、".join("我" if p == me else self.peers.get(p, {}).get("nick", "?") for p in pids[:12])

    def _update_reactions(self, m: Msg) -> None:
        b = self.bubbles.get(m.mid)
        if b is not None:
            me = self.me.get("id", "")
            b.set_reactions([(e, len(w), me in w, self._reaction_names(w)) for e, w in m.reactions.items() if w])

    def _decorate_bubble(self, b, m: Msg) -> None:
        """每个气泡建好后:接上回应、多选。"""
        if m.system:
            return
        b.react.connect(self.react)
        b.select_toggled.connect(self.toggle_select)
        if m.reactions:
            self._update_reactions(m)
        b._react_prev = {e: len(w) for e, w in m.reactions.items() if w}      # 之后新增的回应才弹一下
        if self.selecting is not None:
            b.set_select(True, m.mid in self.selecting)

    def _fill_react_menu(self, menu, m: Msg) -> None:
        sub = make_menu(menu)
        sub.setTitle("回应")
        me = self.me.get("id", "")
        for e in REACTIONS:
            mine = me in m.reactions.get(e, [])
            sub.addAction(f"{e}  ✓" if mine else e, lambda e=e: self.react(m, e))
        menu.addMenu(sub)

    # ---------------------------------------------------------------- 多选 / 转发
    def enter_select(self, m: Msg | None = None) -> None:
        self.selecting = {m.mid} if m is not None else set()
        for mid, b in self.bubbles.items():
            b.set_select(True, mid in self.selecting)
        self.select_bar.setVisible(True)
        self._refresh_select()

    def exit_select(self) -> None:
        if self.selecting is None:
            return
        self.selecting = None
        for b in self.bubbles.values():
            b.set_select(False, False)
        self.select_bar.setVisible(False)

    def toggle_select(self, m: Msg) -> None:
        if self.selecting is None:
            return
        (self.selecting.discard if m.mid in self.selecting else self.selecting.add)(m.mid)
        b = self.bubbles.get(m.mid)
        if b is not None:
            b.set_select(True, m.mid in self.selecting)
        self._refresh_select()

    def _refresh_select(self) -> None:
        self.select_label.setText(f"已选 {len(self.selecting or ())} 条")
        self._hooks("place")

    def _selected(self) -> list[Msg]:
        conv = self.current
        if conv is None or not self.selecting:
            return []
        return [m for m in conv.messages if m.mid in self.selecting and not m.system and not m.gone]

    def forward_selected(self) -> None:
        msgs = self._selected()
        if msgs and self.forward(msgs):
            self.exit_select()

    def fav_selected(self) -> None:
        msgs = [m for m in self._selected() if not m.burn]
        conv = self.current
        if conv is None or conv.kind == "self" or not msgs:
            return
        for m in msgs:
            self.favorite(m)
        self.exit_select()

    def delete_selected(self) -> None:
        msgs = self._selected()
        if not msgs or not ask(self, f"删除 {len(msgs)} 条消息?", "只删除你这台电脑上的,对方那边不受影响。", "删除", danger=True):
            return
        for m in msgs:
            self.delete_local(m)
        self.exit_select()

    def _can_send_to(self, conv: Conv) -> bool:
        if conv.kind == "dm":
            return bool(self.peers.get(conv.target or "", {}).get("online"))
        if conv.kind == "lobby":
            return bool(self.me.get("lobby", True))
        return True

    def forward(self, msgs: list[Msg], target: Conv | None = None) -> bool:
        """转发。target 为空时弹出会话选择。返回是否转发了。"""
        msgs = [m for m in msgs if not m.system and not m.gone and not m.burn and not m.card]
        if not msgs:
            info(self, "没有可以转发的内容", "阅后即焚、投票、游戏这类消息不能转发。")
            return False
        if target is None:
            items = []
            for key in self._ordered_keys():
                c = self.convs[key]
                if c.key == self.current_key:
                    continue
                items.append((key, c.title, "" if self._can_send_to(c) else "(离线)"))
            dlg = ForwardDialog(self, items, len(msgs))
            if not dlg.exec() or not dlg.chosen:
                return False
            target = self.convs.get(dlg.chosen)
        if target is None:
            return False
        if not self._can_send_to(target):
            info(self, "现在发不过去", "对方不在线,或者你已退出大厅。")
            return False
        skipped = 0
        burn, self.burn_secs = self.burn_secs, 0             # 转发的内容不带阅后即焚
        try:
            for m in sorted(msgs, key=lambda x: x.time):
                if m.vid is not None:                       # 匿名纸条里的视频:存一份到临时发件箱,当普通视频发
                    path = self._outbox_copy(m.vid, (m.file or {}).get("name") or "视频.mp4")
                    if path:
                        self._send_paths(target, [path])
                    else:
                        skipped += 1
                elif m.file:
                    path = self.transfers.get(m.file.get("fid"), {}).get("path") or m.file.get("path", "")
                    if not path or not os.path.exists(path):
                        skipped += 1
                    elif os.path.isdir(path):
                        self.send_folder(path, target)
                    else:
                        self._send_paths(target, [path])
                elif m.img is not None:
                    self.send_image_data(target, m.img, m.mime, m.w, m.h, m.sticker)
                elif m.text:
                    self.send_text_to(target, m.text)
        finally:
            self.burn_secs = burn
        note = f"已转发 {len(msgs) - skipped} 条到「{target.title}」"
        if skipped:
            note += f",有 {skipped} 个文件还没下载,没法转发"
        cur = self.current
        if cur is not None:
            self._system(cur, note)
        return True

    def _outbox_copy(self, data: bytes, name: str) -> str:
        """把内容存成发件箱里的一个文件(一周后自动清掉),返回路径;失败返回空字符串。"""
        import uuid
        folder = os.path.join(self.outbox_dir(), uuid.uuid4().hex[:12])
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, os.path.basename(name) or "视频.mp4")
            with open(path, "wb") as f:
                f.write(data)
            return path
        except OSError:
            return ""

    def _ordered_keys(self) -> list[str]:
        keys = [k for k in ("lobby", "self") if k in self.convs]
        keys += [k for k in self.convs if k.startswith("room:")]
        keys += sorted((k for k in self.convs if k.startswith("dm:")), key=lambda k: -self.convs[k].last_time)
        return keys

    def send_text_to(self, conv: Conv, text: str) -> None:
        if conv.kind == "self":
            self._self_add(Msg(text))
            return
        scope, target = self.scope_target(conv)
        skin = self.current_skin()
        mid = self.core.send_text(scope, target, text, 0, skin=skin)
        if mid is None:
            return
        m = Msg(text, mid=mid, sender=self.me["id"], nick=self.me.get("nick", ""), tag=self.me.get("tag", ""),
                mine=True, skin=skin)
        self._add_message(conv, m)

    # ---------------------------------------------------------------- 戳一戳
    def shake(self) -> None:
        if not self.window_visible():
            return
        start = self.pos()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(420)
        for i, dx in enumerate((0, -10, 9, -7, 6, -4, 2, 0)):
            anim.setKeyValueAt(i / 7, QPoint(start.x() + dx, start.y()))
        anim.setEasingCurve(QEasingCurve.Type.Linear)
        anim.start()
        self._shake_anim = anim


    def poke(self, pid: str, conv: Conv | None = None) -> None:
        if not pid or pid == self.me.get("id"):
            return
        now = time.monotonic()
        if now - self._poke_sent < 2.0:
            return
        self._poke_sent = now
        conv = conv or self.open_dm(pid, select=False)
        scope, target = self.scope_target(conv)
        if conv.kind == "dm" and not self.peers.get(pid, {}).get("online"):
            info(self, "对方不在线", "对方在线时才能戳。")
            return
        self.core.send_event(scope, target, "poke", {"to": pid})
        nick = self.peers.get(pid, {}).get("nick", "对方")
        self._system(conv, f"你戳了戳 {nick}")
        self.stats["pokes"] += 1
        if conv.kind in ("lobby", "room"):
            self._rank_entry(conv, self.me.get("id", ""), self.me.get("nick", ""))["pokes"] += 1

    def _ev_poke(self, conv: Conv, d: dict, data: dict) -> None:
        me = self.me.get("id")
        to = data.get("to") if conv.kind != "dm" else me
        if not isinstance(to, str):
            return
        now = time.monotonic()
        if now - self._poke_last.get(d["peer"], -1e9) < POKE_GAP:
            return
        self._poke_last[d["peer"]] = now
        if conv.kind in ("lobby", "room"):
            self._rank_entry(conv, d["peer"], d["nick"])["pokes"] += 1
        if to == me:
            self._system(conv, f"{d['nick']} 戳了戳你")
            if self.window_visible():
                self.shake()
                self.pet.perk()
                self.pet.say("哎呀!", 1.2)
            self._maybe_notify(conv, conv.key == self.current_key, force=True)
        else:
            who = self.peers.get(to, {}).get("nick", "某人")
            self._system(conv, f"{d['nick']} 戳了戳 {who}")

    # ---------------------------------------------------------------- 群公告 / 置顶
    def _apply_group_state(self, conv: Conv) -> None:
        g = getattr(self, "_saved_groups", {}).get(conv.key)
        if isinstance(g, dict):
            if isinstance(g.get("notice"), dict):
                conv.notice = g["notice"]
            if isinstance(g.get("pins"), list):
                conv.pins = [p for p in g["pins"] if isinstance(p, dict)][:MAX_PINS]
                conv.pins_t = float(g.get("pins_t") or 0)
            if type(g.get("name_t")) in (int, float):
                conv.name_t = float(g["name_t"])

    def refresh_notice_bar(self) -> None:
        conv = self.current
        show = conv is not None and conv.kind in ("lobby", "room") and bool(conv.notice or conv.pins)
        self.notice_bar.setVisible(show)
        if show:
            if conv.notice:
                text = conv.notice.get("text", "").replace("\n", "  ")
                self.notice_label.setText(self.notice_label.fontMetrics().elidedText(
                    f"📢  {text}", Qt.TextElideMode.ElideRight, max(120, self.chat_panel.width() - 180)))
                self.notice_label.setToolTip(f"{conv.notice.get('nick', '')} 发布的群公告,点击查看")
            else:
                self.notice_label.setText("📌  置顶消息")
            self.pins_btn.setText(f"📌 {len(conv.pins)}" if conv.pins else "")
            self.pins_btn.setVisible(bool(conv.pins))
        top = 6 + (44 if show else 0)
        self.msg_layout.setContentsMargins(0, 64 + top, 0, self.msg_layout.contentsMargins().bottom())
        self.chat_panel.place_overlays()

    def edit_notice(self, conv: Conv | None = None) -> None:
        conv = conv or self.current
        if conv is None or conv.kind not in ("lobby", "room"):
            return
        cur = (conv.notice or {}).get("text", "")
        dlg = MultiPromptDialog(self, "群公告", "群里所有人都会看到,新进群的人也会收到。", cur,
                                  "例如:每周五晚上 8 点开黑", "发布", 500, extra="删除公告" if cur else "")
        if not dlg.exec():
            return
        text = "" if dlg.extra_clicked else dlg.value
        if not dlg.extra_clicked and not text:
            return
        notice = {"text": text, "nick": self.me.get("nick", ""), "by": self.me.get("id", ""), "time": time.time()}
        conv.notice = notice if text else None
        conv.notice_t = notice["time"]
        scope, target = self.scope_target(conv)
        self.core.send_event(scope, target, "notice", notice)
        self._system(conv, "你发布了群公告" if text else "你删除了群公告")
        self.refresh_notice_bar()

    def show_notice(self) -> None:
        conv = self.current
        if conv is None:
            return
        if not conv.notice:
            self.show_pins_menu()
            return
        n = conv.notice
        when = time.strftime("%m-%d %H:%M", time.localtime(n.get("time", 0)))
        dlg = TextDialog(self, "群公告", [("", n.get("text", ""))], f"{n.get('nick', '')} 发布于 {when}",
                         extra=("修改", "link"))
        dlg.exec()
        if dlg.extra_clicked:
            self.edit_notice(conv)

    def toggle_pin(self, m: Msg) -> None:
        conv = self._conv_of(m)
        if conv is None or conv.kind not in ("lobby", "room"):
            return
        if any(p.get("mid") == m.mid for p in conv.pins):
            conv.pins = [p for p in conv.pins if p.get("mid") != m.mid]
            what = "取消置顶了一条消息"
        else:
            conv.pins = ([{"mid": m.mid, "nick": self.me.get("nick", "") if m.mine else m.nick,
                           "preview": self._body_of(m)[:60]}] + conv.pins)[:MAX_PINS]
            what = "置顶了一条消息"
        conv.pins_t = time.time()
        scope, target = self.scope_target(conv)
        self.core.send_event(scope, target, "pins", {"items": conv.pins, "time": conv.pins_t})
        self._system(conv, f"你{what}")
        self.refresh_notice_bar()

    def show_pins_menu(self) -> None:
        conv = self.current
        if conv is None or not conv.pins:
            return
        m = make_menu(self)
        for p in conv.pins:
            m.addAction(f"{p.get('nick', '')}:{p.get('preview', '')}"[:50], lambda mid=p.get("mid"): self.jump_to(mid))
        popup(m, self.pins_btn.mapToGlobal(QPoint(0, self.pins_btn.height())))

    def _ev_notice(self, conv: Conv, d: dict, data: dict) -> None:
        t = data.get("time")
        text = data.get("text")
        if conv.kind == "dm" or type(t) not in (int, float) or not isinstance(text, str):
            return
        if t <= conv.notice_t:
            return
        conv.notice_t = t
        conv.notice = {"text": text[:500], "nick": d["nick"], "by": d["peer"], "time": t} if text.strip() else None
        if not data.get("sync"):
            self._system(conv, f"{d['nick']} 更新了群公告" if text.strip() else f"{d['nick']} 删除了群公告")
        if conv.key == self.current_key:
            self.refresh_notice_bar()

    def _ev_pins(self, conv: Conv, d: dict, data: dict) -> None:
        t, items = data.get("time"), data.get("items")
        if conv.kind == "dm" or type(t) not in (int, float) or not isinstance(items, list) or t <= conv.pins_t:
            return
        clean = []
        for p in items[:MAX_PINS]:
            if isinstance(p, dict) and isinstance(p.get("mid"), str):
                clean.append({"mid": p["mid"][:64], "nick": str(p.get("nick", ""))[:20],
                              "preview": str(p.get("preview", ""))[:60]})
        conv.pins, conv.pins_t = clean, t
        if not data.get("sync"):
            self._system(conv, f"{d['nick']} 更新了置顶消息")
        if conv.key == self.current_key:
            self.refresh_notice_bar()

    def sync_group_to(self, conv: Conv, pid: str) -> None:
        """有人新进群 / 上线:把群公告、置顶、我投过的票发给他。"""
        scope, target = self.scope_target(conv)
        if conv.kind == "room" and conv.name_t:
            self.core.send_event(scope, target, "room_name", {"name": conv.title, "time": conv.name_t, "sync": True},
                                 to=pid)
        if conv.notice:
            self.core.send_event(scope, target, "notice", {**conv.notice, "sync": True}, to=pid)
        if conv.pins:
            self.core.send_event(scope, target, "pins", {"items": conv.pins, "time": conv.pins_t, "sync": True}, to=pid)
        me = self.me.get("id")
        week = time.time() - 3 * 86400
        n = 0
        for m in reversed(conv.messages):
            if n >= 20 or m.time < week:
                break
            if m.card and m.card.get("type") == "poll" and me in self.votes.get(m.mid, {}):
                self.core.send_event(scope, target, "vote", {"poll": m.mid, "c": self.votes[m.mid][me]}, to=pid)
                n += 1
        self._hooks("group_sync", conv, pid)          # 其它模块(宠物排行榜……)也要给新来的人同步东西

    # ---------------------------------------------------------------- 匿名纸条
    def send_anon_note(self) -> None:
        conv = self._can_send()
        if conv is None or conv.kind == "dm":
            return
        dlg = AnonNoteDialog(self)
        if not dlg.exec():
            return
        self.send_anon_to(conv, dlg.text, dlg.media)

    def send_anon_to(self, conv: Conv, text: str, media: dict | None = None) -> str | None:
        """扔一张匿名纸条(可以夹表情包 / 图片 / 动图 / 视频)。成功返回纸条 id。"""
        scope, target = self.scope_target(conv)
        nid = self.core.send_anon(scope, target, text, media)
        if nid is None:
            why = getattr(self.core, "anon_error", "")
            if why == "old":
                info(self, "暂时发不了带图片 / 视频的纸条", "群里至少要有另外 2 个人用的是 2.1 以上的版本,"
                     "附件才能在大家之间转交。等大家更新后再试,或者先只发文字。")
            elif why == "few" or not why:
                info(self, "人太少了", "群里至少要有 3 个人在线(算上你)才能匿名,不然对方一猜就知道是你。")
            else:
                info(self, "纸条没扔出去", why)
            return None
        m = Msg(text, mid=nid, sender=self.me["id"], nick="匿名纸条", mine=True, anon=True)
        if media and media.get("k") in ("img", "stk"):
            m.img, m.mime = bytes(media["data"]), media["mime"]
            m.w, m.h, m.sticker = int(media.get("w") or 0), int(media.get("h") or 0), media["k"] == "stk"
        elif media and media.get("k") == "vid":
            m.vid = bytes(media["data"])
            f = {"fid": nid, "name": media.get("name") or "匿名视频.mp4", "size": len(m.vid), "anon": True,
                 "probed": True, "dur": int(media.get("dur") or 0), "vw": int(media.get("w") or 0),
                 "vh": int(media.get("h") or 0)}
            if media.get("thumb"):
                f["thumb"] = video.b64(media["thumb"])
            m.file = f
        self._add_message(conv, m)
        self._sent_fx()
        return nid

    # ---------------------------------------------------------------- 自定义头像
    def _fill_avatar_menu(self, menu) -> None:
        sub = make_menu(menu)
        sub.setTitle("我的头像")
        sub.addAction("选择图片…", self.choose_avatar)
        sub.addAction("用宠物当头像", self.use_pet_avatar)
        act = sub.addAction("恢复默认头像", lambda: self.set_avatar(None))
        act.setEnabled(self.my_avatar is not None)
        menu.addMenu(sub)

    def choose_avatar(self) -> None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        path, _ = QFileDialog.getOpenFileName(self, "选择头像图片", folder, imaging.IMAGE_FILTER)
        if not path:
            return
        res = imaging.encode_avatar(imaging.load_file(path))
        if not res:
            info(self, "这张图片用不了", "换一张试试(支持 PNG、JPG、GIF、BMP、WebP)。")
            return
        self.set_avatar(res)

    def use_pet_avatar(self) -> None:
        if not self.fun.get("pet"):
            info(self, "还没有宠物", "先在「趣味互动」里选一只宠物。")
            return
        pm = QPixmap(192, 192)
        pm.fill(QColor("#FFE9C7") if not theme.is_dark() else QColor("#3A3F5C"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pet = self.pet
        p.scale(2.2, 2.2)
        p.translate(43.6 - (pet.W - pet.BOX + 55), 66 - pet.EDGE)
        pet._paint_pet(p, time.monotonic(), "happy")
        p.end()
        res = imaging.encode_avatar(pm.toImage())
        if res:
            self.set_avatar(res)

    def set_avatar(self, res: tuple | None) -> None:
        """换头像并告诉所有在线的人。res = (图片字节, mime) 或 None(恢复默认)。"""
        if res is not None and len(res[0]) > AVATAR_MAX:
            return
        self.my_avatar = res
        self._sync_my_avatar()
        for pid, p in self.peers.items():
            if p.get("online"):
                self._send_avatar(pid)
        self._refresh_self()
        self._after_avatar()

    def _sync_my_avatar(self) -> None:
        me = self.me.get("id")
        if not me:
            return
        img = imaging.decode(self.my_avatar[0]) if self.my_avatar else None
        if img is not None:
            AVATARS[me] = img
        else:
            AVATARS.pop(me, None)
        clear_avatar_cache()

    def _send_avatar(self, pid: str) -> None:
        if self.my_avatar:
            self.core.send_event("dm", pid, "avatar", {"img": base64.b64encode(self.my_avatar[0]).decode("ascii"),
                                                       "mime": self.my_avatar[1]})
        else:
            self.core.send_event("dm", pid, "avatar", {"img": ""})

    def _ev_avatar(self, d: dict, data: dict) -> None:
        pid, raw = d["peer"], data.get("img")
        if not isinstance(raw, str):
            return
        if not raw:
            AVATARS.pop(pid, None)
            self.avatar_from.discard(pid)
        else:
            try:
                blob = base64.b64decode(raw, validate=True)
            except Exception:
                return
            if not (0 < len(blob) <= AVATAR_MAX):
                return
            img = imaging.decode(blob)
            if img is None:
                return
            AVATARS[pid] = img
            self.avatar_from.add(pid)
        clear_avatar_cache()
        self._after_avatar()

    def _after_avatar(self) -> None:
        self.conv_list.viewport().update()
        self.member_list.viewport().update()
        self._refresh_header()
        if self.current is not None:
            self._render_messages(keep_scroll=True)

    # ---------------------------------------------------------------- 群排行榜
    def rank_count(self, conv: Conv, m: Msg, day: datetime.date | None = None) -> None:
        if conv.kind not in ("lobby", "room") or m.system or m.anon:
            return
        pid = self.me.get("id", "") if m.mine else m.sender
        nick = self.me.get("nick", "") if m.mine else m.nick
        e = self._rank_entry(conv, pid, nick, day)
        e["msgs"] += 1
        if m.img is not None:
            e["imgs"] += 1

    def _rank_entry(self, conv: Conv, pid: str, nick: str, day: datetime.date | None = None) -> dict:
        wk = self.rank.setdefault(conv.key, {}).setdefault(week_id(day), {})
        e = wk.setdefault(pid, {"nick": nick, "msgs": 0, "imgs": 0, "pokes": 0})
        e["nick"] = nick or e["nick"]
        return e

    def rank_text(self, conv: Conv, wk: str) -> str:
        data = self.rank.get(conv.key, {}).get(wk, {})
        lines = []
        for key, title, unit in (("msgs", "💬 话痨榜", "条"), ("imgs", "🖼 斗图榜", "张"), ("pokes", "👉 戳戳榜", "次")):
            top = sorted(((e.get(key, 0), e.get("nick", "?")) for e in data.values() if e.get(key, 0) > 0),
                         reverse=True)[:3]
            if top:
                lines.append(title + ":" + "  ".join(f"{'🥇🥈🥉'[i]}{n} {v}{unit}" for i, (v, n) in enumerate(top)))
        return "\n".join(lines)

    def show_rank(self) -> None:
        conv = self.current
        if conv is None or conv.kind not in ("lobby", "room"):
            return
        text = self.rank_text(conv, week_id()) or "这周还没有人说话。"
        TextDialog(self, f"本周排行榜 · {conv.title}", [("", text)],
                   "只统计这台电脑看到的消息数量。每周一公布上周榜单,可以在「趣味互动」里关掉。").exec()

    def _tick_rank(self, day: datetime.date | None = None) -> None:
        """新的一周:公布上周榜单(每个群一次),然后清掉旧数据。"""
        cur = week_id(day)
        for key, weeks in list(self.rank.items()):
            old = sorted(w for w in weeks if w < cur)
            if not old:
                continue
            conv = self.convs.get(key)
            if conv is not None and self.fun.get("rank"):
                text = self.rank_text(conv, old[-1])
                if text:
                    self._system(conv, f"🏆 上周排行榜\n{text}")
            for w in old:
                weeks.pop(w, None)

    # ---------------------------------------------------------------- 群改名(所有人同步)
    def rename_room(self, conv: Conv | None = None) -> bool:
        """修改暗号群的名字,群里所有人都会看到。同时有人改时,以最后一次修改为准。"""
        conv = conv or self.current
        if conv is None or conv.kind != "room":
            return False
        text = prompt(self, "修改群名", "群里所有人都会看到新名字。", conv.title, max_len=MAX_NICK, ok="修改")
        name = clean_nick(text or "")
        if not name or name == conv.title:
            return False
        t = time.time()
        if t <= conv.name_t:                     # 本机时间比别人慢:保证这次修改仍然算"最新"
            t = conv.name_t + 0.001
        self._set_room_name(conv, name, t)
        scope, target = self.scope_target(conv)
        self.core.send_event(scope, target, "room_name", {"name": name, "time": t})
        self._system(conv, f"你把群名改成了「{name}」")
        return True

    def _set_room_name(self, conv: Conv, name: str, t: float) -> None:
        conv.title = name
        conv.name_t = t
        if conv.target in self.room_keys:
            self.room_keys[conv.target]["name"] = name
        if conv.key == self.current_key:
            self._refresh_header()
        self.conv_list.viewport().update()

    def _ev_room_name(self, conv: Conv, d: dict, data: dict) -> None:
        name, t = clean_nick(data.get("name") or ""), data.get("time")
        if conv.kind != "room" or not name or type(t) not in (int, float):
            return
        t = min(float(t), time.time() + 300)      # 时间写到很远的将来也只能算"现在",防止有人把群名锁死
        if t < conv.name_t or (t == conv.name_t and name <= conv.title):
            return
        if name == conv.title:
            conv.name_t = t
            return
        self._set_room_name(conv, name, t)
        if not data.get("sync"):
            self._system(conv, f"{d['nick']} 把群名改成了「{name}」")
