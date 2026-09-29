# ENH-024 — All-time kicker rankings

Status: done

All-time kicker rankings (owner idea, 2026-09-24) — done
2026-09-24. New "Kickers" page: every kicker ever started in the league
ranked by points contributed, the same cut by owner, each season's leading
leg, and nine fixed-rule joke awards. Required a new data artifact —
`fetch.py --starters` walks ESPN's `mBoxscore` one week at a time into
`data/starters-<season>.json` (every started player, all positions, not
just kickers). Verified: all 1,176 team-weeks of started points reconcile
exactly with the scores already in `standings-*.json`; 41 new tests.
