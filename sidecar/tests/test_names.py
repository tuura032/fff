import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import names  # noqa: E402

ESPN = [
    {"espnId": 1, "name": "Kenneth Walker III", "pos": "RB", "team": "SEA"},
    {"espnId": 2, "name": "Ja'Marr Chase", "pos": "WR", "team": "CIN"},
    {"espnId": 3, "name": "D.J. Moore", "pos": "WR", "team": "CHI"},
    {"espnId": 4, "name": "Marvin Harrison Jr.", "pos": "WR", "team": "ARI"},
    {"espnId": 5, "name": "Josh Allen", "pos": "QB", "team": "BUF"},
    {"espnId": 6, "name": "Josh Allen", "pos": "RB", "team": "JAX"},   # same-name case
    {"espnId": 7, "name": "Mike Williams", "pos": "WR", "team": "NYJ"},
    {"espnId": 8, "name": "Mike Williams", "pos": "WR", "team": "PIT"},
    {"espnId": 100, "name": "Vikings D/ST", "pos": "D/ST", "team": "MIN"},
    {"espnId": 101, "name": "Commanders D/ST", "pos": "D/ST", "team": "WSH"},
    {"espnId": 102, "name": "Giants D/ST", "pos": "D/ST", "team": "NYG"},
]


class TestNormalize(unittest.TestCase):
    def test_suffix_punctuation_accents(self):
        self.assertEqual(names.normalize("Kenneth Walker III"), "kenneth walker")
        self.assertEqual(names.normalize("Marvin Harrison Jr."), "marvin harrison")
        self.assertEqual(names.normalize("D.J. Moore"), names.normalize("DJ Moore"))
        self.assertEqual(names.normalize("Ja'Marr Chase"), names.normalize("JaMarr Chase"))
        self.assertEqual(names.normalize("Amon-Ra St. Brown"), "amon ra st brown")
        self.assertEqual(names.normalize("José"), "jose")

    def test_team_abbr_aliases(self):
        self.assertEqual(names.team_abbr("WAS"), "WSH")
        self.assertEqual(names.team_abbr("jac"), "JAX")
        self.assertIsNone(names.team_abbr(""))


class TestDst(unittest.TestCase):
    def test_every_source_format(self):
        for raw in ("MIN", "Minnesota Vikings", "Vikings", "Vikings D/ST",
                    "Minnesota Defense", "minnesota vikings dst"):
            self.assertEqual(names.dst_team(raw), "MIN", raw)
        self.assertEqual(names.dst_team("WAS"), "WSH")
        self.assertEqual(names.dst_team("Washington Commanders"), "WSH")

    def test_ambiguous_city_is_none(self):
        self.assertIsNone(names.dst_team("New York"))
        self.assertEqual(names.dst_team("New York Giants"), "NYG")
        self.assertIsNone(names.dst_team("Not A Team"))


class TestMatcher(unittest.TestCase):
    def setUp(self):
        self.m = names.Matcher(ESPN, aliases={"Ken Walker": "Kenneth Walker"})

    def test_plain_and_suffix(self):
        self.assertEqual(self.m.match("Ja'Marr Chase")["espnId"], 2)
        self.assertEqual(self.m.match("Kenneth Walker")["espnId"], 1)
        self.assertEqual(self.m.match("Marvin Harrison")["espnId"], 4)
        self.assertEqual(self.m.match("DJ Moore")["espnId"], 3)

    def test_alias(self):
        self.assertEqual(self.m.match("Ken Walker")["espnId"], 1)

    def test_default_aliases_survive_config_aliases(self):
        m = names.Matcher([{"espnId": 9, "name": "Adonai Mitchell", "pos": "WR", "team": "NYJ"}],
                          aliases={"Someone": "Else"})
        self.assertEqual(m.match("A.D. Mitchell")["espnId"], 9)

    def test_same_name_disambiguated_by_pos_then_team(self):
        self.assertEqual(self.m.match("Josh Allen", pos="QB")["espnId"], 5)
        self.assertEqual(self.m.match("Mike Williams", pos="WR", team="PIT")["espnId"], 8)
        self.assertIsNone(self.m.match("Mike Williams", pos="WR"))  # still ambiguous

    def test_dst_by_name_or_team(self):
        self.assertEqual(self.m.match("Minnesota Vikings", pos="D")["espnId"], 100)
        self.assertEqual(self.m.match("anything", pos="DST", team="WAS")["espnId"], 101)
        self.assertEqual(self.m.match("Giants", pos="D/ST")["espnId"], 102)

    def test_match_rows_never_drops(self):
        rows = [{"source": "harris", "view": "weekly", "pos": "WR", "name": "Ja'Marr Chase"},
                {"source": "harris", "view": "weekly", "pos": "WR", "name": "Nobody Real"}]
        matched, unmatched = names.match_rows(rows, self.m)
        self.assertEqual([r["espnId"] for r in matched], [2])
        self.assertEqual([r["name"] for r in unmatched], ["Nobody Real"])
        self.assertIn("reason", unmatched[0])
        self.assertEqual(len(matched) + len(unmatched), len(rows))


if __name__ == "__main__":
    unittest.main()
