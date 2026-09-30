# Sidecar — the owner's private waiver and rankings board

A **local-only** admin tool that lives in this repo but is separate from the
public site. It pulls free rankings from the web and FFF's rosters and free
agents from ESPN every time it's opened, and turns them into one board:
waivers at the top, then rankings, then D/ST and K, then advice specific to
the owner's team.

It is **not** part of the static site:
- `build.py`, `docs/`, the bot workflow and the passphrase gate don't know it
  exists;
- nothing it fetches is committed.

Written 2026-09-29. Sources verified live that day (see "Sources").

---

## 1. Hard rules

- **Local only.** Bind to `127.0.0.1`, never `0.0.0.0`. That, and not a
  password, is what keeps it admin-only. No hosting, no GitHub Pages, no
  tunnel.
- **Nothing third-party is committed.** `sidecar/cache/` is gitignored.
  Rankings content must never reach the public repo. Test fixtures (§8) are
  trimmed to a handful of players.
- **Polite fetching.**
  - Only the public pages listed in §3, only when the owner opens or
    refreshes the board, and cached (§4).
  - Honor each site's `robots.txt`. FantasyPros asks for `Crawl-delay: 5`
    and disallows `/ajax/`, `/api/` and `/json/`. Harris disallows
    `?format=json`, so parse its HTML.
  - Use a normal browser-like User-Agent string.
  - Personal use only.
- **No AI at runtime.** Parsing and all ranking math are plain,
  deterministic, tested code. Nothing calls a language or vision model when
  the board loads.
- **Dependencies:** Python stdlib plus `requests`, which is already in
  `requirements.txt`. Parse HTML with the stdlib `html.parser`, no
  BeautifulSoup. The frontend is one HTML page with vanilla JS and its own
  small CSS file, with no build step and no framework (`NOT-BUILDING.md`).
- **Don't touch the site.** No edits to `compute.py`, `build.py`,
  `templates/`, `static/` or `docs/`. Importing read-only helpers from
  `compute.py` (for example `STAT_LABELS`) is fine.

## 2. Layout

```
sidecar/
  SPEC.md            this file
  README.md          how to run it (write it as part of the build)
  server.py          stdlib http.server: serves web/ and a JSON API; 127.0.0.1 only
  config.json        league 877873, season, my teamId (1), cache TTL, thresholds
  sources/
    espn.py          FFF rosters, free agents/waivers, settings, NFL schedule
    ffballers.py     The Fantasy Footballers weekly projections (per analyst)
    harris.py        Harris Football weekly ranks
    fantasypros.py   FantasyPros consensus ranks: ROS, dynasty, weekly K/DST
  names.py           player-name/team normalization + matching to ESPN players
  model.py           pure: scoring, ranks, consensus, tiers, recommendations
  web/index.html, web/app.js, web/app.css
  tests/             unittest + trimmed fixtures
  cache/             gitignored
```

Run it with `python sidecar/server.py`. It prints and opens
`http://127.0.0.1:8765`.

## 3. Sources (verified 2026-09-29)

In every source, `<season>` comes from config and is never hardcoded.

### ESPN (public league, no login)
Base: `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<season>/segments/0/leagues/877873`

