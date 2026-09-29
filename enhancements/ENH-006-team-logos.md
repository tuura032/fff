# ENH-006 — Team logos on the rest of the site

Status: open · Category: content & features

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
