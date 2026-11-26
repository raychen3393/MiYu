"""
密语 · 系统:局域网自动更新(签名验证)、数据管理(位置 / 占用 / 一键清理 / 便携模式)、
出错报告窗口、启动自检和诊断信息。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from .. import changelog, crashlog, errors, imaging, msgdb, selfcheck, stickers as ST, storage, update as U
from ..dialogs import Dialog, TextDialog, ask, info
from ..ui import button, label
from ..version import VERSION


UPDATE_MODES = [("auto", "自动下载,安装前问我"), ("notify", "只提醒,不自动下载"), ("off", "关闭")]


def dir_size(path: str) -> int:
    total = 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class DataDialog(Dialog):
    """数据都放在哪、各占多少、一键清理。rows = [(key, 名字, 说明, 按钮文字)];win 提供 data_size / data_clean。"""

    def __init__(self, win) -> None:
        super().__init__(win, "数据管理")
        self.win = win
        self.setFixedWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(8)
        lay.addWidget(label("数据管理", "dialogTitle"))
        self.where = label("", "hint", wrap=True)
        self.where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.where)
        self.sizes: dict[str, QLabel] = {}
        for key, title, desc, btn in win.data_rows():
            card = QFrame()
            card.setObjectName("plainCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 8, 10, 8)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(title, "cardTitle"))
            col.addWidget(label(desc, "fileSub", wrap=True))
            row.addLayout(col, 1)
            size = label("", "fileSub")
            self.sizes[key] = size
            row.addWidget(size)
            if btn:
                row.addWidget(button(btn, "link", lambda _=False, k=key: self.clean(k)))
            lay.addWidget(card)
        self.total = label("", "section")
        lay.addWidget(self.total)
        row = QHBoxLayout()
        row.addWidget(button("打开数据文件夹", "", win.open_data_folder))
        self.move_btn = button("", "", self.move)
        row.addWidget(self.move_btn)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("一键清理全部…", "destructive", self.clean_all))
        row.addStretch(1)
        row.addWidget(button("完成", "primary", self.accept, 90))
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        win = self.win
        portable = win.data_is_portable()
        self.where.setText(("所有数据都在这一个文件夹里(便携模式,和软件放在一起):\n" if portable
                            else "所有数据都在这一个文件夹里:\n") + win.data_folder())
        total = 0
        for key, lb in self.sizes.items():
            n = win.data_size(key)
            total += n
            lb.setText(imaging.human_size(n) if n else "空")
        self.total.setText(f"一共占用 {imaging.human_size(total)}")
        self.move_btn.setText("改回系统默认位置" if portable else "改成和软件放在一起(便携)")

    def clean(self, key: str) -> None:
        self.win.data_clean(key)
        self.refresh()

    def move(self) -> None:
        self.win.move_data(not self.win.data_is_portable())
        self.refresh()

    def clean_all(self) -> None:
        self.accept()
        self.win.logout()


MAX_ERRORS = 50


class ErrorLog(QObject):
    """本次运行里的出错记录(只在内存,最多 50 种)。任何线程都可以报告,界面线程收到 reported 信号。"""
    reported = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict] = []
        self._lock = threading.Lock()
        self._installed = False

    def add(self, where: str, text: str, sig: str) -> dict:
        """记一条。同一个问题(sig 相同)只记一次,累加次数;返回的 new 表示是不是第一次出现。"""
        now = time.time()
        with self._lock:
            for e in self.entries:
                if e["sig"] == sig:
                    e["count"] += 1
                    e["last"] = now
                    entry = dict(e, new=False)
                    break
            else:
                e = {"time": now, "last": now, "where": where, "text": text, "sig": sig, "count": 1}
                self.entries.append(e)
                del self.entries[:-MAX_ERRORS]
                entry = dict(e, new=True)
        self.reported.emit(entry)
        return entry

    def add_exception(self, where: str, exc: BaseException, tb=None) -> dict:
        return self.add(where, errors.format_exception(exc, tb), errors.signature(exc, tb))

    def install(self) -> None:
        """接管没被处理的错误:界面线程的(sys.excepthook)和其它线程的(threading.excepthook)。
        打包成窗口程序后这些错误原本会被悄悄吞掉,用户只会觉得"点了没反应"。"""
        if self._installed:
            return
        self._installed = True
        old_sys, old_thread = sys.excepthook, threading.excepthook

        def on_sys(etype, exc, tb):
            if issubclass(etype, KeyboardInterrupt):
                return old_sys(etype, exc, tb)
            try:
                self.add_exception("界面", exc, tb)
            except Exception:
                old_sys(etype, exc, tb)

        def on_thread(args):
            if args.exc_type is SystemExit:
                return
            try:
                name = args.thread.name if args.thread is not None else ""
                self.add_exception(f"后台线程 {name}".strip(), args.exc_value, args.exc_traceback)
            except Exception:
                old_thread(args)
        sys.excepthook = on_sys
        threading.excepthook = on_thread

    def text(self) -> str:
        with self._lock:
            entries = list(self.entries)
        return "\n\n".join(error_entry_text(e) for e in entries) if entries else "(本次运行还没有出过错)"


_ERRORS: ErrorLog | None = None


def error_log() -> ErrorLog:
    global _ERRORS
    if _ERRORS is None:
        _ERRORS = ErrorLog()
    return _ERRORS


def error_entry_text(e: dict) -> str:
    when = time.strftime("%H:%M:%S", time.localtime(e["time"]))
    times = f"(出现 {e['count']} 次)" if e.get("count", 1) > 1 else ""
    return f"[{e['where']}] {when}{times}\n{e['text']}"


class _Relay(QObject):
    """把后台线程的结果送回界面线程。"""
    done = Signal(object)


class ReportTextDialog(Dialog):
    """一大段可以复制的文字:出错报告、诊断信息共用。"""

    def __init__(self, parent, title: str, intro: str, text: str, refresh=None) -> None:
        super().__init__(parent, title)
        self.refresh_fn = refresh
        self.setModal(False)
        self.setFixedWidth(600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(8)
        lay.addWidget(label(title, "dialogTitle"))
        lay.addWidget(label(intro, "hint", wrap=True))
        self.box = QPlainTextEdit()
        self.box.setReadOnly(True)
        f = QFont("Consolas")
        f.setPointSizeF(9)
        self.box.setFont(f)
        self.box.setPlainText(text)
        self.box.setFixedHeight(260)
        lay.addWidget(self.box)
        row = QHBoxLayout()
        self.copy_btn = button("复制", "", self.copy, 80)
        row.addWidget(self.copy_btn)
        if refresh is not None:
            row.addWidget(button("重新检查", "", self.refresh, 96))
        row.addStretch(1)
        row.addWidget(button("关闭", "primary", self.accept, 90))
        lay.addLayout(row)

    def copy(self) -> None:
        QApplication.clipboard().setText(self.box.toPlainText())
        self.copy_btn.setText("已复制")

    def refresh(self) -> None:
        if self.refresh_fn is not None:
            self.box.setPlainText(self.refresh_fn())
            self.copy_btn.setText("复制")


class SystemMixin:
    """自动更新、数据管理、出错报告、诊断信息。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_system(self) -> None:
        self.update_mode = "auto"
        self.seen_version = ""                         # 上次打开时的版本:变新了就显示一次「这次更新了什么」
        self.peer_versions: dict[str, str] = {}
        self.update: dict = {"state": "none"}          # none / offered / downloading / ready
        self.update_bad: set = set()                   # 验签失败过的 (对方, 版本),不再重复下载
        self.update_exe: str | None = U.current_exe()  # 正在运行的 exe(直接跑源码时为空,不能自动更新)
        self.update_key: bytes | None = U.release_pubkey()
        self.own_release: dict | None = None           # 我这份 exe 是签过名的发布版 → 可以分给别人
        self._own_checked: dict | None = None
        if self.update_exe and self.update_key:
            threading.Thread(target=self._check_own, name="miyu-selfcheck", daemon=True).start()
        # 出错报告和启动自检
        self.errors = error_log()
        self.errors.reported.connect(self._on_error)
        self._error_dialog: ReportTextDialog | None = None
        self._error_pending: dict | None = None
        self._diag_pending = False
        self.check_results: list = []
        self._check_relay = _Relay()
        self._check_relay.done.connect(self._on_checks)
        QTimer.singleShot(2500, self.run_startup_checks)

    def _restore_system(self, acct: dict, st: dict) -> None:
        self.set_update_mode(st.get("update_mode", "auto"))
        seen = st.get("seen_version")
        self.seen_version = seen if U.valid_version(seen) else ""
        if U.newer(VERSION, self.seen_version or "0"):
            QTimer.singleShot(1800, self.show_whats_new)

    def _settings_system(self) -> dict:
        return {"update_mode": self.update_mode, "seen_version": self.seen_version or VERSION}

    def _tick_system(self, now: float) -> None:
        if self._own_checked and self.own_release is None:
            self.offer_own_release()
        # 3.9.8: 跨网高延迟下双端同时建连可能顶掉首条 ver 事件,对尚未报版本的在线好友定时补发(每 12 秒)
        if self._save_tick % 12 == 0:
            for pid, p in list(self.peers.items()):
                if not p.get("online"):
                    continue
                if pid not in self.peer_versions:
                    self._send_ver(pid)
                elif self._save_tick % 60 == 0 and self.own_release and U.newer(VERSION, self.peer_versions[pid]):
                    self._send_ver(pid)
        u = self.update
        if (u.get("state") == "offered" and self.update_mode == "auto" and self._save_tick % 20 == 0
                and self.peers.get(u.get("peer"), {}).get("online")):
            self.download_update()                    # 上次没下完(对方掉线):接着下

    def _peer_online_system(self, pid: str) -> None:
        self._send_ver(pid)

    # ---------------------------------------------------------------- 局域网自动更新
    def _check_own(self) -> None:
        """后台验证自己这份 exe 的签名(要把整个文件算一遍哈希)。"""
        try:
            v = U.read_release(self.update_exe, self.update_key)
            if v == VERSION:
                self._own_checked = {"size": os.path.getsize(self.update_exe), "mtime": os.path.getmtime(self.update_exe)}
        except OSError:
            pass

    def offer_own_release(self, info_: dict | None = None) -> None:
        """把自己这份签过名的 exe 登记成"任何人可下载",并告诉在线的人我的版本。"""
        info_ = info_ or self._own_checked
        if not info_ or self.own_release is not None:
            return
        fid = uuid.uuid4().hex
        self.core.restore_offers({fid: {"path": self.update_exe, "name": "MiYu.exe", "size": info_["size"],
                                        "scope": "any", "target": None, "mtime": info_["mtime"]}})
        self.own_release = {"fid": fid, "size": info_["size"]}
        for pid, p in self.peers.items():
            if p.get("online"):
                self._send_ver(pid)

    def _send_ver(self, pid: str) -> None:
        data = {"v": VERSION, "rel": self.own_release}
        if self.own_release:                            # 能给别人更新的话,顺便把最近几版的更新内容带上
            data["notes"] = changelog.to_wire()
        self.core.send_event("dm", pid, "ver", data)

    def can_update(self) -> bool:
        return bool(self.update_exe and self.update_key)

    def _ev_ver(self, d: dict, data: dict) -> None:
        pid, v, rel = d["peer"], data.get("v"), data.get("rel")
        if not U.valid_version(v):
            return
        first_seen = pid not in self.peer_versions
        self.peer_versions[pid] = v
        if first_seen and self.own_release and U.newer(VERSION, v):
            self._send_ver(pid)                      # 首次收到对方旧版本时立刻补推一次我的签名发布版
        if not (U.newer(v) and isinstance(rel, dict) and self.can_update() and self.update_mode != "off"):
            return
        fid, size = rel.get("fid"), rel.get("size")
        if not (isinstance(fid, str) and len(fid) == 32 and type(size) is int and 0 < size <= U.MAX_UPDATE_SIZE):
            return
        if (pid, v) in self.update_bad:
            return
        cur = self.update
        if cur["state"] in ("downloading", "ready") and not U.newer(v, cur.get("v", "0")):
            return
        notes = changelog.notes_between(VERSION, v, changelog.from_wire(data.get("notes")))
        offer = {"state": "offered", "peer": pid, "nick": d["nick"], "v": v, "fid": fid, "size": size, "notes": notes}
        if self.update_mode == "auto":
            self.update = offer
            self.download_update()
        elif cur["state"] != "offered" or U.newer(v, cur.get("v", "0")):
            self.update = offer
            self._update_note(f"🆕 发现新版本 v{v}({d['nick']} 那里有)。在 设置 → 软件更新 里下载。"
                              + self._notes_text(notes))

    def _update_note(self, text: str) -> None:
        conv = self.current
        if conv is not None:
            self._system(conv, text)

    def update_dir(self) -> str:
        base = self.store.folder if self.store is not None else os.path.join(tempfile.gettempdir(), "MiYu")
        return os.path.join(base, "update")

    def download_update(self) -> bool:
        u = self.update
        if u.get("state") != "offered":
            return False
        if not self.peers.get(u["peer"], {}).get("online"):
            info(self, "对方不在线", "有新版本的那个人现在不在线,等他上线后会自动重试。")
            return False
        folder = self.update_dir()
        os.makedirs(folder, exist_ok=True)
        u["path"] = os.path.join(folder, f"MiYu-{u['v']}.exe")
        u["state"] = "downloading"
        self.core.download_file(u["peer"], u["fid"], u["path"], u["size"], resume=True)
        return True

    def update_file_done(self, d: dict) -> bool:
        """文件传输完成的事件里,先看是不是更新包。是的话返回 True(不走普通文件的处理)。"""
        u = self.update
        if u.get("state") != "downloading" or d.get("fid") != u.get("fid"):
            return False
        if not d.get("ok"):
            self.update = {"state": "none"} if not d.get("paused") else {**u, "state": "offered"}
            return True
        v = U.read_release(u["path"], self.update_key)
        if v != u["v"] or not U.newer(v):
            self.update_bad.add((u["peer"], u["v"]))             # 签名不对:不是发布者打包的,丢弃
            try:
                os.remove(u["path"])
            except OSError:
                pass
            self.update = {"state": "none"}
            self._update_note("⚠️ 收到的更新包没有通过签名验证,已丢弃。")
            return True
        u["state"] = "ready"
        self._update_note(f"🆕 新版本 v{v} 已经下载好并通过了签名验证。在 设置 → 软件更新 →「安装并重启」。"
                          + self._notes_text(u.get("notes")))
        self.pet.say(f"新版本 v{v} 准备好啦", 4)
        return True

    def install_update(self) -> bool:
        u = self.update
        if u.get("state") != "ready" or not self.update_exe:
            return False
        what = changelog.format_entries(u.get("notes") or [])
        body = "软件会关闭,换成新版本后自动打开。账户和聊天记录不受影响。" + (f"\n\n这次更新了:\n{what}" if what else "")
        if not ask(self, f"安装 v{u['v']} 并重启?", body, "安装并重启"):
            return False
        if U.read_release(u["path"], self.update_key) != u["v"]:            # 安装前再验一次
            self.update = {"state": "none"}
            info(self, "更新包有问题", "文件在下载后被改动过,已取消。")
            return False
        try:
            U.apply_update(u["path"], self.update_exe)
        except OSError as e:
            info(self, "安装失败", f"没法替换软件文件:{e}\n可能是软件所在的文件夹没有写入权限。")
            return False
        self.relaunch = True
        self._force_quit = True
        self.close()
        return True

    @staticmethod
    def _notes_text(notes) -> str:
        """聊天里提示新版本时附上的更新内容(最多列 6 条)。"""
        items = [x for _v, _d, its in (notes or []) for x in its][:6]
        return ("\n更新内容:\n" + "\n".join(f"• {x}" for x in items)) if items else ""

    def show_whats_new(self) -> None:
        """更新后第一次打开:显示这次更新了什么(从上次用的版本到现在)。"""
        old = self.seen_version or "0"
        entries = changelog.notes_between(old, VERSION)
        if not self.seen_version:
            entries = entries[:1]                       # 第一次记录版本:只显示当前这一版
        self.seen_version = VERSION
        if not entries or not self.window_visible():
            return
        rows = [(f"v{v}" + (f"  ·  {d}" if d else ""), "\n".join(f"• {x}" for x in items)) for v, d, items in entries[:5]]
        TextDialog(self, f"已更新到 v{VERSION}", rows, "所有版本的更新内容:设置 → 更新 →「全部更新记录」。",
                   width=520).exec()
        self.save_account()

    def show_changelog(self) -> None:
        ReportTextDialog(self, "全部更新记录", f"当前版本 v{VERSION}。新的在最上面。",
                         changelog.format_entries(changelog.CHANGELOG)).exec()

    def set_update_mode(self, mode: str) -> None:
        self.update_mode = mode if mode in dict(UPDATE_MODES) else "auto"

    def _fill_update_menu(self) -> None:
        m = self.update_menu
        m.clear()
        u = self.update
        if u.get("state") == "ready":
            m.addAction(f"✅ 安装 v{u['v']} 并重启", self.install_update)
        elif u.get("state") == "offered":
            m.addAction(f"⬇ 下载 v{u['v']}", self.download_update)
        elif u.get("state") == "downloading":
            m.addAction(f"正在下载 v{u['v']}…").setEnabled(False)
        m.addAction(f"当前版本 v{VERSION} · 查看局域网里的版本…", self.show_update)
        m.addAction("📝 全部更新记录…", self.show_changelog)
        m.addSeparator()
        for key, name in UPDATE_MODES:
            a = m.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.update_mode == key)
            a.triggered.connect(lambda _=False, k=key: self.set_update_mode(k))

    def show_update(self) -> None:
        for pid, p in list(self.peers.items()):
            if p.get("online") and (pid not in self.peer_versions
                                    or (self.own_release and U.newer(VERSION, self.peer_versions[pid]))):
                self._send_ver(pid)
        rows = [("我的版本", f"v{VERSION}")]
        if not self.update_key:
            status = "这份软件没有发布签名(比如直接用源码运行),不参与自动更新。"
        elif not self.update_exe:
            status = "直接用源码运行时不能自动更新。"
        elif self.own_release:
            status = "这是签过名的发布版,局域网里版本更旧的人可以从你这里更新。"
        else:
            status = "可以接收更新。"
        rows.append(("状态", status))
        u = self.update
        if u.get("notes") and u.get("state") in ("offered", "downloading", "ready"):
            rows.append((f"新版本 v{u['v']} 更新了什么", changelog.format_entries(u["notes"])))
        cur = changelog.entry(VERSION)
        if cur:
            rows.append((f"当前版本 v{VERSION} 更新了什么", "\n".join(f"• {x}" for x in cur[2])))
        for pid, v in sorted(self.peer_versions.items(), key=lambda kv: U.parse_version(kv[1]), reverse=True):
            p = self.peers.get(pid, {})
            if p.get("online"):
                tag = "比你新" if U.newer(v) else ("比你旧" if U.newer(VERSION, v) else "和你一样")
                rows.append((p.get("nick", "?"), f"v{v}  ·  {tag}"))
        old = [p.get("nick", "?") for pid, p in self.peers.items() if p.get("online") and pid not in self.peer_versions]
        if old:
            rows.append(("没报版本的人", "、".join(old[:10]) + "(版本太旧,不支持自动更新,需要手动发一次新版给他们)"))
        dlg = TextDialog(self, "软件更新", rows, "更新包只在局域网里互相传,不连外网;每个包都要通过发布者的签名验证才会安装。",
                         width=520, extra=("全部更新记录", "link"))
        dlg.exec()
        if dlg.extra_clicked:
            self.show_changelog()

    # ---------------------------------------------------------------- 数据管理
    def data_folder(self) -> str:
        return self.store.folder if self.store is not None else storage.default_dir()

    def data_is_portable(self) -> bool:
        return os.path.abspath(self.data_folder()) == os.path.abspath(ST.portable_dir())

    def data_rows(self) -> list:
        return [
            ("account", "账户", "身份、暗号群、设置、宠物成长。删除 = 注销账户", "注销…"),
            ("history", "聊天记录", "开了「保存聊天记录」才有", "清理"),
            ("favs", "我的收藏", "随手记和收藏的消息(收藏的文件本身不在这里)", "清理"),
            ("stickers", "表情包", "收藏的表情图片", "清理"),
            ("background", "聊天背景图", "个性化里选的背景图片(加密保存)", "清理"),
            ("games", "五子棋战绩", "对局记录、人机练习。清理后联网对局的记录会从在线的人那里重新同步回来", "清理"),
            ("temp", "临时文件", "发送文件夹时打的包、下载的更新包", "清理"),
        ]

    def _data_paths(self, key: str) -> list[str]:
        base = self.data_folder()
        sticker_dir = self.stickers.folder
        return {
            "account": [os.path.join(base, storage.ACCOUNT_FILE)],
            "history": [os.path.join(base, n) for n in (storage.HISTORY_FILE, storage.HISTORY_FILE + storage.V1_BACKUP)
                        + msgdb.DB_FILES],
            "favs": [os.path.join(base, storage.FAVS_FILE)],
            "stickers": [sticker_dir],
            "background": [os.path.join(base, storage.BG_FILE)],
            "games": [os.path.join(base, storage.GAMES_FILE)],
            "temp": [os.path.join(base, storage.OUTBOX), os.path.join(base, "update")],
        }.get(key, [])

    def data_size(self, key: str) -> int:
        return sum(dir_size(p) for p in self._data_paths(key) if os.path.exists(p))

    def data_clean(self, key: str) -> None:
        if key == "account":
            self.logout()
        elif key == "history":
            if not ask(self, "清理聊天记录?", "保存在电脑上的聊天记录和当前窗口里的聊天都会清空(收藏不受影响)。", "清理", danger=True):
                return
            for conv in self.convs.values():
                if conv.kind == "self":
                    continue
                for m in conv.messages:
                    m.gone = True
                conv.messages, conv.preview, conv.unread = [], "", 0
            if self.store is not None:
                self.wipe_history_files()
                if self.save_history:
                    self.open_history()
            self._hist_dirty = False
            self._render_messages()
            self.conv_list.viewport().update()
        elif key == "favs":
            self.clear_conv(self.self_conv)
            self.save_favs(force=True)
        elif key == "stickers":
            self.clear_stickers()
        elif key == "background":
            self.set_custom_background(None)
        elif key == "games":
            if not ask(self, "清理五子棋战绩?", "这台电脑上的对局记录和人机练习会删掉。联网对局的记录别人那里也有,"
                       "下次和他们连上时会自动同步回来(排行榜不会因此改变)。", "清理", danger=True):
                return
            self.gm_recs.clear()
            self.gm_practice.clear()
            self._gm_changed()
            self.gm_save()
            self._gm_refresh()
        elif key == "temp":
            keep = self.update.get("path") if self.update.get("state") in ("downloading", "ready") else None
            for p in self._data_paths("temp"):
                if not os.path.isdir(p):
                    continue
                for name in os.listdir(p):
                    full = os.path.join(p, name)
                    if keep and os.path.abspath(full) in (os.path.abspath(keep), os.path.abspath(keep) + ".part"):
                        continue
                    if os.path.isdir(full):
                        shutil.rmtree(full, ignore_errors=True)
                    else:
                        try:
                            os.remove(full)
                        except OSError:
                            pass

    def open_data_folder(self) -> None:
        folder = self.data_folder()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def show_data(self) -> None:
        DataDialog(self).exec()

    def move_data(self, portable: bool) -> bool:
        """把数据文件夹搬到软件旁边(便携)或搬回系统默认位置。"""
        if self.store is None:
            return False
        src = self.store.folder
        dst = ST.portable_dir() if portable else ST.system_dir()
        if os.path.abspath(src) == os.path.abspath(dst):
            return False
        what = "和软件放在一起的 MiYuData 文件夹" if portable else "系统默认位置"
        if not ask(self, "搬动数据?", f"数据会搬到{what}:\n{dst}\n\n注意:数据是和这台电脑的 Windows 账号绑定加密的,"
                                    "把文件夹拷到别的电脑上打不开。", "搬过去"):
            return False
        self.save_account(force=True)
        self.save_history_now(force=True)
        self.save_favs(force=True)
        self.close_db()                              # 数据库要先关上才能搬
        crashlog.stop()                              # 闪退记录文件开着删不掉:先停,搬完在新位置重新开始
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                os.makedirs(dst, exist_ok=True)
        except OSError as e:
            info(self, "搬不过去", f"{e}\n可能是那个位置没有写入权限。数据还在原来的地方。")
            crashlog.start(src)
            if self.save_history:
                self.open_history()
            return False
        inside = os.path.abspath(self.stickers.folder).startswith(os.path.abspath(src) + os.sep)
        self.store.folder = dst
        if inside:
            self.store.stickers_folder = self.stickers.folder = os.path.join(dst, "cache")
        if os.path.isdir(src):
            for name in os.listdir(src):
                if name.endswith(".bin") or name.startswith(msgdb.DB_FILE):
                    storage._shred(os.path.join(src, name))
            shutil.rmtree(src, ignore_errors=True)
        crashlog.start(dst)
        if self.save_history:
            self.open_history()
        return True

    # ---------------------------------------------------------------- 出错报告
    def _ev_error(self, d: dict) -> None:
        """网络模块报上来的后台错误。"""
        self.errors.add(str(d.get("where") or "网络模块"), str(d.get("text") or ""), str(d.get("sig") or ""))

    def _on_error(self, entry: dict) -> None:
        if not entry.get("new"):
            return                                   # 同一个问题已经提示过了,只累加次数
        if self._error_dialog is not None:
            return                                   # 已经开着一个出错窗口
        if not self.window_visible() or self.locked:
            self._error_pending = entry              # 软件藏起来时不弹窗(会暴露),叫回来再说
            return
        self.show_error(entry)

    def show_error(self, entry: dict) -> None:
        text = f"{errors.env_line()}\n{error_entry_text(entry)}"
        n = len(self.errors.entries)
        intro = ("软件遇到了一个问题。不影响使用的话关掉这个窗口就行;方便的话点「复制」,把内容发给开发者,能很快查到原因。\n"
                 "这里只有错误类型和出错的代码位置,没有聊天内容。"
                 + (f"\n本次一共出过 {n} 种错误,设置 →「诊断信息」里能看到全部。" if n > 1 else ""))
        dlg = ReportTextDialog(self, "出错了", intro, text)
        dlg.finished.connect(lambda *_: setattr(self, "_error_dialog", None))
        self._error_dialog = dlg
        dlg.show()

    def show_pending_problems(self) -> None:
        """窗口叫回来 / 解锁后:补上藏起来期间的出错提示和自检问题。"""
        if self.locked:
            return
        if self._error_pending is not None and self._error_dialog is None:
            entry, self._error_pending = self._error_pending, None
            self.show_error(entry)
        elif self._diag_pending:
            self._diag_pending = False
            self.show_diagnostics(problems=True)

    # ---------------------------------------------------------------- 启动自检 / 诊断信息
    def run_startup_checks(self, show_problems: bool = True) -> None:
        store = self.store if self.remember else None

        def work():
            res = selfcheck.run_checks(core=self.core, store=store)
            self._check_relay.done.emit((res, show_problems))
        threading.Thread(target=work, name="miyu-check", daemon=True).start()

    def _on_checks(self, payload) -> None:
        res, show = payload
        self.check_results = res
        if show and selfcheck.has_failure(res):
            if self.window_visible() and not self.locked:
                self.show_diagnostics(problems=True)
            else:
                self._diag_pending = True

    def update_status(self) -> str:
        if not self.update_key:
            return "这份软件没有发布签名(比如直接用源码运行),不参与自动更新"
        if not self.update_exe:
            return "直接用源码运行,不能自动更新"
        return "签过名的发布版,可以分给别人" if self.own_release else "可以接收更新"

    def diagnostics_text(self) -> str:
        checks = selfcheck.format_results(self.check_results) if self.check_results else "(自检还没跑完)"
        wall = self.centralWidget()
        bg = wall.status_text() if hasattr(wall, "status_text") else "?"
        crash = getattr(self, "last_crash", "")
        return (f"{errors.env_line()}\n时间 {time.strftime('%Y-%m-%d %H:%M:%S')}\n自动更新:{self.update_status()}\n"
                f"动态背景:{bg}\n\n"
                f"【启动自检】\n{checks}\n\n【本次的出错记录】\n{self.errors.text()}"
                + (f"\n\n【上次闪退的位置】\n{crash}" if crash else ""))

    def show_crash_report(self) -> None:
        """上次密语意外退出(闪退)了:显示出事时程序执行到哪里,可以复制发给开发者。"""
        text = getattr(self, "last_crash", "")
        if not text or not self.window_visible():
            return
        ReportTextDialog(self, "上次密语意外退出了", "很抱歉!下面是出事时程序执行到的位置(只有代码位置,没有聊天内容)。"
                         "点「复制」发给开发者,就能很快找到原因。以后也可以在 设置 → 数据 →「诊断信息」里看到。",
                         text).exec()

    def show_diagnostics(self, problems: bool = False) -> None:
        if problems:
            title = "启动自检发现问题"
            intro = "有的基础功能不正常,相关的操作可能会失败。点「复制」把下面的内容发给开发者。"
        else:
            title = "诊断信息"
            intro = "软件各项基础功能的状态和本次运行的出错记录。遇到问题时点「复制」发给开发者。没有聊天内容。"

        def refresh() -> str:
            self.check_results = selfcheck.run_checks(core=self.core, store=self.store if self.remember else None)
            return self.diagnostics_text()
        dlg = ReportTextDialog(self, title, intro, self.diagnostics_text(), refresh=refresh)
        if problems:
            dlg.show()
            self._diag_dialog = dlg
        else:
            dlg.exec()
