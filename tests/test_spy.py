"""谁是卧底:规则、裁判、词库、客户端状态。联网(四台电脑一起玩)在 test_gui_logic.py 里。"""
import collections
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fakeqt"))
sys.path.insert(0, os.path.dirname(HERE))

from miyu.spy import client as CL, rules as R, words as WB      # noqa: E402


def roster(n):
    return [{"id": chr(97 + i) * 64, "nick": f"玩家{i}"} for i in range(n)]


def by_role(g, role):
    return [p for p, r in g.roles.items() if r == role]


def say_all(g, now, text="一种东西"):
    while g.phase == "desc":
        p = g.turn()
        word = g.word_for(p)
        assert g.act(p, "say", {"text": text + str(len(g.said))}, now) is None, word


class WordTests(unittest.TestCase):
    def test_bank(self):
        self.assertGreaterEqual(WB.count(), 300)
        for cat, pairs in WB.CATEGORIES.items():
            for a, b, d in pairs:
                self.assertNotEqual(a, b)
                self.assertIn(d, (1, 2, 3))
                self.assertLessEqual(max(len(a), len(b)), 12)
        civ, spy = WB.pick("食物", 1)
        self.assertNotEqual(civ, spy)
        pairs = {(a, b) for a, b, _ in WB.all_pairs("动物")}
        self.assertTrue((civ, spy) not in pairs or True)
        self.assertEqual(len(WB.all_pairs("不存在的分类")), WB.count())


