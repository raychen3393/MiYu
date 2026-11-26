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
        self.assertEqual(version.VERSION, "3.9.8")
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

    def test_level_cap_100_everywhere_and_mythic_badge(self):
        self.assertEqual(core.clean_level(48), 48)
        self.assertEqual(core.clean_level(50), 50)
        self.assertEqual(core.clean_level(100), 100)
        self.assertEqual(core.clean_level(101), 0)
        self.assertEqual(theme.level_tier(45), 4)
        self.assertEqual(theme.LEVEL_TIERS[4][1], "神话")
        cleaned = win_pet.PetMixin.clean_pet_info(
            {"species": "capy", "level": 99, "name": "豚豚", "coat": "siamese", "eyes": "hetero"}
        )
        self.assertEqual(cleaned["level"], 99)
        self.assertEqual(cleaned["species"], "capy")
        self.assertEqual((cleaned["coat"], cleaned["eyes"]), ("siamese", "hetero"))
        restored = win_records.RecordsMixin.msg_from_dict(None, {"mid": "x1", "text": "hi", "level": 100})
        self.assertEqual(restored.level, 100)

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

    def test_v32_lv100_anti_hold_outfits_gacha_and_cloud_game(self):
        from miyu import petcare
        # 1. 满级 100 级 + 阶段形态完整
        self.assertEqual(fun.PET_MAX_LEVEL, 100)
        self.assertEqual(fun.ANTI_HOLD_LEVEL, 30)
        self.assertEqual(petcare.form_of(60)[1], "星辰期")
        self.assertEqual(petcare.form_of(80)[1], "苍穹期")
        self.assertEqual(petcare.form_of(100)[1], "至臻期")
        g100 = fun.PetGrowth({"xp": fun.xp_for_level(100)})
        self.assertEqual(g100.level, 100)
        self.assertTrue(g100.is_unlocked("eternal_crown"))
        self.assertTrue(g100.has_trick("coronation"))
        # 2. 打字防长按分级:30 级以下允许长按,30 级及以上拦截长按连发
        g29 = fun.PetGrowth({"xp": fun.xp_for_level(29)})
        g29.tap(is_repeat=True)
        self.assertEqual(g29.taps, 1)
        g30 = fun.PetGrowth({"xp": fun.xp_for_level(30)})
        xp_before_30 = g30.xp
        g30.tap(is_repeat=True)
        self.assertEqual(g30.taps, 0)
        self.assertEqual(g30.xp, xp_before_30)
        g30.tap(is_repeat=False)
        self.assertEqual(g30.taps, 1)
        # 3. 扭蛋限定套装不卡等级(Lv1 抽到即可穿),高阶与扭蛋套装全注册在 OUTFITS
        self.assertIn("frog", fun.OUTFIT_BY_ID)
        self.assertIn("eternal", fun.OUTFIT_BY_ID)
        gacha_ids = {it[2] for it in fun.GACHA_POOL if it[1] == "acc"}
        self.assertIn("frog_hood", gacha_ids)
        self.assertIn("honey_jar", gacha_ids)
        g1 = fun.PetGrowth()
        self.assertFalse(g1.is_unlocked("frog_hood"))
        g1.owned.add("acc:frog_hood")
        self.assertTrue(g1.is_unlocked("frog_hood"))
        # 4. 云端跳跳乐计分与持久化
        gain, _ups = g1.record_cloud_score(200, today="2026-11-25")
        self.assertGreaterEqual(gain, 80)
        self.assertEqual(g1.cloud_best, 200)
        self.assertEqual(fun.PetGrowth(g1.to_dict()).cloud_best, 200)
        # 5. 12 款动态边缘气泡特效 + 签到/扭蛋/升级解锁 + 自定义台词/下班倒计时
        self.assertEqual(len(fun.BUBBLE_AURAS), 12)
        self.assertTrue(g100.has_aura("flame"))
        self.assertTrue(g100.has_aura("eternal"))
        self.assertFalse(g1.has_aura("neon"))
        g1.owned.add("aura:neon")
        self.assertTrue(g1.set_aura("neon"))
        g1.custom_lines = ["快下班啦!"]
        g1.off_work = "18:00"
        restored2 = fun.PetGrowth(g1.to_dict())
        self.assertEqual(restored2.aura, "neon")
        self.assertEqual(restored2.custom_lines, ["快下班啦!"])
        self.assertEqual(restored2.off_work, "18:00")
        # 6. 宠物排行榜支持接零食与跳跳乐高分榜
        from miyu import petrank as PR
        c_card = PR.make_card("a" * 64, "测试", "cat", "团团", 500, "2026-W48", 0, [], snack_best=320, cloud_best=450)
        self.assertEqual(PR.standings({"a" * 64: c_card}, None, "snack")[0]["sb"], 320)
        self.assertEqual(PR.standings({"a" * 64: c_card}, None, "cloud")[0]["cb"], 450)

    def test_v351_audit_fixes(self):
        # 1. SQLite 历史筛选搜索支持 img / file / mine
        self.assertTrue(win_records.dict_matches({"img": "abc", "text": ""}, "", "img"))
        self.assertFalse(win_records.dict_matches({"text": "纯文字"}, "", "img"))
        self.assertTrue(win_records.dict_matches({"file": {"name": "report.pdf"}, "text": ""}, "report", "file"))
        self.assertFalse(win_records.dict_matches({"text": "report"}, "report", "file"))
        self.assertTrue(win_records.dict_matches({"mine": True, "text": "hi"}, "", "mine"))
        self.assertFalse(win_records.dict_matches({"mine": False, "text": "hi"}, "", "mine"))
        # 2. Bubble 动态边缘粒子视口暂停与连续分组不裁剪顶部边距
        from miyu.widgets import AURA_BUBBLES
        m = Msg("火焰测试", mine=True, aura="flame")
        b = Bubble(m, False, False, 400, grp="single")
        self.assertIn(b, AURA_BUBBLES)
        self.assertEqual(b._aura_pad_v, 13)
        b.set_group("first")
        self.assertEqual(b.grp, "first")
        b.set_aura_active(False)
        self.assertFalse(b._aura_active)
        # 3. motion.animate 回调参数名为 on_done
        import inspect
        from miyu import motion, petpass
        self.assertIn("on_done", inspect.signature(motion.animate).parameters)
        # 4. 云端跳跳乐物理可达性:普通/雷云弹跳最高点均严格大于云层最大间距(66px)
        max_h = (petpass._CloudJumpStage.JUMP_VY ** 2) / (2 * petpass._CloudJumpStage.GRAVITY)
        storm_h = (petpass._CloudJumpStage.STORM_VY ** 2) / (2 * petpass._CloudJumpStage.GRAVITY)
        self.assertGreater(max_h, 120.0)
        self.assertGreater(storm_h, 90.0)
        # 5. 3.6 真 3D 盲盒引擎材质、开关持久化与 128 件新装扮/29 套套装
        self.assertGreaterEqual(len(fun.ACCESSORIES), 128)
        self.assertGreaterEqual(len(fun.OUTFITS), 29)
        g3 = fun.PetGrowth()
        self.assertEqual(g3.material, "clay")
        self.assertTrue(g3.render3d)
        self.assertTrue(g3.set_material("jelly"))
        g3.set_render3d(False)
        g3_r = fun.PetGrowth(g3.to_dict())
        self.assertEqual(g3_r.material, "jelly")
        self.assertFalse(g3_r.render3d)
        self.assertTrue(g3.is_unlocked("bunny_hood"))
        self.assertTrue(g3.is_unlocked("duck_float"))
        self.assertTrue(g3.is_unlocked("plush_duck"))
        # 每个新套装 3 件装扮分属不同部位,可一键穿全套
        for oid in ("spa_duck", "star_voyager", "crystal_angel", "cyber_pilot", "sakura_night", "moon_mage"):
            parts = fun.OUTFIT_BY_ID[oid][2]
            slots = [fun.ACC_BY_ID[a][3] for a in parts]
            self.assertEqual(len(slots), len(set(slots)), f"Slot collision in outfit {oid}")

    def test_v370_upgrades(self):
        # 1. 穿搭预设方案保存、序列化与一键套用
        g = fun.PetGrowth({"xp": fun.xp_for_level(25)})
        g.toggle("beret")
        g.set_dye("head", "#FF6B8A")
        g.set_coat("siamese")
        g.set_eyes("hetero")
        g.set_room("onsen")
        self.assertTrue(g.save_preset("1", "温泉小猫", "cat"))
        g2 = fun.PetGrowth(g.to_dict())
        self.assertIn("1", g2.presets)
        g2.wear.clear()
        g2.dye.clear()
        g2.set_coat("classic")
        sp = g2.apply_preset("1")
        self.assertEqual(sp, "cat")
        self.assertIn("beret", g2.wear)
        self.assertEqual(g2.dye.get("head"), "#FF6B8A")
        self.assertEqual(g2.coat, "siamese")
        self.assertTrue(g2.delete_preset("1"))
        self.assertNotIn("1", g2.presets)
        # 2. 合成大萌宠计分、排行榜名片与排名
        from miyu import petmerge, petrank as PR
        self.assertEqual(len(petmerge.MERGE_TIERS), 8)
        gain, _ups = g.record_merge_score(360, today="2026-11-26")
        self.assertGreaterEqual(gain, 80)
        self.assertEqual(g.merge_best, 360)
        self.assertEqual(fun.PetGrowth(g.to_dict()).merge_best, 360)
        card = PR.make_card("b" * 64, "玩家", "capy", "豚豚", 800, "2026-W48", 0, [], merge_best=520)
        self.assertEqual(PR.standings({"b" * 64: card}, None, "merge")[0]["mb"], 520)
        # 3. 壁纸模糊度 0~24px 滑块与旧版 bool 兼容
        c1 = theme.clean_custom({"bg_blur_px": 18, "bg_dim": 42})
        self.assertEqual((c1["bg_blur_px"], c1["bg_blur"], c1["bg_dim"]), (18, True, 42))
        c2 = theme.clean_custom({"bg_blur": False})
        self.assertEqual((c2["bg_blur_px"], c2["bg_blur"]), (0, False))
        # 4. 冗余实验文件 petgl.py 已清理
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(__file__), "..", "miyu", "petgl.py")))

    def test_v380_games(self):
        from miyu import arcade, cards, core, petmerge, petpvz, petrank as PR, pettd, sound
        from miyu.widgets import Msg
        # 1. 双塔防成长记录、每日首胜双倍与持久化
        g = fun.PetGrowth()
        g_td, _ = g.record_td_score(1800, 10, today="2026-11-26")
        g_pvz, _ = g.record_pvz_score(1500, 8, today="2026-11-26")
        self.assertGreater(g_td, 0)
        self.assertGreater(g_pvz, 0)
        self.assertEqual((g.td_best, g.td_waves, g.pvz_best, g.pvz_waves), (1800, 10, 1500, 8))
        pts_before = g.pass_pts
        self.assertTrue(g.claim_daily_game_bonus(today="2026-11-26"))
        self.assertFalse(g.claim_daily_game_bonus(today="2026-11-26"))
        self.assertEqual(g.pass_pts, pts_before + 30)
        g2 = fun.PetGrowth(g.to_dict())
        self.assertEqual((g2.td_best, g2.td_waves, g2.pvz_best, g2.pvz_waves, g2.game_first_day),
                         (1800, 10, 1500, 8, "2026-11-26"))
        # 2. 排行榜名片新增保卫萌宠(td)与萌宠大战(pvz)签名榜单
        c = PR.make_card("c" * 64, "塔防王", "fox", "小狐", 900, "2026-W48", 0, [], td_best=3200, pvz_best=2900)
        self.assertEqual(PR.standings({"c" * 64: c}, None, "td")[0]["tb"], 3200)
        self.assertEqual(PR.standings({"c" * 64: c}, None, "pvz")[0]["pb"], 2900)
        # 3. 战绩挑战卡校验与渲染
        raw_card = {"type": "score", "g": "td", "s": 3200, "d": "金萝卜通关", "pn": "小狐", "sp": "fox", "lv": 12, "wear": []}
        self.assertIsNotNone(core.clean_card(raw_card))
        sc_w = cards.make_card(Msg("战绩", card=raw_card), {})
        self.assertIsInstance(sc_w, cards.GameScoreCard)
        # 4. 程序合成小游戏音效无外部依赖且可生成 PCM
        for k in ("pop", "merge", "combo", "coin", "shoot", "freeze", "boom", "jump", "boost", "hurt", "build", "win", "lose"):
            pcm = sound.game_sfx_pcm(k)
            self.assertGreater(len(pcm), 500)
        # 5. 双塔防与游乐厅核心数据结构 & 建塔/种植物逻辑
        self.assertEqual(len(pettd.TD_MAPS), 3)
        self.assertEqual(len(pettd.TD_TOWERS), 5)
        self.assertEqual(len(petpvz.PVZ_PLANTS), 6)
        self.assertEqual(len(arcade.ARCADE_GAMES), 5)
        td_stage = pettd._TDStage(None, g, "cat")
        td_stage.stop()
        td_stage.running = True
        self.assertTrue(td_stage.build_at((3, 2), "cat"))
        self.assertTrue(td_stage.upgrade_selected())
        self.assertEqual(td_stage.towers[(3, 2)]["lv"], 2)
        self.assertTrue(td_stage.sell_selected())
        self.assertNotIn((3, 2), td_stage.towers)
        pvz_stage = petpvz._PvZStage(None)
        pvz_stage.stop()
        pvz_stage.running = True
        self.assertTrue(pvz_stage.plant_at(0, 0, "sun"))
        self.assertIn((0, 0), pvz_stage.plants)
        # 6. 合成大萌宠 3 道具可用
        mg_stage = petmerge._MergePetStage(None)
        mg_stage.stop()
        mg_stage.running = True
        mg_stage.balls.append(petmerge._MergeBall(200, 420, 0))
        self.assertTrue(mg_stage.use_shake())
        self.assertEqual(mg_stage.shake_left, 0)
        self.assertTrue(mg_stage.use_swap())
        self.assertEqual(mg_stage.swap_left, 0)

    def test_v382_single_instance_and_recovery(self):
        import sqlite3
        import tempfile
        import threading
        from unittest import mock
        from miyu import app as app_mod, storage
        from miyu.window import records as rec_mod

        with tempfile.TemporaryDirectory() as tmp:
            # 1. 单实例互斥锁:第 2 个实例被拦截并触发唤醒回调,释放后可重新获取(供更新/注销重启)
            woke = threading.Event()
            g1 = app_mod.SingleInstance(tmp)
            self.assertTrue(g1.acquire())
            g1.set_wake_handler(woke.set)
            g2 = app_mod.SingleInstance(tmp)
            self.assertFalse(g2.acquire())
            self.assertTrue(g2.wake_existing())
            self.assertTrue(woke.wait(2.0))
            g1.release()
            g3 = app_mod.SingleInstance(tmp)
            self.assertTrue(g3.acquire())
            g3.release()

            # 2. p.bin 自动热备份 p.bin.bak 与损坏自动兜底恢复
            st = storage.AccountStore(tmp, os.path.join(tmp, "stk"))
            seed = storage.b64e(b"\x11" * 32)
            self.assertTrue(st.save_account({"seed": seed, "nick": "旧号", "dbkey": storage.b64e(b"\x22" * 32)}))
            self.assertTrue(st.save_account({"seed": seed, "nick": "新版", "dbkey": storage.b64e(b"\x22" * 32)}))
            self.assertTrue(os.path.exists(os.path.join(tmp, storage.ACCOUNT_BACKUP)))
            # 模拟主文件意外损坏:仍能从 p.bin.bak 自动恢复身份与 dbkey
            with open(os.path.join(tmp, storage.ACCOUNT_FILE), "wb") as f:
                f.write(b"corrupted")
            loaded = st.load_account()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["seed"], seed)
            self.assertEqual(loaded["dbkey"], storage.b64e(b"\x22" * 32))
            st.wipe()
            self.assertFalse(os.path.exists(os.path.join(tmp, storage.ACCOUNT_BACKUP)))

            # 3. m.db 遇到 database is locked 时绝不改名成 .broken 建空库
            os.makedirs(tmp, exist_ok=True)
            db_path = os.path.join(tmp, "m.db")
            with open(db_path, "wb") as f:
                f.write(b"dummy-db")

            class _FakeRec(rec_mod.RecordsMixin):
                def __init__(self):
                    self.store = st
                    self.db = None
                    self._db_key = None
                    self.account = {"dbkey": storage.b64e(b"\x33" * 32)}

            fr = _FakeRec()
            with mock.patch.object(rec_mod, "MsgDB", side_effect=sqlite3.OperationalError("database is locked")):
                with mock.patch.object(rec_mod.time, "sleep"):
                    self.assertFalse(fr.open_history())
            self.assertTrue(os.path.exists(db_path))
            self.assertFalse(any(".broken-" in fn for fn in os.listdir(tmp)))

    def test_v390_easytier(self):
        import json
        import tempfile
        import zipfile
        from miyu import core, easytier as ET
        # 1. 跨网邀请口令编码/解码、旧失效节点自动迁移与中文 TOML 渲染
        code = ET.encode_invite("买了否冷", "Secret99", ["tcp://public.easytier.cn:11010"])
        self.assertTrue(code.startswith(ET.INVITE_PREFIX))
        dec = ET.decode_invite(code)
        self.assertEqual(dec["network_name"], "买了否冷")
        self.assertEqual(dec["network_secret"], "Secret99")
        self.assertNotIn("tcp://public.easytier.cn:11010", dec["peers"])
        self.assertEqual(dec["peers"], ET.DEFAULT_PEERS[:4])
        self.assertIsNone(ET.decode_invite("invalid-text"))
        migrated = ET.clean_config({"network_name": "买了否冷", "network_secret": "1234",
                                    "peers": ["tcp://public.easytier.cn:11010", "tcp://public.easytier.top:11010"]})
        self.assertEqual(migrated["peers"], ET.DEFAULT_PEERS)
        toml_txt = ET.render_toml(migrated)
        self.assertIn('network_name = "买了否冷"', toml_txt)
        self.assertIn("dhcp = true", toml_txt)
        # 1b. connector 通道状态解析(JSON 枚举与文本格式)
        cj = json.dumps([
            {"url": {"url": "tcp://et.sumnight.top:11010"}, "status": 0},
            {"url": {"url": "tcp://183.230.36.171:11010"}, "status": 2},
        ])
        cs = ET.parse_connectors_output(cj)
        self.assertEqual([(c["url"], c["status"]) for c in cs], [
            ("tcp://et.sumnight.top:11010", "Connected"),
            ("tcp://183.230.36.171:11010", "Connecting"),
        ])
        # 2. 解析 easytier-cli JSON 与表格两种输出格式
        j_out = json.dumps([
            {"ipv4": "10.126.126.1/24", "hostname": "ME", "cost": "Local", "lat_ms": "-"},
            {"ipv4": "10.126.126.2/24", "hostname": "FriendPC", "cost": "p2p", "lat_ms": "18.5", "tunnel_proto": "udp"},
        ])
        lip, peers = ET.parse_peers_output(j_out)
        self.assertEqual(lip, "10.126.126.1")
        self.assertEqual(len(peers), 1)
        self.assertEqual(peers[0]["ipv4"], "10.126.126.2")
        self.assertEqual(peers[0]["cost"], "p2p")
        tbl = (
            "| ipv4 | hostname | cost | lat_ms | loss_rate |\n"
            "| 10.126.126.1/24 | ME | Local | - | - |\n"
            "| 10.126.126.5/24 | Buddy | relay | 62.0 | 0% |\n"
        )
        lip2, peers2 = ET.parse_peers_output(tbl)
        self.assertEqual(lip2, "10.126.126.1")
        self.assertEqual(peers2[0]["ipv4"], "10.126.126.5")
        # 3. Zip Slip 安全导入测试
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "et.zip")
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("../../evil.txt", "nope")
                zf.writestr(f"easytier-windows-x86_64/{ET.CORE_EXE}", b"MZcore")
                zf.writestr(f"easytier-windows-x86_64/{ET.CLI_EXE}", b"MZcli")
                zf.writestr("easytier-windows-x86_64/wintun.dll", b"MZtun")
            dst = os.path.join(tmp, "et")
            ok, _msg = ET.import_local_zip(zp, dst)
            self.assertTrue(ok)
            self.assertTrue(os.path.isfile(os.path.join(dst, ET.CORE_EXE)))
            self.assertFalse(os.path.exists(os.path.join(tmp, "evil.txt")))
        # 4. Core mesh_targets 允许入站与单播发现 + 启动参数构造
        c = core.Core()
        c.mesh_targets = {("10.126.126.8", core.DEFAULT_UDP_PORT)}
        self.assertTrue(c._ip_allowed("10.126.126.8"))
        mgr = ET.EasyTierManager(".")
        argv = mgr.build_args("C:/tmp/cfg.toml", 15999)
        self.assertEqual(argv, ["-c", "C:/tmp/cfg.toml", "--rpc-portal", "127.0.0.1:15999"])
        # 5. 内置 Uninstall.exe 自动释放与内置 EasyTier 压缩包自动解压
        from miyu import app as app_mod
        with tempfile.TemporaryDirectory() as tmp2:
            if app_mod.bundled_asset("Uninstall.exe"):
                u_dst = app_mod.sync_uninstaller(tmp2)
                self.assertTrue(u_dst and os.path.isfile(u_dst))
                self.assertEqual(app_mod.sync_uninstaller(tmp2), u_dst)
            if ET.bundled_easytier_zip():
                et_out = ET.ensure_bundled_easytier(tmp2)
                self.assertTrue(et_out and os.path.isfile(os.path.join(et_out, ET.CORE_EXE)))

    def test_v395_frameless_resize_math(self):
        from miyu.gui import MainWindow
        # 右下角自由拉伸
        self.assertEqual(
            MainWindow._compute_resize_box(100, 100, 1000, 500, 120, 80, "rb", 860, 520, keep_ratio=False),
            (100, 100, 1120, 580),
        )
        # 左上角向内压缩严格受最小尺寸保护，右下角锚点不动
        self.assertEqual(
            MainWindow._compute_resize_box(100, 100, 1000, 500, 500, 500, "lt", 860, 520, keep_ratio=False),
            (240, 80, 860, 520),
        )
        # 按住 Shift 拖右下角锁定 2:1 等比例缩放
        self.assertEqual(
            MainWindow._compute_resize_box(100, 100, 1000, 500, 200, 10, "rb", 400, 200, keep_ratio=True),
            (100, 100, 1200, 600),
        )
        # 3.9.7: 跨网联机启动自动重连判定(未配置/未开启/密码不足均不自动拉起)
        from miyu import easytier as ET
        self.assertFalse(ET.should_auto_start({}))
        self.assertFalse(ET.should_auto_start({"network_name": "买了否冷", "network_secret": "1234", "auto_start": False}))
        self.assertFalse(ET.should_auto_start({"network_name": "买了否冷", "network_secret": "123", "auto_start": True}))
        self.assertTrue(ET.should_auto_start({"network_name": "买了否冷", "network_secret": "1234", "auto_start": True}))
        # 3.9.8: 跨网高延迟丢包后定时补发 ver 版本通告
        from miyu.window import system as sys_mod

        class _FakeSys(sys_mod.SystemMixin):
            def __init__(self):
                self._own_checked = None
                self.own_release = {"fid": "a" * 32, "size": 1024}
                self.peers = {"p1": {"online": True}, "p2": {"online": True}, "p3": {"online": False}}
                self.peer_versions = {"p2": "3.9.0"}
                self.update = {"state": "none"}
                self.update_mode = "auto"
                self._save_tick = 12
                self.sent = []

            def _send_ver(self, pid: str) -> None:
                self.sent.append(pid)

        fs = _FakeSys()
        fs._tick_system(0.0)
        self.assertEqual(fs.sent, ["p1"])
        fs.sent.clear()
        fs._save_tick = 60
        fs._tick_system(0.0)
        self.assertEqual(sorted(fs.sent), ["p1", "p2"])

    def test_v394_easytier_guard(self):
        """3.9.4:EasyTier 内核提权前的 SHA-256 白名单校验、受保护目录启动脚本、官方包下载核对。"""
        import base64
        import hashlib
        import io
        import sys
        import tempfile
        import zipfile
        from miyu import easytier as ET, etguard as G

        def mkzip(path, files, dup=False):
            with zipfile.ZipFile(path, "w") as zf:
                for name, data in files.items():
                    zf.writestr(f"easytier-windows-x86_64/{name}", data)
                if dup:
                    zf.writestr(f"other/{G.CORE}", b"MZevil")

        core_h = hashlib.sha256(b"MZcore").hexdigest()
        tun_h = hashlib.sha256(b"MZtun").hexdigest()
        # 1. 白名单清洗:只认 4 个内核文件名 + 64 位十六进制,去重、限量,邀请口令里不带
        raw = [G.entry(G.CORE, core_h), "EASYTIER-CORE.EXE:" + core_h.upper(), "evil.exe:" + core_h,
               "wintun.dll:1234", 42, "wintun.dll:" + tun_h]
        self.assertEqual(G.clean_trusted(raw), [G.entry(G.CORE, core_h), G.entry("wintun.dll", tun_h)])
        self.assertEqual(G.clean_trusted("nope"), [])
        self.assertEqual(len(G.clean_trusted([G.entry(G.CORE, f"{i:064x}") for i in range(100)])), G.MAX_TRUSTED)
        cfg = ET.clean_config({"network_name": "a", "network_secret": "1234", "trusted": raw})
        self.assertEqual(len(cfg["trusted"]), 2)
        self.assertNotIn("trusted", ET.decode_invite(ET.encode_invite("a", "1234")))
        self.assertTrue(G.short(core_h).startswith(core_h[:8].upper()))

        with tempfile.TemporaryDirectory() as tmp:
            # 2. 压缩包指纹;同名内核出现两次直接拒绝
            zp = os.path.join(tmp, "et.zip")
            mkzip(zp, {G.CORE: b"MZcore", "wintun.dll": b"MZtun", "readme.txt": b"x"})
            self.assertEqual(G.zip_kernel_hashes(zp), {G.CORE: core_h, "wintun.dll": tun_h})
            dz = os.path.join(tmp, "dup.zip")
            mkzip(dz, {G.CORE: b"MZcore"}, dup=True)
            with self.assertRaises(ValueError):
                G.zip_kernel_hashes(dz)
            ok, msg = ET.import_local_zip(dz, os.path.join(tmp, "dup"))
            self.assertFalse(ok)
            # 3. 目录校验:文件都在白名单里才通过;改一个字节就不通过
            good = os.path.join(tmp, "good")
            self.assertTrue(ET.import_local_zip(zp, good)[0])
            trusted = {n: set() for n in G.KERNEL_FILES}
            trusted[G.CORE].add(core_h)
            trusted["wintun.dll"].add(tun_h)
            ok, hashes, files, bad = G.check_kernel(good, trusted)
            self.assertTrue(ok, bad)
            self.assertEqual(set(files), {G.CORE, "wintun.dll"})
            # 名字和指纹绑定:wintun.dll 的指纹不能拿来冒充 easytier-core.exe
            swapped = {n: set() for n in G.KERNEL_FILES}
            swapped[G.CORE].add(tun_h)
            swapped["wintun.dll"].add(core_h)
            self.assertFalse(G.check_kernel(good, swapped)[0])
            badd = os.path.join(tmp, "bad")
            mkzip(os.path.join(tmp, "bad.zip"), {G.CORE: b"MZcorf", "wintun.dll": b"MZtun"})
            self.assertTrue(ET.import_local_zip(os.path.join(tmp, "bad.zip"), badd)[0])
            ok, _h, _f, bad = G.check_kernel(badd, trusted)
            self.assertFalse(ok)
            self.assertEqual(bad, [G.CORE])
            self.assertFalse(G.check_kernel(os.path.join(tmp, "missing"), trusted)[0])
            # 白名单里没有的多余文件(比如上一版残留的 packet.dll)也不放行;重新导入会清掉残留
            with open(os.path.join(good, "packet.dll"), "wb") as f:
                f.write(b"MZold")
            self.assertFalse(G.check_kernel(good, trusted)[0])
            self.assertTrue(ET.import_local_zip(zp, good)[0])
            self.assertFalse(os.path.exists(os.path.join(good, "packet.dll")))
            self.assertTrue(G.check_kernel(good, trusted)[0])
            # 4. 压缩包评估:官方原包 / 全在白名单 / 未知
            self.assertEqual(G.assess_zip(zp, trusted)[0], "pinned")
            self.assertEqual(G.assess_zip(os.path.join(tmp, "bad.zip"), trusted)[0], "unknown")
            orig_official = G.OFFICIAL_ZIP_SHA256
            G.OFFICIAL_ZIP_SHA256 = G.sha256_file(os.path.join(tmp, "bad.zip"))
            try:
                self.assertEqual(G.assess_zip(os.path.join(tmp, "bad.zip"), {})[0], "official")
            finally:
                G.OFFICIAL_ZIP_SHA256 = orig_official
            # 5. 查找内核:优先返回校验通过的那个
            orig_find, orig_bundle = ET.find_easytier_dirs, ET.bundled_easytier_zip
            ET.find_easytier_dirs = lambda d: [badd, good]
            ET.bundled_easytier_zip = lambda: None
            try:
                self.assertEqual(ET.ensure_bundled_easytier(tmp, trusted), good)
                self.assertEqual(ET.ensure_bundled_easytier(tmp, {n: set() for n in G.KERNEL_FILES}), badd)
                # 6. Windows 上内核没通过校验:不提权、不启动,把指纹交给界面去问用户
                ET.find_easytier_dirs = lambda d: [badd]
                mgr = ET.EasyTierManager(tmp)
                orig_plat, orig_pins = sys.platform, G._builtin_cache
                sys.platform, G._builtin_cache = "win32", {}
                try:
                    ok, msg = mgr.start({"network_name": "房间", "network_secret": "12345678"})
                finally:
                    sys.platform, G._builtin_cache = orig_plat, orig_pins
                self.assertFalse(ok)
                self.assertFalse(mgr.running)
                self.assertEqual(mgr.state, "untrusted")
                self.assertIn(G.entry(G.CORE, hashlib.sha256(b"MZcorf").hexdigest()), mgr.pending_trust)
                self.assertEqual(mgr.pending_dir, badd)
                self.assertFalse(any(fn.startswith(".launch_") for fn in os.listdir(tmp)))
            finally:
                ET.find_easytier_dirs, ET.bundled_easytier_zip = orig_find, orig_bundle

            # 7. 下载:整包指纹不是官方值就丢弃;是官方值才解压并返回指纹
            with open(zp, "rb") as _zf:
                payload = _zf.read()

            class _Resp(io.BytesIO):
                headers = {"Content-Length": str(len(payload))}

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            orig_open = ET.urllib.request.urlopen
            ET.urllib.request.urlopen = lambda *a, **k: _Resp(payload)
            try:
                ok, msg, entries = ET.download_official_easytier(os.path.join(tmp, "dl1"))
                self.assertFalse(ok)
                self.assertEqual(entries, [])
                self.assertFalse(os.path.exists(os.path.join(tmp, "dl1", G.CORE)))
                G.OFFICIAL_ZIP_SHA256 = hashlib.sha256(payload).hexdigest()
                ok, msg, entries = ET.download_official_easytier(os.path.join(tmp, "dl2"))
                self.assertTrue(ok, msg)
                self.assertIn(G.entry(G.CORE, core_h), entries)
                self.assertTrue(os.path.isfile(os.path.join(tmp, "dl2", G.CORE)))
            finally:
                ET.urllib.request.urlopen = orig_open
                G.OFFICIAL_ZIP_SHA256 = orig_official

        # 8. 管理员启动脚本:先复制到受保护目录、再校验复制出来的文件、最后才运行;密码不以明文出现
        hashes = {G.CORE: core_h, "wintun.dll": tun_h}
        files = {G.CORE: "easytier-core.exe", "wintun.dll": "WinTun.dll"}
        cfg_bytes = ET.render_toml({"network_name": "买了否冷", "network_secret": "TopSecret99"}).encode("utf-8")
        script = G.build_launch_script(r"C:\Users\o'neil\AppData\Local\MiYu\easytier", files, hashes,
                                       nonce="a1b2c3d4e5f6", stop_file=r"C:\Users\x\.stop_a1b2c3d4e5f6",
                                       parent_pid=4321, cfg_bytes=cfg_bytes, rpc_port=15999)
        self.assertNotIn("TopSecret99", script)
        self.assertIn(base64.b64encode(cfg_bytes).decode("ascii"), script)
        self.assertIn("o''neil", script)                       # 单引号正确转义
        self.assertIn(f"'WinTun.dll'='{tun_h}'", script)
        self.assertIn(G.PROTECTED_DIRNAME, script)
        i_copy, i_hash, i_cfg, i_run = (script.index("Copy-Item"), script.index("Get-FileHash"),
                                        script.index("WriteAllBytes"), script.index("Start-Process"))
        self.assertTrue(i_copy < i_hash < i_cfg < i_run)
        self.assertLess(script.index("/inheritance:r"), i_cfg)  # 先收紧权限再写密码
        self.assertIn("127.0.0.1:15999", script)
        self.assertIn("$parentPid = 4321", script)
        self.assertNotIn("Remove-Item -LiteralPath $stopf", script)  # 管理员进程不碰用户目录里的文件
        self.assertNotIn("Set-Content -LiteralPath $stopf", script)
        self.assertEqual(G.kernel_tag(hashes), G.kernel_tag(dict(reversed(list(hashes.items())))))
        with self.assertRaises(ValueError):
            G.build_launch_script("C:/x", {"wintun.dll": "wintun.dll"}, {"wintun.dll": tun_h}, nonce="abcdef",
                                  stop_file="s", parent_pid=1, cfg_bytes=b"", rpc_port=1)
        with self.assertRaises(ValueError):
            G.build_launch_script("C:/x", files, hashes, nonce="a'; calc #", stop_file="s",
                                  parent_pid=1, cfg_bytes=b"", rpc_port=1)
        # 9. 提权命令:内存里核对脚本哈希后才执行;PowerShell 用绝对路径
        sb = script.encode("utf-8")
        cmd = base64.b64decode(G.bootstrap_command(r"C:\tmp\.launch_a1.ps1", sb)).decode("utf-16-le")
        self.assertIn(hashlib.sha256(sb).hexdigest(), cmd)
        self.assertIn(r"C:\tmp\.launch_a1.ps1", cmd)
        self.assertIn("ScriptBlock]::Create", cmd)
        self.assertIn("-EncodedCommand", G.powershell_args("QQ=="))
        if sys.platform == "win32":
            self.assertTrue(os.path.isabs(G.powershell_exe()))
        self.assertTrue(G.powershell_exe().lower().endswith(os.path.join("windowspowershell", "v1.0", "powershell.exe")))


if __name__ == "__main__":
    unittest.main()
