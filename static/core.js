// =====================================================================
// core.js — Felles helpers, konstanter, state, MultiSelect og modal-stacking.
// Lastes FØRST. Definerer globaler som de andre filene bruker.
// =====================================================================

// === NACE → norske bransjenavn (2-sifret hovedgruppe) ===
const NACE_LABELS = {
  "01": "Jordbruk og husdyrhold", "02": "Skogbruk", "03": "Fiske og akvakultur",
  "05": "Bryting av kull", "06": "Olje- og gassutvinning", "07": "Bergverksdrift (malm)",
  "08": "Bergverksdrift", "09": "Tjenester olje og gass", "10": "Næringsmiddelindustri",
  "11": "Drikkevareindustri", "12": "Tobakksindustri", "13": "Tekstilindustri",
  "14": "Bekledningsindustri", "15": "Lærvareindustri", "16": "Trelast og trevareindustri",
  "17": "Papirindustri", "18": "Trykking og reproduksjon", "19": "Petroleumsraffinering",
  "20": "Kjemisk industri", "21": "Farmasøytisk industri", "22": "Plast- og gummiindustri",
  "23": "Mineralsk industri", "24": "Metallproduksjon", "25": "Metallvareindustri",
  "26": "Elektronikk og optikk", "27": "Elektrisk utstyrsindustri", "28": "Maskinindustri",
  "29": "Bilindustri", "30": "Skipsbygging og transportmidler", "31": "Møbelindustri",
  "32": "Annen industri", "33": "Reparasjon og vedlikehold", "35": "Energi og kraft",
  "36": "Vannforsyning", "37": "Avløp og kloakk", "38": "Avfall og gjenvinning",
  "39": "Miljøtjenester", "41": "Bygg og anlegg", "42": "Anleggsvirksomhet",
  "43": "Spesialisert bygg/anlegg", "45": "Bilbransjen (salg/verksted)", "46": "Engroshandel",
  "47": "Detaljhandel", "49": "Landtransport", "50": "Sjøtransport", "51": "Lufttransport",
  "52": "Lagring og transporttjenester", "53": "Post og bud", "55": "Hotell og overnatting",
  "56": "Restaurant og servering", "58": "Forlag og utgivelse", "59": "Film og lyd",
  "60": "Radio og TV", "61": "Telekommunikasjon", "62": "IT og programvare",
  "63": "Informasjonstjenester", "64": "Bank og finans", "65": "Forsikring",
  "66": "Finansielle hjelpetjenester", "68": "Eiendom", "69": "Juridiske tjenester og regnskap",
  "70": "Hovedkontor og rådgivning", "71": "Arkitekt og ingeniør", "72": "Forskning og utvikling",
  "73": "Reklame og markedsføring", "74": "Annen faglig virksomhet", "75": "Veterinærtjenester",
  "77": "Utleie", "78": "Bemanning og rekruttering", "79": "Reise og turisme",
  "80": "Vakt og sikkerhet", "81": "Renhold og eiendomsservice", "82": "Kontortjenester",
  "84": "Offentlig administrasjon", "85": "Utdanning", "86": "Helsetjenester",
  "87": "Pleie og omsorg", "88": "Sosiale tjenester", "90": "Kultur og kunst",
  "91": "Bibliotek og museum", "92": "Lotteri og spill", "93": "Sport og fritid",
  "94": "Medlemsorganisasjoner", "95": "Reparasjon av forbrukervarer", "96": "Andre personlige tjenester",
  "97": "Husholdningstjenester", "98": "Egenproduksjon for husholdning", "99": "Internasjonale organisasjoner",
};
function naceLabel(code) {
  if (!code) return "";
  const prefix = String(code).slice(0, 2);
  return NACE_LABELS[prefix] || `NACE ${code}`;
}

// Fylke-mapping basert på første 2 sifre av kommunenummer (post-2024-reform)
const FYLKE_MAP = {
  "03": "Oslo", "11": "Rogaland", "15": "Møre og Romsdal", "18": "Nordland",
  "31": "Østfold", "32": "Akershus", "33": "Buskerud", "34": "Innlandet",
  "39": "Vestfold", "40": "Telemark", "42": "Agder", "46": "Vestland",
  "50": "Trøndelag", "54": "Troms og Finnmark", "55": "Troms", "56": "Finnmark",
};
function fylkeFor(kommunenummer) {
  if (kommunenummer == null || kommunenummer === "") return null;
  const digits = String(kommunenummer).replace(/[^\d]/g, "");
  if (!digits) return null;
  const kn = digits.length <= 4 ? digits.padStart(4, "0").slice(-4) : digits.slice(0, 4);
  const prefix2 = kn.slice(0, 2);
  if (prefix2 === "00") return null;
  return FYLKE_MAP[prefix2] || `Annet fylkesområde (${prefix2})`;
}

// === Globale state-variabler (delt på tvers av filer) ===
let allLeads = [];
let allCustomers = [];
let promoteMode = "vunnet";
let currentLead = null;
let parentSelected = null;
let selectedCustomers = new Set();
/* Inkl. kontaktet — ellers forsvinner hele pipelinen fra tabellen når alt er «kontaktet». */
let activeStatusTabs = new Set(["new", "follow_up", "kontaktet", "vunnet"]);
let expandedCustomers = new Set();

