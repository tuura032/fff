# ENH-038 — Week-over-week rank movement arrows on the standings

Status: done 2026-11-03 · Category: content & features

Owner request (2026-11-03): next to each team's rank on the Home standings
table, show how that rank moved since the previous week, green up / red down,
so the table answers "what changed this week" at a glance. Example: 4th last
week, 5th this week → a red `▼1`.

## Contract

### compute.py — `build_standings`

Add one field to every row of `standings`:

- `prevRank` — int or `null`. The rank that team held after week
  `throughWeek - 1`, computed with exactly the same ranking rule as `rank`
  (sort by `points` descending, then `pointsFor` descending, where `points` is
  h2h + top-half points summed over the counted weeks and `pointsFor` is the
  summed raw score rounded to 1 decimal). `null` when `throughWeek < 2`
  (there is no previous week to compare to).

Rules:

1. Use only `weeks_out` (the completed regular-season weeks already built in
   `build_standings`). The previous-week ranking is that list minus its last
   element. Never index the schedule arithmetically.
2. Ties must break the same way the real `rank` does. Write one small helper,
   `rank_teams(weeks, team_ids)` → `{teamId: rank}`, that takes a list of
   week dicts (the `weeks_out` shape: each has `"teams"` with `teamId`,
   `score`, `h2h`, `topHalf`) and the team ids in `team_info` order, and
   sorts with Python's stable sort on `(-points, -round(pointsFor, 1))`.
   Use it for `prevRank`. Do NOT change how `rank` itself is computed.
3. Pure function, no new dependencies, no timestamps.
4. Every other field and the output order stay exactly as they are.

### templates/home.html — the standings table rank cell

The first `<td>` of each standings row currently shows the rank badge
(`loop.index`). Keep the badge exactly as is and add a movement marker right
after it, on the same line:

- Let `change = info.prevRank - loop.index` when `info.prevRank` is not none.
- `change > 0`: `▲` followed by the number, e.g. `▲1`, classes
  `text-emerald-600 dark:text-emerald-400`.
- `change < 0`: `▼` followed by the absolute number, e.g. `▼2`, classes
  `text-red-600 dark:text-red-400`.
- `change == 0`: a muted `–` (en dash), classes `text-slate-300 dark:text-slate-600`.
- `info.prevRank` is none: render nothing.
- Marker element: `<span class="ml-1.5 text-[.65rem] font-semibold tabular-nums ...">`,
  with `title` and `aria-label` text: `Up 1 since week 7 (was 4th)`,
  `Down 2 since week 7 (was 3rd)`, `No change since week 7`, where 7 is
  `throughWeek - 1`. Ordinals: 1st 2nd 3rd 4th … 11th 12th (11–13 are "th").
  The marker symbol itself gets `aria-hidden` only if the label is on the
  outer span (put the label on the outer span).
- Make the badge and marker sit on one line: wrap the cell contents in
  `<span class="inline-flex items-center">…</span>` if needed. Don't let the
  column wrap.
- Add `data-sort="{{ loop.index }}"` to that `<td>` so column sorting keeps
  sorting by rank, not by the marker text.

Only the Home standings table. No other page changes.

### SPEC.md

In the standings schema section (the `"standings": [ { "rank": 1, ... } ]`
example, around §5), add `"prevRank": 2` to the example row and one line
below the block: "**Added 2026-11-03:** `prevRank` — rank after week
throughWeek−1, same ranking rule; `null` before week 2 (ENH-038)."

## Tests (test_compute.py)

Add a test class `TestPrevRank` using the existing `make_raw` / `week_games`
helpers:

1. With `full_season_weeks()` (14 weeks): every row has an int `prevRank`;
   the set of `prevRank` values is exactly 1..12.
2. `rank_teams(out_weeks, ids)` applied to *all* of the output `weeks` equals
   each row's actual `rank` (proves the helper matches the real ranking).
3. `prevRank` equals `rank_teams(weeks[:-1], ...)` for each team.
4. A season with only week 1 played → every `prevRank` is `None`.
5. A constructed 2-week case where a team moves: build week 1 and week 2 with
   `week_games` so that some team is ranked differently after week 2 than
   after week 1, and assert that team's `rank` and `prevRank` explicitly
   (hard-coded expected numbers, not recomputed).

## Done when

- `python -m unittest test_compute -v` passes (all old tests + new ones).
- `python compute.py` runs and `data/standings-2026.json` rows carry
  `prevRank`.
- `python build.py --no-gate` runs without error and `docs/index.html`
  contains the movement markers (`▲`/`▼`/`–`) in the standings rank cells.
  (Do not commit the `--no-gate` build output — see "Don't".)

## Don't

- Don't touch `static/css/app.css`, `package.json`, or run npm — the owner's
  session rebuilds CSS.
- Don't commit anything under `docs/` or `data/` (the owner's session
  regenerates both with the real build). Revert them before finishing:
  `git checkout -- docs data`.
- Don't edit any other template, fetch.py, build.py, or the sidecar.

## Shipped

Built by a local Qwen worker from this spec, reviewed and tweaked by Claude.
`compute.rank_teams()` plus a `prevRank` field on every standings row; Home's
rank cell shows a green ▲N, red ▼N, or muted – with a "Up 1 since week 7
(was 4th)" tooltip and screen-reader text. Review tweaks: ranks 4+ get the same
w-6 box as the top-3 badges so the markers line up, and the label is sr-only
text rather than aria-label on a bare span. Past seasons were recomputed once
so they show the week 13→14 move. Verified: 220 tests OK; real 2026 data
(week 8) gives the expected moves; rendered Home checked in a browser.
