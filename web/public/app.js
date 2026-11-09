"use strict";

// Fixed source -> color slot, so a site keeps its color no matter what is filtered.
const SOURCES = ["Ynet", "Kan News", "Channel 13", "Channel 14", "I24 NEWS", "Channel 12"];
// Daily schedule in UTC (mirrors web/vercel.json and .github/workflows/kan-daily.yml).
const SCHEDULE_UTC = { default: [20, 0], "Kan News": [20, 15] };
const STATUS = {
  ok: { label: "OK", rank: 0 },
  degraded: { label: "Degraded", rank: 1 },
  stale: { label: "Stale", rank: 1 },
  none: { label: "No runs", rank: 1 },
  failing: { label: "Failing", rank: 2 },
};

const colorOf = s => { const i = SOURCES.indexOf(s); return i >= 0 ? `var(--s${i + 1})` : "var(--other)"; };
const order = s => (SOURCES.includes(s) ? SOURCES.indexOf(s) : 99);
const bySource = (a, b) => order(a.source) - order(b.source);
const state = { by: "ingested", days: 30, view: "daily", runs: "all" };
let lastData = null;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = n => (n ?? 0).toLocaleString("en-US");
const fmtTime = iso => new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
const fmtDate = iso => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "–");
const shortTime = iso => new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
const isHebrew = s => /[֐-׿]/.test(s || "");
const siteLabel = s => `<span class="site"><span class="dot" style="background:${colorOf(s)}"></span>${esc(s)}</span>`;

function ago(iso) {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}
function untilNextRun() {
  const now = new Date();
  const [h, m] = SCHEDULE_UTC.default;
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), h, m));
  if (next <= now) next.setUTCDate(next.getUTCDate() + 1);
  const mins = Math.round((next - now) / 60000);
  const local = next.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `Next run ${local} (in ${mins >= 60 ? Math.floor(mins / 60) + " h " : ""}${mins % 60} min)`;
}

function bindSeg(id, key, cast, onChange) {
  $(id).addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    state[key] = cast(b.dataset.v);
    for (const x of $(id).querySelectorAll("button")) x.setAttribute("aria-pressed", x === b);
    onChange();
  });
}
bindSeg("by", "by", String, load);
bindSeg("days", "days", Number, load);
// These only re-draw; the data is the same.
bindSeg("view", "view", String, () => lastData && renderMain(lastData));
bindSeg("runs-filter", "runs", String, () => lastData && renderRuns(lastData.runs));

// ---------- theme ----------
const THEMES = ["auto", "light", "dark"];
function currentTheme() { return document.documentElement.dataset.theme || "auto"; }
function paintThemeBtn() {
  const t = currentTheme();
  $("theme-btn").textContent = t === "dark" ? "☾" : t === "light" ? "☀" : "◐";
  $("theme-btn").title = `Theme: ${t} (click to change)`;
}
$("theme-btn").addEventListener("click", () => {
  const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
  if (next === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = next;
  try { next === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", next); } catch (e) { /* storage blocked */ }
  paintThemeBtn();
  if (lastData) render(lastData);  // SVG colors are read from CSS vars at draw time
});
paintThemeBtn();

// ---------- login ----------
function lock(locked) {
  document.body.classList.toggle("locked", locked);
  if (locked) setTimeout(() => $("password").focus(), 0);
}
$("login-form").addEventListener("submit", async e => {
  e.preventDefault();
  $("login-btn").disabled = true; $("login-error").textContent = "";
  try {
    const r = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("password").value }),
    });
    if (!r.ok) throw new Error(r.status === 401 ? "Wrong password" : `Sign-in failed (${r.status})`);
    $("password").value = "";
    lock(false);
    load(); explore();
  } catch (err) {
    $("login-error").textContent = err.message;
  } finally {
    $("login-btn").disabled = false;
  }
});
$("logout").addEventListener("click", async () => {
  await fetch("/api/login?logout=1", { method: "POST" });
  lastData = null;
  lock(true);
});