// === Felles labels og vekter (også brukt i UI) ===
const STATUS_LABELS = {
  "new": "Nye", "kontaktet": "Kontaktet", "follow_up": "Follow-up",
  "vunnet": "Vunnet", "datterselskap": "Datterselskap",
  "eksisterende_kunde": "Eksisterende kunde", "konsern_kunde": "Konsern-kunde",
  "ikke_aktuell": "Ikke aktuell",
};
const SIGNAL_LABELS = {
  "felles_styreleder": "Styreleder/CEO", "felles_styremedlem": "Styremedlem",
  "selskap_i_vekst": "I vekst", "samme_bransje": "Bransje",
  "nabobedrift_kommune": "Kommune", "nabobedrift_postnummer": "Postnr",
  "kunde_morselskap": "Kunde som morselskap", "kunde_konserntre": "I kundens konserntre",
  "kunde_aksjeeierbok": "Kunde som aksjonær",
};
const SIGNAL_WEIGHTS_JS = {
  "felles_styreleder": 26, "felles_styremedlem": 18, "samme_bransje": 14,
  "nabobedrift_kommune": 8, "selskap_i_vekst": 8, "nabobedrift_postnummer": 12,
  "kunde_morselskap": 22, "kunde_konserntre": 18, "kunde_aksjeeierbok": 20,
};
const BONUS_LABELS = {
  "combo_bransje_postnr": "Tillegg: bransje + postnummer (samme anker)",
  "combo_bransje_kommune": "Tillegg: bransje + kommune (samme anker)",
  "multi_anchor_2": "Tillegg: flere ankere med flere treff (2)",
  "multi_anchor_3": "Tillegg: flere ankere med flere treff (3+)",
};

/** Ekstra nøkler i score_breakdown (ikke SIGNAL_LABELS). */
const SCORE_BREAKDOWN_LABELS = {
  multi_anchor_bonus: "Tillegg: flere ankere",
  synergy_boost: "Tillegg: heving (kryss / flere ankere)",
};

/** True når kryss-bonus er aktiv (bransje + geo på samme anker). */
function leadHasBransjeGeoCombo(lead) {
  return !!(lead.score_breakdown && lead.score_breakdown.combo_bonus);
}

/** Én visningslabel, f.eks. «Bransje+Adresse» / «Bransje+Kommune». */
function bransjeGeoComboShortLabel(lead) {
  const b = lead.score_breakdown || {};
  if (!b.combo_bonus) return "";
  if (lead.geo_label) return `Bransje+${lead.geo_label}`;
  return b.combo_kind === "postnr" ? "Bransje+Postnr" : "Bransje+Kommune";
}

/** Poeng som inngår i én «Bransje+geo»-linje: bransje + aktuell geo-vekt + kryss-tillegg. */
function bransjeGeoComboPoints(lead) {
  const b = lead.score_breakdown || {};
  if (!b.combo_bonus) return 0;
  const br = b.samme_bransje || 0;
  const geo =
    b.combo_kind === "postnr" ? b.nabobedrift_postnummer || 0 : b.nabobedrift_kommune || 0;
  return br + geo + (b.combo_bonus || 0);
}

// === Kjerne-helpers ===
const $ = (id) => document.getElementById(id);
function closeModal(id) { $(id).hidden = true; }

async function fetchJSON(url, opts = {}) {
  const merged = { credentials: "same-origin", ...opts };
  const r = await fetch(url, merged);
  const contentType = r.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await r.json().catch(() => ({})) : await r.text().catch(() => "");
  if (!r.ok) {
    if (r.status === 401) {
      try {
        window.dispatchEvent(new CustomEvent("leadmap-auth-required", { detail: { url } }));
      } catch (e) {
        /* */
      }
    }
    const msg = (data && data.error) ? data.error : `HTTP ${r.status}`;
    throw new Error(msg);
  }
  return data;
}

function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

/** Normaliser org.nr (JSON/Brreg kan gi tall eller streng med mellomrom). */
function normOrgnr(o) {
  if (o == null || o === "") return "";
  return String(o).replace(/\s/g, "");
}

/** Til HTML-attributter (checkbox value): linjeskift kan knekke innerHTML. */
function escAttr(s) {
  return esc(String(s ?? "")).replace(/\r\n|\r|\n/g, " ");
}

/** Minste geo_distance_m (meter) blant alle nabobedrift_postnummer-signaler. */
function minGeoDistanceMetersOnLead(lead) {
  if (!lead || !Array.isArray(lead.signals)) return null;
  let best = null;
  for (const s of lead.signals) {
    if (s.type !== "nabobedrift_postnummer") continue;
    const d = s.geo_distance_m;
    if (d == null) continue;
    const n = Number(d);
    if (!Number.isFinite(n) || n < 0) continue;
    if (best === null || n < best) best = n;
  }
  return best;
}

