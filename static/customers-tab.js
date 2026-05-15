// =====================================================================
// customers-tab.js — Kunder-fanen: liste, sortering, bulk-handling, view-bytte.
// Krever: core.js. Bruker openCustomerDetailModal (definert i customers-modal.js).
// =====================================================================

// === Main tabs (Leads / Kunder) ===
document.querySelectorAll(".main-tab").forEach(b => {
  b.addEventListener("click", () => switchView(b.dataset.view));
});

async function switchView(view) {
  document.querySelectorAll(".main-tab").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $("view-leads").hidden = view !== "leads";
  $("view-customers").hidden = view !== "customers";
  if (view === "map") { if (window.MapView) MapView.show(); }
  else { if (window.MapView) MapView.hide(); }
  if (view === "customers") {
    selectedCustomers.clear();
    await loadCustomers();
    renderCustomersTab();
  } else if (view === "leads") {
    populateFilters();
    renderTabs();
    render();
  }
}

function toggleExpand(orgnr) {
  const k = normCustOrgnr(orgnr);
  if (!k) return;
  if (expandedCustomers.has(k)) expandedCustomers.delete(k);
  else expandedCustomers.add(k);
  renderCustomersTab();
}

async function loadCustomers() {
  const data = await fetchJSON("/api/customers");
  allCustomers = data.customers;
}

/** Normaliser org.nr (Brreg/JSON kan gi tall eller streng med mellomrom). */
function normCustOrgnr(o) {
  return normOrgnr(o);
}

// === Sortering (state + helper) ===
let custSort = {key: "abonnementer", dir: "desc"};

const CUST_PAGE_SIZE_LS = "leadmap-customers-page-size";
const CUST_PAGE_SIZES = [25, 50, 100, 200, 500];
function normCustPageSize(v) {
  const n = parseInt(v, 10);
  return CUST_PAGE_SIZES.includes(n) ? n : 50;
}
let custPage = 1;
let custPageSize = normCustPageSize(typeof localStorage !== "undefined" ? localStorage.getItem(CUST_PAGE_SIZE_LS) : null);
let _custSearchSnap = "\u0000";

function _sortValue(c, key, fallbackEff) {
  switch (key) {
    case "navn": return (c.navn || "").toLowerCase();
    case "orgnr": return c.orgnr || "";
    case "kommune": return (c.kommune || "").toLowerCase();
    case "bransje": return (c.naeringskode1 || "") + (c.nace_beskr || "");
    case "ansatte": return fallbackEff != null ? fallbackEff : (c.antallAnsatte || 0);
    case "abonnementer": return c.abonnementer || 0;
    case "enriched": return c.enriched ? 1 : 0;
    default: return 0;
  }
}

function _computeEffAnsatte(p) {
  if (p.antallAnsatte_override && p.antallAnsatte_override > 0) return p.antallAnsatte_override;
  const direct = p.antallAnsatte || 0;
  const konsernA = p.related?.konsern_ansatte || 0;
  if (konsernA > direct) return konsernA;
  const seen = new Set(p.orgnr ? [p.orgnr] : []);

  function sumManualTree(items) {
    let s = 0;
    (items || []).forEach(r => {
      const ron = r.orgnr;
      if (ron && seen.has(ron)) return;
      if (ron) seen.add(ron);
      s += r.antallAnsatte || 0;
      (r.related?.underenheter || []).forEach(ue => {
        const uon = ue.orgnr;
        if (uon && seen.has(uon)) return;
        if (uon) seen.add(uon);
        s += ue.antallAnsatte || 0;
        s += sumManualTree(ue.manual_subsidiaries);
      });
      s += sumManualTree(r.manual_subsidiaries);
    });
    return s;
  }

  let relSum = 0;
  (p.related?.underenheter || []).forEach(r => {
    const ron = r.orgnr;
    if (ron && seen.has(ron)) return;
    if (ron) seen.add(ron);
    relSum += r.antallAnsatte || 0;
    relSum += sumManualTree(r.manual_subsidiaries);
  });
  relSum += sumManualTree(p.related?.manual_subsidiaries);
  return relSum > 0 ? Math.max(direct, direct + relSum) : direct;
}

