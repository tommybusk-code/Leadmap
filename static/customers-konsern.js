// =====================================================================
// customers-konsern.js — Datter/parent-modaler + konsern-oversikt.
// Krever: core.js. Bruker openCustomerDetailModal, loadCustomers,
// renderCustomersTab, loadStats fra andre filer.
// =====================================================================

// === Manuelt datterselskap (modal-add-sub) ===
let _addSubParent = null;
let _addSubSearchTimer = null;

function openAddSubsidiary(parentOrgnr) {
  _addSubParent = parentOrgnr;
  $("add-sub-search").value = "";
  if ($("add-sub-orgnr")) $("add-sub-orgnr").value = "";
  $("add-sub-results").innerHTML = '<small class="muted">Søk etter selskap eller skriv org.nr…</small>';
  $("modal-add-sub").hidden = false;
  setTimeout(() => $("add-sub-search").focus(), 50);
}

async function searchAddSubsidiary() {
  clearTimeout(_addSubSearchTimer);
  const qRaw = ($("add-sub-search").value || "").trim();
  const digits = qRaw.replace(/\D/g, "");
  const isOrgnr = digits.length === 9;
  if (!isOrgnr && qRaw.length < 2) {
    $("add-sub-results").innerHTML = '<small class="muted">Skriv minst 2 tegn i navn, eller 9 siffer org.nr.</small>';
    return;
  }
  $("add-sub-results").innerHTML = '<small class="muted">Søker…</small>';
  _addSubSearchTimer = setTimeout(async () => {
    const q = ($("add-sub-search").value || "").trim();
    const d = q.replace(/\D/g, "");
    if (d.length !== 9 && q.length < 2) {
      $("add-sub-results").innerHTML = '<small class="muted">Skriv minst 2 tegn i navn, eller 9 siffer org.nr.</small>';
      return;
    }
    try {
      const data = await fetchJSON(`/api/search-brreg?q=${encodeURIComponent(q)}`);
      const results = data.results || [];
      if (!results.length) {
        $("add-sub-results").innerHTML = '<small class="muted">Ingen treff — prøv org.nr-feltet under, eller annen stavemåte.</small>';
        return;
      }
      $("add-sub-results").innerHTML = results.map(r => `
      <div class="add-sub-result" onclick="addSubsidiary('${esc(r.orgnr)}')">
        <b>${esc(r.navn)}</b> <small class="small-muted">${r.ansatte || 0} ans. — ${esc(r.kommune || r.poststed || '')}</small>
        <small class="muted-block">${esc(r.orgnr)}</small>
      </div>
    `).join("");
    } catch (e) {
      $("add-sub-results").innerHTML = `<small class="danger-text">Søk feilet: ${esc(e.message || e)}</small>`;
    }
  }, 280);
}

async function addSubsidiaryByOrgnrField() {
  const raw = ($("add-sub-orgnr") && $("add-sub-orgnr").value) || "";
  const digits = raw.replace(/\D/g, "");
  if (digits.length !== 9) {
    alert("Organisasjonsnummer må være nøyaktig 9 siffer.");
    return;
  }
  await addSubsidiary(digits);
}

async function addSubsidiary(subOrgnr) {
  if (!_addSubParent) return;
  try {
    await fetchJSON(`/api/customers/${_addSubParent}/add-subsidiary`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({orgnr: subOrgnr}),
    });
    $("modal-add-sub").hidden = true;
    if ($("add-sub-orgnr")) $("add-sub-orgnr").value = "";
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    await openCustomerDetailModal(_addSubParent);
  } catch (e) {
    alert("Kunne ikke legge til: " + (e.message || e));
  }
}

async function removeSubsidiary(parentOrgnr, subOrgnr) {
  if (!confirm("Fjerne denne datterselskap-koblingen?")) return;
  try {
    await fetchJSON(`/api/customers/${parentOrgnr}/remove-subsidiary`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({orgnr: subOrgnr}),
    });
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    await openCustomerDetailModal(parentOrgnr);
  } catch (e) {
    alert("Feil: " + (e.message || e));
  }
}

// === Sett moderbedrift (parent_orgnr på kunde, modal-set-parent) ===
let _setParentChild = null;

function openSetParent(childOrgnr) {
  _setParentChild = childOrgnr;
  $("set-parent-search").value = "";
  const candidates = (allCustomers || []).filter(x => x.orgnr && x.orgnr !== childOrgnr && !x.parent_orgnr);
  renderSetParentResults(candidates);
  $("modal-set-parent").hidden = false;
  setTimeout(() => $("set-parent-search").focus(), 50);
}

function renderSetParentResults(list) {
  if (!list.length) {
    $("set-parent-results").innerHTML = '<small class="muted">Ingen treff.</small>';
    return;
  }
  $("set-parent-results").innerHTML = list.slice(0, 30).map(c => `
    <div class="add-sub-result" onclick="setParent('${esc(c.orgnr)}')">
      <b>${esc(c.navn)}</b> <small class="small-muted">${c.antallAnsatte || 0} ans. — ${esc(c.kommune || c.poststed || '')}</small>
      <small class="muted-block">${esc(c.orgnr)}</small>
    </div>
  `).join('');
}

function searchSetParent() {
  const q = ($("set-parent-search").value || "").toLowerCase();
  const candidates = (allCustomers || []).filter(x => {
    if (!x.orgnr || x.orgnr === _setParentChild || x.parent_orgnr) return false;
    if (!q) return true;
    const on = String(x.orgnr || "").replace(/\s/g, "").toLowerCase();
    const qn = q.replace(/\s/g, "");
    return (x.navn || "").toLowerCase().includes(q) || (qn && on.includes(qn));
  });
  renderSetParentResults(candidates);
}