/** Meter til valgt anker (navn må matche signal.anker_navn). */
function minGeoDistanceMetersForAnkerNavn(lead, ankerNavn) {
  if (!lead || !ankerNavn || !Array.isArray(lead.signals)) return null;
  const target = String(ankerNavn);
  let best = null;
  for (const s of lead.signals) {
    if (s.type !== "nabobedrift_postnummer") continue;
    if (String(s.anker_navn || "") !== target) continue;
    const d = s.geo_distance_m;
    if (d == null) continue;
    const n = Number(d);
    if (!Number.isFinite(n) || n < 0) continue;
    if (best === null || n < best) best = n;
  }
  return best;
}

/** Meter til valgt anker (org.nr på signal). */
function minGeoDistanceMetersForAnkerOrgnr(lead, ankerOrgnr) {
  if (!lead || !ankerOrgnr || !Array.isArray(lead.signals)) return null;
  const ao = String(ankerOrgnr).trim();
  let best = null;
  for (const s of lead.signals) {
    if (s.type !== "nabobedrift_postnummer") continue;
    if (String(s.anker_orgnr || "").trim() !== ao) continue;
    const d = s.geo_distance_m;
    if (d == null) continue;
    const n = Number(d);
    if (!Number.isFinite(n) || n < 0) continue;
    if (best === null || n < best) best = n;
  }
  return best;
}

/**
 * Sorteringsnøkkel for geo: lavere = nærmere.
 * Når nøyaktig én anker er valgt i filter, brukes avstand til den ankere.
 */
function geoscoreSortMetric(lead, selectedAnkerNavnSet) {
  if (selectedAnkerNavnSet && selectedAnkerNavnSet.size === 1) {
    const name = [...selectedAnkerNavnSet][0];
    const md = minGeoDistanceMetersForAnkerNavn(lead, name);
    if (md != null) return md;
    const hasPost = (lead.signals || []).some(
      s => s.type === "nabobedrift_postnummer" && String(s.anker_navn || "") === String(name),
    );
    if (hasPost) {
      const g = lead.geoscore;
      if (g != null && Number.isFinite(Number(g))) return Number(g);
    }
    return Infinity;
  }
  const g = lead.geoscore;
  return g != null && Number.isFinite(Number(g)) ? Number(g) : Infinity;
}

function formatMetersShort(m) {
  const n = Number(m);
  if (!Number.isFinite(n) || n < 0) return "";
  const r = Math.round(n);
  if (r < 1000) return `${r} m`;
  return `${new Intl.NumberFormat("nb-NO").format(r)} m`;
}

/** Visningsnavn for geo_tier (Selskapsinfo / geoscore-linje). */
function geoTierDisplayLong(lead) {
  if (!lead) return "";
  const t = lead.geo_tier;
  if (t === "adresse") return "Adresse";
  if (t === "postnr") return "Postnummer";
  if (t === "kommune") return "Kommune";
  if (t === "fylke") return "Fylke";
  return "";
}

/** Kun meter-distanse når Kartverket har tall; tom for plassholder-geoscore. */
function formatGeoscoreDistanceForUi(lead) {
  const g = lead == null ? null : lead.geoscore;
  if (g == null || g === "") return "";
  const n = Number(g);
  if (!Number.isFinite(n)) return "";
  if (n >= 7_500_000) return "";
  if (n < 1000) return `${n} m`;
  return `${new Intl.NumberFormat("nb-NO").format(n)} m`;
}

/** HTML: «Geoscore: Postnummer» (+ meter ved treff). */
function formatGeoscoreLineHtml(lead) {
  const tier = geoTierDisplayLong(lead);
  if (!tier) return `<span class="small-muted">—</span>`;
  const d = formatGeoscoreDistanceForUi(lead);
  const distPart = d ? ` · <strong>${esc(d)}</strong>` : "";
  return (
    `<strong>Geoscore: ${esc(tier)}</strong>${distPart}` +
    ` <small class="small-muted" title="Lavere er nærmere når tallet er meter (Kartverket).">(lavere = nærmere)</small>`
  );
}

/** HTML: luftlinje per kunde-anker for postnr-signaler (geo_distance_m). Billig O(n), maks 10. */
function formatPostnrAnchorDistancesHtml(lead) {
  if (!lead || !Array.isArray(lead.signals)) return "";
  const byAnker = new Map();
  for (const s of lead.signals) {
    if (s.type !== "nabobedrift_postnummer") continue;
    const m = s.geo_distance_m;
    if (m == null) continue;
    const di = Math.round(Number(m));
    if (!Number.isFinite(di) || di < 0) continue;
    const ao = String(s.anker_orgnr || "").trim();
    if (!ao) continue;
    const navn = String(s.anker_navn || ao).trim();
    const prev = byAnker.get(ao);
    if (!prev || di < prev.d) byAnker.set(ao, { navn, d: di });
  }
  if (!byAnker.size) return "";
  const sorted = [...byAnker.values()].sort((a, b) => a.d - b.d);
  const maxN = 10;
  const slice = sorted.slice(0, maxN);
  const tail = sorted.length > maxN ? sorted.length - maxN : 0;
  const bits = slice.map(({ navn, d }) => `<span>${esc(navn)}</span> <strong>${esc(formatMetersShort(d))}</strong>`);
  const suffix = tail ? ` <span class="small-muted">(+${tail} til)</span>` : "";
  return (
    `<div class="selskap-geo-distances small-muted" title="Luftlinje fra lead til kundens gateadresse (Kartverket)">` +
    `<span class="selskap-geo-distances-label">Avstand per kunde:</span> ` +
    bits.join(" · ") +
    suffix +
    `</div>`
  );
}

