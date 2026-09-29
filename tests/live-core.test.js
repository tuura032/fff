'use strict';
/* Tests for the Live page model layer (static/js/live-core.js).
 *
 * Run: node --test tests/live-core.test.js
 *
 * The parity test at the bottom is the important one (ENH-029): every
 * regular-season week of 2025, recomputed from data/raw-2025.json, must
 * match data/standings-2025.json — that is what keeps the JS and
 * compute.py from drifting.
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const LIVE = require('../static/js/live-core.js');

/* ---------- synthetic ESPN payload builders ---------- */

function side(teamId, { totalPoints = null, live = null, projected = null,
                        wp = null } = {}) {
  return {
    teamId,
    totalPoints,
    totalPointsLive: live,
    totalProjectedPointsLive: projected,
    winProbability: wp
  };
}

function game(id, period, away, home, winner) {
  return { id, matchupPeriodId: period, away, home,
           winner: winner || 'UNDECIDED' };
}

function bye(period, t) {
  return { id: 900 + period, matchupPeriodId: period, home: t };
}

function team(id, name) {
  return { id, name, abbrev: 'T' + id, logo: '', primaryOwner: 'o' + id };
}

function payload({ currentMatchupPeriod = 3, entries, teams: t = [] } = {}) {
  return {
    id: 877873,
    seasonId: 2026,
    status: { currentMatchupPeriod, finalScoringPeriod: 14 },
    members: t.map((x) => ({ id: 'o' + x.id, firstName: 'M' })),
    teams: t,
    schedule: entries
  };
}

/* 12 teams, ids 1..12, paired (1,2) (3,4) ... in week 3, plus a stray
 * week-2 entry that must be ignored. live/projected keyed by team id. */
function twelveTeamWeek3(liveScores, projectedScores) {
  const ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  const entries = [
    game(1, 2, side(1, { totalPoints: 50 }), side(2, { totalPoints: 40 }), 'AWAY')
  ];
  for (let i = 0; i < ids.length; i += 2) {
    const a = ids[i];
    const b = ids[i + 1];
    const la = liveScores[a];
    const lb = liveScores[b];
    entries.push(game(
      100 + i, 3,
      side(a, { live: la, projected: projectedScores[a] }),
      side(b, { live: lb, projected: projectedScores[b] }),
      la > lb ? 'AWAY' : lb > la ? 'HOME' : 'UNDECIDED'
    ));
  }
  return payload({ currentMatchupPeriod: 3, entries,
                   teams: ids.map((id) => team(id, 'Team ' + id)) });
}

const DESC_12 = { 1: 150, 2: 140, 3: 135, 4: 130, 5: 125, 6: 120,
                  7: 115, 8: 110, 9: 105, 10: 100, 11: 95, 12: 90 };

/* ---------- scoreToBeat ---------- */

test('scoreToBeat: 12 distinct scores -> the 7th-best (index [5] ascending)', () => {
  const scores = [100, 105, 108, 110, 115, 118, 120, 125, 130, 135, 140, 150];
  assert.strictEqual(LIVE.scoreToBeat(scores), 118);
});

test('scoreToBeat: odd field rounds the top half up (11 teams -> 6 points)', () => {
  // ascending 1..11, index 11//2-1 = 4 -> 5; teams 6..11 (6 of them) beat it
  assert.strictEqual(LIVE.scoreToBeat([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]), 5);
});

test('scoreToBeat: a field of 0 or 1 scores throws, like compute.py', () => {
  assert.throws(() => LIVE.scoreToBeat([]), /at least 2/);
  assert.throws(() => LIVE.scoreToBeat([100]), /at least 2/);
});

test('scoreToBeat: does not mutate its input', () => {
  const scores = [3, 1, 2];
  LIVE.scoreToBeat(scores);
  assert.deepStrictEqual(scores, [3, 1, 2]);
});

/* ---------- weekDualPoints ---------- */