function flattenManualSubsidiaries(items, acc = []) {
  (items || []).forEach(m => {
    acc.push(m);
    flattenManualSubsidiaries(m.manual_subsidiaries, acc);
  });
  return acc;
}

/** Alle orgnr som allerede vises under manuelle datre (inkl. Brreg-barn) — for dedupe mot rot-avdelinger. */
function orgnrsUnderManualBranches(msList) {
  const s = new Set();
  function walkM(m) {
    if (m.orgnr) s.add(normCustOrgnr(m.orgnr));
    (m.related?.underenheter || []).forEach(ue => {
      if (ue.orgnr) s.add(normCustOrgnr(ue.orgnr));
      (ue.manual_subsidiaries || []).forEach(walkM);
    });
    (m.manual_subsidiaries || []).forEach(walkM);
  }
  (msList || []).forEach(walkM);
  return s;
}

function countManualSubtreeDisplayNodes(m) {
  let n = 1;
  (m.related?.underenheter || []).forEach(ue => {
    n += 1;
    (ue.manual_subsidiaries || []).forEach(ch => { n += countManualSubtreeDisplayNodes(ch); });
  });
  (m.manual_subsidiaries || []).forEach(ch => { n += countManualSubtreeDisplayNodes(ch); });
  return n;
}

/** Antall utvidbare rader under én kundepost (avdelinger + manuelt tre), uten selve kunden. */
function countEmbeddedRelatedForCustomer(c) {
  if (!c) return 0;
  const ueL = c.related?.underenheter || [];
  const msL = c.related?.manual_subsidiaries || [];
  const underM = orgnrsUnderManualBranches(msL);
  const ueFilteredLen = ueL.filter(u => !underM.has(normCustOrgnr(u.orgnr))).length;
  const msBranch = (msL || []).reduce((acc, m) => acc + countManualSubtreeDisplayNodes(m), 0);
  return ueFilteredLen + msBranch;
}

/** Navn/orgnr-treff på selve kunderaden (topp eller datterselskap-rad). */
function customerRowMatches(c, qLower) {
  if (!qLower) return true;
  const navn = (c.navn || "").toLowerCase();
  if (navn.includes(qLower)) return true;
  const qn = qLower.replace(/\s/g, "");
  const orgS = normCustOrgnr(c.orgnr).toLowerCase();
  return qn.length > 0 && orgS.includes(qn);
}

/** Brreg/manuelt tre på én kundepost (ikke underordnede kunderader). */
function relatedOwnTreMatchesCustomer(cust, qLower) {
  if (!qLower || !cust) return false;
  const hit = v => String(v || "").toLowerCase().includes(qLower);
  for (const ue of cust.related?.underenheter || []) {
    if (hit(ue.navn) || hit(ue.orgnr)) return true;
  }
  for (const m of cust.related?.manual_subsidiaries || []) {
    if (hit(m.navn) || hit(m.orgnr)) return true;
    for (const ue of m.related?.underenheter || []) {
      if (hit(ue.navn) || hit(ue.orgnr)) return true;
    }
    if (relatedManualDeep(m, hit)) return true;
  }
  return false;
}

/** Treff i tre under toppkunde: eget related + koblede datterselskap-kort og deres tre (rekursivt). */
function relatedSubtreeMatches(parentRecord, qLower) {
  if (!qLower || !parentRecord) return false;
  if (relatedOwnTreMatchesCustomer(parentRecord, qLower)) return true;
  const po = normCustOrgnr(parentRecord.orgnr);
  for (const ch of allCustomers || []) {
    if (normCustOrgnr(ch.parent_orgnr) !== po) continue;
    if (customerRowMatches(ch, qLower)) return true;
    if (relatedOwnTreMatchesCustomer(ch, qLower)) return true;
    if (relatedSubtreeMatches(ch, qLower)) return true;
  }
  return false;
}

