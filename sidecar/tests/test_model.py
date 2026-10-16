import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"

# FFF's real scoring for the stats FFB projects (mSettings, 2026).
FFF_ITEMS = [
    {"statId": 4, "points": 6.0}, {"statId": 5, "points": 0.2},
    {"statId": 20, "points": -2.0}, {"statId": 24, "points": 0.1},
    {"statId": 25, "points": 6.0}, {"statId": 42, "points": 0.1},
    {"statId": 43, "points": 6.0}, {"statId": 53, "points": 0.5},
    {"statId": 72, "points": -2.0},
]
# FFF's lineup: QB, RB x2, WR x2, WR/TE, FLEX, D/ST, K, 5 bench, 1 IR.
FFF_SLOTS = {"0": 1, "2": 2, "4": 2, "5": 1, "6": 0, "16": 1, "17": 1,
             "20": 5, "21": 1, "23": 1}


def p(pid, pos, slot=20, bye=None, status="OWNED"):
    return {"espnId": pid, "name": f"P{pid}", "pos": pos, "team": "X",
            "status": status, "lineupSlotId": slot, "bye": bye}


class TestScoring(unittest.TestCase):
    def test_points_by_stat_override_wins(self):
        pts = model.points_by_stat([{"statId": 53, "points": 1.0,
                                     "pointsOverrides": {"16": 0.5}},
                                    {"statId": 4, "points": 6.0}])
        self.assertEqual(pts, {53: 0.5, 4: 6.0})

    def test_project_points_hand_computed(self):
        pts = model.points_by_stat(FFF_ITEMS)
        qb = {"passing_yards": "250", "passing_touchdowns": "2",
              "interceptions_thrown": "1", "rushing_yards": "20",
              "fumbles_lost": "0.5"}
        # 250/5*0.2=10 + 12 - 2 + 2 - 1 = 21
        self.assertAlmostEqual(model.project_points(qb, pts), 21.0)
        wr = {"receptions": "6", "receiving_yards": "80",
              "receiving_touchdowns": "0.5", "rushing_yards": "0.16"}
        # 3 + 8 + 3 + 0.016 = 14.016
        self.assertAlmostEqual(model.project_points(wr, pts), 14.016)

    def test_unscored_and_bad_fields_ignored(self):
        pts = {53: 0.5}
        self.assertEqual(model.project_points({"receptions": "x", "risk": "9"}, pts), 0)


class TestRanks(unittest.TestCase):
    def test_overall_rank_becomes_positional_and_stats_rank_by_points(self):
        pts = model.points_by_stat(FFF_ITEMS)
        rows = [
            {"source": "fp", "view": "ros", "pos": "RB", "espnId": 10, "rank": 3},
            {"source": "fp", "view": "ros", "pos": "WR", "espnId": 20, "rank": 1},
            {"source": "fp", "view": "ros", "pos": "RB", "espnId": 11, "rank": 7},
            {"source": "ffb-andy", "view": "weekly", "pos": "WR", "espnId": 20,
             "stats": {"receptions": "5", "receiving_yards": "60"}},
            {"source": "ffb-andy", "view": "weekly", "pos": "WR", "espnId": 21,
             "stats": {"receptions": "7", "receiving_yards": "90"}},
        ]
        r = model.positional_ranks(rows, pts)
        self.assertEqual(r["ros"]["fp"], {10: 1, 11: 2, 20: 1})
        self.assertEqual(r["weekly"]["ffb-andy"], {21: 1, 20: 2})

    def test_consensus_toggle_and_spread(self):
        by_src = {"harris": {1: 1, 2: 5}, "ffb-andy": {1: 3, 2: 4},
                  "ffb-mike": {1: 8}}
        c = model.consensus(by_src, ["harris", "ffb-andy", "ffb-mike"])
        self.assertAlmostEqual(c[1]["avg"], 4.0)
        self.assertEqual((c[1]["n"], c[1]["spread"]), (3, 7))
        c2 = model.consensus(by_src, ["harris"])          # toggled down to one
        self.assertEqual((c2[1]["avg"], c2[1]["n"], c2[1]["spread"]), (1, 1, 0))
        self.assertEqual(model.consensus(by_src, ["nope"]), {})

    def test_board_order_puts_thinly_ranked_after(self):
        cons = {1: {"avg": 1.0, "n": 1}, 2: {"avg": 3.0, "n": 3}, 3: {"avg": 2.0, "n": 2}}
        self.assertEqual(model.board_order(cons, 3), [3, 2, 1])

    def test_tiers(self):
        self.assertEqual(model.tiers([1, 2, 3, 8, 9, 10, 20]), [1, 1, 1, 2, 2, 2, 3])
        self.assertEqual(model.tiers([1, 2, 3, 4]), [1, 1, 1, 1])
        self.assertEqual(model.tiers([]), [])
        self.assertEqual(model.tiers([5.0]), [1])

    def test_movers(self):
        self.assertEqual(model.movers({1: 3.0, 2: 10.0, 3: 1.0}, {1: 5.0, 2: 8.5}),
                         {1: 2.0, 2: -1.5})


