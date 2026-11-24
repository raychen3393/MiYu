"""
密语 · 程序入口
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time

from .core import DEFAULT_TCP_PORT, DEFAULT_UDP_PORT, Core


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
    last_crash = crashlog.start(store.folder)    # 闪退记录(Qt 内部出错时 Python 来不及弹窗)
    crashlog.install_qt_handler()
    theme.detect_glass_support()
    theme.setup_font(app)
    if store.is_locked():                        # 设了启动密码:先解锁
        theme.apply(app, "dark" if theme.system_prefers_dark() else "light", glass=True)
        from .window.security import LockDialog
        lock = LockDialog(store.unlock, make_icon())
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

    win.show()
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
    if win.relaunch:
        relaunch()
    return rc


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
