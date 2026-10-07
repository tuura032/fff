/* Waiver Board — local-only. No dependencies; no frameworks.
 *
 * The per-source positional ranks come from the server; consensus, board
 * order and tiers are recomputed here when sources are toggled, mirroring
 * sidecar/model.py (consensus, board_order, tiers).
 */
"use strict";

const SOURCES = ["ffb-andy", "ffb-jason", "ffb-mike", "harris", "fp"];
const SOURCE_LABELS = {
  "ffb-andy": "FFB · Andy", "ffb-jason": "FFB · Jason", "ffb-mike": "FFB · Mike",
  "harris": "Harris", "fp": "FantasyPros",
  "ffb": "FFB",   // consolidated FFB rank (look-back data only)
};
const VIEWS = ["weekly", "ros", "dynasty"];
const VIEW_LABELS = { weekly: "Weekly", ros: "Rest of season", dynasty: "Dynasty" };
const POS_ORDER = ["QB", "RB", "WR", "TE", "K", "D/ST"];
const SLOTS = { 0: "QB", 2: "RB", 4: "WR", 5: "WR/TE", 6: "TE", 23: "FLEX",
                17: "K", 16: "D/ST", 20: "Bench", 21: "IR" };

const state = {
  board: null,
  view: "waivers",
  rankView: "weekly",
  enabled: new Set(SOURCES),
  wa: { pos: "ALL", status: "ALL", minPct: 0, q: "" },
  lb: { tab: "risers", pos: "ALL", who: "ALL", week: null, wpos: "QB" },
  rk: { pos: "ALL", q: "", avail: true },  // avail: only FA + waiver players (the Waivers tab's set), still in rank order
  sort: {},          // per-table { col, dir } — survives view switches
  statusTimer: null,
};

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
              '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, opts) {
  const resp = await fetch(path, opts);
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  return resp.json();
}

/* ---------------- status chips ---------------- */

function chipHTML(name, st) {
  const age = st.ageSec != null
    ? ` · ${st.ageSec < 90 ? `${st.ageSec}s` : Math.round(st.ageSec / 60) + "m"}`
    : "";
  const tip = st.lastError ? ` title="${esc(st.lastError)}"` : "";
  return `<span class="chip ${st.state}"${tip}>${name}${age}</span>`;
}

function renderStatus(status) {
  $("#status-bar").innerHTML = Object.entries(status)
    .map(([name, st]) => chipHTML(name, st)).join("");
}

function startStatusPolling() {
  stopStatusPolling();
  state.statusTimer = setInterval(async () => {
    try {
      const { status } = await api("/api/status");
      renderStatus(status);
      if (!Object.values(status).some((s) => s.state === "refreshing")) {
        if (state.board) { await loadBoard(); }
        stopStatusPolling();
      }
    } catch { /* server briefly busy; keep polling */ }
  }, 2500);
}

function stopStatusPolling() {
  if (state.statusTimer) { clearInterval(state.statusTimer); state.statusTimer = null; }
}

/* ---------------- consensus math (mirrors model.py) ---------------- */

function consensus(ranksBySource, enabled) {
  const per = {};
  for (const s of enabled) {
    const m = ranksBySource[s] || {};
    for (const [pid, rank] of Object.entries(m)) {
      (per[pid] = per[pid] || {})[s] = rank;
    }
  }
  const out = {};
  for (const [pid, rs] of Object.entries(per)) {
    const vals = Object.values(rs);
    out[pid] = {
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
      n: vals.length,
      spread: Math.max(...vals) - Math.min(...vals),
      ranks: rs,
    };
  }
  return out;
}

function boardOrder(cons, nEnabled) {
  const half = nEnabled / 2;
  return Object.keys(cons).sort((a, b) => {
    const da = cons[a].n < half ? 1 : 0;
    const db = cons[b].n < half ? 1 : 0;
    return da - db || cons[a].avg - cons[b].avg || Number(a) - Number(b);
  });
}

function tiers(avgs) {
  if (!avgs.length) return [];
  const gaps = avgs.slice(1).map((v, i) => v - avgs[i]).sort((a, b) => a - b);
  const mid = (gaps.length - 1) / 2;
  const median = gaps.length
    ? (mid % 1 ? (gaps[mid] + gaps[mid + 1]) / 2 : gaps[mid]) : 0;
  const threshold = Math.max(1.5, 2 * median);
  const out = [1];
  let tier = 1;
  for (const g of avgs.slice(1).map((v, i) => v - avgs[i])) {
    if (g > threshold) tier += 1;
    out.push(tier);
  }
  return out;
}

/* ---------------- shared pieces ---------------- */

function playerSub(p) {
  const bits = [];
  if (p.team) bits.push(esc(p.team));
  if (p.bye) bits.push(`bye ${p.bye}`);
  if (p.pctOwned != null) bits.push(`${p.pctOwned.toFixed(1)}% own`);
  return bits.join(" · ");
}

function showMovers(view) {
  return view === "weekly" && Object.keys(state.board.movers || {}).length > 0;
}

