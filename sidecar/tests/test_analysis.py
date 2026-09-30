import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analysis  # noqa: E402
import sources.history as history  # noqa: E402
from sources.common import SourceError  # noqa: E402


class TestSinceDraft(unittest.TestCase):
    POS = {1: "RB", 2: "RB", 3: "RB", 4: "RB", 9: "K"}

    def test_change_is_pre_minus_now_averaged_over_sources(self):
        pre = {"harris": {1: 10, 2: 1}, "ffb": {1: 12, 2: 3}}
        now = {"fp": {1: 4, 2: 5}}
        out = analysis.since_draft(pre, now, self.POS)
        self.assertEqual(out[1], {"pre": 11, "now": 4, "change": 7})
        self.assertEqual(out[2], {"pre": 2, "now": 5, "change": -3})

    def test_new_and_off_the_board_have_no_change(self):
        out = analysis.since_draft({"harris": {1: 5}}, {"fp": {2: 3}},
                                   self.POS)
        self.assertEqual(out[1], {"pre": 5, "now": None, "change": None})
        self.assertEqual(out[2], {"pre": None, "now": 3, "change": None})

    def test_positions_without_predraft_ranks_are_left_out(self):
        # Kickers have ROS ranks but no pre-draft ranks: not all "new".
        out = analysis.since_draft({"harris": {1: 5}},
                                   {"fp": {1: 4, 9: 1}}, self.POS)
        self.assertNotIn(9, out)


