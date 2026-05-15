// =====================================================================
// progress.js — Felles progress-modal for analyse, import og refresh-all.
// Brukes av leads.js (pollAnalysis), features.js (analyze + import + refresh-all),
// og settings.js. Krever core.js for $/closeModal/fetchJSON.
// =====================================================================

// Aktiv jobb-state — overlever lukking av modal, polling fortsetter.
let activeJob = null;

function showProgress(title, statusUrl, withBar = false) {
  activeJob = {
    title, statusUrl, withBar, current: 0, total: 0, progress: "Starter...",
    running: true, log: [], secondaryLine: null,
  };
  $("progress-title").textContent = "⏳ " + title;
  $("progress-current").textContent = "Starter...";
  $("progress-log").textContent = "";
  $("progress-spinner").style.display = withBar ? "none" : "";
  $("progress-bar-wrap").hidden = !withBar;
  $("progress-bar").style.width = "0%";
  $("progress-bar").textContent = "";
  $("btn-progress-close").hidden = true;
  $("btn-progress-minimize").hidden = false;
  $("modal-progress").hidden = false;
  updateHeaderBadge();
}

function renderProgressModal() {
  if (!activeJob || $("modal-progress").hidden) return;
  const hintEl = $("progress-jobs-hint");
  if (hintEl) {
    if (activeJob.secondaryLine) {
      hintEl.textContent = activeJob.secondaryLine;
      hintEl.hidden = false;
    } else {
      hintEl.textContent = "";
      hintEl.hidden = true;
    }
  }
  if (activeJob.log && activeJob.log.length) {
    const log = $("progress-log");
    log.textContent = activeJob.log.map(e => `${e.t.slice(11)}  ${e.msg}`).join("\n");
    log.parentElement.scrollTop = log.parentElement.scrollHeight;
  }
  if (!activeJob.running) {
    $("progress-spinner").style.display = "none";
    $("progress-bar").style.width = "100%";
    $("progress-bar").textContent = "";
    $("progress-current").textContent = "✅ Ferdig";
    $("btn-progress-close").hidden = false;
    $("btn-progress-minimize").hidden = true;
    return;
  }
  if (activeJob.total > 0) {
    const pct = Math.min(100, Math.round((activeJob.current / activeJob.total) * 100));
    $("progress-bar-wrap").hidden = false;
    $("progress-bar").style.width = pct + "%";
    $("progress-bar").textContent = "";
    $("progress-current").textContent =
      `${activeJob.progress || "…"} — ${activeJob.current} / ${activeJob.total} (${pct}%)`;
    $("progress-spinner").style.display = "none";
  } else {
    $("progress-current").textContent = activeJob.progress || "...";
  }
}

function updateHeaderBadge() {
  const el = $("run-status");
  if (!activeJob) { el.textContent = ""; el.onclick = null; el.style.cursor = ""; return; }
  if (!activeJob.running) {
    el.textContent = `✅ ${activeJob.title} ferdig`;
    el.onclick = null; el.style.cursor = "";
    setTimeout(() => { if (activeJob && !activeJob.running) { activeJob = null; updateHeaderBadge(); } }, 5000);
    return;
  }
  if (activeJob.total > 0) {
    const pct = Math.min(100, Math.round((activeJob.current / activeJob.total) * 100));
    el.textContent = `⏳ ${activeJob.title}: ${activeJob.current}/${activeJob.total} (${pct}%)`;
  } else {
    el.textContent = `⏳ ${activeJob.title}: ${activeJob.progress || ""}`.slice(0, 100);
  }
  el.style.cursor = "pointer";
  el.onclick = () => { $("modal-progress").hidden = false; renderProgressModal(); };
}

function pollProgress(onDone) {
  if (!activeJob) return;
  const tick = async () => {
    if (!activeJob) return;
    let s;
    try { s = await fetchJSON(activeJob.statusUrl); }
    catch (e) { setTimeout(tick, 2000); return; }
    activeJob.progress = s.progress;
    activeJob.current = s.current || 0;
    activeJob.total = s.total || 0;
    activeJob.running = s.running;
    activeJob.log = s.log_tail || [];
    /* concurrent_hint endrer seg sjelden — unngå ekstra GET hvert poll-tick (1s). */
    const now = Date.now();
    const lastOv = activeJob._lastJobsOverviewAt || 0;
    if (now - lastOv >= 5000) {
      activeJob._lastJobsOverviewAt = now;
      try {
        const jo = await fetchJSON("/api/jobs/overview");
        if (activeJob && jo) {
          activeJob.secondaryLine = jo.concurrent_hint || null;
        }
      } catch (e2) { /* oversikt valgfri */ }
    }
    renderProgressModal();
    updateHeaderBadge();
    if (s.running) {
      if (activeJob.statusUrl && activeJob.statusUrl.includes("/api/analyze") && typeof refreshLeadsSilently === "function") {
        const now = Date.now();
        if (!window._leadSilentPollTs) window._leadSilentPollTs = 0;
        const vl = $("view-leads");
        if (now - window._leadSilentPollTs > 4500 && vl && !vl.hidden) {
          window._leadSilentPollTs = now;
          void refreshLeadsSilently().catch(() => {});
        }
      }
      setTimeout(tick, 1000);
    } else if (onDone) await onDone();
  };
  tick();
}

$("btn-progress-minimize").addEventListener("click", () => { $("modal-progress").hidden = true; });
$("btn-progress-close").addEventListener("click", () => closeModal("modal-progress"));

async function pollAnalysis() {
  showProgress("Kjører analyse", "/api/analyze/status", true);
  pollProgress(async () => {
    await loadLeads();
    await loadStats();
  });
}

/** Geo + score (Kartverket) — bruker samme status-endepunkt som analyse. */
async function pollGeoRescore() {
  showProgress("Geo + score", "/api/analyze/status", true);
  pollProgress(async () => {
    await loadLeads();
    await loadStats();
  });
}

// === Sjekk om en jobb kjører på serveren (etter side-reload) ===
async function checkExistingJobs() {
  try {
    const o = await fetchJSON("/api/jobs/overview");
    if (o.analysis.running) {
      const title = o.analysis.job === "geo" ? "Geo + score" : "Kjører analyse";
      showProgress(title, "/api/analyze/status", true);
      activeJob.secondaryLine = o.concurrent_hint || null;
      $("modal-progress").hidden = true;
      pollProgress(async () => { await loadLeads(); await loadStats(); });
      return;
    }
    if (o.customer_sync.running) {
      let title = "Bakgrunnsjobb (kunder)";
      if (o.customer_sync.job === "refresh_related") title = "Oppdater alle relaterte";
      else if (o.customer_sync.job === "aksjonaerinfo") title = "Oppdater alle (aksjonærinfo)";
      else if (o.customer_sync.job === "promote_whole_owned") title = "Heleide leads → kundetrær";
      else if (o.customer_sync.job === "import") title = "Importerer kunder";
      showProgress(title, "/api/import/status", true);
      activeJob.secondaryLine = o.concurrent_hint || null;
      $("modal-progress").hidden = true;
      pollProgress(async () => {
        await loadCustomers();
        if (!$("view-customers").hidden) renderCustomersTab();
        await loadLeads();
        await loadStats();
      });
    }
  } catch (e) {}
}
