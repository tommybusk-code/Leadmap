// leads-detail.js — Detaljmodal, status→promote, Proff, LinkedIn, lead-til-lead.
// Krever: core.js, leads-table.js (loadLeads, render, renderTabs)

/** Én linje per person — samme ordlyd som strongAnchorRow (for enkelt-treff uten full re-analyse). */
function formatFellesStyreExplainLine(leadNavn, kundeNavn, fs) {
  if (!fs || !Array.isArray(fs.personer) || !fs.personer.length) return "";
  const ln = (leadNavn || "").trim() || "lead";
  const kn = (kundeNavn || "").trim() || "kunde";
  const parts = [];
  for (const p of fs.personer.slice(0, 5)) {
    const navn = (p.navn || "").trim();
    if (!navn) continue;
    const rl = (p.rolle_lead || "").trim() || "Styre";
    const ra = (p.rolle_anker || "").trim() || "Styre";
    const prefix = p.power ? "👑 " : "👤 ";
    parts.push(`${prefix}${navn} — ${rl} hos ${ln}, ${ra} hos ${kn}`);
  }
  return parts.join("; ");
}

function openDetail(orgnr) {
  const key = normOrgnr(orgnr);
  const l = allLeads.find(x => normOrgnr(x.orgnr) === key);
  if (!l) return;
  $("detail-title").textContent = l.navn;

  const byPerson = {};
  (l.felles_styre || []).forEach(fs => {
    (fs.personer || []).forEach(p => {
      const key = p.navn;
      if (!byPerson[key]) byPerson[key] = {navn: p.navn, power: p.power, rolle_lead: p.rolle_lead, ankers: []};
      byPerson[key].ankers.push({navn: fs.anker_navn, orgnr: fs.anker_orgnr, rolle: p.rolle_anker});
      if (p.power) byPerson[key].power = true;
    });
  });
  const hasPersonData = Object.keys(byPerson).length > 0;

  let personerHtml = "";
  if (hasPersonData) {
    personerHtml = `<div class="detail-section">
      <h3>Felles person-koblinger</h3>
      ${Object.values(byPerson).map(p => `
        <div class="person-card ${p.power ? 'power' : ''}">
          <div class="person-name">
            ${p.power ? '👑' : '👤'} <b>${esc(p.navn)}</b>
            ${p.power ? '<span class="power-badge">Styreleder/CEO</span>' : ''}
          </div>
          <div class="person-rolle-lead">Hos <b>${esc(l.navn)}</b>: ${esc(p.rolle_lead)}</div>
          <div class="person-rolle-list">Hos kundene dine:
            <ul>${p.ankers.map(a => `<li><b>${esc(a.navn)}</b> — ${esc(a.rolle)}</li>`).join('')}</ul>
          </div>
        </div>
      `).join('')}
    </div>`;
  }

  const byAnchor = {};
  (l.signals || []).forEach(s => {
    if (!s.anker_orgnr && !s.anker_navn) return;
    const key = s.anker_orgnr || s.anker_navn;
    if (!byAnchor[key]) byAnchor[key] = {orgnr: s.anker_orgnr, navn: s.anker_navn || "(ukjent)", ansatte: 0, signalTypes: new Set(), details: {}};
    byAnchor[key].signalTypes.add(s.type);
    if (s.detail) {
      const prev = byAnchor[key].details[s.type];
      if (!prev || String(s.detail).length > String(prev).length) byAnchor[key].details[s.type] = s.detail;
    }
    if ((s.anker_ansatte || 0) > byAnchor[key].ansatte) byAnchor[key].ansatte = s.anker_ansatte || 0;
  });

  const anchorList = Object.values(byAnchor);
  function relevance(a) {
    const types = [...a.signalTypes];
    if (!types.length) return 0;
    const maxW = Math.max(...types.map(t => SIGNAL_WEIGHTS_JS[t] || 0));
    return maxW * 100 + types.length;
  }
  anchorList.sort((a, b) => relevance(b) - relevance(a));

  const strongAnchors = anchorList.filter(a => a.signalTypes.size >= 2);
  const singleAnchors = anchorList.filter(a => a.signalTypes.size < 2);
  const ankerless = (l.signals || []).filter(s => !s.anker_orgnr && !s.anker_navn);

  const fellesByAnchor = {};
  (l.felles_styre || []).forEach(fs => { fellesByAnchor[fs.anker_orgnr || fs.anker_navn] = fs; });

  function anchorLink(navn, orgnr) {
    if (orgnr) return `<span class="anchor-link" onclick="openCustomerDetailFromLead('${orgnr}','${l.orgnr}');event.stopPropagation()">${esc(navn)}</span>`;
    return esc(navn);
  }

  function anchorActionsBar(leadOrgnr, anchorOrgnr) {
    if (!anchorOrgnr) return "";
    const ao = normOrgnr(anchorOrgnr);
    const lo = normOrgnr(leadOrgnr);
    const parentCust = (allCustomers || []).find(c => normOrgnr(c.orgnr) === ao);
    const leadCust = (allCustomers || []).find(c => normOrgnr(c.orgnr) === lo);
    const parts = [];
    if (parentCust) {
      parts.push(
        `<button type="button" class="small" onclick="promoteLeadUnderAnchor('${leadOrgnr}','${anchorOrgnr}');event.stopPropagation()">Vunnet · datter her</button>`
      );
    }
    if (leadCust && parentCust) {
      parts.push(
        `<button type="button" class="small secondary" onclick="linkLeadCustomerUnderParent('${leadOrgnr}','${anchorOrgnr}');event.stopPropagation()">Lead som datter av treff</button>`
      );
      if (anchorOrgnr !== leadOrgnr) {
        parts.push(
          `<button type="button" class="small secondary" onclick="linkLeadCustomerUnderParent('${anchorOrgnr}','${leadOrgnr}');event.stopPropagation()" title="Moder = lead-selskapet (som kunde)">Treff som datter av lead</button>`
        );
      }
    }
    if (!parts.length) return "";
    return `<div class="anchor-actions">${parts.join("")}</div>`;
  }

  function strongAnchorTagsHtml(lead, a) {
    const ao = a.orgnr != null && a.orgnr !== "" ? String(a.orgnr) : "";
    const merge = ao ? anchorBransjeGeoMergeInfo(lead, ao) : null;
    const baseTypes = dropKommuneGeoWhenPostnrPresent([...a.signalTypes]);
    const rest = baseTypes.filter(
      t => !merge || (t !== "samme_bransje" && !GEO_SIGNAL_TYPES.has(t))
    );
    const items = rest.map(t => ({
      w: SIGNAL_WEIGHTS_JS[t] || 0,
      html: `<span class="sig-tag t-${t}" title="${esc(SIGNAL_LABELS[t] || t)}">${esc(SIGNAL_LABELS[t] || t)}</span>`,
    }));
    if (merge) {
      items.push({
        w: merge.points,
        html: bransjeGeoComboPillHtml(merge.geoTier, merge.geoWord, merge.points, merge.tipRaw),
      });
    }
    items.sort((x, y) => y.w - x.w);
    return items.map(i => i.html).join("");
  }

  function strongAnchorRow(a) {
    const tags = strongAnchorTagsHtml(l, a);
    const fs = fellesByAnchor[a.orgnr] || fellesByAnchor[a.navn];
    const personHtml = fs ? `<div class="strong-personer">
      ${fs.personer.map(p => `${p.power ? "👑 " : "👤 "}<b>${esc(p.navn)}</b> — ${esc(p.rolle_lead)} hos ${esc(l.navn)}, ${esc(p.rolle_anker)} hos ${esc(a.navn)}`).join("<br>")}
    </div>` : "";
    const sizeBadge = `<span class="strong-size">${a.ansatte || 0} ans.</span>`;
    return `<div class="strong-anchor">
      <div class="strong-anchor-top">
        <span class="anchor-name">${anchorLink(a.navn, a.orgnr)}</span>
        ${sizeBadge}
        <span class="strong-anchor-tags">${tags}</span>
      </div>
      ${personHtml}
      ${anchorActionsBar(l.orgnr, a.orgnr)}
    </div>`;
  }

  const bySigType = {};
  singleAnchors.forEach(a => {
    const t = [...a.signalTypes][0];
    if (!bySigType[t]) bySigType[t] = [];
    bySigType[t].push(a);
  });
  const orderedTypes = Object.keys(bySigType).sort((x, y) => (SIGNAL_WEIGHTS_JS[y] || 0) - (SIGNAL_WEIGHTS_JS[x] || 0));

  let connectionsHtml = "";
  if (anchorList.length === 0 && ankerless.length === 0) {
    connectionsHtml = `<p class="muted">Ingen signaler registrert. Kjør <b>Full re-analyse</b>.</p>`;
  }
  if (strongAnchors.length > 0) {
    connectionsHtml += `<div class="strong-section">
      <div class="strong-section-head">
        <h3>Sterke treff</h3>
        <span class="strong-count">${strongAnchors.length}</span>
      </div>
      ${strongAnchors.map(strongAnchorRow).join("")}
    </div>`;
  }
  orderedTypes.forEach(t => {
    const sortedAnchors = [...bySigType[t]].sort((a, b) => (b.ansatte || 0) - (a.ansatte || 0));
    connectionsHtml += `<div class="signal-section">
      <h4><span class="sig-tag t-${t}">${SIGNAL_LABELS[t] || t}</span> (${sortedAnchors.length})</h4>
      <ul class="signal-anchor-list">
        ${sortedAnchors.map(a => {
          const detRaw = a.details[t];
          let det = detRaw;
          if (
            (t === "felles_styreleder" || t === "felles_styremedlem") &&
            (fellesByAnchor[a.orgnr] || fellesByAnchor[a.navn])
          ) {
            const fs = fellesByAnchor[a.orgnr] || fellesByAnchor[a.navn];
            const rich = formatFellesStyreExplainLine(l.navn, a.navn, fs);
            if (rich) det = rich;
          }
          const size = `<span class="small-muted">(${a.ansatte || 0} ans.)</span>`;
          const detail = det ? ` <span class="small-muted">— ${esc(det)}</span>` : "";
          return `<li class="signal-anchor-li">
            <div class="signal-anchor-row">
              <div class="signal-anchor-text"><b>${anchorLink(a.navn, a.orgnr)}</b> ${size}${detail}</div>
              ${anchorActionsBar(l.orgnr, a.orgnr)}
            </div>
          </li>`;
        }).join("")}
      </ul>
    </div>`;
  });
  if (ankerless.length > 0) {
    connectionsHtml += `<div class="signal-section">
      <h4>Andre signaler</h4>
      <ul>
        ${ankerless.map(s => `<li><span class="sig-tag t-${s.type}">${SIGNAL_LABELS[s.type] || s.type}</span>${s.detail ? ` <small>${esc(s.detail)}</small>` : ''}</li>`).join('')}
      </ul>
    </div>`;
  }

  const b = l.score_breakdown || {};
  const foldingCombo = leadHasBransjeGeoCombo(l);
  const geoPostnrDistancesHtml = formatPostnrAnchorDistancesHtml(l);
  const skipBreakdown = new Set();
  let bundleRowHtml = "";
  if (foldingCombo) {
    skipBreakdown.add("samme_bransje");
    skipBreakdown.add("combo_bonus");
    skipBreakdown.add("combo_kind");
    skipBreakdown.add(b.combo_kind === "postnr" ? "nabobedrift_postnummer" : "nabobedrift_kommune");
    const bundlePts = bransjeGeoComboPoints(l);
    const bundleLbl = bransjeGeoComboShortLabel(l);
    const sub = l.geo_detail ? `<br><small class="small-muted">${esc(l.geo_detail)}</small>` : "";
    bundleRowHtml = `<b>${esc(bundleLbl)}</b><span>+${bundlePts} poeng${sub}</span>`;
  }

  const restEntries = [];
  for (const [t, w] of Object.entries(b)) {
    if (skipBreakdown.has(t)) continue;
    if (t === "combo_kind" || typeof w !== "number") continue;
    restEntries.push({ t, w });
  }
  restEntries.sort((x, y) => (SIGNAL_WEIGHTS_JS[y.t] || 0) - (SIGNAL_WEIGHTS_JS[x.t] || 0));
  const breakRows = [];
  if (bundleRowHtml) breakRows.push(bundleRowHtml);
  for (const { t, w } of restEntries) {
    const lbl = SCORE_BREAKDOWN_LABELS[t] || SIGNAL_LABELS[t] || t;
    breakRows.push(`<b>${esc(lbl)}</b><span>+${w} poeng</span>`);
  }

  const breakSection =
    b && Object.keys(b).length
      ? `<div class="detail-section">
         <h3>Score-fordeling</h3>
         <p class="small-muted" style="margin:0 0 8px">Råpoeng per signal (vekter i innstillinger). Totalscore er råsummen (avrundet, maks 100) pluss eventuelle synergy-tillegg — samme tallskala som vektene, så f.eks. bare kommune-treff gir typisk kommune-vekten som score. Tall i parentes ved en signaloverskrift (f.eks. Kommune (79)) er antall kundeankre med treff; hver signaltype teller maks én råvekt i summen, ikke 79×.</p>
         <div class="detail-grid">
           ${breakRows.join("")}
           <b class="score-total-label">Total score</b>
           <span class="score-total-value">${l.score} av 100</span>
         </div>
       </div>`
      : "";

  const st = l.status || "new";
  const sc = l.score >= 50 ? "score-high" : l.score >= 25 ? "score-mid" : "score-low";
  const locLine = [l.postnummer, l.poststed].filter(Boolean).join(" ").trim();
  const locBits = [locLine, l.kommune].filter(Boolean);
  const locChip = locBits.length
    ? `<span class="detail-chip detail-chip-muted">${esc(locBits.join(" · "))}</span>`
    : "";
  let geoChip = "";
  if (foldingCombo) {
    geoChip = `<span class="detail-hero-combo-slot">${globalBransjeGeoComboPillForLead(l)}</span>`;
  } else if (l.geo_label) {
    geoChip = `<span class="detail-chip detail-chip-geo g-${esc(l.geo_tier)}" title="${esc(l.geo_detail || "")}">${esc(l.geo_label)}</span>`;
  }
  const signalPillsRow =
    (l.signals && l.signals.length)
      ? `<div class="detail-hero-signals sig-list sig-list--like-table">${buildLeadSignalPillsHtml(l, { omitGlobalComboPill: !!foldingCombo })}</div>`
      : "";
  const hero = `<div class="detail-hero detail-hero--compact">
    <div class="detail-hero-chips">
      <span class="detail-chip detail-chip-score score-cell ${sc}">${l.score}<span class="detail-chip-score-label">score</span></span>
      ${l.antallAnsatte ? `<span class="detail-chip">${l.antallAnsatte} ansatte</span>` : ""}
      <span class="detail-chip detail-chip--status status-${st}">${esc(STATUS_LABELS[st] || st)}</span>
      ${geoChip}
      ${locChip}
    </div>
    ${signalPillsRow}
  </div>`;

  $("detail-body").innerHTML = `
    ${hero}
    <div class="detail-section">
      <h3>Selskapsinfo</h3>
      <div class="detail-grid">
        <b>Org.nr</b><span>${l.orgnr}</span>
        <b>Adresse</b><span>${esc(l.adresse || '')}, ${l.postnummer || ''} ${esc(l.poststed || '')}</span>
        <b>Geo (mot kunde)</b><span class="selskap-geo-block">${
          foldingCombo
            ? `<span class="selskap-geo-combo-slot">${globalBransjeGeoComboPillForLead(l)}</span>` +
              (l.geo_detail ? `<div class="small-muted">${esc(l.geo_detail)}</div>` : "") +
              `<div>${formatGeoscoreLineHtml(l)}</div>${geoPostnrDistancesHtml}`
            : l.geo_label
              ? `<span class="detail-chip-inline g-${esc(l.geo_tier)}">${esc(l.geo_label)}</span>` +
                (l.geo_detail ? `<div class="small-muted">${esc(l.geo_detail)}</div>` : "") +
                `<div>${formatGeoscoreLineHtml(l)}</div>${geoPostnrDistancesHtml}`
              : '<span class="small-muted">—</span>'
        }</span>
        <b>Bransje</b><span>${esc(naceLabel(l.naeringskode1))} <small class="small-muted">(${esc(l.naeringskode1 || '')} – ${esc(l.nace_beskr || '')})</small></span>
        <b>Ansatte</b><span>${l.antallAnsatte || 0}${l.vekst_pct ? ` <span class="success-text" style="font-weight:700">📈 +${l.vekst_pct}%</span>` : ''}</span>
        <b>Telefon</b><span>${esc(l.telefon || '—')}</span>
        <b>E-post</b><span>${esc(l.epost || '—')}</span>
        <b>Hjemmeside</b><span>${l.hjemmeside ? `<a href="${esc(l.hjemmeside)}" target="_blank">${esc(l.hjemmeside)}</a>` : '—'}</span>
      </div>
    </div>
    <div class="detail-section">
      <h3>Hvordan er ${esc(l.navn)} knyttet til kundene dine?</h3>
      ${connectionsHtml}
    </div>
    ${breakSection}
  `;
  $("modal-detail").hidden = false;
}

