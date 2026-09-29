"""Compute FFF dual-point standings from a raw ESPN fetch.

Reads data/raw-<season>.json (written by fetch.py) and writes
data/standings-<season>.json per SPEC.md §1 and §5. Pure: no network,
re-runs offline against a committed raw file.

Scoring (SPEC.md §1): each regular-season week, every team can earn up to
2 points — 1 for winning its head-to-head matchup, 1 for finishing in the
top half of the league (strictly above the "score to beat", the 6th-lowest
of the 12 scores, per v1's getApiData.getScoresToBeat()). The regular-season
length is read from mSettings.settings.scheduleSettings.matchupPeriodCount,
never hardcoded; later weeks are the playoff bracket and contribute no dual
points.

Tie rules (SPEC.md §1 — assumptions, pending league confirmation):
- Exact H2H tie -> no point to either team.
- Exact tie at the top-half boundary -> no point to either, so the league
  awards 5 top-half points that week rather than 7.
"""
import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

LEAGUE_ID = "877873"

# A game decided by under this many points counts as "close" for the Clutch
# award; an owner needs at least MIN_CLOSE_GAMES of them to qualify, so one
# lucky squeaker doesn't win it. MIN_WEEKS_FOR_SPLIT is the minimum season
# length before a first-half/second-half comparison means anything.
CLOSE_GAME_MARGIN = 10.0
MIN_CLOSE_GAMES = 3
MIN_WEEKS_FOR_SPLIT = 6

# Margin thresholds for the per-team "how it ended" stats (ENH-025): a loss
# decided by under HEARTBREAK_MARGIN is a heartbreak, a win decided by at
# least BLOWOUT_MARGIN is a blowout.
HEARTBREAK_MARGIN = 5.0
BLOWOUT_MARGIN = 50.0

# ESPN's mSettings.scoringSettings.scoringItems carry statIds, not names, so
# the League Info page (ENH-005) needs a label map. These are the statIds
# this league actually scores, each verified against the per-player applied
# stats (the exact values ESPN multiplies by an item's points). statId ->
# human label.
STAT_LABELS = {
    # Passing
    4: "Passing TD",
    5: "Passing yards (per 5)",
    19: "Passing 2-pt conversion",
    20: "Passing interception",
    # Rushing
    24: "Rushing yards",
    25: "Rushing TD",
    26: "Rushing 2-pt conversion",
    # Receiving
    42: "Receiving yards",
    43: "Receiving TD",
    44: "Receiving 2-pt conversion",
    53: "Receptions (PPR)",
    # Kicking
    77: "FG made (40-49 yds)",
    80: "FG made (0-39 yds)",
    86: "PAT made",
    198: "FG made (50-59 yds)",
    201: "FG made (60+ yds)",
    # Defense
    89: "0 points allowed",
    90: "1-6 points allowed",
    91: "7-13 points allowed",
    92: "14-17 points allowed",
    95: "Interception",
    96: "Fumble recovery",
    97: "Blocked kick",
    98: "Safety",
    99: "Sack",
    123: "28-34 points allowed",
    124: "35-45 points allowed",
    125: "46+ points allowed",
    128: "Under 100 total yards allowed",
    129: "100-199 total yards allowed",
    130: "200-299 total yards allowed",
    132: "350-399 total yards allowed",
    133: "400-449 total yards allowed",
    134: "450-499 total yards allowed",
    135: "500-549 total yards allowed",
    136: "550+ total yards allowed",
    # Returns & turnovers
    63: "Fumble recovered for TD",
    72: "Fumble lost",
    93: "Blocked kick return TD",
    101: "Kickoff return TD",
    102: "Punt return TD",
    103: "Interception return TD",
    104: "Fumble return TD",
}

# Display order for the scoring table: (category, [statIds in order]). The
# statId order within a category is the order the rows render, so the big
# items lead each group. Anything in scoringSettings but not listed here is
# appended to an "Other" group so a new ESPN stat is never silently dropped.
SCORING_ORDER = (
    ("Passing", (4, 5, 19, 20)),
    ("Rushing", (25, 24, 26)),
    ("Receiving", (43, 53, 42, 44)),
    ("Kicking", (80, 77, 198, 201, 86)),
    ("Defense", (99, 95, 96, 97, 98,
                 89, 90, 91, 92, 123, 124, 125,
                 128, 129, 130, 132, 133, 134, 135, 136)),
    ("Returns & Turnovers", (101, 102, 103, 104, 93, 63, 72)),
)

# ESPN lineup slot IDs -> the position label this league uses for that slot,
# for the roster section of the League Info page. Only the slots the league
# fills are listed. Slot 5 is a TE/Flex and slot 23 an RB/WR Flex in this
# league's configuration; the rest are the standard ESPN slot meanings.
LINEUP_SLOT_LABELS = {
    0: "QB",
    2: "RB",
    4: "WR",
    5: "TE / Flex",
    23: "FLEX (RB/WR)",
    17: "K",
    16: "DEF",
}
# Display order for the starter slots (lineup order). Bench and IR are
# handled separately, not part of the starter lineup.
ROSTER_SLOT_ORDER = (0, 2, 4, 5, 23, 17, 16)
BENCH_SLOT = 20
IR_SLOT = 21


def current_streak(h2h_seq):
    """Current H2H streak from a chronological list of 1 (won) / 0 (lost or
    tied) results, most recent last. "W3", "L2", or "-" if no games played.
    """
    if not h2h_seq:
        return "-"
    last = h2h_seq[-1]
    n = 0
    for r in reversed(h2h_seq):
        if r != last:
            break
        n += 1
    return f"{'W' if last else 'L'}{n}"


