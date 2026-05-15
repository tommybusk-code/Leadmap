// leads-table.js — Leads-fanen: lasting, filtre, tabell, sortering.
// Krever: core.js

let leadSort = {key: "score", dir: "desc"};

const LEAD_PAGE_SIZE_LS = "leadmap-leads-page-size";
const LEAD_PAGE_SIZES = [25, 50, 100, 200, 500];
function normLeadPageSize(v) {
  const n = parseInt(v, 10);
  return LEAD_PAGE_SIZES.includes(n) ? n : 50;
}
let leadPage = 1;
let leadPageSize = normLeadPageSize(typeof localStorage !== "undefined" ? localStorage.getItem(LEAD_PAGE_SIZE_LS) : null);

/** Statuser som vises når «Vunnet»-fanen er aktiv (samme som promote / status.json). */
const VUNNET_LIKE_STATUSES = new Set(["vunnet", "eksisterende_kunde", "datterselskap", "konsern_kunde"]);

/** Slå status → hvilken fanes telle-bøtte (fanene viser bare et delsett av STATUS_LABELS). */
function statusCountBucket(st) {
  const s = String(st == null || st === "" ? "new" : st).trim();
  if (VUNNET_LIKE_STATUSES.has(s)) return "vunnet";
  if (["new", "follow_up", "kontaktet", "ikke_aktuell"].includes(s)) return s;
  return "new";
}

/** Faner uten egen knapp for datter/eks.kunde/konsern — disse følger «Vunnet»-filteret. */
function statusMatchesTabs(st, tabs) {
  const s = st || "new";
  if (tabs.has(s)) return true;
  if (VUNNET_LIKE_STATUSES.has(s) && tabs.has("vunnet")) return true;
  return false;
}

async function refreshLeadsSilently() {
  const data = await fetchJSON("/api/leads");
  allLeads = Array.isArray(data.leads) ? data.leads : [];
  applyLeadsApiThresholds(data);
  _repaintLeadsUi();
}

function _repaintLeadsUi() {
  try {
    populateFilters();
  } catch (e) {
    console.error("populateFilters:", e);
  }
  renderTabs();
  render();
  /* Tidligere: ekstra requestAnimationFrame som kjørte populateFilters+render igjen —
     dobbelt DOM- og filterarbeid ved hver refresh (inkl. silent poll). Én pass holder. */
}

async function loadLeads() {
  leadPage = 1;
  try {
    await refreshLeadsSilently();
  } catch (e) {
    console.error("loadLeads:", e);
    allLeads = [];
    try {
      populateFilters();
    } catch (e2) { /* MS kanskje ikke klar */ }
    renderTabs();
    render();
  }
}

async function loadStats() {
  const s = await fetchJSON("/api/stats");
  $("stats").innerHTML = `
    <span>Leads <b>${s.total_leads}</b></span>
    <span>Kunder <b>${s.enriched_customers}/${s.total_customers}</b></span>
    <span>Sist kjørt <b>${s.last_run ? s.last_run.ran_at.replace('T',' ') : '—'}</b></span>
  `;
  const emptyBanner = $("setup-banner-empty");
  if (emptyBanner) emptyBanner.hidden = (s.total_customers || 0) > 0;
}

function renderTabs() {
  const counts = {};
  const order = ["new", "follow_up", "kontaktet", "vunnet", "ikke_aktuell"];
  (allLeads || []).forEach(l => {
    const b = statusCountBucket(l.status);
    counts[b] = (counts[b] || 0) + 1;
  });
  const html = order.map(st => {
    const n = counts[st] || 0;
    const active = activeStatusTabs.has(st);
    return `<button class="${active ? 'active' : ''}" data-status="${st}">${STATUS_LABELS[st]} (${n})</button>`;
  }).join("");
  $("status-tabs").innerHTML = html;
  document.querySelectorAll("#status-tabs button").forEach(b => {
    b.addEventListener("click", () => {
      const st = b.dataset.status;
      if (activeStatusTabs.has(st)) activeStatusTabs.delete(st);
      else activeStatusTabs.add(st);
      leadPage = 1;
      renderTabs();
      render();
    });
  });
}

