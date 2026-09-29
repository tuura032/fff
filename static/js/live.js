/* live.js — the Live page controller (ENH-029).
 *
 * Does the DOM work and the polling; every rule lives in live-core.js so
 * the math stays testable in Node. Fetches ESPN directly from the browser
 * (the one live page on the site) and the committed season snapshot from
 * live-data.json. On a failed fetch it keeps the last good data on screen
 * and says so; with no data at all it shows a friendly empty state.
 *
 * Display-only rounding: scores and deltas are rounded to one decimal
 * everywhere (the model keeps ESPN's exact values), win probabilities are
 * whole percentages. Team names come from live-data.json (our redacted
 * names) — owner names are never rendered on this page.
 */
(function () {
  'use strict';
  if (!window.LIVE || !window.LIVE_CONFIG) return;

  var LIVE = window.LIVE;
  var cfg = window.LIVE_CONFIG;
  var ESPN_URL = LIVE.liveUrl(cfg.season);
  var DATA_URL = 'live-data.json';
  var REFRESH_MS = 60 * 1000;
  var REFRESH_COOLDOWN_MS = 5000;
  var FETCH_TIMEOUT_MS = 10000;

  var state = {
    data: null,      // last good ESPN payload
    liveData: null,  // the committed season snapshot
    liveDataError: null,
    updatedAt: null, // ms timestamp of the last good ESPN fetch
    error: null,     // message from the last failed ESPN fetch
    loading: false,
    stopped: false   // every matchup this week decided -> stop polling
  };

  var el = {};
  ['live-week', 'live-status', 'live-status-dot', 'live-status-text',
   'live-refresh', 'live-error', 'live-error-text', 'live-retry',
   'live-empty', 'live-empty-title', 'live-empty-body', 'live-content',
   'live-scoreboard', 'live-byes', 'live-stb-section', 'live-stb',
   'live-stb-proj', 'live-stb-body', 'live-dual-section', 'live-dual-body',
   'live-ended-section', 'live-ended-note', 'live-ended-body',
   'live-ended-table', 'live-playoff-note'
  ].forEach(function (id) { el[id] = document.getElementById(id); });

  /* "105.7" / "117" — one decimal for display only. "–" when missing.
     Rounding here (and nowhere else) is what keeps float noise like
     +19.700000000000003 off the page. */
  function one(n) {
    if (n === null || n === undefined || !isFinite(n)) return '\u2013';
    return String(Math.round(n * 10) / 10);
  }

  function probPct(v) {
    var n = Number(v);
    return isFinite(n) ? Math.round(n * 100) + '%' : '\u2013';
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* Display names, in priority order: the committed snapshot (redacted,
     canonical), then the ESPN payload, then a placeholder. Never an owner. */
  function names() {
    var map = {};
    if (state.liveData) {
      state.liveData.teams.forEach(function (t) { map[t.teamId] = t.name; });
    }
    if (state.data) {
      var fromEspn = LIVE.teamNames(state.data);
      Object.keys(fromEspn).forEach(function (id) {
        if (!map[id]) map[id] = fromEspn[id];
      });
    }
    return function (teamId) {
      return map[teamId] || 'Team ' + teamId;
    };
  }

  /* "▲ +2.1" / "▼ −3.4" / "◆ 0.0" (on the line: no point for either team). */
  function vsLine(score, line) {
    if (score === null || score === undefined || line === null) {
      return '<span class="text-slate-400 dark:text-slate-500">\u2013</span>';
    }
    var d = score - line;
    if (d > 0) {
      return '<span class="font-semibold text-emerald-600 dark:text-emerald-400">\u25B2 +' + one(d) + '</span>';
    }
    if (d < 0) {
      return '<span class="font-semibold text-rose-600 dark:text-rose-400">\u25BC \u2212' + one(Math.abs(d)) + '</span>';
    }
    return '<span class="text-slate-500 dark:text-slate-400" title="On the line: no top-half point">\u25C6 0.0</span>';
  }

  /* --- Scoreboard --------------------------------------------------- */

  function sideHtml(teamId, score, proj, nameOf, align, won, lost) {
    var scoreCls = 'text-2xl font-bold tabular-nums ' + (
      won ? 'text-emerald-600 dark:text-emerald-400'
        : lost ? 'text-slate-400 dark:text-slate-500'
        : 'text-slate-900 dark:text-white');
    var textCls = align === 'right' ? 'text-right' : 'text-left';
    return (
      '<div class="min-w-0 flex-1">' +
      '<p class="truncate text-sm font-semibold text-slate-800 dark:text-slate-100" title="' + esc(nameOf(teamId)) + '">' + esc(nameOf(teamId)) + '</p>' +
      '<p class="mt-0.5 ' + textCls + ' ' + scoreCls + '">' + one(score) + '</p>' +
      '<p class="' + textCls + ' text-[11px] text-slate-400 dark:text-slate-500">proj ' + one(proj) + '</p>' +
      '</div>');
  }

  function scoreboardCard(g, nameOf) {
    var decidedAway = g.winner === 'AWAY';
    var decidedHome = g.winner === 'HOME';
    var awayPct = g.away.winProbability;
    var bar = (awayPct !== null && isFinite(Number(awayPct)))
      ? '<div class="w-20 shrink-0" title="Win probability, away / home">' +
        '<div class="flex h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">' +
        '<div class="h-full bg-blue-500" style="width:' + (Number(awayPct) * 100).toFixed(0) + '%"></div>' +
        '</div>' +
        '<p class="mt-1 text-center text-[11px] tabular-nums text-slate-500 dark:text-slate-400">' +
        probPct(awayPct) + ' / ' + probPct(g.home.winProbability) + '</p>' +
        '</div>'
      : '<div class="w-20 shrink-0"></div>';

    var status;
    if (g.winner === 'TIE') status = 'Final &middot; tie';
    else if (decidedAway || decidedHome) {
      status = 'Final &middot; ' + esc(nameOf(decidedAway ? g.away.teamId : g.home.teamId)) + ' wins';
    } else if (g.away.live === 0 && g.home.live === 0) status = 'Not started';
    else status = 'In progress';

    return (
      '<article class="rounded-lg border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">' +
      '<div class="flex items-start gap-3">' +
      sideHtml(g.away.teamId, g.away.live, g.away.projected, nameOf, 'left', decidedAway, decidedHome) +
      bar +
      sideHtml(g.home.teamId, g.home.live, g.home.projected, nameOf, 'right', decidedHome, decidedAway) +
      '</div>' +
      '<p class="mt-2 text-center text-xs text-slate-400 dark:text-slate-500">' + status + '</p>' +
      '</article>');
  }

  function renderScoreboard(games, byes, nameOf) {
    el['live-scoreboard'].innerHTML = games.map(function (g) {
      return scoreboardCard(g, nameOf);
    }).join('') || '<p class="text-sm text-slate-500 dark:text-slate-400">No matchups found for this week.</p>';
    el['live-byes'].textContent = byes.length
      ? 'Bye this week: ' + byes.map(function (b) { return nameOf(b && b.teamId); }).join(', ')
      : '';
  }



  /* --- Score to beat + dual points tables --------------------------- */

  function dualChips(n) {
    var w = '<span class="inline-block min-w-[2rem] rounded bg-emerald-100 px-2 py-0.5 text-center text-xs font-bold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">W</span>';
    var top = '<span class="inline-block min-w-[2.75rem] rounded bg-blue-100 px-2 py-0.5 text-center text-xs font-bold text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">TOP</span>';
    if (n >= 2) return w + ' ' + top;
    if (n === 1) return w;
    return '<span class="text-slate-400 dark:text-slate-500">&mdash;</span>';
  }

  function scoreRows(live, proj) {
    /* One row per team with its live score, projected score and duals;
       sorted by live score (nulls last, teamId tie-break) so every table
       on the page reads in the same order. `live`/`proj` are the two
       weekDualPoints(...) results for the same week, so their teams
       arrays line up one-for-one. */
    var lt = live.teams, pt = proj.teams;
    var rows = lt.map(function (r, i) {
      return {
        teamId: r.teamId,
        liveScore: r.score, projScore: pt[i].score,
        liveDual: r.dual, projDual: pt[i].dual
      };
    });
    rows.sort(function (a, b) {
      var av = a.liveScore === null ? -1 : a.liveScore;
      var bv = b.liveScore === null ? -1 : b.liveScore;
      if (bv !== av) return bv - av;
      return a.teamId - b.teamId;
    });
    return rows;
  }

  function renderStb(live, proj, nameOf) {
    el['live-stb'].textContent = one(live.line);
    el['live-stb-proj'].textContent = one(proj.line);
    el['live-stb-body'].innerHTML = scoreRows(live, proj).map(function (r) {
      return (
        '<tr>' +
        '<td class="px-3 py-2 font-medium text-slate-800 dark:text-slate-100">' + esc(nameOf(r.teamId)) + '</td>' +
        '<td class="px-3 py-2 text-right tabular-nums">' + one(r.liveScore) + '</td>' +
        '<td class="px-3 py-2 text-right">' + vsLine(r.liveScore, live.line) + '</td>' +
        '<td class="px-3 py-2 text-right tabular-nums">' + one(r.projScore) + '</td>' +
        '<td class="px-3 py-2 text-right">' + vsLine(r.projScore, proj.line) + '</td>' +
        '</tr>');
    }).join('');
  }

  function renderDual(live, proj, nameOf) {
    el['live-dual-body'].innerHTML = scoreRows(live, proj).map(function (r) {
      return (
        '<tr>' +
        '<td class="px-3 py-2 font-medium text-slate-800 dark:text-slate-100">' + esc(nameOf(r.teamId)) + '</td>' +
        '<td class="px-3 py-2 text-right tabular-nums">' + one(r.liveScore) + '</td>' +
        '<td class="px-3 py-2 text-center">' + dualChips(r.liveDual) + '</td>' +
        '<td class="px-3 py-2 text-right tabular-nums">' + one(r.projScore) + '</td>' +
        '<td class="px-3 py-2 text-center">' + dualChips(r.projDual) + '</td>' +
        '</tr>');
    }).join('');
  }

  /* --- If the week ended now ---------------------------------------- */

  /* The committed snapshot must cover through last week (throughWeek ===
     week - 1) or the total would skip one. Week 1 of a season is the
     natural case where throughWeek is 0, so the same check works. If the
     snapshot already includes this week, adding it again would double
     count, so point at Home instead. */
  function renderEnded(weekProj) {
    var note = el['live-ended-note'];
    var week = LIVE.currentWeek(state.data);
    var showTable = false;

    if (!state.liveData) {
      note.textContent = 'The season snapshot (live-data.json) has not loaded, so there is nothing to add this week to.';
    } else if (state.liveData.season !== cfg.season) {
      note.textContent = 'The season snapshot is from ' + state.liveData.season + '. This table appears once the site has been rebuilt for ' + cfg.season + '.';
    } else if (state.liveData.throughWeek >= week) {
      note.textContent = 'Week ' + week + ' is already in the committed standings — the Home page has the updated table.';
    } else if (!LIVE.catchUp(state.liveData, week)) {
      note.textContent = 'Standings are committed through week ' + state.liveData.throughWeek + ', and it is week ' + week + '. This table appears once last week is in.';
    } else {
      var rows = LIVE.seasonIfEndedNow(state.liveData, weekProj);
      el['live-ended-body'].innerHTML = rows.map(function (r) {
        var move = r.movement > 0
          ? '<span class="font-semibold text-emerald-600 dark:text-emerald-400">\u25B2' + r.movement + '</span>'
          : r.movement < 0
            ? '<span class="font-semibold text-rose-600 dark:text-rose-400">\u25BC' + Math.abs(r.movement) + '</span>'
            : '<span class="text-slate-400 dark:text-slate-500">&mdash;</span>';
        return (
          '<tr>' +
          '<td class="px-3 py-2 text-right tabular-nums text-slate-500 dark:text-slate-400">' + r.rank + '</td>' +
          '<td class="px-3 py-2 font-medium text-slate-800 dark:text-slate-100">' + esc(r.name) + '</td>' +
          '<td class="px-3 py-2 text-right tabular-nums">' + one(r.seasonPoints) + '</td>' +
          '<td class="px-3 py-2 text-right tabular-nums">' + one(r.weekPoints) + '</td>' +
          '<td class="px-3 py-2 text-right font-semibold tabular-nums text-slate-900 dark:text-white">' + one(r.total) + '</td>' +
          '<td class="px-3 py-2 text-right">' + move + '</td>' +
          '</tr>');
      }).join('');
      showTable = true;
    }

    note.classList.toggle('hidden', showTable);
    el['live-ended-table'].classList.toggle('hidden', !showTable);
  }

  /* --- Status chip + empty state ------------------------------------- */

  function renderStatus() {
    var dot = 'h-2 w-2 rounded-full ';
    if (state.stopped) {
      el['live-status-dot'].className = dot + 'bg-emerald-500';
      el['live-status-text'].textContent = 'All final';
    } else if (state.error && state.data) {
      el['live-status-dot'].className = dot + 'bg-rose-500';
      el['live-status-text'].textContent = 'offline';
    } else if (state.updatedAt) {
      el['live-status-dot'].className = dot + 'bg-emerald-500';
      el['live-status-text'].textContent = 'Updated just now';
    } else {
      el['live-status-dot'].className = dot + 'bg-slate-400';
      el['live-status-text'].textContent = 'Connecting\u2026';
    }
  }

  function renderEmpty() {
    if (state.error) {
      el['live-empty-title'].textContent = 'Can\u2019t reach ESPN';
      el['live-empty-body'].textContent = state.error + ' \u2014 this page needs a direct connection to the ESPN API. Check your network (or an ad blocker) and use the refresh button.';
    } else {
      el['live-empty-title'].textContent = 'No live games right now';
      el['live-empty-body'].textContent = 'This page shows the current week while games are on. Check back on a game day, or take a look at the standings in the meantime.';
    }
  }

  function renderAll() {
    var week = state.data ? LIVE.currentWeek(state.data) : null;
    var hasData = week !== null && week !== undefined;

    el['live-empty'].classList.toggle('hidden', hasData);
    el['live-content'].classList.toggle('hidden', !hasData);
    el['live-error'].classList.toggle('hidden', !(hasData && state.error));
    renderStatus();
    if (!hasData) { renderEmpty(); return; }

    var entries = LIVE.weekEntries(state.data, week);
    var live = LIVE.weekDualPoints(state.data, week, 'live');
    var proj = LIVE.weekDualPoints(state.data, week, 'projected');
    var nameOf = names();

    el['live-week'].textContent = week;
    if (state.error) el['live-error-text'].textContent = state.error;
    renderScoreboard(entries.games, entries.byes, nameOf);

    var playoff = week > cfg.regularSeasonWeeks;
    el['live-stb-section'].classList.toggle('hidden', playoff);
    el['live-dual-section'].classList.toggle('hidden', playoff);
    el['live-ended-section'].classList.toggle('hidden', playoff);
    el['live-playoff-note'].classList.toggle('hidden', !playoff);
    if (!playoff) {
      renderStb(live, proj, nameOf);
      renderDual(live, proj, nameOf);
      renderEnded(proj);
    }

    if (LIVE.allFinal(state.data, week)) state.stopped = true;
  }



  /* --- Fetching + polling -------------------------------------------- */

  function fetchESPN() {
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timeout = controller ? setTimeout(function () { controller.abort(); }, FETCH_TIMEOUT_MS) : null;
    return fetch(ESPN_URL, { headers: { Accept: 'application/json' },
                             signal: controller ? controller.signal : undefined })
      .then(function (res) {
        if (!res.ok) throw new Error('ESPN responded ' + res.status);
        return res.json();
      })
      .finally(function () { if (timeout) clearTimeout(timeout); });
  }

  function refresh(manual) {
    if (state.loading) return;
    state.loading = true;
    return fetchESPN()
      .then(function (data) {
        state.data = data;
        state.updatedAt = Date.now();
        state.error = null;
        renderAll();
      })
      .catch(function (err) {
        state.error = (err && err.name === 'AbortError')
          ? 'ESPN took too long to answer'
          : (err && err.message ? err.message : 'unknown error');
        renderAll();
      })
      .then(function () { state.loading = false; });
  }

  /* One-second heartbeat: "Updated Ns ago". The other chip states
     (connecting / offline / all final) are static, so the tick leaves
     them alone. */
  function tick() {
    if (!state.updatedAt || state.stopped || (state.error && state.data)) return;
    var s = Math.floor((Date.now() - state.updatedAt) / 1000);
    el['live-status-text'].textContent = s < 3 ? 'Updated just now' : 'Updated ' + s + 's ago';
  }

  function onVisible() {
    if (document.hidden || state.stopped) return;
    var stale = !state.updatedAt || state.error || (Date.now() - state.updatedAt) > REFRESH_MS;
    if (stale) refresh(false);
  }

  function init() {
    fetch(DATA_URL)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        state.liveData = data;
        if (state.data) renderAll(); // ESPN already arrived: show the full picture
      })
      .catch(function (err) {
        state.liveDataError = (err && err.message) || 'unknown error';
        if (state.data) renderAll();
      });

    refresh(false);

    el['live-refresh'].addEventListener('click', function () {
      el['live-refresh'].disabled = true;
      refresh(true);
      setTimeout(function () {
        if (!state.loading) el['live-refresh'].disabled = false;
      }, REFRESH_COOLDOWN_MS);
    });
    el['live-retry'].addEventListener('click', function () {
      el['live-retry'].disabled = true;
      refresh(true);
      setTimeout(function () { el['live-retry'].disabled = false; }, REFRESH_COOLDOWN_MS);
    });

    setInterval(function () {
      if (document.hidden || state.stopped || state.loading) return;
      refresh(false);
    }, REFRESH_MS);
    document.addEventListener('visibilitychange', onVisible);
    setInterval(tick, 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
