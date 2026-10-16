"use strict";

const app = document.getElementById("app");
const tip = document.getElementById("tip");
const CATS = ["attack", "defence", "boost", "speed"];
const CAT_LABELS = { overall: "Overall", attack: "Attack", defence: "Defence", boost: "Boost", speed: "Speed" };
const TEAM_NAMES = ["Blue", "Orange"];
const DEMOS_HINT = String.raw`Documents\My Games\Rocket League\TAGame\Demos`;

/* ---------- helpers ---------- */

async function api(url, opts) {
  const res = await fetch(url, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || body.error || res.statusText);
  return body;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const teamColor = (t) => (t === 1 ? "var(--orange)" : "var(--blue)");
const teamVarName = (t) => (t === 1 ? "--orange" : "--blue");
const round = (v, d = 0) => (v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d));
const perMatch = (total, n) => (n ? (total / n).toFixed(2) : "–");
const playerHref = (key) => `#/player/${encodeURIComponent(key)}`;

function parseDate(s) {
  if (!s) return null;
  let m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2})[-:](\d{2})/.exec(s);
  return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]) : null;
}
function fmtDate(s, withTime = true) {
  const d = parseDate(s);
  if (!d) return "Unknown date";
  const date = d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  return withTime ? `${date}, ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}` : date;
}
function fmtClock(sec) {
  if (sec == null) return "–";
  sec = Math.max(0, Math.round(sec));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}
