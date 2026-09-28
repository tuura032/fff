# LeagueStats — v2 spec

A standings page for **FFF** (ESPN league `877873`, "Fantasy Football Fantasy"),
computing a scoring system ESPN cannot compute itself.

v1 (2018–19) was Flask + Postgres on Heroku. It died when Heroku dropped free
Postgres. **The frontend never died — only the backend did.**

**This is an enhancement, not a rewrite.** The templates, the Bootstrap layout,
the CSS and the standings table all stay. What changes is where the data comes
from and how the page is served.

---

## 0. Working protocol — READ THIS FIRST, EVERY SESSION

Moved to `AGENTS.md` (one task per session, branch discipline, WORKLOG entry,
stop when done). Read that file first; this one is architecture reference,
not the entry point.

---

## 1. The scoring rule — the whole reason the project exists

Each week, every team can earn **up to 2 points**:

| Point | Condition |
| --- | --- |
| **1** | Win your head-to-head matchup |
| **1** | Finish in the **top half** of the league in raw points that week |

Twelve teams, six matchups, so each week distributes 6 H2H points and 6
top-half points.

**ESPN does not support this natively** — it shows W/L and points-for and leaves
the second point uncomputed. That gap is the product, and it is why this repo
exists at all.

### Exact math

For each week:
1. Collect all 12 team scores.
2. **H2H:** in each of the 6 matchups, the higher score takes the point.
3. **Top half:** sort the scores ascending. Index `[n // 2 - 1]` is the
   **threshold** — the highest score that missed the top half, which is `[5]`
   for this 12-team league. A team earns the point by scoring **strictly
   greater** than it.

   *Amended 2026-09-22 (BUG-006).* This originally said "index `[5]`", ported
   verbatim from v1. That is correct for 12 teams and silently the wrong
   scoring rule for any other league size, so it is now derived from the
   field size. No change to FFF's numbers.

v1 called that threshold the **"score to beat"** and computed it exactly this
way in `getApiData.py:getScoresToBeat()`. It is correct. Keep the name — it is
what the league calls it.

### Scoring window

**Weeks 1–14 only.** Read the value from
`settings.scheduleSettings.matchupPeriodCount` (currently 14) — do
not hardcode it. Weeks 15–17 are the playoff bracket (6 playoff teams) and must
not accumulate dual points.

### Tie rules — ASSUMPTIONS, flagged for confirmation

Not documented in v1. Defaults chosen to match v1's strictly-greater comparison:

- **Exact H2H tie** → no point to either team.
- **Exact tie at the top-half boundary** (6th and 7th identical) → no point to
  either, so the league awards 5 top-half points that week rather than 7.

Write both as explicit branches with tests, not as a side effect of an operator.
Ask the league before the first public run.

---

## 2. Architecture

**Python 3.11+, keeping Jinja2.** Four scripts, run in order:

```
fetch.py     ESPN → data/raw-<season>.json           one HTTP call, whole season
compute.py   raw  → data/standings-<season>.json     the dual-point math
build.py     standings + templates/ → docs/*.html    static render, no server
```

`compute.py` and `build.py` never touch the network, so they re-run offline
against a committed raw file.

**Dependencies — this list is complete:** `requests`, `jinja2`. That is it.
Flask, flask-session, SQLAlchemy and psycopg2 all go.

**Frontend build (added 2026-09-22):** Bootstrap 4 + jQuery, replaced with
Tailwind CSS, compiled dev-time from `src/tailwind.css` to the *committed*
`static/css/app.css` (no CI build step — GitHub Pages serves `static/` as
real files, same as `static/js/hello.js`). This is a Node dev dependency
only; the runtime pipeline above stays Python-only. See `README.md`
§"Frontend (Tailwind CSS)".

**Why Python and not a rewrite in something else:** the templates are Jinja and
they are worth keeping (§4). Rendering them needs Jinja. Anything else means
rewriting the frontend, which is the one part that still works.

---

## 3. Data source

One call returns the **entire season's** schedule with scores:

```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<season>/segments/0/leagues/877873?view=mMatchupScore
```

