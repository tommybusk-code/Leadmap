// =====================================================================
// customers-modal.js — Kundekortet (detail modal) + refresh.
// Krever: core.js. Bruker funksjoner fra customers-tab.js (loadCustomers,
// renderCustomersTab) og customers-konsern.js (openSetParent, clearParent,
// openAddSubsidiary, removeSubsidiary, importMorselskap).
// Krever: leads-detail.js (promoteLeadUnderAnchor, linkLeadCustomerUnderParent) for lead-kontekst.
// =====================================================================

/** Når kundekort åpnes fra et lead-treff: { leadOrgnr } — null ellers. */
let _customerDetailLeadContext = null;

/**
 * Åpner kundekort med «kom fra dette leadet»-kontekst (snarveier mor/datter).
 * @param {string} customerOrgnr
 * @param {string} leadOrgnr
 */
function openCustomerDetailFromLead(customerOrgnr, leadOrgnr) {
  _customerDetailLeadContext = { leadOrgnr: String(leadOrgnr) };
  return openCustomerDetailModal(customerOrgnr, { keepLeadContext: true });
}

function buildCustomerLeadContextHtml(viewingOrgnr, c, editable) {
  const ctx = _customerDetailLeadContext;
  if (!ctx || !ctx.leadOrgnr) return "";
  const leadOrgnr = ctx.leadOrgnr;
  const leadKey = normOrgnr(leadOrgnr);
  const lead = (allLeads || []).find(l => normOrgnr(l.orgnr) === leadKey);
  if (leadKey === normOrgnr(viewingOrgnr)) return "";
  if (!lead) return "";
  const leadCust = (allCustomers || []).find(x => normOrgnr(x.orgnr) === leadKey);
  const herNavn = esc(c.navn);
  const btns = [];
  if (leadCust) {
    btns.push(
      `<button type="button" class="small" onclick="linkLeadCustomerUnderParent('${esc(leadOrgnr)}','${esc(viewingOrgnr)}');event.stopPropagation()" title="${esc(lead.navn)} knyttes som datterselskap av ${herNavn} (${herNavn} blir moderbedrift).">Legg til som datterselskap av «${herNavn}»</button>`,
      `<button type="button" class="small secondary" onclick="linkLeadCustomerUnderParent('${esc(leadOrgnr)}','${esc(viewingOrgnr)}');event.stopPropagation()" title="Samme som forrige knapp, annen ordlyd: ${esc(lead.navn)} registreres med «${c.navn}» som morselskap.">Legg inn som morselskap av «${herNavn}»</button>`
    );
  } else {
    btns.push(
      `<button type="button" class="small" onclick="promoteLeadUnderAnchor('${esc(leadOrgnr)}','${esc(viewingOrgnr)}');event.stopPropagation()" title="${esc(lead.navn)} importeres som kunde under ${herNavn}">Legg til som datterselskap av «${herNavn}»</button>`,
      `<button type="button" class="small secondary" onclick="promoteLeadUnderAnchor('${esc(leadOrgnr)}','${esc(viewingOrgnr)}');event.stopPropagation()" title="Samme som forrige knapp: lead importeres som kunde med «${c.navn}» som morselskap.">Legg inn som morselskap av «${herNavn}»</button>`
    );
  }
  if (leadCust && editable) {
    btns.push(
      `<button type="button" class="small secondary" onclick="linkLeadCustomerUnderParent('${esc(viewingOrgnr)}','${esc(leadOrgnr)}');event.stopPropagation()" title="«${herNavn}» (dette kundekortet) knyttes som datterselskap av «${esc(lead.navn)}». ${esc(lead.navn)} blir moderbedrift i kundelisten.">«${herNavn}» som datterselskap av «${esc(lead.navn)}»</button>`
    );
  }
  return `<div class="customer-lead-context">
    <p class="customer-lead-context-intro"><span class="muted">Åpnet fra lead</span> <b>${esc(lead.navn)}</b> <small class="small-muted">${esc(leadOrgnr)}</small></p>
    <div class="customer-lead-context-actions">${btns.join("")}</div>
  </div>`;
}

