"""Tests for compute.py — the dual-point math (SPEC.md §9 L2).

Run: python -m unittest test_compute -v

Covers the mandatory scenarios: a normal week, an H2H tie, a top-half
boundary tie, and that weeks 15-17 contribute no dual points.
"""
import unittest

import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

import build
import compute
import fetch

UPDATED = "2026-09-18T13:04:11Z"


def make_matchup(week, home_id, away_id, home_score, away_score, played=True):
    if not played:
        return {
            "matchupPeriodId": week,
            "home": {"teamId": home_id, "totalPoints": 0.0},
            "away": {"teamId": away_id, "totalPoints": 0.0},
            "winner": "UNDECIDED",
        }
    if home_score > away_score:
        winner = "HOME"
    elif away_score > home_score:
        winner = "AWAY"
    else:
        winner = "TIE"
    return {
        "matchupPeriodId": week,
        "home": {"teamId": home_id, "totalPoints": home_score},
        "away": {"teamId": away_id, "totalPoints": away_score},
        "winner": winner,
    }


def week_games(scores, week=1):
    """Pair 12 scores in order: (1,2), (3,4), (5,6), (7,8), (9,10), (11,12)."""
    assert len(scores) == 12
    return [(2 * i + 1, 2 * i + 2, scores[2 * i], scores[2 * i + 1])
            for i in range(6)]


def make_bracket_matchup(week, home_id, away_id, home_score, away_score,
                         tier="WINNERS_BRACKET", played=True):
    """A playoff-bracket schedule entry. away_id=None makes it a bye (no
    'away' side at all), which is how ESPN represents a top-seed bye.
    """
    m = make_matchup(week, home_id, away_id or 1, home_score,
                     away_score or 0.0, played=played)
    m["playoffTierType"] = tier
    if away_id is None:
        del m["away"]
        m["winner"] = "UNDECIDED"
    return m


def make_raw(weeks, week_count=14, season=2025, bracket=None,
             playoff_team_count=6, name="Fantasy Football Fantasy",
             final_ranks=None):
    """Build a raw-fetch-shaped dict.

    weeks: {week: [(home_id, away_id, home_score, away_score[, played]), ...]}
    bracket: optional list of pre-built playoff schedule entries.
    """
    schedule = []
    for week, games in weeks.items():
        for game in games:
            schedule.append(make_matchup(week, *game))
    for m in bracket or []:
        schedule.append(m)
    teams = [{"id": i, "name": f"Team {i}", "primaryOwner": f"{{o{i}}}",
              "owners": [f"{{o{i}}}"],
              # ESPN publishes 0 until the season is over.
              "rankCalculatedFinal": (final_ranks or {}).get(i, 0)}
             for i in range(1, 13)]
    members = [{"id": f"{{o{i}}}", "firstName": f"First{i}",
                "lastName": f"Last{i}", "displayName": f"user{i}"}
               for i in range(1, 13)]
    return {
        "mMatchupScore": {"seasonId": season, "id": 877873, "schedule": schedule},
        "mTeam": {"teams": teams, "members": members},
        "mSettings": {"settings": {"name": name,
                                   "scheduleSettings":
                                   {"matchupPeriodCount": week_count,
                                    "playoffTeamCount": playoff_team_count}}},
    }


def full_season_weeks():
    """14 weeks of distinct scores: week w, team i scores 100 + 10w + (i-1)."""
    return {w: week_games([100 + 10 * w + i for i in range(12)], week=w)
            for w in range(1, 15)}


class TestNormalWeek(unittest.TestCase):
    """A normal week: 12 distinct scores, 6 decided matchups."""

    SCORES = [150, 100, 140, 110, 130, 120, 125, 105, 115, 135, 108, 118]

    def setUp(self):
        self.week = compute.compute_week(1, [make_matchup(1, *g)
                                              for g in week_games(self.SCORES)])

    def test_score_to_beat_is_sixth_lowest(self):
        # sorted: 100 105 108 110 115 118 | 120 125 130 135 140 150
        self.assertEqual(self.week["scoreToBeat"], 118)

    def test_h2h_points_go_to_higher_score(self):
        self.assertEqual([g["winner"] for g in self.week["games"]],
                         [1, 3, 5, 7, 10, 12])

    def test_top_half_is_strictly_above_score_to_beat(self):
        top_half = {t["teamId"] for t in self.week["teams"] if t["topHalf"]}
        self.assertEqual(top_half, {1, 3, 5, 6, 7, 10})

    def test_week_points(self):
        expected = {1: 2, 2: 0, 3: 2, 4: 0, 5: 2, 6: 1,
                    7: 2, 8: 0, 9: 0, 10: 2, 11: 0, 12: 1}
        for t in self.week["teams"]:
            self.assertEqual(t["weekPoints"], expected[t["teamId"]],
                             f"team {t['teamId']}")
        # a normal week distributes 6 H2H + 6 top-half = 12 points
        self.assertEqual(sum(t["weekPoints"] for t in self.week["teams"]), 12)

    def test_week_shape(self):
        self.assertEqual(self.week["week"], 1)
        self.assertEqual(len(self.week["games"]), 6)
        self.assertEqual(len(self.week["teams"]), 12)
        self.assertEqual([t["teamId"] for t in self.week["teams"]],
                         list(range(1, 13)))


class TestH2HTie(unittest.TestCase):
    """An exact H2H tie: no point to either team."""

    SCORES = [100, 100, 140, 110, 130, 120, 125, 105, 115, 135, 108, 118]

    def setUp(self):
        self.week = compute.compute_week(1, [make_matchup(1, *g)
                                              for g in week_games(self.SCORES)])

    def test_tied_game_has_no_winner(self):
        self.assertIsNone(self.week["games"][0]["winner"])

    def test_tied_teams_get_no_h2h_point(self):
        by_id = {t["teamId"]: t for t in self.week["teams"]}
        self.assertEqual(by_id[1]["h2h"], 0)
        self.assertEqual(by_id[2]["h2h"], 0)
        # only 5 H2H points awarded that week
        self.assertEqual(sum(t["h2h"] for t in self.week["teams"]), 5)

    def test_rest_of_week_unaffected(self):
        # sorted: 100 100 105 108 110 115 | 118 120 125 130 135 140
        self.assertEqual(self.week["scoreToBeat"], 115)
        by_id = {t["teamId"]: t for t in self.week["teams"]}
        self.assertEqual([t["teamId"] for t in self.week["teams"] if t["topHalf"]],
                         [3, 5, 6, 7, 10, 12])
        self.assertEqual(sum(t["weekPoints"] for t in self.week["teams"]), 11)


class TestTopHalfBoundaryTie(unittest.TestCase):
    """6th and 7th lowest scores identical: neither gets the top-half point,
    so the league awards 5 top-half points that week rather than 7."""

    SCORES = [90, 91, 92, 93, 94, 100, 100, 101, 102, 103, 104, 105]

    def setUp(self):
        self.week = compute.compute_week(1, [make_matchup(1, *g)
                                              for g in week_games(self.SCORES)])

    def test_score_to_beat_is_the_tied_score(self):
        # sorted: 90 91 92 93 94 100 100 101 102 103 104 105
        self.assertEqual(self.week["scoreToBeat"], 100)

    def test_teams_at_the_boundary_get_no_point(self):
        by_id = {t["teamId"]: t for t in self.week["teams"]}
        self.assertEqual(by_id[6]["score"], 100)
        self.assertEqual(by_id[7]["score"], 100)
        self.assertEqual(by_id[6]["topHalf"], 0)
        self.assertEqual(by_id[7]["topHalf"], 0)

    def test_only_five_top_half_points_awarded(self):
        self.assertEqual(sum(t["topHalf"] for t in self.week["teams"]), 5)
        by_id = {t["teamId"]: t for t in self.week["teams"]}
        self.assertEqual([t["teamId"] for t in self.week["teams"] if t["topHalf"]],
                         [8, 9, 10, 11, 12])


class TestPlayoffWeeksContributeNothing(unittest.TestCase):
    """Weeks 15-17 are the playoff bracket: no dual points, no standings data."""

    def setUp(self):
        weeks = full_season_weeks()
        # playoff bracket with huge scores that would distort anything
        # if they leaked into the regular-season math
        weeks[15] = [(1, 2, 500, 400), (3, 4, 450, 350), (5, 6, 420, 380)]
        weeks[16] = [(1, 3, 600, 300), (5, 2, 550, 320)]
        weeks[17] = [(1, 5, 700, 200)]
        self.out = compute.build_standings(make_raw(weeks), UPDATED)

    def test_only_regular_season_weeks_present(self):
        self.assertEqual(self.out["throughWeek"], 14)
        self.assertEqual(self.out["regularSeasonWeeks"], 14)
        self.assertEqual(len(self.out["weeks"]), 14)
        self.assertEqual(max(w["week"] for w in self.out["weeks"]), 14)

    def test_playoff_scores_do_not_reach_standings(self):
        by_id = {r["teamId"]: r for r in self.out["standings"]}
        # team 1's regular-season scores: 100 + 10w for w in 1..14
        expected_pf = sum(100 + 10 * w for w in range(1, 15))
        self.assertEqual(by_id[1]["pointsFor"], expected_pf)
        self.assertEqual(by_id[1]["averageScore"], round(expected_pf / 14, 1))
        # 14 regular-season games, no ties in this fixture
        wins, losses = by_id[1]["record"].split("-")
        self.assertEqual(int(wins) + int(losses), 14)
        # dual points capped at 2 per week x 14 weeks
        for r in self.out["standings"]:
            self.assertLessEqual(r["points"], 28)
            self.assertEqual(r["points"],
                             r["h2hPoints"] + r["topHalfPoints"])

    def test_identical_output_without_playoff_weeks(self):
        out_no_playoffs = compute.build_standings(
            make_raw(full_season_weeks()), UPDATED)
        self.assertEqual(self.out["standings"], out_no_playoffs["standings"])
        self.assertEqual(self.out["weeks"], out_no_playoffs["weeks"])


class TestInProgressSeason(unittest.TestCase):
    """An in-progress season: unplayed weeks are UNDECIDED with 0.0 scores."""

    def setUp(self):
        weeks = {
            1: week_games([150, 100, 140, 110, 130, 120,
                           125, 105, 115, 135, 108, 118], week=1),
            2: week_games([110, 120, 100, 130, 125, 105,
                           140, 95, 135, 100, 150, 90], week=2),
        }
        for w in range(3, 15):
            weeks[w] = [(2 * i + 1, 2 * i + 2, 0.0, 0.0, False)
                        for i in range(6)]
        self.out = compute.build_standings(make_raw(weeks), UPDATED)

    def test_through_week_stops_at_last_complete_week(self):
        self.assertEqual(self.out["throughWeek"], 2)
        self.assertEqual([w["week"] for w in self.out["weeks"]], [1, 2])

    def test_standings_cover_played_weeks_only(self):
        by_id = {r["teamId"]: r for r in self.out["standings"]}
        self.assertEqual(len(self.out["standings"]), 12)
        # team 1: 150 + 110
        self.assertEqual(by_id[1]["pointsFor"], 260.0)
        self.assertEqual(by_id[1]["averageScore"], 130.0)
        wins, losses = by_id[1]["record"].split("-")
        self.assertEqual(int(wins) + int(losses), 2)


class TestStandingsShapeAndSort(unittest.TestCase):
    """§5 output shape, sort order, and record format."""

    def setUp(self):
        self.out = compute.build_standings(make_raw(full_season_weeks()),
                                           UPDATED)

    def test_top_level_keys(self):
        self.assertEqual(self.out["season"], 2025)
        self.assertEqual(self.out["league"], "877873")
        self.assertEqual(self.out["updated"], UPDATED)
        self.assertEqual(self.out["regularSeasonWeeks"], 14)
        self.assertEqual(self.out["throughWeek"], 14)
        self.assertEqual(len(self.out["standings"]), 12)

    def test_ranks_and_sort_order(self):
        rows = self.out["standings"]
        self.assertEqual([r["rank"] for r in rows], list(range(1, 13)))
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a["points"], b["points"])
            if a["points"] == b["points"]:
                self.assertGreaterEqual(a["pointsFor"], b["pointsFor"])

    def test_every_week_distributes_twelve_points(self):
        for w in self.out["weeks"]:
            self.assertEqual(len(w["games"]), 6)
            self.assertEqual(len(w["teams"]), 12)
            self.assertEqual(sum(t["weekPoints"] for t in w["teams"]), 12)

    def test_record_and_owner(self):
        by_id = {r["teamId"]: r for r in self.out["standings"]}
        for r in self.out["standings"]:
            wins, losses = r["record"].split("-")
            self.assertEqual(int(wins) + int(losses), 14)
        self.assertEqual(by_id[1]["owner"], "First1 Last1")
        self.assertEqual(by_id[1]["name"], "Team 1")

    def test_record_includes_ties_when_there_are_any(self):
        weeks = {
            1: week_games([100, 100, 140, 110, 130, 120,
                           125, 105, 115, 135, 108, 118], week=1),
            2: week_games([90, 120, 100, 130, 125, 105,
                           140, 95, 135, 100, 150, 90], week=2),
        }
        out = compute.build_standings(make_raw(weeks, week_count=2), UPDATED)
        by_id = {r["teamId"]: r for r in out["standings"]}
        # team 1: week 1 tie (100-100), week 2 loss (90 vs 120)
        self.assertEqual(by_id[1]["record"], "0-1-1")