function moverCell(pid, view) {
  if (!showMovers(view)) return "";
  const m = state.board.movers[pid];
  if (m == null) return `<td class="num flat">·</td>`;
  const cls = m > 0 ? "up" : m < 0 ? "down" : "flat";
  const arrow = m > 0 ? "▲" : m < 0 ? "▼" : "–";
  return `<td class="num ${cls}">${arrow} ${Math.abs(m).toFixed(1)}</td>`;
}

/* ---------------- sortable tables ---------------- */

// A column: { id, label, num?, title?, get(row) -> sort value,
//             cell?(row) -> inner HTML (default: escaped get), cls?(row) }.
// Every data table goes through sortTable(), so they all sort, scroll
// inside their own box and keep a sticky header the same way.

function applySort(rows, cols, sort) {
  if (!sort) return rows;
  const col = cols.find((c) => c.id === sort.col);
  if (!col) return rows;
  const dir = sort.dir || 1;
  return rows.slice().sort((a, b) => {
    const va = col.get(a), vb = col.get(b);
    if (va == null && vb == null) return a._i - b._i;
    if (va == null) return 1;  // blanks always last, either direction
    if (vb == null) return -1;
    return (va < vb ? -1 : va > vb ? 1 : 0) * dir || (a._i - b._i);
  });
}

function thHTML(col, sort) {
  const active = sort && sort.col === col.id;
  const arrow = active ? (sort.dir === 1 ? "▲" : "▼") : "";
  const aria = active
    ? ` aria-sort="${sort.dir === 1 ? "ascending" : "descending"}"` : "";
  const title = col.title ? ` title="${esc(col.title)}"` : "";
  return `<th class="${col.num ? "num " : ""}sort" data-sort="${col.id}"${aria}${title}>` +
    `${col.label}<span class="sort-arrow">${arrow}</span></th>`;
}

function sortTable(key, cols, rows, opts = {}) {
  rows.forEach((r, i) => { r._i = i; });
  const sort = state.sort[key] || null;
  const shown = applySort(rows, cols, sort).slice(0, opts.limit || Infinity);
  const body = shown.map((r) => `<tr>${cols.map((c) => {
    const cls = [c.num ? "num" : "", c.cls ? c.cls(r) || "" : ""].join(" ").trim();
    const inner = c.cell ? c.cell(r) : esc(c.get(r) ?? "");
    return `<td${cls ? ` class="${cls}"` : ""}>${inner}</td>`;
  }).join("")}</tr>`).join("");
  const more = opts.limit && rows.length > opts.limit
    ? `<p class="note">Showing ${opts.limit} of ${rows.length}${opts.moreNote || ""}.</p>` : "";
  return `<div class="tbl-wrap${opts.compact ? " compact" : ""}" data-key="${key}">
    <table><thead><tr>${cols.map((c) => thHTML(c, sort)).join("")}</tr></thead>
    <tbody>${body || `<tr><td colspan="${cols.length}" class="muted">Nothing to show.</td></tr>`}</tbody></table>
    </div>${more}`;
}

// Click a header: sort by it (numbers start high→low... except ranks,
// which start best-first), click again to flip, a third time to reset.
function toggleSort(key, colId, cols) {
  const cur = state.sort[key];
  const col = cols.find((c) => c.id === colId) || {};
  const first = col.firstDir || (col.num ? -1 : 1);
  if (!cur || cur.col !== colId) state.sort[key] = { col: colId, dir: first };
  else if (cur.dir === first) cur.dir = -first;
  else delete state.sort[key];
  const wrap = $(`.tbl-wrap[data-key="${key}"]`);
  const top = wrap ? wrap.scrollTop : 0;
  render();
  const w2 = $(`.tbl-wrap[data-key="${key}"]`);
  if (w2) w2.scrollTop = top;
}

function bindSort(el, key, cols) {
  $$(`.tbl-wrap[data-key="${key}"] th[data-sort]`, el).forEach((th) => {
    th.onclick = () => toggleSort(key, th.dataset.sort, cols);
  });
}

function posChips(id, current, positions) {
  return `<div class="tabs" id="${id}">${positions.map((p) =>
    `<button data-pos="${p}" class="${p === current ? "active" : ""}">${p === "ALL" ? "All" : p}</button>`).join("")}</div>`;
}

const OPP_ABBR = { JAC: "JAX", WAS: "WSH", LA: "LAR" };

// Opponents arrive as "@ LV" / "NE" (Harris: bare = home) and
// "at HOU" / "vs. JAC" (FantasyPros). Show one format: "@LV", "vs NE".
function fmtOpp(o) {
  const s = String(o || "").trim();
  if (!s) return "";
  const m = s.match(/^(@|at\b|vs\.?)?\s*([A-Za-z]{2,3})$/i);
  if (!m) return s;
  const team = OPP_ABBR[m[2].toUpperCase()] || m[2].toUpperCase();
  const away = m[1] && (m[1] === "@" || m[1].toLowerCase() === "at");
  return away ? `@${team}` : `vs ${team}`;
}

