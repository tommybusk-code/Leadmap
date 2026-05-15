# AI_HANDOVER.md — LeadMap

Dokument for ny utvikler eller AI-agent som skal videreføre **LeadMap**: lokal Flask-app for kundeliste → Brønnøysund-berikning → lead-discovery → scoring og UI for oppfølging.

---

## 1. Prosjektets formål

- **Inndata:** Eksisterende kunder (typisk importert fra Excel/CSV), med valgfritt **konsern-/datterselskap-tre** (Brreg + manuelle koblinger + aksjeeierbok).
- **Prosess:** Analysekjede som beriker kunder, finner nærliggende / bransje-relaterte selskaper som **leads**, kobler **eierskap** (regnskap mor, kundetre, aksjeeierbok 2024), **felles styre** (Brreg roller), **vekst** (egen historikk), **geo** (Kartverket).
- **Utdata:** Sorterbar/filterbar **lead-tabell** (score 0–100), **kunde-fane** med tre og detaljmodal, **status/notater**, mulighet for **promotering** av lead til kunde eller inn i tre som datter.
- **Målgruppe:** Én bruker / internt bruk; **ingen multi-tenant** eller sky-deploy i koden (lokal `127.0.0.1:5050`).

---

## 2. Tech stack

| Lag | Teknologi |
|-----|-----------|
| Backend | **Python 3.10+** (README), **Flask ≥3**, `requests`, `pandas`/`openpyxl`, `beautifulsoup4` |
| Data | **JSON-filer** under `data/` (+ valgfri **SQLite** for aksjeeierbok) |
| Frontend | **Vanilla JS** (ingen React/Vue), én **Jinja**-mal `templates/index.html` |
| Styling | **CSS-moduler** via `@import` i `static/style.css` (`static/css/*.css`) |
| Eksterne APIer | Brønnøysund (enhetsregisteret, underenheter, regnskap), Geonorge adressesøk, Proff (scraping), LinkedIn (kun lenker) |

`requirements.txt`: Flask, requests, openpyxl, pandas, beautifulsoup4.

---

## 3. Mappestruktur (høy nivå)

```
├── app.py                 # Entry: Flask + "/" + import analysis/customers
├── customers.py           # Registrerer web_api blueprint + sideeffekt-importer
├── state.py               # Flask app-instans, _analysis, _import_state, lead-hjelpere
├── paths.py               # ROOT, DATA, alle filstier
├── json_store.py          # Atomisk load/save JSON + mtime-cache
├── persist.py             # get/save customers, leads, status, notes; Excel-backup
├── analysis.py            # run_analysis, run_targeted_analysis; ruter /api/analyze*
├── scoring.py             # Vekter, thresholds, score_lead, theoretical_max
├── discovery.py           # discover_leads_for_anchor (kommune/postnr/NACE)
├── enrichment.py          # Re-eksport av brreg + roller + proff + discovery
├── brreg_api.py           # Enheter, underenheter, søk
├── brreg_konsern.py       # fetch_related, konsern/regnskap
├── brreg_roles.py         # Roller, navn-matching
├── geonorge_adresse.py    # Kartverket/Geonorge + geo_cache
├── geo_enrichment.py      # Haversine, nabobedrift_postnummer-faktorer, batch geokod
├── lead_geo.py            # geo_tier, geo_label, geoscore for API-visning
├── ownership_signals.py   # kunde_morselskap / kunde_konserntre / kunde_aksjeeierbok
├── aksjeeierbok_sqlite.py # Lesing av data/aksjeeierbok_2024.sqlite
├── bok_tree_sync.py       # Heleide datre fra bok → manual_subsidiaries
├── lead_promote_whole_owned.py  # Auto-flytt heleide leads → tre (eksperimentell jobb)
├── related_tree.py        # DFS, merge_fetch_related, manual_subsidiary-API-hjelpere
├── analysis_parallel.py   # Trådpool for analyse-steg
├── proff_scrape.py        # Proff.no scraping
├── blueprints/
│   ├── web_api.py         # Blueprint url_prefix=/api
│   ├── customers_crud.py
│   ├── customers_konsern.py
│   ├── customers_importer.py   # /api/import + /api/import/status
│   ├── leads_routes.py
│   └── settings_routes.py
├── data/                  # Runtime JSON (+ sqlite); .gitignore for mange filer
├── templates/index.html   # Enkelt-side-app, alle modaler
└── static/
    ├── style.css          # @import av css/*
    ├── core.js            # $, fetchJSON, modaler, delte helpers
    ├── features.js        # Analyse-knapper, geo-rescore, orkestrering
    ├── progress.js        # modal-progress + poll
    ├── settings.js        # Innstillinger + vedlikehold-knapper
    ├── import.js          # Excel/CSV-import UI
    ├── leads-table.js, leads-detail.js
    ├── customers-tab.js, customers-modal.js, customers-konsern.js
    ├── theme-init.js
    └── css/               # tokens, base, layout, buttons, filters, table, modals, theme
```

