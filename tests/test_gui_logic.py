"""
界面逻辑测试:用 tests/fakeqt 里的 PySide6 替身 + 真实的网络核心,跑完整的聊天流程。
(替身只模拟控件的状态,不画界面;真实界面需在 Windows 上运行 run.bat 检查。)
运行:python -m unittest tests.test_gui_logic -v
"""
import math
import os
import queue
import sys
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fakeqt"))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import QTimer        # noqa: E402  (替身)
from PySide6.QtWidgets import QApplication  # noqa: E402

from miyu import gui, theme              # noqa: E402
from miyu import cards, dialogs, ui      # noqa: E402
from miyu.window import games, look       # noqa: E402
from miyu.window import system as gui_system  # noqa: E402
from miyu.core import Core               # noqa: E402

gui.ask = lambda *a, **k: True           # 替身里没有真的弹窗,确认框一律"确定"

BASE = 53000 + (os.getpid() % 400) * 10


def make_gif(frames=3, w=40, h=30):
    """手工拼一张会动的 GIF(每帧一种颜色),再塞一段注释,用来检查发送前会不会去掉。"""
    import struct
    out = bytearray(b"GIF89a" + struct.pack("<HH", w, h) + bytes([0xF1, 0, 0]))
    out += bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])           # 4 色调色板
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"               # 循环播放
    out += b"\x21\xfe\x0csecret note\x00\x00"                               # 注释(应该被去掉)
    for i in range(frames):
        out += b"\x21\xf9\x04\x04\x0a\x00\x00\x00"                         # 每帧 0.1 秒
        out += b"\x2c" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00"
        # 最简单的 LZW 数据:清除码 + 颜色 i + 结束码(2 位颜色,最小码长 2)
        clear, end = 4, 5
        bits = clear | (i % 4) << 3 | end << 6
        data = bits.to_bytes(2, "little")
        out += b"\x02" + bytes([len(data)]) + data + b"\x00"
    out += b"\x3b"
    return bytes(out)


def make_jpeg():
    from io import BytesIO
    try:
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", (64, 48), (120, 160, 220)).save(buf, "JPEG")
        return buf.getvalue()
    except ImportError:
        return b"\xff\xd8\xff\xe0" + bytes(2000)


class Harness:
    def __init__(self, name, port, targets, lobby=True, identity=None, **win_kw):
        self.q = queue.Queue()
        self.core = Core(on_event=lambda k, d: self.q.put((k, d)), udp_port=port, tcp_port=0, identity=identity)
        self.core.extra_targets = targets
        self.win = gui.MainWindow(self.core, ui.make_icon(), lobby, **win_kw)
        self.win.show()
        assert self.core.start(nick=name, lobby=lobby), self.core.start_error
        self.win.restore_after_start()

    @property
    def id(self):
        return self.core.id_hex

    def pump(self):
        while True:
            try:
                k, d = self.q.get_nowait()
            except queue.Empty:
                break
            self.win.on_core_event(k, d)
        QTimer.run_pending()

    def conv(self, key):
        return self.win.convs.get(key)

    def texts(self, key, mine=None):
        c = self.conv(key)
        if c is None:
            return []
        return [m.text for m in c.messages if not m.system and (mine is None or m.mine == mine)]

    def systems(self, key):
        c = self.conv(key)
        return [m.text for m in c.messages if m.system] if c else []

    def throws(self, key):
        """扔东西的动画卡片(2.5 起不再是系统消息)。"""
        c = self.conv(key)
        return [m.text for m in c.messages if (m.card or {}).get("type") == "throw"] if c else []

    def say(self, text, burn=0):
        self.win.set_burn(burn)
        self.win.input.setPlainText(text)
        self.win.send_current()
        self.win.set_burn(0)

    def images(self, key, mine=None):
        c = self.conv(key)
        return [m for m in c.messages if m.img is not None and (mine is None or m.mine == mine)] if c else []


def pump_until(hs, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        for h in hs:
            h.pump()
        if cond():
            return True
        time.sleep(0.05)
    for h in hs:
        h.pump()
    return cond()


class FakeCloseEvent:
    def __init__(self):
        self.accepted = None

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class HelperTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(gui.fmt_secs(5), "5s")
        self.assertEqual(gui.fmt_secs(65), "1:05")
        long = "https://example.com/" + "a" * 100
        self.assertIn("​", ui.soft_wrap(long))
        self.assertEqual(ui.soft_wrap(long).replace("​", ""), long)
        self.assertEqual(ui.soft_wrap("中文不需要处理" * 20), "中文不需要处理" * 20)
        self.assertIn(gui.color_for("zz"), ui.AVATAR_COLORS)

    def test_sticker_store(self):
        import tempfile
        from miyu.stickers import StickerStore, sniff_mime
        jpg = make_jpeg()
        self.assertEqual(sniff_mime(jpg), "image/jpeg")
        st = StickerStore(tempfile.mkdtemp())
        a = st.add(jpg)
        self.assertEqual(st.add(jpg), a)                          # 同一张不重复
        self.assertEqual(len(st.items), 1)
        self.assertIsNone(st.add(b"not an image"))
        files = os.listdir(st.folder)
        self.assertEqual(len(files), 1)
        with open(os.path.join(st.folder, files[0]), "rb") as f:
            self.assertTrue(f.read().startswith(b"MIYUSTK"))       # 不是直接的图片文件
        st2 = StickerStore(st.folder)
        st2.load()
        self.assertEqual(st2.items[0]["data"], jpg)
        st2.remove(a)
        self.assertEqual(st2.items, [])
        st.clear()

    def test_detect_effect(self):
        from miyu.fun import detect_effect as d
        cases = {"生日快乐呀": "balloons", "恭喜恭喜": "confetti", "新年快乐!": "fireworks", "我爱你": "hearts",
                 "明天下雪吗": "snow", "外面在下雨": "rain", "晚安~": "stars", "加油!": "flames",
                 "哈哈哈哈哈哈哈": "laugh", "好的": None, "哈哈哈": None, "今天天气不错": None}
        for text, want in cases.items():
            self.assertEqual(d(text), want, text)
        self.assertEqual(d("👍"), ("emoji", "👍"))
        self.assertIsNone(d("ok 👍"))                         # 有文字就不是"单发表情"

    def test_pet_states(self):
        from miyu.fun import TypingPet
        pet = TypingPet()
        self.assertEqual(pet.count, 0)
        for _ in range(20):
            pet.tap("char")
        self.assertEqual(pet.count, 20)
        self.assertEqual(pet.combo, 20)
        self.assertEqual(pet.mood(), "focus")                 # 打得飞快 → 认真脸
        self.assertTrue(pet.combo_visible())
        pet.tap("delete")
        self.assertEqual(pet.mood(), "surprise")
        pet.celebrate()
        self.assertEqual(pet.mood(), "happy")
        pet._happy_t = pet._surprise_t = -1e9
        pet._last_key -= 30                                   # 30 秒没打字 → 睡着
        self.assertEqual(pet.mood(), "sleep")
        pet.perk()                                            # 来消息 → 醒过来抖耳朵
        self.assertNotEqual(pet.mood(), "sleep")
        pet.set_species("bear")
        self.assertEqual(pet.species, "bear")
        pet.set_species("dragon")                             # 不认识的忽略
        self.assertEqual(pet.species, "bear")

    def test_effect_engine(self):
        from miyu.fun import EffectLayer
        layer = EffectLayer()
        layer.width = lambda: 800
        layer.height = lambda: 600
        layer.sparks(100, 500, combo=30)
        self.assertGreaterEqual(len(layer.parts), 8)
        layer.fragments(100, 500)
        layer.send_burst(700, 560)
        for name in ("confetti", "balloons", "hearts", "stars", "laugh", ("emoji", "🐶")):
            layer.play(name)
        self.assertTrue(len(layer.parts) <= 450)
        layer.clear()
        layer.play("fireworks")                               # 火箭升空后会爆开成很多火花
        saw_fw = False
        for _ in range(80):
            layer.step(0.05)
            time.sleep(0.02)
            saw_fw = saw_fw or any(p.kind == "fw" for p in layer.parts)
        self.assertTrue(saw_fw)
        layer.clear()
        layer.play("snow")                                    # 持续生成的特效到点会停
        layer.step(0.1)
        self.assertTrue(layer.spawners)
        layer.spawners[0][0] = time.monotonic() - 1
        layer.step(0.1)
        self.assertFalse(layer.spawners)
        for _ in range(200):
            layer.step(0.05)
        self.assertEqual(layer.parts, [])                     # 最后全部消失

    def test_key_sound(self):
        import io
        import wave
        from miyu.sound import KeySound, key_pcm, key_wav
        peaks = {}
        for kind in ("char", "space", "enter", "delete"):
            with wave.open(io.BytesIO(key_wav(kind)), "rb") as w:
                self.assertLess(w.getnframes() / w.getframerate(), 0.1)
            pcm = key_pcm(kind)
            peaks[kind] = max(abs(x) for x in pcm)
            self.assertLess(peaks[kind], 32767)                # 不爆音
            self.assertGreater(peaks[kind], 4000)              # 也不会小到听不见
            self.assertNotEqual(key_pcm(kind, 0)[:200], key_pcm(kind, 1)[:200])   # 每次按键略有不同
        self.assertLess(max(peaks.values()) / min(peaks.values()), 3)              # 几种键音量差不多
        ks = KeySound()
        ks.prepare()
        self.assertTrue(ks.play("char"))
        self.assertFalse(ks.play("char"))                     # 同一次按键重复上报只响一次
        time.sleep(0.015)
        self.assertTrue(ks.play("space"))                     # 正常连打不会被吞

    def test_ime_keystrokes_exact(self):
        class Ev:
            def __init__(self, pre, commit=""):
                self.pre, self.commit = pre, commit
            def preeditString(self):
                return self.pre
            def commitString(self):
                return self.commit
        box = gui.ChatInput()
        got = []
        box.keystroke.connect(got.append)
        for ev in (Ev("n"), Ev("n"), Ev("ni"), Ev("nih"), Ev("ni"), Ev("", "你")):
            box.inputMethodEvent(ev)
        # n → 按键;同样的 n 再来一次(只是光标变了)→ 不算;i、h → 按键;退格 → 删除;上屏 → 空格
        self.assertEqual(got, ["char", "char", "char", "delete", "space"])
        from miyu.fun import TypingPet
        pet = TypingPet()
        pet.tap("space")
        self.assertLess(time.monotonic() - pet._both_t, 0.1)  # 空格:两只爪子一起拍

    def test_ime_hides_placeholder(self):
        # 用中文输入法拼音时,灰色提示文字要先藏起来,不然会和拼音叠在一起
        class Ev:
            def __init__(self, pre, commit=""):
                self.pre, self.commit = pre, commit
            def preeditString(self):
                return self.pre
            def commitString(self):
                return self.commit
        box = gui.ChatInput()
        box.set_hint("发消息")
        self.assertEqual(box.placeholderText(), "发消息")
        box.inputMethodEvent(Ev("fan"))
        self.assertEqual(box.placeholderText(), "")
        box.set_hint("发消息")                                # 拼写途中刷新提示也不能冒出来
        self.assertEqual(box.placeholderText(), "")
        box.inputMethodEvent(Ev("", "反"))                     # 上屏
        self.assertEqual(box.placeholderText(), "发消息")
        box.inputMethodEvent(Ev("fu"))
        box.inputMethodEvent(Ev(""))                          # 取消拼写
        self.assertEqual(box.placeholderText(), "发消息")

    def test_chime(self):
        import io
        import wave
        from miyu.sound import Notifier, chime_wav
        with wave.open(io.BytesIO(chime_wav()), "rb") as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 44100))
            self.assertAlmostEqual(w.getnframes() / w.getframerate(), 0.55, places=2)
        n = Notifier()
        self.assertTrue(n.play())
        self.assertFalse(n.play())                        # 1.2 秒内不重复响
        self.assertTrue(n.play(force=True))

    def test_dialogs_build(self):
        app = QApplication()
        for name in ("light", "dusk", "dark"):
            theme.apply(app, name, glass=False)
            self.assertIn("QLabel#bubbleMine", theme.build_qss())
            self.assertEqual(theme.T["name"], name)
        self.assertEqual(theme.qcolor("rgba(10,20,30,0.5)").__class__.__name__, "QColor")
        icon = ui.make_icon()
        d = dialogs.StartDialog("匿名-ABCD", icon)
        d.nick.setText("  小明\x00  ")
        self.assertEqual(d.nickname, "小明")
        self.assertTrue(d.join_lobby)
        d.lobby.setChecked(False)
        self.assertFalse(d.join_lobby)
        dialogs.AlertDialog(None, "标题", "内容", [("取消", ""), ("好", "primary")])
        dialogs.PromptDialog(None, "标题", "说明", "值", "提示", "确定", 20)
        j = gui.JoinRoomDialog(None)
        for text, expect_ok, level in (("abc", False, "bad"), ("abcdefg", True, "warn"),
                                       ("晴天-猫爪-火锅-0917", True, "good")):
            j.pw.setText(text)
            self.assertEqual(j.ok.isEnabled(), expect_ok, text)
            self.assertEqual(j.strength.objectName(), level, text)
        gui.SafetyDialog(None, "某人 #ABCD", "11111 22222 33333 44444 55555 66666 77777 88888", False)
        gui.TextDialog(None, "x", [("a", "b")], "note")
        self.assertEqual(ui.fmt_sep(time.time())[:2], "今天")
        self.assertEqual(ui.fmt_sep(time.time() - 86400)[:2], "昨天")


class GuiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ports = [BASE, BASE + 1, BASE + 2]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.A = Harness("阿甲", ports[0], mk(0))
        cls.B = Harness("阿乙", ports[1], mk(1))
        cls.C = Harness("阿丙", ports[2], mk(2))
        cls.all = [cls.A, cls.B, cls.C]

    @classmethod
    def tearDownClass(cls):
        for h in cls.all:
            h.core.stop()

    def test_01_lobby(self):
        A, B, C = self.A, self.B, self.C
        self.assertTrue(pump_until(self.all, lambda: all(h.win.lobby_count() == 3 for h in self.all)))
        self.assertEqual(A.win.member_list.count(), 3)
        self.assertEqual(A.win.me_name.text(), "阿甲")
        self.assertIn("3 人在线", A.win.chat_sub.text())

        A.say("大家好,我是阿甲")
        self.assertEqual(A.texts("lobby", mine=True), ["大家好,我是阿甲"])
        self.assertEqual(A.win.input.toPlainText(), "")
        self.assertTrue(pump_until(self.all, lambda: "大家好,我是阿甲" in B.texts("lobby")
                                   and "大家好,我是阿甲" in C.texts("lobby")))
        m = B.conv("lobby").messages[-1]
        self.assertEqual((m.nick, m.sender, m.mine), ("阿甲", A.id, False))
        self.assertIn(m.mid, B.win.bubbles)               # 当前会话,已经画出气泡
        self.assertTrue(B.win.bubbles[m.mid].body is not None)
        self.assertEqual(A.conv("lobby").messages[-1].status, "")   # 全部送达

    def test_02_dm_and_unread(self):
        A, B = self.A, self.B
        B.win.open_dm(A.id)
        self.assertEqual(B.win.current_key, "dm:" + A.id)
        self.assertTrue(B.win.input.isEnabled())
        B.say("只给你看")
        self.assertTrue(pump_until(self.all, lambda: "只给你看" in A.texts("dm:" + B.id)))
        self.assertEqual(A.conv("dm:" + B.id).unread, 1)
        self.assertNotIn("只给你看", self.C.texts("lobby"))
        self.assertEqual(A.conv("dm:" + B.id).preview, "只给你看")
        A.win.select_conv("dm:" + B.id)
        self.assertEqual(A.conv("dm:" + B.id).unread, 0)
        self.assertIn("阿乙", A.win.chat_title.text())

        A.win.verify_conv(A.conv("dm:" + B.id))
        self.assertTrue(A.conv("dm:" + B.id).verified)
        self.assertEqual(A.win.verify_btn.text(), "已验证")
        self.assertEqual(self.A.core.safety_number(B.id), self.B.core.safety_number(A.id))

    def test_03_burn_after_reading(self):
        A, B = self.A, self.B
        key_on_a, key_on_b = "dm:" + B.id, "dm:" + A.id
        # A 正在看这个私聊:收到就开始倒计时
        A.win.select_conv(key_on_a)
        B.win.select_conv(key_on_b)
        B.say("看完就烧", burn=1)
        self.assertTrue(pump_until(self.all, lambda: "看完就烧" in A.texts(key_on_a)))
        self.assertIsNotNone(A.conv(key_on_a).messages[-1].deadline)
        self.assertIn("🔥", A.conv(key_on_a).preview)
        time.sleep(1.2)
        A.win._on_tick()
        B.win._on_tick()
        self.assertNotIn("看完就烧", A.texts(key_on_a))
        self.assertNotIn("看完就烧", B.texts(key_on_b))

        # A 没在看:不计时;切过去才开始
        A.win.select_conv("lobby")
        B.say("你打开才烧", burn=1)
        self.assertTrue(pump_until(self.all, lambda: "你打开才烧" in A.texts(key_on_a)))
        time.sleep(1.2)
        A.win._on_tick()
        self.assertIn("你打开才烧", A.texts(key_on_a))
        A.win.select_conv(key_on_a)
        time.sleep(1.2)
        A.win._on_tick()
        self.assertNotIn("你打开才烧", A.texts(key_on_a))

    def test_04_secret_room(self):
        A, B, C = self.A, self.B, self.C
        A.core.join_room("晴天-猫爪-火锅-0917", "测试群")
        B.core.join_room("晴天-猫爪-火锅-0917", "")
        self.assertTrue(pump_until(self.all, lambda: any(k.startswith("room:") for k in A.win.convs)
                                   and any(k.startswith("room:") for k in B.win.convs)))
        key = next(k for k in A.win.convs if k.startswith("room:"))
        self.assertIn(key, B.win.convs)
        self.assertEqual(A.conv(key).title, "测试群")
        self.assertEqual(B.conv(key).title, "暗号群 1")
        self.assertEqual(A.win.current_key, key)          # 加入后自动切过去
        tag = key[5:]
        self.assertTrue(pump_until(self.all, lambda: A.win.room_count(tag) == 2 and B.win.room_count(tag) == 2))
        self.assertTrue(any("加入了群" in s for s in A.systems(key)))
        A.say("群里说")
        self.assertTrue(pump_until(self.all, lambda: "群里说" in B.texts(key)))
        time.sleep(0.8)
        C.pump()
        self.assertFalse(any(k.startswith("room:") for k in C.win.convs))
        self.assertFalse(any("群里说" in t for c in C.win.convs.values() for t in [m.text for m in c.messages]))

        # 重复加入同一个暗号 → 提示并切到已有的群
        A.win.select_conv("lobby")
        A.core.join_room("晴天-猫爪-火锅-0917", "再来")
        self.assertTrue(pump_until(self.all, lambda: A.win.current_key == key))

    def test_04b_images(self):
        A, B = self.A, self.B
        jpg = make_jpeg()
        key_b = "dm:" + A.id
        B.win.select_conv(key_b)
        mid = B.win.send_image_data(B.conv(key_b), jpg, "image/jpeg", 64, 48)
        self.assertIsNotNone(mid)
        mine = B.images(key_b, mine=True)[-1]
        self.assertEqual(mine.status, "发送中…")
        self.assertEqual(B.conv(key_b).preview, "我: [图片]")
        key_a = "dm:" + B.id
        self.assertTrue(pump_until(self.all, lambda: any(m.img == jpg for m in A.images(key_a))))
        got = [m for m in A.images(key_a) if m.img == jpg][0]
        self.assertEqual((got.mime, got.w, got.h), ("image/jpeg", 64, 48))
        self.assertTrue(pump_until(self.all, lambda: mine.status == ""))        # 送达后状态清掉
        # 阅后即焚图片:点开才开始倒计时,时间到自动删除
        B.win.set_burn(1)
        B.win.send_image_data(B.conv(key_b), jpg, "image/jpeg", 64, 48)
        B.win.set_burn(0)
        A.win.select_conv(key_a)
        self.assertTrue(pump_until(self.all, lambda: any(m.burn for m in A.images(key_a))))
        burn_img = [m for m in A.images(key_a) if m.burn][0]
        time.sleep(1.2)
        A.win._on_tick()
        self.assertIn(burn_img, A.conv(key_a).messages, "没点开就被烧了")
        self.assertIsNone(burn_img.deadline)
        A.win.open_image(burn_img)
        self.assertIsNotNone(burn_img.deadline)
        time.sleep(1.2)
        A.win._on_tick()
        self.assertNotIn(burn_img, A.conv(key_a).messages)
        self.assertTrue(burn_img.gone)
        self.assertIsNone(burn_img.img)                                       # 图片数据也丢掉
        # 群里发图
        key = next(k for k in A.win.convs if k.startswith("room:"))
        A.win.send_image_data(A.conv(key), jpg, "image/jpeg", 64, 48)
        self.assertTrue(pump_until(self.all, lambda: any(m.img == jpg for m in B.images(key))))
        time.sleep(0.5)
        self.C.pump()
        self.assertFalse(any(m.img for c in self.C.win.convs.values() for m in c.messages))
        # 非法数据发不出去
        self.assertIsNone(A.win.send_image_data(A.conv(key), b"not an image", "image/jpeg", 1, 1))

    def test_04c_theme_switch(self):
        A = self.A
        seen = []
        for _ in range(len(theme.THEMES)):                  # 依次切换一圈,每个主题都会轮到
            A.win.toggle_theme()
            seen.append(theme.T["name"])
        self.assertEqual(sorted(seen), sorted(theme.THEMES))
        A.win.set_theme("dusk")
        self.assertEqual(theme.T["name"], "dusk")
        self.assertTrue(theme.is_dark())                    # 黄昏是浅色文字
        self.assertFalse(A.win.follow_system)
        for name in ("light", "dusk", "dark"):
            theme.apply(QApplication(), name)
            theme.render_wallpaper(900, 600)                # 三套壁纸都能画
            self.assertIn("QLabel#timeSep", theme.build_qss())
        A.win.set_theme("system")
        self.assertTrue(A.win.follow_system)
        A.win._fill_theme_menu()
        A.win.set_burn(30)
        self.assertEqual(A.win.burn_btn.objectName(), "burnOn")
        A.win.set_burn(0)
        self.assertEqual(A.win.burn_btn.objectName(), "round")

    def test_04d_sounds(self):
        A, B = self.A, self.B
        A.win.notifier.MIN_GAP = 0
        key_a, key_b = "dm:" + B.id, "dm:" + A.id
        A.win.select_conv("lobby")                       # A 没在看这个私聊 → 应该响
        B.win.select_conv(key_b)

        def send_and_count(text):
            before = A.win.notifier.played
            B.say(text)
            self.assertTrue(pump_until(self.all, lambda: text in A.texts(key_a)))
            return A.win.notifier.played - before

        self.assertEqual(send_and_count("响一下"), 1)
        A.win.set_muted(A.conv(key_a), True)              # 单个会话静音
        self.assertEqual(send_and_count("静音了"), 0)
        A.win.set_muted(A.conv(key_a), False)
        A.win.set_sound_enabled(False)                    # 总开关
        self.assertEqual(send_and_count("总开关关了"), 0)
        A.win.set_sound_enabled(True)
        A.win.hide()                                      # 隐藏时默认不响
        self.assertEqual(send_and_count("隐藏中"), 0)
        A.win.sound_when_hidden = True
        self.assertEqual(send_and_count("隐藏也响"), 1)
        A.win.sound_when_hidden = False
        A.win.show()
        # 群里同样可以单独静音
        key = next(k for k in A.win.convs if k.startswith("room:"))
        A.win.set_muted(A.conv(key), True)
        before = A.win.notifier.played
        B.win.select_conv(key)
        B.say("群消息静音")
        self.assertTrue(pump_until(self.all, lambda: "群消息静音" in A.texts(key)))
        self.assertEqual(A.win.notifier.played, before)
        A.win.set_muted(A.conv(key), False)

    def test_04e_files(self):
        import tempfile
        A, B = self.A, self.B
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "合同.pdf")
        data = os.urandom(700 * 1024)
        with open(src, "wb") as f:
            f.write(data)
        key_b, key_a = "dm:" + A.id, "dm:" + B.id
        B.win.select_conv(key_b)
        B.win.send_files([src])
        mine = [m for m in B.conv(key_b).messages if m.file][-1]
        fid = mine.file["fid"]
        self.assertTrue(B.win.transfers[fid]["mine"])
        self.assertEqual(B.conv(key_b).preview, "我: [文件] 合同.pdf")
        self.assertTrue(pump_until(self.all, lambda: any(m.file and m.file["fid"] == fid for m in A.conv(key_a).messages)))
        got = [m for m in A.conv(key_a).messages if m.file and m.file["fid"] == fid][0]
        self.assertEqual(A.win.transfers[fid]["state"], "offer")
        dest = os.path.join(tmp, "下载的合同.pdf")
        gui.QStandardPaths.writableLocation = staticmethod(lambda *a: tmp)
        gui.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (dest, ""))
        A.win.on_file_action(got, "download")
        self.assertEqual(A.win.transfers[fid]["state"], "downloading")
        self.assertTrue(pump_until(self.all, lambda: A.win.transfers[fid]["state"] == "done", timeout=30))
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), data)
        self.assertTrue(pump_until(self.all, lambda: B.win.transfers[fid].get("up_done") == 1))
        # 发送方撤回 → 接收方的文件卡片消失
        B.win.recall_msg(mine)
        self.assertTrue(pump_until(self.all, lambda: not any(m.file and m.file["fid"] == fid
                                                             for m in A.conv(key_a).messages)))

    def test_04f_reply_recall_mention(self):
        A, B = self.A, self.B
        key_b, key_a = "dm:" + A.id, "dm:" + B.id
        A.win.select_conv(key_a)
        B.win.select_conv(key_b)
        orig = [m for m in A.conv(key_a).messages if m.text == "只给你看"][0]
        A.win.start_reply(orig)
        self.assertTrue(A.win.reply_bar.isVisible())
        A.say("这是回复")
        self.assertIsNone(A.win.reply_to)
        self.assertTrue(pump_until(self.all, lambda: "这是回复" in B.texts(key_b)))
        r = [m for m in B.conv(key_b).messages if m.text == "这是回复"][0].reply
        self.assertEqual((r["mid"], r["preview"]), (orig.mid, "只给你看"))
        # 撤回
        A.say("说错了")
        self.assertTrue(pump_until(self.all, lambda: "说错了" in B.texts(key_b)))
        A.win.recall_msg([m for m in A.conv(key_a).messages if m.text == "说错了"][0])
        self.assertNotIn("说错了", A.texts(key_a))
        self.assertIn("你撤回了一条消息", A.systems(key_a))
        self.assertTrue(pump_until(self.all, lambda: "说错了" not in B.texts(key_b)))
        self.assertTrue(any("撤回了一条消息" in t for t in B.systems(key_b)))
        # @:被 @ 的人即使静音了也会响,会话列表显示 [有人@我]
        key = next(k for k in A.win.convs if k.startswith("room:"))
        A.win.select_conv("lobby")
        A.win.set_muted(A.conv(key), True)
        before = A.win.notifier.played
        B.win.select_conv(key)
        B.win.input.setPlainText("@")
        B.win.insert_mention(A.win.me["nick"], A.id)
        B.win.input.insertPlainText("看这里")
        B.win.send_current()
        self.assertTrue(pump_until(self.all, lambda: any(m.mention for m in A.conv(key).messages)))
        self.assertTrue(A.conv(key).at_me)
        self.assertEqual(A.win.notifier.played, before + 1)
        A.win.select_conv(key)
        self.assertFalse(A.conv(key).at_me)
        A.win.set_muted(A.conv(key), False)

    def test_04g_read_typing_emoji_stickers(self):
        import tempfile
        from miyu.stickers import StickerStore
        A, B = self.A, self.B
        key_b, key_a = "dm:" + A.id, "dm:" + B.id
        A.win.isActiveWindow = lambda: True
        try:
            B.win.select_conv(key_b)
            A.win.select_conv("lobby")
            B.say("你读了吗")
            self.assertTrue(pump_until(self.all, lambda: "你读了吗" in A.texts(key_a)))
            last = [m for m in B.conv(key_b).messages if m.text == "你读了吗"][0]
            self.assertTrue(pump_until(self.all, lambda: last.receipt == "已送达"))
            A.win.select_conv(key_a)                                   # A 打开会话 → 已读
            self.assertTrue(pump_until(self.all, lambda: last.receipt == "已读"))
            A.win.input.setPlainText("正在打字")
            self.assertTrue(pump_until(self.all, lambda: B.win.is_typing(A.id)))
            self.assertEqual(B.win.chat_sub.text(), "正在输入…")
            A.win.input.clear()
        finally:
            del A.win.isActiveWindow
        # 表情
        A.win.insert_emoji("😀")
        self.assertTrue(A.win.input.toPlainText().endswith("😀"))
        self.assertEqual(A.win.recent_emojis[0], "😀")
        A.win.show_emoji_panel()
        A.win.input.clear()
        # 表情包:收藏 → 重新加载还在 → 发送出去是表情包
        A.win.stickers = StickerStore(tempfile.mkdtemp())
        pic = [m for m in A.images(key_a) if not m.burn][0]
        A.win.add_sticker_from_msg(pic)
        self.assertEqual(len(A.win.stickers.items), 1)
        again = StickerStore(A.win.stickers.folder)
        again.load()
        self.assertEqual(again.items[0]["data"], A.win.stickers.items[0]["data"])
        A.win.send_sticker(A.win.stickers.items[0])
        self.assertTrue(pump_until(self.all, lambda: any(m.sticker for m in B.images(key_b))))
        self.assertEqual(B.conv(key_b).preview, "[表情]")

    def test_04h_fun(self):
        A, B = self.A, self.B
        A.win.effects.width = lambda: 800
        A.win.effects.height = lambda: 600
        A.win.effects.clear()
        before = A.win.pet.count
        for _ in range(12):
            A.win.on_keystroke("char")
        A.win.on_keystroke("delete")
        self.assertEqual(A.win.pet.count, before + 13)
        self.assertTrue(A.win.effects.parts)                  # 打字火花 / 删除碎片
        A.win.set_fun("sparks", False)
        A.win.effects.clear()
        A.win.on_keystroke("char")
        self.assertFalse([q for q in A.win.effects.parts if q.kind != "ember"])   # 火星来自聊天热度,不算
        A.win.set_fun("sparks", True)
        # 发送 → 宠物开心
        A.win.select_conv("lobby")
        A.say("普通的一句话")
        self.assertEqual(A.win.pet.mood(), "happy")
        # 收到关键词 → 全屏特效;12 秒内同一个特效不重复
        A.win.effects.clear()
        B.win.select_conv("lobby")
        B.say("生日快乐!")
        self.assertTrue(pump_until(self.all, lambda: "生日快乐!" in A.texts("lobby")))
        self.assertTrue(any(p.kind == "balloon" for p in A.win.effects.parts))
        A.win.effects.clear()
        B.say("生日快乐呀")
        self.assertTrue(pump_until(self.all, lambda: "生日快乐呀" in A.texts("lobby")))
        self.assertFalse(any(p.kind == "balloon" for p in A.win.effects.parts))
        A.win.set_fun("effects", False)
        B.say("恭喜恭喜")
        self.assertTrue(pump_until(self.all, lambda: "恭喜恭喜" in A.texts("lobby")))
        self.assertFalse(A.win.effects.parts)
        A.win.set_fun("effects", True)
        # 宠物切换 / 关闭
        A.win.set_fun("pet", "bunny")
        self.assertEqual(A.win.pet.species, "bunny")
        A.win.set_fun("pet", None)
        self.assertFalse(A.win.pet.isVisible())
        A.win.set_fun("pet", "cat")
        self.assertTrue(A.win.pet.isVisible())
        A.win._fill_fun_menu()
        # 私聊里对方正在输入 → 底部出现跳动的三个点
        key_a = "dm:" + B.id
        A.win.select_conv(key_a)
        self.assertIsNotNone(A.win.typing_bubble)
        self.assertFalse(A.win.typing_bubble.isVisible())
        B.win.select_conv("dm:" + A.id)
        B.win._typing_sent.clear()
        B.win.input.setPlainText("在打字")
        self.assertTrue(pump_until(self.all, lambda: A.win.typing_bubble is not None and A.win.typing_bubble.isVisible()))
        B.win.input.clear()
        B.say("打完了")
        self.assertTrue(pump_until(self.all, lambda: "打完了" in A.texts(key_a)))
        self.assertFalse(A.win.typing_bubble.isVisible())     # 消息到了,小气泡消失

    def test_05_invisible_and_offline_dm(self):
        A, C = self.A, self.C
        A.win.open_dm(C.id)
        C.win.toggle_lobby(False)
        self.assertTrue(pump_until(self.all, lambda: C.win.me.get("lobby") is False))
        C.win.select_conv("lobby")
        self.assertFalse(C.win.input.isEnabled())
        self.assertIn("隐身", C.win.me_sub.text())
        self.assertTrue(pump_until(self.all, lambda: not A.win.peers[C.id]["online"]))
        self.assertEqual(A.win.current_key, "dm:" + C.id)
        self.assertFalse(A.win.input.isEnabled())
        self.assertIn("对方已离线", A.systems("dm:" + C.id))
        self.assertEqual(A.win.lobby_count(), 2)
        # 重新进大厅
        C.win.toggle_lobby(True)
        self.assertTrue(pump_until(self.all, lambda: A.win.peers[C.id]["online"], timeout=25))
        self.assertIn("对方已上线", A.systems("dm:" + C.id))
        self.assertTrue(A.win.input.isEnabled())

    def test_06_nick_change(self):
        A, B = self.A, self.B
        A.core.set_nick("改名甲")
        self.assertTrue(pump_until(self.all, lambda: B.win.peers[A.id]["nick"] == "改名甲"))
        self.assertEqual(B.conv("dm:" + A.id).title, "改名甲")
        self.assertTrue(pump_until(self.all, lambda: A.win.me_name.text() == "改名甲"))

    def test_07_leave_room(self):
        A, B = self.A, self.B
        key = next(k for k in B.win.convs if k.startswith("room:"))
        B.win.leave_room(B.conv(key))
        self.assertTrue(pump_until(self.all, lambda: key not in B.win.convs))
        self.assertEqual(B.win.current_key in B.win.convs, True)
        self.assertTrue(pump_until(self.all, lambda: any("离开了群" in s for s in A.systems(key))))

    def test_08_panic_and_hide(self):
        A = self.A
        A.win.hotkeys_ok = True
        A.win.input.setPlainText("没发出去的草稿")
        A.win.panic()
        self.assertFalse(A.win.isVisible())
        self.assertFalse(any(k.startswith("dm:") for k in A.win.convs))
        self.assertTrue(all(not c.messages for c in A.win.convs.values() if c.kind != "self"))   # 收藏保留
        self.assertEqual(A.win.input.toPlainText(), "")
        A.win.toggle_hidden()
        self.assertTrue(A.win.isVisible())
        # 隐藏期间收到的阅后即焚不计时
        A.win.hide_window()
        self.B.win.open_dm(A.id)
        self.B.say("隐藏时收到", burn=1)
        self.assertTrue(pump_until(self.all, lambda: "隐藏时收到" in A.texts("dm:" + self.B.id)))
        A.win.select_conv("dm:" + self.B.id)
        time.sleep(1.1)
        A.win._on_tick()
        self.assertIn("隐藏时收到", A.texts("dm:" + self.B.id))
        A.win.show_window()
        time.sleep(1.1)
        A.win._on_tick()
        self.assertNotIn("隐藏时收到", A.texts("dm:" + self.B.id))

    def test_08b_escape_hides(self):
        A, B = self.A, self.B
        A.win.show_window()
        A.win.hotkeys_ok = True
        A.win.start_reply(gui.Msg("要引用的话", nick="某人", sender=B.id))
        A.win.on_escape()                                   # 第一下:只取消引用
        self.assertIsNone(A.win.reply_to)
        self.assertTrue(A.win.isVisible())
        A.win.on_escape()                                   # 第二下:整个软件消失,但没退出
        self.assertFalse(A.win.isVisible())
        self.assertFalse(A.win._force_quit)
        B.win.select_conv("lobby")
        B.say("隐藏期间照常收消息")
        self.assertTrue(pump_until(self.all, lambda: "隐藏期间照常收消息" in A.texts("lobby")))
        A.win.toggle_hidden()                               # Ctrl+Alt+H 叫回
        self.assertTrue(A.win.isVisible())
        A.win.hotkeys_ok = False                            # 热键不可用 → 只最小化
        A.win.on_escape()
        self.assertTrue(A.win.isMinimized())
        A.win.show_window()
        A.win.hotkeys_ok = True

    def test_09_close(self):
        ev = FakeCloseEvent()
        self.C.win.closeEvent(ev)
        self.assertTrue(ev.accepted)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class AccountTests(unittest.TestCase):
    """记住登录、保存聊天记录、注销账户、文件断点续传(界面部分)。"""

    def test_remember_history_logout_and_resume(self):
        import tempfile
        from miyu import crypto as C, storage
        from miyu.stickers import StickerStore
        tmp = tempfile.mkdtemp()
        st_dir = os.path.join(tmp, "stickers")
        store = storage.AccountStore(os.path.join(tmp, "acct"), stickers_folder=st_dir)
        ports = [BASE + 5, BASE + 6]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        A = Harness("小记", ports[0], mk(0), store=store, remember=True, save_history=True)
        B = Harness("小乙", ports[1], mk(1))
        hs = [A, B]
        try:
            self.assertTrue(pump_until(hs, lambda: A.win.lobby_count() == 2 and B.win.lobby_count() == 2))
            A.core.join_room("账户 恢复 暗号 2026", "老地方")
            B.core.join_room("账户 恢复 暗号 2026", "老地方")
            self.assertTrue(pump_until(hs, lambda: any(k.startswith("room:") for k in A.win.convs)
                                       and any(k.startswith("room:") for k in B.win.convs)))
            room = next(k for k in A.win.convs if k.startswith("room:"))
            self.assertTrue(pump_until(hs, lambda: A.win.room_count(room[5:]) == 2))
            A.win.select_conv("lobby")
            A.say("大厅里的话")
            A.win.select_conv(room)
            A.say("群里的话")
            dm = A.win.open_dm(B.id)
            A.say("私聊的话")
            A.say("看完就烧", burn=30)
            self.assertTrue(pump_until(hs, lambda: "看完就烧" in B.texts("dm:" + A.id)))
            A.win.verify_conv(dm)
            A.win.set_muted(A.conv(room), True)
            A.win.set_fun("pet", "bear")
            A.win.setWindowTitle("记事本")
            old_id = A.id
            # 正常退出:账户和记录都保存了
            ev = FakeCloseEvent()
            A.win.closeEvent(ev)
            self.assertTrue(ev.accepted)
            A.core.stop()
            self.assertTrue(os.path.exists(os.path.join(store.folder, storage.ACCOUNT_FILE)))
            from miyu import msgdb
            self.assertTrue(os.path.exists(os.path.join(store.folder, msgdb.DB_FILE)))     # 2.0:加密数据库
            acct = store.load_account()
            self.assertTrue(acct.get("dbkey"))
            self.assertEqual(acct["nick"], "小记")
            self.assertTrue(acct["settings"]["save_history"])
            self.assertEqual(len(acct["rooms"]), 1)
            self.assertNotIn("账户 恢复 暗号 2026", str(acct))        # 只存群密钥,不存暗号本身

            # 重新打开:同一个身份,自动恢复群、记录、设置
            A2 = Harness(acct["nick"], ports[0], mk(0), identity=C.Identity(storage.b64d(acct["seed"])),
                         store=store, account=acct, remember=True, save_history=True)
            hs = [A2, B]
            self.assertEqual(A2.id, old_id)
            self.assertEqual(A2.win.windowTitle(), "记事本")
            self.assertEqual(A2.win.fun["pet"], "bear")
            self.assertIn("大厅里的话", A2.texts("lobby"))
            self.assertEqual(A2.texts("dm:" + B.id), ["私聊的话"])            # 阅后即焚的没有保存
            self.assertTrue(A2.conv("dm:" + B.id).verified)
            self.assertIn("以上是保存的聊天记录", A2.systems("lobby"))
            self.assertTrue(pump_until(hs, lambda: room in A2.win.convs and room[5:] in A2.win.room_keys))
            self.assertEqual(A2.texts(room), ["群里的话"])
            self.assertTrue(A2.conv(room).muted)
            self.assertTrue(pump_until(hs, lambda: A2.win.peers.get(B.id, {}).get("online")
                                       and B.win.peers.get(A2.id, {}).get("online"), timeout=25))
            B.win.select_conv(room)
            B.say("欢迎回来")
            self.assertTrue(pump_until(hs, lambda: "欢迎回来" in A2.texts(room)))

            # ---- 文件:暂停、继续、断网后自动续传,显示速度
            src = os.path.join(tmp, "资料.zip")
            data = os.urandom(24 * 1024 * 1024)
            with open(src, "wb") as f:
                f.write(data)
            B.win.select_conv("dm:" + A2.id) if B.conv("dm:" + A2.id) else B.win.open_dm(A2.id)
            B.win.send_files([src])
            key = "dm:" + B.id
            self.assertTrue(pump_until(hs, lambda: A2.conv(key) and any(m.file for m in A2.conv(key).messages)))
            got = [m for m in A2.conv(key).messages if m.file][-1]
            fid = got.file["fid"]
            dest = os.path.join(tmp, "收到的资料.zip")
            gui.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (dest, ""))
            gui.QStandardPaths.writableLocation = staticmethod(lambda *a: tmp)
            B.core.test_upload_delay = 0.03
            A2.win.on_file_action(got, "download")
            tr = A2.win.transfers[fid]
            self.assertTrue(pump_until(hs, lambda: tr.get("done", 0) > 3 * 1024 * 1024 and tr.get("speed", 0) > 0))
            A2.win.on_file_action(got, "pause")
            self.assertTrue(pump_until(hs, lambda: tr["state"] == "paused"))
            self.assertFalse(tr["auto"])
            self.assertTrue(os.path.exists(dest + ".part"))
            A2.win.on_file_action(got, "resume")
            self.assertEqual(tr["state"], "downloading")
            first = tr["done"]
            self.assertTrue(pump_until(hs, lambda: tr.get("done", 0) > first + 3 * 1024 * 1024))
            conn = A2.core.peers[B.core.my_id].conn
            A2.core.loop.call_soon_threadsafe(conn.close)            # 中途断网
            self.assertTrue(pump_until(hs, lambda: tr["state"] == "paused"))
            self.assertTrue(tr["auto"])
            B.core.test_upload_delay = 0.0

            def tick():
                A2.win._auto_resume(time.monotonic() + 60)            # 不等 8 秒,直接触发自动续传
                return tr["state"] == "done"
            self.assertTrue(pump_until(hs, tick, timeout=40))
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), data)

            # ---- 注销账户:删除所有本机数据(可选表情包),并重新启动
            os.makedirs(st_dir, exist_ok=True)
            with open(os.path.join(st_dir, "x.bin"), "wb") as f:
                f.write(b"sticker")
            A2.win.stickers = StickerStore(st_dir)
            orig_exec = gui.LogoutDialog.exec
            gui.LogoutDialog.exec = lambda self: 1
            gui.LogoutDialog.delete_stickers = property(lambda self: True)
            try:
                A2.win.logout()
            finally:
                gui.LogoutDialog.exec = orig_exec
            self.assertTrue(A2.win.relaunch)
            self.assertFalse(store.has_account())
            self.assertFalse(os.path.exists(os.path.join(store.folder, storage.HISTORY_FILE)))
            self.assertFalse(os.path.exists(os.path.join(store.folder, msgdb.DB_FILE)))
            self.assertFalse(os.path.exists(st_dir))
            ev = FakeCloseEvent()
            A2.win.closeEvent(ev)                                      # 注销后退出不能把账户写回去
            self.assertTrue(ev.accepted)
            self.assertFalse(store.has_account())
            hs.append(A2)
        finally:
            for h in hs:
                h.core.stop()

    def test_not_remembered_writes_nothing(self):
        import tempfile
        from miyu import storage
        tmp = tempfile.mkdtemp()
        store = storage.AccountStore(os.path.join(tmp, "acct"))
        A = Harness("路人", BASE + 8, [], store=store, remember=False)
        try:
            A.say("不会被保存")
            A.win._on_tick()
            ev = FakeCloseEvent()
            A.win.closeEvent(ev)
            self.assertFalse(os.path.exists(store.folder))
            # 中途打开记住登录 → 立即保存;再关掉 → 删除
            A.win.act_remember.setChecked(True)
            A.win.toggle_remember(True)
            self.assertTrue(store.has_account())
            A.win.toggle_remember(False)
            self.assertFalse(store.has_account())
        finally:
            A.core.stop()

    def test_storage_roundtrip(self):
        import tempfile
        from miyu import storage
        tmp = tempfile.mkdtemp()
        store = storage.AccountStore(os.path.join(tmp, "a"))
        self.assertIsNone(store.load_account())
        self.assertTrue(store.save_account({"seed": storage.b64e(os.urandom(32)), "nick": "测试"}))
        self.assertEqual(store.load_account()["nick"], "测试")
        with open(os.path.join(store.folder, storage.ACCOUNT_FILE), "wb") as f:
            f.write(b"garbage")
        self.assertIsNone(store.load_account())                         # 损坏的文件当作没有账户
        m = gui.Msg("烧", burn=10)
        self.assertIsNone(storage.msg_to_dict(m))
        m = gui.Msg("普通", img=b"x" * 10, mime="image/png")
        d = storage.msg_to_dict(m)
        self.assertEqual(storage.msg_kwargs(d)["img"], b"x" * 10)
        self.assertIn("GB", gui.imaging.human_size(3 * 1024 ** 3))
        self.assertEqual(ui.fmt_eta(5), "剩 5 秒")
        self.assertEqual(ui.fmt_eta(3700), "剩 1 小时 1 分")


class PetGrowthTests(unittest.TestCase):
    def test_growth_model(self):
        from miyu import fun
        g = fun.PetGrowth()
        self.assertEqual((g.level, g.name), (1, "团团"))
        self.assertEqual(fun.xp_for_level(2), 300)
        self.assertLess(fun.xp_for_level(10), fun.xp_for_level(11))
        g.toggle("crown")                                   # 没解锁戴不上
        self.assertEqual(g.wear, [])
        self.assertEqual(g.add(299), 0)
        self.assertEqual(g.tap(), 1)                        # 第 300 点经验升到 2 级
        self.assertEqual(g.level, 2)
        self.assertEqual(g.unlocked_at(2)[0][0], "bow")
        g.xp = fun.xp_for_level(12)
        g.toggle("bow")
        g.toggle("flower")                                  # 同一部位:换掉蝴蝶结
        self.assertEqual(g.wear, ["flower"])
        g.toggle("crown")
        g.toggle("glasses")
        g.toggle("headphones")                              # 头部:换掉皇冠
        self.assertEqual(sorted(g.wear), ["flower", "glasses", "headphones"])
        g.toggle("glasses")                                 # 再点一次摘下
        self.assertNotIn("glasses", g.wear)
        self.assertLess(fun.PetGrowth().size(), g.size())
        self.assertEqual(g.size(), 1.0)
        g2 = fun.PetGrowth(g.to_dict())
        self.assertEqual((g2.level, g2.wear, g2.taps), (g.level, g.wear, g.taps))
        bad = fun.PetGrowth({"xp": "x", "wear": ["nope", 3], "name": ""})
        self.assertEqual((bad.xp, bad.wear, bad.name), (0, [], "团团"))
        g3 = fun.PetGrowth({"xp": 999999999})
        self.assertEqual(g3.level, fun.PET_MAX_LEVEL)
        self.assertEqual(g3.progress()[2], 1.0)

    def test_tricks_and_outfits(self):
        """2.5:每 5 级学一个新动作;套装一键穿上已解锁的部件;40 级神话期。"""
        from miyu import fun
        g = fun.PetGrowth({"xp": fun.xp_for_level(12)})
        self.assertEqual([t[1] for t in g.tricks()], ["stretch", "spin"])
        self.assertEqual(len(fun.PetGrowth({"xp": fun.xp_for_level(fun.PET_MAX_LEVEL)}).tricks()), len(fun.TRICKS))
        self.assertTrue(fun.PetGrowth({"xp": fun.xp_for_level(40)}).mythic)
        self.assertFalse(fun.PetGrowth({"xp": fun.xp_for_level(39)}).mythic)
        for need, tid, name, dur in fun.TRICKS:
            self.assertEqual(need % 5, 0)
            self.assertIs(fun.TRICK_BY_ID[tid][2], name)
        for oid, name, parts, _col in fun.OUTFITS:              # 套装部件都存在,而且各占一个部位
            self.assertEqual(len({fun.ACC_BY_ID[x][3] for x in parts}), len(parts), oid)
        big = fun.PetGrowth({"xp": fun.xp_for_level(50)})
        oid, _n, parts, _c = fun.OUTFITS[0]
        for x in parts:
            big.owned.add(x)                                  # 抽卡才有的部件当作已经抽到
        self.assertEqual(big.wear_outfit(oid), [])
        self.assertEqual(big.full_outfit()[0], oid)
        small = fun.PetGrowth({"xp": fun.xp_for_level(2)})
        self.assertTrue(small.wear_outfit(oid))               # 还没解锁的部件会列出来
        self.assertIsNone(small.full_outfit())
        self.assertEqual(fun.PetGrowth({"xp": 10 ** 12}).level, fun.PET_MAX_LEVEL)

    def test_level_card_from_others(self):
        """别人升级:群里出现他的升级卡片;乱填的数据被丢掉,同一个人 20 秒内只显示一次。"""
        from miyu import fun
        from PySide6.QtCore import QPoint
        A = Harness("看热闹的人", BASE + 10, [])
        try:
            conv = A.conv("lobby")
            ok = {"lv": 12, "name": "豆豆", "sp": "bunny", "wear": ["bow", "不存在的装扮"], "form": "成长期"}
            A.win._ev_pet_lv(conv, {"peer": "p-x", "nick": "小明"}, ok)
            A.win._ev_pet_lv(conv, {"peer": "p-x", "nick": "小明"}, dict(ok, lv=13))       # 刷屏:不显示
            A.win._ev_pet_lv(conv, {"peer": "p-y", "nick": "小红"}, dict(ok, lv=999))      # 等级不对:丢掉
            A.win._ev_pet_lv(conv, {"peer": "p-z", "nick": "小蓝"}, dict(ok, sp="dragon", lv="9"))
            cards = [x for x in conv.messages if x.card and x.card.get("type") == "petlv"]
            self.assertEqual(len(cards), 1)
            c = cards[0]
            self.assertEqual((c.card["lv"], c.card["sp"], c.card["wear"], c.mine), (12, "bunny", ["bow"], False))
            self.assertIn("小明", c.text)
            # 右键宠物:表演菜单里学会的能点,没学会的灰着
            A.win.pet_growth.xp = fun.xp_for_level(11)
            A.win.pet_menu(QPoint(0, 0))
        finally:
            A.core.stop()

    def test_level_up_in_window(self):
        A = Harness("养猫的人", BASE + 9, [])
        try:
            g = A.win.pet_growth
            g.xp = 299
            A.win.on_keystroke("char")
            self.assertEqual(g.level, 2)
            self.assertIn("bow", g.wear)                    # 新装扮自动穿上
            # 2.5:在群里看得见窗口时放升级仪式(解锁卡写着学会了什么),群里留一张升级卡片
            ov = A.win.levelup_overlay
            self.assertEqual(ov.level, 2)
            self.assertTrue(any("蝴蝶结" in t for _i, t in ov.lines))
            self.assertTrue(any("抽卡券" in t for _i, t in ov.lines))
            cards = [x for x in A.conv("lobby").messages if x.card and x.card.get("type") == "petlv"]
            self.assertEqual((len(cards), cards[-1].card["lv"], cards[-1].mine), (1, 2, True))
            self.assertIn("bow", cards[-1].card["wear"])
            self.assertEqual(A.win.pet._levelup_lv, 2)
            before, nb = g.xp, len(g.badges)
            A.say("发一条消息")
            self.assertEqual(g.xp, before + 12 + 50 + 30 * (len(g.badges) - nb))  # 第一条消息 +12,打卡 +50,新称号每个 +30
            self.assertTrue(any("今日打卡" in t for t in A.systems("lobby")))
            self.assertEqual(g.messages, 1)
            before, nb = g.xp, len(g.badges)
            A.say("第二条")
            self.assertEqual(g.xp, before + 12 + 30 * (len(g.badges) - nb))
            A.win._fill_fun_menu()
            labels = [a.text() for a in A.win.fun_menu.actions()]
            self.assertTrue(any("团团 · Lv.2" in t for t in labels))
            gui.prompt = lambda *a, **k: "咪咪"
            A.win.rename_pet()
            self.assertEqual(g.name, "咪咪")
            A.win.toggle_wear("bow")
            self.assertNotIn("bow", g.wear)
            self.assertEqual(A.win.account_dict()["pet"]["name"], "咪咪")
        finally:
            A.core.stop()


class HeatSearchTests(unittest.TestCase):
    def test_heat_and_search(self):
        A = Harness("搜一搜", BASE + 7, [])
        try:
            conv = A.conv("lobby")
            self.assertEqual(A.win.chat_panel.heat, 0.0)
            for i in range(6):
                A.win.bump_heat(conv, gui.HEAT_IN)
            h = A.win.heat_of(conv)
            self.assertAlmostEqual(h, 0.9, places=2)
            self.assertAlmostEqual(A.win.chat_panel.heat, h, places=2)
            # 25 秒半衰
            self.assertAlmostEqual(A.win.heat_of(conv, time.monotonic() + gui.HEAT_HALF_LIFE), h / 2, places=2)
            conv.heat_t -= 400                                      # 很久没说话 → 冷却
            A.win._heat_step()
            self.assertEqual(A.win.chat_panel.heat, 0.0)
            A.win.set_fun("heat", False)
            A.win.bump_heat(conv, 1.0)
            self.assertEqual(A.win.chat_panel.heat, 0.0)            # 关掉后不显示
            A.win.set_fun("heat", True)
            A.win.on_keystroke("char")
            self.assertGreater(A.win.chat_panel.heat, 0.5)

            # ---- 搜索
            for t in ["今天去吃火锅", "明天上班", "火锅店在哪", "<b>火锅</b> & 啤酒", "随便聊聊"]:
                A.say(t)
            A.win.open_search()
            self.assertTrue(A.win.search_bar.isVisible())
            A.win.search_edit.setText("火锅")
            A.win._on_search_text("火锅")
            self.assertEqual(len(A.win.search_hits), 3)
            self.assertEqual(A.win.search_count.text(), "3/3")      # 从最新的一条开始
            cur = A.win.search_hits[A.win.search_idx]
            b = A.win.bubbles[cur]
            self.assertTrue(b.property("searchHit"))
            html_text = b.body.text()
            self.assertIn("&lt;b&gt;", html_text)                   # 原文里的 HTML 被转义,不会被执行
            self.assertIn(ui.HIT_BG, html_text)
            A.win.search_step(-1)
            self.assertEqual(A.win.search_count.text(), "2/3")
            self.assertFalse(b.property("searchHit"))
            A.win.search_step(1)
            A.win.search_step(1)                                    # 循环
            self.assertEqual(A.win.search_count.text(), "1/3")
            A.say("火锅又来了")                                      # 搜索中来新消息:计数更新
            self.assertEqual(A.win.search_count.text(), "1/4")
            A.win._on_search_text("不存在的词")
            self.assertEqual(A.win.search_count.text(), "无结果")
            A.win._on_search_text("火锅")
            # ESC:先关搜索,不隐藏窗口
            A.win.hotkeys_ok = True
            A.win.on_escape()
            self.assertFalse(A.win.search_bar.isVisible())
            self.assertTrue(A.win.isVisible())
            self.assertIn("<b>", b.body.text())                     # 关掉后恢复成纯文本
            # 很早的消息(超出渲染范围)也能跳过去
            from miyu.window import records
            for i in range(records.WIN_MAX + 5):
                A.win._add_message(conv, gui.Msg(f"填充 {i}", mid=f"f{i}", sender="x", nick="x", tag="x"),
                                   count_unread=False)
            A.win._render_messages()
            self.assertNotIn(A.win.search_hits[0] if A.win.search_hits else "nope", A.win.bubbles)
            A.win.open_search()
            A.win.search_edit.setText("今天去吃")
            A.win._on_search_text("今天去吃")
            self.assertEqual(len(A.win.search_hits), 1)
            self.assertIn(A.win.search_hits[0], A.win.bubbles)
            A.win.select_conv(A.win.open_dm("ab" * 16).key)        # 切换会话自动关闭搜索
            self.assertFalse(A.win.search_bar.isVisible())
            self.assertTrue(A.win._win_bottom)
        finally:
            A.core.stop()

    def test_highlight_html(self):
        out = ui.highlight_html("Hello hello <x>\n第二行", "hello")
        self.assertEqual(out.count(ui.HIT_BG), 2)
        self.assertIn("&lt;x&gt;", out)
        self.assertIn("<br>", out)


class StartupTests(unittest.TestCase):
    """完整走一遍 app.main() 的启动流程:第一次打开(起昵称)和记住登录后的自动进入。"""

    def test_app_main_first_run_and_auto_login(self):
        import tempfile
        from miyu import app, storage
        tmp = tempfile.mkdtemp()
        orig = storage.default_dir
        storage.default_dir = lambda: os.path.join(tmp, "MiYu")
        created = []
        orig_init = gui.MainWindow.__init__

        def spy(self, *a, **k):
            orig_init(self, *a, **k)
            created.append(self)
        gui.MainWindow.__init__ = spy
        try:
            port = str(BASE + 4)
            self.assertEqual(app.main(["--udp-port", port, "--tcp-port", "0"]), 0)        # 第一次:起昵称窗口
            win = created[-1]
            self.assertTrue(win.remember)
            self.assertTrue(win.save_account(force=True))
            win.core.stop()
            self.assertTrue(storage.AccountStore().has_account())
            self.assertEqual(app.main(["--udp-port", port, "--tcp-port", "0"]), 0)        # 第二次:自动登录
            win2 = created[-1]
            self.assertEqual(win2.core.identity.pub, win.core.identity.pub)
            win2.core.stop()
        finally:
            gui.MainWindow.__init__ = orig_init
            storage.default_dir = orig


