"""
五子棋模块的自动测试:规则、电脑对手、对局记录的签名验证和防篡改、积分和排行榜。
"""
import datetime
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from miyu import crypto as C                              # noqa: E402
from miyu.gomoku import ai, league, record as R           # noqa: E402
from miyu.gomoku.rules import BLACK, WHITE, Board         # noqa: E402

T0 = 1_790_000_000_000      # 一个固定的时间(毫秒),测试不依赖今天几号


class Players:
    def __init__(self, *names):
        self.ids = {n: C.Identity() for n in names}

    def hex(self, n):
        return self.ids[n].pub.hex()


def new_game(P, black, white, mid=None, t0=T0, lim=60):
    rec = R.new_record(mid or os.urandom(16).hex(), P.hex(black), P.hex(white), lim, t0, black, white)
    R.sign_start(rec, P.ids[black], "b")
    R.sign_start(rec, P.ids[white], "w")
    return rec


def act(P, rec, name, kind, ts=None, **kw):
    color = R.color_of(rec, P.hex(name))
    ts = ts if ts is not None else rec["t0"] + 1000 * (len(rec["acts"]) + 1) * 3
    rec["acts"].append(R.make_action(rec, P.ids[name], kind, color, ts, **kw))


def play(P, rec, moves, black, white):
    for i, (x, y) in enumerate(moves):
        act(P, rec, black if i % 2 == 0 else white, "m", x=x, y=y)


BLACK_WINS = [(7, 7), (0, 0), (8, 7), (0, 1), (9, 7), (0, 2), (10, 7), (0, 3), (11, 7)]     # 黑第 9 手连五


class RulesTests(unittest.TestCase):
    def test_five_and_overline_and_draw(self):
        b = Board()
        line = None
        for x, y in BLACK_WINS:
            line = b.place(x, y)
        self.assertEqual(line, [(7, 7), (8, 7), (9, 7), (10, 7), (11, 7)])
        b2 = Board([(0, 0), (9, 9), (1, 1), (9, 10), (2, 2), (9, 11), (4, 4), (9, 12), (5, 5), (3, 9)])
        self.assertEqual(len(b2.place(3, 3)), 6)                       # 长连(6 子)也算赢
        with self.assertRaises(ValueError):
            b2.place(3, 3)                                             # 重复落子
        with self.assertRaises(ValueError):
            b2.place(15, 0)
        self.assertFalse(Board().full)
        b3 = Board()
        b3.undo(1)                                                     # 空棋盘悔棋不出错
        self.assertEqual(b3.turn, BLACK)
        b3.place(7, 7)
        self.assertEqual(b3.turn, WHITE)


