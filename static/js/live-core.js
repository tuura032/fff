/* live-core.js — pure model layer for the Live page (ENH-029).
 *
 * UMD: loads as window.LIVE in the browser and as a CommonJS module in
 * Node (tests/live-core.test.js, run with `node --test`). No DOM, no I/O —
 * everything takes raw ESPN payloads (or our live-data.json) and returns
 * plain data.
 *
 * The rules MUST match compute.py (SPEC.md §1), not the thinkingcap
 * prototype that inspired the page structure:
 *  - score to beat = scores sorted ascending, index n // 2 - 1 — the
 *    highest score that MISSED the top half (the 7th-best of 12).
 *  - the top-half point goes only to scores STRICTLY greater than it;
 *    an exact tie at the boundary gives neither team the point.
 *  - the H2H point goes only to the STRICTLY higher score; an exact tie
 *    gives neither team the point.
 * tests/live-core.test.js asserts parity against data/standings-2025.json
 * so this file and compute.py cannot drift apart.
 */
(function (root, factory) {
  if (typeof module === 'object' && typeof module.exports === 'object') {
    module.exports = factory();
  } else {
    root.LIVE = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var LEAGUE_ID = '877873';

  /** The ESPN read URL the Live page fetches directly from the browser. */
  function liveUrl(season) {
    return (
      'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/' +
      season + '/segments/0/leagues/' + LEAGUE_ID +
      '?view=mMatchupScore&view=mScoreboard&view=mTeam&view=mSettings'
    );
  }

  /** Coerce an ESPN value to a number; null when missing/invalid. */
  function toNum(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  /** The league's in-progress week (1-based), from status.currentMatchupPeriod. */
  function currentWeek(data) {
    var s = data && data.status ? data.status : null;
    return s ? toNum(s.currentMatchupPeriod) : null;
  }

  /**
   * The week's schedule entries, grouped by matchupPeriodId — never by
   * index (standing rule: playoff weeks don't have a fixed entry count).
   *
   * Each side becomes { teamId, live, projected, winProbability } where
   *  - live      = totalPointsLive, falling back to totalPoints
   *  - projected = totalProjectedPointsLive, falling back to live
   * so a side that is not (yet) in game still shows the number ESPN
   * reports. Values are kept exactly as ESPN reports them — no rounding,
   * one decimal is a display concern (live.js).
   *
   * @returns {{ games: Array, byes: Array }}
   */
  function weekEntries(data, period) {
    var games = [];
    var byes = [];
    var want = toNum(period);
    var side = function (t) {
      if (!t) return null;
      var final = toNum(t.totalPoints);
      var live = toNum(t.totalPointsLive);
      var projected = toNum(t.totalProjectedPointsLive);
      return {
        teamId: toNum(t.teamId),
        live: live !== null ? live : final,
        projected: projected !== null ? projected : (live !== null ? live : final),
        winProbability: toNum(t.winProbability)
      };
    };
    for (var i = 0; i < ((data && data.schedule) || []).length; i++) {
      var e = data.schedule[i];
      if (toNum(e.matchupPeriodId) !== want) continue;
      if (e.away && e.home) {
        games.push({ id: toNum(e.id), winner: e.winner,
                     away: side(e.away), home: side(e.home) });
      } else if (e.home || e.away) {
        byes.push(side(e.home || e.away));
      }
    }
    return { games: games, byes: byes };
  }

  /**
   * Port of compute.score_to_beat: the highest score that missed the top
   * half. Sort ascending, take index n // 2 - 1 — [5] of 12, which is the
   * 7th-best. An odd field rounds the top half up (11 teams -> 6 earn the
   * point). Throws on a field of 0 or 1, like the Python original.
   */
  function scoreToBeat(scores) {
    var n = scores.length;
    if (n < 2) {
      throw new Error('scoreToBeat needs at least 2 scores, got ' + n);
    }
    return scores.slice().sort(function (a, b) { return a - b; })
      [Math.floor(n / 2) - 1]; // Python: scores[n // 2 - 1]
  }

  /**
   * This week's dual points for every team, in one mode.
   *
   *   mode 'live'      -> totalPointsLive (+ totalPoints fallback)
   *   mode 'projected' -> totalProjectedPointsLive (+ live fallback)
   *
   * Rules: +1 for the strictly higher score in the matchup, +1 for a
   * score strictly greater than the score to beat. The line pool is every
   * side of every game this week — byes are not in the pool and earn 0.
   *
   * @returns {{
   *   period:(number|null), mode:string, line:(number|null),
   *   teams: Array<{teamId:(number|null), score:(number|null), byed:boolean,
   *                 win:0|1, topHalf:0|1, dual:0|1|2, aboveLine:boolean}>
   * }}
   */
  function weekDualPoints(data, period, mode) {
    var entries = weekEntries(data, period);
    var scoreOf = function (side) {
      if (!side) return null;
      return mode === 'projected' ? side.projected : side.live;
    };

    var pool = [];
    for (var i = 0; i < entries.games.length; i++) {
      var g = entries.games[i];
      var sa = scoreOf(g.away);
      var sh = scoreOf(g.home);
      if (g.away && g.away.teamId !== null && sa !== null) {
        pool.push({ teamId: g.away.teamId, score: sa });
      }
      if (g.home && g.home.teamId !== null && sh !== null) {
        pool.push({ teamId: g.home.teamId, score: sh });
      }
    }

    // A field of 0/1 cannot split; no line, no top-half points. (compute.py
    // raises in that case, which is right for a committed season that
    // always fields all 12.)
    var line = pool.length >= 2
      ? scoreToBeat(pool.map(function (p) { return p.score; }))
      : null;

    var teams = {};
    var order = [];
    var add = function (teamId) {
      if (teamId === null || teamId === undefined) return null;
      if (!teams.hasOwnProperty(teamId)) {
        teams[teamId] = { teamId: teamId, score: null, byed: false,
                          win: 0, topHalf: 0, dual: 0, aboveLine: false };
        order.push(teamId);
      }
      return teams[teamId];
    };

    for (var gi = 0; gi < entries.games.length; gi++) {
      var game = entries.games[gi];
      var aScore = scoreOf(game.away);
      var hScore = scoreOf(game.home);
      var ra = add(game.away && game.away.teamId);
      var rh = add(game.home && game.home.teamId);
      if (ra) ra.score = aScore;
      if (rh) rh.score = hScore;
      if (aScore !== null && hScore !== null) {
        if (aScore > hScore) ra.win = 1;
        else if (hScore > aScore) rh.win = 1; // exact tie: no point either way
      }
    }
    for (var bi = 0; bi < entries.byes.length; bi++) {
      var b = entries.byes[bi];
      var rb = add(b && b.teamId);
      if (rb) {
        rb.byed = true;
        rb.score = scoreOf(b);
      }
    }
    var list = [];
    for (var ti = 0; ti < order.length; ti++) {
      var t = teams[order[ti]];
      // Byes are not matchups: 0 dual points, not in the line pool. Their
      // score (if ESPN reports one) is for display only.
      if (line !== null && t.score !== null && !t.byed) {
        t.aboveLine = t.score > line; // strictly greater; tie at the line gets nothing
      }
      t.topHalf = t.aboveLine ? 1 : 0;
      t.dual = t.win + t.topHalf;
      list.push(t);
    }
    return { period: toNum(period), mode: mode, line: line, teams: list };
  }

  /** Map teamId -> team name, from the ESPN payload. Names only — this
   *  page never displays owner names (ENH-029 "Names"). */
  function teamNames(data) {
    var map = {};
    for (var i = 0; i < ((data && data.teams) || []).length; i++) {
      var t = data.teams[i];
      var id = toNum(t && t.id);
      if (id !== null && t.name) map[id] = t.name;
    }
    return map;
  }

  /**
   * "If the week ended now": the season's dual points (from
   * live-data.json) plus this week's projected dual points, re-ranked,
   * with movement against the committed rank.
   *
   * Ties on the total are broken by the committed rank (stable), then
   * teamId, so the result is deterministic.
   *
   * @param {object} liveData  the docs/live-data.json payload
   * @param {object} week      weekDualPoints(..., 'projected') for the week
   * @returns {Array<{teamId, name, seasonPoints, weekPoints, total,
   *                  rank, movement}>} best first
   */
  function seasonIfEndedNow(liveData, week) {
    var weekById = {};
    for (var i = 0; i < week.teams.length; i++) {
      weekById[week.teams[i].teamId] = week.teams[i];
    }
    var rows = liveData.teams.map(function (t) {
      var w = weekById.hasOwnProperty(t.teamId) ? weekById[t.teamId] : null;
      return {
        teamId: t.teamId,
        name: t.name,
        seasonPoints: t.points,
        weekPoints: w ? w.dual : 0,
        total: t.points + (w ? w.dual : 0),
        oldRank: t.rank
      };
    });
    rows.sort(function (a, b) {
      if (b.total !== a.total) return b.total - a.total;
      if (a.oldRank !== b.oldRank) return a.oldRank - b.oldRank;
      return a.teamId - b.teamId;
    });
    return rows.map(function (r, i) {
      var rank = i + 1;
      return { teamId: r.teamId, name: r.name, seasonPoints: r.seasonPoints,
               weekPoints: r.weekPoints, total: r.total, rank: rank,
               movement: r.oldRank - rank };
    });
  }

  /**
   * Whether the "if it ended now" table is meaningful: the committed
   * standings cover everything up to (and including) last week. When the
   * daily bot has not caught up yet, adding this week would skip one.
   */
  function catchUp(liveData, period) {
    return !!liveData && liveData.throughWeek === toNum(period) - 1;
  }

  /**
   * True once every matchup this week is decided — the point at which
   * polling can stop for the week.
   */
  function allFinal(data, period) {
    var entries = weekEntries(data, period);
    if (!entries.games.length) return false;
    return entries.games.every(function (g) {
      return g.winner === 'HOME' || g.winner === 'AWAY' || g.winner === 'TIE';
    });
  }

  return {
    liveUrl: liveUrl,
    toNum: toNum,
    currentWeek: currentWeek,
    weekEntries: weekEntries,
    scoreToBeat: scoreToBeat,
    weekDualPoints: weekDualPoints,
    teamNames: teamNames,
    seasonIfEndedNow: seasonIfEndedNow,
    catchUp: catchUp,
    allFinal: allFinal
  };
});