// ---------- manual ingestion ----------
$("ingest-btn").addEventListener("click", async () => {
  const btn = $("ingest-btn"), box = $("ingest-result");
  btn.disabled = true; btn.textContent = "Ingesting…";
  box.hidden = false; box.className = "notice";
  box.innerHTML = `<div class="head">Ingesting…</div>Scraping 5 sites now. This takes about 10 to 60 seconds. <a href="/logs" target="_blank">Watch it live in Logs ↗</a>`;
  const t0 = Date.now();
  try {
    const r = await fetch("/api/cron", { method: "POST" });
    if (r.status === 401) { box.hidden = true; return lock(true); }
    const res = await r.json();
    if (!r.ok) throw new Error(res.error || `HTTP ${r.status}`);
    const secs = Math.round((Date.now() - t0) / 1000);
    const sites = [...res.sites].sort(bySource);
    const bad = sites.filter(s => s.error);
    const parts = sites.map(s => s.error
      ? `<span class="bad-text">${esc(s.source)}: failed</span>`
      : `${esc(s.source)} +${s.new_articles} <span class="muted">(${s.links_found} links${s.failed ? `, ${s.failed} skipped` : ""})</span>`);
    box.className = "notice " + (bad.length ? "bad" : "ok");
    box.innerHTML = `<button class="link-btn close" type="button" onclick="this.parentElement.hidden=true">Close</button>
      <div class="head">${bad.length ? "⚠" : "✓"} Done in ${secs} s: ${fmt(res.new_articles)} new article${res.new_articles === 1 ? "" : "s"}${res.run_id ? ` · <a href="/logs?run=${esc(res.run_id)}">see the log</a>` : ""}</div>
      <div>${parts.join(" · ")}</div>
      ${bad.map(s => `<div class="muted">${esc(s.source)}: ${esc(s.error)}</div>`).join("")}
      ${res.kan ? `<div class="muted">Kan News: ${esc(res.kan.message)}</div>` : ""}`;
    load(); explore();
  } catch (e) {
    box.className = "notice bad";
    box.innerHTML = `<button class="link-btn close" type="button" onclick="this.parentElement.hidden=true">Close</button><div class="head">✕ Ingestion failed</div>${esc(e.message)}`;
  } finally {
    btn.disabled = false; btn.textContent = "Ingest now";
  }
});

// ---------- data ----------
async function load() {
  try {
    const r = await fetch(`/api/stats?by=${state.by}&days=${state.days}`);
    if (r.status === 401) return lock(true);
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || r.statusText);
    lastData = data;
    render(data);
  } catch (e) {
    $("pill").className = "pill bad"; $("pill").textContent = "Could not load data";
    $("chart").innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
}

function render(data) {
  const health = Object.fromEntries(data.health.map(h => [h.source, h]));
  const sites = [...data.sites].sort(bySource);
  renderHeader(data);
  renderKpis(data, sites);
  renderSites(sites, health);
  renderMain(data);
  renderCoverage(data);
  renderQuality(sites);
  renderRuns(data.runs);
  renderLatest(data.latest);
  fillSourceFilter(sites);
}

function renderHeader(data) {
  const n = k => data.health.filter(h => h.status === k).length;
  const failing = n("failing"), warn = n("degraded") + n("stale") + n("none");
  const pill = $("pill");
  if (failing) { pill.className = "pill bad"; pill.textContent = `${failing} site${failing > 1 ? "s" : ""} failing`; }
  else if (warn) { pill.className = "pill warn"; pill.textContent = warn > 1 ? `${warn} sites need attention` : "1 site needs attention"; }
  else { pill.className = "pill ok"; pill.textContent = `All ${data.health.length} sites healthy`; }
  const last = data.runs.length ? data.runs[0].ran_at : null;
  $("last-run").textContent = last ? `Last run ${ago(last)}` : "No runs yet";
  $("next-run").textContent = untilNextRun();
}

// ---------- KPI strip ----------
function renderKpis(data, sites) {
  const k = data.kpis;
  const lastRuns = data.health.map(h => h.last_run).filter(Boolean);
  const failedLast = lastRuns.reduce((a, r) => a + (r.failed || 0), 0);
  const newLast = lastRuns.reduce((a, r) => a + (r.new_articles || 0), 0);
  const healthy = data.health.filter(h => h.status === "ok").length;
  const attention = data.health.filter(h => h.status !== "ok").map(h => `${h.source} ${STATUS[h.status].label.toLowerCase()}`);
  let delta = "no data for the week before";
  if (k.prev7) {
    const d = Math.round(((k.last7 - k.prev7) / k.prev7) * 100);
    delta = `<span class="delta ${d >= 0 ? "up" : "down"}">${d >= 0 ? "▲" : "▼"} ${fmt(Math.abs(d))}%</span> vs previous 7 days`;
  }
  const months = k.oldest ? Math.max(1, Math.round((Date.parse(data.today) - Date.parse(k.oldest)) / (30.4 * 864e5))) : 0;
  const tile = (label, value, note, cls = "") =>
    `<div class="kpi ${cls}"><div class="label">${label}</div><div class="value">${value}</div><div class="note" title="${esc(note.replace(/<[^>]+>/g, ""))}">${note}</div></div>`;
  $("kpis").innerHTML =
    tile("Total articles", fmt(k.total), `${fmt(k.total - k.from_csv)} scraped · ${fmt(k.from_csv)} from CSV`) +
    tile("Added, last 7 days", fmt(k.last7), delta) +
    tile("Added today", fmt(k.today), "Israel time") +
    tile("Sites healthy", `${healthy}<small> / ${data.health.length}</small>`,
         attention.length ? attention.join(" · ") : "all scrapers working", healthy < data.health.length ? "caution" : "") +
    tile("Failed in last runs", fmt(failedLast), `${fmt(newLast)} new across all sites' last runs`, failedLast ? "alert" : "") +
    tile("With publish date", `${pct(k.with_date, k.total)}<small>%</small>`, `${fmt(k.total - k.with_date)} without a date`) +
    tile("Morale-scored", `${pct(k.scored, k.total)}<small>%</small>`, `${fmt(k.scored)} of ${fmt(k.total)} have a score`) +
    tile("History reaches", k.oldest ? new Date(k.oldest).toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : "–",
         k.oldest ? `${fmtDate(k.oldest)} · about ${months} month${months > 1 ? "s" : ""}` : "");
}

