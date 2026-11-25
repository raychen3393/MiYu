"""
密语 · 主窗口
MainWindow 负责搭界面、会话和消息、发送、文件传输、外观和菜单、账户保存。
各项功能按主题放在 window/ 文件夹里(见 window/__init__.py),以"混入类"的方式组合进来。
"""
from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import threading
import time

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation, QSize, QStandardPaths, QTimer, QUrl, Qt,
)
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu, QToolButton, QVBoxLayout, QWidget,
)

from . import imaging, motion, storage, stream, theme
from .bubblefx import MODE_IDS as BUBBLE_MODES, BubbleFx
from .core import Core, MAX_NICK, MAX_TEXT, clean_nick
from .dialogs import (
    ImageViewer, JoinRoomDialog, LogoutDialog, SafetyDialog, SendImageDialog, TextDialog, ask, compose_collage, info,
    prompt,
)
from .fun import (
    ACC_BY_ID, EVOLVE_LEVEL, EffectLayer, PetGrowth, SPECIES, TypingBubble, TypingPet, detect_effect,
)
from .icons import avatar, icon
from .sound import KeySound, Notifier
from .stickers import StickerStore
from .theme import T
from .ui import (
    APP_NAME, BURN_CHOICES, DANGER_EXTS, GROUP_GAP, HEADER_H, HEAT_HALF_LIFE, HEAT_IN, HEAT_KEY, HEAT_OUT, LOBBY_COLOR,
    ROOM_COLOR, TIME_GAP, VIDEO_EXTS, color_for, drop_paths, file_ext, fmt_secs, hline, label,
    make_menu, peer_avatar, popup, repolish, tool,
)
from .widgets import (
    Bubble, ChatInput, ChatPanel, ClickFrame, Conv, ConvDelegate, EmojiPanel, MemberDelegate, Msg, MsgArea,
    SearchEdit, TimeSep, Wallpaper,
)
from .window.chat import ChatMixin
from .window.duck import DuckMixin
from .window.spy import SpyMixin
from .window.enter import EnterMixin
from .window.events import EventsMixin
from .window.favorites import FavoritesMixin
from .window.files import FilesMixin
from .window.games import GamesMixin
from .window.gomoku import GomokuMixin
from .window.look import LookMixin
from .window.pet import PetMixin
from .window.petlife import PetLifeMixin
from .window.petrank import PetRankMixin
from .window.records import RecordsMixin
from .window.security import SecurityMixin
from .window.settings import SettingsMixin
from .window.style import StyleMixin
from .window.system import SystemMixin
from .window.throws import ThrowsMixin
from .window.ux import UxMixin


SECURITY_TEXT = (
    "能做到\n"
    "· 不需要服务器、不连外网,消息直接在两台电脑之间传\n"
    "· 全程加密(X25519 + ChaCha20-Poly1305),每条连接使用临时密钥,事后泄露也解不开以前的消息\n"
    "· 暗号群:不知道暗号的人抓包只能看到随机数据,看不出有群,也看不出谁在群里\n"
    "· 隐身:只有同暗号的人能发现你,别人连你的端口什么也得不到\n"
    "· 身份随机生成,不绑定任何真实信息\n"
    "· 「记住登录」和「保存聊天记录」的内容用 Windows DPAPI 加密存在本机,换电脑或换账号打不开;"
    "阅后即焚的消息永远不保存;「注销账户」会覆盖后删除\n"
    "· 设了启动密码时,保存的账户和记录再用密码派生的密钥(scrypt + ChaCha20)加密一层,别人用你的电脑也打不开\n"
    "· 匿名纸条先在群成员之间随机转交几手才发出,收到的人连电脑层面都分辨不出作者;猜拳先交「承诺」再揭晓,谁也偷看不到\n"
    "· 发送图片前自动去掉照片里的位置、设备等信息\n\n"
    "做不到\n"
    "· 公开大厅里的内容,任何装了这个软件的人都能看到\n"
    "· 网管能看到你在和哪些 IP 通信、流量多少(看不到内容)\n"
    "· 电脑被装了监控或录屏软件,任何加密都防不住\n"
    "· 阅后即焚防不了对方截图或拍照\n"
    "· 暗号太简单可能被离线猜中"
)


STICKER_GIF_MAX = 2 * 1024 * 1024     # 动图表情包最大 2MB(太大的动图收藏成静态图)