test('weekDualPoints: 12 distinct live scores, line is 115, points match', () => {
  const data = twelveTeamWeek3(DESC_12, DESC_12);
  const r = LIVE.weekDualPoints(data, 3, 'live');
  assert.strictEqual(r.line, 115); // sorted: 90 95 100 105 110 115 | 120..150
  const byId = {};
  r.teams.forEach((t) => { byId[t.teamId] = t; });
  for (let id = 1; id <= 6; id++) assert.strictEqual(byId[id].topHalf, 1, 'team ' + id);
  for (let id = 7; id <= 12; id++) assert.strictEqual(byId[id].topHalf, 0, 'team ' + id);
  assert.strictEqual(byId[1].win, 1);   // 150 > 140
  assert.strictEqual(byId[1].dual, 2);   // win + top half
  assert.strictEqual(byId[2].win, 0);
  assert.strictEqual(byId[2].dual, 1);   // lost, but top half
  assert.strictEqual(byId[7].dual, 1);   // won (115 > 110) but below the line
  assert.strictEqual(byId[12].dual, 0);
  // 6 wins + 6 top halves distributed
  assert.strictEqual(r.teams.reduce((n, t) => n + t.win, 0), 6);
  assert.strictEqual(r.teams.reduce((n, t) => n + t.topHalf, 0), 6);
});

test('weekDualPoints: exact tie at the boundary gives NEITHER team the point', () => {
  // 6th and 7th best both score 115 -> line is 115, neither beats it.
  const scores = { 1: 150, 2: 140, 3: 135, 4: 130, 5: 125, 6: 115,
                   7: 115, 8: 110, 9: 105, 10: 100, 11: 95, 12: 90 };
  const r = LIVE.weekDualPoints(twelveTeamWeek3(scores, scores), 3, 'live');
  assert.strictEqual(r.line, 115);
  const byId = {};
  r.teams.forEach((t) => { byId[t.teamId] = t; });
  assert.strictEqual(byId[6].topHalf, 0, 'tie at the line: no point');
  assert.strictEqual(byId[7].topHalf, 0, 'tie at the line: no point');
  // the league awards 5 top-half points this week, not 7
  assert.strictEqual(r.teams.reduce((n, t) => n + t.topHalf, 0), 5);
});

test('weekDualPoints: exact H2H tie gives neither team the win point', () => {
  const scores = { 1: 120.5, 2: 120.5, 3: 118, 4: 116, 5: 114, 6: 112,
                   7: 110, 8: 108, 9: 106, 10: 104, 11: 102, 12: 100 };
  const r = LIVE.weekDualPoints(twelveTeamWeek3(scores, scores), 3, 'live');
  const byId = {};
  r.teams.forEach((t) => { byId[t.teamId] = t; });
  assert.strictEqual(byId[1].win, 0);
  assert.strictEqual(byId[2].win, 0);
});

test('weekDualPoints: byes earn 0 and stay out of the line pool', () => {
  const entries = [
    game(101, 3, side(1, { live: 100 }), side(2, { live: 90 })),
    game(102, 3, side(3, { live: 95 }), side(4, { live: 85 })),
    bye(3, side(5, { live: 999 })) // a bye scoring 999 must not move the line
  ];
  const data = payload({ entries, teams: [1, 2, 3, 4, 5].map((i) => team(i, 'T' + i)) });
  const r = LIVE.weekDualPoints(data, 3, 'live');
  const byId = {};
  r.teams.forEach((t) => { byId[t.teamId] = t; });
  assert.strictEqual(r.line, 90); // pool is [85, 90, 95, 100]; bye excluded
  assert.strictEqual(byId[5].byed, true);
  assert.strictEqual(byId[5].dual, 0);
  assert.strictEqual(byId[5].topHalf, 0);
});

test('weekDualPoints: projected mode reads the projected field', () => {
  const live = { 1: 100, 2: 90, 3: 80, 4: 70 };
  const proj = { 1: 101, 2: 105, 3: 85, 4: 75 }; // projected flips game (1,2)
  const data = twelveTeamWeek3(live, proj);
  const rLive = LIVE.weekDualPoints(data, 3, 'live');
  const rProj = LIVE.weekDualPoints(data, 3, 'projected');
  const byId = (r) => { const m = {}; r.teams.forEach((t) => { m[t.teamId] = t; }); return m; };
  assert.strictEqual(byId(rLive)[1].win, 1);   // live: 100 > 90
  assert.strictEqual(byId(rProj)[2].win, 1);   // projected: 105 > 101
  assert.strictEqual(byId(rLive)[1].score, 100);
  assert.strictEqual(byId(rProj)[1].score, 101);
});