def score_to_beat(scores):
    """The week's score to beat: the highest score that missed the top half.

    v1's getApiData.getScoresToBeat() hardcoded index [5] -- correct for a
    12-team league and silently wrong for any other size, which made the
    whole scoring rule (SPEC.md §1, the reason this project exists) compute
    the wrong answer for a league that isn't 12 teams. Derived from the
    field size instead: index [n//2 - 1] is the highest score that missed
    the top half, which is [5] when n == 12.

    For an odd field the top half rounds up (11 teams -> 6 earn the point).
    """
    n = len(scores)
    if n < 2:
        raise ValueError(f"score_to_beat needs at least 2 scores, got {n}")
    return sorted(scores)[n // 2 - 1]


def _played(matchup):
    """True if a schedule entry is a decided game with both sides scored.

    Unplayed games carry winner "UNDECIDED" and 0.0 scores; playoff byes
    carry no 'away' side at all.
    """
    if matchup.get("winner") == "UNDECIDED":
        return False
    home, away = matchup.get("home"), matchup.get("away")
    if not home or not away:
        return False
    return all(isinstance(side.get("totalPoints"), (int, float))
               for side in (home, away))


def compute_week(week, matchups):
    """Dual points for one regular-season week (SPEC.md §1).

    matchups: the week's played schedule entries. Returns the §5 week dict:
    week, scoreToBeat, games, teams.
    """
    games = []
    teams = {}
    for m in matchups:
        home, away = m["home"], m["away"]
        home_id, away_id = home["teamId"], away["teamId"]
        home_score, away_score = home["totalPoints"], away["totalPoints"]
        # H2H point: the higher score takes it.
        if home_score > away_score:
            winner = home_id
        elif away_score > home_score:
            winner = away_id
        else:
            # Exact H2H tie: no point to either team.
            winner = None
        games.append({
            "home": home_id, "away": away_id,
            "homeScore": round(home_score, 1), "awayScore": round(away_score, 1),
            "winner": winner,
        })
        for team_id, score, won in (
                (home_id, home_score, winner == home_id),
                (away_id, away_score, winner == away_id)):
            teams[team_id] = {"teamId": team_id, "score": score,
                              "h2h": 1 if won else 0, "topHalf": 0,
                              "weekPoints": 0}

    stb = score_to_beat([t["score"] for t in teams.values()])
    for t in teams.values():
        # Top-half point: strictly greater than the score to beat. An exact
        # tie at the boundary gives neither.
        t["topHalf"] = 1 if t["score"] > stb else 0
        t["weekPoints"] = t["h2h"] + t["topHalf"]

    return {
        "week": week,
        "scoreToBeat": round(stb, 1),
        "games": games,
        "teams": sorted(teams.values(), key=lambda t: t["teamId"]),
    }


def build_playoffs(schedule, week_count):
    """Winners-bracket results for a season, or None if no champion yet.

    The dual-point scoring stops at week_count (SPEC.md §1) and everything
    after it used to be discarded outright -- which meant the site could not
    say who actually won the league, and Career Stats credited the "title"
    to whoever finished the regular season at #1. In 2025 that was Casey
    Pirsig, who then lost the final to Davíd Huisken by 45 points.

    ESPN tags each schedule entry with playoffTierType; WINNERS_BRACKET is
    the championship bracket (LOSERS_/WINNERS_CONSOLATION_LADDER are the
    also-ran ladders and are ignored). The final is the single bracket game
    in the highest bracket week.

    The final week is taken from every bracket entry, not just the played
    ones: mid-playoffs the later rounds exist but are UNDECIDED, and picking
    the highest *played* week would crown a semifinal winner as champion.
    Returns None until the final itself is decided.
    """
    bracket = [m for m in schedule
               if m.get("playoffTierType") == "WINNERS_BRACKET"
               and m["matchupPeriodId"] > week_count]
    if not bracket:
        return None

    final_week = max(m["matchupPeriodId"] for m in bracket)
    finals = [m for m in bracket if m["matchupPeriodId"] == final_week]
    # Exactly one game decides the title. Anything else is a bracket shape
    # this function does not understand, and guessing a champion is worse
    # than reporting none.
    if len(finals) != 1 or not _played(finals[0]):
        return None

    final = finals[0]
    home, away = final["home"], final["away"]
    if home["totalPoints"] > away["totalPoints"]:
        champion, runner_up = home["teamId"], away["teamId"]
    elif away["totalPoints"] > home["totalPoints"]:
        champion, runner_up = away["teamId"], home["teamId"]
    else:
        # A tied final has no winner to report; ESPN breaks these by rule,
        # not by score, and that rule is not in this payload.
        return None

    games = []
    # Sort by week, then ESPN's entry id to keep output stable across runs.
    # id is always present in real payloads; default 0 so the function does
    # not depend on a field it never otherwise reads.
    for m in sorted(bracket, key=lambda g: (g["matchupPeriodId"], g.get("id", 0))):
        h, a = m.get("home"), m.get("away")
        games.append({
            "week": m["matchupPeriodId"],
            # A bye carries no 'away' side at all (2025 week 15 has 7
            # entries for this reason -- the SPEC.md §3 trap).
            "home": h["teamId"] if h else None,
            "away": a["teamId"] if a else None,
            "homeScore": round(h["totalPoints"], 1) if h else None,
            "awayScore": round(a["totalPoints"], 1) if a else None,
            "bye": a is None or h is None,
        })

    # Points scored in the championship bracket, per team. Byes contribute
    # the bye week's score; a team that lost in round 1 simply has fewer
    # games in the sum, which is what "most points in the playoffs" means.
    playoff_points = {}
    for g in games:
        for team_id, score in ((g["home"], g["homeScore"]),
                               (g["away"], g["awayScore"])):
            if team_id is not None and score is not None:
                playoff_points[team_id] = round(
                    playoff_points.get(team_id, 0.0) + score, 1)
    most_pf = (max(playoff_points, key=lambda t: playoff_points[t])
               if playoff_points else None)

    return {
        "champion": champion,
        "runnerUp": runner_up,
        "mostPointsFor": most_pf,
        "pointsFor": playoff_points,
        "finalWeek": final_week,
        "championScore": round(max(home["totalPoints"], away["totalPoints"]), 1),
        "runnerUpScore": round(min(home["totalPoints"], away["totalPoints"]), 1),
        "games": games,
    }


def build_scoring_table(settings):
    """The league's scoring rules as a grouped table for the League Info page.

    ESPN's scoringSettings.scoringItems carry a statId and either a base
    ``points`` value or a ``pointsOverrides`` entry keyed by the active
    scoring period -- never a name. This resolves each item's effective
    points, labels it via STAT_LABELS, and groups it per SCORING_ORDER.
    Returns ``[{"category": str, "rows": [{"label", "points"}]}]``;
    categories with no scored items are omitted. ("rows", not "items", so the
    key doesn't shadow the dict's built-in ``items`` method in the template.)
    """
    items = (settings.get("scoringSettings") or {}).get("scoringItems") or []
    # statId -> effective points. pointsOverrides wins over the base value:
    # a league that overrides a stat for the current period is the common
    # case, not the exception, so the override is what actually scores.
    points_by_id = {}
    for it in items:
        sid = it.get("statId")
        overrides = it.get("pointsOverrides") or {}
        points_by_id[sid] = next(iter(overrides.values())) if overrides \
            else it.get("points", 0.0)

    table = []
    placed = set()
    for category, ids in SCORING_ORDER:
        rows = [{"label": STAT_LABELS[sid], "points": points_by_id[sid]}
                for sid in ids if sid in points_by_id]
        if rows:
            table.append({"category": category, "rows": rows})
            placed.update(ids)

    # Anything ESPN scores that we haven't labeled: show it as "Stat <id>"
    # rather than drop it, so a new stat is a visible row, not a silent gap.
    extra = [{"label": "Stat {}".format(sid), "points": points_by_id[sid]}
             for sid in sorted(points_by_id) if sid not in placed]
    if extra:
        table.append({"category": "Other", "rows": extra})
    return table


def build_league_rules(settings):
    """The league's standing rules for the League Info page (ENH-005).

    Extracts the settings that answer the recurring league questions --
    roster shape, draft, keepers, playoffs, trades, FAAB -- from mSettings
    so the page reflects what ESPN actually has configured rather than a
    stale copy-paste. Owner-only details that aren't in the API (keeper
    pricing, the draft date) are written in the template, not here.
    """
    roster = settings.get("rosterSettings", {}) or {}
    draft = settings.get("draftSettings", {}) or {}
    trade = settings.get("tradeSettings", {}) or {}
    acq = settings.get("acquisitionSettings", {}) or {}
    sched = settings.get("scheduleSettings", {}) or {}
    scoring = settings.get("scoringSettings", {}) or {}

    slot_counts = roster.get("lineupSlotCounts", {}) or {}
    starters = [{"label": LINEUP_SLOT_LABELS[slot_id],
                 "count": slot_counts.get(str(slot_id), 0)}
                for slot_id in ROSTER_SLOT_ORDER
                if slot_counts.get(str(slot_id), 0)]
    bench = slot_counts.get(str(BENCH_SLOT), 0)
    ir = slot_counts.get(str(IR_SLOT), 0)

    return {
        "roster": {
            "starters": starters,
            "bench": bench,
            "ir": ir,
            "total": sum(s["count"] for s in starters) + bench + ir,
        },
        "draft": {
            "type": draft.get("type", ""),
            "budget": draft.get("auctionBudget"),
            "clockSeconds": draft.get("timePerSelection"),
        },
        "keepers": {
            "count": draft.get("keeperCount"),
        },
        "playoffs": {
            "teamCount": sched.get("playoffTeamCount"),
            "homeTeamBonus": scoring.get("playoffHomeTeamBonus", 0),
            "seedingRule": sched.get("playoffSeedingRule", ""),
        },
        "trades": {
            "vetoVotesRequired": trade.get("vetoVotesRequired"),
        },
        "faab": {
            "type": acq.get("acquisitionType", ""),
            "budget": acq.get("acquisitionBudget"),
        },
    }


def build_standings(raw, updated):
    """Raw fetch dict (mMatchupScore + mTeam + mSettings) -> §5 standings dict.

    Pure function of its inputs; `updated` is the UTC timestamp string the
    caller stamps on the run.
    """
    ms = raw["mMatchupScore"]
    teams_view = raw["mTeam"]
    schedule_settings = raw["mSettings"]["settings"]["scheduleSettings"]
    week_count = schedule_settings["matchupPeriodCount"]
    # How many teams make the playoffs is a league setting, not a constant.
    # home.html used to draw its playoff line at len(standings) // 2, which
    # is 6 here only because this league is 12 teams with a 6-team playoff
    # -- correct by coincidence, wrong for any league that splits differently.
    playoff_team_count = schedule_settings.get("playoffTeamCount")
    # What each owner paid in. The pot is entryFee x size, which is exactly
    # what data/prizes.json pays out, so winnings minus the fee is a real
    # profit/loss figure rather than a vanity number.
    finance = raw["mSettings"]["settings"].get("financeSettings") or {}
    entry_fee = finance.get("entryFee")

    members = {m["id"]: m for m in teams_view.get("members", [])}
    team_info = {}
    for t in teams_view["teams"]:
        owner = members.get(t.get("primaryOwner"), {})
        owner_name = " ".join(p for p in (owner.get("firstName"),
                                          owner.get("lastName")) if p) \
            or owner.get("displayName")
        # ESPN's own end-of-season placement, 1..N across the whole league
        # (playoffs + both consolation ladders), not just the bracket. 0
        # while a season is in progress. Cross-checked against the winners
        # bracket for 2022-2025: rank 1 is the final's winner every time.
        #
        # This matters more than it looks: FFF reseeds the playoffs by hand
        # off the dual-point standings, so ESPN's own `playoffSeed` does NOT
        # reflect the real bracket (2025 has Sharp seeded 3rd and Huisken
        # 4th, while the bracket ran Huisken as the 3 seed). rankCalculated-
        # Final is computed from results, so the manual reseed doesn't
        # corrupt it.
        final_rank = t.get("rankCalculatedFinal") or None
        team_info[t["id"]] = {"name": t.get("name"), "owner": owner_name,
                              "finalRank": final_rank}

    # Group by matchupPeriodId — never index the schedule by arithmetic
    # (SPEC.md §3: the playoffs do not have 6 entries per week).
    by_week = {}
    for m in ms.get("schedule", []):
        by_week.setdefault(m["matchupPeriodId"], []).append(m)

    # A week is complete when every team has a played game in it.
    # throughWeek is the last complete week, counting up from week 1, and
    # never extends past the regular season.
    weeks_out = []
    through_week = 0
    for week in range(1, week_count + 1):
        played = [m for m in by_week.get(week, []) if _played(m)]
        played_teams = {s["teamId"] for m in played for s in (m["home"], m["away"])}
        if len(played_teams) != len(team_info):
            break
        weeks_out.append(compute_week(week, played))
        through_week = week

    stats = {tid: {"h2hPoints": 0, "topHalfPoints": 0, "wins": 0, "losses": 0,
                   "ties": 0, "pointsFor": 0.0, "pointsAgainst": 0.0,
                   "scores": [], "h2h_seq": []}
             for tid in team_info}
    for w in weeks_out:
        for g in w["games"]:
            home, away = g["home"], g["away"]
            stats[home]["pointsFor"] += g["homeScore"]
            stats[away]["pointsFor"] += g["awayScore"]
            stats[home]["pointsAgainst"] += g["awayScore"]
            stats[away]["pointsAgainst"] += g["homeScore"]
            if g["winner"] == home:
                stats[home]["wins"] += 1
                stats[away]["losses"] += 1
            elif g["winner"] == away:
                stats[away]["wins"] += 1
                stats[home]["losses"] += 1
            else:
                stats[home]["ties"] += 1
                stats[away]["ties"] += 1
        for t in w["teams"]:
            s = stats[t["teamId"]]
            s["h2hPoints"] += t["h2h"]
            s["topHalfPoints"] += t["topHalf"]
            s["scores"].append(t["score"])
            s["h2h_seq"].append(t["h2h"])

    standings = []
    for tid, s in stats.items():
        info = team_info[tid]
        points_for = round(s["pointsFor"], 1)
        last3 = s["scores"][-3:]
        standings.append({
            "teamId": tid,
            "name": info["name"],
            "owner": info["owner"],
            "points": s["h2hPoints"] + s["topHalfPoints"],
            "h2hPoints": s["h2hPoints"],
            "topHalfPoints": s["topHalfPoints"],
            # Where they actually finished once the playoffs were done.
            # None for an in-progress season.
            "finalRank": info["finalRank"],
            "record": f'{s["wins"]}-{s["losses"]}'
                      + (f'-{s["ties"]}' if s["ties"] else ""),
            "pointsFor": points_for,
            "pointsAgainst": round(s["pointsAgainst"], 1),
            "averageScore": round(points_for / through_week, 1) if through_week else 0.0,
            "avgLast3": round(sum(last3) / len(last3), 1) if last3 else 0.0,
            # Luck index: H2H points earned minus top-half points earned.
            # Positive means winning matchups more often than raw scoring
            # alone would justify (a favorable schedule); negative means
            # scoring top-half more often than winning (a tough schedule).
            "luckIndex": s["h2hPoints"] - s["topHalfPoints"],
            "streak": current_streak(s["h2h_seq"]),
        })
    standings.sort(key=lambda r: (-r["points"], -r["pointsFor"]))
    ranked = [{"rank": i, **row} for i, row in enumerate(standings, 1)]

    return {
        "season": ms["seasonId"],
        "league": str(ms.get("id", LEAGUE_ID)),
        "leagueName": raw["mSettings"]["settings"].get("name"),
        "updated": updated,
        "regularSeasonWeeks": week_count,
        "playoffTeamCount": playoff_team_count,
        "entryFee": entry_fee,
        # The league's scoring rules, grouped for the League Info page.
        "scoring": build_scoring_table(raw["mSettings"]["settings"]),
        # The league's standing rules (roster, draft, keepers, playoffs,
        # trades, FAAB) for the League Info page.
        "rules": build_league_rules(raw["mSettings"]["settings"]),
        "throughWeek": through_week,
        "weeks": weeks_out,
        "standings": ranked,
        # None until the season's championship game is decided.
        "playoffs": build_playoffs(ms.get("schedule", []), week_count),
        # Every decided game after the regular season, any bracket. These
        # contribute no dual points (SPEC.md §1) -- they're kept so an
        # "all-time head-to-head" record can actually mean all-time.
        "postseason": postseason_games(ms.get("schedule", []), week_count),
    }


def build_live_data(standings):
    """The static season snapshot for the Live page (ENH-029).

    build.py writes this to docs/live-data.json for the newest season only.
    The browser page merges it with the in-game scores it fetches from ESPN
    to show "if the week ended now". Two deliberate absences:

    - No owner names. The live ESPN response carries them in dev tools
      regardless, but this page displays team names only.
    - No `updated` stamp. Everything here is a pure function of
      standings-<season>.json, so the file only changes when the standings
      do -- a timestamp would churn docs/ every bot run.
    """
    return {
        "season": standings["season"],
        "throughWeek": standings["throughWeek"],
        "regularSeasonWeeks": standings["regularSeasonWeeks"],
        "teams": [{"teamId": s["teamId"], "name": s["name"],
                   "points": s["points"], "rank": s["rank"]}
                  for s in standings["standings"]],
    }


def postseason_games(schedule, week_count):
    """Decided games after the regular season, across every bracket tier.

    Separate from build_playoffs(), which deliberately looks at only the
    winners bracket because it is answering "who won the league". This is
    answering "who has played whom", so a consolation-ladder meeting counts
    just as much.
    """
    out = []
    for m in sorted(schedule, key=lambda g: (g["matchupPeriodId"], g.get("id", 0))):
        if m["matchupPeriodId"] <= week_count or not _played(m):
            continue
        home, away = m["home"], m["away"]
        home_score = round(home["totalPoints"], 1)
        away_score = round(away["totalPoints"], 1)
        if home_score > away_score:
            winner = home["teamId"]
        elif away_score > home_score:
            winner = away["teamId"]
        else:
            winner = None
        out.append({"week": m["matchupPeriodId"],
                    "tier": m.get("playoffTierType"),
                    "home": home["teamId"], "away": away["teamId"],
                    "homeScore": home_score, "awayScore": away_score,
                    "winner": winner})
    return out


def build_rivalries(all_standings):
    """All-time head-to-head records between owners, across every given
    season's §5 standings dict (as many seasons as are passed in).

    Matches games by owner name rather than teamId, since a teamId's owner
    can change between seasons (and a team can be renamed) but the owner
    identity is what a "rivalry" actually means. A game between two teams
    with the same owner (shouldn't normally happen) is skipped.

    **Counts the postseason too.** This used to read only the regular-season
    weeks while calling itself "all-time", which hid real meetings: Paul
    Tuura is 0-4 against Casey Pirsig in the regular season but has also
    played him three times in the playoffs and won two, including knocking
    him out of the 2024 winners bracket 101.0-99.0. A head-to-head record
    that omits playoff games is not a head-to-head record.

    Returns (owners, matrix): owners is every owner name seen, sorted;
    matrix[a][b] is a's record against b -- {"wins", "losses", "ties"}
    overall, plus the same three split into "reg*" and "post*" so the UI
    can break it out. Only pairs that have actually played get an entry.
    """
    owners = set()
    matrix = {}

    def cell():
        return {"wins": 0, "losses": 0, "ties": 0,
                "regWins": 0, "regLosses": 0, "regTies": 0,
                "postWins": 0, "postLosses": 0, "postTies": 0}

    def record(owner_by_team, g, phase):
        a, b = owner_by_team.get(g["home"]), owner_by_team.get(g["away"])
        if not a or not b or a == b:
            return
        owners.add(a)
        owners.add(b)
        cell_a = matrix.setdefault(a, {}).setdefault(b, cell())
        cell_b = matrix.setdefault(b, {}).setdefault(a, cell())
        if g["winner"] == g["home"]:
            won, lost = cell_a, cell_b
        elif g["winner"] == g["away"]:
            won, lost = cell_b, cell_a
        else:
            for c in (cell_a, cell_b):
                c["ties"] += 1
                c[phase + "Ties"] += 1
            return
        won["wins"] += 1
        won[phase + "Wins"] += 1
        lost["losses"] += 1
        lost[phase + "Losses"] += 1

    for season in all_standings:
        owner_by_team = {s["teamId"]: s["owner"] for s in season["standings"]}
        for w in season["weeks"]:
            for g in w["games"]:
                record(owner_by_team, g, "reg")
        for g in season.get("postseason") or []:
            record(owner_by_team, g, "post")

    return sorted(owners), matrix


def build_career_stats(all_standings):
    """Career totals per owner across every given season's §5 standings dict.

    Matched by owner name (see build_rivalries for why: teamId's owner can
    change between seasons). Returns a list of career rows, sorted by wins
    desc then pointsFor desc -- the same convention as a single season's
    standings. Each row:

    owner, seasons (count played), wins/losses/ties (career H2H record),
    pointsFor, gamesPlayed, careerAverage (pointsFor / gamesPlayed, a
    weighted average -- NOT the mean of each season's average), titles
    (seasons finished rank 1), topHalfPoints, luckIndex (career total),
    bestWeek/worstWeek ({score, season, week}), bestSeason ({points, season}).
    """
    careers = {}
    for season in all_standings:
        year = season["season"]
        owner_by_team = {s["teamId"]: s["owner"] for s in season["standings"]}
        playoffs = season.get("playoffs")
        champion_owner = (owner_by_team.get(playoffs["champion"])
                          if playoffs else None)
        runner_up_owner = (owner_by_team.get(playoffs["runnerUp"])
                           if playoffs else None)
        # Leading an unfinished season is not a regular-season title. Without
        # this, whoever happens to top the standings in week 2 is credited
        # with a finish they haven't earned.
        season_complete = (season.get("throughWeek")
                           == season.get("regularSeasonWeeks"))
        for row in season["standings"]:
            c = careers.setdefault(row["owner"], {
                "owner": row["owner"], "seasons": 0, "wins": 0, "losses": 0,
                "ties": 0, "pointsFor": 0.0, "gamesPlayed": 0,
                # "titles" counts actual championships (won the final);
                # "regularSeasonFirsts" counts finishing #1 in the dual-point
                # standings. These are NOT the same thing and conflating them
                # is what made the site name the wrong 2025 champion.
                "titles": 0, "regularSeasonFirsts": 0, "runnerUps": 0,
                "championshipYears": [],
                "topHalfPoints": 0, "luckIndex": 0,
                "bestWeek": None, "worstWeek": None, "bestSeason": None,
            })
            c["seasons"] += 1
            parts = [int(p) for p in row["record"].split("-")]
            w, l = parts[0], parts[1]
            t = parts[2] if len(parts) > 2 else 0
            c["wins"] += w
            c["losses"] += l
            c["ties"] += t
            c["pointsFor"] += row["pointsFor"]
            c["gamesPlayed"] += w + l + t
            c["topHalfPoints"] += row["topHalfPoints"]
            c["luckIndex"] += row["luckIndex"]
            if row["rank"] == 1 and season_complete:
                c["regularSeasonFirsts"] += 1
            if champion_owner is not None and row["owner"] == champion_owner:
                c["titles"] += 1
                c["championshipYears"].append(year)
            if runner_up_owner is not None and row["owner"] == runner_up_owner:
                c["runnerUps"] += 1
            if c["bestSeason"] is None or row["points"] > c["bestSeason"]["points"]:
                c["bestSeason"] = {"points": row["points"], "season": year}
        for w in season["weeks"]:
            for t in w["teams"]:
                owner = owner_by_team.get(t["teamId"])
                if not owner or owner not in careers:
                    continue
                c = careers[owner]
                entry = {"score": t["score"], "season": year, "week": w["week"]}
                if c["bestWeek"] is None or t["score"] > c["bestWeek"]["score"]:
                    c["bestWeek"] = entry
                if c["worstWeek"] is None or t["score"] < c["worstWeek"]["score"]:
                    c["worstWeek"] = entry

    for c in careers.values():
        c["careerAverage"] = (round(c["pointsFor"] / c["gamesPlayed"], 1)
                              if c["gamesPlayed"] else 0.0)
        c["pointsFor"] = round(c["pointsFor"], 1)

    return sorted(careers.values(),
                  key=lambda c: (-c["wins"], -c["pointsFor"]))



# --------------------------------------------------------------------------
# All-time kicker rankings (the Kickers page).
#
# Built from data/starters-<season>.json (fetch.py --starters), which holds
# every *started* player week by week. A kicker only counts here if someone
# actually put them in their lineup -- points scored on a bench are points
# nobody chose, and the whole joke of this page is that these are points the
# league earned on purpose.
#
# Owner identity comes from the season's standings (teamId -> owner), the
# same join build_rivalries and build_career_stats use, because a teamId's
# owner can change between seasons.
# --------------------------------------------------------------------------

# ESPN defaultPositionId for a kicker.
KICKER_POS = 5

# Average-based awards need a sample. Ten starts is most of a season's worth
# of Sundays -- enough that one four-field-goal afternoon cannot buy the
# "best foot in the league" trophy.
MIN_KICKER_STARTS = 10

# ESPN proTeamId -> NFL abbreviation, for "Harrison Butker, KC". Verified
# against this league's own data (Boswell 23 PIT, Fairbairn 34 HOU, Zuerlein
# 14 LAR, ...). 0 is ESPN's free-agent/unknown slot.
PRO_TEAMS = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG",
    20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL",
    34: "HOU",
}