async function setParent(parentOrgnr) {
  if (!_setParentChild) return;
  try {
    await fetchJSON(`/api/customers/${_setParentChild}`, {
      method: "PATCH", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({parent_orgnr: parentOrgnr}),
    });
    $("modal-set-parent").hidden = true;
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    await openCustomerDetailModal(_setParentChild);
  } catch (e) {
    alert("Feil: " + (e.message || e));
  }
}

async function clearParent(childOrgnr) {
  if (!confirm("Fjerne moderbedrift-koblingen?")) return;
  try {
    await fetchJSON(`/api/customers/${childOrgnr}`, {
      method: "PATCH", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({parent_orgnr: ""}),
    });
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    await openCustomerDetailModal(childOrgnr);
  } catch (e) {
    alert("Feil: " + (e.message || e));
  }
}

// === Konsern-oversikt og morselskap-import ===
async function importMorselskap(morOrgnr) {
  if (!confirm("Importere morselskapet som kunde og koble alle dets dattere automatisk?")) return;
  try {
    const r = await fetchJSON(`/api/customers/import-morselskap/${morOrgnr}`, {method: "POST"});
    if (r.error) { alert("Feil: " + r.error); return; }
    alert(`✅ Morselskap importert. ${r.dattere_linked} dattere koblet.`);
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    await openCustomerDetailModal(morOrgnr);
  } catch (e) {
    alert("Feil: " + (e.message || e));
  }
}

async function openKonsernOverview() {
  $("konsern-body").innerHTML = '<small class="muted">Henter konsern-data...</small>';
  $("modal-konsern").hidden = false;
  try {
    const data = await fetchJSON("/api/konsern-overview");
    if (!data.groups || !data.groups.length) {
      $("konsern-body").innerHTML = '<p class="muted">Ingen konsern-relasjoner funnet ennå. Kjør "🔄 Oppdater datter-data for alle kunder" først.</p>';
      return;
    }
    const html = data.groups.map(g => {
      const dattereHtml = g.dattere.map(d => {
        const regHint = d.selskap_sum_eiendeler
          ? ` <small class="small-muted">· regnskap eiendeler ${new Intl.NumberFormat("nb-NO").format(d.selskap_sum_eiendeler)} kr</small>`
          : "";
        const konHint = d.rapporterer_til_konsern === true
          ? ' <small class="small-muted">↳ konsernregnskap</small>'
          : "";
        return `
        <li>
          <span class="anchor-link" onclick="closeModal('modal-konsern');openCustomerDetailModal('${esc(d.orgnr)}')">${esc(d.navn)}</span>
          <small class="small-muted">${d.antallAnsatte} ans · ${esc(d.kommune || '')} · ${d.abonnementer} abo</small>${regHint}${konHint}
          ${d.parent_orgnr_set ? '<small class="success-text">🔗 koblet</small>' : ''}
        </li>`;
      }).join('');
      const morHeader = g.mor_er_kunde
        ? `<b>${esc(g.mor_navn || g.mor_orgnr)}</b> <small class="success-text">✓ kunde</small>`
        : `<b>${esc(g.mor_navn || g.mor_orgnr)}</b> <small class="small-muted">— ikke kunde</small>
           <button class="small btn-tiny" onclick="importMorselskap('${esc(g.mor_orgnr)}');closeModal('modal-konsern')">+ Importer</button>`;
      const konsernSize = g.mor_konsern_ansatte
        ? `<small class="small-muted">${g.mor_konsern_ansatte} ansatte i konsernet (${g.mor_periode || ''})</small>` : '';
      const morEiendeler = g.mor_konsern_sum_eiendeler
        ? `<small class="small-muted"> · eiendeler (konsern) ${new Intl.NumberFormat("nb-NO").format(g.mor_konsern_sum_eiendeler)} kr</small>`
        : '';
      return `<div class="konsern-group">
        <div class="konsern-mor">🏢 ${morHeader} ${konsernSize}${morEiendeler}</div>
        <div class="konsern-dattere">${g.dattere.length} dattere som er kunder:</div>
        <ul class="related-list">${dattereHtml}</ul>
      </div>`;
    }).join('');
    const ikkeKunder = data.groups.filter(g => !g.mor_er_kunde);
    const bulkBtn = ikkeKunder.length > 0
      ? `<div class="konsern-bulk"><button onclick="importAllMorselskaper()">📥 Importer alle ${ikkeKunder.length} morselskap som ikke er kunder</button></div>`
      : '';
    $("konsern-body").innerHTML = `
      <p class="muted">Funnet <b>${data.total_groups}</b> konsern-grupper basert på brreg konsernregister.</p>
      ${bulkBtn}
      ${html}
    `;
  } catch (e) {
    $("konsern-body").innerHTML = `<p class="danger-text">Feil: ${esc(e.message || e)}</p>`;
  }
}

async function importAllMorselskaper() {
  if (!confirm("Importere ALLE detekterte morselskap som ikke er kunder, og koble dattrene automatisk?")) return;
  const r = await fetchJSON("/api/customers/import-all-morselskaper", {method: "POST"});
  alert(`✅ ${r.added} morselskap lagt til. ${r.failed} feilet.`);
  closeModal("modal-konsern");
  await loadCustomers();
  if (!$("view-customers").hidden) renderCustomersTab();
  await loadStats();
}
