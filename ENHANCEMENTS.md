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
- **ENH-026** — Team page polish: the ENH-025 pieces that didn't ship
  (2026-09-28). (1) Header stat tiles instead of the one-line summary: dual
  rank, dual points with the h2h/top-half split, record, PF/PA, average,
  all-play % (the all-play numbers are already in the season Stats data).
  (2) The weekly chart as bars colored by win/loss, keeping the dashed
  score-to-beat line. That makes "won with a bottom-half score" and "lost
  with a top-half score" visible at a glance, which the current line chart
  hides. Do BUG-010 first, since it touches the same page.
- **ENH-027** — Season picker should match teams by owner, not ESPN team
  ID (follow-up to BUG-010, 2026-09-28). Team IDs are mostly, not always,
  stable per owner: teamId 9 was Maxwell in 2019–20 and Daniel Sharp from
  2021 on, so the ID-based picker links can land on a different owner's
  page when switching seasons. Needs a cross-season owner→teamId map passed
  into the template.
- **ENH-029** — Live page (owner idea, 2026-09-28). One page, `live.html`,
  that shows this week while games are on. It fetches ESPN directly from the
  browser and does this week's math in the browser. It's the one place the
  site is live. Everything else stays daily, static and computed in Python.
  Proven by a prototype in `D:\Workspace\ff-scoring-app-thinkingcap3.8-27b`
  (`public/live.html`, `public/js/live-core.js`, `public/js/live.js`,
  `test/live.test.js`). Borrow its structure, but **not** its top-half rule
  (see "Rules" below).

  **Why it's allowed:** this reverses "live in-game scoring" in "Explicitly
  not building" for this one page only. Update that section to say so. ESPN
  answers browser requests from any origin (`Access-Control-Allow-Origin`
  echoes the caller; verified 2026-09-28 for `tuura032.github.io` and
  `localhost`). That's unofficial and could change, so the page must fail
  gracefully (see "Failure").

  **Three layers:**
  1. **Live, from ESPN, in the browser.** `GET
     https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<season>/segments/0/leagues/877873?view=mMatchupScore&view=mScoreboard&view=mTeam&view=mSettings`.
     Per side, use `totalPointsLive` (fall back to `totalPoints`),
     `totalProjectedPointsLive` (fall back to live) and `winProbability`.
     Pick the week with `status.currentMatchupPeriod`, and group the schedule
     by `matchupPeriodId`, never by index (standing rule).
  2. **Your data, as a static file.** `build.py` writes
     `docs/live-data.json` for the **newest season only**: `season`,
     `throughWeek`, `regularSeasonWeeks`, and per team `teamId`, team `name`,
     season dual `points` and `rank`. It comes straight from
     `standings-<season>.json`. **No owner names** (see "Names"), and no
     `updated` or other timestamp, so it stays deterministic and the daily
     bot doesn't churn it. The page fetches it once on load.
  3. **Model layer in JS:** `static/js/live-core.js`. Pure functions, no DOM,
     loadable in the browser and in Node for tests. Merge layers 1 and 2 by
     `teamId`, and calculate this week's numbers. `static/js/live.js` does the
     DOM work and polling.

  **Rules (must match `compute.py`, not the prototype):**
  - **Score to beat:** port `compute.score_to_beat` exactly. Sort ascending
    and take index `n // 2 - 1`, which is the highest score that *missed* the
    top half (the 7th-best of 12). A team gets the top-half point only if its
    score is **strictly greater** than that. So a tie at the boundary gives
    **neither** team the point, and an 11-team field awards 6 points
    (SPEC.md §1, `compute.py` `build_week`).
    - The prototype's `topHalfLine` uses the 6th-best score with ≥, which
      differs on exactly these edge cases. Don't copy it.
  - **H2H point:** the higher score leads. An exact tie gives neither team
    the point.
  - Show both **live** and **projected** versions of the score to beat and
    each team's 0/1/2 for the week.
  - **Regular season only:** if the current week is greater than
    `regularSeasonWeeks`, show the scoreboard and hide everything about dual
    points. Playoff weeks don't count (standing rule).
  - Keep decimals as ESPN reports them. Round to one decimal **for display
    only**, and use the same one-decimal display in every spot. The prototype
    leaked float noise like `+19.700000000000003`.

  **What the page shows, in order:**
  1. **Scoreboard:** the six matchups with live score, projected score, and
     win probability as a percentage (not `0.99`).
  2. **Score to beat:** live and projected, with each team shown as above or
     below it and by how much. This is the stat ESPN doesn't show, so give it
     the most prominent spot.
  3. **This week's dual points:** each team's live and projected 0/1/2, with
     plain chips like `W` and `TOP`. The prototype's `1W + 1½` read as "one
     and a half."
  4. **"If the week ended now":** season dual points from `live-data.json`
     plus this week's projected 0/1/2, re-ranked, with movement against
     `rank`. Only show it when `throughWeek == currentMatchupPeriod - 1`.
    - Otherwise the daily bot hasn't caught up with last week yet, and adding
      this week would skip one. In that case, hide the table and show a note.

  **Names:** team names only, on this page. ESPN's `mTeam` response includes
  members' real names, which will be visible in dev tools no matter what.
  That's accepted. But don't *display* owner names anywhere on this page.

  **Refreshing:**
  - Fetch on load, then every 60 s while the tab is visible
    (`visibilitychange`). Stop polling when every matchup this week is final.
  - Show "Updated Ns ago." A manual Refresh button is fine, but disable it for
    a few seconds after each click, so nobody hammers ESPN.

  **Failure:** if ESPN fails or returns an unexpected shape, show a clear
  message and keep the last good data on screen. If there's no data at all
  (outside the season, or ESPN is down), show a friendly empty state that
  links to Home. Don't throw uncaught errors.

  **Site integration:**
  - `templates/live.html` extends `layout.html`, so it gets the passphrase
    gate, nav, dark mode and the swatch colors.
  - Style it with the site's Tailwind classes, not the prototype's CSS. New
    utility classes need an `app.css` rebuild (README "Frontend").
  - Build it for the **newest season only** (the site root), not the archive
    seasons.
  - Add "Live" to both the desktop and mobile navs.
  - On the live page, season-picker options must point at each season's
    `index.html` (`live.html` doesn't exist in the archives). Check this the
    way BUG-010 was checked: resolve every option with
    `new URL(value, location.href)` and expect a 200 response.
  - Chart.js isn't needed. If you add a chart anyway, it's 2.7.1 syntax (see
    ENH-025).

  **Tests:**
  - `node --test tests/live-core.test.js` (Node's built-in runner, no npm
    packages, not in CI). Cover the score to beat, the ties at the boundary
    and in H2H, an odd field size, byes, the merge, and the "ended now"
    re-rank.
  - **Parity test (the important one):** for every regular-season week of
    2025, feed `data/raw-2025.json` to `live-core.js` in final-score mode,
    and assert that each team's h2h and topHalf points and each week's score
    to beat match `data/standings-2025.json` `weeks[]`. That's what keeps the
    JS and Python from drifting.
  - `python -m unittest test_compute -v` still passes (add a test for the
    `live-data.json` builder if it's a function in `compute.py`).

  **Done when:** the tests above pass, and a second `build.py` run changes
  nothing in `docs/`. Playwright on `live.html`, in light/dark and
  desktop/mobile, shows:
  - no console errors;
  - no horizontal page scroll at 390px;
  - a working empty/error state when the ESPN host is blocked (use
    `page.route` to abort it).

## Open — polish & UX

- **ENH-013** — Favicon/branding refresh — `static/fffIcon.png` is still the
  2018 placeholder.
- **ENH-014** — OG/social meta tags + a preview image — the link gets pasted
  into the league chat weekly and unfurls as a bare URL.
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

*Amended 2026-09-28:* live in-game scoring is allowed on **one page** only
(ENH-029, `live.html`), and it runs in the browser. Everything else stays
daily, static and computed in Python.

---

## Done

- **ENH-028** — Game-night refresh cadence, no manual button — done
  2026-09-28. The "Run an update now" footer link is gone (manual dispatch
  stays in the Actions UI); the bot now runs hourly on game nights (Sun
  1–11pm, Mon/Thu 6–11pm and midnight, ET) plus the daily 8am, so the
  freshness line is minutes old when it matters. The commit gate moved from
  "anything in data/ or docs/ changed" to "docs/ changed": raw-*.json carries
  live in-game scores on game weeks (verified on a live week: 2,389 leaf
  diffs, all in-progress-week fields, standings byte-identical), which the
  old gate would have committed every run.
- **ENH-025** — Team pages + data freshness + missing stats — done
  2026-09-28. One page per team per season: a `team.html` index linking
  every team, and `team/<teamId>.html` with a one-line header (rank, dual
  points, record, PF/PA, final rank), a weekly score line chart with the
  score-to-beat line (Chart.js 2.7.1 config, theme-aware), a 2/1/0
  dual-points chip per week, linked schedule
  and separate postseason tables, and this-season H2H vs. every other team.
  Team names link to their pages from every table that shows them. Footer
  "Data through week N · updated …" freshness line (absolute date in HTML,
  relative in the browser) with a workflow-dispatch "Run an update now" link
  — this closes ENH-015. `compute.py` now keeps the old `updated` stamp when
  the data didn't change, so the daily bot doesn't churn `docs/`. Stats page
  gained Pts in losses, Heartbreaks (losses by under 5), Blowouts (wins by
  50+), full decimals, regular season only. Verified: unit tests pass; a
  second build changes nothing in `docs/`; Playwright light/dark and
  desktop/mobile checks show no console errors, no 404s, no horizontal page
  scroll at 390px (tables scroll inside their own containers, as everywhere
  else on the site).
  - *Corrected 2026-09-28 in review:* this entry originally said the header
    had stat tiles with all-play % and that the chart was a win/loss bar
    chart. Neither shipped; they're now ENH-026. The season picker and logo
    link are broken on team pages: BUG-010.
- **ENH-015** — "Last updated" stamp — done 2026-09-28, shipped as the
  freshness line in ENH-025 part B.
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