/** Samme filter + sortering som tabellen (alle treff, ikke bare gjeldende side). */
function getFilteredSortedLeads() {
  if (typeof MS === "undefined" || !MS.signal || !MS.fylke || !MS.kommune || !MS.anker) return [];
  const search = $("f-search").value.toLowerCase().trim();
  const sigSel = new Set(MS.signal.getSelected());
  const fylkeSel = new Set(MS.fylke.getSelected());
  const kommSel = new Set(MS.kommune.getSelected());
  const ankSel = new Set(MS.anker.getSelected());
  const minScore = parseInt($("f-minscore").value || "0");

  const wantCombo = sigSel.has("_bonus_combo");
  const wantMulti = sigSel.has("_bonus_multi");
  const wantGeoMeter = sigSel.has("_geo_luftlinje");
  const realSigs = new Set([...sigSel].filter(s => !s.startsWith("_bonus_") && s !== "_geo_luftlinje"));

  const filtered = (allLeads || []).filter(l => {
    const st = l.status || "new";
    if (activeStatusTabs.size > 0 && !statusMatchesTabs(st, activeStatusTabs)) return false;
    const navnL = (l.navn || "").toLowerCase();
    const orgS = String(l.orgnr || "");
    if (search && !(navnL.includes(search) || orgS.includes(search))) return false;
    if (realSigs.size && !(l.signals || []).some(s => realSigs.has(s.type))) return false;
    if (wantCombo || wantMulti) {
      const b = l.score_breakdown || {};
      const hasCombo = !!b.combo_bonus;
      const hasMulti = !!b.multi_anchor_bonus;
      if (wantCombo && wantMulti) {
        if (!hasCombo && !hasMulti) return false;
      } else if (wantCombo && !hasCombo) return false;
      else if (wantMulti && !hasMulti) return false;
    }
    if (wantGeoMeter) {
      if (typeof minGeoDistanceMetersOnLead !== "function" || minGeoDistanceMetersOnLead(l) == null) return false;
    }
    if (fylkeSel.size) {
      const f = fylkeFor(l.kommunenummer);
      if (!f || !fylkeSel.has(f)) return false;
    }
    if (kommSel.size && !kommSel.has(l.kommune)) return false;
    if (ankSel.size && !(l.anker_navn || []).some(n => ankSel.has(n))) return false;
    if (minScore > 0) {
      const sc = Number(l.score);
      if (Number.isFinite(sc) && sc < minScore) return false;
    }
    return true;
  });

  const dir = leadSort.dir === "asc" ? 1 : -1;
  filtered.sort((a, b) => {
    let va, vb;
    switch (leadSort.key) {
      case "score": va = a.score || 0; vb = b.score || 0; break;
      case "geoscore":
        va = geoscoreSortMetric(a, ankSel);
        vb = geoscoreSortMetric(b, ankSel);
        break;
      case "navn": va = (a.navn || "").toLowerCase(); vb = (b.navn || "").toLowerCase(); break;
      case "anker": va = (a.anker_navn || [])[0] || ""; vb = (b.anker_navn || [])[0] || ""; break;
      case "ansatte": va = a.antallAnsatte || 0; vb = b.antallAnsatte || 0; break;
      case "kommune": va = (a.kommune || "").toLowerCase(); vb = (b.kommune || "").toLowerCase(); break;
      case "status": va = a.status || "new"; vb = b.status || "new"; break;
      default: va = a.score || 0; vb = b.score || 0;
    }
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    if (leadSort.key === "geoscore") {
      const s = (b.score || 0) - (a.score || 0);
      if (s) return s;
      return (a.navn || "").localeCompare(b.navn || "", "nb");
    }
    return 0;
  });
  return filtered;
}