def owned_starts(all_starters, all_standings):
    """Every started player-week from the starter files, stamped with its owner.

    Returns a list of dicts: season, week, teamId, owner, slot, playerId,
    name, pos, proTeam, points -- sorted so everything downstream is
    deterministic. A row whose teamId has no owner in that season's standings
    is dropped rather than attributed to nobody, which also keeps a season
    with starter data but no standings file out of the totals.

    Position-agnostic on purpose: the kicker page is the first thing built on
    this data, not the last.
    """
    owners_by_season = {
        s["season"]: {row["teamId"]: row["owner"] for row in s["standings"]}
        for s in all_standings
    }
    rows = []
    for season_file in all_starters:
        year = season_file["season"]
        owner_by_team = owners_by_season.get(year, {})
        for r in season_file.get("starters") or []:
            owner = owner_by_team.get(r.get("teamId"))
            if not owner:
                continue
            rows.append({
                "season": year,
                "week": r["week"],
                "teamId": r["teamId"],
                "owner": owner,
                "slot": r.get("slot"),
                "playerId": r["playerId"],
                "name": r.get("name") or "Unknown player",
                "pos": r.get("pos"),
                "proTeam": PRO_TEAMS.get(r.get("proTeamId"), ""),
                "points": round(r.get("points") or 0.0, 1),
            })
    return sorted(rows, key=lambda r: (r["season"], r["week"], r["owner"],
                                       r["playerId"]))