const injuryCell = (inj) => (inj && inj !== "ACTIVE"
  ? `<span class="badge ${esc(inj)}">${esc(inj.replace(/_/g, " "))}</span>` : "");

/* ---------------- waivers ---------------- */

const WAIVERS_COLS = [
  { id: "name", label: "Player", get: (r) => r.name.toLowerCase(),
    cell: (r) => `<strong>${esc(r.name)}</strong>${injuryCell(r.injury)}` },
  { id: "pos", label: "Pos", get: (r) => POS_ORDER.indexOf(r.pos), cell: (r) => esc(r.pos) },
  { id: "team", label: "Team", get: (r) => r.team, cls: () => "muted" },
  { id: "bye", label: "Bye", num: true, firstDir: 1, get: (r) => r.bye },
  { id: "status", label: "Status", get: (r) => r.status,
    cell: (r) => `<span class="badge ${r.status}">${r.status}</span>` },
  { id: "owned", label: "Owned %", num: true, get: (r) => r.pctOwned,
    cell: (r) => (r.pctOwned != null ? r.pctOwned.toFixed(1) : "–") },
];

function renderWaivers() {
  const b = state.board;
  const el = $("#view-waivers");
  const f = state.wa;
  const list = Object.entries(b.players)
    .map(([pid, p]) => ({ pid, ...p }))
    .filter((p) => p.status === "FA" || p.status === "WAIVERS")
    .filter((p) => f.pos === "ALL" || p.pos === f.pos)
    .filter((p) => f.status === "ALL" || p.status === f.status)
    .filter((p) => (p.pctOwned || 0) >= f.minPct)
    .filter((p) => !f.q || p.name.toLowerCase().includes(f.q.toLowerCase()))
    .sort((a, b2) => (b2.pctOwned || 0) - (a.pctOwned || 0)
      || POS_ORDER.indexOf(a.pos) - POS_ORDER.indexOf(b2.pos)
      || a.name.localeCompare(b2.name));
  el.innerHTML = `
    <div class="controls">
      ${posChips("wa-pos", f.pos, ["ALL", ...POS_ORDER])}
      <select id="wa-status">${[["ALL", "FA + waivers"], ["WAIVERS", "Waivers"], ["FA", "Free agents"]]
        .map(([v, l]) => `<option value="${v}" ${f.status === v ? "selected" : ""}>${l}</option>`).join("")}</select>
      <label class="tog">min owned %
        <input type="number" id="wa-pct" min="0" max="100" step="5"
               value="${f.minPct}" style="width:64px"></label>
      <input type="text" id="wa-q" placeholder="search name…" value="${esc(f.q)}">
      <span class="muted">${list.length} players</span>
    </div>
    ${sortTable("waivers", WAIVERS_COLS, list, { limit: 400, moreNote: " — narrow the filters" })}`;
  bindSort(el, "waivers", WAIVERS_COLS);
  $$("#wa-pos button", el).forEach((btn) => {
    btn.onclick = () => { state.wa.pos = btn.dataset.pos; renderWaivers(); };
  });
  $("#wa-status").onchange = (e) => { state.wa.status = e.target.value; renderWaivers(); };
  $("#wa-pct").onchange = (e) => { state.wa.minPct = Number(e.target.value) || 0; renderWaivers(); };
  $("#wa-q").oninput = (e) => {
    state.wa.q = e.target.value; renderWaivers();
    const q = $("#wa-q"); q.focus();
    q.setSelectionRange(q.value.length, q.value.length);
  };
}

/* ---------------- rankings / K&D ---------------- */

function sourcesForView(view) {
  const ranks = state.board.ranks[view] || {};
  return SOURCES.filter((s) => ranks[s] && Object.keys(ranks[s]).length);
}

// Board rows for one view + position set. Ranks are positional, so the
// rank shown and the tiers are computed within each position — a QB1 and
// an RB1 are both "1", never #1 and #2 of one list.
function rankRows(view, enabled, positions) {
  const b = state.board;
  const cons = consensus(b.ranks[view] || {}, enabled);
  const order = boardOrder(cons, Math.max(1, enabled.length))
    .filter((pid) => b.players[pid] && positions.includes(b.players[pid].pos));
  const byPos = {};
  order.forEach((pid) => (byPos[b.players[pid].pos] = byPos[b.players[pid].pos] || []).push(pid));
  const posRank = {}, tierOf = {};
  Object.values(byPos).forEach((ids) => {
    ids.forEach((pid, i) => { posRank[pid] = i + 1; });
    tiers(ids.map((pid) => cons[pid].avg)).forEach((t, i) => { tierOf[ids[i]] = t; });
  });
  return order.map((pid) => {
    const p = b.players[pid];
    const c = cons[pid];
    return {
      pid, name: p.name, pos: p.pos, team: p.team, injury: p.injury,
      status: p.status, ownerTeamId: p.ownerTeamId,
      opp: view === "weekly" && b.weekInfo[pid] ? fmtOpp(b.weekInfo[pid].opponent) : "",
      posRank: posRank[pid], tier: tierOf[pid], avg: c.avg, n: c.n,
      spread: c.spread, src: c.ranks, mover: (b.movers || {})[pid],
    };
  });
}

