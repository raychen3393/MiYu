"""
网络核心自动测试:在本机用 127.0.0.1 + 不同端口模拟多台电脑。
运行:python -m unittest tests.test_core -v
"""
import asyncio
import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from miyu import crypto as C          # noqa: E402
from miyu.core import Core            # noqa: E402

BASE_PORT = 52000 + (os.getpid() % 500) * 10


def wait_until(cond, timeout=20.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Node:
    def __init__(self, name, udp_port):
        self.name = name
        self.lock = threading.Lock()
        self.peers = {}
        self.messages = []
        self.sent = {}
        self.rooms = {}
        self.events = []
        self.core = Core(on_event=self.on_event, udp_port=udp_port, tcp_port=0)

    def on_event(self, kind, data):
        with self.lock:
            self.events.append((kind, data))
            if kind == "peer":
                self.peers[data["id"]] = data
            elif kind == "message":
                self.messages.append(data)
            elif kind == "sent":
                self.sent[data["mid"]] = data
            elif kind == "room_joined":
                self.rooms[data["name"]] = data["tag"]
            elif kind == "room_left":
                self.rooms = {k: v for k, v in self.rooms.items() if v != data["tag"]}

    def peer(self, other):
        with self.lock:
            return dict(self.peers.get(other.core.id_hex, {}))

    def online_with(self, other):
        return self.peer(other).get("online", False)

    def got(self, text, scope=None):
        with self.lock:
            return [m for m in self.messages if m["text"] == text and (scope is None or m["scope"] == scope)]


def make_nodes(names, lobby=None):
    lobby = lobby or {}
    ports = {n: BASE_PORT + i for i, n in enumerate(names)}
    nodes = {n: Node(n, ports[n]) for n in names}
    for n, node in nodes.items():
        node.core.extra_targets = [("127.0.0.1", p) for m, p in ports.items() if m != n]
    for n, node in nodes.items():
        assert node.core.start(nick=n, lobby=lobby.get(n, True)), node.core.start_error
    return nodes


class CryptoTests(unittest.TestCase):
    def test_beacon_roundtrip_and_tamper(self):
        ident = C.Identity()
        pkt = C.seal_beacon(C.LOBBY, ident, {"n": "甲", "tp": 1234, "up": 47820, "ts": int(time.time())})
        self.assertEqual(len(pkt), C.BEACON_WIRE_SIZE)
        body = C.open_beacon(C.LOBBY, pkt)
        self.assertEqual(body["id"], ident.pub)
        self.assertEqual(body["n"], "甲")
        bad = bytearray(pkt)
        bad[100] ^= 1
        self.assertIsNone(C.open_beacon(C.LOBBY, bytes(bad)))
        room = C.room_context("correct horse battery staple")
        self.assertIsNone(C.open_beacon(room, pkt))            # 别的密钥解不开

    def test_beacons_all_same_length_and_look_random(self):
        ident = C.Identity()
        room = C.room_context("abc123456")
        a = C.seal_beacon(C.LOBBY, ident, {"n": "x", "tp": 1, "up": 1, "ts": 1})
        b = C.seal_beacon(room, ident, {"n": "一个很长的昵称一个很长的昵称", "tp": 65535, "up": 65535, "ts": 2})
        self.assertEqual(len(a), len(b))
        self.assertNotIn(b"miyu", a + b)
        self.assertNotIn(ident.pub, a + b)

    def test_beacon_cannot_be_moved_to_another_room(self):
        # 知道两个暗号的人,也不能把 A 在大厅的广播"搬"到暗号群里冒充 A 在群里
        ident = C.Identity()
        room = C.room_context("room-pass-1")
        pkt = C.seal_beacon(C.LOBBY, ident, {"n": "a", "tp": 1, "up": 1, "ts": 1})
        inner = C.LOBBY._beacon_aead.decrypt(pkt[:12], pkt[12:], b"miyu-beacon-v1")
        moved = pkt[:12] + room._beacon_aead.encrypt(pkt[:12], inner, b"miyu-beacon-v1")
        self.assertIsNone(C.open_beacon(room, moved))

    def test_room_key_derivation(self):
        self.assertEqual(C.room_context("  同一个暗号 ").tag, C.room_context("同一个暗号").tag)
        self.assertNotEqual(C.room_context("暗号A").tag, C.room_context("暗号B").tag)
        r = C.room_context("暗号A")
        blob = C.seal_room_msg(r, {"text": "hi"})
        self.assertEqual(C.open_room_msg(r, blob)["text"], "hi")
        self.assertIsNone(C.open_room_msg(C.room_context("暗号B"), blob))

    def test_handshake_and_cipher(self):
        a, b = C.Handshake(), C.Handshake()
        sa, ra, ta = a.derive(b.e_pub, True)
        sb, rb, tb = b.derive(a.e_pub, False)
        self.assertEqual((sa, ra, ta), (rb, sb, tb))
        ea, db = C.Cipher(sa), C.Cipher(rb)
        ct = ea.encrypt(C.pad(b"hello"))
        self.assertEqual(C.unpad(db.decrypt(ct)), b"hello")
        ct2 = bytearray(ea.encrypt(C.pad(b"again")))
        ct2[5] ^= 1
        with self.assertRaises(C.CryptoError):
            db.decrypt(bytes(ct2))
        # 重放旧帧也会失败(计数器 nonce)
        db2 = C.Cipher(rb)
        db2.decrypt(ct)
        with self.assertRaises(C.CryptoError):
            db2.decrypt(ct)

    def test_padding_hides_length(self):
        self.assertEqual(len(C.pad(b"a")), len(C.pad(b"a" * 200)))
        self.assertEqual(C.unpad(C.pad("你好".encode())), "你好".encode())

    def test_safety_number_symmetric(self):
        a, b, c = C.Identity(), C.Identity(), C.Identity()
        self.assertEqual(C.safety_number(a.pub, b.pub), C.safety_number(b.pub, a.pub))
        self.assertNotEqual(C.safety_number(a.pub, b.pub), C.safety_number(a.pub, c.pub))
        self.assertEqual(len(C.safety_number(a.pub, b.pub).split()), 8)

    def test_presence_proof(self):
        r = C.room_context("p1")
        a, b = os.urandom(32), os.urandom(32)
        self.assertEqual(C.presence_proof(r, a, b), C.presence_proof(r, a, b))
        self.assertNotEqual(C.presence_proof(r, a, b), C.presence_proof(r, b, a))
        self.assertNotEqual(C.presence_proof(r, a, b), C.presence_proof(C.room_context("p2"), a, b))


class IdentityPersistTests(unittest.TestCase):
    def test_identity_seed_roundtrip(self):
        a = C.Identity()
        b = C.Identity(a.seed)
        self.assertEqual(len(a.seed), 32)
        self.assertEqual(a.pub, b.pub)
        sig = b.sign(b"hello")
        self.assertTrue(C.verify(a.pub, sig, b"hello"))
        self.assertNotEqual(C.Identity().pub, a.pub)

    def test_room_master_restores_same_room(self):
        ctx = C.room_context("correct horse battery staple")
        again = C.ContextKey(ctx.master)
        self.assertEqual(ctx.tag, again.tag)
        self.assertEqual(ctx.msg_key, again.msg_key)

    def test_restored_identity_and_room_on_network(self):
        p0 = BASE_PORT + 300
        a_ident = C.Identity()
        A = Node("A", p0)
        A.core = Core(on_event=A.on_event, udp_port=p0, tcp_port=0, identity=a_ident)
        B = Node("B", p0 + 1)
        A.core.extra_targets = [("127.0.0.1", p0 + 1)]
        B.core.extra_targets = [("127.0.0.1", p0)]
        try:
            self.assertTrue(A.core.start(nick="A", lobby=False))
            self.assertTrue(B.core.start(nick="B", lobby=False))
            self.assertEqual(A.core.identity.pub, a_ident.pub)
            ctx = C.room_context("暗号 恢复 测试 2026")
            # A 用保存的群密钥恢复,B 正常输入暗号
            A.core.restore_room(ctx.master, "老群")
            B.core.join_room("暗号 恢复 测试 2026", "新群")
            self.assertTrue(wait_until(lambda: "老群" in A.rooms and "新群" in B.rooms))
            self.assertEqual(A.rooms["老群"], B.rooms["新群"])
            joined = [d for k, d in A.events if k == "room_joined"][0]
            self.assertTrue(joined.get("restored"))
            self.assertEqual(C.b64d(joined["master"]), ctx.master)
            self.assertTrue(wait_until(lambda: A.online_with(B)))
            A.core.send_text("room", A.rooms["老群"], "恢复成功", 0)
            self.assertTrue(wait_until(lambda: B.got("恢复成功", "room")))
        finally:
            A.core.stop()
            B.core.stop()


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n = make_nodes(["A", "B", "C", "D"], lobby={"D": False})

    @classmethod
    def tearDownClass(cls):
        for node in cls.n.values():
            node.core.stop()

    def test_1_lobby_discovery_and_message(self):
        A, B, C_ = self.n["A"], self.n["B"], self.n["C"]
        self.assertTrue(wait_until(lambda: A.peer(B).get("lobby") and A.peer(C_).get("lobby")
                                   and B.peer(C_).get("lobby")), "大厅互相发现失败")
        mid = A.core.send_text("lobby", None, "大家好", 0)
        self.assertTrue(wait_until(lambda: B.got("大家好", "lobby") and C_.got("大家好", "lobby")))
        self.assertTrue(wait_until(lambda: A.sent.get(mid, {}).get("delivered") == 2))
        m = B.got("大家好")[0]
        self.assertEqual(m["nick"], "A")
        self.assertEqual(m["peer"], A.core.id_hex)

    def test_2_dm_only_to_target(self):
        A, B, C_ = self.n["A"], self.n["B"], self.n["C"]
        wait_until(lambda: A.online_with(B))
        A.core.send_text("dm", B.core.id_hex, "悄悄话", 30)
        self.assertTrue(wait_until(lambda: B.got("悄悄话", "dm")))
        self.assertEqual(B.got("悄悄话")[0]["burn"], 30)
        time.sleep(1)
        self.assertFalse(C_.got("悄悄话"))

    def test_3_rooms_and_invisible_member(self):
        A, B, C_, D = self.n["A"], self.n["B"], self.n["C"], self.n["D"]
        A.core.join_room("correct horse battery staple", "密室")
        B.core.join_room("correct horse battery staple", "我的群")
        C_.core.join_room("别的暗号 12345", "别的群")
        D.core.join_room("correct horse battery staple", "D的群")
        self.assertTrue(wait_until(lambda: "密室" in A.rooms and "我的群" in B.rooms and "D的群" in D.rooms
                                   and "别的群" in C_.rooms))
        tag = A.rooms["密室"]
        self.assertEqual(tag, B.rooms["我的群"])
        self.assertNotEqual(tag, C_.rooms["别的群"])

        self.assertTrue(wait_until(lambda: tag in A.peer(B).get("rooms", []) and tag in B.peer(A).get("rooms", [])))
        # D 没进大厅,只在暗号群里
        self.assertTrue(wait_until(lambda: tag in A.peer(D).get("rooms", []) and tag in B.peer(D).get("rooms", [])),
                        "隐身成员没有出现在暗号群里")
        self.assertFalse(A.peer(D).get("lobby"))
        # C 不在这个群,也看不到 A 在群里
        self.assertNotIn(tag, C_.peer(A).get("rooms", []))

        A.core.send_text("room", tag, "群里的秘密", 0)
        self.assertTrue(wait_until(lambda: B.got("群里的秘密", "room") and D.got("群里的秘密", "room")))
        self.assertEqual(B.got("群里的秘密")[0]["room"], tag)
        time.sleep(1.5)
        self.assertFalse(C_.got("群里的秘密"), "不在群里的人收到了群消息")

        # 大厅消息不会发给隐身的 D
        A.core.send_text("lobby", None, "大厅第二条", 0)
        self.assertTrue(wait_until(lambda: B.got("大厅第二条")))
        time.sleep(1)
        self.assertFalse(D.got("大厅第二条"))
        # C 和 D 没有任何共同空间,不应该连接
        self.assertFalse(C_.online_with(D))
        self.assertFalse(D.online_with(C_))

    def test_3b_images(self):
        A, B, C_, D = self.n["A"], self.n["B"], self.n["C"], self.n["D"]
        tag = A.rooms["密室"]

        def imgs(node, scope=None):
            with node.lock:
                return [m for m in node.messages if m.get("img") and (scope is None or m["scope"] == scope)]

        big = b"\xff\xd8\xff\xe0" + os.urandom(3 * 1024 * 1024)        # 3MB,会拆成分片
        self.assertIsNotNone(A.core.send_image("dm", B.core.id_hex, big, "image/jpeg", 0, 1920, 1080))
        A.core.send_text("dm", B.core.id_hex, "图片后面的一句话", 0)      # 大图传输中,文字照样能发
        self.assertTrue(wait_until(lambda: any(m["img"] == big for m in imgs(B, "dm")), timeout=30))
        self.assertTrue(wait_until(lambda: B.got("图片后面的一句话")))
        m = [m for m in imgs(B, "dm") if m["img"] == big][0]
        self.assertEqual((m["mime"], m["w"], m["h"], m["text"]), ("image/jpeg", 1920, 1080, ""))

        png = b"\x89PNG\r\n\x1a\n" + os.urandom(5000)
        A.core.send_image("room", tag, png, "image/png", 10)
        self.assertTrue(wait_until(lambda: any(m["img"] == png for m in imgs(B, "room"))
                                   and any(m["img"] == png for m in imgs(D, "room"))))
        self.assertEqual([m for m in imgs(B, "room") if m["img"] == png][0]["burn"], 10)
        time.sleep(1)
        self.assertFalse(imgs(C_), "不在群里的人收到了群图片")

        # 发送端拒绝:不是图片 / 太大 / 类型对不上
        self.assertIsNone(A.core.send_image("dm", B.core.id_hex, b"hello world", "image/jpeg"))
        self.assertIsNone(A.core.send_image("dm", B.core.id_hex, b"\xff\xd8\xff" + bytes(9 * 1024 * 1024), "image/jpeg"))
        self.assertIsNone(A.core.send_image("dm", B.core.id_hex, png, "image/jpeg"))
        self.assertIsNone(A.core.send_image("dm", B.core.id_hex, b"\xff\xd8\xff" + bytes(10), "text/html"))

    def test_3c_malformed_parts_rejected(self):
        # 已认证的连接发来不合规的分片 → 对方直接断开,不会无限占内存
        A, B = self.n["A"], self.n["B"]
        fut = asyncio.run_coroutine_threadsafe(self._bad_parts(A.core, B.core.tcp_port, B.core.my_id), A.core.loop)
        self.assertEqual(fut.result(15), "closed")
        # 测试里借用了 A 的身份,B 会断开 A;等 A 自动重连
        self.assertTrue(wait_until(lambda: B.peer(A).get("lobby") and A.peer(B).get("lobby"), timeout=25))
        A.core.send_text("lobby", None, "分片攻击之后", 0)
        self.assertTrue(wait_until(lambda: B.got("分片攻击之后")))

    @staticmethod
    async def _bad_parts(core, port, peer_id):
        from miyu.core import Conn
        r, w = await asyncio.open_connection("127.0.0.1", port)
        conn = Conn(core, r, w, initiator=True)
        try:
            await asyncio.wait_for(conn.handshake(expected_id=peer_id, hello_ctx=C.LOBBY), 5)
            await conn._send_frame(C.canonical({"t": "part", "x": "abc", "i": 0, "n": 100000, "d": "AAAA"}))
            while True:
                await asyncio.wait_for(conn.recv(), 5)
        except (asyncio.IncompleteReadError, ConnectionError):
            return "closed"
        except asyncio.TimeoutError:
            return "still open"
        finally:
            conn.closed = True
            w.close()

    def _events(self, node, kind):
        with node.lock:
            return [d for k, d in node.events if k == kind]

    def test_3d_files(self):
        import tempfile
        A, B, C_, D = self.n["A"], self.n["B"], self.n["C"], self.n["D"]
        tag = A.rooms["密室"]
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "报告 v2.bin")
        payload = os.urandom(3 * 1024 * 1024 + 12345)          # 3MB,很多块
        with open(src, "wb") as f:
            f.write(payload)

        # 私聊发文件:B 收到邀请 → 下载 → 内容一致
        mid, fid, info = A.core.send_file("dm", B.core.id_hex, src)
        self.assertEqual((info["name"], info["size"]), ("报告 v2.bin", len(payload)))
        self.assertTrue(wait_until(lambda: any(m.get("file") and m["file"]["fid"] == fid for m in B.messages)))
        offer = [m for m in B.messages if m.get("file") and m["file"]["fid"] == fid][0]
        dest = os.path.join(tmp, "b_received.bin")
        self.assertTrue(B.core.download_file(offer["peer"], fid, dest, offer["file"]["size"]))
        self.assertTrue(wait_until(lambda: any(d["fid"] == fid for d in self._events(B, "file_done")), timeout=30))
        done = [d for d in self._events(B, "file_done") if d["fid"] == fid][0]
        self.assertTrue(done["ok"], done)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertFalse(os.path.exists(dest + ".part"))
        self.assertTrue(any(d.get("finished") and d["fid"] == fid for d in self._events(A, "file_progress")))

        # 群文件:群成员能下,群外的人伪造请求拿不到
        _, rfid, _ = A.core.send_file("room", tag, src)
        self.assertTrue(wait_until(lambda: any(m.get("file") and m["file"]["fid"] == rfid for m in D.messages)))
        dest2 = os.path.join(tmp, "d_received.bin")
        D.core.download_file(A.core.id_hex, rfid, dest2, len(payload))
        self.assertTrue(wait_until(lambda: any(d["fid"] == rfid and d["ok"] for d in self._events(D, "file_done")),
                                   timeout=30))
        dest3 = os.path.join(tmp, "c_steal.bin")
        C_.core.download_file(A.core.id_hex, rfid, dest3, len(payload))   # C 不在这个群
        self.assertTrue(wait_until(lambda: any(d["fid"] == rfid for d in self._events(C_, "file_done"))))
        self.assertFalse([d for d in self._events(C_, "file_done") if d["fid"] == rfid][0]["ok"])
        self.assertFalse(os.path.exists(dest3))
        self.assertFalse(os.path.exists(dest3 + ".part"))

        # 取消下载:半截文件被删除
        big = os.path.join(tmp, "big.bin")
        with open(big, "wb") as f:
            f.write(os.urandom(40 * 1024 * 1024))
        _, bfid, _ = A.core.send_file("dm", B.core.id_hex, big)
        self.assertTrue(wait_until(lambda: any(m.get("file") and m["file"]["fid"] == bfid for m in B.messages)))
        dest4 = os.path.join(tmp, "b_big.bin")
        A.core.test_upload_delay = 0.05
        B.core.download_file(A.core.id_hex, bfid, dest4, 40 * 1024 * 1024)
        self.assertTrue(wait_until(lambda: any(d["fid"] == bfid and d["done"] > 0 for d in self._events(B, "file_progress"))))
        B.core.cancel_file(bfid)
        self.assertTrue(wait_until(lambda: any(d["fid"] == bfid for d in self._events(B, "file_done"))))
        self.assertFalse(os.path.exists(dest4))
        self.assertTrue(wait_until(lambda: not os.path.exists(dest4 + ".part")))
        self.assertTrue(wait_until(lambda: not A.core.uploads))
        A.core.test_upload_delay = 0.0

        # 撤回文件后,对方就下载不了了
        _, xfid, _ = A.core.send_file("dm", B.core.id_hex, src)
        self.assertTrue(wait_until(lambda: any(m.get("file") and m["file"]["fid"] == xfid for m in B.messages)))
        xmid = [m for m in B.messages if m.get("file") and m["file"]["fid"] == xfid][0]["mid"]
        A.core.recall("dm", B.core.id_hex, xmid)
        self.assertTrue(wait_until(lambda: any(d["target"] == xmid for d in self._events(B, "recall"))))
        B.core.download_file(A.core.id_hex, xfid, os.path.join(tmp, "x.bin"), len(payload))
        self.assertTrue(wait_until(lambda: any(d["fid"] == xfid and not d["ok"] for d in self._events(B, "file_done"))))

    def test_3d2_resume_and_speed(self):
        import tempfile
        A, B = self.n["A"], self.n["B"]
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "big.bin")
        payload = os.urandom(60 * 1024 * 1024)
        with open(src, "wb") as f:
            f.write(payload)
        _, fid, info = A.core.send_file("dm", B.core.id_hex, src)
        self.assertTrue(wait_until(lambda: any(m.get("file") and m["file"]["fid"] == fid for m in B.messages)))
        dest = os.path.join(tmp, "got.bin")

        def done_events():
            return [d for d in self._events(B, "file_done") if d["fid"] == fid]

        # 1) 暂停:半截文件保留(测试里给发送端放慢一点,不然本机太快来不及暂停)
        A.core.test_upload_delay = 0.03
        B.core.download_file(A.core.id_hex, fid, dest, info["size"])
        self.assertTrue(wait_until(lambda: any(d["fid"] == fid and d["done"] > 5 * 1024 * 1024
                                               for d in self._events(B, "file_progress"))))
        B.core.pause_file(fid)
        self.assertTrue(wait_until(lambda: len(done_events()) >= 1))
        self.assertTrue(done_events()[-1]["paused"])
        part = dest + ".part"
        self.assertTrue(os.path.exists(part))
        first = os.path.getsize(part)
        self.assertTrue(0 < first < info["size"])
        self.assertTrue(wait_until(lambda: not A.core.uploads))

        # 2) 继续:从断点接着下(进度事件从断点开始)
        B.core.download_file(A.core.id_hex, fid, dest, info["size"])
        self.assertTrue(wait_until(lambda: any(d["fid"] == fid and d.get("resumed") for d in self._events(B, "file_progress"))))
        resumed_at = [d for d in self._events(B, "file_progress") if d["fid"] == fid and d.get("resumed")][-1]["done"]
        self.assertEqual(resumed_at, first)
        # 3) 中途断网:保留断点
        self.assertTrue(wait_until(lambda: any(d["fid"] == fid and d["done"] > first + 5 * 1024 * 1024
                                               for d in self._events(B, "file_progress"))))
        conn = B.core.peers[A.core.my_id].conn
        B.core.loop.call_soon_threadsafe(conn.close)
        self.assertTrue(wait_until(lambda: len(done_events()) >= 2))
        self.assertTrue(done_events()[-1]["paused"])
        second = os.path.getsize(part)
        self.assertGreater(second, first)
        # 4) 重新连上后再继续,一直到完成,内容完全一致
        self.assertTrue(wait_until(lambda: B.online_with(A) and A.online_with(B), timeout=25))
        A.core.test_upload_delay = 0.0
        t0 = time.time()
        B.core.download_file(A.core.id_hex, fid, dest, info["size"])
        self.assertTrue(wait_until(lambda: any(d.get("ok") for d in done_events()), timeout=60))
        elapsed = time.time() - t0
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)
        self.assertFalse(os.path.exists(part))
        speed = (info["size"] - second) / max(elapsed, 0.001) / 1024 / 1024
        print(f"\n    本机回环传输速度约 {speed:.0f} MB/s")
        self.assertGreater(speed, 5)          # 正常约 200MB/s;门槛放低,避免机器偶尔卡一下就误报

    def test_3f_events_cards_anon(self):
        A, B, C_, D = self.n["A"], self.n["B"], self.n["C"], self.n["D"]
        self.assertTrue(wait_until(lambda: A.online_with(B) and A.online_with(C_)))
        # 事件:私聊
        self.assertTrue(A.core.send_event("dm", B.core.id_hex, "poke", {"x": 1}))
        self.assertTrue(wait_until(lambda: any(d["ev"] == "poke" and d["peer"] == A.core.id_hex
                                               for d in self._events(B, "ev"))))
        self.assertFalse(any(d["ev"] == "poke" for d in self._events(C_, "ev")))
        # 事件:大厅里只发给某一个人
        A.core.send_event("lobby", None, "sync", {"v": 2}, to=C_.core.id_hex)
        self.assertTrue(wait_until(lambda: any(d["ev"] == "sync" for d in self._events(C_, "ev"))))
        time.sleep(0.5)
        self.assertFalse(any(d["ev"] == "sync" for d in self._events(B, "ev")))
        self.assertFalse(A.core.send_event("dm", B.core.id_hex, "x" * 30, {}))
        # 卡片消息 + 气泡皮肤
        mid = A.core.send_card("lobby", None, {"type": "dice", "v": 5})
        self.assertTrue(wait_until(lambda: any(m["mid"] == mid and m["card"]["v"] == 5 for m in B.messages)))
        self.assertIsNone(A.core.send_card("lobby", None, {"type": "virus"}))
        A.core.send_text("lobby", None, "带皮肤", skin="galaxy")
        self.assertTrue(wait_until(lambda: any(m["text"] == "带皮肤" and m["skin"] == "galaxy" for m in B.messages)))
        # 匿名纸条:大厅里 A、B、C 三个人(D 隐身不在大厅)
        nid = A.core.send_anon("lobby", None, "我是谁你猜")
        self.assertIsNotNone(nid)
        for node in (B, C_):
            self.assertTrue(wait_until(lambda node=node: any(m.get("anon") and m["text"] == "我是谁你猜"
                                                             for m in node.messages)))
            got = [m for m in node.messages if m.get("anon")][0]
            self.assertEqual((got["peer"], got["nick"]), ("", "匿名纸条"))
        time.sleep(0.5)
        self.assertFalse(any(m.get("anon") for m in A.messages))       # 作者自己不会再收到一份
        self.assertFalse(any(m.get("anon") for m in D.messages))
        self.assertIsNone(A.core.send_anon("dm", B.core.id_hex, "私聊不能匿名"))
        # 2.1:带附件的纸条。替作者发出的人(B)把附件只发给新版本;旧版本(这里假装 C 是)收到一句文字说明
        from miyu.core import anon_media_wire, clean_anon_media
        gif = b"GIF89a" + b"\x01\x00\x01\x00\x00\x00\x00" + b"\x3b"
        fwd, show = clean_anon_media(anon_media_wire({"k": "img", "data": gif, "mime": "image/gif", "w": 1, "h": 1}))
        self.assertEqual(show["img"], gif)
        pc = B.core._peer_by_hex(C_.core.id_hex)
        saved = set(pc.caps)
        self.assertIn("am", saved)                                   # 在场信息里带着新能力
        pc.caps = set()
        nid2 = "e" * 32
        B.core._submit(B.core._anon_deliver("lobby", None, {"id": nid2, "text": "", "hop": 1, "m": fwd}))
        self.assertTrue(wait_until(lambda: any(m["mid"] == nid2 for m in C_.messages)))
        self.assertTrue(wait_until(lambda: any(m["mid"] == nid2 for m in A.messages)))
        pc.caps = saved
        old = next(m for m in C_.messages if m["mid"] == nid2)
        self.assertIsNone(old["img"])
        self.assertIn("[动图]", old["text"])
        new = next(m for m in A.messages if m["mid"] == nid2)
        self.assertEqual((new["img"], new["mime"], new["text"]), (gif, "image/gif", ""))
        # 坏掉的附件:整张纸条不认
        self.assertIsNone(clean_anon_media({"k": "vid", "d": "AAAA"}))
        self.assertIsNone(clean_anon_media({"k": "img", "d": "!!", "mime": "image/png"}))
        self.assertIsNone(clean_anon_media({"k": "exe", "d": "AAAA"}))

    def test_3e_reply_at_recall_typing_read(self):
        A, B, D = self.n["A"], self.n["B"], self.n["D"]
        tag = A.rooms["密室"]
        reply = {"mid": "m-original", "nick": "B", "preview": "原来那句话\n第二行"}
        mid = A.core.send_text("room", tag, "@B 收到", 0, reply=reply, at=[B.core.id_hex, "bogus"])
        self.assertTrue(wait_until(lambda: B.got("@B 收到")))
        m = B.got("@B 收到")[0]
        self.assertEqual(m["reply"], {"mid": "m-original", "nick": "B", "preview": "原来那句话 第二行"})
        self.assertEqual(m["at"], [B.core.id_hex])
        self.assertTrue(wait_until(lambda: D.got("@B 收到")))
        # 撤回(群里)
        A.core.recall("room", tag, mid)
        self.assertTrue(wait_until(lambda: any(d["target"] == mid and d["room"] == tag for d in self._events(B, "recall"))))
        self.assertTrue(wait_until(lambda: any(d["target"] == mid for d in self._events(D, "recall"))))
        # 正在输入 / 已读(私聊)
        A.core.send_typing(B.core.id_hex)
        self.assertTrue(wait_until(lambda: any(d["peer"] == A.core.id_hex for d in self._events(B, "typing"))))
        B.core.send_read(A.core.id_hex, ["m1", "m2", 123])
        self.assertTrue(wait_until(lambda: any(d["mids"] == ["m1", "m2"] for d in self._events(A, "read"))))

    def test_4_leave_room(self):
        A, B, D = self.n["A"], self.n["B"], self.n["D"]
        tag = A.rooms["密室"]
        B.core.leave_room(B.rooms["我的群"])
        self.assertTrue(wait_until(lambda: tag not in A.peer(B).get("rooms", ["x"])))
        self.assertTrue(A.peer(B).get("online"), "退群后在大厅里应该仍然在线")
        A.core.send_text("room", tag, "B 退群之后", 0)
        self.assertTrue(wait_until(lambda: D.got("B 退群之后")))
        time.sleep(1)
        self.assertFalse(B.got("B 退群之后"))
        # D 退群后和大家没有任何共同空间 → 断开
        D.core.leave_room(D.rooms["D的群"])
        self.assertTrue(wait_until(lambda: not A.online_with(D) and not B.online_with(D)))
        time.sleep(4)
        self.assertFalse(A.online_with(D), "不该重新连上")

    def test_5_rejoin_and_nick_change(self):
        A, B = self.n["A"], self.n["B"]
        B.core.join_room("correct horse battery staple", "回来了")
        tag = A.rooms["密室"]
        self.assertTrue(wait_until(lambda: tag in A.peer(B).get("rooms", [])))
        B.core.set_nick("小B")
        self.assertTrue(wait_until(lambda: A.peer(B).get("nick") == "小B", timeout=15))

    def test_6_lobby_toggle(self):
        A, C_ = self.n["A"], self.n["C"]
        self.assertTrue(wait_until(lambda: A.peer(C_).get("lobby")))
        C_.core.set_lobby(False)          # C 只剩一个和 A 无关的暗号群 → 断开
        self.assertTrue(wait_until(lambda: not A.online_with(C_)))
        C_.core.set_lobby(True)
        self.assertTrue(wait_until(lambda: A.peer(C_).get("lobby"), timeout=25))

    def test_7_scanner_and_garbage_rejected(self):
        A = self.n["A"]
        self.assertFalse(A.core._ip_allowed("10.9.8.7"))
        self.assertTrue(A.core._ip_allowed("127.0.0.1"))
        # 扫描器连进来发随机数据:对方一个字节都不回,直接断开
        s = socket.create_connection(("127.0.0.1", A.core.tcp_port), timeout=3)
        s.sendall(os.urandom(48) + b"\x00\x00\x01\x00" + os.urandom(256))
        s.settimeout(3)
        try:
            data = s.recv(100)
        except (ConnectionResetError, socket.timeout):
            data = b""
        s.close()
        self.assertEqual(data, b"")
        time.sleep(0.5)
        A.core.send_text("lobby", None, "还活着", 0)
        self.assertTrue(wait_until(lambda: self.n["B"].got("还活着")))

    def test_8_impersonation_rejected(self):
        # 握手时对方身份必须和广播里的一致
        A, B = self.n["A"], self.n["B"]
        fut = asyncio.run_coroutine_threadsafe(self._connect_expect(A.core, B.core.tcp_port, os.urandom(32)), A.core.loop)
        self.assertEqual(fut.result(15), "rejected")

    def test_8b_invisible_node_silent_to_lobby(self):
        # D 关闭了大厅、也不在任何群:拿大厅密钥去连 D,D 不回任何东西
        A, D = self.n["A"], self.n["D"]
        fut = asyncio.run_coroutine_threadsafe(
            self._connect_expect(A.core, D.core.tcp_port, None), A.core.loop)
        self.assertEqual(fut.result(15), "rejected")

    @staticmethod
    async def _connect_expect(core, port, wrong_id):
        from miyu.core import Conn
        r, w = await asyncio.open_connection("127.0.0.1", port)
        conn = Conn(core, r, w, initiator=True)
        try:
            await asyncio.wait_for(conn.handshake(expected_id=wrong_id, hello_ctx=C.LOBBY), 5)
            return "accepted"
        except (C.CryptoError, asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError):
            return "rejected"
        finally:
            conn.closed = True
            w.close()

    def test_9_bye_marks_offline(self):
        A, C_ = self.n["A"], self.n["C"]
        self.assertTrue(wait_until(lambda: A.online_with(C_), timeout=25))
        C_.core.stop()
        self.assertTrue(wait_until(lambda: not A.online_with(C_), timeout=5), "退出后没有立即显示离线")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class LazyImportCompatTests(unittest.TestCase):
    """模拟 Python 3.15 打包后的情况:concurrent.futures.ThreadPoolExecutor 是个不能调用的占位对象。"""

    def test_room_and_files_with_broken_threadpool_name(self):
        import asyncio
        import concurrent.futures as cf
        import tempfile
        from miyu import compat
        real = cf.ThreadPoolExecutor

        class lazy_import:                           # 和用户报错里同名的占位对象
            pass
        cf.ThreadPoolExecutor = lazy_import()
        try:
            loop = asyncio.SelectorEventLoop()
            with self.assertRaises(TypeError):         # 不修的话,asyncio 自己就会崩(用户的第二张截图)
                loop.set_default_executor(real())
            loop.close()
            self.assertEqual(compat.fix_lazy_imports(), ["ThreadPoolExecutor"])
            self.assertIs(cf.ThreadPoolExecutor, real)
            cf.ThreadPoolExecutor = lazy_import()      # 再弄坏一次,看 Core.start 自己会不会修
            p0 = BASE_PORT + 400
            A, B = Node("A", p0), Node("B", p0 + 1)
            A.core.extra_targets = [("127.0.0.1", p0 + 1)]
            B.core.extra_targets = [("127.0.0.1", p0)]
            try:
                self.assertTrue(A.core.start(nick="A", lobby=True))
                self.assertTrue(B.core.start(nick="B", lobby=True))
                self.assertIs(cf.ThreadPoolExecutor, real)
                A.core.join_room("延迟导入 测试 暗号", "群")
                B.core.join_room("延迟导入 测试 暗号", "群")
                self.assertTrue(wait_until(lambda: "群" in A.rooms and "群" in B.rooms))
                self.assertFalse([d for k, d in A.events if k == "room_error"])
                # 文件传输也用到后台线程池
                self.assertTrue(wait_until(lambda: A.online_with(B)))
                tmp = tempfile.mkdtemp()
                src = os.path.join(tmp, "a.bin")
                data = os.urandom(3 * 1024 * 1024)
                with open(src, "wb") as f:
                    f.write(data)
                _, fid, info = A.core.send_file("dm", B.core.id_hex, src)
                self.assertTrue(wait_until(lambda: any(m.get("file") and m["file"]["fid"] == fid for m in B.messages)))
                dest = os.path.join(tmp, "b.bin")
                B.core.download_file(A.core.id_hex, fid, dest, info["size"])
                self.assertTrue(wait_until(lambda: any(d.get("ok") and d["fid"] == fid
                                                       for k, d in B.events if k == "file_done"), timeout=30))
                with open(dest, "rb") as f:
                    self.assertEqual(f.read(), data)
            finally:
                A.core.stop()
                B.core.stop()
        finally:
            cf.ThreadPoolExecutor = real
