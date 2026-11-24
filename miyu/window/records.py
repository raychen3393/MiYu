"""
密语 · 聊天记录(2.0)
  · 加密数据库(msgdb.py):不再限 200 条,可以选保留全部或最近 N 天;只把有变化的消息写进去
  · 启动时每个会话只读最近一页,往上翻再一页页读(更快、更省内存)
  · 消息列表只渲染屏幕附近的一段:往上翻自动接上更早的,往下翻接上更新的,太长时裁掉远处的
  · 跳到很早的消息(引用、置顶、搜索)时,从数据库把它和前后的消息读出来,只渲染那一段
  · 旧版本的 h.bin 第一次打开时自动搬进数据库,原文件改名留作备份
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QPushButton

from .. import storage
from ..crypto import ContextKey
from ..msgdb import DB_FILE, MsgDB, WrongKey, remove_files
from ..widgets import Conv, Msg

HISTORY_DAYS = [(0, "全部保留"), (7, "最近 7 天"), (30, "最近 30 天"), (90, "最近 90 天"), (365, "最近一年")]
FIRST_PAGE = 60          # 启动时每个会话读最近几条
PAGE = 60                # 往上 / 往下翻时每次接上几条
WIN_FIRST = 50           # 打开会话时渲染最近几条
WIN_MAX = 160            # 同时渲染的消息最多几条(再多就裁掉远处的)
MEM_KEEP = 400           # 内存里每个会话最多留几条(已经存进数据库的;更早的翻到再读)
MEM_KEEP_NO_DB = 500     # 没开保存记录时,内存里最多留几条(和 1.x 一样,更早的就没了)
JUMP_LOAD_MAX = 20000    # 跳到很早的消息时最多往前读多少条
SEARCH_MAX = 800         # 会话内搜索最多找多少个结果
MAINTAIN_EVERY = 600     # 每 10 分钟清理一次过期记录、回收空间


def msg_sig(m: Msg) -> tuple:
    """消息里会变的部分(编辑、撤回、已读、表情回应…);不变就不用重新写进数据库。"""
    return (m.text, m.edited, m.delivered, m.read, m.fav, m.mention, m.title, m.level,
            tuple(sorted((k, len(v)) for k, v in (m.reactions or {}).items())), len(m.img or b""),
            json.dumps(m.card, sort_keys=True, ensure_ascii=False) if m.card else "",
            (len(m.file.get("thumb") or ""), m.file.get("dur"), bool(m.file.get("probed"))) if m.file else None)


def dict_matches(d: dict, q: str) -> bool:
    f = d.get("file")
    if isinstance(f, dict):
        return q in str(f.get("name", "")).lower()
    return q in str(d.get("text", "")).lower()


class RecordsMixin:
    """聊天记录数据库 + 分页渲染。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_records(self) -> None:
        self.db: MsgDB | None = None
        self._db_key: bytes | None = None
        self._db_sig: dict[str, tuple] = {}           # mid → 写进数据库时的样子
        self._db_known: dict[str, set] = {}          # 会话 → 内存里、已经在数据库里的消息
        self._db_convs: dict[str, tuple] = {}        # 会话 → 写进数据库的 (类型, 名字, 对象)
        self._db_extra: dict = {"transfers": {}, "games": {}, "votes": {}}
        self._db_extra_sig = ""
        self.history_days = 0
        # 分页渲染:当前会话渲染的是 conv.messages[lo:hi];bottom = 跟着最新消息
        self._win_key: str | None = None
        self._win_lo = 0
        self._win_hi = 0
        self._win_bottom = True
        self._anchor: tuple | None = None            # (mid, 在屏幕上的 y, 截止时间):重画后保持这条消息不动
        self._paging_t = 0.0
        self.latest_btn = QPushButton("↓  回到最新", self.chat_panel)
        self.latest_btn.setObjectName("latestBtn")
        self.latest_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.latest_btn.clicked.connect(self.back_to_latest)
        self.latest_btn.hide()

    def _restore_records(self, acct: dict, st: dict) -> None:
        days = st.get("history_days")
        self.history_days = days if days in dict(HISTORY_DAYS) else 0

    def _settings_records(self) -> dict:
        return {"history_days": self.history_days}

    def _save_records(self) -> dict:
        return {"dbkey": storage.b64e(self._db_key)} if self._db_key and self.save_history else {}

    def _place_records(self) -> None:
        b = self.latest_btn
        if not b.isVisible():
            return
        b.adjustSize()
        tl = self._pill.mapTo(self.chat_panel, QPoint(0, 0))
        b.move(int(self.chat_panel.width() / 2 - b.width() / 2), tl.y() - b.height() - 14)
        b.raise_()

    def refresh_latest_btn(self, new: bool = False) -> None:
        """正在看很早的记录时,输入框上方显示「回到最新」(来了新消息就变成「有新消息」)。"""
        b = self.latest_btn
        show = self.current is not None and not self._win_bottom
        if show:
            b.setText("↓  有新消息" if new or b.property("hasNew") else "↓  回到最新")
            b.setProperty("hasNew", bool(new or b.property("hasNew")))
        else:
            b.setProperty("hasNew", False)
        b.setVisible(show)
        self._place_records()

    def _tick_records(self, now: float) -> None:
        if self.db is not None and self._save_tick % MAINTAIN_EVERY == 0:
            self.maintain_history()

    # ---------------------------------------------------------------- 打开 / 关闭数据库
    def history_db_path(self) -> str:
        return os.path.join(self.store.folder, DB_FILE)

    def open_history(self) -> bool:
        """打开(或新建)加密数据库,搬运旧版记录,读出每个会话最近的一页。"""
        if self.store is None or self.db is not None:
            return self.db is not None
        key = storage.b64d(self.account.get("dbkey"))
        fresh = len(key) != 32
        if fresh:
            key = os.urandom(32)
        os.makedirs(self.store.folder, exist_ok=True)
        path = self.history_db_path()
        try:
            db = MsgDB(path, key)
        except (WrongKey, sqlite3.Error):
            # 打不开(账户重建过、文件坏了):挪到一边留着,新建一个
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(path + suffix):
                    try:
                        os.replace(path + suffix, f"{path}.broken-{stamp}{suffix}")
                    except OSError:
                        pass
            try:
                db = MsgDB(path, key)
            except sqlite3.Error:
                return False
        self.db, self._db_key = db, key
        if fresh:
            self.account["dbkey"] = storage.b64e(key)
            self.save_account(force=True)
        self._migrate_v1()
        self.load_history()
        return True

    def close_db(self) -> None:
        if self.db is not None:
            try:
                self.db.close()
            except sqlite3.Error:
                pass
        self.db = None
        self._db_sig.clear()
        self._db_known.clear()
        self._db_convs.clear()

    def wipe_history_files(self) -> None:
        """删掉电脑上保存的所有聊天记录(数据库、旧版文件和它的备份)。"""
        self.close_db()
        if self.store is not None:
            self.store.clear_history()
            remove_files(self.store.folder)
        self._db_key = None
        self.account.pop("dbkey", None)

    def _migrate_v1(self) -> None:
        """1.x 的记录(h.bin,每个会话最多 200 条)搬进数据库;原文件改名成 h.bin.v1bak 留作备份。"""
        if not self.store.has_v1_history():
            return
        h = self.store.load_history()
        if not h:
            return
        for c in h.get("convs") or []:
            if not isinstance(c, dict) or c.get("kind") not in ("lobby", "room", "dm"):
                continue
            key = str(c.get("key", ""))
            msgs = [d for d in (c.get("messages") or []) if isinstance(d, dict) and isinstance(d.get("mid"), str)]
            self.db.put_conv(key, {"kind": c["kind"], "title": str(c.get("title") or ""), "target": c.get("target")})
            self.db.upsert_many(key, msgs)
        extra = {"transfers": h.get("transfers") if isinstance(h.get("transfers"), dict) else {},
                 "games": h.get("games") if isinstance(h.get("games"), dict) else {},
                 "votes": h.get("votes") if isinstance(h.get("votes"), dict) else {}}
        for name, v in extra.items():
            old = self.db.get_meta(name, {})
            self.db.set_meta(name, {**(old if isinstance(old, dict) else {}), **v})
        self.store.retire_v1_history()

    # ---------------------------------------------------------------- 读
    def _restore_transfers(self, transfers: dict) -> None:
        for fid, t in transfers.items():
            if not isinstance(t, dict) or fid in self.transfers:
                continue
            t = dict(t)
            if t.get("mine"):
                t["up"] = {}
            if t.get("state") in ("paused", "downloading"):
                part = str(t.get("path", "")) + ".part"
                if os.path.exists(part):
                    t.update({"state": "paused", "done": os.path.getsize(part)})
                else:
                    t.update({"state": "offer", "done": 0, "auto": False})
            self.transfers[fid] = t

    def msg_from_dict(self, d: dict) -> Msg | None:
        kw = storage.msg_kwargs(d)
        if kw is None:
            return None
        m = Msg(str(d.get("text", "")), **kw)
        if m.anon and m.file and isinstance(d.get("vid"), str):
            m.vid = storage.b64d(d["vid"]) or None        # 匿名纸条里的视频
            if m.vid is None:
                return None
        m.time = float(d.get("time") or time.time())
        m.edited = bool(d.get("edited"))
        m.title = str(d.get("title") or "")[:8]
        m.level = d.get("level") if type(d.get("level")) is int and 0 <= d.get("level") <= 30 else 0
        if isinstance(d.get("reactions"), dict):
            m.reactions = {e: [x for x in w if isinstance(x, str)] for e, w in d["reactions"].items()
                           if isinstance(w, list)}
        m.mention = bool(d.get("mention"))
        m.delivered = bool(d.get("delivered"))
        m.read = bool(d.get("read"))
        m.read_sent = True
        if m.file and m.vid is None and m.file.get("fid") not in self.transfers:
            self.transfers[m.file["fid"]] = ({"mine": True, "up": {}, "up_done": 0} if m.mine
                                             else {"state": "offer", "peer": m.sender})
        return m

    def _remember_loaded(self, conv: Conv, msgs: list[Msg]) -> None:
        known = self._db_known.setdefault(conv.key, set())
        for m in msgs:
            known.add(m.mid)
            self._db_sig[m.mid] = msg_sig(m)

    def load_history(self) -> None:
        db = self.db
        saved_tags = set()
        for r in self.account.get("rooms") or []:
            master = storage.b64d(r.get("master")) if isinstance(r, dict) else b""
            if len(master) == 32:
                saved_tags.add(ContextKey(master).tag)
        extra = {name: db.get_meta(name, {}) for name in ("transfers", "games", "votes")}
        self._db_extra = {k: (v if isinstance(v, dict) else {}) for k, v in extra.items()}
        self._db_extra_sig = json.dumps(self._db_extra, sort_keys=True, ensure_ascii=False)
        self._restore_transfers(self._db_extra["transfers"])
        self.restore_games_history(self._db_extra)
        if self.history_days:
            db.prune(self.history_days)
        for info in db.convs():
            kind, key, target = info.get("kind"), info["key"], info.get("target")
            if kind not in ("lobby", "room", "dm") or (kind == "room" and target not in saved_tags):
                continue
            self._db_convs[key] = (kind, str(info.get("title") or ""), target)
            rows = db.recent(key, FIRST_PAGE)
            restored = [m for m in (self.msg_from_dict(d) for d in rows) if m is not None]
            if not restored:
                continue
            conv = self.convs.get(key)
            if conv is None:
                if kind == "lobby":
                    continue
                conv = Conv(key, kind, str(info.get("title") or ""), target)
                self.convs[key] = conv
                self._apply_conv_prefs(conv)
            conv.db_more = db.count_older(key, restored[0].mid, restored[0].time) > 0
            self._remember_loaded(conv, restored)
            marker = Msg("以上是保存的聊天记录", system=True)
            marker.time = restored[-1].time
            conv.messages = restored + [marker] + conv.messages
            last = restored[-1]
            conv.last_active = conv.last_time = last.time
            conv.preview = self._preview_of(last, conv)
        self._hist_dirty = False

    def load_older(self, conv: Conv, n: int = PAGE) -> int:
        """从数据库再读 n 条更早的,接在会话最前面。返回读到几条。"""
        if self.db is None or not conv.db_more:
            return 0
        known = self._db_known.get(conv.key, set())
        first = next((m for m in conv.messages if m.mid in known), None)
        if first is None:
            first = next((m for m in conv.messages if not m.system), None)
        rows = self.db.older(conv.key, first.mid if first else None, first.time if first else None, n)
        have = {m.mid for m in conv.messages}
        msgs = [m for m in (self.msg_from_dict(d) for d in rows) if m is not None and m.mid not in have]
        conv.db_more = bool(rows) and self.db.count_older(conv.key, rows[0]["mid"], rows[0].get("time")) > 0
        if msgs:
            conv.messages[0:0] = msgs
            self._remember_loaded(conv, msgs)
            if conv.key == self._win_key:
                self._win_lo += len(msgs)
                self._win_hi += len(msgs)
        return len(msgs)

    def ensure_loaded(self, conv: Conv, mid: str) -> bool:
        """确保某条消息在内存里(很早的话,把它到现在之间的都读进来)。"""
        if any(m.mid == mid for m in conv.messages):
            return True
        if self.db is None or not self.db.has(mid):
            return False
        loaded = 0
        while conv.db_more and loaded < JUMP_LOAD_MAX:
            got = self.load_older(conv, 500)
            if not got:
                break
            loaded += got
            if any(m.mid == mid for m in conv.messages[:got]):
                return True
        return any(m.mid == mid for m in conv.messages)

    # ---------------------------------------------------------------- 写
    def _saved_convs(self):
        for key, conv in self.convs.items():
            if conv.kind == "self" or (conv.kind == "room" and conv.target not in self.room_keys):
                continue
            yield key, conv

    def sync_history(self, force: bool = False) -> bool:
        """把有变化的消息写进数据库(新消息、编辑、撤回、已读…),删掉已经删除 / 撤回的。"""
        if not self.save_history or self.db is None or not (self._hist_dirty or force):
            return False
        db = self.db
        try:
            live = set()
            fids, mids = set(), set()
            for key, conv in self._saved_convs():
                live.add(key)
                info = (conv.kind, conv.title, conv.target)
                known = self._db_known.setdefault(key, set())
                present, changed = set(), []
                for m in conv.messages:
                    if m.burn or m.system or m.gone:
                        continue
                    present.add(m.mid)
                    mids.add(m.mid)
                    if m.file:
                        fids.add(m.file.get("fid"))
                    sig = msg_sig(m)
                    if self._db_sig.get(m.mid) != sig:
                        d = storage.msg_to_dict(m)
                        if d:
                            changed.append(d)
                        self._db_sig[m.mid] = sig
                gone = known - present
                if gone:
                    db.delete_mids(gone)
                    for mid in gone:
                        self._db_sig.pop(mid, None)
                if (changed or present) and self._db_convs.get(key) != info:
                    db.put_conv(key, {"kind": info[0], "title": info[1], "target": info[2]})
                    self._db_convs[key] = info
                if changed:
                    db.upsert_many(key, changed)
                self._db_known[key] = present
            for key in [k for k in self._db_convs if k not in live]:      # 关掉的私聊、退出的群
                db.delete_conv(key)
                self._db_convs.pop(key, None)
                self._db_known.pop(key, None)
            self._sync_extra(fids, mids)
        except sqlite3.Error as e:
            self.errors.add("聊天记录", f"{type(e).__name__}: {e}", "db:" + type(e).__name__)
            return False
        self._hist_dirty = False
        return True

    def _sync_extra(self, fids: set, mids: set) -> None:
        keep = ("state", "path", "done", "size", "peer", "auto", "mine", "up_done", "error")
        tr_all = dict(self._db_extra.get("transfers", {}))
        for fid in fids:
            tr = self.transfers.get(fid)
            if tr:
                t = {k: tr[k] for k in keep if k in tr}
                if t.get("state") == "downloading":
                    t.update({"state": "paused", "auto": True})
                tr_all[fid] = t
        gh = self.games_history(mids)
        games = {**self._db_extra.get("games", {}), **gh["games"]}
        votes = {**self._db_extra.get("votes", {}), **gh["votes"]}
        if len(tr_all) > 3000:
            tr_all = dict(list(tr_all.items())[-3000:])
        if len(games) > 1000:
            games = dict(list(games.items())[-1000:])
        if len(votes) > 1000:
            votes = dict(list(votes.items())[-1000:])
        self._db_extra = {"transfers": tr_all, "games": games, "votes": votes}
        sig = json.dumps(self._db_extra, sort_keys=True, ensure_ascii=False, default=str)
        if sig != self._db_extra_sig:
            for name, v in self._db_extra.items():
                self.db.set_meta(name, v)
            self._db_extra_sig = sig

    def forget_conv_history(self, conv: Conv) -> None:
        """清空会话:数据库里这个会话的记录也删掉(包括还没读进来的更早的)。"""
        if self.db is not None:
            self.db.delete_conv(conv.key)
            self._db_convs.pop(conv.key, None)
            self._db_known.pop(conv.key, None)
        conv.db_more = False

    def trim_memory(self, conv: Conv) -> None:
        """内存里的消息太多时,把最早的放掉:存过的以后翻到再读;没开保存记录时和以前一样直接丢。"""
        keep = MEM_KEEP if (self.db is not None and self.save_history) else MEM_KEEP_NO_DB
        extra = len(conv.messages) - keep
        if extra <= 0:
            return
        if conv.key == self._win_key:
            extra = min(extra, self._win_lo)              # 正在显示的那一段不能放掉
            if extra <= 0:
                return
        drop = conv.messages[:extra]
        if self.db is not None and self.save_history:
            self.sync_history(force=True)                  # 先确保都写进去了
            known = self._db_known.get(conv.key, set())
            for m in drop:
                if m.mid in known:
                    known.discard(m.mid)
                    self._db_sig.pop(m.mid, None)
                    m.thumb = None
                else:
                    m.gone = True
            conv.db_more = True
        else:
            for m in drop:
                m.gone = True
        del conv.messages[:extra]
        if conv.key == self._win_key:
            self._win_lo -= extra
            self._win_hi -= extra

    def set_history_days(self, days: int) -> None:
        self.history_days = days if days in dict(HISTORY_DAYS) else 0
        self.maintain_history()

    def maintain_history(self) -> int:
        """删掉超过保留期限的记录,回收空间。"""
        if self.db is None:
            return 0
        try:
            self.sync_history()
            n = self.db.prune(self.history_days)
            self.db.maintain()
        except sqlite3.Error:
            return 0
        return n

    def compact_history(self) -> None:
        if self.db is not None:
            self.sync_history(force=True)
            self.db.compact()

    def history_stats(self) -> tuple[int, int]:
        """(保存了多少条, 占多少字节)"""
        if self.db is None:
            return 0, 0
        try:
            return self.db.count(), self.db.size()
        except sqlite3.Error:
            return 0, 0

    # ---------------------------------------------------------------- 会话内搜索(也搜数据库里还没读进来的)
    def search_mids(self, conv: Conv, q: str) -> list[str]:
        hits = [m.mid for m in conv.messages if self._matches(m, q)]
        if self.db is not None and conv.db_more and len(hits) < SEARCH_MAX:
            known = self._db_known.get(conv.key, set())
            first = next((m for m in conv.messages if m.mid in known), None)
            older = []
            try:
                for d in self.db.scan_older(conv.key, first.mid if first else None, first.time if first else None):
                    if dict_matches(d, q):
                        older.append(d["mid"])
                        if len(older) + len(hits) >= SEARCH_MAX:
                            break
            except sqlite3.Error:
                older = []
            hits = older[::-1] + hits
        return hits

    # ---------------------------------------------------------------- 分页渲染
    def render_window(self, conv: Conv) -> list[Msg]:
        """这次要渲染的那一段消息。"""
        n = len(conv.messages)
        if self._win_key != conv.key:
            self._win_key = conv.key
            self._win_bottom = True
            self._win_lo = max(0, n - WIN_FIRST)
        if self._win_bottom:
            self._win_hi = n
            self._win_lo = max(0, min(self._win_lo, n), self._win_hi - WIN_MAX)
        else:
            self._win_hi = max(0, min(self._win_hi, n))
            self._win_lo = max(0, min(self._win_lo, self._win_hi))
            if self._win_hi - self._win_lo > WIN_MAX:
                self._win_hi = self._win_lo + WIN_MAX
            if self._win_hi >= n:
                self._win_bottom = True
        return conv.messages[self._win_lo:self._win_hi]

    def reset_window(self) -> None:
        self._win_key = None
        self._anchor = None

    def _anchor_on(self, mid: str) -> None:
        b = self.bubbles.get(mid)
        if b is None:
            return
        try:
            y = b.mapTo(self.msg_area.viewport(), QPoint(0, 0)).y()
        except Exception:                                 # noqa: BLE001
            return
        self._anchor = (mid, int(y), time.monotonic() + 0.6)

    def apply_anchor(self) -> bool:
        """重画以后,让锚定的那条消息回到原来的屏幕位置(往上翻页时内容不会跳)。"""
        a = self._anchor
        if a is None:
            return False
        if time.monotonic() > a[2]:
            self._anchor = None
            return False
        b = self.bubbles.get(a[0])
        if b is None:
            return False
        sb = self.msg_area.verticalScrollBar()
        sb.setValue(max(0, int(b.y()) - a[1]))
        return True

    def maybe_page(self, value: int) -> None:
        """滚到靠近顶部 / 底部时,接上更早 / 更新的一页。"""
        conv = self.current
        if conv is None or self._anchor is not None or self._win_key != conv.key:
            return
        now = time.monotonic()
        if now - self._paging_t < 0.25:
            return
        sb = self.msg_area.verticalScrollBar()
        if sb.maximum() <= 0:
            return
        if value <= 120 and (self._win_lo > 0 or conv.db_more):
            self._paging_t = now
            QTimer.singleShot(0, self.page_up)
        elif value >= sb.maximum() - 120 and not self._win_bottom:
            self._paging_t = now
            QTimer.singleShot(0, self.page_down)

    def page_up(self) -> bool:
        conv = self.current
        if conv is None:
            return False
        if self._win_lo == 0 and not self.load_older(conv, PAGE):
            return False
        first = conv.messages[self._win_lo] if self._win_lo < len(conv.messages) else None
        self._win_lo = max(0, self._win_lo - PAGE)
        if self._win_hi - self._win_lo > WIN_MAX:          # 太长了:把最新那头裁掉
            self._win_bottom = False
            self._win_hi = self._win_lo + WIN_MAX
        if first is not None:
            self._anchor_on(first.mid)
        self._stick = False
        self._render_messages(keep_scroll=True)
        return True

    def page_down(self) -> bool:
        conv = self.current
        if conv is None or self._win_bottom:
            return False
        last = conv.messages[self._win_hi - 1] if 0 < self._win_hi <= len(conv.messages) else None
        self._win_hi = min(len(conv.messages), self._win_hi + PAGE)
        if self._win_hi >= len(conv.messages):
            self._win_bottom = True
        if self._win_hi - self._win_lo > WIN_MAX:
            self._win_lo = self._win_hi - WIN_MAX
        if last is not None:
            self._anchor_on(last.mid)
        self._stick = False
        self._render_messages(keep_scroll=True)
        return True

    def after_live_append(self) -> None:
        """一直停在最新处聊天:渲染的条数太多时,把最上面看不到的那些去掉(重画最近一段)。"""
        if self._win_bottom and self._stick and self._win_hi - self._win_lo > WIN_MAX + 40:
            self._win_lo = self._win_hi - WIN_FIRST
            self._render_messages()

    def back_to_latest(self) -> None:
        """回到最新消息(看很早的记录时,右下角的「回到最新」)。"""
        self._win_bottom = True
        conv = self.current
        if conv is not None:
            self._win_lo = max(0, len(conv.messages) - WIN_FIRST)
        self._anchor = None
        self._render_messages()

    def show_window_at(self, mid: str) -> bool:
        """把渲染窗口挪到某条消息附近(必要时先从数据库读进来)。"""
        conv = self.current
        if conv is None:
            return False
        if mid in self.bubbles:
            return True
        if not self.ensure_loaded(conv, mid):
            return False
        idx = next((i for i, m in enumerate(conv.messages) if m.mid == mid), None)
        if idx is None:
            return False
        n = len(conv.messages)
        self._win_lo = max(0, idx - 30)
        self._win_hi = min(n, idx + 40)
        self._win_bottom = self._win_hi >= n
        self._anchor = None
        self._stick = False
        self._render_messages(keep_scroll=True)
        return mid in self.bubbles