function mode(teamSize) {
  return teamSize ? `${teamSize}v${teamSize}` : "";
}
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function showTip(html, x, y) {
  tip.innerHTML = html;
  tip.style.display = "block";
  const r = tip.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > innerHeight - 8) top = y - r.height - 14;
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${Math.max(8, top)}px`;
}
function hideTip() { tip.style.display = "none"; }

function barCell(value, color = "var(--accent)", max = 100, digits = 0) {
  const w = value == null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return `<div class="bar-cell"><span class="num">${round(value, digits)}</span><span class="bar-track"><i style="width:${w}%;background:${color}"></i></span></div>`;
}

/* ---------- resize-aware charts ---------- */

let resizers = [];
let pageAbort = new AbortController(); // aborted on navigation to drop page-specific listeners
addEventListener("resize", debounce(() => resizers.forEach((f) => f()), 120));
function mountChart(el, draw) {
  const run = () => { if (el.isConnected) draw(el, el.clientWidth); };
  resizers.push(run);
  run();
}

/* Line chart: one series, crosshair + tooltip. */
function lineChart(el, { points, xMax, yMax = 100, color, height = 220, xLabel = (x) => x, tooltip, markers = [], dots = false, yTicks = [0, 25, 50, 75, 100], xStep }) {
  mountChart(el, (node, width) => {
    const m = { t: 10, r: 12, b: 26, l: 34 };
    const w = Math.max(200, width), h = height;
    const iw = w - m.l - m.r, ih = h - m.t - m.b;
    const valid = points.filter((p) => p.y != null);
    const xm = xMax ?? Math.max(1, ...points.map((p) => p.x));
    const sx = (x) => m.l + (x / xm) * iw;
    const sy = (y) => m.t + ih - (y / yMax) * ih;
    const path = valid.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");
    const xticks = [];
    const step = xStep ? Math.max(xStep, xStep * Math.ceil(xm / xStep / 8)) : niceStep(xm / 6);
    for (let x = 0; x <= xm + 1e-9; x += step) xticks.push(x);
    node.innerHTML = `<svg width="${w}" height="${h}" role="img">
      <g class="axis">${yTicks.map((t) => `<line class="gridline" x1="${m.l}" x2="${w - m.r}" y1="${sy(t)}" y2="${sy(t)}"/><text x="${m.l - 8}" y="${sy(t) + 4}" text-anchor="end">${t}</text>`).join("")}
      ${xticks.map((t) => `<text x="${sx(t)}" y="${h - 6}" text-anchor="middle">${esc(xLabel(t))}</text>`).join("")}</g>
      ${markers.map((mk) => `<line x1="${sx(mk.x)}" x2="${sx(mk.x)}" y1="${m.t}" y2="${m.t + ih}" stroke="${mk.color}" stroke-width="2" stroke-dasharray="3 3" opacity="0.8"/><circle cx="${sx(mk.x)}" cy="${m.t + 4}" r="4" fill="${mk.color}" stroke="var(--surface)" stroke-width="2"/>`).join("")}
      <path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      ${dots ? valid.map((p) => `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="4" fill="${color}" stroke="var(--surface)" stroke-width="2"/>`).join("") : ""}
      <line class="xhair" y1="${m.t}" y2="${m.t + ih}" stroke="var(--muted)" stroke-width="1" visibility="hidden"/>
      <circle class="xdot" r="5" fill="${color}" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>
      <rect x="${m.l}" y="0" width="${iw}" height="${h}" fill="transparent"/>
    </svg>`;
    const svg = node.querySelector("svg");
    const xhair = svg.querySelector(".xhair"), xdot = svg.querySelector(".xdot");
    svg.addEventListener("mousemove", (e) => {
      const bx = e.clientX - svg.getBoundingClientRect().left;
      const x = ((bx - m.l) / iw) * xm;
      let best = null;
      for (const p of valid) if (!best || Math.abs(p.x - x) < Math.abs(best.x - x)) best = p;
      if (!best) return;
      xhair.setAttribute("x1", sx(best.x)); xhair.setAttribute("x2", sx(best.x)); xhair.setAttribute("visibility", "visible");
      xdot.setAttribute("cx", sx(best.x)); xdot.setAttribute("cy", sy(best.y)); xdot.setAttribute("visibility", "visible");
      showTip(tooltip(best), e.clientX, e.clientY);
    });
    svg.addEventListener("mouseleave", () => { xhair.setAttribute("visibility", "hidden"); xdot.setAttribute("visibility", "hidden"); hideTip(); });
  });
}
function niceStep(raw) {
  const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-9)));
  const n = raw / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
}

/* Field heatmap. Blue goal on the left; cells are shares of time. */
function heatmap(el, { cells, grid, colorVar, caption }) {
  mountChart(el, (node, width) => {
    const goalDepth = 880, goalHalf = 893;
    const totalLen = grid.fieldY * 2 + goalDepth * 2;
    const scale = width / totalLen;
    const h = Math.round(grid.fieldX * 2 * scale);
    const dpr = devicePixelRatio || 1;
    node.innerHTML = `<canvas width="${Math.round(width * dpr)}" height="${Math.round(h * dpr)}" style="height:${h}px" aria-label="${esc(caption)}"></canvas>`;
    const canvas = node.querySelector("canvas");
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const fx = (y) => (y + grid.fieldY + goalDepth) * scale; // field y -> canvas x
    const fy = (x) => (x + grid.fieldX) * scale; // field x -> canvas y
    const left = fx(-grid.fieldY), right = fx(grid.fieldY);
    ctx.fillStyle = cssVar("--surface-2");
    ctx.fillRect(left, 0, right - left, h);
    const max = Math.max(...cells, 1e-9);
    const [r, g, b] = hexToRgb(cssVar(colorVar));
    const cw = (right - left) / grid.ny, ch = h / grid.nx;
    for (let gy = 0; gy < grid.ny; gy++) {
      for (let gx = 0; gx < grid.nx; gx++) {
        const v = cells[gy * grid.nx + gx];
        if (!v) continue;
        ctx.fillStyle = `rgba(${r},${g},${b},${Math.sqrt(v / max) * 0.95})`;
        ctx.fillRect(left + gy * cw, gx * ch, cw + 0.5, ch + 0.5);
      }
    }
    ctx.strokeStyle = cssVar("--muted");
    ctx.globalAlpha = 0.6;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(left, 0.75, right - left, h - 1.5);
    ctx.beginPath();
    ctx.moveTo((left + right) / 2, 0); ctx.lineTo((left + right) / 2, h);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc((left + right) / 2, h / 2, 900 * scale, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
    for (const [side, color] of [[-1, "--blue"], [1, "--orange"]]) {
      ctx.fillStyle = cssVar(color);
      const x0 = side < 0 ? fx(-grid.fieldY - goalDepth) : right;
      ctx.fillRect(x0, fy(-goalHalf), goalDepth * scale, goalHalf * 2 * scale);
    }
    canvas.addEventListener("mousemove", (e) => {
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left, py = e.clientY - rect.top;
      const gy = Math.floor((px - left) / cw), gx = Math.floor(py / ch);
      if (gy < 0 || gy >= grid.ny || gx < 0 || gx >= grid.nx) return hideTip();
      const v = cells[gy * grid.nx + gx] || 0;
      showTip(`<b>${(v * 100).toFixed(1)}%</b> of time in this area`, e.clientX, e.clientY);
    });
    canvas.addEventListener("mouseleave", hideTip);
  });
}

function splitBar(label, parts, colorVar) {
  const shades = [40, 70, 100];
  const total = parts.reduce((s, p) => s + (p.value || 0), 0) || 1;
  return `<div class="split"><div class="split-label"><span>${esc(label)}</span></div>
    <div class="split-bar">${parts.map((p, i) => `<i style="flex:${(p.value || 0) / total};background:color-mix(in oklab, var(${colorVar}) ${shades[i]}%, var(--surface))" title="${esc(p.label)}: ${round(p.value, 1)}%"></i>`).join("")}</div>
    <div class="split-legend">${parts.map((p, i) => `<span><i style="background:color-mix(in oklab, var(${colorVar}) ${shades[i]}%, var(--surface))"></i>${esc(p.label)} ${round(p.value, 0)}%</span>`).join("")}</div></div>`;
}

/* ---------- uploads ---------- */

const fileInput = document.getElementById("file-input");
const overlay = document.getElementById("drop-overlay");
document.getElementById("upload-btn").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => { uploadFiles([...fileInput.files]); fileInput.value = ""; });

let dragDepth = 0;
addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { dragDepth++; overlay.classList.add("show"); } });
addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; overlay.classList.remove("show"); } });
addEventListener("dragover", (e) => e.preventDefault());
addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  overlay.classList.remove("show");
  uploadFiles([...(e.dataTransfer?.files || [])]);
});

async function uploadFiles(files) {
  if (!files.length) return;
  document.querySelector(".upload-panel")?.remove();
  const panel = document.createElement("section");
  panel.className = "upload-panel";
  panel.innerHTML = `<header><b>Uploading ${files.length} replay${files.length > 1 ? "s" : ""}</b><button type="button" aria-label="Close">×</button></header>
    <ul>${files.map((f, i) => `<li data-i="${i}"><span class="fname">${esc(f.name)}</span><span class="state muted">Waiting…</span></li>`).join("")}</ul>`;
  panel.querySelector("header button").addEventListener("click", () => panel.remove());
  document.body.append(panel);
  const setState = (i, html, cls = "") => {
    const s = panel.querySelector(`li[data-i="${i}"] .state`);
    s.className = `state ${cls}`;
    s.innerHTML = html;
  };
  let added = 0;
  const batchSize = 8;
  for (let start = 0; start < files.length; start += batchSize) {
    const batch = files.slice(start, start + batchSize);
    const form = new FormData();
    batch.forEach((f, j) => { form.append("files", f); setState(start + j, "Analysing…", "muted"); });
    try {
      const { results } = await api("/api/replays", { method: "POST", body: form });
      results.forEach((r, j) => {
        const i = start + j;
        if (r.status === "error") return setState(i, esc(r.error), "status-error");
        const m = r.match;
        const desc = `${esc(m.map)} · ${m.score[0]}–${m.score[1]}`;
        if (r.status === "added") added++;
        setState(i, `<a href="#/match/${encodeURIComponent(m.id)}">${r.status === "added" ? "Added" : "Already uploaded"} · ${desc}</a>`, `status-${r.status}`);
      });
    } catch (err) {
      batch.forEach((_, j) => setState(start + j, esc(err.message), "status-error"));
    }
  }
  panel.querySelector("header b").textContent = `Done · ${added} new match${added === 1 ? "" : "es"}`;
  if (added) route();
}

function dropzone() {
  return `<label class="dropzone" id="dropzone">
    <strong>Drop .replay files here</strong>
    <span class="sub">or click to choose files</span>
    <span class="muted" style="font-size:12px;margin-top:8px">Rocket League saves replays in<br><code>${esc(DEMOS_HINT)}</code></span>
  </label>`;
}
function bindDropzone() {
  const dz = document.getElementById("dropzone");
  if (dz) dz.addEventListener("click", (e) => { e.preventDefault(); fileInput.click(); });
}

/* ---------- shared fragments ---------- */

function matchItem(m) {
  const best = m.best_name ? `Best: ${esc(m.best_name)}` : "";
  return `<a class="match-item" href="#/match/${encodeURIComponent(m.id)}">
    <div><div class="title">${esc(m.map)}</div>
      <div class="meta">${fmtDate(m.played_at)} · ${mode(m.team_size)} ${esc(m.match_type || "")}${best ? " · " + best : ""}</div></div>
    <div class="scoreline"><span class="t0">${m.score0}</span><span class="dash">–</span><span class="t1">${m.score1}</span></div>
  </a>`;
}

function emptyState(text) {
  return `<div class="empty"><p>${text}</p></div>`;
}

/* ---------- pages ---------- */

async function homePage() {
  const [stats, board, recent] = await Promise.all([api("/api/stats"), api("/api/players?min_matches=1"), api("/api/matches?limit=6")]);
  const min = board.players.some((p) => p.matches >= 3) ? 3 : 1;
  const top = board.players.filter((p) => p.matches >= min).slice(0, 6);
  app.innerHTML = `
    <section class="hero">
      <div>
        <h1>Who's the best player?</h1>
        <p>Upload Rocket League replays. Every player gets rated from 0 to 100 on attack, defence, boost and speed, and the leaderboard combines all of their matches.</p>
        <div class="tiles" style="margin:0">
          <div class="tile"><div class="label">Matches analysed</div><div class="value">${stats.matches}</div></div>
          <div class="tile"><div class="label">Players rated</div><div class="value">${stats.players}</div></div>
        </div>
      </div>
      ${dropzone()}
    </section>
    <div class="grid-2">
      <section class="card">
        <div class="card-head"><div><h2>Top players</h2><p>Average overall rating${min > 1 ? `, at least ${min} matches` : ""}</p></div><a href="#/leaderboard" class="btn">Leaderboard</a></div>
        ${top.length ? `<div class="table-wrap"><table><tbody>${top.map((p, i) => `
          <tr class="clickable" data-href="${playerHref(p.key)}"><td class="n muted">${i + 1}</td><td><b>${esc(p.name)}</b> <span class="muted">· ${p.matches} match${p.matches > 1 ? "es" : ""}</span></td><td style="width:45%">${barCell(p.overall)}</td></tr>`).join("")}</tbody></table></div>` : emptyState("Upload replays to see ratings.")}
      </section>
      <section class="card">
        <div class="card-head"><div><h2>Recent matches</h2><p>Newest first</p></div><a href="#/matches" class="btn">All matches</a></div>
        ${recent.matches.length ? `<div class="match-list">${recent.matches.map(matchItem).join("")}</div>` : emptyState("No matches yet.")}
      </section>
    </div>`;
  bindDropzone();
}

async function matchesPage() {
  const pageSize = 25;
  let offset = 0;
  app.innerHTML = `<div class="page-head"><div><h1>Matches</h1><p class="sub">Every uploaded match, newest first</p></div></div><section class="card" id="list"></section>`;
  const list = document.getElementById("list");
  async function load() {
    const data = await api(`/api/matches?limit=${pageSize}&offset=${offset}`);
    if (!data.total) {
      list.innerHTML = emptyState("No matches yet. Upload some replays to get started.") + dropzone();
      return bindDropzone();
    }
    const pages = Math.ceil(data.total / pageSize), page = offset / pageSize + 1;
    list.innerHTML = `<div class="match-list">${data.matches.map(matchItem).join("")}</div>
      ${pages > 1 ? `<div class="pager"><button class="btn" data-dir="-1" ${page <= 1 ? "disabled" : ""}>Previous</button><span class="muted">Page ${page} of ${pages}</span><button class="btn" data-dir="1" ${page >= pages ? "disabled" : ""}>Next</button></div>` : ""}`;
    list.querySelectorAll("[data-dir]").forEach((b) => b.addEventListener("click", () => { offset += +b.dataset.dir * pageSize; load(); scrollTo(0, 0); }));
  }
  await load();
}

const MODES = [["", "All modes"], ["1", "1v1"], ["2", "2v2"], ["3", "3v3"], ["4", "4v4"]];
const PERIODS = [["", "All time"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["365", "Last year"]];
const MIN_MATCHES = [1, 2, 3, 5, 10, 20];
const LEADERBOARD_DEFAULTS = { min: 1, sort: "overall", desc: true, mode: "", days: "", players: [], together: false };

function loadPrefs(key, defaults) {
  try { return { ...defaults, ...JSON.parse(localStorage.getItem(key) || "{}") }; } catch { return { ...defaults }; }
}
function savePrefs(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}
const options = (pairs, selected) => pairs.map(([v, l]) => `<option value="${v}" ${String(selected) === String(v) ? "selected" : ""}>${l}</option>`).join("");

async function leaderboardPage() {
  const state = loadPrefs("leaderboard", LEADERBOARD_DEFAULTS);
  const everyone = (await api("/api/players?min_matches=1")).players;
  const byKey = new Map(everyone.map((p) => [p.key, p]));
  // selected players are stored as {key, name}; refresh names from the latest data
  state.players = state.players.filter((p) => p && p.key).map((p) => ({ key: p.key, name: byKey.get(p.key)?.name || p.name }));
  const signal = pageAbort.signal;

  app.innerHTML = `
    <div class="page-head"><div><h1>Leaderboard</h1><p class="sub">Average ratings across every match a player appears in. Click a column to sort.</p></div></div>
    <section class="card filters">
      <div class="filter-players">
        <label class="filter-label" for="player-search">Players</label>
        <div class="picker" id="picker">
          <div class="picked" id="picked"></div>
          <input id="player-search" type="text" placeholder="Search players to compare…" autocomplete="off"
                 role="combobox" aria-expanded="false" aria-controls="picker-list" aria-autocomplete="list">
          <ul class="picker-list" id="picker-list" role="listbox" hidden></ul>
        </div>
        <p class="filter-hint">Pick yourself and your friends to see only them. You can also tick players in the table.</p>
      </div>
      <div class="filter-row">
        <label>Mode <select id="f-mode">${options(MODES, state.mode)}</select></label>
        <label>Period <select id="f-days">${options(PERIODS, state.days)}</select></label>
        <label>Minimum matches <select id="f-min">${options(MIN_MATCHES.map((n) => [n, n]), state.min)}</select></label>
        <label class="check" id="together-label"><input type="checkbox" id="f-together"> Only matches played together</label>
        <span class="spacer"></span>
        <button class="btn" id="f-clear" type="button">Clear filters</button>
      </div>
    </section>
    <section class="card"><div class="card-head"><p id="board-summary" style="margin:0"></p></div><div class="table-wrap" id="board"></div></section>`;

  const search = document.getElementById("player-search");
  const list = document.getElementById("picker-list");
  const together = document.getElementById("f-together");
  let suggestions = [], active = -1, players = [];

  const selectedKeys = () => new Set(state.players.map((p) => p.key));
  const persist = () => savePrefs("leaderboard", state);

  function renderPicked() {
    document.getElementById("picked").innerHTML = state.players.map((p) => `
      <span class="pick">${esc(p.name)}<button type="button" data-remove="${esc(p.key)}" aria-label="Remove ${esc(p.name)}">×</button></span>`).join("");
    const enough = state.players.length >= 2;
    together.disabled = !enough;
    together.checked = enough && state.together;
    document.getElementById("together-label").title = enough ? "Count only matches where a player had another selected player on their team" : "Select at least two players";
  }

  function renderSuggestions() {
    const q = search.value.trim().toLowerCase();
    const taken = selectedKeys();
    suggestions = everyone.filter((p) => !taken.has(p.key) && (!q || p.name.toLowerCase().includes(q)))
      .sort((a, b) => b.matches - a.matches).slice(0, 8);
    active = Math.min(active, suggestions.length - 1);
    const open = document.activeElement === search && suggestions.length > 0;
    list.hidden = !open;
    search.setAttribute("aria-expanded", String(open));
    list.innerHTML = suggestions.map((p, i) => `
      <li role="option" id="opt-${i}" data-key="${esc(p.key)}" class="${i === active ? "active" : ""}" aria-selected="${i === active}">
        <b>${esc(p.name)}</b><span class="muted">${esc(p.platform || "")} · ${p.matches} match${p.matches > 1 ? "es" : ""}</span></li>`).join("");
    if (active >= 0) search.setAttribute("aria-activedescendant", `opt-${active}`); else search.removeAttribute("aria-activedescendant");
  }

  function addPlayer(key) {
    const p = byKey.get(key);
    if (!p || selectedKeys().has(key)) return;
    state.players.push({ key, name: p.name });
    search.value = "";
    active = -1;
    changed();
  }
  function removePlayer(key) {
    state.players = state.players.filter((p) => p.key !== key);
    changed();
  }
  function changed() {
    persist();
    renderPicked();
    renderSuggestions();
    load();
  }

  search.addEventListener("focus", renderSuggestions);
  search.addEventListener("input", () => { active = 0; renderSuggestions(); });
  search.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, suggestions.length - 1); renderSuggestions(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); renderSuggestions(); }
    else if (e.key === "Enter" && suggestions[active]) { e.preventDefault(); addPlayer(suggestions[active].key); }
    else if (e.key === "Escape") { search.blur(); list.hidden = true; }
    else if (e.key === "Backspace" && !search.value && state.players.length) removePlayer(state.players[state.players.length - 1].key);
  });
  // mousedown keeps focus in the input while picking
  list.addEventListener("mousedown", (e) => { const li = e.target.closest("[data-key]"); if (li) { e.preventDefault(); addPlayer(li.dataset.key); } });
  document.getElementById("picker").addEventListener("click", (e) => {
    const rm = e.target.closest("[data-remove]");
    if (rm) removePlayer(rm.dataset.remove); else search.focus();
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("#picker")) { list.hidden = true; search.setAttribute("aria-expanded", "false"); } }, { signal });

  for (const [id, key, num] of [["f-mode", "mode"], ["f-days", "days"], ["f-min", "min", true]]) {
    document.getElementById(id).addEventListener("change", (e) => { state[key] = num ? +e.target.value : e.target.value; persist(); load(); });
  }
  together.addEventListener("change", () => { state.together = together.checked; persist(); load(); });
  document.getElementById("f-clear").addEventListener("click", () => {
    Object.assign(state, { ...LEADERBOARD_DEFAULTS, sort: state.sort, desc: state.desc });
    document.getElementById("f-mode").value = "";
    document.getElementById("f-days").value = "";
    document.getElementById("f-min").value = "1";
    changed();
  });

  const cols = [
    { key: "name", label: "Player" },
    { key: "matches", label: "Matches", n: true },
    { key: "winRate", label: "Win %", n: true },
    { key: "mvps", label: "Best player", n: true },
    { key: "overall", label: "Overall" },
    ...CATS.map((c) => ({ key: c, label: CAT_LABELS[c] })),
    { key: "goalsPer", label: "Goals / match", n: true },
    { key: "savesPer", label: "Saves / match", n: true },
  ];

  let requestId = 0;
  async function load() {
    const id = ++requestId;
    const q = new URLSearchParams({ min_matches: state.min });
    if (state.mode) q.set("mode", state.mode);
    if (state.days) q.set("days", state.days);
    state.players.forEach((p) => q.append("player", p.key));
    if (state.players.length >= 2 && state.together) q.set("together", "true");
    const data = await api(`/api/players?${q}`);
    if (id !== requestId) return; // a newer filter change is in flight
    players = data.players.map((p) => ({ ...p, winRate: p.matches ? (p.wins / p.matches) * 100 : 0, goalsPer: p.goals / p.matches, savesPer: p.saves / p.matches }));
    render();
  }

  function render() {
    const el = document.getElementById("board");
    const parts = [
      state.players.length ? `${state.players.length} selected player${state.players.length > 1 ? "s" : ""}` : "All players",
      MODES.find(([v]) => v === String(state.mode))?.[1],
      PERIODS.find(([v]) => v === String(state.days))?.[1],
      state.min > 1 ? `${state.min}+ matches` : "",
      state.players.length >= 2 && state.together ? "only matches played together" : "",
    ].filter(Boolean);
    document.getElementById("board-summary").innerHTML = `<b>${players.length}</b> player${players.length === 1 ? "" : "s"} · <span class="muted">${esc(parts.join(" · "))}</span>`;
    if (!players.length) {
      el.innerHTML = emptyState(state.players.length ? "None of the selected players have matches that fit these filters." : "No players match these filters yet.");
      return;
    }
    const sorted = [...players].sort((a, b) => {
      const av = a[state.sort], bv = b[state.sort];
      const cmp = typeof av === "string" ? av.localeCompare(bv) : (av ?? -1) - (bv ?? -1);
      return state.desc ? -cmp : cmp;
    });
    const taken = selectedKeys();
    el.innerHTML = `<table><thead><tr><th><span class="sr-only">Select</span></th><th class="n">#</th>${cols.map((c) => `<th class="sortable ${c.n ? "n" : ""} ${state.sort === c.key ? "sorted" : ""}" data-key="${c.key}">${c.label}</th>`).join("")}</tr></thead>
      <tbody>${sorted.map((p, i) => `<tr class="clickable" data-href="${playerHref(p.key)}">
        <td class="select-cell"><input type="checkbox" data-select="${esc(p.key)}" ${taken.has(p.key) ? "checked" : ""} aria-label="Compare ${esc(p.name)}"></td>
        <td class="n muted">${i + 1}</td>
        <td><b>${esc(p.name)}</b> <span class="muted">${esc(p.platform || "")}</span></td>
        <td class="n">${p.matches}</td><td class="n">${round(p.winRate)}%</td><td class="n">${p.mvps || 0}</td>
        <td>${barCell(p.overall)}</td>${CATS.map((c) => `<td>${barCell(p[c])}</td>`).join("")}
        <td class="n">${p.goalsPer.toFixed(2)}</td><td class="n">${p.savesPer.toFixed(2)}</td></tr>`).join("")}</tbody></table>`;
    el.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
      const key = th.dataset.key;
      state.desc = state.sort === key ? !state.desc : key !== "name";
      state.sort = key;
      persist();
      render();
    }));
    el.querySelectorAll("[data-select]").forEach((box) => box.addEventListener("change", () => {
      if (box.checked) addPlayer(box.dataset.select); else removePlayer(box.dataset.select);
    }));
  }

  renderPicked();
  await load();
}

const DETAIL_TABS = {
  Boost: [
    ["avgBoost", "Avg boost", 100, 0], ["boostPerMin", "Used / min", null, 0], ["boostCollected", "Collected", null, 0],
    ["bigPads", "Big pads", null, 0], ["smallPads", "Small pads", null, 0], ["emptyBoostPct", "Time at 0 %", 100, 1], ["fullBoostPct", "Time at 100 %", 100, 1],
  ],
  Movement: [
    ["avgSpeed", "Avg speed (uu/s)", 2300, 0], ["supersonicPct", "Supersonic %", 100, 1], ["boostSpeedPct", "Boost speed %", 100, 1], ["slowPct", "Slow %", 100, 1],
    ["groundPct", "On ground %", 100, 1], ["lowAirPct", "Low air / walls %", 100, 1], ["highAirPct", "High air %", 100, 1],
  ],
  Positioning: [
    ["defThirdPct", "Defensive third %", 100, 1], ["midThirdPct", "Middle third %", 100, 1], ["offThirdPct", "Attacking third %", 100, 1],
    ["behindBallPct", "Behind ball %", 100, 1], ["demos", "Demos", null, 0], ["demoed", "Demoed", null, 0],
  ],
};

async function matchPage(id) {
  const m = await api(`/api/matches/${encodeURIComponent(id)}`);
  const players = [...m.players].sort((a, b) => a.team - b.team || (b.ratings?.overall ?? -1) - (a.ratings?.overall ?? -1));
  const best = m.leaders?.overall;
  const state = { tab: "Boost", focus: best?.key || players[0]?.key, heat: "player" };
  const winner = m.score[0] === m.score[1] ? null : m.score[0] > m.score[1] ? 0 : 1;

  app.innerHTML = `
    <section class="card">
      <div class="match-head">
        <div><h1>${esc(m.map)}</h1><p class="sub" style="margin:6px 0 0">${fmtDate(m.date)} · ${mode(m.teamSize)} ${esc(m.matchType || "")} · ${fmtClock(m.liveSeconds)} played</p></div>
        <div class="big-score">
          <div class="side t0">${m.score[0]}<small>${TEAM_NAMES[0]}${winner === 0 ? " · won" : ""}</small></div><span class="dash">–</span>
          <div class="side t1">${m.score[1]}<small>${TEAM_NAMES[1]}${winner === 1 ? " · won" : ""}</small></div>
        </div>
        <div class="best-callout">${best ? `<div class="muted">Best player</div><div class="who"><a href="${playerHref(best.key)}" class="t${best.team}">${esc(best.name)}</a></div><div class="sub">${round(best.rating)} overall rating</div>` : `<div class="muted">No rated players</div>`}</div>
      </div>
      ${m.leaders ? `<div class="leaders">${CATS.filter((c) => m.leaders[c]).map((c) => `<span class="leader">Top ${CAT_LABELS[c].toLowerCase()}: <a href="${playerHref(m.leaders[c].key)}" class="t${m.leaders[c].team}"><b>${esc(m.leaders[c].name)}</b></a> <b>${round(m.leaders[c].rating)}</b></span>`).join("")}</div>` : ""}
    </section>

    <section class="card"><div class="card-head"><div><h2>Goals</h2><p>When each goal was scored, by team</p></div></div><div class="chart" id="goal-chart"></div></section>

    <section class="card">
      <div class="card-head"><div><h2>Ratings</h2><p>0–100 per category, based on this match. Click a player to see the breakdown below.</p></div></div>
      <div class="table-wrap"><table><thead><tr><th>Player</th><th>Overall</th>${CATS.map((c) => `<th>${CAT_LABELS[c]}</th>`).join("")}<th class="n">Score</th><th class="n">Goals</th><th class="n">Assists</th><th class="n">Saves</th><th class="n">Shots</th></tr></thead>
      <tbody>${[0, 1].map((t) => `<tr class="team-row"><td colspan="11"><span class="team-dot" style="background:${teamColor(t)}"></span>${TEAM_NAMES[t]} · ${m.score[t]}</td></tr>` +
        players.filter((p) => p.team === t).map((p) => `<tr class="clickable" data-focus="${esc(p.key)}">
          <td><a href="${playerHref(p.key)}"><b>${esc(p.name)}</b></a> ${best?.key === p.key ? `<span class="badge best">★ Best</span>` : ""}${p.bot ? ` <span class="badge">Bot</span>` : ""}</td>
          ${p.ratings ? `<td>${barCell(p.ratings.overall, teamColor(t))}</td>${CATS.map((c) => `<td>${barCell(p.ratings[c], teamColor(t))}</td>`).join("")}` : `<td colspan="5" class="muted">Not rated${p.bot ? " (bot)" : " (too little time played)"}</td>`}
          <td class="n">${p.score}</td><td class="n">${p.goals}</td><td class="n">${p.assists}</td><td class="n">${p.saves}</td><td class="n">${p.shots}</td></tr>`).join("")).join("")}
      </tbody></table></div>
    </section>

    <section class="card">
      <div class="card-head"><div><h2>Detailed stats</h2><p>Bars compare players within this match</p></div><div class="tabs" id="tabs">${Object.keys(DETAIL_TABS).map((t) => `<button type="button" data-tab="${t}">${t}</button>`).join("")}</div></div>
      <div class="table-wrap" id="detail"></div>
    </section>

    <section class="card">
      <div class="card-head"><div><h2>Player focus</h2><p id="focus-sub"></p></div><div class="chips" id="chips">${players.filter((p) => p.adv).map((p) => `<button type="button" class="chip" data-key="${esc(p.key)}"><span class="team-dot" style="background:${teamColor(p.team)}"></span>${esc(p.name)}</button>`).join("")}</div></div>
      <div class="focus-grid">
        <div>
          <div class="card-head" style="margin-bottom:8px"><h3>Where they played</h3><div class="tabs" id="heat-tabs"><button type="button" data-heat="player">Player</button><button type="button" data-heat="ball">Ball</button></div></div>
          <div class="chart heatmap" id="heat"></div>
          <p class="muted" style="font-size:12px;margin:6px 0 0">Blue goal on the left. Darker means more time spent there.</p>
          <h3 style="margin:20px 0 8px">Boost over time</h3>
          <div class="chart" id="boost-chart"></div>
          <div class="legend"><span><i style="background:var(--blue)"></i>Blue goal</span><span><i style="background:var(--orange)"></i>Orange goal</span></div>
        </div>
        <div>
          <div class="splits" id="splits"></div>
          <h3 style="margin:24px 0 8px">Why this rating</h3>
          <div class="breakdown" id="breakdown"></div>
        </div>
      </div>
    </section>`;

  // Goal timeline
  mountChart(document.getElementById("goal-chart"), (node, width) => {
    const h = 90, padL = 16, padR = 16, mid = 45;
    const total = Math.max(m.liveSeconds || 300, ...m.goals.map((g) => g.time || 0));
    const sx = (t) => padL + (t / total) * (width - padL - padR);
    const ticks = [];
    for (let t = 0; t <= total; t += 60) ticks.push(t);
    node.innerHTML = `<svg width="${width}" height="${h}">
      <line x1="${padL}" x2="${width - padR}" y1="${mid}" y2="${mid}" stroke="var(--grid)" stroke-width="2"/>
      <g class="axis">${ticks.map((t) => `<line x1="${sx(t)}" x2="${sx(t)}" y1="${mid - 4}" y2="${mid + 4}"/><text x="${sx(t)}" y="${h - 2}" text-anchor="middle">${fmtClock(t)}</text>`).join("")}</g>
      ${m.goals.map((g, i) => {
        const y = g.team === 0 ? mid - 18 : mid + 18;
        return `<g class="goal" data-i="${i}"><line x1="${sx(g.time)}" x2="${sx(g.time)}" y1="${mid}" y2="${y}" stroke="${teamColor(g.team)}" stroke-width="2"/>
          <circle cx="${sx(g.time)}" cy="${y}" r="7" fill="${teamColor(g.team)}" stroke="var(--surface)" stroke-width="2"/>
          <circle cx="${sx(g.time)}" cy="${y}" r="14" fill="transparent"/></g>`;
      }).join("")}
    </svg>`;
    node.querySelectorAll(".goal").forEach((el) => {
      const g = m.goals[+el.dataset.i];
      el.addEventListener("mousemove", (e) => showTip(`<b>${esc(g.player)}</b> · ${TEAM_NAMES[g.team]}<br>${fmtClock(g.time)} into the match${g.overtime ? " (overtime)" : g.secondsRemaining != null ? ` · ${fmtClock(g.secondsRemaining)} left` : ""}`, e.clientX, e.clientY));
      el.addEventListener("mouseleave", hideTip);
    });
  });
  if (!m.goals.length) document.getElementById("goal-chart").innerHTML = `<p class="muted">No goals in this match.</p>`;

  // Detailed stats table
  function renderDetail() {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
    const cols = DETAIL_TABS[state.tab];
    const withAdv = players.filter((p) => p.adv);
    const maxes = Object.fromEntries(cols.map(([k, , max]) => [k, max ?? Math.max(1, ...withAdv.map((p) => p.adv[k] || 0))]));
    document.getElementById("detail").innerHTML = withAdv.length ? `<table><thead><tr><th>Player</th>${cols.map(([, l]) => `<th>${l}</th>`).join("")}</tr></thead><tbody>
      ${withAdv.map((p) => `<tr class="clickable ${p.key === state.focus ? "focus" : ""}" data-focus="${esc(p.key)}"><td><span class="team-dot" style="background:${teamColor(p.team)}"></span>${esc(p.name)}</td>
        ${cols.map(([k, , , d]) => `<td>${barCell(p.adv[k], teamColor(p.team), maxes[k], d)}</td>`).join("")}</tr>`).join("")}</tbody></table>` : emptyState("No detailed data in this replay.");
  }

  function renderFocus() {
    const p = players.find((x) => x.key === state.focus);
    document.querySelectorAll("#chips .chip").forEach((c) => c.classList.toggle("active", c.dataset.key === state.focus));
    document.querySelectorAll("#heat-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.heat === state.heat));
    document.querySelectorAll("#detail tr[data-focus]").forEach((r) => r.classList.toggle("focus", r.dataset.focus === state.focus));
    if (!p || !p.adv) return;
    document.getElementById("focus-sub").textContent = `${p.name} · ${TEAM_NAMES[p.team]} · ${fmtClock(p.adv.time)} on the field`;
    resizers = resizers.filter((f) => !f.focus);
    const before = resizers.length;
    const showBall = state.heat === "ball";
    heatmap(document.getElementById("heat"), { cells: showBall ? m.ball.heatmap : p.heatmap, grid: m.grid, colorVar: showBall ? "--accent" : teamVarName(p.team), caption: showBall ? "Ball positions" : `${p.name} positions` });
    const series = p.boostSeries || [];
    lineChart(document.getElementById("boost-chart"), {
      points: series.map((y, x) => ({ x, y })), xMax: Math.max(series.length - 1, 1), color: teamColor(p.team), height: 180,
      xLabel: fmtClock, xStep: 60, tooltip: (pt) => `<b>${pt.y}</b> boost<br>${fmtClock(pt.x)} into the match`,
      markers: m.goals.map((g) => ({ x: g.time, color: teamColor(g.team) })),
    });
    resizers.slice(before).forEach((f) => (f.focus = true));
    const a = p.adv, tv = teamVarName(p.team);
    document.getElementById("splits").innerHTML = [
      splitBar("Field position", [{ label: "Defensive", value: a.defThirdPct }, { label: "Middle", value: a.midThirdPct }, { label: "Attacking", value: a.offThirdPct }], tv),
      splitBar("Speed", [{ label: "Slow", value: a.slowPct }, { label: "Boost speed", value: a.boostSpeedPct }, { label: "Supersonic", value: a.supersonicPct }], tv),
      splitBar("Height", [{ label: "Ground", value: a.groundPct }, { label: "Low air / walls", value: a.lowAirPct }, { label: "High air", value: a.highAirPct }], tv),
    ].join("");
    document.getElementById("breakdown").innerHTML = p.ratings ? breakdownHtml(p.ratings.breakdown, p.ratings, teamColor(p.team)) : `<p class="muted">This player wasn't rated.</p>`;
  }

  document.getElementById("tabs").addEventListener("click", (e) => { const t = e.target.closest("[data-tab]"); if (t) { state.tab = t.dataset.tab; renderDetail(); } });
  document.getElementById("heat-tabs").addEventListener("click", (e) => { const t = e.target.closest("[data-heat]"); if (t) { state.heat = t.dataset.heat; renderFocus(); } });
  document.getElementById("chips").addEventListener("click", (e) => { const c = e.target.closest("[data-key]"); if (c) { state.focus = c.dataset.key; renderFocus(); } });
  app.addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-focus]");
    if (row && !e.target.closest("a")) {
      state.focus = row.dataset.focus;
      renderFocus();
      document.getElementById("chips").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, { signal: pageAbort.signal });
  renderDetail();
  renderFocus();
}

