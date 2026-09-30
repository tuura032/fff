# Sidecar build — who's doing what (2026-09-29)

Two agents are building this at once. Please don't edit the other one's
files. If you need a change there, add a line to "Requests" below.

| Owner | Files |
|---|---|
| **Cline** | `sources/*`, `server.py`, `web/*`, `config.json`, `README.md`, source fixtures + source tests |
| **Claude (Opus)** | `names.py`, `model.py`, `tests/test_names.py`, `tests/test_model.py` |

## The format `model.py` / `names.py` expect

Import them as top-level modules (`import model, names`). `server.py` runs
from `sidecar/`, so it's already on `sys.path`, and the tests add it
themselves.

**ESPN player** (built by `sources/espn.py`), one dict per player, from both
the rosters and the free-agent call:
```
{"espnId": int, "name": str, "pos": "QB"|"RB"|"WR"|"TE"|"K"|"D/ST",
 "team": "MIN",            # NFL abbr; model.PRO_TEAMS maps ESPN proTeamId
 "status": "FA"|"WAIVERS"|"OWNED", "ownerTeamId": int|None,
 "lineupSlotId": int|None, "injury": str|None, "bye": int|None,
 "pctOwned": float}
```
Use `model.espn_pos(defaultPositionId)` for `pos`.

**Source row** (built by each `sources/*.py`), one per player per source per
view:
```
{"source": "harris"|"ffb-andy"|"ffb-jason"|"ffb-mike"|"fp",
 "view": "weekly"|"ros"|"dynasty",
 "pos": "QB"|"RB"|"WR"|"TE"|"K"|"D/ST",     # normalize D, DST, DEF -> "D/ST"
 "name": str, "team": str|None,             # team when the source gives it
 "rank": int|None,                          # the source's rank: overall or positional, either is fine
 "stats": dict|None}                        # FFB only: the raw projected-stat fields
```
Each row needs `rank` or `stats`. FFB rows with `stats` get points from
`model.project_points(stats, model.points_by_stat(scoringItems))`. FFB K and
D rows, which carry `rank`, can pass `rank` instead.

**Pipeline** (for `server.py`):
```
matcher = names.Matcher(espn_players, aliases=config["aliases"])
matched, unmatched = names.match_rows(rows, matcher)   # adds "espnId"; unmatched -> UI panel
ranks = model.positional_ranks(matched, points_by_stat)  # {view: {source: {espnId: posRank}}}
board = model.consensus(ranks["ros"], enabled=["fp"])    # the browser re-runs this on toggle
```
`model.consensus` is simple enough to mirror in `web/app.js`. The API should
return the per-source positional ranks so the toggles work client-side.

## Requests
(add lines here)

- **Claude → Cline (`sources/espn.py`):** use a free-agent `limit` of at
  least **1500** in the `kona_player_info` filter. With `limit: 600`, some
  waiver players were missing (Adonai Mitchell, WAIVERS, wasn't returned),
  so the matcher couldn't find them. A 1500 pull returned 1,050 players.
- **FYI, live matching check (2026-09-29):** the current Harris pages
  (QB/RB/WR/TE/DEF, 289 rows) against the ESPN rosters plus free agents
  matched 285/289, including all 32 defenses. The two misses were
  nicknames ("Kenneth Gainwell" → "Kenny Gainwell", "A.D. Mitchell" →
  "Adonai Mitchell"), now built into `names.DEFAULT_ALIASES`. `config.json`
  `"aliases"` adds to these.
- **FYI (`model.py`):** FFF has no dedicated TE slot (slot 5 is WR/TE, 23
  is FLEX RB/WR/TE). `model.can_fill_lineup` handles that; please pass the
  raw `lineupSlotCounts` from mSettings unchanged.
