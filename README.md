# LeagueStats

Standings page for **FFF** ("Fantasy Football Fantasy", ESPN league
`877873`) that computes a scoring system ESPN cannot compute itself.

v1 (2018–19) was Flask + Postgres on Heroku. It died when Heroku dropped free
Postgres. The frontend survived — only the data layer is replaced here: three
small Python scripts feed the same templates, and the result is a static site
on GitHub Pages. No database, no server, no secrets.

Live site: <https://tuura032.github.io/fff/> — standings
(click a column header to sort), playoffs and prizes, and a weekly-scoring
chart.

## The scoring rule

Each week, every team can earn up to **2 points**:

| Point | Condition |
| --- | --- |
| 1 | Win your head-to-head matchup |
| 1 | Finish in the **top half** of the league in raw points that week |

Twelve teams, six matchups, so each week distributes 6 H2H points and 6
top-half points. ESPN shows W/L and points-for and leaves the second point
uncomputed — that gap is the product.

**Top half** is decided by the *score to beat*: sort the weekly scores
ascending; index `[n // 2 - 1]` is the threshold — the highest score that
missed the top half (index `[5]` for this 12-team league). A team earns the
point by scoring **strictly greater** than it.

Ties (matching v1's strictly-greater comparison):

- Exact H2H tie → no point to either team.
- Exact tie at the top-half boundary (6th and 7th identical) → no point to
  either, so the league awards 5 top-half points that week rather than 7.

**Regular season only.** Dual points stop after week `matchupPeriodCount`
(14) — read from the ESPN API, never hardcoded. Weeks 15–17 are the playoff
bracket and accumulate no dual points — but they *are* parsed, separately,
to record who actually won the league (see below).

## Champions

Weeks 15–17 carry ESPN's `playoffTierType`. `compute.py` reads the
`WINNERS_BRACKET` entries and records the winner of the final as that
season's champion, under a `playoffs` key on
`data/standings-<season>.json` (`null` until the final is decided).

This matters because "finished #1 in the regular season" and "won the
league" are different things and the site used to conflate them — Career
Stats counted regular-season firsts and called them titles, which named
the wrong owner for four of the five seasons on file. **Titles** 🏆 and
**Reg #1** are now separate columns.

Standings sort by total points, then points-for.

## Stats, records and awards

The Stats page is built entirely from the weekly scores already on file —
no extra ESPN call, nothing stored beyond `standings-<season>.json`.

- **All-play record** — your record if you had played every other team
  every week, i.e. the schedule removed. The gap between it and your real
  record is the cleanest measure of schedule luck, and it is the continuous
  version of the league's own top-half point.
- **Swing** — standard deviation of weekly scores.
- **Robbed / Stole It** — weeks scoring top-half and losing, and weeks
  winning from the bottom half.
- **Season records** — biggest blowout, closest game, high and low scores,
  best score in a loss, worst score in a win, highest and lowest combined.
- **Season awards** — eleven named superlatives, ties shown as co-winners.

Owners are shown by first name where that's unambiguous across every season
on file, and by full name where it isn't (this league has two Daniels).
Team names appear as a second line under the owner on the standings table:
teams get renamed every year, the people don't, so the person is the
identity the site leads with.

Awards are computed by fixed rules and are **not randomised**: `build.py`
must stay deterministic so the daily workflow commits only when the data
actually changed.

## Kickers

The one page nobody asked for. Every kicker ever **started** in this league,
2019 on, ranked by the points they actually put on somebody's board —
bench points don't count, because the joke is that these are points an owner
looked at their lineup and chose. Same data cut by owner (who the position
has been kind to), each season's leading leg, and a trophy case: the best
week ever, the donut king, the longest owner-kicker marriage, the kicker who
has played for more of this league than most of its owners.

There is no "worst week ever" trophy. It would always be a 0.0, and the
league has seventeen of those — the winner would just be whichever zero
sorted first. The donut count does that job with a real number behind it.

It runs off `data/starters-<season>.json`, which is also the groundwork for
anything else lineup-level — matchup cards, weekly recaps, optimal-lineup
regret. Kickers are about 7.7% of every point this league has ever started.

## Prize money

`data/prizes.json` holds the pot. Each prize names the result it pays on —
`standings` (regular-season dual-point rank), `finalRank` (placement after
the playoffs), `regSeasonPF`, `playoffsPF` — so `compute.resolve_prizes()`
can fill in every line without the template knowing the rules.

The file is a `default` list plus optional per-year overrides
(`"2022": [...]`), because a league's pot changes and applying today's
structure to an old season would invent history.

Two views, one resolver:

- **Prize Distribution** — who won each prize line. Titled "Projected"
  only while something is still undecided.
- **Payouts** — the same money ranked by who took it home, because
  **winning the title is not the same as winning the most**. In 2025 the
  champion took $135, but the owner who finished 2nd collected $115 by
  stacking the regular-season prizes.

**Net** is winnings minus the entry fee (`financeSettings.entryFee`, which
times the league size is exactly the pot). Career Stats carries an all-time
winnings table — total, net, and a column per season. A championship does
not guarantee you are up: one owner has a title and is still net −$10.

## How it works

```
fetch.py     ESPN API → data/raw-<season>.json      3 public calls, 1s apart
fetch.py --starters                                 1 call per week (box scores)
             ESPN API → data/starters-<season>.json every started player
compute.py   raw  → data/standings-<season>.json    the dual-point math
build.py     standings + templates/ → docs/         static render, no server
```

Head-to-head records on the Rivalries page count **the postseason as well as
the regular season** — a record that calls itself all-time has to include
playoff meetings. A dot marks pairings that have met in the playoffs; hover
a cell for the split.

`compute.py` and `build.py` never touch the network, so they re-run offline
against a committed raw file. The JSON files are the source of truth — diff
two commits to see exactly what moved.

## Local development

Python 3.11+. Dependencies: `requests`, `jinja2` — that's it for the data
pipeline.

```
pip install -r requirements.txt

python fetch.py --season 2026     # --season defaults to the current year
python fetch.py --season 2026 --starters   # started lineups (Kickers page)
python compute.py --season 2026
python build.py --season 2026
```

`--starters` is one request per week rather than three per season, so it is a
separate call. It only asks for weeks it does not already have and stops at
the first one that has not been played — a full backfill of a new season is
~17 requests, an in-season top-up is one or two.

Or via the task runner (stdlib only, no extra dependency):

```
python tasks.py all        # recompute every season on file, rebuild, test
python tasks.py build      # just re-render docs/
python tasks.py refresh    # fetch this season too (hits the network)
python tasks.py test
```

Open `docs/index.html` in a browser.

### Frontend (Tailwind CSS)

The site is styled with Tailwind CSS, compiled at dev time from
`src/tailwind.css` to `static/css/app.css`. That compiled file **is
committed** — GitHub Pages has no build step, so `static/` has to be
served as real files, same as `static/js/hello.js`. Only needed after
editing a template's class names or `src/tailwind.css`:

```
npm install
npm run build:css      # one-shot
npm run watch:css       # rebuilds on save, for template work
```

Rebuild it and re-run `python build.py` before committing a template
change, or the deployed CSS won't match the markup.

Tests (the dual-point math — the only file with real logic):

```
python -m unittest test_compute -v
```

`build.py` output is deterministic (no timestamps), so a rebuild changes
`docs/` only when the data changes.

## Names and the league phrase

This repo is **public** — free GitHub Pages requires it — so everything in
`data/` and `docs/` is world-readable. Two things follow from that.

**Surnames are redacted on write.** `fetch.redact_members()` truncates every
`lastName` to three characters before the raw file is saved, applies the same
truncation inside `displayName` (some members set theirs to their full name),
and swaps a surname out of any team named after its owner — "Team
Hildebrandt" becomes "Team Ethan", using the first name so it still reads
like a team name. The site shows first names alone unless two owners collide,
in which case each gets the shortest prefix that separates them:
"Daniel Se." and "Daniel Sh.". See `SPEC.md` §3.

Note this stopped the ongoing exposure; it did not rewrite history. Commits
made before 2026-09-23 still carry full surnames.

**A shared phrase gates the site.** Set a repository secret named
`LEAGUE_PHRASE`; the workflow passes it to `build.py`, which bakes only its
SHA-256 into the pages. The phrase itself is never committed. With the secret
unset the gate is omitted entirely, so a local `python build.py` still
produces a browsable site.

Be clear about what the gate is: the page content ships inside the HTML
either way, so it keeps out passers-by, not anyone willing to open devtools.
It is a doorbell, not a lock. That is an acceptable trade here precisely
*because* the surnames are already gone — there is nothing behind it worth
the effort.

`LEAGUE_PHRASE_SHA256` can be set instead, to rebuild the site identically
without knowing the phrase (the digest is public in the deployed page
anyway). Without it, anyone rebuilding locally would ship a gate-less site.

That is not hypothetical — it happened on 2026-09-23, during unrelated work,
and `git add -A` committed the result. So `build.py` now reads the digest
back out of `docs/index.html` and **refuses** to build when doing so would
remove a live gate, printing the command to recover:

```
ERROR: docs/ is currently gated but no passphrase is set, so this build
would strip the gate from every page.
  Set LEAGUE_PHRASE, or pass the existing digest:
    LEAGUE_PHRASE_SHA256=<digest> python build.py
  If removing the gate is intended, re-run with --no-gate.
```

**Staying out of search results.** The gate only hides content visually, so
a crawler would happily index straight through it. Two things stop that:

- `<meta name="robots" content="noindex, nofollow">` on every page. This is
  the one that works — it is read per page.
- `docs/robots.txt`. Largely symbolic today: a crawler only looks for
  `robots.txt` at a *domain* root, and this site lives on a subpath
  (`user.github.io/repo/`), so the file is never requested. It is there so
  the protection holds if a custom domain is ever added.

### Custom domain

Custom domains *are* available on GitHub Free with a public repo (the plan
restriction is on Pages from **private** repos, not on domains).

Put the bare host in `data/domain.txt` — one line, no scheme, no trailing
slash — and `build.py` writes it to `docs/CNAME` on every build:

```
fff.example.com
```

Setting a custom domain in repo Settings also makes GitHub commit a `CNAME`
file itself, but `docs/` is regenerated and re-committed every morning by
the workflow, so keeping the domain in `data/domain.txt` makes it explicit
and reproducible rather than a file nobody's build knows about. If a
`docs/CNAME` shows up without `data/domain.txt`, the build prints a note
rather than clobbering it.

DNS, per GitHub's docs:

| Type | For | Record |
| --- | --- | --- |
| `CNAME` | `www` or any subdomain (recommended) | `tuura032.github.io` |
| `A` | apex (`example.com`) | `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` |
| `AAAA` | apex, IPv6 | `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153` |

A subdomain is the more stable choice: the apex A records are GitHub server
IPs and can change, while the `CNAME` target never does. Tick **Enforce
HTTPS** in Settings once the certificate is issued, and verify the domain
(Settings → Pages → *Verify*) to prevent takeover if the site is ever
disabled.

**A custom domain also makes `robots.txt` start working**, since the site
would finally be at a domain root where crawlers actually request it.

**Do not make the repo private.** GitHub Free lists Pages as "GitHub Pages in
public repositories" — going private disables Pages and the site 404s. On a
paid plan Pages keeps working from a private repo, but the published site is
*still public*: per GitHub's docs, publishing a Pages site privately needs an
organization account on GitHub Enterprise Cloud. Private repo buys nothing
here, which is why the names are stripped at the source instead.

## Deployment

GitHub Pages serves `docs/` from the `main` branch. A GitHub Actions workflow
runs hourly on game nights (Sunday 1–11pm, Monday and Thursday 6–11pm and
midnight, ET) and daily at 8am, plus on manual dispatch from the Actions UI:
fetch → compute → build, then **commits only if the rendered site (`docs/`)
changed** — data-only churn such as live in-game scores does not commit.
Hourly on game nights: ESPN finalizes scores shortly after the final
whistle, and the daily run absorbs ESPN's stat corrections for a day or two
after games.

**Known limitation:** GitHub disables scheduled workflows on public repos
after **60 days of repository inactivity**. In-season the job commits
regularly and stays alive; February–August it goes dormant and needs one
manual re-enable each August.

## Files

| Path | What |
| --- | --- |
| `fetch.py` | ESPN API → `data/raw-<season>.json` (verbatim, no transform); `--starters` → `data/starters-<season>.json` (started lineups, trimmed subset) |
| `compute.py` | raw → `data/standings-<season>.json` (the dual-point math + playoff bracket), plus the render-time rivalry/career/season-stats derivations |
| `build.py` | renders `templates/` to `docs/`, copies `static/` |
| `test_compute.py` | unit tests for the scoring rule |
| `data/` | committed raw + computed JSON per season |
| `data/starters-<season>.json` | every started player, week by week (`fetch.py --starters`) — what the Kickers page ranks |
| `data/prizes.json` | the league pot — labels, amounts, and which result each prize is awarded on (`default` list, plus optional per-year overrides) |
| `tasks.py` | one-command wrappers for fetch/compute/build/test |
| `docs/` | the rendered static site (what Pages serves) |
| `AGENTS.md` | agent working protocol + repo map — read this first |
| `SPEC.md` | architecture reference — scoring rule, data schema, decisions |
| `enhancements/` | the backlog, one file per item; shipped items in `enhancements/done/` (see `enhancements/README.md`) |
| `BUGS.md` | defect log |