class TestLuckIndexAndStreak(unittest.TestCase):
    """Luck index (h2hPoints - topHalfPoints) and current H2H streak.

    full_season_weeks() pairs teams (1,2) (3,4) ... (11,12) every week with
    strictly increasing scores by team id, so the higher id in each pair
    always wins H2H. Team 2 wins every week (h2h) while always scoring in
    the bottom half (topHalf never earned) -- maximally lucky. Team 12 wins
    every week AND always scores top-half -- deserved wins, no luck. Team 1
    loses every week and is always bottom half -- unlucky in neither
    direction, just bad.
    """

    def setUp(self):
        self.out = compute.build_standings(make_raw(full_season_weeks()),
                                           UPDATED)
        self.by_id = {r["teamId"]: r for r in self.out["standings"]}

    def test_lucky_team_wins_without_scoring(self):
        team2 = self.by_id[2]
        self.assertEqual(team2["h2hPoints"], 14)
        self.assertEqual(team2["topHalfPoints"], 0)
        self.assertEqual(team2["luckIndex"], 14)
        self.assertEqual(team2["streak"], "W14")

    def test_deserving_team_has_no_luck(self):
        team12 = self.by_id[12]
        self.assertEqual(team12["h2hPoints"], 14)
        self.assertEqual(team12["topHalfPoints"], 14)
        self.assertEqual(team12["luckIndex"], 0)
        self.assertEqual(team12["streak"], "W14")

    def test_losing_team_streak_and_zero_luck(self):
        team1 = self.by_id[1]
        self.assertEqual(team1["h2hPoints"], 0)
        self.assertEqual(team1["topHalfPoints"], 0)
        self.assertEqual(team1["luckIndex"], 0)
        self.assertEqual(team1["streak"], "L14")

    def test_streak_breaks_on_result_change(self):
        weeks = {
            1: week_games([150, 100, 140, 110, 130, 120,
                           125, 105, 115, 135, 108, 118], week=1),
            2: week_games([90, 120, 100, 130, 125, 105,
                           140, 95, 135, 100, 150, 91], week=2),
        }
        # team 1: week 1 win (150 > 100), week 2 loss (90 < 120)
        out = compute.build_standings(make_raw(weeks, week_count=2), UPDATED)
        by_id = {r["teamId"]: r for r in out["standings"]}
        self.assertEqual(by_id[1]["streak"], "L1")

    def test_no_games_played_streak_is_dash(self):
        weeks = {w: [(2 * i + 1, 2 * i + 2, 0.0, 0.0, False) for i in range(6)]
                 for w in range(1, 15)}
        out = compute.build_standings(make_raw(weeks), UPDATED)
        for r in out["standings"]:
            self.assertEqual(r["streak"], "-")
            self.assertEqual(r["luckIndex"], 0)


class TestRivalries(unittest.TestCase):
    """build_rivalries: all-time head-to-head records, matched by owner."""

    def setUp(self):
        self.season1 = compute.build_standings(
            make_raw(full_season_weeks(), season=2024), UPDATED)
        # Same owners, same team ids, second season -- as if the same
        # 12-team league played a second year (make_raw's team/owner
        # mapping is deterministic by id, so this reuses it exactly).
        self.season2 = compute.build_standings(
            make_raw(full_season_weeks(), season=2025), UPDATED)

    def test_record_accumulates_across_seasons(self):
        owners, matrix = compute.build_rivalries([self.season1, self.season2])
        # team 1 (First1 Last1) always loses to team 2 (First2 Last2) in
        # full_season_weeks(), 14 times per season, 2 seasons = 28 meetings.
        a, b = "First1 Last1", "First2 Last2"
        self.assertIn(a, owners)
        self.assertEqual((matrix[a][b]["wins"], matrix[a][b]["losses"],
                          matrix[a][b]["ties"]), (0, 28, 0))
        self.assertEqual((matrix[b][a]["wins"], matrix[b][a]["losses"],
                          matrix[b][a]["ties"]), (28, 0, 0))
        # No playoff games in the fixture, so it is all regular season.
        self.assertEqual(matrix[a][b]["regLosses"], 28)
        self.assertEqual(matrix[a][b]["postLosses"], 0)

    def test_teams_that_never_met_have_no_entry(self):
        _, matrix = compute.build_rivalries([self.season1])
        # team 1 only ever plays team 2 in full_season_weeks()'s fixed pairing.
        self.assertNotIn("First3 Last3", matrix["First1 Last1"])

    def test_single_season_matches_that_seasons_games(self):
        owners, matrix = compute.build_rivalries([self.season1])
        self.assertEqual(len(owners), 12)
        a, b = "First1 Last1", "First2 Last2"
        self.assertEqual(matrix[a][b]["losses"], 14)

    def test_no_seasons_gives_empty_result(self):
        owners, matrix = compute.build_rivalries([])
        self.assertEqual(owners, [])
        self.assertEqual(matrix, {})


class TestCareerStats(unittest.TestCase):
    """build_career_stats: cross-season totals per owner."""

    def setUp(self):
        self.season1 = compute.build_standings(
            make_raw(full_season_weeks(), season=2024), UPDATED)
        self.season2 = compute.build_standings(
            make_raw(full_season_weeks(), season=2025), UPDATED)

    def test_totals_accumulate_across_seasons(self):
        careers = compute.build_career_stats([self.season1, self.season2])
        by_owner = {c["owner"]: c for c in careers}
        # team 12 (First12 Last12) wins every H2H game and always tops the
        # scoring in full_season_weeks(): 14 wins/season x 2 seasons.
        team12 = by_owner["First12 Last12"]
        self.assertEqual(team12["seasons"], 2)
        self.assertEqual(team12["wins"], 28)
        self.assertEqual(team12["losses"], 0)
        self.assertEqual(team12["gamesPlayed"], 28)
        # Finishing #1 in the regular season is NOT a championship. Neither
        # test season has a playoff bracket, so nobody has a title.
        self.assertEqual(team12["regularSeasonFirsts"], 2)
        self.assertEqual(team12["titles"], 0)

    def test_career_average_is_weighted_not_mean_of_seasons(self):
        careers = compute.build_career_stats([self.season1, self.season2])
        by_owner = {c["owner"]: c for c in careers}
        c = by_owner["First1 Last1"]
        self.assertEqual(c["gamesPlayed"], 28)
        self.assertAlmostEqual(c["careerAverage"],
                               round(c["pointsFor"] / 28, 1))

    def test_best_and_worst_week_tracked_with_season_and_week(self):
        careers = compute.build_career_stats([self.season1, self.season2])
        by_owner = {c["owner"]: c for c in careers}
        # team 12's score each week is 100 + 10w + 11, identical in both
        # seasons since full_season_weeks() doesn't vary by season -- the
        # tie at week 14 (251 in both years) goes to whichever season was
        # given first (2024), since ties don't overwrite bestWeek/worstWeek.
        c = by_owner["First12 Last12"]
        self.assertEqual(c["bestWeek"], {"score": 251, "season": 2024, "week": 14})
        self.assertEqual(c["worstWeek"], {"score": 121, "season": 2024, "week": 1})

    def test_sorted_by_wins_then_points_for(self):
        careers = compute.build_career_stats([self.season1, self.season2])
        for a, b in zip(careers, careers[1:]):
            self.assertGreaterEqual(a["wins"], b["wins"])
            if a["wins"] == b["wins"]:
                self.assertGreaterEqual(a["pointsFor"], b["pointsFor"])

    def test_empty_input_gives_empty_result(self):
        self.assertEqual(compute.build_career_stats([]), [])


if __name__ == "__main__":
    unittest.main()

class TestScoreToBeatScalesWithLeagueSize(unittest.TestCase):
    """score_to_beat derives the boundary from the field size.

    v1 hardcoded index [5], the 6th-lowest of 12. Any other league size
    silently computed the wrong top-half boundary -- the scoring rule this
    whole project exists to get right.
    """

    def test_twelve_team_league_is_unchanged(self):
        scores = [100 + i for i in range(12)]  # 100..111
        self.assertEqual(compute.score_to_beat(scores), 105)
        self.assertEqual(compute.score_to_beat(scores), sorted(scores)[5])

    def test_ten_team_league_uses_fifth_lowest(self):
        scores = [100 + i for i in range(10)]  # 100..109
        self.assertEqual(compute.score_to_beat(scores), 104)
        self.assertEqual(len([s for s in scores if s > 104]), 5)

    def test_eight_team_league_uses_fourth_lowest(self):
        scores = [100 + i for i in range(8)]
        self.assertEqual(compute.score_to_beat(scores), 103)
        self.assertEqual(len([s for s in scores if s > 103]), 4)

    def test_odd_league_rounds_the_top_half_up(self):
        scores = [100 + i for i in range(11)]  # 100..110
        self.assertEqual(compute.score_to_beat(scores), 104)
        self.assertEqual(len([s for s in scores if s > 104]), 6)

    def test_order_does_not_matter(self):
        self.assertEqual(compute.score_to_beat([5, 1, 4, 2, 3, 6]),
                         compute.score_to_beat([1, 2, 3, 4, 5, 6]))

    def test_too_few_scores_raises(self):
        with self.assertRaises(ValueError):
            compute.score_to_beat([100])


