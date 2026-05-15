# Refaktor-audit — LeadMap

**Mål:** Kartlegge teknisk gjeld, store komponenter og anti-mønstre uten UI-redesign eller store arkitekturgrep. Anbefalinger følger `PROJECT_RULES.md` (små iterasjoner, 3–5 filer per runde der det er refaktor).

**Kontekst:** Flask + JSON-filer + vanilla JS. Se `AI_HANDOVER.md` for full arkitektur.

---

## 1. Arkitektur (kort)

| Lag | Mønster | Observasjon |
|-----|---------|-------------|
| Backend | Én `Flask`-app (`state.app`), `web_api`-blueprint + ruter direkte på `app` fra `analysis.py` | To registreringsstier øker kognitiv last; forutsigbart, men rotete for ny utvikler. |
| Jobber | `_analysis` og `_import_state` (to «sluser») | Bevisst design; **ikke** slå sammen uten redesign (`AI_HANDOVER` §21). |
| Persistens | `json_store` (atomisk skriv + mtime-cache) + `persist` | Godt for lokal bruk; skaleringsgrense er filstørrelse og `deepcopy`. |
| Frontend | Script-rekkefølge i `index.html`, globale funksjoner | Ingen bundler — lav inngangsterskel, men vanskelig å isolere moduler. |

---

## 2. Teknisk gjeld (prioritert)

### 2.1 Høy — påvirker vedlikehold og risiko

1. **`analysis.py` (~708 linjer)**  
   Blandet: HTTP-endepunkter, orkestrering, fase-logging, parallell berikning. Naturlig kandidat for **gradvis** uttrekk (kun hjelpefunksjoner først, deretter ruter til blueprint i egen runde — håndbok allerede foreslår dette).

2. **`state.py` — «Gud-modul»**  
   Flask-app, jobb-state, `_enrich_signals_with_anchor_size`, migrering, logging, vekst-historikk. Tett kobling gjør enhetstesting vanskelig uten å splitte **tynne** hjelpemoduler (f.eks. kun signal-filtrering).

3. **Org.nr som `int` vs `str` i JSON og API**  
   Flere steder brukes `str(oid).strip()`, andre steder rå `L["orgnr"]` som nøkkel mot `status` / `notes` / `lead_relations`. Gir **inkonsistent oppførsel** mellom endepunkter (se `BUG_REPORT.md`).

4. **Samtidige skrivere**  
   Analyse og import kan begge oppdatere `customers.json` / `leads.json`. Dokumentert i UI (`get_jobs_overview`); ingen fil-lås — teknisk gjeld for **dataintegritet**, ikke bare ytelse.

5. **Ingen automatiserte tester**  
   Ingen `test_*.py` i repo. Regresjonsrisiko ved endringer i `related_tree.norm_org`, `merge_fetch_related`, scoring-grenser.

### 2.2 Medium — dokumentasjon og duplikatkode

1. **`README.md` vs faktisk struktur**  
   Nevnt i handover: avvik fra `blueprints/`, `paths.py`, osv.

2. **Legacy `static/app.js`, `static/leads.js`, `static/customers.js`**  
   Erstattet av moduler; bør enten slettes eller tydelig merkes «deprecated» i én README-linje (én liten endring, ikke full opprydding).

3. **Overlappende «promote»-flyter**  
   `/api/leads/<orgnr>/promote`, manuell datter i tre, `lead_promote_whole_owned`. Tre konsepter som brukeren må forstå — ikke nødvendigvis feil, men **konseptgjeld**.

4. **Kundenøkkel = navn (dict)**  
   Skjør ved duplikatnavn; delvis mitigert i import. Strukturendring er stor; anbefales **ikke** uten eksplisitt krav.

### 2.3 Lav — kosmetikk / fremtidig

1. **Inline styles i `index.html`**  
   Handover nevner flytting til CSS ved «touch-ups» — lav prioritet hvis ikke UI-jobb.

2. **Manglende samlet API-dokument**  
   Tabell eller OpenAPI ville redusert onboarding-kostnad.

---

## 3. Store filer og «for store» komponenter