function populateFilters() {
  if (typeof MS === "undefined" || !MS.signal || !MS.fylke || !MS.kommune || !MS.anker) return;
  const leads = allLeads || [];
  const sigCount = {};
  leads.forEach(l => (l.signals || []).forEach(s => { sigCount[s.type] = (sigCount[s.type] || 0) + 1; }));
  let nCombo = 0, nMulti = 0, nGeoMeter = 0;
  leads.forEach(l => {
    const b = l.score_breakdown || {};
    if (b.combo_bonus) nCombo++;
    if (b.multi_anchor_bonus) nMulti++;
    if (typeof minGeoDistanceMetersOnLead === "function" && minGeoDistanceMetersOnLead(l) != null) nGeoMeter++;
  });
  const sigOpts = [...Object.keys(sigCount)].sort()
    .map(t => ({value: t, label: SIGNAL_LABELS[t] || t, count: sigCount[t]}));
  sigOpts.push({value: "_bonus_combo", label: "Kryss: bransje + geo (samme anker)", count: nCombo});
  sigOpts.push({value: "_bonus_multi", label: "✨ Multi-anker-bonus (2+ ankere)", count: nMulti});
  sigOpts.push({value: "_geo_luftlinje", label: "Geo: luftlinje (meter fra anker)", count: nGeoMeter});
  MS.signal.setOptions(sigOpts);

  const fylkeCount = {};
  leads.forEach(l => {
    const f = fylkeFor(l.kommunenummer);
    if (f) fylkeCount[f] = (fylkeCount[f] || 0) + 1;
  });
  MS.fylke.setOptions([...Object.keys(fylkeCount)].sort()
    .map(f => ({value: f, label: f, count: fylkeCount[f]})));

  const fylkeSel = new Set(MS.fylke.getSelected());
  const kommCount = {};
  leads.forEach(l => {
    const f = fylkeFor(l.kommunenummer);
    if (fylkeSel.size && (!f || !fylkeSel.has(f))) return;
    if (l.kommune) kommCount[l.kommune] = (kommCount[l.kommune] || 0) + 1;
  });
  MS.kommune.setOptions([...Object.keys(kommCount)].sort()
    .map(k => ({value: k, label: k, count: kommCount[k]})));

  const ankerCount = {};
  leads.forEach(l => (l.anker_navn || []).forEach(n => { ankerCount[n] = (ankerCount[n] || 0) + 1; }));
  MS.anker.setOptions(Object.keys(ankerCount).sort((a, b) => ankerCount[b] - ankerCount[a])
    .map(a => ({value: a, label: a, count: ankerCount[a]})));
}

function render() {
  const filtered = getFilteredSortedLeads();

  const totalFiltered = filtered.length;
  const size = leadPageSize;
  const totalPages = Math.max(1, Math.ceil(totalFiltered / size) || 1);
  if (leadPage > totalPages) leadPage = totalPages;
  if (leadPage < 1) leadPage = 1;
  const start = (leadPage - 1) * size;
  const pageRows = totalFiltered ? filtered.slice(start, start + size) : [];

  $("leads-tbody").innerHTML = pageRows.map((l, i) => row(l, start + i + 1)).join("");
  const nAll = (allLeads || []).length;
  $("counter").textContent = `${totalFiltered} av ${nAll}`;

  const pager = $("leads-pager");
  if (pager) {
    pager.hidden = false;
    const info = $("leads-page-info");
    if (info) {
      info.textContent = totalFiltered
        ? `Viser ${start + 1}–${start + pageRows.length} · side ${leadPage} av ${totalPages}`
        : "Ingen treff";
    }
    const prev = $("leads-prev");
    const next = $("leads-next");
    if (prev) prev.disabled = leadPage <= 1 || totalFiltered === 0;
    if (next) next.disabled = leadPage >= totalPages || totalFiltered === 0;
  }

  document.querySelectorAll("#leads-table th.sortable").forEach(th => {
    const k = th.dataset.sort;
    th.classList.toggle("sorted", k === leadSort.key);
    th.classList.toggle("sort-asc", k === leadSort.key && leadSort.dir === "asc");
    th.classList.toggle("sort-desc", k === leadSort.key && leadSort.dir === "desc");
  });

  document.querySelectorAll(".status-select").forEach(s => {
    s.addEventListener("change", e => {
      e.stopPropagation();
      updateStatus(e.target.dataset.orgnr, e.target.value);
    });
    s.addEventListener("click", e => e.stopPropagation());
  });
  document.querySelectorAll(".actions-cell button").forEach(b => b.addEventListener("click", e => e.stopPropagation()));
  document.querySelectorAll("#leads-tbody tr").forEach(tr => {
    tr.addEventListener("click", () => openDetail(tr.dataset.orgnr));
  });

  const preset = $("f-sort-preset");
  if (preset && typeof preset.matches === "function" && !preset.matches(":focus")) {
    const cur = `${leadSort.key}:${leadSort.dir}`;
    const ok = [...preset.options].some(o => o.value === cur);
    if (ok) preset.value = cur;
  }
}

