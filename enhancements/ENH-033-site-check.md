# ENH-033 — One committed site check that every change runs

Status: open · Category: quality of life / dev experience

**Why:** every recent miss was something a standard check would have caught
before review:
- BUG-010: dead season-picker/logo links on team pages;
- ENH-025: CSS 404, and a chart crash before the fix;
- BUG-012: an invalid workflow file that stopped the bot.

Instead, each session writes a throwaway `check_enh0xx.py` and leaves it
untracked. Replace them with one committed check, so an agent working
unsupervised has a pass/fail answer.

Do this after BUG-011 and ENH-019. It uses `build.py --check`.

## `python tasks.py check`

Runs these in order, stops at the first failure, and exits non-zero:
1. `python -m unittest test_compute` (with `LEAGUE_PHRASE` and
   `LEAGUE_PHRASE_SHA256` cleared; see BUG-011).
2. `node --test tests/` if `node` is on PATH. Otherwise print a warning and
   skip.
3. `python build.py --check` (ENH-019): the committed `docs/` matches a fresh
   build.
4. A **workflow check** on `.github/workflows/*.yml`: it parses; only
   allowed top-level keys (`name`, `run-name`, `on`, `permissions`, `env`,
   `defaults`, `concurrency`, `jobs`); every `cron` has 5 fields. Use
   `actionlint` if it's installed, otherwise PyYAML. If neither is available,
   warn and skip.
5. `python check_site.py` (below).

## `check_site.py` (committed, repo root)

Playwright (Python), a dev-only dependency. It's not added to
`requirements.txt`, which stays the bot's pipeline dependencies. Document
the install in README "Frontend"/dev setup.

- **Serve and unlock:** serve `docs/` on a free local port. Unlock the gate
  by setting `leaguestats:unlocked` in `localStorage` to the digest in the
  built HTML (read it from `docs/index.html`; don't hardcode it).
- **Pages:** every `.html` under `docs/` for the root season, plus
  `index.html` and one team page from each archive season. `--all` covers
  every page of every season.
- **Matrix:** desktop 1440×900 and mobile 390×844, in light and dark (set
  `localStorage.theme` so the site's own toggle logic is used).
- **Live page:** abort requests to `lm-api-reads.fantasy.espn.com` with
  `page.route`, so the check is deterministic and tests the failure state.
  `--live` lets them through.
- **Fail on:**
  - any console error or uncaught page error;
  - any same-origin response ≥ 400;
  - `document.documentElement.scrollWidth` > viewport width;
  - any same-origin `a[href]` or `<select>` option `value` that, resolved
    with `new URL(value, location.href)`, doesn't return 200. Fetch each
    unique URL once. This is the BUG-010 check.
- **Output:** one line per failure (page, viewport, theme, what failed) and a
  summary count. `--shots DIR` also saves full-page screenshots, named
  `{page}-{theme}-{viewport}.png`, for before/after reviews.

## Also

- Delete the untracked one-off scripts (`check_enh0*.py`, `shoot_enh0*.py`,
  `_check_*`, `_bisect.py` and their `_*.txt` outputs) once this covers
  them.
- Update `AGENTS.md`: every item's verification is `python tasks.py check`
  passing, plus anything item-specific in its spec. A "done" claim without a
  passing check isn't done.

## Done when

`python tasks.py check` passes on the current `dev`. It also fails, with a
clear line, for each of these planted faults, which are then reverted:
- a relative link that 404s from a team page;
- a CSS path that 404s;
- a JS error on one page;
- a 600px-wide element on mobile;
- a top-level `timezone:` key in the workflow.