function breakdownHtml(breakdown, ratings, color) {
  return ["attack", "defence", "boost", "speed", "impact"].filter((c) => breakdown?.[c]).map((c) => `
    <div><h3><span>${c === "impact" ? "Impact (in-game score)" : CAT_LABELS[c]}</span>${ratings && ratings[c] != null ? `<span>${round(ratings[c])}</span>` : ""}</h3>
    ${breakdown[c].map((part) => `<div class="row"><span>${esc(part.label)}</span><span class="val">${round(part.value, part.value % 1 ? 1 : 0)}</span>${barCell(part.score, color)}</div>`).join("")}</div>`).join("");
}

async function playerPage(key) {
  const p = await api(`/api/players/${encodeURIComponent(key)}`);
  const winRate = p.matches ? (p.wins / p.matches) * 100 : 0;
  const shooting = p.totals.shots ? (p.totals.goals / p.totals.shots) * 100 : 0;
  const ranked = p.comparison.filter((c) => c.diff != null);
  const strongest = ranked[0], weakest = ranked[ranked.length - 1];
  const insight = strongest && weakest && strongest !== weakest
    ? `Strongest at <b>${CAT_LABELS[strongest.category].toLowerCase()}</b> (${strongest.diff >= 0 ? "+" : ""}${strongest.diff} vs average). Most room to improve in <b>${CAT_LABELS[weakest.category].toLowerCase()}</b> (${weakest.diff >= 0 ? "+" : ""}${weakest.diff}).`
    : "";
  const history = [...p.history].reverse();

  app.innerHTML = `
    <div class="page-head"><div><h1>${esc(p.name)}</h1>
      <p class="sub" style="margin:6px 0 0">${esc(p.platform || "")}${p.rank ? ` · Rank #${p.rank} of ${p.rankedPlayers}${p.rankMinMatches > 1 ? ` players with ${p.rankMinMatches}+ matches` : ""}` : ""}${p.aliases.length ? ` · Also played as ${p.aliases.map(esc).join(", ")}` : ""}</p></div></div>
    <div class="tiles">
      <div class="tile"><div class="label">Overall rating</div><div class="value">${round(p.ratings.overall)}</div><div class="hint">Average of ${p.ratedMatches} rated</div></div>
      <div class="tile"><div class="label">Matches</div><div class="value">${p.matches}</div><div class="hint">${p.wins} wins · ${round(winRate)}%</div></div>
      <div class="tile"><div class="label">Best player</div><div class="value">${p.mvps}</div><div class="hint">times in a match</div></div>
      <div class="tile"><div class="label">Goals / match</div><div class="value">${perMatch(p.totals.goals, p.matches)}</div><div class="hint">${round(shooting)}% shooting</div></div>
      <div class="tile"><div class="label">Saves / match</div><div class="value">${perMatch(p.totals.saves, p.matches)}</div></div>
      <div class="tile"><div class="label">Assists / match</div><div class="value">${perMatch(p.totals.assists, p.matches)}</div></div>
    </div>
    <div class="grid-2">
      <section class="card">
        <div class="card-head"><div><h2>Ratings vs everyone</h2><p>Bar: ${esc(p.name)}'s average. Line: average of all rated players.</p></div></div>
        ${["overall", ...CATS].map((c) => `<div class="compare-row"><span>${CAT_LABELS[c]}</span>
          <div class="compare-track" data-tip="${esc(`${CAT_LABELS[c]}: ${round(p.ratings[c], 1)} (everyone: ${round(p.everyone[c], 1)})`)}"><span class="fill" style="width:${p.ratings[c] ?? 0}%"></span><span class="avg" style="left:calc(${p.everyone[c] ?? 0}% - 1px)"></span></div>
          <b class="num" style="text-align:right">${round(p.ratings[c])}</b></div>`).join("")}
        <div class="legend"><span><i style="background:var(--accent)"></i>${esc(p.name)}</span><span><i style="background:var(--text);width:2px;height:12px"></i>All players</span></div>
        ${insight ? `<p class="insight">${insight}</p>` : ""}
      </section>
      <section class="card">
        <div class="card-head"><div><h2>Overall rating by match</h2><p>Oldest to newest</p></div></div>
        <div class="chart" id="trend"></div>
      </section>
    </div>
    <div class="grid-2" style="margin-top:20px">
      <section class="card">
        <div class="card-head"><div><h2>Where they play</h2><p>Average over matches, own goal always on the left</p></div></div>
        ${p.heatmap ? `<div class="chart heatmap" id="heat"></div>` : `<p class="muted">No position data.</p>`}
        <div class="splits" style="margin-top:20px">${p.adv.defThirdPct != null ? [
          splitBar("Field position", [{ label: "Defensive", value: p.adv.defThirdPct }, { label: "Middle", value: p.adv.midThirdPct }, { label: "Attacking", value: p.adv.offThirdPct }], "--accent"),
          splitBar("Height", [{ label: "Ground", value: p.adv.groundPct }, { label: "Low air / walls", value: p.adv.lowAirPct }, { label: "High air", value: p.adv.highAirPct }], "--accent"),
        ].join("") : ""}</div>
      </section>
      <section class="card">
        <div class="card-head"><div><h2>What drives the ratings</h2><p>Average value per match and the score it earns (0–100)</p></div></div>
        <div class="breakdown">${breakdownHtml(p.breakdown, p.ratings, "var(--accent)")}</div>
      </section>
    </div>
    <section class="card" style="margin-top:20px">
      <div class="card-head"><div><h2>Match history</h2></div></div>
      <div class="table-wrap"><table><thead><tr><th>Date</th><th>Map</th><th>Result</th><th class="n">Score</th><th>Overall</th>${CATS.map((c) => `<th>${CAT_LABELS[c]}</th>`).join("")}<th class="n">G</th><th class="n">A</th><th class="n">Sv</th><th class="n">Sh</th></tr></thead>
      <tbody>${history.map((h) => `<tr class="clickable" data-href="#/match/${encodeURIComponent(h.matchId)}">
        <td>${fmtDate(h.playedAt, false)}</td><td>${esc(h.map)} <span class="muted">${mode(h.teamSize)}</span></td>
        <td><span class="result ${h.won ? "win" : h.won === 0 ? "loss" : ""}">${h.won ? "Win" : h.won === 0 ? "Loss" : "–"}</span> ${h.isBest ? `<span class="badge best">★ Best</span>` : ""}</td>
        <td class="n"><span class="t0">${h.score[0]}</span>–<span class="t1">${h.score[1]}</span></td>
        <td>${barCell(h.overall, teamColor(h.team))}</td>${CATS.map((c) => `<td>${barCell(h[c], teamColor(h.team))}</td>`).join("")}
        <td class="n">${h.goals}</td><td class="n">${h.assists}</td><td class="n">${h.saves}</td><td class="n">${h.shots}</td></tr>`).join("")}</tbody></table></div>
    </section>`;

  const rated = p.history.filter((h) => h.overall != null);
  if (rated.length) {
    lineChart(document.getElementById("trend"), {
      points: rated.map((h, i) => ({ x: i, y: h.overall, h })), xMax: Math.max(rated.length - 1, 1), color: "var(--accent)", dots: rated.length <= 40,
      xLabel: (x) => `#${x + 1}`, xStep: 1,
      tooltip: (pt) => `<b>${round(pt.y)}</b> overall<br>${esc(pt.h.map)} · ${fmtDate(pt.h.playedAt, false)}<br>${pt.h.won ? "Win" : "Loss"} ${pt.h.score[0]}–${pt.h.score[1]}${pt.h.isBest ? " · ★ Best player" : ""}`,
    });
  } else {
    document.getElementById("trend").innerHTML = `<p class="muted">No rated matches yet.</p>`;
  }
  if (p.heatmap) heatmap(document.getElementById("heat"), { cells: p.heatmap, grid: { nx: 24, ny: 30, fieldX: 4096, fieldY: 5120 }, colorVar: "--accent", caption: `${p.name} average positions` });
  app.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (e) => showTip(esc(el.dataset.tip), e.clientX, e.clientY));
    el.addEventListener("mouseleave", hideTip);
  });
}