function relatedManualDeep(m, hit) {
  return (m.manual_subsidiaries || []).some(ch =>
    hit(ch.navn) || hit(ch.orgnr) ||
    (ch.related?.underenheter || []).some(ue => hit(ue.navn) || hit(ue.orgnr)) ||
    relatedManualDeep(ch, hit)
  );
}

/** Innrykk i px (ingen kunstig grense på antall grener — dybde kappes kun visuelt). */
function customerTreeIndentPx(tier) {
  return Math.min(Math.max(tier, 0), 40) * 18;
}

/** Antall koblede kunderader + rot-manuelle + rot-UE (direkte under denne kunden). */
function customerExpandableChildCount(cust) {
  if (!cust || !cust.orgnr) return 0;
  const po = normCustOrgnr(cust.orgnr);
  const nSub = (allCustomers || []).filter(x => normCustOrgnr(x.parent_orgnr) === po).length;
  const ueL = cust.related?.underenheter || [];
  const msL = cust.related?.manual_subsidiaries || [];
  const underM = orgnrsUnderManualBranches(msL);
  const ueF = ueL.filter(u => !underM.has(u.orgnr)).length;
  return nSub + msL.length + ueF;
}

function manualNodeExpandableChildCount(m) {
  if (!m || !m.orgnr) return 0;
  const mo = normCustOrgnr(m.orgnr);
  const ue = (m.related?.underenheter || []).length;
  const ms = (m.manual_subsidiaries || []).length;
  const co = (allCustomers || []).filter(x => normCustOrgnr(x.parent_orgnr) === mo).length;
  return ue + ms + co;
}

function ueNodeExpandableChildCount(ue) {
  if (!ue || !ue.orgnr) return 0;
  const uo = normCustOrgnr(ue.orgnr);
  return (ue.manual_subsidiaries || []).length + (allCustomers || []).filter(x => normCustOrgnr(x.parent_orgnr) === uo).length;
}

function appendEmbeddedManualRowsForCustomer(cust, tier, rows) {
  const ueL = cust.related?.underenheter || [];
  const msL = cust.related?.manual_subsidiaries || [];
  const underM = orgnrsUnderManualBranches(msL);
  const ueF = ueL.filter(u => !underM.has(u.orgnr));
  (msL || []).forEach(m => appendManualSubtreeRows(m, tier, rows));
  ueF.forEach(ue => appendUeSubtreeRows(ue, tier, rows));
}

function appendManualSubtreeRows(m, tier, rows) {
  const hc = manualNodeExpandableChildCount(m);
  rows.push({
    ...m,
    _isChild: true,
    _kind: "manual_subsidiary",
    _subTier: tier,
    _indentPx: customerTreeIndentPx(tier),
    _treePadPx: 6 + customerTreeIndentPx(tier),
    _hasChildren: hc > 0,
    _childCount: hc,
    _expanded: expandedCustomers.has(normCustOrgnr(m.orgnr)),
  });
  if (!expandedCustomers.has(normCustOrgnr(m.orgnr))) return;
  (m.related?.underenheter || []).forEach(ue => appendUeSubtreeRows(ue, tier + 1, rows));
  (m.manual_subsidiaries || []).forEach(ms => appendManualSubtreeRows(ms, tier + 1, rows));
}

function appendUeSubtreeRows(ue, tier, rows) {
  const hc = ueNodeExpandableChildCount(ue);
  rows.push({
    ...ue,
    _isChild: true,
    _kind: "underenhet",
    _subTier: tier,
    _indentPx: customerTreeIndentPx(tier),
    _treePadPx: 6 + customerTreeIndentPx(tier),
    _hasChildren: hc > 0,
    _childCount: hc,
    _expanded: expandedCustomers.has(normCustOrgnr(ue.orgnr)),
  });
  if (!expandedCustomers.has(normCustOrgnr(ue.orgnr))) return;
  (ue.manual_subsidiaries || []).forEach(ms => appendManualSubtreeRows(ms, tier + 1, rows));
}