class AITests(unittest.TestCase):
    def test_wins_blocks_and_is_fast(self):
        b = Board([(5, 7), (5, 8), (6, 7), (6, 8), (7, 7), (7, 8), (8, 7), (9, 9)])
        for lvl in ai.LEVELS:
            self.assertIn(ai.choose(b, lvl), [(4, 7), (9, 7)])           # 能赢就赢
        b2 = Board([(5, 7), (5, 8), (6, 7), (6, 8), (7, 7), (9, 9), (8, 7)])
        for lvl in ai.LEVELS:
            self.assertIn(ai.choose(b2, lvl), [(4, 7), (9, 7)])          # 对方要赢就堵
        self.assertEqual(ai.choose(Board(), "hard"), (7, 7))

    def test_hard_beats_easy(self):
        wins = 0
        for seed in range(3):
            rng = random.Random(seed)
            b = Board()
            while True:
                lvl = "hard" if b.turn == BLACK else "easy"
                if b.place(*ai.choose(b, lvl, rng)):
                    wins += b.turn == WHITE                             # 刚下的是黑棋
                    break
                if b.full:
                    break
        self.assertGreaterEqual(wins, 2)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.P = Players("甲", "乙", "丙")

    def test_signed_game_verifies(self):
        rec = new_game(self.P, "甲", "乙")
        play(self.P, rec, BLACK_WINS, "甲", "乙")
        res = R.evaluate(rec)
        self.assertTrue(res["ok"])
        self.assertEqual((res["status"], res["winner"], len(res["moves"])), ("five", "b", 9))
        self.assertEqual(res["end_i"], 8)
        self.assertEqual(R.clean_record(rec), rec)                      # 格式检查原样通过

    def test_tampering_is_detected(self):
        rec = new_game(self.P, "甲", "乙")
        play(self.P, rec, BLACK_WINS, "甲", "乙")
        bad = R.clean_record(rec)
        bad["acts"][3]["x"] = 5                                         # 改了中间一步的位置
        self.assertEqual(R.evaluate(bad)["n_acts"], 3)                  # 从这一步起都不认
        self.assertEqual(R.evaluate(bad)["status"], "playing")
        bad2 = R.clean_record(rec)
        bad2["nb"] = "冒充的人"                                          # 改开局信息:签名对不上
        self.assertFalse(R.evaluate(bad2)["ok"])
        bad3 = R.clean_record(rec)
        bad3["acts"][8]["s"] = bad3["acts"][6]["s"]                     # 拿别的签名凑
        self.assertEqual(R.evaluate(bad3)["status"], "playing")
        # 丙替乙签一步:签名用的不是乙的私钥
        rec4 = new_game(self.P, "甲", "乙")
        act(self.P, rec4, "甲", "m", x=7, y=7)
        a = R.make_action(rec4, self.P.ids["丙"], "m", "w", T0 + 9000, x=8, y=8)
        rec4["acts"].append(a)
        self.assertEqual(R.evaluate(rec4)["n_acts"], 1)
        # 不轮到自己 / 下在已有棋子的位置
        rec5 = new_game(self.P, "甲", "乙")
        act(self.P, rec5, "甲", "m", x=7, y=7)
        rec5["acts"].append(R.make_action(rec5, self.P.ids["甲"], "m", "b", T0 + 9000, x=8, y=8))
        self.assertEqual(R.evaluate(rec5)["n_acts"], 1)
        rec6 = new_game(self.P, "甲", "乙")
        act(self.P, rec6, "甲", "m", x=7, y=7)
        act(self.P, rec6, "乙", "m", x=7, y=7)
        self.assertEqual(R.evaluate(rec6)["n_acts"], 1)
        self.assertIsNone(R.clean_record({**rec, "b": rec["w"]}))      # 自己和自己下
        self.assertIsNone(R.clean_record({**rec, "lim": 7}))
        self.assertIsNone(R.clean_record({**rec, "acts": [{"k": "m"}]}))

    def test_undo_needs_consent_and_resign_timeout(self):
        P = self.P
        rec = new_game(P, "甲", "乙")
        act(P, rec, "甲", "m", x=7, y=7)
        act(P, rec, "乙", "m", x=8, y=8)
        act(P, rec, "乙", "u", n=1)                                     # 乙要悔自己的棋,只能由甲同意
        self.assertEqual(R.evaluate(rec)["n_acts"], 2)
        rec["acts"].pop()
        act(P, rec, "甲", "u", n=1)                                     # 甲同意:乙那一手退回
        res = R.evaluate(rec)
        self.assertEqual((res["n_acts"], res["moves"], res["undos"]), (3, [(7, 7)], 1))
        act(P, rec, "乙", "m", x=6, y=6)
        act(P, rec, "甲", "m", x=9, y=9)
        act(P, rec, "乙", "u", n=2)                                     # 轮到乙;乙想退两手(自己的和甲的)只能由甲同意
        self.assertEqual(R.evaluate(rec)["n_acts"], 5)
        rec["acts"].pop()
        act(P, rec, "甲", "u", n=2)
        self.assertEqual(R.evaluate(rec)["moves"], [(7, 7)])
        self.assertEqual(R.evaluate(rec)["n_acts"], 6)
        act(P, rec, "乙", "r")
        res = R.evaluate(rec)
        self.assertEqual((res["status"], res["winner"]), ("resign", "b"))
        act(P, rec, "甲", "m", x=1, y=1)                                # 结束后再下:不认
        self.assertEqual(R.evaluate(rec)["n_acts"], 7)
        # 超时只能由轮到的一方自己认
        rec2 = new_game(P, "甲", "乙")
        act(P, rec2, "甲", "m", x=7, y=7)
        act(P, rec2, "甲", "t")
        self.assertEqual(R.evaluate(rec2)["status"], "playing")
        rec2["acts"].pop()
        act(P, rec2, "乙", "t")
        self.assertEqual(R.evaluate(rec2)["winner"], "b")

    def test_abandon_needs_ack_and_merge(self):
        P = self.P
        rec = new_game(P, "甲", "乙")
        play(P, rec, [(7, 7), (8, 8), (7, 8)], "甲", "乙")
        act(P, rec, "甲", "a")                                          # 甲说乙掉线了
        self.assertEqual(R.evaluate(rec)["status"], "abandon_pending")
        pending = R.clean_record(rec)
        act(P, rec, "甲", "k")                                          # 只能乙自己确认
        self.assertEqual(R.evaluate(rec)["status"], "abandon_pending")
        rec["acts"].pop()
        act(P, rec, "乙", "k")
        res = R.evaluate(rec)
        self.assertEqual((res["status"], res["winner"]), ("abandon", "b"))
        # 合并:结束的胜过没结束的;顺序无关
        self.assertIs(R.better(pending, rec), rec)
        self.assertIs(R.better(rec, pending), rec)
        short = R.clean_record(rec)
        short["acts"] = short["acts"][:2]
        self.assertIs(R.better(short, pending), pending)               # 都没结束:更长的
        # 同时操作:一边认输、一边落子(同一手)→ 大家选同一份
        a = new_game(P, "甲", "乙", mid="c" * 32)
        play(P, a, [(7, 7), (8, 8)], "甲", "乙")
        b = R.clean_record(a)
        act(P, a, "甲", "r")
        act(P, b, "甲", "m", x=1, y=1)
        self.assertIs(R.better(a, b), a)
        self.assertIs(R.better(b, a), a)