- `?view=mRoster&view=mTeam&view=mSettings`: every roster (`teams[].roster.entries[].playerPoolEntry.player`, plus `lineupSlotId`), team names, `status.currentMatchupPeriod`, `settings.rosterSettings.lineupSlotCounts`, and `settings.scoringSettings.scoringItems` (FFF's real scoring).
- `?view=kona_player_info` with the header
  `X-Fantasy-Filter: {"players":{"filterStatus":{"value":["FREEAGENT","WAIVERS"]},"limit":300,"sortPercOwned":{"sortPriority":1,"sortAsc":false}}}`
  returns free agents and waiver players. Each has `status` (FREEAGENT or
  WAIVERS), `player.fullName`, `defaultPositionId`, `proTeamId`,
  `injuryStatus` and `ownership.percentOwned`. Verified: it returned De'Von
  Achane (WAIVERS, IR), Cameron Dicker and others.
- The owner is **teamId 1** ("Walker, Kenneth Ranger"). Put it in
  `config.json`, not in code.

### The Fantasy Footballers (free weekly)
`https://www.thefantasyfootballers.com/<season>-<pos>-rankings/`, where
`<pos>` is `quarterback`, `running-back`, `wide-receiver`, `tight-end`,
`kicker` or `defense`.
- The page embeds JSON rows, one per player **per analyst** (`analyst_name`:
  Andy, Jason, Mike), with projected stats (`passing_yards`,
  `passing_touchdowns`, `interceptions_thrown`, `rushing_yards`,
  `rushing_touchdowns`, `receptions`, `receiving_yards`,
  `receiving_touchdowns`, `fumbles_lost`, …) plus `name`,
  `fantasy_position`, `team`, `bye_week`, `injury_status`, `adp` and `week`.
  There are **no rank fields**; ranks come from projections (§5).
- Each position page seems to contain the offensive positions too, and the
  kicker/defense pages add K and D. Fetch all six anyway, and de-duplicate
  by (player, analyst).
- Find the JSON by locating the array that contains `"analyst_name"`. Parse
  it with `json`, not a regex over individual fields. If the structure
  isn't found, that's a **source failure** (§4), not an empty list.
- The K and D rows use different stat fields. Inspect them. If they can be
  mapped to FFF scoring, do that. Otherwise rank K and D by the page's own
  order, and say which in the UI.
- The rest-of-season, dynasty and waiver rankings are under `/footclan/`,
  the **paid** tier. Don't fetch them.

### Harris Football (free weekly)
`https://www.harrisfootball.com/ranks` (QB), `/rb-ranks`, `/wr-ranks`,
`/te-ranks` and `/def-ranks` (D/ST). There is **no kicker page**
(`/k-ranks` returns 404).
- Plain HTML `<table>` rows: rank, player, opponent (`@ CAR` or `NE`). The RB
  page has two tables, "Standard Scoring" and PPR. **Take the PPR table**,
  found by its heading text, not by table index. Where only one table
  exists, use it.
- The opponent column gives the matchup. The player's own NFL team isn't
  shown, so match names against ESPN (§6).

### FantasyPros consensus (free; for rest-of-season, dynasty, K/DST)
- `https://www.fantasypros.com/nfl/rankings/ros-half-point-ppr-overall.php`:
  rest-of-season (404 players when checked).
- `https://www.fantasypros.com/nfl/rankings/dynasty-overall.php`: dynasty
  (464, including `player_age`).
- Weekly `k.php` and `dst.php` under `/nfl/rankings/`. Confirm the exact
  URLs during the build.
- Each page embeds `var ecrData = {...};` JSON. `players[]` has
  `player_name`, `player_team_id`, `player_position_id`, `rank_ecr`,
  `rank_min`, `rank_max`, `player_bye_week`, `player_owned_avg`, and for
  dynasty `player_age`. Confirm the rank field names from a live page.
- Wait 5 s between FantasyPros requests (crawl-delay).

### Which source feeds which view
| View | Sources the owner can toggle |
|---|---|
| **Weekly** | Harris, Andy, Jason, Mike |
| **Rest of season** | FantasyPros ROS |
| **Dynasty / keeper** | FantasyPros dynasty |
| **K (weekly)** | Andy, Jason, Mike, FantasyPros K |
| **D/ST (weekly)** | Harris, Andy, Jason, Mike, FantasyPros DST |

- Rest of season and dynasty have one free source each. The UI must say so
  ("1 source"), not present it as a consensus.
- Adding a source later should mean adding one module to `sources/` and one
  line in a registry. Design for that.

## 4. Fetching, caching, failure

- **Open:** `GET /api/board` returns the last cached board immediately,
  with each source's `fetchedAt`. If any source is older than the TTL
  (default 60 min, from `config.json`), refresh those sources in a
  background thread. The page polls `GET /api/status` and re-renders when
  they finish. This is stale-while-revalidate, so the board is never blank
  while fetching.
- **Refresh:** `POST /api/refresh` refetches every source now, ignoring the
  TTL, but still respecting FantasyPros' crawl-delay.
- **Cache:** per source, as raw response plus parsed rows plus timestamp,
  under `sidecar/cache/` (write to a temp file, then rename, so a crash
  can't leave a half-written file).
- **Failure:** a source that fails (HTTP error, timeout, or structure not
  found) keeps its last good cache, and the UI shows a warning chip:
  "Harris: layout changed, showing Tue 9:14pm data". One broken source never
  blanks the board. Parser failures must be loud: a page that parses to zero
  players is a failure, not "no rankings this week".
- **Status line** at the top: each source with its age, rows parsed and
  status.

## 5. Model (`model.py`, pure, fully tested)

- **Projected points with FFF's real scoring.** Convert each FFB analyst's
  projected stats to points using `scoringItems` from ESPN `mSettings`.
  Map FFB field → ESPN statId, **verifying every ID against `STAT_LABELS`
  in `compute.py`**; don't trust a list from memory. Items with no FFB
  equivalent are ignored, and the UI notes it once. This means format
  (half vs full PPR) doesn't matter: every projection is scored the way FFF
  scores.
- **Positional ranks per source.** Andy, Jason and Mike: sort by projected
  points within each position. Harris, FantasyPros: use their ranks, made
  positional (FantasyPros overall → rank within position).
- **Consensus** for a view = the mean positional rank across the
  **enabled** sources that rank the player. Also show `n` (how many sources
  ranked them) and **spread** (max − min). A player ranked by fewer than
  half the enabled sources sorts after fully ranked players, so a player
  ranked by one source isn't ranked high by accident.
- **Tiers** within each position: start a new tier where the gap to the
  next consensus rank is well above the position's typical gap. Keep the
  rule simple and documented, and test it with fixed inputs.
- **Movers:** keep one snapshot per ISO week in the cache. Once last week's
  snapshot exists, show the change in consensus rank (↑/↓). The column is
  hidden until then.
- **Ownership:** every player is labeled **free agent**, **waivers** (with
  the ESPN status) or **owned by <team name>**, from the ESPN data.

## 6. Name matching (`names.py`)

- Normalize: lowercase, strip punctuation, collapse whitespace, drop
  suffixes (Jr, Sr, II, III, IV, V), and handle common nickname variants
  through a small alias table in `config.json` (e.g. "Kenneth Walker III",
  "Ken Walker").
- Match against the ESPN player pool from both ESPN calls. Use the NFL team
  as a tiebreaker when a source provides it (FFB `team`, FantasyPros
  `player_team_id`).
- **D/ST:** each source names defenses differently (team name, city,
  "Bills D/ST"). Map every one to an NFL team abbreviation, then to ESPN's
  D/ST entry.
- **Unmatched names are never dropped silently.** List them in a
  collapsible "Unmatched (N)" panel with the source and raw name, so the
  alias table can be extended. Show a test failure if a fixture name
  doesn't match.

## 7. The page, in this order

The owner's rule: general information first, advice for his team last.

1. **Header:** view switcher (Weekly · Rest of season · Dynasty), the source
   toggles for the current view (checkboxes; all on by default; saved in
   `localStorage`), the status line (§4), and a Refresh button.
2. **Waiver wire:** only free agents and waiver players in FFF.
   - Sorted by consensus for the current view. Position filter chips (All,
     QB, RB, WR, TE, FLEX).
   - Columns: player, position, NFL team, bye, injury, % owned, FA/waivers,
     consensus, each enabled source's rank, spread, tier and movers.
   - Default view: **Rest of season** (pickups are about the rest of the
     year), and Weekly is one click away.
   - Highlight players whose consensus beats someone on the owner's roster
     at the same position.
3. **Rankings:** the full table for the view, every player, with the same
   columns plus "owned by", so it's the general-purpose board. The source
   toggles re-rank it live in the browser from the per-source ranks the API
   returns. Sortable, and searchable by name.
4. **D/ST and K:** two compact weekly tables with their own toggles
   (sources in §3), marking which are available. Streaming line: "Best
   available D/ST this week: X (consensus N) vs yours: Y (N)."
5. **My team** (teamId 1), last:
   - **Roster:** every player with weekly, ROS and dynasty consensus, and
     lineup slot, injury and bye.
   - **Upgrade suggestions:** "Add X, drop Y". Pair a free agent with the
     owner's worst player at the same position when the FA's ROS consensus
     is at least `upgradeMargin` positional spots better (default 5, in
     `config.json`). Never suggest a drop that would leave fewer players at
     a position than `lineupSlotCounts` requires to start, and skip players
     in the IR slot. Show the numbers behind each suggestion.
   - **Drop candidates:** the owner's bench players ranked worst relative to
     the best free agent at their position (ROS). Listed, not automatic.
   - **Keeper targets:** the owner's roster sorted by dynasty consensus, and
     the best free agents by dynasty rank, marked as "dynasty: 1 source".
     FFF keeper pricing isn't in ESPN; showing costs is out of scope for v1.
   - **Bye-week check:** positions where the owner's starters share a bye in
     the next three weeks.

**Look:** dark by default, dense and readable tables, sticky table headers,
works at 1440 and on a phone at 390 (tables scroll inside their container,
not the page). Use the site as a loose style reference, but with its own
CSS.

## 8. Tests (`python -m unittest discover sidecar/tests`)

- **Fixtures:** one trimmed saved page per source (FFB JSON with about 6
  players across 2 analysts; Harris RB with both tables and about 6 rows;
  FantasyPros `ecrData` with about 6 players; ESPN FA and roster JSON with a
  few players). Trim each to the minimum needed to test the parser.
- **Parsers:** correct rows from each fixture; the Harris PPR table is
  chosen over Standard; a page with the structure missing raises a
  source-failure error, not an empty list.
- **Scoring:** a hand-computed projected-points example against a fixture
  `scoringItems`.
- **Model:** consensus with sources toggled; spread; the "fewer than half"
  sort rule; tiers on fixed inputs; upgrade suggestions respecting
  `upgradeMargin`, starting-slot minimums and IR; bye-week check.
- **Names:** suffix and punctuation cases, an alias, a D/ST from each
  source's format, and an unmatched name that lands in the unmatched list.

## 9. Done when

- Tests pass. `python sidecar/server.py` starts, binds only to
  `127.0.0.1`, and the board renders with live data from all four sources
  plus ESPN.
- Blocking one source (point its URL at a 404 in config) shows its warning
  chip, keeps the others working, and serves its last cache.
- `git status` shows no files under `sidecar/cache/`, and nothing
  third-party is committed beyond the trimmed fixtures.
- The owner gets screenshots of each section at 1440 and 390, and a list of
  unmatched names from a live run, if any.
- The site is untouched: `python build.py --check` passes if ENH-019 has
  shipped, or else `git diff --stat docs/ templates/ static/ compute.py
  build.py` is empty.

## 10. Later (not v1)

FAAB bid suggestions; the other four leagues (private, so they need ESPN
cookies); keeper-cost math from FFF's rules; more sources through the
`sources/` registry; trade suggestions.
