"""FantasyPros consensus ranks: rest-of-season, dynasty, weekly K and D/ST.

Each page embeds `var ecrData = {...};` JSON; players[] carries
rank_ecr (overall), which model.positional_ranks makes positional. The
site asks for Crawl-delay: 5, so requests are spaced (config
"fantasyprosDelaySec", default 5) (SPEC.md §1/§3).

K and D/ST feed the "weekly" view (the main board has no FP offensive
source; the K/D/ST tables do). Dynasty rows carry player_age for the
keeper section.
"""
import time

from .common import SourceError, find_ecr_data, now_iso, to_int

# page key -> (view, fallback position). Position normally comes from the
# player row itself; the fallback covers a page whose rows omit it.
PAGES = {"ros": ("ros", None), "dynasty": ("dynasty", None),
         "k": ("weekly", "K"), "dst": ("weekly", "D/ST")}


def _norm_pos(value, fallback):
    v = str(value or "").strip().upper()
    if v in ("DST", "DEF", "D"):
        return "D/ST"
    if v in ("QB", "RB", "WR", "TE", "K"):
        return v
    return fallback


def parse_page(text, view, fallback_pos=None):
    """One FantasyPros page -> rank rows (pure; tested)."""
    data = find_ecr_data(text)  # raises SourceError on missing structure
    rows = []
    for p in data["players"]:
        row = {
            "source": "fp",
            "view": view,
            "pos": _norm_pos(p.get("player_position_id"), fallback_pos),
            "name": p.get("player_name"),
            "team": p.get("player_team_id"),
            "bye": to_int(p.get("player_bye_week")),
            "injury": None,
            "rank": to_int(p.get("rank_ecr")),
            "opponent": p.get("player_opponent"),
            "stats": None,
        }
        age = to_int(p.get("player_age"))
        if age is not None:
            row["age"] = age
        rows.append(row)
    return rows


def fetch(client, cfg, season):
    urls = cfg["urls"]["fantasypros"]
    delay = int(cfg.get("fantasyprosDelaySec", 5))
    rows = []
    raw = {}
    for i, (key, (view, fallback)) in enumerate(PAGES.items()):
        if i:
            time.sleep(delay)  # robots.txt Crawl-delay: 5
        text = client.get(urls[key]).text
        raw[key] = text
        rows.extend(parse_page(text, view, fallback))
    if not rows:
        raise SourceError("fantasypros: no players parsed from any page")
    return {"fetchedAt": now_iso(), "raw": raw, "rows": rows, "notes": []}