class MainWindow(EventsMixin, SecurityMixin, ChatMixin, FavoritesMixin, FilesMixin, GamesMixin, PetMixin, PetLifeMixin,
                 LookMixin, StyleMixin, UxMixin, RecordsMixin, SystemMixin, SettingsMixin, GomokuMixin, ThrowsMixin,
                 PetRankMixin, DuckMixin, SpyMixin, EnterMixin, QMainWindow):
    # 各功能模块(window/ 文件夹)的钩子按这个顺序调用,见 window/__init__.py
    TOPICS = ("security", "chat", "files", "games", "pet", "petlife", "look", "style", "ux", "records", "system",
              "gomoku", "throws", "petrank", "duck", "spy", "enter")

    def _hooks(self, kind: str, *args) -> list:
        """调用每个功能模块的 _<kind>_<模块> 钩子(没有就跳过),返回结果列表。"""
        out = []
        for t in self.TOPICS:
            fn = getattr(self, f"_{kind}_{t}", None)
            if fn is not None:
                out.append(fn(*args))
        return out

    def _merged(self, kind: str) -> dict:
        d: dict = {}
        for part in self._hooks(kind):
            d.update(part or {})
        return d

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if getattr(self, "lock_overlay", None) is not None and self.lock_overlay.isVisible():
            self.lock_overlay.setGeometry(self.centralWidget().rect())
        if getattr(self, "eye_overlay", None) is not None:
            self.eye_overlay.setGeometry(self.centralWidget().rect())
        if getattr(self, "throw_layer", None) is not None and self.throw_layer.isVisible():
            self.throw_layer.setGeometry(self.centralWidget().rect())
    def __init__(self, core: Core, app_icon: QIcon, lobby: bool, store: "storage.AccountStore | None" = None,
                 account: dict | None = None, remember: bool = False, save_history: bool = False) -> None:
        super().__init__()
        if theme.GLASS_SUPPORTED:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._glass_capable = True
        self.core = core
        self.me = core.self_info()
        self.me["lobby"] = lobby
        self.peers: dict[str, dict] = {}
        self.convs: dict[str, Conv] = {}
        self.current_key = "lobby"
        self.bubbles: dict[str, Bubble] = {}
        self.bubble_fx = BubbleFx()                # 气泡动效:出场 / 撤回碎掉 / @我晃一晃 / 回应弹一下
        Bubble.react_hook = lambda chip, e: self.bubble_fx.react_pop(chip, e, self.msg_container, theme.is_dark())
        self.burn_secs = 0
        self._stick = True
        self._view_last_time: float | None = None
        self._force_quit = False
        self._warned_hide = False
        self._viewers: list[ImageViewer] = []
        self._shadows: list[tuple[QGraphicsDropShadowEffect, float]] = []
        self.flash_enabled = True
        self.hotkeys_ok = False
        self.notifier = Notifier()
        self.sound_enabled = True          # 总开关
        self.sound_when_hidden = False     # 窗口被老板键隐藏时默认不响,以免暴露
        self.follow_system = True          # 外观跟随 Windows 设置
        self.frameless = sys.platform == "win32"   # Windows 默认无边框通顶窗口
        self.compact_side = False                  # 左侧会话栏紧凑模式(74px 头像轨)
        self.members_open = True                   # 右侧成员栏展开状态
        self._drag_win_pos: QPoint | None = None
        self.reply_to: Msg | None = None   # 正在引用回复的消息
        self.pending_at: dict[str, str] = {}   # 输入框里 @ 过的人:昵称 → id("all" = 所有人)
        self.transfers: dict[str, dict] = {}   # 文件传输状态 fid → {...}
        self.typing_until: dict[str, float] = {}
        self._typing_sent: dict[str, float] = {}
        self.send_receipts = True          # 发送"已读"
        self.send_typing_on = True         # 发送"正在输入"
        self.recent_emojis: list[str] = []
        self.stickers = StickerStore()
        # 趣味互动设置(只存在本次运行)
        self.fun = {"pet": "cat", "sparks": True, "combo": True, "send_anim": True, "effects": True, "keysound": False,
                    "heat": True, "skin": None, "fx": "spark", "snd": "default", "bubble": "soft", "skits": True,
                    "rank": True, "gpet": True, "lv_badge": True, "throw_fx": True, "pet_beat": True}
        self.keysound = KeySound()
        self.typing_bubble: TypingBubble | None = None
        self._fx_last: dict[tuple, float] = {}
        # 账户保存(记住我)
        self.store = store
        self.account = account or {}
        self.remember = bool(remember and store is not None)
        self.save_history = bool(save_history and self.remember)
        self.room_keys: dict[str, dict] = {}     # 群 tag → {"master", "name"},用来下次自动恢复暗号群
        self.verified_ids: set[str] = set()
        self.muted_keys: set[str] = set()
        self.pinned_keys: list[str] = []         # 置顶的会话(按置顶先后)
        self.relaunch = False                    # 注销后重新启动
        self.last_crash = ""                     # 上次闪退的记录(app.py 启动时读出来)
        self._acct_snapshot = ""
        self._hist_dirty = False
        self._save_tick = 0
        self.heat_timer = QTimer(self)           # 聊天热度光晕的动画(要在界面建好、切换会话之前就存在)
        self.heat_timer.setInterval(140)
        self.heat_timer.timeout.connect(self._heat_step)

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon)
        self._apply_window_frame(initial=True)
        self.resize(1160, 760)
        self.setMinimumSize(860, 560)
        self.setAcceptDrops(True)
        self._build()
        self.pet_growth = PetGrowth(self.account.get("pet"))
        self.pet.growth = self.pet_growth
        self._hooks("init")
        self.chat_panel.extras_cb = lambda: self._hooks("place")
        if self.account:
            self._restore_settings(self.account)

        lobby_conv = Conv("lobby", "lobby", "公开大厅")
        self.convs["lobby"] = lobby_conv
        self._apply_conv_prefs(lobby_conv)
        self._system(lobby_conv, "同一局域网里进入大厅的人都在这里,内容所有人可见。私密内容请用私聊或暗号群。\n"
                                 "按 ESC 软件会立即消失(不会退出),按 Ctrl+Alt+H 叫回来。")
        self._init_self_conv()
        if self.save_history:
            self.open_history()                  # 加密数据库:读出每个会话最近的一页
        self._refresh_icons()
        self._refresh_self()
        self._apply_fun()
        self._refresh_conv_list()
        self.switch_to("lobby")

        self.tick = QTimer(self)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start(1000)
        find = QShortcut(QKeySequence("Ctrl+F"), self)
        find.setContext(Qt.ShortcutContext.WindowShortcut)
        find.activated.connect(self.open_search)
        prefs = QShortcut(QKeySequence("Ctrl+,"), self)        # 设置(只在密语窗口里有效)
        prefs.setContext(Qt.ShortcutContext.WindowShortcut)
        prefs.activated.connect(lambda: self.show_settings())

        for seq, fn in (("Ctrl+Alt+H", self.toggle_hidden), ("Ctrl+Alt+X", self.panic)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(fn)
        # ESC:弹窗 / 看大图 / 表情面板 / 菜单里按 ESC 只关它们自己;
        # 在主窗口按 ESC,整个软件从屏幕和任务栏上消失(不退出),Ctrl+Alt+H 叫回
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.setContext(Qt.ShortcutContext.WindowShortcut)
        esc.activated.connect(self.on_escape)

    # ------------------------------------------------------------ 布局
    def _build(self) -> None:
        central = Wallpaper()
        central.setObjectName("central")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_chat(), 1)
        root.addWidget(self._build_members())
        self.setCentralWidget(central)

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(284)
        self.sidebar_panel = side
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 16, 12, 10)
        lay.setSpacing(6)
        self._side_lay = lay

        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 0, 0)
        self.rail_btn = tool("sidebar", 32, "round", "收起 / 展开会话侧边栏(紧凑摸鱼模式)")
        self.rail_btn.clicked.connect(lambda: self.set_compact_side(not self.compact_side))
        head.addWidget(self.rail_btn)
        self.side_title = label(APP_NAME, "largeTitle")
        head.addWidget(self.side_title)
        head.addStretch(1)
        self.gomoku_btn = tool("gomoku", 32, "round", "五子棋:大厅、排行榜、我的战绩")
        self.gomoku_btn.clicked.connect(lambda: self.open_gomoku())
        head.addWidget(self.gomoku_btn)
        self.duck_btn = tool("duck", 32, "round", "派对游戏:谁是坏鸭、谁是卧底(4~10 人联机)")
        self.duck_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        party = make_menu(self)
        party.addAction("🦆  谁是坏鸭(地图上跑动的推理游戏)", lambda: self.open_duck())
        party.addAction("🕵  谁是卧底(说一句话猜身份)", lambda: self.open_spy())
        self.duck_btn.setMenu(party)
        head.addWidget(self.duck_btn)
        self.theme_btn = tool("", 32, "round", "外观")
        self.theme_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.theme_menu = make_menu(self)
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)
        self.theme_btn.setMenu(self.theme_menu)
        head.addWidget(self.theme_btn)
        self.add_btn = tool("plus", 32, "round", "加入暗号群 / 手动添加 IP")
        self.add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_menu = make_menu(self)
        self._menu_icon(self.add_menu.addAction("加入 / 创建暗号群", self.join_room_dialog), "lock")
        self._menu_icon(self.add_menu.addAction("手动添加对方 IP", self.add_manual_ip), "wifi")
        self.add_btn.setMenu(self.add_menu)
        head.addWidget(self.add_btn)
        lay.addLayout(head)
        lay.addSpacing(8)

        self.conv_list = QListWidget()
        self.conv_list.setItemDelegate(ConvDelegate(self))
        self.conv_list.setMouseTracking(True)
        self.conv_list.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.conv_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.conv_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.conv_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.conv_list.customContextMenuRequested.connect(self._conv_menu)
        self.conv_list.currentItemChanged.connect(self._on_conv_changed)
        lay.addWidget(self.conv_list, 1)

        lay.addWidget(hline())
        me = ClickFrame()
        me.setObjectName("meCard")
        me.setCursor(Qt.CursorShape.PointingHandCursor)
        me.setToolTip("查看我的身份与指纹(紧凑模式下打开设置)")
        me.clicked.connect(lambda: self.show_settings() if self.compact_side else self.show_identity())
        ml = QHBoxLayout(me)
        ml.setContentsMargins(8, 8, 4, 8)
        ml.setSpacing(10)
        self._me_lay = ml
        self.me_avatar = QLabel()
        self.me_avatar.setFixedSize(36, 36)
        ml.addWidget(self.me_avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.me_name = label("", "meName")
        self.me_sub = label("", "subtitle")
        col.addWidget(self.me_name)
        col.addWidget(self.me_sub)
        ml.addLayout(col, 1)
        self.menu_btn = tool("sliders", 32, "round", "设置  Ctrl+,")
        self._build_menu()                                  # 2.0:菜单里的开关仍是状态的"真身",设置窗口直接读写它们
        self.menu_btn.clicked.connect(lambda: self.show_settings())
        ml.addWidget(self.menu_btn)
        lay.addWidget(me)
        side.installEventFilter(self)
        return side

    def _menu_icon(self, action, name: str):
        action.setProperty("iconName", name)
        action.setIcon(icon(name, T["icon"], 16))
        return action

    def _build_menu(self) -> QMenu:
        m = make_menu(self)
        self._menu_icon(m.addAction("修改昵称…", self.change_nick), "pencil")
        self._menu_icon(m.addAction("我的身份与指纹", self.show_identity), "user")
        m.addSeparator()
        self.act_lobby = QAction("在公开大厅中显示我", self)
        self.act_lobby.setCheckable(True)
        self.act_lobby.setChecked(self.me.get("lobby", True))
        self.act_lobby.triggered.connect(self.toggle_lobby)
        m.addAction(self.act_lobby)
        self.act_glass = QAction("毛玻璃效果" if theme.GLASS_SUPPORTED else "毛玻璃效果(需要 Windows 11)", self)
        self.act_glass.setCheckable(True)
        self.act_glass.setChecked(theme.GLASS)
        self.act_glass.setEnabled(theme.GLASS_SUPPORTED)
        self.act_glass.triggered.connect(self.toggle_glass)
        m.addAction(self.act_glass)
        self._menu_icon(m.addAction("个性化外观(主题、颜色、透明度、背景图)…", lambda: self.show_personalize()), "palette")
        self.act_sound = QAction("消息提示音", self)
        self.act_sound.setCheckable(True)
        self.act_sound.setChecked(True)
        self.act_sound.triggered.connect(self.set_sound_enabled)
        m.addAction(self.act_sound)
        self.act_sound_hidden = QAction("窗口隐藏时也响提示音", self)
        self.act_sound_hidden.setCheckable(True)
        self.act_sound_hidden.setChecked(False)
        self.act_sound_hidden.triggered.connect(lambda on: setattr(self, "sound_when_hidden", on))
        m.addAction(self.act_sound_hidden)
        self._menu_icon(m.addAction("试听提示音", lambda: self.notifier.play(force=True)), "bell")
        m.addSeparator()
        self.fun_menu = make_menu(self)
        self.fun_menu.setTitle("趣味互动")
        self.fun_menu.aboutToShow.connect(self._fill_fun_menu)
        self._menu_icon(m.addMenu(self.fun_menu), "smile")
        m.addSeparator()
        self.act_flash = QAction("新消息时闪烁任务栏", self)
        self.act_flash.setCheckable(True)
        self.act_flash.setChecked(True)
        self.act_flash.triggered.connect(lambda on: setattr(self, "flash_enabled", on))
        m.addAction(self.act_flash)
        m.addAction("窗口标题伪装…", self.disguise_title)
        self.act_drop_confirm = QAction("拖进来的图片和文件先确认再发送", self)
        self.act_drop_confirm.setCheckable(True)
        self.act_drop_confirm.setChecked(False)
        self.act_drop_confirm.triggered.connect(lambda on: setattr(self, "drop_confirm", on))
        m.addAction(self.act_drop_confirm)
        m.addSeparator()
        self.act_receipts = QAction("私聊发送「已读」", self)
        self.act_receipts.setCheckable(True)
        self.act_receipts.setChecked(True)
        self.act_receipts.triggered.connect(lambda on: setattr(self, "send_receipts", on))
        m.addAction(self.act_receipts)
        self.act_typing = QAction("私聊发送「正在输入」", self)
        self.act_typing.setCheckable(True)
        self.act_typing.setChecked(True)
        self.act_typing.triggered.connect(lambda on: setattr(self, "send_typing_on", on))
        m.addAction(self.act_typing)
        self._menu_icon(m.addAction("清空表情包…", self.clear_stickers), "smile")
        m.addSeparator()
        self.act_remember = QAction("记住登录(下次自动进入)", self)
        self.act_remember.setCheckable(True)
        self.act_remember.setChecked(self.remember)
        self.act_remember.setEnabled(self.store is not None)
        self.act_remember.triggered.connect(self.toggle_remember)
        m.addAction(self.act_remember)
        self.act_history = QAction("保存聊天记录", self)
        self.act_history.setCheckable(True)
        self.act_history.setChecked(self.save_history)
        self.act_history.setEnabled(self.store is not None)
        self.act_history.triggered.connect(self.toggle_history)
        m.addAction(self.act_history)
        self._menu_icon(m.addAction("启动密码…", lambda: self.set_password_dialog()), "lock")
        m.addAction("📈  聊天年报…", lambda: self.show_report())
        self.act_privacy = QAction("防偷看模式(离开窗口时模糊聊天内容)", self)
        self.act_privacy.setCheckable(True)
        self.act_privacy.setChecked(True)
        self.act_privacy.triggered.connect(lambda on: self.set_privacy(on))
        m.addAction(self.act_privacy)
        self.avatar_menu_host = m
        m.addAction("🖼  选择头像图片…", lambda: self.choose_avatar())
        m.addAction("🐾  用宠物当头像", lambda: self.use_pet_avatar())
        m.addAction("↩  恢复默认头像", lambda: self.set_avatar(None))
        m.addSeparator()
        self.update_menu = make_menu(m)
        self.update_menu.setTitle("软件更新")
        self.update_menu.aboutToShow.connect(lambda: self._fill_update_menu())
        m.addMenu(self.update_menu)
        m.addAction("🗂  数据管理(位置、占用、一键清理)…", lambda: self.show_data())
        m.addAction("🩺  诊断信息和出错记录…", lambda: self.show_diagnostics())
        m.addSeparator()
        self._menu_icon(m.addAction("隐藏窗口\tCtrl+Alt+H", self.hide_window), "eye_off")
        self._menu_icon(m.addAction("清空记录并隐藏\tCtrl+Alt+X", self.panic), "trash")
        m.addSeparator()
        self._menu_icon(m.addAction("安全说明", self.show_security), "info")
        self._menu_icon(m.addAction("注销账户…", self.logout), "logout")
        self.act_quit = self._menu_icon(m.addAction("退出(保留账户)" if self.remember else "退出", self.close), "power")
        self.main_menu = m
        return m

    def _build_chat(self) -> QWidget:
        panel = ChatPanel()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.msg_area = MsgArea()
        self.msg_area.setObjectName("msgArea")
        self.msg_area.setWidgetResizable(True)
        self.msg_area.setFrameShape(QFrame.Shape.NoFrame)
        self.msg_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.msg_area.viewport().setAutoFillBackground(False)
        self.msg_container = QWidget()
        self.msg_container.setObjectName("msgContainer")
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setContentsMargins(0, HEADER_H + 6, 0, 10)
        self.msg_layout.setSpacing(2)
        self.msg_layout.addStretch(1)                      # 消息贴底显示
        self.msg_area.setWidget(self.msg_container)
        self.msg_area.resized.connect(self._refit_bubbles)
        sb = self.msg_area.verticalScrollBar()
        sb.rangeChanged.connect(self._on_range_changed)
        sb.valueChanged.connect(self._on_scroll)
        lay.addWidget(self.msg_area, 1)

        # 浮动顶栏
        header = QFrame(panel)
        header.setObjectName("chatHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 10, 14, 10)
        hl.setSpacing(12)
        self.chat_avatar = QLabel()
        self.chat_avatar.setFixedSize(36, 36)
        hl.addWidget(self.chat_avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.chat_title = label("", "title")
        self.chat_sub = label("", "subtitle")
        col.addWidget(self.chat_title)
        col.addWidget(self.chat_sub)
        hl.addLayout(col, 1)
        self.verify_btn = QToolButton()
        self.verify_btn.setObjectName("textBtn")
        self.verify_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.verify_btn.setIconSize(QSize(17, 17))
        self.verify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.verify_btn.clicked.connect(self.verify_current)
        hl.addWidget(self.verify_btn)
        self.prank_btn = tool("trophy", 34, "round", "宠物等级排行榜")
        self.prank_btn.clicked.connect(lambda: self.open_pet_rank())
        hl.addWidget(self.prank_btn)
        self.search_btn = tool("search", 34, "round", "搜索聊天记录(Ctrl+F)")
        self.search_btn.clicked.connect(self.open_search)
        hl.addWidget(self.search_btn)
        self.bell_btn = tool("bell", 34, "round")
        self.bell_btn.clicked.connect(self.toggle_mute_current)
        hl.addWidget(self.bell_btn)
        self.clear_btn = tool("trash", 34, "round", "清空本机上的这段记录")
        self.clear_btn.clicked.connect(self.clear_current)
        hl.addWidget(self.clear_btn)
        self.members_btn = tool("users", 34, "round", "显示 / 隐藏右侧成员栏")
        self.members_btn.clicked.connect(lambda: self.set_members_open(not self.members_open))
        hl.addWidget(self.members_btn)
        self.win_bar = QWidget(header)
        wl = QHBoxLayout(self.win_bar)
        wl.setContentsMargins(4, 0, 0, 0)
        wl.setSpacing(2)
        self.min_btn = tool("minimize", 30, "winBtn", "最小化")
        self.min_btn.setStyleSheet("")
        self.min_btn.clicked.connect(self.showMinimized)
        self.max_btn = tool("maximize", 30, "winBtn", "最大化 / 还原")
        self.max_btn.setStyleSheet("")
        self.max_btn.clicked.connect(self.toggle_maximize)
        self.close_btn = tool("close", 30, "winClose", "隐藏窗口(Esc) · 右键退出")
        self.close_btn.setStyleSheet("")
        self.close_btn.clicked.connect(self.close)
        for wb in (self.min_btn, self.max_btn, self.close_btn):
            wb.setIconSize(QSize(15, 15))
            wl.addWidget(wb)
        hl.addWidget(self.win_bar)
        self.win_bar.setVisible(bool(self.frameless and sys.platform == "win32"))
        header.installEventFilter(self)
        self._chat_header = header
        panel.header = header

        # 会话内搜索条(浮在顶栏下面)
        sbar = QFrame(panel)
        sbar.setObjectName("searchBar")
        sl = QHBoxLayout(sbar)
        sl.setContentsMargins(12, 4, 6, 4)
        sl.setSpacing(4)
        self.search_icon = QLabel()
        self.search_icon.setFixedSize(16, 16)
        sl.addWidget(self.search_icon)
        self.search_edit = SearchEdit()
        self.search_edit.setObjectName("searchEdit")
        self.search_edit.setPlaceholderText("搜索当前会话")
        self.search_edit.textChanged.connect(self._on_search_text)
        self.search_edit.prev_hit.connect(lambda: self.search_step(-1))
        self.search_edit.next_hit.connect(lambda: self.search_step(1))
        self.search_edit.closed.connect(self.close_search)
        sl.addWidget(self.search_edit, 1)
        self.search_count = label("", "searchCount")
        sl.addWidget(self.search_count)
        self.search_up = tool("chevron_up", 28, "round", "上一个(更早)  Enter")
        self.search_up.clicked.connect(lambda: self.search_step(-1))
        self.search_down = tool("chevron_down", 28, "round", "下一个(更新)  Shift+Enter")
        self.search_down.clicked.connect(lambda: self.search_step(1))
        self.search_close = tool("close", 28, "round", "关闭搜索  Esc")
        self.search_close.clicked.connect(self.close_search)
        for b in (self.search_up, self.search_down, self.search_close):
            sl.addWidget(b)
        sbar.setVisible(False)
        panel.search = sbar
        self.search_bar = sbar
        self.search_hits: list[str] = []
        self.search_idx = -1

        # 输入区
        comp = QFrame()
        comp.setObjectName("composer")
        outer = QVBoxLayout(comp)
        outer.setContentsMargins(16, 4, 16, 16)
        outer.setSpacing(6)
        self.reply_bar = QFrame()
        self.reply_bar.setObjectName("replyBar")
        rl = QHBoxLayout(self.reply_bar)
        rl.setContentsMargins(12, 6, 6, 6)
        rl.setSpacing(8)
        self.reply_icon = QLabel()
        self.reply_icon.setFixedSize(16, 16)
        rl.addWidget(self.reply_icon)
        self.reply_text = label("", "replyText")
        rl.addWidget(self.reply_text, 1)
        self.reply_close = tool("close", 26, "round", "取消引用")
        self.reply_close.clicked.connect(self.cancel_reply)
        rl.addWidget(self.reply_close)
        self.reply_bar.setVisible(False)
        outer.addWidget(self.reply_bar)

        cl = QHBoxLayout()
        cl.setSpacing(6)
        self.img_btn = tool("image", 36, "round", "发送图片\n也可以直接粘贴截图,或把图片拖进来")
        self.img_btn.clicked.connect(self.pick_images)
        cl.addWidget(self.img_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.file_btn = tool("paperclip", 36, "round", "发送文件\n也可以把文件拖进来")
        self.file_btn.clicked.connect(self.attach_menu)
        cl.addWidget(self.file_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.emoji_btn = tool("smile", 36, "round", "表情 / 表情包")
        self.emoji_btn.clicked.connect(self.show_emoji_panel)
        cl.addWidget(self.emoji_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.burn_btn = tool("flame", 36, "round", "阅后即焚")
        self.burn_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.burn_menu = make_menu(self)
        self.burn_btn.setMenu(self.burn_menu)
        self.burn_menu.aboutToShow.connect(self._fill_burn_menu)
        cl.addWidget(self.burn_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.tools_btn = tool("grid", 36, "round", "Bento 工具箱:投票、抽签、骰子、派对游戏、画板、匿名纸条、萌宠互动")
        self.tools_menu = make_menu(self)
        self.tools_menu.aboutToShow.connect(self.fill_tools_menu)
        self.tools_btn.clicked.connect(self.open_tools_drawer)
        cl.addWidget(self.tools_btn, 0, Qt.AlignmentFlag.AlignBottom)

        pill = QFrame()
        pill.setObjectName("composerPill")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(14, 3, 4, 3)
        pl.setSpacing(6)
        self.input = ChatInput()
        self.input.send.connect(self.send_current)
        self.input.images.connect(self.handle_images)
        self.input.files.connect(self.send_files)
        self.input.at_typed.connect(self.on_at_typed)
        self.input.textChanged.connect(self._on_input_changed)
        self.input.keystroke.connect(self.on_keystroke)
        pl.addWidget(self.input, 1)
        self.send_btn = tool("arrow_up", 30, "sendBtn", "发送(Enter)")
        self.send_btn.setIconSize(QSize(16, 16))
        self.send_btn.clicked.connect(self.send_current)
        pl.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignBottom)
        cl.addWidget(pill, 1)
        outer.addLayout(cl)
        lay.addWidget(comp)

        self.chat_panel = panel
        self.pet = TypingPet(panel)
        self.effects = EffectLayer(panel)
        panel.pet, panel.effects, panel.pill = self.pet, self.effects, pill
        self._pill, self._composer = pill, comp
        pill.installEventFilter(self)
        comp.installEventFilter(self)
        return panel

    def _build_members(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("members")
        panel.setFixedWidth(232)
        self.members_panel = panel
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 22, 12, 12)
        lay.setSpacing(8)
        self.member_title = label("", "section")
        self.member_title.setContentsMargins(8, 0, 0, 0)
        lay.addWidget(self.member_title)
        self.member_list = QListWidget()
        self.member_list.setItemDelegate(MemberDelegate(self))
        self.member_list.setMouseTracking(True)
        self.member_list.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.member_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.member_list.itemDoubleClicked.connect(self._member_double_clicked)
        self.member_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.member_list.customContextMenuRequested.connect(self._member_menu)
        lay.addWidget(self.member_list, 1)
        self.member_hint = label("双击成员发起私聊", "faint", wrap=True)
        self.member_hint.setContentsMargins(8, 0, 0, 0)
        lay.addWidget(self.member_hint)
        panel.installEventFilter(self)
        return panel

    # ------------------------------------------------------------ 主题
    def _refresh_icons(self) -> None:
        ic = T["icon"]
        for b in (self.rail_btn, self.add_btn, self.gomoku_btn, self.duck_btn, self.prank_btn, self.menu_btn,
                  self.img_btn, self.clear_btn, self.members_btn, self.file_btn, self.emoji_btn,
                  self.search_btn, self.tools_btn):
            b.setIcon(icon(b.property("iconName"), ic, 19))
        for b in (self.min_btn, self.max_btn, self.close_btn):
            b.setIcon(icon(b.property("iconName"), ic, 15))
        for b in (self.search_up, self.search_down, self.search_close):
            b.setIcon(icon(b.property("iconName"), ic, 15))
        self.search_icon.setPixmap(icon("search", T["sub"], 16).pixmap(16, 16))
        self.reply_close.setIcon(icon("close", ic, 14))
        self.reply_icon.setPixmap(icon("reply", T["accent"], 16).pixmap(16, 16))
        self.theme_btn.setIcon(icon(theme.THEME_SWATCH.get(T["name"], ("", "sun"))[1], ic, 19))
        self.theme_btn.setToolTip(f"外观:{T['label']}")
        self.send_btn.setIcon(icon("arrow_up", T["on_accent"], 16, 2.2))
        if getattr(self, "hover_bar", None) is not None:
            self.hover_bar.refresh_icons()
        for menu in (self.main_menu, self.add_menu):
            for act in menu.actions():
                name = act.property("iconName")
                if name:
                    act.setIcon(icon(name, ic, 16))
        self._refresh_burn_btn()
        self._refresh_bell()

    def _refresh_bell(self) -> None:
        conv = self.current
        muted = bool(conv and conv.muted) or not self.sound_enabled
        self.bell_btn.setIcon(icon("bell_off" if muted else "bell", T["icon"], 19))
        if not self.sound_enabled:
            self.bell_btn.setToolTip("提示音总开关已关闭(在设置里打开)")
        elif conv is not None:
            self.bell_btn.setToolTip("这个会话已静音,点击开启提示音" if conv.muted else "点击关闭这个会话的提示音")

    def _after_theme(self) -> None:
        theme.style_titlebar(self)
        self.centralWidget().update()
        self.pet.update()
        for eff, strength in self._shadows:
            r, g, b, a = T["shadow"]
            eff.setColor(QColor(r, g, b, int(a * strength)))
        self._refresh_icons()
        self._refresh_self()
        self._refresh_header()
        self._refresh_members()
        self._render_messages(keep_scroll=True)
        self.conv_list.viewport().update()

    def _fill_theme_menu(self) -> None:
        m = self.theme_menu
        m.clear()
        head = m.addAction("外观")
        head.setEnabled(False)
        for name in theme.THEMES:
            act = m.addAction(self.swatch_icon(theme.THEME_SWATCH[name][0]), theme.THEMES[name]["label"])
            act.setCheckable(True)
            act.setChecked(T["name"] == name and not self.follow_system and not self.follow_time)
            act.triggered.connect(lambda _=False, n=name: self.set_theme(n))
        m.addSeparator()
        act = m.addAction("跟随系统(浅色 / 深色)")
        act.setCheckable(True)
        act.setChecked(self.follow_system)
        act.triggered.connect(lambda: self.set_theme("system"))
        act = m.addAction("随时间变化(清晨 / 白天 / 黄昏 / 星空夜晚)")
        act.setCheckable(True)
        act.setChecked(self.follow_time)
        act.triggered.connect(lambda: self.set_theme("time"))
        act = m.addAction("深夜护眼(22 点到 6 点自动变暖变暗)")
        act.setCheckable(True)
        act.setChecked(self.eyecare)
        act.triggered.connect(lambda on: self.set_eyecare(on))
        m.addSeparator()
        self._menu_icon(m.addAction("个性化:主题色、气泡颜色、透明度、背景图…", self.show_personalize), "palette")

    def set_theme(self, name: str) -> None:
        if name == "time":
            self.set_follow_time(True)
            return
        self.follow_time = False
        self.follow_system = name == "system"
        if self.follow_system:
            name = "dark" if theme.system_prefers_dark() else "light"
        theme.apply(QApplication.instance(), name)
        self._after_theme()

    def toggle_theme(self) -> None:
        """依次切换所有主题:浅色 → 樱花 → 黄昏 → 紫夜 → 深海 → 深色 → 纯黑 → 浅色。"""
        order = list(theme.THEMES)
        self.set_theme(order[(order.index(T["name"]) + 1) % len(order)] if T["name"] in order else "light")

    def toggle_glass(self, on: bool) -> None:
        theme.apply(QApplication.instance(), T["name"], glass=on)
        if theme.GLASS_SUPPORTED:
            theme.set_backdrop(self, theme.GLASS)
        self._after_theme()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        theme.style_titlebar(self)
        theme.apply_frameless_dwm(self)

    # ------------------------------------------------------------ 无边框与面板收折
    def _apply_window_frame(self, initial: bool = False) -> None:
        was_vis = not initial and self.isVisible()
        geom = self.geometry() if was_vis else None
        if self.frameless and sys.platform == "win32":
            flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            for extra in ("WindowMinMaxButtonsHint", "WindowSystemMenuHint"):
                f = getattr(Qt.WindowType, extra, None)
                if f is not None:
                    flags = flags | f
            self.setWindowFlags(flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._glass_capable = True
        else:
            self.setWindowFlags(Qt.WindowType.Window)
            if theme.GLASS_SUPPORTED:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                self._glass_capable = True
        if getattr(self, "win_bar", None) is not None:
            self.win_bar.setVisible(bool(self.frameless and sys.platform == "win32"))
        if was_vis:
            if geom is not None:
                self.setGeometry(geom)
            self.show()
            theme.style_titlebar(self)
            theme.apply_frameless_dwm(self)

    def set_frameless(self, on: bool) -> None:
        on = bool(on) and sys.platform == "win32"
        if on == self.frameless:
            return
        self.frameless = on
        self._apply_window_frame(initial=False)

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_max_icon()

    def _sync_max_icon(self) -> None:
        if getattr(self, "max_btn", None) is not None:
            name = "restore" if bool(self.isMaximized()) else "maximize"
            self.max_btn.setProperty("iconName", name)
            self.max_btn.setIcon(icon(name, T["icon"], 15))

    def _update_min_width(self) -> None:
        sw = 76 if self.compact_side else 284
        mw = 232 if self.members_open else 0
        self.setMinimumSize(max(440, sw + mw + 344), 520)

    def set_compact_side(self, on: bool) -> None:
        self.compact_side = bool(on)
        self.sidebar_panel.setFixedWidth(76 if self.compact_side else 284)
        self._side_lay.setContentsMargins(6 if self.compact_side else 12, 16, 6 if self.compact_side else 12, 10)
        self._me_lay.setContentsMargins(10 if self.compact_side else 8, 8, 6 if self.compact_side else 4, 8)
        for w in (self.side_title, self.gomoku_btn, self.duck_btn, self.theme_btn, self.add_btn,
                  self.me_name, self.me_sub, self.menu_btn):
            w.setVisible(not self.compact_side)
        self._update_min_width()
        self.conv_list.doItemsLayout()
        self.conv_list.viewport().update()
        self._refit_bubbles()

    def set_members_open(self, on: bool) -> None:
        self.members_open = bool(on)
        self.members_panel.setVisible(self.members_open)
        self._update_min_width()
        self._refit_bubbles()

    def nativeEvent(self, eventType, message):
        if self.frameless and sys.platform == "win32" and not self.isMaximized():
            try:
                if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
                    import ctypes.wintypes
                    msg = ctypes.wintypes.MSG.from_address(int(message))
                    if msg.message == 0x0084:              # WM_NCHITTEST:边缘 6px 缩放窗口
                        pt = self.mapFromGlobal(QCursor.pos())
                        x, y, w, h = pt.x(), pt.y(), self.width(), self.height()
                        b = 6
                        left, right = 0 <= x < b, w - b <= x <= w
                        top, bottom = 0 <= y < b, h - b <= y <= h
                        if top and left:
                            return True, 13
                        if top and right:
                            return True, 14
                        if bottom and left:
                            return True, 16
                        if bottom and right:
                            return True, 17
                        if left:
                            return True, 10
                        if right:
                            return True, 11
                        if top:
                            return True, 12
                        if bottom:
                            return True, 15
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    # ------------------------------------------------------------ 查询
    def lobby_members(self) -> list[dict]:
        return [p for p in self.peers.values() if p.get("online") and p.get("lobby")]

    def room_members(self, tag: str | None) -> list[dict]:
        return [p for p in self.peers.values() if p.get("online") and tag in p.get("rooms", [])]

    def lobby_count(self) -> int:
        return len(self.lobby_members()) + 1

    def room_count(self, tag: str | None) -> int:
        return len(self.room_members(tag)) + 1

    def default_preview(self, conv: Conv) -> str:
        if conv.kind == "self":
            return "随手记 · 收藏的消息和文件"
        if conv.kind == "lobby":
            return f"{self.lobby_count()} 人在线" if self.me.get("lobby", True) else "隐身中"
        if conv.kind == "room":
            return f"{self.room_count(conv.target)} 人在线 · 暗号群"
        peer = self.peers.get(conv.target or "", {})
        return "在线" if peer.get("online") else "离线"

    def conv_avatar(self, conv: Conv, size: int) -> QPixmap:
        if conv.kind == "self":
            return avatar("", "#F2A93B", size, "star")
        if conv.kind == "lobby":
            return avatar("", LOBBY_COLOR if self.me.get("lobby", True) else "#A0A4AB", size, "hash")
        if conv.kind == "room":
            return avatar("", ROOM_COLOR, size, "lock")
        return peer_avatar(conv.target or "", conv.title, size)

    def conv_label(self, conv: Conv) -> str:
        return conv.title

    @property
    def current(self) -> Conv | None:
        return self.convs.get(self.current_key)

    def window_visible(self) -> bool:
        return self.isVisible() and not self.isMinimized()

    @staticmethod
    def scope_target(conv: Conv):
        if conv.kind == "lobby":
            return "lobby", None
        return ("room" if conv.kind == "room" else "dm"), conv.target

    # ------------------------------------------------------------ 会话列表
    def _refresh_conv_list(self) -> None:
        keys = [k for k in self.pinned_keys if k in self.convs]           # 置顶的排最前(按置顶的先后)
        keys += ["lobby"] if "lobby" in self.convs else []
        keys += ["self"] if "self" in self.convs else []
        keys += [k for k in self.convs if k.startswith("room:")]
        keys += sorted((k for k in self.convs if k.startswith("dm:")), key=lambda k: -self.convs[k].last_active)
        keys = list(dict.fromkeys(keys))
        self.conv_list.blockSignals(True)
        self.conv_list.clear()
        for k in keys:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, k)
            self.conv_list.addItem(item)
            if k == self.current_key:
                self.conv_list.setCurrentItem(item)
        self.conv_list.blockSignals(False)

    def _on_conv_changed(self, cur, _prev) -> None:
        if cur is not None:
            self.switch_to(cur.data(Qt.ItemDataRole.UserRole))

    def select_conv(self, key: str) -> None:
        if key not in self.convs:
            return
        if self.current_key != key:
            self._leave_conv()
        self.current_key = key
        self._refresh_conv_list()
        self.switch_to(key)

    def switch_to(self, key: str) -> None:
        conv = self.convs.get(key)
        if conv is None:
            return
        changed = self.current_key != key
        before = motion.snapshot(self.msg_area.viewport()) if changed and self.current_key else None
        if changed:
            self._leave_conv()
        self.current_key = key
        conv.unread = 0
        conv.at_me = False
        self._render_messages()
        if changed:
            motion.crossfade(self.msg_area.viewport(), before, 170)  # 切换会话:旧内容淡出(交叉淡化)
        self._refresh_header()
        self._refresh_members()
        self._refresh_input_state()
        self._start_visible_burns()
        self._mark_read(conv)
        self.conv_list.viewport().update()
        self._heat_step()
        self.refresh_notice_bar()
        self._hooks("switch", conv)
        if self.input.isEnabled():
            self.input.setFocus()

    def _leave_conv(self) -> None:
        """离开当前会话:取消引用 / 编辑、关闭搜索。"""
        self.exit_select()
        self.cancel_edit()
        self.cancel_reply()
        self.close_search()
        self.reset_window()

    def _conv_menu(self, pos) -> None:
        item = self.conv_list.itemAt(pos)
        if item is None:
            return
        conv = self.convs.get(item.data(Qt.ItemDataRole.UserRole))
        if conv is None:
            return
        m = make_menu(self)
        self._menu_icon(m.addAction("取消置顶" if conv.pinned else "置顶会话",
                                    lambda: self.set_pinned(conv, not conv.pinned)), "pin")
        if conv.kind == "self":
            self._menu_icon(m.addAction("清空收藏…", lambda: self.clear_conv(conv)), "trash")
            popup(m, self.conv_list.viewport().mapToGlobal(pos))
            return
        if conv.muted:
            self._menu_icon(m.addAction("关闭免打扰", lambda: self.set_muted(conv, False)), "bell")
        else:
            self._menu_icon(m.addAction("消息免打扰", lambda: self.set_muted(conv, True)), "bell_off")
        self._menu_icon(m.addAction("清空聊天记录", lambda: self.clear_conv(conv)), "trash")
        if conv.kind == "room":
            self._menu_icon(m.addAction("修改群名…", lambda: self.rename_room(conv)), "pencil")
            self._menu_icon(m.addAction("退出这个暗号群", lambda: self.leave_room(conv)), "power")
        elif conv.kind == "dm":
            self._menu_icon(m.addAction("验证安全码", lambda: self.verify_conv(conv)), "shield")
            self._menu_icon(m.addAction("关闭会话", lambda: self.close_dm(conv)), "close")
        popup(m, self.conv_list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ 消息渲染
    def _bubble_maxw(self) -> int:
        return int(max(240, min(self.msg_area.viewport().width() * 0.62, 600)))

    def _clear_bubbles(self) -> None:
        self.typing_bubble = None
        if getattr(self, "hover_bar", None) is not None:
            self.hide_hover_bar()
        while self.msg_layout.count() > 1:
            item = self.msg_layout.takeAt(1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.bubbles.clear()

    def _render_messages(self, keep_scroll: bool = False) -> None:
        sb = self.msg_area.verticalScrollBar()
        old_value, stick = sb.value(), self._stick
        self.msg_container.setUpdatesEnabled(False)
        self.bubble_fx.clear()
        self._clear_bubbles()
        self._view_last_time = None
        conv = self.current
        if conv is not None:
            maxw = self._bubble_maxw()
            msgs = self.render_window(conv)           # 只渲染屏幕附近的一段(往上 / 往下翻再接)
            grps = self.group_positions(msgs)
            prev = None
            for m, grp in zip(msgs, grps):
                self._append_msg(conv, m, prev, maxw, grp)
                prev = m
            if conv.kind == "dm":
                self.typing_bubble = TypingBubble()
                self.msg_layout.addWidget(self.typing_bubble)
                self.typing_bubble.setVisible(self.is_typing(conv.target))
        self.msg_container.setUpdatesEnabled(True)
        self.refresh_latest_btn()
        self.schedule_gif_sync()
        if self._anchor is not None:                    # 翻页:保持锚定的那条消息在原来的位置
            self._stick = False
            QTimer.singleShot(0, self.apply_anchor)
        elif keep_scroll and not stick:
            self._stick = False
            QTimer.singleShot(0, lambda: sb.setValue(min(old_value, sb.maximum())))
        else:
            self._stick = True
            QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))

    @staticmethod
    def _needs_head(conv: Conv, m: Msg, prev: Msg | None) -> bool:
        if m.system or m.mine or conv.kind == "dm":
            return False
        return prev is None or prev.system or prev.sender != m.sender or m.time - prev.time >= TIME_GAP

    @staticmethod
    def continues(prev: Msg | None, m: Msg) -> bool:
        """m 和上一条是不是同一个人连续发的(两分钟以内):是的话合成一组显示。"""
        if prev is None or prev.system or m.system or prev.anon or m.anon:
            return False
        if prev.mine != m.mine or (not m.mine and prev.sender != m.sender):
            return False
        return 0 <= m.time - prev.time < GROUP_GAP

    @classmethod
    def group_positions(cls, msgs: list) -> list[str]:
        """每条消息在组里的位置:single / first / mid / last。"""
        out = []
        n = len(msgs)
        for i, m in enumerate(msgs):
            before = i > 0 and cls.continues(msgs[i - 1], m)
            after = i + 1 < n and cls.continues(m, msgs[i + 1])
            out.append("mid" if before and after else "last" if before else "first" if after else "single")
        return out

    def _append_msg(self, conv: Conv, m: Msg, prev: Msg | None, maxw: int, grp: str | None = None) -> None:
        if not m.system:
            if self._view_last_time is None or m.time - self._view_last_time >= TIME_GAP:
                self._add_row(TimeSep(m.time))
            self._view_last_time = m.time
        if grp is None:                                # 新来的一条:接在上一条后面的话,上一条变成组的开头 / 中间
            grp = "single"
            if self.continues(prev, m):
                grp = "last"
                pb = self.bubbles.get(prev.mid)
                if pb is not None:
                    pb.set_group("mid" if pb.grp in ("mid", "last") else "first")
        b = Bubble(m, self._needs_head(conv, m, prev), conv.kind != "dm", maxw,
                   self.transfers.get(m.file["fid"]) if m.file else None,
                   self.card_state(m) if m.card else None, grp)
        b.card_action.connect(self.on_card_action)
        b.poke.connect(lambda msg, c=conv: self.poke(msg.sender, c))
        b.open_image.connect(self.open_image)
        b.menu_requested.connect(self.bubble_menu)
        b.jump.connect(self.jump_to)
        b.file_action.connect(self.on_file_action)
        b.hovered.connect(self.hover_bubble)
        b.unhovered.connect(self.unhover_bubble)
        if self.search_hits and m.mid in self.search_hits:
            cur = self.search_hits[self.search_idx] if 0 <= self.search_idx < len(self.search_hits) else None
            b.set_search(self.search_edit.text().strip(), m.mid == cur)
        self._add_row(b)
        self.bubbles[m.mid] = b
        self._decorate_bubble(b, m)
        if m.file and not m.vid:
            self.maybe_probe(conv, m)                      # 没有封面的视频:本机有文件就自己取一张

    def _add_row(self, w) -> None:
        """加一行消息;如果有"正在输入"小气泡,插在它前面。"""
        if self.typing_bubble is not None:
            idx = self.msg_layout.indexOf(self.typing_bubble)
            if idx >= 0:
                self.msg_layout.insertWidget(idx, w)
                return
        self.msg_layout.addWidget(w)

    def _refit_bubbles(self) -> None:
        maxw = self._bubble_maxw()
        for b in self.bubbles.values():
            b.fit(maxw)

    def _on_range_changed(self, _lo: int, hi: int) -> None:
        if self.apply_anchor():
            return
        if self._stick:
            self.msg_area.verticalScrollBar().setValue(hi)

    def _on_scroll(self, value: int) -> None:
        self._stick = value >= self.msg_area.verticalScrollBar().maximum() - 40 and self._win_bottom
        self.maybe_page(value)

    # ------------------------------------------------------------ 添加消息
    def _system(self, conv: Conv, text: str) -> None:
        self._add_message(conv, Msg(text, system=True), count_unread=False)

    @staticmethod
    def _body_of(m: Msg) -> str:
        if m.burn:
            return "🔥 阅后即焚消息"
        if m.vid is not None:
            return "[视频]"
        if m.file:
            return f"[文件] {m.file.get('name', '')}"
        if m.img is not None:
            if m.sticker:
                return "[表情]"
            return "[动图]" if m.mime == "image/gif" and imaging.is_animated_gif(m.img) else "[图片]"
        return m.text.strip().split("\n", 1)[0][:60]

    @classmethod
    def _preview_of(cls, m: Msg, conv: Conv) -> str:
        who = "我: " if m.mine else (f"{m.nick}: " if conv.kind != "dm" else "")
        return who + cls._body_of(m)

    def _add_message(self, conv: Conv, m: Msg, count_unread: bool = True) -> None:
        conv.messages.append(m)
        if not m.system and not m.burn:
            self._hist_dirty = True
        if not m.system and count_unread and conv.kind != "self":
            self.bump_heat(conv, HEAT_OUT if m.mine else HEAT_IN)
            self.record_message(conv, m)
            self.rank_count(conv, m)
            if m.mine:
                self.pet.touch()
                if self.visit is not None:
                    self.visit["msgs"] += 1
            self._hooks("message", conv, m)
        self.trim_memory(conv)                     # 内存里太多了:最早的放掉(存过的翻到再从数据库读)
        if not m.system:
            conv.last_active = conv.last_time = m.time
            conv.preview = self._preview_of(m, conv)
        is_current = conv.key == self.current_key
        visible = is_current and self.window_visible()
        if m.burn and (m.mine or (visible and m.img is None)):
            m.deadline = time.monotonic() + m.burn
        if is_current and m.mine and not self._win_bottom:
            self.back_to_latest()                  # 正在看很早的记录时自己发了消息:回到最新
        elif is_current and not self._win_bottom:
            self.refresh_latest_btn(new=True)      # 正在看很早的记录:不打断,只提示有新消息
        elif is_current:
            prev = conv.messages[-2] if len(conv.messages) >= 2 else None
            if m.mine:
                self._stick = True
            self._win_hi = len(conv.messages)
            self._append_msg(conv, m, prev, self._bubble_maxw())
            self.after_live_append()
            if m.mime == "image/gif":
                self.schedule_gif_sync()
            if visible and not m.system:
                self._message_fx(m)
        elif count_unread and not m.system:
            conv.unread += 1
            if m.mention:
                conv.at_me = True
        if not m.mine and not m.system and count_unread:
            self.typing_until.pop(m.sender, None)
            self._refresh_typing_bubble()
            if self.flash_enabled and self.isVisible() and (not self.isActiveWindow() or not is_current):
                QApplication.alert(self, 0)
            self._maybe_notify(conv, is_current, force=m.mention)
            if is_current:
                self._mark_read(conv)
        if conv.kind == "self" and conv.key == self.current_key:
            self._refresh_header()
        if is_current and self.search_bar.isVisible() and not m.system:
            self.search_refresh()
        if conv.kind == "dm" and not m.system:
            self._refresh_conv_list()
        else:
            self.conv_list.viewport().update()

    # ------------------------------------------------------------ 提示音
    def _maybe_notify(self, conv: Conv, is_current: bool, force: bool = False) -> bool:
        if not self.sound_enabled or (conv.muted and not force):      # 被 @ 时,静音的会话也会响
            return False
        if not self.isVisible() and not self.sound_when_hidden:
            return False
        if is_current and self.window_visible() and self.isActiveWindow():
            return False                         # 正在看这个会话,不打扰
        return self.notifier.play()

    def _apply_conv_prefs(self, conv: Conv) -> None:
        conv.muted = conv.key in self.muted_keys
        conv.pinned = conv.key in self.pinned_keys
        self._apply_group_state(conv)
        if conv.kind == "dm":
            conv.verified = conv.target in self.verified_ids

    def set_muted(self, conv: Conv, muted: bool) -> None:
        conv.muted = muted
        (self.muted_keys.add if muted else self.muted_keys.discard)(conv.key)
        if conv.key == self.current_key:
            self._refresh_bell()
        self.conv_list.viewport().update()

    def toggle_mute_current(self) -> None:
        if not self.sound_enabled:
            self.set_sound_enabled(True)
            if self.current is not None and self.current.muted:
                self.set_muted(self.current, False)
            return
        if self.current is not None:
            self.set_muted(self.current, not self.current.muted)

    def set_sound_enabled(self, on: bool) -> None:
        self.sound_enabled = bool(on)
        self.act_sound.setChecked(self.sound_enabled)
        self._refresh_bell()

    # ------------------------------------------------------------ 阅后即焚 / 定时刷新
    def _start_visible_burns(self) -> None:
        conv = self.current
        if conv is None or not self.window_visible():
            return
        now = time.monotonic()
        for m in conv.messages:
            if m.burn and m.deadline is None and m.img is None:     # 图片要点开才开始计时
                m.deadline = now + m.burn
                b = self.bubbles.get(m.mid)
                if b:
                    b.update_meta(now)

    def _on_tick(self) -> None:
        now = time.monotonic()
        self._save_tick += 1
        if self._save_tick % 5 == 0:
            self.save_account()
            self.save_favs()
        if self._save_tick % 15 == 0:
            self.save_history_now()
        self._auto_resume(now)
        self._hooks("tick", now)
        self._start_visible_burns()
        expired = [pid for pid, t in self.typing_until.items() if t <= now]
        for pid in expired:
            self.typing_until.pop(pid, None)
        if expired:
            self._refresh_header()
            self._refresh_typing_bubble()
            self.conv_list.viewport().update()
        burned_current = False
        for conv in self.convs.values():
            expired = [m for m in conv.messages if m.deadline is not None and m.deadline <= now]
            if not expired:
                continue
            for m in expired:
                m.gone = True
                m.img = None
                m.thumb = None
            dead = {m.mid for m in expired}
            conv.messages = [m for m in conv.messages if m.mid not in dead]
            last = next((m for m in reversed(conv.messages) if not m.system), None)
            conv.preview = self._preview_of(last, conv) if last else "🔥 消息已焚毁"
            if conv.key == self.current_key:
                burned_current = True
        if burned_current:
            self._render_messages(keep_scroll=True)
            self.conv_list.viewport().update()
        else:
            for b in self.bubbles.values():
                if b.msg.burn:
                    b.update_meta(now)

    # ------------------------------------------------------------ 顶栏 / 成员 / 输入状态
    def _refresh_self(self) -> None:
        nick = self.me.get("nick", "")
        self._sync_my_avatar()
        self.me_avatar.setPixmap(peer_avatar(self.me.get("id", ""), nick, 36))
        self.me_name.setText(nick)
        mode = "大厅可见" if self.me.get("lobby", True) else "隐身中"
        lan = "" if self.me.get("ips") else "  ·  未检测到局域网"
        lv = f"Lv.{self.pet_growth.level}  ·  " if getattr(self, "pet_growth", None) is not None else ""
        self.me_sub.setText(f"#{self.me.get('tag', '')}  ·  {lv}{mode}{lan}")
        self.act_lobby.setChecked(self.me.get("lobby", True))
        self.act_glass.setChecked(theme.GLASS)

    def _refresh_header(self) -> None:
        conv = self.current
        if conv is None:
            return
        self._refresh_bell()
        self.chat_avatar.setPixmap(self.conv_avatar(conv, 36))
        self.verify_btn.setVisible(conv.kind == "dm")
        self.prank_btn.setVisible(conv.kind in ("lobby", "room"))
        self.bell_btn.setVisible(conv.kind != "self")
        self.clear_btn.setToolTip("清空收藏" if conv.kind == "self" else "清空本机上的这段记录")
        if conv.kind != "dm" and self.chat_sub.objectName() != "subtitle":
            self.chat_sub.setObjectName("subtitle")
            repolish(self.chat_sub)
        if conv.kind == "self":
            self.chat_title.setText("我的收藏")
            n = sum(1 for m in conv.messages if not m.system)
            self.chat_sub.setText(f"{n} 条  ·  只在这台电脑上,不会发给任何人")
        elif conv.kind == "lobby":
            self.chat_title.setText("公开大厅")
            if self.me.get("lobby", True):
                self.chat_sub.setText(f"{self.lobby_count()} 人在线  ·  大厅里的人都能看到")
            else:
                self.chat_sub.setText("你已退出大厅,大厅里的人看不到你")
        elif conv.kind == "room":
            self.chat_title.setText(conv.title)
            self.chat_sub.setText(f"{self.room_count(conv.target)} 人在线  ·  只有知道暗号的人能看到")
        else:
            peer = self.peers.get(conv.target or "", {})
            self.chat_title.setText(conv.title)
            state = "在线" if peer.get("online") else "离线"
            if self.is_typing(conv.target):
                self.chat_sub.setText("正在输入…")
                self.chat_sub.setObjectName("subtitleAccent")
            else:
                self.chat_sub.setText(f"#{peer.get('tag', '')}  ·  {state}  ·  端到端加密")
                self.chat_sub.setObjectName("subtitle")
            repolish(self.chat_sub)
            self.verify_btn.setText("已验证" if conv.verified else "验证")
            self.verify_btn.setToolTip("已当面核对过安全码" if conv.verified else "核对安全码,确认对方没被冒充")
            self.verify_btn.setIcon(icon("shield_check" if conv.verified else "shield",
                                         T["good"] if conv.verified else T["icon"], 17))
            self.verify_btn.setObjectName("verified" if conv.verified else "textBtn")
            repolish(self.verify_btn)

    def _refresh_members(self) -> None:
        conv = self.current
        self.member_list.clear()
        if conv is None:
            return
        if conv.kind == "self":
            self.member_title.setText("我的收藏")
            self.member_hint.setText("在别的会话里右键消息 →「收藏」\n就会存到这里。\n也可以直接把文件拖进来。")
            me = QListWidgetItem()
            me.setData(Qt.ItemDataRole.UserRole, {"id": self.me.get("id", ""), "nick": self.me.get("nick", ""),
                                                  "tag": self.me.get("tag", ""), "online": True, "me": True})
            self.member_list.addItem(me)
            return
        if conv.kind == "dm":
            peer = self.peers.get(conv.target or "", {})
            people = [peer] if peer else []
            self.member_title.setText("私聊对象")
            self.member_hint.setText("右键可以验证安全码。\n对方重启软件后会变成新身份。")
        else:
            people = self.lobby_members() if conv.kind == "lobby" else self.room_members(conv.target)
            if conv.kind == "lobby" and not self.me.get("lobby", True):
                people = []
            self.member_title.setText(f"成员  ·  {len(people) + 1}")
            self.member_hint.setText("双击成员发起私聊")
            me = QListWidgetItem()
            me.setData(Qt.ItemDataRole.UserRole, {"id": self.me.get("id", ""), "nick": self.me.get("nick", ""),
                                                  "tag": self.me.get("tag", ""), "online": True, "me": True})
            self.member_list.addItem(me)
        for p in sorted(people, key=lambda x: x.get("nick", "").lower()):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, dict(p))
            item.setToolTip("双击私聊 · 右键更多")
            self.member_list.addItem(item)

    def _refresh_input_state(self) -> None:
        conv = self.current
        enabled, ph = True, "发消息"
        if conv is None:
            enabled = False
        elif conv.kind == "lobby" and not self.me.get("lobby", True):
            enabled, ph = False, "你已退出大厅,可在设置里重新进入"
        elif conv.kind == "dm" and not self.peers.get(conv.target or "", {}).get("online"):
            enabled, ph = False, "对方已离线"
        elif conv.kind == "self":
            ph = "随手记点什么,或者把文件、图片拖进来"
        for w in (self.input, self.send_btn, self.img_btn, self.burn_btn, self.file_btn, self.emoji_btn):
            w.setEnabled(enabled)
        is_self = conv is not None and conv.kind == "self"
        self.burn_btn.setVisible(not is_self)
        self.tools_btn.setVisible(not is_self)
        self.input.set_hint(ph)

    def _member_double_clicked(self, item) -> None:
        d = item.data(Qt.ItemDataRole.UserRole) or {}
        if d.get("id") and not d.get("me"):
            self.open_dm(d["id"])

    def _member_menu(self, pos) -> None:
        item = self.member_list.itemAt(pos)
        d = (item.data(Qt.ItemDataRole.UserRole) or {}) if item else {}
        pid = d.get("id")
        if not pid or d.get("me"):
            return
        m = make_menu(self)
        self._menu_icon(m.addAction("私聊", lambda: self.open_dm(pid)), "user")
        self._menu_icon(m.addAction("验证安全码", lambda: self.verify_conv(self.open_dm(pid, select=False))), "shield")
        m.addSeparator()
        conv = self.current
        m.addAction("👉  戳一戳", lambda: self.poke(pid, conv if conv is not None and conv.kind != "dm" else None))
        m.addAction(f"🐾  让{self.pet_growth.name}去 TA 家串门", lambda: self.send_pet_visit(pid))
        self.add_fun_menus(m, pid, conv)
        m.addAction("⚫  邀请下五子棋…", lambda: self.gm_invite_dialog(pid))
        if self.dk_room is not None:
            m.addAction("🦆  邀请来玩谁是坏鸭", lambda: self.dk_invite(pid))
        if self.sp_room is not None:
            m.addAction("🕵  邀请来玩谁是卧底", lambda: self.sp_invite(pid))
        popup(m, self.member_list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ 阅后即焚按钮
    def _fill_burn_menu(self) -> None:
        self.burn_menu.clear()
        head = self.burn_menu.addAction("阅后即焚")
        head.setEnabled(False)
        for text, secs in BURN_CHOICES:
            act = self.burn_menu.addAction(text if secs else "不焚毁")
            act.setCheckable(True)
            act.setChecked(secs == self.burn_secs)
            act.triggered.connect(lambda _=False, s=secs: self.set_burn(s))

    def set_burn(self, secs: int) -> None:
        self.burn_secs = int(secs)
        self._refresh_burn_btn()

    def _refresh_burn_btn(self) -> None:
        b = self.burn_btn
        if self.burn_secs:
            b.setObjectName("burnOn")
            b.setIcon(icon("flame", T["burn"], 18))
            b.setText(fmt_secs(self.burn_secs))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setMinimumWidth(36)
            b.setMaximumWidth(120)
            b.setToolTip(f"阅后即焚已开启:{fmt_secs(self.burn_secs)}")
        else:
            b.setObjectName("round")
            b.setIcon(icon("flame", T["icon"], 19))
            b.setText("")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            b.setFixedSize(36, 36)
            b.setToolTip("阅后即焚")
        b.setFixedHeight(36)
        repolish(b)

    # ------------------------------------------------------------ 操作
    def open_dm(self, pid: str, select: bool = True) -> Conv:
        key = "dm:" + pid
        conv = self.convs.get(key)
        if conv is None:
            peer = self.peers.get(pid, {})
            conv = Conv(key, "dm", peer.get("nick", "未知"), pid)
            self.convs[key] = conv
            self._apply_conv_prefs(conv)
            self._system(conv, "私聊消息端到端加密,只有你们两个人能看到。\n想确认对方没被冒充,可以点右上角「验证」。")
            self._refresh_conv_list()
        if select:
            self.select_conv(key)
        return conv

    def send_current(self) -> None:
        conv = self.current
        text = self.input.toPlainText().strip("\n ").rstrip()
        if self.editing is not None:
            if text:
                self.finish_edit(text)
            return
        if conv is None or not text or not self.input.isEnabled():
            return
        if conv.kind == "self":
            self.self_note(text)
            return
        if len(text) > MAX_TEXT:
            info(self, "消息太长", f"一条消息最多 {MAX_TEXT} 个字,当前 {len(text)} 个。")
            return
        scope, target = self.scope_target(conv)
        burn = self.burn_secs
        reply = self._reply_payload()
        at = self._collect_at(text) if conv.kind != "dm" else []
        skin = self.current_skin() if not burn else None
        mid = self.core.send_text(scope, target, text, burn, reply=reply, at=at, skin=skin)
        if mid is None:
            self._system(conv, "发送失败:网络模块未运行")
            return
        m = Msg(text, mid=mid, sender=self.me["id"], nick=self.me.get("nick", ""), tag=self.me.get("tag", ""),
                mine=True, burn=burn, reply=reply, at=at, skin=skin)
        self._add_message(conv, m)
        self.input.clear()
        self.pending_at.clear()
        self.cancel_reply()
        self._sent_fx()
        if conv.kind == "dm":
            self._typing_sent.pop(conv.target, None)     # 对方收到消息会清掉"正在输入",接着打字要能马上再显示

    # ---- 图片
    def pick_images(self) -> None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        paths, _ = QFileDialog.getOpenFileNames(self, "选择图片", folder, imaging.IMAGE_FILTER)
        if not paths:
            return
        items, too_big = [], []
        for p in paths[:9]:
            it = imaging.load_image_path(p)
            if it is None and imaging.is_image_path(p) and os.path.getsize(p) > imaging.GIF_MAX:
                too_big.append(p)                          # 超过 8MB 的动图:当文件发,对方下载后照样会动
            else:
                items.append(it)
        if too_big:
            self.send_files(too_big)
        if items:
            self.handle_images(items)

    def handle_images(self, images) -> None:
        conv = self.current
        if conv is None or not self.input.isEnabled():
            info(self, "现在不能发送", "当前会话无法发送消息(对方离线,或你已退出大厅)。")
            return
        imgs = [i for i in (images or []) if i is not None and not i.isNull()][:9]      # QImage 或动图 Gif
        bad = len(images or []) - len(imgs)
        if not imgs:
            info(self, "无法读取图片", "图片格式不支持,或者图片太大。")
            return
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            encoded = [e for e in (imaging.encode_any(i) for i in imgs) if e]
        finally:
            QApplication.restoreOverrideCursor()
        if not encoded:
            info(self, "图片处理失败", "这张图片无法压缩到可以发送的大小。")
            return
        first = imaging.preview_image(imgs[0])
        if first is None:
            info(self, "无法读取图片", "图片格式不支持,或者图片太大。")
            return
        preview = imaging.thumbnail(first, 320, 14)
        previews = [imaging.preview_image(im) for im in imgs]
        thumbs = [imaging.thumbnail(im, 108, 10, shadow=False) for im in previews if im is not None]
        can_collage = (len(encoded) >= 2 and not self.burn_secs
                       and not any(isinstance(im, imaging.Gif) for im in imgs))
        dlg = SendImageDialog(self, preview, len(encoded), sum(len(e[0]) for e in encoded), self.burn_secs,
                              self.conv_label(conv), bad + len(imgs) - len(encoded),
                              thumbs=thumbs, can_collage=can_collage)
        if not dlg.exec():
            return
        if getattr(dlg, "merge_collage", False):
            merged = compose_collage([im for im in previews if im is not None])
            enc_one = imaging.encode_any(merged) if merged is not None else None
            if enc_one:
                self.send_image_data(conv, *enc_one)
                return
        for data, mime, w, h in encoded:
            self.send_image_data(conv, data, mime, w, h)

    def send_image_data(self, conv: Conv, data: bytes, mime: str, w: int, h: int, sticker: bool = False) -> str | None:
        if conv.kind == "self":
            self.self_image(data, mime, w, h, sticker)
            return None
        scope, target = self.scope_target(conv)
        burn = self.burn_secs
        reply = self._reply_payload()
        mid = self.core.send_image(scope, target, data, mime, burn, w, h, reply=reply, sticker=sticker)
        if mid is None:
            self._system(conv, "图片发送失败")
            return None
        m = Msg("", mid=mid, sender=self.me["id"], nick=self.me.get("nick", ""), tag=self.me.get("tag", ""),
                mine=True, burn=burn, img=data, mime=mime, w=w, h=h, reply=reply, sticker=sticker)
        m.status = "发送中…"
        self._add_message(conv, m)
        self.cancel_reply()
        self._sent_fx()
        return mid

    def open_image(self, m: Msg) -> None:
        if m.gone or m.img is None:
            return
        if m.burn and m.deadline is None:            # 阅后即焚图片:打开才开始倒计时
            m.deadline = time.monotonic() + m.burn
            b = self.bubbles.get(m.mid)
            if b:
                b.update_meta(time.monotonic())
        conv = self._conv_of(m)
        gallery = ([x for x in conv.messages if x.img is not None and not x.burn and not x.gone]
                   if conv is not None and not m.burn else [m])
        v = ImageViewer(self, m, gallery=gallery)
        self._viewers.append(v)
        v.finished.connect(lambda _=0, v=v: self._viewers.remove(v) if v in self._viewers else None)
        v.show()

    # ---- 引用回复
    def _conv_of(self, m: Msg) -> Conv | None:
        for conv in self.convs.values():
            if any(x is m for x in conv.messages):
                return conv
        return None

    def start_reply(self, m: Msg) -> None:
        self.reply_to = m
        who = "我" if m.mine else m.nick
        text = f"回复 {who}:{self._body_of(m)}"
        self.reply_text.setText(self.reply_text.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 520))
        self.reply_bar.setVisible(True)
        self.input.setFocus()

    def cancel_reply(self) -> None:
        self.reply_to = None
        if hasattr(self, "reply_bar"):
            self.reply_bar.setVisible(False)

    def _reply_payload(self) -> dict | None:
        m = self.reply_to
        if m is None or m.gone:
            return None
        return {"mid": m.mid, "nick": self.me.get("nick", "") if m.mine else m.nick, "preview": self._body_of(m)[:80]}

    def jump_to(self, mid: str) -> None:
        b = self.bubbles.get(mid)
        if b is None and self.show_window_at(mid):         # 很早的消息:从数据库读出来,只渲染那一段
            b = self.bubbles.get(mid)
        if b is None:
            self.statusTip_flash("原消息已不在(可能被撤回、焚毁或清空)")
            return
        self._stick = False
        QTimer.singleShot(0, lambda b=b: self.msg_area.ensureWidgetVisible(b, 0, HEADER_H + 20))
        b.flash()

    def statusTip_flash(self, text: str) -> None:
        conv = self.current
        if conv is not None:
            self._system(conv, text)

    # ---- 消息右键菜单 / 撤回
    def bubble_menu(self, m: Msg, pos) -> None:
        conv = self._conv_of(m)
        if conv is None or m.gone:
            return
        menu = make_menu(self)
        self._menu_icon(menu.addAction("回复", lambda: self.start_reply(m)), "reply")
        if m.img is None and not m.file and m.text:
            self._menu_icon(menu.addAction("复制", lambda: QApplication.clipboard().setText(m.text)), "copy")
        if m.img is not None and not m.burn:
            self._menu_icon(menu.addAction("添加到表情", lambda: self.add_sticker_from_msg(m)), "smile")
        self._fill_react_menu(menu, m)
        if not m.burn and not m.card:
            menu.addAction("转发…", lambda: self.forward([m]))
        menu.addAction("多选", lambda: self.enter_select(m))
        if conv.kind != "self" and not m.burn:
            self._menu_icon(menu.addAction("收藏", lambda: self.favorite(m)), "star")
        if conv.kind == "self" and m.fav:
            menu.addAction("查看原消息", lambda: self.goto_original(m))
        if conv.kind != "dm" and not m.mine and not m.anon:
            self._menu_icon(menu.addAction(f"@{m.nick}", lambda: self.insert_mention(m.nick, m.sender, True)), "at")
            menu.addAction(f"👉  戳一戳 {m.nick}", lambda: self.poke(m.sender, conv))
            self.add_fun_menus(menu, m.sender, conv)
        if conv.kind in ("lobby", "room"):
            pinned = any(p.get("mid") == m.mid for p in conv.pins)
            menu.addAction("📌  取消置顶" if pinned else "📌  置顶", lambda: self.toggle_pin(m))
        menu.addSeparator()
        if (m.mine and not m.anon and not m.burn and m.img is None and not m.file and not m.card and m.text
                and not m.fav):
            self._menu_icon(menu.addAction("编辑", lambda: self.start_edit(m)), "pencil")
        if m.mine and not m.anon and conv.kind != "self":
            self._menu_icon(menu.addAction("撤回", lambda: self.recall_msg(m)), "undo")
        if conv.kind == "self":
            self._menu_icon(menu.addAction("从收藏中删除", lambda: self.delete_local(m)), "trash")
            popup(menu, pos)
            return
        self._menu_icon(menu.addAction("从本机删除", lambda: self.delete_local(m)), "trash")
        popup(menu, pos)

    def _replace_with_notice(self, conv: Conv, m: Msg, text: str) -> None:
        self._hist_dirty = True
        notice = Msg(text, system=True)
        notice.time = m.time
        for i, x in enumerate(conv.messages):
            if x is m:
                conv.messages[i] = notice
                break
        m.gone = True
        m.img = None
        m.thumb = None
        if self.reply_to is m:
            self.cancel_reply()
        if m.file and not m.mine:
            tr = self.transfers.get(m.file["fid"], {})
            if tr.get("state") == "downloading":
                self.core.cancel_file(m.file["fid"])
        last = next((x for x in reversed(conv.messages) if not x.system), None)
        conv.preview = self._preview_of(last, conv) if last else text
        if conv.key == self.current_key:
            if self.window_visible():
                self.bubble_fx.mode = self.fun.get("bubble", "soft")
                self.bubble_fx.shatter(self.bubbles.get(m.mid), self.msg_area.viewport())   # 撤回:碎成小块掉下去
            self._render_messages(keep_scroll=True)
        self.conv_list.viewport().update()

    def recall_msg(self, m: Msg) -> None:
        conv = self._conv_of(m)
        if conv is None or not m.mine:
            return
        scope, target = self.scope_target(conv)
        self.core.recall(scope, target, m.mid)
        if m.file:
            self.transfers.pop(m.file["fid"], None)
        self._replace_with_notice(conv, m, "你撤回了一条消息")
        self._update_receipts(conv)

    def delete_local(self, m: Msg) -> None:
        conv = self._conv_of(m)
        if conv is None:
            return
        conv.messages = [x for x in conv.messages if x is not m]
        m.gone = True
        m.img = None
        self._hist_dirty = True
        if conv.kind == "self":
            self._favs_dirty = True
        if conv.key == self.current_key:
            self._render_messages(keep_scroll=True)
        self.conv_list.viewport().update()

    def _ev_recall(self, d: dict) -> None:
        scope = d.get("scope")
        key = "lobby" if scope == "lobby" else ("room:" + (d.get("room") or "") if scope == "room" else "dm:" + d["peer"])
        conv = self.convs.get(key)
        if conv is None:
            return
        m = next((x for x in conv.messages if x.mid == d["target"] and x.sender == d["peer"] and not x.system), None)
        if m is not None:
            self._replace_with_notice(conv, m, f"{d['nick']} 撤回了一条消息")

    # ---- @某人
    def _collect_at(self, text: str) -> list[str]:
        return [pid for nick, pid in self.pending_at.items() if f"@{nick}" in text]

    def _mention_candidates(self, conv: Conv) -> list[dict]:
        people = self.lobby_members() if conv.kind == "lobby" else self.room_members(conv.target)
        return sorted(people, key=lambda x: x.get("nick", "").lower())

    def on_at_typed(self) -> None:
        conv = self.current
        if conv is None or conv.kind == "dm":
            return
        menu = make_menu(self)
        self._menu_icon(menu.addAction("所有人", lambda: self.insert_mention("所有人", "all")), "at")
        people = self._mention_candidates(conv)
        if people:
            menu.addSeparator()
        for p in people:
            menu.addAction(QIcon(avatar(p.get("nick", ""), color_for(p["id"]), 20)), f"{p.get('nick', '')}  #{p.get('tag', '')}",
                           lambda p=p: self.insert_mention(p.get("nick", ""), p["id"]))
        rect = self.input.cursorRect()
        popup(menu, self.input.viewport().mapToGlobal(QPoint(rect.left(), rect.bottom() + 6)))

    def insert_mention(self, nick: str, pid: str, with_at: bool = False) -> None:
        self.input.insertPlainText(("@" if with_at else "") + nick + " ")
        self.pending_at[nick] = pid
        self.input.setFocus()

    # ---- 表情 / 表情包
    def show_emoji_panel(self, tab: int = 0) -> None:
        self.stickers.ensure()
        panel = EmojiPanel(self, self.recent_emojis, self.stickers.items, tab if isinstance(tab, int) else 0)
        panel.picked.connect(self.insert_emoji)
        panel.sticker_picked.connect(self.send_sticker)
        panel.add_sticker.connect(self.import_stickers)
        panel.remove_sticker.connect(self.stickers.remove)
        pos = self.emoji_btn.mapToGlobal(QPoint(0, 0))
        panel.move(pos.x() - 8, pos.y() - panel.height() - 8)
        panel.show()

    def insert_emoji(self, e: str) -> None:
        self.input.insertPlainText(e)
        if e in self.recent_emojis:
            self.recent_emojis.remove(e)
        self.recent_emojis.insert(0, e)
        del self.recent_emojis[16:]

    def send_sticker(self, st: dict) -> None:
        conv = self.current
        if conv is None or not self.input.isEnabled():
            return
        self.send_image_data(conv, st["data"], st["mime"], 0, 0, sticker=True)
        self.stickers.add(st["data"], st["mime"])          # 挪到最前面

    def add_sticker_from_msg(self, m: Msg) -> None:
        if m.img is None:
            return
        if m.mime == "image/gif" and imaging.is_animated_gif(m.img) and len(m.img) <= STICKER_GIF_MAX:
            data, mime = m.img, m.mime                     # 动图表情:原样收藏,发出去照样会动
        else:
            img = imaging.decode(m.img)
            enc = imaging.encode_sticker(img) if img is not None else None
            data, mime = (enc[0], enc[1]) if enc else (m.img, m.mime)
        try:
            ok = self.stickers.add(data, mime) is not None
        except OSError as e:
            ok = False
            info(self, "添加失败", str(e))
            return
        conv = self._conv_of(m)
        if conv is not None:
            self._system(conv, "已添加到表情包" if ok else "这张图片无法添加为表情包")

    def import_stickers(self) -> None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        paths, _ = QFileDialog.getOpenFileNames(self, "导入表情包", folder, imaging.IMAGE_FILTER)
        added = 0
        for p in paths[:50]:
            it = imaging.load_image_path(p)
            if isinstance(it, imaging.Gif) and len(it.data) <= STICKER_GIF_MAX:
                if self.stickers.add(it.data, "image/gif"):
                    added += 1
                continue
            img = imaging.preview_image(it)
            enc = imaging.encode_sticker(img) if img is not None else None
            if enc and self.stickers.add(enc[0], enc[1]):
                added += 1
        if paths:
            self.show_emoji_panel(1)

    def clear_stickers(self) -> None:
        if ask(self, "清空表情包?", "所有收藏的表情包会从这台电脑上删除。", "清空", danger=True):
            self.stickers.clear()

    # ---- 文件
    def pick_files(self) -> None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要发送的文件", folder, "所有文件 (*)")
        if paths:
            self.send_files(paths)

    def send_files(self, paths) -> None:
        conv = self.current
        if conv is None or not self.input.isEnabled():
            info(self, "现在不能发送", "当前会话无法发送消息(对方离线,或你已退出大厅)。")
            return
        paths = [p for p in (paths or []) if os.path.isfile(p)][:20]
        if not paths:
            return
        if conv.kind == "self":
            self.self_files(paths)
            return
        if len(paths) > 1 and not ask(self, f"发送 {len(paths)} 个文件?", f"到「{conv.title}」", "发送"):
            return
        self._send_paths(conv, paths)                      # 视频会自动取封面(window/files.py)

    def on_file_action(self, m: Msg, action: str) -> None:
        if m.vid is not None:                              # 匿名纸条里的视频
            self.anon_video_action(m, action)
            return
        fid = m.file["fid"]
        tr = self.transfers.setdefault(fid, {"state": "offer", "peer": m.sender})
        if action in ("download", "dlplay"):               # dlplay:点了视频封面,下载完自动播放
            if not self.peers.get(m.sender, {}).get("online"):
                info(self, "无法下载", "对方已离线。文件只在发送方在线时才能下载。")
                return
            folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            if m.file.get("dir"):                  # 文件夹:选一个放的位置,下载完自动解压
                where = QFileDialog.getExistingDirectory(self, "文件夹保存到哪里", folder)
                if not where:
                    return
                path = os.path.join(where, m.file.get("name") or "文件夹.zip")
                tr["dir"] = True
            else:
                default = os.path.join(folder, m.file.get("name") or "文件")
                path, _ = QFileDialog.getSaveFileName(self, "保存文件", default)
                if not path:
                    return
            if not self._disk_ok(path, int(m.file["size"])):
                return
            tr.update({"state": "downloading", "done": 0, "path": path, "error": "", "size": m.file["size"],
                       "peer": m.sender, "auto": False, "autoplay": action == "dlplay", "stream": None})
            self._reset_speed(tr)
            self.core.download_file(m.sender, fid, path, m.file["size"], resume=False)
        elif action == "stream":                           # 视频还在下载:先看已经下好的部分
            if tr.get("state") == "done":
                self.play_video(tr.get("path", ""))
            elif tr.get("state") == "downloading" and tr.get("stream"):
                self.stream_video(fid, m.file.get("name", ""))
        elif action == "pause":
            tr["auto"] = False
            self.core.pause_file(fid)
        elif action == "resume":
            tr.setdefault("size", m.file["size"])
            tr["autoplay"] = tr.get("autoplay") or False
            tr["peer"] = m.sender
            if not self.peers.get(m.sender, {}).get("online"):
                tr.update({"state": "paused", "auto": True})
                info(self, "对方现在不在线", "对方上线后会自动从断点继续下载。")
            else:
                self._resume_download(fid, tr)
        elif action == "cancel":
            if tr.get("state") == "paused":
                try:
                    os.remove(tr.get("path", "") + ".part")
                except OSError:
                    pass
                tr.update({"state": "error", "error": "已取消", "auto": False, "done": 0})
                self._hist_dirty = True
            else:
                self.core.cancel_file(fid)
        elif action == "open":
            path = tr.get("path", "")
            if not os.path.exists(path):
                info(self, "找不到文件", "文件可能已被移动或删除。")
                return
            if file_ext(path) in DANGER_EXTS and not ask(self, "打开可执行文件?", "这个文件可以在你的电脑上运行程序。"
                                                          "只有确认来源可信时才打开。", "仍然打开", danger=True):
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif action == "play":
            self.play_video(tr.get("path", ""))
        elif action == "folder":
            self.reveal_file(tr.get("path", ""))
        self._update_file_card(fid)

    def _disk_ok(self, path: str, size: int) -> bool:
        """下载前看看硬盘空间够不够(大视频动不动十几 GB)。"""
        try:
            free = shutil.disk_usage(os.path.dirname(os.path.abspath(path)) or ".").free
        except OSError:
            return True
        if free >= size + 256 * 1024 * 1024:
            return True
        info(self, "硬盘空间不够", f"这个文件有 {imaging.human_size(size)},保存的位置只剩 {imaging.human_size(free)}。"
             "换个硬盘保存,或者先清理一下空间。")
        return False

    def _check_stream(self, tr: dict) -> None:
        """下载中的视频能不能边下边看:索引在开头的 MP4 / MOV,而且已经下了一点。结果记在 tr["stream"]。"""
        if tr.get("stream") is not None or not stream.can_stream(tr.get("path", "")):
            return
        done = int(tr.get("done") or 0)
        if done < min(int(tr.get("size") or 0), stream.STREAM_MIN):
            return
        ok = stream.mp4_streamable(tr["path"] + ".part", done)
        if ok is not None:
            tr["stream"] = ok

    @staticmethod
    def reveal_file(path: str) -> None:
        if not path:
            return
        if sys.platform == "win32" and os.path.exists(path):
            explorer = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe")
            subprocess.Popen(f'"{explorer}" /select,"{os.path.normpath(path)}"')
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    @staticmethod
    def _reset_speed(tr: dict) -> None:
        for k in ("speed", "lt", "ld"):
            tr.pop(k, None)

    @staticmethod
    def _track_speed(tr: dict, done: int) -> None:
        now = time.monotonic()
        if "lt" in tr:
            dt = now - tr["lt"]
            if dt < 0.15:
                return
            inst = max(0.0, (done - tr["ld"]) / dt)
            tr["speed"] = inst if not tr.get("speed") else tr["speed"] * 0.6 + inst * 0.4
        tr["lt"], tr["ld"] = now, done

    def _resume_download(self, fid: str, tr: dict) -> None:
        tr.update({"state": "downloading", "error": "", "auto": False, "retry": time.monotonic()})
        self._reset_speed(tr)
        self.core.download_file(tr["peer"], fid, tr["path"], int(tr.get("size", 0)), resume=True)
        self._update_file_card(fid)

    def _auto_resume(self, now: float) -> None:
        """因为断网 / 对方掉线而停下的下载:对方在线时自动从断点继续(每 8 秒最多尝试一次)。"""
        for fid, tr in list(self.transfers.items()):
            if (tr.get("state") == "paused" and tr.get("auto") and tr.get("path") and tr.get("peer")
                    and self.peers.get(tr["peer"], {}).get("online") and now - tr.get("retry", 0) >= 8):
                self._resume_download(fid, tr)

    def _update_file_card(self, fid: str) -> None:
        for b in self.bubbles.values():
            if b.msg.file and b.msg.file.get("fid") == fid:
                b.update_transfer(self.transfers.get(fid, {}))

    def _ev_file_progress(self, d: dict) -> None:
        fid = d["fid"]
        tr = self.transfers.get(fid)
        if tr is None:
            return
        if d.get("dir") == "up":
            peer = d.get("peer", "")
            if d.get("finished"):
                tr["up"].pop(peer, None)
                tr["up_done"] = tr.get("up_done", 0) + 1
            elif d.get("stopped"):
                tr["up"].pop(peer, None)
            else:
                tr["up"][peer] = (d.get("done", 0), d.get("total", 1))
            if tr["up"]:
                self._track_speed(tr, sum(x for x, _ in tr["up"].values()))
            else:
                self._reset_speed(tr)
        else:
            if tr.get("state") == "downloading":
                tr["done"] = d.get("done", 0)
                if d.get("resumed"):
                    self._reset_speed(tr)
                self._track_speed(tr, tr["done"])
                self._check_stream(tr)
        self._update_file_card(fid)

    def _ev_file_done(self, d: dict) -> None:
        if self.update_file_done(d):               # 是软件更新包,不是聊天里的文件
            return
        fid = d["fid"]
        tr = self.transfers.get(fid)
        if tr is None:
            return
        if d.get("ok"):
            tr.update({"state": "done", "path": d.get("path", tr.get("path", "")), "auto": False})
            if tr.get("dir") and not tr.get("folder"):
                self._extract_folder(fid, tr)
                return
            self._video_downloaded(fid, tr)
        elif d.get("paused") and tr.get("path"):
            err = d.get("error", "")
            tr.update({"state": "paused", "error": err, "auto": err != "已暂停",
                       "done": d.get("done", tr.get("done", 0)), "retry": time.monotonic()})
        else:
            tr.update({"state": "error", "error": d.get("error", "下载失败"), "auto": False})
        self._reset_speed(tr)
        self._hist_dirty = True
        self._update_file_card(fid)

    def _video_downloaded(self, fid: str, tr: dict) -> None:
        """视频下载好了:点封面下载的直接开始播放;对方没发封面的话自己取一张。"""
        conv, m = None, None
        for c in self.convs.values():
            m = next((x for x in reversed(c.messages) if x.file and x.file.get("fid") == fid), None)
            if m is not None:
                conv = c
                break
        path = tr.get("path", "")
        if m is None or not path or file_ext(path) not in VIDEO_EXTS:
            return
        streaming = self.video_win is not None and getattr(self.video_win, "path", "") == path
        if tr.pop("autoplay", False) and self.window_visible() and not streaming:   # 正在边下边看的就接着看
            QTimer.singleShot(0, lambda: self.play_video(path))
        if not m.file.get("thumb"):
            m.file["probed"] = True
            self.probe_video(path, lambda res, c=conv, msg=m: self.apply_poster(c, msg, res))

    # ---- 趣味互动
    def _apply_fun(self) -> None:
        pet_on = bool(self.fun["pet"])
        self.pet.setVisible(pet_on)
        if pet_on:
            self.pet.set_species(self.fun["pet"])
        self.pet.show_combo = self.fun["combo"]
        self.msg_layout.setContentsMargins(0, HEADER_H + 6, 0, 58 if pet_on else 10)   # 让最后一条消息不被宠物挡住
        self.chat_panel.place_overlays()

    def set_fun(self, key: str, value) -> None:
        self.fun[key] = value
        if key == "keysound" and value:
            threading.Thread(target=self.keysound.prepare, name="miyu-keyprep", daemon=True).start()
        if key in ("pet", "combo"):
            self._apply_fun()
        if key in ("pet", "gpet"):
            self.refresh_gpet()
            self.desktop_pet_sync()
        if key == "lv_badge":
            self._sync_level()
        if key == "effects" and not value:
            self.effects.clear()
        if key == "heat":
            self._heat_step()

    def _fill_fun_menu(self) -> None:
        fm = self.fun_menu
        fm.clear()
        head = fm.addAction("打字宠物")
        head.setEnabled(False)
        for key, sp in list(SPECIES.items()) + [(None, {"label": "不显示"})]:
            act = fm.addAction(sp["label"])
            act.setCheckable(True)
            act.setChecked(self.fun["pet"] == key)
            act.triggered.connect(lambda _=False, k=key: self.set_fun("pet", k))
        g = self.pet_growth
        cur, need, _ = g.progress()
        lvl = fm.addAction(f"{g.name} · Lv.{g.level}" + (f"(经验 {cur:,} / {need:,})" if need else "(满级)"))
        lvl.setEnabled(False)
        fm.addAction("给宠物改名…", self.rename_pet)
        fm.addAction("👗  衣橱和形态(装扮、表情、进化)…", self.show_wardrobe)
        fm.addAction("🍽  喂食和玩耍(也可以右键点宠物)…", lambda: self.pet_menu(QCursor.pos()))
        skins = make_menu(fm)
        skins.setTitle("气泡皮肤(对方也看得到)")
        self._fill_skin_menu(skins)
        fm.addMenu(skins)
        act = fm.addAction("允许别人的宠物来串门")
        act.setCheckable(True)
        act.setChecked(self.allow_visits)
        act.triggered.connect(lambda on: setattr(self, "allow_visits", on))
        self._fill_more_fun(fm)
        fm.addSeparator()
        for key, text in (("sparks", "打字火花"), ("combo", "连击计数"), ("send_anim", "发送动画"),
                          ("effects", "聊天特效(关键词、表情雨)"), ("heat", "聊天热度背景"), ("keysound", "打字音效")):
            act = fm.addAction(text)
            act.setCheckable(True)
            act.setChecked(bool(self.fun[key]))
            act.triggered.connect(lambda on, k=key: self.set_fun(k, on))
        fm.addSeparator()
        demo = make_menu(fm)
        demo.setTitle("预览特效")
        for name, text in (("balloons", "🎈 生日快乐"), ("confetti", "🎉 恭喜"), ("fireworks", "🎆 新年快乐"),
                           ("hearts", "❤️ 爱你"), ("snow", "❄️ 下雪"), ("rain", "🌧 下雨"), ("stars", "🌙 晚安"),
                           ("flames", "💪 加油"), ("laugh", "😂 哈哈哈")):
            demo.addAction(text, lambda n=name: self.effects.play(n))
        fm.addMenu(demo)
        stat = fm.addAction(f"累计敲击 {g.taps:,} 次 · 发送 {g.messages:,} 条 · 本次最高连击 {self.pet.best_combo}")
        stat.setEnabled(False)

    # ---- 聊天热度
    @staticmethod
    def heat_of(conv: Conv, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return conv.heat * 0.5 ** (max(0.0, now - conv.heat_t) / HEAT_HALF_LIFE)

    def bump_heat(self, conv: Conv, amount: float) -> None:
        if conv.kind == "self":                    # 自己的会话没有"热度"
            return
        now = time.monotonic()
        conv.heat = min(1.0, self.heat_of(conv, now) + amount)
        conv.heat_t = now
        if conv.key == self.current_key and self.fun.get("heat") and not self.heat_timer.isActive():
            self._heat_step()

    def _heat_step(self) -> None:
        conv = self.current
        h = self.heat_of(conv) if conv is not None and self.fun.get("heat") and self.window_visible() else 0.0
        panel = self.chat_panel
        if h <= 0.02:
            self.heat_timer.stop()
            if panel.heat:
                panel.heat = 0.0
                panel.update()
            return
        panel.heat = h
        panel.update()
        if h > 0.7 and self.fun.get("effects") and random.random() < (h - 0.7) * 0.6:
            self.effects._ember()                  # 聊得很热时,底部偶尔飘起一点火星
            self.effects._kick()
        if not self.heat_timer.isActive():
            self.heat_timer.start()

    # ---- 会话内搜索
    def open_search(self) -> None:
        if self.current is None:
            return
        self.search_bar.setVisible(True)
        self.chat_panel.place_overlays()
        self.search_edit.setFocus()
        self.search_edit.selectAll()
        if self.search_edit.text():
            self._on_search_text(self.search_edit.text())

    def close_search(self) -> None:
        if not self.search_bar.isVisible() and not self.search_hits:
            return
        self.search_bar.setVisible(False)
        self.search_hits, self.search_idx = [], -1
        for b in self.bubbles.values():
            b.set_search("", False)
        if self.input.isEnabled():
            self.input.setFocus()

    @staticmethod
    def _matches(m: Msg, q: str) -> bool:
        if m.system or m.gone:
            return False
        if m.file:
            return q in str(m.file.get("name", "")).lower()
        return q in m.text.lower()

    def _on_search_text(self, text: str) -> None:
        q = text.strip().lower()
        conv = self.current
        self.search_hits = self.search_mids(conv, q) if q and conv else []
        self.search_idx = len(self.search_hits) - 1        # 从最新的一条开始
        self._show_hit()

    def search_refresh(self) -> None:
        """搜索中来了新消息:重新算命中,当前位置不变。"""
        cur = self.search_hits[self.search_idx] if 0 <= self.search_idx < len(self.search_hits) else None
        q = self.search_edit.text().strip().lower()
        conv = self.current
        self.search_hits = self.search_mids(conv, q) if q and conv else []
        self.search_idx = self.search_hits.index(cur) if cur in self.search_hits else len(self.search_hits) - 1
        self._show_hit(scroll=False)

    def search_step(self, d: int) -> None:
        if not self.search_hits:
            return
        self.search_idx = (self.search_idx + d) % len(self.search_hits)
        self._show_hit()

    def _show_hit(self, scroll: bool = True) -> None:
        q = self.search_edit.text().strip()
        n = len(self.search_hits)
        if not q:
            self.search_count.setText("")
        else:
            self.search_count.setText(f"{self.search_idx + 1}/{n}" if n else "无结果")
        self.search_count.setProperty("empty", bool(q) and not n)
        repolish(self.search_count)
        for b in (self.search_up, self.search_down):
            b.setEnabled(n > 1)
        cur = self.search_hits[self.search_idx] if 0 <= self.search_idx < n else None
        if cur is not None and cur not in self.bubbles:
            self.show_window_at(cur)                      # 命中的是很早的消息:把那一段读出来渲染
        hits = set(self.search_hits)
        for mid, b in self.bubbles.items():
            b.set_search(q if mid in hits else "", mid == cur)
        if cur is not None and scroll:
            b = self.bubbles.get(cur)
            if b is not None:
                self._stick = False
                QTimer.singleShot(0, lambda b=b: self.msg_area.ensureWidgetVisible(b, 0, HEADER_H + 60))

    # ---- 宠物养成
    def _pet_level_up(self) -> None:
        """宠物升级:升级仪式(光柱 + 大数字 + 解锁卡),在群里发一张升级卡片,解锁的装扮自动穿上。"""
        from .fun import MYTHIC_LEVEL, TRICKS
        from .petcare import form_of
        g = self.pet_growth
        lv = g.level
        self.pet.level_up(lv)
        g.tickets += 1
        g.daily["levelup"] = lv
        lines: list[tuple[str, str]] = []
        form_now, form_before = form_of(lv), form_of(lv - 1)
        evolved = form_now[0] != form_before[0] and lv in (EVOLVE_LEVEL, MYTHIC_LEVEL)
        if form_now[0] != form_before[0]:
            lines.append(("🦋" if evolved else "🌱", f"进入「{form_now[1]}」:{form_now[2]}"))
        for aid, name, _lv, slot in g.unlocked_at(lv):
            if not any(ACC_BY_ID[w][3] == slot for w in g.wear):
                g.toggle(aid)                      # 新装扮自动穿上(那个部位空着的话)
            lines.append(("👒", f"新装扮「{name}」"))
        for sid, name, need, *_rest in theme.SKINS:
            if need == lv:
                lines.append(("💬", f"气泡皮肤「{name}」"))
        for need, tid, name, _dur in TRICKS:
            if need == lv:
                lines.append(("🎭", f"新动作「{name}」(右键宠物 → 表演一个)"))
        lines.append(("🎟️", "抽卡券 × 1"))
        title = f"{g.name} 升级了!"
        sub = f"✨ {g.name} 进化成了{form_now[1]}!" if evolved else ""
        shown = False
        if self.window_visible() and not self.locked and self.fun.get("effects", True):
            shown = self._levelup_show(lv, title, lines, sub, evolved)
        conv = self.current
        if conv is not None and (not shown or conv.kind not in ("lobby", "room")):
            text = f"🎉 {g.name} 升到 Lv.{lv} 了!" + "".join(f"\n{icon} {t}" for icon, t in lines)
            self._system(conv, text)
        self._announce_level(lv)
        for need, tid, _n, _d in TRICKS:
            if need == lv:
                QTimer.singleShot(2600, lambda t=tid: self.pet.trick(t))     # 当场表演一下刚学会的动作
        self.pet.update()

    def _levelup_show(self, lv: int, title: str, lines: list, sub: str, big: bool) -> bool:
        from .levelup import LevelUpOverlay
        ov = getattr(self, "levelup_overlay", None)
        if ov is None:
            ov = LevelUpOverlay(self.chat_panel)
            self.levelup_overlay = ov
        try:
            c = self.pet.geometry().center()
            origin = QPointF(c.x(), self.pet.geometry().top() + 40)
        except Exception:                           # noqa: BLE001
            origin = None
        ov.play(lv, title, lines, origin, sub, big)
        if big:
            self.effects.play("fireworks")
        return True

    def _announce_level(self, lv: int) -> None:
        """在我所在的群里发一张升级卡片(别人那边也会出现)。"""
        from .petcare import form_of
        g = self.pet_growth
        data = {"lv": lv, "name": g.name, "sp": self.pet.species, "wear": list(g.wear)[:8], "form": form_of(lv)[1]}
        for conv in list(self.convs.values()):
            if conv.kind not in ("lobby", "room"):
                continue
            if conv.kind == "lobby" and not self.me.get("lobby", True):
                continue
            scope, target = self.scope_target(conv)
            try:
                self.core.send_event(scope, target, "pet_lv", data)
            except Exception:                       # noqa: BLE001
                continue
            self._add_level_card(conv, self.me["id"], self.me.get("nick", ""), data, mine=True)

    def _add_level_card(self, conv: Conv, pid: str, nick: str, data: dict, mine: bool = False) -> None:
        card = {"type": "petlv", "lv": data["lv"], "name": data["name"], "sp": data["sp"], "wear": data["wear"],
                "form": data.get("form", "")}
        who = "我" if mine else nick
        m = Msg(f"🎉 {who}的{data['name']}升到 Lv.{data['lv']} 了!", sender=pid, nick=nick, mine=mine,
                tag=self.me.get("tag", "") if mine else (self.peers.get(pid) or {}).get("tag", ""), card=card)
        self.fresh_cards.add(m.mid)
        self._add_message(conv, m, count_unread=False)

    def rename_pet(self) -> None:
        text = prompt(self, "给宠物起名字", "最多 8 个字。", self.pet_growth.name, max_len=8, ok="好")
        if text is not None and text.strip():
            self.pet_growth.name = text.strip()[:8]

    def toggle_wear(self, aid: str) -> None:
        self.pet_growth.toggle(aid)
        self.pet.update()

    def _cursor_point(self) -> QPoint:
        r = self.input.cursorRect()
        return self.input.viewport().mapTo(self.chat_panel, r.center())

    def on_keystroke(self, kind: str) -> None:
        self.pet.tap(kind)                         # 宠物关掉时也记数,连击照常算
        self.record_key()
        self.privacy_touch()
        if self.visitor is not None:               # 来做客的宠物也跟着拍
            self.visitor.tap(kind)
            self.visit["taps"] += 1
        if self.current is not None:
            self.bump_heat(self.current, HEAT_KEY)
        if self.pet_growth.tap():
            self._pet_level_up()
        if self.pet_growth.pending:
            self._show_achievements()
        if self.fun["sparks"] and self.window_visible():
            pt = self._cursor_point()
            if kind == "delete":
                self.effects.fragments(pt.x(), pt.y())
            else:
                self.effects.sparks(pt.x(), pt.y(), self.pet.combo if self.fun["combo"] else 1)
        if self.fun["keysound"]:
            self.keysound.play(kind)

    def _sent_fx(self) -> None:
        if self.pet_growth.sent():
            self._pet_level_up()
        elif self.fun["pet"]:
            self.pet.cheer()                       # 跳一下,举起双爪,飘一颗小爱心
        if self.pet_growth.pending:
            self._show_achievements()
        if self.fun["send_anim"] and self.window_visible():
            c = self.send_btn.mapTo(self.chat_panel, self.send_btn.rect().center())
            self.effects.send_burst(c.x(), c.y())

    def _message_fx(self, m: Msg) -> None:
        """新消息出现在当前会话时:淡入;收到的让宠物抖耳朵;命中关键词放全屏特效。"""
        b = self.bubbles.get(m.mid)
        if b is not None:
            self.bubble_fx.mode = self.fun.get("bubble", "soft")
            after = (lambda b=b: self.bubble_fx.wiggle(b)) if getattr(m, "mention", False) and not m.mine else None
            if not self.bubble_fx.enter(b, self.msg_container, after) and after is not None:
                after()
        if not m.mine and self.fun["pet"]:
            self.pet.perk()
        if self.fun["effects"] and m.img is None and not m.file:
            eff = detect_effect(m.text)
            if eff:
                key = (self.current_key, eff if isinstance(eff, str) else eff[0])
                now = time.monotonic()
                if now - self._fx_last.get(key, -1e9) >= 12:          # 同一个特效 12 秒内不重复放
                    self._fx_last[key] = now
                    self.effects.play(eff)

    def _refresh_typing_bubble(self) -> None:
        conv = self.current
        if self.typing_bubble is not None and conv is not None:
            self.typing_bubble.setVisible(conv.kind == "dm" and self.is_typing(conv.target))

    def eventFilter(self, obj, ev) -> bool:
        if obj is getattr(self, "_pill", None) or obj is getattr(self, "_composer", None):
            if ev.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show):
                self.chat_panel.place_overlays()
        if self.frameless and obj in (getattr(self, "_chat_header", None), getattr(self, "sidebar_panel", None),
                                      getattr(self, "members_panel", None)):
            t = ev.type()
            if t == QEvent.Type.MouseButtonDblClick and obj is getattr(self, "_chat_header", None):
                if ev.button() == Qt.MouseButton.LeftButton:
                    self.toggle_maximize()
                    return True
            elif t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                if obj is not getattr(self, "_chat_header", None) and pos.y() > HEADER_H:
                    pass
                else:
                    child = obj.childAt(pos)
                    if not isinstance(child, QToolButton):
                        wh = self.windowHandle()
                        if wh is not None and hasattr(wh, "startSystemMove"):
                            wh.startSystemMove()
                        else:
                            gpos = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else QCursor.pos()
                            self._drag_win_pos = gpos - self.frameGeometry().topLeft()
                        return True
            elif t == QEvent.Type.MouseMove and self._drag_win_pos is not None:
                gpos = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else QCursor.pos()
                self.move(gpos - self._drag_win_pos)
                return True
            elif t == QEvent.Type.MouseButtonRelease:
                self._drag_win_pos = None
        lists = {getattr(self, "_member_vp", None): "member", getattr(self, "_conv_vp", None): "conv"}
        if obj in lists and obj is not None:
            t = ev.type()
            if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                target = self._drop_target(lists[obj], ev.position().toPoint()) if drop_paths(ev.mimeData()) else None
                if target is not None:
                    ev.acceptProposedAction()
                else:
                    ev.ignore()
                return True
            if t == QEvent.Type.Drop:
                target = self._drop_target(lists[obj], ev.position().toPoint())
                paths = drop_paths(ev.mimeData())
                if target is not None and paths:
                    ev.acceptProposedAction()
                    QTimer.singleShot(0, lambda: self.drop_on_conv(target, paths))
                return True
        return super().eventFilter(obj, ev)

    def _drop_target(self, which: str, pos) -> Conv | None:
        """投送:拖到成员列表里的某个人(私聊发给他)或会话列表里的某个会话。"""
        if which == "member":
            item = self.member_list.itemAt(pos)
            d = (item.data(Qt.ItemDataRole.UserRole) or {}) if item else {}
            if not d.get("id") or d.get("me"):
                return None
            return self.open_dm(d["id"], select=False)
        item = self.conv_list.itemAt(pos)
        return self.convs.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    # ---- 正在输入 / 已读
    def is_typing(self, pid: str | None) -> bool:
        return bool(pid) and self.typing_until.get(pid, 0) > time.monotonic()

    def _on_input_changed(self) -> None:
        conv = self.current
        if conv is None or conv.kind != "dm" or not self.send_typing_on or not self.input.toPlainText().strip():
            return
        now = time.monotonic()
        if now - self._typing_sent.get(conv.target, 0) >= 3 and self.peers.get(conv.target, {}).get("online"):
            self._typing_sent[conv.target] = now
            self.core.send_typing(conv.target)

    def _ev_typing(self, d: dict) -> None:
        self.typing_until[d["peer"]] = time.monotonic() + 5.5
        cur = self.current
        if cur is not None and cur.kind == "dm" and cur.target == d["peer"]:
            self._refresh_header()
            self._refresh_typing_bubble()
        self.conv_list.viewport().update()

    def _mark_read(self, conv: Conv | None) -> None:
        if conv is None or conv.kind != "dm" or conv.key != self.current_key:
            return
        if not (self.window_visible() and self.isActiveWindow()):
            return
        mids = [m.mid for m in conv.messages if not m.mine and not m.system and not m.read_sent]
        if not mids:
            return
        for m in conv.messages:
            if not m.mine and not m.system:
                m.read_sent = True
        if self.send_receipts:
            self.core.send_read(conv.target, mids)

    def _ev_read(self, d: dict) -> None:
        conv = self.convs.get("dm:" + d["peer"])
        if conv is None:
            return
        mids = set(d.get("mids") or [])
        for m in conv.messages:
            if m.mine and m.mid in mids:
                m.read = True
                m.delivered = True
        self._update_receipts(conv)

    def _update_receipts(self, conv: Conv) -> None:
        """私聊里只在最后一条自己的消息下面显示"已送达 / 已读"(和 iMessage 一样)。"""
        if conv.kind != "dm":
            return
        last = next((m for m in reversed(conv.messages) if m.mine and not m.system), None)
        for m in conv.messages:
            if not m.mine or m.system:
                continue
            new = ("已读" if m.read else "已送达" if m.delivered else "") if m is last else ""
            if m.receipt != new:
                m.receipt = new
                b = self.bubbles.get(m.mid)
                if b is not None:
                    b.update_meta(time.monotonic())

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange and getattr(self, "convs", None):
            self._sync_max_icon()
            self._hooks("winstate")                  # 最小化 / 还原(桌面陪伴的宠物跟着出现、消失)
        if e.type() == QEvent.Type.ActivationChange and getattr(self, "convs", None):
            if getattr(self, "cover", None) is not None:
                self.on_activation(self.isActiveWindow())
            if self.isActiveWindow():
                self._mark_read(self.current)

    # ---- 会话
    def clear_conv(self, conv: Conv) -> None:
        if conv.kind == "self":
            if not ask(self, "清空收藏?", "收藏里的所有内容都会被删除(收藏的文件本身不会被删)。", "清空", danger=True):
                return
            self._favs_dirty = True
            conv.messages = [m for m in conv.messages if m.system][:1]
            if conv.key == self.current_key:
                self._render_messages()
            conv.preview, conv.unread = "", 0
            self.conv_list.viewport().update()
            self._refresh_header()
            return
        self._hist_dirty = True
        for m in conv.messages:
            m.gone = True
        conv.messages = []
        self.forget_conv_history(conv)
        conv.preview = ""
        conv.unread = 0
        conv.last_time = 0.0
        if conv.key == self.current_key:
            self._render_messages()
        self.conv_list.viewport().update()

    def clear_current(self) -> None:
        if self.current is not None:
            self.clear_conv(self.current)

    def close_dm(self, conv: Conv) -> None:
        self._hist_dirty = True
        for m in conv.messages:
            m.gone = True
        self.convs.pop(conv.key, None)
        if self.current_key == conv.key:
            self.current_key = "lobby"
        self._refresh_conv_list()
        self.switch_to(self.current_key)

    def leave_room(self, conv: Conv) -> None:
        if ask(self, f"退出「{conv.title}」?", "本机的群聊记录会一起删除。", "退出", danger=True):
            self.core.leave_room(conv.target)

    def verify_current(self) -> None:
        if self.current is not None and self.current.kind == "dm":
            self.verify_conv(self.current)

    def verify_conv(self, conv: Conv) -> None:
        peer = self.peers.get(conv.target or "", {})
        number = self.core.safety_number(conv.target)
        name = f"{peer.get('nick', conv.title)} #{peer.get('tag', '')}"
        if SafetyDialog(self, name, number, conv.verified).exec():
            conv.verified = True
            if conv.target:
                self.verified_ids.add(conv.target)
            self._system(conv, "你已将对方标记为「已验证」")
            if conv.key == self.current_key:
                self._refresh_header()

    def join_room_dialog(self) -> None:
        dlg = JoinRoomDialog(self)
        if dlg.exec():
            self.core.join_room(dlg.passphrase, dlg.room_name)
            self.me_sub.setText("正在生成群密钥…")

    def change_nick(self) -> None:
        text = prompt(self, "修改昵称", "其他人会看到新的昵称。", self.me.get("nick", ""), max_len=MAX_NICK)
        if text is not None and clean_nick(text):
            self.core.set_nick(text)

    def show_identity(self) -> None:
        ips = "   ".join(self.me.get("ips") or []) or "没有检测到"
        rows = [
            ("昵称", f"{self.me.get('nick', '')}   #{self.me.get('tag', '')}"),
            ("个人指纹", self.me.get("fingerprint", "")),
            ("本机局域网 IP(对方手动添加你时需要)", ips),
            ("端口", f"UDP {self.me.get('udp_port')}   ·   TCP {self.me.get('tcp_port')}"),
        ]
        note = ("身份已加密保存在这台电脑上(绑定当前 Windows 账号),下次打开自动登录。点「注销账户」会彻底删除。"
                if self.remember else "身份在本次启动时随机生成,只存在内存里,关闭软件后就永久消失。")
        dlg = TextDialog(self, "我的身份", rows, note, extra=("注销账户", "destructive"))
        dlg.exec()
        if dlg.extra_clicked:
            self.logout()

    def show_security(self) -> None:
        TextDialog(self, "安全说明", [("", SECURITY_TEXT)], width=520).exec()

    def toggle_lobby(self, on: bool) -> None:
        if not on and not ask(self, "退出公开大厅?", "退出后大厅里的人看不到你,你也收不到大厅消息。\n暗号群和已有私聊照常可用。",
                              "退出大厅"):
            self.act_lobby.setChecked(True)
            return
        self.core.set_lobby(on)
        if on:
            self.note_entered("lobby")                   # 重新进入大厅:刚进来的 90 秒里放自己的登场效果

    def add_manual_ip(self) -> None:
        text = prompt(self, "手动添加对方 IP", "自动发现不到对方时使用(例如路由器开了 AP 隔离)。\n"
                      "对方的 IP 可以在他的「我的身份」里看到。", placeholder="例如 192.168.1.23", ok="添加")
        if text is None or not text.strip():
            return
        if self.core.add_manual_target(text):
            info(self, "已发送发现请求", f"已向 {text.strip()} 发送请求。对方需要开着密语,并且和你在同一个空间"
                                         "(都在大厅,或者用同一个暗号)。")
        else:
            info(self, "IP 格式不对", "请输入类似 192.168.1.23 的地址。")

    def disguise_title(self) -> None:
        text = prompt(self, "窗口标题伪装", "任务栏和窗口上显示的标题。", self.windowTitle(), ok="应用")
        if text is not None:
            self.setWindowTitle(text.strip() or APP_NAME)

    # ------------------------------------------------------------ 老板键
    def on_hotkey(self, name: str) -> None:
        if name == "toggle":
            self.toggle_hidden()
        elif name == "panic":
            self.panic()

    def on_escape(self) -> None:
        if self.selecting is not None:         # 正在多选:先退出多选
            self.exit_select()
            return
        if self.editing is not None:           # 正在编辑消息:先取消编辑
            self.cancel_edit()
            return
        if self.reply_to is not None:          # 正在引用回复时,第一下 ESC 先取消引用
            self.cancel_reply()
            return
        if self.search_bar.isVisible():        # 正在搜索时,先关搜索
            self.close_search()
            return
        if self.hotkeys_ok:
            self._hide_all()                   # 完全消失,Ctrl+Alt+H 叫回
        else:
            self.showMinimized()               # 全局热键不可用时只最小化,免得叫不回来

    def toggle_hidden(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide_window()
        else:
            self.show_window()

    def _hide_all(self) -> None:
        self.effects.clear()
        if getattr(self, "throw_layer", None) is not None:
            self.throw_layer.clear()
        if getattr(self, "enter_overlay", None) is not None:
            self.enter_overlay.stop()
        self.heat_timer.stop()
        self.ambient_pause()                   # 藏起来时白噪音必须停
        self.close_video()                     # 视频也关掉
        self.privacy_uncover()
        if self.lock_on_show:
            self.lock_now()                    # 设了"叫回时要密码":藏起来的同时就锁上
        for v in list(self._viewers):
            v.reject()
        for w in QApplication.topLevelWidgets():
            if w is not self and w.isVisible():
                w.hide()
        self.hide()

    def hide_window(self) -> None:
        if not self.hotkeys_ok and not self._warned_hide:
            self._warned_hide = True
            if not ask(self, "隐藏窗口?", "全局热键没有注册成功(可能被其他软件占用),隐藏后无法用 Ctrl+Alt+H 叫回窗口,"
                                        "只能结束程序。", "仍然隐藏"):
                return
        self._hide_all()

    def show_window(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self._start_visible_burns()
        self._heat_step()
        self.ambient_resume()
        self.show_pending_problems()

    def panic(self) -> None:
        """清空所有聊天记录(包括私聊会话)、剪贴板,然后隐藏窗口。"""
        for v in list(self._viewers):
            v.reject()
        for key in [k for k in self.convs if k.startswith("dm:")]:
            for m in self.convs.pop(key).messages:
                m.gone = True
        for conv in self.convs.values():
            if conv.kind == "self":                # 收藏是你特意存下的,紧急清空不删(注销账户才删)
                continue
            for m in conv.messages:
                m.gone = True
            conv.messages, conv.preview, conv.unread, conv.last_time = [], "", 0, 0.0
        self.input.clear()
        self.cancel_reply()
        self.close_search()
        self.pending_at.clear()
        imaging.thumb_cache.clear()                # 内存里缓存的图片缩略图也清掉
        self.effects.clear()
        for conv in self.convs.values():
            conv.heat = 0.0
        QApplication.clipboard().clear()
        if self.store is not None and self.save_history:
            self.wipe_history_files()
            self.open_history()                     # 之后的新消息照样加密保存(换了一把新钥匙)
        self._hist_dirty = False
        if self.current_key not in self.convs:
            self.current_key = "lobby"
        self._refresh_conv_list()
        self.switch_to(self.current_key)
        if self.hotkeys_ok:
            self._hide_all()
        else:
            self.showMinimized()

    def closeEvent(self, e) -> None:
        if self.remember:
            text = "账户会保留,下次打开自动登录。\n" + ("聊天记录已加密保存在本机。" if self.save_history
                                                  else "聊天记录没有开启保存,退出后清空。")
            ok = self._force_quit or ask(self, "退出密语?", text, "退出")
        else:
            ok = self._force_quit or ask(self, "退出密语?", "没有开启「记住登录」,本次的聊天记录和身份都会立即销毁。",
                                         "退出", danger=True)
        if ok:
            self._force_quit = True
            self.save_account(force=True)
            self.save_history_now(force=True)
            self.close_db()
            self.save_favs(force=True)
            self.tick.stop()
            for v in list(self._viewers):
                v.reject()
            e.accept()
            QTimer.singleShot(0, QApplication.quit)
        else:
            e.ignore()

    # ------------------------------------------------------------ 账户(记住我)
    def _restore_settings(self, acct: dict) -> None:
        st = acct.get("settings") if isinstance(acct.get("settings"), dict) else {}
        self.follow_system = bool(st.get("follow_system", True))
        self.sound_enabled = bool(st.get("sound", True))
        self.act_sound.setChecked(self.sound_enabled)
        self.sound_when_hidden = bool(st.get("sound_hidden", False))
        self.act_sound_hidden.setChecked(self.sound_when_hidden)
        self.flash_enabled = bool(st.get("flash", True))
        self.act_flash.setChecked(self.flash_enabled)
        self.send_receipts = bool(st.get("receipts", True))
        self.act_receipts.setChecked(self.send_receipts)
        self.send_typing_on = bool(st.get("typing", True))
        self.act_typing.setChecked(self.send_typing_on)
        if "frameless" in st and sys.platform == "win32":
            self.set_frameless(bool(st.get("frameless", True)))
        if "compact_side" in st:
            self.set_compact_side(bool(st.get("compact_side", False)))
        if "members_open" in st:
            self.set_members_open(bool(st.get("members_open", True)))
        fun = st.get("fun") if isinstance(st.get("fun"), dict) else {}
        for k in self.fun:
            if k not in fun:
                continue
            if k == "pet":
                if fun[k] is None or fun[k] in SPECIES:
                    self.fun[k] = fun[k]
            elif k == "skin":
                self.fun[k] = fun[k] if fun[k] in theme.SKIN_BY_ID else None
            elif k in ("fx", "snd"):
                self.fun[k] = fun[k] if isinstance(fun[k], str) else self.fun[k]
            elif k == "bubble":
                self.fun[k] = fun[k] if fun[k] in BUBBLE_MODES else "soft"
            else:
                self.fun[k] = bool(fun[k])
        if "bubble" not in fun and fun.get("pop") is False:      # 2.4 以前关掉了「气泡弹出动画」
            self.fun["bubble"] = "off"
        self._hooks("restore", acct, st)
        if self.fun.get("keysound"):
            threading.Thread(target=self.keysound.prepare, name="miyu-keyprep", daemon=True).start()
        self.recent_emojis = [e for e in (st.get("recent_emojis") or []) if isinstance(e, str)][:24]
        title = st.get("title")
        if isinstance(title, str) and title.strip():
            self.setWindowTitle(title[:60])
        self.verified_ids = {x for x in (acct.get("verified") or []) if isinstance(x, str)}
        self.muted_keys = {x for x in (acct.get("muted") or []) if isinstance(x, str)}
        self.pinned_keys = list(dict.fromkeys(x for x in (acct.get("pinned") or []) if isinstance(x, str)))[:50]

    def restore_after_start(self) -> None:
        """网络启动后调用:恢复暗号群和还没被下载完的文件邀请。"""
        for r in self.account.get("rooms") or []:
            if isinstance(r, dict):
                master = storage.b64d(r.get("master"))
                if len(master) == 32:
                    self.core.restore_room(master, str(r.get("name") or ""))
        offers = self.account.get("offers")
        if isinstance(offers, dict):
            self.core.restore_offers(offers)

    def account_dict(self) -> dict:
        rooms = []
        for tag, rk in self.room_keys.items():
            conv = self.convs.get("room:" + tag)
            if conv is not None:
                rooms.append({"master": rk["master"], "name": conv.title})
        try:
            offers = list(self.core.offers.items())
        except RuntimeError:
            offers = []
        week = time.time() - 7 * 86400
        offers = sorted(((fid, o) for fid, o in offers if o.get("time", 0) >= week), key=lambda x: -x[1].get("time", 0))
        title = self.windowTitle()
        return {
            "seed": storage.b64e(self.core.identity.seed),
            "nick": self.me.get("nick", ""),
            "lobby": bool(self.me.get("lobby", True)),
            "rooms": rooms,
            "settings": {
                "theme": T["name"], "follow_system": self.follow_system, "glass": theme.GLASS,
                "frameless": self.frameless, "compact_side": self.compact_side, "members_open": self.members_open,
                "sound": self.sound_enabled, "sound_hidden": self.sound_when_hidden, "flash": self.flash_enabled,
                "receipts": self.send_receipts, "typing": self.send_typing_on, "fun": dict(self.fun),
                "recent_emojis": self.recent_emojis[:24], "title": "" if title == APP_NAME else title,
                "save_history": self.save_history,
                **self._merged("settings"),
            },
            "verified": sorted(self.verified_ids),
            "muted": sorted(self.muted_keys),
            "pinned": list(self.pinned_keys),
            "pet": self.pet_growth.to_dict(),
            **self._merged("save"),
            "offers": {fid: {k: o.get(k) for k in ("path", "name", "size", "scope", "target", "mtime", "time")}
                       for fid, o in offers[:100]},
        }

    def save_account(self, force: bool = False) -> bool:
        if not self.remember or self.store is None:
            return False
        try:
            d = self.account_dict()
        except Exception:
            return False
        import json
        snap = json.dumps(d, sort_keys=True, ensure_ascii=False)
        if not force and snap == self._acct_snapshot:
            return True
        if self.store.save_account(d):
            self._acct_snapshot = snap
            return True
        return False

    def save_history_now(self, force: bool = False) -> bool:
        """把有变化的消息写进加密数据库(见 window/records.py)。"""
        return self.sync_history(force)

    def toggle_remember(self, on: bool) -> None:
        if self.store is None:
            self.act_remember.setChecked(False)
            return
        if on:
            self.remember = True
            self.save_account(force=True)
            self.save_favs(force=True)
            self.act_history.setEnabled(True)
        else:
            if not ask(self, "关闭记住登录?", "会删除保存在这台电脑上的账户、聊天记录和收藏(表情包保留)。\n"
                                            "关闭后,下次打开会是一个全新的身份。", "关闭", danger=True):
                self.act_remember.setChecked(True)
                return
            self.remember = False
            self.save_history = False
            self.act_history.setChecked(False)
            self.close_db()
            self.store.wipe(stickers=False)
            self._acct_snapshot = ""
        self.act_quit.setText("退出(保留账户)" if self.remember else "退出")

    def toggle_history(self, on: bool) -> None:
        if self.store is None:
            self.act_history.setChecked(False)
            return
        if on:
            if not ask(self, "保存聊天记录?", "聊天记录会加密保存在这台电脑上,重新打开还在。\n"
                                            "阅后即焚的消息永远不会保存;按 Ctrl+Alt+X 或「注销账户」会一起删除。", "保存"):
                self.act_history.setChecked(False)
                return
            if not self.remember:
                self.act_remember.setChecked(True)
                self.toggle_remember(True)
            self.save_history = True
            self.save_account(force=True)
            self.open_history()
            self.save_history_now(force=True)
        else:
            if not ask(self, "不再保存聊天记录?", "已经保存在电脑上的记录会被删除,当前窗口里的聊天不受影响。", "不再保存"):
                self.act_history.setChecked(True)
                return
            self.save_history = False
            self.wipe_history_files()
            self.save_account(force=True)

    def logout(self) -> None:
        dlg = LogoutDialog(self, self.remember)
        if not dlg.exec():
            return
        self.remember = False                 # 退出时不要再写账户文件
        self.save_history = False
        self.close_db()
        if self.store is not None:
            self.store.wipe(stickers=dlg.delete_stickers)
        if dlg.delete_stickers:
            self.stickers.clear()
        for conv in self.convs.values():
            for m in conv.messages:
                m.gone = True
        QApplication.clipboard().clear()
        self.relaunch = True
        self._force_quit = True
        self.close()

    # ------------------------------------------------------------ 网络事件
    def on_core_event(self, kind: str, data) -> None:
        handler = getattr(self, "_ev_" + kind, None)
        if handler is not None:
            handler(data)

    def _ev_ready(self, d: dict) -> None:
        self.me.update(d)
        self._refresh_self()
        self._refresh_header()
        self._refresh_members()

    def _ev_self(self, d: dict) -> None:
        old_lobby = self.me.get("lobby", True)
        self.me.update(d)
        self._refresh_self()
        if old_lobby != self.me.get("lobby", True):
            lobby = self.convs.get("lobby")
            if lobby:
                self._system(lobby, "你已重新进入公开大厅" if self.me["lobby"] else "你已退出公开大厅(隐身中)")
        self._refresh_header()
        self._refresh_members()
        self._refresh_input_state()
        self.conv_list.viewport().update()

    def _ev_peer(self, d: dict) -> None:
        pid = d["id"]
        old = self.peers.get(pid)
        self.peers[pid] = d
        name = d["nick"]
        old_rooms = set(old.get("rooms", [])) if old and old.get("online") else set()
        new_rooms = set(d.get("rooms", [])) if d.get("online") else set()
        if bool(d.get("online")) != bool(old and old.get("online")) and old is not None:
            motion.note_status(pid, bool(d.get("online")))           # 头像上的小圆点亮起 / 暗下时有一圈动画
            self._pulse_lists()
        if d.get("online") and not (old and old.get("online")):
            self._hooks("peer_online", pid)
        for tag in new_rooms - old_rooms:
            conv = self.convs.get("room:" + tag)
            if conv:
                self._system(conv, f"{name} 加入了群")
                self.sync_group_to(conv, pid)
        if d.get("online") and d.get("lobby") and not (old and old.get("online") and old.get("lobby")):
            lobby = self.convs.get("lobby")
            if lobby is not None and self.me.get("lobby", True):
                self.sync_group_to(lobby, pid)
        for tag in old_rooms - new_rooms:
            conv = self.convs.get("room:" + tag)
            if conv:
                self._system(conv, f"{name} 离开了群")
        conv = self.convs.get("dm:" + pid)
        if conv is not None:
            conv.title = name
            if old is not None and bool(old.get("online")) != bool(d.get("online")):
                self._system(conv, "对方已上线" if d.get("online") else "对方已离线")
        cur = self.current
        if cur is not None and (cur.kind != "dm" or cur.target == pid):
            self._refresh_header()
            self._refresh_members()
            self._refresh_input_state()
        self.conv_list.viewport().update()

    def _pulse_lists(self) -> None:
        """在线状态的动画进行中:会话列表和成员列表每秒刷新 30 次,动画放完就停。"""
        if not hasattr(self, "_pulse_timer"):
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setInterval(33)
            self._pulse_timer.timeout.connect(self._pulse_step)
        if not self._pulse_timer.isActive():
            self._pulse_timer.start()

    def _pulse_step(self) -> None:
        self.conv_list.viewport().update()
        self.member_list.viewport().update()
        if not motion.any_pulse():
            self._pulse_timer.stop()

    def _ev_message(self, d: dict) -> None:
        scope = d.get("scope")
        if scope == "lobby":
            conv = self.convs.get("lobby")
        elif scope == "room":
            conv = self.convs.get("room:" + (d.get("room") or ""))
        elif scope == "dm":
            conv = self.convs.get("dm:" + d["peer"]) or self.open_dm(d["peer"], select=False)
        else:
            conv = None
        if conv is None:
            return
        m = Msg(d.get("text", ""), mid=d["mid"], sender=d["peer"], nick=d["nick"], tag=d["tag"],
                burn=int(d.get("burn", 0)), img=d.get("img"), mime=d.get("mime"),
                w=int(d.get("w") or 0), h=int(d.get("h") or 0), reply=d.get("reply"), at=d.get("at") or [],
                file=d.get("file"), sticker=bool(d.get("sticker")), card=d.get("card"), skin=d.get("skin"),
                anon=bool(d.get("anon")))
        m.title = str(d.get("title") or "")
        m.level = int(d.get("level") or 0) if self.fun.get("lv_badge", True) else 0
        if isinstance(d.get("vid"), (bytes, bytearray)) and m.anon:
            m.vid = bytes(d["vid"])                       # 匿名纸条里的视频:内容就在消息里
        if m.card:
            self.fresh_cards.add(m.mid)
        m.mention = conv.kind != "dm" and ("all" in m.at or self.me.get("id") in m.at)
        if m.file and m.vid is None:
            self.transfers.setdefault(m.file["fid"], {"state": "offer", "peer": d["peer"]})
        self._add_message(conv, m)

    def _ev_sent(self, d: dict) -> None:
        mid = d["mid"]
        for conv in self.convs.values():
            m = next((x for x in reversed(conv.messages) if x.mid == mid), None)
            if m is None:
                continue
            if d.get("scope") == "dm":
                m.status = "" if d.get("delivered") else "未送达,对方已离线"
                m.delivered = bool(d.get("delivered"))
                self._update_receipts(conv)
            elif d.get("total", 0) == 0:
                m.status = "暂无其他人在线"
            elif d.get("delivered", 0) < d.get("total", 0):
                m.status = f"已送达 {d['delivered']}/{d['total']} 人"
            else:
                m.status = ""
            b = self.bubbles.get(mid)
            if b:
                b.update_meta(time.monotonic())
            break

    def _ev_room_joined(self, d: dict) -> None:
        key = "room:" + d["tag"]
        if d.get("master"):
            self.room_keys[d["tag"]] = {"master": d["master"], "name": d["name"]}
        conv = self.convs.get(key)
        if conv is None:
            conv = Conv(key, "room", d["name"], d["tag"])
            self.convs[key] = conv
            self._apply_conv_prefs(conv)
            if d.get("restored"):
                self._system(conv, "已自动恢复这个暗号群。")
            else:
                self._system(conv, "已加入暗号群。只有输入了同一暗号的人能看到这里的消息。\n想移除某人,只能所有人换一个新暗号。")
        self._refresh_self()
        if d.get("restored"):
            self._refresh_conv_list()
            if self.current_key == key:
                self.switch_to(key)
        else:
            self.select_conv(key)
            self.note_entered(key)                       # 刚加入的暗号群:90 秒里把登场效果发给碰到的人

    def _ev_room_left(self, d: dict) -> None:
        self.room_keys.pop(d["tag"], None)
        self.muted_keys.discard("room:" + d["tag"])
        if "room:" + d["tag"] in self.pinned_keys:
            self.pinned_keys.remove("room:" + d["tag"])
        self._hist_dirty = True
        conv = self.convs.pop("room:" + d["tag"], None)
        if conv is not None:
            for m in conv.messages:
                m.gone = True
        if self.current_key == "room:" + d["tag"]:
            self.current_key = "lobby"
        self._refresh_conv_list()
        self.switch_to(self.current_key)

    def _ev_room_error(self, d: dict) -> None:
        self._refresh_self()
        if d.get("tag") and ("room:" + d["tag"]) in self.convs:
            self.select_conv("room:" + d["tag"])
        info(self, "暗号群", d.get("text", "加入失败"))