**Merk:** `static/app.js`, `static/leads.js`, `static/customers.js` er i praksis **erstattet** av `core.js` + moduler (kommentar i `app.js`). `index.html` laster **ikke** disse tre.

---

## 4. Arkitektur

### 4.1 Backend

- **Én Flask-app** (`state.app`). Blueprint **`web_api`** (`/api`) for kunder, leads, import, settings.
- **`analysis.py`** registrerer ruter **direkte på `app`** (`/api/analyze`, `/api/analyze/status`, `/api/geo-rescore`, `/api/jobs/overview`) — historisk, ikke refaktorert inn i blueprint.
- **To uavhengige «jobb-sluser»** (se `state.get_jobs_overview()`):
  - **`_analysis`:** analyse / geo-rescore / målrettet analyse (maks én).
  - **`_import_state`:** Excel-import, «oppdater alle relaterte», «aksjonærinfo»-bulk, **promote_whole_owned** (maks én av disse om gangen).
- **Persistens:** Ingen ORM; `json_store.save_json` skriver atomisk. `persist.save_customers` trigget også Excel-backup `kunder_backup.xlsx` (sti i `paths.CUSTOMERS_BACKUP`).

### 4.2 Frontend

- **Ingen bundler:** script-rekkefølge i `index.html` definerer avhengigheter.
- **Mønster:** `fetchJSON` i `core.js`, globale funksjoner, `$(id)` for DOM.
- **Fremdrift:** `showProgress` + `pollProgress` mot `/api/analyze/status` **eller** `/api/import/status` avhengig av jobb.

### 4.3 Kundedata og tre

- `customers.json` er et **dict**: nøkkel er ofte firmanavn eller hybridnøkkel; verdi er kunde-dict med `orgnr`, `related` (Brreg `underenheter` + `manual_subsidiaries`), valgfri `parent_orgnr` for «egne kundekort»-datterselskap.
- **Nested tre:** `related_tree.py` — `merge_fetch_related` bevarer manuelle datre ved Brreg-refresh.

---

## 5. «Database»-design

Det er **ingen tradisjonell database** for kjerneentiteter.

| Fil | Innhold |
|-----|---------|
| `data/customers.json` | Objekt: `{ lagringsnøkkel: kundeDict }` |
| `data/leads.json` | **Liste** av lead-objekter (orgnr, navn, signals, score, …) |
| `data/status.json` | `{ orgnr_str: status }` |
| `data/notes.json` | `{ orgnr: notattekst }` |
| `data/settings.json` | `weights` + `thresholds` |
| `data/discovery_cache.json` | Per-anker discovery-resultat |
| `data/geo_cache.json` | Geonorge-resultat cache |
| `data/roller_cache.json` | Brreg roller (rå/liste) |
| `data/ownership_mor_cache.json` | Regnskaps-mor oppslag |
| `data/ansatte_history.json` | Vekst-baseline |
| `data/lead_relations.json` | Lead-til-lead forelder |
| `data/aksjonaerinfo_bulk_state.json` | Org.nr-snapshot for inkrementell Brreg-bulk |
| `data/aksjeeierbok_2024.sqlite` | Tabell `aksjeeier_org` (bygges fra CSV via `aksjeeierbok_sqlite.py`) |

