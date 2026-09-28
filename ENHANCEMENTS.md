# Enhancements

The live backlog. Newest last within each section. See `AGENTS.md` for the
working protocol. Superseded `ROADMAP.md` and `BENCH_POINTS.md` — their still
-open findings are folded in below (2026-09-23); the rest is git history.

**Format:** id, description, why it's easy (data already on hand, if true),
status.

---

## Open — content & features

- **ENH-003** — Matchup visualizer: per-week box-score cards (two teams,
  scores, a bar, W/L + top-half badges). Pairs with ENH-004.
- **ENH-004** — Weekly recap: auto-generated, deterministic (not AI) recap —
  top scorer, biggest upset, score to beat, who got unlucky/backed in. Fully
  computable from `weeks[]`, already stored.
- **ENH-006** — Team logos + abbreviations — `teams[].logo` and
  `teams[].abbrev` are already in every raw file, unused.
- **ENH-007** — Owner profile pages (`/owner/<name>`) — career arc,
  best/worst weeks, full H2H list. Career Stats covers the aggregate half;
  the "Owners" sidebar accordion currently expands to a dead end with no
  pages to link to — build this or cut the accordion.
- **ENH-008** — Championship / playoff-odds simulator. Wants more of the
  season played out first; biggest remaining payoff on the list.
- **ENH-009** — Small free wins already sitting in `mTeam`/`mSettings`, no
  new fetch: `transactionCounter` → "Most Active Manager" / FAAB-spent
  awards; `draftDayProjectedRank` vs `currentProjectedRank` → riser/bust;
  `teams[].eliminated` → an "eliminated" badge.
- **ENH-010** — Records book / power rankings / head-to-head compare view —
  lower priority than ENH-003/004, same "content, not scaffolding" bucket.
