# Agent instructions

Read this file first, every session. It replaces re-reading SPEC.md,
ROADMAP.md, and BENCH_POINTS.md cover-to-cover just to get oriented — pull
those in only if the task actually needs the detail they hold.

## What this repo is

A static standings site for a 12-team ESPN fantasy football league, computing
a dual-point scoring system ESPN itself doesn't expose. Three Python scripts
(no server, no database) turn ESPN's API into committed JSON, then render it
to `docs/` for GitHub Pages. See `SPEC.md` §1 if you need the exact scoring
math, or `README.md` for the full picture.

## Working protocol

**One task per session. Stop when it is done.**

1. `git checkout dev` (never commit to `main` — a daily bot auto-commits data
   there, and Pages deploys from it). If `main` moved, merge `origin/main`
   into `dev`, never rebase.
2. Work the item you were given. If none was named, take the open bug in
   `BUGS.md` first, then the lowest-numbered file in `enhancements/`. Read
   only that item's file, not the whole folder, and never `enhancements/done/` or `enhancements/shelved/`
   unless the task points there. Do exactly that one thing — no drive-by refactors, no extra scripts, no "while I was
   here."
3. If anything is ambiguous, stop and ask rather than guessing.
4. Append one entry to `WORKLOG.md` (local-only, gitignored — session notes
   don't belong in the public repo) describing what changed and what you
   verified.
5. Stop. Say what's next; don't start it.
6. Always summarize if you committed, and ask if you should finish the push to main (or merge or PR, whatever). After review, changes will frequently want to go live quickly, especially for smaller changes.

## Repo layout

| Path | What |
| --- | --- |
| `fetch.py` | ESPN API → `data/raw-<season>.json`, verbatim, no transform. `--starters` is a second pass (one request per week) → `data/starters-<season>.json`, started lineups |
| `compute.py` | raw → `data/standings-<season>.json` — the dual-point math, playoff bracket, rivalries, career stats. **The only file with real logic; it has tests.** |
| `build.py` | renders `templates/` + `data/` → `docs/`, copies `static/` |
| `test_compute.py` | run with `python -m unittest test_compute -v` before touching `compute.py` |
| `tasks.py` | stdlib task runner: `python tasks.py {all,build,refresh,test}` |
| `templates/` | Jinja2 templates (Tailwind-styled) — don't touch outside a task that says to |
| `static/` | committed CSS/JS/fonts — `static/css/app.css` is compiled output, see README "Frontend" |
| `data/` | committed raw + computed JSON per season; `starters-<season>.json` is every started player-week; `data/prizes.json` is the pot config |
| `docs/` | rendered static site, what Pages actually serves — regenerated, don't hand-edit |
| `SPEC.md` | architecture reference: data schema, deploy config, decisions not to re-litigate |
| `BUGS.md` | defect log — check "Open" before assuming something's broken |
| `enhancements/` | the backlog, one file per item (`ENH-NNN-<slug>.md`) — each file is that item's spec; finished items `git mv` to `enhancements/done/`; `NOT-BUILDING.md` lists settled "no"s; conventions in `enhancements/README.md` |
| `WORKLOG.md` | gitignored session log — read for "what happened most recently" |
| `screenshots/` | Playwright visual baselines, one folder per commit hash; prune old ones when it gets large (see `screenshots/README.md`) |

## Standing rules (don't re-derive these)

- Playoff seeding: never trust ESPN's `playoffSeed` — this league reseeds by
  hand off the dual-point standings. Use `rankCalculatedFinal`.
- Never truncate a score with `| int` — decimals decide matchups.
- `build.py` output must stay deterministic (no timestamps, no randomness) or
  the daily bot commits every morning even when nothing changed.
- Group the ESPN schedule by `matchupPeriodId`, never index it arithmetically
  — playoff weeks don't have a fixed number of entries.
- Two dependencies only for the data pipeline: `requests`, `jinja2`. Don't add
  more.