// ---------- site status board ----------
function sparkline(history, color) {
  const W = 220, H = 34, P = 3;
  const pts = history.map(r => r.links ?? 0);
  if (!pts.length) return `<svg class="spark" viewBox="0 0 ${W} ${H}"></svg>`;
  // One-off deep runs (the backfill) would flatten everything else, so the scale
  // follows the typical run and taller points are clipped and marked.
  const sorted = [...pts].sort((a, b) => a - b), median = sorted[Math.floor(sorted.length / 2)];
  const cap = Math.max(4, median * 2.5, ...pts.filter(v => v <= median * 2.5));
  const x = i => P + (pts.length > 1 ? (i / (pts.length - 1)) * (W - 2 * P) : (W - 2 * P) / 2);
  const y = v => H - P - (Math.min(v, cap) / cap) * (H - 2 * P);
  let svg = `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Links found per run">`;
  svg += `<path d="M${pts.map((v, i) => `${x(i)},${y(v)}`).join("L")}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>`;
  history.forEach((r, i) => {
    const t = `${shortTime(r.ran_at)} · ${fmt(r.links ?? 0)} links · ${r.ok ? `+${r.new} new` : esc(r.error || "no links")}`;
    if (!r.ok) svg += `<circle cx="${x(i)}" cy="${y(pts[i])}" r="2.6" fill="var(--critical)"><title>${t}</title></circle>`;
    else if (pts[i] > cap) svg += `<circle cx="${x(i)}" cy="${y(pts[i])}" r="2.2" fill="${color}"><title>${t} (off scale)</title></circle>`;
    else svg += `<circle cx="${x(i)}" cy="${y(pts[i])}" r="5" fill="transparent"><title>${t}</title></circle>`;
  });
  return svg + `</svg>`;
}

function renderSites(sites, health) {
  const all = [...new Set([...sites.map(s => s.source), ...Object.keys(health)])].sort((a, b) => order(a) - order(b));
  if (!all.length) { $("sites").innerHTML = `<div class="empty">No data yet.</div>`; return; }
  const totals = Object.fromEntries(sites.map(s => [s.source, s]));
  $("sites").innerHTML = all.map(src => {
    const h = health[src] || { status: "none", history: [] }, s = totals[src] || {};
    const hist = h.history || [], lr = h.last_run;
    const okRuns = hist.filter(r => r.ok).length;
    const st = STATUS[h.status] || STATUS.none;
    return `<div class="site-card" style="--c:${colorOf(src)}">
      <div class="top"><span class="name">${esc(src)}</span><span class="badge ${h.status}">${st.label}</span></div>
      ${sparkline(hist, colorOf(src))}
      <div class="facts">
        <div class="fact"><div class="k">Links</div><div class="v">${lr ? fmt(lr.links_found) : "–"}</div></div>
        <div class="fact"><div class="k">New</div><div class="v">${lr ? (lr.new_articles ? "+" + fmt(lr.new_articles) : "0") : "–"}</div></div>
        <div class="fact"><div class="k">Failed</div><div class="v ${lr && lr.failed ? "bad-text" : ""}">${lr ? fmt(lr.failed) : "–"}</div></div>
        <div class="fact"><div class="k">Stored</div><div class="v">${fmt(s.total)}</div></div>
      </div>
      <div class="when"><span>${lr ? `Last run ${ago(lr.ran_at)}` : "Never run"}</span><span>${okRuns}/${hist.length} runs OK</span></div>
      ${lr && lr.error ? `<div class="err" title="${esc(lr.error)}">${esc(lr.error)}</div>` : ""}
    </div>`;
  }).join("");
}

