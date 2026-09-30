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


if __name__ == "__main__":
    unittest.main()
