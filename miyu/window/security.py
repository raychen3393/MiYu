"""
密语 · 启动密码(锁屏)和防偷看模式。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QTextOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .. import theme
from ..dialogs import Dialog, Switch, ask, info
from ..icons import app_logo
from ..theme import T, qcolor
from ..ui import button, label


class PrivacyCover(QWidget):
    """防偷看:把聊天内容盖成一片模糊。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.blurred: QPixmap | None = None
        self.hide()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), qcolor(T["bg"]))
        if self.blurred is not None:
            p.drawPixmap(self.rect(), self.blurred)
        tint = QColor(T["bg"])
        tint.setAlpha(110)
        p.fillRect(self.rect(), tint)
        p.setPen(qcolor(T["sub"]))
        p.drawText(QRectF(self.rect()), "🙈  内容已模糊 · 把鼠标移回来,或直接打字",
                   QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class LockDialog(Dialog):
    """启动时输入密码。check(password) 返回 True 表示正确。"""

    def __init__(self, check, app_icon=None) -> None:
        super().__init__(None, "密语")
        if app_icon is not None:
            self.setWindowIcon(app_icon)
        self.check = check
        self.forgot = False
        self.fails = 0
        self.setFixedWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 32, 36, 26)
        lay.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(app_logo(64))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)
        lay.addWidget(label("密语已上锁", "bigTitle", center=True))
        lay.addWidget(label("输入启动密码解锁", "hint", center=True))
        lay.addSpacing(10)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("启动密码")
        self.edit.returnPressed.connect(self.try_unlock)
        lay.addWidget(self.edit)
        self.err = label("", "errorText", center=True)
        lay.addWidget(self.err)
        lay.addSpacing(6)
        self.go = button("解锁", "primary", self.try_unlock)
        self.go.setMinimumHeight(40)
        lay.addWidget(self.go)
        lay.addWidget(button("忘记密码?", "link", self._forgot))

    def try_unlock(self) -> None:
        pw = self.edit.text()
        if not pw:
            return
        if self.check(pw):
            self.accept()
            return
        self.fails += 1
        self.edit.clear()
        if self.fails >= 3:                        # 输错 3 次以上:每次多等几秒,防止乱试
            wait = min(30, 2 * (self.fails - 2))
            self.err.setText(f"密码不对,{wait} 秒后再试")
            self.go.setEnabled(False)
            self.edit.setEnabled(False)
            QTimer.singleShot(wait * 1000, self._release)
        else:
            self.err.setText("密码不对")

    def _release(self) -> None:
        self.go.setEnabled(True)
        self.edit.setEnabled(True)
        self.err.setText("")
        self.edit.setFocus()

    def _forgot(self) -> None:
        if ask(self, "忘记密码?", "密码无法找回(没有任何人能解开)。\n只能注销这个账户,以全新的身份重新开始。\n"
                                  "表情包会保留。", "注销账户", danger=True):
            self.forgot = True
            self.reject()