class NewFeatureTests(unittest.TestCase):
    """第三批功能:编辑、文件夹、投送、戳一戳、公告置顶、投票抽签骰子、匿名纸条、小游戏、一起画、宠物串门、皮肤、背景、年报。"""

    @classmethod
    def setUpClass(cls):
        ports = [BASE + 20, BASE + 21, BASE + 22]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.A = Harness("小甲", ports[0], mk(0))
        cls.B = Harness("小乙", ports[1], mk(1))
        cls.C = Harness("小丙", ports[2], mk(2))
        cls.all = [cls.A, cls.B, cls.C]
        assert pump_until(cls.all, lambda: all(h.win.lobby_count() == 3 for h in cls.all), timeout=25)

    @classmethod
    def tearDownClass(cls):
        for h in cls.all:
            h.core.stop()

    def dm(self, a, b):
        return a.win.open_dm(b.id, select=True)

    def test_01_edit(self):
        A, B = self.A, self.B
        self.dm(A, B)
        A.say("原来的话")
        key_b = "dm:" + A.id
        self.assertTrue(pump_until(self.all, lambda: "原来的话" in B.texts(key_b)))
        m = [x for x in A.conv("dm:" + B.id).messages if x.text == "原来的话"][0]
        A.win.start_edit(m)
        self.assertEqual(A.win.input.toPlainText(), "原来的话")
        A.win.input.setPlainText("改过的话")
        A.win.send_current()
        self.assertIsNone(A.win.editing)
        self.assertTrue(m.edited)
        self.assertTrue(pump_until(self.all, lambda: "改过的话" in B.texts(key_b)))
        got = [x for x in B.conv(key_b).messages if x.text == "改过的话"][0]
        self.assertTrue(got.edited)
        # 别人冒充改我的消息:不生效
        B.core.send_event("dm", A.id, "edit", {"target": m.mid, "text": "被篡改"})
        time.sleep(0.6)
        pump_until(self.all, lambda: False, timeout=0.5)
        self.assertEqual(m.text, "改过的话")
        # ESC 取消编辑
        A.win.start_edit(m)
        A.win.on_escape()
        self.assertIsNone(A.win.editing)
        self.assertEqual(A.win.input.toPlainText(), "")

    def test_02_folder_and_drop(self):
        import tempfile
        from miyu.window import files as features
        A, B = self.A, self.B
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "项目资料")
        os.makedirs(os.path.join(src, "子目录", "空的"))
        files = {"说明.txt": b"hello", os.path.join("子目录", "数据.bin"): os.urandom(300 * 1024)}
        for rel, data in files.items():
            with open(os.path.join(src, rel), "wb") as f:
                f.write(data)
        A.win.store = None
        conv = self.dm(A, B)
        A.win.send_folder(src)
        self.assertTrue(pump_until(self.all, lambda: any(x.file and x.file.get("dir") for x in conv.messages)))
        key_b = "dm:" + A.id
        self.assertTrue(pump_until(self.all, lambda: any(x.file and x.file.get("dir") for x in B.conv(key_b).messages)))
        got = [x for x in B.conv(key_b).messages if x.file and x.file.get("dir")][-1]
        dest_dir = os.path.join(tmp, "收件")
        os.makedirs(dest_dir)
        gui.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: dest_dir)
        gui.QStandardPaths.writableLocation = staticmethod(lambda *a: tmp)
        B.win.on_file_action(got, "download")
        tr = B.win.transfers[got.file["fid"]]
        self.assertTrue(pump_until(self.all, lambda: tr.get("folder"), timeout=30))
        out = tr["path"]
        self.assertEqual(os.path.basename(out), "项目资料")
        for rel, data in files.items():
            with open(os.path.join(out, rel), "rb") as f:
                self.assertEqual(f.read(), data)
        self.assertTrue(os.path.isdir(os.path.join(out, "子目录", "空的")))
        self.assertFalse(os.path.exists(os.path.join(dest_dir, "项目资料.zip")))     # zip 解压后删掉了
        # 恶意压缩包:路径跳出目标文件夹 → 拒绝
        import zipfile
        bad = os.path.join(tmp, "bad.zip")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../../逃出去.txt", b"x")
        with self.assertRaises(ValueError):
            features.safe_extract(bad, os.path.join(tmp, "bad_out"))
        # 投送:把文件拖到会话列表里 C 的私聊上
        f1 = os.path.join(tmp, "投送.txt")
        with open(f1, "wb") as f:
            f.write(b"drop")
        c_conv = A.win.open_dm(self.C.id, select=False)
        A.win.drop_on_conv(c_conv, [f1])
        self.assertTrue(pump_until(self.all, lambda: any(x.file and x.file["name"] == "投送.txt"
                                                         for x in self.C.conv("dm:" + A.id).messages)
                                   if self.C.conv("dm:" + A.id) else False))

    def test_03_poke(self):
        A, B, C = self.A, self.B, self.C
        A.win._poke_sent = 0
        A.win.poke(B.id)
        key_b = "dm:" + A.id
        self.assertTrue(pump_until(self.all, lambda: any("戳了戳你" in t for t in B.systems(key_b))))
        n = sum("戳了戳你" in t for t in B.systems(key_b))
        A.win._poke_sent = 0
        A.win.poke(B.id)                                    # 3 秒内再戳:对方那边只算一次
        pump_until(self.all, lambda: False, timeout=0.8)
        self.assertEqual(sum("戳了戳你" in t for t in B.systems(key_b)), n)
        # 群里戳:旁观的人看到"甲 戳了戳 乙"
        A.win._poke_sent = 0
        C.win._poke_last.clear()
        A.win.poke(B.id, A.conv("lobby"))
        self.assertTrue(pump_until(self.all, lambda: any("小甲 戳了戳 小乙" in t for t in C.systems("lobby"))))

    def test_04_notice_pins(self):
        A, B, C = self.A, self.B, self.C
        A.win.select_conv("lobby")
        orig = (dialogs.MultiPromptDialog.exec, dialogs.MultiPromptDialog.value)
        dialogs.MultiPromptDialog.exec = lambda self: 1
        dialogs.MultiPromptDialog.value = property(lambda self: "周五晚上八点开黑")
        try:
            A.win.edit_notice()
        finally:
            dialogs.MultiPromptDialog.exec, dialogs.MultiPromptDialog.value = orig
        self.assertTrue(A.win.notice_bar.isVisible())
        self.assertTrue(pump_until(self.all, lambda: (B.conv("lobby").notice or {}).get("text") == "周五晚上八点开黑"))
        self.assertTrue(any("更新了群公告" in t for t in B.systems("lobby")))
        A.say("这条要置顶")
        m = [x for x in A.conv("lobby").messages if x.text == "这条要置顶"][0]
        A.win.toggle_pin(m)
        self.assertTrue(pump_until(self.all, lambda: any(p["mid"] == m.mid for p in B.conv("lobby").pins)))
        # 新来的人:同步公告和置顶(不刷屏)
        C.conv("lobby").notice, C.conv("lobby").notice_t = None, 0.0
        C.conv("lobby").pins, C.conv("lobby").pins_t = [], 0.0
        before = len(C.systems("lobby"))
        A.win.sync_group_to(A.conv("lobby"), C.id)
        self.assertTrue(pump_until(self.all, lambda: C.conv("lobby").notice and C.conv("lobby").pins))
        self.assertEqual(len(C.systems("lobby")), before)
        # 旧的公告不能覆盖新的
        B.core.send_event("lobby", None, "notice", {"text": "过期的", "time": 1.0})
        pump_until(self.all, lambda: False, timeout=0.6)
        self.assertEqual(A.conv("lobby").notice["text"], "周五晚上八点开黑")
        A.win.toggle_pin(m)
        self.assertTrue(pump_until(self.all, lambda: not B.conv("lobby").pins))

    def test_05_poll_lottery_dice(self):
        A, B, C = self.A, self.B, self.C
        A.win.select_conv("lobby")
        orig = (games.PollDialog.exec, games.PollDialog.card)
        games.PollDialog.exec = lambda self: 1
        games.PollDialog.card = lambda self: {"type": "poll", "q": "吃什么", "opts": ["火锅", "烧烤", "日料"],
                                                   "multi": False}
        try:
            A.win.start_poll()
        finally:
            games.PollDialog.exec, games.PollDialog.card = orig
        poll = [x for x in A.conv("lobby").messages if x.card and x.card.get("type") == "poll"][-1]
        self.assertTrue(pump_until(self.all, lambda: any(x.mid == poll.mid for x in B.conv("lobby").messages)))
        bpoll = [x for x in B.conv("lobby").messages if x.mid == poll.mid][0]
        B.win.vote(bpoll, 0)
        C.win.vote([x for x in C.conv("lobby").messages if x.mid == poll.mid][0], 0) if pump_until(
            self.all, lambda: any(x.mid == poll.mid for x in C.conv("lobby").messages)) else None
        A.win.vote(poll, 2)
        self.assertTrue(pump_until(self.all, lambda: A.win.poll_state(poll)["counts"] == [2, 0, 1]))
        self.assertTrue(pump_until(self.all, lambda: B.win.poll_state(bpoll)["counts"] == [2, 0, 1]))
        B.win.vote(bpoll, 1)                                 # 单选:改投
        self.assertTrue(pump_until(self.all, lambda: A.win.poll_state(poll)["counts"] == [1, 1, 1]))
        self.assertEqual(A.win.poll_state(poll)["voters"], 3)
        # 抽签
        orig = (games.LotteryDialog.exec, games.LotteryDialog.chosen)
        games.LotteryDialog.exec = lambda self: 1
        games.LotteryDialog.chosen = lambda self: self.members
        try:
            A.win.start_lottery()
        finally:
            games.LotteryDialog.exec, games.LotteryDialog.chosen = orig
        lot = [x for x in A.conv("lobby").messages if x.card and x.card.get("type") == "draw"][-1]
        self.assertIn(lot.card["win"], {A.id, B.id, C.id})
        self.assertTrue(pump_until(self.all, lambda: any(x.mid == lot.mid for x in B.conv("lobby").messages)))
        # 骰子
        A.win.roll_dice()
        dice = [x for x in A.conv("lobby").messages if x.card and x.card.get("type") == "dice"][-1]
        self.assertIn(dice.card["v"], range(1, 7))
        self.assertTrue(pump_until(self.all, lambda: any(x.mid == dice.mid for x in C.conv("lobby").messages)))

    def test_06_anon(self):
        A, B, C = self.A, self.B, self.C
        A.win.select_conv("lobby")
        from miyu.window import anon
        orig = (anon.AnonNoteDialog.exec, anon.AnonNoteDialog.text)
        anon.AnonNoteDialog.exec = lambda self: 1
        anon.AnonNoteDialog.text = property(lambda self: "其实我很喜欢这个群")
        try:
            A.win.send_anon_note()
        finally:
            anon.AnonNoteDialog.exec, anon.AnonNoteDialog.text = orig
        mine = [x for x in A.conv("lobby").messages if x.anon]
        self.assertTrue(mine and mine[-1].mine)
        for h in (B, C):
            self.assertTrue(pump_until(self.all, lambda h=h: any(x.anon and x.text == "其实我很喜欢这个群"
                                                                 for x in h.conv("lobby").messages)))
            got = [x for x in h.conv("lobby").messages if x.anon][-1]
            self.assertEqual(got.sender, "")
            self.assertEqual(got.nick, "匿名纸条")
        pump_until(self.all, lambda: False, timeout=0.5)
        self.assertEqual(len([x for x in A.conv("lobby").messages if x.anon]), 1)   # 作者那边不重复

    def test_06a_anon_paste(self):
        """2.5:匿名纸条里粘贴 / 拖进来的截图、图片文件、视频文件直接变成附件,不用去文件夹里找。"""
        import tempfile
        from miyu.window import anon

        class Url:
            def __init__(self, p): self.p = p
            def isLocalFile(self): return True
            def toLocalFile(self): return self.p

        class Mime:
            def __init__(self, paths=(), image=None, text=""):
                self.paths, self.image, self._text = list(paths), image, text
            def hasUrls(self): return bool(self.paths)
            def urls(self): return [Url(p) for p in self.paths]
            def hasImage(self): return self.image is not None
            def imageData(self): return self.image
            def hasText(self): return bool(self._text)
            def text(self): return self._text

        dlg = anon.AnonNoteDialog(self.A.win)
        tmp = tempfile.mkdtemp()
        gif_path = os.path.join(tmp, "斗图.gif")
        with open(gif_path, "wb") as f:
            f.write(make_gif(frames=3))
        doc = os.path.join(tmp, "说明.txt")
        open(doc, "w").close()
        # 复制的图片文件(动图保持会动)
        m = Mime([doc, gif_path])
        self.assertTrue(anon.mime_has_media(m))
        self.assertTrue(dlg.use_mime(m))
        self.assertEqual(dlg.media["k"], "img")
        self.assertEqual(dlg.media["mime"], "image/gif")
        # 复制的视频文件走视频那条路(会去掉拍摄位置等信息)
        vid = os.path.join(tmp, "clip.MP4")
        open(vid, "wb").close()
        seen = []
        dlg.use_video_path = lambda p: seen.append(p) or True
        self.assertTrue(dlg.use_mime(Mime([vid])))
        self.assertEqual(seen, [vid])
        # 截图(剪贴板里只有图片,没有文件)
        from PySide6.QtGui import QImage
        shot = QImage()
        got = []
        dlg.use_image_item = lambda it, title="": got.append((it, title)) or True
        self.assertTrue(dlg.use_mime(Mime(image=shot)))
        self.assertEqual(got, [(shot, "粘贴的图片")])
        # 纯文字 / 别的文件不当附件
        self.assertFalse(anon.mime_has_media(Mime(text="你好")))
        self.assertFalse(anon.mime_has_media(Mime([doc])))

    def test_06b_anon_media(self):
        """2.1:匿名纸条夹动图 / 表情包 / 视频,内容跟着纸条转交,收到的人看到的是同样的东西。"""
        import struct
        from miyu import video
        A, B, C = self.A, self.B, self.C
        A.win.select_conv("lobby")
        conv = A.conv("lobby")
        for h in (B, C):                                    # 在场信息里带了新能力
            self.assertTrue(pump_until(self.all, lambda h=h: all("am" in p.caps for p in h.core.peers.values()
                                                                  if p.online)))
        gif = make_gif(frames=3)
        nid = A.win.send_anon_to(conv, "", {"k": "img", "data": gif, "mime": "image/gif", "w": 40, "h": 30})
        self.assertTrue(nid)
        mine = next(x for x in conv.messages if x.mid == nid)
        self.assertEqual((mine.img, mine.mime, mine.text), (gif, "image/gif", ""))
        for h in (B, C):
            self.assertTrue(pump_until(self.all, lambda h=h: any(x.mid == nid for x in h.conv("lobby").messages)))
            got = next(x for x in h.conv("lobby").messages if x.mid == nid)
            self.assertTrue(got.anon)
            self.assertEqual(got.sender, "")
            self.assertEqual((got.img, got.mime), (gif, "image/gif"))
            self.assertEqual(got.text, "")
        # 文字 + 表情包
        nid2 = A.win.send_anon_to(conv, "送你们一个表情", {"k": "stk", "data": gif, "mime": "image/gif"})
        self.assertTrue(pump_until(self.all, lambda: any(x.mid == nid2 and x.sticker and x.text == "送你们一个表情"
                                                         for x in B.conv("lobby").messages)))
        # 视频:内容带在纸条里,收到的人直接能放
        def box(t, body):
            return struct.pack(">I", 8 + len(body)) + t + body
        mp4 = box(b"ftyp", b"isom\x00\x00\x02\x00isom") + box(b"moov", box(b"udta", b"GPS+25.03")) + box(b"mdat", b"v" * 3000)
        clean = video.scrub_mp4(mp4)
        self.assertNotIn(b"GPS", clean)
        nid3 = A.win.send_anon_to(conv, "看这个", {"k": "vid", "data": clean, "name": "猫.mp4", "thumb": None,
                                                    "dur": 4200, "w": 640, "h": 360})
        self.assertTrue(nid3)
        self.assertEqual(next(x for x in conv.messages if x.mid == nid3).vid, clean)
        self.assertTrue(pump_until(self.all, lambda: any(x.mid == nid3 for x in C.conv("lobby").messages)))
        got = next(x for x in C.conv("lobby").messages if x.mid == nid3)
        self.assertEqual(got.vid, clean)
        self.assertEqual(got.file["name"], "猫.mp4")
        self.assertEqual(got.file["dur"], 4200)
        from miyu.widgets import VideoCard
        if nid3 in C.win.bubbles:
            card = C.win.bubbles[nid3].card
            self.assertIsInstance(card, VideoCard)
            self.assertEqual(card._poster_act, "play")
        self.assertEqual(C.win._body_of(got), "[视频]")
        # 别人还是旧版本(没有新能力):带附件的纸条发不出去,给出原因
        saved = {p.id: set(p.caps) for p in A.core.peers.values()}
        try:
            for p in A.core.peers.values():
                p.caps = set()
            self.assertIsNone(A.core.send_anon("lobby", None, "", {"k": "img", "data": gif, "mime": "image/gif"}))
            self.assertEqual(A.core.anon_error, "old")
            self.assertTrue(A.core.send_anon("lobby", None, "纯文字照样能发"))
        finally:
            for p in A.core.peers.values():
                p.caps = saved.get(p.id, set())
        # 格式不对的附件
        self.assertIsNone(A.core.send_anon("lobby", None, "", {"k": "vid", "data": b"not a video" * 10}))
        self.assertIsNone(A.core.send_anon("lobby", None, "", {"k": "img", "data": b"xx", "mime": "image/png"}))

    def test_07_gomoku(self):
        A, B = self.A, self.B
        self.dm(A, B)
        A.win.start_game("gomoku")
        card = [x for x in A.conv("dm:" + B.id).messages if x.card and x.card.get("game") == "gomoku"][-1]
        key_b = "dm:" + A.id
        self.assertTrue(pump_until(self.all, lambda: any(x.mid == card.mid for x in B.conv(key_b).messages)))
        bcard = [x for x in B.conv(key_b).messages if x.mid == card.mid][0]
        self.assertTrue(A.win.game_state(card)["my_turn"])          # 发起的人执黑先走
        self.assertFalse(B.win.game_state(bcard)["my_turn"])
        B.win.game_action(bcard, "move", (0, 0))                     # 没轮到:无效
        self.assertEqual(B.win.game_state(bcard)["moves"], [])
        for i in range(5):
            A.win.game_action(card, "move", (7 + i, 7))
            self.assertTrue(pump_until(self.all, lambda i=i: len(B.win.game_state(bcard)["moves"]) == 2 * i + 1))
            if i < 4:
                B.win.game_action(bcard, "move", (7 + i, 9))
                self.assertTrue(pump_until(self.all, lambda i=i: len(A.win.game_state(card)["moves"]) == 2 * i + 2))
        self.assertEqual(A.win.game_state(card)["over"], "win")
        self.assertEqual(B.win.game_state(bcard)["over"], "lose")
        self.assertEqual(len(A.win.game_state(card)["line"]), 5)

    def test_08_rps(self):
        A, B = self.A, self.B
        self.dm(A, B)
        A.win.start_game("rps")
        card = [x for x in A.conv("dm:" + B.id).messages if x.card and x.card.get("game") == "rps"][-1]
        key_b = "dm:" + A.id
        self.assertTrue(pump_until(self.all, lambda: any(x.mid == card.mid for x in B.conv(key_b).messages)))
        bcard = [x for x in B.conv(key_b).messages if x.mid == card.mid][0]
        A.win.game_action(card, "pick", "rock")
        self.assertTrue(pump_until(self.all, lambda: B.win.game_state(bcard)["their_ready"]))
        self.assertIsNone(B.win.game_state(bcard)["theirs"])         # 只知道对方出了,不知道出的什么
        B.win.game_action(bcard, "pick", "scissors")
        self.assertTrue(pump_until(self.all, lambda: A.win.game_state(card)["result"] == "win"
                                   and B.win.game_state(bcard)["result"] == "lose"))
        # 篡改揭晓:和承诺对不上的不算
        g = {"game": "rps", "their_h": "0" * 64}
        self.assertNotEqual(cards.rps_hash("x", "rock", "n"), g["their_h"])

    def test_09_board(self):
        A, B, C = self.A, self.B, self.C
        A.win.select_conv("lobby")
        A.win.start_board()
        card = [x for x in A.conv("lobby").messages if x.card and x.card.get("type") == "board"][-1]
        bid = card.card["bid"]
        wb = A.win.whiteboards[bid]
        wb.canvas.strokes["s1"] = {"c": "#FF453A", "w": 7.0, "pts": [10, 10, 50, 60, 90, 80], "by": "me", "open": False}
        wb._on_points("s1", [10, 10, 50, 60, 90, 80], True)
        self.assertTrue(pump_until(self.all, lambda: B.win.boards.get(bid) and len(B.win.boards[bid]["strokes"]) == 1))
        st = list(B.win.boards[bid]["strokes"].values())[0]
        self.assertEqual((st["c"], st["pts"]), ("#FF453A", [10, 10, 50, 60, 90, 80]))
        # 后来的人打开画板:向大家要已有的笔画
        C.win.boards.pop(bid, None)
        ccard = [x for x in C.conv("lobby").messages if x.mid == card.mid] if pump_until(
            self.all, lambda: any(x.mid == card.mid for x in C.conv("lobby").messages)) else []
        C.win.open_board(ccard[0])
        self.assertTrue(pump_until(self.all, lambda: len(C.win.boards[bid]["strokes"]) >= 1))
        # 撤销:只能撤自己的
        wb.undo_mine()
        self.assertTrue(pump_until(self.all, lambda: len(B.win.boards[bid]["strokes"]) == 0))
        # 笔迹数据不合法:丢弃
        self.assertIsNone(games.clean_stroke({"pts": [1, 2, 3], "c": "#000000", "w": 3}))
        self.assertIsNone(games.clean_stroke({"pts": [1, 2], "c": "red;", "w": 3}))

    def test_10_pet_visit_and_pat(self):
        A, B = self.A, self.B
        self.dm(A, B)
        A.win.send_pet_visit(B.id)
        self.assertTrue(A.win.pet_away)
        self.assertTrue(A.win.pet.away)
        self.assertTrue(pump_until(self.all, lambda: B.win.visitor is not None))
        self.assertIn(A.win.pet_growth.name, B.win.visitor.label)
        B.win.on_keystroke("char")                                   # 客人也跟着拍
        self.assertEqual(B.win.visit["taps"], 1)
        xp, nb = A.win.pet_growth.xp, len(A.win.pet_growth.badges)
        B.win._end_visit()
        self.assertIsNone(B.win.visitor)
        self.assertTrue(pump_until(self.all, lambda: not A.win.pet_away))
        self.assertEqual(A.win.pet_growth.xp, xp + 30 + 30 * (len(A.win.pet_growth.badges) - nb))
        self.assertIn("visit1", A.win.pet_growth.badges)                 # 称号「串门新手」
        self.assertEqual(A.win.pet_growth.friends[B.id]["v"], 10)        # 友谊值 +10
        self.assertEqual(B.win.pet_growth.friends[A.id]["v"], 10)
        self.assertTrue(any("回来了" in t for t in A.systems("dm:" + B.id)))
        # 不接待客人
        B.win.allow_visits = False
        A.win.send_pet_visit(B.id)
        self.assertTrue(pump_until(self.all, lambda: not A.win.pet_away))
        self.assertTrue(any("没去成" in t for t in A.systems("dm:" + B.id)))
        B.win.allow_visits = True
        # 撸宠物:加经验(+5);连点 6 下会被嫌弃
        xp, nb = A.win.pet_growth.xp, len(A.win.pet_growth.badges)
        A.win.pat_pet()
        self.assertEqual(A.win.pet_growth.xp, xp + 5 + 30 * (len(A.win.pet_growth.badges) - nb))
        A.win.pet._pats = []
        kinds = [A.win.pet.pat() for _ in range(6)]
        self.assertEqual(kinds[-1], "annoyed")

    def test_11_skin_time_report(self):
        from miyu import theme as th
        A, B = self.A, self.B
        A.win.set_skin("jelly")
        A.win.pet_growth.xp = 0
        self.assertIsNone(A.win.current_skin())                      # 等级不够用不了
        A.win.pet_growth.xp = 2000
        self.assertEqual(A.win.current_skin(), "jelly")
        self.dm(A, B)
        A.say("果冻气泡")
        key_b = "dm:" + A.id
        self.assertTrue(pump_until(self.all, lambda: any(x.text == "果冻气泡" and x.skin == "jelly"
                                                         for x in B.conv(key_b).messages)))
        B.win.select_conv(key_b)
        m = [x for x in B.conv(key_b).messages if x.text == "果冻气泡"][0]
        self.assertEqual(B.win.bubbles[m.mid].body.objectName(), "skin_jelly")
        A.win.set_skin(None)
        # 随时间变化
        A.win.follow_time = True
        for hour, name, variant in ((6, "light", "dawn"), (12, "light", None), (18, "dusk", None), (23, "dark", "night")):
            A.win._apply_time_theme(hour)
            self.assertEqual((th.T["name"], th.T.get("variant")), (name, variant))
        self.assertIn("stars", th.T["wall"])
        A.win.set_theme("light")
        self.assertFalse(A.win.follow_time)
        # 年报
        A.say("年报测试 😂😂🎉")
        data = A.win.report_data("year")
        self.assertGreater(data["sent"], 0)
        self.assertEqual(data["emojis"][0][0], "😂")
        self.assertTrue(any(c[2] == B.id for c in data["contacts"]))
        for p in ("month", "all"):
            self.assertIn("title", A.win.report_data(p))
        look.ReportCard(data)

    def test_12_password(self):
        import tempfile
        from miyu import storage
        tmp = tempfile.mkdtemp()
        store = storage.AccountStore(os.path.join(tmp, "a"))
        store.save_account({"seed": storage.b64e(os.urandom(32)), "nick": "带锁的"})
        store.save_history({"convs": []})
        store.set_password("芝麻开门")
        store.save_account({"seed": storage.b64e(os.urandom(32)), "nick": "带锁的"})
        store.save_history({"convs": [], "secret": "记录"})
        with open(os.path.join(store.folder, storage.ACCOUNT_FILE), "rb") as f:
            self.assertNotIn("带锁的".encode(), f.read())             # 文件里看不到明文
        s2 = storage.AccountStore(store.folder)
        self.assertTrue(s2.is_locked())
        self.assertIsNone(s2.load_account())
        self.assertFalse(s2.unlock("不对"))
        self.assertTrue(s2.unlock("芝麻开门"))
        self.assertEqual(s2.load_account()["nick"], "带锁的")
        self.assertEqual(s2.load_history()["secret"], "记录")
        self.assertTrue(s2.verify("芝麻开门"))
        self.assertFalse(s2.verify("x"))
        s2.set_password(None)
        s2.save_account({"seed": storage.b64e(os.urandom(32)), "nick": "去掉锁"})
        self.assertFalse(storage.AccountStore(store.folder).is_locked())
        # 窗口:叫回时要密码
        A = self.A
        A.win.store = s2
        s2.set_password("1234")
        A.win.lock_on_show = True
        A.win.hotkeys_ok = True
        A.win._hide_all()
        self.assertTrue(A.win.locked)
        A.win.lock_overlay.edit.setText("错的")
        A.win.lock_overlay.try_unlock()
        self.assertTrue(A.win.locked)
        A.win.lock_overlay.edit.setText("1234")
        A.win.lock_overlay.try_unlock()
        self.assertFalse(A.win.locked)
        A.win.show_window()
        A.win.lock_on_show = False
        A.win.store = None

    def test_13_daily_achievements(self):
        from miyu import fun
        g = fun.PetGrowth()
        g.sent("2026-11-15")
        self.assertIn(("今日打卡", 50), g.take_pending())
        g.sent("2026-11-16")
        g.take_pending()
        g.sent("2026-11-17")
        got = g.take_pending()
        self.assertIn(("连续打卡 3 天", 180), got)
        self.assertEqual(g.streak, 3)
        g.sent("2026-11-19")                                         # 断了一天
        self.assertEqual(g.streak, 1)
        for _ in range(20):
            g.pat("2026-11-19")
        self.assertTrue(any(n == "撸宠达人" for n, _ in g.take_pending()))
        g2 = fun.PetGrowth(g.to_dict())
        self.assertEqual((g2.streak, g2.daily["pats"]), (1, 20))


