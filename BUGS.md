# Bugs

Defects to work through. Newest last. See `SPEC.md` §0 for the working protocol.

**Format:** id, date, title, where found, what's wrong, impact, resolution (once
fixed), status.

---

## Open

- **BUG-010** (2026-09-28) — Team pages: season picker and logo link 404.
  Found in the post-ENH-025 review (Playwright, resolving every link on
  `docs/team/2.html` and `docs/2019/team/2.html`).
  - **What's wrong:** team pages live one folder down (`team/<id>.html`).
    ENH-025 added `root_prefix` to the nav links, stylesheet and favicon, but
    not to two relative URLs in `layout.html`:
    - the header logo's `href="index.html"` resolves to `team/index.html`;
    - the season picker's option values (`{{ base }}{{ s }}/{{ active_page }}`)
      resolve from the page's own folder. From `team/2.html`, "2025" goes to
      `team/2025/team/2.html`. From `2019/team/2.html`, "2025" goes to
      `2019/2025/team/2.html`, and "2026" reloads the same 2019 page.
  - **Impact:** on every team page in every season, the logo and all season
    options are dead links, or land on the wrong page. Flat pages are
    unaffected. This was missed because ENH-025's Playwright check looked for
    404s on page load, not on link targets.
  - **Also fix while in there:** the `build.py` comment says team IDs are
    "stable per owner across seasons", which is false for **teamId 9**
    (Maxwell 2019–20, Daniel Sharp 2021+). Once the picker works, switching
    seasons on team 9's page across 2020→2021 lands on the other owner.
    Either accept that and correct the comment, or have the picker match by
    owner for team pages.
  - **Verify:** for a current-season and a 2019 team page, resolve the logo
    href and every picker option with `new URL(value, location.href)`, and
    check that each one returns 200 and is the page you expect.
  - Status: open.
- **BUG-011** (2026-09-28) — `TestPassphraseGate` fails when
  `LEAGUE_PHRASE_SHA256` is set in the shell. Found by the ENH-025 session
  (WORKLOG). The test isolates `LEAGUE_PHRASE` but not the digest
  passthrough, so a leftover digest from a gated local rebuild makes it fail
  for reasons unrelated to the code. Fix: have the test clear or patch both
  env vars. Low impact, since only local test runs are affected. Status: open.

## Resolved

One line each (full write-ups: git history, 2026-09-18 → 2026-09-22).

- **BUG-001** (2026-09-18) — spec named a nonexistent key →
  `matchupPeriodCount` (SPEC.md §1 corrected).
- **BUG-002** (2026-09-18) — week count not in the fetched views → third call
  (`mSettings`) added to `fetch.py`.
- **BUG-003** (2026-09-22) — Career Stats credited the title to the wrong
  owner (weeks 15–17 discarded) → `build_playoffs()` parses the winners'
  bracket; separate **Titles** / **Reg #1** columns.
- **BUG-004** (2026-09-22) — click-to-sort dead on Home (colspan divider row
  threw in the comparator) → narrow rows treated as decoration; headers
  keyboard-operable.
- **BUG-005** (2026-09-22) — Stats chart rendered a filled blob and tooltips
  threw (3.x API on Chart.js 2.x) → `fill: false`, 2.x callback; Chart.js only
  on graph.html.
- **BUG-006** (2026-09-22) — `score_to_beat()` hardcoded a 12-team field →
  `sorted(scores)[len(scores) // 2 - 1]`; tests cover 8–12 teams.
- **BUG-007** (2026-09-22) — leading an unfinished season counted as a
  regular-season title → only counted when `throughWeek == regularSeasonWeeks`.
- **BUG-008** (2026-09-22) — season picker threw away the page you were on →
  options append `active_page`; links built off `root_season`, not
  `current_season`.
- **BUG-009** (2026-09-22) — past seasons buried the result → champion banner,
  sortable **Finish** column, **Final Standings** table. **Standing rule:** the
  league reseeds the playoffs by hand, so ESPN's `playoffSeed` is wrong — use
  `rankCalculatedFinal`.