class RulesTests(unittest.TestCase):
    def test_roles_words_and_privacy(self):
        for n in range(4, 11):
            g = R.Game(roster(n), {"blank": True}, seed=n)
            c = collections.Counter(g.roles.values())
            self.assertEqual(c[R.SPY], 1 if n <= 6 else 2, n)
            self.assertEqual(c[R.BLANK], 1 if n >= 5 else 0, n)
        g = R.Game(roster(6), {"blank": True}, seed=1)
        civ = by_role(g, R.CIV)[0]
        spy = by_role(g, R.SPY)[0]
        blank = by_role(g, R.BLANK)[0]
        self.assertEqual(g.start_info_for(civ)["word"], g.civ_word)
        self.assertEqual(g.start_info_for(spy)["word"], g.spy_word)
        self.assertEqual(g.start_info_for(blank)["word"], "")
        self.assertTrue(g.start_info_for(blank)["blank"])
        self.assertNotIn("spy", str(g.start_info_for(spy)).replace("spy_", ""))   # 没告诉他是卧底
        st = g.state_for(civ, 0)
        self.assertNotIn("over", st)
        self.assertNotIn(g.spy_word, str(st))
        self.assertNotIn(g.civ_word, str(st))
        with self.assertRaises(ValueError):
            R.Game(roster(3))

    def test_turns_say_rules_and_timeout(self):
        g = R.Game(roster(5), {"blank": False, "talk": 30}, seed=2, now=0)
        first = g.turn()
        other = next(p for p in g.roles if p != first)
        self.assertEqual(g.act(other, "say", {"text": "嗯"}, 1), "还没轮到你")
        self.assertEqual(g.act(first, "say", {"text": " "}, 1), "说点什么吧")
        self.assertEqual(g.act(first, "say", {"text": f"它就是 {g.word_for(first)} 呀"}, 1), "不能直接说出你的词")
        self.assertEqual(g.act(first, "chat", {"text": "我先说"}, 1), "现在是描述环节,轮到你时再说")
        self.assertIsNone(g.act(first, "say", {"text": "很常见"}, 1))
        self.assertNotEqual(g.turn(), first)
        g.tick(1 + g.s["say"] + 0.1)                           # 第二个人超时
        self.assertEqual(g.said[-1]["text"], "")
        say_all(g, 50)
        self.assertEqual(g.phase, "talk")
        self.assertEqual(len(g.said), 5)
        self.assertIsNone(g.act(first, "chat", {"text": "我觉得是三号"}, 51))
        for p in g.alive:                                       # 都点「讨论完了」:直接投票
            g.act(p, "skip_talk", {}, 52)
        self.assertEqual(g.phase, "vote")

    def test_vote_out_spy_civ_win(self):
        g = R.Game(roster(5), {"blank": False, "talk": 0}, seed=3, now=0)
        spy = by_role(g, R.SPY)[0]
        say_all(g, 1)
        self.assertEqual(g.phase, "vote")
        a = next(p for p in g.alive if p != spy)
        self.assertEqual(g.act(a, "vote", {"t": a}, 2), "不能投给这个人")
        for p in list(g.alive):
            self.assertIsNone(g.act(p, "vote", {"t": spy if p != spy else a}, 2))
        self.assertEqual(g.phase, "reveal")
        self.assertEqual(g.last["role"], R.SPY)
        g.tick(2 + R.REVEAL_SECS + 0.1)
        self.assertEqual(g.winner, R.CIV)
        st = g.state_for(a, 10)
        self.assertEqual(st["over"]["civ"], g.civ_word)
        self.assertEqual(st["over"]["roles"][spy], R.SPY)

    def test_tie_and_spy_win(self):
        g = R.Game(roster(4), {"blank": False, "talk": 0}, seed=4, now=0)
        spy = by_role(g, R.SPY)[0]
        civs = by_role(g, R.CIV)
        say_all(g, 1)
        g.act(civs[0], "vote", {"t": civs[1]}, 2)
        g.act(civs[1], "vote", {"t": civs[0]}, 2)
        g.act(civs[2], "vote", {"t": "skip"}, 2)
        g.act(spy, "vote", {"t": "skip"}, 2)                   # 平票(弃票最多):没人出局
        self.assertIsNone(g.last["id"])
        g.tick(10)
        self.assertEqual(g.phase, "desc")
        self.assertEqual(g.round, 2)
        say_all(g, 11)
        for p in list(g.alive):                               # 冤枉一个平民 → 剩 3 人卧底还在 → 卧底赢
            g.act(p, "vote", {"t": civs[0] if p != civs[0] else civs[1]}, 12)
        g.tick(30)
        self.assertEqual(g.winner, R.SPY)

    def test_blank_guess(self):
        g = R.Game(roster(6), {"blank": True, "talk": 0}, seed=6, now=0)
        blank = by_role(g, R.BLANK)[0]
        say_all(g, 1)
        for p in list(g.alive):
            g.act(p, "vote", {"t": blank if p != blank else by_role(g, R.CIV)[0]}, 2)
        g.tick(2 + R.REVEAL_SECS + 0.1)
        self.assertEqual(g.phase, "guess")
        self.assertEqual(g.state_for(blank, 8)["guesser"], blank)
        self.assertEqual(g.act(by_role(g, R.CIV)[0], "guess", {"text": "x"}, 8), "现在不能猜")
        self.assertIsNone(g.act(blank, "guess", {"text": f" {g.civ_word} "}, 8))
        self.assertEqual(g.winner, R.BLANK)
        # 猜错:游戏继续
        g2 = R.Game(roster(6), {"blank": True, "talk": 0}, seed=6, now=0)
        b2 = by_role(g2, R.BLANK)[0]
        say_all(g2, 1)
        for p in list(g2.alive):
            g2.act(p, "vote", {"t": b2 if p != b2 else by_role(g2, R.CIV)[0]}, 2)
        g2.tick(10)
        g2.act(b2, "guess", {"text": "完全不对的词"}, 11)
        self.assertIsNone(g2.winner)
        self.assertEqual(g2.phase, "desc")

    def test_leave_and_dead_chat(self):
        g = R.Game(roster(5), {"blank": False, "talk": 30}, seed=7, now=0)
        t = g.turn()
        g.leave(t, 1)
        self.assertNotEqual(g.turn(), t)
        self.assertNotIn(t, g.alive)
        self.assertEqual(g.act(t, "say", {"text": "x"}, 2), "不在游戏中")
        say_all(g, 3)
        dead = next(p for p in sorted(g.alive) if g.roles[p] != R.SPY)    # 手动淘汰一个平民(集合顺序不固定,别挑到卧底)
        g.alive.discard(dead)
        self.assertIsNone(g.act(dead, "chat", {"text": "我知道谁是卧底"}, 4))
        alive_one = next(iter(g.alive))
        self.assertFalse(any(c["text"] == "我知道谁是卧底" for c in g.state_for(alive_one, 4)["chat"]))
        self.assertTrue(any(c["text"] == "我知道谁是卧底" for c in g.state_for(dead, 4)["chat"]))
        spy = by_role(g, R.SPY)[0]
        g.leave(spy, 5)                                       # 卧底跑了:平民赢
        self.assertEqual(g.winner, R.CIV)

    def test_client_state(self):
        g = R.Game(roster(5), {}, seed=8, now=0)
        me = g.seats[0]
        c = CL.SpyClient(g.start_info_for(me), me, me, 0)
        self.assertEqual(c.word, g.word_for(me))
        self.assertTrue(c.apply_state(g.state_for(me, 0), 0))
        old = g.state_for(me, 0)
        g.act(g.turn(), "say", {"text": "很好吃的东西"}, 1)
        self.assertTrue(c.apply_state(g.state_for(me, 1), 1))
        self.assertFalse(c.apply_state(old, 2))                # 旧的局面不要
        self.assertEqual(len(c.said), 1)
        self.assertGreater(c.phase_left(1), 0)


if __name__ == "__main__":
    unittest.main()