// ---------- main chart ----------
function dayRange(data) {
  // Full day range (oldest first) so empty days show as gaps; "All" starts at the earliest day with data.
  const DAY = 864e5;
  const todayMs = Date.parse(data.today);  // YYYY-MM-DD parses as UTC midnight
  let span = data.days;
  if (!span) {
    const first = data.daily.reduce((m, r) => (r.day < m ? r.day : m), data.today);
    span = Math.round((todayMs - Date.parse(first)) / DAY);
  }
  const days = [];
  for (let i = span; i >= 0; i--) days.push(new Date(todayMs - i * DAY).toISOString().slice(0, 10));
  return days;
}

function renderMain(data) {
  const present = new Set(data.daily.map(d => d.source));
  const sources = [...SOURCES.filter(s => present.has(s)), ...[...present].filter(s => !SOURCES.includes(s)).sort()];
  const days = dayRange(data);
  const byDay = {};
  for (const r of data.daily) (byDay[r.day] ||= {})[r.source] = r.count;

  const dateKind = state.by === "published" ? "published" : "ingested";
  const inRange = data.daily.reduce((a, r) => a + r.count, 0);
  $("chart-hint").textContent = `${fmt(inRange)} articles ${state.days ? `in the last ${state.days} days` : "in total"}, by ${dateKind} date`;
  if (state.view === "total") {
    $("chart-title").textContent = "Total articles over time";
    $("legend").innerHTML = "";
    renderTotal(days, byDay, sources, data.kpis.total);
  } else {
    $("chart-title").textContent = "Articles per day";
    $("legend").innerHTML = sources.map(s => `<span><span class="dot" style="background:${colorOf(s)}"></span>${esc(s)}</span>`).join("");
    renderChart(days, byDay, sources);
  }
}

// Charts are drawn at the container's real pixel width (re-drawn on resize),
// so they fill wide screens without stretching text.
function chartSize(el) {
  const W = Math.max(300, Math.round(el.clientWidth || 1000));
  return { W, H: W < 600 ? 230 : 300 };
}
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => lastData && (renderMain(lastData), renderCoverage(lastData)), 150);
});
function niceScale(max) {
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(1, max))));
  const step = mag * ([1, 2, 5, 10].find(f => max / (mag * f) <= 5) || 10);
  return { step, yMax: Math.max(step, Math.ceil(max / step) * step) };
}
function placeTip(tip, el, e) {
  tip.style.display = "block";
  const box = el.getBoundingClientRect();
  let left = e.clientX - box.left + 12;
  if (left + tip.offsetWidth > box.width) left = e.clientX - box.left - tip.offsetWidth - 12;
  tip.style.left = Math.max(0, left) + "px";
  tip.style.top = Math.max(0, e.clientY - box.top - tip.offsetHeight - 8) + "px";
}

