# ENH-037 — Sidecar: Keepers tab (trade targets, with keeper prices)

Status: done 2026-10-16 · Category: content & features

Scope: `sidecar/` only. The public site is untouched. Builds on ENH-036 (the
merged Board: position chips, Show control, WA/FA badges, sortable tables,
column picker).

## Problem

The owner wants to trade for players who are cheap to keep and could be top-20
at their position (rookies and second-years are common targets, but any player
is fair at the right price). Nothing in the sidecar knows keeper prices, because
FFF's pricing isn't in ESPN's settings. So the owner can see who is good but
not what they cost to keep, and can't tell which players on other teams, or in
the free-agent pool, are worth a trade offer.

## The rules (owner-confirmed; do not re-litigate)

- Each team keeps up to `keeperCount` (2) players into the next season.
- **A keeper's price = last auction price + a yearly increment.** The
  increment depends on how many consecutive years he has already been kept.
- **UDFA** (not drafted in the most recent auction) has a base of **$5**.
- Worked examples from the owner: drafted at $1 → 1 + 7 = **$8** to keep;
  UDFA → 5 + 7 = **$12**.
- Price follows the player, so a trade changes nothing.
- The tab shows the price to keep **next season** (the 2027 price during the
  2026 season). The 2026 price is already spent.

The yearly increment, by number of consecutive keeper years already used:

| Keeps already used | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| Increment | +$7 | +$10 | +$12 | +$15 |

The league page (`templates/league.html`) lists only the first three tiers.
The **+$15 fourth tier was found in the draft data**: player 4241389 went
$1 → 8 → 18 → 30 → 45 from 2020–24. There is no data for a fifth year. For
four or more used keeper years, apply +$15 and mark the price **estimated**
(show a `~`). Do not edit the public site page; note it in the Shipped
paragraph so the owner can decide.

## Data: ESPN's draft history

`GET {espn base}?view=mDraftDetail` returns `draftDetail.picks[]`. Each pick has
`playerId`, `teamId`, `bidAmount` (auction price) and `keeper` (true if the
pick was a keeper). It works unauthenticated for FFF, for every season from
2019. (2018 is a different format; start at 2019, which is also where
`data/raw-<season>.json` begins.) `playerId` is the same ESPN id the board
already matches on (`espnId`).

- New source module (e.g. `sidecar/sources/drafts.py`), registered like the
  others, with `rows: []` (it is not a rank source).
- **Cache each past season permanently.** A finished draft never changes, so
  fetch once and keep `sidecar/cache/draft-<season>.json`. Re-fetch only the
  current season, on the normal refresh. Failures follow SPEC §3 (keep the last
  good cache, show the warning chip).
- Do **not** use ESPN's own `keeperValue` / `keeperValueFuture` fields on the
  roster and player entries. They are mostly 0/1/2 and do not follow the
  league's rules.

### The price function (pure, in `sidecar/model.py`, unit-tested)

Given a player's picks by season (`{season: {bidAmount, keeper}}`) and the
current season `S`:

1. If the player has **no pick in season `S`'s draft**: base = **5**, keeps
   used = 0 (UDFA).
2. Else base = that pick's `bidAmount`. Keeps used `k` = the number of
   consecutive seasons ending at `S` in which his pick has `keeper: true`
   (0 if the `S` pick is a normal auction buy, so a re-buy at auction resets
   the chain).
3. Next-season price = base + `increments[min(k, 3)]`. If `k >= 4`, mark
   `estimated`. If the chain runs back to the earliest season fetched
   (2019), `k` is only a lower bound, so mark `estimated` there too.

Config: add to `sidecar/config.json`:
`"keepers": {"udfaBase": 5, "increments": [7, 10, 12, 15], "overrides": {}}`.
`overrides` maps an espnId to a fixed next-season price, for the cases where the
commissioner entered something unusual (see backtest). An override replaces the
computed price and is shown with a `*`.

Unit-test vectors (all real FFF players):