**Kontrakter:** `leads.json` **må** forbli JSON-array. `status`/`notes` **bør** være objekter; nyere kode defensivt håndterer skjevheter. Org.nr skal normaliseres via `related_tree.norm_org` der det er kritisk.

---

## 6. Hvordan scoring fungerer

Implementasjon: **`scoring.py`**, funksjon **`score_lead(lead)`**.

1. **Signalvekter** lastes fra `data/settings.json` (fallback `DEFAULT_WEIGHTS`). `S._reload()` brukes etter innstillingslagring.
2. **Per signaltype:** tas **høyeste** vekt blant signaler av samme `type` (unike typer).
3. **`nabobedrift_postnummer`:** vekt multipliseres med `geo_distance_factor` (0–1) når satt.
4. **Små ankere:** for signaler som ikke er `nabobedrift_*`, dempes vekt om `anker_ansatte` < `small_anchor_threshold` (faktor `small_anchor_factor` %).
5. **Combo-bonus:** én gang per lead — `samme_bransje` + `nabobedrift_postnummer` **slår** `samme_bransje` + `nabobedrift_kommune`.
6. **Multi-anker-bonus:** antall ankere med ≥2 signaltyper → `multi_anchor_2` / `multi_anchor_3`.
7. **Aksjeeierbok-signaler:** `kunde_aksjeeierbok` (og mor med bok-andel) inkluderes i scoring kun om `ownership_pct` ligger i `[kunde_aksjeeierbok_min_pct, kunde_aksjeeierbok_max_pct]`.
8. **Vist score 0–100:** `raw` skaleres med `100 / theoretical_max_raw_points()` (samme formel som innstillinger-UI), cap 100.

**Viktig:** Signaltype-strenger må være synkron med frontend (f.eks. `SIGNAL_LABELS` / piller i `core.js`).

---

## 7. Hvordan geoscore fungerer

- **Geokoding:** `geonorge_adresse.py` → `geo_cache.json`. `geo_enrichment.run_geocode_and_attach` geokoder kunder og leads, skriver `geo_lat`/`geo_lon` på entiteter der det lykkes.
- **Avstand til anker:** `geo_enrichment.attach_nabobedrift_distance_factors` setter `geo_distance_m` og `geo_distance_factor` på `nabobedrift_postnummer`-signaler når både lead og anker har koordinater; bruker `THRESHOLDS.nabobedrift_postnr_distance_max_m`.
- **Presentasjon (API):** `lead_geo.enrich_lead_geo` setter `geo_tier` (`postnr` / `adresse` / `kommune` / `fylke`), `geo_label`, `geo_detail`, og **`geoscore`** — et enkelt tall for sortering (`_geoscore_for_lead`: lavere = nærmere; postnr uten koordinater får store plassholdere).
- **Anker-indeks:** `customers_by_orgnr_map` / `geo_enrichment.customers_by_orgnr` inkluderer **alle noder i kundetrær** (`related_tree.all_tree_entities_by_orgnr`) slik at signaler fra datre matcher riktig enhet.

**Synk:** `fylke_for` i `lead_geo.py` må stemme med logikk i `core.js` (`FYLKE_MAP`-kommentar i kode).

---

## 8. Hvordan enrichment fungerer

**Pipeline (forenklet `analysis.run_analysis`):**

1. Parallell **kundeberikning** (navn → Brreg) + `fetch_related` der `related` mangler.
2. **Ankere til discovery:** `_all_discovery_anchors` — toppkunder + **hele treet** (underenheter + manuelle datre); fyller manglende NACE/kommune med `find_company_by_orgnr`.
3. **Discovery:** per anker `discover_leads_for_anchor` (kommune, postnummer, NACE) med disk-cache; throttling sleep i discovery.
4. **Aggregering** av leads + vekst-signaler (`ansatte_history`).
5. **Felles styre:** Brreg roller, cache i `roller_cache.json`.
6. **Ownership:** `ownership_signals.enrich_leads_with_customer_ownership` (mor fra regnskap, tre, aksjeeierbok).
7. **Heleid lead → tre (valgfritt steg):** `lead_promote_whole_owned.promote_whole_owned_leads_from_pool` med `rebuild_anchor_each_move=False` i analyse (ytelse).
8. Filtrering mot eksisterende kunder / promoterte statuser.
9. **Scoring** + lagring `leads.json`.
10. **Geo** (inkrementell eller full) + ev. re-score.

