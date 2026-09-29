# ENH-012 — Lineup-level data

Status: open · Category: content & features

Lineup-level data: literal bench points, optimal-lineup
regret. **Half-unblocked 2026-09-24 by ENH-024** — started lineups are now
on disk (`data/starters-<season>.json`, every position, 2019–present) via
`mBoxscore`, not `mRoster`. What is still missing is the *bench*: the
starters file deliberately stores only who played. Bench points and
optimal-lineup regret need `rosterForCurrentScoringPeriod` kept too, which
is the same requests and a bigger file — a decision, not a blocker.
