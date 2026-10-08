# ENH-035 — Top-six line history

Status: open · Category: content & features

The Top Six Finishes column says how many times an owner cleared the line,
but not where the line was or how close the misses were. Example, 2026
through week 4: Paul is 4th in total points but has 1 top-six finish,
because he finished 7th twice (week 3: 103.6 vs a 107.1 line, week 4:
114.6 vs 122.3) and 12th once. From the standings table alone, that looks
like a bug. It isn't, and showing the line makes that clear.

Show, for every week of a season: where the top-six line sat, and which
side of it each owner landed on, by how much.

**Data is already there.** `weeks[].scoreToBeat` in `standings-<season>.json`
is the line (the 7th-highest score, i.e. what you had to beat to get a
top-half point). Each week's `games[]` has every score. No `compute.py`
change should be needed unless the owner wants a precomputed margin.

**Open: where it goes.** The owner hasn't decided yet; ask before building.
Candidates:
- a week-by-owner grid on the standings page (cells colored above or below,
  showing the margin), under or beside the table;
- a per-week strip on the team page. ENH-026 (2) already plans bar charts
  colored by win/loss with the dashed score-to-beat line, so the two may
  merge;
- a history of the line itself (one value per week, across seasons), as
  context for what a top-half score usually takes.

**Rules:**
- Show margins with one decimal; never truncate (AGENTS.md).
- Exact ties at the line follow whatever `compute.py` already does for
  top-half points. Check it; don't invent a new rule.
- Output stays deterministic.

**Done when:** for any season, a reader can see each week's line value and
every owner's above/below result with the margin, and the counts match the
Top Six Finishes column.