- **Public league. No cookies, no auth, no secrets in the repo.** This is what
  makes the whole no-credentials design possible.
- A second call with `view=mTeam` gets team names and owners. Sleep 1s between
  each call — it is an unauthenticated public API.
- A third call with `view=mSettings` carries the regular-season length —
  `settings.scheduleSettings.matchupPeriodCount`. Neither `mMatchupScore` nor
  `mTeam` includes a `settings` object, so L2 needs this view.
- Shape:
  ```jsonc
  { "schedule": [
      { "matchupPeriodId": 5,
        "home": { "teamId": 1, "totalPoints": 143.8 },
        "away": { "teamId": 4, "totalPoints": 117.4 } } ] }
  ```

- A fourth view, `mBoxscore`, carries the actual lineups -- but only for one
  week per request. `fetch.py --starters` walks it week by week into a
  separate artifact; see §5.

### Surnames are redacted on write (added 2026-09-23)

The one deliberate exception to "verbatim". This repo is **public** — free
GitHub Pages requires it — so every byte in `data/` is world-readable, and
ESPN's member records carry full legal names.

`fetch.redact_members()` runs before the raw file is written and:

- truncates every `lastName` to `SURNAME_KEEP` (3) characters,
- applies the same truncation inside `displayName`, since some members have
  set theirs to their full name,
- swaps a surname out of any **team name** built from it ("Team Hildebrandt"
  → "Team Ethan"), using the first name so the result still reads like a
  team name,
- drops `notificationSettings` as noise.

Nothing downstream needs more: `compute.py` builds owner identity from the
first name plus the surviving prefix, and `compute.short_names()` shows the
first name alone unless two owners collide, in which case each gets the
shortest prefix that separates them ("Daniel Se." / "Daniel Sh.").

**This does not rewrite history.** Commits made before this change still
carry full surnames in `data/`. Cleaning those would need a history rewrite
and a force-push, which the owner has previously declined for a similar
issue; the decision here was to stop the ongoing exposure, not to erase the
record.

### Two traps inherited from v1 — do not re-introduce

1. **Do not index `schedule` by arithmetic.** v1 used `(week-1)*6 + matchup`,
   assuming exactly 6 ordered entries per week. True for weeks 1–14, **false in
   the playoffs** — week 15 of 2025 has 7 entries. Always filter on
   `matchupPeriodId`.

2. **`getApiData.py:getWeeklyScores()` is broken.** It indexes `schedule[0]`
   inside a loop over `matchup`, and assigns the home team twice so away never
   lands — every team gets week 1's home score. Do not port it. Read
   `getScoresToBeat()` in the same file first; that one is correct and is the
   model to follow.

---

## 4. The frontend — kept, not replaced

**Superseded 2026-09-22** for the visual layer specifically: `static/dashboard.css`
and Bootstrap 4/jQuery are gone, replaced with Tailwind CSS (owner-requested
full redesign, not an incremental fix — see §2). The section below is kept
for history; `templates/*.html` structure/Jinja logic is still the v2
rewrite's work and still the thing being built on, just with Tailwind
classes instead of Bootstrap ones.

`templates/` is v1's work and the Jinja structure is still what's being built
on (now with Tailwind classes). The five lines of literal Flask coupling
(`url_for`, `get_flashed_messages`) and the server-side sort routes
(`/total_wins`, `/h2h`, …) were removed during L3/L6 — sorting is vanilla
client-side JS in `static/js/` now. Historical detail: git history around
those commits.

### Pages to render

`home.html` is the priority. `playoffs.html`, `player1.html`, `graph.html`,
`weeklyupdate.html`, `update.html`, `welcome.html`, `error.html` exist in
`templates/`; `update.html` and `error.html` were admin/Flask concerns and can
be dropped. Render the rest only if the data supports them — **do not invent
data to fill a template.** If a page needs something `standings.json` does not
have, note it in `WORKLOG.md` and leave the page unrendered.

---

## 5. Output shape

`data/standings-<season>.json` — the committed artifact the page renders from.