class TestPlayoffBracket(unittest.TestCase):
    """build_playoffs: who actually won the league.

    Regression cover for the bug where weeks 15-17 were discarded entirely,
    so Career Stats credited the title to the regular-season #1 finisher
    even when that owner lost the championship game.
    """

    def _season_with_final(self, home_id, away_id, home_score, away_score,
                           season=2025):
        bracket = [
            make_bracket_matchup(15, 3, None, 110.0, None),   # 1-seed bye
            make_bracket_matchup(15, 5, 9, 136.0, 177.4),
            make_bracket_matchup(16, 3, 9, 140.9, 115.8),
            make_bracket_matchup(17, home_id, away_id, home_score, away_score),
        ]
        return compute.build_standings(
            make_raw(full_season_weeks(), season=season, bracket=bracket),
            UPDATED)

    def test_champion_is_the_winner_of_the_final(self):
        out = self._season_with_final(2, 12, 108.9, 154.5)
        self.assertEqual(out["playoffs"]["champion"], 12)
        self.assertEqual(out["playoffs"]["runnerUp"], 2)
        self.assertEqual(out["playoffs"]["finalWeek"], 17)
        self.assertEqual(out["playoffs"]["championScore"], 154.5)
        self.assertEqual(out["playoffs"]["runnerUpScore"], 108.9)

    def test_home_team_can_win_the_final(self):
        out = self._season_with_final(4, 12, 102.3, 80.0)
        self.assertEqual(out["playoffs"]["champion"], 4)
        self.assertEqual(out["playoffs"]["runnerUp"], 12)

    def test_champion_need_not_be_the_regular_season_leader(self):
        # Team 12 tops the regular season in full_season_weeks(); team 2
        # wins the final. The champion must be team 2.
        out = self._season_with_final(2, 5, 150.0, 100.0)
        self.assertEqual(out["standings"][0]["teamId"], 12)
        self.assertEqual(out["playoffs"]["champion"], 2)

    def test_no_bracket_means_no_champion(self):
        out = compute.build_standings(make_raw(full_season_weeks()), UPDATED)
        self.assertIsNone(out["playoffs"])

    def test_undecided_final_means_no_champion_yet(self):
        bracket = [
            make_bracket_matchup(15, 5, 9, 136.0, 177.4),
            make_bracket_matchup(16, 3, 9, 140.9, 115.8),
            make_bracket_matchup(17, 3, 9, 0.0, 0.0, played=False),
        ]
        out = compute.build_standings(
            make_raw(full_season_weeks(), bracket=bracket), UPDATED)
        self.assertIsNone(out["playoffs"])

    def test_mid_playoffs_does_not_crown_a_semifinal_winner(self):
        # The final exists but is unplayed. Picking the highest *played*
        # bracket week would wrongly crown the week-16 winner.
        bracket = [
            make_bracket_matchup(16, 3, 9, 140.9, 115.8),
            make_bracket_matchup(17, 3, 11, 0.0, 0.0, played=False),
        ]
        out = compute.build_standings(
            make_raw(full_season_weeks(), bracket=bracket), UPDATED)
        self.assertIsNone(out["playoffs"])

    def test_consolation_ladder_never_produces_a_champion(self):
        bracket = [
            make_bracket_matchup(17, 7, 8, 120.0, 90.0,
                                 tier="LOSERS_CONSOLATION_LADDER"),
            make_bracket_matchup(17, 5, 6, 130.0, 95.0,
                                 tier="WINNERS_CONSOLATION_LADDER"),
        ]
        out = compute.build_standings(
            make_raw(full_season_weeks(), bracket=bracket), UPDATED)
        self.assertIsNone(out["playoffs"])

    def test_tied_final_reports_no_champion(self):
        out = self._season_with_final(2, 12, 120.0, 120.0)
        self.assertIsNone(out["playoffs"])

    def test_bracket_byes_are_recorded_without_an_away_team(self):
        out = self._season_with_final(2, 12, 108.9, 154.5)
        byes = [g for g in out["playoffs"]["games"] if g["bye"]]
        self.assertEqual(len(byes), 1)
        self.assertEqual(byes[0]["home"], 3)
        self.assertIsNone(byes[0]["away"])

    def test_playoff_scores_still_contribute_no_dual_points(self):
        out = self._season_with_final(2, 12, 108.9, 154.5)
        self.assertEqual(out["throughWeek"], 14)
        self.assertEqual([w["week"] for w in out["weeks"]], list(range(1, 15)))

    def test_playoff_team_count_and_league_name_come_from_settings(self):
        out = compute.build_standings(
            make_raw(full_season_weeks(), playoff_team_count=4,
                     name="Some Other League"), UPDATED)
        self.assertEqual(out["playoffTeamCount"], 4)
        self.assertEqual(out["leagueName"], "Some Other League")


class TestCareerChampionships(unittest.TestCase):
    """Career titles count championships won, not regular seasons led."""

    def setUp(self):
        # Team 12 dominates both regular seasons. Team 2 wins the 2024
        # final; team 12 wins the 2025 final.
        self.s2024 = compute.build_standings(
            make_raw(full_season_weeks(), season=2024, bracket=[
                make_bracket_matchup(17, 2, 12, 150.0, 100.0)]), UPDATED)
        self.s2025 = compute.build_standings(
            make_raw(full_season_weeks(), season=2025, bracket=[
                make_bracket_matchup(17, 12, 2, 150.0, 100.0)]), UPDATED)

    def test_titles_track_the_final_not_the_standings(self):
        by_owner = {c["owner"]: c
                    for c in compute.build_career_stats([self.s2024, self.s2025])}
        t12, t2 = by_owner["First12 Last12"], by_owner["First2 Last2"]
        # Team 12 led the regular season twice but won one title.
        self.assertEqual(t12["regularSeasonFirsts"], 2)
        self.assertEqual(t12["titles"], 1)
        self.assertEqual(t12["championshipYears"], [2025])
        self.assertEqual(t12["runnerUps"], 1)
        # Team 2 never led the regular season but has a ring.
        self.assertEqual(t2["regularSeasonFirsts"], 0)
        self.assertEqual(t2["titles"], 1)
        self.assertEqual(t2["championshipYears"], [2024])
        self.assertEqual(t2["runnerUps"], 1)

    def test_owners_without_rings_have_none(self):
        by_owner = {c["owner"]: c
                    for c in compute.build_career_stats([self.s2024, self.s2025])}
        self.assertEqual(by_owner["First7 Last7"]["titles"], 0)
        self.assertEqual(by_owner["First7 Last7"]["championshipYears"], [])

    def test_season_without_a_bracket_awards_no_titles(self):
        plain = compute.build_standings(
            make_raw(full_season_weeks(), season=2026), UPDATED)
        by_owner = {c["owner"]: c for c in compute.build_career_stats([plain])}
        self.assertEqual(sum(c["titles"] for c in by_owner.values()), 0)
        self.assertEqual(by_owner["First12 Last12"]["regularSeasonFirsts"], 1)

    def test_leading_an_unfinished_season_is_not_a_regular_season_title(self):
        # Two weeks played out of 14: nobody has finished anything yet.
        partial = compute.build_standings(
            make_raw({w: week_games([100 + 10 * w + i for i in range(12)],
                                     week=w) for w in (1, 2)}, season=2026),
            UPDATED)
        self.assertEqual(partial["throughWeek"], 2)
        by_owner = {c["owner"]: c
                    for c in compute.build_career_stats([partial])}
        self.assertEqual(partial["standings"][0]["owner"], "First12 Last12")
        self.assertEqual(by_owner["First12 Last12"]["regularSeasonFirsts"], 0)
        self.assertEqual(sum(c["regularSeasonFirsts"]
                             for c in by_owner.values()), 0)


class TestFinalRank(unittest.TestCase):
    """finalRank carries ESPN's end-of-season placement.

    FFF reseeds the playoffs by hand off the dual-point standings, so
    `playoffSeed` does not describe the real bracket. `rankCalculatedFinal`
    is computed from results, so it survives the manual reseed -- verified
    against the winners bracket for 2022-2025, where rank 1 is the final's
    winner every time.
    """

    def test_final_rank_is_carried_onto_each_standings_row(self):
        out = compute.build_standings(
            make_raw(full_season_weeks(),
                     final_ranks={12: 3, 2: 1, 5: 2}), UPDATED)
        by_team = {r["teamId"]: r for r in out["standings"]}
        self.assertEqual(by_team[2]["finalRank"], 1)
        self.assertEqual(by_team[5]["finalRank"], 2)
        self.assertEqual(by_team[12]["finalRank"], 3)

    def test_in_progress_season_has_no_final_rank(self):
        # ESPN publishes rankCalculatedFinal as 0 until the season ends;
        # 0 must become None so the UI can hide the column rather than
        # show a league of zeroth-place finishers.
        out = compute.build_standings(make_raw(full_season_weeks()), UPDATED)
        self.assertTrue(all(r["finalRank"] is None for r in out["standings"]))

    def test_final_rank_is_independent_of_regular_season_rank(self):
        # Team 12 tops the dual-point standings; team 2 finishes 1st.
        out = compute.build_standings(
            make_raw(full_season_weeks(),
                     final_ranks={2: 1, 12: 4}), UPDATED)
        by_team = {r["teamId"]: r for r in out["standings"]}
        self.assertEqual(out["standings"][0]["teamId"], 12)
        self.assertEqual(by_team[12]["rank"], 1)
        self.assertEqual(by_team[12]["finalRank"], 4)
        self.assertEqual(by_team[2]["finalRank"], 1)


class TestOrdinalFilter(unittest.TestCase):
    """build.ordinal: placements are rendered as 1st/2nd/3rd/11th."""

    def test_common_suffixes(self):
        self.assertEqual(build.ordinal(1), "1st")
        self.assertEqual(build.ordinal(2), "2nd")
        self.assertEqual(build.ordinal(3), "3rd")
        self.assertEqual(build.ordinal(4), "4th")

    def test_teens_are_all_th(self):
        # The case a last-digit lookup gets wrong: "11st", "12nd", "13rd".
        for n in (11, 12, 13):
            self.assertTrue(build.ordinal(n).endswith("th"), n)

    def test_twenties_resume_normal_suffixes(self):
        self.assertEqual(build.ordinal(21), "21st")
        self.assertEqual(build.ordinal(22), "22nd")
        self.assertEqual(build.ordinal(23), "23rd")

    def test_none_renders_empty(self):
        self.assertEqual(build.ordinal(None), "")


class TestAllPlayRecords(unittest.TestCase):
    """all_play_records: record against the whole field, schedule removed."""

    def setUp(self):
        self.season = compute.build_standings(
            make_raw(full_season_weeks()), UPDATED)
        self.ap = compute.all_play_records(self.season)

    def test_every_team_plays_every_other_team_each_week(self):
        # 12 teams -> 11 notional games each, 14 weeks -> 154.
        for tid, rec in self.ap.items():
            total = rec["wins"] + rec["losses"] + rec["ties"]
            self.assertEqual(total, 11 * 14, f"team {tid}")

    def test_top_scorer_beats_the_whole_field_every_week(self):
        # full_season_weeks() gives team 12 the highest score every week.
        self.assertEqual(self.ap[12]["wins"], 11 * 14)
        self.assertEqual(self.ap[12]["losses"], 0)
        self.assertEqual(self.ap[12]["pct"], 1.0)

    def test_bottom_scorer_loses_to_the_whole_field(self):
        self.assertEqual(self.ap[1]["wins"], 0)
        self.assertEqual(self.ap[1]["losses"], 11 * 14)
        self.assertEqual(self.ap[1]["pct"], 0.0)

    def test_wins_and_losses_are_symmetric_across_the_league(self):
        total_w = sum(r["wins"] for r in self.ap.values())
        total_l = sum(r["losses"] for r in self.ap.values())
        self.assertEqual(total_w, total_l)

    def test_ties_count_as_half_a_win(self):
        # One week, six matchups, every team scoring exactly the same.
        season = compute.build_standings(
            make_raw({1: week_games([100.0] * 12)}), UPDATED)
        ap = compute.all_play_records(season)
        self.assertEqual(ap[1]["ties"], 11)
        self.assertEqual(ap[1]["wins"], 0)
        self.assertEqual(ap[1]["pct"], 0.5)


class TestScoringProfile(unittest.TestCase):
    """scoring_profile: volatility, weekly extremes, lucky/unlucky weeks."""

    def test_identical_scores_every_week_have_no_deviation(self):
        weeks = {w: week_games([100 + i for i in range(12)], week=w)
                 for w in range(1, 5)}
        season = compute.build_standings(make_raw(weeks), UPDATED)
        prof = compute.scoring_profile(season)
        self.assertEqual(prof[1]["stdev"], 0.0)

    def test_stdev_rises_with_swing(self):
        steady = {w: week_games([100 + i for i in range(12)], week=w)
                  for w in (1, 2)}
        swingy = {1: week_games([100 + i for i in range(12)], week=1),
                  2: week_games([200 + i for i in range(12)], week=2)}
        a = compute.scoring_profile(
            compute.build_standings(make_raw(steady), UPDATED))
        b = compute.scoring_profile(
            compute.build_standings(make_raw(swingy), UPDATED))
        self.assertLess(a[1]["stdev"], b[1]["stdev"])

    def test_weekly_firsts_and_lasts(self):
        season = compute.build_standings(
            make_raw(full_season_weeks()), UPDATED)
        prof = compute.scoring_profile(season)
        self.assertEqual(prof[12]["weeklyFirsts"], 14)
        self.assertEqual(prof[12]["weeklyLasts"], 0)
        self.assertEqual(prof[1]["weeklyLasts"], 14)

    def test_lucky_win_is_a_bottom_half_score_that_won(self):
        # Team 1 scores 10 (lowest by far) but its opponent scores 5.
        scores = [10.0, 5.0] + [100 + i for i in range(10)]
        season = compute.build_standings(
            make_raw({1: week_games(scores)}), UPDATED)
        prof = compute.scoring_profile(season)
        team1 = next(t for t in season["weeks"][0]["teams"] if t["teamId"] == 1)
        self.assertEqual(team1["h2h"], 1)
        self.assertEqual(team1["topHalf"], 0)
        self.assertEqual(prof[1]["luckyWins"], 1)
        self.assertEqual(prof[1]["unluckyLosses"], 0)

    def test_unlucky_loss_is_a_top_half_score_that_lost(self):
        # Teams 1 and 2 are the top two scores, but they play each other,
        # so the loser scored top-half and still lost.
        scores = [150.0, 149.0] + [100 + i for i in range(10)]
        season = compute.build_standings(
            make_raw({1: week_games(scores)}), UPDATED)
        prof = compute.scoring_profile(season)
        team2 = next(t for t in season["weeks"][0]["teams"] if t["teamId"] == 2)
        self.assertEqual(team2["h2h"], 0)
        self.assertEqual(team2["topHalf"], 1)
        self.assertEqual(prof[2]["unluckyLosses"], 1)


