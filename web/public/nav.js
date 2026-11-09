// Sidebar shared by every page: phone drawer, "On this page" highlighting, next-run time.
(() => {
  const side = document.getElementById("sidebar");
  const scrim = document.getElementById("side-scrim");
  const btn = document.getElementById("menu-btn");
  const narrow = window.matchMedia("(max-width: 960px)");

  function setOpen(open) {
    side.classList.toggle("open", open);
    scrim.hidden = !open;
    btn.setAttribute("aria-expanded", open);
    if (open) side.querySelector("a")?.focus();
  }
  btn.addEventListener("click", () => setOpen(!side.classList.contains("open")));
  scrim.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", e => { if (e.key === "Escape" && side.classList.contains("open")) { setOpen(false); btn.focus(); } });
  // On a phone, following a link closes the drawer
  side.addEventListener("click", e => { if (e.target.closest("a") && narrow.matches) setOpen(false); });
  narrow.addEventListener("change", () => setOpen(false));

  // Highlight the section in view
  const links = [...side.querySelectorAll(".side-sub")];
  const targets = links.map(a => {
    const id = a.getAttribute("href").slice(1);
    return document.getElementById(id) || document.querySelector(`[data-section="${id}"]`);
  });
  links.forEach((a, i) => a.addEventListener("click", e => {
    if (!targets[i]) return;
    e.preventDefault();
    targets[i].scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    history.replaceState(null, "", location.pathname + location.search);
  }));
  function spy() {
    const line = Math.min(160, window.innerHeight * 0.25);  // just under the top bar
    let current = 0;
    // Side-by-side panels share a top edge; the first of them (the left one) wins
    let lastTop = -Infinity;
    targets.forEach((t, i) => {
      if (!t) return;
      const top = Math.round(t.getBoundingClientRect().top);
      if (top <= line && top > lastTop) { current = i; lastTop = top; }
    });
    // At the very bottom, the last section counts as current
    if (window.scrollY > 0 && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
      for (let i = targets.length - 1; i >= 0; i--) if (targets[i] && targets[i].offsetParent) { current = i; break; }
    }
    links.forEach((a, i) => a.classList.toggle("active", i === current));
  }
  let ticking = false;
  window.addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { spy(); ticking = false; }); } }, { passive: true });
  window.addEventListener("resize", spy);
  // Panels fill in after the data arrives, which moves everything: re-check then too
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => spy());
    ro.observe(document.body);
    for (const t of targets) if (t) ro.observe(t);
  }
  setTimeout(spy, 0);

  // Next scheduled scrape, in local time
  function nextRun() {
    const now = new Date();
    const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 20, 0));
    if (next <= now) next.setUTCDate(next.getUTCDate() + 1);
    const mins = Math.round((next - now) / 60000);
    const at = next.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    document.getElementById("side-next").textContent =
      `${at} · in ${mins >= 60 ? Math.floor(mins / 60) + "h " : ""}${mins % 60}m`;
  }
  nextRun();
  setInterval(nextRun, 60000);
})();
