import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from sources.common import Cache  # noqa: E402

WK39 = date(2026, 9, 22)   # ISO 2026-W39
WK40 = date(2026, 9, 29)   # ISO 2026-W40


class TestSnapshotMovers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Cache(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_week_has_no_movers(self):
        movers, since = server.snapshot_movers(self.cache, 2026, {1: 3.0},
                                               WK40)
        self.assertEqual((movers, since), ({}, None))
        self.assertEqual(self.cache.names("snapshot-weekly-2026-"),
                         ["snapshot-weekly-2026-2026-W40"])

    def test_reloads_in_the_same_week_do_not_reset_movers(self):
        server.snapshot_movers(self.cache, 2026, {1: 5.0, 2: 2.0}, WK39)
        for _ in range(3):  # the old bug: each load became the baseline
            movers, since = server.snapshot_movers(
                self.cache, 2026, {1: 3.0, 2: 4.0}, WK40)
        self.assertEqual(movers, {1: 2.0, 2: -2.0})
        self.assertEqual(since, "2026-W39")

    def test_this_weeks_snapshot_tracks_the_latest_board(self):
        server.snapshot_movers(self.cache, 2026, {1: 5.0}, WK40)
        server.snapshot_movers(self.cache, 2026, {1: 4.0}, WK40)
        self.assertEqual(self.cache.load("snapshot-weekly-2026-2026-W40"),
                         {"1": 4.0})

    def test_compares_with_newest_earlier_week(self):
        server.snapshot_movers(self.cache, 2026, {1: 9.0}, date(2026, 9, 15))
        server.snapshot_movers(self.cache, 2026, {1: 6.0}, WK39)
        movers, since = server.snapshot_movers(self.cache, 2026, {1: 5.0},
                                               WK40)
        self.assertEqual((movers, since), ({1: 1.0}, "2026-W39"))


# Build-board keep payload (ENH-037): every player in the pool gets a
# next-season price, including players with no draft history at all.
CFG = {
    "season": 2026,
    "myTeamId": 11,
    "keepers": {"udfaBase": 5, "increments": [7, 10, 12, 15], "overrides": {}},
}
PLAYERS = [
    # Auction buy in the 2026 draft -> base + $7 (yr 1)
    {"espnId": 1, "name": "Auction Guy", "pos": "RB", "status": "OWNED",
     "ownerTeamId": 5},
    # Re-bought at auction in 2026 after being kept in 2025 -> the
    # auction buy resets the chain -> used 0, base + $7
    {"espnId": 2, "name": "Rebuy Guy", "pos": "WR", "status": "OWNED",
     "ownerTeamId": 5},
    # Kept in 2025, not drafted in 2026 -> UDFA base
    {"espnId": 3, "name": "Ex Keeper", "pos": "QB", "status": "FA"},
    # Never drafted in any fetched season -> UDFA base too
    {"espnId": 4, "name": "Never Drafted", "pos": "TE", "status": "WAIVERS"},
]
DRAFTS = {
    "fetchedAt": "2026-10-16T00:00:00+00:00",
    "seasons": list(range(2019, 2027)),
    "picks": {
        "1": {"2026": {"bid": 3, "keeper": False}},
        "2": {"2025": {"bid": 20, "keeper": True},
              "2026": {"bid": 30, "keeper": False}},
        "3": {"2025": {"bid": 40, "keeper": True}},
    },
    "notes": [],
}


class TestBoardKeep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Cache(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def board(self, with_drafts=True):
        self.cache.save("espn", {"fetchedAt": "2026-10-16T00:00:00+00:00",
                                 "players": PLAYERS, "league": {}})
        if with_drafts:
            self.cache.save("drafts", DRAFTS)
        return server.build_board(server.State(dict(CFG), self.cache))

    def test_every_player_gets_a_keep_price(self):
        players = self.board()["players"]
        self.assertEqual(len(players), 4)
        self.assertEqual(players["1"]["keep"],
                         {"price": 10, "base": 3, "kind": "auction",
                          "used": 0, "estimated": False, "override": False})
        k2 = players["2"]["keep"]
        self.assertEqual((k2["price"], k2["base"], k2["kind"], k2["used"]),
                         (37, 30, "auction", 0))
        # Drafted in an earlier season but no pick this one: UDFA base.
        self.assertEqual((players["3"]["keep"]["price"],
                          players["3"]["keep"]["kind"]), (12, "udfa"))
        # No draft history at all: same $12, never "–".
        self.assertEqual((players["4"]["keep"]["price"],
                          players["4"]["keep"]["kind"]), (12, "udfa"))

    def test_override_from_config_wins(self):
        cfg = dict(CFG)
        cfg["keepers"] = dict(CFG["keepers"], overrides={"1": 99})
        self.cache.save("espn", {"fetchedAt": "2026-10-16T00:00:00+00:00",
                                 "players": PLAYERS, "league": {}})
        self.cache.save("drafts", DRAFTS)
        players = server.build_board(server.State(cfg, self.cache))["players"]
        self.assertEqual((players["1"]["keep"]["price"],
                          players["1"]["keep"]["override"]), (99, True))

    def test_no_drafts_source_yet_means_no_keep_field(self):
        for p in self.board(with_drafts=False)["players"].values():
            self.assertNotIn("keep", p)


if __name__ == "__main__":
    unittest.main()
