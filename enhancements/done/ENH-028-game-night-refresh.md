# ENH-028 — Game-night refresh cadence, no manual button

Status: done

Game-night refresh cadence, no manual button — done
2026-09-28. The "Run an update now" footer link is gone (manual dispatch
stays in the Actions UI); the bot now runs hourly on game nights (Sun
1–11pm, Mon/Thu 6–11pm and midnight, ET) plus the daily 8am, so the
freshness line is minutes old when it matters. The commit gate moved from
"anything in data/ or docs/ changed" to "docs/ changed": raw-*.json carries
live in-game scores on game weeks (verified on a live week: 2,389 leaf
diffs, all in-progress-week fields, standings byte-identical), which the
old gate would have committed every run.
