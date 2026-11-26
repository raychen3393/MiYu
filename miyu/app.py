"""
密语 · 程序入口
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time

from .core import DEFAULT_TCP_PORT, DEFAULT_UDP_PORT, Core

INSTANCE_FILE = ".instance"


class SingleInstance:
    """3.8.2 防多开单实例锁 + 本机回环唤醒哨兵。
    按数据目录生成唯一互斥锁：双击多次时第 2 个进程直接唤醒已有窗口并退出，
    绝不与已运行进程争抢 p.bin / m.db，避免误弹登录框或损坏聊天记录。"""

    def __init__(self, folder: str) -> None:
        self.folder = os.path.abspath(folder)
        self._tag = hashlib.sha256(self.folder.lower().encode("utf-8")).hexdigest()[:24]
        self._mutex = None
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._token = ""
        self._on_wake = None
        self.acquired = False

    def _info_path(self) -> str:
        return os.path.join(self.folder, INSTANCE_FILE)

    def acquire(self) -> bool:
        if sys.platform == "win32":
            try:
                import ctypes
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
                k32.CreateMutexW.restype = ctypes.c_void_p
                h = k32.CreateMutexW(None, False, f"Local\\MiYu_SingleInstance_{self._tag}")
                err = ctypes.get_last_error()
                if h and err == 183:  # ERROR_ALREADY_EXISTS
                    k32.CloseHandle(h)
                    return False
                self._mutex = h
            except Exception:
                self._mutex = None
        self.acquired = True
        self._start_listener()
        return True

    def _start_listener(self) -> None:
        try:
            os.makedirs(self.folder, exist_ok=True)
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", 0))
            srv.listen(4)
            srv.settimeout(0.5)
            port = srv.getsockname()[1]
            self._sock = srv
            self._token = secrets.token_hex(16)
            tmp = f"{self._info_path()}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"port": port, "token": self._token, "pid": os.getpid()}, f)
            os.replace(tmp, self._info_path())
            threading.Thread(target=self._serve, name="miyu-wake", daemon=True).start()
        except OSError:
            self._sock = None

    def set_wake_handler(self, fn) -> None:
        self._on_wake = fn

    def _serve(self) -> None:
        srv = self._sock
        if srv is None:
            return
        expect = f"WAKE {self._token}".encode("ascii")
        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(0.5)
                data = conn.recv(128)
                if data.strip() == expect:
                    conn.sendall(b"OK")
                    cb = self._on_wake
                    if callable(cb):
                        cb()
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def wake_existing(self) -> bool:
        """通知已在运行的密语进程将主窗口唤醒置顶。"""
        for _ in range(4):
            try:
                with open(self._info_path(), encoding="utf-8") as f:
                    d = json.load(f)
                port, tok = int(d["port"]), str(d["token"])
                with socket.create_connection(("127.0.0.1", port), timeout=0.6) as s:
                    s.sendall(f"WAKE {tok}".encode("ascii"))
                    if s.recv(16).startswith(b"OK"):
                        return True
            except Exception:
                time.sleep(0.18)
        return False

    def release(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self.acquired:
            try:
                if os.path.exists(self._info_path()):
                    os.remove(self._info_path())
            except OSError:
                pass
        if self._mutex is not None and sys.platform == "win32":
            try:
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(self._mutex)
            except Exception:
                pass
            self._mutex = None
        self.acquired = False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="MiYu", description="密语 · 局域网加密聊天")
    parser.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT, help="发现广播端口(所有人必须一致)")
    parser.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT, help="首选连接端口(被占用会自动换)")
    parser.add_argument("--debug", action="store_true", help="在控制台输出调试信息(不写文件)")
    parser.add_argument("--selftest", action="store_true", help="只检查程序能不能启动,然后退出(打包时用)")
    args, _ = parser.parse_known_args(argv)
    if args.selftest:
        from . import gui, selfcheck, update  # noqa: F401  能导入就说明打包没缺东西
        return 1 if selfcheck.has_failure(selfcheck.run_checks(network=False)) else 0
    from . import update as _update
    _update.cleanup_old()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MiYu.LanChat")
        except Exception:
            pass

    from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
    from PySide6.QtWidgets import QApplication

    from . import gui
    from .dialogs import StartDialog, info
    from .ui import make_icon
    from .widgets import Bridge
    from . import motion

    app = QApplication(sys.argv[:1])
    app.setApplicationName("MiYu")
    app.setQuitOnLastWindowClosed(False)      # 窗口被老板键隐藏时,关掉弹窗不能让程序退出
    from .window.system import error_log
    error_log().install()                     # 没被处理的错误弹出出错报告窗口,而不是悄悄吞掉
    motion.install(app)                       # 按钮悬停动效(全局)
    translator = QTranslator(app)
    if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)

    from . import crashlog, crypto as C, storage, theme
    store = storage.AccountStore()
    guard = SingleInstance(store.folder)
    if not guard.acquire():
        guard.wake_existing()                    # 已有密语进程在运行:直接唤醒原窗口并安静退出,绝不抢读写数据
        return 0
    try:
        last_crash = crashlog.start(store.folder)    # 闪退记录(Qt 内部出错时 Python 来不及弹窗)
        crashlog.install_qt_handler()
        theme.detect_glass_support()
        theme.setup_font(app)
        if store.is_locked():                        # 设了启动密码:先解锁
            theme.apply(app, "dark" if theme.system_prefers_dark() else "light", glass=True)
            from .window.security import LockDialog
            lock = LockDialog(store.unlock, make_icon())
            guard.set_wake_handler(lambda: QTimer.singleShot(0, lambda: (lock.showNormal(), lock.raise_(), lock.activateWindow())))
            if not lock.exec():
                if not lock.forgot:
                    return 0
                store.wipe(stickers=False)           # 忘记密码:只能注销,重新开始
        account = store.load_account()               # 记住了登录 → 直接用保存的身份进入,不再问昵称
        settings = (account or {}).get("settings") or {}

        name = settings.get("theme") if not settings.get("follow_system", True) else None
        variant = None
        if settings.get("follow_time"):
            t = time.localtime()
            name, variant, _ = theme.period_for(t.tm_hour + t.tm_min / 60)
        if name not in theme.THEMES:
            name = "dark" if theme.system_prefers_dark() else "light"
        theme.set_custom(settings.get("custom"))                 # 个性化:主题色、气泡颜色、透明度
        motion.set_enabled(settings.get("motion", True))         # 界面动效
        theme.apply(app, name, glass=bool(settings.get("glass", True)), variant=variant)
        icon = make_icon()
        app.setWindowIcon(icon)

        if account:
            core = Core(udp_port=args.udp_port, tcp_port=args.tcp_port,
                        identity=C.Identity(storage.b64d(account["seed"])))
            nick, lobby = account.get("nick") or None, bool(account.get("lobby", True))
            remember, save_history = True, bool(settings.get("save_history"))
        else:
            core = Core(udp_port=args.udp_port, tcp_port=args.tcp_port)
            start = StartDialog(core.nick, icon)
            guard.set_wake_handler(lambda: QTimer.singleShot(0, lambda: (start.showNormal(), start.raise_(), start.activateWindow())))
            if not start.exec():
                return 0
            nick, lobby = start.nickname or None, start.join_lobby
            remember, save_history = start.remember_me, start.save_history

        bridge = Bridge()
        win = gui.MainWindow(core, icon, lobby, store=store, account=account, remember=remember,
                             save_history=save_history)
        bridge.event.connect(win.on_core_event)
        core.on_event = bridge.event.emit            # 后台线程发信号,Qt 自动排队到界面线程

        if not core.start(nick=nick, lobby=lobby):
            info(None, "启动失败",
                     f"网络模块启动失败:{core.start_error}\n\n"
                     f"可能是 UDP {args.udp_port} 端口被其他程序占用。关闭占用的程序后再试。", warn=True)
            return 1
        win.restore_after_start()
        if remember and not account:
            QTimer.singleShot(1500, lambda: win.save_account(force=True))   # 等昵称、IP 等信息就绪后保存

        hotkeys = None
        failed: list[str] = []
        if sys.platform == "win32":
            from .hotkey_win import MOD_ALT, MOD_CONTROL, GlobalHotkeys
            hotkeys = GlobalHotkeys({
                "toggle": (MOD_CONTROL | MOD_ALT, ord("H")),
                "panic": (MOD_CONTROL | MOD_ALT, ord("X")),
            })
            hotkeys.triggered.connect(win.on_hotkey)
            failed = hotkeys.start()
            win.hotkeys_ok = "toggle" not in failed

        def _wake_main() -> None:
            if hasattr(win, "show_window"):
                win.show_window()
            else:
                win.showNormal()
                win.raise_()
                win.activateWindow()

        guard.set_wake_handler(lambda: QTimer.singleShot(0, _wake_main))
        win.show()
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            threading.Thread(target=sync_uninstaller, name="miyu-uninst-sync", daemon=True).start()
        if last_crash:                               # 上次闪退了:告诉用户出事的位置,方便反馈
            win.last_crash = crashlog.summary(last_crash)
            QTimer.singleShot(1500, win.show_crash_report)
        if hotkeys is not None and failed:
            names = {"toggle": "Ctrl+Alt+H", "panic": "Ctrl+Alt+X"}
            keys = "、".join(names[n] for n in failed)
            QTimer.singleShot(400, lambda: win._system(
                win.convs["lobby"], f"提示:全局热键 {keys} 被其他软件占用,只能在本窗口有焦点时使用。"))

        rc = app.exec()
        if hotkeys is not None:
            hotkeys.stop()
        core.stop()
        crashlog.stop()                              # 正常退出:没有闪退,删掉记录
        do_relaunch = bool(win.relaunch)
    finally:
        guard.release()                              # 必须在 relaunch 新进程启动前释放单实例锁
    if do_relaunch:
        relaunch()
    return rc


def bundled_asset(name: str) -> str | None:
    """查找打包内置的 assets/<name> 文件（兼容冻结单文件与源码运行）。"""
    roots: list[str] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        roots.append(getattr(sys, "_MEIPASS"))
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for r in roots:
        p = os.path.join(r, "assets", name)
        if os.path.isfile(p):
            return p
    return None


def sync_uninstaller(target_dir: str | None = None) -> str | None:
    """将内置的轻量 Uninstall.exe 自动同步到 MiYu.exe 同目录（按大小+SHA256 校验，存在最新版不重复写）。"""
    if sys.platform != "win32":
        return None
    src = bundled_asset("Uninstall.exe")
    if not src:
        return None
    dst_dir = target_dir or (os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else "")
    if not dst_dir or not os.path.isdir(dst_dir):
        return None
    dst = os.path.join(dst_dir, "Uninstall.exe")
    try:
        with open(src, "rb") as f:
            raw = f.read()
        if os.path.isfile(dst) and os.path.getsize(dst) == len(raw):
            with open(dst, "rb") as f:
                if hashlib.sha256(f.read()).digest() == hashlib.sha256(raw).digest():
                    return dst
        tmp = os.path.join(dst_dir, f".Uninstall.{os.getpid()}.tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return dst
    except OSError:
        return dst if os.path.isfile(dst) else None


def relaunch() -> None:
    """注销账户后以全新身份重新打开软件。"""
    env = os.environ.copy()
    # PyInstaller 单文件版:让新进程重新解压,不要沿用即将被删除的临时目录
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for k in list(env):
        if k == "_MEIPASS2" or k.startswith("_PYI_"):
            env.pop(k, None)
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        cmd = [sys.executable, main_py] if os.path.exists(main_py) else [sys.executable, "-m", "miyu"]
    cmd += sys.argv[1:]
    flags = 0
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(cmd, env=env, close_fds=True, creationflags=flags)
    except OSError:
        pass
