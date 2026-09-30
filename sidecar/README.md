# Sidecar

The owner's private, local-only waiver and rankings board for FFF. It's
separate from the public site in this repo. `SPEC.md` is the full spec;
`COORDINATION.md` records the build-time file split.

**Run it**

```
python sidecar/server.py          # http://127.0.0.1:8765
python sidecar/server.py --check  # fetch every source once, print, exit
python -m unittest discover sidecar/tests    # 43 tests
```

Binds `127.0.0.1` only. The board loads from `cache/*.json` instantly;
stale sources (older than `cacheTtlMinutes`, default 60) re-fetch in the
background — stale-while-revalidate, so the board is never blank.

**Views** (tabs in `web/`)

- **Waivers** — ESPN free agents + waivers, sorted by % owned, with
  consensus rank when a rank source covers them.
- **Rankings** — weekly / rest-of-season / dynasty. The server returns
  per-source *positional* ranks; the browser re-runs consensus, order,
  and tiers when you toggle sources, so toggling is instant.
- **K & D/ST** — the rankings table filtered to kickers and defenses;
  FantasyPros supplies this week's opponent. FFB K/D rows carry
  per-analyst page ranks (those pages have no projections).
- **My Team** — the owner's roster (config `myTeamId`), starter/bench
  vs the wire (upgrade/drop recommendations at `upgradeMargin`), and
  upcoming byes.

**Sources** (`sources/`): ESPN (rosters + FA/WAIVERS pull with limit 1500,
plus `proTeamSchedules_wl` from the seasons endpoint for byes),
FantasyFootballers (Andy/Jason/Mike weekly pages), Harris Football (PPR
tables), FantasyPros (ROS/dynasty/K/D-embeds). Each module's `parse` is
pure and fixture-tested in `tests/`.

**API**: `GET /api/status` (per-source freshness: fresh/stale/refreshing/
failed/never), `GET /api/board` (assembled board + `weekInfo`),
`POST /api/refresh` (`{"source": name}` or `{}` for all). A failed
refresh keeps serving the cache and marks the chip `failed` with the
error as a tooltip.

**Config** (`config.json`): league/season/team ids, TTL, URLs, and
`aliases` (extra name-matching on top of `names.DEFAULT_ALIASES`).
`cache/` is gitignored — never commit it; third-party rankings in
particular stay local.