| Picks (season: $ / kept?) | Season | Expected next price |
| --- | --- | --- |
| no 2026 pick | 2026 | 12 (UDFA 5 + 7) |
| 2026: $1 auction | 2026 | 8 |
| 2025: $1 auction; 2026: $8 kept | 2026 | 18 |
| 2023: $22; 2024: $29 kept; 2025: $39 kept; 2026: $51 kept | 2026 | 66 (k = 3, +15) |
| 2023: $10 kept; 2024: $40 auction; 2025: $27 auction; 2026: $34 kept | 2026 | 44 (k = 1: the chain resets at the 2024 re-buy) |
| 2021: 1, 8, 18, 30, 45 (all kept after the first) | 2024 | 45 + 15 = 60, `estimated` (k = 4) |

### Backtest (owner can't see this; the builder must run it)

The rule was backtested against ESPN's recorded keeper prices: for every
keeper pick in season S with prior history, compute the price from the prior
seasons and compare it to the recorded `bidAmount`. Results:

- **2024–2026: 50 of 53 match** (2024 19/19, 2025 14/16, 2026 17/18).
- The three misses look like commissioner-entered exceptions: espnId
  `4426502` (2025, recorded 25, rule says 28), `4596448` (2025, recorded 22,
  rule says 12, no prior pick) and `4372016` (2026, recorded 8, rule says 15).
- **Before 2024 the increments were different** (+5 / +8 / +9 in 2021–23, and
  some prices didn't move). Don't backtest or extend the rule before 2024.

Done-when includes re-running this backtest in a test (against a trimmed
fixture, not live ESPN) and reporting the match count. The same 3 misses are
expected; any other miss means the function is wrong.

## Design: the Keepers tab

Nav becomes **Board · Keepers · K & D/ST · My Team · Look back**.

One table, every player in the league pool: mine, other teams', free agents and
waiver players. The point is to find trade targets, so other teams' players
are first-class rows.

Columns: **Rk** (dynasty position rank, e.g. WR28) · **Player** (+ injury tag)
· **Pos** · **Team** · **Owner** (`mine`, a team abbreviation, or an FA/WA
badge, same styling as the Board) · **Draft** (last auction history: `2026
auction $12`, `2026 kept $8 (yr 1)`, or `UDFA`) · **Used** (keeper years used)
· **Keep price** (next season; bold; `~` estimated, `*` override) · **Dyn**
(dynasty consensus rank within position) · **ROS** (rest-of-season rank
within position) · **Owned %**.

Controls:

| Control | Values | Default |
| --- | --- | --- |
| Position chips | QB / RB / WR / TE (no K / D/ST) | All four |
| Show | All / On other teams / Free agents & waivers / Mine | On other teams |
| **Top N at position** (checkbox + number) | filters on dynasty position rank ≤ N | on, N = 20 |
| **Max keep price** (number, $) | blank = no limit | blank |
| Search | name | empty |

- Default sort: **keep price ascending**, ties by dynasty rank. With the top-20
  filter on, the top of the list is the cheapest players with top-20 upside:
  the trade-target list the owner asked for.
- Header clicks sort any column, using the existing `sortTable`.
- "Top N" uses the Dynasty position rank the Board's Dynasty view already
  computes. A player with no dynasty rank is excluded while the filter is on
  and shows `–` otherwise.
- Players I own are visually highlighted, so a comparison like Lemon vs a
  target is one glance. Show → Mine lists only my roster, which doubles as
  the owner's "who would I keep" view (a small "N of 2 keepers" count is
  welcome but not required).
- A tooltip on **Keep price** states the formula and the tier table; a
  tooltip on `~` says "estimated: fourth+ keeper year or the chain is cut off
  at 2019".

## Not this item

- Trade suggestions, value-over-price scoring, or a "best trade" ranker.
  Facts and filters only.
- Rookie / second-year labels. ESPN's player payload has no rookie, draft-year
  or experience field (checked `kona_player_info`), so don't scrape for one.
  The owner can already filter by dynasty rank and price.
- Editing the public League Info page (+$15 tier) or the keeper rule text.
- Roster-aware logic: bye-week cover, add/drop pairs, "better than my starter."
  That's the later "Moves" item.