class TestSeasonRecords(unittest.TestCase):
    """season_records: single-game and single-week superlatives."""

    def setUp(self):
        # wk1 has a 60-point blowout (1 v 2) and a 1-point squeaker (3 v 4).
        wk1 = [(1, 2, 160.0, 100.0), (3, 4, 121.0, 120.0),
               (5, 6, 130.0, 110.0), (7, 8, 125.0, 105.0),
               (9, 10, 115.0, 112.0), (11, 12, 118.0, 108.0)]
        self.season = compute.build_standings(make_raw({1: wk1}), UPDATED)
        self.rec = compute.season_records(self.season)

    def test_biggest_blowout(self):
        self.assertEqual(self.rec["blowout"]["margin"], 60.0)
        self.assertEqual(self.rec["blowout"]["winner"], "First1 Last1")
        self.assertEqual(self.rec["blowout"]["loser"], "First2 Last2")

    def test_closest_game(self):
        self.assertEqual(self.rec["closest"]["margin"], 1.0)
        self.assertEqual(self.rec["closest"]["winner"], "First3 Last3")

    def test_high_and_low_weeks(self):
        self.assertEqual(self.rec["high"]["score"], 160.0)
        self.assertEqual(self.rec["high"]["owner"], "First1 Last1")
        self.assertEqual(self.rec["low"]["score"], 100.0)

    def test_tough_loss_is_the_best_losing_score(self):
        # 120.0 (team 4) is the highest score among the six losers.
        self.assertEqual(self.rec["toughLoss"]["score"], 120.0)
        self.assertEqual(self.rec["toughLoss"]["owner"], "First4 Last4")

    def test_cheap_win_is_the_worst_winning_score(self):
        # 115.0 (team 9) is the lowest score among the six winners.
        self.assertEqual(self.rec["cheapWin"]["score"], 115.0)
        self.assertEqual(self.rec["cheapWin"]["owner"], "First9 Last9")

    def test_shootout_uses_combined_points(self):
        # Combined totals: 260, 241, 240, 230, 227, 226.
        self.assertEqual(self.rec["shootout"]["combined"], 260.0)

    def test_there_is_no_snoozer_record(self):
        # Dropped on purpose: it named two more owners for a bad game on a
        # page that already has a Lowest Score record.
        self.assertNotIn("snoozer", self.rec)

    def test_no_weeks_gives_no_records(self):
        empty = compute.build_standings(make_raw({}), UPDATED)
        self.assertEqual(compute.season_records(empty), {})


class TestSeasonAwards(unittest.TestCase):
    """season_awards: named superlatives, and deterministic."""

    def setUp(self):
        self.season = compute.build_standings(
            make_raw(full_season_weeks()), UPDATED)
        self.stats = compute.build_season_stats(self.season)
        self.by_key = {a["key"]: a for a in self.stats["awards"]}

    def test_the_wall_goes_to_the_best_all_play_record(self):
        self.assertEqual(self.by_key["wall"]["owners"], ["First12 Last12"])

    def test_ceiling_goes_to_the_top_scorer(self):
        self.assertEqual(self.by_key["ceiling"]["owners"], ["First12 Last12"])

    def test_there_is_no_coldest_night_award(self):
        # Dropped on purpose: the Lowest Score record already names that
        # owner for that exact week, so awarding it too is the same dig
        # twice.
        self.assertNotIn("floor", self.by_key)

    def test_every_award_is_fully_populated(self):
        for a in self.stats["awards"]:
            for field in ("key", "emoji", "name", "blurb", "owners", "detail"):
                self.assertTrue(a.get(field), f"{a.get('key')}.{field}")

    def test_awards_are_deterministic_across_runs(self):
        # The daily workflow commits only when docs/ changes, so an award
        # that rerolled per run would manufacture a commit every morning.
        again = compute.build_season_stats(self.season)["awards"]
        self.assertEqual(self.stats["awards"], again)

    def test_ties_break_on_team_id_not_iteration_order(self):
        # Every team scores identically every week, so every stat ties.
        weeks = {w: week_games([100.0] * 12, week=w) for w in range(1, 4)}
        season = compute.build_standings(make_raw(weeks), UPDATED)
        a = compute.build_season_stats(season)["awards"]
        b = compute.build_season_stats(season)["awards"]
        self.assertEqual(a, b)

    def test_empty_season_produces_no_crash(self):
        empty = compute.build_standings(make_raw({}), UPDATED)
        stats = compute.build_season_stats(empty)
        self.assertEqual(stats["records"], {})
        self.assertIsInstance(stats["awards"], list)

    def test_stats_table_covers_every_owner(self):
        self.assertEqual(len(self.stats["table"]), 12)
        row = next(r for r in self.stats["table"] if r["teamId"] == 12)
        self.assertEqual(row["allPlayPct"], 1.0)
        self.assertEqual(row["weeklyFirsts"], 14)


class TestAwardTies(unittest.TestCase):
    """Ties are shown as co-winners, not silently handed to one owner."""

    def test_names_formats_one_two_and_three_winners(self):
        rows = [{"owner": "A"}, {"owner": "B"}, {"owner": "C"}]
        self.assertEqual(compute._names(rows[:1]), "A")
        self.assertEqual(compute._names(rows[:2]), "A & B")
        self.assertEqual(compute._names(rows), "A, B & C")

    def test_leaders_returns_every_tied_row_ordered_by_team_id(self):
        rows = [{"teamId": 7, "v": 5}, {"teamId": 2, "v": 5},
                {"teamId": 9, "v": 1}]
        self.assertEqual([r["teamId"] for r in compute._leaders(rows, "v")],
                         [2, 7])
        self.assertEqual([r["teamId"]
                          for r in compute._leaders(rows, "v", reverse=False)],
                         [9])

    def test_leaders_ignores_rows_missing_the_stat(self):
        rows = [{"teamId": 1, "v": None}, {"teamId": 2, "v": 3}]
        self.assertEqual(compute._leaders(rows, "v"), [{"teamId": 2, "v": 3}])
        self.assertEqual(compute._leaders([{"teamId": 1, "v": None}], "v"), [])

    def test_a_shared_award_names_both_owners_and_is_flagged(self):
        # Every team identical every week -> every award is a 12-way tie.
        weeks = {w: week_games([100.0] * 12, week=w) for w in range(1, 4)}
        season = compute.build_standings(make_raw(weeks), UPDATED)
        awards = compute.build_season_stats(season)["awards"]
        self.assertTrue(awards)
        for a in awards:
            self.assertTrue(a["shared"], a["key"])
            self.assertGreater(len(a["owners"]), 1, a["key"])

    def test_a_clear_winner_is_not_flagged_as_shared(self):
        season = compute.build_standings(
            make_raw(full_season_weeks()), UPDATED)
        by_key = {a["key"]: a for a in compute.build_season_stats(season)["awards"]}
        self.assertFalse(by_key["wall"]["shared"])
        self.assertEqual(by_key["wall"]["owners"], ["First12 Last12"])


class TestShortNames(unittest.TestCase):
    """short_names: first name when unambiguous, full name when not.

    The league talks about each other by first name, and team names change
    yearly while people do not -- so the person is the identity the site
    leads with.
    """

    def test_unique_first_names_shorten(self):
        m = compute.short_names(["Casey Pirsig", "Pat Benner"])
        self.assertEqual(m["Casey Pirsig"], "Casey")
        self.assertEqual(m["Pat Benner"], "Pat")

    def test_colliding_first_names_get_the_shortest_distinguishing_prefix(self):
        # This league really does have both Daniels. One letter won't do it
        # -- they're both S -- so it grows to two.
        m = compute.short_names(["Daniel Senger", "Daniel Sharp", "Pat Benner"])
        self.assertEqual(m["Daniel Senger"], "Daniel Se.")
        self.assertEqual(m["Daniel Sharp"], "Daniel Sh.")
        self.assertEqual(m["Pat Benner"], "Pat")

    def test_one_letter_is_enough_when_it_separates(self):
        m = compute.short_names(["Daniel Senger", "Daniel Torres"])
        self.assertEqual(m["Daniel Senger"], "Daniel S.")
        self.assertEqual(m["Daniel Torres"], "Daniel T.")

    def test_prefix_grows_as_far_as_it_needs_to(self):
        m = compute.short_names(["Chris Smith", "Chris Smythe"])
        self.assertEqual(m["Chris Smith"], "Chris Smi.")
        self.assertEqual(m["Chris Smythe"], "Chris Smy.")

    def test_three_way_collision(self):
        m = compute.short_names(["Chris Smith", "Chris Smythe", "Chris Jones"])
        self.assertEqual(sorted(m.values()),
                         ["Chris Jon.", "Chris Smi.", "Chris Smy."])

    def test_similar_but_distinct_first_names_both_shorten(self):
        m = compute.short_names(["Nick Kubit", "Nicholas Polansky"])
        self.assertEqual(m["Nick Kubit"], "Nick")
        self.assertEqual(m["Nicholas Polansky"], "Nicholas")

    def test_single_word_and_empty_owners_are_safe(self):
        m = compute.short_names(["Cher", None, ""])
        self.assertEqual(m["Cher"], "Cher")
        self.assertNotIn(None, m)

    def test_the_same_owner_listed_twice_still_shortens(self):
        # Owners repeat across seasons; that is not a collision.
        m = compute.short_names(["Pat Benner", "Pat Benner"])
        self.assertEqual(m["Pat Benner"], "Pat")

    def test_join_names(self):
        self.assertEqual(compute.join_names([]), "")
        self.assertEqual(compute.join_names(["A"]), "A")
        self.assertEqual(compute.join_names(["A", "B"]), "A & B")
        self.assertEqual(compute.join_names(["A", "B", "C"]), "A, B & C")


class TestSurgeAndClutch(unittest.TestCase):
    """The two positive awards added to replace the piled-on negative ones."""

    def test_surge_is_second_half_minus_first_half(self):
        # Team 1 scores 100 for 3 weeks then 140 for 3 weeks: +40.
        weeks = {}
        for w in range(1, 7):
            base = 100.0 if w <= 3 else 140.0
            weeks[w] = week_games([base] + [50 + i for i in range(11)], week=w)
        season = compute.build_standings(make_raw(weeks), UPDATED)
        prof = compute.scoring_profile(season)
        self.assertEqual(prof[1]["surge"], 40.0)

    def test_surge_is_none_for_a_short_season(self):
        weeks = {w: week_games([100 + i for i in range(12)], week=w)
                 for w in (1, 2)}
        season = compute.build_standings(make_raw(weeks), UPDATED)
        prof = compute.scoring_profile(season)
        self.assertIsNone(prof[1]["surge"])

    def test_close_games_are_counted_under_the_margin(self):
        # 1v2 decided by 5 (close), 3v4 by 40 (not).
        wk = [(1, 2, 105.0, 100.0), (3, 4, 140.0, 100.0),
              (5, 6, 130.0, 110.0), (7, 8, 125.0, 105.0),
              (9, 10, 115.0, 112.0), (11, 12, 118.0, 108.0)]
        season = compute.build_standings(make_raw({1: wk}), UPDATED)
        prof = compute.scoring_profile(season)
        self.assertEqual(prof[1]["closeGames"], 1)
        self.assertEqual(prof[1]["closeWins"], 1)
        self.assertEqual(prof[3]["closeGames"], 0)

    def test_clutch_needs_a_minimum_sample(self):
        # One close game is not a clutch record.
        wk = [(1, 2, 105.0, 100.0), (3, 4, 140.0, 100.0),
              (5, 6, 130.0, 110.0), (7, 8, 125.0, 105.0),
              (9, 10, 145.0, 112.0), (11, 12, 148.0, 108.0)]
        season = compute.build_standings(make_raw({1: wk}), UPDATED)
        prof = compute.scoring_profile(season)
        self.assertEqual(prof[1]["closeGames"], 1)
        self.assertIsNone(prof[1]["closeWinPct"])
        keys = {a["key"] for a in compute.build_season_stats(season)["awards"]}
        self.assertNotIn("clutch", keys)