/** Rekursiv: kundekort-dattre, deretter hvert korts manuelle/Brreg-tre (egen +/- per orgnr). */
function appendCustomerChildrenRows(cust, tier, rows) {
  const kids = (allCustomers || []).filter(x => normCustOrgnr(x.parent_orgnr) === normCustOrgnr(cust.orgnr))
    .sort((a, b) => (a.navn || "").localeCompare(b.navn || "", "nb"));
  for (const ch of kids) {
    const hc = customerExpandableChildCount(ch);
    rows.push({
      ...ch,
      _isChild: true,
      _kind: "datterselskap",
      _subTier: tier,
      _indentPx: customerTreeIndentPx(tier),
      _treePadPx: 6 + customerTreeIndentPx(tier),
      _hasChildren: hc > 0,
      _childCount: hc,
      _expanded: expandedCustomers.has(normCustOrgnr(ch.orgnr)),
    });
    if (!expandedCustomers.has(normCustOrgnr(ch.orgnr))) continue;
    appendCustomerChildrenRows(ch, tier + 1, rows);
    appendEmbeddedManualRowsForCustomer(ch, tier + 1, rows);
  }
}

/** Finn toppkunde-orgnr for en datterselskap-rad (parent_orgnr-kjede). */
function datterselskapRootOrgnr(customerByOrgnr, c) {
  const seen = new Set();
  let cur = c;
  while (cur && normCustOrgnr(cur.parent_orgnr) && !seen.has(normCustOrgnr(cur.orgnr))) {
    seen.add(normCustOrgnr(cur.orgnr));
    cur = customerByOrgnr.get(normCustOrgnr(cur.parent_orgnr));
  }
  return cur && !normCustOrgnr(cur.parent_orgnr) ? cur.orgnr : null;
}