async function updateStatus(orgnr, status) {
  const key = normOrgnr(orgnr);
  if (["vunnet", "eksisterende_kunde", "datterselskap"].includes(status)) {
    const lead = allLeads.find(x => normOrgnr(x.orgnr) === key);
    promote(orgnr, lead ? lead.navn : "", status);
    return;
  }
  await fetchJSON(`/api/leads/${orgnr}/status`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({status}),
  });
  const l = allLeads.find(x => normOrgnr(x.orgnr) === key);
  if (l) l.status = status;
  renderTabs();
  render();
}

async function openLink(url) {
  const data = await fetchJSON(url);
  const target = data.url || data.opened;
  if (target) window.open(target, "_blank", "noopener");
}

function openLinkedIn(orgnr, name) {
  $("linkedin-title").textContent = `LinkedIn: ${name}`;
  $("modal-linkedin").hidden = false;
  document.querySelectorAll("#modal-linkedin .li-buttons button").forEach(b => {
    b.onclick = async () => {
      const data = await fetchJSON(`/api/leads/${orgnr}/linkedin/${b.dataset.role}`);
      const target = data.url || data.opened;
      if (target) window.open(target, "_blank", "noopener");
      closeModal("modal-linkedin");
    };
  });
}

async function fetchProffData(orgnr, name) {
  $("proff-name").textContent = name;
  $("proff-result").textContent = "Henter styre fra Brønnøysund + nøkkeltall fra Proff...";
  $("modal-proff").hidden = false;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 25000);
    const r = await fetch(`/api/leads/${orgnr}/proff-data`, {method: "POST", signal: ctrl.signal});
    clearTimeout(timer);
    const data = await r.json();
    $("proff-result").textContent = formatProffData(data.proff);
  } catch (e) {
    $("proff-result").textContent = `⚠️ Henting feilet. Bruk "P"-knappen for å åpne Proff.no manuelt.\n${e.message || e}`;
  }
}