test('weekDualPoints: falls back to totalPoints when live fields are absent', () => {
  const entries = [
    game(1, 3, side(1, { totalPoints: 105.7 }), side(2, { totalPoints: 99.3 })),
    game(2, 3, side(3, { totalPoints: 90 }), side(4, { totalPoints: 88 }))
  ];
  const data = payload({ entries, teams: [1, 2, 3, 4].map((i) => team(i, 'T' + i)) });
  const r = LIVE.weekDualPoints(data, 3, 'live');
  const byId = {};
  r.teams.forEach((t) => { byId[t.teamId] = t; });
  assert.strictEqual(byId[1].score, 105.7, 'decimals kept exactly as reported');
  assert.strictEqual(r.line, 90, 'line is the highest score that missed: 88 90 | 99.3 105.7');
  // a line can itself be a reported decimal — kept exactly
  assert.strictEqual(LIVE.scoreToBeat([105.7, 99.3]), 99.3);
});

test('weekDualPoints: only the requested period is used', () => {
  const data = twelveTeamWeek3(DESC_12, DESC_12);
  const r2 = LIVE.weekDualPoints(data, 2, 'live'); // the stray week-2 game
  assert.strictEqual(r2.teams.length, 2);
});


/* ---------- payload helpers ---------- */

test('currentWeek: reads status.currentMatchupPeriod', () => {
  const data = twelveTeamWeek3(DESC_12, DESC_12);
  assert.strictEqual(LIVE.currentWeek(data), 3);
  assert.strictEqual(LIVE.currentWeek({}), null);
  assert.strictEqual(LIVE.currentWeek(null), null);
});

test('weekEntries: groups by matchupPeriodId, never by index', () => {
  const data = twelveTeamWeek3(DESC_12, DESC_12);
  const { games, byes } = LIVE.weekEntries(data, 3);
  assert.strictEqual(games.length, 6);
  assert.strictEqual(byes.length, 0);
  assert.strictEqual(games[0].away.live, 150); // kept exactly as reported
});

test('liveUrl: season, league and the four views', () => {
  const url = LIVE.liveUrl(2026);
  const u = new URL(url);
  assert.strictEqual(u.origin + u.pathname,
    'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leagues/877873');
  assert.deepStrictEqual([...u.searchParams.getAll('view')],
    ['mMatchupScore', 'mScoreboard', 'mTeam', 'mSettings']);
});

test('teamNames: teamId -> name only, no owner names', () => {
  const data = twelveTeamWeek3(DESC_12, DESC_12);
  const names = LIVE.teamNames(data);
  assert.strictEqual(names[1], 'Team 1');
  assert.strictEqual(Object.keys(names).length, 12);
  for (const n of Object.values(names)) assert.ok(!/^\s*M/.test(n) || n.startsWith('Team'));
});

test('teamLogos: teamId -> logo URL, empty and missing logos skipped', () => {
  const data = payload({ teams: [
    { id: 1, name: 'A', logo: 'https://a.espncdn.com/1.svg' },
    { id: 2, name: 'B', logo: '' },      // unset -> UI falls back to name only
    { id: 3, name: 'C' }                  // field absent entirely
  ] });
  const logos = LIVE.teamLogos(data);
  assert.strictEqual(logos[1], 'https://a.espncdn.com/1.svg');
  assert.strictEqual(Object.keys(logos).length, 1);
  assert.deepStrictEqual(LIVE.teamLogos(twelveTeamWeek3(DESC_12, DESC_12)), {});
  assert.deepStrictEqual(LIVE.teamLogos(null), {});
});

test('allFinal: false while any game is undecided, true once all decided', () => {
  const data = twelveTeamWeek3(DESC_12, DESC_12);
  // twelveTeamWeek3 sets winner UNDECIDED only on exact ties; no ties here
  assert.strictEqual(LIVE.allFinal(data, 3), true);
  data.schedule[data.schedule.length - 1].winner = 'UNDECIDED';
  assert.strictEqual(LIVE.allFinal(data, 3), false);
  assert.strictEqual(LIVE.allFinal(data, 99), false); // no games -> not final
});

test('catchUp: true only when throughWeek is the week before', () => {
  const liveData = { throughWeek: 2 };
  assert.strictEqual(LIVE.catchUp(liveData, 3), true);
  assert.strictEqual(LIVE.catchUp(liveData, 4), false);
  assert.strictEqual(LIVE.catchUp(null, 3), false);
});

/* ---------- seasonIfEndedNow ---------- */