def kicker_starts(all_starters, all_standings):
    """owned_starts() narrowed to started kickers."""
    return [r for r in owned_starts(all_starters, all_standings)
            if r["pos"] == KICKER_POS]


def _kicker_rows(starts):
    """One row per kicker, career totals, best first.

    name/proTeam are taken from the most recent start, so a kicker who
    changed teams reads as wherever he kicks now rather than wherever he was
    in 2019.
    """
    kickers = {}
    for s in starts:
        k = kickers.setdefault(s["playerId"], {
            "playerId": s["playerId"], "name": s["name"], "proTeam": s["proTeam"],
            "points": 0.0, "starts": 0, "zeroes": 0, "doubleDigits": 0,
            "seasons": [], "owners": {}, "best": None, "worst": None,
            "lastSeen": (0, 0),
        })
        k["points"] += s["points"]
        k["starts"] += 1
        if s["points"] <= 0:
            k["zeroes"] += 1
        if s["points"] >= 10:
            k["doubleDigits"] += 1
        if s["season"] not in k["seasons"]:
            k["seasons"].append(s["season"])
        k["owners"][s["owner"]] = k["owners"].get(s["owner"], 0) + 1
        week = {"points": s["points"], "season": s["season"],
                "week": s["week"], "owner": s["owner"]}
        if k["best"] is None or s["points"] > k["best"]["points"]:
            k["best"] = week
        if k["worst"] is None or s["points"] < k["worst"]["points"]:
            k["worst"] = week
        if (s["season"], s["week"]) >= k["lastSeen"]:
            k["lastSeen"] = (s["season"], s["week"])
            k["name"], k["proTeam"] = s["name"], s["proTeam"]

    rows = []
    for k in kickers.values():
        k.pop("lastSeen")
        # Owners who started him, most-loyal first -- the "ridden by" column.
        k["ownerCounts"] = sorted(k.pop("owners").items(),
                                  key=lambda kv: (-kv[1], kv[0]))
        k["ownerList"] = [name for name, _ in k["ownerCounts"]]
        k["points"] = round(k["points"], 1)
        k["average"] = round(k["points"] / k["starts"], 1) if k["starts"] else 0.0
        k["seasons"].sort()
        rows.append(k)
    return sorted(rows, key=lambda k: (-k["points"], -k["starts"], k["name"]))