function formatProffData(p) {
  if (!p) return "Ingen data.";
  let out = "";
  const hasRoller = p.roller && p.roller.length;
  const fin = ["driftsinntekter", "driftsresultat", "resultat_for_skatt", "egenkapital", "eiendeler"];
  const hasFin = fin.some(k => p[k]);

  if (hasRoller) {
    out += "═══ STYRE OG LEDELSE (Brønnøysund) ═══\n\n";
    p.roller.forEach(r => out += `  ${(r.rolle || '').padEnd(28)} ${r.navn}\n`);
    out += "\n";
  } else if (p.roller_error) {
    out += `⚠️ ${p.roller_error}\n\n`;
  }
  if (hasFin) {
    out += "═══ NØKKELTALL (Proff.no) ═══\n\n";
    fin.forEach(k => { if (p[k]) out += `  ${k.replace(/_/g,' ').padEnd(22)} ${p[k]}\n`; });
    out += "\n";
  }
  if (!hasRoller && !hasFin && p.proff_status) out += `${p.proff_status}\n\n`;
  if (p.proff_url) out += `→ Åpne i nettleser: ${p.proff_url}\n`;
  return out || JSON.stringify(p, null, 2);
}

/** Åpner «Vunnet»-flyten med valgt morselskap (kun når treff er importert som kunde). */
async function promoteLeadUnderAnchor(leadOrgnr, parentOrgnr) {
  const lo = normOrgnr(leadOrgnr);
  const po = normOrgnr(parentOrgnr);
  if (!(allCustomers || []).length && typeof loadCustomers === "function") {
    try {
      await loadCustomers();
    } catch (e) {
      console.error("loadCustomers (før promote):", e);
    }
  }
  const lead = allLeads.find(x => normOrgnr(x.orgnr) === lo);
  let parent = (allCustomers || []).find(c => normOrgnr(c.orgnr) === po);
  if (!parent && typeof loadCustomers === "function") {
    try {
      await loadCustomers();
    } catch (e) {
      console.error("loadCustomers (retry promote):", e);
    }
    parent = (allCustomers || []).find(c => normOrgnr(c.orgnr) === po);
  }
  if (!lead) return;
  if (!parent) {
    alert(
      "Fant ikke moderbedriften i kundelisten for org.nr " + (parentOrgnr || "(ukjent)") + ". " +
      "Åpne kundefanen eller oppdater siden og prøv igjen.",
    );
    return;
  }
  promote(leadOrgnr, lead.navn, "datterselskap");
  parentSelected = { orgnr: parentOrgnr, navn: parent.navn };
  $("parent-query").value = parent.navn;
  $("parent-selected").textContent = "✓ Knyttes til: " + parent.navn;
  $("parent-suggestions").hidden = true;
  $("parent-suggestions").innerHTML = "";
  closeModal("modal-cust-detail");
}