function rankCols(view, enabled, multiPos) {
  const b = state.board;
  const cols = [
    { id: "rank", label: "Rk", num: true, firstDir: 1, get: (r) => r._i,
      cell: (r) => (multiPos ? `${esc(r.pos)}${r.posRank}` : r.posRank), cls: () => "tier-cell" },
    { id: "name", label: "Player", get: (r) => r.name.toLowerCase(),
      cell: (r) => `<strong>${esc(r.name)}</strong>${injuryCell(r.injury)}` },
  ];
  if (multiPos) cols.push({ id: "pos", label: "Pos", get: (r) => POS_ORDER.indexOf(r.pos), cell: (r) => esc(r.pos) });
  cols.push({ id: "team", label: "Team", get: (r) => r.team, cls: () => "muted" });
  if (view === "weekly") cols.push({ id: "opp", label: "Opp", get: (r) => r.opp || null, cls: () => "muted" });
  cols.push({ id: "roster", label: "Roster", get: (r) => (r.status === "OWNED" ? `~${r.ownerTeamId}` : r.status),
    cell: (r) => whoLabel(r) });
  enabled.forEach((s) => cols.push({ id: `src-${s}`, label: SOURCE_LABELS[s], num: true, firstDir: 1,
    get: (r) => r.src[s], cell: (r) => (r.src[s] != null ? r.src[s] : "–"),
    cls: (r) => (r.src[s] == null ? "muted" : "") }));
  cols.push(
    { id: "avg", label: "Avg", num: true, firstDir: 1, get: (r) => r.avg,
      cell: (r) => `<strong>${r.avg.toFixed(1)}</strong>` },
    { id: "spread", label: "Sprd", num: true, title: "max − min across sources", get: (r) => r.spread, cls: () => "muted" },
    { id: "tier", label: "Tier", num: true, firstDir: 1, get: (r) => r.tier, cell: (r) => `T${r.tier}`,
      cls: (r) => `tier t${Math.min(r.tier, 6)}` },
  );
  if (showMovers(view)) {
    cols.push({ id: "mover", label: "Δ", num: true, title: `avg rank change since ${b.meta.moversSince}`,
      get: (r) => r.mover,
      cell: (r) => (r.mover == null ? "·" : `${r.mover > 0 ? "▲" : r.mover < 0 ? "▼" : "–"} ${Math.abs(r.mover).toFixed(1)}`),
      cls: (r) => (r.mover > 0 ? "up" : r.mover < 0 ? "down" : "flat") });
  }
  return cols;
}

function sourceToggles(avail) {
  return avail.map((s) => `<label class="tog"><input type="checkbox" data-s="${s}"
    ${state.enabled.has(s) ? "checked" : ""}>${SOURCE_LABELS[s]}</label>`).join("");
}

function bindSourceToggles(el, rerender) {
  $$("input[data-s]", el).forEach((cb) => {
    cb.onchange = () => {
      if (cb.checked) state.enabled.add(cb.dataset.s);
      else state.enabled.delete(cb.dataset.s);
      rerender();
    };
  });
}

function renderRankings() {
  const el = $("#view-rankings");
  const b = state.board;
  const view = state.rankView;
  const f = state.rk;
  const avail = sourcesForView(view);
  const enabled = SOURCES.filter((s) => state.enabled.has(s) && avail.includes(s));
  const positions = f.pos === "ALL" ? POS_ORDER : [f.pos];
  let rows = rankRows(view, enabled, positions);
  // Ranks (Rk, tiers) stay computed over everyone, so "RB34" still means the 34th RB overall.
  if (f.avail) rows = rows.filter((r) => r.status === "FA" || r.status === "WAIVERS");
  if (f.q) rows = rows.filter((r) => r.name.toLowerCase().includes(f.q.toLowerCase()));
  const cols = rankCols(view, enabled, f.pos === "ALL");
  const key = `rank-${view}`;
  el.innerHTML = `
    <div class="controls">
      <div class="tabs">${VIEWS.map((v) => `<button data-v="${v}"
        class="${v === view ? "active" : ""}">${VIEW_LABELS[v]}</button>`).join("")}</div>
      ${posChips("rk-pos", f.pos, ["ALL", ...POS_ORDER])}
      <input type="text" id="rk-q" placeholder="search name…" value="${esc(f.q)}">
      <label class="tog" title="Hide rostered players: show only free agents and waivers, in rank order">
        <input type="checkbox" id="rk-avail" ${f.avail ? "checked" : ""}>Available only (FA + waivers)</label>
      <span class="muted">${rows.length} players</span>
    </div>
    <div class="controls">${sourceToggles(avail)}</div>
    ${sortTable(key, cols, rows)}
    <details class="panel"><summary>Unmatched
      (${Object.values(b.unmatched).reduce((n, r) => n + r.length, 0)})</summary>
      <table><thead><tr><th>Source</th><th>Player</th><th>Pos</th><th>Team</th></tr></thead>
      <tbody>${Object.entries(b.unmatched).flatMap(([src, un]) =>
        un.map((r) => `<tr><td class="muted">${esc(src)}</td>
          <td>${esc(r.name)}</td><td>${esc(r.pos)}</td>
          <td class="muted">${esc(r.team) || ""}</td></tr>`)).join("")}
      </tbody></table>
    </details>`;
  bindSort(el, key, cols);
  $$("button[data-v]", el).forEach((btn) => {
    btn.onclick = () => { state.rankView = btn.dataset.v; renderRankings(); };
  });
  $$("#rk-pos button", el).forEach((btn) => {
    btn.onclick = () => { state.rk.pos = btn.dataset.pos; renderRankings(); };
  });
  $("#rk-avail").onchange = (e) => { state.rk.avail = e.target.checked; renderRankings(); };
  $("#rk-q").oninput = (e) => {
    state.rk.q = e.target.value; renderRankings();
    const q = $("#rk-q"); q.focus();
    q.setSelectionRange(q.value.length, q.value.length);
  };
  bindSourceToggles(el, renderRankings);
}