class FavoritesTests(unittest.TestCase):
    """我的收藏:自己的会话。"""

    def test_self_conversation(self):
        import tempfile
        from miyu import storage
        tmp = tempfile.mkdtemp()
        store = storage.AccountStore(os.path.join(tmp, "acct"))
        ports = [BASE + 30, BASE + 31]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        A = Harness("收藏家", ports[0], mk(0), store=store, remember=True)
        B = Harness("朋友", ports[1], mk(1))
        hs = [A, B]
        try:
            self.assertIn("self", A.win.convs)
            keys = [A.win.conv_list.item(i).data(gui.Qt.ItemDataRole.UserRole)
                    for i in range(A.win.conv_list.count())] if hasattr(A.win.conv_list, "item") else []
            # 随手记:不走网络
            A.win.select_conv("self")
            sent_before = len([k for k, _ in []])
            A.say("明天带身份证")
            self.assertEqual(A.texts("self"), ["明天带身份证"])
            self.assertTrue(A.conv("self").messages[-1].mine)
            self.assertFalse(A.win.tools_btn.isVisible())
            # 收藏别人发的消息
            self.assertTrue(pump_until(hs, lambda: A.win.lobby_count() == 2 and B.win.lobby_count() == 2))
            B.win.select_conv("lobby")
            B.say("会议改到 3 点")
            self.assertTrue(pump_until(hs, lambda: "会议改到 3 点" in A.texts("lobby")))
            m = [x for x in A.conv("lobby").messages if x.text == "会议改到 3 点"][0]
            A.win.favorite(m)
            fav = A.conv("self").messages[-1]
            self.assertEqual(fav.text, "会议改到 3 点")
            self.assertEqual((fav.fav["from"], fav.fav["where"]), ("朋友", "公开大厅"))
            # 阅后即焚的不能收藏
            burn = gui.Msg("烧", burn=10, sender="x", nick="x")
            A.conv("lobby").messages.append(burn)
            n = len(A.conv("self").messages)
            A.win.favorite(burn)
            self.assertEqual(len(A.conv("self").messages), n)
            # 存文件:只记位置
            f = os.path.join(tmp, "合同.pdf")
            with open(f, "wb") as fp:
                fp.write(b"pdf")
            A.win.select_conv("self")
            A.win.send_files([f])
            item = A.conv("self").messages[-1]
            self.assertTrue(item.file["local"])
            self.assertEqual(A.win.transfers[item.file["fid"]]["path"], f)
            # 编辑随手记:只改本机
            note = [x for x in A.conv("self").messages if x.text == "明天带身份证"][0]
            A.win.start_edit(note)
            A.win.input.setPlainText("明天带身份证和户口本")
            A.win.send_current()
            self.assertEqual(note.text, "明天带身份证和户口本")
            # 查看原消息
            A.win.goto_original(fav)
            self.assertEqual(A.win.current_key, "lobby")
            # 紧急清空:聊天没了,收藏还在
            A.win.hotkeys_ok = True
            A.win.panic()
            self.assertEqual(A.texts("lobby"), [])
            self.assertIn("会议改到 3 点", A.texts("self"))
            # 收藏不进聊天记录文件,单独保存;重开还在
            A.win.save_history_now(force=True)
            if A.win.db is not None:
                self.assertNotIn("self", [c["key"] for c in A.win.db.convs()])
            ev = FakeCloseEvent()
            A.win.closeEvent(ev)
            A.core.stop()
            self.assertTrue(os.path.exists(os.path.join(store.folder, storage.FAVS_FILE)))
            from miyu import crypto as C
            acct = store.load_account()
            A2 = Harness(acct["nick"], ports[0], mk(0), identity=C.Identity(storage.b64d(acct["seed"])),
                         store=store, account=acct, remember=True)
            hs = [A2, B]
            self.assertEqual(A2.texts("self")[:2], ["明天带身份证和户口本", "会议改到 3 点"])
            again = [x for x in A2.conv("self").messages if x.file]
            self.assertTrue(again and again[0].file["path"] == f)
            self.assertEqual(A2.win.transfers[again[0].file["fid"]]["path"], f)
            # 清空收藏
            A2.win.clear_conv(A2.conv("self"))
            self.assertEqual(A2.texts("self"), [])
            A2.win.save_favs()
            self.assertEqual(store.load_favs(), [])
            # 注销:收藏文件也删掉
            orig = gui.LogoutDialog.exec
            gui.LogoutDialog.exec = lambda self: 1
            try:
                A2.win.logout()
            finally:
                gui.LogoutDialog.exec = orig
            self.assertFalse(os.path.exists(os.path.join(store.folder, storage.FAVS_FILE)))
        finally:
            for h in hs:
                h.core.stop()

    def test_not_remembered_favs_in_memory(self):
        A = Harness("路过", BASE + 33, [])
        try:
            self.assertTrue(any("关掉软件后这里也会清空" in t for t in A.systems("self")))
            A.win.select_conv("self")
            A.say("临时记一下")
            self.assertFalse(A.win.save_favs(force=True))
        finally:
            A.core.stop()


