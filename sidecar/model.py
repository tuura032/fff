"""Sidecar board math: scoring, positional ranks, consensus, tiers, advice.

Pure functions over plain dicts, with no I/O, no network and no AI, so
everything here is unit-tested with fixed inputs. The data shapes are in
COORDINATION.md. Owned by the Claude session.

Positional ranks are 1-based and lower is better everywhere. A player is
identified by ESPN's `espnId`.
"""
from statistics import mean, median

# ESPN defaultPositionId -> position.
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}

# ESPN proTeamId -> NFL abbr. The same table as compute.PRO_TEAMS, copied
# rather than imported so the sidecar never loads the site's pipeline code.
PRO_TEAMS = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG",
    20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL",
    34: "HOU",
}

# ESPN lineup slot -> positions that may fill it. FFF starts QB, RB x2,
# WR x2, WR/TE (5), FLEX (23), K, D/ST, and has no dedicated TE slot.
SLOT_ELIGIBLE = {
    0: {"QB"}, 2: {"RB"}, 4: {"WR"}, 5: {"WR", "TE"}, 6: {"TE"},
    23: {"RB", "WR", "TE"}, 16: {"D/ST"}, 17: {"K"},
}
BENCH_SLOT, IR_SLOT = 20, 21

# The Fantasy Footballers projection field -> (ESPN statId, divisor). The
# statIds are checked against compute.STAT_LABELS: 5 is "Passing yards (per
# 5)", so its stat value is yards / 5; 3 is plain passing yards, for
# leagues that score it that way. Projections are fractional, so there is no
# flooring.
FFB_STATS = {
    "passing_yards": [(3, 1), (5, 5)],
    "passing_touchdowns": [(4, 1)],
    "interceptions_thrown": [(20, 1)],
    "rushing_yards": [(24, 1)],
    "rushing_touchdowns": [(25, 1)],
    "receptions": [(53, 1)],
    "receiving_yards": [(42, 1)],
    "receiving_touchdowns": [(43, 1)],
    "fumbles_lost": [(72, 1)],
}


def espn_pos(default_position_id):
    return ESPN_POS.get(default_position_id)


# --------------------------------------------------------------------------
# Scoring

def points_by_stat(scoring_items):
    """{statId: points} from ESPN mSettings scoringItems.

    A pointsOverrides entry wins over the base value, the same rule as
    compute.build_scoring_table.
    """
    out = {}
    for it in scoring_items or []:
        overrides = it.get("pointsOverrides") or {}
        out[it["statId"]] = (next(iter(overrides.values())) if overrides
                             else it.get("points", 0))
    return out


def project_points(stats, pts_by_stat):
    """Projected fantasy points for one FFB projection row, in FFF scoring.

    Fields with no mapping, and statIds the league doesn't score, contribute
    nothing.
    """
    total = 0.0
    for field, targets in FFB_STATS.items():
        try:
            value = float(stats.get(field) or 0)
        except (TypeError, ValueError):
            continue
        for stat_id, divisor in targets:
            if stat_id in pts_by_stat:
                total += value / divisor * pts_by_stat[stat_id]
    return total


# --------------------------------------------------------------------------
# Ranks and consensus

def positional_ranks(rows, pts_by_stat=None):
    """Per-source positional ranks.

    rows: matched source rows (with espnId). A row with `rank` is ordered by
    that rank within (view, source, pos), so an overall rank becomes
    positional. A row with only `stats` is ordered by projected points,
    highest first. Ties go to the lower espnId, so results are deterministic.

    Returns {view: {source: {espnId: positionalRank}}}. If a player appears
    twice for one (view, source), the better entry wins.
    """
    groups = {}
    for r in rows:
        if r.get("rank") is not None:
            key = float(r["rank"])
        elif r.get("stats") is not None and pts_by_stat is not None:
            key = -project_points(r["stats"], pts_by_stat)
        else:
            continue
        g = groups.setdefault((r["view"], r["source"], r["pos"]), {})
        pid = r["espnId"]
        if pid not in g or key < g[pid]:
            g[pid] = key
    out = {}
    for (view, source, _pos), g in groups.items():
        ordered = sorted(g.items(), key=lambda kv: (kv[1], kv[0]))
        dest = out.setdefault(view, {}).setdefault(source, {})
        for i, (pid, _k) in enumerate(ordered, start=1):
            dest[pid] = i
    return out


def consensus(ranks_by_source, enabled):
    """Consensus over the enabled sources for one view.

    Returns {espnId: {"avg", "n", "spread", "ranks": {source: rank}}}, where
    avg is the mean positional rank across enabled sources that rank the
    player, n is how many did, and spread is max - min (0 for one source).
    """
    enabled = [s for s in enabled if s in ranks_by_source]
    per_player = {}
    for s in enabled:
        for pid, rank in ranks_by_source[s].items():
            per_player.setdefault(pid, {})[s] = rank
    out = {}
    for pid, ranks in per_player.items():
        vals = list(ranks.values())
        out[pid] = {"avg": mean(vals), "n": len(vals),
                    "spread": max(vals) - min(vals), "ranks": ranks}
    return out


def board_order(cons, n_enabled):
    """espnIds in board order.

    Players ranked by at least half of the enabled sources come first, by
    average; the rest follow, also by average. This keeps a player one
    source loves from outranking the consensus.
    """
    half = n_enabled / 2
    return sorted(cons, key=lambda pid: (cons[pid]["n"] < half,
                                         cons[pid]["avg"], pid))