function row(l, rank) {
  const sc = l.score >= 50 ? "score-high" : l.score >= 25 ? "score-mid" : "score-low";
  const status = l.status || "new";

  const sigInner = buildLeadSignalPillsHtml(l, { compact: true });

  const sa = strongestAnchor(l);
  const ankNamesAll = l.anker_navn || [];
  let ankerCell;
  if (!sa) ankerCell = `<div class="anker-cell">—</div>`;
  else if (sa.total === 1) ankerCell = `<div class="anker-cell"><span class="anker-name">${esc(sa.strongest)}</span></div>`;
  else ankerCell = `<div class="anker-cell"><span class="anker-name">${esc(sa.strongest)}</span><small class="anker-more">+${sa.total - 1}</small></div>`;
  const parentBadge = l.parent_lead_navn ? `<small style="color:var(--primary);font-size:10px">↳ del av ${esc(l.parent_lead_navn)}</small>` : '';

  return `<tr class="s-${status}" data-orgnr="${l.orgnr}">
    <td>${rank}</td>
    <td><span class="score-cell ${sc}">${l.score}</span></td>
    <td><b>${esc(l.navn)}</b>${parentBadge ? '<br>' + parentBadge : ''}<br><small class="small-muted" title="${esc(l.naeringskode1 || '')} – ${esc(l.nace_beskr || '')}">${l.orgnr} · ${esc(naceLabel(l.naeringskode1))}</small></td>
    <td class="wrap"><div class="sig-list sig-list--table sig-list--like-table">${sigInner}</div></td>
    <td title="${esc(ankNamesAll.join(', '))}">${ankerCell}</td>
    <td>${l.antallAnsatte || 0}</td>
    <td>${esc(l.kommune || "")}</td>
    <td>
      <select class="status-select" data-orgnr="${l.orgnr}">
        ${Object.entries(STATUS_LABELS).map(([v, lbl]) =>
          `<option value="${v}"${status===v?' selected':''}>${lbl}</option>`
        ).join('')}
      </select>
    </td>
    <td class="actions-cell">
      <button class="small" onclick="openLink('/api/leads/${l.orgnr}/website')" title="Hjemmeside">🌐</button>
      <button class="small" onclick="openLink('/api/leads/${l.orgnr}/proff')" title="Proff.no">P</button>
      <button class="small" onclick="openLinkedIn('${l.orgnr}', '${esc(l.navn)}')" title="LinkedIn">in</button>
      <button class="small" onclick="fetchProffData('${l.orgnr}', '${esc(l.navn)}')" title="Hent styre+nøkkeltall">📊</button>
      <button class="small" onclick="openLinkParent('${l.orgnr}', '${esc(l.navn)}')" title="Knytt til hovedselskap (lead-til-lead)">🔗</button>
    </td>
  </tr>`;
}

let _leadsFilterRenderTimer = null;
function _scheduleLeadsFilterRender() {
  leadPage = 1;
  if (_leadsFilterRenderTimer) clearTimeout(_leadsFilterRenderTimer);
  _leadsFilterRenderTimer = setTimeout(() => {
    _leadsFilterRenderTimer = null;
    render();
  }, 140);
}

["f-search", "f-minscore"].forEach(id => {
  $(id).addEventListener("input", _scheduleLeadsFilterRender);
  $(id).addEventListener("change", () => {
    leadPage = 1;
    if (_leadsFilterRenderTimer) {
      clearTimeout(_leadsFilterRenderTimer);
      _leadsFilterRenderTimer = null;
    }
    render();
  });
});

$("btn-reset-filters").addEventListener("click", () => {
  $("f-search").value = "";
  $("f-minscore").value = "0";
  ["signal", "fylke", "kommune", "anker"].forEach(k => {
    if (MS[k]) {
      MS[k].selected.clear();
      MS[k]._renderButton();
      MS[k]._renderDropdown();
    }
  });
  const preset = $("f-sort-preset");
  if (preset) preset.value = "";
  activeStatusTabs = new Set(["new", "follow_up", "kontaktet", "vunnet"]);
  leadPage = 1;
  populateFilters();
  renderTabs();
  render();
});

const _leadsTable = $("leads-table");
if (_leadsTable) {
  _leadsTable.addEventListener("click", (e) => {
    const th = e.target.closest("th.sortable");
    if (!th || !_leadsTable.contains(th)) return;
    const k = th.dataset.sort;
    if (leadSort.key === k) {
      leadSort.dir = leadSort.dir === "asc" ? "desc" : "asc";
    } else {
      leadSort.key = k;
      leadSort.dir = ["score", "ansatte"].includes(k) ? "desc" : "asc";
    }
    const preset = $("f-sort-preset");
    if (preset) preset.value = "";
    render();
  });
}

