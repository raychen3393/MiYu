"""
密语 · 局域网自动更新(纯逻辑,不涉及界面)

发布的 exe 末尾带一个 88 字节的"尾巴":标记(8) + 版本号(16) + Ed25519 签名(64)。
签名用的私钥只在打包的人手里(build.bat 自动生成,放在用户目录的 .miyu_release 里),
对应的公钥打包进每一份 exe。收到别人传来的新版后先验签,不是同一把私钥签的一律丢弃,
所以局域网里的其他人没法冒充发布者推送假更新。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .version import VERSION

MAGIC = b"MIYUREL1"
TRAILER = 8 + 16 + 64
MAX_UPDATE_SIZE = 600 * 1024 * 1024
_VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){0,3}$")


def valid_version(v) -> bool:
    return isinstance(v, str) and bool(_VERSION_RE.match(v))


def parse_version(v: str) -> tuple:
    return tuple(int(x) for x in v.split(".")) if valid_version(v) else (0,)


def newer(a: str, b: str = VERSION) -> bool:
    """a 比 b 新?"""
    pa, pb = parse_version(a), parse_version(b)
    n = max(len(pa), len(pb))
    return pa + (0,) * (n - len(pa)) > pb + (0,) * (n - len(pb))


def _digest(path: str, length: int) -> bytes:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        left = length
        while left > 0:
            chunk = f.read(min(4 * 1024 * 1024, left))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
    return h.digest()


def _message(version: str, digest: bytes) -> bytes:
    return b"miyu-release-v1|" + version.encode("ascii").ljust(16, b"\0") + digest


def _trailer(path: str) -> tuple[str, bytes, int] | None:
    """读尾巴:(版本号, 签名, 正文长度)。没有尾巴返回 None。"""
    try:
        size = os.path.getsize(path)
        if size <= TRAILER:
            return None
        with open(path, "rb") as f:
            f.seek(size - TRAILER)
            t = f.read(TRAILER)
    except OSError:
        return None
    if t[:8] != MAGIC:
        return None
    try:
        version = t[8:24].rstrip(b"\0").decode("ascii")
    except UnicodeDecodeError:
        return None
    return (version, t[24:], size - TRAILER) if valid_version(version) else None


def sign_file(path: str, version: str, priv: Ed25519PrivateKey) -> None:
    """给 exe 加上签名尾巴(已经有的话先去掉旧的)。"""
    if not valid_version(version):
        raise ValueError("版本号格式不对")
    old = _trailer(path)
    body = old[2] if old else os.path.getsize(path)
    sig = priv.sign(_message(version, _digest(path, body)))
    with open(path, "r+b") as f:
        f.truncate(body)
        f.seek(body)
        f.write(MAGIC + version.encode("ascii").ljust(16, b"\0") + sig)


def read_release(path: str, pubkey: bytes | None) -> str | None:
    """验证一份 exe 的签名。通过返回它的版本号,否则 None。"""
    if not pubkey or len(pubkey) != 32:
        return None
    t = _trailer(path)
    if t is None:
        return None
    version, sig, body = t
    try:
        Ed25519PublicKey.from_public_bytes(pubkey).verify(sig, _message(version, _digest(path, body)))
    except (InvalidSignature, ValueError, OSError):
        return None
    return version


def release_pubkey() -> bytes | None:
    """打包时写进来的发布公钥。直接用源码运行、或者没签名的版本没有,自动更新就不启用。"""
    try:
        from ._pubkey import RELEASE_PUBKEY
        key = bytes.fromhex(RELEASE_PUBKEY)
        return key if len(key) == 32 else None
    except Exception:
        return None


def current_exe() -> str | None:
    return sys.executable if getattr(sys, "frozen", False) else None


def apply_update(new_exe: str, cur_exe: str) -> None:
    """用新版替换正在运行的 exe。Windows 不让覆盖运行中的程序,但允许改名:
    先把自己改名成 .old,再把新版放到原来的位置;失败就改回去。"""
    old = cur_exe + ".old"
    try:
        os.remove(old)
    except OSError:
        pass
    os.replace(cur_exe, old)
    try:
        shutil.copyfile(new_exe, cur_exe)
    except OSError:
        try:
            os.remove(cur_exe)
        except OSError:
            pass
        os.replace(old, cur_exe)
        raise


def cleanup_old(cur_exe: str | None = None) -> None:
    """启动时删掉上次更新留下的旧版本。"""
    cur_exe = cur_exe or current_exe()
    if cur_exe:
        try:
            os.remove(cur_exe + ".old")
        except OSError:
            pass
