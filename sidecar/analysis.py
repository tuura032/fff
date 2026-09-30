"""Look-back analysis: how rankings have moved since the draft, and how
accurate each source was in weeks already played.

Pure functions over plain dicts (same conventions as model.py): positional
ranks are 1-based and lower is better, players are keyed by espnId.
Tested in tests/test_analysis.py.
"""
from statistics import mean

import model

POS_ORDER = ("QB", "RB", "WR", "TE", "K", "D/ST")

# "Starter-worthy" depth per position in a 12-team FFF week: QB/TE/K/D/ST
# start one each; RB and WR start two each (plus WR/TE and FLEX). A source
# is scored on how many of its top K finished top K.
TOP_K = {"QB": 12, "RB": 24, "WR": 24, "TE": 12, "K": 12, "D/ST": 12}


def since_draft(pre_ranks, now_ranks, positions):
    """Pre-draft consensus vs today's consensus, per player.

    pre_ranks / now_ranks: {source: {espnId: positionalRank}} (all sources
    used); positions: {espnId: pos}. Only positions ranked on both sides
    count, so kickers (no pre-draft ranks) aren't all "new".

    Returns {espnId: {"pre", "now", "change"}}: avg positional ranks
    rounded to 0.1, and change = pre - now (positive = moved up). A player
    ranked on only one side gets None for the other side and for change:
    "new since the draft" or "off the board".
    """
    pre = model.consensus(pre_ranks or {}, list(pre_ranks or {}))
    now = model.consensus(now_ranks or {}, list(now_ranks or {}))
    both = ({positions.get(p) for p in pre}
            & {positions.get(p) for p in now}) - {None}
    out = {}
    for pid in set(pre) | set(now):
        if positions.get(pid) not in both:
            continue
        a = pre[pid]["avg"] if pid in pre else None
        b = now[pid]["avg"] if pid in now else None
        out[pid] = {
            "pre": round(a, 1) if a is not None else None,
            "now": round(b, 1) if b is not None else None,
            "change": round(a - b, 1) if a is not None and b is not None
            else None,
        }
    return out


def actual_finish(points, positions):
    """{espnId: positional finish}; 1 = most points, ties share the better."""
    by_pos = {}
    for pid, pts in points.items():
        by_pos.setdefault(positions.get(pid), []).append(pts)
    return {pid: 1 + sum(1 for other in by_pos[positions.get(pid)]
                         if other > pts)
            for pid, pts in points.items()}


def _avg_ranks(values):
    """Ranks of values (1 = smallest), ties get the average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs, ys):
    """Spearman rank correlation; None when undefined (n < 3 or no spread)."""
    if len(xs) < 3:
        return None
    rx, ry = _avg_ranks(xs), _avg_ranks(ys)
    mx, my = mean(rx), mean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if not sxx or not syy:
        return None
    return sxy / (sxx * syy) ** 0.5


def week_accuracy(week_ranks, points, positions):
    """Score each source's ranks for one played week.

    week_ranks: {source: {espnId: positionalRank}} for the week.
    points: {espnId: actual points} for every player ESPN has for that
    week; a ranked player with no entry scored 0 (inactive, hurt).
    positions: {espnId: pos}.

    Returns {"summary": [...], "players": [...]}:
      summary, one row per (pos, source): n ranked, k, hits (of the
        source's top k, how many finished top k), rho (Spearman between
        the source's rank and the actual finish; 1.0 is perfect) and mae
        (mean |rank - finish|).
      players: every ranked player, plus top-k finishers no source ranked,
        with ranks, pts and finish.
    """
    ranked = set()
    for ranks in week_ranks.values():
        ranked |= set(ranks)
    pts = dict(points)
    for pid in ranked:
        pts.setdefault(pid, 0.0)
    pts = {pid: p for pid, p in pts.items() if positions.get(pid)}
    finish = actual_finish(pts, positions)

    summary = []
    for pos in POS_ORDER:
        k = TOP_K[pos]
        for source in sorted(week_ranks):
            ranks = week_ranks[source]
            ids = [pid for pid in ranks if positions.get(pid) == pos]
            if not ids:
                continue
            top = [pid for pid in ids if ranks[pid] <= k]
            rho = spearman([ranks[p] for p in ids], [finish[p] for p in ids])
            summary.append({
                "pos": pos, "source": source, "n": len(ids), "k": k,
                "hits": sum(1 for pid in top if finish[pid] <= k),
                "rho": round(rho, 3) if rho is not None else None,
                "mae": round(mean(abs(ranks[p] - finish[p]) for p in ids), 1),
            })

    shown = ranked | {pid for pid, f in finish.items()
                      if f <= TOP_K.get(positions.get(pid), 12)}
    players = [{
        "espnId": pid, "pos": positions.get(pid),
        "ranks": {s: r[pid] for s, r in sorted(week_ranks.items())
                  if pid in r},
        "pts": pts[pid], "finish": finish[pid],
    } for pid in shown if pid in finish]
    players.sort(key=lambda p: (POS_ORDER.index(p["pos"])
                                if p["pos"] in POS_ORDER else 99,
                                p["finish"], p["espnId"]))
    return {"summary": summary, "players": players}


def lookback(ranks, history):
    """The board's "Look back" block from ranks + the history payload.

    ranks: build_board's {view: {source: {espnId: rank}}} (includes the
    history views "predraft" and "week<n>"). history: the cached history
    payload (weeks, actuals keyed by str espnId).
    """
    acts = {int(k): v for k, v in ((history or {}).get("actuals") or {}).items()}
    positions = {pid: a["pos"] for pid, a in acts.items()}
    weeks = {}
    for w in (history or {}).get("weeks") or []:
        wr = ranks.get(f"week{w}")
        if not wr:
            continue
        pts = {pid: a["pts"][str(w)] for pid, a in acts.items()
               if str(w) in a["pts"]}
        weeks[str(w)] = week_accuracy(wr, pts, positions)
    pre = ranks.get("predraft") or {}
    return {
        "sinceDraft": {str(pid): v for pid, v in
                       since_draft(pre, ranks.get("ros") or {},
                                   positions).items()}
        if pre else {},
        "preSources": sorted(pre),
        "weeks": weeks,
    }