def _kicker_owner_rows(starts):
    """One row per owner: what the position has given them, career.

    Sorted by total points, which is mostly a function of seasons played --
    the interesting column is the average, and the template says so.
    """
    owners = {}
    for s in starts:
        o = owners.setdefault(s["owner"], {
            "owner": s["owner"], "points": 0.0, "starts": 0, "zeroes": 0,
            "kickers": {}, "best": None, "worst": None, "seasons": [],
        })
        o["points"] += s["points"]
        o["starts"] += 1
        if s["points"] <= 0:
            o["zeroes"] += 1
        if s["season"] not in o["seasons"]:
            o["seasons"].append(s["season"])
        o["kickers"][s["name"]] = o["kickers"].get(s["name"], 0) + 1
        week = {"points": s["points"], "season": s["season"],
                "week": s["week"], "name": s["name"]}
        if o["best"] is None or s["points"] > o["best"]["points"]:
            o["best"] = week
        if o["worst"] is None or s["points"] < o["worst"]["points"]:
            o["worst"] = week

    rows = []
    for o in owners.values():
        counts = sorted(o.pop("kickers").items(), key=lambda kv: (-kv[1], kv[0]))
        o["distinctKickers"] = len(counts)
        o["favorite"] = ({"name": counts[0][0], "starts": counts[0][1]}
                         if counts else None)
        o["points"] = round(o["points"], 1)
        o["average"] = round(o["points"] / o["starts"], 1) if o["starts"] else 0.0
        o["seasons"].sort()
        rows.append(o)
    return sorted(rows, key=lambda o: (-o["points"], o["owner"]))


def _kicker_awards(starts, kickers, owner_rows, share, short=None):
    """The joke trophies. Every one is a fixed rule over the rows above.

    Ties are broken by a deterministic sort key rather than reported as
    shared: this is a bit page, and one name on the donut award is funnier
    than two. Each award is {emoji, name, headline, detail, blurb}, and any
    award the data cannot support is left out rather than rendered empty.

    `short` is the display-name map from short_names(). Unlike the tables,
    which shorten in the template with the `short` filter, these lines have
    the owner's name built into a sentence -- so the shortening has to happen
    here, where the sentence is assembled.
    """
    awards = []
    if not starts or not kickers:
        return awards
    short = short or {}

    def who(owner):
        return short.get(owner, owner)

    goat = kickers[0]
    awards.append({
        "emoji": "\U0001f3c6", "name": "The Golden Boot",
        "headline": goat["name"],
        "detail": f"{goat['points']} points in {goat['starts']} starts",
        "blurb": ("Most points any kicker has ever scored while in somebody's "
                  "starting lineup. Nobody drafted him on purpose."),
    })

    best = max(starts, key=lambda s: (s["points"], -s["season"], -s["week"]))
    awards.append({
        "emoji": "\U0001f4a5", "name": "Best week ever",
        "headline": f"{best['name']} — {best['points']}",
        "detail": f"{best['season']} week {best['week']}, started by {who(best['owner'])}",
        "blurb": "The most points any kicker has scored in a single week.",
    })

    # No "worst week ever" award. It is always a 0.0 and there are 17 of
    # them, so the winner is whichever zero happens to sort first -- an
    # arbitrary pick dressed up as a record. Donut king below tells the
    # same joke with a real count behind it.
    donuts = [o for o in owner_rows if o["zeroes"]]
    if donuts:
        king = min(donuts, key=lambda o: (-o["zeroes"], o["owner"]))
        total_donuts = sum(o["zeroes"] for o in owner_rows)
        awards.append({
            "emoji": "\U0001f369", "name": "Donut king",
            "headline": who(king["owner"]),
            "detail": f"{king['zeroes']} scoreless kicker starts",
            "blurb": (f"{total_donuts} times in league history a started kicker "
                      f"has scored nothing at all. These ones are his."),
        })

    # Longest owner-kicker marriage: the pairing with the most starts.
    pairings = {}
    for s in starts:
        key = (s["owner"], s["name"])
        pairings[key] = pairings.get(key, 0) + 1
    (loyal_owner, loyal_kicker), loyal_starts = min(
        pairings.items(), key=lambda kv: (-kv[1], kv[0]))
    awards.append({
        "emoji": "\U0001f48d", "name": "Longest marriage",
        "headline": f"{who(loyal_owner)} + {loyal_kicker}",
        "detail": f"{loyal_starts} weeks together",
        "blurb": "The longest any owner has stuck with one kicker.",
    })

    journeyman = min(kickers,
                     key=lambda k: (-len(k["ownerList"]), -k["starts"], k["name"]))
    if len(journeyman["ownerList"]) > 1:
        awards.append({
            "emoji": "\U0001f9f3", "name": "League journeyman",
            "headline": journeyman["name"],
            "detail": f"started by {len(journeyman['ownerList'])} different owners",
            "blurb": ("Has kicked for more of this league than most of its "
                      "owners have."),
        })

    qualified = [o for o in owner_rows if o["starts"] >= MIN_KICKER_STARTS]
    if len(qualified) > 1:
        blessed = max(qualified, key=lambda o: (o["average"], o["owner"]))
        cursed = min(qualified, key=lambda o: (o["average"], o["owner"]))
        awards.append({
            "emoji": "\U0001f340", "name": "Blessed foot",
            "headline": who(blessed["owner"]),
            "detail": f"{blessed['average']} points per kicker start",
            "blurb": (f"Best return at the position in the league, over "
                      f"{blessed['starts']} starts. Skill, obviously."),
        })
        awards.append({
            "emoji": "\U0001f63f", "name": "Cursed foot",
            "headline": who(cursed["owner"]),
            "detail": f"{cursed['average']} points per kicker start",
            "blurb": (f"Worst return at the position, over {cursed['starts']} "
                      f"starts. There is no strategy that fixes this."),
        })

    one_offs = [k for k in kickers if k["starts"] == 1]
    if one_offs:
        pick = min(one_offs, key=lambda k: (k["points"], k["name"]))
        awards.append({
            "emoji": "\U0001f44b", "name": "One and done",
            "headline": f"{len(one_offs)} kickers",
            "detail": f"worst of them: {pick['name']}, {pick['points']}",
            "blurb": "Started exactly once, ever, and never again.",
        })

    awards.append({
        "emoji": "\U0001f4ca", "name": "Share of everything",
        "headline": f"{share}%",
        "detail": "of every point this league has ever started",
        "blurb": "How much of this league's scoring came from the kicker slot.",
    })
    return awards


def build_kicker_stats(all_starters, all_standings, short=None):
    """All-time kicker rankings: leaderboard, owners, awards, per-season bests.

    Started kickers only (see the section comment). Returns None when there
    is no starter data at all, so the site can skip the page rather than
    render an empty one.

    `short` is short_names()'s display map, used for the award lines only
    (see _kicker_awards).

    Keys: kickers (career rows, most points first), owners (career rows per
    owner), awards, bySeason (each season's leading kicker), totalPoints,
    totalStarts, distinctKickers, share (kicker points as a percentage of
    every started point, all positions), seasons.
    """
    every_start = owned_starts(all_starters, all_standings)
    starts = [r for r in every_start if r["pos"] == KICKER_POS]
    if not starts:
        return None

    # Denominator for the share stat: every started point, all positions --
    # the same universe of rows the numerator comes from, so the percentage
    # is of points this site actually accounts for.
    all_points = round(sum(r["points"] for r in every_start), 1)
    total_points = round(sum(s["points"] for s in starts), 1)
    share = round(100 * total_points / all_points, 1) if all_points else 0.0

    kickers = _kicker_rows(starts)
    owner_rows = _kicker_owner_rows(starts)

    # Each season's leading kicker, newest first -- the same leaderboard cut
    # one year at a time, which is where the "wait, who?" moments live.
    by_season = []
    seasons = sorted({s["season"] for s in starts}, reverse=True)
    for year in seasons:
        rows = _kicker_rows([s for s in starts if s["season"] == year])
        if rows:
            top = rows[0]
            by_season.append({
                "season": year, "name": top["name"], "proTeam": top["proTeam"],
                "points": top["points"], "starts": top["starts"],
                "average": top["average"], "owners": top["ownerList"],
            })

    return {
        "kickers": kickers,
        "owners": owner_rows,
        "awards": _kicker_awards(starts, kickers, owner_rows, share, short),
        "bySeason": by_season,
        "totalPoints": total_points,
        "totalStarts": len(starts),
        "distinctKickers": len(kickers),
        "share": share,
        "seasons": sorted(seasons),
    }


# --------------------------------------------------------------------------
# Per-season advanced stats, records and awards.
#
# All derived from the §5 week data already on disk -- no extra ESPN call.
# Computed at render time (like build_rivalries/build_career_stats) rather
# than stored in standings-<season>.json, so the committed artifact stays
# the raw scoring record and these stay free to change shape.
# --------------------------------------------------------------------------