class BatchFourTests(unittest.TestCase):
    """第四批:回应、转发多选、头像、排行榜、称号、小剧场、抽卡、日记、进化、音效主题、白噪音、护眼、防偷看。"""

    @classmethod
    def setUpClass(cls):
        ports = [BASE + 40, BASE + 41, BASE + 42]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.A = Harness("阿一", ports[0], mk(0))
        cls.B = Harness("阿二", ports[1], mk(1))
        cls.C = Harness("阿三", ports[2], mk(2))
        cls.all = [cls.A, cls.B, cls.C]
        assert pump_until(cls.all, lambda: all(h.win.lobby_count() == 3 for h in cls.all), timeout=25)

    @classmethod
    def tearDownClass(cls):
        for h in cls.all:
            h.core.stop()

    def test_01_reactions_and_title(self):
        A, B, C = self.A, self.B, self.C
        A.win.pet_growth.badges["k1k"] = "2026-11-17"
        A.win.pet_growth.title = "k1k"
        A.win.core.title = A.win.pet_growth.title_text()
        A.win.select_conv("lobby")
        B.win.select_conv("lobby")
        A.say("给我点个赞")
        self.assertTrue(pump_until(self.all, lambda: "给我点个赞" in B.texts("lobby")))
        bm = [x for x in B.conv("lobby").messages if x.text == "给我点个赞"][0]
        self.assertEqual(bm.title, "初出茅庐")                         # 称号跟着消息过来
        am = [x for x in A.conv("lobby").messages if x.text == "给我点个赞"][0]
        B.win.react(bm, "👍")
        self.assertTrue(pump_until(self.all, lambda: am.reactions.get("👍") == [B.id]))
        self.assertEqual(A.win.bubbles[am.mid].react_chips, [("👍", 1, False)])
        self.assertEqual(B.win.bubbles[bm.mid].react_chips, [("👍", 1, True)])
        A.win.react(am, "👍")
        self.assertTrue(pump_until(self.all, lambda: len(bm.reactions.get("👍", [])) == 2))
        B.win.react(bm, "👍")                                          # 再点一次取消
        self.assertTrue(pump_until(self.all, lambda: am.reactions.get("👍") == [A.id]))
        B.win.react(bm, "💩")                                          # 不在列表里的表情:忽略
        self.assertNotIn("💩", bm.reactions)
        B.core.send_event("lobby", None, "react", {"target": am.mid, "e": "<b>", "on": True})
        pump_until(self.all, lambda: False, timeout=0.5)
        self.assertEqual(list(am.reactions), ["👍"])

    def test_02_select_and_forward(self):
        A, B = self.A, self.B
        A.win.select_conv("lobby")
        A.say("转发一")
        A.say("转发二")
        msgs = [x for x in A.conv("lobby").messages if x.text in ("转发一", "转发二")]
        A.win.enter_select(msgs[0])
        self.assertTrue(A.win.select_bar.isVisible())
        A.win.toggle_select(msgs[1])
        self.assertEqual(A.win.selecting, {msgs[0].mid, msgs[1].mid})
        self.assertTrue(A.win.bubbles[msgs[1].mid].sel_btn.isChecked())
        dm = A.win.open_dm(B.id, select=False)
        self.assertTrue(A.win.forward(A.win._selected(), dm))
        key_b = "dm:" + A.id
        self.assertTrue(pump_until(self.all, lambda: B.conv(key_b) and B.texts(key_b)[-2:] == ["转发一", "转发二"]))
        A.win.forward(msgs[:1], A.conv("self"))                         # 转发到我的收藏
        self.assertIn("转发一", A.texts("self"))
        A.win.hotkeys_ok = True
        A.win.on_escape()                                               # ESC 先退出多选
        self.assertIsNone(A.win.selecting)
        self.assertTrue(A.win.isVisible())
        from miyu.window import chat as more
        more.ask = lambda *a, **k: True
        A.win.enter_select(msgs[0])
        A.win.delete_selected()
        self.assertNotIn("转发一", A.texts("lobby"))
        self.assertIsNone(A.win.selecting)
        burn = gui.Msg("烧", burn=5, mine=True)
        self.assertFalse(A.win.forward([burn], dm))                     # 阅后即焚不能转发

    def test_03_avatar(self):
        from miyu.window import chat as more
        A, B = self.A, self.B
        orig_decode = gui.imaging.decode
        gui.imaging.decode = lambda data: object() if data and data[:2] == b"\xff\xd8" else None
        self.addCleanup(lambda: (setattr(gui.imaging, "decode", orig_decode), ui.AVATARS.clear()))
        A.win.set_avatar((make_jpeg(), "image/jpeg"))
        self.assertTrue(pump_until(self.all, lambda: A.id in B.win.avatar_from))
        self.assertIn(A.id, ui.AVATARS)
        self.assertIn("avatar", A.win.account_dict())
        B.core.send_event("dm", A.id, "avatar", {"img": "!!!不是图片"})
        B.core.send_event("dm", A.id, "avatar", {"img": "QUFB" * (more.AVATAR_MAX // 2)})     # 太大
        pump_until(self.all, lambda: False, timeout=0.5)
        self.assertNotIn(B.id, A.win.avatar_from)
        A.win.set_avatar(None)
        self.assertTrue(pump_until(self.all, lambda: A.id not in B.win.avatar_from))

    def test_04_rank(self):
        import datetime
        A, B = self.A, self.B
        A.win.select_conv("lobby")
        B.win.select_conv("lobby")
        for i in range(9):
            B.say(f"排行 {i}")
        A.say("我也说一句")
        self.assertTrue(pump_until(self.all, lambda: "排行 8" in A.texts("lobby")))
        text = A.win.rank_text(A.conv("lobby"), more_week())
        self.assertIn("话痨榜", text)
        self.assertLess(text.index("阿二"), text.index("阿一"))            # 阿二说得多,排前面
        nxt = datetime.date.today() + datetime.timedelta(days=7)
        A.win.set_fun("rank", False)
        n = len(A.systems("lobby"))
        A.win._tick_rank(nxt)
        self.assertEqual(len(A.systems("lobby")), n)                    # 关掉后不公布
        B.win._tick_rank(nxt)
        self.assertTrue(any("上周排行榜" in t for t in B.systems("lobby")))
        self.assertEqual(B.win.rank.get("lobby"), {})                   # 旧数据清掉
        A.win.set_fun("rank", True)

    def test_05_skit_and_friends(self):
        A, B = self.A, self.B
        A.win.open_dm(B.id, select=True)
        self.assertTrue(A.win.start_skit(B.id, "fish"))
        self.assertTrue(pump_until(self.all, lambda: A.win.visitor is not None and B.win.visitor is not None))
        self.assertTrue(A.win.visit["skit"] and B.win.visit["skit"])
        self.assertEqual(A.win.pet_growth.counts["skits"], 1)
        self.assertIn("skit1", B.win.pet_growth.badges)
        self.assertGreaterEqual(A.win.pet_growth.friends[B.id]["v"], 5)
        self.assertEqual(A.win.pet_growth.friends[B.id]["pet"]["name"], "团团")
        for h in (A, B):
            h.win.visit["until"] = 0
            h.win._tick_pets(time.monotonic())
            self.assertIsNone(h.win.visitor)
        pump_until(self.all, lambda: False, timeout=0.5)
        self.assertFalse(A.win.pet_away)
        B.win.set_fun("skits", False)                                   # 对方关了小剧场:演不起来
        A.win.start_skit(B.id, "note")
        pump_until(self.all, lambda: False, timeout=0.6)
        self.assertIsNone(A.win.visitor)
        B.win.set_fun("skits", True)
        # 合照要友谊值 30
        A.win.pet_growth.friends[B.id]["v"] = 10
        n = len(A.conv("dm:" + B.id).messages)
        A.win.take_photo(B.id)
        self.assertEqual(len(A.conv("dm:" + B.id).messages), n)

    def test_06_privacy_eyecare_fx_sound(self):
        A = self.A
        self.assertTrue(A.win.privacy)                                   # 默认开
        A.win.privacy_cover()
        self.assertTrue(A.win.cover.isVisible())
        A.win.on_keystroke("char")                                       # 打字 = 人在,恢复
        self.assertFalse(A.win.cover.isVisible())
        A.win.on_activation(False)                                       # 窗口失去焦点
        self.assertTrue(A.win.cover.isVisible())
        A.win.set_privacy(False)
        self.assertFalse(A.win.cover.isVisible())
        A.win.on_activation(False)
        self.assertFalse(A.win.cover.isVisible())                        # 关掉后不再模糊
        A.win.set_privacy(True)
        A.win._tick_eyecare(23)
        self.assertTrue(A.win.eye_overlay.isVisible())
        A.win._tick_eyecare(12)
        self.assertFalse(A.win.eye_overlay.isVisible())
        A.win.set_eyecare(False)
        A.win._tick_eyecare(2)
        self.assertFalse(A.win.eye_overlay.isVisible())
        A.win.set_eyecare(True)
        # 打字特效主题:没解锁用不了,解锁后火花变成花瓣
        g = A.win.pet_growth
        g.xp = 0
        g.owned.discard("fx:sakura")
        A.win.set_fx("sakura")
        self.assertEqual(A.win.effects.fx_theme, "spark")
        g.owned.add("fx:sakura")
        A.win.set_fx("sakura")
        A.win.effects.parts.clear()
        A.win.effects.sparks(100, 100, 3)
        self.assertTrue(A.win.effects.parts and all(q.kind == "petal" for q in A.win.effects.parts))
        A.win.set_fx("spark")
        # 音效主题
        g.owned.add("snd:muyu")
        A.win.set_snd("muyu")
        self.assertEqual((A.win.notifier.theme, A.win.keysound.theme), ("muyu", "muyu"))
        A.win.set_snd("cat")                                             # 没解锁 → 默认
        self.assertEqual(A.win.notifier.theme, "default")
        # 白噪音:藏起来必须停
        A.win.set_ambient("rain")
        self.assertEqual(A.win.ambient.kind, "rain")
        A.win.hotkeys_ok = True
        A.win._hide_all()
        self.assertIsNone(A.win.ambient.kind)
        A.win.show_window()
        self.assertEqual(A.win.ambient.kind, "rain")
        A.win.set_ambient(None)
        self.assertIsNone(A.win.ambient.kind)

    def test_07_gacha_and_evolution_in_window(self):
        import random as _r
        from miyu import fun
        A = self.A
        g = A.win.pet_growth
        g.tickets = 3
        res = A.win.gacha_draw(_r.Random(1))
        self.assertIsNotNone(res)
        self.assertEqual(g.tickets, 2)
        g.xp = fun.xp_for_level(20) - 1
        t = g.tickets
        A.win.select_conv("lobby")
        A.win.on_keystroke("char")
        self.assertTrue(g.evolved)
        self.assertEqual(g.tickets, t + 1)                              # 升级送一张券
        ov = A.win.levelup_overlay
        self.assertTrue(ov.subtitle and "进化成了" in ov.subtitle)          # 进化时仪式上有一行大字
        self.assertTrue(any(x.card and x.card.get("type") == "petlv" and x.card["lv"] == 20
                            for x in A.conv("lobby").messages))
        acct = A.win.account_dict()
        g2 = fun.PetGrowth(acct["pet"])
        self.assertEqual((g2.tickets, g2.level, sorted(g2.owned)), (g.tickets, g.level, sorted(g.owned)))
        self.assertIn("privacy", acct["settings"])


def more_week():
    from miyu.window import chat as more
    return more.week_id()


class GrowthModelTests(unittest.TestCase):
    def test_gacha_badges_diary_friends(self):
        import random as _r
        from miyu import fun
        g = fun.PetGrowth()
        self.assertIsNone(g.draw())                                     # 没券抽不了
        self.assertTrue(g.grant_daily("2026-11-17"))
        self.assertFalse(g.grant_daily("2026-11-17"))                   # 一天一张
        self.assertTrue(g.grant_daily("2026-11-18"))
        self.assertEqual(g.tickets, 2)
        g.tickets = 400
        rng = _r.Random(7)
        seen, gap, worst = set(), 0, 0
        for _ in range(400):
            r = g.draw(rng)
            seen.add(r["rarity"])
            gap = 0 if r["rarity"] in ("SR", "SSR") else gap + 1
            worst = max(worst, gap)
            if r["rarity"] != "N" and r["new"]:
                self.assertIn(f"{r['kind']}:{r['id']}", g.owned)
        self.assertLess(worst, fun.GACHA_PITY)                          # 保底:10 抽内必有 SR 以上
        self.assertEqual(seen, {"N", "R", "SR", "SSR"})
        self.assertEqual(g.tickets, 0)
        self.assertIn("gacha10", g.badges)
        self.assertTrue(g.has("skin", "jelly"))                         # 抽到的东西不够等级也能用
        self.assertTrue(g.is_unlocked("bow"))
        g.title = "gacha10"
        self.assertEqual(g.title_text(), "抽卡爱好者")
        # 日记:换天时把前一天写下来
        d = fun.PetGrowth()
        day = fun._today()
        for _ in range(1200):
            d.tap(day)
        d.sent(day, hour=3)
        d.note_visit("visitors", "阿二家的团团")
        d.tap("2099-01-01")                                             # 到了"第二天"
        self.assertEqual(len(d.diary), 1)
        self.assertEqual(d.diary[0]["d"], day)
        for word in ("1,200", "1 条", "阿二家的团团", "哼"):
            self.assertIn(word, d.diary[0]["t"])
        self.assertIn("night", d.badges)                                # 凌晨发过消息
        self.assertIn("k1k", d.badges)
        self.assertTrue(d.today_diary())
        # 友谊值
        self.assertEqual(d.add_friend("p1", "阿二", 10), ("初识", "认识"))
        self.assertEqual(d.add_friend("p1", "阿二", 25), ("认识", "朋友"))
        d.add_friend("p1", "阿二", 500)
        self.assertEqual(d.friends["p1"]["v"], 100)
        self.assertIn("friend", d.badges)
        self.assertFalse(d.evolved)
        d.xp = fun.xp_for_level(20)
        self.assertTrue(d.evolved)
        again = fun.PetGrowth(d.to_dict())
        self.assertEqual((again.friends["p1"]["v"], len(again.diary), again.badges.keys()),
                         (100, len(d.diary), d.badges.keys()))
        bad = fun.PetGrowth({"owned": [1, "x"], "badges": {"nope": 1}, "title": "nope", "friends": {"a": 3},
                             "counts": "x", "diary": [3]})
        self.assertEqual((bad.title, bad.badges, bad.friends, bad.diary), ("", {}, {}, []))

    def test_sound_themes_and_ambient(self):
        from miyu import sound as S
        for th in ("muyu", "8bit", "cat"):
            self.assertTrue(S.chime_wav(theme=th).startswith(b"RIFF"))
            for kind in ("char", "space", "enter", "delete"):
                pcm = S.key_pcm(kind, 1, th)
                self.assertTrue(pcm and max(abs(x) for x in pcm) <= 32767)
        self.assertNotEqual(S.chime_wav(theme="muyu"), S.chime_wav())
        for kind, _ in S.AMBIENT:
            pcm = S.ambient_pcm(kind, secs=1.0)
            self.assertEqual(len(pcm), S.AMBIENT_RATE)
            self.assertLessEqual(max(abs(x) for x in pcm), 0.81)
        a = S.Ambient()
        self.assertFalse(a.play("nope"))
        self.assertTrue(a.play("fire", 0.3))
        a.stop()
        self.assertIsNone(a.kind)


class SystemTests(unittest.TestCase):
    """局域网自动更新、看视频、数据管理。"""

    def _keys(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return priv, pub

    def test_update_signature_logic(self):
        import tempfile
        from miyu import update as U
        priv, pub = self._keys()
        other_priv, other_pub = self._keys()
        tmp = tempfile.mkdtemp()
        exe = os.path.join(tmp, "MiYu.exe")
        body = os.urandom(300000)
        with open(exe, "wb") as f:
            f.write(body)
        self.assertIsNone(U.read_release(exe, pub))                      # 没签名
        U.sign_file(exe, "2.0.1", priv)
        self.assertEqual(os.path.getsize(exe), len(body) + U.TRAILER)
        self.assertEqual(U.read_release(exe, pub), "2.0.1")
        self.assertIsNone(U.read_release(exe, other_pub))                # 别人的公钥验不过
        U.sign_file(exe, "2.0.2", priv)                                  # 重新签:不会越签越长
        self.assertEqual(os.path.getsize(exe), len(body) + U.TRAILER)
        self.assertEqual(U.read_release(exe, pub), "2.0.2")
        with open(exe, "r+b") as f:                                      # 改一个字节 → 验不过
            f.seek(1000)
            f.write(b"\x00" if body[1000:1001] != b"\x00" else b"\x01")
        self.assertIsNone(U.read_release(exe, pub))
        with open(exe, "wb") as f:                                       # 改版本号(冒充更新的版本)→ 验不过
            f.write(body)
        U.sign_file(exe, "2.0.2", priv)
        with open(exe, "r+b") as f:
            f.seek(len(body) + 8)
            f.write(b"9.9.9".ljust(16, b"\0"))
        self.assertIsNone(U.read_release(exe, pub))
        self.assertTrue(U.newer("1.10.0", "1.9.9"))
        self.assertTrue(U.newer("2.0", "1.99.99"))
        self.assertFalse(U.newer("1.6", "1.6.0"))
        self.assertFalse(U.newer("abc", "1.0"))
        self.assertFalse(U.valid_version("1.0; rm -rf"))
        # 替换正在运行的 exe:旧的改名成 .old,新的放到原位置
        cur, new = os.path.join(tmp, "cur.exe"), os.path.join(tmp, "new.exe")
        for p, data in ((cur, b"old"), (new, b"new!")):
            with open(p, "wb") as f:
                f.write(data)
        U.apply_update(new, cur)
        with open(cur, "rb") as f:
            self.assertEqual(f.read(), b"new!")
        self.assertTrue(os.path.exists(cur + ".old"))
        U.cleanup_old(cur)
        self.assertFalse(os.path.exists(cur + ".old"))

    def test_lan_update_end_to_end(self):
        import tempfile
        from miyu import update as U
        from miyu.window import system
        system.ask = lambda *a, **k: True
        system.info = lambda *a, **k: None
        priv, pub = self._keys()
        evil_priv, _ = self._keys()
        tmp = tempfile.mkdtemp()
        new_exe = os.path.join(tmp, "new", "MiYu.exe")
        os.makedirs(os.path.dirname(new_exe))
        body = os.urandom(2 * 1024 * 1024)
        with open(new_exe, "wb") as f:
            f.write(body)
        U.sign_file(new_exe, "9.9.9", priv)
        ports = [BASE + 50, BASE + 51, BASE + 52]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        A, B, C = Harness("旧版", ports[0], mk(0)), Harness("新版", ports[1], mk(1)), Harness("坏人", ports[2], mk(2))
        hs = [A, B, C]
        try:
            self.assertTrue(pump_until(hs, lambda: all(h.win.lobby_count() == 3 for h in hs), timeout=25))
            self.assertTrue(pump_until(hs, lambda: A.win.peer_versions.get(B.id) == system.VERSION))   # 互相报版本
            self.assertFalse(A.win.can_update())                         # 直接跑源码:不参与更新
            cur = os.path.join(tmp, "installed", "MiYu.exe")
            os.makedirs(os.path.dirname(cur))
            with open(cur, "wb") as f:
                f.write(b"old version")
            A.win.update_exe, A.win.update_key = cur, pub
            # 坏人:用自己的私钥签了一个"新版"
            fake = os.path.join(tmp, "fake.exe")
            with open(fake, "wb") as f:
                f.write(os.urandom(50000))
            U.sign_file(fake, "99.0.0", evil_priv)
            C.win.update_exe = fake
            C.win.offer_own_release({"size": os.path.getsize(fake), "mtime": os.path.getmtime(fake)})
            C.core.send_event("dm", A.id, "ver", {"v": "99.0.0", "rel": C.win.own_release})
            self.assertTrue(pump_until(hs, lambda: (C.id, "99.0.0") in A.win.update_bad, timeout=20))
            self.assertEqual(A.win.update["state"], "none")
            self.assertTrue(any("没有通过签名验证" in t for t in A.systems("lobby")))
            self.assertFalse(os.path.exists(os.path.join(A.win.update_dir(), "MiYu-99.0.0.exe")))
            # 关闭更新:什么都不做
            A.win.set_update_mode("off")
            B.win.update_exe = new_exe
            B.win.offer_own_release({"size": os.path.getsize(new_exe), "mtime": os.path.getmtime(new_exe)})
            B.core.send_event("dm", A.id, "ver", {"v": "9.9.9", "rel": B.win.own_release})
            pump_until(hs, lambda: False, timeout=0.6)
            self.assertEqual(A.win.update["state"], "none")
            # 只提醒
            A.win.set_update_mode("notify")
            B.core.send_event("dm", A.id, "ver", {"v": "9.9.9", "rel": B.win.own_release})
            self.assertTrue(pump_until(hs, lambda: A.win.update["state"] == "offered"))
            self.assertTrue(A.win.download_update())
            self.assertTrue(pump_until(hs, lambda: A.win.update["state"] == "ready", timeout=30))
            self.assertEqual(U.read_release(A.win.update["path"], pub), "9.9.9")
            self.assertNotIn(A.win.update["fid"], A.win.transfers)       # 不会当成聊天文件
            A.win._fill_update_menu()
            self.assertTrue(any("安装 v9.9.9" in a.text() for a in A.win.update_menu.actions()))
            A.win.show_update()
            # 安装:替换 exe,准备重启
            self.assertTrue(A.win.install_update())
            with open(cur, "rb") as f:
                self.assertEqual(f.read()[:len(body)], body)
            self.assertTrue(os.path.exists(cur + ".old"))
            self.assertTrue(A.win.relaunch)
            self.assertEqual(A.win.account_dict()["settings"]["update_mode"], "notify")
        finally:
            for h in hs:
                h.core.stop()

    def test_release_tool(self):
        import subprocess
        import tempfile
        from miyu import update as U
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tmp = tempfile.mkdtemp()
        env = dict(os.environ, MIYU_RELEASE_DIR=os.path.join(tmp, "keys"))
        pubfile = os.path.join(root, "miyu", "_pubkey.py")
        try:
            subprocess.run([sys.executable, os.path.join(root, "tools", "release.py"), "prepare"], env=env, check=True,
                           capture_output=True)
            self.assertTrue(os.path.exists(os.path.join(tmp, "keys", "key.bin")))
            ns: dict = {}
            exec(open(pubfile, encoding="utf-8").read(), ns)
            pub = bytes.fromhex(ns["RELEASE_PUBKEY"])
            exe = os.path.join(tmp, "MiYu.exe")
            with open(exe, "wb") as f:
                f.write(os.urandom(10000))
            subprocess.run([sys.executable, os.path.join(root, "tools", "release.py"), "sign", exe], env=env, check=True,
                           capture_output=True)
            self.assertEqual(U.read_release(exe, pub), U.VERSION)
            subprocess.run([sys.executable, os.path.join(root, "tools", "release.py"), "prepare"], env=env, check=True,
                           capture_output=True)                          # 再打包一次:还是同一把钥匙
            ns2: dict = {}
            exec(open(pubfile, encoding="utf-8").read(), ns2)
            self.assertEqual(ns2["RELEASE_PUBKEY"], ns["RELEASE_PUBKEY"])
        finally:
            if os.path.exists(pubfile):
                os.remove(pubfile)

    def test_video_and_data(self):
        import tempfile
        from miyu import stickers as ST, storage
        from miyu.window import system
        system.ask = lambda *a, **k: True
        tmp = tempfile.mkdtemp()
        store = storage.AccountStore(os.path.join(tmp, "sys", "MiYu"), stickers_folder=os.path.join(tmp, "sys", "MiYu", "cache"))
        A = Harness("看片", BASE + 55, [], store=store, remember=True, save_history=True)
        try:
            from miyu.stickers import StickerStore
            A.win.stickers = StickerStore(store.stickers_folder)
            # 视频文件:按钮变成"播放"
            A.win.select_conv("self")
            video = os.path.join(tmp, "旅行.MP4")
            doc = os.path.join(tmp, "表格.xlsx")
            for p in (video, doc):
                with open(p, "wb") as f:
                    f.write(b"x" * 100)
            A.win.send_files([video, doc])
            mv, md = [x for x in A.conv("self").messages if x.file][-2:]
            from miyu.widgets import VideoCard
            vcard = A.win.bubbles[mv.mid].card
            self.assertIsInstance(vcard, VideoCard)                       # 视频:封面卡片,点封面就播放
            self.assertEqual(vcard._poster_act, "play")
            self.assertEqual(vcard.btn_a.text(), "所在文件夹")
            self.assertEqual(A.win.bubbles[md.mid].card.btn_a.text(), "打开")
            A.win.on_file_action(mv, "play")                             # 测试环境没有多媒体模块 → 交给系统播放器
            self.assertEqual(A.win.video_fallbacks, 1)
            A.win.video_win = type("W", (), {"stop": lambda s: setattr(A, "stopped", True), "close": lambda s: None})()
            A.win.hotkeys_ok = True
            A.win._hide_all()                                            # 藏起来:播放器必须关
            self.assertTrue(A.stopped)
            self.assertIsNone(A.win.video_win)
            A.win.show_window()
            # 数据管理
            A.say("记一笔")
            A.win.save_account(force=True)
            A.win.save_favs(force=True)
            os.makedirs(os.path.join(store.folder, "out", "abc"))
            with open(os.path.join(store.folder, "out", "abc", "包.zip"), "wb") as f:
                f.write(b"z" * 5000)
            with open(os.path.join(store.stickers_folder, "s.bin") if os.path.isdir(store.stickers_folder)
                      else os.path.join(tmp, "s.bin"), "wb") as f:
                f.write(b"s" * 300)
            self.assertGreater(A.win.data_size("account"), 0)
            self.assertGreater(A.win.data_size("favs"), 0)
            self.assertEqual(A.win.data_size("temp"), 5000)
            A.win.data_clean("temp")
            self.assertEqual(A.win.data_size("temp"), 0)
            self.assertEqual([r[0] for r in A.win.data_rows()],
                         ["account", "history", "favs", "stickers", "background", "games", "temp"])
            # 便携模式:搬到软件旁边
            portable = os.path.join(tmp, "app", "MiYuData")
            os.makedirs(os.path.dirname(portable))
            orig = ST.portable_dir
            ST.portable_dir = lambda: portable
            try:
                old = store.folder
                self.assertFalse(A.win.data_is_portable())
                self.assertTrue(A.win.move_data(True))
                self.assertEqual(store.folder, portable)
                self.assertTrue(A.win.data_is_portable())
                self.assertFalse(os.path.exists(old))
                self.assertTrue(os.path.exists(os.path.join(portable, storage.ACCOUNT_FILE)))
                self.assertEqual(ST.base_dir(), portable)                # 下次启动会自动用这里
                self.assertEqual(len(storage.b64d(store.load_account()["seed"])), 32)   # 搬过去还读得出来
                self.assertTrue(A.win.stickers.folder.startswith(portable))
                self.assertFalse(A.win.move_data(True))                  # 已经在那里了
            finally:
                ST.portable_dir = orig
        finally:
            A.core.stop()


class RenameErrorDiagTests(unittest.TestCase):
    """群改名(所有人同步)、出错报告窗口、启动自检和诊断信息。"""

    def test_room_rename_syncs(self):
        ports = [BASE + 60, BASE + 61, BASE + 62]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        A, B = Harness("改名甲", ports[0], mk(0)), Harness("改名乙", ports[1], mk(1))
        hs = [A, B]
        C = None
        try:
            A.core.join_room("改名 测试 暗号 2026", "我起的名字")
            B.core.join_room("改名 测试 暗号 2026", "他起的名字")
            self.assertTrue(pump_until(hs, lambda: any(k.startswith("room:") for k in A.win.convs)
                                       and any(k.startswith("room:") for k in B.win.convs)))
            key = next(k for k in A.win.convs if k.startswith("room:"))
            self.assertTrue(pump_until(hs, lambda: A.win.room_count(key[5:]) == 2))
            from miyu.window import chat
            chat.prompt = lambda *a, **k: "  周末   爬山群  "
            self.assertTrue(A.win.rename_room(A.conv(key)))
            self.assertEqual(A.conv(key).title, "周末   爬山群")
            self.assertTrue(pump_until(hs, lambda: B.conv(key).title == "周末   爬山群"))
            self.assertTrue(any("改名甲 把群名改成了「周末   爬山群」" in t for t in B.systems(key)))
            self.assertEqual(B.win.room_keys[key[5:]]["name"], "周末   爬山群")       # 下次登录也是新名字
            # 旧的修改(时间更早)不会覆盖新的
            B.core.send_event("room", key[5:], "room_name", {"name": "过期的名字", "time": 1.0})
            pump_until(hs, lambda: False, timeout=0.6)
            self.assertEqual(A.conv(key).title, "周末   爬山群")
            # 时间写到很远的将来:只算"现在",之后别人还能改
            B.core.send_event("room", key[5:], "room_name", {"name": "想锁死", "time": 9e12})
            self.assertTrue(pump_until(hs, lambda: A.conv(key).title == "想锁死"))
            self.assertLess(A.conv(key).name_t, time.time() + 400)
            time.sleep(0.01)
            chat.prompt = lambda *a, **k: "解锁了"
            self.assertTrue(A.win.rename_room(A.conv(key)))
            self.assertTrue(pump_until(hs, lambda: B.conv(key).title == "解锁了"))
            # 大厅和私聊不能改
            self.assertFalse(A.win.rename_room(A.conv("lobby")))
            # 后来进群的人:自动拿到现在的群名(不刷提示)
            C = Harness("改名丙", ports[2], mk(2))
            hs.append(C)
            C.core.join_room("改名 测试 暗号 2026", "丙自己起的")
            self.assertTrue(pump_until(hs, lambda: C.conv(key) is not None and C.conv(key).title == "解锁了", timeout=25))
            self.assertFalse(any("把群名改成了" in t for t in C.systems(key)))
            # 跟着账户保存
            acct = A.win.account_dict()
            self.assertEqual([r["name"] for r in acct["rooms"]], ["解锁了"])
            self.assertGreater(acct["groups"][key]["name_t"], 0)
            # ＋ 菜单和会话右键菜单里有入口
            A.win.select_conv(key)
            A.win.fill_tools_menu()
            self.assertTrue(any("修改群名" in a.text() for a in A.win.tools_menu.actions()))
            # 改成一样的名字 / 空名字:什么都不做
            chat.prompt = lambda *a, **k: "解锁了"
            self.assertFalse(A.win.rename_room(A.conv(key)))
            chat.prompt = lambda *a, **k: "   "
            self.assertFalse(A.win.rename_room(A.conv(key)))
        finally:
            for h in hs:
                h.core.stop()

    def test_error_report_window(self):
        from miyu import errors
        from miyu.window import system
        A = Harness("出错", BASE + 65, [])
        try:
            log = A.win.errors
            self.assertIs(log, system.error_log())

            def boom():
                return {}["没有这个键"]
            try:
                boom()
            except KeyError as e:
                exc = e
            text = errors.format_exception(exc)
            self.assertIn("KeyError", text)
            self.assertIn("test_gui_logic.py:", text)
            self.assertNotIn(os.path.dirname(os.path.abspath(__file__)), text)   # 不带电脑上的完整路径
            entry = log.add_exception("界面", exc)
            self.assertTrue(entry["new"])
            self.assertIsNotNone(A.win._error_dialog)                          # 弹出了出错窗口
            self.assertIn("KeyError", A.win._error_dialog.box.toPlainText())
            self.assertIn("密语 v", A.win._error_dialog.box.toPlainText())
            A.win._error_dialog.copy()
            self.assertEqual(A.win._error_dialog.copy_btn.text(), "已复制")
            again = log.add_exception("界面", exc)                             # 同一个问题:不再弹,只累加
            self.assertFalse(again["new"])
            self.assertEqual([e for e in log.entries if e["sig"] == entry["sig"]][0]["count"], 2)
            A.win._error_dialog = None
            # 软件藏起来时不弹窗,叫回来再弹
            A.win.hotkeys_ok = True
            A.win._hide_all()
            A.win.hide()
            log.add("后台线程", "ValueError: 测试", "ValueError@x.py:1")
            self.assertIsNone(A.win._error_dialog)
            self.assertIsNotNone(A.win._error_pending)
            A.win.show_window()
            self.assertIsNotNone(A.win._error_dialog)
            self.assertIn("ValueError: 测试", A.win._error_dialog.box.toPlainText())
            A.win._error_dialog = None
            # 网络模块的后台错误
            A.core.loop.call_soon_threadsafe(lambda: 1 / 0)
            self.assertTrue(pump_until([A], lambda: any("ZeroDivisionError" in e["text"] for e in log.entries)))
            net = [e for e in log.entries if "ZeroDivisionError" in e["text"]][0]
            self.assertEqual(net["where"], "网络模块")

            def quiet():
                raise ConnectionResetError("对方断线")
            A.core.loop.call_soon_threadsafe(quiet)                              # 断线是正常情况:不报
            pump_until([A], lambda: False, timeout=0.5)
            self.assertFalse(any("ConnectionResetError" in e["text"] for e in log.entries))
            self.assertIn("ZeroDivisionError", log.text())
        finally:
            A.core.stop()

    def test_selfcheck_and_diagnostics(self):
        import concurrent.futures as cf
        from miyu import crypto as C, selfcheck
        res = selfcheck.run_checks(network=False)
        names = [r["name"] for r in res]
        self.assertEqual(names[:2], ["加密", "后台线程池"])
        self.assertFalse(selfcheck.has_failure(res), selfcheck.format_results(res))
        self.assertIn("视频", names)
        # 模拟用户电脑上那种"线程池是个占位对象"的情况:自检会自己修好
        real = cf.ThreadPoolExecutor

        class lazy_import:
            pass
        cf.ThreadPoolExecutor = lazy_import()
        try:
            r = {x["name"]: x for x in selfcheck.run_checks(network=False)}
            self.assertEqual(r["后台线程池"]["level"], "ok")
        finally:
            cf.ThreadPoolExecutor = real
        # 加密坏了:报 fail
        orig = C.scrypt32
        C.scrypt32 = lambda *a: (_ for _ in ()).throw(TypeError("'lazy_import' object is not callable"))
        try:
            r = {x["name"]: x for x in selfcheck.run_checks(network=False)}
            self.assertEqual(r["加密"]["level"], "fail")
            self.assertIn("lazy_import", r["加密"]["detail"])
        finally:
            C.scrypt32 = orig
        # 窗口:启动后自动跑一遍(包括网络和数据文件夹),有问题弹窗
        import tempfile
        from miyu import storage
        store = storage.AccountStore(os.path.join(tempfile.mkdtemp(), "d"))
        A = Harness("诊断", BASE + 66, [], store=store, remember=True)
        try:
            A.win.run_startup_checks()
            self.assertTrue(pump_until([A], lambda: len(A.win.check_results) >= 6))
            r = {x["name"]: x for x in A.win.check_results}
            self.assertEqual(r["网络"]["level"], "ok")
            self.assertEqual(r["数据文件夹"]["level"], "ok")
            text = A.win.diagnostics_text()
            for word in ("启动自检", "出错记录", "自动更新", "密语 v"):
                self.assertIn(word, text)
            bad = [{"name": "加密", "level": "fail", "detail": "坏了"}]
            A.win._on_checks((bad, True))
            self.assertTrue(A.win._diag_dialog.box.toPlainText())
        finally:
            A.core.stop()

    def test_app_selftest_exit_code(self):
        from miyu import app
        self.assertEqual(app.main(["--selftest"]), 0)


class _FakeUrl:
    def __init__(self, path):
        self.path = path

    def isLocalFile(self):
        return True

    def toLocalFile(self):
        return self.path


class _FakeMime:
    def __init__(self, paths=(), image=False):
        self.paths = list(paths)
        self.image = image

    def hasUrls(self):
        return bool(self.paths)

    def urls(self):
        return [_FakeUrl(p) for p in self.paths]

    def hasImage(self):
        return self.image

    def hasText(self):
        return False


class _FakeDrag:
    def __init__(self, mime):
        self._mime = mime
        self.accepted = None

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class _FakeImage:
    def isNull(self):
        return False

    def width(self):
        return 64

    def height(self):
        return 48


class GroupPetModelTests(unittest.TestCase):
    """群宠物的同步模型:每人一份计数取最大、名字以最后修改为准、防刷上限、离谱数据截断。"""

    def test_merge_and_caps(self):
        from miyu.petcare import GP_DAILY_FEEDS, GP_DAILY_XP, GroupPet
        a, b = GroupPet(), GroupPet()
        self.assertEqual(a.contribute("A", "甲", 4, today="2026-11-17"), 4)
        self.assertEqual(b.contribute("B", "乙", 10, today="2026-11-17"), 10)
        self.assertTrue(a.merge(b.to_wire()))
        self.assertTrue(b.merge(a.to_wire()))
        self.assertEqual(a.total, b.total)
        self.assertEqual(a.total, 14)
        self.assertFalse(a.merge(b.to_wire()))               # 再合并一次不会重复算
        # 每天上限
        self.assertEqual(a.contribute("A", "甲", 10_000, today="2026-11-17"), GP_DAILY_XP - 4)
        self.assertEqual(a.contribute("A", "甲", 5, today="2026-11-17"), 0)
        self.assertEqual(a.contribute("A", "甲", 5, today="2026-11-18"), 5)        # 第二天重新算
        fed = [a.feed("A", "甲", "fish", today="2026-11-18") for _ in range(GP_DAILY_FEEDS + 1)]
        self.assertEqual(fed.count(True), GP_DAILY_FEEDS)
        self.assertEqual(a.feeds["A"], GP_DAILY_FEEDS)
        self.assertEqual(a.act["by"], "甲")
        # 名字:时间新的赢;旧的不会覆盖
        a.rename("  小  团子  ", "甲")
        self.assertEqual(a.name[0], "小 团子")
        b.merge(a.to_wire())
        self.assertEqual(b.name[0], "小 团子")
        b.merge({"n": ["过期名字", 1.0, "丙"]})
        self.assertEqual(b.name[0], "小 团子")
        # 离谱的数据:负数、浮点、超大值、不认识的种类都挡住
        c = GroupPet()
        c.merge({"x": {"X": -5, "Y": 1.5, "Z": 10 ** 12, 3: 7}, "s": ["dragon", 9e9, "x"], "n": ["", 9e9, "x"]})
        self.assertEqual(c.xp, {"Z": 10_000_000})
        self.assertEqual(c.species[0], "bunny")
        # 保存再读回来
        d = GroupPet(a.to_dict())
        self.assertEqual((d.total, d.name[0], d.feeds_left(today="2026-11-18")), (a.total, a.name[0], 0))
        self.assertGreater(len(a.top()), 0)

    def test_care_and_forms(self):
        from miyu import fun, petcare
        g = fun.PetGrowth({"food": 30, "joy": 50, "care_t": time.time() - 3600 * 2, "xp": fun.xp_for_level(2)})
        g.care()
        self.assertAlmostEqual(g.food, 30 - 8, delta=0.5)
        self.assertEqual(g.feed("cake"), -1)                 # 6 级才解锁
        self.assertEqual(g.feed("fish"), 0)
        self.assertGreater(g.food, 40)
        self.assertEqual(g.play("bubble"), -1)
        self.assertEqual(g.play("yarn"), 0)
        self.assertEqual(g.counts["feeds"], 1)
        self.assertFalse(g.set_expr("cool"))
        self.assertTrue(g.set_expr("smile"))
        self.assertEqual(fun.PetGrowth(g.to_dict()).expr, "smile")
        self.assertEqual(petcare.form_of(1)[1], "幼年期")
        self.assertEqual(petcare.form_of(20)[1], "进化期")
        self.assertEqual(petcare.form_of(30)[1], "传说期")
        self.assertEqual(petcare.next_form(25), (30, "传说期"))
        self.assertEqual(petcare.next_form(30), (40, "神话期"))
        self.assertEqual(petcare.form_of(40)[1], "神话期")
        self.assertIsNone(petcare.next_form(fun.PET_MAX_LEVEL))
        big = fun.PetGrowth({"xp": fun.xp_for_level(30)})
        self.assertTrue(big.legendary)
        for aid, *_ in fun.ACCESSORIES:                     # 新装扮都有部位、都能戴
            self.assertIn(fun.ACC_BY_ID[aid][3], dict(fun.SLOTS))
            big.toggle(aid)
        self.assertEqual(len(big.wear), len(fun.SLOTS))      # 每个部位一件
        for _ in range(50):
            big.feed("fish")
        self.assertIn("feed50", big.badges)


class ThemeCustomTests(unittest.TestCase):
    def test_presets_custom_and_blob(self):
        app = QApplication()
        for name in theme.THEMES:                            # 七套主题都能生成样式表、画壁纸
            theme.apply(app, name)
            theme.render_wallpaper(900, 600)
            qss = theme.build_qss()
            self.assertIn('QLabel#bubbleMine[grp="first"][side="r"]', qss)
            self.assertIn("QLabel#lvBadge", qss)
            self.assertIn(name, theme.THEME_SWATCH)
        try:
            theme.set_custom({"accent": "#34C759", "bubble": "#FFD60A", "glass": 100, "bg_dim": 999, "junk": 1})
            theme.apply(app, "light")
            self.assertEqual(theme.T["accent"], "#34C759")
            self.assertEqual(theme.T["mine"], "#FFD60A")
            self.assertEqual(theme.T["on_mine"], "#1D1D1F")          # 黄色气泡配深色字
            self.assertEqual(theme.CUSTOM["bg_dim"], 100)
            self.assertNotIn("junk", theme.CUSTOM)
            self.assertLess(float(theme.T["side"].split(",")[-1][:-1]), float(theme.LIGHT["side"].split(",")[-1][:-1]))
            self.assertEqual(theme.clean_custom({"accent": "red", "glass": "x"})["accent"], "")
            self.assertEqual(theme.text_on("#007AFF"), "#FFFFFF")
            self.assertEqual(theme.level_tier(25), 2)
        finally:
            theme.set_custom({"accent": "", "bubble": "", "glass": 50, "bg_dim": 35, "bg_blur": True})
            theme.apply(app, "light")
        import tempfile
        from miyu import storage
        with tempfile.TemporaryDirectory() as d:
            st = storage.AccountStore(d, os.path.join(d, "st"))
            self.assertTrue(st.save_blob(storage.BG_FILE, b"\xff\xd8abc"))
            self.assertEqual(st.load_blob(storage.BG_FILE), b"\xff\xd8abc")
            st.save_blob(storage.BG_FILE, None)
            self.assertEqual(st.load_blob(storage.BG_FILE), b"")


class V17Tests(unittest.TestCase):
    """1.7:连续消息合并、快捷操作条、会话置顶 / 免打扰、拖拽直接发送、个性化、宠物照料、群宠物、桌面陪伴、等级标识。"""

    @classmethod
    def setUpClass(cls):
        ports = [BASE + 70, BASE + 71, BASE + 72]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.A = Harness("七甲", ports[0], mk(0))
        cls.B = Harness("七乙", ports[1], mk(1))
        cls.C = Harness("七丙", ports[2], mk(2))
        cls.all = [cls.A, cls.B, cls.C]
        assert pump_until(cls.all, lambda: all(h.win.lobby_count() == 3 for h in cls.all), timeout=25)

    @classmethod
    def tearDownClass(cls):
        for h in cls.all:
            h.core.stop()

    def test_01_grouping(self):
        from miyu.widgets import Msg
        W = gui.MainWindow
        t0 = 1000.0
        ms = []
        for i, (mine, sender, dt) in enumerate([(True, "me", 0), (True, "me", 30), (True, "me", 60), (False, "x", 70),
                                                 (False, "y", 80), (False, "y", 400)]):
            m = Msg(f"m{i}", sender=sender, mine=mine)
            m.time = t0 + dt
            ms.append(m)
        self.assertEqual(W.group_positions(ms), ["first", "mid", "last", "single", "single", "single"])
        # 窗口里:同一个人连着发,前一条自动变成组的开头 / 中间
        A = self.A
        A.win.select_conv("lobby")
        A.say("热身")                                        # 今天第一条会触发「今日打卡」系统提示,先发掉
        A.say("第一句")
        A.say("第二句")
        A.say("第三句")
        c = A.conv("lobby")
        bs = [A.win.bubbles[m.mid] for m in c.messages[-3:]]
        self.assertEqual([b.grp for b in bs], ["first", "mid", "last"])
        self.assertEqual(bs[1].body.property("grp"), "mid")
        self.assertEqual(bs[1].body.property("side"), "r")
        A.win._render_messages()                             # 整体重画:结果一样
        self.assertEqual([A.win.bubbles[m.mid].grp for m in c.messages[-3:]], ["first", "mid", "last"])

    def test_02_hover_actions(self):
        from miyu.window import ux
        ux.ask = lambda *a, **k: True
        A = self.A
        A.win.select_conv("lobby")
        A.say("可以复制的话")
        m = A.conv("lobby").messages[-1]
        self.assertEqual(A.win.hover_actions(m), ["react:👍", "react:❤️", "react:😂", "reply", "copy", "fav", "delete", "more"])
        A.win.hover_bubble(A.win.bubbles[m.mid])
        self.assertTrue(A.win.hover_bar.isVisible())
        self.assertIs(A.win.hover_bar.bubble.msg, m)
        A.win._hover_act("reply")
        self.assertIs(A.win.reply_to, m)
        self.assertFalse(A.win.hover_bar.isVisible())
        A.win.cancel_reply()
        n = len(A.win.self_conv.messages)
        A.win.quick_action(m, "fav")
        self.assertEqual(len(A.win.self_conv.messages), n + 1)
        A.win.quick_action(m, "delete")
        self.assertNotIn(m, A.conv("lobby").messages)
        burn = A.win._system                                 # 阅后即焚:不能复制、不能收藏
        A.say("焚", burn=10)
        mb = A.conv("lobby").messages[-1]
        self.assertEqual(A.win.hover_actions(mb), ["react:👍", "react:❤️", "react:😂", "reply", "delete", "more"])
        self.assertTrue(callable(burn))

    def test_03_pin_and_mute(self):
        A, B = self.A, self.B
        conv = A.win.open_dm(B.id, select=False)
        A.win.set_pinned(conv, True)
        self.assertEqual(A.win.pinned_keys[0], conv.key)
        self.assertTrue(conv.pinned)
        items = [A.win.conv_list.item(i).data(0) for i in range(A.win.conv_list.count())] \
            if hasattr(A.win.conv_list, "item") else None
        if items:
            self.assertEqual(items[0], conv.key)
        self.assertEqual(A.win.account_dict()["pinned"][0], conv.key)
        A.win.set_pinned(conv, False)
        self.assertNotIn(conv.key, A.win.pinned_keys)
        # 保存后再恢复
        A.win.set_pinned(conv, True)
        acct = A.win.account_dict()
        A.win.pinned_keys = []
        A.win._restore_settings(acct)
        self.assertEqual(A.win.pinned_keys, [conv.key])
        A.win.set_pinned(conv, False)

    def test_04_drop_send(self):
        import tempfile
        from miyu import imaging
        A, B = self.A, self.B
        conv = A.win.open_dm(B.id, select=True)
        orig_enc = imaging.encode_for_send
        imaging.encode_for_send = lambda img: (make_jpeg(), "image/jpeg", 64, 48)
        A.win._load_drop_image = lambda p: _FakeImage()
        try:
            with tempfile.TemporaryDirectory() as d:
                pic = os.path.join(d, "照片.png")
                vid = os.path.join(d, "片段.mp4")
                doc = os.path.join(d, "说明.txt")
                folder = os.path.join(d, "资料")
                os.makedirs(folder)
                for p, data in ((pic, b"png"), (vid, b"v" * 3000), (doc, "你好".encode()),
                                (os.path.join(folder, "a.txt"), b"a")):
                    with open(p, "wb") as f:
                        f.write(data)
                mime = _FakeMime([pic, vid, doc, folder])
                self.assertTrue(A.win.is_send_drop(mime))
                self.assertFalse(A.win.is_send_drop(_FakeMime([])))
                ev = _FakeDrag(mime)
                A.win.dragEnterEvent(ev)
                self.assertTrue(ev.accepted)
                self.assertTrue(A.win.drop_overlay.isVisible())
                self.assertIn(conv.title, A.win.drop_overlay.title)
                self.assertIn("1 张图片", A.win.drop_overlay.detail)
                self.assertIn("1 个视频", A.win.drop_overlay.detail)
                self.assertIn("文件夹", A.win.drop_overlay.detail)
                n = len(conv.messages)
                A.win.dropEvent(_FakeDrag(mime))
                self.assertFalse(A.win.drop_overlay.isVisible())
                QTimer.run_pending()
                self.assertTrue(pump_until(self.all, lambda: len([m for m in conv.messages[n:] if not m.system]) >= 4))
                new = [m for m in conv.messages[n:] if not m.system]
                self.assertIsNotNone(new[0].img)                         # 图片直接发成图片(没有弹确认)
                names = [m.file["name"] for m in new if m.file]
                self.assertIn("片段.mp4", names)
                self.assertIn("说明.txt", names)
                self.assertTrue(any(x.startswith("资料") for x in names))  # 文件夹打包发
                self.assertTrue(pump_until(self.all, lambda: len([m for m in B.conv("dm:" + A.id).messages
                                                                  if m.file or m.img]) >= 4))
                # 从浏览器拖来的图片(没有文件路径)
                k = len(conv.messages)
                self.assertEqual(A.win.send_dropped([], [_FakeImage()]), 1)
                self.assertIsNotNone(conv.messages[k].img)
                # 拖到输入框上:交给窗口处理
                ev2 = _FakeDrag(_FakeMime([doc]))
                A.win.input.dragEnterEvent(ev2)
                self.assertTrue(ev2.accepted)
                A.win.dragLeaveEvent(ev2)
                self.assertFalse(A.win.drop_overlay.isVisible())
        finally:
            imaging.encode_for_send = orig_enc
            del A.win._load_drop_image

    def test_05_level_badge_and_personalize(self):
        A, B = self.A, self.B
        A.win._sync_level()
        self.assertEqual(A.core.level, A.win.pet_growth.level)
        A.win.pet_growth.add(xp_needed := gui.PetGrowth().__class__({"xp": 0}).xp + 20000)
        A.win._sync_level()
        lv = A.win.pet_growth.level
        self.assertGreater(lv, 1)
        A.win.select_conv("lobby")
        A.say("看我的等级")
        self.assertTrue(pump_until(self.all, lambda: any(m.text == "看我的等级" and m.level == lv
                                                         for m in B.conv("lobby").messages)))
        self.assertIn(f"Lv.{lv}", A.win.me_sub.text())
        A.win.set_level_badge(False)
        self.assertEqual(A.core.level, 0)
        A.win.set_level_badge(True)
        self.assertTrue(xp_needed)
        # 个性化:改主题色立刻生效,并跟着设置保存
        try:
            A.win.apply_personalize({"accent": "#FF9500"})
            self.assertEqual(theme.T["accent"], "#FF9500")
            self.assertEqual(A.win.account_dict()["settings"]["custom"]["accent"], "#FF9500")
            A.win.set_custom_background(None)
            self.assertFalse(theme.has_custom_bg())
            A.win._fill_theme_menu()
            from miyu.window.style import PersonalizeDialog
            dlg = PersonalizeDialog(A.win)
            dlg.set_value("bubble", "#FFD60A")
            self.assertEqual(theme.T["mine"], "#FFD60A")
            dlg.pick_theme("violet")
            self.assertEqual(theme.T["name"], "violet")
            dlg.reset()
            self.assertEqual(theme.CUSTOM["bubble"], "")
            self.assertEqual(dlg.dim_key(), "wall_dim")     # 没选背景图:调暗的是渐变壁纸
            dlg.queue(dlg.dim_key(), 40, 90)
            dlg.flush()
            self.assertEqual(theme.CUSTOM["wall_dim"], 40)
            theme.wallpaper(300, 200)
            dlg.queue("glass", 90, 200)                      # 拖滑块:先记下,停手再应用
            self.assertEqual(theme.CUSTOM["glass"], 50)
            dlg.flush()
            self.assertEqual(theme.CUSTOM["glass"], 90)
            dlg.reject()                                     # 取消:恢复打开窗口之前的样子
            self.assertEqual(theme.CUSTOM["glass"], 50)
            self.assertEqual(theme.CUSTOM["wall_dim"], 0)
            self.assertEqual(theme.CUSTOM["accent"], "#FF9500")
        finally:
            A.win.apply_personalize({"accent": ""})

    def test_06_pet_care_and_notice(self):
        A, B = self.A, self.B
        g = A.win.pet_growth
        g.food = 20.0
        self.assertTrue(A.win.feed_pet("fish"))
        self.assertEqual(A.win.pet.acting(), "eat")
        self.assertGreater(g.food, 40)
        self.assertTrue(A.win.play_pet("yarn"))
        self.assertEqual(A.win.pet.acting(), "play")
        A.win.pet_menu(QApplication())                       # 菜单能建出来
        A.win._fill_fun_menu()
        from miyu.window.petlife import WardrobeDialog
        dlg = WardrobeDialog(A.win)
        dlg.toggle("bow")
        dlg.set_expr("smile")
        self.assertIn("bow", g.wear)
        self.assertEqual(g.expr, "smile")
        # 别的会话来消息:宠物冒"!"招手
        A.win.select_conv("lobby")
        A.win.pet._alert_t = -1e9
        bconv = B.win.open_dm(A.id, select=True)
        B.say("在吗")
        self.assertTrue(pump_until(self.all, lambda: any(m.text == "在吗" for m in A.conv("dm:" + B.id).messages)))
        self.assertGreater(A.win.pet._alert_t, 0)
        self.assertTrue(bconv)

    def test_07_group_pet(self):
        A, B, C = self.A, self.B, self.C
        for h in (A, B):
            h.core.join_room("群宠物 测试 暗号 2026", "养宠群")
        self.assertTrue(pump_until(self.all, lambda: all(any(k.startswith("room:") for k in h.win.convs) for h in (A, B))))
        key = next(k for k in A.win.convs if k.startswith("room:"))
        tag = key[5:]
        self.assertTrue(pump_until(self.all, lambda: A.win.room_count(tag) == 2))
        A.win.select_conv(key)
        self.assertTrue(A.win.gpet.isVisible())             # 在群里时群宠物趴在输入框左边
        A.say("给群宠物攒经验")
        self.assertEqual(A.win.gpets[tag].xp[A.id], 4)
        from miyu.window import petlife
        self.assertTrue(A.win.feed_gpet("fish"))
        self.assertTrue(pump_until(self.all, lambda: tag in B.win.gpets and B.win.gpets[tag].total == A.win.gpets[tag].total))
        self.assertEqual(B.win.gpets[tag].feeds[A.id], 1)
        # B 改名,A 收到
        petlife.prompt = lambda *a, **k: "汤圆"
        B.win.rename_gpet(B.conv(key))
        self.assertTrue(pump_until(self.all, lambda: A.win.gpets[tag].name[0] == "汤圆"))
        self.assertTrue(any("把群宠物改名为「汤圆」" in t for t in A.systems(key)))
        # 升级:所有人都看到
        from miyu import fun
        A.win.gpets[tag].xp[A.id] = fun.xp_for_level(5)
        A.win.send_gpet(tag)
        self.assertTrue(pump_until(self.all, lambda: B.win.gpets[tag].level >= 5))
        self.assertTrue(any("群宠物 汤圆 升到 Lv." in t for t in B.systems(key)))
        # 对方落后时会补发
        B.win.gpets[tag].xp[B.id] = 7
        B.win.gpets[tag].nicks[B.id] = "七乙"
        B.win.send_gpet(tag)
        self.assertTrue(pump_until(self.all, lambda: A.win.gpets[tag].xp.get(B.id) == 7))
        # 跟着账户保存
        acct = A.win.account_dict()
        self.assertIn(tag, acct["gpets"])
        A.win.select_conv("lobby")
        self.assertFalse(A.win.gpet.isVisible())
        A.win.gpet_menu(QApplication())
        A.win.show_gpet_rank(A.conv(key))
        self.assertTrue(C)

    def test_08_desktop_pet(self):
        A = self.A
        A.win.set_desktop_pet(True)
        A.win.showMinimized()
        A.win.desktop_pet_sync()
        self.assertIsNotNone(A.win.desktop_win)
        self.assertTrue(A.win.desktop_win.isVisible())
        # 窗口最小化时来消息:桌面上的宠物招手,不显示是谁发的
        from miyu.widgets import Msg
        A.win._say_t = 0
        m = Msg("hi", sender=self.B.id, nick="七乙")
        A.win.pet_notice(A.conv("lobby"), m)
        self.assertGreater(A.win.desktop_win.pet._alert_t, 0)
        self.assertEqual(A.win.desktop_win.pet._say[0], "✉️ 有新消息~")
        A.win.restore_from_desktop()
        A.win.desktop_pet_sync()
        self.assertFalse(A.win.desktop_win.isVisible())
        # 老板键藏起来:桌面宠物也不出现
        A.win.showMinimized()
        A.win._hide_all()
        A.win.desktop_pet_sync()
        self.assertFalse(A.win.desktop_win.isVisible())
        A.win.show_window()
        A.win.set_desktop_pet(False)


class ClickOrderTests(unittest.TestCase):
    """可点击控件要先让 Qt 处理完点击,最后才发信号(收到信号的地方可能把控件删掉,1.7.0 出过这个错)。"""

    def test_super_before_emit(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QLabel
        from miyu.widgets import ClickFrame, ClickLabel, DblLabel

        class Ev:
            def button(self):
                return Qt.MouseButton.LeftButton

        for cls, base, handler, sig in ((ClickLabel, QLabel, "mouseReleaseEvent", "clicked"),
                                        (DblLabel, QLabel, "mouseDoubleClickEvent", "double_clicked"),
                                        (ClickFrame, QFrame, "mouseReleaseEvent", "clicked")):
            order = []
            w = cls()
            getattr(w, sig).connect(lambda: order.append("emit"))
            had = handler in base.__dict__
            orig = base.__dict__.get(handler)
            setattr(base, handler, lambda self, e: order.append("super"))
            try:
                getattr(w, handler)(Ev())
            finally:
                if had:
                    setattr(base, handler, orig)
                else:
                    delattr(base, handler)
            self.assertEqual(order, ["super", "emit"], cls.__name__)


class ChangelogTests(unittest.TestCase):
    """每个版本都要写更新内容;别人发来的更新内容要过滤。"""

    def test_changelog(self):
        from miyu import changelog, update
        from miyu.version import VERSION
        self.assertEqual(changelog.CHANGELOG[0][0], VERSION, "版本号加大后,记得在 changelog.py 最上面写这一版的更新内容")
        vs = [e[0] for e in changelog.CHANGELOG]
        for a, b in zip(vs, vs[1:]):
            self.assertTrue(update.newer(a, b), f"{a} 应该比 {b} 新")
        for v, d, items in changelog.CHANGELOG:
            self.assertTrue(items)
        got = changelog.notes_between("1.7.1", "1.7.3")
        self.assertEqual([e[0] for e in got], ["1.7.3", "1.7.2"])
        wire = changelog.to_wire()
        self.assertEqual(changelog.from_wire(wire)[0][0], VERSION)
        junk = [["9.9", "x" * 50, ["  好的  ", 5, "y" * 500]], ["bad", "", ["a"]], "nope", ["1.0.0", "", []]]
        clean = changelog.from_wire(junk)
        self.assertEqual(clean, [("9.9", "", ["好的", "y" * changelog.MAX_ITEM_LEN])])
        self.assertIn("v1.7.3", changelog.format_entries(got))

    def test_whats_new(self):
        app = QApplication()
        h = Harness("记录甲", BASE + 75, [])
        try:
            from miyu import changelog
            vs = [e[0] for e in changelog.CHANGELOG]
            h.win.seen_version = vs[3]                     # 跳过了三个版本
            shown = []
            orig = gui_system.TextDialog
            gui_system.TextDialog = lambda *a, **k: shown.append(a) or types.SimpleNamespace(exec=lambda: 1)
            try:
                h.win.show_whats_new()
            finally:
                gui_system.TextDialog = orig
            from miyu.version import VERSION
            self.assertEqual(h.win.seen_version, VERSION)
            titles = [r[0] for r in shown[0][2]]
            self.assertTrue(titles[0].startswith(f"v{VERSION}"))
            self.assertEqual([t.split()[0] for t in titles], [f"v{v}" for v in vs[:3]])
            self.assertFalse(any(t.startswith(f"v{vs[3]}") for t in titles))
            self.assertEqual(h.win.account_dict()["settings"]["seen_version"], VERSION)
            self.assertIn("更新内容", h.win._notes_text([("1.9.0", "", ["新东西"])]))
            h.win._fill_update_menu()
            h.win.show_update()
            h.win.show_changelog()
            self.assertTrue(app is not None)
        finally:
            h.core.stop()


class RecordsTests(unittest.TestCase):
    """2.0 聊天记录:加密数据库、迁移、翻页、搜索旧记录、跳转、内存裁剪、撤回同步、保留期限。"""

    def _win(self, store, acct, port):
        return Harness("记录员", port, [], store=store, account=acct, remember=True, save_history=True)

    def _fill(self, h, conv, n, start=0, t0=None):
        t0 = t0 or time.time() - 86400 * 3
        for i in range(start, start + n):
            m = gui.Msg(f"第 {i} 条" + (" 火锅" if i % 97 == 0 else ""), mid=f"r{i:05d}", sender="peer", nick="乙", tag="2B2B")
            m.time = t0 + i
            h.win._add_message(conv, m, count_unread=False)

    def test_db_paging_search_and_migration(self):
        import tempfile
        from miyu import msgdb, storage
        from miyu.window import records
        with tempfile.TemporaryDirectory() as tmp:
            store = storage.AccountStore(os.path.join(tmp, "acct"))
            # ---- 先放一份 1.x 的旧记录(h.bin),看能不能搬进数据库
            store.save_account({"nick": "记录员", "seed": storage.b64e(os.urandom(32))})
            old = {"v": 1, "convs": [{"key": "lobby", "kind": "lobby", "title": "公开大厅", "target": None,
                                      "messages": [{"mid": "v1a", "text": "旧版的话", "time": time.time() - 9e5,
                                                    "sender": "x", "nick": "x", "tag": "x"}]}],
                   "transfers": {}, "games": {}, "votes": {}}
            store.save_history(old)
            h = self._win(store, store.load_account(), BASE + 76)
            try:
                self.assertIsNotNone(h.win.db)
                self.assertIn("旧版的话", h.texts("lobby"))
                self.assertFalse(store.has_v1_history())                       # 原文件改名留作备份
                self.assertTrue(os.path.exists(os.path.join(store.folder, storage.HISTORY_FILE + storage.V1_BACKUP)))
                conv = h.conv("lobby")
                self._fill(h, conv, 2000)
                h.win.save_history_now(force=True)
                self.assertEqual(h.win.db.count("lobby"), 2001)
                self.assertLessEqual(len(conv.messages), records.MEM_KEEP + 5)     # 内存里只留一部分
                self.assertTrue(conv.db_more)
                # ---- 渲染只有一段
                h.win.select_conv("lobby")
                self.assertLessEqual(len(h.win.bubbles), records.WIN_MAX)
                self.assertIn("r01999", h.win.bubbles)
                # ---- 往上翻:接上更早的(必要时从数据库读)
                for _ in range(12):
                    h.win._paging_t = 0
                    h.win._anchor = None
                    h.win.page_up()
                self.assertLessEqual(len(h.win.bubbles), records.WIN_MAX)
                self.assertFalse(h.win._win_bottom)
                self.assertTrue(h.win.latest_btn.isVisible())
                h.win.back_to_latest()
                self.assertTrue(h.win._win_bottom)
                self.assertFalse(h.win.latest_btn.isVisible())
                # ---- 会话内搜索能搜到数据库里还没读进来的
                h.win.open_search()
                h.win.search_edit.setText("火锅")
                h.win._on_search_text("火锅")
                self.assertEqual(len(h.win.search_hits), len([i for i in range(2000) if i % 97 == 0]))
                h.win.search_idx = 0
                h.win._show_hit()                                          # 跳到最早的那条
                self.assertIn(h.win.search_hits[0], h.win.bubbles)
                h.win.close_search()
                # ---- 引用跳转到很早的消息
                h.win.back_to_latest()
                h.win.jump_to("r00003")
                self.assertIn("r00003", h.win.bubbles)
                # ---- 撤回 / 删除同步到数据库
                h.win.back_to_latest()
                last = conv.messages[-1]
                h.win.delete_local(last)
                h.win.save_history_now()
                self.assertFalse(h.win.db.has(last.mid))
                # ---- 编辑后重写
                m = conv.messages[-1]
                m.text = "改过的内容"
                m.edited = True
                h.win._hist_dirty = True
                h.win.save_history_now()
                self.assertEqual(h.win.db.recent("lobby", 1)[0]["text"], "改过的内容")
                # ---- 退出再打开:只读最近一页,翻得回去
                ev = FakeCloseEvent()
                h.win.closeEvent(ev)
                h.core.stop()
            finally:
                h.core.stop()
            acct = store.load_account()
            self.assertTrue(acct.get("dbkey"))
            h2 = self._win(store, acct, BASE + 77)
            try:
                conv = h2.conv("lobby")
                saved = [x for x in conv.messages if not x.system]
                self.assertEqual(len(saved), records.FIRST_PAGE)
                self.assertEqual(saved[-1].text, "改过的内容")
                self.assertTrue(conv.db_more)
                got = h2.win.load_older(conv, 100)
                self.assertEqual(got, 100)
                # 文件里看不到明文
                with open(os.path.join(store.folder, msgdb.DB_FILE), "rb") as f:
                    raw = f.read()
                self.assertNotIn("火锅".encode(), raw)
                self.assertNotIn(b"lobby", raw)
                # ---- 保留期限:只留最近 1 天(上面的消息都是 3 天前的)
                h2.win.history_days = 7
                self.assertEqual(h2.win.maintain_history(), 1)                 # 旧版那条是 10 天前的
                records.HISTORY_DAYS.append((1, "测试"))
                try:
                    h2.win.set_history_days(1)                                 # 其余都是 3 天前的
                    self.assertEqual(h2.win.db.count("lobby"), 0)
                finally:
                    records.HISTORY_DAYS.pop()
                self.assertEqual(h2.win.account_dict()["settings"]["history_days"], 1)
                # ---- 关掉「保存聊天记录」:数据库删掉
                h2.win.toggle_history(False)
                self.assertIsNone(h2.win.db)
                self.assertFalse(os.path.exists(os.path.join(store.folder, msgdb.DB_FILE)))
                self.assertFalse(os.path.exists(os.path.join(store.folder, storage.HISTORY_FILE + storage.V1_BACKUP)))
            finally:
                h2.core.stop()


class SettingsTests(unittest.TestCase):
    """2.0 设置窗口:八个分类、跨分类搜索、开关直接生效、和原来的菜单状态保持同步。"""

    def test_settings_window(self):
        import tempfile
        from miyu import motion, storage
        from miyu.window import records, settings
        with tempfile.TemporaryDirectory() as tmp:
            store = storage.AccountStore(os.path.join(tmp, "acct"))
            store.save_account({"nick": "设置员", "seed": storage.b64e(os.urandom(32))})
            h = Harness("设置员", BASE + 78, [], store=store, account=store.load_account(), remember=True,
                        save_history=True)
            try:
                from PySide6.QtWidgets import QWidget
                w = h.win
                QWidget.stray.clear()
                d = settings.SettingsDialog(w)
                d.show()
                # 没有父窗口就被显示的标签,在 Windows 上会变成一个个小窗口闪过(2.0.0 的 bug)
                self.assertEqual(QWidget.stray, [])
                # ---- 每个分类都有内容,每一项都建出了一行
                self.assertEqual([c[0] for c in settings.CATEGORIES],
                                 ["account", "look", "chat", "notify", "pet", "security", "update", "data"])
                self.assertEqual({s.cat for s in d.specs}, {c[0] for c in settings.CATEGORIES})
                self.assertEqual(len(d.rows), len(d.specs))
                for s in d.specs:
                    if s.kind in ("switch", "choice", "menu", "button"):
                        self.assertTrue(callable(s.set), s.title)
                    if s.kind in ("choice", "menu"):
                        self.assertTrue(s.options, s.title)
                d.refresh()
                QTimer.run_pending()
                for i in range(len(settings.CATEGORIES)):
                    d._on_nav(i)

                def row(title):
                    return next(r for r in d.rows if r.spec.title == title)

                # ---- 搜索:标题、说明、关键词都算;多个词要同时命中
                self.assertIn("启动密码", [s.title for s in d.matches("密码")])
                self.assertIn("动态背景", [s.title for s in d.matches("静态")])
                self.assertIn("界面动效", [s.title for s in d.matches("动画")])
                self.assertEqual([s.title for s in d.matches("聊天 期限")], ["保留多久"])
                self.assertEqual(d.matches("   "), [])
                self.assertEqual(d.matches("没有这种设置"), [])
                d._on_search("提示音")
                self.assertTrue(d.result_rows)
                self.assertTrue(all(r.title.text().startswith("通知 › ") for r in d.result_rows))
                d.result_rows[0].ctrl.setChecked(False)                       # 结果页里也能直接调
                QTimer.run_pending()
                self.assertFalse(w.act_sound.isChecked())
                self.assertFalse(row("消息提示音").ctrl.isChecked())          # 分类页同步刷新
                d._on_search("没有这种设置")
                self.assertEqual(d.result_rows, [])
                self.assertEqual(QWidget.stray, [])                           # 搜索结果页也不能有
                d._on_search("")
                row("消息提示音").ctrl.setChecked(True)
                QTimer.run_pending()
                self.assertTrue(w.act_sound.isChecked())
                # ---- 动效、动态背景:直接生效,并且记进账户
                row("界面动效").ctrl.setChecked(False)
                QTimer.run_pending()
                self.assertFalse(motion.ENABLED)
                self.assertFalse(w.account_dict()["settings"]["motion"])
                row("界面动效").ctrl.setChecked(True)
                QTimer.run_pending()
                self.assertTrue(motion.ENABLED)
                r = row("动态背景")
                self.assertEqual(r.ctrl.text(), "明显")                         # 默认:看得出在动
                r._on_choice("off")
                QTimer.run_pending()
                self.assertFalse(theme.CUSTOM["ambient"])
                self.assertFalse(w.account_dict()["settings"]["custom"]["ambient"])
                self.assertTrue(r.ctrl.text().startswith("静态"))
                r._on_choice(1)
                QTimer.run_pending()
                self.assertTrue(theme.CUSTOM["ambient"])
                self.assertEqual(theme.CUSTOM["ambient_level"], 1)
                self.assertEqual(w.account_dict()["settings"]["custom"]["ambient_level"], 1)
                r._on_choice(2)
                QTimer.run_pending()
                self.assertEqual(theme.CUSTOM["ambient_level"], 2)
                # ---- 聊天记录保留期限
                r = row("保留多久")
                self.assertTrue(r.ctrl.isEnabled())
                self.assertEqual(r.ctrl.text(), "全部保留")
                r._on_choice(30)
                QTimer.run_pending()
                self.assertEqual(w.history_days, 30)
                self.assertEqual(r.ctrl.text(), dict(records.HISTORY_DAYS)[30])
                self.assertIn("已保存", row("数据库").sub.text())
                row("数据库")._on_button()                                      # 整理数据库
                QTimer.run_pending()
                row("保存聊天记录").ctrl.setChecked(False)                      # 关掉保存 → 期限变灰
                QTimer.run_pending()
                self.assertIsNone(w.db)
                self.assertFalse(r.ctrl.isEnabled())
                self.assertFalse(row("数据库").ctrl.isEnabled())
                # ---- 没解锁的特效:菜单里是灰的,就算选中也不生效
                r = row("打字特效主题")
                locked = [o for o in r.ctrl.options if not o[2]]
                self.assertTrue(locked)
                r._on_choice(locked[0][0])
                QTimer.run_pending()
                self.assertEqual(w.fun.get("fx", "spark"), "spark")
                # ---- 主题
                row("主题")._on_choice("dark")
                QTimer.run_pending()
                self.assertEqual(theme.T["name"], "dark")
                self.assertEqual(row("主题").ctrl.text(), theme.THEMES["dark"]["label"])
                row("主题")._on_choice("light")
                QTimer.run_pending()
                # ---- 会关掉窗口的操作:先关设置窗口,再执行
                called = []
                d.run(lambda: called.append(1), True)
                self.assertFalse(d.isVisible())
                self.assertEqual(called, [])
                QTimer.run_pending()
                self.assertEqual(called, [1])
                # ---- 齿轮按钮打开设置窗口
                w.menu_btn.clicked.emit()
            finally:
                motion.set_enabled(True)
                h.core.stop()


class MotionTests(unittest.TestCase):
    """2.0 微动效:关掉时一切瞬间完成;状态变化的小圆点脉冲会自己结束。"""

    def test_animate_and_pulses(self):
        from miyu import motion
        seen, done = [], []
        motion.set_enabled(False)
        try:
            self.assertIsNone(motion.animate(object(), 0.0, 1.0, 200, seen.append, lambda: done.append(1)))
            self.assertEqual(seen, [1.0])
            self.assertEqual(done, [1])
            motion.note_status("p1", True)                     # 关掉动效时不记录
            self.assertEqual(motion.pulse_of("p1"), -1.0)
        finally:
            motion.set_enabled(True)
        motion.note_status("p2", False)
        t0 = motion.status_changes["p2"][0]
        self.assertAlmostEqual(motion.pulse_of("p2", t0 + motion.PULSE_SECS / 2), 0.5, places=3)
        self.assertTrue(motion.any_pulse())
        self.assertEqual(motion.pulse_of("p2", t0 + motion.PULSE_SECS + 0.01), -1.0)
        self.assertNotIn("p2", motion.status_changes)

    def test_switch_quiet(self):
        from miyu import motion
        sw = motion.Switch(False)
        got = []
        sw.toggled.connect(got.append)
        sw.set_quiet(True)
        self.assertTrue(sw.isChecked())
        self.assertEqual(got, [])                              # 刷新状态不触发信号
        sw.setChecked(False)
        self.assertEqual(got, [False])

    def test_hover_skips(self):
        from PySide6.QtWidgets import QPushButton
        from miyu import motion
        b = QPushButton("x")
        self.assertTrue(motion.HoverFx.eligible(b))
        b.setObjectName("latestBtn")
        self.assertFalse(motion.HoverFx.eligible(b))
        self.assertFalse(motion.HoverFx.eligible(motion.Switch(False)))


class AmbientTests(unittest.TestCase):
    """2.0 动态背景:光斑和柔光确实在动、看得见;前台正常动、后台慢慢动、最小化 / 隐藏时停下。"""

    def test_spots_move_and_visible(self):
        theme.apply(QApplication(), "violet")
        try:
            self.assertEqual(theme.clean_custom({})["ambient_level"], 2)                 # 默认「明显」
            self.assertEqual(theme.clean_custom({"ambient_level": 9})["ambient_level"], 2)
            for level, lo, hi in ((2, 40, 170), (1, 15, 120)):
                theme.set_custom({"ambient_level": level})
                cfg = theme.AMBIENT_LEVELS[level]
                amax = cfg["alpha"][0]
                avg = 0.0
                for t in range(0, 60, 3):
                    a = theme.ambient_spots(1200, 760, float(t))
                    b = theme.ambient_spots(1200, 760, t + 1.0)
                    self.assertEqual(len(a), 4)
                    for s in a:
                        self.assertGreaterEqual(s[4], amax * (1 - 2 * cfg["breathe"][2]) - 1e-9)
                        self.assertLessEqual(s[4], amax + 1e-9)
                    moved = max(math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(a, b))
                    self.assertLess(moved, hi, level)                       # 不会快到晃眼
                    avg += moved / 20
                self.assertGreater(avg, lo, level)                          # 平均每秒挪得出肉眼看得见的距离
                b1 = theme.ambient_beam(1200, 760, 3.0)
                b2 = theme.ambient_beam(1200, 760, 4.0)
                self.assertNotEqual(b1[:2], b2[:2])
        finally:
            theme.set_custom({"ambient_level": 2})
            theme.apply(QApplication(), "light")

    def test_wallpaper_states(self):
        from miyu.widgets import Wallpaper
        win = types.SimpleNamespace(visible=True, minimized=False, active=True)
        wp = Wallpaper()
        wp.window = lambda: types.SimpleNamespace(isVisible=lambda: win.visible, isMinimized=lambda: win.minimized,
                                                  isActiveWindow=lambda: win.active)
        updates = []
        wp.update = lambda *a: updates.append(1)
        wp.set_ambient(True)
        updates.clear()
        wp._last_tick -= 0.06
        wp._step()
        self.assertEqual(wp.state(), 2)
        self.assertGreater(wp._t, 0)
        self.assertEqual(len(updates), 1)
        # 后台:时间照走,但每秒只画 4 帧
        win.active = False
        self.assertEqual(wp.state(), 1)
        wp._last_paint = time.monotonic()
        t0 = wp._t
        wp._last_tick -= 0.06
        wp._step()
        self.assertGreater(wp._t, t0)
        self.assertEqual(len(updates), 1)
        wp._last_paint -= 1
        wp._step()
        self.assertEqual(len(updates), 2)
        # 最小化 / 藏起来:完全停下,时间也不走(回来时不会跳)
        for attr, v in (("minimized", True), ("visible", False)):
            setattr(win, attr, v)
            t0 = wp._t
            wp._last_tick -= 5
            wp._step()
            self.assertEqual(wp._t, t0)
            self.assertEqual(wp.state(), 0)
            setattr(win, attr, not v)
        self.assertIn("帧", wp.status_text())
        wp.set_ambient(False)
        self.assertEqual(wp.state(), 0)
        self.assertIn("静态", wp.status_text())


class MediaTests(unittest.TestCase):
    """2.1:动图、视频封面、匿名视频的保存。"""

    def test_gif_parse_and_send_path(self):
        import tempfile
        from miyu import imaging
        g = make_gif(frames=4)
        w, h, n, clean = imaging.parse_gif(g, clean=True)
        self.assertEqual((w, h, n), (40, 30, 4))
        self.assertNotIn(b"secret note", clean)                     # 注释去掉了
        self.assertIn(b"NETSCAPE2.0", clean)                        # 循环播放保留
        self.assertTrue(imaging.is_animated_gif(g))
        self.assertFalse(imaging.is_animated_gif(make_gif(frames=1)))
        self.assertIsNone(imaging.parse_gif(g[:30]))                # 截断的
        self.assertIsNone(imaging.parse_gif(b"GIF89a" + b"\xff" * 20))
        self.assertEqual(imaging.gif_meta(g), (40, 30, 4))
        self.assertIsNone(imaging.gif_meta(b"x" * (imaging.GIF_MAX + 1)))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "动.gif")
            with open(path, "wb") as f:
                f.write(g)
            it = imaging.load_image_path(path)
            self.assertIsInstance(it, imaging.Gif)                  # 动图保持会动
            data, mime, gw, gh = imaging.encode_any(it)
            self.assertEqual((mime, gw, gh), ("image/gif", 40, 30))
            self.assertNotIn(b"secret note", data)
            big = os.path.join(tmp, "大.gif")
            with open(big, "wb") as f:
                f.write(g[:-1] + b"\x21\xfe\xff" + b"z" * 255 + (b"\xff" + b"z" * 255) * (imaging.GIF_MAX // 256 + 10)
                        + b"\x00\x3b")
            self.assertIsNone(imaging.load_image_path(big))          # 超过 8MB 的动图:交给调用方当文件发

    def test_gif_bubble_and_sync(self):
        from miyu.widgets import GIF_LABELS, Bubble, GifLabel
        g = make_gif(frames=3)
        m = gui.Msg("", mid="g" * 32, sender="x", nick="x", tag="x", img=g, mime="image/gif", w=40, h=30)
        b = Bubble(m, True, True, 400)
        self.assertIsInstance(b._img, GifLabel)
        self.assertIn(b._img, set(GIF_LABELS))
        b._img.set_active(True)
        b._img.set_active(False)
        st = gui.Msg("", mid="s" * 32, sender="x", nick="x", tag="x", img=g, mime="image/gif", sticker=True)
        self.assertIsInstance(Bubble(st, True, True, 400)._img, GifLabel)
        burn = gui.Msg("", mid="b" * 32, sender="x", nick="x", tag="x", img=g, mime="image/gif", burn=10)
        self.assertNotIsInstance(Bubble(burn, True, True, 400)._img, GifLabel)   # 阅后即焚:先打码,点开才看
        h = Harness("动图", BASE + 79, [])
        try:
            h.win.sync_gifs()
        finally:
            h.core.stop()

    def test_video_poster_event(self):
        """发视频后封面跟着发过去;收到的人卡片上显示封面和时长;点封面 = 下载完自动播放。"""
        import tempfile
        from miyu import video
        jpeg = make_jpeg()
        calls = []

        class FakeProbe:
            def __init__(self, path, parent=None):
                calls.append(path)
                self.done = types.SimpleNamespace(connect=lambda cb: QTimer.singleShot(
                    0, lambda: cb({"thumb": jpeg, "dur": 61500, "w": 1280, "h": 720})))
        orig = video.VideoProbe
        video.VideoProbe = FakeProbe
        tmp = tempfile.mkdtemp()
        A = Harness("放映员", BASE + 80, [("127.0.0.1", BASE + 81)])
        B = Harness("观众", BASE + 81, [("127.0.0.1", BASE + 80)])
        try:
            self.assertTrue(pump_until([A, B], lambda: B.id in A.win.peers and A.win.peers[B.id].get("online")))
            A.win.select_conv("lobby")
            path = os.path.join(tmp, "旅行.mp4")
            with open(path, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypisom" + b"v" * 5000)
            A.win.send_files([path])
            self.assertEqual(calls, [path])
            mine = [x for x in A.conv("lobby").messages if x.file][-1]
            self.assertTrue(pump_until([A, B], lambda: any(x.file and x.file.get("thumb")
                                                             for x in B.conv("lobby").messages)))
            self.assertEqual(mine.file["dur"], 61500)
            got = [x for x in B.conv("lobby").messages if x.file][-1]
            self.assertEqual(video.clean_poster(got.file["thumb"]), jpeg)
            self.assertEqual((got.file["dur"], got.file["vw"], got.file["vh"]), (61500, 1280, 720))
            card = B.win.bubbles[got.mid].card if got.mid in B.win.bubbles else None
            if card is not None:
                self.assertEqual(card._poster_act, "dlplay")       # 还没下载:点封面 = 下载完自动播放
                self.assertIsNotNone(card.poster.pm)
            # 冒名顶替的封面不认(不是这条消息的发送者)
            B.win._ev_fthumb(B.conv("lobby"), {"peer": "f" * 64}, {"mid": got.mid, "fid": got.file["fid"],
                                                                    "thumb": video.b64(b"\xff\xd8\xff" + b"0" * 10)})
            self.assertEqual(video.clean_poster(got.file["thumb"]), jpeg)
            # 收到的封面要是小 JPEG
            self.assertIsNone(video.clean_poster(video.b64(b"\x89PNG\r\n\x1a\n" + b"0" * 20)))
            self.assertIsNone(video.clean_poster(video.b64(b"\xff\xd8\xff" + b"0" * (video.POSTER_RECV_MAX + 1))))
            # 点封面下载
            save = os.path.join(tmp, "下载的.mp4")
            orig_dlg = gui.QFileDialog.getSaveFileName
            orig_loc = gui.QStandardPaths.writableLocation
            gui.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (save, ""))
            gui.QStandardPaths.writableLocation = staticmethod(lambda *a: tmp)
            try:
                B.win.on_file_action(got, "dlplay")
            finally:
                gui.QFileDialog.getSaveFileName = orig_dlg
                gui.QStandardPaths.writableLocation = orig_loc
            tr = B.win.transfers[got.file["fid"]]
            self.assertTrue(tr.get("autoplay"))
            self.assertTrue(pump_until([A, B], lambda: tr.get("state") == "done", timeout=20))
            self.assertFalse(tr.get("autoplay"))                     # 下载完开始播放(测试里没有播放器)
        finally:
            video.VideoProbe = orig
            A.core.stop()
            B.core.stop()

    def test_mp4_scrub_and_history(self):
        import struct
        from miyu import storage, video

        def box(t, body):
            return struct.pack(">I", 8 + len(body)) + t + body
        mp4 = (box(b"ftyp", b"isom\x00\x00\x02\x00isom")
               + box(b"moov", box(b"mvhd", b"\x00\x00\x00\x00" + b"\xab" * 8 + b"\x00" * 88)
                     + box(b"udta", box(b"\xa9xyz", b"+25.0330+121.5654/")) + box(b"meta", b"iPhone 15"))
               + box(b"uuid", b"x" * 16 + b"<xmp/>") + box(b"mdat", b"frame" * 50))
        clean = video.scrub_mp4(mp4)
        self.assertEqual(len(clean), len(mp4))                      # 大小、位置都不变
        for secret in (b"+25.0330", b"iPhone", b"<xmp/>", b"\xab" * 8):
            self.assertNotIn(secret, clean)
        self.assertTrue(clean.endswith(box(b"mdat", b"frame" * 50)))
        self.assertIsNone(video.scrub_mp4(b"\x1aE\xdf\xa3" + b"\x00" * 40))
        self.assertIsNone(video.scrub_mp4(mp4[:50]))
        self.assertEqual(video.fmt_dur(83000), "1:23")
        # 匿名视频跟着聊天记录加密保存,重新打开还在
        m = gui.Msg("看这个", mid="a" * 32, sender="", nick="匿名纸条", anon=True,
                    file={"fid": "a" * 32, "name": "猫.mp4", "size": len(clean), "anon": True, "dur": 1000})
        m.vid = clean
        d = storage.msg_to_dict(m)
        self.assertEqual(storage.b64d(d["vid"]), clean)
        h = Harness("记录", BASE + 82, [])
        try:
            back = h.win.msg_from_dict(d)
            self.assertEqual(back.vid, clean)
            self.assertNotIn(back.file["fid"], h.win.transfers)       # 匿名视频不走文件传输
        finally:
            h.core.stop()


class GomokuNetTests(unittest.TestCase):
    """五子棋联网对战:房间、邀请、落子同步、悔棋 / 重新开始 / 再来一局、认输、掉线判负和确认、记录同步、排行榜一致。"""
    WIN = [(7, 7), (0, 0), (8, 7), (0, 1), (9, 7), (0, 2), (10, 7), (0, 3), (11, 7)]      # 黑第 9 手连五

    @classmethod
    def setUpClass(cls):
        from miyu.window import gomoku as G
        cls.G = G
        cls._ask = G.ask
        G.ask = lambda *a, **k: True
        ports = [BASE + 83, BASE + 84, BASE + 85]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.A = Harness("棋手甲", ports[0], mk(0))
        cls.B = Harness("棋手乙", ports[1], mk(1))
        cls.C = Harness("观众丙", ports[2], mk(2))
        cls.all = [cls.A, cls.B, cls.C]
        ok = pump_until(cls.all, lambda: all(len([p for p in h.win.peers.values() if p.get("online")]) >= 2
                                            for h in cls.all), timeout=30)
        assert ok, "三个节点没连上"

    @classmethod
    def tearDownClass(cls):
        cls.G.ask = cls._ask
        for h in cls.all:
            h.core.stop()

    def _start(self, color="b"):
        A, B = self.A, self.B
        for h in (A, B):
            if h.win.gm_live is not None:
                h.win.gm_live["over"] = True
                h.win.gm_live = None
            h.win.gm_ai = None
        A.win.gm_create_room("测试房", 60, color)
        rid = A.win.gm_my_room["rid"]
        self.assertTrue(pump_until(self.all, lambda: any(r["rid"] == rid for r in B.win.gm_rooms_list())))
        B.win.gm_join(rid)
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live is not None and B.win.gm_live is not None
                                   and A.win.gm_live["id"] == B.win.gm_live["id"]))
        self.assertIsNone(A.win.gm_my_room)                            # 有人加入,房间关掉
        return A.win.gm_live["id"]

    def _play(self, moves, first, second):
        for i, (x, y) in enumerate(moves):
            (first if i % 2 == 0 else second).win.gm_play(x, y)
            n = i + 1
            self.assertTrue(pump_until(self.all, lambda n=n: len(first.win.gm_live["res"]["moves"]) == n
                                       and len(second.win.gm_live["res"]["moves"]) == n), f"第 {n} 手没同步")

    def test_1_room_game_record_and_league(self):
        A, B, C = self.A, self.B, self.C
        mid = self._start("b")
        self.assertEqual(A.win.gm_live["me"], "b")
        self.assertEqual(B.win.gm_live["me"], "w")
        B.win.gm_play(5, 5)                                            # 不轮到乙:没反应
        pump_until(self.all, lambda: False, timeout=0.3)
        self.assertEqual(A.win.gm_live["res"]["moves"], [])
        self._play(self.WIN, A, B)
        for h in (A, B):
            self.assertTrue(h.win.gm_live["over"])
            self.assertEqual(h.win.gm_live["res"]["status"], "five")
        self.assertEqual(A.win.gm_view()["status_kind"], "win")
        self.assertEqual(B.win.gm_view()["status_kind"], "loss")
        # 记录发给了在线的所有人;三台电脑的排行榜一样
        self.assertTrue(pump_until(self.all, lambda: mid in C.win.gm_recs
                                   and C.win.gm_recs[mid]["acts"] == A.win.gm_recs[mid]["acts"]))
        boards = [[(r["id"], r["pts"], r["wins"]) for r in league_rows(h)] for h in self.all]
        self.assertEqual(boards[0], boards[1])
        self.assertEqual(boards[0], boards[2])
        top = league_rows(A)[0]
        self.assertEqual((top["id"], top["pts"]), (A.id, 3))
        # 重复收到同一步:不变;伪造的记录:不认
        rec = A.win.gm_recs[mid]
        B.win._gm_ev_act({"peer": A.id}, {"id": mid, "i": 0, "a": rec["acts"][0]})
        self.assertEqual(len(B.win.gm_recs[mid]["acts"]), 9)
        import json
        fake = json.loads(json.dumps(rec))
        fake["acts"][-1]["x"] = 3                                      # 改最后一步:签名对不上
        fake["id"] = "f" * 32
        C.win._gm_ev_recs({"peer": B.id}, {"recs": [fake]})
        self.assertTrue("f" * 32 not in C.win.gm_recs or C.win.gm_recs["f" * 32]["acts"] != fake["acts"])
        self.assertEqual(league_rows(C)[0]["pts"], 3)                  # 排行榜没被改
        # 再来一局:乙请求,甲同意 → 交换先后手
        B.win.gm_request("rematch")
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live["req_in"] is not None))
        A.win.gm_answer(True)
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live["id"] != mid and B.win.gm_live is not None
                                   and B.win.gm_live["id"] == A.win.gm_live["id"]))
        self.assertEqual(A.win.gm_live["me"], "w")
        self.assertEqual(B.win.gm_live["me"], "b")
        B.win.gm_resign()                                              # 一手没下就认输:不计分
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live["over"]))
        g = next(x for x in A.win.gm_games() if x["id"] == A.win.gm_live["id"])
        self.assertFalse(g["rated"])
        self.assertIn("不到 10 手", g["why"])

    def test_2_undo_restart_invite(self):
        A, B = self.A, self.B
        mid = self._start("b")
        self._play([(7, 7), (8, 8)], A, B)
        A.win.gm_request("undo")                                       # 轮到甲:退两手(乙的和甲的)
        self.assertTrue(pump_until(self.all, lambda: B.win.gm_live["req_in"] is not None))
        self.assertIn("悔棋", B.win.gm_view()["banner"])
        B.win.gm_answer(True)
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live["res"]["moves"] == []
                                   and B.win.gm_live["res"]["moves"] == []))
        self._play([(6, 6)], A, B)
        B.win.gm_request("undo")                                       # 乙没下过:不能悔
        self.assertIsNone(B.win.gm_live["req_out"])
        A.win.gm_request("undo")                                       # 甲刚下:退一手;乙拒绝
        self.assertTrue(pump_until(self.all, lambda: B.win.gm_live["req_in"] is not None))
        B.win.gm_answer(False)
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live["req_out"] is None))
        self.assertEqual(A.win.gm_live["res"]["moves"], [(6, 6)])
        B.win.gm_request("restart")                                    # 重新开始:这盘作废,颜色不变
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live["req_in"] is not None))
        A.win.gm_answer(True)
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live["id"] != mid
                                   and B.win.gm_live["id"] == A.win.gm_live["id"]))
        self.assertEqual(A.win.gm_recs[mid]["acts"][-1]["k"], "v")
        self.assertEqual(R_eval(A.win.gm_recs[mid])["status"], "void")
        self.assertEqual(A.win.gm_live["me"], "b")
        A.win.gm_leave()                                               # 退出 = 认输
        self.assertTrue(pump_until(self.all, lambda: B.win.gm_live["over"] and B.win.gm_live["left"]))
        self.assertFalse(B.win.gm_view()["buttons"]["rematch"])        # 对方走了:不能再来一局
        # 邀请:甲邀请乙,乙接受 → 甲开局
        B.win.gm_live = None
        A.win.gm_invite(B.id, 30, "w")
        self.assertTrue(pump_until(self.all, lambda: B.win.gm_inv_dialogs))
        iid, dlg = next(iter(B.win.gm_inv_dialogs.items()))
        dlg.choice = True
        B.win._gm_inv_done(iid, A.id, dlg)
        self.assertTrue(pump_until(self.all, lambda: A.win.gm_live is not None and B.win.gm_live is not None
                                   and A.win.gm_live["id"] == B.win.gm_live["id"] and not A.win.gm_live["over"]))
        self.assertEqual(A.win.gm_live["me"], "w")
        self.assertEqual(A.win.gm_live["rec"]["lim"], 30)

    def test_3_disconnect_claim_ack_and_dispute(self):
        A, B = self.A, self.B
        self._start("b")
        self._play([(7, 7), (8, 8), (7, 8)], A, B)
        # 乙一直在线:甲硬说乙掉线 → 乙的软件不认,这局不计分
        LA = A.win.gm_live
        LA["off_t"] = time.monotonic() - 200                           # 假装甲这边看到乙掉线很久了
        A.win.peers[B.id]["online"] = False
        A.win.gm_claim()
        A.win.peers[B.id]["online"] = True
        self.assertEqual(LA["res"]["status"], "abandon_pending")
        self.assertTrue(pump_until(self.all, lambda: B.win.gm_live["over"]))
        self.assertTrue(B.win.gm_live.get("disputed"))
        self.assertEqual(B.win.gm_live["res"]["status"], "abandon_pending")
        # 再来一盘:乙真的掉线了很久(回来后记得掉线时长)→ 乙的软件确认
        mid = self._start("b")
        self._play([(7, 7), (8, 8)], A, B)
        B.win.gm_live["last_off"] = 120.0
        LA = A.win.gm_live
        LA["off_t"] = time.monotonic() - 200
        A.win.peers[B.id]["online"] = False
        A.win.gm_claim()
        A.win.peers[B.id]["online"] = True
        self.assertTrue(pump_until(self.all, lambda: R_eval(A.win.gm_recs[mid])["status"] == "abandon"
                                   and R_eval(B.win.gm_recs[mid])["status"] == "abandon"))
        self.assertEqual(R_eval(A.win.gm_recs[mid])["winner"], "b")

    def test_4_resync_practice_and_window(self):
        A, B, C = self.A, self.B, self.C
        if not A.win.gm_recs:
            self.test_1_room_game_record_and_league()
        before = [(r["id"], r["pts"]) for r in league_rows(A)]
        C.win.gm_recs.clear()                                          # 丙的记录丢了:和别人一对就回来了
        C.win._gm_changed()
        C.win._peer_online_gomoku(A.id)
        self.assertTrue(pump_until(self.all, lambda: set(C.win.gm_recs) >= set(A.win.gm_recs)))
        self.assertEqual([(r["id"], r["pts"]) for r in league_rows(C)], before)
        # 人机练习
        from miyu.gomoku import ai as AI
        if A.win.gm_live is not None:
            A.win.gm_live["over"] = True
            A.win.gm_live = None
        A.win.gm_start_ai("easy", "b")
        for _ in range(120):
            S = A.win.gm_ai
            if S is None or S["over"]:
                break
            if S["thinking"]:
                QTimer.run_pending()
                continue
            x, y = AI.choose(S["board"], "hard")
            A.win.gm_play(x, y)
            QTimer.run_pending()
        self.assertTrue(A.win.gm_practice)
        self.assertIn(A.win.gm_practice[-1]["result"], ("win", "loss", "draw"))
        A.win.gm_request("rematch")                                    # 再来一局:换成执白
        self.assertEqual(A.win.gm_ai["me"], "w")
        QTimer.run_pending()                                           # 电脑执黑先下
        self.assertEqual(len(A.win.gm_ai["board"].moves), 1)
        A.win.gm_request("undo")                                       # 只有电脑那一手:不能悔
        self.assertEqual(len(A.win.gm_ai["board"].moves), 1)
        # 窗口:每一页都能画出来
        A.win.open_gomoku("lobby")
        win = A.win.gm_win
        for page in ("lobby", "game", "rank", "me"):
            win.go(page)
            win.refresh_all()
        win.pages["rank"].tabs.select("week")
        win.pages["rank"].tabs.select("today")
        win.pages["me"].filter.select("ai")
        win.pages["me"].filter.select("pvp")
        hist = A.win.gm_practice[-1]
        A.win.gm_replay("ai", hist)
        win.pages["game"].end_replay()
        A.win.gm_leave(quiet=True)
        win.toast("测试提示")
        self.assertTrue(A.win.gm_lobby_status() is not None)


