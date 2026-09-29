# ENH-032 — Multi-league support

Status: open · Category: multi-league

**Sequence this last.** It's real work, but lower payoff than the content
and UX items, and everything unblocking it is already done: the playoff
count comes from settings, and there's no more 12-team hardcoding.

The app is a handful of hardcoded constants away from supporting more than
one league. Most of the values it needs are already in the fetched JSON:

- **League ID and name:** the ID is hardcoded in `fetch.py` and `compute.py`,
  and the literal league name in 9 templates. Move them to config, and use
  `mSettings.settings.name`, which is already fetched but unused for this.
- **Layout:** `docs/<league>/<season>/`, with a league picker next to the
  season picker.
- **Config:** a `leagues.yml` that maps league ID to display config, looped
  the same way seasons already are (the L9 pattern, one level up).

(This was the unnumbered "Open — multi-league" section of the old
`ENHANCEMENTS.md`, numbered when the backlog was split into files.)
