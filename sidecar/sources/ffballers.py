"""The Fantasy Footballers weekly projections, per analyst.

Each position page embeds two different payloads (verified live 2026-09-29):

- the main array, one row per player per analyst with projected stats
  (``analyst_name``: Andy, Jason, Mike). Every position page carries the
  same full array; rows are de-duplicated by (player_id, analyst_id).
- on the kicker and defense pages only, a second `let data = [...]` array
  of ranked K/D rows. These rows carry per-analyst rank fields (``andy``,
  ``jason``, ``mike``) and no projections, so per SPEC.md §3 K and D use
  the page's own order -- the per-analyst ranks are passed straight
  through, and the UI says so.

Rows with projections go to model.project_points; the K/D rank rows pass
``rank`` instead (COORDINATION.md).
"""
import model
from .common import (SourceError, find_data_arrays, find_projection_array,
                     now_iso, to_int)

# Full position names are the working slugs (verified live; short forms like
# "rb" 404).
SLUGS = ("quarterback", "running-back", "wide-receiver", "tight-end",
         "kicker", "defense")

# analyst_name (lowercased) -> rank-source key.
ANALYSTS = {"andy": "ffb-andy", "jason": "ffb-jason", "mike": "ffb-mike"}

# The projected-stat fields the page carries that model.FFB_STATS can score;
# imported from model so the two can't drift.
STAT_FIELDS = tuple(model.FFB_STATS)


def fetch(client, cfg, season):
    url = cfg["urls"]["ffballers"]
    pages = {}
    for slug in SLUGS:
        pages[slug] = client.get(url.format(season=season, pos=slug)).text
    return parse(pages, season)


def parse(pages, season=None):
    """Build the FFB payload from {slug: page text} (pure; tested)."""
    notes = []
    main = {}
    for slug, text in pages.items():
        arr = find_projection_array(text)
        if arr is None:
            continue
        for r in arr:
            key = (r.get("player_id"), r.get("analyst_id"))
            main.setdefault(key, r)
    if not main:
        raise SourceError("ffballers: no projection array found on any page")

    rows = []
    for row in main.values():
        analyst = str(row.get("analyst_name") or "").strip().lower()
        key = ANALYSTS.get(analyst)
        if key is None:
            continue  # a new/renamed analyst shows up as no rows, not junk
        rows.append({
            "source": key,
            "view": "weekly",
            "pos": str(row.get("fantasy_position") or "").upper(),
            "name": row.get("name"),
            "team": row.get("team"),
            "bye": to_int(row.get("bye_week")),
            "injury": row.get("injury_status"),
            "rank": None,
            "stats": {k: row.get(k) for k in STAT_FIELDS if k in row},
        })

    for slug, want, pos in (("kicker", "K", "K"), ("defense", "D", "D/ST")):
        text = pages.get(slug)
        ranked = []
        if text:
            for arr in find_data_arrays(text):
                ranked.extend(r for r in arr
                              if isinstance(r, dict)
                              and str(r.get("fantasy_position")) == want
                              and r.get("rank") is not None)
        if not ranked:
            notes.append(f"{slug} page: no ranked rows found "
                         f"(page layout may have changed)")
            continue
        seen = set()
        for r in ranked:
            pid = r.get("player_id")
            if pid in seen:
                continue
            seen.add(pid)
            for analyst, key in ANALYSTS.items():
                rank = to_int(r.get(analyst))
                if rank is None:
                    continue
                rows.append({
                    "source": key,
                    "view": "weekly",
                    "pos": pos,
                    "name": r.get("name"),
                    "team": r.get("team"),
                    "bye": to_int(r.get("bye_week")),
                    "injury": None,
                    "rank": rank,
                    "stats": None,
                })

    return {
        "fetchedAt": now_iso(),
        "raw": {slug: text for slug, text in pages.items()},
        "rows": rows,
        "notes": notes,
    }
