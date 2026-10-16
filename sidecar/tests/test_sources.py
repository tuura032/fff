import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sources.drafts as drafts  # noqa: E402
import sources.espn as espn  # noqa: E402
import sources.ffballers as ffb  # noqa: E402
import sources.harris as harris  # noqa: E402
import sources.fantasypros as fp  # noqa: E402
from sources.common import Cache, SourceError  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
CFG = {"leagueId": "877873"}


def fixture(name):
    return (FIX / name).read_text(encoding="utf-8")


def fixture_json(name):
    return json.loads(fixture(name))


class TestFfbParsers(unittest.TestCase):
    def setUp(self):
        self.kicker = fixture("ffb_kicker.html")
        self.defense = fixture("ffb_defense.html")

    def test_main_rows_from_all_pages_deduped(self):
        out = ffb.parse({"kicker": self.kicker})
        main = [r for r in out["rows"] if r["stats"] is not None]
        # 6 players x 2 analysts (Andy, Jason); the page is its own main.
        self.assertEqual(len(main), 12)
        self.assertEqual({r["source"] for r in main},
                         {"ffb-andy", "ffb-jason"})
        self.assertEqual({r["pos"] for r in main},
                         {"QB", "RB", "WR", "TE"})
        by_key = {(r["source"], r["name"]): r for r in main}
        gibbs = by_key[("ffb-andy", "Jahmyr Gibbs")]
        self.assertEqual(gibbs["view"], "weekly")
        self.assertEqual(gibbs["team"], "DET")
        self.assertEqual(gibbs["bye"], 6)
        self.assertEqual(gibbs["injury"], "NORMAL")
        self.assertEqual(gibbs["stats"]["rushing_yards"], "95.0")
        self.assertIsNone(gibbs["rank"])

    def test_k_rows_carry_per_analyst_ranks(self):
        out = ffb.parse({"kicker": self.kicker})
        k = [r for r in out["rows"] if r["pos"] == "K"]
        # 3 kickers x 3 analysts
        self.assertEqual(len(k), 9)
        mc = {r["source"]: r["rank"] for r in k if r["name"] == "Evan McPherson"}
        self.assertEqual(mc, {"ffb-andy": 1, "ffb-jason": 5, "ffb-mike": 2})
        self.assertTrue(all(r["stats"] is None for r in k))

    def test_d_rows_become_dst(self):
        out = ffb.parse({"kicker": self.kicker, "defense": self.defense})
        d = [r for r in out["rows"] if r["pos"] == "D/ST"]
        self.assertEqual(len(d), 6)  # 2 defenses x 3 analysts
        minn = {r["source"]: r["rank"] for r in d
                if r["name"] == "Minnesota Vikings"}
        self.assertEqual(minn, {"ffb-andy": 1, "ffb-jason": 2, "ffb-mike": 1})

    def test_missing_kd_rows_are_a_note_not_a_failure(self):
        out = ffb.parse({"kicker": fixture("ffb_main_only.html")})
        self.assertTrue(any(r["pos"] == "QB" for r in out["rows"]))
        self.assertFalse(any(r["pos"] == "K" for r in out["rows"]))
        self.assertTrue(any("kicker page" in n for n in out["notes"]))

    def test_no_projection_array_is_a_source_failure(self):
        with self.assertRaises(SourceError):
            ffb.parse({"kicker": "<html><body>no json here</body></html>"})

    def test_dedupes_repeated_main_array(self):
        # Both pages carry the same main array; rows must not double.
        out = ffb.parse({"kicker": self.kicker, "quarterback": self.kicker})
        main = [r for r in out["rows"] if r["stats"] is not None]
        self.assertEqual(len(main), 12)


class TestHarrisParsers(unittest.TestCase):
    def test_ppr_table_chosen_over_standard(self):
        rows = harris.parse_page(fixture("harris_rb.html"), "RB")
        self.assertEqual([r["rank"] for r in rows], [1, 2, 3, 4])
        self.assertEqual(rows[3]["name"], "Kenneth Walker")
        self.assertEqual(rows[3]["opponent"], "@ LV")

    def test_single_table_page_uses_it(self):
        rows = harris.parse_page(fixture("harris_te.html"), "TE")
        self.assertEqual([r["name"] for r in rows],
                         ["Dalton Kincaid", "Sam LaPorta", "Isaiah Likely"])

    def test_page_without_rank_rows_is_a_source_failure(self):
        with self.assertRaises(SourceError):
            harris.parse_page(fixture("harris_empty.html"), "RB")



