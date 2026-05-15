// =====================================================================
// settings.js — Innstillinger: enkle forhåndsvalg + valgfri finjustering.
// Krever core.js, progress.js (showProgress/pollProgress).
// =====================================================================

$("btn-settings").addEventListener("click", async () => {
  const s = await fetchJSON("/api/settings");
  renderSettings(s);
  $("modal-settings").hidden = false;
});

const THRESHOLD_FIELDS = [
  { key: "small_anchor_threshold", label: "Lite-anker-grense (ansatte)", kind: "int", max: 1000 },
  { key: "small_anchor_factor", label: "Dempningsfaktor (% av full vekt)", kind: "int", max: 100 },
  { key: "min_lead_ansatte", label: "Minimum ansatte for leads", kind: "int", max: 1000 },
  { key: "min_anchor_ansatte", label: "Minimum ansatte for ankere (0 = av)", kind: "int", max: 1000 },
  { key: "nabobedrift_postnr_distance_max_m", label: "Maks meter for postnr-signal (lineær avtagende vekt)", kind: "int", max: 100000 },
  {
    key: "geo_postnr_addr_mult",
    label: "Same adresse: multiplikator mot «Næring samme postnr» (1–2,5; høyere = tyngre adressetreff)",
    kind: "float",
    min: 1,
    max: 2.5,
    step: 0.02,
    fallback: 1.38,
  },
  {
    key: "geo_kommune_vs_postnr_cap",
    label: "Kommune maks som andel av sterkest postnr/adresse-nivå (0,25–1)",
    kind: "float",
    min: 0.25,
    max: 1,
    step: 0.02,
    fallback: 0.88,
  },
  { key: "score_boost_combo_points", label: "Ekstra score-poeng ved kryss (bransje+geo)", kind: "int", max: 25 },
  { key: "score_boost_multi_points", label: "Ekstra score-poeng ved flere ankere (2+ treff)", kind: "int", max: 25 },
];

const OWNERSHIP_PCT_STEP = 0.1;
const PRESET_WEIGHTS = {
  balanced: {
    felles_styreleder: 26,
    felles_styremedlem: 18,
    samme_bransje: 14,
    nabobedrift_kommune: 8,
    selskap_i_vekst: 8,
    nabobedrift_postnummer: 11,
    kunde_morselskap: 22,
    kunde_konserntre: 18,
    kunde_aksjeeierbok: 20,
    combo_bransje_postnr: 18,
    combo_bransje_kommune: 12,
    multi_anchor_2: 10,
    multi_anchor_3: 18,
  },
  eierskap: {
    felles_styreleder: 20,
    felles_styremedlem: 14,
    samme_bransje: 12,
    nabobedrift_kommune: 6,
    selskap_i_vekst: 7,
    nabobedrift_postnummer: 8,
    kunde_morselskap: 30,
    kunde_konserntre: 26,
    kunde_aksjeeierbok: 28,
    combo_bransje_postnr: 14,
    combo_bransje_kommune: 9,
    multi_anchor_2: 9,
    multi_anchor_3: 16,
  },
  styre: {
    felles_styreleder: 34,
    felles_styremedlem: 26,
    samme_bransje: 12,
    nabobedrift_kommune: 6,
    selskap_i_vekst: 7,
    nabobedrift_postnummer: 7,
    kunde_morselskap: 16,
    kunde_konserntre: 12,
    kunde_aksjeeierbok: 14,
    combo_bransje_postnr: 14,
    combo_bransje_kommune: 9,
    multi_anchor_2: 9,
    multi_anchor_3: 16,
  },
  naerhet: {
    felles_styreleder: 20,
    felles_styremedlem: 14,
    samme_bransje: 20,
    nabobedrift_kommune: 12,
    selskap_i_vekst: 7,
    nabobedrift_postnummer: 14,
    kunde_morselskap: 16,
    kunde_konserntre: 12,
    kunde_aksjeeierbok: 14,
    combo_bransje_postnr: 20,
    combo_bransje_kommune: 14,
    multi_anchor_2: 11,
    multi_anchor_3: 20,
  },
};