/** Geoscore: lavere = nærmere (meter fra Kartverket, eller grov plassholder for postnr/kommune/fylke). */
function formatGeoscoreForUi(lead) {
  const tier = geoTierDisplayLong(lead);
  const d = formatGeoscoreDistanceForUi(lead);
  if (tier) return d ? `${tier} · ${d}` : tier;
  const g = lead == null ? null : lead.geoscore;
  if (g == null || g === "") return "—";
  const n = Number(g);
  if (!Number.isFinite(n)) return "—";
  if (n < 7_500_000) {
    if (n < 1000) return `${n} m`;
    return `${new Intl.NumberFormat("nb-NO").format(n)} m`;
  }
  if (n < 10_000_000) return "Postnummer";
  if (n < 20_000_000) return "Kommune";
  if (n < 50_000_000) return "Fylke";
  return "—";
}

/** Geo-signaler som slås sammen til én geo-pille (tabell + kundekort). */
const GEO_SIGNAL_TYPES = new Set(["nabobedrift_kommune", "nabobedrift_postnummer"]);

/** Grense for eierskap i piller (synkes fra /api/leads → thresholds). */
function applyLeadsApiThresholds(data) {
  if (!data || !data.thresholds) return;
  const lo = Number(data.thresholds.kunde_aksjeeierbok_min_pct);
  const hi = Number(data.thresholds.kunde_aksjeeierbok_max_pct);
  window.__ownershipPctLimits = {
    min: Number.isFinite(lo) ? lo : 5,
    max: Number.isFinite(hi) ? hi : 100,
  };
}

function ownershipPillBand() {
  const d = window.__ownershipPctLimits || {};
  const lo = Number.isFinite(Number(d.min)) ? Number(d.min) : 5;
  const hi = Number.isFinite(Number(d.max)) ? Number(d.max) : 100;
  return { min: lo, max: hi };
}

/** Når både postnr og kommune-signaler finnes: vis kun postnr (vekter tyngre, unngå dobbelt pille). */
function dropKommuneGeoWhenPostnrPresent(types) {
  const arr = [...types];
  if (arr.includes("nabobedrift_postnummer") && arr.includes("nabobedrift_kommune")) {
    return arr.filter(t => t !== "nabobedrift_kommune");
  }
  return arr;
}

/** Eierskap i signal-piller: andel innenfor innstilt [min, max] % (aksjeeierbok / mor-andel). */
const OWNERSHIP_PILL_TYPES = new Set(["kunde_aksjeeierbok", "kunde_morselskap"]);
/** Samme praktiske terskel som heleid-flyt i bok (`bok_tree_sync.WHOLE_OWN_MIN_PCT`). */
const PROMOTE_FROM_LEADS_TABLE_MIN_BOK_PCT = 99;

function _dedupeSignalsByAnkerPreferHigherPct(signals) {
  const by = new Map();
  for (const s of signals) {
    const ao = String(s.anker_orgnr || "");
    const prev = by.get(ao);
    const pc =
      s.ownership_pct != null && Number.isFinite(Number(s.ownership_pct)) ? Number(s.ownership_pct) : null;
    const prevPc =
      prev && prev.ownership_pct != null && Number.isFinite(Number(prev.ownership_pct))
        ? Number(prev.ownership_pct)
        : null;
    if (!prev || (pc != null && (prevPc == null || pc > prevPc))) by.set(ao, s);
  }
  return [...by.values()];
}

function _formatPctOne(x) {
  const n = Number(x);
  if (!Number.isFinite(n)) return "";
  return Number.isInteger(n) ? String(Math.round(n)) : n.toFixed(1);
}

/**
 * Ekstra tekst på eierskap-piller (prosent; flere treff: kort navn + % per kunde).
 * Aksjonær: ikke vis antall aksjer i pilla — detalj ligger i tooltip (detail).
 */
function formatOwnershipPillSuffix(sigType, rawCandidates) {
  if (!OWNERSHIP_PILL_TYPES.has(sigType) || !rawCandidates.length) return "";
  const cands = rawCandidates.filter(s => {
    const p = s.ownership_pct;
    if (p == null || !Number.isFinite(Number(p))) return sigType !== "kunde_aksjeeierbok";
    const n = Number(p);
    const { min, max } = ownershipPillBand();
    return n >= min && n <= max;
  });
  if (!cands.length) return "";
  const list = sigType === "kunde_aksjeeierbok" ? _dedupeSignalsByAnkerPreferHigherPct(cands) : cands;
  const showName = list.length > 1;
  const bits = list
    .map(s => {
      const pctPart =
        s.ownership_pct != null && Number.isFinite(Number(s.ownership_pct))
          ? `${_formatPctOne(s.ownership_pct)}%`
          : "";
      if (!pctPart) return "";
      const name = (s.anker_navn || "").trim();
      if (showName && name) {
        const short = name.length > 18 ? `${name.slice(0, 16)}…` : name;
        return `${short}: ${pctPart}`;
      }
      return pctPart;
    })
    .filter(Boolean);
  if (!bits.length) return "";
  const max = 2;
  if (bits.length <= max) return ` · ${bits.join(" · ")}`;
  return ` · ${bits.slice(0, max).join(" · ")} · +${bits.length - max}`;
}

