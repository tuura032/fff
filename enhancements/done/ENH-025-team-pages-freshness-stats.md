# ENH-025 — Team pages + data freshness + missing stats

Status: done

Team pages + data freshness + missing stats — done
2026-09-28. One page per team per season: a `team.html` index linking
every team, and `team/<teamId>.html` with a one-line header (rank, dual
points, record, PF/PA, final rank), a weekly score line chart with the
score-to-beat line (Chart.js 2.7.1 config, theme-aware), a 2/1/0
dual-points chip per week, linked schedule
and separate postseason tables, and this-season H2H vs. every other team.
Team names link to their pages from every table that shows them. Footer
"Data through week N · updated …" freshness line (absolute date in HTML,
relative in the browser) with a workflow-dispatch "Run an update now" link
— this closes ENH-015. `compute.py` now keeps the old `updated` stamp when
the data didn't change, so the daily bot doesn't churn `docs/`. Stats page
gained Pts in losses, Heartbreaks (losses by under 5), Blowouts (wins by
50+), full decimals, regular season only. Verified: unit tests pass; a
second build changes nothing in `docs/`; Playwright light/dark and
desktop/mobile checks show no console errors, no 404s, no horizontal page
scroll at 390px (tables scroll inside their own containers, as everywhere
else on the site).
- *Corrected 2026-09-28 in review:* this entry originally said the header
  had stat tiles with all-play % and that the chart was a win/loss bar
  chart. Neither shipped; they're now ENH-026. The season picker and logo
  link are broken on team pages: BUG-010.
