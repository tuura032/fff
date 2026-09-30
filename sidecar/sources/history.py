"""Look-back data: pre-draft and past-week ranks, plus ESPN weekly actuals.

The ranks are not scraped here. They come from the owner's draft-assistant
repo (config "history.dir"), which already holds them as copy-pasted source
pages merged into JSON:

  predraft  app/data/rankings.json   Harris + FFB positional ranks (PPR)
  weekly    rankings/week-<n>.json   Harris + FFB ranks for week n

Like every source, the payload lands only in sidecar/cache/ (gitignored);
third-party ranks are never committed to this repo.

Actual points are one ESPN request: kona_player_info with
filterStatsForTopScoringPeriodIds returns every player's per-week
appliedTotal in FFF scoring (checked: all 324 started player-weeks in
data/starters-2026.json match). The response also carries last season's
weeks, so rows are kept only when seasonId is this season.
"""
import json
import re
from pathlib import Path

import model
from .common import SourceError, now_iso

# FFB's consolidated rank ("Rank" column) is its own source key: the
# per-analyst weekly keys (ffb-andy/jason/mike) are a different ranking.
SOURCE_KEYS = {"harris": "harris", "ffballers": "ffb"}
ACTUALS_FILTER = {"players": {
    "limit": 2000,
    "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
    "filterStatsForTopScoringPeriodIds": {"value": 18,
                                          "additionalValue": []}}}


def _pos(value):
    v = str(value or "").upper()
    return "D/ST" if v in ("DST", "D/ST", "DEF", "D") else v


def fetch(client, cfg, season):
    h = cfg.get("history") or {}
    if not h.get("dir"):
        raise SourceError("history: config has no history.dir")
    root = Path(h["dir"])
    pre_path = root / h.get("predraft", "app/data/rankings.json")
    try:
        predraft = json.loads(pre_path.read_text(encoding="utf-8"))
        weekly = {}
        for p in sorted(root.glob(h.get("weekly", "rankings/week-*.json"))):
            m = re.search(r"week-(\d+)\.json$", p.name)
            if m:
                weekly[int(m.group(1))] = json.loads(
                    p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceError(f"history: {exc}") from exc

    flt = json.loads(json.dumps(ACTUALS_FILTER))
    flt["players"]["filterStatsForTopScoringPeriodIds"]["additionalValue"] = [
        f"00{season}"]
    base = cfg["urls"]["espn"].format(season=season, leagueId=cfg["leagueId"])
    resp = client.get(base + "?view=kona_player_info",
                      headers={"X-Fantasy-Filter": json.dumps(flt)}).json()
    return parse(predraft, weekly, resp, season)


def predraft_rows(predraft):
    rows = []
    for p in (predraft.get("players") or {}).values():
        ranks = (p.get("ranks") or {}).get("ppr") or {}
        for src, key in SOURCE_KEYS.items():
            if ranks.get(src) is None:
                continue
            rows.append({"source": key, "view": "predraft",
                         "pos": _pos(p.get("position")), "name": p["name"],
                         "team": p.get("team"), "rank": ranks[src],
                         "stats": None})
    return rows


def weekly_rows(week, data):
    rows = []
    for p in data.get("players") or []:
        key = SOURCE_KEYS.get(p.get("source"))
        if key is None or p.get("rank") is None:
            continue
        rows.append({"source": key, "view": f"week{week}",
                     "pos": _pos(p.get("position")), "name": p["name"],
                     "team": None, "rank": p["rank"], "stats": None})
    return rows


def actuals(resp, season):
    """{espnId(str): {"pos", "pts": {week(str): points}}} for this season."""
    out = {}
    for entry in resp.get("players") or []:
        p = entry.get("player") or {}
        pos = model.espn_pos(p.get("defaultPositionId"))
        if not pos:
            continue
        pts = {}
        for s in p.get("stats") or []:
            if (s.get("seasonId") == season and s.get("statSourceId") == 0
                    and s.get("statSplitTypeId") == 1
                    and s.get("scoringPeriodId")):
                pts[str(s["scoringPeriodId"])] = round(
                    s.get("appliedTotal") or 0.0, 2)
        out[str(p.get("id") or entry.get("id"))] = {"pos": pos, "pts": pts}
    return out


def parse(predraft, weekly, resp, season):
    """Build the history payload from already-loaded inputs (pure; tested)."""
    rows = predraft_rows(predraft)
    for week, data in sorted(weekly.items()):
        rows += weekly_rows(week, data)
    if not rows:
        raise SourceError("history: no pre-draft or weekly rank rows")
    acts = actuals(resp, season)
    if not acts:
        raise SourceError("history: ESPN actuals response has no players")
    return {
        "fetchedAt": now_iso(),
        "rows": rows,
        "weeks": sorted(weekly),
        "actuals": acts,
        "notes": [],
    }
