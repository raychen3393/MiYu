"""
2.4 新功能的逻辑测试:谁是坏鸭(地图、规则、裁判、客户端、任务小游戏)、宠物名片和排行榜、扔东西的道具表。
联网部分(四台电脑一起玩)在 test_gui_logic.py 里。
"""
import collections
import os
import random
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fakeqt"))
sys.path.insert(0, os.path.dirname(HERE))

from miyu import crypto as C                                  # noqa: E402
from miyu import petrank as PR                                # noqa: E402
from miyu import throwfx                                      # noqa: E402
from miyu.duck import client as CL, rules as RU, tasks as TK, world as Wd     # noqa: E402
from miyu.fun import ACCESSORIES, ACC_BY_ID, GACHA_POOL, WEAPONS, xp_for_level  # noqa: E402


def roster(n):
    return [{"id": chr(97 + i) * 64, "nick": f"玩家{i}", "color": Wd.COLORS[i % 10][0]} for i in range(n)]


def fresh(g, now):
    """测试里时间是跳着走的:让所有人"刚刚还在",免得被当成掉线。"""
    for p in g.players.values():
        p["seen"] = now


def place(g, pid, x, y):
    g.players[pid]["x"], g.players[pid]["y"] = float(x), float(y)


class MapTests(unittest.TestCase):
    def reach(self, locked=frozenset()):
        step = 10
        start = (int(Wd.BUTTON[0]), int(Wd.BUTTON[1]))
        seen, q = {start}, collections.deque([start])
        while q:
            x, y = q.popleft()
            for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
                n = (x + dx, y + dy)
                if n not in seen and Wd.walkable(n[0], n[1], locked):
                    seen.add(n)
                    q.append(n)
        return seen

    def test_all_rooms_and_tasks_reachable(self):
        seen = self.reach()
        near = lambda x, y: any(abs(a - x) <= 10 and abs(b - y) <= 10 for a, b in seen)   # noqa: E731
        for rid, _n, r, _c in Wd.ROOMS:
            self.assertTrue(near(*r.center()), rid)
        for t in Wd.TASK_SPOTS:
            self.assertTrue(Wd.walkable(t[3], t[4]), t[0])
            self.assertTrue(near(t[3], t[4]), t[0])
        self.assertTrue(near(Wd.LIGHT_SWITCH[1], Wd.LIGHT_SWITCH[2]))
        self.assertEqual(len({t[0] for t in Wd.TASK_SPOTS}), len(Wd.TASK_SPOTS))
        self.assertTrue(all(Wd.DOORS[rid] for rid, *_ in Wd.ROOMS))

    def test_locked_doors_block_room(self):
        seen = self.reach(frozenset({"kitchen"}))
        kx, ky = Wd.ROOM_BY_ID["kitchen"][2].center()
        self.assertFalse(any(abs(a - kx) <= 10 and abs(b - ky) <= 10 for a, b in seen))
        # 锁着的门挡视线
        hall = Wd.HALLS[0]
        self.assertTrue(Wd.line_of_sight(400, 300, 800, 300))
        self.assertFalse(Wd.line_of_sight(400, 300, 800, 300, frozenset({"kitchen"})))
        self.assertTrue(hall.w > hall.h)

    def test_move_slides_and_ghost(self):
        x, y = Wd.move(1200, 790, 0, -2000)                    # 往墙上撞:停在墙里面
        self.assertTrue(Wd.walkable(x, y))
        x2, y2 = Wd.move(1200, 640, 30, -30)                   # 斜着贴墙:只走横的那一半
        self.assertGreater(x2, 1200)
        gx, gy = Wd.move(950, 700, 0, -120, ghost=True)         # 幽灵穿墙
        self.assertFalse(Wd.walkable(gx, gy))
        self.assertFalse(Wd.line_of_sight(1200, 790, 350, 300))  # 广场看不到厨房