class TestLineup(unittest.TestCase):
    def test_fff_lineup_needs_no_te(self):
        full = ["QB", "RB", "RB", "WR", "WR", "WR", "WR", "D/ST", "K"]
        self.assertTrue(model.can_fill_lineup(full, FFF_SLOTS))
        self.assertFalse(model.can_fill_lineup(full[:-1], FFF_SLOTS))      # no K
        self.assertTrue(model.can_fill_lineup(
            ["QB", "RB", "RB", "RB", "WR", "WR", "TE", "D/ST", "K"], FFF_SLOTS))
        self.assertFalse(model.can_fill_lineup(
            ["QB", "RB", "WR", "WR", "TE", "TE", "TE", "D/ST", "K"], FFF_SLOTS))  # 1 RB


class TestAdvice(unittest.TestCase):
    def setUp(self):
        self.mine = [p(1, "QB", 0), p(2, "RB", 2), p(3, "RB", 2), p(4, "WR", 4),
                     p(5, "WR", 4), p(6, "WR", 5), p(7, "RB", 23), p(8, "D/ST", 16),
                     p(9, "K", 17), p(10, "RB", 20), p(11, "WR", 20),
                     p(12, "RB", 21)]                                  # 12 on IR
        self.cons = {1: {"avg": 5}, 2: {"avg": 2}, 3: {"avg": 9}, 4: {"avg": 3},
                     5: {"avg": 12}, 6: {"avg": 20}, 7: {"avg": 15}, 10: {"avg": 40},
                     11: {"avg": 45}, 12: {"avg": 99},
                     50: {"avg": 22}, 51: {"avg": 30}, 52: {"avg": 42}}
        self.fas = [p(50, "RB", None, status="FA"), p(51, "WR", None, status="WAIVERS"),
                    p(52, "WR", None, status="FA")]

    def test_upgrades_margin_ir_and_one_per_drop(self):
        s = model.upgrades(self.mine, self.fas, self.cons, FFF_SLOTS, margin=5)
        pairs = [(x["add"]["espnId"], x["drop"]["espnId"], x["gain"]) for x in s]
        # RB: FA 50 (22) vs worst active RB 10 (40): gain 18. IR player 12 (99)
        # is never the drop. WR: FA 51 (30) vs 11 (45): gain 15; FA 52 (42)
        # only gains 3, below the margin.
        self.assertEqual(pairs, [(50, 10, 18.0), (51, 11, 15.0)])

    def test_upgrade_never_breaks_lineup(self):
        mine = [p(1, "QB", 0), p(2, "RB", 2), p(3, "RB", 2), p(4, "WR", 4),
                p(5, "WR", 4), p(6, "WR", 5), p(7, "WR", 23), p(8, "D/ST", 16),
                p(9, "K", 17)]
        cons = {9: {"avg": 30}, 60: {"avg": 1}}
        s = model.upgrades(mine, [p(60, "K", None, status="FA")], cons, FFF_SLOTS)
        self.assertEqual([x["drop"]["espnId"] for x in s], [9])   # K for K is fine
        cons = {3: {"avg": 40}, 61: {"avg": 1}}
        # There's no swap at all without a same-position FA: never drop an RB for a WR.
        self.assertEqual(model.upgrades(mine, [p(61, "WR", None, status="FA")],
                                        cons, FFF_SLOTS), [])

    def test_unranked_owned_player_not_suggested_as_drop(self):
        cons = {50: {"avg": 1}}
        self.assertEqual(model.upgrades(self.mine, self.fas, cons, FFF_SLOTS), [])

    def test_drop_candidates_bench_only_sorted_by_deficit(self):
        d = model.drop_candidates(self.mine, self.fas, self.cons)
        self.assertEqual([(x["player"]["espnId"], x["deficit"]) for x in d],
                         [(10, 18.0), (11, 15.0)])

    def test_bye_conflicts_starters_in_window(self):
        mine = [p(1, "QB", 0, bye=6), p(2, "RB", 2, bye=6), p(3, "RB", 20, bye=6),
                p(4, "WR", 4, bye=9), p(5, "WR", 4, bye=5)]
        out = model.bye_conflicts(mine, current_week=5, horizon=3)
        self.assertEqual({w: [x["espnId"] for x in ps] for w, ps in out.items()},
                         {5: [5], 6: [1, 2]})


KEEPERS = {"udfaBase": 5, "increments": [7, 10, 12, 15], "overrides": {}}


def pick(bid, kept=False):
    return {"bid": bid, "keeper": kept}


