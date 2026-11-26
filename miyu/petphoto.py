"""
密语 3.7 · 萌宠「双人合拍大头贴」生成器 (2.5D 拍立得贴纸相框)
  · 支持与在线好友 / 群友 / 群宠物 / 单宠自拍生成高清晰度 2.5D 合影 PNG
  · 内置 4 套主题贴纸相框（樱花拍立得 / 奶油胶片 / 星空炫彩 / 复古胶卷）与日期水印
  · 一键发送到当前聊天晒娃，或保存到本地相册
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QPointF, QRectF, QStandardPaths, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QTextOption
from PySide6.QtWidgets import QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .dialogs import Dialog, info
from .fun import ACC_BY_ID, PetGrowth, SPECIES, TypingPet, star_path
from .ui import button, label

FRAME_STYLES = [
    ("sakura", "🌸 樱花拍立得", "#FFF0F6", "#FFD6E7", "#FF8FAB", "#5C2A3E"),
    ("cream", "🧈 奶油胶片", "#FFFDF7", "#FFF3D6", "#F5B301", "#4A3B28"),
    ("starry", "🌌 星空炫彩", "#1A1633", "#2D235C", "#B197FC", "#F3EEFF"),
    ("retro", "🎞️ 复古胶卷", "#F4EFE6", "#E6DBC8", "#8D6E63", "#3E2C23"),
]


def _render_single_pet(species: str, growth: PetGrowth, w: int = 240, h: int = 165) -> QImage:
    """高分屏离屏透明渲染一只完整的 2.5D 萌宠(含装扮、染色、毛色、瞳色,零白底)。"""
    img = QImage(w * 2, h * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    img.setDevicePixelRatio(2.0)
    pet = TypingPet(None)
    pet.bare = True
    pet.centered = True
    pet.visitor = True
    pet.show_room = False
    pet.growth = growth
    pet.set_species(species if species in SPECIES else "cat")
    pet.resize(TypingPet.W, TypingPet.H)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scale = 1.62
    p.translate(w / 2.0, h - 18.0)
    p.scale(scale, scale)
    p.translate(-TypingPet.W / 2.0, -TypingPet.EDGE)
    pet._paint_pet(p, time.monotonic(), "idle")
    p.end()
    return img


def render_photobooth(my_growth: PetGrowth, my_species: str, my_nick: str,
                      peer_spec: dict | None = None, style_id: str = "sakura",
                      caption: str = "") -> QImage:
    """生成 680x460 (2x 清晰度) 的 2.5D 萌宠合拍大头贴 QImage。"""
    st = next((s for s in FRAME_STYLES if s[0] == style_id), FRAME_STYLES[0])
    _sid, _sname, bg_top, bg_bot, accent_hex, text_hex = st
    W, H = 680, 460
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # 1) 外框拍立得卡片
    outer = QRectF(8, 8, W - 16, H - 16)
    p.setPen(QPen(QColor(accent_hex), 2.5))
    p.setBrush(QColor("#FFFFFF" if style_id != "starry" else "#16132A"))
    p.drawRoundedRect(outer, 26, 26)

    # 2) 内景相纸渐变背景
    photo = QRectF(28, 28, W - 56, H - 122)
    g = QLinearGradient(photo.topLeft(), photo.bottomRight())
    g.setColorAt(0.0, QColor(bg_top))
    g.setColorAt(1.0, QColor(bg_bot))
    p.setPen(QPen(QColor(accent_hex).lighter(120), 1.4))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(photo, 18, 18)

    # 氛围圆点 & 星星贴纸装饰
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(photo, 18, 18)
    p.setClipPath(clip)
    p.setPen(Qt.PenStyle.NoPen)
    ac = QColor(accent_hex)
    for cx, cy, rr, a in ((90, 80, 68, 30), (590, 95, 76, 30), (340, 290, 120, 22)):
        c = QColor(ac)
        c.setAlpha(a)
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy), rr, rr)

    # 复古胶卷齿孔装饰
    if style_id == "retro":
        p.setBrush(QColor(62, 44, 35, 38))
        for hx in range(44, W - 44, 32):
            p.drawRoundedRect(QRectF(hx, 34, 14, 9), 3, 3)
            p.drawRoundedRect(QRectF(hx, photo.bottom() - 15, 14, 9), 3, 3)

    # 底部桌台线条
    desk_y = photo.bottom() - 48
    p.setBrush(QColor(255, 255, 255, 165) if style_id != "starry" else QColor(255, 255, 255, 28))
    p.drawRect(QRectF(photo.left(), desk_y, photo.width(), photo.bottom() - desk_y))
    p.setPen(QPen(QColor(accent_hex), 1.6))
    p.drawLine(QPointF(photo.left(), desk_y), QPointF(photo.right(), desk_y))

    # 3) 渲染 1 只或 2 只 2.5D 萌宠
    left_img = _render_single_pet(my_species, my_growth)
    if peer_spec is not None:
        pg = PetGrowth({"xp": max(0, int(peer_spec.get("xp", 0)))})
        lv = max(1, int(peer_spec.get("level", 1)))
        if pg.level < lv:
            from .fun import xp_for_level
            pg.xp = xp_for_level(lv)
        pg.wear = [w for w in (peer_spec.get("wear") or []) if w in ACC_BY_ID]
        pg.coat = str(peer_spec.get("coat") or "classic")
        pg.eyes = str(peer_spec.get("eyes") or "obsidian")
        pg.dye = dict(peer_spec.get("dye") or {})
        right_img = _render_single_pet(str(peer_spec.get("species") or "cat"), pg)
        p.drawImage(QRectF(95, desk_y - 147, 240, 165), left_img)
        p.drawImage(QRectF(345, desk_y - 147, 240, 165), right_img)
        # 中间漂浮一颗合拍小心心
        p.save()
        p.translate(W / 2.0, desk_y - 96)
        p.setPen(QPen(QColor("#FFFFFF"), 2.0))
        p.setBrush(QColor("#FF6B8A"))
        hp = QPainterPath(QPointF(0, 12))
        hp.cubicTo(-18, 2, -14, -14, 0, -5)
        hp.cubicTo(14, -14, 18, 2, 0, 12)
        p.drawPath(hp)
        p.restore()
    else:
        p.drawImage(QRectF(W / 2.0 - 120, desk_y - 147, 240, 165), left_img)

    # 角落小星星贴纸
    for sx, sy, sr in ((62, 72, 9.0), (W - 68, 76, 10.0), (88, 132, 5.5), (W - 92, 146, 6.0)):
        p.save()
        p.translate(sx, sy)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFD43B"))
        p.drawPath(star_path(sr, 0.45))
        p.restore()

    # 宠物名牌小标签
    bf = QFont()
    bf.setFamilies(["Segoe UI Variable Text", "Microsoft YaHei UI", "PingFang SC"])
    bf.setPixelSize(13)
    bf.setWeight(QFont.Weight.Bold)
    p.setFont(bf)
    def _draw_tag(cx: float, txt: str) -> None:
        tw = p.fontMetrics().horizontalAdvance(txt) + 22
        tr = QRectF(cx - tw / 2, desk_y + 11, tw, 26)
        p.setPen(QPen(QColor(accent_hex), 1.2))
        p.setBrush(QColor("#FFFFFF" if style_id != "starry" else "#2B224C"))
        p.drawRoundedRect(tr, 13, 13)
        p.setPen(QColor(text_hex))
        p.drawText(tr, txt, QTextOption(Qt.AlignmentFlag.AlignCenter))

    my_tag = f"{my_growth.name} · Lv.{my_growth.level}"
    if peer_spec is not None:
        _draw_tag(215, my_tag)
        p_name = str(peer_spec.get("name") or peer_spec.get("nick") or "好朋友")[:10]
        p_lv = max(1, int(peer_spec.get("level", 1)))
        _draw_tag(465, f"{p_name} · Lv.{p_lv}")
    else:
        _draw_tag(W / 2.0, my_tag)
    p.restore()

    # 4) 拍立得底部留白：寄语 + 日期水印
    cap = caption.strip() or (
        f"{my_nick} × {peer_spec.get('nick', '好友')} 的萌宠大头贴 ✨" if peer_spec else f"{my_nick} & {my_growth.name} 今日打卡 ✨"
    )
    cf = QFont(bf)
    cf.setPixelSize(16)
    p.setFont(cf)
    p.setPen(QColor(text_hex))
    p.drawText(QRectF(36, H - 84, W - 72, 30), cap[:34], QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))

    df = QFont(bf)
    df.setPixelSize(12)
    df.setWeight(QFont.Weight.Medium)
    p.setFont(df)
    p.setPen(QColor(text_hex).lighter(130) if style_id != "starry" else QColor("#B197FC"))
    today = time.strftime("%Y.%m.%d")
    p.drawText(QRectF(36, H - 48, W - 72, 22), f"📸 MiYu 2.5D PhotoBooth  ·  {today}",
               QTextOption(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight))
    p.end()
    return img


class PhotoBoothDialog(Dialog):
    """萌宠双人合拍大头贴预览与一键发送窗口。"""

    def __init__(self, win, initial_peer_id: str | None = None) -> None:
        super().__init__(win, "萌宠双人合拍大头贴")
        self.win = win
        self.setFixedWidth(560)
        self._style = "sakura"
        self._img: QImage | None = None
        self._peers = self._collect_targets()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(label("📸 2.5D 萌宠合拍大头贴", "dialogTitle"))

        # 选择合拍对象 + 相框风格
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        ctrl.addWidget(label("合拍对象:", "hint"))
        self.partner_box = QComboBox(self)
        for label_txt, _spec in self._peers:
            self.partner_box.addItem(label_txt)
        if initial_peer_id:
            for i, (_t, sp) in enumerate(self._peers):
                if sp and sp.get("id") == initial_peer_id:
                    self.partner_box.setCurrentIndex(i)
                    break
        self.partner_box.currentIndexChanged.connect(self._render)
        ctrl.addWidget(self.partner_box, 1)
        lay.addLayout(ctrl)

        srow = QHBoxLayout()
        srow.setSpacing(6)
        self._style_btns: dict[str, QPushButton] = {}
        for sid, sname, *_r in FRAME_STYLES:
            b = QPushButton(sname, self)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setChecked(sid == self._style)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=sid: self._pick_style(k))
            srow.addWidget(b)
            self._style_btns[sid] = b
        lay.addLayout(srow)

        self.cap_edit = QLineEdit(self)
        self.cap_edit.setPlaceholderText("写一句合拍寄语（留空自动生成）…")
        self.cap_edit.setMaxLength(32)
        self.cap_edit.textChanged.connect(self._render)
        lay.addWidget(self.cap_edit)

        self.preview_lab = QLabel(self)
        self.preview_lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lab.setFixedSize(510, 345)
        self.preview_lab.setObjectName("plainCard")
        lay.addWidget(self.preview_lab, 0, Qt.AlignmentFlag.AlignHCenter)

        brow = QHBoxLayout()
        brow.addWidget(button("💾 保存 PNG", "", self._save_png, 112))
        brow.addStretch(1)
        brow.addWidget(button("关闭", "", self.reject, 76))
        self.send_btn = button("📤 发送到当前聊天", "primary", self._send_chat, 152)
        brow.addWidget(self.send_btn)
        lay.addLayout(brow)
        self._render()

    def _collect_targets(self) -> list[tuple[str, dict | None]]:
        out: list[tuple[str, dict | None]] = []
        seen: set[str] = set()
        # 优先收集排行榜 / 好友宠物名片 + 在线群友
        pr_cards = getattr(self.win, "pr_cards", {}) or {}
        me_id = self.win.me.get("id", "")
        for pid, p in (self.win.peers or {}).items():
            if pid == me_id:
                continue
            seen.add(pid)
            card = pr_cards.get(pid) or {}
            nick = p.get("nick") or card.get("n") or "好友"
            pet_name = card.get("pn") or f"{nick}的萌宠"
            sp = card.get("sp") or "cat"
            lv = card.get("lv") or p.get("level") or 1
            wear = card.get("wear") or []
            out.append((f"🐾 {nick} · {pet_name} (Lv.{lv})",
                        {"id": pid, "nick": nick, "name": pet_name, "species": sp, "level": lv, "wear": wear}))
        for pid, card in pr_cards.items():
            if pid == me_id or pid in seen:
                continue
            seen.add(pid)
            nick = card.get("n") or "群友"
            pet_name = card.get("pn") or "萌宠"
            out.append((f"🐾 {nick} · {pet_name} (Lv.{card.get('lv', 1)})",
                        {"id": pid, "nick": nick, "name": pet_name, "species": card.get("sp", "cat"),
                         "level": card.get("lv", 1), "wear": card.get("wear", [])}))
        # 当前群宠物(如果在暗号群)
        conv = getattr(self.win, "current", None)
        if conv is not None and conv.kind == "room" and hasattr(self.win, "gpet_for"):
            gp = self.win.gpet_for(conv.target)
            out.insert(0, (f"🏠 群宠 {gp.name[0]} (Lv.{gp.level})",
                           {"id": "gpet", "nick": conv.title, "name": gp.name[0], "species": gp.species[0],
                            "level": gp.level, "wear": list(gp.wear[0])}))
        out.append(("✨ 单宠自拍大头贴", None))
        return out

    def _pick_style(self, sid: str) -> None:
        self._style = sid
        for k, b in self._style_btns.items():
            b.setChecked(k == sid)
        self._render()

    def _render(self) -> None:
        idx = max(0, min(len(self._peers) - 1, self.partner_box.currentIndex()))
        partner = self._peers[idx][1] if self._peers else None
        self._img = render_photobooth(
            self.win.pet_growth, self.win.pet.species, self.win.me.get("nick", "我"),
            partner, self._style, self.cap_edit.text(),
        )
        pm = QPixmap.fromImage(self._img).scaled(
            self.preview_lab.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.preview_lab.setPixmap(pm)

    def _png_bytes(self) -> bytes:
        if self._img is None:
            return b""
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        self._img.save(buf, "PNG")
        return bytes(ba)

    def _save_png(self) -> None:
        if self._img is None:
            return
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        default = f"{folder}/MiYu_PhotoBooth_{time.strftime('%Y%m%d_%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "保存萌宠大头贴", default, "PNG 图片 (*.png)")
        if path:
            self._img.save(path, "PNG")
            info(self, "已保存", f"大头贴已保存到：\n{path}")

    def _send_chat(self) -> None:
        conv = getattr(self.win, "current", None)
        if conv is None or not self.win.input.isEnabled():
            info(self, "当前无法发送", "请先切到一个可发送消息的会话。")
            return
        if self._img is not None:
            self.win._send_one_image(conv, self._img)
            self.win.pet.celebrate()
            self.win.pet.say("咔嚓! 大头贴发出去啦 📸", 2.8)
            self.accept()