## Files

- `sidecar/sources/drafts.py` (new), registered in the source registry
- `sidecar/model.py`: the pure price function
- `sidecar/server.py`: additive only; each player in the API gains a
  `keep` object (`{price, base, kind, used, estimated, override}`); no
  existing field changes
- `sidecar/config.json`: the `keepers` block above
- `sidecar/web/index.html`, `app.js`, `app.css`: the Keepers tab
- `sidecar/tests/`: price-function vectors, the backtest on a fixture, a
  source-parse test
- `sidecar/SPEC.md`: a short Keepers section (§7 layout; the "out of scope
  for v1" notes about keeper costs are now obsolete, so update them)
- `enhancements/README.md`: add this item to "Next up"; move this file to
  `done/` with a Shipped note when finished

## Done when

- `node --check sidecar/web/app.js` is clean and
  `python -m unittest discover sidecar/tests` is green, including every vector
  in the table above and the backtest (50/53 on the trimmed fixture; the three
  misses named above).
- Live server, Playwright at 1440 and 390, dark theme:
  - Default load shows the Keepers tab with other teams' players, top-20
    dynasty filter on, sorted by keep price ascending.
  - Toggling Show to Free agents & waivers, Mine and All changes the set
    correctly; Max price and Top N filters work; Top N off shows players with
    no dynasty rank.
  - A player drafted at $1 and still rostered shows 8; a UDFA shows 12; a
    player kept three times shows the +$15 price with no `~`; one kept four
    or more times shows `~`.
  - Board, K & D/ST, My Team and Look back still work.
- `git diff --stat` shows changes only under `sidecar/` and `enhancements/`.
- The Shipped note reports the backtest result, whether the 2018 season was
  skipped, and the +$15 tier (so the owner can update the league page).

## Shipped (2026-10-16)

Built as specced: the **Keepers** tab (between Board and K & D/ST);
`sources/drafts.py` (one `mDraftDetail` request per season, 2019–current;
finished seasons cached permanently as `cache/draft-<year>.json`, the current
season re-fetched on the normal refresh, failures keep the last good cache);
the pure `model.keeper_price()` + `keeper_backtest()`; an additive `keep`
object (`{price, base, kind, used, estimated, override}`) on **every** board
player in the API; the `keepers` block in `config.json` (`udfaBase`,
`increments`, `overrides`); and the UI — position chips, Show (default: other
teams), Top N (on, 20), Max keep price, search, click-sort headers,
my-player highlight, formula/`~` tooltips.

Backtest on the trimmed fixture (`tests/fixtures/draft_backtest.json`,
2019–2026 history): **50/53** across 2024–2026 (19/19, 14/16, 17/18). The
three misses are commissioner-entered exceptions, not rule drift — recorded
vs rule: 4426502 ($25 vs $28), 4596448 ($22 vs $12), 4372016 ($8 vs $15).
They are the candidates for `keepers.overrides`. 2018 was skipped (different
ESPN format, per spec). The **+$15 fourth tier is confirmed in real data**
(player 4241389: $1 → 8 → 18 → 30 → 45, 2020–24); the public League Info
page still lists only three tiers and was left untouched per spec — the owner
may update it. No `~` estimated rows exist in the current live pool (no chain
runs that long and none is cut off at 2019); the estimated path is covered by
unit tests.

Two real bugs surfaced while wiring it up and were fixed: cached draft files
store player ids as strings while live parsing emits ints (the per-player
index now normalizes to int), and keep prices were initially attached only to
players present in the draft history (now every board player gets one; a
player with no pick in the current season gets the $5 UDFA base → $12).

Verified: 81 sidecar tests green; `node --check sidecar/web/app.js` clean;
Playwright, dark theme, at 1440 and 390 — 22/22 checks (default view, all
Show toggles, Top N off showing unranked players, Max price, search, header
sort, my highlight, and regression on every other tab); `git diff --stat`
limited to `sidecar/` and `enhancements/`.