class LeagueTests(unittest.TestCase):
    def setUp(self):
        self.P = Players("甲", "乙", "丙", "丁")

    def _five(self, black, white, t0, mid=None):
        rec = new_game(self.P, black, white, mid=mid, t0=t0)
        play(self.P, rec, BLACK_WINS, black, white)
        return rec

    def test_points_rank_and_streaks(self):
        P = self.P
        recs = {}
        day = 3600 * 1000 * 30                                          # 每盘隔 30 小时,不碰每天上限
        order = [("甲", "乙"), ("甲", "丙"), ("乙", "丙"), ("甲", "丁"), ("丙", "甲")]   # 前一个执黑(黑必胜)
        for i, (b, w) in enumerate(order):
            r = self._five(b, w, T0 + i * day)
            recs[r["id"]] = r
        draw = new_game(P, "乙", "丁", t0=T0 + 6 * day)               # 平局:用"下满"太长,这里用认输测其它
        recs[draw["id"]] = draw                                         # 未下完:不计分
        games = league.games_from(recs, now=T0 + 100 * day)
        rows = league.standings(games)
        top = {r["nick"]: r for r in rows}
        self.assertEqual(top["甲"]["pts"], 9)                            # 3 胜 1 负
        self.assertEqual((top["甲"]["wins"], top["甲"]["losses"], top["甲"]["games"]), (3, 1, 4))
        self.assertEqual(top["甲"]["best"], 3)                           # 连赢乙、丙、丁
        self.assertEqual(top["甲"]["streak"], 0)                         # 最后一盘输给丙
        self.assertEqual(rows[0]["nick"], "甲")
        self.assertEqual(top["丙"]["pts"], 3)
        self.assertEqual(top["乙"]["pts"], 3)
        # 丙和乙同分同胜场:比胜率(乙 1/2,丙 1/3)
        self.assertLess(top["乙"]["rank"], top["丙"]["rank"])
        unfinished = next(g for g in games if g["id"] == draw["id"])
        self.assertFalse(unfinished["rated"])
        rank, me, above = league.rank_of(rows, P.hex("丙"))
        self.assertEqual(me["nick"], "丙")
        self.assertEqual(above["nick"], "乙")

    def test_ties_short_games_cap_and_future(self):
        P = self.P
        recs = {}
        for i in range(7):                                              # 甲乙 24 小时内下 7 盘:只有前 5 盘计分
            r = self._five("甲", "乙", T0 + i * 60_000)
            recs[r["id"]] = r
        quick = new_game(P, "丙", "丁", t0=T0)                         # 两手就认输:不计分
        act(P, quick, "丙", "m", x=7, y=7)
        act(P, quick, "丁", "r")
        recs[quick["id"]] = quick
        future = self._five("丙", "丁", T0 + 10 ** 9)                   # 时间在未来
        recs[future["id"]] = future
        games = league.games_from(recs, now=T0 + 3600_000)
        rated = [g for g in games if g["rated"]]
        self.assertEqual(len(rated), 5)
        capped = [g for g in games if "24 小时" in g["why"]]
        self.assertEqual(len(capped), 2)
        self.assertIn("不到 10 手", next(g for g in games if g["id"] == quick["id"])["why"])
        self.assertIn("时间异常", next(g for g in games if g["id"] == future["id"])["why"])
        rows = league.standings(games)
        self.assertEqual([(r["nick"], r["pts"]) for r in rows], [("甲", 15), ("乙", 0)])
        # 第二天:窗口滑过去了又能计分
        later = self._five("甲", "乙", T0 + 25 * 3600_000)
        recs[later["id"]] = later
        games = league.games_from(recs, now=T0 + 26 * 3600_000)
        self.assertTrue(next(g for g in games if g["id"] == later["id"])["rated"])
        # 完全并列:同一名次
        a = self._five("丙", "丁", T0 + 5 * 3600_000)
        b = self._five("丁", "丙", T0 + 6 * 3600_000)
        rows = league.standings(league.games_from({a["id"]: a, b["id"]: b}, now=T0 + 10 ** 10))
        self.assertEqual([r["rank"] for r in rows], [1, 1])
        # 历史记录
        hist = league.history(games, P.hex("乙"))
        self.assertEqual(len(hist), 8)
        self.assertEqual(hist[0]["opp_nick"], "甲")
        self.assertEqual({h["result"] for h in hist}, {"loss"})

    def test_periods_local_time(self):
        now = datetime.datetime(2026, 11, 18, 15, 30)                    # 周三下午
        lo, hi = league.period_bounds("today", now)
        self.assertEqual(datetime.datetime.fromtimestamp(lo / 1000), datetime.datetime(2026, 11, 18))
        self.assertEqual(hi - lo, 86400 * 1000)
        lo, hi = league.period_bounds("week", now)
        self.assertEqual(datetime.datetime.fromtimestamp(lo / 1000), datetime.datetime(2026, 11, 16))   # 周一
        self.assertEqual(league.period_bounds("total"), (None, None))
        recs = {}
        for t in (lo - 1000, lo + 1000):                                # 本周一 0 点前后各一盘
            r = self._five("甲", "乙", t - 27_000)                      # 第 9 手在开局 27 秒后,正好落在 t
            recs[r["id"]] = r
        games = league.games_from(recs, now=hi)
        week = league.standings(games, lo, hi)
        self.assertEqual(week[0]["games"], 1)
        self.assertEqual(league.standings(games)[0]["games"], 2)


if __name__ == "__main__":
    unittest.main()
