"""
密语 · 边下边看(2.5)
- 视频还在下载时,播放器通过一个只在本机(127.0.0.1)监听的小服务器读文件:
  已经下载到的部分直接给,还没下载到的部分就等一等(播放器那边显示"缓冲中"),拖进度条照常能用。
- 地址里带一个随机口令,别的程序猜不到;只有本机能连,不会触发防火墙提示。
- 每次只打开文件读一小块就关掉:下载完成时要把 .part 改名成正式文件,Windows 上开着的文件改不了名。
- 只有"索引在开头"的 MP4 / MOV 能边下边看(播放器一开始就要读索引);索引在末尾的要下完才能放。
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

READ_BLOCK = 256 * 1024               # 每次读多少
WAIT_STEP = 0.2                       # 数据还没到时每隔多久看一次
WAIT_MAX = 180.0                      # 最多等多久(下载停了 / 对方掉线)
STREAM_MIN = 8 * 1024 * 1024          # 下载到这么多才允许开始边下边看(小视频下完为止)
MIME = {"mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime"}
STREAM_EXTS = set(MIME)


# ---------------------------------------------------------------- MP4 能不能边下边看
def mp4_streamable(path: str, have: int | None = None) -> bool | None:
    """看 MP4 / MOV 顶层的块:索引(moov)在画面数据(mdat)前面 → True;在后面 → False;
    还没下载到能判断的位置 → None。have = 已经下载了多少字节(默认按文件大小)。"""
    try:
        size = os.path.getsize(path) if have is None else have
        with open(path, "rb") as f:
            pos = 0
            for _ in range(64):                             # 顶层块不会很多
                if pos + 8 > size:
                    return None
                f.seek(pos)
                head = f.read(16)
                if len(head) < 8:
                    return None
                n = int.from_bytes(head[:4], "big")
                kind = head[4:8]
                if pos == 0 and kind != b"ftyp":
                    return False                            # 不是 MP4 / MOV
                if n == 1:
                    if len(head) < 16:
                        return None
                    n = int.from_bytes(head[8:16], "big")
                elif n == 0:                                # 一直到文件末尾
                    return kind == b"moov"
                if n < 8:
                    return False
                if kind == b"moov":
                    return True
                if kind == b"mdat":
                    return False
                pos += n
    except OSError:
        return None
    return False


def can_stream(name: str) -> bool:
    return os.path.splitext(name or "")[1].lower().lstrip(".") in STREAM_EXTS


# ---------------------------------------------------------------- 本机小服务器
class Source:
    """一个正在下载的视频。info() 返回 (现在的文件路径, 已经能读的字节数, 总大小, 状态)。
    状态:"down" 还在下 / "done" 下完了 / "fail" 停了或取消了。"""

    def __init__(self, info) -> None:
        self.info = info
        self.alive = True


class StreamServer:
    def __init__(self) -> None:
        self.sources: dict[str, Source] = {}
        self.lock = threading.Lock()
        self.httpd: ThreadingHTTPServer | None = None
        self.port = 0

    def _ensure(self) -> None:
        if self.httpd is not None:
            return
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a) -> None:           # 不往控制台打日志
                pass

            def do_HEAD(self) -> None:
                server.handle(self, head=True)

            def do_GET(self) -> None:
                server.handle(self, head=False)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.daemon_threads = True
        self.httpd, self.port = httpd, httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, name="miyu-stream", daemon=True).start()

    def add(self, info, name: str = "video.mp4") -> str:
        """登记一个视频,返回播放器用的地址。"""
        with self.lock:
            self._ensure()
            token = secrets.token_urlsafe(18)
            self.sources[token] = Source(info)
        ext = os.path.splitext(name)[1].lower() or ".mp4"
        return f"http://127.0.0.1:{self.port}/{token}/v{ext}"

    def remove(self, url: str) -> None:
        token = url.split("/")[3] if url.count("/") >= 4 else ""
        with self.lock:
            src = self.sources.pop(token, None)
        if src is not None:
            src.alive = False

    def stop(self) -> None:
        with self.lock:
            for s in self.sources.values():
                s.alive = False
            self.sources.clear()
            httpd, self.httpd = self.httpd, None
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except OSError:
                pass

    # ---- 处理一个请求
    def handle(self, h: BaseHTTPRequestHandler, head: bool) -> None:
        parts = h.path.split("/")
        token = parts[1] if len(parts) > 2 else ""
        with self.lock:
            src = self.sources.get(token)
        if src is None:
            h.send_error(404)
            return
        try:
            path, have, total, state = src.info()
        except Exception:                                   # noqa: BLE001
            h.send_error(404)
            return
        if total <= 0 or state == "fail":
            h.send_error(404)
            return
        start, end = 0, total - 1
        rng = h.headers.get("Range", "")
        partial = False
        if rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].strip().partition("-")
            try:
                if a:
                    start = int(a)
                    if b:
                        end = min(int(b), total - 1)
                elif b:                                     # bytes=-500:最后 500 字节
                    start = max(0, total - int(b))
                partial = True
            except ValueError:
                h.send_error(400)
                return
            if start >= total or start > end:
                h.send_response(416)
                h.send_header("Content-Range", f"bytes */{total}")
                h.send_header("Content-Length", "0")
                h.end_headers()
                return
        ext = os.path.splitext(h.path)[1].lower().lstrip(".")
        h.send_response(206 if partial else 200)
        h.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        h.send_header("Accept-Ranges", "bytes")
        h.send_header("Content-Length", str(end - start + 1))
        if partial:
            h.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        if head:
            return
        pos = start
        waited = 0.0
        try:
            while pos <= end and src.alive:
                path, have, total, state = src.info()
                if state == "fail":
                    return
                if pos < have:
                    data = read_block(path, pos, min(READ_BLOCK, have - pos, end + 1 - pos))
                    if data is None:                       # 刚好在改名:再看一次
                        time.sleep(0.05)
                        continue
                    h.wfile.write(data)
                    pos += len(data)
                    waited = 0.0
                    continue
                if waited >= WAIT_MAX:
                    return
                time.sleep(WAIT_STEP)                       # 还没下载到这里:等一等
                waited += WAIT_STEP
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return                                          # 播放器拖了进度条 / 关了


def read_block(path: str, pos: int, n: int) -> bytes | None:
    """打开 → 读一块 → 马上关掉(不长时间占着文件,下载完才能改名)。"""
    try:
        with open(path, "rb") as f:
            f.seek(pos)
            data = f.read(n)
        return data or None
    except OSError:
        return None


_server: StreamServer | None = None


def server() -> StreamServer:
    global _server
    if _server is None:
        _server = StreamServer()
    return _server
