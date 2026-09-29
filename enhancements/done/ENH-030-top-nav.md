# ENH-030 — Top nav with grouped menus; Teams dropdown replaces the Teams page

Status: done 2026-09-28 · Category: polish & UX

**Why:** the owner prefers the top nav from the thinkingcap prototype
(`D:\Workspace\ff-scoring-app-thinkingcap3.8-27b`: brand on the left, a few
nav items in the middle, controls on the right). It gives every page the
full width back from the 224px sidebar. Ten sidebar items are too many for a
top bar, so group them. The Teams index page (`team.html`) exists only to
pick a team, which a dropdown does in one click, so it goes away.

Do this before ENH-031 (live page layout). That page's design depends on
the width this frees up.

## The nav

**Home · Live ● · Teams ▾ · Playoffs · Stats · All-time ▾**

- **Live ●:** keep the existing rule, root season only, with the red dot.
- **Teams ▾:** the current "Owners" accordion list, renamed. One row per
  team in standings order: rank, **team name** (bold), owner short name
  (small, muted). Each row links to that team's page (`team/<id>.html`). Show
  all rows with **no inner scrollbar**; today's `max-h-64 overflow-y-auto`
  shows 6 of 12. Mark the current team's row when you're on its page.
- **All-time ▾:** Career Stats, Rivalries, Kickers (Kickers only when
  `kicker_stats`, as now).
- **League Info** moves out of the nav into the footer, as a plain link next
  to the "Data through week N" line.
- **Season picker:** a compact select on the right of the header, next to
  the theme toggle.
- **Header tagline:** "DUAL-POINT STANDINGS, RANKINGS, AND STATS" gives up
  its center slot to the nav. Move the text under Home's page heading as a
  subtitle.

## Where it goes

- **Desktop (`md` and up):** the nav goes in the existing fixed header
  (`<header>` in `layout.html`). Delete the `<aside>` sidebar, and drop the
  `md:pl-60` offsets from `<main>` and `<footer>`. Content can use a
  comfortable max width (the prototype uses about 1100px, centered).
- **Mobile:** keep a single horizontally scrolling nav row under the header.
  **Watch out:** a dropdown panel rendered *inside* an `overflow-x-auto` row
  is clipped by it. On mobile, open Teams and All-time as a full-width panel
  below the nav row, outside the scroller, not as an absolutely positioned
  popover inside it.

## Dropdown behavior

- Use a `<button aria-expanded aria-controls>` toggle, as the owners
  accordion does today. Reuse its JS.
- Clicking outside or pressing Esc closes it. Only one menu is open at a
  time.
- The parent item shows as active when you're on any page inside it (Teams
  on `team/<id>.html`, All-time on careers/rivalries/kickers).

## Removing the Teams index

- Stop emitting `team.html` in `build.py` (the index emit, not the
  per-team pages).
- `build.py` doesn't delete stale HTML, so `git rm` the existing
  `docs/team.html` and `docs/<season>/team.html` files.
- Grep templates for links to `team.html` and repoint or remove them. The
  season picker on a team page keeps pointing at `team/<id>.html` (BUG-010
  behavior).

## Keep

- Every page must work from both depths, so use `root_prefix` on every new
  link (see BUG-010).
- The site must stay deterministic.
- New Tailwind utility classes need an `app.css` rebuild (README
  "Frontend").
- Owner names in the Teams dropdown are fine (the sidebar shows them today).
  The live page shows team names only, but that rule is about the live page,
  not the nav.

## Done when

- Playwright, light/dark × desktop (1440) / mobile (390), on Home, a
  current-season team page, a 2019 team page, Stats and Live:
  - no console errors, and no horizontal page scroll;
  - both dropdowns open, show every item, and close on outside click/Esc;
  - on mobile, the dropdown panels aren't clipped.
- Resolve every nav link, footer link and season-picker option on a team
  page and a flat page with `new URL(href, location.href)`, and expect a 200
  response. This is the check that caught BUG-010.
- A second `build.py` run changes nothing in `docs/`.
- Screenshots of before/after for the owner.

## Shipped

The sidebar is gone; every page now carries the top nav
**Home · Live ● · Teams ▾ · Playoffs · Stats · All-time ▾** in the existing
fixed header, with the season picker as a compact select beside the theme
toggle and League Info in the footer next to the "Data through week N"
line. The Teams dropdown lists all 12 teams in standings order (rank, team
name, muted owner short name, current team's row marked) with no inner
scrollbar; All-time holds Career Stats, Rivalries and Kickers
(conditional, as before). Mobile keeps one horizontally scrolling nav row,
and Teams/All-time open as full-width panels below the row, outside the
scroller, so they never clip. Menus are `aria-expanded`/`aria-controls`
buttons reusing the old owners-accordion JS: outside click and Esc close,
one menu open at a time, the parent item is active on its pages. The header
tagline moved under Home's page heading as a subtitle (both the
current-season and past-season variants). `build.py` no longer emits the
Teams index, the old `docs/team.html` / `docs/<season>/team.html` files were
removed, and every nav/footer/picker href carries `root_prefix` (plus
`base`), so all links resolve at both depths.

Verified: `python -m unittest test_compute` 208/208; a Playwright pass over
light/dark × desktop (1440) / mobile (390) on Home, a current-season team
page, a 2019 team page, Stats and Live found no console errors and no
horizontal scroll, confirmed both dropdowns (open, 12 rows, close on
outside click/Esc, one at a time, mobile panels not clipped), and fetched
every nav/footer/picker link at both depths (all 200). Two consecutive
`build.py` runs with the gate digest preserved produced byte-identical
`docs/` trees. Before/after screenshots in `screenshots/enh030/` (14
shots); the site resolves its theme from `localStorage['theme']` and
ignores the browser color scheme, so the shooting script pins the theme
explicitly per shot.
