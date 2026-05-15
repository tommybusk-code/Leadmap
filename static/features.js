// =====================================================================
// features.js — Add customer + analyze-knapper + MS-init + init-kall.
// Krever: core, leads, customers, progress, settings, import.
// =====================================================================

(function initActionsPanel() {
  const SUPPORTS_HAS =
    typeof CSS !== "undefined" && CSS.supports && CSS.supports("selector(:has(*))");

  function readToggleSizePx() {
    const raw = getComputedStyle(document.documentElement)
      .getPropertyValue("--app-actions-toggle-size")
      .trim();
    const n = parseFloat(raw);
    return Number.isFinite(n) && n > 0 ? n : 32;
  }

  function syncToggleDock(panel, toggle) {
    if (!panel || !toggle) return;
    if (SUPPORTS_HAS) {
      toggle.style.removeProperty("left");
      return;
    }
    const open = !panel.classList.contains("is-collapsed");
    const tw = readToggleSizePx();
    const w = Math.min(232, Math.max(0, window.innerWidth - tw));
    toggle.style.left = open ? `${w}px` : "0px";
  }

  function wire() {
    const panel = document.getElementById("app-actions-panel");
    const toggle = document.getElementById("app-actions-toggle");
    if (!panel || !toggle || toggle.dataset.wired === "1") return;
    toggle.dataset.wired = "1";
    const LS_KEY = "leadmap-actions-panel-collapsed";
    function setCollapsed(collapsed) {
      panel.classList.toggle("is-collapsed", collapsed);
      const open = !collapsed;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.title = collapsed ? "Vis handlingspanel" : "Skjul handlingspanel";
      toggle.setAttribute("aria-label", collapsed ? "Vis handlingspanel" : "Skjul handlingspanel");
      try {
        localStorage.setItem(LS_KEY, collapsed ? "1" : "0");
      } catch (e) { /* private mode */ }
      syncToggleDock(panel, toggle);
    }
    toggle.addEventListener("click", () => setCollapsed(!panel.classList.contains("is-collapsed")));
    window.addEventListener("resize", () => syncToggleDock(panel, toggle));
    try {
      if (localStorage.getItem(LS_KEY) === "1") setCollapsed(true);
      else syncToggleDock(panel, toggle);
    } catch (e) {
      syncToggleDock(panel, toggle);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();

// === Add customer ===
$("btn-add").addEventListener("click", () => {
  $("add-result").textContent = "";
  $("add-query").value = "";
  $("add-abonnementer").value = "";
  $("add-suggestions").innerHTML = "";
  $("add-suggestions").hidden = true;
  delete $("add-query").dataset.orgnr;
  $("modal-add").hidden = false;
  setTimeout(() => $("add-query").focus(), 50);
});

let suggestTimer = null;
$("add-query").addEventListener("input", () => {
  clearTimeout(suggestTimer);
  const q = $("add-query").value.trim();
  if (q.length < 2 || /^\d+$/.test(q)) { $("add-suggestions").hidden = true; return; }
  suggestTimer = setTimeout(async () => {
    const data = await fetchJSON(`/api/search-brreg?q=${encodeURIComponent(q)}`);
    const sugg = $("add-suggestions");
    if (!data.results || !data.results.length) { sugg.hidden = true; return; }
    sugg.innerHTML = data.results.map(r =>
      `<div data-orgnr="${r.orgnr}" data-name="${esc(r.navn)}">
         <b>${esc(r.navn)}</b><small> · ${r.orgnr} · ${esc(r.kommune || '')} · ${r.ansatte || 0} ansatte</small>
       </div>`).join("");
    sugg.hidden = false;
    sugg.querySelectorAll("div").forEach(d => {
      d.onclick = () => {
        $("add-query").value = d.dataset.name;
        $("add-query").dataset.orgnr = d.dataset.orgnr;
        sugg.hidden = true;
      };
    });
  }, 250);
});

$("btn-add-confirm").addEventListener("click", async () => {
  const q = $("add-query").value.trim();
  const orgnr = $("add-query").dataset.orgnr;
  if (!q) return;
  const abo = parseInt($("add-abonnementer").value || "0");
  $("add-result").textContent = "Henter...";
  const body = orgnr ? {query: orgnr, abonnementer: abo} : {query: q, abonnementer: abo};
  const data = await fetchJSON("/api/customers/add", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  if (data.error) $("add-result").textContent = "❌ " + data.error;
  else if (data.added) {
    $("add-result").textContent = `✅ Lagt til: ${data.customer.navn}\nKjører målrettet analyse for denne kunden i bakgrunnen.`;
    if (data.targeted_analysis_queued && typeof pollAnalysis === "function") pollAnalysis();
    try {
      await loadCustomers();
    } catch (e) {
      console.error("loadCustomers:", e);
    }
    if (typeof populateFilters === "function") populateFilters();
    if (!$("view-customers").hidden) renderCustomersTab();
    loadStats();
    setTimeout(() => closeModal("modal-add"), 1500);
  } else if (data.already_exists) {
    $("add-result").textContent = `ℹ️ Allerede i listen: ${data.customer.navn}`;
    try {
      await loadCustomers();
    } catch (e) {
      console.error("loadCustomers:", e);
    }
    if (typeof populateFilters === "function") populateFilters();
    if (!$("view-customers").hidden) renderCustomersTab();
    loadStats();
    setTimeout(() => closeModal("modal-add"), 1200);
  }
  delete $("add-query").dataset.orgnr;
});

// === Analyze ===
$("btn-analyze").addEventListener("click", async () => {
  await fetchJSON("/api/analyze", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({full_rebuild: false, geo_only_new_leads: true}),
  });
  pollAnalysis();
});
$("btn-analyze-full").addEventListener("click", async () => {
  if (!confirm("Full re-analyse går igjennom alle kunder på nytt og tar noen minutter. Fortsette?")) return;
  await fetchJSON("/api/analyze", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({full_rebuild: true, geo_only_new_leads: false}),
  });
  pollAnalysis();
});

$("btn-analyze-no-geo").addEventListener("click", async () => {
  await fetchJSON("/api/analyze", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({full_rebuild: false, skip_geocode: true}),
  });
  pollAnalysis();
});

$("btn-geo-rescore").addEventListener("click", async () => {
  if (!confirm(
    "Henter koordinater fra Kartverket for kunder og leads med gateadresse, beregner luftlinje på nytt og oppdaterer score.\n\nIngen full lead-discovery — det gjør du med «Kjør analyse».\n\nFortsette?",
  )) return;
  const data = await fetchJSON("/api/geo-rescore", {method: "POST"});
  if (data.running && data.started === false) {
    alert("En analyse- eller geo-jobb kjører allerede. Vent til den er ferdig.");
    return;
  }
  pollGeoRescore();
});

// === Initialiser MultiSelect-instanser (krever render + populateFilters) ===
MS.signal = new MultiSelect("ms-signal-btn", "ms-signal-dropdown", {label: "signaler", searchable: true, onChange: () => { leadPage = 1; render(); }});
MS.fylke = new MultiSelect("ms-fylke-btn", "ms-fylke-dropdown", {label: "fylker", searchable: false, onChange: () => { leadPage = 1; populateFilters(); render(); }});
MS.kommune = new MultiSelect("ms-kommune-btn", "ms-kommune-dropdown", {label: "kommuner", searchable: true, onChange: () => { leadPage = 1; render(); }});
MS.anker = new MultiSelect("ms-anker-btn", "ms-anker-dropdown", {label: "ankere", searchable: true, onChange: () => { leadPage = 1; render(); }});

// === Init (await loadLeads slik at stats/leads ikke raser om den ene feiler) ===
(async () => {
  try {
    await loadStats();
  } catch (e) {
    console.error("loadStats:", e);
  }
  await loadLeads();
  checkExistingJobs();
})();
setInterval(loadStats, 30000);
