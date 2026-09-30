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

function moverCell(pid, view) {
  if (view !== "weekly" || !state.board.movers) return "";
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
      ${view === "weekly" ? moverCell(pid, view) : ""}
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
      <th class="num">Tier</th>${view === "weekly" ? '<th class="num">Δ</th>' : ""}
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

/* ---------------- dispatch / refresh / init ---------------- */

function render() {
  if (!state.board) return;
  if (state.view === "waivers") renderWaivers();
  else if (state.view === "rankings") renderRankings({});
  else if (state.view === "kd") renderKD();
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

