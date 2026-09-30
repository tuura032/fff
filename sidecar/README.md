# Sidecar

The owner's private, local-only waiver and rankings board for FFF. It's
separate from the public site in this repo. `SPEC.md` is the full spec;
`COORDINATION.md` records the build-time file split.

**Run it**

```
python sidecar/server.py          # http://127.0.0.1:8765
python sidecar/server.py --check  # fetch every source once, print, exit
python -m unittest discover sidecar/tests    # 60 tests
```

Binds `127.0.0.1` only. The board loads from `cache/*.json` instantly;
stale sources (older than `cacheTtlMinutes`, default 60) re-fetch in the
background — stale-while-revalidate, so the board is never blank.

**Views** (tabs in `web/`)

- **Waivers** — ESPN free agents + waivers, sorted by % owned. No rank
  columns yet (SPEC.md §7 wants consensus/source/tier columns here).
- **Rankings** — weekly / rest-of-season / dynasty. The server returns
  per-source *positional* ranks; the browser re-runs consensus, order,
  and tiers when you toggle sources, so toggling is instant. Weekly shows
  a Δ (movers) column once a snapshot from an earlier ISO week exists:
  one `cache/snapshot-weekly-<season>-<YYYY-Www>.json` per week.
- **K & D/ST** — the rankings table filtered to kickers and defenses;
  FantasyPros supplies this week's opponent. FFB K/D rows carry
  per-analyst page ranks (those pages have no projections).
- **My Team** — the owner's roster (config `myTeamId`), starter/bench
  vs the wire (upgrade/drop recommendations at `upgradeMargin`), and
  upcoming byes.
- **Look back** — *Since the draft*: pre-draft consensus (Harris + FFB)
  vs today's ROS consensus — risers, fallers, new, off the board —
  filterable by position and roster. *Week N*: each source's ranks for a
  played week vs actual FFF points (top-k hits, rank correlation, avg
  miss) plus a per-player drilldown. Math in `analysis.py` (tested).

**Sources** (`sources/`): ESPN (rosters + FA/WAIVERS pull with limit 1500,
plus `proTeamSchedules_wl` from the seasons endpoint for byes),
FantasyFootballers (Andy/Jason/Mike weekly pages), Harris Football (PPR
tables), FantasyPros (ROS/dynasty/K/D-embeds), and `history`: the
pre-draft and past-week ranks read from the owner's draft-assistant repo
(config `history.dir`: `app/data/rankings.json`, `rankings/week-<n>.json`)
plus one ESPN request for every player's weekly actuals. Each module's
`parse` is pure and fixture-tested in `tests/`.

**API**: `GET /api/status` (per-source freshness: fresh/stale/refreshing/
failed/never), `GET /api/board` (assembled board + `weekInfo`),
`POST /api/refresh` (`{"source": name}` or `{}` for all). A failed
refresh keeps serving the cache and marks the chip `failed` with the
error as a tooltip.

**Config** (`config.json`): league/season/team ids, TTL, URLs, and
`aliases` (extra name-matching on top of `names.DEFAULT_ALIASES`).
`cache/` is gitignored — never commit it; third-party rankings in
particular stay local.