def all_play_records(season):
    """Each team's record as if it played every other team every week.

    The truest measure of strength in fantasy: it removes the schedule
    entirely. 12 teams x 14 weeks = 154 notional games. It is also the
    natural extension of this league's own top-half point -- top-half is
    the binary version of the same idea -- so a team whose all-play rate is
    far above its actual win rate has been unlucky rather than bad.

    Returns {teamId: {wins, losses, ties, pct}}; pct counts a tie as half.
    """
    out = {}
    for w in season["weeks"]:
        scores = [(t["teamId"], t["score"]) for t in w["teams"]]
        for team_id, score in scores:
            rec = out.setdefault(team_id, {"wins": 0, "losses": 0, "ties": 0})
            for other_id, other in scores:
                if other_id == team_id:
                    continue
                if score > other:
                    rec["wins"] += 1
                elif score < other:
                    rec["losses"] += 1
                else:
                    rec["ties"] += 1
    for rec in out.values():
        total = rec["wins"] + rec["losses"] + rec["ties"]
        rec["pct"] = round((rec["wins"] + 0.5 * rec["ties"]) / total, 3) if total else 0.0
    return out


def scoring_profile(season):
    """Volatility and weekly extremes per team.

    - stdev: population standard deviation of weekly scores. Low means a
      team you can predict; high means one that wins big and loses big.
    - high/low: that team's best and worst week.
    - weeklyFirsts/weeklyLasts: how often it was the whole league's top or
      bottom scorer in a week.
    - luckyWins: won the matchup while scoring in the bottom half.
    - unluckyLosses: scored in the top half and lost anyway.

    The last two are expressed in the league's own dual-point terms (the
    per-week h2h/topHalf flags), which is what makes them worth showing
    here rather than a generic "close losses" stat.
    """
    out = {}
    for w in season["weeks"]:
        scores = [t["score"] for t in w["teams"]]
        best = max(scores) if scores else None
        worst = min(scores) if scores else None
        for t in w["teams"]:
            p = out.setdefault(t["teamId"], {
                "scores": [], "weeklyFirsts": 0, "weeklyLasts": 0,
                "luckyWins": 0, "unluckyLosses": 0})
            p["scores"].append(t["score"])
            if t["score"] == best:
                p["weeklyFirsts"] += 1
            if t["score"] == worst:
                p["weeklyLasts"] += 1
            if t["h2h"] and not t["topHalf"]:
                p["luckyWins"] += 1
            if t["topHalf"] and not t["h2h"]:
                p["unluckyLosses"] += 1

    # Close games: decided by under 10 points. Counted from the matchups
    # rather than the per-team flags, since margin isn't in w["teams"].
    # The per-team "how it ended" stats (ENH-025) ride along in the same
    # pass over the decided games: points scored in losses, heartbreaks
    # (losses by under 5), blowout wins (by 50+).
    for w in season["weeks"]:
        for g in w["games"]:
            if g["winner"] is None:
                continue
            margin = abs(g["homeScore"] - g["awayScore"])
            if margin < CLOSE_GAME_MARGIN:
                for team_id in (g["home"], g["away"]):
                    p = out.setdefault(team_id, {})
                    p["closeGames"] = p.get("closeGames", 0) + 1
                    if g["winner"] == team_id:
                        p["closeWins"] = p.get("closeWins", 0) + 1
            win_id = g["winner"]
            win_score = (g["homeScore"] if win_id == g["home"]
                         else g["awayScore"])
            lose_id = g["away"] if win_id == g["home"] else g["home"]
            lose_score = (g["awayScore"] if win_id == g["home"]
                          else g["homeScore"])
            win_p = out.setdefault(win_id, {})
            lose_p = out.setdefault(lose_id, {})
            lose_p["pointsInLosses"] = round(
                lose_p.get("pointsInLosses", 0.0) + lose_score, 1)
            if margin < HEARTBREAK_MARGIN:
                lose_p["heartbreaks"] = lose_p.get("heartbreaks", 0) + 1
            if margin >= BLOWOUT_MARGIN:
                win_p["blowoutWins"] = win_p.get("blowoutWins", 0) + 1

    for p in out.values():
        scores = p.pop("scores", [])
        p["stdev"] = round(statistics.pstdev(scores), 1) if len(scores) > 1 else 0.0
        p["high"] = max(scores) if scores else 0.0
        p["low"] = min(scores) if scores else 0.0
        p.setdefault("closeGames", 0)
        p.setdefault("closeWins", 0)
        p.setdefault("pointsInLosses", 0.0)
        p.setdefault("heartbreaks", 0)
        p.setdefault("blowoutWins", 0)
        p["closeWinPct"] = (round(p["closeWins"] / p["closeGames"], 3)
                            if p["closeGames"] >= MIN_CLOSE_GAMES else None)
        # Second half vs first half average -- who got hot down the stretch.
        # Needs enough weeks for the halves to mean anything.
        if len(scores) >= MIN_WEEKS_FOR_SPLIT:
            half = len(scores) // 2
            first_half = sum(scores[:half]) / half
            second_half = sum(scores[half:]) / (len(scores) - half)
            p["surge"] = round(second_half - first_half, 1)
        else:
            p["surge"] = None
    return out


def season_records(season):
    """Single-game and single-week superlatives for one season.

    Ties resolve to the earliest week (records are only replaced on a
    strict improvement), so a rebuild is deterministic.
    """
    if not season["weeks"]:
        return {}
    owner = {s["teamId"]: s["owner"] for s in season["standings"]}

    blowout = closest = high = low = None
    tough_loss = cheap_win = shootout = None

    for w in season["weeks"]:
        for g in w["games"]:
            if g["winner"] is None:
                continue
            win_id = g["winner"]
            home_won = win_id == g["home"]
            lose_id = g["away"] if home_won else g["home"]
            win_score = g["homeScore"] if home_won else g["awayScore"]
            lose_score = g["awayScore"] if home_won else g["homeScore"]

            margin = round(win_score - lose_score, 1)
            entry = {"margin": margin, "week": w["week"],
                     "winner": owner.get(win_id), "loser": owner.get(lose_id),
                     "winnerScore": win_score, "loserScore": lose_score,
                     "combined": round(win_score + lose_score, 1)}
            if blowout is None or margin > blowout["margin"]:
                blowout = entry
            if closest is None or margin < closest["margin"]:
                closest = entry
            if shootout is None or entry["combined"] > shootout["combined"]:
                shootout = entry

            # Highest score that still lost / lowest score that still won.
            if tough_loss is None or lose_score > tough_loss["score"]:
                tough_loss = {"score": lose_score, "week": w["week"],
                              "owner": owner.get(lose_id),
                              "opponent": owner.get(win_id),
                              "opponentScore": win_score}
            if cheap_win is None or win_score < cheap_win["score"]:
                cheap_win = {"score": win_score, "week": w["week"],
                             "owner": owner.get(win_id),
                             "opponent": owner.get(lose_id),
                             "opponentScore": lose_score}

        for t in w["teams"]:
            e = {"score": t["score"], "week": w["week"],
                 "owner": owner.get(t["teamId"])}
            if high is None or t["score"] > high["score"]:
                high = e
            if low is None or t["score"] < low["score"]:
                low = e

    return {"blowout": blowout, "closest": closest, "high": high, "low": low,
            "toughLoss": tough_loss, "cheapWin": cheap_win,
            "shootout": shootout}


def _leaders(rows, key, reverse=True):
    """Every row tied for the max (or min) `key`, ordered by teamId.

    Returns a list because ties are real and a league notices them: in 2025
    two owners both stole six games while scoring in the bottom half, and
    quietly handing the award to one of them invites an argument the data
    does not actually support. Empty list if no row has that stat.
    """
    rows = [r for r in rows if r.get(key) is not None]
    if not rows:
        return []
    best = (max if reverse else min)(r[key] for r in rows)
    return sorted((r for r in rows if r[key] == best),
                  key=lambda r: r["teamId"])


def _names(rows):
    """'A', 'A & B', or 'A, B & C' for a list of co-winners."""
    return join_names([r["owner"] for r in rows])


def join_names(names):
    """'A', 'A & B', or 'A, B & C'."""
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " & " + names[-1]


