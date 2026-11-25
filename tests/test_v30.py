"""MiYu 3.0 专项单元测试:安全与存储修复、2.5D 宠物引擎、无边框与紧凑面板、代码块与多图画廊。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

# 使用 fakeqt 测试纯逻辑与界面状态机(不弹真窗口)
FAKEQT = os.path.join(os.path.dirname(__file__), "fakeqt")
if FAKEQT not in sys.path:
    sys.path.insert(0, FAKEQT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from miyu import changelog, core, crypto, fun, pet3d, storage, theme, ui, version  # noqa: E402
from miyu.widgets import Bubble, Msg  # noqa: E402
from miyu.window import pet as win_pet, records as win_records  # noqa: E402


class V30BugfixAndSecurityTests(unittest.TestCase):
    def test_version_and_changelog_synced(self):
        self.assertEqual(version.VERSION, "3.1.0")
        self.assertEqual(changelog.CHANGELOG[0][0], version.VERSION)

    def test_password_change_preserves_all_encrypted_blobs(self):
        with tempfile.TemporaryDirectory() as d:
            st = storage.AccountStore(d, os.path.join(d, "st"))
            seed = storage.b64e(os.urandom(32))
            self.assertTrue(st.save_account({"seed": seed, "nick": "阿狸", "rooms": []}))
            self.assertTrue(st.save_favs([{"mid": "m1", "text": "重要收藏"}]))
            self.assertTrue(st.save_blob(storage.BG_FILE, b"custom-wallpaper-bytes"))
            self.assertTrue(st.save_blob(storage.GAMES_FILE, b'{"matches": [1, 2, 3]}'))

            # 设置启动密码后重新打开:收藏、背景、五子棋战绩必须都在
            st.set_password("Secr3t!Pass")
            st2 = storage.AccountStore(d, os.path.join(d, "st"))
            self.assertTrue(st2.is_locked())
            self.assertTrue(st2.unlock("Secr3t!Pass"))
            self.assertTrue(st2.has_password)
            self.assertEqual(st2.load_account()["nick"], "阿狸")
            self.assertEqual(st2.load_favs()[0]["text"], "重要收藏")
            self.assertEqual(st2.load_blob(storage.BG_FILE), b"custom-wallpaper-bytes")
            self.assertEqual(st2.load_blob(storage.GAMES_FILE), b'{"matches": [1, 2, 3]}')

            # 修改密码后再去掉密码:仍然全部保留
            st2.set_password("NewPass#99")
            st2.set_password("")
            st3 = storage.AccountStore(d, os.path.join(d, "st"))
            self.assertFalse(st3.is_locked())
            self.assertEqual(st3.load_account()["nick"], "阿狸")
            self.assertEqual(st3.load_favs()[0]["mid"], "m1")
            self.assertEqual(st3.load_blob(storage.BG_FILE), b"custom-wallpaper-bytes")
            self.assertEqual(st3.load_blob(storage.GAMES_FILE), b'{"matches": [1, 2, 3]}')

    def test_level_cap_50_everywhere_and_mythic_badge(self):
        self.assertEqual(core.clean_level(48), 48)
        self.assertEqual(core.clean_level(50), 50)
        self.assertEqual(core.clean_level(51), 0)
        self.assertEqual(theme.level_tier(45), 4)
        self.assertEqual(theme.LEVEL_TIERS[4][1], "神话")
        cleaned = win_pet.PetMixin.clean_pet_info(
            {"species": "capy", "level": 47, "name": "豚豚", "coat": "siamese", "eyes": "hetero"}
        )
        self.assertEqual(cleaned["level"], 47)
        self.assertEqual(cleaned["species"], "capy")
        self.assertEqual((cleaned["coat"], cleaned["eyes"]), ("siamese", "hetero"))
        restored = win_records.RecordsMixin.msg_from_dict(None, {"mid": "x1", "text": "hi", "level": 49})
        self.assertEqual(restored.level, 49)

    def test_anon_first_hop_obfuscated(self):
        id_a = crypto.Identity()
        c = core.Core(identity=id_a, udp_port=0, tcp_port=0)
        captured = []
        c._group_peers = lambda scope, target: [object(), object()]

        def fake_fwd(scope, target, d, exclude=None):
            captured.append(dict(d))
            return None

        c._anon_forward = fake_fwd
        c._submit = lambda coro: True
        for _ in range(25):
            nid = c.send_anon("lobby", None, "秘密纸条")
            self.assertIsNotNone(nid)
        self.assertEqual(len(captured), 25)
        for pkt in captured:
            self.assertGreaterEqual(pkt["hop"], 1)
            self.assertLessEqual(pkt["hop"], 3)


class V30Pet3DAndUIUpgradeTests(unittest.TestCase):
    def test_pet3d_species_genetics_rooms_and_ten_pull(self):
        for sk in ("cat", "bunny", "bear", "capy", "shiba", "fox", "penguin"):
            self.assertIn(sk, fun.SPECIES)
        pose = pet3d.Pose3D()
        pose.start_pinch()
        pose.move_pinch(28.0, -14.0)
        self.assertTrue(pose.pinching)
        self.assertGreater(pose.pinch_x, 0)
        dist = pose.end_pinch()
        self.assertGreater(dist, 10.0)
        self.assertFalse(pose.pinching)

        g = fun.PetGrowth({"xp": fun.xp_for_level(42), "tickets": 12})
        self.assertTrue(g.set_coat("siamese"))
        self.assertTrue(g.set_eyes("hetero"))
        self.assertTrue(g.set_room("onsen"))
        g2 = fun.PetGrowth(g.to_dict())
        self.assertEqual((g2.coat, g2.eyes, g2.room), ("siamese", "hetero", "onsen"))

        res = g2.draw_many(10)
        self.assertEqual(len(res), 10)
        self.assertEqual(g2.tickets, 2)
        self.assertTrue(any(r["rarity"] in ("SR", "SSR") for r in res))  # 10 连保底必出 SR/SSR

    def test_markdown_code_blocks_and_xss_safety(self):
        app = QApplication()
        theme.apply(app, "terminal")
        self.assertEqual(theme.T["name"], "terminal")

        raw = "看看这段代码:\n```python\ndef hi(x):\n    return '<script>alert(1)</script>'\n```\n再试试 `rm -rf <img onerror=1>` 命令"
        blocks = ui.parse_markdown_blocks(raw)
        self.assertEqual([b[0] for b in blocks], ["text", "code", "text"])
        self.assertEqual(blocks[1][1], "python")
        code_html = ui.highlight_code_html(blocks[1][2], "python")
        self.assertNotIn("<script>", code_html)
        self.assertIn("&lt;script&gt;", code_html)
        inline_html = ui.inline_code_html(blocks[2][2])
        self.assertNotIn("<img", inline_html)
        self.assertIn("&lt;img", inline_html)

        m = Msg(raw, mine=True)
        bub = Bubble(m, False, False, 520)
        self.assertEqual(len(bub.code_cards), 1)
        self.assertIsNotNone(bub.body)
        bub.set_search("看看", True)
        self.assertTrue(bub.property("searchHit"))
        bub.set_search("", False)
        self.assertFalse(bub.property("searchHit"))

    def test_v31_xp_rebalance_dye_checkin_pass_and_snack_game(self):
        from miyu import petpass
        # Lv2 仍严格为 300,但高等级曲线大幅降低难度
        self.assertEqual(fun.xp_for_level(2), 300)
        self.assertLess(fun.xp_for_level(20), 25000)
        self.assertLess(fun.xp_for_level(50), 95000)
        # Lv1 新手立刻能穿多件装扮
        lv1 = fun.PetGrowth()
        lv1_accs = [a[0] for a in fun.ACCESSORIES if a[2] == 1]
        self.assertGreaterEqual(len(lv1_accs), 5)
        self.assertTrue(lv1.is_unlocked("beret"))
        self.assertTrue(lv1.is_unlocked("sweater"))
        # 装扮自由染色与持久化
        self.assertTrue(lv1.set_dye("body", "#339AF0"))
        self.assertEqual(fun.PetGrowth(lv1.to_dict()).dye["body"], "#339AF0")
        # 7 日循环签到 + 特殊动作解锁
        res1 = petpass.do_checkin(lv1, today="2026-11-25")
        self.assertIsNotNone(res1)
        self.assertEqual(res1[0], 1)
        self.assertIsNone(petpass.do_checkin(lv1, today="2026-11-25"))  # 同一天不能重复签
        petpass.do_checkin(lv1, today="2026-11-26")
        petpass.do_checkin(lv1, today="2026-11-27")                     # 第 3 天解锁「后空翻」
        self.assertTrue(lv1.has_trick("backflip"))
        # 通行证积分领取 + 接零食小游戏结算
        gain, _ups = lv1.record_snack_score(160, today="2026-11-27")
        self.assertGreaterEqual(gain, 60)
        self.assertEqual(lv1.snack_best, 160)
        lv1.pass_pts = 1050
        got, _ = petpass.claim_all_pass(lv1)
        self.assertGreaterEqual(len(got), 10)
        self.assertTrue(lv1.has_trick("rainbow"))
        self.assertTrue(lv1.is_unlocked("king_robe"))
        # 序列化恢复完整性
        restored = fun.PetGrowth(lv1.to_dict())
        self.assertEqual(restored.snack_best, 160)
        self.assertIn(15, restored.pass_claimed)


if __name__ == "__main__":
    unittest.main()
