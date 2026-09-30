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

/* ---------------- waivers ---------------- */

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
      <select id="wa-pos">${["ALL", ...POS_ORDER].map((p) =>
        `<option value="${p}" ${f.pos === p ? "selected" : ""}>${p}</option>`).join("")}</select>
      <select id="wa-status">${["ALL", "WAIVERS", "FA"].map((s) =>
        `<option value="${s}" ${f.status === s ? "selected" : ""}>${s}</option>`).join("")}</select>
      <label class="tog">min owned
        <input type="number" id="wa-pct" min="0" max="100" step="5"
               value="${f.minPct}" style="width:64px"></label>
      <input type="text" id="wa-q" placeholder="search name…" value="${esc(f.q)}">
      <span class="muted">${list.length} players</span>
    </div>
    <table><thead><tr>
      <th>Player</th><th>Pos</th><th>Team</th><th>Status</th>
      <th class="num">Owned</th><th>Injury</th>
    </tr></thead><tbody>
      ${list.slice(0, 400).map((p) => `<tr>
        <td>${esc(p.name)}<div class="muted" style="font-size:11px">${playerSub(p)}</div></td>
        <td>${esc(p.pos)}</td><td>${esc(p.team) || ""}</td>
        <td><span class="badge ${p.status}">${p.status}</span></td>
        <td class="num">${p.pctOwned != null ? p.pctOwned.toFixed(1) : "–"}</td>
        <td class="muted">${esc(p.injury) || ""}</td>
      </tr>`).join("")}
    </tbody></table>
    ${list.length > 400 ? `<p class="note">Showing 400 of ${list.length} — narrow the filters.</p>` : ""}`;
  $("#wa-pos").onchange = (e) => { state.wa.pos = e.target.value; renderWaivers(); };
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

function renderRankings(opts = {}) {
  const el = $(opts.el || "#view-rankings");
  const b = state.board;
  const view = state.rankView;
  const avail = sourcesForView(view);
  const enabled = SOURCES.filter((s) => state.enabled.has(s) && avail.includes(s));
  const cons = consensus(b.ranks[view] || {}, enabled);
  const order = boardOrder(cons, Math.max(1, enabled.length))
    .filter((pid) => !opts.positions
      || opts.positions.includes(b.players[pid] && b.players[pid].pos));
  const tierMap = {};
  tiers(order.map((pid) => cons[pid].avg)).forEach((t, i) => { tierMap[order[i]] = t; });

  const rows = order.map((pid, i) => {
    const p = b.players[pid];
    const c = cons[pid];
    const opp = (view === "weekly" && b.weekInfo[pid]) || null;
    const rankCells = enabled.map((s) =>
      `<td class="num">${c.ranks[s] != null ? c.ranks[s] : "–"}</td>`).join("");
    return `<tr>
      <td class="num tier-cell">${i + 1}</td>
      <td><strong>${esc(p ? p.name : pid)}</strong></td>
      <td>${esc(p ? p.pos : "")}</td>
      <td class="muted">${esc(p && p.team) || ""}</td>
      ${view === "weekly" ? `<td class="muted">${esc(opp ? opp.opponent : "")}</td>` : ""}
      ${rankCells}
      <td class="num"><strong>${c.avg.toFixed(1)}</strong></td>
      <td class="num muted">${c.n}</td>
      <td class="num muted">${c.spread}</td>
      <td class="num muted">T${tierMap[pid]}</td>
      ${moverCell(pid, view)}
    </tr>`;
  }).join("");

  el.innerHTML = `
    <div class="controls">
      <div class="tabs">${VIEWS.map((v) => `<button data-v="${v}"
        class="${v === view ? "active" : ""}">${VIEW_LABELS[v]}</button>`).join("")}</div>
      ${avail.map((s) => `<label class="tog"><input type="checkbox" data-s="${s}"
        ${state.enabled.has(s) ? "checked" : ""}>${SOURCE_LABELS[s]}</label>`).join("")}
    </div>
    ${opts.note ? `<p class="note">${opts.note}</p>` : ""}
    <table><thead><tr>
      <th class="num">#</th><th>Player</th><th>Pos</th><th>Team</th>
      ${view === "weekly" ? "<th>Opp</th>" : ""}
      ${enabled.map((s) => `<th class="num">${SOURCE_LABELS[s]}</th>`).join("")}
      <th class="num">Avg</th><th class="num">n</th><th class="num">Sprd</th>
      <th class="num">Tier</th>${showMovers(view)
        ? `<th class="num" title="avg rank change since ${esc(b.meta.moversSince)}">Δ</th>` : ""}
    </tr></thead><tbody>${rows}</tbody></table>
    <details class="panel"><summary>Unmatched
      (${Object.values(b.unmatched).reduce((n, r) => n + r.length, 0)})</summary>
      <table><thead><tr><th>Source</th><th>Player</th><th>Pos</th><th>Team</th></tr></thead>
      <tbody>${Object.entries(b.unmatched).flatMap(([src, un]) =>
        un.map((r) => `<tr><td class="muted">${esc(src)}</td>
          <td>${esc(r.name)}</td><td>${esc(r.pos)}</td>
          <td class="muted">${esc(r.team) || ""}</td></tr>`)).join("")}
      </tbody></table>
    </details>`;
  $$("button[data-v]", el).forEach((btn) => {
    btn.onclick = () => { state.rankView = btn.dataset.v; renderRankings(opts); };
  });
  $$("input[data-s]", el).forEach((cb) => {
    cb.onchange = () => {
      if (cb.checked) state.enabled.add(cb.dataset.s);
      else state.enabled.delete(cb.dataset.s);
      renderRankings(opts);
    };
  });
}

function renderKD() {
  renderRankings({
    el: "#view-kd",
    positions: ["K", "D/ST"],
    note: "FFB kicker/D rows are per-analyst page ranks (those pages carry no " +
          "projections); Harris and FantasyPros add positional ranks and, for " +
          "FantasyPros, this week's opponent.",
  });
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

  const row = (p, showOpp) => {
    const opp = (b.weekInfo[p.pid] && showOpp) || null;
    return `<tr>
      <td class="slot-label">${showOpp ? "" : ""}</td>
      <td><strong>${esc(p.name)}</strong></td>
      <td>${esc(p.pos)}</td>
      <td class="muted">${esc(p.team) || ""}</td>
      ${showOpp ? `<td class="muted">${esc(opp ? opp.opponent : "")}</td>` : ""}
      <td class="muted">${p.bye ? `bye ${p.bye}` : ""}</td>
      <td class="muted">${p.injury && p.injury !== "ACTIVE"
        ? esc(p.injury.replace(/_/g, " ")) : ""}</td>
    </tr>`;
  };

  const ups = b.recommendations.upgrades.slice(0, 5);
  const drops = b.recommendations.drops.slice(0, 5);
  const byes = Object.entries(b.recommendations.byes);

  el.innerHTML = `
    <div class="controls">
      <span class="muted">Roster, week ${b.meta.currentWeek || "?"}</span>
    </div>
    <table><thead><tr><th></th><th>Player</th><th>Pos</th><th>Team</th>
      <th>Opp</th><th>Bye</th><th>Injury</th></tr></thead><tbody>
      ${starters.map(([sid, ps]) => ps.map((p) =>
        row(p, true).replace('<td class="slot-label"></td>',
          `<td class="slot-label">${SLOTS[sid] || sid}</td>`))).join("")}
      ${bench.map((p) => row(p, false)
        .replace('<td class="slot-label"></td>', `<td class="slot-label">Bench</td>`))
        .join("")}
      ${ir.map((p) => row(p, false)
        .replace('<td class="slot-label"></td>', `<td class="slot-label">IR</td>`))
        .join("")}
      ${others.map((p) => row(p, false)
        .replace('<td class="slot-label"></td>', `<td class="slot-label">${esc(p.lineupSlotId)}</td>`))
        .join("")}
    </tbody></table>

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
    <table><thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>Roster</th>
      <th class="num">Pre-draft</th><th class="num">Now</th><th class="num">Change</th>
    </tr></thead><tbody>
      ${list.slice(0, 60).map((r) => `<tr>
        <td><strong>${esc(r.p.name)}</strong>${r.p.injury && r.p.injury !== "ACTIVE"
          ? `<span class="badge ${esc(r.p.injury)}">${esc(r.p.injury.replace(/_/g, " "))}</span>` : ""}</td>
        <td>${esc(r.p.pos)}</td><td class="muted">${esc(r.p.team) || ""}</td>
        <td>${whoLabel(r.p)}</td>
        <td class="num">${r.pre != null ? `${esc(r.p.pos)}${r.pre}` : "–"}</td>
        <td class="num">${r.now != null ? `${esc(r.p.pos)}${r.now}` : "–"}</td>
        <td class="num ${r.change > 0 ? "up" : r.change < 0 ? "down" : "flat"}">${r.change == null ? ""
          : `${r.change > 0 ? "▲" : "▼"} ${Math.abs(r.change)}`}</td>
      </tr>`).join("")}
    </tbody></table>
    ${list.length > 60 ? `<p class="note">Showing 60 of ${list.length}.</p>` : ""}`;
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
    if (rank == null) return `<td class="num muted">–</td>`;
    const miss = rank - finish;   // > 0: finished better than ranked
    const cls = Math.abs(miss) <= 3 ? "flat" : miss > 0 ? "up" : "down";
    return `<td class="num">${rank} <span class="${cls}" style="font-size:11px">${
      miss === 0 ? "✓" : (miss > 0 ? "+" : "") + miss}</span></td>`;
  };
  return `
    <h2 class="lb-h">Week ${esc(f.week)}: who ranked it best</h2>
    ${weeks.length > 1 ? `<div class="controls"><select id="lb-week">${weeks.map((w) =>
      `<option value="${w}" ${w === f.week ? "selected" : ""}>Week ${w}</option>`).join("")}</select></div>` : ""}
    <p class="note">Each source's week ${esc(f.week)} positional ranks vs actual FFF points.
      <strong>Hits</strong>: of its top k, how many finished top k (k = starters league-wide).
      <strong>Corr</strong>: rank correlation with the actual finish (1 = perfect, 0 = coin flip).
      <strong>Avg miss</strong>: mean |rank − finish| over everyone it ranked.</p>
    <table class="lb-sum"><thead><tr><th>Pos</th>
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
    </tbody></table>

    <div class="controls" style="margin-top:14px">
      <div class="tabs">${positions.map((p) =>
        `<button data-lbp="${p}" class="${p === f.wpos ? "active" : ""}">${p}</button>`).join("")}</div>
      <span class="muted">sorted by actual finish · +N = beat its rank by N</span>
    </div>
    <table><thead><tr><th class="num">Finish</th><th>Player</th><th>Roster</th>
      <th class="num">Pts</th>${srcs.map((s) => `<th class="num">${srcLabel(s)}</th>`).join("")}
    </tr></thead><tbody>
      ${players.map((r) => {
        const p = b.players[r.espnId] || { name: `#${r.espnId}`, status: "FA" };
        return `<tr><td class="num tier-cell">${r.finish}</td>
          <td><strong>${esc(p.name)}</strong> <span class="muted">${esc(p.team) || ""}</span></td>
          <td>${whoLabel(p)}</td>
          <td class="num">${r.pts.toFixed(1)}</td>
          ${srcs.map((s) => missCell(r.ranks[s], r.finish)).join("")}</tr>`;
      }).join("")}
    </tbody></table>`;
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

