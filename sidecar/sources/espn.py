"""ESPN: FFF rosters, free agents/waivers, and league settings.

Builds the ESPN player dicts that names.Matcher consumes (COORDINATION.md):
one dict per player, from both the twelve rosters and the free-agent pull.

The free-agent call is a single request with limit 1500 -- COORDINATION.md
request: with limit 600, waiver players were missing (Adonai Mitchell), so
the matcher couldn't find them; a 1500 pull returned all 1,050.

Player byes are not on the player records: they come from a third request,
proTeamSchedules_wl -> settings.proTeams[] {id, byeWeek}, mapped by
proTeamId. D/ST players get their team's bye the same way.

This week's NFL opponents are NOT fetched from ESPN here: site.api.espn.com
returns 403 from this network and the league's base payload carries no
calendar. Opponents arrive instead on the FantasyPros K/DST rows, which the
board attaches to each player.
"""
import json

import model
from .common import SourceError, now_iso

FA_LIMIT = 1500
FA_FILTER = {"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                         "limit": FA_LIMIT,
                         "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}


def fetch(client, cfg, season):
    base = cfg["urls"]["espn"].format(season=season, leagueId=cfg["leagueId"])
    league = client.get(base + "?view=mRoster&view=mTeam&view=mSettings").json()
    fa = client.get(base + "?view=kona_player_info",
                    headers={"X-Fantasy-Filter": json.dumps(FA_FILTER)}).json()
    pro = client.get(cfg["urls"]["espnProTeams"].format(season=season)
                     + "?view=proTeamSchedules_wl").json()
    return parse(league, fa, pro, cfg, season)


def bye_map(pro):
    """proTeamSchedules_wl response -> {proTeamId: byeWeek} (pure; tested)."""
    teams = ((pro or {}).get("settings") or {}).get("proTeams") or []
    return {t.get("id"): t.get("byeWeek") for t in teams if t.get("id")}


def parse(league, fa, pro, cfg, season):
    """Build the ESPN payload from the three raw responses (pure; tested)."""
    if not league.get("teams"):
        raise SourceError("espn: league response has no teams")
    byes = bye_map(pro)
    players = []
    teams = {}
    for team in league["teams"]:
        tid = team.get("id")
        teams[tid] = {"id": tid, "name": team.get("name"),
                      "abbrev": team.get("abbrev")}
        for entry in (team.get("roster", {}).get("entries") or []):
            p = (entry.get("playerPoolEntry") or {}).get("player") or {}
            pos = model.espn_pos(p.get("defaultPositionId"))
            if not pos:
                continue
            players.append({
                "espnId": p.get("id"),
                "name": p.get("fullName"),
                "pos": pos,
                "team": model.PRO_TEAMS.get(p.get("proTeamId")),
                "status": "OWNED",
                "ownerTeamId": tid,
                "lineupSlotId": entry.get("lineupSlotId"),
                "injury": p.get("injuryStatus"),
                "bye": byes.get(p.get("proTeamId")),
                "pctOwned": None,
            })

    fa_players = fa.get("players") or []
    if not fa_players:
        raise SourceError("espn: free-agent response has no players")
    for entry in fa_players:
        p = entry.get("player") or {}
        pos = model.espn_pos(p.get("defaultPositionId"))
        if not pos:
            continue
        ownership = p.get("ownership") or {}
        players.append({
            "espnId": p.get("id") or entry.get("id"),
            "name": p.get("fullName"),
            "pos": pos,
            "team": model.PRO_TEAMS.get(p.get("proTeamId")),
            "status": "WAIVERS" if entry.get("status") == "WAIVERS" else "FA",
            "ownerTeamId": None,
            "lineupSlotId": None,
            "injury": p.get("injuryStatus"),
            "bye": byes.get(p.get("proTeamId")),
            "pctOwned": ownership.get("percentOwned"),
        })

    settings = league.get("settings") or {}
    status = league.get("status") or {}
    return {
        "fetchedAt": now_iso(),
        "raw": {"league": league, "freeAgents": fa, "proTeams": pro},
        "players": players,
        "teams": list(teams.values()),
        "league": {
            "season": season,
            "currentWeek": status.get("currentMatchupPeriod"),
            "scoringItems": ((settings.get("scoringSettings") or {})
                             .get("scoringItems")),
            "lineupSlotCounts": ((settings.get("rosterSettings") or {})
                                 .get("lineupSlotCounts")),
        },
        "rows": [],   # ESPN is the match target, not a rank source
        "notes": [],
    }