**Enkeltkunde:** `customers_crud.apply_brreg_refresh_to_entity` — `find_company_by_orgnr` + `fetch_related` + merge.

**Enrichment-modul:** `enrichment.py` re-eksporterer `brreg_*`, `proff_scrape`, `discovery`.

---

## 9. Kjente bugs / fallgruver

- **`/api/import/status`:** krevde at `_import_state["log"]` var liste; ellers **500** ved poll (mitigert med type-sjekk).
- **`status.json` / `notes.json` korrupte** (ikke-objekt): kunne knekke lead-flytting; mitigert i `lead_promote_whole_owned.py`.
- **Flask-ruterekkefølge:** `/leads/promote-whole-owned-to-customers` må registreres **før** `/leads/<orgnr>/promote` (allerede slik i fil).
- **`lead_promote_whole_owned`:** tidligere `NameError` på `_norm_orgnr` — bruk `norm_org` fra `related_tree`.
- **Samtidige jobber:** analyse og import kan kjøre samtidig og **begge skrive** kunde/lead-filer — `get_jobs_overview` advares i UI.
- **Org.nr som int/str** i JSON: flere steder brukes `norm_org` / `str(o).strip()` — inkonsistens gir cache-miss eller feil statusnøkkel.

---

## 10. Teknisk gjeld

- **`analysis.py` ~708 linjer:** blandet orkestrering, HTTP-ruter, parallellisering — kandidat for splitting.
- **`state.py`:** Flask-app + global analyse/import-state + scoring-relaterte hjelpere — tett kobling.
- **Kundenøkkel i `customers.json`:** navn-basert dict-nøkkel er skjør ved duplikatnavn (delvis mitigert i import).
- **README** mappestruktur matcher ikke fullt dagens `blueprints/`, `paths.py`, osv.
- **Duplisert konsept:** «promote lead» som toppkunde (`/api/leads/<orgnr>/promote`) vs «manual subsidiary in tree» vs `lead_promote_whole_owned` — tre overlappende flows.
- **Ingen sentral feilhåndtering** på tvers av API (mange bare `jsonify` + statuskode).
- **Tester:** lite / ingen automatiserte tester i repoet (sjekk om lagt til senere).

---

## 11. Stabile vs eksperimentelle deler

### Stabile (kjernen)

- Brreg-oppslag (`brreg_api`, `brreg_konsern`), discovery-mønster, scoring-modell, geo-cache + Kartverket-integrasjon, roller-cache, leads-tabell + kunde-tabell UI-grunnmur, import fra Excel/CSV, `json_store`/`persist`.

### Eksperimentelle / nyere

- **`lead_promote_whole_owned`:** automatisk flytting av heleide leads til `manual_subsidiaries` (bakgrunnsjobb + delvis analyse-hook).
- **Inkrementell `refresh-all-aksjonaerinfo`** med `data/aksjonaerinfo_bulk_state.json` + Shift=full.
- **Discovery-ankere inkluderer hele treet** (ikke bare manuelle datre) — påvirker analyse-kostnad og lead-mengde.
- **Bulk-jobs på `_import_state`** utvidet med `job=promote_whole_owned` (deler kø med import — forstå låslogikk før ny jobbtype).

---

## 12. Performance-problemer

- **Stor `leads.json`:** alt lastes i minne per request ved `get_leads()`; scoring/geo på hver GET `/api/leads`.
- **Analyse:** mange parallelle Brreg/Geonorge-kall; `fetch_related` per enhet er tung.
- **`promote_whole_owned` med `rebuild_anchor_each_move=True`:** full `_build_orgnr_to_anchor_map` etter **hver** flytting (bok-BFS + kunder) — O(flyttinger × kundeKompleksitet).
- **Inkrementell aksjonærinfo:** reduserer Brreg-kall, men første kjøring er fortsatt full tre-gjennomgang.
- **`json_store`:** `copy.deepcopy` på hver read — kostbart for store filer.