async function ratingsPage() {
  const model = await api("/api/model");
  const fmtRange = (lo, hi) => (lo > hi ? `${hi} best · ${lo} or worse scores 0` : `${lo} or less scores 0 · ${hi}+ scores 100`);
  app.innerHTML = `
    <div class="page-head"><div><h1>How ratings work</h1><p class="sub">Every player in every match gets a 0–100 rating per category. The leaderboard averages them across matches.</p></div></div>
    <section class="card">
      <h2 style="margin-bottom:8px">The idea</h2>
      <p class="sub" style="margin:0 0 8px">Each stat is placed on a 0–100 scale between a low and a high benchmark, then the stats in a category are combined with the weights below.
      Goals, shots, assists and saves are counted <b>per 5 minutes</b> on the field, so short matches and overtime are compared fairly.
      Players with less than ${model.minSeconds} seconds on the field, and bots, aren't rated.</p>
      <p class="sub" style="margin:0">The benchmarks are fixed, so a rating doesn't change when other people upload replays.
      <b>Overall</b> = ${Object.entries(model.overallWeights).map(([k, w]) => `${Math.round(w * 100)}% ${k === "impact" ? "impact (in-game score per minute)" : CAT_LABELS[k].toLowerCase()}`).join(" + ")}.
      The best player in a match is the one with the highest overall rating.</p>
    </section>
    <div class="grid-2">${Object.entries(model.categories).map(([cat, parts]) => `
      <section class="card model-cat"><h2 style="margin-bottom:12px">${CAT_LABELS[cat]}</h2>
        <div class="table-wrap"><table><thead><tr><th>Stat</th><th class="n">Weight</th><th>Scale</th></tr></thead><tbody>
        ${parts.map((p) => `<tr><td>${esc(p.label)}</td><td class="n">${Math.round(p.weight * 100)}%</td><td class="muted">${fmtRange(p.low, p.high)}</td></tr>`).join("")}
        </tbody></table></div></section>`).join("")}
    </div>`;
}