class GomokuReconnectTests(GomokuNetTests):
    """掉线重连:中途丢了一步(网络断了),重新连上后自动同步,对局接着下;掉线期间计时暂停。"""

    def test_1_room_game_record_and_league(self):
        pass

    def test_2_undo_restart_invite(self):
        pass

    def test_3_disconnect_claim_ack_and_dispute(self):
        pass

    def test_4_resync_practice_and_window(self):
        pass

    def test_5_lost_move_resyncs(self):
        A, B = self.A, self.B
        self._start("b")
        self._play([(7, 7)], A, B)
        orig = B.win._gm_send
        dropped = []
        B.win._gm_send = lambda pid, name, data: dropped.append(name) or True if name == "gm_act" else orig(pid, name, data)
        try:
            B.win.gm_play(8, 8)                                        # 这一步在路上丢了
        finally:
            B.win._gm_send = orig
        self.assertEqual(dropped, ["gm_act"])
        pump_until(self.all, lambda: False, timeout=0.3)
        self.assertEqual(len(A.win.gm_live["res"]["moves"]), 1)
        # 甲这边看到乙掉线(计时暂停),然后又连上了
        A.win.peers[B.id]["online"] = False
        A.win._gm_live_tick(time.monotonic())
        self.assertIsNotNone(A.win.gm_live["off_t"])
        self.assertIn("掉线", A.win.gm_view()["status"])
        self.assertFalse(A.win.gm_view()["can_play"])
        clock_before = A.win.gm_clock_view()[1]["text"]
        A.win.peers[B.id]["online"] = True
        A.win._gm_live_tick(time.monotonic() + 30)                     # 掉线 30 秒:不算在计时里
        self.assertIsNone(A.win.gm_live["off_t"])
        self.assertTrue(pump_until(self.all, lambda: len(A.win.gm_live["res"]["moves"]) == 2))
        self.assertEqual(A.win.gm_live["res"]["moves"], B.win.gm_live["res"]["moves"])
        self.assertTrue(A.win.gm_view()["can_play"])                   # 轮到甲,接着下
        self.assertTrue(clock_before)
        A.win.gm_play(7, 8)
        self.assertTrue(pump_until(self.all, lambda: len(B.win.gm_live["res"]["moves"]) == 3))


