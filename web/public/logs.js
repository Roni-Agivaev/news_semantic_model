// Scrape logs page: recent runs on the left, the selected run's events on the right.
// Follows a running scrape live by polling /api/logs.
const SOURCES = ["Ynet", "Kan News", "Channel 13", "Channel 14", "I24 NEWS", "Channel 12"];
const POLL_LIVE_MS = 4000;    // while a run is in progress
const POLL_IDLE_MS = 30000;   // otherwise, to notice a new run
const TRIGGERS = {
  cron: "Daily cron", manual: "Ingest now", "kan-action": "Kan (GitHub)",
  backfill: "Backfill", local: "Local run",
};
const STATUS_TEXT = { ok: "OK", warn: "Warnings", error: "Errors", running: "Running", unfinished: "Cut off" };
// The section-walk, sitemap, link and summary events; "everything" adds each article.
const STEP_EVENTS = new Set(["start", "sitemap", "section", "links", "save", "done"]);

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = n => (n ?? 0).toLocaleString("en-US");
const colorOf = s => { const i = SOURCES.indexOf(s); return i >= 0 ? `var(--s${i + 1})` : "var(--other)"; };
const isHebrew = s => /[֐-׿]/.test(s || "");
const when = iso => new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const clock = iso => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const live = r => r && r.status === "running";