class TestPrizeResolution(unittest.TestCase):
    """resolve_prizes: each prize line paired with the owner who won it."""

    PRIZES = [
        {"label": "1st Place", "amount": 25, "award": "standings", "rank": 1},
        {"label": "Reg Season Most PF", "amount": 30, "award": "regSeasonPF"},
        {"label": "1st Overall", "amount": 90, "award": "finalRank", "rank": 1},
        {"label": "3rd Overall", "amount": 30, "award": "finalRank", "rank": 3},
    ]

    def _season(self, **kw):
        return compute.build_standings(
            make_raw(full_season_weeks(), **kw), UPDATED)

    def test_finished_season_resolves_every_prize(self):
        season = self._season(final_ranks={2: 1, 5: 2, 7: 3})
        items = compute.resolve_prizes(season, self.PRIZES)
        self.assertTrue(all(i["decided"] for i in items))
        by_label = {i["label"]: i["owner"] for i in items}
        self.assertEqual(by_label["1st Overall"], "First2 Last2")
        self.assertEqual(by_label["3rd Overall"], "First7 Last7")
        # Team 12 tops the dual-point standings and points-for.
        self.assertEqual(by_label["1st Place"], "First12 Last12")
        self.assertEqual(by_label["Reg Season Most PF"], "First12 Last12")

    def test_in_progress_season_leaves_playoff_prizes_undecided(self):
        items = compute.resolve_prizes(self._season(), self.PRIZES)
        by_label = {i["label"]: i for i in items}
        self.assertTrue(by_label["1st Place"]["decided"])
        self.assertFalse(by_label["1st Overall"]["decided"])
        self.assertIsNone(by_label["1st Overall"]["owner"])

    def test_prizes_for_season_accepts_a_plain_list(self):
        self.assertEqual(compute.prizes_for_season(self.PRIZES, 2025),
                         self.PRIZES)

    def test_prizes_for_season_prefers_a_year_override(self):
        other = [{"label": "Winner", "amount": 10, "award": "finalRank",
                  "rank": 1}]
        config = {"default": self.PRIZES, "2022": other}
        self.assertEqual(compute.prizes_for_season(config, 2022), other)
        self.assertEqual(compute.prizes_for_season(config, 2025), self.PRIZES)

    def test_prizes_for_season_handles_junk(self):
        self.assertEqual(compute.prizes_for_season(None, 2025), [])
        self.assertEqual(compute.prizes_for_season({}, 2025), [])


class TestSeasonPayouts(unittest.TestCase):
    """season_payouts: the same money, ranked by who took it home."""

    def test_the_champion_does_not_automatically_top_the_payouts(self):
        # This is the whole point of the table. Team 12 leads the regular
        # season and scoring ($25 + $30) and finishes 2nd ($60) = $115.
        # Team 2 wins the title for $90 and collects nothing else.
        prizes = [
            {"label": "1st Place", "amount": 25, "award": "standings", "rank": 1},
            {"label": "Most PF", "amount": 30, "award": "regSeasonPF"},
            {"label": "1st Overall", "amount": 90, "award": "finalRank", "rank": 1},
            {"label": "2nd Overall", "amount": 60, "award": "finalRank", "rank": 2},
        ]
        season = compute.build_standings(
            make_raw(full_season_weeks(), final_ranks={2: 1, 12: 2}), UPDATED)
        rows = compute.season_payouts(season, prizes)
        self.assertEqual(rows[0]["owner"], "First12 Last12")
        self.assertEqual(rows[0]["total"], 115)
        self.assertEqual(rows[1]["owner"], "First2 Last2")
        self.assertEqual(rows[1]["total"], 90)

    def test_net_subtracts_the_entry_fee(self):
        prizes = [{"label": "1st Overall", "amount": 90,
                   "award": "finalRank", "rank": 1}]
        season = compute.build_standings(
            make_raw(full_season_weeks(), final_ranks={2: 1}), UPDATED)
        season["entryFee"] = 25.0
        rows = {r["owner"]: r for r in compute.season_payouts(season, prizes)}
        self.assertEqual(rows["First2 Last2"]["net"], 65)
        # Everyone else is out the entry fee.
        self.assertEqual(rows["First7 Last7"]["total"], 0)
        self.assertEqual(rows["First7 Last7"]["net"], -25)

    def test_every_owner_appears_even_with_no_winnings(self):
        season = compute.build_standings(make_raw(full_season_weeks()), UPDATED)
        self.assertEqual(len(compute.season_payouts(season, [])), 12)

    def test_payouts_are_ranked_by_total(self):
        prizes = [
            {"label": "A", "amount": 10, "award": "standings", "rank": 3},
            {"label": "B", "amount": 50, "award": "standings", "rank": 1},
        ]
        season = compute.build_standings(make_raw(full_season_weeks()), UPDATED)
        rows = [r for r in compute.season_payouts(season, prizes) if r["total"]]
        self.assertEqual([r["total"] for r in rows], [50, 10])


class TestCareerPayouts(unittest.TestCase):
    """career_payouts: all-time winnings, overall and per year."""

    PRIZES = [{"label": "1st Overall", "amount": 90,
               "award": "finalRank", "rank": 1}]

    def _season(self, year, champion):
        s = compute.build_standings(
            make_raw(full_season_weeks(), season=year,
                     final_ranks={champion: 1}), UPDATED)
        s["entryFee"] = 25.0
        return s

    def test_totals_and_per_season_breakdown(self):
        seasons = [self._season(2024, 2), self._season(2025, 2)]
        rows = {r["owner"]: r
                for r in compute.career_payouts(seasons, self.PRIZES)}
        champ = rows["First2 Last2"]
        self.assertEqual(champ["total"], 180)
        self.assertEqual(champ["bySeason"], {2024: 90, 2025: 90})
        self.assertEqual(champ["paid"], 50)
        self.assertEqual(champ["net"], 130)

    def test_a_champion_can_still_be_net_negative(self):
        # One title across four seasons of entry fees. This really happens:
        # Polansky won 2022 and is still down on the league.
        seasons = [self._season(y, 2 if y == 2022 else 5)
                   for y in (2022, 2023, 2024, 2025)]
        rows = {r["owner"]: r
                for r in compute.career_payouts(seasons, self.PRIZES)}
        polansky = rows["First2 Last2"]
        self.assertEqual(polansky["total"], 90)
        self.assertEqual(polansky["paid"], 100)
        self.assertEqual(polansky["net"], -10)

    def test_undecided_seasons_pay_nothing(self):
        # An in-progress season has no finalRank, so no prize is decided and
        # the season must not contribute money or entry fees.
        live = compute.build_standings(
            make_raw(full_season_weeks(), season=2026), UPDATED)
        live["entryFee"] = 25.0
        rows = compute.career_payouts([live], self.PRIZES)
        self.assertEqual(rows, [])

    def test_mixed_decided_and_undecided(self):
        live = compute.build_standings(
            make_raw(full_season_weeks(), season=2026), UPDATED)
        live["entryFee"] = 25.0
        rows = {r["owner"]: r for r in
                compute.career_payouts([self._season(2025, 2), live],
                                       self.PRIZES)}
        self.assertEqual(rows["First2 Last2"]["total"], 90)
        self.assertNotIn(2026, rows["First2 Last2"]["bySeason"])
        self.assertEqual(rows["First2 Last2"]["paid"], 25)


class TestRivalriesIncludePostseason(unittest.TestCase):
    """A head-to-head record that calls itself all-time must count playoffs.

    Regression for a real miss: the Rivalries page showed Paul Tuura 0-4
    against Casey Pirsig, which is right for the regular season and hid
    three playoff meetings that Tuura won two of -- including knocking
    Pirsig out of the 2024 winners bracket 101.0-99.0.
    """

    def _season(self, bracket):
        return compute.build_standings(
            make_raw(full_season_weeks(), bracket=bracket), UPDATED)

    def test_postseason_games_are_captured(self):
        season = self._season([
            make_bracket_matchup(15, 1, 2, 120.0, 100.0),
            make_bracket_matchup(16, 3, 4, 90.0, 95.0,
                                 tier="LOSERS_CONSOLATION_LADDER"),
        ])
        post = season["postseason"]
        self.assertEqual(len(post), 2)
        self.assertEqual(post[0]["winner"], 1)
        self.assertEqual(post[1]["winner"], 4)
        self.assertEqual(post[1]["tier"], "LOSERS_CONSOLATION_LADDER")

    def test_consolation_meetings_count_toward_the_rivalry(self):
        # Team 1 loses to team 2 all 14 regular-season weeks, then beats
        # them twice in a consolation bracket.
        season = self._season([
            make_bracket_matchup(15, 1, 2, 120.0, 100.0,
                                 tier="LOSERS_CONSOLATION_LADDER"),
            make_bracket_matchup(16, 1, 2, 130.0, 100.0,
                                 tier="LOSERS_CONSOLATION_LADDER"),
        ])
        _, matrix = compute.build_rivalries([season])
        cell = matrix["First1 Last1"]["First2 Last2"]
        self.assertEqual((cell["wins"], cell["losses"]), (2, 14))
        self.assertEqual((cell["regWins"], cell["regLosses"]), (0, 14))
        self.assertEqual((cell["postWins"], cell["postLosses"]), (2, 0))

    def test_the_split_always_sums_to_the_total(self):
        season = self._season([make_bracket_matchup(15, 1, 2, 120.0, 100.0)])
        _, matrix = compute.build_rivalries([season])
        for a, opponents in matrix.items():
            for b, c in opponents.items():
                self.assertEqual(c["wins"], c["regWins"] + c["postWins"])
                self.assertEqual(c["losses"], c["regLosses"] + c["postLosses"])
                self.assertEqual(c["ties"], c["regTies"] + c["postTies"])

    def test_unplayed_and_bye_entries_are_skipped(self):
        season = self._season([
            make_bracket_matchup(15, 1, None, 120.0, None),        # bye
            make_bracket_matchup(16, 1, 2, 0.0, 0.0, played=False),
        ])
        self.assertEqual(season["postseason"], [])

    def test_postseason_still_contributes_no_dual_points(self):
        season = self._season([make_bracket_matchup(15, 1, 2, 200.0, 100.0)])
        self.assertEqual(season["throughWeek"], 14)
        self.assertEqual([w["week"] for w in season["weeks"]],
                         list(range(1, 15)))


class TestSurnameRedaction(unittest.TestCase):
    """fetch.redact_members: nothing world-readable carries a full surname.

    The repo is public (free GitHub Pages requires it), so everything
    written to data/ is published. See SPEC.md §3.
    """

    def _raw(self):
        return {"mTeam": {
            "members": [
                {"id": "{a}", "firstName": "Ethan", "lastName": "Hildebrandt",
                 "displayName": "ethan.h123",
                 "notificationSettings": [{"id": "noise"}]},
                {"id": "{b}", "firstName": "Sam", "lastName": "Engsberg",
                 "displayName": "Sam Engsberg"},
                {"id": "{c}", "firstName": "Pat", "lastName": "Ben"},
            ],
            "teams": [
                {"id": 1, "primaryOwner": "{a}", "name": "Team Hildebrandt"},
                {"id": 2, "primaryOwner": "{b}", "name": "Lt. Surge Energy"},
                {"id": 3, "primaryOwner": "{c}", "name": "Unrelated"},
            ]}}

    def test_surnames_are_truncated(self):
        out = fetch.redact_members(self._raw())
        names = {m["firstName"]: m["lastName"] for m in out["mTeam"]["members"]}
        self.assertEqual(names["Ethan"], "Hil")
        self.assertEqual(names["Sam"], "Eng")

    def test_a_display_name_holding_a_full_name_is_truncated_too(self):
        out = fetch.redact_members(self._raw())
        sam = next(m for m in out["mTeam"]["members"] if m["firstName"] == "Sam")
        self.assertEqual(sam["displayName"], "Sam Eng")

    def test_opaque_display_handles_are_left_alone(self):
        out = fetch.redact_members(self._raw())
        ethan = next(m for m in out["mTeam"]["members"]
                     if m["firstName"] == "Ethan")
        self.assertEqual(ethan["displayName"], "ethan.h123")

    def test_a_team_named_after_its_owner_loses_the_surname(self):
        out = fetch.redact_members(self._raw())
        names = {t["id"]: t["name"] for t in out["mTeam"]["teams"]}
        self.assertEqual(names[1], "Team Ethan")
        self.assertEqual(names[2], "Lt. Surge Energy")
        self.assertEqual(names[3], "Unrelated")

    def test_notification_noise_is_dropped(self):
        out = fetch.redact_members(self._raw())
        for m in out["mTeam"]["members"]:
            self.assertNotIn("notificationSettings", m)

    def test_no_full_surname_survives_anywhere(self):
        blob = json.dumps(fetch.redact_members(self._raw()))
        for surname in ("Hildebrandt", "Engsberg"):
            self.assertNotIn(surname, blob)

    def test_running_twice_is_a_no_op(self):
        once = fetch.redact_members(self._raw())
        twice = fetch.redact_members(json.loads(json.dumps(once)))
        self.assertEqual(once, twice)

    def test_already_short_surnames_are_untouched(self):
        out = fetch.redact_members(self._raw())
        pat = next(m for m in out["mTeam"]["members"] if m["firstName"] == "Pat")
        self.assertEqual(pat["lastName"], "Ben")