```jsonc
{
  "season": 2025,
  "league": "877873",
  "updated": "2026-09-18T13:04:11Z",
  "regularSeasonWeeks": 14,
  "throughWeek": 14,
  "weeks": [
    { "week": 5,
      "scoreToBeat": 108.9,
      "games": [ { "home": 1, "away": 4, "homeScore": 143.8, "awayScore": 117.4, "winner": 1 } ],
      "teams": [ { "teamId": 1, "score": 143.8, "h2h": 1, "topHalf": 1, "weekPoints": 2 } ] }
  ],
  "standings": [
    { "rank": 1, "teamId": 1, "name": "…", "owner": "…",
      "points": 21, "h2hPoints": 11, "topHalfPoints": 10,
      "record": "11-3", "pointsFor": 1698.4, "pointsAgainst": 1502.1,
      "averageScore": 121.3, "avgLast3": 118.0 }
  ]
}
```

Keep the per-week detail — it is what makes a weekly-recap view possible later
without re-fetching, and it is how you audit a standings change by diffing two
commits.

**Added 2026-09-22:** `leagueName`, `playoffTeamCount`, and `playoffs` —
the last being the winners-bracket result (`null` until a season's final is
decided):

```jsonc
"playoffs": {
  "champion": 12, "runnerUp": 2,
  "championScore": 154.5, "runnerUpScore": 108.9,
  "mostPointsFor": 12, "pointsFor": { "12": 494.7 },
  "finalWeek": 17,
  "games": [ { "week": 15, "home": 2, "away": null, "bye": true } ]
}
```

Weeks 15-17 still contribute **no dual points** (§1) — the bracket is read
only to record who won, which is a different question from the standings.

**Standings sort:** `points` desc, then `pointsFor` desc.

### `data/starters-<season>.json` (added 2026-09-24)

The second committed artifact: every **started** player, week by week. Written
by `fetch.py --starters`, which is a separate, manual-ish pass over ESPN's
`mBoxscore` view -- one request per matchup period, because the response only
carries rosters for the `scoringPeriodId` in the query.

```jsonc
{
  "season": 2025,
  "weeks": [1, 2, 3],
  "starters": [
    { "week": 1, "teamId": 1, "slot": 17, "playerId": 15683,
      "name": "Justin Tucker", "pos": 5, "proTeamId": 33, "points": 11.0 }
  ]
}
```

Three things about this file that are decisions, not accidents:

- **It is a trimmed subset, not a transform.** ESPN sends 0.5-0.9 MB per week
  -- projections, per-stat breakdowns, ownership, injury history. Keeping it
  verbatim would be ~100 MB a season in a repo that commits its data. Eight
  fields are kept and the rest is dropped at fetch time.