const PRESET_CHIPS = [
  { id: "balanced", title: "Balansert", hint: "Blanding av alle treff — anbefalt start." },
  { id: "eierskap", title: "Mer eierskap", hint: "Hever konsern, morselskap og aksjonær." },
  { id: "styre", title: "Mer styreverv", hint: "Hever felles styreleder og styremedlem." },
  { id: "naerhet", title: "Mer nærhet", hint: "Hever bransje, kommune og postnummer." },
];

function applyPresetWeights(presetId) {
  const pw = PRESET_WEIGHTS[presetId] || PRESET_WEIGHTS.balanced;
  document.querySelectorAll('#weights-grid input[data-kind="weight"]').forEach(el => {
    const k = el.dataset.key;
    if (!k || pw[k] == null) return;
    const v = parseInt(String(pw[k]), 10) || 0;
    el.value = String(v);
    el.setAttribute("aria-valuenow", el.value);
    syncWeightOut(el);
  });
  const nums = Array.from(document.querySelectorAll('#weights-grid input[data-kind="weight"]')).map(
    el => parseInt(el.value || "0", 10) || 0,
  );
  const sliderMax = Math.max(WEIGHT_SLIDER_MAX, ...nums, 0);
  $("weights-grid").dataset.sliderMax = String(sliderMax);
  refreshSliderMaxes();
}

function highlightMatchingPresetChip() {
  const modal = $("modal-settings");
  if (!modal) return;
  const cur = readWeightState();
  let match = null;
  for (const { id } of PRESET_CHIPS) {
    const pw = PRESET_WEIGHTS[id];
    const ok = Object.keys(pw).every(k => (cur[k] || 0) === pw[k]);
    if (ok) {
      match = id;
      break;
    }
  }
  modal.querySelectorAll(".preset-chip").forEach(b => {
    b.classList.toggle("preset-chip--active", match != null && b.dataset.preset === match);
  });
}

$("modal-settings").addEventListener("click", ev => {
  const chip = ev.target.closest(".preset-chip");
  if (!chip || !$("modal-settings").contains(chip)) return;
  ev.preventDefault();
  const id = chip.dataset.preset;
  if (!id || !PRESET_WEIGHTS[id]) return;
  applyPresetWeights(id);
  $("modal-settings").querySelectorAll(".preset-chip").forEach(b => b.classList.remove("preset-chip--active"));
  chip.classList.add("preset-chip--active");
});

/** Øvre grense for HTML-slider (lagrede vekter kan være høyere hvis innlastet fra fil). */
const WEIGHT_SLIDER_MAX = 500;

function readWeightState() {
  const w = {};
  document.querySelectorAll('#weights-grid input[data-kind="weight"]').forEach(i => {
    w[i.dataset.key] = parseInt(i.value || "0", 10) || 0;
  });
  return w;
}

/** Les vekter til lagring; åpner «Finjuster»-details ved behov (noen nettlesere er ustabile når den er lukket). */
function readWeightStateForSave() {
  let w = readWeightState();
  if (Object.keys(w).length) return w;
  const det = document.querySelector("#weights-grid details.settings-weights-details");
  if (det && !det.open) {
    det.open = true;
    w = readWeightState();
  }
  return w;
}

/** Fallback når terskel-felt ikke finnes (må matche scoring.py-standard). */
const GEO_SCORE_MODEL = { postnrAddrMult: 1.38, kommuneVsPostnrCap: 0.88 };