test('seasonIfEndedNow: adds projected points, re-ranks, shows movement', () => {
  const liveData = {
    season: 2026, throughWeek: 2, regularSeasonWeeks: 14,
    teams: [
      { teamId: 1, name: 'A', points: 4, rank: 1 },
      { teamId: 2, name: 'B', points: 4, rank: 2 },
      { teamId: 3, name: 'C', points: 2, rank: 3 },
      { teamId: 4, name: 'D', points: 0, rank: 4 }
    ]
  };
  // Week: 1 takes 0, 2 takes 2 (leads on 6), 3 takes 2 (ties 1 on 4 ->
  // keeps 3rd by committed rank), 4 takes 1
  const week = {
    period: 3, mode: 'projected', line: 100,
    teams: [
      { teamId: 1, score: 90, byed: false, win: 0, topHalf: 0, dual: 0, aboveLine: false },
      { teamId: 2, score: 150, byed: false, win: 1, topHalf: 1, dual: 2, aboveLine: true },
      { teamId: 3, score: 140, byed: false, win: 1, topHalf: 1, dual: 2, aboveLine: true },
      { teamId: 4, score: 110, byed: false, win: 0, topHalf: 1, dual: 1, aboveLine: true }
    ]
  };
  const rows = LIVE.seasonIfEndedNow(liveData, week);
  assert.deepStrictEqual(
    rows.map((r) => [r.teamId, r.total, r.rank, r.movement]),
    [[2, 6, 1, 1], [1, 4, 2, -1], [3, 4, 3, 0], [4, 1, 4, 0]]
  );
  // tie on 4: committed rank breaks it, so 1 (rank 1) stays above 3 (rank 3)
  assert.strictEqual(rows[1].teamId, 1);
  assert.strictEqual(rows[2].teamId, 3);
});

test('seasonIfEndedNow: a team missing from the week keeps its season points', () => {
  const liveData = {
    throughWeek: 2,
    teams: [
      { teamId: 1, name: 'A', points: 2, rank: 1 },
      { teamId: 2, name: 'B', points: 1, rank: 2 }
    ]
  };
  const week = { period: 3, mode: 'projected', line: null,
                 teams: [{ teamId: 2, score: 100, byed: false, win: 1, topHalf: 0, dual: 1, aboveLine: false }] };
  const rows = LIVE.seasonIfEndedNow(liveData, week);
  // both land on 2 total -> committed rank keeps 1 ahead of 2
  assert.deepStrictEqual(
    rows.map((r) => [r.teamId, r.weekPoints, r.total, r.rank]),
    [[1, 0, 2, 1], [2, 1, 2, 2]]
  );
});

/* ---------- parity: the important one ----------
 * Every regular-season week of 2025, recomputed from the raw ESPN fetch
 * in final-score mode, must agree with compute.py's committed output:
 * the week's score to beat and each team's H2H and top-half points.
 */
test('parity: 2025 weeks match data/standings-2025.json', () => {
  const dir = path.join(__dirname, '..', 'data');
  const raw = JSON.parse(fs.readFileSync(path.join(dir, 'raw-2025.json'), 'utf8'));
  const standings = JSON.parse(fs.readFileSync(path.join(dir, 'standings-2025.json'), 'utf8'));
  const payload = {
    status: raw.mMatchupScore.status,
    schedule: raw.mMatchupScore.schedule,
    teams: raw.mTeam.teams
  };
  assert.ok(standings.weeks.length >= 1, 'standings-2025 has weeks');
  for (const w of standings.weeks) {
    const r = LIVE.weekDualPoints(payload, w.week, 'live');
    // compute.py rounds the line to one decimal for storage; the JS model
    // keeps the exact value, so compare at that precision.
    assert.strictEqual(Math.round(r.line * 10) / 10, w.scoreToBeat,
      'week ' + w.week + ' score to beat');
    const byId = {};
    r.teams.forEach((t) => { byId[t.teamId] = t; });
    for (const pt of w.teams) {
      const jt = byId[pt.teamId];
      assert.ok(jt, 'week ' + w.week + ' missing team ' + pt.teamId);
      assert.strictEqual(jt.win, pt.h2h,
        'week ' + w.week + ' team ' + pt.teamId + ' h2h');
      assert.strictEqual(jt.topHalf, pt.topHalf,
        'week ' + w.week + ' team ' + pt.teamId + ' topHalf');
    }
  }
});

