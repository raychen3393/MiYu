"""
密语 · 发送文件夹(打包 / 自动解压)、投送(拖到人或会话上)、软件内看视频(播放器在 player.py)。
2.5:视频最大 20GB;索引在开头的 MP4 / MOV 下载到一部分就能边下边看(见 stream.py)。
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections import deque

from PySide6.QtCore import QPoint, QStandardPaths, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from .. import imaging, storage, stream, video
from ..core import MAX_FILE
from ..dialogs import info
from ..player import VideoPlayer, clean_prefs, fmt_ms  # noqa: F401  (fmt_ms 别处还在用)
from ..ui import VIDEO_EXTS, button, file_ext, label, make_menu, popup
from ..widgets import Conv, Msg, VideoCard

PLAY_TMP = "MiYu-play"                # 匿名视频播放时临时解出来的文件(关掉播放器就删)


def safe_extract(zip_path: str, dest: str) -> None:
    """解压对方发来的文件夹:拒绝绝对路径和 ..,防止写到目标文件夹外面;限制总大小。"""
    dest = os.path.abspath(dest)
    total = 0
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if len(infos) > 200000:
            raise ValueError("文件太多")
        for zi in infos:
            total += zi.file_size
            if total > 2 * MAX_FILE:
                raise ValueError("解压后太大")
            name = zi.filename.replace("\\", "/")
            if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
                raise ValueError("压缩包里有不安全的路径")
            target = os.path.abspath(os.path.join(dest, name))
            if not (target == dest or target.startswith(dest + os.sep)):
                raise ValueError("压缩包里有不安全的路径")
        z.extractall(dest)


def prune_outbox(out_dir: str, days: int = 7) -> None:
    """删掉一周前打包的临时 zip(对方早该下完了)。"""
    try:
        names = os.listdir(out_dir)
    except OSError:
        return
    cutoff = time.time() - days * 86400
    for n in names:
        p = os.path.join(out_dir, n)
        try:
            if os.path.getmtime(p) < cutoff:
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        except OSError:
            pass


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def zip_folder(folder: str, out_dir: str) -> str:
    """把文件夹打包成 zip(只存储不压缩,快;大多数文件本来就压缩过)。"""
    name = os.path.basename(os.path.normpath(folder)) or "文件夹"
    sub = os.path.join(out_dir, uuid.uuid4().hex[:12])        # 每个包单独一个目录,对方看到的名字就是文件夹名
    os.makedirs(sub, exist_ok=True)
    out = os.path.join(sub, name + ".zip")
    root = os.path.dirname(os.path.normpath(folder))
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for dirpath, dirnames, files in os.walk(folder):
            rel_dir = os.path.relpath(dirpath, root)
            if not files and not dirnames:
                z.writestr(rel_dir.replace(os.sep, "/") + "/", b"")
            for fn in files:
                full = os.path.join(dirpath, fn)
                try:
                    total += os.path.getsize(full)
                except OSError:
                    continue
                if total > MAX_FILE:
                    raise ValueError("文件夹超过 4GB")
                z.write(full, os.path.relpath(full, root))
    return out


def is_video_name(path: str) -> bool:
    return file_ext(os.path.basename(path or "")) in VIDEO_EXTS


def clean_play_tmp() -> None:
    """删掉上次没来得及删的匿名视频临时文件。"""
    folder = os.path.join(tempfile.gettempdir(), PLAY_TMP)
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


class FilesMixin:
    """文件夹、投送、看视频。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_files(self) -> None:
        self.video_win: VideoPlayer | None = None
        self.video_prefs = clean_prefs(None)    # 播放器的比例 / 透明度 / 置顶(会记住)
        self.video_fallbacks = 0                 # 没有视频模块、交给系统播放器的次数
        self._probe_q: deque = deque()           # 等着取封面的视频(一次只开一个)
        self._probe = None
        self._play_tmp: list[str] = []
        prune_outbox(self.outbox_dir())
        clean_play_tmp()
        # 投送:文件可以直接拖到成员 / 会话上(拖放事件在 MainWindow.eventFilter 里处理)
        self._member_vp, self._conv_vp = self.member_list.viewport(), self.conv_list.viewport()
        for vp in (self._member_vp, self._conv_vp):
            vp.setAcceptDrops(True)
            vp.installEventFilter(self)

    # ---------------------------------------------------------------- 发送文件夹 / 投送
    def attach_menu(self) -> None:
        m = make_menu(self)
        self._menu_icon(m.addAction("发送文件…", self.pick_files), "file")
        self._menu_icon(m.addAction("发送文件夹…", self.pick_folder), "folder")
        popup(m, self.file_btn.mapToGlobal(QPoint(0, -m.sizeHint().height() - 6)))

    def pick_folder(self) -> None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        path = QFileDialog.getExistingDirectory(self, "选择要发送的文件夹", folder)
        if path:
            self.send_folder(path)

    def outbox_dir(self) -> str:
        base = self.store.folder if self.store is not None else os.path.join(tempfile.gettempdir(), "MiYu")
        return os.path.join(base, storage.OUTBOX)

    def send_folder(self, folder: str, conv: Conv | None = None) -> None:
        conv = conv or self.current
        if conv is None:
            return
        if conv.kind == "self":                    # 收藏夹:只记下文件夹位置
            self.self_files([folder])
            return
        name = os.path.basename(os.path.normpath(folder)) or "文件夹"
        self._system(conv, f"正在打包文件夹「{name}」…")
        out_dir = self.outbox_dir()
        result: dict = {}

        def work():
            try:
                result["zip"] = zip_folder(folder, out_dir)
            except Exception as e:                      # noqa: BLE001
                result["error"] = str(e) or "打包失败"

        th = threading.Thread(target=work, name="miyu-zip", daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                QTimer.singleShot(150, poll)
                return
            if "error" in result:
                self._system(conv, f"文件夹「{name}」发送失败:{result['error']}")
                return
            self._send_paths(conv, [result["zip"]], folder=True)
        QTimer.singleShot(50, poll)

    def _send_paths(self, conv: Conv, paths: list[str], folder: bool = False) -> None:
        if conv.kind == "self":
            self.self_files(paths)
            return
        scope, target = self.scope_target(conv)
        for path in paths:
            res = self.core.send_file(scope, target, path, reply=self._reply_payload(), folder=folder)
            if res is None:
                big = "视频最大 20GB,其它文件最大 4GB" if not folder else "文件夹打包后最大 4GB"
                self._system(conv, f"无法发送「{os.path.basename(path)}」(文件为空、太大或无法读取。{big})")
                continue
            mid, fid, finfo = res
            self.transfers[fid] = {"mine": True, "path": path, "up": {}, "up_done": 0}
            m = Msg("", mid=mid, sender=self.me["id"], nick=self.me.get("nick", ""), tag=self.me.get("tag", ""),
                    mine=True, file=dict(finfo), reply=self._reply_payload())
            self._add_message(conv, m)
            self.stats["files"] += 1
            if not folder and is_video_name(path):         # 视频:取封面和时长,好了再发给大家
                self.probe_video(path, lambda res, c=conv, msg=m: self.apply_poster(c, msg, res, announce=True))
        self.cancel_reply()
        self._sent_fx()

    def drop_on_conv(self, conv: Conv, paths: list[str]) -> None:
        """投送:文件拖到某个人 / 某个会话上,直接发过去。"""
        folders = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p)][:20]
        if not folders and not files:
            return
        if conv.kind == "dm" and not self.peers.get(conv.target or "", {}).get("online"):
            info(self, "对方不在线", "对方在线时才能接收文件。")
            return
        self.select_conv(conv.key)
        if files:
            self._send_paths(conv, files)
        for f in folders[:5]:
            self.send_folder(f, conv)

    def _extract_folder(self, fid: str, tr: dict) -> None:
        """收到的文件夹:下载完自动解压,然后删掉 zip。"""
        zpath = tr.get("path", "")
        dest = unique_path(os.path.splitext(zpath)[0])
        tr["state"] = "extracting"
        self._update_file_card(fid)
        result: dict = {}

        def work():
            try:
                tmp = dest + ".unpacking"
                safe_extract(zpath, tmp)
                inner = os.listdir(tmp)
                if len(inner) == 1 and os.path.isdir(os.path.join(tmp, inner[0])):
                    shutil.move(os.path.join(tmp, inner[0]), dest)
                    shutil.rmtree(tmp, ignore_errors=True)
                else:
                    os.replace(tmp, dest)
                os.remove(zpath)
                result["ok"] = dest
            except Exception as e:                      # noqa: BLE001
                result["error"] = str(e) or "解压失败"

        th = threading.Thread(target=work, name="miyu-unzip", daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                QTimer.singleShot(150, poll)
                return
            if "ok" in result:
                tr.update({"state": "done", "path": result["ok"], "folder": True})
            else:
                tr.update({"state": "done", "error": "", "note": f"自动解压失败:{result['error']},已保存为 zip"})
            self._hist_dirty = True
            self._update_file_card(fid)
        QTimer.singleShot(50, poll)

    def _restore_files(self, acct: dict, st: dict) -> None:
        self.video_prefs = clean_prefs(st.get("video"))

    def _settings_files(self) -> dict:
        return {"video": dict(self.video_prefs)}

    # ---------------------------------------------------------------- 看视频
    def _same_video(self, path: str) -> bool:
        """这个视频已经在播放器里开着:拿到前面来(顺便取消鼠标穿透),不重新打开。"""
        w = self.video_win
        if w is None or not path or w.path != path:
            return False
        try:
            w.set_passthrough(False)
            w.show()
            w.raise_()
            w.activateWindow()
        except RuntimeError:                    # 窗口已经没了
            self.video_win = None
            return False
        return True

    def play_video(self, path: str) -> None:
        if self._same_video(path):
            return
        if not path or not os.path.exists(path):
            info(self, "找不到文件", "文件可能已被移动或删除。")
            return
        self.close_video()
        try:
            win = VideoPlayer(self, path, prefs=self.video_prefs)
        except Exception:                       # 没有多媒体模块:交给系统播放器
            self.video_fallbacks += 1
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        self.video_win = win
        win.show()

    def stream_info(self, fid: str):
        """边下边看:本机小服务器问"现在文件在哪、下了多少"时调用(在别的线程里,只读不改)。"""
        def info_fn():
            tr = self.transfers.get(fid) or {}
            path, total, state = tr.get("path", ""), int(tr.get("size") or 0), tr.get("state")
            if state == "done":
                try:
                    return path, os.path.getsize(path), total, "done"
                except OSError:
                    return path, 0, total, "fail"
            if state != "downloading":
                return path, 0, total, "fail"
            try:
                have = os.path.getsize(path + ".part")
            except OSError:
                have = 0
            return path + ".part", min(have, total), total, "down"
        return info_fn

    def stream_video(self, fid: str, name: str = "") -> None:
        """视频还在下载:先看已经下载到的部分。"""
        tr = self.transfers.get(fid) or {}
        path = tr.get("path", "")
        if self._same_video(path):
            return
        self.close_video()
        srv = stream.server()
        fn = self.stream_info(fid)
        try:
            url = srv.add(fn, name or os.path.basename(path))
        except OSError:
            info(self, "暂时不能边下边看", "等下载完再播放吧。")
            return

        def dl():
            _p, have, total, state = fn()
            return (have / total if total else 0.0), state
        try:
            win = VideoPlayer(self, path, source=url, prefs=self.video_prefs, dl_info=dl,
                              title=f"{name or os.path.basename(path)}  ·  边下边看")
        except Exception:                       # 没有多媒体模块:只能下完再用系统播放器
            srv.remove(url)
            self.video_fallbacks += 1
            info(self, "这台电脑不能边下边看", "下载完以后会用系统播放器打开。")
            tr["autoplay"] = True
            return
        self.video_win = win
        win.show()

    def video_passthrough_off(self) -> None:
        w = self.video_win
        if w is not None:
            try:
                w.set_passthrough(False)
                w.raise_()
            except RuntimeError:
                self.video_win = None

    def close_video(self) -> None:
        """关掉播放器(窗口藏起来时必须停,不然还有声音)。"""
        w, self.video_win = self.video_win, None
        if w is not None:
            try:
                w.stop()
                w.close()
            except Exception:
                pass
        QTimer.singleShot(800, self._drop_play_tmp)        # 播放器松开文件后,删掉临时解出来的匿名视频

    # ---------------------------------------------------------------- 视频封面
    def probe_video(self, path: str, cb) -> None:
        """排队取视频的封面和时长,好了调用 cb(结果或 None)。一次只开一个视频。"""
        self._probe_q.append((path, cb))
        self._next_probe()

    def _next_probe(self) -> None:
        if self._probe is not None or not self._probe_q:
            return
        path, cb = self._probe_q.popleft()
        try:
            pr = video.VideoProbe(path, self)
        except Exception:                                   # noqa: BLE001
            cb(None)
            QTimer.singleShot(0, self._next_probe)
            return
        self._probe = pr

        def done(res, cb=cb):
            self._probe = None
            try:
                cb(res)
            finally:
                QTimer.singleShot(0, self._next_probe)
        pr.done.connect(done)

    def apply_poster(self, conv: Conv | None, m: Msg, res, announce: bool = False) -> None:
        """封面取好了:记到消息里、刷新卡片;自己发的视频再把封面发给会话里的人。"""
        f = m.file
        if f is None:
            return
        f["probed"] = True
        if res:
            if res.get("thumb"):
                f["thumb"] = video.b64(res["thumb"])
            f["dur"] = int(res.get("dur") or 0)
            f["vw"], f["vh"] = int(res.get("w") or 0), int(res.get("h") or 0)
        self._hist_dirty = True
        if conv is not None and conv.kind == "self":
            self._favs_dirty = True
        self._refresh_video_card(m)
        if announce and res and conv is not None and conv.kind in ("lobby", "room", "dm"):
            scope, target = self.scope_target(conv)
            data = {"mid": m.mid, "fid": f["fid"], "dur": f.get("dur", 0), "w": f.get("vw", 0), "h": f.get("vh", 0)}
            if f.get("thumb"):
                data["thumb"] = f["thumb"]
            self.core.send_event(scope, target, "fthumb", data)

    def _refresh_video_card(self, m: Msg) -> None:
        b = self.bubbles.get(m.mid)
        if b is not None and isinstance(b.card, VideoCard):
            b.card.refresh_poster()

    def _ev_fthumb(self, conv: Conv, d: dict, data: dict) -> None:
        """对方发来的视频封面(跟在视频消息后面)。只认同一个人发的、同一个文件。"""
        mid, fid = data.get("mid"), data.get("fid")
        m = next((x for x in reversed(conv.messages) if x.mid == mid and x.sender == d["peer"] and x.file
                  and x.file.get("fid") == fid and not x.mine), None)
        if m is None:
            return

        def num(key: str, hi: int) -> int:
            v = data.get(key)
            return v if type(v) is int and 0 <= v <= hi else 0
        thumb = video.clean_poster(data.get("thumb"))
        if thumb:
            m.file["thumb"] = video.b64(thumb)
        m.file.update({"dur": num("dur", 48 * 3600 * 1000), "vw": num("w", 16384), "vh": num("h", 16384),
                       "probed": True})
        self._hist_dirty = True
        self._refresh_video_card(m)

    def maybe_probe(self, conv: Conv, m: Msg) -> None:
        """显示一条没有封面的视频时(旧版本发的、对方没发封面):本机有文件就自己取一张。"""
        f = m.file
        if not f or f.get("probed") or f.get("thumb") or f.get("dir") or not is_video_name(f.get("name", "")):
            return
        path = self.transfers.get(f.get("fid"), {}).get("path") or f.get("path", "")
        if not path or not os.path.isfile(path) or (not m.mine and self.transfers.get(f["fid"], {}).get("state") != "done"):
            return
        f["probed"] = True
        self.probe_video(path, lambda res, c=conv, msg=m: self.apply_poster(c, msg, res))

    # ---------------------------------------------------------------- 匿名纸条里的视频
    def anon_video_action(self, m: Msg, action: str) -> None:
        if m.vid is None:
            return
        name = (m.file or {}).get("name") or "匿名视频.mp4"
        if action == "play":
            path = self._write_play_tmp(m.vid, name)
            if path:
                self.play_video(path)
                self._play_tmp.append(path)
        elif action == "save":
            folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
            path, _ = QFileDialog.getSaveFileName(self, "保存视频", os.path.join(folder, name),
                                                  f"视频 (*.{file_ext(name) or 'mp4'})")
            if path:
                try:
                    with open(path, "wb") as f:
                        f.write(m.vid)
                except OSError as e:
                    info(self, "保存失败", str(e))

    @staticmethod
    def _write_play_tmp(data: bytes, name: str) -> str:
        folder = os.path.join(tempfile.gettempdir(), PLAY_TMP)
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, uuid.uuid4().hex[:12] + "." + (file_ext(name) or "mp4"))
            with open(path, "wb") as f:
                f.write(data)
            return path
        except OSError:
            return ""

    def _drop_play_tmp(self) -> None:
        keep = []
        for p in self._play_tmp:
            if self.video_win is not None and self.video_win.path == p:
                keep.append(p)
                continue
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
            except OSError:
                keep.append(p)                              # 还被占着:下次再删(启动时也会清一遍)
        self._play_tmp = keep