class TestWeekAccuracy(unittest.TestCase):
    def test_finish_ties_share_the_better_rank(self):
        pos = {1: "QB", 2: "QB", 3: "QB", 4: "RB"}
        f = analysis.actual_finish({1: 20, 2: 30, 3: 20, 4: 5}, pos)
        self.assertEqual(f, {2: 1, 1: 2, 3: 2, 4: 1})

    def test_spearman(self):
        self.assertAlmostEqual(analysis.spearman([1, 2, 3], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(analysis.spearman([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertIsNone(analysis.spearman([1, 2], [1, 2]))
        self.assertIsNone(analysis.spearman([1, 2, 3], [5, 5, 5]))

    def test_summary_and_players(self):
        # 14 QBs scored; the source ranks QBs 1..13 (13 is outside top 12).
        pos = {pid: "QB" for pid in range(1, 15)}
        points = {pid: 100 - pid for pid in range(1, 15)}   # 1 is best
        points[2] = 0.0     # ranked #2, busted: finishes 14th
        points[14] = 150.0  # unranked, finishes 1st
        ranks = {"harris": {pid: pid for pid in range(1, 14)}}
        out = analysis.week_accuracy(ranks, points, pos)
        (row,) = out["summary"]
        self.assertEqual((row["pos"], row["source"], row["n"], row["k"]),
                         ("QB", "harris", 13, 12))
        # Top 12 by rank: 1..12. #2 busted, so 11 hits.
        self.assertEqual(row["hits"], 11)
        self.assertGreater(row["rho"], 0)
        by_id = {p["espnId"]: p for p in out["players"]}
        self.assertEqual(by_id[2]["finish"], 14)
        self.assertEqual(by_id[2]["ranks"], {"harris": 2})
        # 14 finished top 12 without being ranked: shown, with no ranks.
        self.assertEqual((by_id[14]["ranks"], by_id[14]["finish"]), ({}, 1))

    def test_ranked_player_without_stats_scored_zero(self):
        pos = {1: "RB", 2: "RB", 3: "RB"}
        out = analysis.week_accuracy({"ffb": {1: 1, 2: 2, 3: 3}},
                                     {1: 10.0, 2: 5.0}, pos)
        by_id = {p["espnId"]: p for p in out["players"]}
        self.assertEqual((by_id[3]["pts"], by_id[3]["finish"]), (0.0, 3))


class TestLookback(unittest.TestCase):
    def test_assembles_weeks_and_since_draft(self):
        ranks = {"predraft": {"harris": {1: 3}}, "ros": {"fp": {1: 1}},
                 "week1": {"harris": {1: 1, 2: 2, 3: 3}}}
        hist = {"weeks": [1, 2], "actuals": {
            "1": {"pos": "WR", "pts": {"1": 9.0}},
            "2": {"pos": "WR", "pts": {"1": 12.0}},
            "3": {"pos": "WR", "pts": {"1": 1.0}}}}
        out = analysis.lookback(ranks, hist)
        self.assertEqual(out["sinceDraft"]["1"]["change"], 2)
        self.assertEqual(list(out["weeks"]), ["1"])  # week 2 has no ranks
        self.assertEqual(out["preSources"], ["harris"])

    def test_no_history_is_empty(self):
        self.assertEqual(analysis.lookback({"ros": {}}, None),
                         {"sinceDraft": {}, "preSources": [], "weeks": {}})


class TestHistoryParse(unittest.TestCase):
    PREDRAFT = {"players": {
        "josh-allen-buf": {"name": "Josh Allen", "team": "BUF",
                           "position": "QB", "ranks": {
                               "standard": {"harris": 9},
                               "ppr": {"harris": 1, "ffballers": 2,
                                       "composite": 1}}},
        "texans": {"name": "Houston Texans", "team": "HOU",
                   "position": "DST",
                   "ranks": {"ppr": {"harris": 1}}}}}
    WEEK1 = {"players": [
        {"name": "Lamar Jackson", "position": "QB", "rank": 1,
         "source": "harris"},
        {"name": "Jacksonville Jaguars", "position": "DST", "rank": 1,
         "source": "ffballers"},
        {"name": "Someone", "position": "QB", "rank": 1,
         "source": "unknown"}]}
    ESPN = {"players": [{"player": {
        "id": 3918298, "defaultPositionId": 1,
        "stats": [
            {"seasonId": 2026, "scoringPeriodId": 1, "statSourceId": 0,
             "statSplitTypeId": 1, "appliedTotal": 24.26},
            {"seasonId": 2025, "scoringPeriodId": 1, "statSourceId": 0,
             "statSplitTypeId": 1, "appliedTotal": 99.0},
            {"seasonId": 2026, "scoringPeriodId": 2, "statSourceId": 1,
             "statSplitTypeId": 1, "appliedTotal": 20.0},
            {"seasonId": 2026, "scoringPeriodId": 0, "statSourceId": 0,
             "statSplitTypeId": 0, "appliedTotal": 70.0}]}}]}

    def test_rows_use_ppr_ranks_and_source_keys(self):
        out = history.parse(self.PREDRAFT, {1: self.WEEK1}, self.ESPN, 2026)
        rows = {(r["view"], r["source"], r["name"]): r for r in out["rows"]}
        self.assertEqual(rows[("predraft", "harris", "Josh Allen")]["rank"], 1)
        self.assertEqual(rows[("predraft", "ffb", "Josh Allen")]["rank"], 2)
        self.assertEqual(rows[("predraft", "harris", "Houston Texans")]["pos"],
                         "D/ST")
        self.assertEqual(rows[("week1", "ffb", "Jacksonville Jaguars")]["pos"],
                         "D/ST")
        self.assertNotIn("composite", {r["source"] for r in out["rows"]})
        self.assertEqual(len(out["rows"]), 5)  # unknown source dropped
        self.assertEqual(out["weeks"], [1])

    def test_actuals_keep_only_this_seasons_weekly_actuals(self):
        out = history.parse(self.PREDRAFT, {}, self.ESPN, 2026)
        self.assertEqual(out["actuals"],
                         {"3918298": {"pos": "QB", "pts": {"1": 24.26}}})

    def test_empty_inputs_are_a_source_failure(self):
        with self.assertRaises(SourceError):
            history.parse({}, {}, self.ESPN, 2026)
        with self.assertRaises(SourceError):
            history.parse(self.PREDRAFT, {}, {"players": []}, 2026)

    def test_missing_config_is_a_source_failure(self):
        with self.assertRaises(SourceError):
            history.fetch(None, {}, 2026)


if __name__ == "__main__":
    unittest.main()
