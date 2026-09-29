# ENH-031 — Live page layout: borrow the prototype's design, keep our logic

Status: open · Category: polish & UX

**Why:** the owner finds the thinkingcap prototype's live page
(`D:\Workspace\ff-scoring-app-thinkingcap3.8-27b`, `public/live.html`,
`public/css/app.css`, `public/js/live.js`) easier to read than ours. Our
`templates/live.html` is right on the rules (strict score to beat, pinned by
the parity test); the prototype is wrong there. So change **presentation
only**. Don't touch `static/js/live-core.js` or its tests, except to add a
field the view needs.

Do ENH-030 (top nav) first. This layout assumes the full page width.

## What to take from the prototype

1. **Scoreboard cards with the teams stacked.** Each card is one matchup:
   the away team on one row, "vs" as a small divider, the home team on the
   row below. Each row has a logo, the team name and a big live score on the
   right. The footer line shows the projected scores and the game state.
   - Today's side-by-side layout truncates names ("De'Von to Brea…",
     "Ultimate Fulfill…"). Stacked rows give each name the card's full
     width. Names must not truncate at 1440px, and may ellipsize at 390px.
   - Put the win probability on each row as a percentage with a thin bar
     (the prototype's final version does this), not one combined "1% / 99%"
     bar.
   - Show three cards per row on desktop, two on tablet, one on phone.
2. **Team logos** on the scoreboard and in the tables. `live.js` already
   reads logos from the ESPN payload. If a logo fails to load, show the
   team's initials in a small rounded square (don't show a broken image).
   Keep the team **names** from the source `live.js` uses today, not ESPN's
   `name` field (which may differ).
3. **Panels with a clear hierarchy.** Each section (Scoreboard, Score to
   beat, This week's dual points, If the week ended now) sits in its own
   rounded panel with a bold heading and a one-line muted description, as in
   the prototype.
4. **Accent colors for the headline numbers.** The live score to beat in one
   accent and the projected one in another (the prototype uses yellow and
   purple). Use the same two colors for the "live" and "projected" columns
   in the tables below, so the reader learns the pairing once. Both must be
   readable in light and dark mode, so pick from the site's Tailwind palette
   and check contrast.
5. **Dual-point chips:** keep the `W` / `TOP` chips and a big 0/1/2 number,
   like the prototype's final version.

## Keep as it is

- **The rules and wording:** "Score to beat", "the highest score that missed
  the top half", and strictly-above.
- The 60 s visibility-aware polling, the "Updated Ns ago" chip and Refresh
  button (move them to the page header's right side, as in the prototype),
  the failure and empty states, the bye line, and the "If the week ended now"
  gating.
- Team names only, with no owner names on this page.
- `layout.html` inheritance: gate, nav, dark mode, and Tailwind only. Don't
  copy the prototype's CSS file; translate it into utility classes and
  rebuild `app.css`.

## Done when

- `node --test tests/live-core.test.js` and `python -m unittest
  test_compute` still pass (the logic didn't change).
- Playwright on `live.html`, light/dark × desktop (1440) / mobile (390):
  - no console errors, and no horizontal page scroll;
  - no truncated team names at 1440;
  - logo fallback works (block the logo hosts with `page.route`);
  - the ESPN-blocked state still renders.
- Before/after screenshots for the owner, taken during a live week if
  possible (Sunday afternoon), or else against a saved ESPN response served
  with `page.route`.
