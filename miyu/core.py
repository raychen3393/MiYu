"""
密语 · 网络核心(无界面,可单独测试)

运行在后台线程里的 asyncio 事件循环:
- UDP 广播发现(大厅 / 暗号群),所有发现包都是加密的、等长的
- TCP 点对点加密连接(握手见 crypto.py)
- 在场信息(presence)走加密连接:谁在大厅、谁和我同在哪个暗号群
- 公开大厅 / 暗号群 / 私聊三种消息

界面通过 on_event(kind, data) 回调接收事件(在后台线程里调用),
通过下面的公开方法下发操作(线程安全)。
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import ipaddress
import os
import json
import logging
import random
import secrets
import socket
import struct
import sys
import threading
import time
import uuid

from . import compat, errors
from . import crypto as C

log = logging.getLogger("miyu")
_SYS_RNG = secrets.SystemRandom()

DEFAULT_UDP_PORT = 47820
DEFAULT_TCP_PORT = 47821

BEACON_INTERVAL = 3.0       # 发现广播间隔(秒)
BEACON_FRESH = 15.0         # 多久内收到过 beacon 算"新鲜"
PRESENCE_INTERVAL = 10.0    # 在场信息 / 心跳间隔
CONN_IDLE_TIMEOUT = 40.0    # 这么久没收到任何数据就断开
HANDSHAKE_TIMEOUT = 10.0
MAX_FRAME = 768 * 1024        # 文件数据块 512KB + 头部
SMALL_LIMIT = 200 * 1024     # 超过这个大小的消息拆成分片发送(大图片)
PART_SIZE = 150 * 1024
MAX_PARTS = 320
MAX_LARGE = 40 * 1024 * 1024    # 2.1:匿名纸条可以带视频(最大 20MB,在暗号群里要加密两层,约 36MB)
MAX_PENDING_LARGE = 8
MAX_TEXT = 5000
MAX_NICK = 20
MAX_BURN = 3600
MAX_PEERS = 300
MAX_IMAGE = 8 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024 * 1024        # 单个文件最大 4GB
MAX_VIDEO = 20 * 1024 * 1024 * 1024      # 2.5:视频最大 20GB(一两个小时的高清录屏 / 电影也能发)
LONG_VIDEO_EXTS = {"mp4", "mkv", "mov", "avi", "webm", "m4v", "wmv", "flv", "ts", "mpg", "mpeg", "3gp"}


def max_size_for(name: str, folder: bool = False) -> int:
    """这个文件最大能多大:视频 20GB,其它(包括打包的文件夹)4GB。"""
    ext = os.path.splitext(name or "")[1].lower().lstrip(".")
    return MAX_VIDEO if not folder and ext in LONG_VIDEO_EXTS else MAX_FILE
FILE_CHUNK = 512 * 1024
SOCK_BUF = 4 * 1024 * 1024
PROGRESS_EVERY = 0.2
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
IMAGE_MAGIC = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/gif": b"GIF8",
    "image/webp": b"RIFF",
}


def valid_image(data: bytes, mime) -> bool:
    if mime not in IMAGE_MAGIC or not isinstance(data, (bytes, bytearray)):
        return False
    if not (0 < len(data) <= MAX_IMAGE) or not data.startswith(IMAGE_MAGIC[mime]):
        return False
    return mime != "image/webp" or data[8:12] == b"WEBP"


def safe_filename(name) -> str:
    """去掉路径、非法字符和 Windows 保留名,防止对方用文件名做手脚。"""
    name = str(name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"/\\|?*').strip(" .")
    name = name[:120]
    if not name or name.split(".")[0].upper() in _WIN_RESERVED:
        name = "文件_" + name if name else "文件"
    return name


def _is_mid(x) -> bool:
    return isinstance(x, str) and 0 < len(x) <= 64


def clean_reply(r) -> dict | None:
    """引用回复:被引用消息的 id、发送者昵称、内容摘要。"""
    if not isinstance(r, dict) or not _is_mid(r.get("mid")):
        return None
    preview = " ".join(str(r.get("preview", "")).split())[:80]
    return {"mid": r["mid"], "nick": clean_nick(r.get("nick", "")), "preview": preview}


def clean_at(a) -> list[str]:
    """@ 的对象:身份 id(64 位十六进制)或 "all"。"""
    if not isinstance(a, list):
        return []
    out = []
    for x in a[:50]:
        if x == "all" or (isinstance(x, str) and len(x) == 64 and all(c in "0123456789abcdef" for c in x)):
            if x not in out:
                out.append(x)
    return out


def _replace_retry(src: str, dst: str, tries: int = 20) -> None:
    """改名;文件刚好被别的地方读着(比如边下边看的播放器)时等一下再试,别把下好的大文件丢了。"""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.05)


def clean_file(f) -> dict | None:
    if not isinstance(f, dict):
        return None
    fid, size = f.get("fid"), f.get("size")
    if not (isinstance(fid, str) and len(fid) == 32 and all(c in "0123456789abcdef" for c in fid)):
        return None
    if type(size) is not int or not (0 < size <= max_size_for(str(f.get("name") or ""), f.get("dir") is True)):
        return None
    out = {"fid": fid, "name": safe_filename(f.get("name")), "size": size}
    if f.get("dir") is True:                     # 打包好的文件夹:对方下载完自动解压
        out["dir"] = True
    return out


# 卡片消息(投票、抽签、骰子、游戏邀请、画板邀请)和事件(编辑、戳一戳、公告、走棋、笔迹……)
CARD_TYPES = {"poll", "draw", "dice", "game", "board"}
MAX_CARD_JSON = 16 * 1024
MAX_EVENT_JSON = 512 * 1024
ANON_FORWARD_P = 0.67          # 匿名纸条:每一跳有 2/3 的概率再随机转给别人(Crowds 协议)
ANON_MAX_HOPS = 8
ANON_VIDEO_MAX = 20 * 1024 * 1024    # 匿名纸条里的视频最大 20MB(要经过别人转交,内容直接带在纸条里)
ANON_THUMB_MAX = 96 * 1024
ANON_VIDEO_EXTS = (".mp4", ".mov", ".m4v")
CAP_ANON_MEDIA = "am"                # 在场信息里的"能力":能转交 / 显示带图片、视频的匿名纸条(2.1 起)
MY_CAPS = [CAP_ANON_MEDIA]
ANON_PLACEHOLDER = {"img": "[图片]", "gif": "[动图]", "stk": "[表情包]", "vid": "[视频]"}


def clean_anon_media(mm) -> tuple[dict, dict] | None:
    """匿名纸条附带的内容(表情包 / 图片 / 动图 / 视频)。
    返回 (原样转交用的字典, 显示用的字典);格式不对返回 None。"""
    if not isinstance(mm, dict):
        return None
    k = mm.get("k")

    def num(key: str, hi: int) -> int:
        v = mm.get(key)
        return v if type(v) is int and 0 <= v <= hi else 0
    try:
        data = C.b64d(mm.get("d")) if isinstance(mm.get("d"), str) else b""
    except (ValueError, TypeError):
        return None
    if k in ("img", "stk"):
        mime = mm.get("mime")
        if not valid_image(data, mime):
            return None
        w, h = num("w", 100000), num("h", 100000)
        return ({"k": k, "d": mm["d"], "mime": mime, "w": w, "h": h},
                {"img": data, "mime": mime, "w": w, "h": h, "sticker": k == "stk"})
    if k == "vid":
        if not (16 <= len(data) <= ANON_VIDEO_MAX) or data[4:8] != b"ftyp":
            return None
        name = safe_filename(mm.get("name"))
        if not name.lower().endswith(ANON_VIDEO_EXTS):
            name = "匿名视频.mp4"
        thumb = mm.get("thumb")
        if thumb is not None:
            try:
                tb = C.b64d(thumb) if isinstance(thumb, str) else b""
            except (ValueError, TypeError):
                tb = b""
            thumb = thumb if 0 < len(tb) <= ANON_THUMB_MAX and tb.startswith(b"\xff\xd8\xff") else None
        dur, w, h = num("dur", 48 * 3600 * 1000), num("w", 16384), num("h", 16384)
        fwd = {"k": "vid", "d": mm["d"], "name": name, "dur": dur, "w": w, "h": h}
        if thumb:
            fwd["thumb"] = thumb
        return fwd, {"vid": data, "name": name, "size": len(data), "thumb": thumb, "dur": dur, "vw": w, "vh": h}
    return None


def anon_media_wire(media: dict) -> dict | None:
    """界面给的匿名附件(原始字节)→ 网络上用的格式(base64)。"""
    if not isinstance(media, dict) or not isinstance(media.get("data"), (bytes, bytearray)):
        return None
    k = media.get("k")
    out = {"k": k, "d": C.b64e(bytes(media["data"]))}
    if k in ("img", "stk"):
        out.update({"mime": media.get("mime"), "w": int(media.get("w") or 0), "h": int(media.get("h") or 0)})
    elif k == "vid":
        out.update({"name": str(media.get("name") or "匿名视频.mp4"), "dur": int(media.get("dur") or 0),
                    "w": int(media.get("w") or 0), "h": int(media.get("h") or 0)})
        if media.get("thumb"):
            out["thumb"] = C.b64e(bytes(media["thumb"]))
    else:
        return None
    return out


def anon_placeholder(fwd: dict) -> str:
    """给还不支持的旧版本看的文字。"""
    k = fwd.get("k")
    if k == "img" and fwd.get("mime") == "image/gif":
        k = "gif"
    return f"{ANON_PLACEHOLDER.get(k, '[附件]')}(对方版本太旧看不到,升级到 2.1 以上就行)"
SKINS = {"jelly", "cloud", "candy", "mint", "galaxy", "gold", "rainbow"}


def _json_size(obj) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    except (TypeError, ValueError):
        return 1 << 30


def clean_card(x) -> dict | None:
    if not isinstance(x, dict) or x.get("type") not in CARD_TYPES or _json_size(x) > MAX_CARD_JSON:
        return None
    return x


def clean_title(v) -> str:
    """名字旁边的称号:最多 8 个字,去掉换行。"""
    return " ".join(str(v).split())[:8] if isinstance(v, str) else ""


MAX_PET_LEVEL = 50


def clean_level(v) -> int:
    """名字旁边的等级标识:1~50,其它一律不显示。"""
    return v if type(v) is int and 1 <= v <= MAX_PET_LEVEL else 0


def clean_skin(v) -> str | None:
    return v if isinstance(v, str) and v in SKINS else None


def error_detail(e: BaseException) -> str:
    """出错时给用户看的说明:错误类型 + 信息 + 最后几处出错位置(方便截图定位)。"""
    import traceback
    frames = traceback.extract_tb(e.__traceback__)[-3:]
    where = " ← ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in reversed(frames))
    return f"{type(e).__name__}: {e}" + (f"\n位置:{where}" if where else "")


def _hash_prefix(path: str, n: int, h) -> None:
    """把文件前 n 个字节算进哈希(续传时用,在线程里跑)。"""
    with open(path, "rb") as f:
        left = n
        while left > 0:
            chunk = f.read(min(4 * 1024 * 1024, left))
            if not chunk:
                raise OSError("文件比预期短")
            h.update(chunk)
            left -= len(chunk)


def clean_nick(nick) -> str:
    s = "".join(ch for ch in str(nick) if ch.isprintable()).strip()
    return s[:MAX_NICK]


def parse_target(text: str):
    """'192.168.1.20' 或 '192.168.1.20:47820' → (ip, port);无效返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    host, port = text, DEFAULT_UDP_PORT
    if text.count(":") == 1:
        host, _, p = text.partition(":")
        try:
            port = int(p)
        except ValueError:
            return None
    try:
        ip = ipaddress.IPv4Address(host.strip())
    except ValueError:
        return None
    if ip.is_unspecified or ip.is_multicast or not (0 < port < 65536):
        return None
    return str(ip), port