def short_names(owners):
    """Map each full owner name to the shortest name that stays unambiguous.

    The league talks about each other by first name, and team names change
    every year while people do not -- so the person is the identity the site
    leads with, and team names were rejected as a disambiguator for exactly
    that reason.

    First name alone wherever it is unique. Where two owners share one, each
    gets the *shortest* surname prefix that separates them, as an
    abbreviation: this league's Daniel Senger and Daniel Sharp become
    "Daniel Se." and "Daniel Sh." (one letter would not do it -- both are S).
    Surnames reach this function already truncated by fetch.redact_members,
    so even the full stored value is only a few characters.

    Computed over *all* seasons at once so a given owner reads the same on
    every page, rather than shortening on pages where the other Daniel
    happens not to appear.
    """
    by_first = {}
    for owner in owners:
        if not owner:
            continue
        by_first.setdefault(owner.split()[0], []).append(owner)

    out = {}
    for first, group in by_first.items():
        unique = sorted(set(group))
        if len(unique) == 1:
            out[unique[0]] = first
            continue
        surnames = {o: " ".join(o.split()[1:]) for o in unique}
        # Grow the prefix until every surname in this group is distinct.
        longest = max((len(v) for v in surnames.values()), default=0)
        n = 1
        while n < longest and len({v[:n] for v in surnames.values()}) < len(unique):
            n += 1
        for owner in unique:
            prefix = surnames[owner][:n]
            out[owner] = f"{first} {prefix}." if prefix else first
    return out


