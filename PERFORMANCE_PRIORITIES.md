# Prioritert ytelses- og stabilitetsbacklog — LeadMap

Oppdatert etter gjennomgang av backend (Flask + JSON), `GET /api/leads`, import, og frontend (leads-tabell, polling). **Ingen tradisjonell database** — «tunge kall» = disk JSON + `deepcopy`, Brreg/Geonorge, og full DOM-oppdatering.

---

## P0 — Kritisk / høyest brukerpåvirkning (allerede delvis adressert)

| # | Funn | Status |
|---|------|--------|
| P0.1 | Org.nr `int` vs `str` ga feil status/notater/stats/relasjoner | **Fikset** (`norm_org` i `leads_routes`, `settings_routes`, `state`, `analysis`) |
| P0.2 | `promote_whole_owned` worker brukte `rebuild_anchor_each_move=True` | **Fikset** (`False` i worker) |

---

## P1 — Server: største kost per operasjon

| # | Funn | Tiltak (iterativt) | Filer (ca.) |
|---|------|-------------------|-------------|
| P1.1 | **`GET /api/leads`** scorer, hydrerer geo og beriker **alle** leads per request | Vurder cache med invalidasjon ved `save_json(LEADS_FILE)` **eller** lettvekts `GET /api/stats`-sti uten full scoring når kun tall trengs (stats bruker allerede ikke scoring — fortsatt `get_leads()` + `deepcopy`) | `leads_routes`, `json_store`/`persist` |
| P1.2 | **`json_store.load_json`**: `copy.deepcopy` på hvert treff mot cache | Profilér; deretter trygg strategi (evt. egen sti for «read-only metadata») — **ikke** halvveis fjerne kopi uten full mutasjonskartlegging | `json_store.py` |
| P1.3 | **`save_json`**: `deepcopy` ved cache-oppdatering | La stå til P1.2 er analysert | `json_store.py` |
| P1.4 | Samtidig analyse + import skriver samme JSON | Dokumentert; vurder eksplisitt serialisering/lås **kun** ved målt tap | `state` / jobb-API |

---

## P2 — Frontend: tabell, lister, «re-renders»

| # | Funn | Tiltak | Status |
|---|------|--------|--------|
| P2.1 | **`_repaintLeadsUi`** kalte `populateFilters` + `render` **to ganger** (synk + rAF) | Én pass — **Runde 1** | **Gjort** |
| P2.2 | **`render()`** bygger hele `innerHTML` på tbody + nye event listeners hver gang | Akseptabelt for moderat n; vurder senere kun oppdatering av endrede rader (større grep). **Input-søk:** debounce ~140 ms (**Runde 3**) | delvis |
| P2.3 | **`pollProgress`**: `/api/jobs/overview` hvert sekund under jobb | Throttle **Runde 1** | **Gjort** |
| P2.4 | **`refreshLeadsSilently`** under analyse hvert ~4,5 s på leads-fanen | Allerede begrenset; avhengig av P1.1 for serverkost | — |

---

## P3 — Import / enrichment

| # | Funn | Tiltak |
|---|------|--------|
| P3.1 | Import: `ThreadPoolExecutor(8)` × Brreg per rad | OK for throughput; vurder lavere `max_workers` ved rate-limit fra Brreg |
| P3.2 | Analyse: mange ankere → discovery med `sleep(throttle)` | La terskel/throttle være konfigurerbar før endring av standard |
| P3.3 | `fetch_related` per enhet | Allerede tungt; unngå re-fetch når `related` er komplett (små guards) |

---

## P4 — Store filer / vedlikehold (ikke ytelse først)

Se `REFACTOR_AUDIT.md` — `analysis.py`, `core.js`, `customers-tab.js`, osv. Refaktor **kun** når det løser målt problem.

---

## Anbefalt rekkefølge (neste runder)

1. **Runde 2 (server, 3–5 filer):** Profilér `GET /api/leads`; deretter målrettet reduksjon av `deepcopy`-frekvens eller delvis respons-cache (med tydelig invalidasjon).
2. **Runde 3 (frontend):** Debounce `render()` på `input` i søkefelt (kun hvis tastetrykk føles trege med store lister).
3. **Runde 4:** Import/analyse — små guards mot duplikat Brreg-kall.

---

## Runde 2 (utført): `get_leads_readonly` + `load_json(..., deep_copy=False)`

- **`json_store.load_json`:** valgfri `deep_copy=False` — fersk `json.loads` fra disk, **ingen** mtime-cache og **ingen** `deepcopy` (trygt når resultatet ikke deles på tvers av tråder som forventer isolert cache-objekt). *(Parameternavnet er ikke `copy` — det overskygget `import copy`.)*
- **`persist_leads.py`:** ny modul med `get_leads()` (uendret semantikk: cache + deepcopy) og `get_leads_readonly()` (spar deepcopy).
- **`persist.py`:** re-eksporterer `get_leads` / `get_leads_readonly` fra `persist_leads` (eksisterende `from persist import get_leads` fungerer).
- **Byttet til readonly** der listen muteres lokalt og lagres med `save_json(LEADS_FILE, …)` eller kun leses: `api_stats`, settings/rescore, kunde-GET m. relaterte leads, state `_remove_anchor_from_leads`, analyse `run_geo_rescore_only`, samt lette lead-ruter (søk, linkedin, …) og promote-stier.
- **`api_leads`:** bruker fortsatt **`get_leads()`** (cache + isolert kopi) fordi respons bygges på muterte lead-objekter uten alltid å skrive til disk.

## Runde 3 (utført): analyse-snapshot + debounce søk

- **`analysis.py`:** `load_json(LEADS_FILE, [], deep_copy=False)` for forrige leads-snapshot og for `prev_by_orgnr`-bygging (kun lesing før merge inn i `new`).
- **`leads-table.js`:** debounce ~140 ms på `f-search` / `f-minscore` **input**; umiddelbar `render()` på **change** (avbryter ventende timeout).
- **`customers-tab.js`:** tilsvarende debounce på `cust-search-tab` **input** (tung `renderCustomersTab`).