// K and D/ST: always this week's ranks, one table per position (SPEC §7).
function renderKD() {
  const el = $("#view-kd");
  const avail = sourcesForView("weekly");
  const enabled = SOURCES.filter((s) => state.enabled.has(s) && avail.includes(s));
  const cols = rankCols("weekly", enabled, false);
  const block = (pos, label) => {
    const rows = rankRows("weekly", enabled, [pos]);
    const best = rows.find((r) => r.status === "FA" || r.status === "WAIVERS");
    const mine = rows.find((r) => r.ownerTeamId === state.board.meta.myTeamId);
    const line = best
      ? `Best available: <strong>${esc(best.name)}</strong> (${pos}${best.posRank}, avg ${best.avg.toFixed(1)})` +
        (mine ? ` vs yours: <strong>${esc(mine.name)}</strong> (${pos}${mine.posRank}, avg ${mine.avg.toFixed(1)})` : "")
      : "No ranked free agent.";
    return `<h2 class="lb-h">${label}</h2><p class="note">${line}</p>
      ${sortTable(`kd-${pos}`, cols, rows, { compact: true })}`;
  };
  el.innerHTML = `
    <div class="controls">${sourceToggles(avail)}</div>
    <p class="note">This week's ranks. FFB kicker/D rows are per-analyst page ranks
      (those pages carry no projections).</p>
    ${block("K", "Kickers")}${block("D/ST", "Defenses")}`;
  ["K", "D/ST"].forEach((pos) => bindSort(el, `kd-${pos}`, cols));
  bindSourceToggles(el, renderKD);
}

/* ---------------- my team ---------------- */