function dur(sec) {
  if (sec == null) return "–";
  sec = Math.round(sec);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60), s = sec % 60;
  return m < 60 ? `${m}m ${String(s).padStart(2, "0")}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}
function ago(iso) {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

const st = {
  runs: [], runId: new URLSearchParams(location.search).get("run"), pinned: false,
  run: null, events: [], level: "all", step: "all", open: new Set(), timer: null,
};
st.pinned = !!st.runId;  // a run named in the URL stays selected when new runs appear

// ---------- theme ----------
const THEMES = ["auto", "light", "dark"];
const currentTheme = () => document.documentElement.dataset.theme || "auto";
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
});
paintThemeBtn();

// ---------- login ----------
function lock(locked) {
  document.body.classList.toggle("locked", locked);
  if (locked) { clearTimeout(st.timer); setTimeout(() => $("password").focus(), 0); }
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
    refresh();
  } catch (err) {
    $("login-error").textContent = err.message;
  } finally {
    $("login-btn").disabled = false;
  }
});
$("logout").addEventListener("click", async () => {
  await fetch("/api/login?logout=1", { method: "POST" });
  lock(true);
});

// ---------- data ----------
async function api(qs) {
  const r = await fetch(`/api/logs${qs}`);
  if (r.status === 401) { lock(true); throw new Error("signed out"); }
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}

async function refresh() {
  clearTimeout(st.timer);
  try {
    // Without a pinned run the API returns the newest one, so the page follows new runs
    const body = await api(st.pinned && st.runId ? `?run=${encodeURIComponent(st.runId)}` : "");
    st.runs = body.runs; st.run = body.run; st.events = body.events;
    st.runId = body.run ? body.run.id : null;
    renderRuns();
    renderRun();
    renderHeader();
  } catch (e) {
    if (e.message === "signed out") return;
    $("pill").className = "pill bad"; $("pill").textContent = "Could not load logs";
    $("events").innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
  const anyLive = st.runs.some(live);
  st.timer = setTimeout(refresh, anyLive ? POLL_LIVE_MS : POLL_IDLE_MS);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && !document.body.classList.contains("locked")) refresh(); });

function select(id) {
  st.runId = id; st.pinned = true; st.open.clear();
  history.replaceState(null, "", `?run=${id}`);
  refresh();
}

// ---------- header ----------
function renderHeader() {
  const running = st.runs.filter(live);
  const pill = $("pill");
  if (running.length) {
    pill.className = "pill live";
    pill.textContent = `${running.length === 1 ? "A run is" : running.length + " runs are"} in progress`;
  } else if (st.runs.length) {
    const last = st.runs[0];
    pill.className = "pill " + ({ ok: "ok", warn: "warn" }[last.status] || "bad");
    pill.textContent = `Idle · last run ${ago(last.started_at)} · ${STATUS_TEXT[last.status] || last.status}`;
  } else {
    pill.className = "pill"; pill.textContent = "No runs logged yet";
  }
  $("refreshed").textContent = `Updated ${new Date().toLocaleTimeString("en-GB")} · refreshes every ${running.length ? POLL_LIVE_MS / 1000 + " s" : POLL_IDLE_MS / 1000 + " s"}`;
}

// ---------- run list ----------
function badge(status) {
  return `<span class="badge st-${esc(status)}">${status === "running" ? '<i class="pulse"></i>' : ""}${esc(STATUS_TEXT[status] || status)}</span>`;
}
function renderRuns() {
  $("runs-hint").textContent = st.runs.length ? `${st.runs.length} runs in the last 30 days, newest first` : "Newest first";
  if (!st.runs.length) {
    $("run-list").innerHTML = `<li class="empty">No runs logged yet.<br>The next daily run (20:00 UTC) or a click on <b>Ingest now</b> will show up here.</li>`;
    return;
  }
  $("run-list").innerHTML = st.runs.map(r => `
    <li><button type="button" class="run-item${r.id === st.runId ? " active" : ""}" data-id="${esc(r.id)}">
      <div class="run-top"><b>${esc(TRIGGERS[r.trigger] || r.trigger)}</b>${badge(r.status)}</div>
      <div class="run-when">${esc(when(r.started_at))} · ${dur(r.seconds)}</div>
      <div class="run-counts">
        <span>${r.new_articles != null ? `<b>+${fmt(r.new_articles)}</b> new` : "…"}</span>
        ${r.warn ? `<span class="warn-text">${fmt(r.warn)} warn</span>` : ""}
        ${r.error ? `<span class="bad-text">${fmt(r.error)} err</span>` : ""}
        <span class="muted">${r.sources.length === 1 ? esc(r.sources[0]) : r.sources.length + " sites"}</span>
      </div>
    </button></li>`).join("");
}
$("run-list").addEventListener("click", e => {
  const b = e.target.closest(".run-item"); if (b) select(b.dataset.id);
});

// ---------- selected run ----------
function renderRun() {
  const r = st.run;
  if (!r) {
    $("run-title").textContent = "Run"; $("run-sub").textContent = "";
    $("run-facts").innerHTML = ""; $("site-chips").innerHTML = "";
    $("events").innerHTML = `<div class="empty">Select a run.</div>`; $("events-info").textContent = "";
    return;
  }
  $("run-title").innerHTML = `${esc(TRIGGERS[r.trigger] || r.trigger)} ${badge(r.status)}`;
  $("run-sub").textContent = `Run ${r.id} · started ${when(r.started_at)}`;
  const facts = [
    ["Duration", dur(r.seconds) + (live(r) ? " so far" : "")],
    ["New articles", r.new_articles != null ? fmt(r.new_articles) : "…"],
    ["Sites", r.sources.length],
    ["Events", fmt(r.info + r.warn + r.error)],
    ["Warnings", fmt(r.warn)],
    ["Errors", fmt(r.error)],
  ];
  $("run-facts").innerHTML = facts.map(([k, v], i) =>
    `<div class="fact${i === 4 && r.warn ? " warn" : ""}${i === 5 && r.error ? " bad" : ""}"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

  // Per-site outcome: the summary once finished, otherwise the latest "done" events
  const sites = [...r.sources].sort((a, b) => SOURCES.indexOf(a) - SOURCES.indexOf(b));
  const doneOf = Object.fromEntries(st.events.filter(e => e.step === "done").map(e => [e.source, e]));
  $("site-chips").innerHTML = sites.map(s => {
    const sum = r.summary && r.summary[s];
    const done = doneOf[s];
    let cls = "running", text = "working…";
    if (sum) {
      cls = sum.error ? "error" : (sum.failed || sum.title_only) ? "warn" : "ok";
      text = sum.error ? "failed" : `+${sum.new_articles} new · ${sum.links_found} links${sum.failed ? ` · ${sum.failed} failed` : ""}`;
    } else if (done) {
      cls = done.level === "info" ? "ok" : done.level; text = done.message.replace(/^Done in \d+s: /, "");
    } else if (r.status === "unfinished") {
      cls = "error"; text = "never finished";
    }
    return `<button type="button" class="chip c-${cls}" data-site="${esc(s)}" title="Show only ${esc(s)}">
      <span class="dot" style="background:${colorOf(s)}"></span><b>${esc(s)}</b><span>${esc(text)}</span></button>`;
  }).join("");

  const cur = $("f-site").value;
  $("f-site").innerHTML = `<option value="">All sites</option>` + sites.map(s => `<option${s === cur ? " selected" : ""}>${esc(s)}</option>`).join("");
  renderEvents();
}
$("site-chips").addEventListener("click", e => {
  const c = e.target.closest(".chip"); if (!c) return;
  $("f-site").value = $("f-site").value === c.dataset.site ? "" : c.dataset.site;
  renderEvents();
});