class RulesTests(unittest.TestCase):
    def test_roles_by_player_count(self):
        for n in range(4, 11):
            g = RU.Game(roster(n), {"dodo": True}, seed=n)
            roles = collections.Counter(p["role"] for p in g.players.values())
            self.assertEqual(roles[RU.DUCK], 1 if n <= 6 else 2, n)
            self.assertEqual(roles[RU.DODO], 1 if n >= 6 else 0, n)
            self.assertTrue(all(len(p["tasks"]) == 5 for p in g.players.values()))
        g = RU.Game(roster(10), {"ducks": 3, "dodo": False}, seed=1)
        self.assertEqual(sum(p["role"] == RU.DUCK for p in g.players.values()), 3)
        with self.assertRaises(ValueError):
            RU.Game(roster(3))
        with self.assertRaises(ValueError):
            RU.Game(roster(11))
        s = RU.clean_settings({"kill_cd": 999, "tasks": "x", "reveal": False, "evil": 1})
        self.assertEqual((s["kill_cd"], s["tasks"], s["reveal"]), (60, 5, False))
        self.assertNotIn("evil", s)

    def setup_game(self, n=5, **kw):
        g = RU.Game(roster(n), {"dodo": False, "discuss": 0, "sheriff": False, "detective": False, **kw}, seed=7, now=0)
        duck = next(p for p in g.players.values() if p["role"] == RU.DUCK)
        geese = [p for p in g.players.values() if p["role"] == RU.GOOSE]
        return g, duck, geese

    def test_kill_rules(self):
        g, duck, geese = self.setup_game()
        v = geese[0]
        place(g, duck["id"], 1000, 700)
        place(g, v["id"], 1040, 700)
        self.assertEqual(g.act(duck["id"], "kill", {"t": v["id"]}, 5), "还在冷却")
        self.assertEqual(g.act(geese[1]["id"], "kill", {"t": v["id"]}, 20), "现在不能刀")
        place(g, v["id"], 1400, 900)
        self.assertEqual(g.act(duck["id"], "kill", {"t": v["id"]}, 20), "离得太远")
        place(g, v["id"], 1040, 700)
        self.assertIsNone(g.act(duck["id"], "kill", {"t": v["id"]}, 20))
        self.assertFalse(v["alive"])
        self.assertEqual(len(g.bodies), 1)
        evs = g.take_events()
        self.assertIn(([v["id"]], {"e": "dead", "by": duck["id"], "sheriff": False}), evs)
        fx = [to for to, e in evs if e.get("e") == "kill_fx"][0]
        self.assertIn(duck["id"], fx)                              # 刀的人自己看得到
        self.assertEqual(g.act(duck["id"], "kill", {"t": geese[1]["id"]}, 21), "还在冷却")
        # 隔着墙刀不到
        g2, d2, gs2 = self.setup_game()
        place(g2, d2["id"], 590, 790)                          # 配电室门口的走廊
        place(g2, gs2[0]["id"], 590, 700)                      # 配电室里,墙的另一边
        self.assertFalse(Wd.line_of_sight(590, 790, 590, 700))
        self.assertIn(g2.act(d2["id"], "kill", {"t": gs2[0]["id"]}, 30), ("隔着墙", "离得太远"))

    def test_report_meeting_vote_and_eject(self):
        g, duck, geese = self.setup_game(reveal=True)
        v = geese[0]
        place(g, duck["id"], 1000, 700)
        place(g, v["id"], 1030, 700)
        g.act(duck["id"], "kill", {"t": v["id"]}, 20)
        place(g, geese[1]["id"], 1300, 900)
        self.assertEqual(g.act(geese[1]["id"], "report", {}, 21), "附近没有尸体")
        place(g, geese[1]["id"], 1060, 720)
        self.assertIsNone(g.act(geese[1]["id"], "report", {}, 21))
        self.assertEqual(g.phase, "meeting")
        self.assertEqual(g.bodies, [])
        self.assertEqual(g.act(v["id"], "vote", {"t": duck["id"]}, 22), "现在不能投票")     # 死人不能投
        self.assertEqual(g.act(geese[1]["id"], "vote", {"t": v["id"]}, 22), "不能投给这个人")
        alive = g.alive()
        for p in alive:
            if p is duck:
                self.assertIsNone(g.act(p["id"], "vote", {"t": "skip"}, 23))
            else:
                self.assertIsNone(g.act(p["id"], "vote", {"t": duck["id"]}, 23))
        self.assertEqual(g.act(alive[0]["id"], "vote", {"t": "skip"}, 23), "不在游戏中")      # 已经结束了
        ej = [e for _to, e in g.take_events() if e.get("e") == "eject"][0]
        self.assertEqual(ej["out"], duck["id"])
        self.assertEqual(ej["role"], RU.DUCK)
        self.assertEqual(g.winner, RU.GOOSE)                   # 唯一的坏鸭被投出去

    def test_discussion_lock_tie_and_resume(self):
        g = RU.Game(roster(6), {"dodo": False, "discuss": 10, "vote": 30, "sheriff": False, "detective": False},
                    seed=3, now=0)
        a, b, c, d = [p["id"] for p in g.alive()][:4]
        place(g, a, *Wd.BUTTON)
        self.assertIn("刚开完会", g.act(a, "button", {}, 5))
        self.assertIsNone(g.act(a, "button", {}, 12))
        self.assertEqual(g.players[a]["buttons"], 0)
        self.assertEqual(g.act(b, "vote", {"t": c}, 13), "还在讨论,等一下再投")
        g.act(a, "vote", {"t": c}, 23)
        g.act(b, "vote", {"t": d}, 23)                         # 一票对一票,其余人没投
        fresh(g, 53)
        g.tick(12 + 10 + 30 + 1)                               # 时间到
        self.assertEqual(g.phase, "eject")
        ej = [e for _to, e in g.take_events() if e.get("e") == "eject"][0]
        self.assertIsNone(ej["out"])
        self.assertEqual(len(g.alive()), 6)
        fresh(g, 60)
        g.tick(12 + 41 + RU.EJECT_SECS + 1)
        self.assertEqual(g.phase, "play")
        self.assertIn("次数用完", g.act(a, "button", {}, 200))

    def test_dodo_and_duck_wins(self):
        g = RU.Game(roster(6), {"dodo": True, "discuss": 0, "sheriff": False, "detective": False}, seed=11, now=0)
        dodo = next(p for p in g.players.values() if p["role"] == RU.DODO)
        caller = next(p for p in g.alive() if p is not dodo)
        g.start_meeting(caller["id"], None, 20)
        for p in g.alive():
            g.act(p["id"], "vote", {"t": dodo["id"]}, 21)
        self.assertEqual(g.winner, RU.DODO)
        # 坏鸭追上人数:5 人局 1 鸭,刀掉 3 个好鹅后 1 : 1
        g, duck, geese = self.setup_game()
        t = 20
        for v in geese[:3]:
            place(g, duck["id"], 1000, 700)
            place(g, v["id"], 1030, 700)
            self.assertIsNone(g.act(duck["id"], "kill", {"t": v["id"]}, t))
            t += 30
        self.assertEqual(g.winner, RU.DUCK)
        self.assertEqual(g.phase, "over")
        over = [e for _to, e in g.take_events() if e.get("e") == "over"][0]
        self.assertEqual(over["roles"][duck["id"]], RU.DUCK)
        self.assertEqual(g.act(geese[3]["id"], "task", {"t": geese[3]["tasks"][0]}, t), "不在游戏中")

    def test_tasks_win_and_fake_tasks(self):
        g, duck, geese = self.setup_game(tasks=2)
        p = geese[0]
        tid = p["tasks"][0]
        place(g, p["id"], 1200, 790)
        self.assertEqual(g.act(p["id"], "task", {"t": tid}, 5), "离任务点太远")
        spot = Wd.TASK_BY_ID[tid]
        place(g, p["id"], spot[3], spot[4])
        self.assertIsNone(g.act(p["id"], "task", {"t": tid}, 5))
        self.assertEqual(g.act(p["id"], "task", {"t": tid}, 5), "这个任务不用做")
        self.assertEqual(g.task_progress(), (1, 2 * len(geese)))
        d0 = duck["tasks"][0]
        place(g, duck["id"], Wd.TASK_BY_ID[d0][3], Wd.TASK_BY_ID[d0][4])
        g.act(duck["id"], "task", {"t": d0}, 6)                # 坏鸭的假任务不算进度
        self.assertEqual(g.task_progress()[0], 1)
        for q in geese:                                        # 死了的好鹅(幽灵)也能做任务
            for t in q["tasks"]:
                if t in q["done"]:
                    continue
                place(g, q["id"], Wd.TASK_BY_ID[t][3], Wd.TASK_BY_ID[t][4])
                g.act(q["id"], "task", {"t": t}, 7)
        self.assertEqual(g.winner, RU.GOOSE)
        self.assertIn("任务", g.win_reason)

    def test_sabotage_lights_and_doors(self):
        g, duck, geese = self.setup_game(sabo_cd=30)
        self.assertIn("冷却", g.act(duck["id"], "sabo", {"k": "lights"}, 5))
        self.assertIsNone(g.act(duck["id"], "sabo", {"k": "lights"}, 20))
        self.assertEqual(g.vision(geese[0]), Wd.VISION_DARK)
        self.assertEqual(g.vision(duck), Wd.VISION)
        self.assertIn("冷却", g.act(duck["id"], "sabo", {"k": "doors", "room": "kitchen"}, 21))
        place(g, geese[1]["id"], *Wd.BUTTON)
        self.assertIn("关灯", g.act(geese[1]["id"], "button", {}, 25))
        p = geese[0]
        place(g, p["id"], 1200, 790)
        self.assertEqual(g.act(p["id"], "fix", {}, 22), "离电闸太远")
        place(g, p["id"], Wd.LIGHT_SWITCH[1], Wd.LIGHT_SWITCH[2])
        self.assertIsNone(g.act(p["id"], "fix", {}, 22))
        self.assertEqual(g.act(p["id"], "fix", {"done": True}, 22.3), "还没修好")
        self.assertIsNone(g.act(p["id"], "fix", {"done": True}, 23.5))
        self.assertFalse(g.lights_off)
        self.assertIsNone(g.act(duck["id"], "sabo", {"k": "doors", "room": "kitchen"}, 51))
        self.assertIn("kitchen", g.locked)
        place(g, p["id"], 350, 300)
        self.assertFalse(g.on_input(p["id"], 700, 300, 1, 2.0, 52))   # 锁着门出不去
        fresh(g, 62)
        g.tick(51 + RU.DOORS_SECS + 0.1)
        self.assertNotIn("kitchen", g.locked)

    def test_input_validation_and_left(self):
        g, duck, geese = self.setup_game()
        p = geese[0]
        place(g, p["id"], 1200, 790)
        self.assertTrue(g.on_input(p["id"], 1210, 790, 1, 0.08, 1))
        tp = p["tp"]
        self.assertFalse(g.on_input(p["id"], 1600, 790, 1, 0.08, 1.1))    # 走太快:拉回去
        self.assertEqual(p["tp"], tp + 1)
        self.assertFalse(g.on_input(p["id"], 1000, 560, 1, 1.0, 2))       # 走进墙里
        self.assertFalse(g.on_input(p["id"], "x", None, 1, 0.1, 2))
        for q in g.players.values():
            q["seen"] = 100
        p["seen"] = 0
        g.tick(100)
        self.assertTrue(p["left"])
        self.assertFalse(p["alive"])
        self.assertIn((None, {"e": "left", "id": p["id"]}), g.take_events())

    def test_snapshot_privacy(self):
        g, duck, geese = self.setup_game()
        a, b, c = geese[0], geese[1], geese[2]
        place(g, a["id"], 1200, 790)
        place(g, b["id"], 1260, 790)                           # 看得见
        place(g, c["id"], 350, 300)                            # 在厨房,看不见
        place(g, duck["id"], 1300, 820)
        snap = g.snapshot_for(a["id"], 5)
        ids = {row[0] for row in snap["p"]}
        self.assertIn(b["id"], ids)
        self.assertNotIn(c["id"], ids)
        self.assertNotIn("kc", snap)                           # 好鹅不知道刀的冷却
        self.assertIn("kc", g.snapshot_for(duck["id"], 5))
        b["alive"] = False                                    # 活人看不到幽灵,幽灵看得到所有人
        self.assertNotIn(b["id"], {row[0] for row in g.snapshot_for(a["id"], 5)["p"]})
        self.assertIn(c["id"], {row[0] for row in g.snapshot_for(b["id"], 5)["p"]})
        info_a, info_d = g.start_info_for(a["id"]), g.start_info_for(duck["id"])
        self.assertEqual(info_a["role"], RU.GOOSE)
        self.assertNotIn("mates", info_a)
        self.assertEqual(info_d["mates"], [])
        self.assertNotIn("role", str(info_a["roster"]))        # 名单里没有别人的身份

    def test_chat_ghosts_only(self):
        g, duck, geese = self.setup_game()
        self.assertEqual(g.act(geese[0]["id"], "chat", {"text": "嗨"}, 1), "只有开会的时候才能说话")
        geese[1]["alive"] = False
        self.assertIsNone(g.act(geese[1]["id"], "chat", {"text": "我死了"}, 1))
        to, ev = g.take_events()[-1]
        self.assertEqual(sorted(to), [geese[1]["id"]])        # 只发给幽灵
        g.start_meeting(geese[0]["id"], None, 20)
        g.take_events()
        self.assertIsNone(g.act(geese[0]["id"], "chat", {"text": "我觉得是红色"}, 21))
        self.assertIsNone(g.take_events()[-1][0])

    def test_sheriff_and_detective(self):
        g = RU.Game(roster(7), {"dodo": False, "discuss": 0}, seed=5, now=0)
        roles = collections.Counter(p["role"] for p in g.players.values())
        self.assertEqual((roles[RU.SHERIFF], roles[RU.DETECTIVE], roles[RU.DUCK]), (1, 1, 2))
        sh = next(p for p in g.players.values() if p["role"] == RU.SHERIFF)
        de = next(p for p in g.players.values() if p["role"] == RU.DETECTIVE)
        ducks = [p for p in g.players.values() if p["role"] == RU.DUCK]
        goose = next(p for p in g.players.values() if p["role"] == RU.GOOSE)
        self.assertIn("kc", g.snapshot_for(sh["id"], 1))
        self.assertEqual(g.snapshot_for(de["id"], 1)["ck"], 1)
        # 侦探查验:只有自己知道结果,一局一次
        place(g, de["id"], 1000, 700)
        place(g, ducks[0]["id"], 1040, 700)
        g.take_events()
        self.assertIsNone(g.act(de["id"], "check", {"t": ducks[0]["id"]}, 5))
        self.assertEqual(g.take_events(), [([de["id"]], {"e": "checked", "t": ducks[0]["id"], "duck": True})])
        self.assertIn("用完", g.act(de["id"], "check", {"t": goose["id"]}, 6))
        self.assertEqual(g.act(goose["id"], "check", {"t": de["id"]}, 6), "现在不能查验")
        # 警长刀对了:坏鸭倒下
        place(g, sh["id"], 1000, 700)
        self.assertIsNone(g.act(sh["id"], "kill", {"t": ducks[0]["id"]}, 20))
        self.assertFalse(ducks[0]["alive"])
        self.assertTrue(sh["alive"])
        # 警长刀错了:自己倒下,对方没事
        place(g, goose["id"], 1040, 700)
        self.assertIsNone(g.act(sh["id"], "kill", {"t": goose["id"]}, 60))
        self.assertFalse(sh["alive"])
        self.assertTrue(goose["alive"])
        kinds = [e["k"] for e in g.log]
        self.assertEqual(kinds, ["shot", "misfire"])
        # 坏鸭不能刀同伴;任务进度算上警长和侦探
        place(g, ducks[1]["id"], 1060, 700)
        place(g, ducks[0]["id"], 1040, 700)
        ducks[0]["alive"] = True
        ducks[1]["kill_at"] = 0
        self.assertEqual(g.act(ducks[1]["id"], "kill", {"t": ducks[0]["id"]}, 61), "那是你的同伴")
        self.assertEqual(g.task_progress()[1], 5 * 5)
        self.assertEqual(RU.team_of(RU.SHERIFF), RU.GOOSE)

    def test_log_and_lag(self):
        g, duck, geese = self.setup_game()
        place(g, duck["id"], 1000, 700)
        place(g, geese[0]["id"], 1040, 700)
        g.act(duck["id"], "kill", {"t": geese[0]["id"]}, 20)
        place(g, geese[1]["id"], 1060, 720)
        g.act(geese[1]["id"], "report", {}, 21)
        for p in g.alive():
            g.act(p["id"], "vote", {"t": duck["id"] if p is not duck else "skip"}, 22)
        over = [e for _to, e in g.take_events() if e.get("e") == "over"][0]
        self.assertEqual([e["k"] for e in over["log"]], ["kill", "report", "eject", "over"])
        self.assertEqual(over["log"][0]["room"], "plaza")
        g2, d2, gs2 = self.setup_game()
        fresh(g2, 0)
        gs2[0]["seen"] = -10                                      # 10 秒没动静:别人看到「掉线中」,但还没出局
        place(g2, gs2[1]["id"], gs2[0]["x"] + 40, gs2[0]["y"])
        g2.tick(0)
        row = next(r for r in g2.snapshot_for(gs2[1]["id"], 0)["p"] if r[0] == gs2[0]["id"])
        self.assertEqual(row[5], 1)
        self.assertFalse(gs2[0]["left"])
        g2.tick(25)
        self.assertTrue(gs2[0]["left"])                           # 超过 30 秒才出局

    def test_practice(self):
        g = RU.Game(roster(1), {"tasks": 2}, practice=True)
        p = next(iter(g.players.values()))
        self.assertEqual(p["role"], RU.GOOSE)
        g.tick(1000)
        self.assertFalse(p["left"])
        for t in p["tasks"]:
            place(g, p["id"], Wd.TASK_BY_ID[t][3], Wd.TASK_BY_ID[t][4])
            g.act(p["id"], "task", {"t": t}, 1001)
        self.assertEqual(g.winner, RU.GOOSE)


