"""
密语 · 表情包收藏
表情包是本软件唯一会保存到硬盘的内容(否则关掉就没了)。
Windows 上每个文件都用系统的 DPAPI 加密(绑定当前 Windows 账号):
在资源管理器里看到的只是一堆打不开的 .bin 文件,换台电脑或换个账号也解不开。
"""
from __future__ import annotations

import hashlib
import os
import sys

from .core import IMAGE_MAGIC, valid_image

HEADER_DPAPI = b"MIYUSTK1"
HEADER_PLAIN = b"MIYUSTK0"
MAX_STICKERS = 300


PORTABLE_NAME = "MiYuData"


def app_dir() -> str:
    """软件所在的文件夹(打包后是 exe 的位置)。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def portable_dir() -> str:
    return os.path.join(app_dir(), PORTABLE_NAME)


def system_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "MiYu")
    return os.path.join(os.path.expanduser("~"), ".miyu")


def base_dir() -> str:
    """密语所有数据的总文件夹。软件旁边有 MiYuData 文件夹就用它(便携模式),否则用系统默认位置。"""
    p = portable_dir()
    return p if os.path.isdir(p) else system_dir()


def default_dir() -> str:
    return os.path.join(base_dir(), "cache")


def sniff_mime(data: bytes) -> str | None:
    for mime, magic in IMAGE_MAGIC.items():
        if data.startswith(magic) and valid_image(data, mime):
            return mime
    return None


# ---------------------------------------------------------------- Windows DPAPI
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.DWORD, ctypes.POINTER(BLOB)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):   # UI_FORBIDDEN
        raise OSError("DPAPI 失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def seal(data: bytes) -> bytes:
    if sys.platform == "win32":
        try:
            return HEADER_DPAPI + _dpapi(data, True)
        except Exception:
            pass
    return HEADER_PLAIN + data


def unseal(raw: bytes) -> bytes | None:
    try:
        if raw.startswith(HEADER_DPAPI) and sys.platform == "win32":
            return _dpapi(raw[len(HEADER_DPAPI):], False)
        if raw.startswith(HEADER_PLAIN):
            return raw[len(HEADER_PLAIN):]
    except Exception:
        return None
    return None


class StickerStore:
    def __init__(self, folder: str | None = None) -> None:
        self.folder = folder or default_dir()
        self.items: list[dict] = []          # {"id", "data", "mime"},最新的在前
        self.loaded = False

    def load(self) -> None:
        self.loaded = True
        self.items = []
        try:
            names = [n for n in os.listdir(self.folder) if n.endswith(".bin")]
        except OSError:
            return
        paths = sorted((os.path.join(self.folder, n) for n in names), key=lambda p: -os.path.getmtime(p))
        for path in paths[:MAX_STICKERS]:
            try:
                with open(path, "rb") as f:
                    data = unseal(f.read())
            except OSError:
                continue
            mime = sniff_mime(data) if data else None
            if mime:
                self.items.append({"id": os.path.basename(path)[:-4], "data": data, "mime": mime})

    def ensure(self) -> None:
        if not self.loaded:
            self.load()

    def add(self, data: bytes, mime: str | None = None) -> str | None:
        """添加一个表情包,返回 id;已经有了就挪到最前面。"""
        self.ensure()
        mime = mime or sniff_mime(data)
        if not mime or not valid_image(data, mime):
            return None
        sid = hashlib.sha256(data).hexdigest()[:24]
        existing = next((it for it in self.items if it["id"] == sid), None)
        if existing:
            self.items.remove(existing)
            self.items.insert(0, existing)
            try:
                os.utime(os.path.join(self.folder, sid + ".bin"))
            except OSError:
                pass
            return sid
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, sid + ".bin"), "wb") as f:
            f.write(seal(data))
        self.items.insert(0, {"id": sid, "data": data, "mime": mime})
        while len(self.items) > MAX_STICKERS:
            self.remove(self.items[-1]["id"])
        return sid

    def remove(self, sid: str) -> None:
        self.ensure()
        self.items = [it for it in self.items if it["id"] != sid]
        try:
            os.remove(os.path.join(self.folder, sid + ".bin"))
        except OSError:
            pass

    def clear(self) -> None:
        self.ensure()
        for it in list(self.items):
            self.remove(it["id"])
        self.items = []
        try:
            os.rmdir(self.folder)
        except OSError:
            pass