/** True når denne kunden (anker) er det ankeret som har bransje+geo-kryss på leadet. */
function anchorParticipatesInBransjeGeoCombo(lead, anchorOrgnr) {
  if (!anchorOrgnr || !leadHasBransjeGeoCombo(lead)) return false;
  const b = lead.score_breakdown || {};
  const ao = String(anchorOrgnr);
  const types = new Set(
    (lead.signals || [])
      .filter(s => String(s.anker_orgnr || "") === ao)
      .map(s => s.type)
  );
  if (!types.has("samme_bransje")) return false;
  if (b.combo_kind === "postnr") return types.has("nabobedrift_postnummer");
  return types.has("nabobedrift_kommune");
}

/**
 * Samme anker har bransje + geo (kommune/postnr). Brukes på kundekort: én bonus-pille,
 * også når kryss-tillegget i totalscore tilskrives et annet anker.
 * @returns {{ geoTier: string, geoWord: string, points: number, tipRaw: string } | null}
 */
function anchorBransjeGeoMergeInfo(lead, anchorOrgnr) {
  if (!anchorOrgnr) return null;
  const ao = String(anchorOrgnr);
  const types = new Set(
    (lead.signals || [])
      .filter(s => String(s.anker_orgnr || "") === ao)
      .map(s => s.type)
  );
  if (!types.has("samme_bransje")) return null;
  const hasPost = types.has("nabobedrift_postnummer");
  const hasKomm = types.has("nabobedrift_kommune");
  if (!hasPost && !hasKomm) return null;

  const fullCombo = anchorParticipatesInBransjeGeoCombo(lead, anchorOrgnr);
  const b = lead.score_breakdown || {};
  let geoTier;
  let geoWord;
  if (hasPost) {
    const gt = lead.geo_tier;
    geoTier = gt === "adresse" || gt === "postnr" || gt === "kommune" || gt === "fylke" ? gt : "postnr";
    geoWord = lead.geo_label || "Postnr";
  } else {
    geoTier = "kommune";
    geoWord = lead.geo_label === "Kommune" ? lead.geo_label : "Kommune";
  }

  let points;
  let tipRaw;
  if (fullCombo) {
    points = bransjeGeoComboPoints(lead);
    tipRaw =
      (lead.geo_detail || "Samme anker: bransje og geografisk nærhet.") +
      ` Oppsummert i score: +${points} poeng (bransje + geo + kryss-tillegg etter innstillinger).`;
  } else {
    const br = b.samme_bransje ?? SIGNAL_WEIGHTS_JS.samme_bransje ?? 0;
    if (hasPost) {
      points = br + (b.nabobedrift_postnummer ?? SIGNAL_WEIGHTS_JS.nabobedrift_postnummer ?? 0);
    } else {
      points = br + (b.nabobedrift_kommune ?? SIGNAL_WEIGHTS_JS.nabobedrift_kommune ?? 0);
    }
    tipRaw =
      (lead.geo_detail ? lead.geo_detail + " " : "") +
      `Bransje og geo mot denne kunden. Indikativ vektsum +${points} poeng på kortet (kryss-tillegg i totalscore kan tilfalle et annet anker).`;
  }
  const md = minGeoDistanceMetersForAnkerOrgnr(lead, anchorOrgnr);
  if (md != null) {
    tipRaw += ` Luftlinje ca. ${formatMetersShort(md)}.`;
  }
  return { geoTier, geoWord, points, tipRaw };
}

function bransjeGeoComboPillHtml(geoTier, geoWord, points, tipRaw) {
  return (
    `<span class="sig-tag sig-combo" title="${esc(tipRaw)}">` +
    `<span class="sig-combo-part sig-combo-b">Bransje</span>` +
    `<span class="sig-combo-x" aria-hidden="true">+</span>` +
    `<span class="sig-combo-part sig-combo-g g-${esc(geoTier)}">${esc(geoWord)}</span>` +
    `<span class="sig-combo-pts">+${points}</span>` +
    `</span>`
  );
}