class ClientTests(unittest.TestCase):
    def make(self, role="duck"):
        info = {"gid": "g", "role": role, "tasks": ["k_code", "p_wire"], "mates": [],
                "roster": [{"id": "me", "nick": "我", "color": "red"}, {"id": "b", "nick": "乙", "color": "blue"}]}
        return CL.Client(info, "me", "host", 0)

    def test_snapshot_interpolation_and_teleport(self):
        c = self.make()
        c.apply_snapshot({"ph": "play", "me": [1200, 790, 1, 1], "p": [["b", 1250, 790, 1, 1]], "b": [], "tb": [0, 10]}, 1.0)
        self.assertEqual((c.x, c.y), (1200.0, 790.0))
        c.apply_snapshot({"ph": "play", "me": [1200, 790, 1, 1], "p": [["b", 1290, 790, 1, 1]], "b": []}, 1.1)
        x, _y, _f = c.pos_of("b", 1.1 + CL.INTERP_DELAY - 0.05)
        self.assertTrue(1250 < x < 1290)
        c.step(1, 0, 0.1)
        self.assertGreater(c.x, 1200)
        moved = c.x
        c.apply_snapshot({"ph": "play", "me": [999, 790, 1, 1], "p": [], "b": []}, 1.2)    # tp 没变:不跳
        self.assertEqual(c.x, moved)
        self.assertEqual(c.visible_ids(), [])
        c.apply_snapshot({"ph": "play", "me": [1100, 790, 2, 1], "p": [], "b": []}, 1.3)   # tp 变了:跳过去
        self.assertEqual(c.x, 1100.0)

    def test_nearby_actions_and_events(self):
        c = self.make()
        t = Wd.TASK_BY_ID["k_code"]
        c.x, c.y = t[3], t[4]
        self.assertEqual(c.use_action(), ("task", "k_code"))
        c.x, c.y = Wd.BUTTON
        self.assertEqual(c.use_action(), ("button", None))
        c.apply_snapshot({"ph": "play", "me": [1200, 790, 0, 1], "p": [["b", 1230, 790, 1, 1]],
                          "b": [["z", 1210, 800]], "kc": 0}, 2)
        self.assertEqual(c.kill_target(2.5), "b")
        self.assertEqual(c.near_body(), "z")
        c.apply_event({"e": "meeting", "caller": "b", "body": "z"}, 3)
        self.assertEqual(c.phase, "meeting")
        self.assertIsNone(c.kill_target(3))
        c.apply_event({"e": "chat", "by": "b", "text": "x" * 300}, 3)
        self.assertEqual(len(c.chat[-1]["text"]), 120)
        c.apply_event({"e": "eject", "out": "me", "role": "duck", "votes": {"b": "me"}}, 4)
        self.assertFalse(c.alive)
        c.apply_event({"e": "over", "win": "goose", "why": "x", "roles": {"me": "duck"}}, 5)
        self.assertEqual(c.phase, "over")
        self.assertFalse(c.step(1, 0, 0.1))                    # 结束了不能走
        self.assertEqual([x[0] for x in c.my_tasks()], ["k_code", "p_wire"])


