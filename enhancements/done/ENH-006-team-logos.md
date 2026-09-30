# ENH-006 — Team logos on the rest of the site

Status: done 2026-09-30 · Category: content & features

`teams[].logo` and `teams[].abbrev` are in every raw file, unused by
`compute.py`.

**Already done (ENH-031):** the live page shows logos from the live ESPN
payload, and falls back to initials in a rounded square when an image fails.

**Remaining:** carry `logo` (and `abbrev`, if useful) per team into
`standings-<season>.json`, and show logos on the static pages:
- Home standings rows;
- team page headers;
- the Teams dropdown in the nav;
- optionally Playoffs and Rivalries.

Reuse the live page's fallback behavior, so logos look the same everywhere.
Logos are per season, since owners change them, so each season uses its own
raw file. Some logo URLs point at third-party hosts: never let a broken
image break the layout.

## Shipped (2026-09-30)

- `compute.py` carries `logo` + `abbrev` from the raw `mTeam` block onto
  every standings row (per season, from that season's own raw file) and onto
  `build_team_season` output for the team pages. Missing/empty values
  become `null` (tests in `test_compute.py::TestTeamLogos`).
- `templates/layout.html` gains a `team_logo` macro (small 20px / large 40px)
  that renders the circle `<img>`, or the initials in a rounded square when
  the URL is absent. Initials come from a new `initials` filter in
  `build.py` — same rule as `live.js`'s `logoInitials` (this Jinja
  environment has no `regex_replace`).
- `static/js/team-logo.js` (included from the layout with `root_prefix`, so
  team-page depth resolves) swaps any logo that fails to load for its
  initials via a capture-phase error listener — the same trick `live.js`
  uses, so a dead third-party image never breaks the layout.
- Logos now render in: the home standings rows, the Teams dropdown (desktop
  + mobile menus), team page headers (large), and the Playoffs page
  (champion banner + Final Standings team column). Rivalries was skipped on
  purpose: it is an all-time, owner-keyed matrix and a per-season logo would
  show the wrong year's image.
- `abbrev` is carried in the JSON for future use; no UI needed it (names and
  initials cover every display site).
- Verified: 211 unit tests OK; `node --check` on the new script; double
  build byte-identical (determinism); Playwright pass over home/team/playoffs
  in both themes at 1440 + 390 — including the real dead-logo case (a dead
  imgur URL from 2019-era teams falls back to its initials square), and a
  functional check that an injected dead logo is swapped for its initials.
  Screenshots in `screenshots/logos-check/`.
