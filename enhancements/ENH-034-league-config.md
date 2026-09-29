# ENH-034 — Move FFF's league-specific values into one config file (no output change)

Status: open · Category: multi-league

First step of ENH-032. Pure refactor. **The acceptance test is that the
site doesn't change.**

**Why now:** the league is hardcoded in about 20 places, and every new
feature adds more. Pulling the values out while they're few is cheap, and it
can be verified exactly. It doesn't depend on the multi-league hosting
decision in ENH-032.

## Build

- **`leagues.json`** at the repo root. It's JSON because `requirements.txt`
  stays `requests` + `jinja2`. It holds a list with one entry for now:
  ```
  {"slug": "fff", "espnLeagueId": "877873", "name": "Fantasy Football Fantasy",
   "scoring": "dual", "public": true, "live": true, "prizes": "data/prizes.json"}
  ```
- **A small loader** (e.g. `league_config.py`, stdlib only) that returns the
  entry for a slug, defaulting to `fff`.
- **Replace the hardcoded values:**
  - `LEAGUE_ID` in `fetch.py` and `compute.py`;
  - the literal league name in the templates (13 of them contain
    "Fantasy Football Fantasy"). Pass it in the render context once from
    `build.py`, and don't repeat it per template;
  - the prizes path;
  - the league ID in `static/js/live-core.js`. `live.js` should read it from
    something `build.py` emits, not a JS constant.
- **`scoring` and `live` are read but only `"dual"` and `true` are
  implemented.** Any other value should raise a clear "not implemented yet"
  error. Don't build standard scoring here.
- Leave the League Info page's keeper pricing, the reseeding rule, and the
  data/docs folder layout alone. Those are later steps.

## Done when

- `git diff --stat` on `data/` is empty, and on `docs/` it's empty, except
  where the league ID now reaches `live.js` through a new field (list the
  exact files and lines in the commit message; nothing else may change).
- `grep -rn 877873` outside `leagues.json`, tests and `data/` finds nothing.
- Tests (Python and Node) pass. `python tasks.py check` passes (ENH-033).