class MiniGameTests(unittest.TestCase):
    def test_wires(self):
        g = TK.Wires(None, random.Random(1))
        done = []
        g.done.connect(lambda: done.append(1))
        for i in range(4):
            j = g.right.index(g.left[i])
            wrong = (j + 1) % 4
            g.press(*g.node("l", i))
            g.release(*g.node("r", wrong))
            self.assertNotIn(i, g.links)
            g.press(*g.node("l", i))
            g.move(200, 150)
            g.release(*g.node("r", j))
        self.assertTrue(g.finished)

    def test_swipe(self):
        g = TK.Swipe(None, random.Random(1))
        for dt, ok in ((0.1, False), (3.0, False), (0.9, True)):
            g.press(g.cx, g.Y)
            g.move(g.X1, g.Y)
            g.release(g.X1, g.Y, now=g.t0 + dt)
            self.assertEqual(g.finished, ok, dt)

    def test_seq_drag_memory_switches(self):
        g = TK.Seq(None, random.Random(2))
        click = lambda n: g.press(g.cell_rect(g.cells.index(n)).x() + 5, g.cell_rect(g.cells.index(n)).y() + 5)  # noqa: E731
        # 替身的 QRectF 不能取坐标:直接按格子算
        g.cell_rect = lambda i: type("R", (), {"x": lambda s: 40 + (i % 4) * 92, "y": lambda s: 70 + (i // 4) * 96,
                                               "left": lambda s: 40 + (i % 4) * 92, "right": lambda s: 120 + (i % 4) * 92,
                                               "top": lambda s: 70 + (i // 4) * 96, "bottom": lambda s: 154 + (i // 4) * 96})()
        click(1)
        click(3)                                                # 点错:从头来
        self.assertEqual(g.next, 1)
        for n in range(1, 9):
            click(n)
        self.assertTrue(g.finished)
        d = TK.Drag(None, random.Random(3), "g_carrot")
        d.target = type("R", (), {"left": lambda s: 300, "right": lambda s: 400, "top": lambda s: 80, "bottom": lambda s: 240})()
        for _ in range(10):
            it = next((i for i in d.items if not i[2]), None)
            if it is None:
                break
            d.hold, d.off = d.items.index(it), (0.0, 0.0)          # 叠在一起的时候直接拿这一个
            d.move(350, 150)
            d.release(350, 150)
        self.assertTrue(d.finished)
        m = TK.Memory(None, random.Random(4))
        m.shown_at = -100
        for ch in "00000" if m.code != "00000" else "11111":
            m.key(ch)
        self.assertFalse(m.finished)
        m.shown_at = -100
        for ch in m.code:
            m.key(ch)
        self.assertTrue(m.finished)
        s = TK.Switches(None, random.Random(5))
        s.sw_rect = lambda i: type("R", (), {"left": lambda _s: i * 100, "right": lambda _s: i * 100 + 50,
                                             "top": lambda _s: 0, "bottom": lambda _s: 100})()
        for i, on in enumerate(list(s.on)):
            if not on:
                s.press(i * 100 + 10, 50)
        self.assertTrue(s.finished)
        for kind in ("wires", "swipe", "seq", "drag", "memory", "switch", "nope"):
            self.assertIsInstance(TK.make_game(kind, "f_fish"), TK.MiniGame)


class PetRankTests(unittest.TestCase):
    def card(self, ident, xp, nick="小明", ts=1_790_000_000_000, wk="2026-W47", w0=0):
        c = PR.make_card(ident.pub.hex(), nick, "cat", "团团", xp, wk, w0, ["bow", "nope"], ts)
        return PR.sign_card(c, ident)

    def test_sign_verify_tamper(self):
        a, b = C.Identity(), C.Identity()
        now = 1_790_000_100_000
        c = self.card(a, 5000)
        self.assertEqual(c["lv"], PR.level_of(5000))
        self.assertEqual(c["wear"], ["bow"])
        self.assertIsNotNone(PR.clean_card(c, now))
        for k, v in (("xp", 999999), ("lv", 30), ("n", "冒充"), ("id", b.pub.hex())):
            bad = dict(c)
            bad[k] = v
            self.assertIsNone(PR.clean_card(bad, now), k)
        forged = PR.sign_card(dict(c, xp=999999, lv=PR.level_of(999999)), b)     # 别人签的
        self.assertIsNone(PR.clean_card(forged, now))
        self.assertIsNone(PR.clean_card(self.card(a, 100, ts=now + 3_600_000), now))   # 来自未来
        self.assertIsNone(PR.clean_card(dict(c, w0=6000), now))
        self.assertIsNone(PR.clean_card("x", now))

    def test_accept_newer_and_suspicious(self):
        a = C.Identity()
        cards, flags = {}, {}
        now = 1_800_000_000_000
        t = 1_790_000_000_000
        self.assertIsNotNone(PR.accept(cards, flags, self.card(a, 1000, ts=t), now))
        self.assertIsNone(PR.accept(cards, flags, self.card(a, 900, ts=t - 1), now))       # 旧的不要
        self.assertIsNotNone(PR.accept(cards, flags, self.card(a, 400_000, ts=t + 3_600_000), now))
        self.assertTrue(flags.get(a.pub.hex()))                # 一小时涨 40 万:可疑
        self.assertIsNotNone(PR.accept(cards, flags, self.card(a, 401_000, ts=t + 7_200_000), now))
        self.assertFalse(flags.get(a.pub.hex(), False))

    def test_standings_ties_and_week(self):
        ids = [C.Identity() for _ in range(4)]
        cards = {}
        for ident, xp, w0 in zip(ids, (20000, 20000, 5000, 90000), (19000, 15000, 0, 90000)):
            c = PR.clean_card(self.card(ident, xp, w0=w0), 1_790_000_100_000)
            cards[c["id"]] = c
        rows = PR.standings(cards, None, "level", wk="2026-W47")
        self.assertEqual(rows[0]["xp"], 90000)
        self.assertEqual([r["rank"] for r in rows], [1, 2, 2, 4])     # 同级同经验并列
        week = PR.standings(cards, None, "week", wk="2026-W47")
        self.assertEqual([r["gain"] for r in week], [5000, 5000, 1000])
        self.assertEqual(PR.standings(cards, None, "week", wk="2026-W48"), [])    # 新的一周清零
        rank, mine, above = PR.rank_of(rows, ids[2].pub.hex())
        self.assertEqual((rank, above["rank"]), (4, 2))
        members = {ids[0].pub.hex()}
        self.assertEqual(len(PR.standings(cards, members, "level")), 1)
        self.assertRegex(PR.week_key(), r"^\d{4}-W\d{2}$")
        self.assertEqual(PR.ago(int(time.time() * 1000)), "刚刚")


class ContentTests(unittest.TestCase):
    def test_items_weapons_and_accessories(self):
        self.assertEqual(len(throwfx.ITEMS), 8)
        self.assertEqual(set(throwfx.STAIN_SECS), set(throwfx.ITEM_BY_ID))
        self.assertTrue(throwfx.FRIENDLY <= set(throwfx.ITEM_BY_ID))
        self.assertEqual([w[0] for w in WEAPONS], ["fist", "pillow", "hammer", "flick"])
        self.assertGreaterEqual(len(ACCESSORIES), 32)
        self.assertEqual(len(ACC_BY_ID), len(ACCESSORIES))     # id 不重复
        lv30 = [a for a in ACCESSORIES if a[2] == 30]
        self.assertTrue(lv30)
        for _r, kind, iid, _n in GACHA_POOL:
            if kind == "acc":
                self.assertIn(iid, ACC_BY_ID)
        self.assertEqual(xp_for_level(1), 0)


if __name__ == "__main__":
    unittest.main()
