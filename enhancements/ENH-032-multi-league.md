# ENH-032 — Multi-league: one codebase, a gated URL per league

Status: open (**blocked** on the privacy decision below; ENH-034 isn't) ·
Category: multi-league

The owner runs about five ESPN leagues and wants the app to serve all of
them. It was shelved in error on 2026-09-29 and revived the same day.

## Decided (owner, 2026-09-29)

- **One codebase, not five copies.** A fix or feature lands once and every
  league gets it. With copies, the ~15 fixes of 2026-09-27/28 would have
  been made five times.
- **ESPN only.** Other platforms aren't in scope.
- **FFF is the only dual-point league.** The others use standard ESPN
  standings. `scoring` becomes a per-league setting (`dual` or `standard`),
  and everything dual-specific is shown only for `dual` (dual points, score
  to beat, top-half stats). Rivalries, careers, team pages, kickers, prizes
  and history still apply to every league.
- **FFF is the only public league.** The others are private ESPN leagues:
  fetching them needs the `espn_s2` + `SWID` cookies, stored as repo
  secrets, never committed.
- **A URL per league, each with its own passphrase**
  (`…/fff/`, `…/<league-slug>/`). The passphrase **unlocks**; it doesn't
  **select**. Reasons:
  - A link shared in a group chat goes to the right league.
  - Each league's phrase can be changed without touching the others.
  - A typo shows "wrong phrase," not someone else's league.
  - The mapping from phrase to league never has to exist anywhere.

  Use an unguessable slug if a league's name shouldn't show in its URL.

## The blocker: today's gate doesn't protect anything

The repo is **public**, and the gate is cosmetic (`layout.html`: "the gate
only hides the content visually, since the HTML ships either way"). The raw
ESPN payloads are committed in `data/`. That's fine for FFF, which is
public on ESPN anyway. For a private league it would publish the league's
data to anyone who looks. So before any private league goes on this site,
pick one:

1. **Real encryption behind the passphrase** (recommended). Keeps the
   no-accounts model and GitHub Pages. `build.py` encrypts each private
   league's pages (AES-GCM, key from the league phrase via PBKDF2; the
   "staticrypt" approach), so the published HTML is unreadable without the
   phrase. The private league's raw and computed data must not be committed
   in plain text either. Either fetch all seasons fresh on each bot run (a
   few requests per season), or commit it encrypted. Cost: moderate build
   work; a forgotten phrase means rotating it and rebuilding; and the live
   page can't work for private leagues (the browser has no ESPN login).
2. **A private repo plus a host with real access control,** for example
   Cloudflare Pages + Cloudflare Access: free for small groups, and members
   log in with an emailed one-time code. Strongest protection and no crypto
   code, but it introduces per-person email lists (a light form of "users")
   and moves hosting off GitHub Pages.
3. **Ask each league to make itself public on ESPN.** No new code: the
   current model works as is. The owner is asking; any league that says yes
   skips this blocker.

## Sequence

1. **ENH-034:** move FFF's values into `leagues.json` with no output change.
   Not blocked.
2. **Per-league layout:** `data/<slug>/…`, `docs/<slug>/…` (FFF moves under
   `docs/fff/`, with a redirect from the current root URLs so existing links
   keep working), a gate per league, and `scoring: standard`. It needs a
   spec once the blocker is decided, because option 1 changes what gets
   committed.
3. **Private-league fetch** (cookies from secrets), then onboard leagues one
   at a time.

## Still true from the original note

`mSettings.settings.name` is already fetched and can supply each league's
display name. The season loop in `build.py` (the L9 pattern) is the model
for the league loop, one level up.