/** Kobler eksisterende kundekort for lead-org.nr under treff-kunden (PATCH). */
async function linkLeadCustomerUnderParent(leadOrgnr, parentOrgnr) {
  const lo = normOrgnr(leadOrgnr);
  const po = normOrgnr(parentOrgnr);
  const child = (allCustomers || []).find(c => normOrgnr(c.orgnr) === lo);
  const parent = (allCustomers || []).find(c => normOrgnr(c.orgnr) === po);
  if (!child || !parent) {
    alert("Begge selskap må allerede være kunder. Bruk «Vunnet · datter her» for å importere leadet som datter.");
    return;
  }
  if (child.parent_orgnr && child.parent_orgnr !== parentOrgnr) {
    if (!confirm(`«${child.navn}» har allerede en moderbedrift. Erstatte med «${parent.navn}»?`)) return;
  } else if (!confirm(`Knytte «${child.navn}» som datterselskap av «${parent.navn}»?`)) {
    return;
  }
  try {
    await fetchJSON(`/api/customers/${leadOrgnr}`, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({parent_orgnr: parentOrgnr}),
    });
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    closeModal("modal-detail");
    closeModal("modal-cust-detail");
    await openCustomerDetailModal(leadOrgnr);
  } catch (e) {
    alert("Kunne ikke knytte: " + (e.message || e));
  }
}