/* ---------- router ---------- */

const ROUTES = [
  [/^#?\/?$/, homePage, "home"],
  [/^#\/matches$/, matchesPage, "matches"],
  [/^#\/leaderboard$/, leaderboardPage, "leaderboard"],
  [/^#\/ratings$/, ratingsPage, "ratings"],
  [/^#\/match\/(.+)$/, matchPage, "matches"],
  [/^#\/player\/(.+)$/, playerPage, "leaderboard"],
];

async function route() {
  const hash = location.hash || "#/";
  const found = ROUTES.find(([re]) => re.test(hash));
  if (!found) { location.hash = "#/"; return; }
  const [re, page, nav] = found;
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
  resizers = [];
  pageAbort.abort();
  pageAbort = new AbortController();
  hideTip();
  app.innerHTML = `<div class="loading">Loading…</div>`;
  try {
    await page(...hash.match(re).slice(1).map(decodeURIComponent));
  } catch (err) {
    app.innerHTML = `<div class="error">${esc(err.message)}</div>`;
  }
}

app.addEventListener("click", (e) => {
  const row = e.target.closest("tr[data-href]");
  if (row && !e.target.closest("a, input, button, label")) location.hash = row.dataset.href;
});
addEventListener("hashchange", () => { route(); scrollTo(0, 0); });
route();
