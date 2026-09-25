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

## Open — polish & UX

- **ENH-013** — Favicon/branding refresh — `static/fffIcon.png` is still the
  2018 placeholder.
- **ENH-014** — OG/social meta tags + a preview image — the link gets pasted
  into the league chat weekly and unfurls as a bare URL.
- **ENH-015** — "Last updated" stamp — `standings-<season>.json` carries
  `updated`; no template renders it.
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