class TestPassphraseGate(unittest.TestCase):
    """build.phrase_hash: the phrase never ships, only its digest."""

    def setUp(self):
        self._saved = os.environ.get("LEAGUE_PHRASE")

    def tearDown(self):
        os.environ.pop("LEAGUE_PHRASE", None)
        if self._saved is not None:
            os.environ["LEAGUE_PHRASE"] = self._saved

    def test_no_secret_means_no_gate(self):
        os.environ.pop("LEAGUE_PHRASE", None)
        self.assertEqual(build.phrase_hash(), "")

    def test_blank_secret_means_no_gate(self):
        os.environ["LEAGUE_PHRASE"] = "   "
        self.assertEqual(build.phrase_hash(), "")

    def test_hash_matches_sha256_and_hides_the_phrase(self):
        os.environ["LEAGUE_PHRASE"] = "go lions"
        got = build.phrase_hash()
        self.assertEqual(
            got, hashlib.sha256(b"go lions").hexdigest())
        self.assertNotIn("go lions", got)
        self.assertEqual(len(got), 64)

    def test_surrounding_whitespace_is_ignored(self):
        os.environ["LEAGUE_PHRASE"] = "  go lions  "
        a = build.phrase_hash()
        os.environ["LEAGUE_PHRASE"] = "go lions"
        self.assertEqual(a, build.phrase_hash())