function renderChart(days, byDay, sources) {
  const el = $("chart");
  const { W, H } = chartSize(el), m = { t: 8, r: 8, b: 26, l: 42 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const totalOf = d => sources.reduce((a, s) => a + ((byDay[d] || {})[s] || 0), 0);
  if (!days.some(d => totalOf(d) > 0)) { el.innerHTML = `<div class="empty">No articles in this range yet.</div>`; return; }
  const { step, yMax } = niceScale(Math.max(...days.map(totalOf)));
  const y = v => m.t + ih - (v / yMax) * ih;
  const band = iw / days.length, bw = Math.max(2, Math.min(26, band * 0.7));
  const GAP = 1, R = 3;

  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Stacked bar chart of articles per day by site">`;
  for (let v = 0; v <= yMax; v += step) {
    svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(${v === 0 ? "--axis" : "--grid"})" stroke-width="1"/>`;
    svg += `<text class="tick" x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`;
  }
  const labelEvery = Math.ceil(days.length / Math.max(3, Math.floor(iw / 70)));
  days.forEach((d, i) => {
    const cx = m.l + band * i + band / 2, x = cx - bw / 2;
    let acc = 0;
    const segs = sources.map(s => ({ s, v: (byDay[d] || {})[s] || 0 })).filter(o => o.v > 0);
    segs.forEach((o, k) => {
      const y0 = y(acc); acc += o.v;
      const top = k === segs.length - 1;
      const h = Math.max(1, y0 - y(acc) - (top ? 0 : GAP));
      const yTop = y0 - h;
      if (top && h > R) {
        svg += `<path d="M${x},${y0}V${yTop + R}Q${x},${yTop} ${x + R},${yTop}H${x + bw - R}Q${x + bw},${yTop} ${x + bw},${yTop + R}V${y0}Z" fill="${colorOf(o.s)}"/>`;
      } else {
        svg += `<rect x="${x}" y="${yTop}" width="${bw}" height="${h}" fill="${colorOf(o.s)}"/>`;
      }
    });
    if (i % labelEvery === 0 || i === days.length - 1)
      svg += `<text class="tick" x="${cx}" y="${H - 8}" text-anchor="middle">${d.slice(5).replace("-", "/")}</text>`;
    svg += `<rect class="hit" data-i="${i}" x="${m.l + band * i}" y="${m.t}" width="${band}" height="${ih}" fill="transparent"/>`;
  });
  svg += `</svg><div class="tooltip" id="tip"></div>`;
  el.innerHTML = svg;

  const tip = $("tip");
  el.querySelectorAll(".hit").forEach(h => {
    h.addEventListener("mousemove", e => {
      const d = days[+h.dataset.i], row = byDay[d] || {};
      const rows = sources.filter(s => row[s]).map(s =>
        `<div class="row"><span class="dot" style="background:${colorOf(s)}"></span>${esc(s)}<b>${row[s]}</b></div>`).join("");
      tip.innerHTML = `<div style="font-weight:600;margin-bottom:4px">${d} · ${fmt(totalOf(d))} articles</div>${rows || '<div class="muted">No articles</div>'}`;
      placeTip(tip, el, e);
      h.setAttribute("fill", "rgba(127,127,127,0.08)");
    });
    h.addEventListener("mouseleave", () => { tip.style.display = "none"; h.setAttribute("fill", "transparent"); });
  });
}

// Running total of articles in the database, one point per day.
function renderTotal(days, byDay, sources, total) {
  const el = $("chart");
  const { W, H } = chartSize(el), m = { t: 20, r: 56, b: 26, l: 48 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  if (!total) { el.innerHTML = `<div class="empty">No articles yet.</div>`; return; }
  const added = days.map(d => sources.reduce((a, s) => a + ((byDay[d] || {})[s] || 0), 0));
  // Articles from before the first day shown, so the line starts at the real total.
  let run = total - added.reduce((a, b) => a + b, 0);
  const cum = added.map(n => (run += n));
  const { step, yMax } = niceScale(Math.max(...cum));
  const y = v => m.t + ih - (v / yMax) * ih;
  const x = i => m.l + (days.length > 1 ? (i / (days.length - 1)) * iw : iw / 2);

  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Line chart of the total number of articles over time">`;
  for (let v = 0; v <= yMax; v += step) {
    svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(${v === 0 ? "--axis" : "--grid"})" stroke-width="1"/>`;
    svg += `<text class="tick" x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`;
  }
  const labelEvery = Math.ceil(days.length / Math.max(3, Math.floor(iw / 70)));
  days.forEach((d, i) => {
    if (i % labelEvery === 0 || i === days.length - 1)
      svg += `<text class="tick" x="${x(i)}" y="${H - 8}" text-anchor="middle">${d.slice(5).replace("-", "/")}</text>`;
  });
  const pts = cum.map((v, i) => `${x(i)},${y(v)}`);
  svg += `<path d="M${pts[0]}L${pts.join("L")}L${x(cum.length - 1)},${y(0)}L${x(0)},${y(0)}Z" fill="var(--s1)" opacity="0.12"/>`;
  svg += `<path d="M${pts.join("L")}" fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  const li = cum.length - 1;
  svg += `<circle cx="${x(li)}" cy="${y(cum[li])}" r="4" fill="var(--s1)" stroke="var(--surface-1)" stroke-width="2"/>`;
  svg += `<text class="end-label" x="${x(li) + 8}" y="${y(cum[li]) + 4}">${fmt(cum[li])}</text>`;
  svg += `<line id="xh" y1="${m.t}" y2="${m.t + ih}" stroke="var(--axis)" stroke-width="1" visibility="hidden"/>`;
  svg += `<circle id="xd" r="4" fill="var(--s1)" stroke="var(--surface-1)" stroke-width="2" visibility="hidden"/>`;
  svg += `<rect id="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/>`;
  svg += `</svg><div class="tooltip" id="tip"></div>`;
  el.innerHTML = svg;

  const svgEl = el.querySelector("svg"), tip = $("tip"), xh = $("xh"), xd = $("xd");
  $("hit").addEventListener("mousemove", e => {
    const p = svgEl.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
    const sx = p.matrixTransform(svgEl.getScreenCTM().inverse()).x;
    const i = Math.max(0, Math.min(days.length - 1, Math.round(((sx - m.l) / iw) * (days.length - 1))));
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
    xd.setAttribute("cx", x(i)); xd.setAttribute("cy", y(cum[i])); xd.setAttribute("visibility", "visible");
    tip.innerHTML = `<div style="font-weight:600;margin-bottom:4px">${days[i]}</div>
      <div class="row">Total<b>${fmt(cum[i])}</b></div>
      <div class="row muted">Added that day<b>+${fmt(added[i])}</b></div>`;
    placeTip(tip, el, e);
  });
  $("hit").addEventListener("mouseleave", () => {
    tip.style.display = "none"; xh.setAttribute("visibility", "hidden"); xd.setAttribute("visibility", "hidden");
  });
}

// ---------- coverage heatmap ----------
function renderCoverage(data) {
  const el = $("coverage"), DAY = 864e5;
  // 90 days need room; a phone gets the last 30 so the cells stay visible.
  const N = el.clientWidth && el.clientWidth < 640 ? 30 : (data.coverage_days || 90);
  const todayMs = Date.parse(data.today);
  const days = Array.from({ length: N + 1 }, (_, i) => new Date(todayMs - (N - i) * DAY).toISOString().slice(0, 10));
  const grid = {};
  for (const c of data.coverage) (grid[c.source] ||= {})[c.day] = c.count;
  const sources = [...new Set([...data.sites.map(s => s.source)])].sort((a, b) => order(a) - order(b));
  if (!sources.length) { el.innerHTML = `<div class="empty">No data yet.</div>`; return; }
  // Shade per site against that site's own busy day, so a small site's gaps are as visible as a big one's.
  const level = (v, max) => (v ? 0.22 + 0.78 * Math.min(1, v / max) : 0);
  const cols = `repeat(${days.length}, minmax(0, 1fr))`;
  const monthMarks = days.map((d, i) => (d.endsWith("-01") || i === 0) ? `<span style="left:${(i / days.length) * 100}%">${new Date(d).toLocaleDateString("en-GB", { month: "short" })}</span>` : "").join("");
  let html = `<div class="heatmap" style="grid-template-columns:max-content minmax(0,1fr) max-content">
    <span></span><div class="months">${monthMarks}</div><span class="total muted">${N}d</span>`;
  for (const s of sources) {
    const row = grid[s] || {}, vals = days.map(d => row[d]).filter(Boolean);  // only the days shown
    const max = vals.length ? Math.max(...[...vals].sort((a, b) => a - b).slice(0, Math.ceil(vals.length * 0.95))) || 1 : 1;
    const empty = days.filter(d => !row[d]).length;
    html += `<span class="label"><span class="dot" style="background:${colorOf(s)}"></span>${esc(s)}</span>
      <div class="cells" style="grid-template-columns:${cols}">${days.map(d => {
        const v = row[d] || 0, a = level(v, max);
        return `<i data-s="${esc(s)}" data-d="${d}" data-v="${v}" style="${v ? `background:color-mix(in srgb, ${colorOf(s)} ${Math.round(a * 100)}%, var(--grid))` : ""}"></i>`;
      }).join("")}</div>
      <span class="total" title="${empty} days with nothing stored">${fmt(vals.reduce((a, b) => a + b, 0))}</span>`;
  }
  html += `</div><div class="heat-legend">Fewer <i style="background:var(--grid)"></i>${[0.3, 0.55, 0.8, 1].map(a => `<i style="background:color-mix(in srgb, var(--text-secondary) ${a * 100}%, var(--grid))"></i>`).join("")} More · shaded per site against its own busiest days</div>
    <div class="tooltip" id="heat-tip"></div>`;
  el.innerHTML = html;
  const tip = $("heat-tip");
  el.querySelectorAll(".cells i").forEach(c => {
    c.addEventListener("mousemove", e => {
      tip.innerHTML = `<div style="font-weight:600">${esc(c.dataset.s)}</div><div class="row">${c.dataset.d}<b>${c.dataset.v} article${c.dataset.v === "1" ? "" : "s"}</b></div>`;
      placeTip(tip, el, e);
    });
    c.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  });
  $("coverage-hint").textContent = `Articles per site per publish day, last ${N} days. Empty cells are days with nothing stored.`;
}

// ---------- data quality ----------
function renderQuality(sites) {
  if (!sites.length) { $("quality").innerHTML = `<div class="empty">No data yet.</div>`; return; }
  const bar = (n, total) => {
    const p = pct(n, total);
    return `<span class="pct ${p < 80 ? "low" : ""}">${p}%<span class="bar"><i style="width:${p}%"></i></span></span>`;
  };
  const delay = h => h == null ? '<span class="muted">–</span>' : h < 48 ? `${h} h` : `${(h / 24).toFixed(1)} d`;
  const maxTotal = Math.max(...sites.map(s => s.total));
  const sum = k => sites.reduce((a, s) => a + (s[k] || 0), 0);
  const T = { total: sum("total"), with_text: sum("with_text"), with_date: sum("with_date"), scored: sum("scored"), last7: sum("last7"), from_csv: sum("from_csv") };
  $("quality").innerHTML = `<table>
    <thead><tr><th>Site</th><th>Articles</th><th>Last 7 d</th><th>From CSV</th><th>With text</th><th>With date</th><th>Scored</th>
      <th>Avg length</th><th>Median delay</th><th>Oldest</th><th>Newest</th><th>Last stored</th></tr></thead>
    <tbody>${sites.map(s => `<tr>
      <td>${siteLabel(s.source)}</td>
      <td><span class="share"><b>${fmt(s.total)}</b><span class="bar"><i style="width:${(s.total / maxTotal) * 100}%;background:${colorOf(s.source)}"></i></span></span></td>
      <td class="${s.last7 ? "" : "zero"}">${fmt(s.last7)}</td>
      <td class="${s.from_csv ? "" : "zero"}">${fmt(s.from_csv)}</td>
      <td>${bar(s.with_text, s.total)}</td>
      <td>${bar(s.with_date, s.total)}</td>
      <td>${bar(s.scored, s.total)}</td>
      <td>${s.avg_len ? fmt(s.avg_len) : "–"}</td>
      <td>${delay(s.median_delay_h)}</td>
      <td>${fmtDate(s.oldest)}</td>
      <td>${fmtDate(s.newest)}</td>
      <td title="${s.last_ingested ? esc(fmtTime(s.last_ingested)) : ""}">${s.last_ingested ? ago(s.last_ingested) : "–"}</td>
    </tr>`).join("")}
    <tr style="font-weight:600"><td>All sites</td><td>${fmt(T.total)}</td><td>${fmt(T.last7)}</td><td>${fmt(T.from_csv)}</td>
      <td>${bar(T.with_text, T.total)}</td><td>${bar(T.with_date, T.total)}</td><td>${bar(T.scored, T.total)}</td>
      <td></td><td></td><td></td><td></td><td></td></tr>
    </tbody></table>`;
}

// ---------- run log ----------
function renderRuns(runs) {
  const problem = r => !r.ok || r.failed > 0 || r.error;
  const shown = state.runs === "problems" ? runs.filter(problem) : runs;
  $("runs-hint").textContent = `${fmt(runs.length)} most recent runs across all sites · ${fmt(runs.filter(problem).length)} with problems`;
  if (!shown.length) { $("runs").innerHTML = `<div class="empty">${state.runs === "problems" ? "No problems in recent runs." : "No runs yet."}</div>`; return; }
  $("runs").innerHTML = `<table>
    <thead><tr><th>Time</th><th class="left">Site</th><th class="left">Result</th><th>Links</th><th>New</th><th>Failed</th><th class="left">Error</th></tr></thead>
    <tbody>${shown.map(r => `<tr>
      <td title="${esc(fmtTime(r.ran_at))}">${r.run_id ? `<a class="run-link" href="/logs?run=${esc(r.run_id)}" title="Open this run's log">${shortTime(r.ran_at)}</a>` : shortTime(r.ran_at)}</td>
      <td class="left">${siteLabel(r.source)}</td>
      <td class="left">${r.ok ? `<span class="ok-text">✓ OK</span>` : `<span class="bad-text">✕ Failed</span>`}</td>
      <td>${fmt(r.links_found)}</td>
      <td class="${r.new_articles ? "" : "zero"}">${r.new_articles ? "+" + fmt(r.new_articles) : "0"}</td>
      <td class="${r.failed ? "bad-text" : "zero"}">${fmt(r.failed)}</td>
      <td class="err-cell" title="${esc(r.error || "")}">${esc(r.error || "")}</td>
    </tr>`).join("")}</tbody></table>`;
}

// ---------- latest articles ----------
function renderLatest(items) {
  if (!items.length) { $("latest").innerHTML = `<li class="empty">No scraped articles yet.</li>`; return; }
  $("latest").innerHTML = items.map(a => `<li dir="${isHebrew(a.title) ? "rtl" : "ltr"}">
      <div class="meta"><span class="dot" style="background:${colorOf(a.source)}"></span><span class="src">${esc(a.source)}</span>
        <span>${a.published_at ? `published ${ago(a.published_at)}` : `saved ${ago(a.ingested_at)}`}</span></div>
      <a href="${esc(a.url)}" target="_blank" rel="noopener" dir="auto">${esc(a.title)}</a>
    </li>`).join("");
}

// ---------- article explorer ----------
const PAGE = 50;
const ex = { offset: 0, total: 0, seq: 0 };
function fillSourceFilter(sites) {
  const sel = $("f-source");
  if (sel.options.length > 1) return;
  for (const s of sites) sel.add(new Option(`${s.source} (${fmt(s.total)})`, s.source));
}
function highlight(text, q) {
  const safe = esc(text);
  if (!q) return safe;
  const re = new RegExp(esc(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
  return safe.replace(re, m => `<mark>${m}</mark>`);
}
async function explore() {
  const q = $("f-q").value.trim();
  const params = new URLSearchParams({ q, source: $("f-source").value, limit: PAGE, offset: ex.offset });
  if ($("f-from").value) params.set("from", $("f-from").value);
  if ($("f-to").value) params.set("to", $("f-to").value);
  const seq = ++ex.seq;
  $("explorer-hint").textContent = "Searching…";
  try {
    const r = await fetch(`/api/articles?${params}`);
    if (r.status === 401) return lock(true);
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || r.statusText);
    if (seq !== ex.seq) return;  // a newer search already replaced this one
    ex.total = data.total;
    renderExplorer(data.items, q);
  } catch (e) {
    if (seq === ex.seq) $("explorer").innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
}
function renderExplorer(items, q) {
  const from = ex.total ? ex.offset + 1 : 0, to = ex.offset + items.length;
  $("explorer-hint").textContent = `${fmt(ex.total)} article${ex.total === 1 ? "" : "s"} match. Click a row to preview it.`;
  $("pager-info").textContent = ex.total ? `${fmt(from)}–${fmt(to)} of ${fmt(ex.total)}` : "";
  $("prev").disabled = ex.offset === 0;
  $("next").disabled = to >= ex.total;
  if (!items.length) { $("explorer").innerHTML = `<div class="empty">No articles match these filters.</div>`; return; }
  $("explorer").innerHTML = `<table>
    <thead><tr><th>Published</th><th class="left">Site</th><th>Title</th><th>Length</th><th>Origin</th><th>Score</th></tr></thead>
    <tbody>${items.map((a, i) => `<tr class="row" data-i="${i}">
      <td>${a.published_at ? fmtDate(a.published_at) : `<span class="muted">saved ${fmtDate(a.ingested_at)}</span>`}</td>
      <td class="left">${siteLabel(a.source)}</td>
      <td class="title" dir="auto" title="${esc(a.title)}">${highlight(a.title, q)}</td>
      <td>${a.length ? fmt(a.length) : '<span class="muted">title only</span>'}</td>
      <td>${a.origin === "csv" ? "CSV" : "Scraper"}</td>
      <td>${a.score == null ? '<span class="muted">–</span>' : Number(a.score).toFixed(2)}</td>
    </tr><tr class="detail" data-i="${i}" hidden><td colspan="6">
      <div class="snippet" dir="auto">${highlight(a.snippet || "", q)}${a.length > 700 ? "…" : ""}</div>
      <div class="detail-meta">
        <a href="${esc(a.url)}" target="_blank" rel="noopener">Open original ↗</a>
        <span>Stored ${esc(fmtTime(a.ingested_at))}</span>
        ${a.published_at ? `<span>Published ${esc(fmtTime(a.published_at))}</span>` : ""}
        <span>${fmt(a.length)} characters</span>
      </div>
    </td></tr>`).join("")}</tbody></table>`;
}
$("explorer").addEventListener("click", e => {
  if (e.target.closest("a")) return;
  const row = e.target.closest("tr.row"); if (!row) return;
  const detail = $("explorer").querySelector(`tr.detail[data-i="${row.dataset.i}"]`);
  detail.hidden = !detail.hidden;
});
let searchTimer;
const restart = () => { ex.offset = 0; clearTimeout(searchTimer); searchTimer = setTimeout(explore, 300); };
$("f-q").addEventListener("input", restart);
for (const id of ["f-source", "f-from", "f-to"]) $(id).addEventListener("change", restart);
$("filters").addEventListener("submit", e => { e.preventDefault(); restart(); });
$("filters").addEventListener("reset", () => setTimeout(restart, 0));
$("prev").addEventListener("click", () => { ex.offset = Math.max(0, ex.offset - PAGE); explore(); });
$("next").addEventListener("click", () => { ex.offset += PAGE; explore(); });

load();
explore();
setInterval(() => { if (lastData) $("next-run").textContent = untilNextRun(); }, 60000);