| Fil | Linjer (ca.) | Problem |
|-----|--------------|---------|
| `analysis.py` | 708 | Monolitt; vanskelig å navigere og trygt endre. |
| `static/core.js` | 697 | Modaler, `fetchJSON`, signal-labels, delte helpers — mange ansvarsområder. |
| `static/customers-tab.js` | 570 | Tabell + tre + søk i én fil. |
| `static/leads-detail.js` | 555 | Lead-modal + mange sideeffekter. |
| `static/settings.js` | 526 | Vekter + vedlikehold + jobb-knapper. |
| `static/customers-modal.js` | 451 | Kundedetalj + relaterte leads. |
| `blueprints/customers_crud.py` | 436 | CRUD + refresh + geo-kall. |
| `geo_enrichment.py` | 394 | Pipeline + hydrate + refresh — forståelig domene, men lang. |
| `ownership_signals.py` | 386 | Bok + tre + mor — naturlig komplekst. |

**Anbefaling:** Ikke «splitt alt». Velg **ett** snitt per runde (f.eks. kun `hydrate_*` + `attach_*` i egen modul, eller kun analyse-fasehjelpere), verifiser med `python -m compileall .`.

---

## 4. Anti-mønstre og risiko-soner

1. **`request.get_json(force=True)` uten `silent=True`** (f.eks. `api_set_status`, `api_set_note` i `leads_routes.py`)  
   Ugyldig body kan gi 500 i stedet for kontrollert 400 — liten stabiliseringsfiks mulig.

2. **`json_store.load_json` — bred `except Exception`**  
   Korrupt JSON returnerer `default` uten logging. Skjuler datafeil; kan gjøre feilsøking vanskelig (stabilitet: vurder logglinje på parse-feil, ikke endre atomisk skriv).

3. **Globale muterbare jobb-dicts** (`_import_state`, `_analysis`)  
   Noen felt oppdateres uten samme lås som andre steder (f.eks. import progress vs start-sjekk). Fungerer ofte, men er klassisk flertråds-risiko ved utvidelse.

4. **Flere `get_leads()`-kall i samme request**  
   F.eks. enkeltruter som finner lead med `next(...)` etter full `get_leads()` — unødvendig I/O og `deepcopy`-kost ved store lister.

5. **Frontend: globale variabler og tett kobling**  
   Forventet for stacken; risiko er regresjon ved kryssende `loadLeads()` / `loadCustomers()`-rekkefølge — mitigeres med små, eksplisitte «etter jobb»-callbacks fremfor nye abstraksjonslag.

---

## 5. Forslag til små, iterative refaktor-runder (uten UI-redesign)

**Runde A — korrekthet (2–4 filer):**  
Normaliser org.nr-nøkler konsekvent i `api_leads`, `api_stats`, notat-/relasjons-oppslag (detaljer i `BUG_REPORT.md`).

**Runde B — ytelse (1–2 filer):**  
`json_store`: reduser eller fjern unødvendig `deepcopy` på lesevei der mutasjon ikke skjer (se `PERFORMANCE_PLAN.md`).

**Runde C — struktur (3–5 filer):**  
Flytt **kun** `run_analysis`/`run_targeted_analysis`-hjelpefunksjoner som `_merge_preserved_lead_analysis` og `_all_discovery_anchors` til f.eks. `analysis_helpers.py` — `analysis.py` beholder ruter til slutt.

**Runde D — testbarhet (2–3 filer):**  
Legg til `pytest` + tester for `norm_org`, `merge_fetch_related` (minimal fixtures), én scoring-grensetest.

**Unngå i første omgang:**  
Full React/Vue, ORM, sammenslåing av jobb-køer, endring av `customers.json`-nøkkelstrategi.

---

## 6. Avhengigheter som ikke bør ryddes «for penhet»

- `scoring.theoretical_max_raw_points()` ↔ `static/settings.js` (synk).
- `merge_fetch_related` — bevar `manual_subsidiaries`.
- Atomisk `save_json` (tmp + replace).
- Geonorge User-Agent (latin-1).

Se `AI_HANDOVER.md` §21.

---

*Generert som del av prosjektovertakelse (mai 2026). Oppdater etter hver vesentlig endring.*