class TestPhraseHashPassthrough(unittest.TestCase):
    """LEAGUE_PHRASE_SHA256 lets a build reproduce the gate without the phrase.

    Without it, any rebuild by someone who lacks the secret would silently
    ship a gate-less site.
    """

    def setUp(self):
        self._saved = {k: os.environ.get(k)
                       for k in ("LEAGUE_PHRASE", "LEAGUE_PHRASE_SHA256")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_a_valid_digest_is_used_as_is(self):
        digest = hashlib.sha256(b"go lions").hexdigest()
        os.environ["LEAGUE_PHRASE_SHA256"] = digest
        self.assertEqual(build.phrase_hash(), digest)

    def test_digest_is_case_insensitive(self):
        digest = hashlib.sha256(b"go lions").hexdigest()
        os.environ["LEAGUE_PHRASE_SHA256"] = digest.upper()
        self.assertEqual(build.phrase_hash(), digest)

    def test_the_phrase_wins_over_a_digest(self):
        os.environ["LEAGUE_PHRASE"] = "go lions"
        os.environ["LEAGUE_PHRASE_SHA256"] = "0" * 64
        self.assertEqual(build.phrase_hash(),
                         hashlib.sha256(b"go lions").hexdigest())

    def test_a_malformed_digest_is_refused_rather_than_trusted(self):
        # Shipping "not-a-hash" as the gate would make every phrase fail.
        for bad in ("not-a-hash", "abc", "z" * 64, hashlib.sha256(b"x").hexdigest()[:63]):
            os.environ["LEAGUE_PHRASE_SHA256"] = bad
            self.assertEqual(build.phrase_hash(), "", bad)


class TestCustomDomain(unittest.TestCase):
    """docs/CNAME is emitted from data/domain.txt.

    The daily workflow regenerates and re-commits docs/, so the domain has
    to be part of the build rather than a file GitHub dropped in once.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = pathlib.Path(self.tmp) / "data"
        self.docs = pathlib.Path(self.tmp) / "docs"
        self.data.mkdir()
        self.docs.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_cname(self):
        """Mirror build.py's CNAME rule against a temp tree."""
        path = self.data / "domain.txt"
        if path.exists():
            domain = path.read_text(encoding="utf-8").strip()
            if domain:
                (self.docs / "CNAME").write_text(domain + "\n", encoding="utf-8")
        return (self.docs / "CNAME")

    def test_domain_file_produces_a_cname(self):
        (self.data / "domain.txt").write_text("fff.example.com\n",
                                              encoding="utf-8")
        out = self._write_cname()
        self.assertTrue(out.exists())
        # Pages wants the bare host, one line, no scheme or trailing slash.
        self.assertEqual(out.read_text(encoding="utf-8"), "fff.example.com\n")

    def test_no_domain_file_means_no_cname(self):
        self.assertFalse(self._write_cname().exists())

    def test_blank_domain_file_means_no_cname(self):
        (self.data / "domain.txt").write_text("   \n", encoding="utf-8")
        self.assertFalse(self._write_cname().exists())

    def test_whitespace_is_trimmed(self):
        (self.data / "domain.txt").write_text("  fff.example.com  \n\n",
                                              encoding="utf-8")
        self.assertEqual(self._write_cname().read_text(encoding="utf-8"),
                         "fff.example.com\n")


class TestGateRegressionGuard(unittest.TestCase):
    """build.previous_gate_hash: don't silently un-gate a gated site.

    Regression for a real incident: a rebuild during unrelated work ran
    without the digest, stripped the gate from all 40 pages, and `git add
    -A` committed it -- publishing the league ungated until someone
    noticed. build.py now refuses that build unless --no-gate is passed.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.docs = pathlib.Path(self.tmp) / "docs"
        self.docs.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_back_the_digest_from_a_built_page(self):
        digest = "a" * 64
        (self.docs / "index.html").write_text(
            f"<html><script>var HASH = '{digest}';</script></html>",
            encoding="utf-8")
        self.assertEqual(build.previous_gate_hash(self.docs), digest)

    def test_no_docs_yet_is_not_a_gate(self):
        self.assertEqual(build.previous_gate_hash(self.docs), "")

    def test_an_ungated_page_reports_no_gate(self):
        (self.docs / "index.html").write_text("<html>no gate here</html>",
                                              encoding="utf-8")
        self.assertEqual(build.previous_gate_hash(self.docs), "")

    def test_an_empty_hash_is_not_treated_as_a_gate(self):
        # build.py renders var HASH = '' when the gate is off; that must
        # not look like an existing gate or every later build would fail.
        (self.docs / "index.html").write_text(
            "<script>var HASH = '';</script>", encoding="utf-8")
        self.assertEqual(build.previous_gate_hash(self.docs), "")

    def test_a_malformed_digest_is_not_treated_as_a_gate(self):
        (self.docs / "index.html").write_text(
            "<script>var HASH = 'nope';</script>", encoding="utf-8")
        self.assertEqual(build.previous_gate_hash(self.docs), "")


# --------------------------------------------------------------------------
# Started lineups (fetch.py --starters) and the all-time kicker rankings.
# --------------------------------------------------------------------------

def make_entry(player_id, name, points, pos, slot=None):
    """One rosterForCurrentScoringPeriod entry (slot given) or a
    rosterForMatchupPeriod one (slot zeroed, the way ESPN sends it)."""
    return {
        "lineupSlotId": 0 if slot is None else slot,
        "playerId": player_id,
        "playerPoolEntry": {
            "appliedStatTotal": points,
            "player": {"id": player_id, "fullName": name,
                       "defaultPositionId": pos, "proTeamId": 12},
        },
    }


def make_side(team_id, started, benched=(), total=None):
    """A boxscore side: the started nine plus the bench ESPN also sends.

    started/benched: (playerId, name, points, pos, slot) tuples. The starters
    appear in BOTH roster blocks (slot zeroed in the matchup one, real in the
    current one); the bench only in the current-period block.
    """
    return {
        "teamId": team_id,
        "totalPoints": (sum(s[2] for s in started) if total is None else total),
        "rosterForMatchupPeriod": {
            "entries": [make_entry(p, n, pts, pos) for p, n, pts, pos, _ in started],
        },
        "rosterForCurrentScoringPeriod": {
            "entries": ([make_entry(p, n, pts, pos, slot)
                         for p, n, pts, pos, slot in started]
                        + [make_entry(p, n, pts, pos, 20)
                           for p, n, pts, pos, _ in benched]),
        },
    }


def make_starter_file(season, rows):
    """A data/starters-<season>.json-shaped dict from (week, teamId,
    playerId, name, points[, pos]) tuples."""
    out = []
    for row in rows:
        week, team_id, player_id, name, points = row[:5]
        pos = row[5] if len(row) > 5 else compute.KICKER_POS
        out.append({"week": week, "teamId": team_id, "slot": 17,
                    "playerId": player_id, "name": name, "pos": pos,
                    "proTeamId": 12, "points": points})
    return {"season": season, "weeks": sorted({r["week"] for r in out}),
            "starters": out}


class TestStarterRows(unittest.TestCase):
    """fetch.starter_rows: the started nine, and only those."""

    STARTED = [
        (1, "Quarter Back", 25.0, 1, 0),
        (2, "Runner Up", 12.0, 2, 2),
        (3, "Wide Out", 8.0, 3, 4),
        (4, "Tight Fit", 6.0, 4, 6),
        (5, "Flex Guy", 9.0, 2, 23),
        (6, "Kick Kicker", 11.0, 5, 17),
        (7, "Some Defense", 4.0, 16, 16),
    ]
    BENCHED = [(8, "Bench Warmer", 30.0, 2, 20)]

    def setUp(self):
        self.payload = {"schedule": [
            {"matchupPeriodId": 3,
             "home": make_side(1, self.STARTED, self.BENCHED),
             "away": make_side(2, self.STARTED)},
            # A different period in the same response: rosters only come back
            # for the week that was asked for, but other periods are still
            # listed and must not be read.
            {"matchupPeriodId": 4,
             "home": {"teamId": 3, "totalPoints": 0.0},
             "away": {"teamId": 4, "totalPoints": 0.0}},
        ]}
        self.rows = fetch.starter_rows(self.payload, 3)

    def test_only_starters_are_kept(self):
        self.assertEqual(len(self.rows), 2 * len(self.STARTED))
        self.assertNotIn("Bench Warmer", [r["name"] for r in self.rows])

    def test_slot_comes_from_the_current_period_roster(self):
        # rosterForMatchupPeriod zeroes lineupSlotId, so a naive read would
        # report every starter in slot 0 and the kicker would be unfindable.
        kicker = next(r for r in self.rows if r["pos"] == compute.KICKER_POS)
        self.assertEqual(kicker["slot"], 17)
        self.assertEqual(kicker["points"], 11.0)

    def test_rows_carry_the_requested_week_and_team(self):
        self.assertEqual({r["week"] for r in self.rows}, {3})
        self.assertEqual({r["teamId"] for r in self.rows}, {1, 2})

    def test_other_matchup_periods_are_ignored(self):
        self.assertNotIn(3, {r["teamId"] for r in self.rows})

    def test_an_unplayed_week_stores_nothing(self):
        # ESPN returns a projected lineup for a future week with every
        # appliedStatTotal at 0. Storing it would put a wall of fake zeroes
        # in the donut column.
        payload = {"schedule": [
            {"matchupPeriodId": 9,
             "home": make_side(1, [(1, "Kick Kicker", 0.0, 5, 17)], total=0.0),
             "away": make_side(2, [(1, "Kick Kicker", 0.0, 5, 17)], total=0.0)},
        ]}
        self.assertEqual(fetch.starter_rows(payload, 9), [])

    def test_a_playoff_bye_has_no_opponent_and_does_not_crash(self):
        payload = {"schedule": [
            {"matchupPeriodId": 15,
             "home": make_side(1, [(6, "Kick Kicker", 11.0, 5, 17)])},
        ]}
        rows = fetch.starter_rows(payload, 15)
        self.assertEqual([r["teamId"] for r in rows], [1])


class TestDumpStarters(unittest.TestCase):
    """fetch.dump_starters: deterministic, one row per line."""

    ROWS = [
        {"week": 2, "teamId": 1, "slot": 17, "playerId": 9, "name": "B",
         "pos": 5, "proTeamId": 12, "points": 3.0},
        {"week": 1, "teamId": 2, "slot": 17, "playerId": 8, "name": "A",
         "pos": 5, "proTeamId": 12, "points": 7.0},
        {"week": 1, "teamId": 1, "slot": 17, "playerId": 7, "name": "C",
         "pos": 5, "proTeamId": 12, "points": 5.0},
    ]

    def test_round_trips_as_json(self):
        data = json.loads(fetch.dump_starters(2025, self.ROWS))
        self.assertEqual(data["season"], 2025)
        self.assertEqual(data["weeks"], [1, 2])
        self.assertEqual(len(data["starters"]), 3)

    def test_rows_are_sorted_by_week_team_player(self):
        data = json.loads(fetch.dump_starters(2025, self.ROWS))
        self.assertEqual([(r["week"], r["teamId"], r["playerId"])
                          for r in data["starters"]],
                         [(1, 1, 7), (1, 2, 8), (2, 1, 9)])

    def test_input_order_does_not_change_the_file(self):
        # The daily bot commits when a file changes. A fetch that reordered
        # rows would manufacture a commit every morning.
        a = fetch.dump_starters(2025, self.ROWS)
        b = fetch.dump_starters(2025, list(reversed(self.ROWS)))
        self.assertEqual(a, b)

    def test_one_line_per_player(self):
        text = fetch.dump_starters(2025, self.ROWS)
        self.assertEqual(sum(1 for line in text.splitlines()
                             if line.startswith('    {')), 3)

    def test_only_the_documented_fields_are_written(self):
        rows = [dict(self.ROWS[0], injuryStatus="ACTIVE", onTeamId=4)]
        data = json.loads(fetch.dump_starters(2025, rows))
        self.assertEqual(set(data["starters"][0]), set(fetch.STARTER_FIELDS))


class TestKickerStarts(unittest.TestCase):
    """compute.owned_starts / kicker_starts: the owner join."""

    def setUp(self):
        self.standings = [compute.build_standings(
            make_raw(full_season_weeks(), season=2025), UPDATED)]
        self.files = [make_starter_file(2025, [
            (1, 1, 100, "Alpha Kicks", 20.0),
            (1, 1, 900, "Quarter Back", 30.0, 1),
            (1, 99, 100, "Alpha Kicks", 99.0),
        ])]

    def test_kicker_starts_keeps_only_kickers(self):
        rows = compute.kicker_starts(self.files, self.standings)
        self.assertEqual([r["name"] for r in rows], ["Alpha Kicks"])

    def test_owned_starts_keeps_every_position(self):
        rows = compute.owned_starts(self.files, self.standings)
        self.assertEqual(sorted(r["pos"] for r in rows), [1, 5])

    def test_the_owner_is_attached_from_that_seasons_standings(self):
        row = compute.kicker_starts(self.files, self.standings)[0]
        self.assertEqual(row["owner"], "First1 Last1")
        self.assertEqual(row["season"], 2025)
        self.assertEqual(row["proTeam"], "KC")

    def test_a_team_with_no_owner_is_dropped_not_credited_to_nobody(self):
        rows = compute.kicker_starts(self.files, self.standings)
        self.assertEqual([r["teamId"] for r in rows], [1])

    def test_a_season_with_no_standings_file_is_skipped(self):
        files = self.files + [make_starter_file(2018, [(1, 1, 100, "A", 5.0)])]
        rows = compute.kicker_starts(files, self.standings)
        self.assertEqual({r["season"] for r in rows}, {2025})


class TestKickerStats(unittest.TestCase):
    """compute.build_kicker_stats: the leaderboard, the owners, the trophies.

    Fixture, two seasons. Alpha Kicks is the all-time leader and is ridden by
    two owners; Bravo Boot is the donut machine; Charlie Leg is a one-off.
    """

    def setUp(self):
        self.standings = [
            compute.build_standings(make_raw(full_season_weeks(), season=2025),
                                    UPDATED),
            compute.build_standings(make_raw(full_season_weeks(), season=2024),
                                    UPDATED),
        ]
        self.files = [
            make_starter_file(2025, [
                (1, 1, 100, "Alpha Kicks", 20.0),
                (2, 1, 100, "Alpha Kicks", 10.0),
                (1, 3, 100, "Alpha Kicks", 5.0),
                (1, 2, 200, "Bravo Boot", 0.0),
                (2, 2, 200, "Bravo Boot", 0.0),
                (2, 3, 300, "Charlie Leg", 9.0),
                (1, 1, 900, "Quarter Back", 29.0, 1),
            ]),
            make_starter_file(2024, [
                (1, 1, 100, "Alpha Kicks", 15.0),
                (1, 4, 200, "Bravo Boot", 12.0),
            ]),
        ]
        self.short = {f"First{i} Last{i}": f"First{i}" for i in range(1, 13)}
        self.stats = compute.build_kicker_stats(self.files, self.standings,
                                                self.short)
        self.by_name = {k["name"]: k for k in self.stats["kickers"]}
        self.awards = {a["name"]: a for a in self.stats["awards"]}

    def test_totals(self):
        self.assertEqual(self.stats["totalPoints"], 71.0)
        self.assertEqual(self.stats["totalStarts"], 8)
        self.assertEqual(self.stats["distinctKickers"], 3)
        self.assertEqual(self.stats["seasons"], [2024, 2025])

    def test_leaderboard_is_ranked_by_points(self):
        self.assertEqual([k["name"] for k in self.stats["kickers"]],
                         ["Alpha Kicks", "Bravo Boot", "Charlie Leg"])

    def test_a_kickers_career_row(self):
        alpha = self.by_name["Alpha Kicks"]
        self.assertEqual(alpha["points"], 50.0)
        self.assertEqual(alpha["starts"], 4)
        self.assertEqual(alpha["average"], 12.5)
        self.assertEqual(alpha["doubleDigits"], 3)
        self.assertEqual(alpha["zeroes"], 0)
        self.assertEqual(alpha["seasons"], [2024, 2025])

    def test_best_and_worst_week_name_the_owner_who_started_him(self):
        alpha = self.by_name["Alpha Kicks"]
        self.assertEqual(alpha["best"], {"points": 20.0, "season": 2025,
                                         "week": 1, "owner": "First1 Last1"})
        self.assertEqual(alpha["worst"], {"points": 5.0, "season": 2025,
                                          "week": 1, "owner": "First3 Last3"})

    def test_owners_are_listed_most_loyal_first(self):
        alpha = self.by_name["Alpha Kicks"]
        self.assertEqual(alpha["ownerList"], ["First1 Last1", "First3 Last3"])
        self.assertEqual(alpha["ownerCounts"][0], ("First1 Last1", 3))

    def test_a_scoreless_start_counts_as_a_zero(self):
        self.assertEqual(self.by_name["Bravo Boot"]["zeroes"], 2)
        self.assertEqual(self.by_name["Bravo Boot"]["points"], 12.0)

    def test_owner_rows(self):
        rows = {o["owner"]: o for o in self.stats["owners"]}
        first = rows["First1 Last1"]
        self.assertEqual(first["points"], 45.0)
        self.assertEqual(first["starts"], 3)
        self.assertEqual(first["average"], 15.0)
        self.assertEqual(first["distinctKickers"], 1)
        self.assertEqual(first["favorite"], {"name": "Alpha Kicks", "starts": 3})
        self.assertEqual(rows["First2 Last2"]["zeroes"], 2)

    def test_owner_rows_are_ranked_by_points(self):
        self.assertEqual(self.stats["owners"][0]["owner"], "First1 Last1")

    def test_share_is_of_every_started_point(self):
        # 71 kicker points out of 100 started (the 29-point QB is the rest).
        self.assertEqual(self.stats["share"], 71.0)

    def test_by_season_names_each_years_leader_newest_first(self):
        self.assertEqual([(b["season"], b["name"], b["points"])
                          for b in self.stats["bySeason"]],
                         [(2025, "Alpha Kicks", 35.0), (2024, "Alpha Kicks", 15.0)])
        self.assertEqual(self.stats["bySeason"][0]["owners"],
                         ["First1 Last1", "First3 Last3"])

    def test_no_starter_data_means_no_page(self):
        self.assertIsNone(compute.build_kicker_stats([], self.standings))
        self.assertIsNone(compute.build_kicker_stats(
            [make_starter_file(2025, [(1, 1, 900, "Quarter Back", 29.0, 1)])],
            self.standings))

    def test_results_are_deterministic_across_runs(self):
        again = compute.build_kicker_stats(self.files, self.standings, self.short)
        self.assertEqual(self.stats, again)

    def test_every_award_is_fully_populated(self):
        for a in self.stats["awards"]:
            for field in ("emoji", "name", "headline", "detail", "blurb"):
                self.assertTrue(a.get(field), f"{a.get('name')}.{field}")

    def test_golden_boot_goes_to_the_all_time_leader(self):
        self.assertEqual(self.awards["The Golden Boot"]["headline"], "Alpha Kicks")

    def test_best_week_award(self):
        self.assertIn("Alpha Kicks", self.awards["Best week ever"]["headline"])
        self.assertIn("20.0", self.awards["Best week ever"]["headline"])

    def test_there_is_no_worst_week_award(self):
        # Dropped on purpose: the worst kicker week is always a 0.0 and the
        # league has 17 of them, so the "record" is only whichever zero
        # sorts first. Donut king counts them instead, which is the same
        # joke with something real behind it.
        self.assertNotIn("Worst week ever", self.awards)

    def test_donut_king_is_the_owner_with_the_most_scoreless_starts(self):
        self.assertEqual(self.awards["Donut king"]["headline"], "First2")
        self.assertIn("2 scoreless", self.awards["Donut king"]["detail"])

    def test_longest_marriage_is_the_most_started_pairing(self):
        self.assertEqual(self.awards["Longest marriage"]["headline"],
                         "First1 + Alpha Kicks")
        self.assertIn("3 weeks", self.awards["Longest marriage"]["detail"])

    def test_journeyman_is_the_most_widely_started_kicker(self):
        self.assertEqual(self.awards["League journeyman"]["headline"],
                         "Alpha Kicks")

    def test_one_and_done_counts_single_start_kickers(self):
        self.assertIn("1 kicker", self.awards["One and done"]["headline"])
        self.assertIn("Charlie Leg", self.awards["One and done"]["detail"])

    def test_award_lines_use_short_owner_names(self):
        # The tables shorten in the template; these sentences can't, so the
        # shortening has to happen in compute or the page mixes both forms.
        for a in self.stats["awards"]:
            self.assertNotIn("Last1", a["headline"] + a["detail"])

    def test_average_awards_need_a_real_sample(self):
        # Nobody in the fixture has MIN_KICKER_STARTS starts, so the
        # best/worst-average trophies are withheld rather than handed to
        # whoever had one good Sunday.
        self.assertNotIn("Blessed foot", self.awards)
        self.assertNotIn("Cursed foot", self.awards)

    def test_average_awards_appear_once_the_sample_is_there(self):
        rows = [(w, 1, 100, "Alpha Kicks", 20.0)
                for w in range(1, compute.MIN_KICKER_STARTS + 1)]
        rows += [(w, 2, 200, "Bravo Boot", 1.0)
                 for w in range(1, compute.MIN_KICKER_STARTS + 1)]
        stats = compute.build_kicker_stats(
            [make_starter_file(2025, rows)], self.standings, self.short)
        awards = {a["name"]: a for a in stats["awards"]}
        self.assertEqual(awards["Blessed foot"]["headline"], "First1")
        self.assertEqual(awards["Cursed foot"]["headline"], "First2")


class TestKickerPageWiring(unittest.TestCase):
    """The page is rendered when there is starter data, and skipped when not."""

    def test_kickers_is_in_the_page_list(self):
        self.assertIn(("kickers.html", "kickers.html"), build.PAGES)

    def test_the_template_renders_from_real_data(self):
        seasons = sorted(int(p.stem.split("-")[1])
                         for p in pathlib.Path("data").glob("standings-*.json"))
        standings = [json.loads(pathlib.Path(f"data/standings-{y}.json")
                                .read_text(encoding="utf-8")) for y in seasons]
        files = [json.loads(p.read_text(encoding="utf-8"))
                 for p in sorted(pathlib.Path("data").glob("starters-*.json"))]
        if not files:
            self.skipTest("no data/starters-*.json on file")
        stats = compute.build_kicker_stats(files, standings)
        self.assertTrue(stats["kickers"])
        # Every kicker's points must equal the sum of their own starts, which
        # is the one invariant the whole page rests on.
        starts = compute.kicker_starts(files, standings)
        for k in stats["kickers"][:5]:
            own = sum(s["points"] for s in starts
                      if s["playerId"] == k["playerId"])
            self.assertAlmostEqual(k["points"], round(own, 1), places=1)

    def test_started_points_reconcile_with_the_committed_standings(self):
        # The strongest available check that the starter files are the real
        # lineups: every team-week's started points must add up to the score
        # the standings already record.
        for path in sorted(pathlib.Path("data").glob("starters-*.json")):
            year = int(path.stem.split("-")[1])
            standings_path = pathlib.Path(f"data/standings-{year}.json")
            if not standings_path.exists():
                continue
            starters = json.loads(path.read_text(encoding="utf-8"))
            season = json.loads(standings_path.read_text(encoding="utf-8"))
            sums = {}
            for r in starters["starters"]:
                key = (r["week"], r["teamId"])
                sums[key] = sums.get(key, 0.0) + (r["points"] or 0.0)
            for week in season["weeks"]:
                for team in week["teams"]:
                    key = (week["week"], team["teamId"])
                    self.assertIn(key, sums, f"{year} {key} has no starters")
                    self.assertAlmostEqual(sums[key], team["score"], places=1,
                                           msg=f"{year} week {key}")


# --------------------------------------------------------------------------
# Team pages (ENH-025).
# --------------------------------------------------------------------------

class TestTeamSeason(unittest.TestCase):
    """compute.build_team_season: the per-team page data (ENH-025).

    Fixture math (full_season_weeks): week w, team i scores 100 + 10w + i,
    so team 12 wins every week by 1 from the top of the league (2 pts each,
    28 total) and team 1 loses every week by 1 from the bottom (0 total).
    """

    def setUp(self):
        self.season = compute.build_standings(
            make_raw(full_season_weeks()), UPDATED)

    def test_unknown_team_returns_none(self):
        self.assertIsNone(compute.build_team_season(self.season, 99))

    def test_header_comes_from_the_standings_row(self):
        d = compute.build_team_season(self.season, 12)
        self.assertEqual(d["owner"], "First12 Last12")
        self.assertEqual(d["rank"], 1)
        self.assertEqual(d["points"], 28)

    def test_every_week_has_score_line_and_split(self):
        d = compute.build_team_season(self.season, 1)
        self.assertEqual(len(d["weeks"]), 14)
        first = d["weeks"][0]
        self.assertEqual(first["score"], 110)
        self.assertEqual(first["scoreToBeat"], 115)
        self.assertEqual(first["result"], "L")
        self.assertEqual(first["weekPoints"], 0)
        self.assertEqual(first["opponentId"], 2)

    def test_best_team_is_all_twos(self):
        d = compute.build_team_season(self.season, 12)
        self.assertTrue(all(w["weekPoints"] == 2 for w in d["weeks"]))
        self.assertTrue(all(w["result"] == "W" for w in d["weeks"]))
        self.assertTrue(all(w["topHalf"] for w in d["weeks"]))

    def test_h2h_counts_and_margins(self):
        d = compute.build_team_season(self.season, 12)
        # Fixed pairings in this fixture: team 12 only ever plays team 11.
        self.assertEqual(len(d["h2h"]), 1)
        row = {r["teamId"]: r for r in d["h2h"]}
        self.assertEqual(row[11]["wins"], 14)
        self.assertEqual(row[11]["losses"], 0)
        self.assertAlmostEqual(row[11]["pointsFor"], 2604.0)
        self.assertAlmostEqual(row[11]["pointsAgainst"], 2590.0)
        self.assertAlmostEqual(row[11]["margin"], 14.0)

    def test_h2h_is_symmetric(self):
        a = compute.build_team_season(self.season, 1)
        b = compute.build_team_season(self.season, 2)
        a_vs_b = {r["teamId"]: r for r in a["h2h"]}
        b_vs_a = {r["teamId"]: r for r in b["h2h"]}
        self.assertEqual(a_vs_b[2]["wins"], b_vs_a[1]["losses"])
        self.assertAlmostEqual(a_vs_b[2]["pointsFor"],
                               b_vs_a[1]["pointsAgainst"])
        self.assertAlmostEqual(a_vs_b[2]["margin"], -b_vs_a[1]["margin"])

    def test_postseason_games_are_split_out(self):
        bracket = [
            make_bracket_matchup(15, 1, 2, 130.0, 120.0),
            make_bracket_matchup(16, 1, 12, 90.0, 100.0,
                                 tier="LOSERS_BRACKET"),
            make_bracket_matchup(15, 3, 4, 100.0, 90.0),  # other teams
        ]
        season = compute.build_standings(
            make_raw(full_season_weeks(), bracket=bracket), UPDATED)
        d = compute.build_team_season(season, 1)
        self.assertEqual(len(d["weeks"]), 14)  # regular season only
        self.assertEqual([g["week"] for g in d["postseason"]], [15, 16])
        self.assertEqual(d["postseason"][0]["result"], "W")
        self.assertEqual(d["postseason"][0]["tier"], "WINNERS_BRACKET")
        self.assertEqual(d["postseason"][1]["result"], "L")
        self.assertEqual(d["postseason"][1]["tier"], "LOSERS_BRACKET")
        # Postseason meetings don't touch the regular-season h2h table.
        row = {r["teamId"]: r for r in d["h2h"]}
        self.assertEqual((row[2]["wins"], row[2]["losses"]), (0, 14))

    def test_deterministic(self):
        self.assertEqual(compute.build_team_season(self.season, 1),
                         compute.build_team_season(self.season, 1))


class TestTeamPageWiring(unittest.TestCase):
    """Every team of every season on disk builds a page's worth of data."""

    def test_every_team_of_every_season_builds(self):
        for path in sorted(pathlib.Path("data").glob("standings-*.json")):
            year = int(path.stem.split("-")[1])
            season = json.loads(path.read_text(encoding="utf-8"))
            for s in season["standings"]:
                d = compute.build_team_season(season, s["teamId"])
                self.assertIsNotNone(d, (year, s["teamId"]))
                self.assertEqual(len(d["weeks"]), season["throughWeek"],
                                 (year, s["teamId"]))
                # The chips under the chart must agree with the standings
                # table: the same dual points, just week by week.
                self.assertEqual(sum(w["weekPoints"] for w in d["weeks"]),
                                 s["points"], (year, s["teamId"]))
                # One h2h row per opponent met so far (mid-season teams
                # have met fewer than 11), covering exactly every week.
                opponents = {w["opponentId"] for w in d["weeks"]}
                self.assertEqual(len(d["h2h"]), len(opponents),
                                 (year, s["teamId"]))
                self.assertEqual(
                    sum(r["wins"] + r["losses"] + r["ties"]
                        for r in d["h2h"]),
                    len(d["weeks"]), (year, s["teamId"]))




class TestUpdatedStamp(unittest.TestCase):
    """compute.main keeps the old `updated` stamp when nothing else changed.

    The stamp is rendered on every page (ENH-025), so re-stamping a run
    whose data didn't move would change docs/ every morning and the daily
    bot would commit a diff it manufactured.
    """

    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        self.data = pathlib.Path(self.tmp) / "data"
        self.data.mkdir()
        (self.data / "raw-2025.json").write_text(
            json.dumps(make_raw(full_season_weeks(), season=2025)),
            encoding="utf-8")

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        os.chdir(self.tmp)
        old_argv = sys.argv
        sys.argv = ["compute.py", "--season", "2025"]
        try:
            compute.main()
        finally:
            sys.argv = old_argv
        return json.loads((self.data / "standings-2025.json")
                          .read_text(encoding="utf-8"))

    def test_unchanged_data_keeps_the_old_stamp(self):
        first = self._run()
        stamp = first["updated"]
        time.sleep(1.1)  # the second run's clock must read a new second
        second = self._run()
        self.assertEqual(second["updated"], stamp)

    def test_changed_data_gets_a_new_stamp(self):
        first = self._run()
        raw = json.loads((self.data / "raw-2025.json")
                         .read_text(encoding="utf-8"))
        raw["mMatchupScore"]["schedule"][0]["home"]["totalPoints"] += 5
        (self.data / "raw-2025.json").write_text(json.dumps(raw),
                                                 encoding="utf-8")
        time.sleep(1.1)
        second = self._run()
        self.assertNotEqual(second["updated"], first["updated"])


class TestMarginStats(unittest.TestCase):
    """The per-team "how it ended" stats: loss points, heartbreaks, blowouts."""

    def _profile(self, scores):
        season = compute.build_standings(make_raw({1: week_games(scores)}),
                                         UPDATED)
        return season, compute.scoring_profile(season)

    def test_points_in_losses_heartbreaks_and_blowouts(self):
        # (1,2) 100-96   margin 4  -> heartbreak for 2
        # (3,4) 100-95   margin 5  -> close loss for 4, not a heartbreak
        # (5,6) 150-100  margin 50 -> blowout win for 5
        # (7,8) 151-100  margin 51 -> blowout win for 7
        # (9,10) 100-100 tie      -> nothing
        # (11,12) 200-149 margin 51 -> blowout win for 11
        scores = [100.0, 96.0, 100.0, 95.0, 150.0, 100.0,
                  151.0, 100.0, 100.0, 100.0, 200.0, 149.0]
        season, prof = self._profile(scores)
        self.assertEqual(prof[2]["pointsInLosses"], 96.0)
        self.assertEqual(prof[2]["heartbreaks"], 1)
        self.assertEqual(prof[4]["pointsInLosses"], 95.0)
        self.assertEqual(prof[4]["heartbreaks"], 0)  # margin 5 is not under 5
        self.assertEqual(prof[6]["pointsInLosses"], 100.0)
        self.assertEqual(prof[6]["blowoutWins"], 0)
        self.assertEqual(prof[5]["blowoutWins"], 1)
        self.assertEqual(prof[7]["blowoutWins"], 1)
        self.assertEqual(prof[11]["blowoutWins"], 1)
        self.assertEqual(prof[12]["pointsInLosses"], 149.0)
        self.assertEqual(prof[12]["heartbreaks"], 0)
        # The tie produces no loss, heartbreak, or blowout for either team.
        self.assertEqual(prof[9]["pointsInLosses"], 0.0)
        self.assertEqual(prof[10]["pointsInLosses"], 0.0)
        self.assertEqual(prof[9]["heartbreaks"], 0)
        self.assertEqual(prof[9]["blowoutWins"], 0)
        # Close-game accounting is untouched by the new stats: only the
        # two sub-10-margin games count, and only the winners of those.
        self.assertEqual(prof[1]["closeGames"], 1)
        self.assertEqual(prof[1]["closeWins"], 1)
        self.assertEqual(prof[4]["closeGames"], 1)
        self.assertEqual(prof[4]["closeWins"], 0)
        self.assertEqual(prof[6]["closeGames"], 0)
        self.assertEqual(prof[11]["closeGames"], 0)
        # The stats reach the Stats page table.
        table = {t["teamId"]: t
                 for t in compute.build_season_stats(season)["table"]}
        self.assertEqual(table[2]["heartbreaks"], 1)
        self.assertEqual(table[2]["pointsInLosses"], 96.0)
        self.assertEqual(table[5]["blowoutWins"], 1)
        self.assertEqual(table[3]["heartbreaks"], 0)
        self.assertEqual(table[3]["blowoutWins"], 0)

    def test_blowout_threshold_is_inclusive(self):
        # Exactly 50 is a blowout; the losing side of a 50-point game is
        # not a heartbreak.
        scores = [150.0, 100.0] + [100.0 + i for i in range(10)]
        _season, prof = self._profile(scores)
        self.assertEqual(prof[1]["blowoutWins"], 1)
        self.assertEqual(prof[2]["blowoutWins"], 0)
        self.assertEqual(prof[2]["heartbreaks"], 0)

