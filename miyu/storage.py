"""
密语 · 账户保存(记住我)

只有勾选「记住我」才会写硬盘,保存在 %LOCALAPPDATA%\\MiYu 里:
  - p.bin  账户:身份私钥、昵称、暗号群密钥(不是暗号本身)、各项设置、宠物成长、已验证的人等
  - h.bin  聊天记录:只有打开「保存聊天记录」才会有;阅后即焚的消息永远不保存
两个文件都用 Windows DPAPI 加密(绑定当前 Windows 账号),换电脑或换账号都解不开。
「注销账户」会先用随机数据覆盖再删除这些文件。
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import shutil
import time

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from .stickers import default_dir as _stickers_dir, seal, unseal

ACCOUNT_FILE = "p.bin"
ACCOUNT_BACKUP = "p.bin.bak"          # 3.8.2 自动热备份:防止意外断电/杀软占用导致账户与 dbkey 丢失
HISTORY_FILE = "h.bin"                # 1.x 的聊天记录(2.0 起改用 msgdb 数据库,这个只用来迁移)
V1_BACKUP = ".v1bak"
FAVS_FILE = "f.bin"               # 我的收藏(只要开了记住登录就保存,不受「保存聊天记录」开关影响)
BG_FILE = "b.bin"                 # 自定义聊天背景图
GAMES_FILE = "g.bin"              # 五子棋:对局记录(大家互相同步的)、人机练习战绩、没下完的对局
FAV_IMAGE_MAX = 8 * 1024 * 1024
VERSION = 1
HISTORY_PER_CONV = 200            # 每个会话最多保存最近 200 条
HISTORY_IMAGE_MAX = 8 * 1024 * 1024          # 2.0 起用数据库存,动图(最大 8MB)也能保存
HISTORY_VIDEO_MAX = 20 * 1024 * 1024         # 匿名纸条里的视频
OUTBOX = "out"                    # 发送文件夹时临时打包的 zip


class Locked(Exception):
    """账户设了启动密码,还没解锁。"""


def derive_key(password: str, salt: bytes) -> bytes:
    from .crypto import scrypt32
    return scrypt32(password.encode("utf-8"), salt)


def default_dir() -> str:
    from .stickers import base_dir
    return base_dir()


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s) -> bytes:
    try:
        return base64.b64decode(s, validate=True) if isinstance(s, str) else b""
    except Exception:
        return b""


def _shred(path: str) -> None:
    """用随机数据覆盖一遍再删除(SSD 上不能保证物理擦除,但文件内容本来就是加密的)。"""
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as f:
            left = size
            while left > 0:
                n = min(left, 1024 * 1024)
                f.write(os.urandom(n))
                left -= n
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    try:
        os.remove(path)
    except OSError:
        pass


class AccountStore:
    def __init__(self, folder: str | None = None, stickers_folder: str | None = None) -> None:
        self.folder = folder or default_dir()
        self.stickers_folder = stickers_folder or _stickers_dir()
        self.key: bytes | None = None          # 启动密码派生出的密钥(只在内存里)
        self.salt: bytes | None = None

    # ---- 启动密码
    @property
    def has_password(self) -> bool:
        return self.key is not None

    def _outer_one(self, name: str) -> dict | None:
        raw = self._read_raw(self._path(name))
        if raw is None:
            return None
        try:
            data = unseal(raw)
            d = json.loads(data.decode("utf-8")) if data is not None else None
            return d if isinstance(d, dict) else None
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def _outer(self) -> dict | None:
        return self._outer_one(ACCOUNT_FILE) or self._outer_one(ACCOUNT_BACKUP)

    def is_locked(self) -> bool:
        """账户文件被启动密码加密了,而且本次还没解锁。"""
        d = self._outer()
        return bool(d and d.get("enc")) and self.key is None

    def unlock(self, password: str) -> bool:
        d = self._outer()
        if not (d and d.get("enc")):
            return False
        salt = b64d(d.get("salt"))
        key = derive_key(password, salt)
        try:
            raw = b64d(d.get("ct"))
            ChaCha20Poly1305(key).decrypt(raw[:12], raw[12:], b"miyu-" + ACCOUNT_FILE.encode())
        except Exception:
            return False
        self.key, self.salt = key, salt
        return True

    def verify(self, password: str) -> bool:
        """窗口叫回时校验密码(不读文件,和内存里的密钥比)。"""
        if self.key is None or self.salt is None:
            return False
        return hmac.compare_digest(derive_key(password, self.salt), self.key)

    def set_password(self, password: str | None) -> None:
        """设置 / 修改 / 去掉启动密码,并自动将已有的收藏、背景图、战绩等文件用新密钥重加密落盘。"""
        existing: list[tuple[str, object]] = []
        for name in (ACCOUNT_FILE, FAVS_FILE, BG_FILE, GAMES_FILE, HISTORY_FILE):
            if os.path.exists(self._path(name)):
                try:
                    val = self._read(name)
                except Locked:
                    val = None
                if val is not None:
                    existing.append((name, val))
        if password:
            self.salt = os.urandom(16)
            self.key = derive_key(password, self.salt)
        else:
            self.key = self.salt = None
        for name, val in existing:
            self._write(name, val)

    # ---- 底层读写
    def _path(self, name: str) -> str:
        return os.path.join(self.folder, name)

    def _read_raw(self, path: str) -> bytes | None:
        """读取文件:Windows 上遇到杀软或瞬时占锁自动短暂重试,绝不轻率返回 None。"""
        for i in range(6):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except PermissionError:
                if i == 5:
                    return None
                time.sleep(0.04)
            except OSError:
                return None
        return None

    def _replace_safe(self, src: str, dst: str) -> None:
        for i in range(6):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if i == 5:
                    raise
                time.sleep(0.04)

    def _write(self, name: str, obj, *, aad_name: str | None = None) -> bool:
        tmp = ""
        try:
            os.makedirs(self.folder, exist_ok=True)
            data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if self.key is not None:               # 设了启动密码:先用密码派生的密钥加密一层,外面再套 DPAPI
                nonce = os.urandom(12)
                ct = ChaCha20Poly1305(self.key).encrypt(nonce, data, b"miyu-" + (aad_name or name).encode())
                data = json.dumps({"enc": 1, "salt": b64e(self.salt), "ct": b64e(nonce + ct)}).encode("utf-8")
            raw = seal(data)
            dst = self._path(name)
            if name == ACCOUNT_FILE and os.path.exists(dst):
                # 覆盖主账户前把上一份完好文件保留为 p.bin.bak
                try:
                    if os.path.getsize(dst) > 0:
                        btmp = self._path(f"{ACCOUNT_BACKUP}.{os.getpid()}.tmp")
                        shutil.copyfile(dst, btmp)
                        self._replace_safe(btmp, self._path(ACCOUNT_BACKUP))
                except OSError:
                    pass
            tmp = self._path(f"{name}.{os.getpid()}.tmp")
            with open(tmp, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            self._replace_safe(tmp, dst)             # 原子替换:写到一半断电也不会损坏旧文件
            return True
        except (OSError, TypeError, ValueError):
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False

    def _read(self, name: str, *, aad_name: str | None = None):
        raw = self._read_raw(self._path(name))
        if raw is None:
            return None
        data = unseal(raw)
        if data is None:
            return None
        try:
            d = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if isinstance(d, dict) and d.get("enc"):
            if self.key is None:
                raise Locked()
            try:
                blob = b64d(d.get("ct"))
                plain = ChaCha20Poly1305(self.key).decrypt(blob[:12], blob[12:], b"miyu-" + (aad_name or name).encode())
                return json.loads(plain.decode("utf-8"))
            except Exception:
                return None
        return d

    # ---- 账户
    def has_account(self) -> bool:
        return os.path.exists(self._path(ACCOUNT_FILE)) or os.path.exists(self._path(ACCOUNT_BACKUP))

    def load_account(self) -> dict | None:
        for fn in (ACCOUNT_FILE, ACCOUNT_BACKUP):
            try:
                d = self._read(fn, aad_name=ACCOUNT_FILE)
            except Locked:
                return None
            if isinstance(d, dict) and len(b64d(d.get("seed"))) == 32:
                return d
        return None

    def save_account(self, d: dict) -> bool:
        d = dict(d)
        d["v"] = VERSION
        return self._write(ACCOUNT_FILE, d)

    # ---- 聊天记录
    def load_history(self) -> dict:
        try:
            d = self._read(HISTORY_FILE)
        except Locked:
            return {}
        return d if isinstance(d, dict) else {}

    def save_history(self, d: dict) -> bool:
        return self._write(HISTORY_FILE, d)

    def load_favs(self) -> list:
        try:
            d = self._read(FAVS_FILE)
        except Locked:
            return []
        return d.get("items", []) if isinstance(d, dict) and isinstance(d.get("items"), list) else []

    def save_favs(self, items: list) -> bool:
        return self._write(FAVS_FILE, {"v": 1, "items": items})

    # ---- 五子棋(和账户一样 DPAPI + 启动密码加密)
    def save_games(self, d: dict) -> bool:
        return self._write(GAMES_FILE, {"v": 1, **d})

    def load_games(self) -> dict:
        try:
            d = self._read(GAMES_FILE)
        except Locked:
            return {}
        return d if isinstance(d, dict) else {}

    # ---- 自定义背景图等二进制小文件(同样 DPAPI + 启动密码加密)
    def save_blob(self, name: str, data: bytes | None) -> bool:
        if not data:
            p = self._path(name)
            if os.path.exists(p):
                _shred(p)
            return True
        return self._write(name, {"v": 1, "b": b64e(data)})

    def load_blob(self, name: str) -> bytes:
        try:
            d = self._read(name)
        except Locked:
            return b""
        return b64d(d.get("b")) if isinstance(d, dict) else b""

    def has_v1_history(self) -> bool:
        """有没有 1.x 版的聊天记录文件(2.0 第一次打开时搬进数据库)。"""
        return os.path.exists(self._path(HISTORY_FILE))

    def retire_v1_history(self) -> None:
        """搬完以后,旧文件改名留作备份(内容还是加密的)。"""
        p = self._path(HISTORY_FILE)
        if os.path.exists(p):
            try:
                os.replace(p, p + V1_BACKUP)
            except OSError:
                pass

    def clear_history(self) -> None:
        """删掉 1.x 的记录文件和它的备份(2.0 的数据库由主窗口关掉后再删)。"""
        _shred(self._path(HISTORY_FILE))
        _shred(self._path(HISTORY_FILE + V1_BACKUP))

    # ---- 注销
    def wipe(self, stickers: bool = False) -> None:
        for name in (ACCOUNT_FILE, ACCOUNT_BACKUP, HISTORY_FILE, FAVS_FILE, BG_FILE, GAMES_FILE,
                     ACCOUNT_FILE + ".tmp", HISTORY_FILE + ".tmp", FAVS_FILE + ".tmp",
                     BG_FILE + ".tmp", GAMES_FILE + ".tmp", HISTORY_FILE + V1_BACKUP):
            p = self._path(name)
            if os.path.exists(p):
                _shred(p)
        if os.path.isdir(self.folder):
            for fn in os.listdir(self.folder):
                if fn.endswith(".tmp"):
                    _shred(os.path.join(self.folder, fn))
        from .msgdb import remove_files                     # 2.0 的聊天记录数据库(调用前要先关掉)
        remove_files(self.folder)
        out = self._path(OUTBOX)
        if os.path.isdir(out):
            shutil.rmtree(out, ignore_errors=True)
        self.key = self.salt = None
        if stickers and os.path.isdir(self.stickers_folder):
            for name in os.listdir(self.stickers_folder):
                _shred(os.path.join(self.stickers_folder, name))
            shutil.rmtree(self.stickers_folder, ignore_errors=True)
        try:
            if os.path.isdir(self.folder) and not os.listdir(self.folder):
                os.rmdir(self.folder)
        except OSError:
            pass


# ---------------------------------------------------------------- 消息 ⇄ 可保存的字典
MSG_FIELDS = ("mid", "sender", "nick", "tag", "text", "mine", "time", "mime", "w", "h", "reply", "at", "file",
              "mention", "sticker", "delivered", "read", "edited", "card", "skin", "aura", "anon", "fav", "reactions",
              "title", "level")


def msg_to_dict(m, img_max: int = HISTORY_IMAGE_MAX) -> dict | None:
    """阅后即焚、系统提示、已撤回/已焚毁的消息都不保存。"""
    if m.burn or m.system or m.gone:
        return None
    d = {k: getattr(m, k) for k in MSG_FIELDS}
    if m.img:
        if len(m.img) > img_max:
            return None
        d["img"] = b64e(m.img)
    vid = getattr(m, "vid", None)
    if vid:                                          # 匿名纸条里的视频(最大 20MB,和图片一样加密存在数据库里)
        if len(vid) > HISTORY_VIDEO_MAX:
            return None
        d["vid"] = b64e(vid)
    return d


def msg_kwargs(d: dict) -> dict | None:
    if not isinstance(d, dict) or not isinstance(d.get("mid"), str):
        return None
    img = b64d(d.get("img")) or None
    return {
        "mid": d["mid"], "sender": str(d.get("sender", "")), "nick": str(d.get("nick", "")),
        "tag": str(d.get("tag", "")), "mine": bool(d.get("mine")), "img": img,
        "mime": d.get("mime") if img else None, "w": int(d.get("w") or 0), "h": int(d.get("h") or 0),
        "reply": d.get("reply") if isinstance(d.get("reply"), dict) else None,
        "at": [a for a in (d.get("at") or []) if isinstance(a, str)],
        "file": d.get("file") if isinstance(d.get("file"), dict) else None,
        "sticker": bool(d.get("sticker")),
        "card": d.get("card") if isinstance(d.get("card"), dict) else None,
        "skin": d.get("skin") if isinstance(d.get("skin"), str) else None,
        "aura": d.get("aura") if isinstance(d.get("aura"), str) else None,
        "anon": bool(d.get("anon")),
        "fav": d.get("fav") if isinstance(d.get("fav"), dict) else None,
    }
