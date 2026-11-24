"""
Windows 全局热键(老板键)。窗口没有焦点、甚至被隐藏时也能响应。
在独立线程里 RegisterHotKey + GetMessageW,收到后通过 Qt 信号通知界面。
"""
from __future__ import annotations

import ctypes
import sys
import threading

from PySide6.QtCore import QObject, Signal

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class GlobalHotkeys(QObject):
    triggered = Signal(str)

    def __init__(self, bindings: dict, parent=None) -> None:
        """bindings: {名字: (修饰键, 虚拟键码)},例如 {"toggle": (MOD_CONTROL | MOD_ALT, ord("H"))}"""
        super().__init__(parent)
        self._bindings = list(bindings.items())
        self._tid = None
        self._thread = None
        self.failed: list[str] = []

    def start(self, timeout: float = 2.0) -> list[str]:
        """启动并返回注册失败的热键名字(被别的软件占用时会失败)。"""
        if sys.platform != "win32":
            return [name for name, _ in self._bindings]
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), name="miyu-hotkeys", daemon=True)
        self._thread.start()
        ready.wait(timeout)
        return list(self.failed)

    def _run(self, ready: threading.Event) -> None:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._tid = kernel32.GetCurrentThreadId()
        ids: dict[int, str] = {}
        for i, (name, (mods, vk)) in enumerate(self._bindings, start=1):
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                ids[i] = name
            else:
                self.failed.append(name)
        ready.set()

        msg = wintypes.MSG()
        try:
            while True:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == WM_HOTKEY:
                    name = ids.get(int(msg.wParam))
                    if name:
                        try:
                            self.triggered.emit(name)
                        except RuntimeError:   # 界面已销毁
                            break
        finally:
            for i in ids:
                user32.UnregisterHotKey(None, i)

    def stop(self) -> None:
        if sys.platform != "win32" or not self._tid:
            return
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostThreadMessageW.restype = wintypes.BOOL
        user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(1.0)