class TestFantasyProsParsers(unittest.TestCase):
    def test_rows_from_ecr_data(self):
        rows = fp.parse_page(fixture("fp_ros.html"), "ros")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["view"] == "ros" and r["source"] == "fp"
                            for r in rows))
        self.assertEqual(rows[0]["name"], "Jahmyr Gibbs")
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["bye"], 6)
        k = next(r for r in rows if r["name"] == "Evan McPherson")
        self.assertEqual(k["pos"], "K")
        self.assertEqual(k["opponent"], "vs. JAC")

    def test_dynasty_rows_carry_age(self):
        rows = fp.parse_page(fixture("fp_dynasty.html"), "dynasty")
        self.assertEqual(rows[0]["age"], 26)
        self.assertEqual(rows[1]["age"], 24)

    def test_missing_ecr_data_is_a_source_failure(self):
        with self.assertRaises(SourceError):
            fp.parse_page(fixture("fp_missing.html"), "ros")


class TestEspnParsers(unittest.TestCase):
    def setUp(self):
        self.league = fixture_json("espn_league.json")
        self.fa = fixture_json("espn_fa.json")
        self.pro = fixture_json("espn_proteams.json")

    def test_players_from_rosters_and_fa(self):
        out = espn.parse(self.league, self.fa, self.pro, CFG, 2026)
        self.assertEqual(len(out["players"]), 6)  # 4 roster + 2 FA
        by_id = {p["espnId"]: p for p in out["players"]}
        self.assertEqual(by_id[100]["pos"], "QB")
        self.assertEqual(by_id[100]["team"], "DAL")      # proTeamId 6
        self.assertEqual(by_id[100]["status"], "OWNED")
        self.assertEqual(by_id[100]["ownerTeamId"], 1)
        self.assertEqual(by_id[101]["pos"], "K")          # proTeamId 34 -> K
        self.assertEqual(by_id[102]["pos"], "D/ST")       # proTeamId 6
        self.assertEqual(by_id[200]["status"], "WAIVERS")
        self.assertEqual(by_id[200]["pctOwned"], 88.07)
        self.assertEqual(by_id[200]["pctOwnedChange"], -1.45)
        self.assertEqual(by_id[201]["status"], "FA")
        self.assertIsNone(by_id[201]["pctOwned"])
        self.assertIsNone(by_id[201]["pctOwnedChange"])
        self.assertIsNone(by_id[100]["pctOwnedChange"])  # roster players

    def test_byes_come_from_pro_team_schedules(self):
        out = espn.parse(self.league, self.fa, self.pro, CFG, 2026)
        by_id = {p["espnId"]: p for p in out["players"]}
        self.assertEqual(by_id[100]["bye"], 9)    # DAL
        self.assertEqual(by_id[101]["bye"], 11)   # JAX kicker
        self.assertEqual(by_id[102]["bye"], 9)    # D/ST gets its team's bye
        self.assertEqual(by_id[200]["bye"], 10)   # MIA (waiver player)
        self.assertEqual(by_id[201]["bye"], 8)    # ARI (free agent)

    def test_bye_map_tolerates_missing_settings(self):
        self.assertEqual(espn.bye_map({}), {})
        self.assertEqual(espn.bye_map(None), {})
        self.assertEqual(espn.bye_map({"settings": {}}), {})
        out = espn.parse(self.league, self.fa, {}, CFG, 2026)
        self.assertTrue(all(p["bye"] is None for p in out["players"]))

    def test_league_block_passthrough(self):
        out = espn.parse(self.league, self.fa, self.pro, CFG, 2026)
        self.assertEqual(out["league"]["currentWeek"], 4)
        self.assertEqual(len(out["league"]["scoringItems"]), 3)
        self.assertEqual(out["league"]["lineupSlotCounts"]["2"], 2)
        self.assertEqual(out["teams"][0]["name"], "Test One")
        self.assertEqual(out["rows"], [])

    def test_empty_responses_are_source_failures(self):
        with self.assertRaises(SourceError):
            espn.parse({}, self.fa, self.pro, CFG, 2026)
        with self.assertRaises(SourceError):
            espn.parse(self.league, {"players": []}, self.pro, CFG, 2026)