function promote(orgnr, name, mode) {
  currentLead = orgnr;
  promoteMode = mode || "vunnet";
  parentSelected = null;
  $("parent-selected").textContent = "";
  $("parent-query").value = "";
  $("parent-suggestions").hidden = true;

  const titles = {
    "vunnet": "Markér som vunnet",
    "eksisterende_kunde": "Markér som eksisterende kunde",
    "datterselskap": "Markér som datterselskap/underselskap",
  };
  $("modal-promote").querySelector("h2").textContent = titles[promoteMode];
  $("promote-name").textContent = name;
  const isChild = promoteMode === "datterselskap";
  $("promote-abo").value = promoteMode === "vunnet" ? "50" : "";
  $("promote-abo").placeholder = promoteMode === "vunnet" ? "Antall abonnementer" : "Antall abonnementer (hvis kjent)";
  $("promote-abo").style.display = isChild ? "none" : "";
  $("parent-picker").hidden = !isChild;
  $("modal-promote").hidden = false;
  if (promoteMode === "datterselskap") setTimeout(() => $("parent-query").focus(), 100);
}

let parentTimer = null;
$("parent-query").addEventListener("input", () => {
  clearTimeout(parentTimer);
  const q = $("parent-query").value.trim();
  if (q.length < 2) { $("parent-suggestions").hidden = true; return; }
  parentTimer = setTimeout(async () => {
    const data = await fetchJSON(`/api/customers/search?q=${encodeURIComponent(q)}`);
    const sugg = $("parent-suggestions");
    if (!data.results || !data.results.length) { sugg.hidden = true; return; }
    sugg.innerHTML = data.results.map(r =>
      `<div data-orgnr="${r.orgnr}" data-navn="${esc(r.navn)}">
         <b>${esc(r.navn)}</b> <small>${r.orgnr || ''} · ${esc(r.kommune || '')}</small>
       </div>`).join("");
    sugg.hidden = false;
    sugg.querySelectorAll("div").forEach(d => {
      d.onclick = () => {
        parentSelected = {orgnr: d.dataset.orgnr, navn: d.dataset.navn};
        $("parent-query").value = d.dataset.navn;
        $("parent-selected").textContent = `✓ Knyttes til: ${d.dataset.navn}`;
        sugg.hidden = true;
      };
    });
  }, 250);
});