/** Full bransje+geo combo-pille (samme HTML som leads-tabellen) når leadet har globalt kryss. */
function globalBransjeGeoComboPillForLead(lead) {
  if (!leadHasBransjeGeoCombo(lead)) return "";
  const breakdown = lead.score_breakdown || {};
  const bundlePts = bransjeGeoComboPoints(lead);
  const geoTier = lead.geo_tier || (breakdown.combo_kind === "postnr" ? "postnr" : "kommune");
  const geoWord = lead.geo_label || (breakdown.combo_kind === "postnr" ? "Postnr" : "Kommune");
  let tipRaw =
    (lead.geo_detail || "Samme anker: bransje og geografisk nærhet.") +
    ` Oppsummert i score: +${bundlePts} poeng (bransje + geo + kryss-tillegg etter innstillinger).`;
  const mGlob = minGeoDistanceMetersOnLead(lead);
  if (mGlob != null) {
    tipRaw += ` Luftlinje korteste vei ca. ${formatMetersShort(mGlob)}.`;
  }
  return bransjeGeoComboPillHtml(geoTier, geoWord, bundlePts, tipRaw);
}

/**
 * HTML-streng med signal-piller (samme logikk som leads-tabellen).
 * @param {object} lead
 * @param {{
 *   anchorOrgnr?: string|null,
 *   compact?: boolean,
 *   maxCompactPills?: number,
 *   omitGlobalComboPill?: boolean,
 * }} [opts] `anchorOrgnr`: kun treff mot én kunde (kundekort). `compact`: tabell — vis maks N piller + «+k».
 * `omitGlobalComboPill`: ikke legg inn global bransje+geo-pille (brukes når den vises annet sted, f.eks. detalj-hero).
 */
function buildLeadSignalPillsHtml(lead, opts) {
  opts = opts || {};
  const compact = !!opts.compact;
  const omitGlobalComboPill = !!opts.omitGlobalComboPill;
  const maxCompactPills = Math.min(12, Math.max(4, Number(opts.maxCompactPills) || 6));
  const anchorOrgnr =
    opts.anchorOrgnr != null && opts.anchorOrgnr !== "" ? String(opts.anchorOrgnr) : null;
  const allSigs = lead.signals || [];
  const signals = anchorOrgnr
    ? allSigs.filter(s => String(s.anker_orgnr || "") === anchorOrgnr)
    : allSigs;
  const uniqueTypes = dropKommuneGeoWhenPostnrPresent([...new Set(signals.map(s => s.type))]);
  const breakdown = lead.score_breakdown || {};

  const anchorMerge = anchorOrgnr ? anchorBransjeGeoMergeInfo(lead, anchorOrgnr) : null;
  const globalMerge = !anchorOrgnr && leadHasBransjeGeoCombo(lead);
  const mergeBransjeGeo = !!(anchorMerge || globalMerge);

  const anchorHasGeoSignal =
    signals.some(s => GEO_SIGNAL_TYPES.has(s.type)) ||
    (anchorOrgnr &&
      (lead.geo_tier === "adresse" || lead.geo_label === "Adresse") &&
      Array.isArray(lead.geo_match_anker_orgnrs) &&
      lead.geo_match_anker_orgnrs.some(o => String(o) === String(anchorOrgnr)));
  const showGeoOnly =
    !mergeBransjeGeo && !!lead.geo_label && (anchorOrgnr ? anchorHasGeoSignal : true);

  let sigTypesForPills;
  if (mergeBransjeGeo) {
    sigTypesForPills = uniqueTypes.filter(t => t !== "samme_bransje" && !GEO_SIGNAL_TYPES.has(t));
  } else if (showGeoOnly) {
    sigTypesForPills = uniqueTypes.filter(t => !GEO_SIGNAL_TYPES.has(t));
  } else {
    sigTypesForPills = uniqueTypes;
  }

  let leadGeoOrComboPill = "";
  if (anchorMerge) {
    const m = anchorMerge;
    leadGeoOrComboPill = bransjeGeoComboPillHtml(m.geoTier, m.geoWord, m.points, m.tipRaw);
  } else if (globalMerge) {
    if (!omitGlobalComboPill) {
      leadGeoOrComboPill = globalBransjeGeoComboPillForLead(lead);
    }
  } else if (showGeoOnly) {
    const ank = Array.isArray(lead.geo_match_anker_navn) ? lead.geo_match_anker_navn.filter(Boolean) : [];
    const tipParts = [lead.geo_detail || ""];
    if (ank.length) tipParts.push("Kunder: " + ank.join(", "));
    const addrLine = [lead.adresse, lead.postnummer, lead.poststed].filter(Boolean).join(", ").trim();
    if (lead.geo_tier === "adresse" && addrLine) tipParts.push(addrLine);
    const tip = tipParts.filter(Boolean).join(" — ");
    const mGlob = minGeoDistanceMetersOnLead(lead);
    // Samme besøksadresse: luftlinje er ~0 m — ikke vis i pilla.
    const meterSuffix =
      lead.geo_tier === "adresse" || mGlob == null ? "" : ` · ${formatMetersShort(mGlob)}`;
    leadGeoOrComboPill = `<span class="sig-tag geo-tag g-${esc(lead.geo_tier)}" title="${esc(tip)}">${esc(lead.geo_label)}${meterSuffix}</span>`;
  }

  const typePills = [];
  for (const t of sigTypesForPills) {
    const lab = SIGNAL_LABELS[t] || t;
    const candidates = signals.filter(s => s.type === t);
    let pctStr = "";
    if (OWNERSHIP_PILL_TYPES.has(t)) {
      pctStr = formatOwnershipPillSuffix(t, candidates);
    } else {
      const pcts = candidates
        .map(s => s.ownership_pct)
        .filter(v => v != null && Number.isFinite(Number(v)))
        .map(Number);
      if (pcts.length === 1) {
        const x = pcts[0];
        pctStr = ` · ${Number.isInteger(x) ? String(Math.round(x)) : x.toFixed(1)}%`;
      } else if (pcts.length > 1) {
        const mx = Math.max(...pcts);
        pctStr = ` · inntil ${Number.isInteger(mx) ? String(Math.round(mx)) : mx.toFixed(1)}%`;
      }
    }
    const tip = [lab, ...candidates.map(s => s.detail).filter(Boolean)].join(" — ");
    let html = "";
    if (t === "kunde_aksjeeierbok") {
      const { min, max } = ownershipPillBand();
      const withPct = candidates.filter(s => {
        const p = s.ownership_pct;
        if (p == null || !Number.isFinite(Number(p))) return false;
        const n = Number(p);
        return n >= min && n <= max;
      });
      const list = _dedupeSignalsByAnkerPreferHigherPct(withPct);
      let best = null;
      for (const s of list) {
        const n = Number(s.ownership_pct);
        if (!Number.isFinite(n) || n < PROMOTE_FROM_LEADS_TABLE_MIN_BOK_PCT || !s.anker_orgnr) continue;
        if (
          !best ||
          n > Number(best.ownership_pct) ||
          (n === Number(best.ownership_pct) && String(s.anker_orgnr) < String(best.anker_orgnr))
        ) {
          best = s;
        }
      }
      if (best && best.anker_orgnr && typeof promoteLeadUnderAnchor === "function") {
        const lo = String(lead.orgnr ?? "");
        const po = String(best.anker_orgnr);
        const an = (best.anker_navn || "").trim();
        const tip2 =
          `${tip} — Klikk: importer som datterselskap under «${an || po}» (${po}).`;
        html =
          `<span class="sig-tag t-${t} sig-tag--promote-bok" role="button" tabindex="0" title="${esc(tip2)}"` +
          ` onclick="void promoteLeadUnderAnchor('${lo}','${po}');event.stopPropagation()">${esc(lab)}${pctStr}</span>`;
      }
    }
    if (!html) {
      html = `<span class="sig-tag t-${t}" title="${esc(tip)}">${esc(lab)}${pctStr}</span>`;
    }
    typePills.push({ html, summary: lab + (pctStr ? pctStr.replace(/ · /, " ") : "") });
  }

  const pieces = [];
  if (leadGeoOrComboPill) {
    pieces.push({ html: leadGeoOrComboPill, summary: lead.geo_label ? String(lead.geo_label) : "Geo" });
  }
  pieces.push(...typePills);

  let bonusTags = "";
  if (!anchorOrgnr && breakdown.multi_anchor_bonus) {
    bonusTags = `<span class="sig-tag sig-multi" title="Flere kunder med flere typer treff mot dette leadet">Flere ankere +${breakdown.multi_anchor_bonus}</span>`;
    pieces.push({ html: bonusTags, summary: `Flere ankere (+${breakdown.multi_anchor_bonus})` });
  }

  if (!compact || pieces.length <= maxCompactPills) {
    return pieces.map(p => p.html).join("");
  }

  const keepN = maxCompactPills - 1;
  const head = pieces.slice(0, keepN);
  const tail = pieces.slice(keepN);
  const tipLine = tail.map(p => p.summary).join(" · ");
  const more = `<span class="sig-tag sig-more" title="${esc(tipLine)}">+${tail.length}</span>`;
  return head.map(p => p.html).join("") + more;
}

