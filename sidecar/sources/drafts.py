"""ESPN draft history: auction prices and keeper flags, 2019 onward.

The mDraftDetail view is public (no login) and covers every season from
2019; 2018 is a different ESPN format and is not fetched. Each pick carries
the player id, the auction bid and a keeper flag -- the raw material for
the Keepers tab's next-season price (model.keeper_price, ENH-037).

A finished draft never changes, so each past season is cached permanently
in cache/draft-<season>.json and fetched exactly once; only the current
season re-fetches on the normal refresh. A failed fetch keeps the last
good cache/drafts.json and shows the warning chip (SPEC.md §3).
"""
from pathlib import Path

from .common import Cache, SourceError, now_iso

# First season with the modern pick format; the site's data starts here too.
EARLIEST = 2019


def url(cfg, season):
    return (cfg["urls"]["espn"].format(season=season, leagueId=cfg["leagueId"])
            + "?view=mDraftDetail")


def parse_picks(response):
    """One mDraftDetail response -> {playerId: {"bid", "keeper"}}.

    Raises SourceError when the structure is missing -- a layout change is
    a source failure (warning chip), never an empty draft.
    """
    picks = ((response or {}).get("draftDetail") or {}).get("picks") or []
    if not picks:
        raise SourceError("drafts: mDraftDetail response has no picks")
    out = {}
    for p in picks:
        pid = p.get("playerId")
        if pid is None:
            continue
        out[int(pid)] = {"bid": p.get("bidAmount"),
                         "keeper": bool(p.get("keeper"))}
    return out


def fetch(client, cfg, season, cache_dir=None):
    """Every season from 2019 to the current one.

    Past seasons: read from the permanent cache, fetched once if missing.
    The current season: always re-fetched. Returns the source payload with
    "raw" (per-season picks), "picks" (per-player index) and "seasons".
    """
    cache = Cache(cache_dir or Path(__file__).resolve().parents[1] / "cache")
    per_season = {}
    for s in range(EARLIEST, season):
        per_season[s] = cache.load(f"draft-{s}")
        if per_season[s] is None:
            per_season[s] = parse_picks(client.get(url(cfg, s)).json())
            cache.save(f"draft-{s}", per_season[s])
    per_season[season] = parse_picks(client.get(url(cfg, season)).json())

    picks = {}
    for s, season_picks in per_season.items():
        for pid, pick in season_picks.items():
            # int(): cached seasons carry string keys, live picks ints.
            picks.setdefault(int(pid), {})[str(s)] = pick
    return {
        "fetchedAt": now_iso(),
        "raw": {str(s): v for s, v in per_season.items()},
        "picks": {str(pid): v for pid, v in
                  sorted(picks.items(), key=lambda kv: int(kv[0]))},
        "seasons": sorted(per_season),
        "rows": [],  # not a rank source
        "notes": [f"seasons {EARLIEST}-{season}, {len(picks)} players with picks"],
    }