def tiers(avgs):
    """Tier numbers (1-based) for a list of consensus averages, best first.

    A new tier starts where the gap to the previous player is larger than
    max(1.5, 2 * the median gap). Averages from several sources move in
    fractional steps, so a gap of 1.5+ spots, and twice the usual spacing,
    marks a real drop-off. The input must be sorted ascending.
    """
    if not avgs:
        return []
    gaps = [b - a for a, b in zip(avgs, avgs[1:])]
    threshold = max(1.5, 2 * median(gaps)) if gaps else 0
    out, tier = [1], 1
    for g in gaps:
        if g > threshold:
            tier += 1
        out.append(tier)
    return out


def movers(current, previous):
    """{espnId: spots moved} between two {espnId: avg} snapshots.

    Positive means the player moved up (better rank). Players missing from
    either snapshot are omitted.
    """
    return {pid: round(previous[pid] - avg, 1)
            for pid, avg in current.items() if pid in previous}


# --------------------------------------------------------------------------
# Team advice

def can_fill_lineup(positions, slot_counts):
    """True if these players' positions can fill every starting slot.

    positions: list of positions (IR players excluded by the caller).
    slot_counts: ESPN lineupSlotCounts ({"0": 1, "2": 2, ...}); bench and IR
    are ignored. This is a small bipartite matching, done most-constrained
    slot first, with backtracking.
    """
    slots = []
    for sid, count in (slot_counts or {}).items():
        sid = int(sid)
        if sid in SLOT_ELIGIBLE:
            slots += [SLOT_ELIGIBLE[sid]] * int(count)
    slots.sort(key=len)
    pool = list(positions)

    def fill(i):
        if i == len(slots):
            return True
        tried = set()
        for j, pos in enumerate(pool):
            if pos in slots[i] and pos not in tried:
                tried.add(pos)
                pool.pop(j)
                if fill(i + 1):
                    return True
                pool.insert(j, pos)
        return False

    return fill(0)


def upgrades(mine, free_agents, cons, slot_counts, margin=5):
    """"Add X, drop Y" suggestions.

    mine / free_agents: ESPN player dicts. cons: {espnId: {"avg": ...}},
    normally rest-of-season. A free agent is paired with the owner's worst
    ranked non-IR player at the same position when the free agent is at
    least `margin` positional spots better and the lineup can still be
    filled after the swap. Owned players with no consensus rank are skipped,
    not treated as worst: no rank usually means a matching gap, not a bad
    player. Each drop is suggested once, for its best add.

    Returns [{"add", "drop", "addAvg", "dropAvg", "gain"}], best gain first.
    """
    active = [p for p in mine if p.get("lineupSlotId") != IR_SLOT]
    worst_by_pos = {}
    for p in active:
        c = cons.get(p["espnId"])
        if c is None:
            continue
        cur = worst_by_pos.get(p["pos"])
        if cur is None or c["avg"] > cons[cur["espnId"]]["avg"]:
            worst_by_pos[p["pos"]] = p
    best = {}
    for fa in free_agents:
        c = cons.get(fa["espnId"])
        drop = worst_by_pos.get(fa["pos"])
        if c is None or drop is None:
            continue
        gain = cons[drop["espnId"]]["avg"] - c["avg"]
        if gain < margin:
            continue
        after = [p["pos"] for p in active if p is not drop] + [fa["pos"]]
        if not can_fill_lineup(after, slot_counts):
            continue
        prev = best.get(drop["espnId"])
        if prev is None or gain > prev["gain"]:
            best[drop["espnId"]] = {"add": fa, "drop": drop,
                                    "addAvg": c["avg"],
                                    "dropAvg": cons[drop["espnId"]]["avg"],
                                    "gain": round(gain, 1)}
    return sorted(best.values(), key=lambda s: (-s["gain"], s["add"]["espnId"]))


def drop_candidates(mine, free_agents, cons):
    """The owner's bench players, worst relative to the waiver wire first.

    For each bench player with a consensus rank, deficit = their avg minus
    the best free agent's avg at the same position. A positive deficit means
    the wire has someone better. Listed for the owner to judge, never
    automatic. Returns [{"player", "avg", "bestFreeAgent", "deficit"}].
    """
    best_fa = {}
    for fa in free_agents:
        c = cons.get(fa["espnId"])
        if c is None:
            continue
        cur = best_fa.get(fa["pos"])
        if cur is None or c["avg"] < cons[cur["espnId"]]["avg"]:
            best_fa[fa["pos"]] = fa
    out = []
    for p in mine:
        if p.get("lineupSlotId") != BENCH_SLOT or p["espnId"] not in cons:
            continue
        fa = best_fa.get(p["pos"])
        avg = cons[p["espnId"]]["avg"]
        deficit = (avg - cons[fa["espnId"]]["avg"]) if fa else None
        out.append({"player": p, "avg": avg, "bestFreeAgent": fa,
                    "deficit": None if deficit is None else round(deficit, 1)})
    return sorted(out, key=lambda d: (d["deficit"] is None,
                                      -(d["deficit"] or 0), d["player"]["espnId"]))


def bye_conflicts(mine, current_week, horizon=3):
    """Weeks in [current_week, current_week + horizon) where starters are out.

    Starters are players in a starting slot (not bench/IR). Returns
    {week: [players]} for weeks with at least one starter on bye; the UI
    highlights weeks where two or more share a position.
    """
    weeks = range(current_week, current_week + horizon)
    out = {}
    for p in mine:
        if p.get("lineupSlotId") in (BENCH_SLOT, IR_SLOT, None):
            continue
        if p.get("bye") in weeks:
            out.setdefault(p["bye"], []).append(p)
    return dict(sorted(out.items()))