function renderCustomersTab() {
  const qRaw = ($("cust-search-tab").value || "").trim();
  const qLower = qRaw.toLowerCase();
  if (qLower !== _custSearchSnap) {
    custPage = 1;
    _custSearchSnap = qLower;
  }
  const customerByOrgnr = new Map(
    (allCustomers || []).filter(c => c.orgnr).map(c => [normCustOrgnr(c.orgnr), c])
  );

  let parents;
  /** Alle rader med parent_orgnr — alltid brukt under utvidet tre slik at datterselskap ikke skjules av søk. */
  const children = (allCustomers || []).filter(c => normCustOrgnr(c.parent_orgnr));

  if (!qLower) {
    parents = (allCustomers || []).filter(c => !normCustOrgnr(c.parent_orgnr));
  } else {
    const parentOrgnrsToShow = new Set();
    for (const c of allCustomers || []) {
      if (!customerRowMatches(c, qLower)) continue;
      if (!normCustOrgnr(c.parent_orgnr)) parentOrgnrsToShow.add(normCustOrgnr(c.orgnr));
      else {
        const root = datterselskapRootOrgnr(customerByOrgnr, c);
        if (root) parentOrgnrsToShow.add(normCustOrgnr(root));
      }
    }
    for (const c of allCustomers || []) {
      if (!normCustOrgnr(c.parent_orgnr) && relatedSubtreeMatches(c, qLower)) {
        parentOrgnrsToShow.add(normCustOrgnr(c.orgnr));
      }
    }
    parents = (allCustomers || []).filter(
      c => !normCustOrgnr(c.parent_orgnr) && parentOrgnrsToShow.has(normCustOrgnr(c.orgnr))
    );
  }

  const effByOrgnr = {};
  parents.forEach(p => { effByOrgnr[normCustOrgnr(p.orgnr)] = _computeEffAnsatte(p); });

  // Sortér parents
  const dir = custSort.dir === "asc" ? 1 : -1;
  parents.sort((a, b) => {
    const va = _sortValue(a, custSort.key, effByOrgnr[normCustOrgnr(a.orgnr)]);
    const vb = _sortValue(b, custSort.key, effByOrgnr[normCustOrgnr(b.orgnr)]);
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return 0;
  });

  const totalParents = parents.length;
  const pSize = custPageSize;
  const totalPages = Math.max(1, Math.ceil(totalParents / pSize) || 1);
  if (custPage > totalPages) custPage = totalPages;
  if (custPage < 1) custPage = 1;
  const pOff = (custPage - 1) * pSize;
  const parentsPage = parents.slice(pOff, pOff + pSize);

  // Bygg rader (parent + barn hvis utvidet) — kun for foreldre på denne siden
  const rows = [];
  parentsPage.forEach(p => {
    const ueList = p.related?.underenheter || [];
    const msList = p.related?.manual_subsidiaries || [];
    const childList = children.filter(c => normCustOrgnr(c.parent_orgnr) === normCustOrgnr(p.orgnr));
    const underManual = new Set(orgnrsUnderManualBranches(msList));
    childList.forEach(ch => {
      orgnrsUnderManualBranches(ch.related?.manual_subsidiaries).forEach(o => underManual.add(o));
    });
    const ueFiltered = ueList.filter(ue => !underManual.has(normCustOrgnr(ue.orgnr)));
    const manualBranchCount = (msList || []).reduce(
      (acc, m) => acc + countManualSubtreeDisplayNodes(m), 0
    );
    const embeddedUnderChildren = childList.reduce(
      (acc, ch) => acc + countEmbeddedRelatedForCustomer(ch), 0
    );
    const totalChildren = ueFiltered.length + manualBranchCount + childList.length + embeddedUnderChildren;
    rows.push({
      ...p,
      _effAnsatte: effByOrgnr[normCustOrgnr(p.orgnr)],
      _isTopCustomer: true,
      _indentPx: 0,
      _treePadPx: 6,
      _hasRelated: totalChildren > 0,
      _hasChildren: totalChildren > 0,
      _childCount: totalChildren,
      _expanded: expandedCustomers.has(normCustOrgnr(p.orgnr)),
    });
    if (expandedCustomers.has(normCustOrgnr(p.orgnr))) {
      appendCustomerChildrenRows(p, 1, rows);
      appendEmbeddedManualRowsForCustomer(p, 1, rows);
    }
  });

  const totalRelated = parents.reduce((sum, p) => {
    const chList = children.filter(c => normCustOrgnr(c.parent_orgnr) === normCustOrgnr(p.orgnr));
    const embedded = chList.reduce((a, ch) => a + countEmbeddedRelatedForCustomer(ch), 0);
    const msL = p.related?.manual_subsidiaries || [];
    const underM = new Set(orgnrsUnderManualBranches(msL));
    chList.forEach(ch => {
      orgnrsUnderManualBranches(ch.related?.manual_subsidiaries).forEach(o => underM.add(o));
    });
    const ueFilteredLen = (p.related?.underenheter || []).filter(u => !underM.has(normCustOrgnr(u.orgnr))).length;
    const msBranch = msL.reduce((acc, m) => acc + countManualSubtreeDisplayNodes(m), 0);
    return sum + ueFilteredLen + msBranch + chList.length + embedded;
  }, 0);
  $("cust-counter").textContent = `${totalParents} kunder, ${totalRelated} relaterte`;

  const cpg = $("cust-pager");
  if (cpg) {
    cpg.hidden = totalParents === 0;
    const inf = $("cust-page-info");
    if (inf) {
      inf.textContent = totalParents
        ? `Viser kunde ${pOff + 1}–${pOff + parentsPage.length} av ${totalParents} · side ${custPage} av ${totalPages}`
        : "";
    }
    const pr = $("cust-prev");
    const nx = $("cust-next");
    if (pr) pr.disabled = custPage <= 1 || totalParents === 0;
    if (nx) nx.disabled = custPage >= totalPages || totalParents === 0;
  }

  $("cust-tab-tbody").innerHTML = rows.map(c => {
    const checked = c._isTopCustomer && selectedCustomers.has(c.orgnr || "") ? "checked" : "";
    const kindBadge = c._kind === "underenhet" ? ' <small class="kind-avdeling">avdeling</small>' :
                      c._kind === "manual_subsidiary" ? ' <small class="kind-manual">datter (manuell)</small>' :
                      c._kind === "datterselskap" ? ' <small class="kind-datter">datter</small>' : '';
    const ansatteVisible = c._isChild ? (c.antallAnsatte || 0) : (c._effAnsatte || c.antallAnsatte || 0);
    const checkboxCell = c._isTopCustomer
      ? `<td><input type="checkbox" class="cust-tab-check" data-orgnr="${c.orgnr || ''}" ${checked} onclick="event.stopPropagation()"></td>`
      : '<td></td>';
    const expandBtn = c._hasChildren && c.orgnr
      ? `<button class="expand-btn" onclick="event.stopPropagation();toggleExpand('${esc(c.orgnr)}')" title="${c._expanded ? "Skjul" : "Vis"} ${c._childCount} under">${c._expanded ? "−" : "+"}</button>`
      : '<span class="expand-btn-spacer"></span>';
    const aboCell = c._isTopCustomer && c.orgnr
      ? `<input type="number" class="editable-abo" value="${c.abonnementer || 0}" min="0" data-orgnr="${esc(c.orgnr)}" onclick="event.stopPropagation()">`
      : `${c.abonnementer || 0}`;
    const rowClick = c.orgnr ? `onclick="openCustomerDetailModal('${esc(c.orgnr)}')"` : "";
    const statusIcon = c._isTopCustomer ? (c.enriched ? "✅" : "⚠️") : '<small class="small-muted">—</small>';
    const promoteIcon = c.promotion_mode === "morselskap_auto" ? "🏢" :
                        c.promotion_mode === "datterselskap" ? "🔗" :
                        c.promoted_from_lead ? "🏆" : "";
    const treePad = c._treePadPx != null ? c._treePadPx : 6;
    const nameCellClass = c._isChild ? "cust-tree-name cust-child" : "cust-tree-name";
    const nameCellStyle = ` style="padding-left:${treePad}px"`;
    return `<tr ${rowClick} class="${c.orgnr ? "row-clickable" : ""}">
      ${checkboxCell}
      <td class="${nameCellClass}"${nameCellStyle}>${expandBtn}<span class="cust-tree-label"><b>${esc(c.navn || "")}</b>${kindBadge}</span></td>
      <td>${esc(c.orgnr || "")}</td>
      <td>${esc(c.kommune || "")}</td>
      <td>${esc((c.naeringskode1 || "") + " " + (c.nace_beskr || "").slice(0, 18))}</td>
      <td>${ansatteVisible}</td>
      <td>${aboCell}</td>
      <td>${statusIcon} ${promoteIcon}</td>
    </tr>`;
  }).join("");

  // Wire-up checkbox + abo
  document.querySelectorAll(".cust-tab-check").forEach(cb => {
    cb.addEventListener("change", e => {
      const o = e.target.dataset.orgnr;
      if (e.target.checked) selectedCustomers.add(o);
      else selectedCustomers.delete(o);
      updateBulkButtonTab();
    });
  });
  document.querySelectorAll(".editable-abo").forEach(inp => {
    inp.addEventListener("blur", async e => {
      const orgnr = e.target.dataset.orgnr;
      const v = parseInt(e.target.value || "0");
      await fetchJSON(`/api/customers/${orgnr}`, {
        method: "PATCH", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({abonnementer: v}),
      });
    });
    inp.addEventListener("keydown", e => { if (e.key === "Enter") e.target.blur(); });
  });

  // Sort-pil
  document.querySelectorAll("#customers-tab-table th.sortable").forEach(th => {
    const k = th.dataset.sort;
    th.classList.toggle("sorted", k === custSort.key);
    th.classList.toggle("sort-asc", k === custSort.key && custSort.dir === "asc");
    th.classList.toggle("sort-desc", k === custSort.key && custSort.dir === "desc");
  });
  updateBulkButtonTab();
}