function renderTeam() {
  const b = state.board;
  const el = $("#view-team");
  const mine = Object.entries(b.players)
    .filter(([pid, p]) => p.ownerTeamId === b.meta.myTeamId)
    .map(([pid, p]) => ({ pid, ...p }));
  const slotIds = [0, 2, 4, 5, 23, 17, 16];
  const starters = slotIds.map((sid) => [sid,
    mine.filter((p) => p.lineupSlotId === sid)
        .sort((a, b2) => POS_ORDER.indexOf(a.pos) - POS_ORDER.indexOf(b2.pos))]);
  const bench = mine.filter((p) => p.lineupSlotId === 20);
  const ir = mine.filter((p) => p.lineupSlotId === 21);
  const others = mine.filter((p) => ![...slotIds, 20, 21]
    .includes(p.lineupSlotId));

  // Consensus avg positional rank per view, over the enabled sources.
  const cons = {};
  VIEWS.forEach((v) => {
    const en = sourcesForView(v).filter((s2) => state.enabled.has(s2));
    cons[v] = consensus(b.ranks[v] || {}, en);
  });
  const rk = (v, p) => (cons[v][p.pid]
    ? `${esc(p.pos)}${cons[v][p.pid].avg.toFixed(1)}` : `<span class="muted">–</span>`);
  const row = (p, label) => `<tr>
      <td class="slot-label">${esc(label)}</td>
      <td><strong>${esc(p.name)}</strong>${injuryCell(p.injury)}</td>
      <td>${esc(p.pos)}</td>
      <td class="muted">${esc(p.team) || ""}</td>
      <td class="muted">${esc(fmtOpp(b.weekInfo[p.pid] && b.weekInfo[p.pid].opponent))}</td>
      <td class="num muted">${p.bye || ""}</td>
      ${VIEWS.map((v) => `<td class="num">${rk(v, p)}</td>`).join("")}
    </tr>`;

  const ups = b.recommendations.upgrades.slice(0, 5);
  const drops = b.recommendations.drops.slice(0, 5);
  const byes = Object.entries(b.recommendations.byes);

  el.innerHTML = `
    <div class="controls">
      <span class="muted">Roster, week ${b.meta.currentWeek || "?"}</span>
    </div>
    <div class="tbl-wrap"><table><thead><tr><th>Slot</th><th>Player</th><th>Pos</th>
      <th>Team</th><th>Opp</th><th class="num">Bye</th>
      ${VIEWS.map((v) => `<th class="num" title="consensus avg positional rank">${VIEW_LABELS[v]}</th>`).join("")}
    </tr></thead><tbody>
      ${starters.map(([sid, ps]) => {
        const want = Number((b.meta.lineupSlotCounts || {})[sid] || 0);
        const empty = Array.from({ length: Math.max(0, want - ps.length) }, () =>
          `<tr><td class="slot-label">${SLOTS[sid] || sid}</td>
            <td colspan="${5 + VIEWS.length}" class="down"><strong>Empty slot</strong></td></tr>`);
        return ps.map((p) => row(p, SLOTS[sid] || sid)).join("") + empty.join("");
      }).join("")}
      ${bench.map((p) => row(p, "Bench")).join("")}
      ${ir.map((p) => row(p, "IR")).join("")}
      ${others.map((p) => row(p, p.lineupSlotId)).join("")}
    </tbody></table></div>

    <div class="rec-card"><h3>Upgrades to consider</h3>
      ${ups.length ? ups.map((u) => `<div class="rec-line">
        <span>Add <strong>${esc(u.add.name)}</strong>
        <span class="muted">(${esc(u.add.pos)} ${esc(u.add.team) || ""})</span></span>
        <span>Drop <strong>${esc(u.drop.name)}</strong></span>
        <span class="gain">+${u.gain}</span></div>`).join("")
        : `<p class="muted">None this week (margin ${b.meta.upgradeMargin}).</p>`}
    </div>

    <div class="rec-card"><h3>Bench players vs the wire</h3>
      ${drops.length ? drops.map((d) => `<div class="rec-line">
        <span><strong>${esc(d.player.name)}</strong>
        <span class="muted">avg ${d.avg.toFixed(1)}</span></span>
        ${d.bestFreeAgent
          ? `<span>Wire: <strong>${esc(d.bestFreeAgent.name)}</strong></span>
             <span class="${d.deficit > 0 ? "down" : "flat"}">
               ${d.deficit > 0 ? `+${d.deficit} better out there` : "you're fine"}</span>`
          : `<span class="muted">no ranked free agent at ${esc(d.player.pos)}</span>`}
      </div>`).join("") : `<p class="muted">No ranked bench players.</p>`}
    </div>

    <div class="rec-card"><h3>Bye weeks ahead</h3>
      ${byes.length ? byes.map(([w, ps]) => `<div class="rec-line">
        <span>Week ${w}:</span>
        ${ps.map((p) => `<span>${esc(p.name)} <span class="muted">${esc(p.pos)}</span></span>`).join(", ")}
      </div>`).join("") : `<p class="muted">No starter on bye in the next 3 weeks.</p>`}
    </div>`;
}

/* ---------------- look back ---------------- */

const LB_TABS = {
  risers: "Risers", fallers: "Fallers", new: "New since draft", off: "Off the board",
};

function srcLabel(s) { return SOURCE_LABELS[s] || s; }

function whoLabel(p) {
  if (p.status !== "OWNED") return `<span class="badge ${esc(p.status)}">${esc(p.status)}</span>`;
  if (p.ownerTeamId === state.board.meta.myTeamId) return `<strong>mine</strong>`;
  const t = (state.board.teams || []).find((t2) => t2.id === p.ownerTeamId);
  return `<span class="muted">${esc(t ? t.abbrev || t.name : p.ownerTeamId)}</span>`;
}

function whoMatches(p, who) {
  if (who === "ALL") return true;
  if (who === "MINE") return p.ownerTeamId === state.board.meta.myTeamId;
  if (who === "AVAIL") return p.status === "FA" || p.status === "WAIVERS";
  return p.status === "OWNED" && p.ownerTeamId !== state.board.meta.myTeamId;
}

const SD_COLS = [
  { id: "name", label: "Player", get: (r) => r.name.toLowerCase(),
    cell: (r) => `<strong>${esc(r.name)}</strong>${injuryCell(r.injury)}` },
  { id: "pos", label: "Pos", get: (r) => POS_ORDER.indexOf(r.pos), cell: (r) => esc(r.pos) },
  { id: "team", label: "Team", get: (r) => r.team, cls: () => "muted" },
  { id: "roster", label: "Roster", get: (r) => (r.status === "OWNED" ? `~${r.ownerTeamId}` : r.status),
    cell: (r) => whoLabel(r) },
  { id: "pre", label: "Pre-draft", num: true, firstDir: 1, get: (r) => r.pre,
    cell: (r) => (r.pre != null ? `${esc(r.pos)}${r.pre}` : "–") },
  { id: "now", label: "Now", num: true, firstDir: 1, get: (r) => r.now,
    cell: (r) => (r.now != null ? `${esc(r.pos)}${r.now}` : "–") },
  { id: "change", label: "Change", num: true, get: (r) => r.change,
    cell: (r) => (r.change == null ? "" : `${r.change > 0 ? "▲" : "▼"} ${Math.abs(r.change)}`),
    cls: (r) => (r.change > 0 ? "up" : r.change < 0 ? "down" : "flat") },
];

