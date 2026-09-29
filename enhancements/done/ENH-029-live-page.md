# ENH-029 — Live page (this week, live in the browser)

Status: done

Full spec as written before the build: `git show cd0ebc0 -- ENHANCEMENTS.md`.

Live page (this week, live in the browser) — done
2026-09-28. `live.html`, emitted for the newest season only: it fetches the
current week's ESPN scoreboard straight from the browser (polls every 60 s
while the tab is visible), merges it with a deterministic `docs/live-data.json`
snapshot that `build.py` writes (season, throughWeek, regularSeasonWeeks and
per-team teamId/name/points/rank — no owner names, no timestamp), and computes
score-to-beat, dual points and "if the week ended now" in the browser. The
rules live in `static/js/live-core.js` (pure, UMD — browser and Node) and are
pinned to `compute.py` by a Node parity test over every 2025 week
(`tests/live-core.test.js`); `live.js` does the DOM and polling. Bye weeks
render the byed teams in a "Bye this week:" line, and byed teams stay in the
score-to-beat and dual-points tables. Fails gracefully when ESPN is
unreachable (last daily data + a note). `build.py` skips `live.js` /
`live-core.js` when copying static assets into older-season archives, since
only the root season has a live page. Verified: unit + Node tests pass; a
second build changes nothing in `docs/`; Playwright checks (light/dark ×
desktop/mobile, ESPN blocked, synthetic bye week) pass with no console errors
and no horizontal page scroll at 390px.