def league_rows(h):
    from miyu.gomoku import league
    return league.standings(h.win.gm_games())


def R_eval(rec):
    from miyu.gomoku import record
    return record.evaluate(rec)


# ====================================================================== 2.4:扔东西 / 揍宠物 / 宠物排行榜 / 谁是坏鸭
class FunNetTests(unittest.TestCase):
    """三个人在大厅里:扔东西(连击合并、防刷、扔回去)、揍宠物(结果由主人决定、反击、关掉)、宠物名片和排行榜。"""

    @classmethod
    def setUpClass(cls):
        ports = [BASE + 86, BASE + 87, BASE + 88]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.A = Harness("扔扔甲", ports[0], mk(0))
        cls.B = Harness("挨扔乙", ports[1], mk(1))
        cls.C = Harness("围观丙", ports[2], mk(2))
        cls.all = [cls.A, cls.B, cls.C]
        assert pump_until(cls.all, lambda: all(len(h.win.lobby_members()) >= 2 for h in cls.all), timeout=30), "没连上"

    @classmethod
    def tearDownClass(cls):
        for h in cls.all:
            h.core.stop()

    def test_1_throw_combo_and_limits(self):
        A, B, C = self.A, self.B, self.C
        lobby = A.conv("lobby")
        A.win.select_conv(lobby) if hasattr(A.win, "select_conv") else None
        A.win._throw_sent.clear()
        self.assertTrue(A.win.throw_at(B.id, "tomato", lobby))
        self.assertTrue(pump_until(self.all, lambda: any("扔了一个番茄" in t for t in C.throws("lobby"))
                                   and any("向 你 扔了一个番茄" in t for t in B.throws("lobby"))))
        self.assertTrue(any("你 向" in t and "番茄" in t for t in A.throws("lobby")))
        self.assertFalse(A.win.throw_at(B.id, "tomato", lobby))       # 冷却中
        time.sleep(0.9)                                                # 别人那边:同一个人 0.8 秒内扔的第二下不显示
        A.win._throw_sent = [time.monotonic() - 5]
        self.assertTrue(A.win.throw_at(B.id, "tomato", lobby))
        ok = pump_until(self.all, lambda: any("扔了 2 个番茄" in t for t in C.throws("lobby")))
        self.assertTrue(ok, C.throws("lobby")[-5:] + [str(C.win._throw_recv), str(C.conv("lobby").messages[-1].text)])
        self.assertEqual(sum("番茄" in t for t in C.throws("lobby")), 1)          # 合并成一条
        self.assertEqual(B.win.throw_stats["hit_me"], 2)
        time.sleep(0.9)
        A.win._throw_sent = [time.monotonic() - 5]
        self.assertTrue(A.win.throw_at(B.id, "rose", lobby))
        self.assertTrue(pump_until(self.all, lambda: any("送给 你 一朵玫瑰" in t for t in B.throws("lobby"))))
        A.win._throw_sent = [time.monotonic() - 1] * THROW_LIMIT()
        self.assertFalse(A.win.throw_at(B.id, "egg", lobby))         # 一分钟扔太多
        self.assertFalse(A.win.throw_at(A.id, "egg", lobby))         # 不能扔自己
        self.assertFalse(A.win.throw_at(B.id, "brick", lobby))       # 没有这个道具
        # 别人那边:同一个人连着扔得太快的,直接丢掉
        time.sleep(0.9)
        before = len(C.throws("lobby"))
        A.win._throw_sent = []
        for item in ("egg", "snow"):
            A.win.core.send_event("lobby", None, "throw", {"to": B.id, "it": item, "c": 1})
        pump_until(self.all, lambda: False, timeout=0.6)
        self.assertEqual(len(C.throws("lobby")) - before, 1)
        # 被扔的人可以扔回去
        B.win._throw_sent.clear()
        pill = B.win._throw_pill
        self.assertIsNotNone(pill)
        B.win._throw_back(A.id, "tomato", B.conv("lobby"))
        self.assertTrue(pump_until(self.all, lambda: any("向 你 扔了一个番茄" in t for t in A.throws("lobby"))))
        # 卡片:内容、连击数、点一下重播
        m = next(x for x in reversed(C.conv("lobby").messages) if (x.card or {}).get("type") == "throw"
                 and x.card["item"] == "tomato" and x.card["from"] == A.id)
        self.assertEqual(m.card["to"], B.id)
        self.assertEqual(m.card["n"], 2)
        self.assertFalse(m.system)
        C.win.on_card_action(m, "replay", None)
        from miyu.cards import make_card, ThrowCard
        card = make_card(m, {"fresh": True})
        self.assertIsInstance(card, ThrowCard)
        card.update_state({"n": 3})
        self.assertEqual(card.stage.n, 3)
        lay = C.win.throw_layer
        self.assertIsNotNone(lay)
        self.assertTrue(lay.stages or lay.flying or lay.ghosts)

    def test_2_beat_pet_outcomes(self):
        A, B, C = self.A, self.B, self.C
        lobby = A.conv("lobby")
        A.win._beat_sent.clear()
        A.win._beat_times.clear()
        B.win._beat_recv.clear()
        B.win._beat_outcome = lambda rng=None: "hit"
        joy = B.win.pet_growth.joy
        self.assertTrue(A.win.beat_pet(B.id, "hammer", lobby))
        self.assertTrue(pump_until(self.all, lambda: any("用玩具锤揍了你的" in t for t in B.systems("lobby"))
                                   and any("用玩具锤揍了" in t for t in C.systems("lobby"))))
        self.assertTrue(any("你 用玩具锤揍了" in t for t in A.systems("lobby")))
        self.assertEqual(B.win.pet._hurt[0], "hammer")
        self.assertLess(B.win.pet_growth.joy, joy + 0.001)
        self.assertEqual(A.win._beat_pending, {})
        self.assertFalse(A.win.beat_pet(B.id, "fist", lobby))        # 冷却
        # 反击:揍的人自己的宠物挨一爪
        A.win._beat_sent.clear()
        B.win._beat_recv.clear()
        B.win._beat_outcome = lambda rng=None: "counter"
        self.assertTrue(A.win.beat_pet(B.id, "fist", lobby))
        self.assertTrue(pump_until(self.all, lambda: any("反被它揍了回去" in t for t in C.systems("lobby"))))
        pump_until(self.all, lambda: A.win.pet._hurt is not None and A.win.pet._hurt[0] == "paw", timeout=2)
        self.assertEqual(A.win.pet._hurt[:3:2], ("paw", "hit"))
        # 关掉之后揍不了,别人也看不到消息
        A.win._beat_sent.clear()
        B.win._beat_recv.clear()
        B.win.fun["pet_beat"] = False
        n_c = len(C.systems("lobby"))
        self.assertTrue(A.win.beat_pet(B.id, "flick", lobby))
        self.assertTrue(pump_until(self.all, lambda: any("关掉了宠物互动" in t for t in A.systems("lobby"))))
        self.assertEqual(len(C.systems("lobby")), n_c)
        B.win.fun["pet_beat"] = True
        # 冒充:丙替乙说结果 —— 没用
        A.win._beat_pending["fake01"] = {"to": B.id, "w": "fist", "conv": "lobby", "deadline": time.monotonic() + 5}
        C.win.core.send_event("lobby", None, "pbeat_r", {"id": "fake01", "by": A.id, "to": B.id, "w": "fist", "o": "hit"})
        pump_until(self.all, lambda: False, timeout=0.5)
        self.assertIn("fake01", A.win._beat_pending)
        A.win._beat_pending.clear()

    def test_3_pet_cards_and_rank(self):
        A, B, C = self.A, self.B, self.C
        A.win.pet_growth.xp = 30000
        B.win.pet_growth.xp = 12000
        C.win.pet_growth.xp = 30000
        for h in self.all:
            h.win.pr_broadcast()
        want = {A.id: 30000, B.id: 12000, C.id: 30000}
        self.assertTrue(pump_until(self.all, lambda: all(h.win.pr_cards.get(pid, {}).get("xp") == xp
                                                         for h in self.all for pid, xp in want.items() if pid != h.id)))
        rows = A.win.pr_rows(A.conv("lobby"), "level")
        self.assertEqual(len(rows), 3, rows)
        self.assertEqual(rows[0]["rank"], rows[1]["rank"])            # 甲丙同级同经验:并列
        self.assertEqual(rows[2]["id"], B.id)
        for h in self.all:                                            # 三台电脑排出来的一样
            self.assertEqual([(r["id"], r["rank"]) for r in h.win.pr_rows(h.conv("lobby"), "level")],
                             [(r["id"], r["rank"]) for r in rows])
        week = A.win.pr_rows(A.conv("lobby"), "week")
        self.assertTrue(all(r["gain"] >= 0 for r in week))
        # 丙冒充甲发名片 / 改了经验的转发:都收不下
        fake = dict(A.win.pr_my_card(), xp=999999, lv=30)
        C.win.core.send_event("lobby", None, "pcard", {"c": fake})
        C.win.core.send_event("lobby", None, "pcards", {"cs": [fake]})
        pump_until(self.all, lambda: False, timeout=0.5)
        self.assertEqual(B.win.pr_cards[A.id]["xp"], 30000)
        # 新人进群:转发我知道的名片(签名不变,照样能验)
        B.win.pr_cards.pop(C.id, None)
        A.win._group_sync_petrank(A.conv("lobby"), B.id)
        self.assertTrue(pump_until(self.all, lambda: C.id in B.win.pr_cards))
        # 存档 → 读档
        saved = A.win._save_petrank()["prank"]
        A2 = types.SimpleNamespace()
        from miyu.window.petrank import PetRankMixin
        PetRankMixin._init_petrank(A2)
        PetRankMixin._restore_petrank(A2, {"prank": saved}, {})
        self.assertEqual(set(A2.pr_cards), set(A.win.pr_cards))
        # 窗口
        A.win.open_pet_rank(A.conv("lobby"))
        win = A.win.pr_win
        for tab in ("week", "gpet", "level"):
            win.tabs.select(tab)
            win.refresh(force=True)
        self.assertIn("第", win.me_text.text() if hasattr(win.me_text, "text") else "第")


def THROW_LIMIT():
    from miyu.window.throws import THROW_PER_MIN
    return THROW_PER_MIN


class EnterFxTests(unittest.TestCase):
    """2.5 进群特效:刚进群的人把登场效果发给碰到的人;收到的人限频、可关、只在正看着这个群时放。"""

    @classmethod
    def setUpClass(cls):
        ports = [BASE + 98, BASE + 99]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.A = Harness("登场甲", ports[0], mk(0))
        cls.B = Harness("看戏乙", ports[1], mk(1))
        cls.all = [cls.A, cls.B]
        assert pump_until(cls.all, lambda: all(len(h.win.lobby_members()) >= 1 for h in cls.all), timeout=30), "没连上"

    @classmethod
    def tearDownClass(cls):
        for h in cls.all:
            h.core.stop()

    def test_1_newcomer_sends_choice(self):
        A, B = self.A, self.B
        B.win.select_conv("lobby")
        pump_until(self.all, lambda: False, timeout=0.8)            # 刚启动时互相发的登场效果先放完
        if B.win.enter_overlay is not None:
            B.win.enter_overlay.stop()
        B.win._enter_shown.clear()
        A.win.enter_fx = "lightning"
        A.win.note_entered("lobby", show_mine=False)
        A.win.sync_group_to(A.conv("lobby"), B.id)
        self.assertTrue(pump_until(self.all, lambda: A.id in B.win._enter_shown))
        ov = B.win.enter_overlay
        self.assertEqual(ov.fx, "lightning")
        self.assertIn("登场甲 来了", ov.text)
        # 同一个人 10 分钟内不再放
        t0 = ov.t0
        A.win.sync_group_to(A.conv("lobby"), B.id)
        pump_until(self.all, lambda: False, timeout=0.5)
        self.assertEqual(B.win.enter_overlay.t0, t0)
        # 进群超过 90 秒就不发了
        sent = []
        orig = A.win.core.send_event
        A.win.core.send_event = lambda *a, **k: sent.append(a[2])
        try:
            A.win._enter_t["lobby"] = time.monotonic() - 200
            A.win.sync_group_to(A.conv("lobby"), B.id)
            self.assertNotIn("enter", sent)
            A.win._enter_t["lobby"] = time.monotonic()
            A.win.enter_fx = "off"                                    # 选了"不放"
            A.win.sync_group_to(A.conv("lobby"), B.id)
            self.assertNotIn("enter", sent)
            A.win.enter_fx = "pet"
            A.win.sync_group_to(A.conv("lobby"), B.id)
            self.assertIn("enter", sent)
        finally:
            A.win.core.send_event = orig

    def test_2_receiver_rules(self):
        B = self.B
        conv = B.conv("lobby")
        B.win.select_conv("lobby")
        B.win._enter_shown.clear()
        if B.win.enter_overlay is not None:
            B.win.enter_overlay.stop()
        ev = lambda pid, data: B.win._ev_enter(conv, {"peer": pid, "nick": "小明"}, data)   # noqa: E731
        ev("p-1", {"fx": "炸弹"})                                     # 没有这个效果:不放
        self.assertNotIn("p-1", B.win._enter_shown)
        B.win.enter_see = False                                     # 关掉了别人的特效
        ev("p-2", {"fx": "stars"})
        self.assertNotIn("p-2", B.win._enter_shown)
        B.win.enter_see = True
        ev("p-3", {"fx": "pet", "sp": "dragon", "lv": "99", "wear": ["bow", 3]})   # 乱填的宠物数据换成默认
        self.assertIn("p-3", B.win._enter_shown)
        self.assertEqual(B.win.enter_overlay.fx, "pet")
        ev("p-5", {"fx": "stars"})                                   # 同时好几个人进群:排队一个一个放
        self.assertEqual([q[0] for q in B.win.enter_overlay.queue], ["stars"])
        B.win.select_conv("self")                                   # 没在看这个群:不放
        ev("p-4", {"fx": "stars"})
        self.assertNotIn("p-4", B.win._enter_shown)
        # 设置会记住
        B.win.set_enter_fx("petals")
        st = B.win.account_dict()["settings"]
        self.assertEqual((st["enter_fx"], st["enter_see"]), ("petals", True))
        B.win.enter_overlay.stop()