def local_ipv4s() -> list[str]:
    ips: set[str] = set()
    try:
        for *_, sa in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(sa[0])
    except OSError:
        pass
    # UDP connect 不会真的发包,只是让系统选出走哪个网卡
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            ips.add(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    return sorted(ip for ip in ips if not ip.startswith("127.") and ip != "0.0.0.0")


def _win_subnet_broadcasts() -> dict[str, str]:
    """Windows 下通过 GetIpAddrTable 读取每块网卡真实的 IPv4 子网掩码,算出准确的定向广播地址(支持 /16、/22 等网段)。"""
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        class MIB_IPADDRROW(ctypes.Structure):
            _fields_ = [
                ("dwAddr", wintypes.DWORD),
                ("dwIndex", wintypes.DWORD),
                ("dwMask", wintypes.DWORD),
                ("dwBCastAddr", wintypes.DWORD),
                ("dwReasmSize", wintypes.DWORD),
                ("unused1", wintypes.USHORT),
                ("wType", wintypes.USHORT),
            ]

        iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
        size = wintypes.ULONG(0)
        iphlpapi.GetIpAddrTable(None, ctypes.byref(size), False)
        if not size.value:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        if iphlpapi.GetIpAddrTable(buf, ctypes.byref(size), False) != 0:
            return {}
        count = struct.unpack_from("<I", buf.raw, 0)[0]
        row_size = ctypes.sizeof(MIB_IPADDRROW)
        out: dict[str, str] = {}
        for i in range(min(count, 128)):
            off = 4 + i * row_size
            if off + row_size > len(buf.raw):
                break
            row = MIB_IPADDRROW.from_buffer_copy(buf.raw, off)
            ip_b = struct.pack("<I", row.dwAddr)
            mask_b = struct.pack("<I", row.dwMask)
            ip_int = int.from_bytes(ip_b, "big")
            mask_int = int.from_bytes(mask_b, "big")
            if ip_int and 0 < mask_int < 0xFFFFFFFF:
                bcast_int = (ip_int & mask_int) | (~mask_int & 0xFFFFFFFF)
                ip_s = socket.inet_ntoa(ip_b)
                out[ip_s] = socket.inet_ntoa(bcast_int.to_bytes(4, "big"))
        return out
    except Exception:
        return {}


# ====================================================================== 数据结构
class Room:
    def __init__(self, ctx: C.ContextKey, name: str) -> None:
        self.ctx = ctx
        self.name = name
        self.tag = ctx.tag


class Peer:
    def __init__(self, pid: bytes) -> None:
        self.id = pid
        self.nick = ""
        self.ip: str | None = None
        self.tcp_port: int | None = None
        self.udp_port: int | None = None
        self.beacon_ctx: dict[str, float] = {}   # 上下文 → 最近一次收到 beacon 的时间
        self.beacon_ts: dict[str, int] = {}      # 上下文 → beacon 里的发送时间(防旧包重放)
        self.first_seen = time.monotonic()
        self.conn: Conn | None = None
        self.connecting = False
        self.next_try = 0.0
        self.fail_count = 0
        # 以下来自加密连接里的在场信息(可信)
        self.presence_ok = False
        self.caps: set[str] = set()              # 对方支持的新功能(在场信息里带的)
        self.in_lobby = False
        self.rooms: set[str] = set()
        self.last_proofs: set[str] = set()

    @property
    def online(self) -> bool:
        c = self.conn
        return c is not None and c.authed and not c.closed


class Conn:
    """一条已加密的 TCP 连接。"""

    def __init__(self, core: "Core", reader, writer, initiator: bool) -> None:
        self.core = core
        self.reader = reader
        self.writer = writer
        self.initiator = initiator
        self.peer_id: bytes | None = None
        self.peer_nick = ""
        self.authed = False
        self.closed = False
        self.tx: C.Cipher | None = None
        self.rx: C.Cipher | None = None
        self.lock = asyncio.Lock()
        self.last_rx = time.monotonic()
        self._parts: dict[str, dict] = {}       # 正在接收的分片消息
        self._tune(writer)
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else None
        if ip and ip.startswith("::ffff:"):
            ip = ip[7:]
        self.ip = ip

    @staticmethod
    def _tune(writer) -> None:
        """加大收发缓冲、关掉 Nagle:大文件跑满带宽,聊天消息也不会被延迟。"""
        sock = writer.get_extra_info("socket")
        try:
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCK_BUF)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCK_BUF)
        except OSError:
            pass
        try:
            writer.transport.set_write_buffer_limits(high=8 * 1024 * 1024, low=2 * 1024 * 1024)
        except Exception:
            pass

    @property
    def initiator_id(self) -> bytes | None:
        return self.core.my_id if self.initiator else self.peer_id

    async def handshake(self, expected_id: bytes | None = None, hello_ctx: C.ContextKey | None = None) -> None:
        hs = C.Handshake()
        if self.initiator:
            if hello_ctx is None:
                raise C.CryptoError("缺少共同空间")
            self.writer.write(hs.e_pub + C.hello_tag(hello_ctx, hs.e_pub))
            await self.writer.drain()
            peer_e = await self.reader.readexactly(32)
        else:
            hello = await self.reader.readexactly(32 + C.HELLO_TAG_SIZE)
            peer_e = hello[:32]
            if not C.check_hello([c for _, c in self.core._contexts()], peer_e, hello[32:]):
                raise C.CryptoError("对方不在任何共同空间里")
            self.writer.write(hs.e_pub)
            await self.writer.drain()
        send_key, recv_key, transcript = hs.derive(peer_e, self.initiator)
        self.tx, self.rx = C.Cipher(send_key), C.Cipher(recv_key)

        me = self.core.identity
        my_role, peer_role = (b"I", b"R") if self.initiator else (b"R", b"I")
        await self.send({
            "t": "auth",
            "id": C.b64e(me.pub),
            "nick": self.core.nick,
            "sig": C.b64e(me.sign(C.auth_payload(transcript, my_role))),
        })
        msg = await self.recv()
        if msg.get("t") != "auth":
            raise C.CryptoError("握手失败")
        pid = C.b64d(msg["id"])
        sig = C.b64d(msg["sig"])
        if len(pid) != 32 or pid == me.pub:
            raise C.CryptoError("身份无效")
        if not C.verify(pid, sig, C.auth_payload(transcript, peer_role)):
            raise C.CryptoError("身份签名验证失败")
        if expected_id is not None and pid != expected_id:
            raise C.CryptoError("对方身份与广播不一致")
        self.peer_id = pid
        self.peer_nick = clean_nick(msg.get("nick", ""))
        self.authed = True

    async def _send_frame(self, data: bytes) -> None:
        padded = C.pad(data)
        async with self.lock:
            if self.closed:
                raise ConnectionError("连接已关闭")
            ct = self.tx.encrypt(padded)
            try:
                self.writer.write(struct.pack(">I", len(ct)) + ct)
                await self.writer.drain()
            except (ConnectionError, OSError):
                self.close()
                raise

    async def send_binary(self, header: dict, data: bytes) -> None:
        """头部 JSON + 原始字节(文件数据不用 base64,省 1/3 流量)。"""
        h = C.canonical(header)
        await self._send_frame(b"\x01" + struct.pack(">I", len(h)) + h + data)

    async def send(self, obj: dict) -> None:
        data = C.canonical(obj)
        if len(data) <= SMALL_LIMIT:
            await self._send_frame(data)
            return
        # 大消息(图片)拆成分片,每片单独加密;分片之间别的消息可以插队,不会卡住聊天
        n = -(-len(data) // PART_SIZE)
        if n > MAX_PARTS:
            raise ValueError("消息太大")
        xid = uuid.uuid4().hex[:16]
        for i in range(n):
            part = data[i * PART_SIZE:(i + 1) * PART_SIZE]
            await self._send_frame(C.canonical({"t": "part", "x": xid, "i": i, "n": n, "d": C.b64e(part)}))

    def _on_part(self, obj: dict) -> dict | None:
        x, i, n, d = obj.get("x"), obj.get("i"), obj.get("n"), obj.get("d")
        if not (isinstance(x, str) and 0 < len(x) <= 32 and type(i) is int and type(n) is int
                and isinstance(d, str) and 1 < n <= MAX_PARTS and 0 <= i < n):
            raise C.CryptoError("分片格式错误")
        now = time.monotonic()
        for k in [k for k, v in self._parts.items() if now - v["t"] > 120]:
            del self._parts[k]
        st = self._parts.get(x)
        if st is None:
            if len(self._parts) >= MAX_PENDING_LARGE:
                raise C.CryptoError("同时接收的大消息过多")
            st = self._parts[x] = {"n": n, "got": {}, "size": 0, "t": now}
        if st["n"] != n or i in st["got"]:
            raise C.CryptoError("分片重复或不一致")
        chunk = C.b64d(d)
        st["size"] += len(chunk)
        if st["size"] > MAX_LARGE:
            raise C.CryptoError("消息超过大小上限")
        st["got"][i] = chunk
        st["t"] = now
        if len(st["got"]) < n:
            return None
        del self._parts[x]
        whole = json.loads(b"".join(st["got"][k] for k in range(n)).decode("utf-8"))
        if not isinstance(whole, dict) or whole.get("t") == "part":
            raise C.CryptoError("分片内容错误")
        return whole

    async def recv(self) -> dict:
        hdr = await self.reader.readexactly(4)
        n = struct.unpack(">I", hdr)[0]
        if n < 16 or n > MAX_FRAME:
            raise C.CryptoError("帧长度异常")
        ct = await self.reader.readexactly(n)
        plain = C.unpad(self.rx.decrypt(ct))
        if plain[:1] == b"\x01":                         # 二进制帧(文件数据)
            if len(plain) < 5:
                raise C.CryptoError("帧格式错误")
            hl = struct.unpack(">I", plain[1:5])[0]
            if 5 + hl > len(plain):
                raise C.CryptoError("帧格式错误")
            obj = json.loads(plain[5:5 + hl].decode("utf-8"))
            if isinstance(obj, dict):
                obj["_bin"] = plain[5 + hl:]
        else:
            obj = json.loads(plain.decode("utf-8"))
        if not isinstance(obj, dict):
            raise C.CryptoError("帧格式错误")
        self.last_rx = time.monotonic()
        return obj

    async def run(self) -> None:
        try:
            while not self.closed:
                obj = await self.recv()
                if obj.get("t") == "part":
                    obj = self._on_part(obj)
                    if obj is None:
                        continue
                try:
                    self.core._on_frame(self, obj)
                except Exception:
                    log.exception("处理消息出错")
        except (asyncio.IncompleteReadError, ConnectionError, OSError, C.CryptoError, ValueError):
            pass
        finally:
            self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.writer.close()
        except Exception:
            pass
        self.core._on_conn_closed(self)


class _UdpProto(asyncio.DatagramProtocol):
    def __init__(self, core: "Core") -> None:
        self.core = core

    def datagram_received(self, data, addr):
        try:
            self.core._on_datagram(data, addr)
        except Exception:
            log.exception("处理广播包出错")

    def error_received(self, exc):  # Windows 上 ICMP 端口不可达会报到这里,忽略
        pass


# ====================================================================== 核心
class Core:
    def __init__(self, on_event=None, udp_port: int = DEFAULT_UDP_PORT, tcp_port: int = DEFAULT_TCP_PORT,
                 extra_targets=None, identity: C.Identity | None = None) -> None:
        self.on_event = on_event or (lambda kind, data: None)
        self.identity = identity or C.Identity()
        self.test_upload_delay = 0.0
        self.title = ""                     # 佩戴的称号,随消息一起发出
        self.level = 0                      # 宠物等级(名字旁边的等级标识),随消息一起发出,0 = 不发
        self._anon_seen: collections.OrderedDict = collections.OrderedDict()      # 已显示的匿名纸条
        self.anon_error = ""                      # 上一次匿名纸条发不出去的原因(few = 人太少, old = 别人版本太旧)
        self.my_id = self.identity.pub
        self.nick = "匿名-" + C.short_tag(self.my_id)
        self.udp_port = udp_port
        self._tcp_pref = tcp_port
        self.tcp_port: int | None = None
        self.extra_targets = [tuple(t) for t in (extra_targets or [])]   # 测试用:额外的单播目标
        self.manual_targets: set[tuple[str, int]] = set()
        self.lobby_enabled = True
        self.rooms: dict[str, Room] = {}
        self.peers: dict[bytes, Peer] = {}
        self.beacon_ips: dict[str, float] = {}
        self.local_ips: list[str] = []
        self._send_socks: dict[str, socket.socket] = {}
        self._fallback_sock: socket.socket | None = None
        self._reply_rl: dict[tuple, float] = {}
        self._seen: collections.OrderedDict = collections.OrderedDict()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.pool = None                    # 自己的后台线程池(start 时建)
        self._thread: threading.Thread | None = None
        self._server = None
        self._udp_transport = None
        self._tasks: list[asyncio.Task] = []
        self.running = False
        self.start_error: str | None = None
        self.offers: dict[str, dict] = {}                 # 我发出的文件 fid → 路径等
        self.downloads: dict[str, dict] = {}              # 正在下载的文件
        self.uploads: dict[tuple, asyncio.Task] = {}      # (对方 id, fid) → 发送任务

    # ------------------------------------------------------------ 只读信息(任意线程)
    @property
    def id_hex(self) -> str:
        return self.my_id.hex()

    @property
    def tag(self) -> str:
        return C.short_tag(self.my_id)

    @property
    def fingerprint(self) -> str:
        return C.fingerprint(self.my_id)

    def safety_number(self, peer_hex: str) -> str:
        return C.safety_number(self.my_id, bytes.fromhex(peer_hex))

    def self_info(self) -> dict:
        return {
            "id": self.id_hex, "nick": self.nick, "tag": self.tag, "fingerprint": self.fingerprint,
            "tcp_port": self.tcp_port, "udp_port": self.udp_port, "ips": list(self.local_ips),
            "lobby": self.lobby_enabled,
        }

    # ------------------------------------------------------------ 生命周期
    def start(self, nick: str | None = None, lobby: bool = True, timeout: float = 10.0) -> bool:
        if nick:
            self.nick = clean_nick(nick) or self.nick
        self.lobby_enabled = bool(lobby)
        self.loop = asyncio.SelectorEventLoop()
        # 后台线程池由自己管理,每次都显式传给 run_in_executor,不用 asyncio 的默认线程池:
        # Python 3.15 打包成 exe 后,默认线程池那条路会碰到"延迟导入"的占位对象(见 compat.py)
        compat.fix_lazy_imports()
        from concurrent.futures.thread import ThreadPoolExecutor
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="miyu-work")
        self.loop.set_exception_handler(self._loop_error)
        ready = threading.Event()
        self._thread = threading.Thread(target=self._thread_main, args=(ready,), name="miyu-core", daemon=True)
        self._thread.start()
        ready.wait(timeout)
        return self.running and self.start_error is None

    def stop(self, timeout: float = 3.0) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        fut = self._submit(self._shutdown())
        if fut is not None:
            try:
                fut.result(timeout)
            except Exception:
                pass
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except RuntimeError:
            pass
        if self._thread:
            self._thread.join(timeout)

    def _loop_error(self, loop, context: dict) -> None:
        """后台任务里没被处理的错误:交给界面的出错报告。对方断线、超时这类正常情况只记日志。"""
        exc = context.get("exception")
        if exc is None or errors.is_quiet(exc):
            log.debug("后台: %s", context.get("message"))
            return
        log.error("后台出错: %s", exc)
        self._emit("error", {"where": "网络模块", "text": errors.format_exception(exc),
                             "sig": errors.signature(exc)})

    def _thread_main(self, ready: threading.Event) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._startup())
        except Exception as e:
            self.start_error = f"{type(e).__name__}: {e}"
            log.error("启动失败: %s", self.start_error)
            ready.set()
            self._close_sockets()
            self.loop.close()
            if self.pool is not None:
                self.pool.shutdown(wait=False)
            return
        ready.set()
        try:
            self.loop.run_forever()
        finally:
            pending = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._close_sockets()
            self.loop.close()
            if self.pool is not None:
                self.pool.shutdown(wait=False)

    async def _startup(self) -> None:
        try:
            self._server = await asyncio.start_server(self._on_inbound, "0.0.0.0", self._tcp_pref)
        except OSError:
            self._server = await asyncio.start_server(self._on_inbound, "0.0.0.0", 0)  # 端口被占用就随机
        self.tcp_port = self._server.sockets[0].getsockname()[1]

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind(("", self.udp_port))
        except OSError:
            sock.close()
            raise OSError(f"UDP 端口 {self.udp_port} 被占用")
        sock.setblocking(False)
        self._udp_transport, _ = await self.loop.create_datagram_endpoint(lambda: _UdpProto(self), sock=sock)

        fb = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        fb.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        fb.setblocking(False)
        self._fallback_sock = fb

        self.running = True
        self._refresh_ifaces(emit=False)
        self._tasks = [self.loop.create_task(self._beacon_loop()), self.loop.create_task(self._maint_loop())]
        self._emit("ready", self.self_info())

    async def _shutdown(self) -> None:
        for fid in list(self.downloads):
            dl = self.downloads.pop(fid)
            try:
                dl["f"].close()
                os.remove(dl["part"])
            except OSError:
                pass
        conns = [p.conn for p in self.peers.values() if p.conn and not p.conn.closed and p.conn.authed]
        if conns:
            try:
                await asyncio.wait_for(asyncio.gather(*(c.send({"t": "bye"}) for c in conns),
                                                      return_exceptions=True), 1.0)
            except asyncio.TimeoutError:
                pass
        self.running = False
        for c in conns:
            c.close()
        if self._server:
            self._server.close()
        if self._udp_transport:
            self._udp_transport.close()
        for t in self._tasks:
            t.cancel()

    def _close_sockets(self) -> None:
        for s in list(self._send_socks.values()) + ([self._fallback_sock] if self._fallback_sock else []):
            try:
                s.close()
            except OSError:
                pass
        self._send_socks.clear()
        self._fallback_sock = None

    # ------------------------------------------------------------ 线程安全的操作接口
    def _submit(self, coro):
        if self.loop is None or self.loop.is_closed() or not self.running:
            coro.close()
            return None
        try:
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        except RuntimeError:
            coro.close()
            return None

    def _call(self, fn, *args) -> None:
        if self.loop is None or self.loop.is_closed() or not self.running:
            return
        try:
            self.loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            pass

    def set_nick(self, nick: str) -> bool:
        n = clean_nick(nick)
        if not n:
            return False
        self._call(self._set_nick, n)
        return True

    def set_lobby(self, enabled: bool) -> None:
        self._call(self._set_lobby, bool(enabled))

    def join_room(self, passphrase: str, name: str = "") -> None:
        self._submit(self._join_room(passphrase, clean_nick(name)))

    def leave_room(self, tag: str) -> None:
        self._call(self._leave_room, tag)

    def add_manual_target(self, text: str) -> bool:
        t = parse_target(text)
        if t is None:
            return False
        self._call(self._add_manual_target, t)
        return True

    @staticmethod
    def _extras(extra: dict, reply=None, at=None) -> dict:
        r = clean_reply(reply)
        if r:
            extra["reply"] = r
        a = clean_at(at)
        if a:
            extra["at"] = a
        return extra

    def send_text(self, scope: str, target: str | None, text: str, burn: int = 0, reply=None, at=None,
                  skin: str | None = None) -> str | None:
        text = str(text)[:MAX_TEXT]
        if not text.strip():
            return None
        extra = {"text": text}
        if clean_skin(skin):
            extra["skin"] = skin
        return self._queue_msg(scope, target, self._extras(extra, reply, at), burn)

    def send_card(self, scope: str, target: str | None, card: dict, text: str = "") -> str | None:
        """卡片消息:投票、抽签、骰子、游戏邀请、画板邀请。"""
        card = clean_card(card)
        if card is None:
            return None
        return self._queue_msg(scope, target, {"text": str(text)[:200], "x": card}, 0)

    def send_event(self, scope: str, target: str | None, name: str, data: dict, to: str | None = None) -> bool:
        """不显示成消息的事件(编辑、戳一戳、公告、投票、走棋、笔迹……),按会话加密送达。
        to=某人的 id 时只发给他(仍然用这个会话的密钥加密)。"""
        if not isinstance(name, str) or not (0 < len(name) <= 24) or not isinstance(data, dict):
            return False
        if _json_size(data) > MAX_EVENT_JSON:
            return False
        base = {"mid": uuid.uuid4().hex, "kind": "ev", "ev": name, "d": data}
        return self._submit(self._deliver(scope, target, base, only=to)) is not None

    def send_anon(self, scope: str, target: str | None, text: str, media: dict | None = None) -> str | None:
        """匿名纸条:先随机交给群里另一个人,每个人以 2/3 概率继续随机转交,否则替大家发出。
        收到的人只知道是谁最后转发的,而转发的人也分不清上一个人是作者还是转发者。
        media = 附带的表情包 / 图片 / 动图 / 视频(原始字节,见 anon_media_wire),内容跟着纸条一起转交。
        失败返回 None,原因写在 self.anon_error 里。"""
        self.anon_error = ""
        text = str(text)[:MAX_TEXT]
        fwd = None
        if media is not None:
            wire = anon_media_wire(media)
            cleaned = clean_anon_media(wire) if wire else None
            if cleaned is None:
                self.anon_error = "附件格式不对或太大"
                return None
            fwd = cleaned[0]
        if (not text.strip() and fwd is None) or scope not in ("lobby", "room"):
            self.anon_error = "纸条是空的"
            return None
        peers = self._group_peers(scope, target)
        if len(peers) < 2:                                    # 算上自己至少 3 个人才谈得上匿名
            self.anon_error = "few"
            return None
        if fwd is not None and len([p for p in peers if CAP_ANON_MEDIA in p.caps]) < 2:
            self.anon_error = "old"                           # 带图片 / 视频的纸条只在新版本之间转交
            return None
        nid = uuid.uuid4().hex
        self._anon_seen[nid] = None
        # 初始跳数从随机值(1~3)起步,避免第一跳通过 hop==0 识别出原作者
        d = {"id": nid, "text": text, "hop": _SYS_RNG.randint(1, 3)}
        if fwd is not None:
            d["m"] = fwd
        if self._submit(self._anon_forward(scope, target, d, exclude=None)) is None:
            self.anon_error = "发送失败"
            return None
        return nid

    def send_image(self, scope: str, target: str | None, data: bytes, mime: str, burn: int = 0,
                   w: int = 0, h: int = 0, reply=None, sticker: bool = False) -> str | None:
        """发送图片(data 是已经压缩好的 JPEG/PNG 字节)。sticker=True 表示表情包(显示得小一些)。"""
        if not valid_image(data, mime):
            return None
        extra = {"text": "", "img": bytes(data), "mime": mime, "w": max(0, int(w)), "h": max(0, int(h))}
        if sticker:
            extra["stk"] = 1
        return self._queue_msg(scope, target, self._extras(extra, reply), burn)

    def send_file(self, scope: str, target: str | None, path: str, reply=None, folder: bool = False):
        """发出文件邀请,对方点"下载"时才真正传输。返回 (mid, fid, 文件信息) 或 None。"""
        try:
            if not os.path.isfile(path):
                return None
            size = os.path.getsize(path)
        except OSError:
            return None
        if not (0 < size <= max_size_for(path, folder)):
            return None
        fid = uuid.uuid4().hex
        info = {"fid": fid, "name": safe_filename(os.path.basename(path)), "size": size}
        if folder:
            info["dir"] = True
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        self.offers[fid] = {"path": path, "name": info["name"], "size": size, "scope": scope, "target": target,
                            "mtime": mtime, "time": time.time()}
        mid = self._queue_msg(scope, target, self._extras({"text": "", "file": info}, reply), 0)
        if mid is None:
            self.offers.pop(fid, None)
            return None
        self.offers[fid]["mid"] = mid
        return mid, fid, info

    def recall(self, scope: str, target: str | None, mid: str) -> str | None:
        """撤回自己发的消息(对方在线时立即从对方界面删除)。"""
        for fid, o in list(self.offers.items()):
            if o.get("mid") == mid:
                self.offers.pop(fid, None)
                self._call(self._cancel_uploads, fid)
        return self._queue_msg(scope, target, {"kind": "recall", "target": mid}, 0)

    def send_typing(self, peer_hex: str) -> None:
        self._submit(self._send_to(peer_hex, {"t": "typing"}))

    def send_read(self, peer_hex: str, mids) -> None:
        mids = [m for m in (mids or []) if _is_mid(m)][:200]
        if mids:
            self._submit(self._send_to(peer_hex, {"t": "read", "mids": mids}))

    def download_file(self, peer_hex: str, fid: str, dest: str, size: int, resume: bool = True) -> bool:
        """下载文件。resume=True 时如果有上次没下完的 .part,从断点接着下。"""
        if not dest or not isinstance(fid, str):
            return False
        return self._submit(self._start_download(peer_hex, fid, dest, int(size), resume)) is not None

    def pause_file(self, fid: str) -> None:
        """暂停下载:保留已下载的部分,之后可以继续。"""
        self._call(self._pause_file, fid)

    def cancel_file(self, fid: str) -> None:
        self._call(self._cancel_file, fid)

    def restore_room(self, master: bytes, name: str) -> None:
        """用保存的群密钥恢复暗号群(不需要再输入暗号)。"""
        self._call(self._restore_room, bytes(master), clean_nick(name))

    def restore_offers(self, offers: dict) -> None:
        """恢复上次发出、对方还没下载的文件邀请(文件没被改动才有效)。"""
        for fid, o in (offers or {}).items():
            if isinstance(o, dict) and isinstance(fid, str) and o.get("path"):
                self.offers.setdefault(fid, dict(o))

    def _queue_msg(self, scope: str, target, extra: dict, burn) -> str | None:
        try:
            burn = max(0, min(int(burn), MAX_BURN))
        except (TypeError, ValueError):
            burn = 0
        mid = uuid.uuid4().hex
        if self._submit(self._send_msg(scope, target, mid, extra, burn)) is None:
            return None
        return mid

    # ------------------------------------------------------------ 事件
    def _emit(self, kind: str, data: dict) -> None:
        try:
            self.on_event(kind, data)
        except Exception:
            log.exception("事件回调出错")

    def _peer_info(self, p: Peer) -> dict:
        return {
            "id": p.id.hex(), "nick": p.nick or ("匿名-" + C.short_tag(p.id)), "tag": C.short_tag(p.id),
            "online": p.online, "lobby": p.online and p.in_lobby, "rooms": sorted(p.rooms) if p.online else [],
        }

    def _emit_peer(self, p: Peer) -> None:
        self._emit("peer", self._peer_info(p))

    # ------------------------------------------------------------ 网卡与发包
    def _refresh_ifaces(self, emit: bool = True) -> None:
        ips = local_ipv4s()
        self._bcast_map = _win_subnet_broadcasts()
        if ips == self.local_ips and set(ips) == set(self._send_socks):
            return
        for ip in list(self._send_socks):
            if ip not in ips:
                try:
                    self._send_socks.pop(ip).close()
                except OSError:
                    pass
        for ip in ips:
            if ip in self._send_socks:
                continue
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind((ip, 0))      # 绑定到具体网卡,保证每块网卡都能广播出去
                s.setblocking(False)
                self._send_socks[ip] = s
            except OSError:
                s.close()
        changed = ips != self.local_ips
        self.local_ips = ips
        if emit and changed:
            self._emit("self", self.self_info())

    def _broadcast(self, pkt: bytes) -> None:
        port = self.udp_port
        if not self._send_socks and self._fallback_sock:
            try:
                self._fallback_sock.sendto(pkt, ("255.255.255.255", port))
            except OSError:
                pass
        bcasts = getattr(self, "_bcast_map", None) or {}
        for ip, s in list(self._send_socks.items()):
            dsts = {"255.255.255.255", ip.rsplit(".", 1)[0] + ".255"}
            if ip in bcasts:
                dsts.add(bcasts[ip])
            for dst in dsts:
                try:
                    s.sendto(pkt, (dst, port))
                except OSError:
                    pass

    def _unicast(self, pkt: bytes, addr) -> None:
        if self._fallback_sock is None:
            return
        try:
            self._fallback_sock.sendto(pkt, addr)
        except OSError:
            pass

    def _contexts(self) -> list[tuple[str, C.ContextKey]]:
        out = []
        if self.lobby_enabled:
            out.append((C.LOBBY_TAG, C.LOBBY))
        out.extend((r.tag, r.ctx) for r in self.rooms.values())
        return out

    def _beacon_for(self, ctx: C.ContextKey) -> bytes:
        return C.seal_beacon(ctx, self.identity, {
            "v": 1, "n": self.nick, "tp": self.tcp_port, "up": self.udp_port, "ts": int(time.time()),
        })

    def _send_beacons(self, only: C.ContextKey | None = None) -> None:
        for _key, ctx in self._contexts():
            if only is not None and ctx is not only:
                continue
            pkt = self._beacon_for(ctx)
            self._broadcast(pkt)
            for t in self.manual_targets:
                self._unicast(pkt, t)
            for t in self.extra_targets:
                self._unicast(pkt, t)

    async def _beacon_loop(self) -> None:
        while self.running:
            try:
                self._send_beacons()
            except Exception:
                log.exception("发送广播出错")
            await asyncio.sleep(BEACON_INTERVAL + random.uniform(-0.6, 0.6))

    # ------------------------------------------------------------ 收到发现广播
    def _on_datagram(self, data: bytes, addr) -> None:
        if len(data) != C.BEACON_WIRE_SIZE or not self.running:
            return
        for key, ctx in self._contexts():
            body = C.open_beacon(ctx, data)
            if body is not None:
                self._on_beacon(key, ctx, body, addr)
                return

    def _on_beacon(self, key: str, ctx: C.ContextKey, body: dict, addr) -> None:
        pid = body["id"]
        if pid == self.my_id:
            return
        try:
            tp, up, ts = int(body["tp"]), int(body.get("up", DEFAULT_UDP_PORT)), int(body.get("ts", 0))
        except (KeyError, TypeError, ValueError):
            return
        if not (0 < tp < 65536 and 0 < up < 65536) or abs(time.time() - ts) > 86400:
            return
        p = self.peers.get(pid)
        if p is None:
            if len(self.peers) >= MAX_PEERS:
                return
            p = Peer(pid)
            self.peers[pid] = p
        if ts < p.beacon_ts.get(key, 0):
            return                                   # 旧包重放,丢弃
        now = time.monotonic()
        p.beacon_ts[key] = ts
        is_new = now - p.beacon_ctx.get(key, -1e9) > BEACON_FRESH
        p.beacon_ctx[key] = now
        p.ip, p.tcp_port, p.udp_port = addr[0], tp, up
        if not p.nick:
            p.nick = clean_nick(body.get("n", ""))
        self.beacon_ips[addr[0]] = now
        if is_new:
            # 回一个单播 beacon,让对方立刻发现我(广播只通一个方向时也能连上)
            rl = (addr[0], key)
            if now - self._reply_rl.get(rl, -1e9) > 5:
                self._reply_rl[rl] = now
                self._unicast(self._beacon_for(ctx), (addr[0], up))
        self._maybe_connect(p)

    def _shared_beacon_ctx(self, p: Peer) -> C.ContextKey | None:
        """从对方最近的广播里,找一个我们共同所在的空间(优先暗号群)。"""
        now = time.monotonic()
        mine = dict(self._contexts())
        best = None
        for k, t in p.beacon_ctx.items():
            if k in mine and now - t < BEACON_FRESH:
                if k != C.LOBBY_TAG:
                    return mine[k]
                best = mine[k]
        return best

    def _shares_beacon_ctx(self, p: Peer) -> bool:
        return self._shared_beacon_ctx(p) is not None

    def _shares_context(self, p: Peer) -> bool:
        return (self.lobby_enabled and p.in_lobby) or bool(p.rooms)

    # ------------------------------------------------------------ 建立连接
    def _maybe_connect(self, p: Peer) -> None:
        if not self.running or p.online or p.connecting or p.ip is None or p.tcp_port is None:
            return
        now = time.monotonic()
        if now < p.next_try or not self._shares_beacon_ctx(p):
            return
        # 约定 ID 小的一方主动连;对方 6 秒还没连过来,另一方再主动连
        if self.my_id < p.id or now - p.first_seen > 6.0:
            p.connecting = True
            self.loop.create_task(self._connect(p))

    async def _connect(self, p: Peer) -> None:
        writer = None
        try:
            ctx = self._shared_beacon_ctx(p)
            if ctx is None:
                raise ConnectionError("没有共同空间")
            reader, writer = await asyncio.wait_for(asyncio.open_connection(p.ip, p.tcp_port), 5)
            conn = Conn(self, reader, writer, initiator=True)
            await asyncio.wait_for(conn.handshake(expected_id=p.id, hello_ctx=ctx), HANDSHAKE_TIMEOUT)
        except Exception as e:
            log.debug("连接 %s 失败: %r", p.ip, e)
            if writer is not None:
                writer.close()
            p.fail_count += 1
            p.next_try = time.monotonic() + min(30.0, 3.0 * 2 ** min(p.fail_count, 4))
            return
        finally:
            p.connecting = False
        p.fail_count = 0
        if self._adopt(conn):
            self.loop.create_task(conn.run())

    def _ip_allowed(self, ip: str | None) -> bool:
        """只接受发过有效广播的 IP(或手动添加的 IP)连进来,端口扫描器直接断开。"""
        if not ip:
            return False
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        if any(t[0] == ip for t in self.manual_targets):
            return True
        t = self.beacon_ips.get(ip)
        return t is not None and time.monotonic() - t < 120

    async def _on_inbound(self, reader, writer) -> None:
        peer = writer.get_extra_info("peername")
        if not self.running or not self._ip_allowed(peer[0] if peer else None):
            writer.close()
            return
        conn = Conn(self, reader, writer, initiator=False)
        try:
            await asyncio.wait_for(conn.handshake(), HANDSHAKE_TIMEOUT)
        except Exception as e:
            log.debug("入站握手失败: %r", e)
            writer.close()
            return
        if self._adopt(conn):
            await conn.run()

    def _adopt(self, conn: Conn) -> bool:
        """握手成功的连接登记到对应的人身上;同一个人有两条连接时按固定规则留一条。"""
        if not self.running:
            conn.close()
            return False
        pid = conn.peer_id
        p = self.peers.get(pid)
        if p is None:
            if len(self.peers) >= MAX_PEERS:
                conn.close()
                return False
            p = Peer(pid)
            self.peers[pid] = p
        old = p.conn
        if old is not None and not old.closed and old.authed:
            pref = min(self.my_id, pid)
            if old.initiator_id == pref and conn.initiator_id != pref:
                conn.close()
                return False
            p.conn = conn
            old.close()          # 已不是 p.conn,不会触发离线
        else:
            p.conn = conn
            p.presence_ok, p.in_lobby, p.rooms, p.last_proofs = False, False, set(), set()
        if conn.ip:
            p.ip = conn.ip
        if conn.peer_nick:
            p.nick = conn.peer_nick
        self.loop.create_task(self._send_presence(p))
        self._emit_peer(p)
        return True

    def _on_conn_closed(self, conn: Conn) -> None:
        if conn.peer_id is None or not self.running:
            return
        p = self.peers.get(conn.peer_id)
        if p is None or p.conn is not conn:
            return
        p.conn = None
        p.presence_ok, p.in_lobby, p.rooms = False, False, set()
        for fid, dl in list(self.downloads.items()):
            if dl["peer"] == p.id:
                self._fail_download(fid, "连接断开", keep_part=True)
        for (pid, fid), task in list(self.uploads.items()):
            if pid == p.id:
                task.cancel()
        now = time.monotonic()
        p.first_seen = now
        p.next_try = max(p.next_try, now + 1.0)
        self._emit_peer(p)

    # ------------------------------------------------------------ 在场信息
    def _presence_obj(self, p: Peer) -> dict:
        proofs = [C.presence_proof(r.ctx, self.my_id, p.id) for r in self.rooms.values()]
        while len(proofs) < 4 or len(proofs) % 4:          # 补随机数,隐藏"在几个群"
            proofs.append(C.random_proof())
        _SYS_RNG.shuffle(proofs)
        return {"t": "presence", "nick": self.nick, "lobby": self.lobby_enabled, "rooms": proofs, "cap": MY_CAPS}

    async def _send_presence(self, p: Peer) -> None:
        c = p.conn
        if c is None or c.closed:
            return
        try:
            await c.send(self._presence_obj(p))
        except Exception:
            c.close()

    def _broadcast_presence(self) -> None:
        for p in list(self.peers.values()):
            if p.online:
                self.loop.create_task(self._send_presence(p))

    def _rooms_from_proofs(self, p: Peer) -> set[str]:
        return {r.tag for r in self.rooms.values() if C.presence_proof(r.ctx, p.id, self.my_id) in p.last_proofs}

    def _on_presence(self, p: Peer, obj: dict) -> None:
        nick = clean_nick(obj.get("nick", "")) or p.nick
        lobby = bool(obj.get("lobby"))
        proofs = obj.get("rooms")
        p.last_proofs = {x for x in proofs[:64] if isinstance(x, str)} if isinstance(proofs, list) else set()
        caps = obj.get("cap")
        p.caps = {x for x in caps[:16] if isinstance(x, str) and len(x) <= 8} if isinstance(caps, list) else set()
        rooms = self._rooms_from_proofs(p)
        changed = (nick != p.nick or lobby != p.in_lobby or rooms != p.rooms or not p.presence_ok)
        p.nick, p.in_lobby, p.rooms, p.presence_ok = nick, lobby, rooms, True
        for k in list(p.beacon_ctx):                        # 以加密通道里的信息为准
            if (k == C.LOBBY_TAG and not lobby) or (k != C.LOBBY_TAG and k not in rooms):
                p.beacon_ctx.pop(k, None)
        if not self._shares_context(p):
            p.next_try = time.monotonic() + 5.0
            p.conn.close()
            return
        if changed:
            self._emit_peer(p)

    def _drop_unshared(self) -> None:
        now = time.monotonic()
        for p in list(self.peers.values()):
            if p.online and p.presence_ok and not self._shares_context(p):
                p.next_try = now + 5.0
                p.conn.close()

    # ------------------------------------------------------------ 收到加密帧
    def _on_frame(self, conn: Conn, obj: dict) -> None:
        p = self.peers.get(conn.peer_id)
        if p is None:
            return
        t = obj.get("t")
        if t == "presence":
            if p.conn is conn:
                self._on_presence(p, obj)
        elif t == "msg":
            self._on_msg(p, obj)
        elif t == "typing":
            self._emit("typing", {"peer": p.id.hex()})
        elif t == "read":
            mids = obj.get("mids")
            if isinstance(mids, list):
                self._emit("read", {"peer": p.id.hex(), "mids": [m for m in mids[:200] if _is_mid(m)]})
        elif t == "file_req":
            self._on_file_req(p, obj)
        elif t == "file_chunk":
            self._on_file_chunk(p, obj)
        elif t == "file_done":
            self._on_file_done(p, obj)
        elif t in ("file_err", "file_cancel"):
            self._on_file_stop(p, obj, t)
        elif t == "bye":
            p.beacon_ctx.clear()
            conn.close()

    def _on_msg(self, p: Peer, obj: dict) -> None:
        scope = obj.get("scope")
        room_tag = None
        if scope == "room":
            blob = obj.get("blob")
            if not isinstance(blob, str):
                return
            fields = None
            for r in self.rooms.values():
                fields = C.open_room_msg(r.ctx, blob)
                if fields is not None:
                    room_tag = r.tag
                    break
            if fields is None:
                return
        elif scope == "lobby":
            if not (self.lobby_enabled and p.in_lobby):
                return
            fields = obj
        elif scope == "dm":
            fields = obj
        else:
            return
        mid = fields.get("mid")
        if not _is_mid(mid):
            return
        key = (p.id, mid)
        if key in self._seen:
            return
        base = {"scope": scope, "room": room_tag, "peer": p.id.hex(), "nick": p.nick or ("匿名-" + C.short_tag(p.id)),
                "tag": C.short_tag(p.id), "mid": mid}
        kind = fields.get("kind", "msg")
        if kind == "recall":
            target = fields.get("target")
            if not _is_mid(target):
                return
            self._remember(key)
            self._emit("recall", {**base, "target": target})
            return
        if kind == "ev":
            name, d = fields.get("ev"), fields.get("d")
            if not isinstance(name, str) or not (0 < len(name) <= 24) or not isinstance(d, dict):
                return
            self._remember(key)
            if name in ("anon_fwd", "anon"):
                self._on_anon(p, scope, room_tag, name, d)
                return
            self._emit("ev", {**base, "ev": name, "d": d})
            return
        if kind != "msg":
            return
        text = fields.get("text", "")
        if not isinstance(text, str):
            return
        image = mime = None
        w = h = 0
        file = None
        if fields.get("img") is not None:
            mime = fields.get("mime")
            try:
                image = C.b64d(fields["img"])
                w, h = max(0, min(int(fields.get("w", 0)), 100000)), max(0, min(int(fields.get("h", 0)), 100000))
            except (ValueError, TypeError, AttributeError):
                return
            if not valid_image(image, mime):
                return
        elif fields.get("file") is not None:
            file = clean_file(fields.get("file"))
            if file is None:
                return
        card = clean_card(fields.get("x")) if fields.get("x") is not None else None
        if fields.get("x") is not None and card is None:
            return
        if image is None and file is None and card is None and not text.strip():
            return
        self._remember(key)
        try:
            burn = max(0, min(int(fields.get("burn", 0)), MAX_BURN))
        except (TypeError, ValueError):
            burn = 0
        if file is not None:
            burn = 0                                   # 文件不支持阅后即焚
        self._emit("message", {
            **base, "text": text[:MAX_TEXT], "burn": burn, "time": time.time(),
            "img": image, "mime": mime, "w": w, "h": h, "file": file, "sticker": bool(image and fields.get("stk")),
            "reply": clean_reply(fields.get("reply")), "at": clean_at(fields.get("at")),
            "card": card, "skin": clean_skin(fields.get("skin")), "title": clean_title(fields.get("ttl")),
            "level": clean_level(fields.get("lv")),
        })

    # ---- 匿名纸条
    def _group_peers(self, scope: str, target) -> list[Peer]:
        if scope == "lobby":
            return [p for p in self.peers.values() if p.online and p.in_lobby] if self.lobby_enabled else []
        if scope == "room" and target in self.rooms:
            return [p for p in self.peers.values() if p.online and target in p.rooms]
        return []

    async def _anon_forward(self, scope: str, target, d: dict, exclude: Peer | None) -> None:
        peers = self._group_peers(scope, target)
        if d.get("m") is not None:                            # 带附件:只交给能处理的新版本
            peers = [p for p in peers if CAP_ANON_MEDIA in p.caps]
        choices = [p for p in peers if p is not exclude] or peers
        if not choices:
            if d.get("hop", 0) > 0:                           # 转不出去了:由我替作者发出
                await self._anon_deliver(scope, target, d)
                self._anon_show(scope, target if scope == "room" else None, d["id"], d["text"],
                                clean_anon_media(d.get("m")))
            return
        nxt = _SYS_RNG.choice(choices)
        await self._deliver(scope, target, {"mid": uuid.uuid4().hex, "kind": "ev", "ev": "anon_fwd", "d": d},
                            only=nxt.id.hex())

    async def _anon_deliver(self, scope: str, target, d: dict) -> None:
        """替作者把纸条发给群里所有人(包括作者本人)。附件只发给新版本,旧版本收到一句文字说明。"""
        mid = uuid.uuid4().hex
        fwd = d.get("m")
        full = {"id": d["id"], "text": d["text"]}
        if fwd is None:
            await self._deliver(scope, target, {"mid": mid, "kind": "ev", "ev": "anon", "d": full})
            return
        full["m"] = fwd
        lite = {"id": d["id"], "text": (d["text"] + "\n" if d["text"].strip() else "") + anon_placeholder(fwd)}
        for p in self._group_peers(scope, target):
            body = full if CAP_ANON_MEDIA in p.caps else lite
            await self._deliver(scope, target, {"mid": mid, "kind": "ev", "ev": "anon", "d": body}, only=p.id.hex())

    def _on_anon(self, p: Peer, scope: str, room_tag, name: str, d: dict) -> None:
        nid, text, hop = d.get("id"), d.get("text"), d.get("hop", 0)
        if not (_is_mid(nid) and isinstance(text, str) and type(hop) is int):
            return
        media = None
        if d.get("m") is not None:
            media = clean_anon_media(d.get("m"))
            if media is None:
                return
        if not text.strip() and media is None:
            return
        target = room_tag if scope == "room" else None
        if scope not in ("lobby", "room"):
            return
        text = text[:MAX_TEXT]
        if name == "anon_fwd":                      # 同一张纸条可能被随机转回来,不去重,靠跳数上限结束
            nd = {"id": nid, "text": text, "hop": hop + 1}
            if media is not None:
                nd["m"] = media[0]
            if hop < ANON_MAX_HOPS and _SYS_RNG.random() < ANON_FORWARD_P:
                self.loop.create_task(self._anon_forward(scope, target, nd, exclude=p))
            else:                                   # 由我替作者发给群里所有人(包括作者本人)
                self.loop.create_task(self._anon_deliver(scope, target, nd))
                self._anon_show(scope, room_tag, nid, text, media)
            return
        self._anon_show(scope, room_tag, nid, text, media)

    def _anon_show(self, scope: str, room_tag, nid: str, text: str, media: tuple | None = None) -> None:
        if nid in self._anon_seen:
            return
        self._anon_seen[nid] = None
        if len(self._anon_seen) > 2000:
            self._anon_seen.popitem(last=False)
        msg = {"scope": scope, "room": room_tag, "peer": "", "nick": "匿名纸条", "tag": "", "mid": nid,
               "text": text, "burn": 0, "time": time.time(), "img": None, "mime": None, "w": 0, "h": 0,
               "file": None, "sticker": False, "reply": None, "at": [], "card": None, "skin": None, "anon": True}
        show = media[1] if media else None
        if show and "img" in show:
            msg.update({"img": show["img"], "mime": show["mime"], "w": show["w"], "h": show["h"],
                        "sticker": show["sticker"]})
        elif show and "vid" in show:
            f = {"fid": nid, "name": show["name"], "size": show["size"], "dur": show["dur"], "vw": show["vw"],
                 "vh": show["vh"], "anon": True, "probed": True}
            if show.get("thumb"):
                f["thumb"] = show["thumb"]
            msg.update({"file": f, "vid": show["vid"]})
        self._emit("message", msg)

    def _remember(self, key) -> None:
        self._seen[key] = None
        if len(self._seen) > 5000:
            self._seen.popitem(last=False)

    # ------------------------------------------------------------ 定向发送 / 文件传输
    def _peer_by_hex(self, peer_hex) -> Peer | None:
        try:
            return self.peers.get(bytes.fromhex(peer_hex))
        except (TypeError, ValueError):
            return None

    async def _send_to(self, peer_hex, obj: dict) -> None:
        p = self._peer_by_hex(peer_hex)
        if p is not None and p.online:
            try:
                await p.conn.send(obj)
            except Exception:
                pass

    async def _safe_send(self, p: Peer, obj: dict) -> None:
        c = p.conn
        if c is not None and not c.closed and c.authed:
            try:
                await c.send(obj)
            except Exception:
                pass

    def _may_download(self, p: Peer, offer: dict) -> bool:
        scope, target = offer["scope"], offer["target"]
        if scope == "dm":
            return target == p.id.hex()
        if scope == "lobby":
            return self.lobby_enabled and p.in_lobby
        if scope == "room":
            return target in self.rooms and target in p.rooms
        if scope == "any":                       # 软件更新包:任何连上的人都可以取(对方会验签)
            return True
        return False

    # ---- 接收方
    async def _start_download(self, peer_hex: str, fid: str, dest: str, size: int, resume: bool = True) -> None:
        if fid in self.downloads:
            return
        p = self._peer_by_hex(peer_hex)
        if p is None or not p.online:
            self._emit("file_done", {"fid": fid, "ok": False, "error": "对方不在线", "paused": True})
            return
        part = dest + ".part"
        offset = 0
        try:
            if resume and os.path.exists(part):
                offset = os.path.getsize(part)
                if offset > size:
                    offset = 0
        except OSError:
            offset = 0
        h = hashlib.sha256()
        if offset:
            try:
                await self.loop.run_in_executor(self.pool, _hash_prefix, part, offset, h)
            except OSError:
                offset, h = 0, hashlib.sha256()
        try:
            f = open(part, "ab" if offset else "wb")
            if offset:
                f.truncate(offset)
        except OSError as e:
            self._emit("file_done", {"fid": fid, "ok": False, "error": f"无法写入:{e.strerror or e}"})
            return
        self.downloads[fid] = {"peer": p.id, "dest": dest, "part": part, "f": f, "size": size, "done": offset,
                               "next": 0, "hash": h, "last": 0.0, "t": time.monotonic()}
        self._emit("file_progress", {"fid": fid, "done": offset, "total": size, "dir": "down", "resumed": offset > 0})
        try:
            await p.conn.send({"t": "file_req", "fid": fid, "offset": offset})
        except Exception:
            self._fail_download(fid, "连接中断", keep_part=True)

    def _fail_download(self, fid: str, error: str, notify_peer: bool = False, keep_part: bool = False) -> None:
        """下载停止。keep_part=True 时保留已下载的部分(断点),之后可以继续。"""
        dl = self.downloads.pop(fid, None)
        if dl is None:
            return
        try:
            dl["f"].close()
        except OSError:
            pass
        if not keep_part:
            try:
                os.remove(dl["part"])
            except OSError:
                pass
        if notify_peer:
            p = self.peers.get(dl["peer"])
            if p is not None and p.online:
                self.loop.create_task(self._safe_send(p, {"t": "file_cancel", "fid": fid}))
        self._emit("file_done", {"fid": fid, "ok": False, "error": error, "paused": keep_part, "done": dl["done"],
                                 "total": dl["size"]})

    def _on_file_chunk(self, p: Peer, obj: dict) -> None:
        fid = obj.get("fid")
        dl = self.downloads.get(fid) if isinstance(fid, str) else None
        data = obj.get("_bin")
        if dl is None or dl["peer"] != p.id or not isinstance(data, bytes):
            return
        if obj.get("seq") != dl["next"]:
            self._fail_download(fid, "数据顺序错误,可以重新继续", True, keep_part=True)
            return
        dl["next"] += 1
        dl["t"] = time.monotonic()
        dl["done"] += len(data)
        if dl["done"] > dl["size"]:
            self._fail_download(fid, "数据超出文件大小", True)
            return
        try:
            dl["f"].write(data)
        except OSError as e:
            self._fail_download(fid, f"写入失败:{e.strerror or e}", True)
            return
        dl["hash"].update(data)
        now = time.monotonic()
        if now - dl["last"] >= PROGRESS_EVERY:
            dl["last"] = now
            self._emit("file_progress", {"fid": fid, "done": dl["done"], "total": dl["size"], "dir": "down"})

    def _on_file_done(self, p: Peer, obj: dict) -> None:
        fid = obj.get("fid")
        dl = self.downloads.get(fid) if isinstance(fid, str) else None
        if dl is None or dl["peer"] != p.id:
            return
        if dl["done"] != dl["size"] or obj.get("sha256") != dl["hash"].hexdigest():
            self._fail_download(fid, "文件校验失败,请重新下载")
            return
        self.downloads.pop(fid, None)
        try:
            dl["f"].close()
            _replace_retry(dl["part"], dl["dest"])
        except OSError as e:
            try:
                os.remove(dl["part"])
            except OSError:
                pass
            self._emit("file_done", {"fid": fid, "ok": False, "error": f"保存失败:{e.strerror or e}"})
            return
        self._emit("file_done", {"fid": fid, "ok": True, "path": dl["dest"], "size": dl["size"]})

    def _on_file_stop(self, p: Peer, obj: dict, t: str) -> None:
        fid = obj.get("fid")
        if not isinstance(fid, str):
            return
        dl = self.downloads.get(fid)
        if dl is not None and dl["peer"] == p.id:
            if t == "file_cancel":
                self._fail_download(fid, "对方中断了发送", keep_part=True)
            else:
                self._fail_download(fid, str(obj.get("error") or "文件已失效")[:60])
        task = self.uploads.get((p.id, fid))
        if task is not None:
            task.cancel()

    def _cancel_file(self, fid: str) -> None:
        if fid in self.downloads:
            self._fail_download(fid, "已取消", notify_peer=True)
        self._cancel_uploads(fid)

    def _pause_file(self, fid: str) -> None:
        if fid in self.downloads:
            self._fail_download(fid, "已暂停", notify_peer=True, keep_part=True)

    def _restore_room(self, master: bytes, name: str) -> None:
        if len(master) != 32:
            return
        ctx = C.ContextKey(master)
        if ctx.tag in self.rooms:
            return
        room = Room(ctx, name or f"暗号群 {len(self.rooms) + 1}")
        self.rooms[room.tag] = room
        self._emit("room_joined", {"tag": room.tag, "name": room.name, "master": C.b64e(master), "restored": True})
        for p in self.peers.values():
            if p.online and p.presence_ok:
                rooms = self._rooms_from_proofs(p)
                if rooms != p.rooms:
                    p.rooms = rooms
                    self._emit_peer(p)
        self._broadcast_presence()
        self._send_beacons(only=ctx)

    def _cancel_uploads(self, fid: str) -> None:
        for (pid, f), task in list(self.uploads.items()):
            if f == fid:
                task.cancel()

    # ---- 发送方
    def _on_file_req(self, p: Peer, obj: dict) -> None:
        fid = obj.get("fid")
        offer = self.offers.get(fid) if isinstance(fid, str) else None
        if offer is None or not self._may_download(p, offer):
            self.loop.create_task(self._safe_send(p, {"t": "file_err", "fid": fid if isinstance(fid, str) else "",
                                                      "error": "文件已失效(对方撤回了,或已退出)"}))
            return
        offset = obj.get("offset", 0)
        if type(offset) is not int or not (0 <= offset <= offer["size"]):
            offset = 0
        try:
            changed = (os.path.getsize(offer["path"]) != offer["size"]
                       or (offer.get("mtime") and abs(os.path.getmtime(offer["path"]) - offer["mtime"]) > 1))
        except OSError:
            changed = True
        if changed:
            self.loop.create_task(self._safe_send(p, {"t": "file_err", "fid": fid, "error": "文件已被移动或修改"}))
            return
        key = (p.id, fid)
        if key not in self.uploads:
            self.uploads[key] = self.loop.create_task(self._upload(p, fid, offer, offset))

    async def _upload(self, p: Peer, fid: str, offer: dict, offset: int = 0) -> None:
        conn = p.conn
        total, sent, seq, last = offer["size"], offset, 0, 0.0
        peer_hex = p.id.hex()
        try:
            h = hashlib.sha256()
            if offset:                                      # 断点续传:前面那段只算校验,不重发
                await self.loop.run_in_executor(self.pool, _hash_prefix, offer["path"], offset, h)
            with open(offer["path"], "rb") as f:
                f.seek(offset)
                while True:
                    chunk = await self.loop.run_in_executor(self.pool, f.read, FILE_CHUNK)
                    if not chunk:
                        break
                    sent += len(chunk)
                    if sent > total:
                        raise ValueError("文件在发送过程中被修改了")
                    h.update(chunk)
                    await conn.send_binary({"t": "file_chunk", "fid": fid, "seq": seq}, chunk)
                    seq += 1
                    if self.test_upload_delay:                  # 只在测试里用,正常为 0(不限速)
                        await asyncio.sleep(self.test_upload_delay)
                    now = time.monotonic()
                    if now - last >= PROGRESS_EVERY:
                        last = now
                        self._emit("file_progress", {"fid": fid, "done": sent, "total": total, "dir": "up",
                                                     "peer": peer_hex})
            if sent != total:
                raise ValueError("文件在发送过程中被修改了")
            await conn.send({"t": "file_done", "fid": fid, "sha256": h.hexdigest(), "size": sent})
            self._emit("file_progress", {"fid": fid, "done": sent, "total": total, "dir": "up", "peer": peer_hex,
                                         "finished": True})
        except asyncio.CancelledError:
            self.loop.create_task(self._safe_send(p, {"t": "file_cancel", "fid": fid}))
            self._emit("file_progress", {"fid": fid, "done": sent, "total": total, "dir": "up", "peer": peer_hex,
                                         "stopped": True})
            raise
        except (OSError, ValueError) as e:
            msg = str(e) if isinstance(e, ValueError) else "发送方读取文件失败"
            self.loop.create_task(self._safe_send(p, {"t": "file_err", "fid": fid, "error": msg}))
            self._emit("file_progress", {"fid": fid, "done": sent, "total": total, "dir": "up", "peer": peer_hex,
                                         "stopped": True})
        except ConnectionError:
            self._emit("file_progress", {"fid": fid, "done": sent, "total": total, "dir": "up", "peer": peer_hex,
                                         "stopped": True})
        finally:
            self.uploads.pop((p.id, fid), None)

    # ------------------------------------------------------------ 发送
    async def _send_msg(self, scope: str, target, mid: str, extra: dict, burn: int) -> None:
        base = {"mid": mid, "burn": burn, **extra}
        if self.title:
            base["ttl"] = self.title
        if self.level:
            base["lv"] = self.level
        if isinstance(base.get("img"), (bytes, bytearray)):
            base["img"] = C.b64e(base["img"])
        ok, total = await self._deliver(scope, target, base)
        self._emit("sent", {"mid": mid, "scope": scope, "target": target, "delivered": ok, "total": total})

    async def _deliver(self, scope: str, target, base: dict, only: str | None = None) -> tuple[int, int]:
        """按会话把 base 加密送给该收到的人。only=某人 id 时只送给他。返回 (送达数, 应送达数)。"""
        peers: list[Peer] = []
        obj = None
        if scope == "lobby" and self.lobby_enabled:
            obj = {"t": "msg", "scope": "lobby", **base}
            peers = [p for p in self.peers.values() if p.online and p.in_lobby]
        elif scope == "room" and target in self.rooms:
            obj = {"t": "msg", "scope": "room", "blob": C.seal_room_msg(self.rooms[target].ctx, base)}
            peers = [p for p in self.peers.values() if p.online and target in p.rooms]
        elif scope == "dm":
            p = self._peer_by_hex(target)
            if p is not None and p.online:
                peers = [p]
            obj = {"t": "msg", "scope": "dm", **base}
        if only is not None:
            peers = [p for p in peers if p.id.hex() == only]
        ok = 0
        if obj is not None and peers:
            results = await asyncio.gather(*(p.conn.send(obj) for p in peers), return_exceptions=True)
            ok = sum(1 for r in results if not isinstance(r, BaseException))
        return ok, len(peers)

    # ------------------------------------------------------------ 状态变更(在事件循环线程执行)
    def _set_nick(self, nick: str) -> None:
        self.nick = nick
        self._broadcast_presence()
        self._emit("self", self.self_info())

    def _set_lobby(self, enabled: bool) -> None:
        if enabled == self.lobby_enabled:
            return
        self.lobby_enabled = enabled
        if not enabled:
            for p in self.peers.values():
                p.beacon_ctx.pop(C.LOBBY_TAG, None)
            self._drop_unshared()
        self._broadcast_presence()
        self._emit("self", self.self_info())
        if enabled:
            self._send_beacons(only=C.LOBBY)

    async def _join_room(self, passphrase: str, name: str) -> None:
        try:
            ctx = await self.loop.run_in_executor(self.pool, C.room_context, passphrase)
        except C.CryptoError as e:
            self._emit("room_error", {"text": f"暗号无效:{e}"})
            return
        except Exception as e:
            self._emit("room_error", {"text": f"加入失败:{error_detail(e)}"})
            return
        if ctx.tag in self.rooms:
            self._emit("room_error", {"text": "你已经在这个暗号群里了", "tag": ctx.tag})
            return
        room = Room(ctx, name or f"暗号群 {len(self.rooms) + 1}")
        self.rooms[room.tag] = room
        self._emit("room_joined", {"tag": room.tag, "name": room.name, "master": C.b64e(ctx.master)})
        for p in self.peers.values():
            if p.online and p.presence_ok:
                rooms = self._rooms_from_proofs(p)
                if rooms != p.rooms:
                    p.rooms = rooms
                    self._emit_peer(p)
        self._broadcast_presence()
        self._send_beacons(only=ctx)

    def _leave_room(self, tag: str) -> None:
        room = self.rooms.pop(tag, None)
        if room is None:
            return
        for p in self.peers.values():
            p.beacon_ctx.pop(tag, None)
            if tag in p.rooms:
                p.rooms.discard(tag)
                self._emit_peer(p)
        self._drop_unshared()
        self._broadcast_presence()
        self._emit("room_left", {"tag": tag})

    def _add_manual_target(self, t: tuple[str, int]) -> None:
        self.manual_targets.add(t)
        for _key, ctx in self._contexts():
            self._unicast(self._beacon_for(ctx), t)

    # ------------------------------------------------------------ 定时维护
    async def _maint_loop(self) -> None:
        last_presence = time.monotonic()
        last_iface = time.monotonic()
        while self.running:
            await asyncio.sleep(2.0)
            now = time.monotonic()
            try:
                for p in list(self.peers.values()):
                    c = p.conn
                    if c is not None and not c.closed and now - c.last_rx > CONN_IDLE_TIMEOUT:
                        c.close()
                    if not p.online:
                        self._maybe_connect(p)
                        last = max(p.beacon_ctx.values(), default=p.first_seen)
                        if not p.connecting and now - last > 120:
                            self.peers.pop(p.id, None)
                for fid in [f for f, dl in self.downloads.items() if now - dl["t"] > 60]:
                    self._fail_download(fid, "传输超时", notify_peer=True, keep_part=True)
                if now - last_presence >= PRESENCE_INTERVAL:
                    last_presence = now
                    self._broadcast_presence()
                if now - last_iface >= 20:
                    last_iface = now
                    self._refresh_ifaces()
                for d, ttl in ((self.beacon_ips, 300), (self._reply_rl, 60)):
                    for k in [k for k, t in d.items() if now - t > ttl]:
                        d.pop(k, None)
            except Exception:
                log.exception("维护任务出错")