- **Starters only.** The row set comes from `rosterForMatchupPeriod` (the nine
  who played; their points sum exactly to the team's `totalPoints`), while
  `slot` is looked up from `rosterForCurrentScoringPeriod`, which is the only
  block with a real `lineupSlotId` -- and also the only one with the bench in
  it. Never take the row set from the second block.
- **`pos` is `defaultPositionId`**: 1 QB, 2 RB, 3 WR, 4 TE, 5 K, 16 D/ST.

Not part of the default fetch: past seasons never change, so re-walking 2019
every morning would be ~17 pointless requests. The incremental run asks only
for weeks it does not have and stops at the first unplayed one.

**The invariant worth testing against:** a team-week's started points must sum
to that team's `score` in `standings-<season>.json`. All 1,176 team-weeks on
file reconcile exactly; `test_compute.py` asserts it.

---

## 6. Why no database

Not effort. The workload has none of the properties a database is for:

- **No queries.** Exactly one view. A database earns its keep when you need to
  ask questions you did not anticipate.
- **No mutation.** Every run recomputes ~170 numbers from scratch in
  milliseconds. No incremental state, transactions, or concurrency.
- **Git is already the right database for this shape** — append-only,
  timestamped, versioned. Diff two commits to see exactly what moved.
- **A database is what killed v1.** Removing the server removes the only
  component that can expire, rot, or bill you.

**Revisit if:** arbitrary cross-season queries, more than one writer, features
with real relational shape (trades, player-level weekly history), or data that
outgrows a git-diffable file.

An optional DB *sink* is fine later — write to it **in addition to** the JSON,
never instead. The site must keep rendering when it is down.

---

## 7. Deploy

**GitHub Pages** serving `/docs` from the default branch. **GitHub Actions** on
a schedule:

```yaml
on:
  schedule:
    - cron: '0 8 * * *'       # daily: stat corrections + safety net
    - cron: '0 13-23 * * 0'   # Sunday: hourly through the final
    - cron: '0 18-23 * * 1,4' # Mon/Thu: the night game
    - cron: '0 0 * * 1,4'     # Mon/Thu midnight
  workflow_dispatch:         # manual "run now" (Actions UI)
timezone: America/New_York   # crons above are ET, not UTC
```

Run fetch → compute → build, then **commit only if the rendered site
(`docs/`) changed** — not merely the data: `raw-*.json` carries live
in-game scores on game weeks, which would churn a commit every run while
the site stays byte-identical. When `docs/` changes, `data/` ships with it
as a consistent snapshot.

Hourly on game nights rather than once a day: ESPN finalizes scores shortly
after the final whistle, so the site picks up the new week within ~an hour
of games ending; the daily run absorbs ESPN's stat corrections for a day or
two after games. One missed run then costs nothing.

**Known limitation, document it in the README:** GitHub disables scheduled
workflows on public repos after **60 days of repository inactivity**. In-season
the job commits regularly and stays alive; Feb–Aug it goes dormant and needs one
manual re-enable each August.

---

## 8. Repo setup

This work goes to a **new remote** — `LeagueStatsReloaded`, renamed to
`fff` on 2026-09-23 to shorten the Pages URL to
`tuura032.github.io/fff/`. Git operations against the old name still
redirect; **the old Pages URL does not** — GitHub lists project site URLs
as the one thing a rename does not redirect, so
`tuura032.github.io/LeagueStatsReloaded/` now 404s. The site itself needed
no changes: every link in `templates/` is relative, so it works at any
path. The original
`tuura032/LeagueStats` is being made **private** and kept as-is.

- **Fresh history (owner decision, 2026-09-22).** The new repo starts from a
  clean `git init`; the 2018–19 commits do not ride along. GitHub Push
  Protection blocked the first push (the old history carries the Postgres
  URL below), and the owner chose a fresh baseline over unblocking the
  secret or rewriting history. The 2018 lineage stays readable in the
  private repo.
- **`application.py` carried a hardcoded Postgres URL.** It is deleted
  before the first commit, so the secret exists only in the private repo's
  history. The database is long dead.
- Deleted from the working tree before the first commit (the private repo
  keeps them): `application.py`, `getApiData.py`, `Procfile`,
  `__pycache__/`. `getApiData.py:getScoresToBeat()` — the §1 reference
  implementation — was read and ported into `compute.py` in L2.
- `requirements.txt` shrinks to `requests` and `jinja2`.

---

## 9. Task list

L1–L9 (fetch → compute → de-Flask → build → data-drive sidebar → client-side
sort → GitHub Action/Pages → README → multi-season archive) are all complete
as of 2026-09-22. See `WORKLOG.md` and git history for what each did. Current
open work lives in `ENHANCEMENTS.md` and `BUGS.md`, not here.

---

## 10. Decisions — do not re-litigate

- **Enhancement, not rewrite.** The frontend stays. (§4)
- **No database, no server, no secrets.** (§6)
- **Static output committed to the repo**, served by Pages. (§7)
- **Files are the source of truth.** Any future DB is an additive sink.
- **Two dependencies**, `requests` and `jinja2`. (§2)
- **Scoring covers the regular season only**, length read from the API. (§1)
- **Self-hosting was considered and declined** for this site — it is a static
  page that free hosting serves better, and a 36TB NAS is the wrong machine to
  expose. Self-host things that benefit from being local; this does not.