function updateBulkButtonTab() {
  $("bulk-count-tab").textContent = selectedCustomers.size;
  $("btn-bulk-delete-tab").disabled = selectedCustomers.size === 0;
}

// === Listeners ===
let _custTabSearchRenderTimer = null;
function _scheduleRenderCustomersTab() {
  if (_custTabSearchRenderTimer) clearTimeout(_custTabSearchRenderTimer);
  _custTabSearchRenderTimer = setTimeout(() => {
    _custTabSearchRenderTimer = null;
    renderCustomersTab();
  }, 140);
}
$("cust-search-tab").addEventListener("input", _scheduleRenderCustomersTab);
const _btnAddCustTab = $("btn-add-customer-tab");
if (_btnAddCustTab && !_btnAddCustTab.dataset.wired) {
  _btnAddCustTab.dataset.wired = "1";
  _btnAddCustTab.addEventListener("click", () => {
    const ref = $("btn-add");
    if (ref) ref.click();
  });
}
$("cust-check-all-tab").addEventListener("change", e => {
  const checked = e.target.checked;
  document.querySelectorAll(".cust-tab-check").forEach(cb => {
    cb.checked = checked;
    if (checked) selectedCustomers.add(cb.dataset.orgnr);
    else selectedCustomers.delete(cb.dataset.orgnr);
  });
  updateBulkButtonTab();
});
$("btn-bulk-delete-tab").addEventListener("click", async () => {
  if (!confirm(`Slette ${selectedCustomers.size} valgte kunder?\nAlle ankerreferanser i leads fjernes også.`)) return;
  await fetchJSON("/api/customers/delete-bulk", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({orgnrs: [...selectedCustomers]}),
  });
  selectedCustomers.clear();
  await loadCustomers();
  await loadLeads();
  await loadStats();
  custPage = 1;
  renderCustomersTab();
});