- **ENH-011** — Rank-movement arrows using git history (diff this week's
  `standings-<season>.json` against last week's commit). Cheap, high
  perceived-liveness.
- **ENH-012** — Lineup-level data: literal bench points, optimal-lineup
  regret. **Half-unblocked 2026-09-24 by ENH-024** — started lineups are now
  on disk (`data/starters-<season>.json`, every position, 2019–present) via
  `mBoxscore`, not `mRoster`. What is still missing is the *bench*: the
  starters file deliberately stores only who played. Bench points and
  optimal-lineup regret need `rosterForCurrentScoringPeriod` kept too, which
  is the same requests and a bigger file — a decision, not a blocker.
- **ENH-021** — Announcements section (owner idea, 2026-09-23): a place for
  league announcements so the site has more of a "home page" feel. Placement
  is open — home page or wherever makes sense. Checking the standings is the
  main use case, so this must not push the standings out of the way.
- **ENH-022** — League feed (owner idea, 2026-09-23): a feed of league
  chatter — user comments, plus the ability to create polls (e.g. "should we
  switch to 2QB or superflex?") that members can vote on. Open question,
  unsolved: this is user-generated content and the static-site + daily-git-
  commit strategy has no way to persist comments or votes. If it can't be
  done cleanly, the fallback is the existing Facebook group and this item
  stays open/closed as "not here."
- **ENH-023** — Luck vs. skill index (owner idea, 2026-09-23). Replace the
  current `luckIndex` (h2h − topHalf = "lucky wins − unlucky losses") with a
  skill/luck split on the all-play record (`all_play_records`, already
  computed): **skill** = all-play win rate (scoring vs. the whole league,
  schedule removed); **luck** = actual wins − (all-play rate × games) = net
  wins of schedule/matching luck. Verified 2021–24: the luck spread is 3–6
  wins and tells real stories (2024: 2nd-best all-play scorer finished 5-9 on
  a brutal draw). Flavor stats: close-game win % (<10-pt games) and
  home-run-minus-bomb (weekly top scorer minus weekly last).
  - Owner's alt data point: scoring vs. **league average** (easy — we have
    `averageScore`). Logged as a candidate "skill" proxy.
  - **Caveat (don't over-claim):** with team-level weekly scores we can't
    separate *skill* from *roster luck* — a great waiver-wire haul or drafting
    a breakout RB1 inflates scoring without "skill." So all-play rate and
    league-average scoring are proxies for "underlying scoring," not pure
    skill. The split cleanly separates *schedule* luck, not skill from roster
    luck.
  - Pythagorean/margin luck is **degenerate here**: in H2H the higher scorer
    always wins (0 exceptions in 2024), so there's no "outscored but lost."
- **ENH-025** — Team pages + data freshness + a few missing stats (owner
  idea, 2026-09-28). Came from comparing this site with two one-shot local-
  LLM builds of the same idea (`D:\Workspace\ff-scoring-app-*`). Both had a
  page for each team, a "data as of / refresh" indicator and a couple of
  stats we don't. The owner rates team pages as the big miss. Build in this
  order and stop after any part if the session runs long: **A** is the core
  deliverable, **B** and **C** are smaller.

  **A. One page per team per season** (the big one).
  - Output: `team-<teamId>.html` next to each season's other pages, i.e.
    `docs/team-<id>.html` for the newest season and
    `docs/<season>/team-<id>.html` for older ones — reuse `build.py`'s
    existing season loop, don't invent a new layout. Deterministic output, as
    always.
  - Link to it from every team/owner name in the standings table on Home.
    Also link names on the other per-season pages (Playoffs, the season Stats
    page) wherever a teamId is on hand, and apply this to *every* table that
    shows team names, not just the first one you edit.
  - Header: team name, owner, and stat tiles for dual rank, dual points
    (h2h + top-half split), record, points for/against, average, and
    all-play %. Every value already exists in `standings[]` or the Stats page
    data.
  - **Weekly chart** (Chart.js — the site loads **2.7.1** from the CDN in
    `layout.html`, so use the 2.x config API; v3/v4 syntax silently renders
    nothing). One bar per regular-season week for the team's score, colored
    win vs. loss, plus a line for that week's `scoreToBeat` (already in
    `weeks[]`) so the top-half cutoff is visible. Point markers only, with no
    curve smoothing (`lineTension: 0`), because the values are discrete. Use
    the same theme-aware color approach as `graph.html` (the hidden swatch
    trick in `layout.html`) so it works in dark mode.
  - **Dual-points strip**: one small chip per week showing 2 / 1 / 0, with a
    tooltip or legend for what earned it (W, top half). Reads a whole season
    at a glance.
  - **Schedule table**: week, opponent (linked to their team page), score,
    opponent score, W/L, top-half ✓, dual points that week. Regular season
    only, since dual points only count there. Playoff/consolation games
    (`postseason[]`, with `tier`) go in a separate small "Postseason" table
    below, clearly labeled and not counted.
  - **Head-to-head this season** vs. every other team: W-L, PF/PA, margin.
    Link to Rivalries for all-time H2H — don't duplicate it.
  - Mobile: no horizontal page scroll at 390px wide. Tables may scroll
    inside their own container, not the page.
  - Relationship to ENH-007: this is the per-*season* team view. ENH-007
    (cross-season owner profiles) stays open and can link to these pages
    later. Don't build ENH-007 here.

  **B. Data freshness, in a static site's terms.**
  - A small "Data through week N · updated <date>" line on Home (this is
    ENH-015; close it when done). Render the absolute date from `updated` in
    the HTML, and let a few lines of JS turn it into a relative "2 hours ago"
    in the browser. The HTML stays deterministic; only the viewer's clock
    changes what's shown.
  - **Watch out:** `compute.py` stamps `updated` with *now* on every run, so
    rendering it as-is makes `docs/` change every morning even when no score
    changed. Fix that in `compute.py`: if the rest of the new standings dict
    equals the existing file's (ignoring `updated`), keep the old `updated`.
    Add a test for it in `test_compute.py`.
  - "Refresh": there's no server to refetch from, but the bot's workflow
    already has `workflow_dispatch`. Add a small, low-key footer link, "Run an
    update now ↗", pointing at
    `https://github.com/tuura032/fff/actions/workflows/update-standings.yml`.
    It only works for repo writers, so say so in the link's title text. No
    live-fetch button, no client-side ESPN calls: CORS blocks them, and it
    would break the static model.

  **C. Missing stats for the season Stats page (`graph.html`).**
  - Add to the Advanced stats table, computed in `compute.py` with tests:
    - **Pts in losses**: total points scored in losses (the "unluckiest team"
      stat).
    - **Heartbreaks**: losses by under 5 points.
    - **Blowouts**: wins by 50+.
  - Keep full decimals (never `| int`), regular season only, from `weeks[]`.
  - Already covered, don't re-add: best score in a loss, closest game,
    biggest blowout, shootout, and top-half-but-lost ("Robbed").

  Done when: `python -m unittest test_compute -v` passes; `python tasks.py
  all` (or compute + build) runs clean; a second `build.py` run changes
  nothing in `docs/`; and a Playwright check of Home, a team page and the
  Stats page in light/dark and desktop/mobile shows no console errors and no
  horizontal page scroll. Rebuild and commit `data/` + `docs/` locally, on
  `dev`.

## Open — polish & UX

- **ENH-013** — Favicon/branding refresh — `static/fffIcon.png` is still the
  2018 placeholder.
- **ENH-014** — OG/social meta tags + a preview image — the link gets pasted
  into the league chat weekly and unfurls as a bare URL.
- **ENH-015** — "Last updated" stamp — `standings-<season>.json` carries
  `updated`; no template renders it. Folded into ENH-025 part B.
- **ENH-016** — Mobile pass 2: fade/scroll affordance on tables that overflow
  right, sticky table headers, rivalry matrix rethink for mobile (pick an
  owner → ranked list of their H2H records, not a 12×12 grid), consistent nav
  labels between desktop and mobile ("Stats" vs "Careers" vs full names).
- **ENH-017** — Accessibility: wrap sort `<th>` labels in a `<button>` so
  they're keyboard-reachable; add a non-color cue to the red/green H2H/rivalry
  heatmaps; give the pinned-row click target a `role` and focus style.
- **ENH-018** — Vendor/pin Chart.js and upgrade off 2.7.1 (currently 9 years
  old, loaded on every page though only `graph.html` uses it).

## Open — quality of life / dev experience

- **ENH-019** — `build.py --check` mode: fail if `docs/` would change on a
  clean rebuild. Catches template/data drift early.

## Open — multi-league

The app is a handful of hardcoded constants away from supporting more than
one league — most of the values it needs are already in the fetched JSON:

- League ID (`fetch.py`/`compute.py`) and the literal league name (9
  templates) → config + `mSettings.settings.name` (already fetched, just
  unused for this).
- `docs/<league>/<season>/` layout + a league picker next to the season
  picker.
- A `leagues.yml` mapping league ID → display config, looped the same way
  seasons already are (L9 pattern, one level up).

Sequence this last — it's real work but lower payoff than the content/UX
items above, and every piece unblocking it (playoff-count-from-settings, no
more 12-team hardcoding) is already done.

## Explicitly not building

From the 2026-09-22 outside consult — recorded so it doesn't get
re-litigated: a database (see `SPEC.md` §6), a JS framework, user
accounts/login, live in-game scoring, ESPN-beating projections, or unit tests
for template rendering (the screenshot baseline is the right tool for that).

---

## Done

- **ENH-024** — All-time kicker rankings (owner idea, 2026-09-24) — done
  2026-09-24. New "Kickers" page: every kicker ever started in the league
  ranked by points contributed, the same cut by owner, each season's leading
  leg, and nine fixed-rule joke awards. Required a new data artifact —
  `fetch.py --starters` walks ESPN's `mBoxscore` one week at a time into
  `data/starters-<season>.json` (every started player, all positions, not
  just kickers). Verified: all 1,176 team-weeks of started points reconcile
  exactly with the scores already in `standings-*.json`; 41 new tests.

- **ENH-001** — Historical / multi-season data — done 2026-09-22 (L9).
  Archive now covers 2019–2026; newest season with data is the site root.
- **ENH-002** — Season picker (dropdown to select league year) — done
  2026-09-22 (L9). Picker macro in `templates/layout.html`; options keep the
  current page and are built off `root_season` (BUG-008).
- **ENH-020** — Stat help bubbles + mobile column visibility — done
  2026-09-23. "?" bubbles beside Home/Playoffs stat headers explain each
  stat (hover on desktop, tap/keyboard on mobile); H2H Wins and Top Six
  Finishes no longer hidden on small screens; Playoffs "Week N" renamed
  "Most Recent". The tip is a JS-positioned floating div clamped to the
  viewport — a pure-CSS ::after tip clipped at the table's overflow
  container edge on phones.
- **ENH-005** — League Info page — done 2026-09-23. New "League Info" tab
  answers the recurring questions (roster, scoring, draft, keepers, playoffs,
  tiebreakers, trades/FAAB, dues). The scoring table and standing rules are
  read straight from `mSettings` (`compute.build_scoring_table` /
  `build_league_rules`), so they track any commissioner change; keeper pricing
  (not in the ESPN API) is owner-confirmed config in the template.

For everything else shipped before 2026-09-23 (dual-point stats page, luck
index, rivalries, career stats, dark mode, Tailwind rewrite, real champions
from the playoff bracket, prize/payout split, etc.) — see `git log` and
`WORKLOG.md`; the old `ROADMAP.md` narrative tracking all of that by hand is
retired as of this consolidation.