function filtered() {
  const site = $("f-site").value, q = $("f-q").value.trim().toLowerCase();
  return st.events.filter(e =>
    (!site || e.source === site) &&
    (st.level === "all" || (st.level === "warn" ? e.level !== "info" : e.level === "error")) &&
    (st.step === "all" || STEP_EVENTS.has(e.step) || e.level !== "info") &&
    (!q || e.message.toLowerCase().includes(q) || (e.url || "").toLowerCase().includes(q)));
}

function renderEvents() {
  const r = st.run; if (!r) return;
  const box = $("events");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const rows = filtered();
  const t0 = new Date(r.started_at);
  $("events-info").textContent = `${fmt(rows.length)} of ${fmt(st.events.length)} events` + (live(r) ? " · live" : "");
  if (!st.events.length) {
    box.innerHTML = `<div class="empty">${live(r) ? "Waiting for the first events…" : "This run recorded no events."}</div>`;
    return;
  }
  if (!rows.length) { box.innerHTML = `<div class="empty">No events match the filters.</div>`; return; }
  box.innerHTML = `<table class="log">
    <thead><tr><th>Time</th><th class="left">Site</th><th class="left">Level</th><th class="left">Step</th><th class="left msg-h">Message</th></tr></thead>
    <tbody>${rows.map(e => {
      const rel = (new Date(e.at) - t0) / 1000;
      const open = st.open.has(e.id);
      const detail = e.detail ? Object.entries(e.detail).map(([k, v]) => `<span><span class="muted">${esc(k)}</span> ${esc(v)}</span>`).join("") : "";
      return `<tr class="ev lv-${e.level}${open ? " open" : ""}" data-id="${e.id}">
        <td class="t" title="${esc(clock(e.at))}">${clock(e.at)}<span class="rel">+${rel.toFixed(1)}s</span></td>
        <td class="left">${e.source ? `<span class="site"><span class="dot" style="background:${colorOf(e.source)}"></span>${esc(e.source)}</span>` : ""}</td>
        <td class="left"><span class="lvl ${e.level}">${e.level}</span></td>
        <td class="left step">${esc(e.step)}</td>
        <td class="left msg"><span dir="auto">${esc(e.message)}</span></td>
      </tr>${open ? `<tr class="ev-detail"><td colspan="5">
        ${e.url ? `<div><a href="${esc(e.url)}" target="_blank" rel="noopener" dir="ltr">${esc(e.url)}</a></div>` : ""}
        ${detail ? `<div class="kv">${detail}</div>` : ""}
        <div class="muted">${esc(new Date(e.at).toLocaleString("en-GB"))}</div>
      </td></tr>` : ""}`;
    }).join("")}</tbody></table>`;
  if (live(r) && $("follow").checked && (atBottom || !box.dataset.seen)) box.scrollTop = box.scrollHeight;
  box.dataset.seen = "1";
}
$("events").addEventListener("click", e => {
  if (e.target.closest("a")) return;
  const tr = e.target.closest("tr.ev"); if (!tr) return;
  const id = Number(tr.dataset.id);
  st.open.has(id) ? st.open.delete(id) : st.open.add(id);
  renderEvents();
});

function bindSeg(id, key) {
  $(id).addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    st[key] = b.dataset.v;
    for (const x of $(id).querySelectorAll("button")) x.setAttribute("aria-pressed", x === b);
    renderEvents();
  });
}
bindSeg("f-level", "level");
bindSeg("f-step", "step");
$("f-site").addEventListener("change", renderEvents);
$("f-q").addEventListener("input", renderEvents);
$("filters").addEventListener("submit", e => e.preventDefault());

refresh();
