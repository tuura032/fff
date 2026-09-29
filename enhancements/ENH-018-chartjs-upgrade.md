# ENH-018 — Vendor/pin Chart.js and upgrade off 2.7.1

Status: open · Category: polish & UX

Chart.js 2.7.1 is about 9 years old and loaded from the cdnjs CDN.

**Already done:** it's no longer loaded on every page. `layout.html` loads it
only for `graph.html`, and `templates/team.html` loads its own copy.

**Remaining:**
- Vendor a pinned copy under `static/`, so charts work if the CDN is
  unavailable.
- Load it from one place (the two script tags are duplicated today).
- Optionally upgrade to v4. Both charts (`graph.html` and the team page) use
  the v2 config API (`scales.xAxes`/`yAxes`, `tooltips`), which v3+ silently
  ignores, so an upgrade means rewriting both configs and a visual check.