class LockOverlay(QWidget):
    """窗口叫回时盖住全部内容的锁屏。"""
    unlocked = Signal()

    def __init__(self, parent, check) -> None:
        super().__init__(parent)
        self.check = check
        self.fails = 0
        self.setObjectName("lockOverlay")
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        box = QFrame()
        box.setObjectName("card")
        box.setFixedWidth(340)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(30, 28, 30, 24)
        bl.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(app_logo(56))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(logo)
        bl.addWidget(label("已锁定", "dialogTitle", center=True))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("启动密码")
        self.edit.returnPressed.connect(self.try_unlock)
        bl.addWidget(self.edit)
        self.err = label("", "errorText", center=True)
        bl.addWidget(self.err)
        self.go = button("解锁", "primary", self.try_unlock)
        bl.addWidget(self.go)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(box)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.hide()

    def paintEvent(self, e) -> None:
        theme.paint_wallpaper(self, e)

    def lock(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.edit.clear()
        self.err.setText("")
        self.show()
        self.raise_()
        self.edit.setFocus()

    def try_unlock(self) -> None:
        pw = self.edit.text()
        if not pw:
            return
        if self.check(pw):
            self.hide()
            self.fails = 0
            self.unlocked.emit()
            return
        self.fails += 1
        self.edit.clear()
        if self.fails >= 3:
            wait = min(30, 2 * (self.fails - 2))
            self.err.setText(f"密码不对,{wait} 秒后再试")
            self.go.setEnabled(False)
            self.edit.setEnabled(False)
            QTimer.singleShot(wait * 1000, self._release)
        else:
            self.err.setText("密码不对")

    def _release(self) -> None:
        self.go.setEnabled(True)
        self.edit.setEnabled(True)
        self.err.setText("")


class PasswordDialog(Dialog):
    """设置 / 修改 / 去掉启动密码。结果:action = "set" | "remove",password = 新密码。"""

    def __init__(self, parent, has_password: bool, lock_on_show: bool, verify=None) -> None:
        super().__init__(parent, "启动密码")
        self.verify = verify
        self.action = ""
        self.password = ""
        self.setFixedWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        lay.addWidget(label("修改启动密码" if has_password else "设置启动密码", "dialogTitle"))
        lay.addWidget(label("打开软件时要先输入密码。保存在电脑上的账户和聊天记录会用这个密码再加密一层,"
                            "别人用你的电脑也打不开。\n密码忘了无法找回,只能注销账户。", "hint", wrap=True))
        lay.addSpacing(4)
        self.old = None
        if has_password:
            self.old = QLineEdit()
            self.old.setEchoMode(QLineEdit.EchoMode.Password)
            self.old.setPlaceholderText("当前密码")
            lay.addWidget(self.old)
        self.new1 = QLineEdit()
        self.new1.setEchoMode(QLineEdit.EchoMode.Password)
        self.new1.setPlaceholderText("新密码(至少 4 位)")
        lay.addWidget(self.new1)
        self.new2 = QLineEdit()
        self.new2.setEchoMode(QLineEdit.EchoMode.Password)
        self.new2.setPlaceholderText("再输一遍")
        lay.addWidget(self.new2)
        card = QFrame()
        card.setObjectName("plainCard")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(14, 6, 12, 6)
        cl.addWidget(label("叫回窗口时也要输密码"))
        cl.addStretch(1)
        self.on_show = Switch(lock_on_show)
        cl.addWidget(self.on_show)
        lay.addWidget(card)
        self.err = label("", "errorText")
        lay.addWidget(self.err)
        row = QHBoxLayout()
        if has_password:
            row.addWidget(button("去掉密码", "destructive", self._remove))
        row.addStretch(1)
        row.addWidget(button("取消", "", self.reject, 80))
        ok = button("保存", "primary", self._save, 80)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)

    def _check_old(self) -> bool:
        if self.old is None:
            return True
        if self.verify is not None and self.verify(self.old.text()):
            return True
        self.err.setText("当前密码不对")
        return False

    def _save(self) -> None:
        if not self._check_old():
            return
        a, b = self.new1.text(), self.new2.text()
        if len(a) < 4:
            self.err.setText("新密码至少 4 位")
            return
        if a != b:
            self.err.setText("两次输入的不一样")
            return
        self.action, self.password = "set", a
        self.accept()

    def _remove(self) -> None:
        if not self._check_old():
            return
        self.action = "remove"
        self.accept()

    @property
    def lock_on_show(self) -> bool:
        return self.on_show.isChecked()