# mDraftDetail test responses: player 999 appears every season (kept from
# 2021 on), and each season adds one more player drafted that year only.
def draft_response(season, broken=False):
    if broken:
        return {"draftDetail": {"drafted": True, "inProgress": False}}
    return {"draftDetail": {"drafted": True, "inProgress": False, "picks": [
        {"playerId": 999, "bidAmount": season - 2018, "keeper": season > 2020,
         "teamId": 1},
        {"playerId": 1000 + season, "bidAmount": 1, "keeper": False,
         "teamId": 2},
    ]}}


class FakeDraftClient:
    """Canned mDraftDetail responses; records which seasons were fetched."""

    def __init__(self, broken=()):
        self.broken = set(broken)
        self.calls = []

    def get(self, url, headers=None):
        season = int(re.search(r"seasons/(\d+)", url).group(1))
        self.calls.append(season)
        broken = self.broken

        class _Resp:
            def json(self):
                if season in broken:
                    raise SourceError(f"drafts: simulating {season} failure")
                return draft_response(season)
        return _Resp()


class TestDrafts(unittest.TestCase):
    CFG = {"leagueId": "877873",
           "urls": {"espn": "https://x/seasons/{season}/segments/0/"
                            "leagues/{leagueId}"}}

    def test_parse_picks(self):
        out = drafts.parse_picks(draft_response(2024))
        self.assertEqual(out, {999: {"bid": 6, "keeper": True},
                               3024: {"bid": 1, "keeper": False}})

    def test_no_picks_is_a_source_failure(self):
        with self.assertRaises(SourceError):
            drafts.parse_picks(draft_response(2024, broken=True))

    def test_finished_seasons_are_cached_permanently(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeDraftClient()
            payload = drafts.fetch(client, self.CFG, 2026, cache_dir=tmp)
            self.assertEqual(client.calls, list(range(2019, 2027)))
            self.assertEqual(payload["seasons"], list(range(2019, 2027)))
            self.assertEqual(sorted((Path(tmp) / f"draft-{s}.json")
                                    .exists() for s in range(2019, 2026)),
                             [True] * 7)
            # Second refresh: only the current season goes to ESPN again.
            client2 = FakeDraftClient()
            payload2 = drafts.fetch(client2, self.CFG, 2026, cache_dir=tmp)
            self.assertEqual(client2.calls, [2026])
            self.assertEqual(payload2["picks"], payload["picks"])

    def test_per_player_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = drafts.fetch(FakeDraftClient(), self.CFG, 2026,
                                   cache_dir=tmp)
            p999 = payload["picks"]["999"]
            self.assertEqual(p999["2026"], {"bid": 8, "keeper": True})
            self.assertEqual(p999["2019"], {"bid": 1, "keeper": False})
            self.assertIn("2026", payload["picks"]["3026"])  # one-year player
            self.assertTrue(payload["notes"])

    def test_broken_past_season_is_a_failure_not_an_empty_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError):
                drafts.fetch(FakeDraftClient(broken=(2021,)), self.CFG, 2026,
                             cache_dir=tmp)
            # The good seasons were still cached for next time.
            self.assertTrue((Path(tmp) / "draft-2019.json").exists())


class TestCache(unittest.TestCase):
    def test_save_load_roundtrip_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Cache(tmp)
            c.save("harris", {"fetchedAt": "x", "rows": [1, 2]})
            self.assertEqual(c.load("harris"),
                             {"fetchedAt": "x", "rows": [1, 2]})
            self.assertEqual(c.load("missing"), None)
            self.assertEqual([p.name for p in Path(tmp).iterdir()],
                             ["harris.json"])

    def test_overwrite_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Cache(tmp)
            c.save("espn", {"v": 1})
            c.save("espn", {"v": 2})
            self.assertEqual(c.load("espn"), {"v": 2})


if __name__ == "__main__":
    unittest.main()