class TestKeeperPrice(unittest.TestCase):
    """ENH-037 vectors (all real FFF players)."""

    def test_udfa_no_pick_this_season(self):
        r = model.keeper_price({}, 2026, KEEPERS)
        self.assertEqual((r["price"], r["base"], r["kind"], r["used"]),
                         (12, 5, "udfa", 0))
        self.assertFalse(r["estimated"])

    def test_first_auction_buy(self):
        r = model.keeper_price({2026: pick(1)}, 2026, KEEPERS)
        self.assertEqual((r["price"], r["kind"], r["used"]), (8, "auction", 0))

    def test_first_keeper_year(self):
        r = model.keeper_price({2025: pick(1), 2026: pick(8, True)}, 2026, KEEPERS)
        self.assertEqual((r["price"], r["kind"], r["used"]), (18, "kept", 1))

    def test_third_keeper_year_uses_fourth_tier(self):
        picks = {2023: pick(22), 2024: pick(29, True), 2025: pick(39, True),
                 2026: pick(51, True)}
        r = model.keeper_price(picks, 2026, KEEPERS)
        self.assertEqual((r["price"], r["used"]), (66, 3))
        self.assertFalse(r["estimated"])

    def test_rebuy_at_auction_resets_the_chain(self):
        picks = {2023: pick(10, True), 2024: pick(40), 2025: pick(27),
                 2026: pick(34, True)}
        r = model.keeper_price(picks, 2026, KEEPERS)
        self.assertEqual((r["price"], r["used"]), (44, 1))

    def test_fourth_keeper_year_is_estimated(self):
        # Real: 4241389, $1 -> 8 -> 18 -> 30 -> 45 from 2020-24 (kept).
        # Next price 45 + 15 = 60, k = 4 -> estimated.
        picks = {2020: pick(1), 2021: pick(8, True), 2022: pick(18, True),
                 2023: pick(30, True), 2024: pick(45, True)}
        r = model.keeper_price(picks, 2024, KEEPERS)
        self.assertEqual((r["price"], r["used"]), (60, 4))
        self.assertTrue(r["estimated"])

    def test_chain_reaching_earliest_season_is_estimated(self):
        # Kept back to 2019 (the first fetched season): k is a lower bound.
        base = {2020: pick(12, True), 2021: pick(24, True)}
        r = model.keeper_price({**base, 2019: pick(5, True)}, 2021, KEEPERS)
        self.assertEqual((r["used"], r["price"]), (3, 39))
        self.assertTrue(r["estimated"])
        # Same chain bounded by a 2019 auction re-buy: exact, one shorter.
        r2 = model.keeper_price({**base, 2019: pick(5)}, 2021, KEEPERS)
        self.assertEqual((r2["used"], r2["price"]), (2, 36))
        self.assertFalse(r2["estimated"])

    def test_dropped_player_with_old_history_is_udfa(self):
        # Kept in 2023-24, not in the 2025/26 drafts -> UDFA base, not a
        # continuation of the old chain (owner-confirmed).
        r = model.keeper_price({2023: pick(14, True), 2024: pick(24, True)},
                               2026, KEEPERS)
        self.assertEqual((r["price"], r["kind"], r["used"]), (12, "udfa", 0))

    def test_override_replaces_computed_price(self):
        keepers = {**KEEPERS, "overrides": {"777": 99}}
        r = model.keeper_price({2026: pick(1)}, 2026, keepers, espn_id=777)
        self.assertEqual((r["price"], r["override"]), (99, True))
        self.assertFalse(r["estimated"])
        # The Draft column still shows the real pick.
        self.assertEqual((r["kind"], r["base"]), ("auction", 1))


class TestKeeperBacktest(unittest.TestCase):
    """The rule against the league's recorded keeper prices.

    fixtures/draft_backtest.json is trimmed real FFF data: every player
    with a keeper pick in 2024-26, with full 2019+ history. Expected
    result from the owner's backtest: 50 of 53 match; the three misses
    are commissioner-entered exceptions (candidates for config
    "overrides").
    """

    @classmethod
    def setUpClass(cls):
        raw = json.loads((FIX / "draft_backtest.json")
                         .read_text(encoding="utf-8"))
        cls.picks = {int(pid): {int(s): v for s, v in ps.items()}
                     for pid, ps in raw["picks"].items()}

    def test_2024_all_nineteen_match(self):
        self.assertEqual(model.keeper_backtest(self.picks, 2024, KEEPERS),
                         (19, []))

    def test_2025_two_commissioner_exceptions(self):
        self.assertEqual(model.keeper_backtest(self.picks, 2025, KEEPERS),
                         (14, [(4426502, 25, 28), (4596448, 22, 12)]))

    def test_2026_one_commissioner_exception(self):
        self.assertEqual(model.keeper_backtest(self.picks, 2026, KEEPERS),
                         (17, [(4372016, 8, 15)]))

    def test_total_is_50_of_53(self):
        total = sum(model.keeper_backtest(self.picks, s, KEEPERS)[0]
                    for s in (2024, 2025, 2026))
        self.assertEqual(total, 50)


if __name__ == "__main__":
    unittest.main()
