"""
密语 · 启动自检(不依赖界面)

检查软件靠得住的几样基础:加密、后台线程池、数据文件夹、本机加密保存、网络、视频模块、声音。
每项结果是 {"name", "level", "detail"},level 为 ok / info / warn(能用但有功能受影响)/ fail(会出问题)。
打包时 build.bat 用 --selftest 跑一遍不需要网络的项目,有 fail 就不签名。
"""
from __future__ import annotations

import os
import sys
import uuid

LEVEL_MARK = {"ok": "✓", "info": "·", "warn": "⚠", "fail": "✗"}


def _check(results: list, name: str, fn) -> None:
    try:
        level, detail = fn()
    except Exception as e:                             # 检查本身出错 = 这一项有问题
        level, detail = "fail", f"{type(e).__name__}: {e}"
    results.append({"name": name, "level": level, "detail": detail})


def _crypto():
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    from . import crypto as C
    a = C.Identity()
    if not C.verify(a.pub, a.sign(b"miyu"), b"miyu") or C.verify(a.pub, a.sign(b"miyu"), b"miyU"):
        return "fail", "身份签名验证结果不对"
    if C.Identity(a.seed).pub != a.pub:
        return "fail", "保存的身份恢复不出来"
    k1, k2 = X25519PrivateKey.generate(), X25519PrivateKey.generate()
    if k1.exchange(k2.public_key()) != k2.exchange(k1.public_key()):
        return "fail", "密钥交换结果不一致"
    aead = ChaCha20Poly1305(os.urandom(32))
    nonce = os.urandom(12)
    if aead.decrypt(nonce, aead.encrypt(nonce, b"hello", None), None) != b"hello":
        return "fail", "加密解密结果不一致"
    if len(C.scrypt32(b"miyu-selftest", b"0123456789abcdef")) != 32:
        return "fail", "暗号派生密钥长度不对"
    return "ok", "签名、密钥交换、加密、暗号派生都正常"


def _threadpool(core=None):
    import concurrent.futures as cf

    from . import compat
    compat.fix_lazy_imports()
    if not isinstance(cf.ThreadPoolExecutor, type):
        return "fail", f"线程池是个占位对象:{type(cf.ThreadPoolExecutor).__name__}"
    pool = getattr(core, "pool", None)
    own = pool is None
    if own:
        from concurrent.futures.thread import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=1)
    try:
        if pool.submit(lambda: 6 * 7).result(timeout=5) != 42:
            return "fail", "后台任务结果不对"
    finally:
        if own:
            pool.shutdown(wait=False)
    return "ok", "后台任务正常(加入暗号群、发文件都靠它)"


def _data_folder(store):
    folder = store.folder
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f".check-{uuid.uuid4().hex[:8]}")
    with open(path, "wb") as f:
        f.write(b"ok")
    with open(path, "rb") as f:
        ok = f.read() == b"ok"
    os.remove(path)
    return ("ok", f"可以读写:{folder}") if ok else ("fail", f"写进去的内容读出来不一样:{folder}")


def _dpapi():
    if sys.platform != "win32":
        return "info", "不是 Windows,保存的内容不用 DPAPI 加密"
    from .stickers import HEADER_DPAPI, seal, unseal
    raw = seal(b"miyu-check")
    if not raw.startswith(HEADER_DPAPI):
        return "warn", "Windows 自带的本机加密(DPAPI)用不了,保存在电脑上的内容只做了简单处理"
    if unseal(raw) != b"miyu-check":
        return "fail", "本机加密的内容解不开"
    return "ok", "保存在电脑上的内容会用 Windows 自带的加密(DPAPI)"


def _network(core):
    if core.start_error:
        return "fail", core.start_error
    if not core.running:
        return "fail", "网络模块没有运行"
    ips = list(core.local_ips)
    detail = f"TCP 端口 {core.tcp_port},UDP 端口 {core.udp_port}"
    if not ips:
        return "warn", detail + ";没检测到局域网 IP 地址,可能没连网"
    return "ok", detail + ",本机地址 " + "、".join(ips[:4])


def _video():
    import PySide6.QtMultimedia  # noqa: F401
    import PySide6.QtMultimediaWidgets  # noqa: F401
    return "ok", "可以在软件里直接看视频"


def _video_safe():
    try:
        return _video()
    except Exception as e:
        return "warn", f"视频模块用不了({type(e).__name__}),看视频会改用系统播放器"


def _sound():
    if sys.platform != "win32":
        return "info", "不是 Windows,没有提示音"
    import winsound  # noqa: F401
    return "ok", "提示音可用"


def run_checks(core=None, store=None, network: bool = True) -> list:
    """跑一遍自检。core / store 为空时跳过对应的项目。"""
    results: list = []
    _check(results, "加密", _crypto)
    _check(results, "后台线程池", lambda: _threadpool(core))
    if store is not None:
        _check(results, "数据文件夹", lambda: _data_folder(store))
    _check(results, "本机加密保存", _dpapi)
    if network and core is not None:
        _check(results, "网络", lambda: _network(core))
    _check(results, "视频", _video_safe)
    _check(results, "声音", _sound)
    return results


def has_failure(results: list) -> bool:
    return any(r["level"] == "fail" for r in results)


def format_results(results: list) -> str:
    return "\n".join(f"{LEVEL_MARK.get(r['level'], '?')} {r['name']}:{r['detail']}" for r in results)