function readGeoModelForTotal() {
  let postnrAddrMult = GEO_SCORE_MODEL.postnrAddrMult;
  let kommuneVsPostnrCap = GEO_SCORE_MODEL.kommuneVsPostnrCap;
  const g1 = document.querySelector('#thresholds-grid input[data-key="geo_postnr_addr_mult"]');
  const g2 = document.querySelector('#thresholds-grid input[data-key="geo_kommune_vs_postnr_cap"]');
  if (g1) {
    const x = parseFloat(g1.value);
    if (Number.isFinite(x)) postnrAddrMult = Math.max(1, Math.min(2.5, x));
  }
  if (g2) {
    const x = parseFloat(g2.value);
    if (Number.isFinite(x)) kommuneVsPostnrCap = Math.max(0.25, Math.min(1, x));
  }
  return { postnrAddrMult, kommuneVsPostnrCap };
}

/** Samme «teoretisk maks råsum» som i scoring.py (sum signalvekter + største kryss + største multi). */
function totalFromWeights(w, geo) {
  const ADDR = geo?.postnrAddrMult ?? GEO_SCORE_MODEL.postnrAddrMult;
  const CAP = geo?.kommuneVsPostnrCap ?? GEO_SCORE_MODEL.kommuneVsPostnrCap;
  const baseMax = Object.keys(SIGNAL_LABELS).reduce((s, k) => {
    let v = w[k] || 0;
    if (k === "nabobedrift_postnummer") {
      v *= ADDR;
    } else if (k === "nabobedrift_kommune") {
      const wp = (w.nabobedrift_postnummer || 0) * ADDR;
      const wk = w[k] || 0;
      v = wp > 0 ? Math.min(wk, wp * CAP) : wk;
    }
    return s + v;
  }, 0);
  const comboMax = Math.max(w.combo_bransje_postnr || 0, w.combo_bransje_kommune || 0);
  const multiMax = Math.max(w.multi_anchor_2 || 0, w.multi_anchor_3 || 0);
  return baseMax + comboMax + multiMax;
}

function syncWeightOut(el) {
  const row = el.closest(".weight-slider-row");
  if (!row) return;
  const out = row.querySelector(".weight-slider-out");
  if (out) out.textContent = String(parseInt(el.value || "0", 10) || 0);
}

function syncAllWeightOutputs() {
  document.querySelectorAll('#weights-grid input[data-kind="weight"]').forEach(el => {
    syncWeightOut(el);
    el.setAttribute("aria-valuenow", el.value);
  });
}

function resetWeightSliderBounds() {
  const grid = $("weights-grid");
  const m = parseInt(grid?.dataset?.sliderMax || String(WEIGHT_SLIDER_MAX), 10) || WEIGHT_SLIDER_MAX;
  document.querySelectorAll('#weights-grid input[data-kind="weight"]').forEach(el => {
    el.min = "0";
    el.max = String(m);
    el.setAttribute("aria-valuemin", "0");
    el.setAttribute("aria-valuemax", String(m));
  });
}

function onWeightSliderInput(ev) {
  const el = ev.target;
  if (!el.matches("input.weight-slider[data-kind=\"weight\"]")) return;
  const maxV = parseInt(el.max || String(WEIGHT_SLIDER_MAX), 10) || WEIGHT_SLIDER_MAX;
  let v = parseInt(el.value || "0", 10) || 0;
  if (v < 0) v = 0;
  if (v > maxV) v = maxV;
  el.value = String(v);
  el.setAttribute("aria-valuenow", el.value);
  syncWeightOut(el);
  updateMaxTotal();
  highlightMatchingPresetChip();
}

function onWeightSliderChange(ev) {
  const el = ev.target;
  if (!el.matches("input.weight-slider[data-kind=\"weight\"]")) return;
  syncWeightOut(el);
  updateMaxTotal();
  highlightMatchingPresetChip();
}

function refreshSliderMaxes() {
  resetWeightSliderBounds();
  syncAllWeightOutputs();
  updateMaxTotal();
}