class SecurityMixin:
    """启动密码、防偷看。"""

    # ---------------------------------------------------------------- 钩子(见 gui.MainWindow.TOPICS)

    def _init_security(self) -> None:
        self.lock_on_show = False                # 叫回窗口时也要输密码
        self.privacy = True                      # 防偷看模式(默认开)
        self._mouse_out_t = 0.0
        self.lock_overlay = LockOverlay(self.centralWidget(), self._check_password)
        self.lock_overlay.unlocked.connect(self._on_unlocked)
        self.cover = PrivacyCover(self.msg_area)

    def _restore_security(self, acct: dict, st: dict) -> None:
        self.lock_on_show = bool(st.get("lock_on_show", False))
        self.privacy = bool(st.get("privacy", True))
        self.act_privacy.setChecked(self.privacy)

    def _settings_security(self) -> dict:
        return {"lock_on_show": self.lock_on_show, "privacy": self.privacy}

    def _tick_security(self, now: float) -> None:
        if self.privacy and self._mouse_out_t and now - self._mouse_out_t >= 2.0 and not self.cover.isVisible():
            self.privacy_cover()                 # 鼠标离开窗口 2 秒还没回来

    def _place_security(self) -> None:
        if self.cover.isVisible():
            self.cover.setGeometry(self.msg_area.rect())

    # ---------------------------------------------------------------- 启动密码
    def _check_password(self, pw: str) -> bool:
        return self.store is not None and self.store.verify(pw)

    def set_password_dialog(self) -> None:
        if self.store is None or not self.remember:
            info(self, "先打开「记住登录」", "启动密码是用来保护保存在电脑上的账户的。没开记住登录时什么也不保存,不需要密码。")
            return
        dlg = PasswordDialog(self, self.store.has_password, self.lock_on_show, self.store.verify)
        if not dlg.exec():
            return
        self.lock_on_show = dlg.lock_on_show
        if dlg.action == "set":
            self.store.set_password(dlg.password)
            info(self, "已设置启动密码", "下次打开软件要先输入密码。" + ("用 Ctrl+Alt+H 叫回窗口时也要输入。"
                                                                     if self.lock_on_show else ""))
        elif dlg.action == "remove":
            self.store.set_password(None)
            self.lock_on_show = False
        self.save_account(force=True)
        self.save_favs(force=True)
        self._save_background()
        self.gm_save()
        self.save_history_now(force=True)

    def lock_now(self) -> None:
        if self.store is not None and self.store.has_password:
            self.lock_overlay.lock()

    def _on_unlocked(self) -> None:
        if self.input.isEnabled():
            self.input.setFocus()
        self.show_pending_problems()

    @property
    def locked(self) -> bool:
        return self.lock_overlay.isVisible()

    # ---------------------------------------------------------------- 防偷看
    def set_privacy(self, on: bool) -> None:
        self.privacy = on
        if not on:
            self.privacy_uncover()

    def privacy_cover(self) -> None:
        if not self.privacy or self.cover.isVisible() or not self.window_visible():
            return
        try:
            pm = self.msg_area.grab()
            w, h = max(1, pm.width() // 14), max(1, pm.height() // 14)
            self.cover.blurred = pm.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        except Exception:
            self.cover.blurred = None
        self.cover.setGeometry(self.msg_area.rect())
        self.cover.show()
        self.cover.raise_()

    def privacy_uncover(self) -> None:
        self._mouse_out_t = 0.0
        if self.cover.isVisible():
            self.cover.hide()
            self.cover.blurred = None

    def privacy_touch(self) -> None:
        """在窗口里打字 = 人就在电脑前,恢复清晰。"""
        if self._mouse_out_t:
            self._mouse_out_t = time.monotonic()
        if self.cover.isVisible():
            self.privacy_uncover()
            self._mouse_out_t = time.monotonic()

    def enterEvent(self, e) -> None:
        super().enterEvent(e)
        if getattr(self, "cover", None) is not None and self.isActiveWindow():
            self.privacy_uncover()

    def leaveEvent(self, e) -> None:
        super().leaveEvent(e)
        if getattr(self, "cover", None) is not None and self.privacy:
            self._mouse_out_t = time.monotonic()               # 2 秒后还没回来就模糊(在 _tick_more 里)

    def on_activation(self, active: bool) -> None:
        if active:
            if self.underMouse():
                self.privacy_uncover()
        elif self.privacy:
            self.privacy_cover()