function fmtNokkelTall(n) {
  if (n == null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("nb-NO").format(n);
}

function _ownershipKildeTitle(k) {
  if (k === "regnskap") return "Regnskapsmessig morselskap (Brønnøysund)";
  if (k === "koblet") return "Datterselskap koblet i kundelisten";
  if (k === "lead") return "Lead med signal «morselskap» mot denne kunden";
  return k || "";
}

/** Eierskap-seksjon: andeler fra aksjeeierbok innenfor innstilt min–maks %. */
function buildOwnershipEierskapHtml(data) {
  const ak = Array.isArray(data.ownership_aksjonaer) ? data.ownership_aksjonaer : [];
  const mor = Array.isArray(data.ownership_morselskap) ? data.ownership_morselskap : [];
  const lim = data.ownership_stake_pct_limits || { min: 5, max: 100 };
  const lo = Number(lim.min);
  const hi = Number(lim.max);
  const loOk = Number.isFinite(lo) ? lo : 5;
  const hiOk = Number.isFinite(hi) ? hi : 100;
  const loTxt = Number.isInteger(loOk) ? String(Math.round(loOk)) : loOk.toFixed(1).replace(/\.0$/, "");
  const hiTxt = Number.isInteger(hiOk) ? String(Math.round(hiOk)) : hiOk.toFixed(1).replace(/\.0$/, "");
  const rangeAk =
    hiOk >= 99.5 ? `minst ${loTxt} %` : `mellom ${loTxt} % og ${hiTxt} %`;
  const rangeMor = hiOk >= 99.5 ? `minst ${loTxt} %` : `mellom ${loTxt} % og ${hiTxt} %`;
  const pillsA = ak
    .map(
      x =>
        `<span class="cust-own-pill cust-own-pill--aksjonær" role="button" tabindex="0" title="${esc(x.orgnr)} — aksjeeierbok 2024" onclick="openCustomerDetailModal('${esc(x.orgnr)}')">${esc(x.navn)} · ${x.pct}%</span>`,
    )
    .join("");
  const pillsM = mor
    .map(x => {
      const pctPart = x.pct != null ? ` · ${x.pct}%` : "";
      return `<span class="cust-own-pill cust-own-pill--mor" role="button" tabindex="0" title="${esc(x.orgnr)} — ${_ownershipKildeTitle(x.kilde)}" onclick="openCustomerDetailModal('${esc(x.orgnr)}')">${esc(x.navn)}${pctPart}</span>`;
    })
    .join("");
  const emptyAk = `<span class="small-muted">Ingen registrerte eierandeler (${rangeAk}) i aksjeeierbok.</span>`;
  const emptyMor = '<span class="small-muted">Ingen datterselskap/lead med mor mot denne kunden.</span>';
  return `
    <div class="detail-section detail-section--ownership">
      <h3>Eierskap <small class="small-muted" style="font-weight:400">aksjeeierbok 2024 · mor i app</small></h3>
      <div class="cust-own-grid">
        <div class="cust-own-col">
          <h4 class="cust-own-h"><span class="cust-own-label-pill">Kunde som aksjonær</span></h4>
          <p class="cust-own-hint small-muted">Selskap der denne kunden eier <strong>${rangeAk}</strong> av aksjene (aksjeeierbok 2024). Justeres under <strong>Innstillinger</strong>.</p>
          <div class="cust-own-pills">${ak.length ? pillsA : emptyAk}</div>
        </div>
        <div class="cust-own-col">
          <h4 class="cust-own-h"><span class="cust-own-label-pill cust-own-label-pill--mor">Kunde som morselskap</span></h4>
          <p class="cust-own-hint small-muted">Selskap som har denne kunden som mor (regnskap), koblet datter, eller morselskap-lead. <strong>Prosent</strong> fra aksjeeierbok når anker eier <strong>${rangeMor}</strong> i selskapet.</p>
          <div class="cust-own-pills">${mor.length ? pillsM : emptyMor}</div>
        </div>
      </div>
    </div>`;
}

/** Brreg: antall underenheter, regnskapsår, konsern-flagg og nøkkeltall. */
function buildBrregRegnskapHtml(c) {
  const r = c.related;
  if (!r || r.error) return "";
  const parts = [];
  const ueList = r.underenheter || [];
  const ueN = r.underenheter_antall != null ? r.underenheter_antall : ueList.length;
  if (ueN > 0) {
    parts.push(`<li><b>Underenheter</b> <span class="small-muted">${ueN} registrert i enhetsregisteret</span></li>`);
  }
  if (r.regnskap_siste_aar) {
    parts.push(`<li><b>Siste regnskapsår</b> ${esc(r.regnskap_siste_aar)} <span class="small-muted">(regnskapsregisteret)</span></li>`);
  }
  if (r.rapporterer_til_konsern === true) {
    parts.push(`<li>Rapporterer <b>konsernregnskap</b> under morselskap <span class="small-muted">(merket i årsregnskapet)</span></li>`);
  } else if (r.rapporterer_til_konsern === false) {
    parts.push(`<li>Ikke markert som del av annet konsern <span class="small-muted">(eget årsregnskap)</span></li>`);
  }
  const sk = [];
  if (r.selskap_sum_eiendeler) sk.push(`eiendeler ${fmtNokkelTall(r.selskap_sum_eiendeler)} kr`);
  if (r.selskap_sum_egenkapital) sk.push(`egenkapital ${fmtNokkelTall(r.selskap_sum_egenkapital)} kr`);
  if (r.selskap_aarsresultat != null) sk.push(`årsresultat ${fmtNokkelTall(r.selskap_aarsresultat)} kr`);
  if (r.selskap_driftsresultat != null) sk.push(`driftsresultat ${fmtNokkelTall(r.selskap_driftsresultat)} kr`);
  if (sk.length) {
    parts.push(`<li><b>Årsregnskap (selskap)</b> ${sk.join(" · ")}</li>`);
  }
  const kk = [];
  if (r.konsern_sum_eiendeler) kk.push(`eiendeler ${fmtNokkelTall(r.konsern_sum_eiendeler)} kr`);
  if (r.konsern_sum_egenkapital) kk.push(`egenkapital ${fmtNokkelTall(r.konsern_sum_egenkapital)} kr`);
  if (r.konsern_aarsresultat != null) kk.push(`årsresultat ${fmtNokkelTall(r.konsern_aarsresultat)} kr`);
  if (kk.length) {
    parts.push(`<li><b>Konsolidert konsern</b> ${kk.join(" · ")} <span class="small-muted">(${esc(r.konsern_periode || "")})</span></li>`);
  }
  if (!parts.length) return "";
  return `<div class="detail-section"><h3>Brreg — struktur og regnskap</h3><ul class="related-list">${parts.join("")}</ul></div>`;
}

/** Rot-kundens orgnr (eier av related-treet) — alltid brukt ved fjerning av manuelle koblinger. */
function _subsTreeRootOrgnr(c, data) {
  if (data && data.root_customer_orgnr) return data.root_customer_orgnr;
  if (c && c.orgnr && (!data || !data.is_subsidiary)) return c.orgnr;
  return "";
}

/**
 * Rekursiv liste: avdelinger (+ manuelle under), manuelle datre (+ under).
 * parentOrgnr til add-subsidiary = nodens eget orgnr (også under avdeling / barnebarn).
 */
function buildSubsidiariesSectionHtml(c, data) {
  const rootOrgnr = _subsTreeRootOrgnr(c, data);
  const canEditTree = !!rootOrgnr;
  const ueList = c.related?.underenheter || [];
  const msList = c.related?.manual_subsidiaries || [];

  function manualLi(m) {
    const nestedUe = (m.related?.underenheter || []).map(ueLi).join("");
    const kids = (m.manual_subsidiaries || []).map(manualLi).join("");
    const btns = canEditTree
      ? `<button type="button" class="small btn-tiny" onclick="openAddSubsidiary('${esc(m.orgnr)}')" title="Legg til manuelt selskap under denne">+ under</button>
         <button type="button" class="small btn-tiny" onclick="removeSubsidiary('${esc(rootOrgnr)}','${esc(m.orgnr)}')" title="Fjern kobling">✕</button>`
      : "";
    const nested = [nestedUe, kids].filter(Boolean).join("");
    return `<li><b>${esc(m.navn)}</b> <small class="small-muted">(${m.antallAnsatte || 0} ans., ${esc(m.kommune || "")}) — manuell</small> ${btns}
      ${nested ? `<ul class="related-list nested-subs">${nested}</ul>` : ""}</li>`;
  }

  function ueLi(u) {
    const manuals = (u.manual_subsidiaries || []).map(manualLi).join("");
    const addUnder = canEditTree
      ? `<button type="button" class="small btn-tiny" onclick="openAddSubsidiary('${esc(u.orgnr)}')" title="Manuell datter/avdeling under denne Brreg-avdelingen">+ under</button>`
      : "";
    return `<li><b>${esc(u.navn)}</b> <small class="small-muted">(${u.antallAnsatte || 0} ans., ${esc(u.kommune || "")}) — avdeling</small> ${addUnder}
      ${manuals ? `<ul class="related-list nested-subs">${manuals}</ul>` : ""}</li>`;
  }

  const items = [...ueList.map(ueLi), ...msList.map(manualLi)].join("");
  const topAdd = canEditTree && c.orgnr
    ? (!data.is_subsidiary
      ? `<button type="button" class="small btn-mini" onclick="openAddSubsidiary('${esc(c.orgnr)}')">➕ Legg til manuelt (under hovedselskap)</button>`
      : `<button type="button" class="small btn-mini" onclick="openAddSubsidiary('${esc(c.orgnr)}')">➕ Legg til manuelt under denne</button>`)
    : "";

  const ueCount = c.related?.underenheter_antall != null ? c.related.underenheter_antall : ueList.length;
  const ueHint = ueCount ? ` <small class="small-muted">(${ueCount} fra Brreg)</small>` : "";

  return `
    <div class="detail-section">
      <h3>Datterselskaper / underenheter${ueHint} ${topAdd}</h3>
      ${items ? `<ul class="related-list">${items}</ul>` : '<p class="muted no-relations">Ingen datterselskaper koblet ennå.</p>'}
    </div>`;
}

async function refreshCustomer(orgnr) {
  const btn = event.target;
  btn.disabled = true; btn.textContent = "⏳ Henter...";
  try {
    const data = await fetchJSON(`/api/customers/${orgnr}/refresh`, {method: "POST"});
    const sync = data.sync_heleide_bok;
    if (sync && sync.added > 0) {
      alert(
        `Aksjeeierbok: ${sync.added} heleide selskap (≥99 %) er lagt inn som datre i treet. ` +
        `(Allerede i tre: ${sync.skipped_in_tree || 0}, Brreg manglet: ${sync.skipped_brreg || 0}.)`,
      );
    }
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    await openCustomerDetailModal(orgnr, { keepLeadContext: true });
  } catch (e) {
    alert("Feil: " + e);
    btn.disabled = false; btn.textContent = "🔄 Oppdater";
  }
}

async function syncHeleideFraBok(orgnr) {
  const btn = event.target;
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ Synker...";
  try {
    const data = await fetchJSON(`/api/customers/${orgnr}/sync-heleide-fra-bok`, {method: "POST"});
    let msg = `Ferdig: ${data.added || 0} nye datre i treet.`;
    if (data.skipped_in_tree) msg += ` ${data.skipped_in_tree} fantes allerede i et kundetre.`;
    if (data.skipped_brreg) msg += ` ${data.skipped_brreg} ikke funnet i Brreg.`;
    if (data.error && !(data.added > 0)) msg = data.error;
    alert(msg);
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    await openCustomerDetailModal(orgnr, { keepLeadContext: true });
  } catch (e) {
    alert("Feil: " + e);
    btn.disabled = false;
    btn.textContent = prev;
  }
}

/**
 * @param {string} orgnr
 * @param {{ fromLeadOrgnr?: string, keepLeadContext?: boolean }} [opts]
 */
async function openCustomerDetailModal(orgnr, opts) {
  if (opts && opts.keepLeadContext) {
    /* behold _customerDetailLeadContext */
  } else if (opts && opts.fromLeadOrgnr) {
    _customerDetailLeadContext = { leadOrgnr: String(opts.fromLeadOrgnr) };
  } else {
    _customerDetailLeadContext = null;
  }

  const data = await fetchJSON(`/api/customers/${orgnr}`);
  if (data.error) { alert(data.error); return; }
  const c = data.customer;
  const eff = data.effective_ansatte;
  const related = data.related_leads || [];
  const editable = !data.is_subsidiary;

  // Banners
  const subBanner = data.is_subsidiary ? `
    <div class="banner-subsidiary">
      🏢 ${esc(data.subsidiary_kind)} av <span class="anchor-link" onclick="openCustomerDetailModal('${esc(data.parent_orgnr)}')">${esc(data.parent_navn)}</span>
    </div>` : '';

  const parentBanner = c.parent_orgnr ? `
    <div class="banner-parent">
      🔗 Datterselskap av <span class="anchor-link" onclick="openCustomerDetailModal('${esc(c.parent_orgnr)}')">${esc(c.parent_navn || c.parent_orgnr)}</span>
      <button type="button" class="small btn-tiny" onclick="clearParent('${esc(c.orgnr)}')">Fjern kobling</button>
    </div>` : '';

  // Konsern-banner: vis hvis kunden er datter i et brreg-konsern
  const morOrgnr = c.related?.mor_orgnr;
  const morNavnK = c.related?.mor_navn;
  const morAnsatte = c.related?.konsern_ansatte;
  const morPeriode = c.related?.konsern_periode;
  const morErKunde = morOrgnr && (allCustomers || []).some(x => normOrgnr(x.orgnr) === normOrgnr(morOrgnr));
  const morSameAsLinkedParent = morOrgnr && c.parent_orgnr && normOrgnr(morOrgnr) === normOrgnr(c.parent_orgnr);
  const morKonEie = c.related?.konsern_sum_eiendeler;
  const konsernBanner = morOrgnr && !morSameAsLinkedParent ? `
    <div class="banner-konsern">
      🏢 Konsern (Brønnøysund): <b>${esc(morNavnK || morOrgnr)}</b>
      ${morAnsatte ? ` <small class="small-muted">(${morAnsatte} ans. i konsernet ${morPeriode || ''})</small>` : ''}
      ${morKonEie ? ` <small class="small-muted">· konsern eiendeler ${fmtNokkelTall(morKonEie)} kr</small>` : ""}
      ${morErKunde
        ? ` <button type="button" class="small btn-tiny" onclick="openCustomerDetailModal('${esc(morOrgnr)}')">Åpne morselskap</button>`
        : ` <button type="button" class="small btn-tiny" onclick="importMorselskap('${esc(morOrgnr)}')">+ Importer som kunde</button>`}
    </div>` : '';

  const enrichChip = c.enriched
    ? `<span class="detail-chip detail-chip--ok">Beriket</span>`
    : `<span class="detail-chip detail-chip--warn">Ikke beriket</span>`;
  const subChip = data.is_subsidiary
    ? `<span class="detail-chip">Datterselskap</span>`
    : "";
  const ownAk = data.ownership_aksjonaer || [];
  const ownMor = data.ownership_morselskap || [];
  const ownHeroChips = `<span class="detail-chip detail-chip-ownhead" title="Selskap der kunden eier ≥5 % (aksjeeierbok 2024)">Kunde som aksjonær · ${ownAk.length}</span>
         <span class="detail-chip detail-chip-ownhead detail-chip-ownhead--mor" title="Selskap med mor mot denne kunden (regnskap / koblet / lead)">Kunde som morselskap · ${ownMor.length}</span>`;
  const heroCust = `<div class="detail-hero detail-hero--customer">
    <div class="detail-hero-customer-top">
      <span class="detail-mono">${esc(c.orgnr || "")}</span>
      ${enrichChip}
    </div>
    <div class="detail-hero-chips">
      <span class="detail-chip">${eff} ans. <span class="detail-chip-sublabel">effektivt</span></span>
      ${subChip}
      ${ownHeroChips}
    </div>
  </div>`;

  // Tittel + refresh-knapp (også for datterselskap i tre — Brreg-relasjoner). Heleide-fra-bok kun toppkunde.
  const showRefresh = Boolean(c.orgnr);
  const isTopCustomer = !data.is_subsidiary;
  $("cust-detail-title").innerHTML = `${esc(c.navn)} ${
    showRefresh
      ? `<button type="button" class="small btn-mini" onclick="refreshCustomer('${esc(c.orgnr)}')" title="Brreg-kort og relasjoner (konsern/underenheter) for dette selskapet. For toppkunde: også synk av heleide datre fra aksjeeierbok.">🔄 Oppdater</button>` +
        (isTopCustomer
          ? ` <button type="button" class="small btn-mini secondary" onclick="syncHeleideFraBok('${esc(c.orgnr)}')" title="Uten full roten-oppdatering: legg inn manuelle datre for alle selskaper der kunden eier ≥99 % i aksjeeierbok 2024">📘 Heleide fra bok → tre</button>`
          : "")
      : ""
  }`;

  // Leads-seksjonen
  const relatedHtml = related.length ? `
    <div class="detail-section">
      <h3>Leads knyttet til denne kunden (${data.total_leads})</h3>
      <ul class="related-list">
        ${related.slice(0, 30).map(L => `<li class="customer-related-lead">
          <div class="customer-related-lead-head"><b>${esc(L.navn)}</b> <span class="small-muted">— score ${L.score}, ${L.antallAnsatte || 0} ans., ${esc(L.kommune || "")}</span></div>
          <div class="sig-list sig-list--customer-lead sig-list--like-table">${buildLeadSignalPillsHtml(L, { anchorOrgnr: c.orgnr })}</div>
        </li>`).join('')}
      </ul>
      ${data.total_leads > 30 ? `<small class="small-muted">+${data.total_leads - 30} flere</small>` : ''}
    </div>` : '<p class="muted">Ingen leads knyttet til denne kunden ennå.</p>';

  const subsHtml = buildSubsidiariesSectionHtml(c, data);

  const leadContextHtml = buildCustomerLeadContextHtml(c.orgnr, c, editable);
  const ownershipHtml = buildOwnershipEierskapHtml(data);

  const linkedDaughterCustomers = (allCustomers || []).filter(x => x.parent_orgnr === c.orgnr);
  const linkedDaughtersHtml = linkedDaughterCustomers.length && editable
    ? `<div class="detail-section">
        <h3>Koblede datterselskaper (eget kundekort)</h3>
        <p class="muted small">Disse er koblet via «Datterselskap av …». Manuelt tre under dem vises under <b>${esc(c.navn || "mor")}</b> i kunder-fanen når du utvider (+).</p>
        <ul class="related-list">
          ${linkedDaughterCustomers.map(ch => `<li>
            <b class="anchor-link" onclick="openCustomerDetailModal('${esc(ch.orgnr)}')">${esc(ch.navn)}</b>
            <small class="small-muted">${esc(ch.orgnr)}</small>
            <button type="button" class="small btn-tiny" onclick="openAddSubsidiary('${esc(ch.orgnr)}')">+ Manuelt tre under</button>
          </li>`).join("")}
        </ul>
      </div>`
    : "";

  // Redigerbare felter
  const inputAttr = (field, val) => editable
    ? `<input class="cust-edit" data-orgnr="${esc(c.orgnr)}" data-field="${field}" value="${esc(val ?? '')}">`
    : `<span>${esc(val ?? '—')}</span>`;
  const intInputAttr = (field, val) => editable
    ? `<input class="cust-edit" type="number" min="0" data-orgnr="${esc(c.orgnr)}" data-field="${field}" value="${val ?? 0}">`
    : `<span>${val ?? 0}</span>`;

  // Ansatte-verdi (én rad — manuell, konsern, eller aggregat)
  const konsernA = c.related?.konsern_ansatte;
  const konsernKilde = c.related?.konsern_kilde;
  let ansatteValue;
  if (c.antallAnsatte_override && c.antallAnsatte_override > 0) {
    ansatteValue = `${c.antallAnsatte_override} <small class="success-text">(manuelt satt)</small>`;
  } else if (konsernA && konsernA > (c.antallAnsatte || 0)) {
    const note = konsernKilde === "morselskap" && morNavnK
      ? `via konsernet til ${esc(morNavnK)} (${morPeriode || ''})`
      : `konsernregnskap ${morPeriode || ''}`;
    ansatteValue = `${eff} <small class="small-muted">(${note})</small>`;
  } else {
    ansatteValue = `${eff}`;
  }

  // Bygg modal
  $("cust-detail-body").innerHTML = `
    ${subBanner}
    ${parentBanner}
    ${konsernBanner}
    ${heroCust}
    ${leadContextHtml}
    ${ownershipHtml}
    ${editable && !c.parent_orgnr ? `<div class="parent-action"><button class="small secondary" onclick="openSetParent('${esc(c.orgnr)}')">Marker som datterselskap av annen kunde…</button></div>` : ''}
    <div class="detail-section">
      <h3>Selskapsinfo ${editable ? '<small class="small-muted" style="font-weight:400">— klikk i felt for å redigere</small>' : ''}</h3>
      <div class="detail-grid">
        <b>Navn</b>${inputAttr('navn', c.navn)}
        <b>Org.nr</b><span>${esc(c.orgnr || '')}</span>
        <b>Org.form</b><span>${esc(c.organisasjonsform_kode || "—")}</span>
        <b>Adresse</b>${inputAttr('adresse', c.adresse)}
        <b>Postnr</b>${inputAttr('postnummer', c.postnummer)}
        <b>Poststed</b>${inputAttr('poststed', c.poststed)}
        <b>Kommune</b>${inputAttr('kommune', c.kommune)}
        <b>Bransje</b><span>${esc(naceLabel(c.naeringskode1))} <small class="small-muted">(${esc(c.naeringskode1 || '')})</small></span>
        <b>Ansatte</b><span>${ansatteValue}</span>
        <b>Overstyr ansatte</b>${intInputAttr('antallAnsatte_override', c.antallAnsatte_override || '')}
        <b>Abonnementer</b>${intInputAttr('abonnementer', c.abonnementer)}
        <b>Telefon</b>${inputAttr('telefon', c.telefon)}
        <b>E-post</b>${inputAttr('epost', c.epost)}
        <b>Hjemmeside</b>${inputAttr('hjemmeside', c.hjemmeside)}
        <b>Notater</b>${editable ? `<textarea class="cust-edit" data-orgnr="${esc(c.orgnr)}" data-field="notater" rows="2">${esc(c.notater || '')}</textarea>` : `<span>${esc(c.notater || '—')}</span>`}
      </div>
    </div>
    ${buildBrregRegnskapHtml(c)}
    ${subsHtml}
    ${linkedDaughtersHtml}
    ${relatedHtml}
  `;
  $("modal-cust-detail").hidden = false;

  // Auto-lagre ved blur eller Enter
  document.querySelectorAll(".cust-edit").forEach(inp => {
    const save = async () => {
      const orgnr = inp.dataset.orgnr;
      const field = inp.dataset.field;
      const val = inp.value;
      try {
        await fetchJSON(`/api/customers/${orgnr}`, {
          method: "PATCH", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({[field]: val}),
        });
        inp.classList.add("saved-flash");
        setTimeout(() => inp.classList.remove("saved-flash"), 800);
      } catch (e) {
        inp.classList.add("error-flash");
        alert("Kunne ikke lagre: " + e);
      }
    };
    inp.addEventListener("blur", save);
    inp.addEventListener("keydown", e => {
      if (inp.tagName === "TEXTAREA") {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) inp.blur();
      } else if (e.key === "Enter") {
        inp.blur();
      }
    });
  });
}