// Klikkbar header-sortering (event delegation)
const _custTable = $("customers-tab-table");
if (_custTable) {
  _custTable.addEventListener("click", (e) => {
    const th = e.target.closest("th.sortable");
    if (!th || !_custTable.contains(th)) return;
    const k = th.dataset.sort;
    if (custSort.key === k) {
      custSort.dir = custSort.dir === "asc" ? "desc" : "asc";
    } else {
      custSort.key = k;
      custSort.dir = ["ansatte", "abonnementer", "enriched"].includes(k) ? "desc" : "asc";
    }
    custPage = 1;
    renderCustomersTab();
  });
}

(function initCustPagerDom() {
  const sz = $("cust-page-size");
  if (!sz || sz.dataset.wired === "1") return;
  sz.dataset.wired = "1";
  sz.value = String(custPageSize);
  sz.addEventListener("change", () => {
    custPageSize = normCustPageSize(sz.value);
    try { localStorage.setItem(CUST_PAGE_SIZE_LS, String(custPageSize)); } catch (e) {}
    custPage = 1;
    renderCustomersTab();
  });
  const pr = $("cust-prev");
  const nx = $("cust-next");
  if (pr) pr.addEventListener("click", () => { if (custPage > 1) { custPage--; renderCustomersTab(); } });
  if (nx) nx.addEventListener("click", () => { custPage++; renderCustomersTab(); });
})();
