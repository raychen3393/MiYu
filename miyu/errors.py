"""
密语 · 出错信息的整理(不依赖界面,网络模块也能用)

只记录错误类型、说明和出错的代码位置(文件名:行号),不记录聊天内容,也不写硬盘。
"""
from __future__ import annotations

import asyncio
import os
import platform
import sys
import traceback

from .version import VERSION

# 这些是网络上的正常情况(对方断线、超时……),不算软件出错
QUIET_TYPES = (ConnectionError, TimeoutError, asyncio.IncompleteReadError, asyncio.CancelledError, BrokenPipeError)


def env_line() -> str:
    kind = "打包版" if getattr(sys, "frozen", False) else "源码运行"
    return (f"密语 v{VERSION} · {platform.system()} {platform.release()} ({platform.version()}) · "
            f"Python {platform.python_version()} · {kind}")


def frames_of(tb, limit: int = 10) -> list:
    return traceback.extract_tb(tb)[-limit:] if tb is not None else []


def format_exception(exc: BaseException, tb=None) -> str:
    """错误类型和说明,加上最后几处出错位置(只写文件名,不写电脑上的完整路径)。"""
    tb = tb if tb is not None else exc.__traceback__
    lines = [f"{type(exc).__name__}: {exc}"]
    for f in frames_of(tb):
        code = (f.line or "").strip()
        lines.append(f"  {os.path.basename(f.filename)}:{f.lineno} {f.name}" + (f"  →  {code}" if code else ""))
    cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    if cause is not None and cause is not exc:
        lines.append(f"(起因 {type(cause).__name__}: {cause})")
    return "\n".join(lines)


def signature(exc: BaseException, tb=None) -> str:
    """同一个问题的"指纹":错误类型 + 最后出错的位置。用来判断是不是重复出现的同一个错误。"""
    fr = frames_of(tb if tb is not None else exc.__traceback__)
    last = fr[-1] if fr else None
    return f"{type(exc).__name__}@{os.path.basename(last.filename)}:{last.lineno}" if last else type(exc).__name__


def is_quiet(exc: BaseException) -> bool:
    return isinstance(exc, QUIET_TYPES)
