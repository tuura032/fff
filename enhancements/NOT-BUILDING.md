# Explicitly not building

From the 2026-09-22 outside consult, recorded so it doesn't get
re-litigated:
- a database (see `SPEC.md` §6)
- a JS framework
- user accounts/login
- live in-game scoring
- ESPN-beating projections
- unit tests for template rendering (the screenshot baseline is the right
  tool for that)

*Amended 2026-09-28:* live in-game scoring is allowed on **one page** only
(ENH-029, `live.html`), and it runs in the browser. Everything else stays
daily, static and computed in Python.
