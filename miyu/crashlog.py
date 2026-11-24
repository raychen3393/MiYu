"""
密语 · 闪退记录

有些错误发生在 Qt(界面库)内部,程序会被系统直接结束,Python 来不及弹出"出错了"窗口 —— 用户看到的就是闪退。
这里在启动时打开 Python 自带的 faulthandler:出事的那一刻,把每个线程正在执行的代码位置
(只有文件名、行号、函数名,没有任何聊天内容)写进数据文件夹里的 crash.log;Qt 自己报的警告也顺手记下。
正常退出时删掉这个文件;下次启动如果发现里面有闪退记录,就弹窗给用户看,可以一键复制发给开发者。
"""
from __future__ import annotations

import faulthandler
import os
import time

FILE = "crash.log"
MARKERS = ("Fatal Python error", "Windows fatal exception", "Current thread", "Thread 0x", "[Qt 致命]")
MAX_QT_LINES = 200

_fh = None
_path = ""
_qt_count = 0


def start(folder: str) -> str:
    """开始记录。返回上一次闪退留下的记录(没有闪退返回空字符串)。"""
    global _fh, _path
    prev = ""
    try:
        os.makedirs(folder, exist_ok=True)
        _path = os.path.join(folder, FILE)
        if os.path.exists(_path):
            with open(_path, encoding="utf-8", errors="replace") as f:
                text = f.read(60_000)
            if any(m in text for m in MARKERS):          # 只有真的出过事才算(被任务管理器结束、断电不算)
                prev = text
            os.remove(_path)
        _fh = open(_path, "w", encoding="utf-8")
        from .errors import env_line
        _fh.write(f"{env_line()}\n启动时间 {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        _fh.flush()
        faulthandler.enable(file=_fh, all_threads=True)
    except Exception:                                     # noqa: BLE001  记录不了也不影响使用
        _fh = None
    return prev


def install_qt_handler() -> None:
    """Qt 的警告 / 严重错误也写进去(闪退前 Qt 常常会先报一句为什么)。"""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:                                     # noqa: BLE001
        return
    levels = {QtMsgType.QtWarningMsg: "Qt 警告", QtMsgType.QtCriticalMsg: "Qt 严重", QtMsgType.QtFatalMsg: "Qt 致命"}

    def handler(kind, ctx, msg):
        global _qt_count
        name = levels.get(kind)
        if name is None or _fh is None or _qt_count >= MAX_QT_LINES:
            return
        _qt_count += 1
        try:
            where = f" ({os.path.basename(ctx.file or '')}:{ctx.line})" if ctx is not None and ctx.file else ""
            _fh.write(f"[{name}] {time.strftime('%H:%M:%S')} {msg}{where}\n")
            _fh.flush()
        except Exception:                                 # noqa: BLE001
            pass
    qInstallMessageHandler(handler)


def stop() -> None:
    """正常退出:关掉记录并删掉文件。"""
    global _fh
    try:
        faulthandler.disable()
    except Exception:                                     # noqa: BLE001
        pass
    if _fh is not None:
        try:
            _fh.close()
        except Exception:                                 # noqa: BLE001
            pass
        _fh = None
    try:
        if _path and os.path.exists(_path):
            os.remove(_path)
    except OSError:
        pass


def summary(text: str, limit: int = 40) -> str:
    """给用户看的版本:只留前面的环境信息和出事时主线程的调用位置,去掉电脑上的完整路径。"""
    out = []
    for line in text.splitlines():
        line = line.rstrip()
        if 'File "' in line:                              # File "C:\...\miyu\gui.py", line 123 in send_current
            try:
                head, rest = line.split('File "', 1)
                path, tail = rest.split('"', 1)
                line = f'{head}File "{os.path.basename(path)}"{tail}'
            except ValueError:
                pass
        out.append(line)
        if len(out) >= limit:
            out.append("……")
            break
    return "\n".join(out)