// Returnerer sterkeste anker (etter relevans) + totalt antall ankere for lead
function strongestAnchor(lead) {
  const byA = {};
  (lead.signals || []).forEach(s => {
    if (!s.anker_navn) return;
    if (!byA[s.anker_navn]) byA[s.anker_navn] = new Set();
    byA[s.anker_navn].add(s.type);
  });
  const list = Object.entries(byA).map(([navn, types]) => ({navn, types: [...types]}));
  if (!list.length) return null;
  list.sort((a, b) => {
    const wA = Math.max(...a.types.map(t => SIGNAL_WEIGHTS_JS[t] || 0));
    const wB = Math.max(...b.types.map(t => SIGNAL_WEIGHTS_JS[t] || 0));
    if (wB !== wA) return wB - wA;
    return b.types.length - a.types.length;
  });
  return {strongest: list[0].navn, total: list.length};
}

// === MultiSelect dropdown ===
class MultiSelect {
  constructor(btnId, ddId, opts = {}) {
    this.btn = $(btnId);
    this.dd = $(ddId);
    this.label = opts.label || "valgt";
    this.searchable = opts.searchable !== false;
    this.onChange = opts.onChange || (() => {});
    this.selected = new Set();
    this.options = [];
    if (!this.btn || !this.dd) {
      console.warn("MultiSelect: fant ikke", btnId, ddId);
      return;
    }
    this.btn.addEventListener("click", e => { e.stopPropagation(); this.toggle(); });
    document.addEventListener("click", e => {
      if (!this.btn || !this.dd) return;
      if (!this.btn.contains(e.target) && !this.dd.contains(e.target)) this.dd.hidden = true;
    });
  }
  setOptions(options) {
    if (!this.btn || !this.dd) return;
    const list = Array.isArray(options)
      ? options.filter(o => o != null && "value" in o && "label" in o)
      : [];
    this.options = list;
    const existing = new Set(list.map(o => String(o.value)));
    this.selected = new Set([...this.selected].filter(v => existing.has(String(v))));
    this._renderDropdown();
    this._renderButton();
  }
  toggle() {
    if (!this.btn || !this.dd) return;
    const open = this.dd.hidden;
    document.querySelectorAll(".ms-dropdown").forEach(d => d.hidden = true);
    this.dd.hidden = !open;
    if (open) {
      this._renderDropdown();
      const s = this.dd.querySelector(".ms-search");
      if (s) setTimeout(() => s.focus(), 30);
    }
  }
  _renderButton() {
    if (!this.btn) return;
    const n = this.selected.size;
    if (n === 0) {
      this.btn.textContent = `Alle ${this.label}`;
      this.btn.classList.remove("has-selection");
    } else if (n === 1) {
      const opt = this.options.find(o => String(o.value) === [...this.selected][0]);
      this.btn.textContent = opt ? opt.label : `1 ${this.label}`;
      this.btn.classList.add("has-selection");
    } else {
      this.btn.textContent = `${n} valgt`;
      this.btn.classList.add("has-selection");
    }
  }
  _renderDropdown() {
    if (!this.dd) return;
    const search = this.searchable
      ? `<input type="text" class="ms-search" placeholder="Søk..." />` : "";
    const opts = this.options.map(o => {
      const v = String(o.value);
      const checked = this.selected.has(v) ? "checked" : "";
      const cnt = (o.count != null) ? `<small>${o.count}</small>` : "";
      return `<label class="ms-option"><input type="checkbox" value="${escAttr(v)}" ${checked}>${esc(o.label)}${cnt}</label>`;
    }).join("");
    this.dd.innerHTML = search + `<div class="ms-options-list">${opts || '<small class="small-muted" style="padding:8px">Ingen valg</small>'}</div><div class="ms-actions"><button type="button" class="ms-clear">Fjern alle</button></div>`;

    this.dd.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener("change", e => {
        if (e.target.checked) this.selected.add(e.target.value);
        else this.selected.delete(e.target.value);
        this._renderButton();
        this.onChange();
      });
    });
    if (this.searchable) {
      const searchEl = this.dd.querySelector(".ms-search");
      if (searchEl) searchEl.addEventListener("input", e => {
        const q = e.target.value.toLowerCase();
        this.dd.querySelectorAll(".ms-option").forEach(opt => {
          opt.style.display = opt.textContent.toLowerCase().includes(q) ? "" : "none";
        });
      });
    }
    const clr = this.dd.querySelector(".ms-clear");
    if (clr) {
      clr.addEventListener("click", () => {
        this.selected.clear();
        this._renderButton();
        this._renderDropdown();
        this.onChange();
      });
    }
  }
  getSelected() { return [...this.selected]; }
  has(v) { return this.selected.has(v); }
}