---

## 13. TODO-liste (forslag)

- [ ] Enhetstester for `related_tree.norm_org`, `merge_fetch_related`, scoring-grenser.
- [ ] Refaktor: flytt `/api/analyze*` inn i blueprint + felles jobb-hjelpere.
- [ ] Vurder SQLite eller index på `leads` for store datasett (eller server-side paginering som matcher filter).
- [ ] Dokumenter alle API-endepunkter i én OpenAPI/Swagger eller tabell i README.
- [ ] Rydd `static/app.js` / `leads.js` / `customers.js` (slett eller dokumenter «deprecated» tydelig).
- [ ] Gjenoppta `README.md` med faktisk mappestruktur og nye features (bok, konsern, promote).
- [ ] Vurder å cache `get_leads()` per-request eller delvis re-score kun endrede rader.
- [ ] E2E-smoke: import → analyse → én lead-promote.

---

## 14. Viktigste filer (hurtigreferanse)

| Fil | Rolle |
|-----|--------|
| `state.py` | Flask `app`, `_analysis`, `_import_state`, `get_jobs_overview` |
| `paths.py` | Alle datastier |
| `analysis.py` | Hovedanalyse + API for analyse/geo |
| `scoring.py` | Score og innstillingsvekter |
| `ownership_signals.py` | Konsern/eierskap-signaler |
| `geo_enrichment.py` + `geonorge_adresse.py` | Geokoding og avstandsfaktorer |
| `lead_geo.py` | geo_tier / geoscore for UI |
| `related_tree.py` | Tre-DFS, merge, subsidiary attach |
| `blueprints/customers_crud.py` | CRUD, refresh, søk, add |
| `blueprints/customers_konsern.py` | Konsern, bulk-refresh, import morselskap |
| `blueprints/leads_routes.py` | Leads API + promote whole owned worker |
| `blueprints/customers_importer.py` | Import + `/api/import/status` |
| `templates/index.html` | UI-skjelett + script-rekkefølge |
| `static/core.js` | fetchJSON, modaler, felles UI |
| `static/features.js` | Analyse/geo-knapper |
| `static/progress.js` | Fremdriftsmodal |

---

## 15. Komponenter som er «for store»

| Fil | Ca. linjer | Merknad |
|-----|------------|---------|
| `static/core.js` | ~697 | Mange helpers + modal + signal-pills |
| `analysis.py` | ~708 | Monolitt |
| `static/customers-tab.js` | ~570 | Tabell + tre + søk |
| `static/leads-detail.js` | ~555 | Lead-modal |
| `static/settings.js` | ~526 | Vekter + vedlikehold |
| `static/customers-modal.js` | ~451 | Kundedetalj + relaterte leads |
| `blueprints/customers_crud.py` | ~436 | API + mye logikk |
| `blueprints/customers_konsern.py` | ~414 | Konsern + bulk |
| `geo_enrichment.py` | ~394 | Geokoding-pipeline |
| `ownership_signals.py` | ~386 | Bok + tre + mor |

---

## 16. Eksterne API-er (nettverk)

| Tjeneste | Bruk | Modul |
|----------|------|--------|
| `data.brreg.no/enhetsregisteret` | Enheter, underenheter, søk | `brreg_api.py` |
| `data.brreg.no/regnskapsregisteret` | Regnskap, konsern, mor-orgnr | `brreg_konsern.py`, `ownership_signals` |
| `data.brreg.no/enhetsregisteret/api/roller` | Styremedlemmer | `brreg_roles.py` |
| `ws.geonorge.no/adresser/v1/sok` | Adresse → koordinater | `geonorge_adresse.py` |
| `proff.no` | Scraping av nøkkeltall | `proff_scrape.py` |
| LinkedIn | **Kun** `window.open` URL-er fra `leads_routes` | — |

**Aksjeeierbok:** Offline SQLite bygget fra offisiell CSV (`Aksjeeierbok/aksjeeiebok_2024.csv` → `data/aksjeeierbok_2024.sqlite`).

---

## 17. Autentisering