$("btn-promote-confirm").addEventListener("click", async () => {
  if (promoteMode === "datterselskap" && !parentSelected) {
    alert("Velg morselskap fra kundelisten først.");
    return;
  }
  const abo = parseInt($("promote-abo").value || "0");
  const rerun = $("promote-rerun").checked;
  const body = {abonnementer: abo, auto_analyze: rerun, mode: promoteMode};
  if (parentSelected) {
    body.parent_orgnr = parentSelected.orgnr;
    body.parent_navn = parentSelected.navn;
  }
  const pr = await fetchJSON(`/api/leads/${currentLead}/promote`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  closeModal("modal-promote");
  if (pr.targeted_analysis_queued) pollAnalysis();
  await loadLeads();
  await loadStats();
});

let linkLeadOrgnr = null;
let linkLeadSelected = null;

function openLinkParent(orgnr, navn) {
  linkLeadOrgnr = orgnr;
  linkLeadSelected = null;
  $("link-name").textContent = navn;
  $("link-query").value = "";
  $("link-suggestions").innerHTML = "";
  $("link-suggestions").hidden = true;
  $("link-selected").textContent = "";
  const key = normOrgnr(orgnr);
  const cur = allLeads.find(x => normOrgnr(x.orgnr) === key);
  $("link-current").textContent = cur && cur.parent_lead_navn
    ? `Nåværende kobling: ${cur.parent_lead_navn}` : "";
  $("modal-link-parent").hidden = false;
  setTimeout(() => $("link-query").focus(), 50);
}

let linkTimer = null;
$("link-query").addEventListener("input", () => {
  clearTimeout(linkTimer);
  const q = $("link-query").value.trim();
  if (q.length < 2) { $("link-suggestions").hidden = true; return; }
  linkTimer = setTimeout(async () => {
    const data = await fetchJSON(`/api/leads/search?q=${encodeURIComponent(q)}`);
    const sugg = $("link-suggestions");
    const filtered = (data.results || []).filter(r => r.orgnr !== linkLeadOrgnr);
    if (!filtered.length) { sugg.hidden = true; return; }
    sugg.innerHTML = filtered.map(r =>
      `<div data-orgnr="${r.orgnr}" data-navn="${esc(r.navn)}">
         <b>${esc(r.navn)}</b> <small>${r.orgnr || ''} · ${esc(r.kommune || '')} · score ${r.score}</small>
       </div>`).join("");
    sugg.hidden = false;
    sugg.querySelectorAll("div").forEach(d => {
      d.onclick = () => {
        linkLeadSelected = {orgnr: d.dataset.orgnr, navn: d.dataset.navn};
        $("link-query").value = d.dataset.navn;
        $("link-selected").textContent = `✓ Knyttes til: ${d.dataset.navn}`;
        sugg.hidden = true;
      };
    });
  }, 250);
});

$("btn-link-confirm").addEventListener("click", async () => {
  if (!linkLeadSelected) { alert("Velg et hovedselskap først."); return; }
  await fetchJSON(`/api/leads/${linkLeadOrgnr}/parent-lead`, {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({parent_orgnr: linkLeadSelected.orgnr, parent_navn: linkLeadSelected.navn}),
  });
  closeModal("modal-link-parent");
  await loadLeads();
});

$("btn-link-clear").addEventListener("click", async () => {
  await fetchJSON(`/api/leads/${linkLeadOrgnr}/parent-lead`, {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({}),
  });
  closeModal("modal-link-parent");
  await loadLeads();
});