function weightSliderRow(key, label, v, sliderMax) {
  const raw = parseInt(v, 10) || 0;
  const maxV = sliderMax || WEIGHT_SLIDER_MAX;
  const safe = Math.max(0, Math.min(maxV, raw));
  return (
    `<label for="w-${key}">${label}</label>` +
    `<div class="weight-slider-row">` +
    `<input type="range" class="weight-slider" id="w-${key}" data-key="${key}" data-kind="weight" ` +
    `value="${safe}" min="0" max="${maxV}" step="1" aria-valuemin="0" aria-valuemax="${maxV}" aria-valuenow="${safe}">` +
    `<span class="weight-slider-out" aria-hidden="true">${safe}</span>` +
    `</div>`
  );
}

function _ownershipRoundStep(x) {
  return Math.round(x / OWNERSHIP_PCT_STEP) * OWNERSHIP_PCT_STEP;
}

function _fmtOwnershipPct(x) {
  const n = Number(x);
  if (!Number.isFinite(n)) return "0";
  const r = Math.round(n * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

function buildOwnershipDualRangeHtml(lo, hi) {
  return (
    `<label class="ownership-dual-range-label" style="grid-column: 1 / -1">Kunde som aksjonær — andel i bok som teller</label>` +
    `<div class="ownership-dual-range-host" style="grid-column: 1 / -1">` +
    `<div class="ownership-dual-range" id="ownership-dual-range">` +
    `<div class="ownership-dual-range__rails" aria-hidden="true">` +
    `<span class="ownership-dual-range__track"></span>` +
    `<span class="ownership-dual-range__fill" id="ownership-pct-fill"></span>` +
    `</div>` +
    `<input type="range" class="ownership-dual-range__min" id="ownership-pct-min" min="0" max="100" step="${OWNERSHIP_PCT_STEP}" value="${lo}" ` +
    `data-key="kunde_aksjeeierbok_min_pct" data-kind="threshold" data-numeric="float" aria-label="Minimum aksjonærandel i prosent" />` +
    `<input type="range" class="ownership-dual-range__max" id="ownership-pct-max" min="0" max="100" step="${OWNERSHIP_PCT_STEP}" value="${hi}" ` +
    `data-key="kunde_aksjeeierbok_max_pct" data-kind="threshold" data-numeric="float" aria-label="Maksimum aksjonærandel i prosent" />` +
    `</div>` +
    `<p class="ownership-dual-range__readout" id="ownership-pct-readout" aria-live="polite"></p>` +
    `<p class="settings-grid-note ownership-dual-range-hint">Dra venstre krok for minimum, høyre for maksimum. Mellom dem telles andelen i signaler og på kundekort.</p>` +
    `</div>`
  );
}

function syncOwnershipDualRangeVisual() {
  const minEl = $("ownership-pct-min");
  const maxEl = $("ownership-pct-max");
  const fill = $("ownership-pct-fill");
  const readout = $("ownership-pct-readout");
  if (!minEl || !maxEl || !fill || !readout) return;
  const step = OWNERSHIP_PCT_STEP;
  let lo = _ownershipRoundStep(parseFloat(minEl.value) || 0);
  let hi = _ownershipRoundStep(parseFloat(maxEl.value) || 100);
  const active = document.activeElement;
  if (lo < 0) lo = 0;
  if (hi > 100) hi = 100;
  if (lo > hi - step) {
    if (active === minEl) hi = Math.min(100, lo + step);
    else if (active === maxEl) lo = Math.max(0, hi - step);
    else lo = Math.max(0, hi - step);
  }
  if (hi < lo + step) hi = Math.min(100, lo + step);
  minEl.value = String(lo);
  maxEl.value = String(hi);
  const gap = hi - lo;
  minEl.style.zIndex = gap < 12 ? "3" : "2";
  maxEl.style.zIndex = gap < 12 ? "2" : "3";
  fill.style.left = `${lo}%`;
  fill.style.width = `${Math.max(0, hi - lo)}%`;
  readout.textContent = `${_fmtOwnershipPct(lo)} % – ${_fmtOwnershipPct(hi)} %`;
}

function bindOwnershipDualRange() {
  const minEl = $("ownership-pct-min");
  const maxEl = $("ownership-pct-max");
  if (!minEl || !maxEl) return;
  const go = () => syncOwnershipDualRangeVisual();
  minEl.addEventListener("input", go);
  maxEl.addEventListener("input", go);
  minEl.addEventListener("change", go);
  maxEl.addEventListener("change", go);
  syncOwnershipDualRangeVisual();
}

function renderSettings(s) {
  const w0 = s.weights || {};
  const nums = Object.values(w0).map(x => parseInt(x, 10) || 0).filter(n => n >= 0);
  const sliderMax = Math.max(WEIGHT_SLIDER_MAX, ...nums, 0);
  const signalRows = Object.entries(SIGNAL_LABELS)
    .map(([key, label]) => weightSliderRow(key, label, s.weights[key] ?? 0, sliderMax))
    .join("");
  const divider = `<label class="section-divider">Kryss og flere ankere</label>`;
  const bonusRows = Object.entries(BONUS_LABELS)
    .map(([key, label]) => weightSliderRow(key, label, s.weights[key] ?? 0, sliderMax))
    .join("");
  const presetBar =
    `<p class="settings-simple-lead muted">Vist lead-score er råsummen av treffene (maks 100), pluss eventuelle synergy-tillegg. Hold pekeren over et forhåndsvalg for kort forklaring.</p>` +
    `<div class="preset-btn-row" role="group" aria-label="Forhåndsvalg for vekting">` +
    PRESET_CHIPS.map(
      ({ id, title, hint }) =>
        `<button type="button" class="secondary preset-chip" data-preset="${id}" title="${escAttr(hint)}">${esc(title)}</button>`,
    ).join("") +
    `</div>` +
    `<details class="settings-weights-details" open>` +
    `<summary>Finjuster hvert signal (valgfritt)</summary>` +
    `<div class="settings-grid-note settings-grid-note--tight">Skyvefeltene er råpoeng per signal. Total lead-score summerer disse (maks 100); kryss og flere ankere kan i tillegg gi faste synergy-poeng (se terskler under).</div>` +
    `<div class="settings-grid">` +
    signalRows +
    divider +
    bonusRows +
    `</div></details>`;
  $("weights-grid").innerHTML = presetBar;
  $("weights-grid").dataset.sliderMax = String(sliderMax);

  const thr = s.thresholds || {};
  const thrRows = THRESHOLD_FIELDS.map(f => {
    const raw = thr[f.key];
    if (f.kind === "float") {
      const fb = f.fallback != null ? f.fallback : 0;
      let v = raw != null && raw !== "" ? Number(raw) : fb;
      if (!Number.isFinite(v)) v = fb;
      v = Math.max(f.min, Math.min(f.max, v));
      const step = f.step != null ? f.step : 0.01;
      return `<label>${f.label}</label><input type="number" data-key="${f.key}" data-kind="threshold" data-numeric="float" value="${v}" min="${f.min}" max="${f.max}" step="${step}">`;
    }
    const v = raw != null && raw !== "" ? parseInt(raw, 10) : 0;
    const vv = Number.isFinite(v) ? v : 0;
    const max = f.key === "small_anchor_factor" ? 100 : f.max;
    return `<label>${f.label}</label><input type="number" data-key="${f.key}" data-kind="threshold" data-numeric="int" value="${vv}" min="0" max="${max}">`;
  }).join("");
  let lo =
    thr.kunde_aksjeeierbok_min_pct != null && thr.kunde_aksjeeierbok_min_pct !== ""
      ? Number(thr.kunde_aksjeeierbok_min_pct)
      : 5;
  let hi =
    thr.kunde_aksjeeierbok_max_pct != null && thr.kunde_aksjeeierbok_max_pct !== ""
      ? Number(thr.kunde_aksjeeierbok_max_pct)
      : 100;
  if (!Number.isFinite(lo)) lo = 5;
  if (!Number.isFinite(hi)) hi = 100;
  lo = Math.max(0, Math.min(100, _ownershipRoundStep(lo)));
  hi = Math.max(0, Math.min(100, _ownershipRoundStep(hi)));
  if (lo > hi - OWNERSHIP_PCT_STEP) lo = hi - OWNERSHIP_PCT_STEP;
  if (hi < lo + OWNERSHIP_PCT_STEP) hi = lo + OWNERSHIP_PCT_STEP;
  const ownershipDual = buildOwnershipDualRangeHtml(lo, hi);
  const thrNote =
    `<div class="settings-grid-note">Endring av aksjonær-intervall bygger eierskapssignaler på nytt ved lagring.</div>`;
  $("thresholds-grid").innerHTML = thrRows + ownershipDual + thrNote;

  document.querySelectorAll("#weights-grid input[data-kind=\"weight\"]").forEach(el => {
    el.addEventListener("input", onWeightSliderInput);
    el.addEventListener("change", onWeightSliderChange);
  });
  document.querySelectorAll("#thresholds-grid input").forEach(i => {
    i.addEventListener("input", updateMaxTotal);
  });
  bindOwnershipDualRange();
  refreshSliderMaxes();
  highlightMatchingPresetChip();
}

function updateMaxTotal() {
  const w = readWeightState();
  const total = totalFromWeights(w, readGeoModelForTotal());
  const el = $("max-total-display");
  const divHtml =
    total > 0
      ? `Teoretisk maks råsum: <strong>${total}</strong> <small>— referanse for sliderne (maks mulig å samle i én lead før tak på 100).</small>`
      : `<strong>0</strong> <small>Velg et forhåndsvalg over, eller åpne «Finjuster» og øk minst én vekt.</small>`;
  el.innerHTML = `<div class="max-total ok">${divHtml}</div>`;
}

/** Synlig tilbakemelding — `alert()` etter `await` blir ofte undertrykt (Safari / stram popup-policy). */
function showLeadmapNotice(text, opts = {}) {
  const isErr = !!opts.error;
  const ms = opts.ms != null ? opts.ms : isErr ? 14000 : 10000;
  let bar = document.getElementById("leadmap-global-notice");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "leadmap-global-notice";
    bar.style.cssText = [
      "position:fixed",
      "bottom:22px",
      "left:50%",
      "transform:translateX(-50%)",
      "max-width:min(560px,94vw)",
      "z-index:10001",
      "padding:14px 18px",
      "border-radius:10px",
      "font-size:14px",
      "line-height:1.4",
      "box-shadow:0 6px 28px rgba(0,0,0,.2)",
      "border:1px solid",
      "font-family:inherit",
      "text-align:left",
    ].join(";");
    document.body.appendChild(bar);
  }
  bar.setAttribute("role", isErr ? "alert" : "status");
  bar.style.background = isErr ? "var(--danger-bg, #3d1515)" : "var(--surface-2, #eef0f3)";
  bar.style.borderColor = isErr ? "var(--danger, #c62828)" : "var(--border-strong, #b8bcc4)";
  bar.style.color = isErr ? "var(--danger-contrast, #fff)" : "var(--text, #1a1d21)";
  bar.textContent = text;
  bar.hidden = false;
  bar.style.display = "block";
  clearTimeout(showLeadmapNotice._t);
  showLeadmapNotice._t = setTimeout(() => {
    bar.hidden = true;
    bar.style.display = "none";
  }, ms);
}

async function onSettingsSaveClick(ev) {
  ev.preventDefault();
  ev.stopPropagation();
  const saveBtn = $("btn-settings-save");
  const weights = readWeightStateForSave();
  if (!Object.keys(weights).length) {
    const errMsg =
      "Kunne ikke lese signalvekter (ingen slider funnet). Lukk vinduet og åpne «Innstillinger» på nytt.";
    showLeadmapNotice(errMsg, { error: true });
    queueMicrotask(() => {
      try {
        alert(errMsg);
      } catch (e) { /* */ }
    });
    return;
  }
  const thresholds = {};
  document.querySelectorAll('#thresholds-grid input[data-kind="threshold"]').forEach(i => {
    const k = i.dataset.key;
    if (i.dataset.numeric === "float") {
      const v = parseFloat(i.value);
      thresholds[k] = Number.isFinite(v) ? v : 0;
    } else {
      thresholds[k] = parseInt(i.value || "0", 10) || 0;
    }
  });
  if (saveBtn) saveBtn.disabled = true;
  showLeadmapNotice("Lagrer innstillinger og teller score på nytt …", { ms: 60000, error: false });
  try {
    const data = await fetchJSON("/api/settings", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({weights, thresholds}),
    });
    await loadLeads();
    closeModal("modal-settings");
    let msg = `Lagret. ${data.rescored || 0} leads fikk ny score (uten ny geokoding).`;
    if (data.removed_below_threshold) msg += ` ${data.removed_below_threshold} leads fjernet (under ny min ansatte for leads).`;
    if (data.removed_small_anchor) msg += ` ${data.removed_small_anchor} leads fjernet (ankre under min ansatte).`;
    showLeadmapNotice(msg, { error: false });
  } catch (ex) {
    const m = ex && ex.message ? ex.message : String(ex);
    const errLine = "Lagring feilet: " + m;
    showLeadmapNotice(errLine + " — sjekk at appen kjører og nettverket er ok.", { error: true });
    queueMicrotask(() => {
      try {
        alert(errLine);
      } catch (e2) { /* */ }
    });
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

(function wireSettingsSave() {
  const saveBtn = $("btn-settings-save");
  if (!saveBtn) {
    console.error("[settings] btn-settings-save mangler — lagring er ikke koblet.");
    return;
  }
  saveBtn.type = "button";
  saveBtn.addEventListener("click", onSettingsSaveClick);
})();

const _btnSettingsReset = $("btn-settings-reset");
if (_btnSettingsReset) {
  _btnSettingsReset.type = "button";
  _btnSettingsReset.addEventListener("click", async () => {
    if (!confirm("Sette alle vekter til «Balansert» (standard)? Lagres til serveren med én gang.")) return;
    await fetchJSON("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ weights: { ...PRESET_WEIGHTS.balanced } }),
    });
    const s = await fetchJSON("/api/settings");
    renderSettings(s);
    if (typeof loadLeads === "function") await loadLeads();
  });
}

// === Heleide leads (aksjeeierbok) → manuelle datre i kundetrær ===
$("btn-promote-whole-owned-leads").addEventListener("click", async () => {
  if (!confirm(
    "Flytte leads som er minst 99 % eid (aksjeeierbok 2024) av et org.nr i kundetreet?\n" +
    "De legges inn som manuelle datre under eieren og fjernes fra lead-listen.\n\n" +
    "Åpner fremdriftsvindu med én gang (kan minimeres). Jobben kjører i bakgrunn.",
  )) return;
  closeModal("modal-settings");
  showProgress("Heleide leads → kundetrær", "/api/import/status", true);
  if (typeof updateHeaderBadge === "function") updateHeaderBadge();
  try {
    const r = await fetchJSON("/api/leads/promote-whole-owned-to-customers", {method: "POST"});
    if (!r.started) {
      closeModal("modal-progress");
      activeJob = null;
      if (typeof updateHeaderBadge === "function") updateHeaderBadge();
      alert(r.error || r.message || "Kunne ikke starte.");
      return;
    }
    if (activeJob) {
      activeJob.total = Math.max(1, Number(r.total) || 0);
      activeJob.current = 0;
      activeJob.progress = "Jobb startet…";
      renderProgressModal();
      updateHeaderBadge();
    }
    pollProgress(async () => {
      await loadCustomers();
      if (!$("view-customers").hidden) renderCustomersTab();
      await loadLeads();
      await loadStats();
    });
  } catch (ex) {
    closeModal("modal-progress");
    activeJob = null;
    if (typeof updateHeaderBadge === "function") updateHeaderBadge();
    alert("Feil: " + (ex && ex.message ? ex.message : ex));
  }
});

$("btn-delete-all").addEventListener("click", async () => {
  if (!confirm("⚠️ Dette sletter ALLE kunder permanent. Er du sikker?")) return;
  if (!confirm("Helt sikker? Denne handlingen kan ikke angres.")) return;
  await fetchJSON("/api/customers/delete-all", {method: "POST"});
  closeModal("modal-settings");
  await loadStats();
  alert("Alle kunder slettet.");
});

// === Dedupliser kunder (samme orgnr → én rad) ===
$("btn-dedupe").addEventListener("click", async () => {
  if (!confirm("Slå sammen alle kunder med samme org.nr til én oppføring?\nVinneren beholder høyeste abonnementer + alle felter.")) return;
  const data = await fetchJSON("/api/customers/deduplicate", {method: "POST"});
  if (data.merged) {
    alert(`✅ ${data.merged} duplikater slått sammen. ${data.remaining} kunder gjenstår.`);
  } else {
    alert("Ingen duplikater funnet.");
  }
  closeModal("modal-settings");
  await loadCustomers();
  if (!$("view-customers").hidden) renderCustomersTab();
  await loadStats();
});

// === Konsern-oversikt (review) ===
$("btn-konsern-overview").addEventListener("click", () => {
  closeModal("modal-settings");
  openKonsernOverview();
});

// === Hent ferskt konsern/datter-data for alle kunder ===
$("btn-refresh-all-related").addEventListener("click", async () => {
  if (!confirm("Hente ferskt konsern/datter-data fra Brønnøysund for ALLE kunder?\nKan ta 2-5 minutter avhengig av antall kunder.")) return;
  const r = await fetchJSON("/api/customers/refresh-all-related", {method: "POST"});
  if (r.error) { alert("Feil: " + r.error); return; }
  closeModal("modal-settings");
  showProgress("Oppdaterer datter-data", "/api/import/status", true);
  pollProgress(async () => {
    await loadCustomers();
    if (!$("view-customers").hidden) renderCustomersTab();
    await loadLeads();
    await loadStats();
  });
});

$("btn-refresh-all-aksjonaerinfo").addEventListener("click", async (ev) => {
  const full = ev.shiftKey;
  const msg = full
    ? "FULL oppdatering (Shift): alle selskaper i alle kundetrær hentes på nytt fra Brreg. Tar lengst tid."
    : "Beriker kun nye org.nr i kundetrær siden forrige vellykkede bulk-kjøring (første gang: alle). " +
      "Når du fjerner en kunde, ryddes snapshot automatisk neste gang det ikke er noe nytt å gjøre.\n\n" +
      "Hold Shift og klikk for å tvinge full Brreg-runde for alle noder.";
  if (!confirm(msg)) return;
  try {
    const r = await fetchJSON("/api/customers/refresh-all-aksjonaerinfo", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({full}),
    });
    if (!r.started) {
      alert(r.message || "Ingen nye å oppdatere.");
      return;
    }
    closeModal("modal-settings");
    showProgress("Oppdater alle (aksjonærinfo)", "/api/import/status", true);
    pollProgress(async () => {
      await loadCustomers();
      if (!$("view-customers").hidden) renderCustomersTab();
      await loadStats();
    });
  } catch (ex) {
    alert("Feil: " + (ex && ex.message ? ex.message : ex));
  }
});