// MS-instanser initialiseres i features.js (etter at render/populateFilters er definert)
let MS = {};

// === ESC + klikk utenfor modal lukker (kun øverste) ===
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    const open = [...document.querySelectorAll(".modal:not([hidden])")];
    if (!open.length) return;
    open.sort((a, b) => (parseInt(a.style.zIndex) || 100) - (parseInt(b.style.zIndex) || 100));
    open[open.length - 1].hidden = true;
  }
});
document.querySelectorAll(".modal").forEach(m => {
  m.addEventListener("click", e => { if (e.target === m) m.hidden = true; });
});

// Auto-stable z-index: når en modal åpnes mens andre er åpne, settes høyere z-index.
(function patchModalStacking() {
  let nextZ = 200;
  const modals = document.querySelectorAll(".modal");
  modals.forEach(m => {
    const observer = new MutationObserver(muts => {
      for (const mut of muts) {
        if (mut.attributeName === "hidden" && !m.hidden) {
          const others = [...document.querySelectorAll(".modal:not([hidden])")].filter(x => x !== m);
          if (others.length) m.style.zIndex = String(nextZ++);
          else { m.style.zIndex = ""; nextZ = 200; }
        }
      }
    });
    observer.observe(m, {attributes: true});
  });
})();

(function initThemeToggle() {
  const btn = document.getElementById("btn-theme-toggle");
  if (!btn) return;
  function syncToggleUi() {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    btn.setAttribute("aria-label", dark ? "Bytt til lys modus" : "Bytt til mørk modus");
    btn.setAttribute("title", dark ? "Lys modus" : "Mørk modus");
    btn.textContent = dark ? "☀️" : "🌙";
  }
  btn.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("leadmap-theme", next); } catch (e) {}
    syncToggleUi();
  });
  syncToggleUi();
})();