**Ingen.** Appen er ment for **lokal bruk** uten login, sessions eller tokens. Ikke eksponer mot åpent nett uten reverse proxy + auth.

---

## 18. Import-flow (kunder)

1. Bruker velger fil i `import.js` → `POST /api/import?preview=true` for forhåndsvisning.
2. Bekreft → `POST /api/import` (uten preview) med fil.
3. `customers_importer.api_import` setter `_import_state`, starter tråd `_do_import`.
4. Tråden: parallell Brreg-oppslag per rad → dedupe mot eksisterende `orgnr` → `save_customers`.
5. UI: `showProgress` + `pollProgress` mot `/api/import/status` (`running`, `current`, `total`, `log_tail`, `result`).

---

## 19. State management-strategi

### Server

- **`_analysis`:** `running`, `job`, `progress`, `log`, `current`, `total`, `phase`.
- **`_import_state`:** `running`, `job`, `progress`, `log`, `current`, `total`, `result`.
- **`threading.Lock` `_lock`** rundt analyse-start og deler av logging (se `analysis.py` / `state.py`).

### Klient

- **Ingen Redux:** modulglobale variabler (`activeJob` i `progress.js`, `promoteMode` i `core.js`, osv.).
- **Oppdatering:** `loadLeads()`, `loadCustomers()`, `loadStats()`, `renderCustomersTab()` etter jobber.
- **Gjenopptak etter reload:** `checkExistingJobs()` i `progress.js` (ved load) sjekker `/api/jobs/overview`.

---

## 20. Styling-struktur

- **`static/style.css`** importerer i rekkefølge: `tokens` → `base` → `layout` → `buttons` → `filters` → `table` → `modals` → `theme`.
- **Design tokens:** `static/css/tokens.css` (farger, spacing — brukes av tema).
- **Tema:** `theme-init.js` + `theme.css` + klasser på `body` / logo-variant.
- **Store inline styles** finnes fortsatt i `index.html` (handlingspanel-lås) — vurder å flytte til `layout.css` ved touch-ups.

---

## 21. Ting som IKKE bør endres uten grundig gjennomgang

- **`scoring.theoretical_max_raw_points()`** og `_BASE_SIGNAL_WEIGHT_KEYS` må være konsistent med **`static/settings.js`** (ellers viser UI feil «teoretisk maks»).
- **Signaltype-strenger** (`felles_styreleder`, `kunde_aksjeeierbok`, …) — avhengig av både `scoring.py`, `ownership_signals.py`, `state.py` (piller), og `core.js` (SIGNAL_LABELS).
- **`related_tree.merge_fetch_related`** — skal alltid bevare `manual_subsidiaries` fra eksisterende `related`; ellers slettes brukerdata ved refresh.
- **`norm_org` / org.nr-normalisering** — endringer påvirker matching på tvers av kunder, leads, bok, cache-nøkler.
- **`json_store` atomiske skriv** — ikke erstatt med rå `open().write()` uten tmp+replace.
- **To jobb-køer** — ikke slå sammen `_analysis` og `_import_state` uten å redesigne alle «allerede i gang»-sjekker.
- **Geonorge User-Agent** — må være **latin-1**-kompatibel (kommentar i `geonorge_adresse.py`); ikke sett UTF-8-tegn i header.

---

## 22. Script-lastrekkefølge (index.html)

Rekkefølge nederst i `templates/index.html` (cache-bust `?v=` kan endres ved deploy):

1. `core.js`  
2. `leads-table.js`, `leads-detail.js`  
3. `customers-tab.js`, `customers-modal.js`, `customers-konsern.js`  
4. `progress.js`, `settings.js`, `import.js`  
5. `features.js`  

`theme-init.js` lastes i `<head>`.

---

## 23. Kjør lokalt

```bash
pip install -r requirements.txt
python app.py
# → http://127.0.0.1:5050
```

Bygg aksjeeierbok-DB ved behov: `python aksjeeierbok_sqlite.py` (se filens `main`).

---

*Sist oppdatert for handover: generert fra kodebase-inspeksjon (mai 2026). Juster seksjoner etter hver større feature-merge.*
