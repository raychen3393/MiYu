"""
密语 · 加密层

- 身份:Ed25519 签名密钥(每次启动随机生成,不落盘)
- 发现广播(beacon):ChaCha20-Poly1305 加密 + 签名,所有 beacon 等长
- 点对点连接:X25519 临时密钥交换(前向保密)+ 身份签名互认 + 计数器 nonce
- 暗号群:scrypt(暗号) 派生群密钥,群消息额外用群密钥再加密一层
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import unicodedata

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_RAW = serialization.Encoding.Raw
_RAW_PUB = serialization.PublicFormat.Raw

BEACON_PLAIN_SIZE = 512                      # beacon 明文统一填充到这个长度
BEACON_WIRE_SIZE = 12 + BEACON_PLAIN_SIZE + 16  # nonce + 密文 + tag = 540 字节
FRAME_BLOCK = 256                            # 连接内每帧明文填充到 256 的倍数


class CryptoError(Exception):
    pass


# ---------------------------------------------------------------- 工具函数
def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"), validate=True)


def hkdf(ikm: bytes, info: bytes, length: int = 32, salt: bytes | None = None) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def pad(data: bytes, block: int = FRAME_BLOCK) -> bytes:
    """4 字节长度 + 数据 + 0 填充到 block 的整数倍(在加密之前做,隐藏真实长度)。"""
    n = len(data)
    total = -(-(n + 4) // block) * block
    return struct.pack(">I", n) + data + b"\x00" * (total - n - 4)


def unpad(buf: bytes) -> bytes:
    if len(buf) < 4:
        raise CryptoError("帧太短")
    n = struct.unpack(">I", buf[:4])[0]
    if n > len(buf) - 4:
        raise CryptoError("长度字段错误")
    return buf[4:4 + n]


# ---------------------------------------------------------------- 身份
class Identity:
    def __init__(self, seed: bytes | None = None) -> None:
        """seed 为空时随机生成新身份;传入之前保存的 32 字节私钥则恢复同一个身份。"""
        self._priv = Ed25519PrivateKey.from_private_bytes(seed) if seed else Ed25519PrivateKey.generate()
        self.pub: bytes = self._priv.public_key().public_bytes(_RAW, _RAW_PUB)

    @property
    def seed(self) -> bytes:
        return self._priv.private_bytes(_RAW, serialization.PrivateFormat.Raw, serialization.NoEncryption())

    def sign(self, data: bytes) -> bytes:
        return self._priv.sign(data)


def verify(pub: bytes, sig: bytes, data: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, data)
        return True
    except (InvalidSignature, ValueError):
        return False


def short_tag(pub: bytes) -> str:
    """4 位短标签,用来区分同名的人,如 7F3A。"""
    return hashlib.sha256(b"miyu-tag" + pub).hexdigest()[:4].upper()


def fingerprint(pub: bytes) -> str:
    """个人指纹:8 组 4 位十六进制。"""
    h = hashlib.sha256(b"miyu-fp" + pub).hexdigest()[:32].upper()
    return " ".join(h[i:i + 4] for i in range(0, 32, 4))


def safety_number(pub_a: bytes, pub_b: bytes) -> str:
    """两个人的共同安全码:双方看到的完全一样,8 组 5 位数字。"""
    a, b = sorted((pub_a, pub_b))
    d = hashlib.sha256(b"miyu-safety-v1" + a + b).digest()
    groups = [str(int.from_bytes(d[i:i + 4], "big") % 100000).zfill(5) for i in range(0, 32, 4)]
    return " ".join(groups)


# ---------------------------------------------------------------- 上下文(大厅 / 暗号群)
class ContextKey:
    """一个"空间"的密钥:公开大厅或某个暗号群。"""

    def __init__(self, master: bytes) -> None:
        self.master = master                 # 保存账户时存它,而不是存暗号本身
        self.beacon_key = hkdf(master, b"miyu-beacon-key")
        self.msg_key = hkdf(master, b"miyu-msg-key")
        self.presence_key = hkdf(master, b"miyu-presence-key")
        self.tag = hkdf(master, b"miyu-tag", 8).hex()
        self._beacon_aead = ChaCha20Poly1305(self.beacon_key)
        self._msg_aead = ChaCha20Poly1305(self.msg_key)


# 公开大厅的密钥是内置常量:只起"混淆"作用,让抓包看不出明文;
# 任何装了软件的人都能进入大厅,这是设计如此。
LOBBY = ContextKey(hashlib.sha256(b"miyu-public-lobby-v1").digest())
LOBBY_TAG = "lobby"

_ROOM_SALT = b"miyu-room-salt-v1"


def normalize_passphrase(passphrase: str) -> bytes:
    return unicodedata.normalize("NFKC", passphrase.strip()).encode("utf-8")


def scrypt32(data: bytes, salt: bytes) -> bytes:
    """scrypt(n=2^15, r=8, p=1) → 32 字节。
    用 cryptography 库的实现,不用 hashlib.scrypt:后者在新版 Python 打包成 exe 后可能是个
    "延迟导入"对象,调用会报 'lazy_import' object is not callable。两者算出的结果完全相同。"""
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(data)


def room_context(passphrase: str) -> ContextKey:
    """由暗号派生群密钥。scrypt 故意算得慢,增加暴力猜暗号的成本。"""
    pw = normalize_passphrase(passphrase)
    if not pw:
        raise CryptoError("暗号不能为空")
    master = scrypt32(pw, _ROOM_SALT)
    return ContextKey(master)


# ---------------------------------------------------------------- beacon(发现广播)
_BEACON_AAD = b"miyu-beacon-v1"


def seal_beacon(ctx: ContextKey, ident: Identity, fields: dict) -> bytes:
    body = dict(fields)
    body["id"] = b64e(ident.pub)
    body["c"] = ctx.tag
    payload = canonical(body)
    sig = ident.sign(b"miyu-beacon-sig" + payload)
    inner = struct.pack(">H", len(payload)) + payload + sig
    if len(inner) > BEACON_PLAIN_SIZE:
        raise CryptoError("beacon 内容过长")
    inner += b"\x00" * (BEACON_PLAIN_SIZE - len(inner))
    nonce = os.urandom(12)
    return nonce + ctx._beacon_aead.encrypt(nonce, inner, _BEACON_AAD)


def open_beacon(ctx: ContextKey, data: bytes) -> dict | None:
    """解开 beacon;密钥不对、被篡改、签名不对都返回 None。"""
    if len(data) != BEACON_WIRE_SIZE:
        return None
    try:
        inner = ctx._beacon_aead.decrypt(data[:12], data[12:], _BEACON_AAD)
        n = struct.unpack(">H", inner[:2])[0]
        if n + 2 + 64 > len(inner):
            return None
        payload = inner[2:2 + n]
        sig = inner[2 + n:2 + n + 64]
        body = json.loads(payload.decode("utf-8"))
        if not isinstance(body, dict) or body.get("c") != ctx.tag:
            return None
        pub = b64d(body["id"])
        if len(pub) != 32 or not verify(pub, sig, b"miyu-beacon-sig" + payload):
            return None
        body["id"] = pub
        return body
    except (InvalidTag, ValueError, KeyError, TypeError, UnicodeDecodeError, struct.error):
        return None


# ---------------------------------------------------------------- 点对点握手与加密通道
class Handshake:
    """X25519 临时密钥交换。每次连接都用新的临时密钥,用完即弃 → 前向保密。"""

    def __init__(self) -> None:
        self._e = X25519PrivateKey.generate()
        self.e_pub: bytes = self._e.public_key().public_bytes(_RAW, _RAW_PUB)

    def derive(self, peer_e_pub: bytes, initiator: bool):
        if len(peer_e_pub) != 32 or peer_e_pub == self.e_pub:
            raise CryptoError("握手数据无效")
        shared = self._e.exchange(X25519PublicKey.from_public_bytes(peer_e_pub))
        if shared == b"\x00" * 32:
            raise CryptoError("握手数据无效")
        e_i, e_r = (self.e_pub, peer_e_pub) if initiator else (peer_e_pub, self.e_pub)
        transcript = hashlib.sha256(b"miyu-hs-v1" + e_i + e_r).digest()
        okm = hkdf(shared, b"miyu-session-keys", 64, salt=transcript)
        k_i2r, k_r2i = okm[:32], okm[32:]
        send_key, recv_key = (k_i2r, k_r2i) if initiator else (k_r2i, k_i2r)
        return send_key, recv_key, transcript


def auth_payload(transcript: bytes, role: bytes) -> bytes:
    return b"miyu-auth-v1" + transcript + role


class Cipher:
    """单方向加密器,nonce 用递增计数器,保证不重复,也防重放/乱序。"""

    def __init__(self, key: bytes) -> None:
        self._aead = ChaCha20Poly1305(key)
        self._n = 0

    def _nonce(self) -> bytes:
        n = struct.pack(">IQ", 0, self._n)
        self._n += 1
        return n

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._aead.encrypt(self._nonce(), plaintext, None)

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._aead.decrypt(self._nonce(), ciphertext, None)
        except InvalidTag as e:
            raise CryptoError("解密失败:数据被篡改或密钥不对") from e


# ---------------------------------------------------------------- 暗号群消息 / 在场证明
_ROOM_AAD = b"miyu-room-msg-v1"


def seal_room_msg(ctx: ContextKey, obj: dict) -> str:
    nonce = os.urandom(12)
    return b64e(nonce + ctx._msg_aead.encrypt(nonce, canonical(obj), _ROOM_AAD + ctx.tag.encode()))


def open_room_msg(ctx: ContextKey, blob: str) -> dict | None:
    try:
        raw = b64d(blob)
        if len(raw) < 12 + 16:
            return None
        obj = json.loads(ctx._msg_aead.decrypt(raw[:12], raw[12:], _ROOM_AAD + ctx.tag.encode()).decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except (InvalidTag, ValueError, TypeError, UnicodeDecodeError):
        return None


def presence_proof(ctx: ContextKey, sender: bytes, receiver: bytes) -> str:
    """证明"我在这个暗号群里",只有同群的人能验证,别人看到的只是随机数。"""
    return hmac.new(ctx.presence_key, b"miyu-presence" + sender + receiver, hashlib.sha256).hexdigest()[:32]


def random_proof() -> str:
    return os.urandom(16).hex()


HELLO_TAG_SIZE = 16


def hello_tag(ctx: ContextKey, e_pub: bytes) -> bytes:
    """连接的第一个包附带这个标签:不知道共同密钥的人(扫描器)连进来,对方一个字节都不回。"""
    return hmac.new(ctx.presence_key, b"miyu-hello" + e_pub, hashlib.sha256).digest()[:HELLO_TAG_SIZE]


def check_hello(ctxs, e_pub: bytes, tag: bytes) -> bool:
    return any(hmac.compare_digest(hello_tag(c, e_pub), tag) for c in ctxs)