function renderSinceDraft(lb) {
  const b = state.board;
  const f = state.lb;
  let list = Object.entries(lb.sinceDraft)
    .map(([pid, v]) => ({ pid, ...v, p: b.players[pid] }))
    .filter((r) => r.p && (f.pos === "ALL" || r.p.pos === f.pos) && whoMatches(r.p, f.who));
  if (f.tab === "risers") list = list.filter((r) => r.change > 0).sort((a, c) => c.change - a.change);
  else if (f.tab === "fallers") list = list.filter((r) => r.change < 0).sort((a, c) => a.change - c.change);
  else if (f.tab === "new") list = list.filter((r) => r.pre == null).sort((a, c) => a.now - c.now);
  else list = list.filter((r) => r.now == null).sort((a, c) => a.pre - c.pre);
  const rosSrc = sourcesForView("ros").map(srcLabel).join(" + ") || "none";
  return `
    <h2 class="lb-h">Since the draft</h2>
    <div class="controls">
      <div class="tabs">${Object.entries(LB_TABS).map(([k, v]) =>
        `<button data-lbt="${k}" class="${k === f.tab ? "active" : ""}">${v}</button>`).join("")}</div>
      <select id="lb-pos">${["ALL", ...POS_ORDER].map((p) =>
        `<option value="${p}" ${f.pos === p ? "selected" : ""}>${p}</option>`).join("")}</select>
      <select id="lb-who">${[["ALL", "Everyone"], ["MINE", "My team"],
        ["AVAIL", "Available"], ["OTHERS", "Other teams"]].map(([v, l]) =>
        `<option value="${v}" ${f.who === v ? "selected" : ""}>${l}</option>`).join("")}</select>
      <span class="muted">${list.length} players</span>
    </div>
    <p class="note">Avg positional rank. Pre-draft: ${lb.preSources.map(srcLabel).join(" + ")}
      (PPR, early Sept). Now: rest of season, ${esc(rosSrc)}.</p>
    ${sortTable(`sd-${f.tab}`, SD_COLS, list.map((r) => ({ ...r.p, pid: r.pid, pre: r.pre, now: r.now, change: r.change })), { limit: 60 })}`;
}

function renderWeekAccuracy(lb) {
  const b = state.board;
  const weeks = Object.keys(lb.weeks).sort((a, c) => a - c);
  if (!weeks.length) return `<h2 class="lb-h">Weekly accuracy</h2>
    <p class="note">No past-week ranks loaded (rankings/week-&lt;n&gt;.json).</p>`;
  const f = state.lb;
  if (!weeks.includes(f.week)) f.week = weeks[weeks.length - 1];
  const wk = lb.weeks[f.week];
  const srcs = [...new Set(wk.summary.map((r) => r.source))].sort();
  const positions = POS_ORDER.filter((p) => wk.summary.some((r) => r.pos === p));
  if (!positions.includes(f.wpos)) f.wpos = positions[0];
  const best = {};
  positions.forEach((pos) => {
    best[pos] = Math.max(...wk.summary.filter((r) => r.pos === pos).map((r) => r.hits));
  });
  const players = wk.players.filter((p) => p.pos === f.wpos);
  const missCell = (rank, finish) => {
    if (rank == null) return `<span class="muted">–</span>`;
    const miss = rank - finish;   // > 0: finished better than ranked
    const cls = Math.abs(miss) <= 3 ? "flat" : miss > 0 ? "up" : "down";
    return `${rank} <span class="${cls}" style="font-size:11px">${
      miss === 0 ? "✓" : (miss > 0 ? "+" : "") + miss}</span>`;
  };
  const wkCols = [
    { id: "finish", label: "Finish", num: true, firstDir: 1, get: (r) => r.finish, cls: () => "tier-cell" },
    { id: "name", label: "Player", get: (r) => r.name.toLowerCase(),
      cell: (r) => `<strong>${esc(r.name)}</strong> <span class="muted">${esc(r.team) || ""}</span>` },
    { id: "roster", label: "Roster", get: (r) => (r.status === "OWNED" ? `~${r.ownerTeamId}` : r.status),
      cell: (r) => whoLabel(r) },
    { id: "pts", label: "Pts", num: true, get: (r) => r.pts, cell: (r) => r.pts.toFixed(1) },
    ...srcs.map((s2) => ({ id: `src-${s2}`, label: srcLabel(s2), num: true, firstDir: 1,
      get: (r) => r.ranks[s2], cell: (r) => missCell(r.ranks[s2], r.finish) })),
  ];
  f.wkCols = wkCols;
  return `
    <h2 class="lb-h">Week ${esc(f.week)}: who ranked it best</h2>
    ${weeks.length > 1 ? `<div class="controls"><select id="lb-week">${weeks.map((w) =>
      `<option value="${w}" ${w === f.week ? "selected" : ""}>Week ${w}</option>`).join("")}</select></div>` : ""}
    <p class="note">Each source's week ${esc(f.week)} positional ranks vs actual FFF points.
      <strong>Hits</strong>: of its top k, how many finished top k (k = starters league-wide).
      <strong>Corr</strong>: rank correlation with the actual finish (1 = perfect, 0 = coin flip).
      <strong>Avg miss</strong>: mean |rank − finish| over everyone it ranked.</p>
    <div class="tbl-wrap"><table class="lb-sum"><thead><tr><th>Pos</th>
      ${srcs.map((s) => `<th class="num">${srcLabel(s)} hits</th><th class="num">Corr</th><th class="num">Avg miss</th>`).join("")}
    </tr></thead><tbody>
      ${positions.map((pos) => `<tr><td><strong>${pos}</strong></td>${srcs.map((s) => {
        const r = wk.summary.find((x) => x.pos === pos && x.source === s);
        if (!r) return `<td class="num muted">–</td><td></td><td></td>`;
        const top = srcs.length > 1 && r.hits === best[pos];
        return `<td class="num ${top ? "up" : ""}">${r.hits}/${r.k}</td>
          <td class="num">${r.rho != null ? r.rho.toFixed(2) : "–"}</td>
          <td class="num muted">${r.mae.toFixed(1)} <span style="font-size:11px">(n ${r.n})</span></td>`;
      }).join("")}</tr>`).join("")}
    </tbody></table></div>

    <div class="controls" style="margin-top:14px">
      <div class="tabs">${positions.map((p) =>
        `<button data-lbp="${p}" class="${p === f.wpos ? "active" : ""}">${p}</button>`).join("")}</div>
      <span class="muted">sorted by actual finish · +N = beat its rank by N</span>
    </div>
    ${sortTable(`wk-${f.week}-${f.wpos}`, wkCols, players.map((r) => ({ ...(b.players[r.espnId] || { name: `#${r.espnId}`, status: "FA" }), ...r })))}`;
}

