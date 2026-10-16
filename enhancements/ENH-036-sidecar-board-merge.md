# ENH-036 — Sidecar: one board (merge Waivers + Rankings)

Status: open · Category: polish & UX

Scope: `sidecar/` only. The public site is untouched.

## Problem

The waiver board's two home tabs split one decision in two. **Waivers**
(home) lists who is claimable, sorted by Owned %, with no quality signal. The
owner says it has "never actually been helpful". **Rankings** has the quality
signal, but the owner has to go there to find out who is worth a claim. It
also has confusing controls: an "Available only (FA + waivers)" checkbox, and
on the Waivers tab an "FA + waivers" dropdown. Both ask the same question
(who is available?) in different words, and neither says what the values
mean.

It is one table of players with different columns. The owner's workflow is
"who can I claim, and who is worth it", and that belongs in one view.

## Decisions already made (do not re-litigate)

- **One board replaces both tabs.** Nav becomes **Board · K & D/ST · My Team
  · Look back**. Board is the home tab. There is no Waivers tab.
- **A player is available or not.** Wording is "Available" everywhere. The
  string "FA + waivers" must not appear anywhere in the UI.
- **FA vs WA is a status shown on each row**, not a separate filter. FFF's
  claim window follows the week:
  - Sun–Tue: everyone dropped or unrostered is on the waiver list, so WA
    carries no special meaning.
  - Wed–Sat: only players dropped that week (or after TNF) are WA, so a
    midweek WA is itself the "just dropped" signal.
  - FA: a free agent, not on the claim list.
  Both are claimable. There is no separate "just dropped" feature, because
  a WA badge already means it. The Status column is sortable, so WAs
  cluster when the owner wants them.
- **Ranks are per position.** "RB34" means the 34th RB, and tiers are
  computed within a position (existing behavior; do not change it).

## Design

### Controls

| Control | Values | Default |
| --- | --- | --- |
| View tabs (existing) | Weekly / Rest of season / Dynasty | Weekly |
| Position chips (existing) | All / QB / RB / WR / TE / K / D/ST | All |
| **Show** (segmented control; replaces both the checkbox and the dropdown) | Available / Rostered / All players | Available |
| Search (existing) | name | empty |
| Columns ▾ (new) | checkbox menu, see below | see below |
| Source toggles (existing) | re-rank live | all on |

- One availability control only. "Rostered" lists players on other teams and
  mine, with the owner abbreviation or "mine" in the Roster column.
- "All" on the position chips includes **only QB / RB / WR / TE**. K and
  D/ST have their own tab, and they swamp a mixed list because their ranks
  aren't comparable to other positions. The K and D/ST chips stay, so the
  owner can still look at one.
- Default sort when position is All is **Owned % descending**. It is the
  only cross-position signal in the payload (a mixed list sorted by
  position-rank average is meaningless). When a single position is chosen,
  the default sort is the board rank, as today. Click-to-sort headers keep
  working. A real cross-position comparison against the owner's roster is
  a later "Moves" item, not this one.
- The old min-owned-% input is dropped. Owned % is a sortable column.

### Status badge (Roster column)

- **WA** — tooltip: "On the claim list right now. Sun–Tue that is everyone;
  Wed–Sat it is only players dropped this week (or after TNF)."
- **FA** — tooltip: "Free agent — claim is instant."
- Rostered players keep the owner abbreviation, or **mine**.
- If the already-fetched `raw.freeAgents` response carries a waiver-clear
  date, show it like ESPN does ("WA · Fri"). **Look for it; do not guess it
  from the weekday.** It depends on the player's game day. If the field is
  not in `raw.freeAgents`, show plain WA and say so in the Shipped note.

### Columns

Rk (tier-coloured) · Player (+ injury tag) · Pos · Team · Opp · Roster/status
· per-source ranks (from the source toggles) · Avg · Sprd · Tier · Δ ·
Owned %.

Columns ▾ is a checkbox menu. Defaults: Team ✓, Opp ✓, Bye ✗, Sprd ✗,
Tier ✓, Δ ✓, Owned % ✓. The choice persists in localStorage under
`waiverboard.cols` and survives a reload (wrap storage access in try/catch).
Δ's header tooltip must say what it is: the average rank change since the
last snapshot (it already carries `moversSince`), not an upgrade over the
owner's roster.

Optional extra column, **only if already present in the fetched
`raw.freeAgents`, with no new requests**: ownership change (ESPN's `+/-`
next to %ROST). Add it to the picker, default off. Record in the Shipped
note whether it was available.

### Unchanged

Rank math, source toggles and live re-ranking, the Unmatched panel, the
K & D/ST, My Team and Look back tabs, `server.py` and the API contract.

## Not this item

- A **Proj** (projected points) column next to rank, ESPN-style. The FFB
  analyst projections already go through `model.project_points`, but
  surfacing them needs an API change. That belongs to a later "Moves" item, so
  don't start it here.
- Anything that compares a free agent to the owner's roster (Δ vs. my slot,
  bye-week cover, add/drop pairs, keeper cost).
- Newly-available-since-last-week highlighting (snapshot infrastructure
  exists; separate item if wanted).

## Files

- `sidecar/web/index.html` — nav
- `sidecar/web/app.js` — delete `renderWaivers`, `WAIVERS_COLS`, `state.wa`;
  the board gains the Show control, the status badge, the Owned % column,
  the column picker, the position-All rule and the default sort
- `sidecar/web/app.css` — picker, segmented control, badge
- `sidecar/SPEC.md` §7 — layout section updated to match
- `enhancements/README.md` — add this item to "Next up"; on shipping, move
  this file to `done/` per the README

## Done when

- `node --check sidecar/web/app.js` is clean and
  `python -m unittest discover sidecar/tests` is green (the API is
  untouched).
- On the live server (Playwright at 1440 and 390, dark theme):
  - Default load shows the Board, Available, Owned %-sorted, with WA/FA
    badges and no K or D/ST rows.
  - Selecting QB (or any single position) sorts by board rank.
  - Rostered and All players show the right sets; no label anywhere reads
    "FA + waivers".
  - Sorting by the Status column groups WA and FA.
  - The column picker toggles columns and persists across a reload.
  - K & D/ST, My Team and Look back still work (regression pass).
- `git diff --stat` shows changes only under `sidecar/` and `enhancements/`.
- The Shipped note says whether the waiver-clear date and the ownership
  change were found in `raw.freeAgents`.
