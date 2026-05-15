# Ytelsesplan — LeadMap

**Prinsipp:** Stabilitet først; målrettede grep med lav risiko. Ingen UI-redesign. Ingen obligatorisk omskriving til database — vurder paginering/cache kun når behov er bekreftet (store `leads.json`).

---

## 1. Måling (før endringer)

Anbefalt baseline (manuelt / enkle script):

1. **Størrelse på `data/leads.json` og `data/customers.json`** (MB + antall leads/kunder).
2. **Tid for `GET /api/leads`** (nettverk utenom, f.eks. `curl -w "%{time_total}"` lokalt).
3. **Antall Brreg/Geonorge-kall** under én full analyse (logg i eksisterende analyse-log der mulig).

Uten tall: prioriter punktene under i den angitte rekkefølgen.

---

## 2. Kritisk sti: `GET /api/leads`

**Observasjon:** Hver forespørsel:

- `get_leads()` → `load_json` → **mtime-cache + `copy.deepcopy` per treff** (se `json_store.py`).
- Migreringssjekk per lead, `S._reload()`, full kundelasting, `_enrich_signals_with_anchor_size` (itererer alle kunder per request), `hydrate_geo_distance_factors_for_leads`, **full scoring** per lead (`S.score_lead`), sortering, `enrich_lead_geo` per lead.

**Konsekvens:** O(n) på antall leads med relativt tung konstant; skalerer dårlig når `leads.json` vokser. UI kaller dette ved init og etter jobber (`loadLeads`).

### Tiltak (prioritert)

| # | Tiltak | Risiko | Estimat |
|---|--------|--------|---------|
| P1 | **Unngå `deepcopy` på hver lesing** når konsumenter ikke muterer (f.eks. returner kopi kun ved skrive-behov, eller dokumenter «read-only» og fjern kopi for spesifikke paths). Alternativ: shallow copy av ytterliste der indre dict ikke muteres i read-path. | Medium — må kartlegge alle muterende kall etter `get_leads()`. | Liten refaktor, 1–2 filer først. |
| P2 | **Cache ferdig «API-view»** av leads i minne med invalidasjon ved `save_json(LEADS_FILE, ...)` — *kun* hvis P1 ikke rekker; øker kompleksitet (invalidasjon må treffe alle skrivepunkter). | Høy hvis invalidasjon glemmes. | Vurder etter P1. |
| P3 | **Server-side paginering / filtrering** for tabellen — krever frontend-koordinering (samme datakontrakt eller nytt endepunkt). Ikke «UI-redesign», men API- og JS-endring. | Medium. | Bare ved dokumentert behov (tusenvis av rader). |

---

## 3. `json_store.load_json` / `save_json`

- **`deepcopy` på cache-hit og etter load** (`json_store.py` linjer 25, 32, 58) er O(størrelse på dokument) per operasjon.
- **Atomisk skriv** er bra — behold.

**Tiltak:** Profilér med typisk `leads.json`; hvis `deepcopy` dominerer, innfør «dirty read»-sti for lesing som ikke endrer data (se P1).

---

## 4. Analyse-pipeline (`analysis.py` + discovery)

**Observasjoner:**

- **Mange ankere:** `_all_discovery_anchors` inkluderer hele kundetreet → mange `discover_leads_for_anchor`-kall (hver med `time.sleep(throttle)` i `discovery.py`).
- **`fetch_related` per enhet** er nevnt som tungt i handover.
- Parallellisering (`analysis_parallel`) hjelper, men eksterne APIer er fortsatt flaskehals.

**Tiltak:**

| # | Tiltak | Merknad |
|---|--------|---------|
| A1 | Hold **eksisterende** throttling; vurder *konfigurerbar* `throttle` eller redusert søk `size` kun etter avtale (påvirker lead-dekning). | Avveining kvalitet/ytelse. |
| A2 | **Inkrementell analyse** der mulig (alleredel delvis for geo) — utvid kun med tydelig spesifikasjon. | |
| A3 | Unngå unødvendig **re-fetch** av Brreg-data når `related` allerede er komplett (defensiv sjekk før nettverk). | Små, lokale guards. |

---

## 5. `lead_promote_whole_owned`

- `rebuild_anchor_each_move=True` (default) kaller `_build_orgnr_to_anchor_map` etter **hver** flytting → O(flyttinger × tre-kompleksitet).  
- Analyse bruker allerede `rebuild_anchor_each_move=False` (handover).

**Tiltak:** Sørg for at bakgrunnsjobb/UI som starter promote også bruker `False` der hele batch kjøres (verifiser `leads_routes` worker). Ikke endre default i biblioteket uten å lese alle kallsteder.

---

## 6. `settings` POST — full geo-refresh

`blueprints/settings_routes.py`: ved lagring av innstillinger kjøres `GEO.refresh_geo_scoring_for_leads` + lagring av kunder og leads. Det er **korrekt** for konsistent score, men dyrt for store datasett.

**Tiltak:**  
- Vurder å trigge full refresh **kun** når vekter/tersler som påvirker geo/eierskap faktisk endres (delvis allerede for eierskapsterskel). Utvid med eksplisitt diff på geo-relevante tersler.  
- Liten, lokal optimalisering — ikke fjern refresh uten analyse av avhengigheter.

---

## 7. Frontend

- **Hele lead-listen** lastes i én JSON — samme flaskehals som backend.
- Ingen umiddelbar virtualisering uten tabell-endring (kan regnes som UI — utenfor scope med mindre bruker ber om det).

**Tiltak:** Koordiner med P3 (API paginering) ved behov.

---

## 8. Excel-backup (`persist._save_customers_backup`)

Kjører ved `save_customers` — kan bli treg ved veldig mange kunder.  
**Tiltak:** Asynkron backup eller sjeldnere backup (f.eks. kun ved import-slutt) — lav prioritet; test nøye.

---

## 9. Anbefalt rekkefølge (kort)

1. Verifiser og dokumenter faktisk `GET /api/leads`-tid og filstørrelse.  
2. Angrip **`deepcopy` / get_leads-hot path** med minste invasive endring.  
3. Verifiser **`promote_whole_owned`**-parametre i alle kallsteder.  
4. Deretter: betinget geo-refresh ved settings, paginering ved behov.

---

*Generert som del av prosjektovertakelse (mai 2026).*
