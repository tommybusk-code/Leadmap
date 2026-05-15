# Bug-rapport — LeadMap

**Status:** Funnet gjennom statisk kodegjennomgang + `AI_HANDOVER.md`. Ingen endringer er gjort i denne omgangen.  
**Alvor:** *Kritisk* / *Høy* / *Medium* / *Lav* — subjektiv vurdering for intern bruk.

---

## 1. Inkonsistent org.nr-nøkkel for `status` / `notes` / statistikk

**Alvor:** Høy (data vises feil eller «forsvinner» sporadisk)

**Beskrivelse:**  
JSON kan representere org.nr som **tall** (f.eks. `987654321`) eller **streng**. `notes.json` og `status.json` fylles typisk fra URL-stier og lagres med **streng**-nøkler.

- I `blueprints/leads_routes.py` brukes for `status`: `key = str(oid).strip()` mens `note` hentes med `notes.get(L["orgnr"], "")` uten samme normalisering.
- I `blueprints/settings_routes.py` (`api_stats`) brukes `status.get(L["orgnr"], "new")` uten `str(...).strip()`.

**Konsekvens:**  
- Notater vises ikke i lead-listen selv om de finnes på disk.  
- Statistikk per status kan avvike fra det `/api/leads` viser for samme lead.

**Forslag til fiks (liten, iterativ):**  
Bruk én felles nøkkelfunksjon (f.eks. `norm_org` fra `related_tree` eller `normalize_lead_orgnr` fra `geo_enrichment`) for alle oppslag mot `status`, `notes` og `lead_relations` i API-respons og statistikk.

**Berørte filer (indikativt):** `blueprints/leads_routes.py`, `blueprints/settings_routes.py` (+ eventuelt andre steder som gjør `status.get(L["orgnr"])`).

---

## 2. `lead_relations`-oppslag med rå `L["orgnr"]`

**Alvor:** Medium

**Beskrivelse:** I `api_leads` brukes `relations.get(L["orgnr"])` mens `status` bruker strengnormalisert nøkkel. Samme int/str-problem som over kan gi manglende `parent_lead_*` i API-respons.

---

## 3. Samtidige jobber skriver samme JSON-filer

**Alvor:** Medium (intermitterende tap / overskriving — vanskelig å reprodusere)

**Beskrivelse:** Analyse (`_analysis`) og import/relaterte (`_import_state`) kan kjøre parallelt og begge kalle `save_customers` / `save_json(LEADS_FILE, ...)`. Sist som skriver «vinner».

**Mitigering i dag:** UI viser hint via `get_jobs_overview()`.

**Forslag (større, ikke påkrevd nå):** Fil-lås eller kø for skriv til samme fil; eller eksplisitt blokkering av andre jobben i API. Avveies mot enkel lokal bruk.

---

## 4. `request.get_json(force=True)` uten `silent=True` på enkelte POST-ruter

**Alvor:** Lav–medium (500 ved ugyldig JSON i stedet for 400)

**Eksempel:** `api_set_status`, `api_set_note` i `leads_routes.py` bruker `force=True` uten `silent=True`. Ugyldig body kan kaste og gi 500.

**Forslag:** `silent=True` + eksplisitt 400 med melding, eller behold `force` men fang `BadRequest`.

---

## 5. `json_store.load_json` svelger alle lesefeil

**Alvor:** Medium (skjult datakorrupsjon / «alt ble tomt»)

**Beskrivelse:** Ved JSON parse-feil eller annet unntak under lesing returneres `default` uten logging. For `LEADS_FILE` med default `[]` kan en korrupt fil midlertidig oppføre seg som «ingen leads» til noe lagrer på nytt — med risiko for overskriving.

**Forslag:** Logg exception + filsti; vurder ikke å overskrive hvis load feilet (krever nøye design for å unngå å blokkere app).

---

## 6. Kjente historiske bugs (fra handover — verifiser fortsatt relevant)

| Sak | Status i kode |
|-----|----------------|
| `/api/import/status` 500 hvis `log` ikke er liste | Mitigert: `isinstance(log, list)` i `customers_importer.api_import_status`. |
| Korrupt `status`/`notes` ved promote whole owned | Mitigert: type-sjekk i `lead_promote_whole_owned.py`. |
| Flask-ruterekkefølge promote | Handover sier korrekt rekkefølge — behold ved nye ruter. |
| `NameError` `_norm_orgnr` i promote | Skal være fikset (`norm_org` brukes). |

---

## 7. Mulige edge cases (krever manuell test)

1. **`api_search_leads`** — sammenligner `q` med `orgnr` uten å normalisere mellomrom; små UX-avvik.  
2. **`api_linkedin` / `api_website`** — `next(..., L["orgnr"] == orgnr)` — streng fra URL vs int i liste kan gi 404.  
3. **Tom eller ikke-liste `leads.json`** — delvis håndtert i promote-worker; andre ruter kan anta liste.

---

## 8. Anbefalt rekkefølge for utbedring

1. **§1 og §2** (org.nr-nøkler) — høyeste brukerverdi, lav risiko om `norm_org` brukes konsekvent.  
2. **§4** (JSON-feilhåndtering) — rask stabilitetsgevinst.  
3. **§5** (logging ved load-feil) — bedre feilsøking.  
4. **§3** (samtidig skriving) — kun etter behov / repro.

---

*Generert som del av prosjektovertakelse (mai 2026). Oppdater når bugs lukkes eller nye verifiseres.*