function renderLookback() {
  const lb = state.board.lookback || { sinceDraft: {}, preSources: [], weeks: {} };
  const el = $("#view-lookback");
  if (!Object.keys(lb.sinceDraft).length && !Object.keys(lb.weeks).length) {
    el.innerHTML = `<p class="note">No look-back data yet. The <code>history</code> source
      reads config <code>history.dir</code>; check its status chip.</p>`;
    return;
  }
  el.innerHTML = renderSinceDraft(lb) + renderWeekAccuracy(lb);
  bindSort(el, `sd-${state.lb.tab}`, SD_COLS);
  const wsort = $(".tbl-wrap[data-key^='wk-']", el);
  if (wsort) bindSort(el, wsort.dataset.key, state.lb.wkCols);
  $$("button[data-lbt]", el).forEach((btn) => {
    btn.onclick = () => { state.lb.tab = btn.dataset.lbt; renderLookback(); };
  });
  $$("button[data-lbp]", el).forEach((btn) => {
    btn.onclick = () => { state.lb.wpos = btn.dataset.lbp; renderLookback(); };
  });
  $("#lb-pos").onchange = (e) => { state.lb.pos = e.target.value; renderLookback(); };
  $("#lb-who").onchange = (e) => { state.lb.who = e.target.value; renderLookback(); };
  const wsel = $("#lb-week");
  if (wsel) wsel.onchange = (e) => { state.lb.week = e.target.value; renderLookback(); };
}

/* ---------------- dispatch / refresh / init ---------------- */

function render() {
  if (!state.board) return;
  if (state.view === "waivers") renderWaivers();
  else if (state.view === "rankings") renderRankings({});
  else if (state.view === "kd") renderKD();
  else if (state.view === "lookback") renderLookback();
  else renderTeam();
}

function toast(msg, ms = 2500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), ms);
}

async function loadBoard() {
  state.board = await api("/api/board");
  $("#season").textContent = `${state.board.meta.season || ""} · week ${state.board.meta.currentWeek || "?"}`;
  renderStatus(state.board.status);
  render();
}

async function refreshAll() {
  const btn = $("#refresh");
  btn.disabled = true;
  toast("Refreshing sources…", 60000);
  try {
    await api("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    startStatusPolling();
  } catch (e) {
    toast(`Refresh failed: ${e.message}`, 6000);
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $$("#views button").forEach((btn) => {
    btn.onclick = () => {
      state.view = btn.dataset.view;
      $$("#views button").forEach((b2) =>
        b2.classList.toggle("active", b2 === btn));
      $$(".view").forEach((v) => v.classList.add("hidden"));
      $(`#view-${state.view}`).classList.remove("hidden");
      render();
    };
  });
  $("#refresh").onclick = refreshAll;
  loadBoard().catch((e) => toast(`Load failed: ${e.message}`, 8000));
});