def season_awards(season, all_play, profile):
    """Named end-of-season superlatives.

    Deliberately NOT random. build.py's output has to be deterministic:
    the daily workflow commits only when docs/ changes, so an award that
    rerolled every run would manufacture a commit each morning and make the
    git history useless as a record of what actually moved. These are fixed
    rules that happen to be fun.

    Each award is {key, emoji, name, blurb, owner, detail}. Awards whose
    stat does not exist yet are omitted rather than rendered empty.
    """
    rows = []
    for s in season["standings"]:
        ap = all_play.get(s["teamId"], {})
        pr = profile.get(s["teamId"], {})
        rows.append({**s, "allPlayPct": ap.get("pct"), "stdev": pr.get("stdev"),
                     "high": pr.get("high"), "low": pr.get("low"),
                     "weeklyFirsts": pr.get("weeklyFirsts"),
                     "weeklyLasts": pr.get("weeklyLasts"),
                     "luckyWins": pr.get("luckyWins"),
                     "unluckyLosses": pr.get("unluckyLosses"),
                     "surge": pr.get("surge"),
                     "closeWinPct": pr.get("closeWinPct"),
                     "closeWins": pr.get("closeWins"),
                     "closeGames": pr.get("closeGames")})

    weeks = len(season["weeks"])
    awards = []

    def add(key, emoji, name, blurb, winners, detail):
        # Winners are carried as a list of full owner names; joining and
        # shortening them for display is the template's job.
        if winners:
            awards.append({"key": key, "emoji": emoji, "name": name,
                           "blurb": blurb,
                           "owners": [w["owner"] for w in winners],
                           "shared": len(winners) > 1,
                           "detail": detail(winners[0])})

    add("wall", "\U0001F9F1", "The Wall",
        "Best record if everyone played everyone every week, schedule removed.",
        _leaders(rows, "allPlayPct"),
        lambda r: "{:.1f}% all-play".format(r["allPlayPct"] * 100))

    add("metronome", "\U0001F3AF", "The Metronome",
        "Smallest week-to-week swing. You always knew what was coming.",
        _leaders(rows, "stdev", reverse=False),
        lambda r: "±{} pts per week".format(r["stdev"]))

    add("rollercoaster", "\U0001F3A2", "The Rollercoaster",
        "Biggest week-to-week swing. Boom or bust, never in between.",
        _leaders(rows, "stdev"),
        lambda r: "±{} pts per week".format(r["stdev"]))

    if any(r["unluckyLosses"] for r in rows):
        add("robbed", "\U0001F494", "Robbed",
            "Most weeks scoring top half and losing the matchup anyway.",
            _leaders(rows, "unluckyLosses"),
            lambda r: "{} of {} weeks".format(r["unluckyLosses"], weeks))

    if any(r["luckyWins"] for r in rows):
        add("horseshoe", "\U0001F340", "Horseshoe",
            "Most wins while scoring in the bottom half. Found a way.",
            _leaders(rows, "luckyWins"),
            lambda r: "{} of {} weeks".format(r["luckyWins"], weeks))

    add("punchingbag", "\U0001F94A", "Punching Bag",
        "Faced the most points all season. Nobody had a harder draw.",
        _leaders(rows, "pointsAgainst"),
        lambda r: "{} points against".format(r["pointsAgainst"]))

    add("ceiling", "\U0001F525", "Highest Ceiling",
        "The single biggest week anyone put up.",
        _leaders(rows, "high"),
        lambda r: "{} in one week".format(r["high"]))

    # No "coldest night" award: the Lowest Score record already names that
    # owner for that exact week, and awarding it too is the same dig twice.
    # One factual record is a record; repeating it is piling on.

    if any(r["surge"] is not None for r in rows):
        add("closer", "\U0001F4C8", "The Closer",
            "Biggest jump from the first half of the season to the second.",
            _leaders(rows, "surge"),
            lambda r: "+{} pts per week after the break".format(r["surge"]))

    if any(r["closeWinPct"] is not None for r in rows):
        add("clutch", "⏱️", "Clutch",
            "Best record in games decided by under {:g} points.".format(
                CLOSE_GAME_MARGIN),
            _leaders(rows, "closeWinPct"),
            lambda r: "{}-{} in close games".format(
                r["closeWins"], r["closeGames"] - r["closeWins"]))

    if any(r["weeklyFirsts"] for r in rows):
        add("topdog", "\U0001F451", "Week Winner",
            "Led the entire league in scoring the most times.",
            _leaders(rows, "weeklyFirsts"),
            lambda r: "{} weekly high{}".format(
                r["weeklyFirsts"], "s" if r["weeklyFirsts"] != 1 else ""))

    # Paper Tiger only means anything once there is a cut to miss.
    cut = season.get("playoffTeamCount") or (len(season["standings"]) // 2)
    missed = [r for r in rows if r["rank"] > cut]
    if missed:
        add("papertiger", "\U0001F42F", "Paper Tiger",
            "Most points scored by a team that missed the top {}.".format(cut),
            _leaders(missed, "pointsFor"),
            lambda r: "{} PF, finished {}th".format(r["pointsFor"], r["rank"]))

    return awards


def build_season_stats(season):
    """Everything the Stats page needs for one season, in one call."""
    all_play = all_play_records(season)
    profile = scoring_profile(season)
    table = []
    for s in season["standings"]:
        ap = all_play.get(s["teamId"], {})
        pr = profile.get(s["teamId"], {})
        table.append({
            "owner": s["owner"], "teamId": s["teamId"], "rank": s["rank"],
            "record": s["record"], "pointsFor": s["pointsFor"],
            "pointsAgainst": s["pointsAgainst"],
            "allPlayWins": ap.get("wins", 0),
            "allPlayLosses": ap.get("losses", 0),
            "allPlayTies": ap.get("ties", 0),
            "allPlayPct": ap.get("pct", 0.0),
            "stdev": pr.get("stdev", 0.0),
            "high": pr.get("high", 0.0), "low": pr.get("low", 0.0),
            "weeklyFirsts": pr.get("weeklyFirsts", 0),
            "weeklyLasts": pr.get("weeklyLasts", 0),
            "luckyWins": pr.get("luckyWins", 0),
            "unluckyLosses": pr.get("unluckyLosses", 0),
            "pointsInLosses": pr.get("pointsInLosses", 0.0),
            "heartbreaks": pr.get("heartbreaks", 0),
            "blowoutWins": pr.get("blowoutWins", 0),
        })
    return {"table": table,
            "records": season_records(season),
            "awards": season_awards(season, all_play, profile)}


def build_team_season(season, team_id):
    """One team's single-season story for its team page (ENH-025).

    Returns None when team_id is not in this season, so a build can skip a
    stale link. Otherwise a dict with:

    - `weeks`: one entry per regular-season week the team played: its score,
      that week's score-to-beat line, the dual-point split, and the matchup
      result. Regular season only -- dual points don't count anywhere else,
      and the schedule table the page renders from this must stay clean of
      playoff games.
    - `postseason`: the team's playoff/consolation games from the season's
      `postseason` list, shown in their own table and never counted.
    - `h2h`: the regular-season head-to-head against each other team: W-L-T,
      points for/against, margin.

    Pure function of the season dict; the same standing rules as the rest of
    the module (weeks looked up by week number, decimals left untruncated).
    """
    standings = season.get("standings") or []
    info = next((s for s in standings if s["teamId"] == team_id), None)
    if info is None:
        return None
    owner = {s["teamId"]: s["owner"] for s in standings}
    name = {s["teamId"]: s.get("name") for s in standings}

    def result_of(game):
        winner = game["winner"]
        if winner == team_id:
            return "W"
        return "T" if winner is None else "L"

    weeks = []
    h2h = {}
    for w in season.get("weeks") or []:
        t = next((t for t in w["teams"] if t["teamId"] == team_id), None)
        game = next((g for g in w["games"]
                     if team_id in (g["home"], g["away"])), None)
        if t is None or game is None:
            continue
        home = game["home"] == team_id
        opponent = game["away"] if home else game["home"]
        my_score = game["homeScore"] if home else game["awayScore"]
        their_score = game["awayScore"] if home else game["homeScore"]
        result = result_of(game)
        weeks.append({
            "week": w["week"],
            "score": t["score"],
            "scoreToBeat": w["scoreToBeat"],
            "topHalf": t["topHalf"],
            "h2hPoint": t["h2h"],
            "weekPoints": t["weekPoints"],
            "opponentId": opponent,
            "opponent": owner.get(opponent),
            "opponentScore": their_score,
            "result": result,
        })
        rec = h2h.setdefault(opponent,
                             {"wins": 0, "losses": 0, "ties": 0,
                              "pf": 0.0, "pa": 0.0})
        if result == "W":
            rec["wins"] += 1
        elif result == "T":
            rec["ties"] += 1
        else:
            rec["losses"] += 1
        rec["pf"] += my_score
        rec["pa"] += their_score

    rows = []
    for other in sorted(h2h):
        rec = h2h[other]
        rows.append({
            "teamId": other,
            "name": name.get(other),
            "owner": owner[other],
            "wins": rec["wins"],
            "losses": rec["losses"],
            "ties": rec["ties"],
            "pointsFor": round(rec["pf"], 1),
            "pointsAgainst": round(rec["pa"], 1),
            "margin": round(rec["pf"] - rec["pa"], 1),
        })
    rows.sort(key=lambda r: (-r["wins"], -r["margin"], r["owner"]))

    postseason = []
    for g in season.get("postseason") or []:
        if team_id not in (g["home"], g["away"]):
            continue
        home = g["home"] == team_id
        opponent = g["away"] if home else g["home"]
        postseason.append({
            "week": g["week"],
            "tier": g.get("tier"),
            "opponentId": opponent,
            "opponent": owner.get(opponent),
            "score": g["homeScore"] if home else g["awayScore"],
            "opponentScore": g["awayScore"] if home else g["homeScore"],
            "result": result_of(g),
        })
    postseason.sort(key=lambda g: (g["week"], g["opponentId"] or 0))

    return {
        "teamId": team_id,
        "name": info.get("name"),
        "owner": info["owner"],
        "rank": info["rank"],
        "points": info["points"],
        "record": info.get("record"),
        "pointsFor": info.get("pointsFor"),
        "pointsAgainst": info.get("pointsAgainst"),
        "finalRank": info.get("finalRank"),
        "weeks": weeks,
        "postseason": postseason,
        "h2h": rows,
    }


# --------------------------------------------------------------------------
# Prize money.
#
# The pot is entryFee x league size, which is exactly what data/prizes.json
# pays out, so winnings minus the entry fee is a real profit/loss number.
#
# Resolution lives here rather than in the template because two different
# views need it -- the prize table and the payout ranking -- and having the
# Jinja macro own it once meant the two could silently disagree.
# --------------------------------------------------------------------------

def prizes_for_season(config, season):
    """The prize list that applies to one season.

    `config` is either a plain list (one structure for every season) or a
    dict with a "default" list and optional per-year overrides keyed by the
    season as a string. The override exists because a league's pot changes
    over the years and quietly applying today's structure to 2022 would
    invent history.
    """
    if isinstance(config, list):
        return config
    if not isinstance(config, dict):
        return []
    return config.get(str(season)) or config.get("default") or []


def resolve_prizes(season, prizes):
    """Pair each prize with the owner who won it.

    Returns [{prize, owner, amount, label, decided}]. `owner` is None and
    `decided` False when the result isn't known yet (mid-season, or a
    prize whose award key nothing satisfies).
    """
    standings = season.get("standings") or []
    by_final = {s.get("finalRank"): s for s in standings if s.get("finalRank")}
    playoffs = season.get("playoffs") or {}
    owner_by_team = {s["teamId"]: s["owner"] for s in standings}

    top_pf = None
    if standings:
        top_pf = max(standings, key=lambda s: (s["pointsFor"], -s["teamId"]))

    out = []
    for prize in prizes:
        award, rank = prize.get("award"), prize.get("rank", 1)
        owner = None
        if award == "standings":
            row = next((s for s in standings if s["rank"] == rank), None)
            owner = row["owner"] if row else None
        elif award == "finalRank":
            row = by_final.get(rank)
            owner = row["owner"] if row else None
        elif award == "regSeasonPF":
            owner = top_pf["owner"] if top_pf else None
        elif award == "playoffsPF":
            owner = owner_by_team.get(playoffs.get("mostPointsFor"))
        out.append({"label": prize.get("label", ""),
                    "amount": prize.get("amount", 0),
                    "bye": prize.get("bye", False),
                    "owner": owner, "decided": owner is not None})
    return out


def season_payouts(season, prizes):
    """Who took home what, ranked by total.

    The headline point: the champion does not automatically top this. The
    title pays $90, but a regular-season winner who also led the league in
    scoring and finished 2nd overall collects $25 + $30 + $60 = $115. The
    prize table shows who won each line; this shows who actually cashed.

    Returns rows of {owner, total, net, prizes: [{label, amount}]}, sorted
    by total desc then owner, including owners who won nothing.
    """
    resolved = resolve_prizes(season, prizes)
    fee = season.get("entryFee") or 0

    rows = {}
    for s in season.get("standings") or []:
        rows[s["owner"]] = {"owner": s["owner"], "total": 0, "prizes": []}
    for item in resolved:
        if not item["decided"]:
            continue
        row = rows.setdefault(item["owner"],
                              {"owner": item["owner"], "total": 0, "prizes": []})
        row["total"] += item["amount"]
        row["prizes"].append({"label": item["label"], "amount": item["amount"]})

    for row in rows.values():
        row["entryFee"] = fee
        row["net"] = round(row["total"] - fee, 2)
        # Whole dollars read better than 115.0 when every prize is an int.
        if row["net"] == int(row["net"]):
            row["net"] = int(row["net"])

    return sorted(rows.values(), key=lambda r: (-r["total"], r["owner"]))


def career_payouts(all_standings, config):
    """All-time winnings per owner across every season on file.

    Only seasons whose prizes are fully decided contribute, so an
    in-progress year doesn't hand out money that hasn't been won. Returns
    rows of {owner, total, net, seasons, bySeason: {year: amount}, titles},
    sorted by total desc.
    """
    rows = {}
    for season in all_standings:
        prizes = prizes_for_season(config, season["season"])
        resolved = resolve_prizes(season, prizes)
        # A season pays out only once every prize on it has been decided.
        if not resolved or not all(item["decided"] for item in resolved):
            continue
        year = season["season"]
        fee = season.get("entryFee") or 0
        for s in season.get("standings") or []:
            row = rows.setdefault(s["owner"], {
                "owner": s["owner"], "total": 0, "paid": 0,
                "seasons": 0, "bySeason": {}})
            row["seasons"] += 1
            row["paid"] += fee
            row["bySeason"].setdefault(year, 0)
        for item in resolved:
            row = rows.get(item["owner"])
            if row is None:
                continue
            row["total"] += item["amount"]
            row["bySeason"][year] = row["bySeason"].get(year, 0) + item["amount"]

    for row in rows.values():
        row["net"] = round(row["total"] - row["paid"], 2)
        for key in ("net", "paid", "total"):
            if row[key] == int(row[key]):
                row[key] = int(row[key])
    return sorted(rows.values(), key=lambda r: (-r["total"], r["owner"]))


def main():
    parser = argparse.ArgumentParser(
        description="Compute FFF dual-point standings from raw ESPN data.")
    parser.add_argument("--season", type=int, default=datetime.now().year,
                        help="Season year to compute (default: current year)")
    args = parser.parse_args()
    season = args.season

    raw_path = Path("data") / f"raw-{season}.json"
    if not raw_path.exists():
        print(f"ERROR: {raw_path} not found. Run fetch.py --season {season} first.",
              file=sys.stderr)
        sys.exit(1)
    raw = json.loads(raw_path.read_text())

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    standings = build_standings(raw, updated)

    out = Path("data") / f"standings-{season}.json"
    # ENH-025: keep the old `updated` stamp when nothing else changed. The
    # stamp is rendered on every page, so re-stamping a run whose data did
    # not move would change docs/ every morning and the daily bot would
    # commit a diff it manufactured. (Value-only compare: dict equality
    # ignores key order, so a reordered-but-identical file still counts.)
    if out.exists():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            old = None
        if isinstance(old, dict):
            candidate = dict(standings)
            candidate["updated"] = old.get("updated")
            if candidate == old:
                standings = candidate
    out.write_text(json.dumps(standings, indent=2) + "\n")
    print(f"Wrote {out} ({out.stat().st_size} bytes), "
          f"through week {standings['throughWeek']} of {standings['regularSeasonWeeks']}")


if __name__ == "__main__":
    main()