(function initLeadSortPreset() {
  const preset = $("f-sort-preset");
  if (!preset || preset.dataset.wired === "1") return;
  preset.dataset.wired = "1";
  preset.addEventListener("change", () => {
    const v = (preset.value || "").trim();
    if (!v) return;
    const parts = v.split(":");
    if (parts.length !== 2) return;
    leadSort = {key: parts[0], dir: parts[1]};
    render();
  });
})();

(function initLeadsPagerDom() {
  const sz = $("leads-page-size");
  if (!sz || sz.dataset.wired === "1") return;
  sz.dataset.wired = "1";
  sz.value = String(leadPageSize);
  sz.addEventListener("change", () => {
    leadPageSize = normLeadPageSize(sz.value);
    try { localStorage.setItem(LEAD_PAGE_SIZE_LS, String(leadPageSize)); } catch (e) {}
    leadPage = 1;
    render();
  });
  const prev = $("leads-prev");
  const next = $("leads-next");
  if (prev) prev.addEventListener("click", () => { if (leadPage > 1) { leadPage--; render(); } });
  if (next) next.addEventListener("click", () => { leadPage++; render(); });
})();

/**
 * Tvinger thead + colgroup i synk med row() (9 kolonner). Unngår feil kolonneinndeling
 * når nettleseren har mellomlagret gammelt index.html (f.eks. ekstra Geoscore-kolonne).
 */
function syncLeadsTableChrome() {
  const table = document.getElementById("leads-table");
  if (!table || table.dataset.colsSynced === "1") return;
  table.dataset.colsSynced = "1";
  const cg = table.querySelector("colgroup");
  if (cg) {
    cg.innerHTML = `
    <col style="width:60px">
    <col style="width:76px">
    <col style="width:280px">
    <col>
    <col style="width:150px">
    <col style="width:64px">
    <col style="width:110px">
    <col style="width:120px">
    <col style="width:190px">`;
  }
  const tr = table.querySelector("thead tr");
  if (tr) {
    tr.innerHTML = `
      <th>#</th>
      <th class="sortable" data-sort="score">Score</th>
      <th class="sortable" data-sort="navn">Selskap</th>
      <th>Signaler</th>
      <th class="sortable" data-sort="anker">Anker</th>
      <th class="sortable" data-sort="ansatte">Ans.</th>
      <th class="sortable" data-sort="kommune">Kommune</th>
      <th class="sortable" data-sort="status">Status</th>
      <th>Handlinger</th>`;
  }
}

syncLeadsTableChrome();

(function initLeadsExportXlsx() {
  const btn = $("btn-export-leads-xlsx");
  if (!btn || btn.dataset.wired === "1") return;
  btn.dataset.wired = "1";
  btn.addEventListener("click", async () => {
    if (typeof MS === "undefined" || !MS.signal) {
      alert("Filtre er ikke klare ennå — vent til leads er lastet.");
      return;
    }
    const filtered = getFilteredSortedLeads();
    if (!filtered.length) {
      alert("Ingen leads i gjeldende filter.");
      return;
    }
    const warnAt = 12000;
    if (filtered.length > warnAt) {
      if (!confirm(
        `Du eksporterer ${filtered.length} rader. Det kan ta litt tid og bli en stor fil. Fortsette?`,
      )) return;
    }
    const leads = filtered.map((l, i) => ({ ...l, rank_i_eksport: i + 1 }));
    try {
      const r = await fetch("/api/leads/export-filtered", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ leads }),
      });
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (j && j.error) msg = j.error;
        } catch (e) { /* */ }
        throw new Error(msg);
      }
      const blob = await r.blob();
      const dispo = r.headers.get("Content-Disposition") || "";
      let fn = `leadmap-filter-${new Date().toISOString().slice(0, 16).replace("T", "-").replace(/:/g, "")}.xlsx`;
      const m = /filename\*=UTF-8''([^;]+)|filename="([^"]+)"/i.exec(dispo);
      if (m) fn = decodeURIComponent((m[1] || m[2] || fn).trim());
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = fn;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (ex) {
      alert("Eksport feilet: " + (ex && ex.message ? ex.message : ex));
    }
  });

  // Eksponér filtrerte leads for kart-visning
  window.getLeadsForMap = () => getFilteredSortedLeads();
})();