class DuckNetTests(unittest.TestCase):
    """谁是坏鸭:四个人联机。房间、加入、选颜色、改设置、开局身份保密、走路同步、刀人、报告、开会投票、结算、
    冒充房主无效、中途离开、邀请、单人试玩。房主的裁判循环在测试里手动推进(替身的计时器不会自己跑)。"""

    @classmethod
    def setUpClass(cls):
        from miyu.window import duck as D
        cls.D = D
        cls._ask = D.ask
        D.ask = lambda *a, **k: True
        ports = [BASE + 89, BASE + 90, BASE + 91, BASE + 92]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.hs = [Harness(n, ports[i], mk(i)) for i, n in enumerate(("房主甲", "鹅乙", "鹅丙", "鹅丁"))]
        cls.A, cls.B, cls.C, cls.Dd = cls.hs
        assert pump_until(cls.hs, lambda: all(len([p for p in h.win.peers.values() if p.get("online")]) >= 3
                                              for h in cls.hs), timeout=40), "四个节点没连上"

    @classmethod
    def tearDownClass(cls):
        cls.D.ask = cls._ask
        for h in cls.hs:
            h.core.stop()

    def pump(self, cond, timeout=10.0, host=None):
        host = host or self.A
        def step():
            host.win._dk_host_step()
            return cond()
        return pump_until(self.hs, step, timeout=timeout)

    def _room(self):
        A = self.A
        for h in self.hs:
            if h.win.dk_room is not None or h.win.dk_client is not None:
                h.win.dk_leave_room(quiet=True)
        pump_until(self.hs, lambda: False, timeout=0.3)
        self.assertTrue(A.win.dk_create_room("测试房"))
        rid = A.win.dk_room["id"]
        self.assertTrue(pump_until(self.hs, lambda: all(rid in h.win.dk_rooms for h in self.hs[1:])))
        for h in self.hs[1:]:
            self.assertTrue(h.win.dk_join(rid))
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.dk_room is not None and len(h.win.dk_room["members"]) == 4
                                                        for h in self.hs)))
        return rid

    def test_1_room_colors_settings_and_start(self):
        A, B, C, D = self.hs
        rid = self._room()
        colors = [m["color"] for m in A.win.dk_room["members"]]
        self.assertEqual(len(set(colors)), 4)
        taken = colors[0]
        B.win.dk_set_color(taken)                                      # 被人用了:不行
        pump_until(self.hs, lambda: False, timeout=0.4)
        self.assertNotEqual(next(m["color"] for m in A.win.dk_room["members"] if m["id"] == B.id), taken)
        B.win.dk_set_color("pink")
        self.assertTrue(pump_until(self.hs, lambda: all(next(m["color"] for m in h.win.dk_room["members"]
                                                             if m["id"] == B.id) == "pink" for h in self.hs)))
        C.win.dk_set_setting("discuss", 30)                            # 不是房主:改不了
        A.win.dk_set_setting("discuss", 0)
        A.win.dk_set_setting("vote", 30)
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.dk_room["s"]["discuss"] == 0 for h in self.hs)))
        self.assertFalse(B.win.dk_start())                             # 只有房主能开始
        self.assertTrue(A.win.dk_start())
        self.assertTrue(self.pump(lambda: all(h.win.dk_client is not None and h.win.dk_client.snaps >= 2
                                              for h in self.hs)))
        g = A.win.dk_game
        roles = {pid: p["role"] for pid, p in g.players.items()}
        self.assertEqual(sum(r == "duck" for r in roles.values()), 1)
        for h in self.hs:                                             # 每个人只知道自己的身份
            c = h.win.dk_client
            self.assertEqual(c.role, roles[h.id])
            self.assertEqual(len(c.roster), 4)
            self.assertEqual(c.host, A.id)
        self.assertEqual(A.win.dk_room["st"], "play")
        self.assertTrue(pump_until(self.hs, lambda: B.win.dk_rooms.get(rid, {}).get("st") == "play"))
        # 走路:乙往右走,房主那边收到位置
        cb = B.win.dk_client
        x0 = g.players[B.id]["x"]
        for _ in range(6):
            cb.step(1, 0, 0.05)
            B.win.dk_frame(0.1)
        self.assertTrue(self.pump(lambda: g.players[B.id]["x"] > x0 + 20))
        # 冒充房主发画面:不理
        cc = C.win.dk_client
        D.win.core.send_event("dm", C.id, "dk_st", {"ph": "over", "me": [0, 0, 999, 0]})
        D.win.core.send_event("dm", C.id, "dk_ev", {"evs": [{"e": "dead", "by": D.id}]})
        pump_until(self.hs, lambda: False, timeout=0.4)
        self.assertEqual(cc.phase, "play")
        self.assertTrue(cc.alive)
        self.assertNotEqual(cc.tp, 999)
        # 窗口的每一帧(替身里手动调用,检查不出错)
        for h in self.hs:
            gp = h.win.dk_win.pages["game"]
            gp.frame()
            gp.refresh_hud(h.win.dk_client, time.monotonic())

    def test_2_kill_report_vote_and_finish(self):
        A, B, C, D = self.hs
        if A.win.dk_game is None:
            self.test_1_room_colors_settings_and_start()
        g = A.win.dk_game
        hs_by = {h.id: h for h in self.hs}
        duck_id = next(pid for pid, p in g.players.items() if p["role"] == "duck")
        geese = [pid for pid, p in g.players.items() if p["role"] != "duck"]
        victim, finder = geese[0], geese[1]
        now = time.monotonic()
        for pid, (x, y) in ((duck_id, (1000, 700)), (victim, (1040, 700)), (finder, (1300, 900))):
            g.players[pid]["x"], g.players[pid]["y"] = float(x), float(y)
            g.players[pid]["tp"] += 1
        g.players[duck_id]["kill_at"] = now - 1
        self.assertTrue(self.pump(lambda: all(abs(hs_by[pid].win.dk_client.x - g.players[pid]["x"]) < 1
                                              for pid in (duck_id, victim, finder))))
        hs_by[duck_id].win.dk_action("kill", {"t": victim})
        self.assertTrue(self.pump(lambda: not hs_by[victim].win.dk_client.alive))
        self.assertEqual(hs_by[victim].win.dk_client.dead_by, duck_id)
        self.assertEqual(len(g.bodies), 1)
        # 离得远的人报告不了;走过去再报告
        fh = hs_by[finder]
        fh.win.dk_action("report", {})
        self.assertTrue(self.pump(lambda: g.phase == "play", timeout=1))
        g.players[finder]["x"], g.players[finder]["y"] = 1070.0, 720.0
        g.players[finder]["tp"] += 1
        self.assertTrue(self.pump(lambda: abs(fh.win.dk_client.x - 1070) < 1))
        fh.win.dk_action("report", {})
        self.assertTrue(self.pump(lambda: all(h.win.dk_client.phase == "meeting" for h in self.hs)))
        for h in self.hs:
            h.win.dk_win.pages["game"].frame()
        # 开会聊天:活人的话大家都看到;幽灵的话只有幽灵看到
        fh.win.dk_chat("我在尸体旁边看到了")
        hs_by[victim].win.dk_chat("我是被刀的那个")
        self.assertTrue(self.pump(lambda: all(any(m["text"] == "我在尸体旁边看到了" for m in h.win.dk_client.chat)
                                              for h in self.hs)))
        self.assertFalse(any(m["text"] == "我是被刀的那个" for m in fh.win.dk_client.chat))
        # 投票:都投坏鸭(坏鸭自己弃票)
        for pid, h in hs_by.items():
            if pid == victim:
                continue
            h.win.dk_vote("skip" if pid == duck_id else duck_id)
        self.assertTrue(self.pump(lambda: all(h.win.dk_client.phase in ("eject", "over") for h in self.hs)))
        self.assertTrue(self.pump(lambda: all(h.win.dk_client.over is not None for h in self.hs)))
        for h in self.hs:
            o = h.win.dk_client.over
            self.assertEqual(o["win"], "goose")
            self.assertEqual(o["roles"][duck_id], "duck")
            h.win.dk_win.pages["game"].frame()
        A.win._dk_over_t = time.monotonic() - 5
        A.win._dk_host_step()
        self.assertIsNone(A.win.dk_game)
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.dk_room["st"] == "wait" for h in self.hs)))
        for h in self.hs:
            h.win.dk_back_to_room()
            self.assertIsNone(h.win.dk_client)

    def test_3_leave_end_invite_and_practice(self):
        A, B, C, D = self.hs
        self._room()
        self.assertTrue(A.win.dk_start())
        self.assertTrue(self.pump(lambda: all(h.win.dk_client is not None for h in self.hs)))
        D.win.dk_leave_room(quiet=True)                                # 丁中途走了:当他出局
        self.assertTrue(self.pump(lambda: A.win.dk_game is None or A.win.dk_game.players[D.id]["left"]))
        self.assertTrue(self.pump(lambda: D.id in B.win.dk_client.gone or B.win.dk_client.over is not None))
        self.assertIsNone(D.win.dk_room)
        A.win.dk_leave_room(quiet=True)                                # 房主走了:房间解散
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.dk_room is None and h.win.dk_client is None
                                                        for h in self.hs)))
        # 邀请:丙开房间,邀请乙,乙(自动同意)进来
        C.win.dk_create_room("丙的房间")
        rid = C.win.dk_room["id"]
        C.win.dk_invite(B.id)
        self.assertTrue(pump_until(self.hs, lambda: B.win.dk_room is not None and B.win.dk_room["id"] == rid))
        self.assertFalse(C.win.dk_start())                             # 两个人不够
        C.win.dk_leave_room(quiet=True)
        pump_until(self.hs, lambda: B.win.dk_room is None)
        # 房间满了 / 已经开始:进不去
        A.win.dk_create_room("满员房")
        A.win.dk_room["members"] += [{"id": f"x{i}" * 8, "nick": "假人", "color": "white"} for i in range(9)]
        rid = A.win.dk_room["id"]
        A.win._dk_broadcast_room()
        pump_until(self.hs, lambda: rid in B.win.dk_rooms)
        B.win.dk_join(rid)
        self.assertTrue(pump_until(self.hs, lambda: B.win._dk_joining is None))
        self.assertIsNone(B.win.dk_room)
        A.win.dk_leave_room(quiet=True)
        # 单人试玩:做完任务就结束
        B.win.dk_practice()
        g = B.win.dk_game
        self.assertTrue(B.win.dk_practice_on)
        me = g.players[B.id]
        for t in me["tasks"]:
            from miyu.duck import world as Wd
            me["x"], me["y"] = float(Wd.TASK_BY_ID[t][3]), float(Wd.TASK_BY_ID[t][4])
            B.win.dk_client.x, B.win.dk_client.y = me["x"], me["y"]
            B.win.dk_action("task", {"t": t})
        B.win._dk_host_step()
        self.assertEqual(B.win.dk_client.over["win"], "goose")
        B.win.dk_quit_game()
        self.assertIsNone(B.win.dk_client)
        self.assertFalse(B.win.dk_practice_on)


class SpyNetTests(unittest.TestCase):
    """谁是卧底:四个人联机。房间、设置、开局每人只拿到自己的词、轮流描述、讨论、投票、揭晓、结算、冒充房主无效、离开。"""

    @classmethod
    def setUpClass(cls):
        from miyu.window import spy as S
        cls.S = S
        cls._ask = S.ask
        S.ask = lambda *a, **k: True
        ports = [BASE + 93, BASE + 94, BASE + 95, BASE + 96]
        mk = lambda i: [("127.0.0.1", p) for j, p in enumerate(ports) if j != i]  # noqa: E731
        cls.hs = [Harness(n, ports[i], mk(i)) for i, n in enumerate(("卧底房主", "卧底乙", "卧底丙", "卧底丁"))]
        assert pump_until(cls.hs, lambda: all(len([p for p in h.win.peers.values() if p.get("online")]) >= 3
                                              for h in cls.hs), timeout=40), "四个节点没连上"

    @classmethod
    def tearDownClass(cls):
        cls.S.ask = cls._ask
        for h in cls.hs:
            h.core.stop()

    def pump(self, cond, timeout=10.0):
        A = self.hs[0]
        def step():
            A.win._sp_host_step()
            return cond()
        return pump_until(self.hs, step, timeout=timeout)

    def test_1_full_game(self):
        A, B, C, D = self.hs
        self.assertTrue(A.win.sp_create_room("卧底测试房"))
        rid = A.win.sp_room["id"]
        self.assertTrue(pump_until(self.hs, lambda: all(rid in h.win.sp_rooms for h in self.hs[1:])))
        for h in self.hs[1:]:
            h.win.sp_join(rid)
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.sp_room and len(h.win.sp_room["members"]) == 4
                                                        for h in self.hs)))
        B.win.sp_set_setting("talk", 60)                               # 不是房主:改不了
        A.win.sp_set_setting("talk", 0)
        A.win.sp_set_setting("cat", "动物")
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.sp_room["s"]["talk"] == 0 and h.win.sp_room["s"]["cat"] == "动物"
                                                        for h in self.hs)))
        self.assertTrue(A.win.sp_start())
        self.assertTrue(self.pump(lambda: all(h.win.sp_client is not None and h.win.sp_client.states >= 1 for h in self.hs)))
        g = A.win.sp_game
        from miyu.spy import words as WB
        self.assertIn((g.civ_word, g.spy_word), {(a, b) for a, b, _ in WB.CATEGORIES["动物"]} |
                      {(b, a) for a, b, _ in WB.CATEGORIES["动物"]})
        by = {h.id: h for h in self.hs}
        for h in self.hs:                                             # 每个人只知道自己的词
            self.assertEqual(h.win.sp_client.word, g.word_for(h.id))
        spy = next(p for p, r in g.roles.items() if r == "spy")
        # 冒充房主发局面:不理
        cb = B.win.sp_client
        v = cb.version
        C.win.core.send_event("dm", B.id, "sp_st", {"v": 999, "ph": "over", "over": {"win": "spy"}})
        pump_until(self.hs, lambda: False, timeout=0.4)
        self.assertNotEqual(cb.phase, "over")
        # 轮流描述
        for _ in range(4):
            turn = A.win.sp_game.turn()
            h = by[turn]
            self.assertTrue(self.pump(lambda: h.win.sp_client.turn == turn))
            h.win.sp_win.pages["game"].frame()
            h.win.sp_action("say", {"text": f"描述{len(A.win.sp_game.said)}号"})
            self.assertTrue(self.pump(lambda: len(A.win.sp_game.said) >= 1 and A.win.sp_game.turn() != turn))
        self.assertTrue(self.pump(lambda: all(h.win.sp_client.phase == "vote" and len(h.win.sp_client.said) == 4
                                              for h in self.hs)))
        # 说出自己的词:被拒绝(房主回 sp_err)
        # 投票:都投卧底
        for pid, h in by.items():
            h.win.sp_win.pages["game"].frame()
            target = spy if pid != spy else next(p for p in by if p != spy)
            h.win.sp_vote(target)
        self.assertTrue(self.pump(lambda: all(h.win.sp_client.phase in ("reveal", "over") for h in self.hs)))
        A.win.sp_game.phase_end = 0                                    # 跳过揭晓动画
        self.assertTrue(self.pump(lambda: all(h.win.sp_client.over is not None for h in self.hs)))
        for h in self.hs:
            o = h.win.sp_client.over
            self.assertEqual(o["win"], "civ")
            self.assertEqual(o["roles"][spy], "spy")
            self.assertEqual(o["civ"], g.civ_word)
            h.win.sp_win.pages["game"].frame()
        A.win._sp_over_t = time.monotonic() - 10
        A.win._sp_host_step()
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.sp_room["st"] == "wait" for h in self.hs)))
        for h in self.hs:
            h.win.sp_back_to_room()

    def test_2_errors_and_leave(self):
        A, B, C, D = self.hs
        if A.win.sp_room is None:
            self.test_1_full_game()
        A.win.sp_set_setting("talk", 30)
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.sp_room["s"]["talk"] == 30 for h in self.hs)))
        self.assertTrue(A.win.sp_start())
        self.assertTrue(self.pump(lambda: all(h.win.sp_client is not None and h.win.sp_client.states >= 1
                                              and h.win.sp_client.gid == A.win.sp_game.gid for h in self.hs)))
        by = {h.id: h for h in self.hs}
        g = A.win.sp_game
        turn = g.turn()
        h = by[turn]
        h.win.sp_action("say", {"text": "就是" + g.word_for(turn)})
        if h is not A:
            pump_until(self.hs, lambda: False, timeout=0.5)
        self.assertEqual(len(g.said), 0)                               # 说出自己的词:不算
        other = next(x for x in self.hs if x.id != turn)
        other.win.sp_action("say", {"text": "抢着说"})
        pump_until(self.hs, lambda: False, timeout=0.3)
        self.assertEqual(len(g.said), 0)
        # 有人离开:轮到他时自动跳过;房主走了房间解散
        D.win.sp_leave_room(quiet=True)
        self.assertTrue(self.pump(lambda: D.id in A.win.sp_game.left if A.win.sp_game else True))
        self.assertTrue(self.pump(lambda: D.id not in B.win.sp_client.alive))
        A.win.sp_leave_room(quiet=True)
        self.assertTrue(pump_until(self.hs, lambda: all(h.win.sp_room is None and h.win.sp_client is None for h in self.hs)))
        # 邀请
        C.win.sp_create_room("丙的卧底房")
        rid = C.win.sp_room["id"]
        C.win.sp_invite(B.id)
        self.assertTrue(pump_until(self.hs, lambda: B.win.sp_room is not None and B.win.sp_room["id"] == rid))
        self.assertFalse(C.win.sp_start())                             # 两个人不够
        C.win.sp_leave_room(quiet=True)
        self.assertTrue(pump_until(self.hs, lambda: B.win.sp_room is None))


class VideoPlayerTests(unittest.TestCase):
    """2.5:播放器的画面比例 / 透明度 / 置顶 / 鼠标穿透,以及视频还在下载时边下边看。"""

    def setUp(self):
        import types
        from PySide6 import _base
        self._saved = {k: sys.modules.get(k) for k in ("PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets")}
        for name in self._saved:                         # 测试环境没有多媒体模块:临时塞一个替身
            mod = types.ModuleType(name)
            mod.__getattr__ = lambda n, mod=mod: (_ for _ in ()).throw(AttributeError(n)) if n.startswith("__") \
                else mod.__dict__.setdefault(n, type(n, (_base._Obj,), {}))
            sys.modules[name] = mod

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def test_ratio_math(self):
        from miyu.player import clean_prefs, ratio_rect
        (x, y, w, h), src = ratio_rect("keep", 1920, 1080, 1000, 1000)     # 原始比例:上下黑边
        self.assertEqual((x, w), (0, 1000))
        self.assertAlmostEqual(h, 562.5)
        self.assertAlmostEqual(y, (1000 - 562.5) / 2)
        (x, y, w, h), _ = ratio_rect("4:3", 1920, 1080, 1600, 900)          # 强制 4:3:左右黑边
        self.assertAlmostEqual(w / h, 4 / 3)
        self.assertEqual(h, 900)
        tgt, (sx, sy, sw, sh) = ratio_rect("fill", 1920, 1080, 1000, 1000)  # 铺满:左右裁掉
        self.assertEqual(tgt, (0, 0, 1000, 1000))
        self.assertAlmostEqual(sw, 1080)
        self.assertAlmostEqual(sx, (1920 - 1080) / 2)
        self.assertEqual(ratio_rect("stretch", 640, 480, 300, 100)[0], (0, 0, 300, 100))
        self.assertEqual(ratio_rect("21:9", 0, 0, 0, 0)[0], (0, 0, 0, 0))
        p = clean_prefs({"op": 0.05, "ratio": "nope", "top": "yes", "hover": False})
        self.assertEqual(p, {"op": 0.2, "ratio": "keep", "top": False, "hover": False})

    def test_player_controls(self):
        from miyu import player
        prefs = player.clean_prefs({"ratio": "16:9"})
        w = player.VideoPlayer(None, "/tmp/电影.mp4", prefs=prefs)
        self.assertIsNone(w.canvas)                       # 100% 不透明:用系统视频控件
        self.assertIn("16 : 9", w.ratio_btn.text())
        w.cycle_ratio()
        self.assertEqual(prefs["ratio"], "4:3")
        w._on_op_slider(60)                               # 调透明度:改成自己画画面
        self.assertAlmostEqual(prefs["op"], 0.6)
        self.assertIsNotNone(w.canvas)
        self.assertEqual(w.canvas.mode, "4:3")
        self.assertEqual(w.op_label.text(), "60%")
        w._on_op_slider(5)
        self.assertAlmostEqual(prefs["op"], 0.2)          # 最低 20%,不会完全看不见
        w.toggle_top()
        self.assertTrue(prefs["top"])
        player.info_ok = lambda parent: True
        w.set_passthrough(True)
        self.assertTrue(w.passthrough)
        w.set_passthrough(False)
        self.assertFalse(w.passthrough)
        self.assertFalse(w.streaming)
        w.stop()

    def test_stream_while_downloading(self):
        import tempfile
        from miyu import stream
        from miyu.widgets import Msg
        A = Harness("追剧的人", BASE + 97, [])
        try:
            tmp = tempfile.mkdtemp()
            dest = os.path.join(tmp, "一小时录屏.mp4")
            head = (24).to_bytes(4, "big") + b"ftypisom" + bytes(12) + (16).to_bytes(4, "big") + b"moov" + bytes(8)
            with open(dest + ".part", "wb") as f:
                f.write(head + bytes(stream.STREAM_MIN))
            fid = "b" * 32
            size = 3 * 1024 * 1024 * 1024
            m = Msg("", sender="p-x", nick="小明", file={"fid": fid, "name": "一小时录屏.mp4", "size": size})
            A.win._add_message(A.conv("lobby"), m)
            tr = A.win.transfers[fid] = {"state": "downloading", "done": 0, "path": dest, "size": size,
                                         "peer": "p-x", "stream": None}
            A.win._ev_file_progress({"fid": fid, "done": 1024, "total": size, "dir": "down"})
            self.assertIsNone(tr["stream"])               # 下得太少,还不判断
            A.win._ev_file_progress({"fid": fid, "done": len(head) + stream.STREAM_MIN, "total": size, "dir": "down"})
            self.assertTrue(tr["stream"])
            card = A.win.bubbles[m.mid].card
            self.assertEqual(card._poster_act, "stream")
            self.assertIn("边下边看", card.poster.sub)
            A.win.on_file_action(m, "stream")
            w = A.win.video_win
            self.assertIsNotNone(w)
            self.assertTrue(w.streaming and w.source.startswith("http://127.0.0.1:"))
            self.assertEqual(w.path, dest)
            frac, state = w.dl_info()
            self.assertEqual(state, "down")
            self.assertGreater(frac, 0)
            # 再点一次封面:同一个视频不重新打开(顺便取消穿透)
            A.win.on_file_action(m, "stream")
            self.assertIs(A.win.video_win, w)
            # 播放器设置会记住
            A.win.video_prefs["ratio"] = "4:3"
            self.assertEqual(A.win.account_dict()["settings"]["video"]["ratio"], "4:3")
            # 下完了:正在看的不重复弹播放器
            tr["autoplay"] = True
            A.win._ev_file_done({"fid": fid, "ok": True, "path": dest, "size": size})
            self.assertIs(A.win.video_win, w)
            A.win.close_video()
            # 索引在末尾的视频:提示要下完才能看
            fid2 = "c" * 32
            dest2 = os.path.join(tmp, "录像.mov")
            with open(dest2 + ".part", "wb") as f:
                f.write((24).to_bytes(4, "big") + b"ftypqt  " + bytes(12) + (16 + stream.STREAM_MIN).to_bytes(4, "big")
                        + b"mdat" + bytes(stream.STREAM_MIN + 8))
            m2 = Msg("", sender="p-x", nick="小明", file={"fid": fid2, "name": "录像.mov", "size": size})
            A.win._add_message(A.conv("lobby"), m2)
            tr2 = A.win.transfers[fid2] = {"state": "downloading", "done": 0, "path": dest2, "size": size,
                                           "peer": "p-x"}
            A.win._ev_file_progress({"fid": fid2, "done": stream.STREAM_MIN + 40, "total": size, "dir": "down"})
            self.assertIs(tr2["stream"], False)
            self.assertIn("要下完才能看", A.win.bubbles[m2.mid].card.poster.sub)
            self.assertEqual(A.win.bubbles[m2.mid].card._poster_act, "")
        finally:
            A.core.stop()
            stream.server().stop()


class BubbleFxTests(unittest.TestCase):
    """2.5 气泡动效:出场姿势、连发错开、动画期间先藏真气泡、播完一定放出来;旧设置迁移;回应弹一下。"""

    def test_pose(self):
        from miyu import bubblefx as bf
        for mode in ("soft", "lively"):
            for mine in (True, False):
                dx, dy, s, rot, op = bf.enter_pose(mode, 0.0, mine)
                self.assertEqual(op, 0.0)
                self.assertGreater(dy, 0)                               # 从下面浮上来
                self.assertEqual(dx > 0, mine)                          # 自己的从右边、别人的从左边
                self.assertLess(s, 1.0)
                end = bf.enter_pose(mode, 1.0, mine)
                self.assertEqual([round(x, 6) for x in end], [0, 0, 1, 0, 1])
        peak = max(bf.enter_pose("lively", k / 50, True)[2] for k in range(51))
        soft_peak = max(bf.enter_pose("soft", k / 50, True)[2] for k in range(51))
        self.assertGreater(peak, 1.0)                                    # 活泼:冲过头再弹回来
        self.assertLess(soft_peak, peak)                                 # 细腻:回弹幅度远小于活泼
        self.assertLessEqual(soft_peak, 1.02)

    def test_enter_hides_then_releases(self):
        from miyu import bubblefx as bf, motion

        class R:                                                         # 替身环境里的 QRect 不会算,换一个真的
            def __init__(self, pt, sz): self._w, self._h = sz
            def width(self): return self._w
            def height(self): return self._h
            def adjusted(self, *a): return self

        class PM:
            def isNull(self): return False

        class B:
            def __init__(self, mine): self.msg = type("M", (), {"mine": mine})(); self.upd = []
            def mapTo(self, *a): return (0, 0)
            def size(self): return (200, 40)
            def grab(self): return PM()
            def setUpdatesEnabled(self, v): self.upd.append(v)
            def update(self): pass

        orig_rect, orig_ghost = bf.QRect, bf._Ghost
        made = []

        class G:
            def __init__(self, parent, pm, rect, mine, mode, delay, done):
                self.delay, self.done_cb, self.mine = delay, done, mine
                made.append(self)
            def finish(self):
                cb, self.done_cb = self.done_cb, None
                if cb:
                    cb()
        bf.QRect, bf._Ghost = R, G
        try:
            fx = bf.BubbleFx()
            motion.ENABLED = True
            box = type("C", (), {"layout": lambda s: None})()
            done = []
            b1, b2, b3 = B(True), B(False), B(False)
            self.assertTrue(fx.enter(b1, box, lambda: done.append(1)))
            self.assertTrue(fx.enter(b2, box))
            self.assertTrue(fx.enter(b3, box))
            self.assertEqual([round(g.delay, 2) for g in made], [0, 0.07, 0.14])   # 连着来:一条接一条
            self.assertEqual(b1.upd, [False])                            # 动画期间先不画真气泡
            made[0].finish()
            self.assertEqual(b1.upd, [False, True])                      # 播完放出来
            self.assertEqual(done, [1])
            fx.clear()                                                   # 换会话:没播完的也马上放出来
            self.assertEqual((b2.upd[-1], b3.upd[-1]), (True, True))
            self.assertEqual(fx.ghosts, [])
            fx.mode = "off"
            self.assertFalse(fx.enter(B(True), box))
            fx.mode = "soft"
            motion.ENABLED = False                                       # 关了界面动效:也不播
            self.assertFalse(fx.enter(B(True), box))
        finally:
            bf.QRect, bf._Ghost = orig_rect, orig_ghost
            motion.ENABLED = True

    def test_legacy_setting_and_react_hook(self):
        from miyu.widgets import Bubble, Msg
        A = Harness("动效", BASE + 100, [])
        try:
            A.win._restore_settings({"settings": {"fun": {"pop": False}}})
            self.assertEqual(A.win.fun["bubble"], "off")                # 以前关掉了弹出动画 → 关闭
            A.win._restore_settings({"settings": {"fun": {"bubble": "lively"}}})
            self.assertEqual(A.win.fun["bubble"], "lively")
            A.win._restore_settings({"settings": {"fun": {"bubble": "乱填"}}})
            self.assertEqual(A.win.fun["bubble"], "soft")
            self.assertEqual(A.win.account_dict()["settings"]["fun"]["bubble"], "soft")
            # 回应变多时那个表情弹一下;刚建好的气泡不弹
            A.win.select_conv("lobby")
            m = Msg("好耶", sender="p-x", nick="小明")
            A.win._add_message(A.conv("lobby"), m)
            b = A.win.bubbles[m.mid]
            popped = []
            orig = Bubble.react_hook
            Bubble.react_hook = lambda chip, e: popped.append(e)
            try:
                from PySide6.QtCore import QTimer
                QTimer.pending.clear()
                b.set_reactions([("👍", 1, False, "小红")])
                QTimer.run_pending()
                self.assertEqual(popped, ["👍"])
                b.set_reactions([("👍", 1, False, "小红"), ("😂", 2, True, "我、小红")])
                QTimer.run_pending()
                self.assertEqual(popped, ["👍", "😂"])
                b.set_reactions([("😂", 1, True, "我")])               # 变少不弹
                QTimer.run_pending()
                self.assertEqual(popped, ["👍", "😂"])
            finally:
                Bubble.react_hook = orig
            # 撤回:不报错(替身环境里截不了图,直接换成提示)
            A.win._replace_with_notice(A.conv("lobby"), m, "小明 撤回了一条消息")
            self.assertTrue(any(x.system and "撤回" in x.text for x in A.conv("lobby").messages))
        finally:
            A.core.stop()
