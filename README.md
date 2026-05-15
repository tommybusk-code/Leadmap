# LeadMap — lokal web-app

Liten, lokal Flask-app for å håndtere leads basert på din kundebase.
Henter alt fra **Brønnøysund** (gratis), kjører lead-discovery, og lar deg jobbe igjennom listen i et nettlesergrensesnitt.

## Installasjon

Krever Python 3.10+ og pip.

```bash
cd leadmap   # eller rotmappen til det klonede repoet (valgfritt mappenavn)
pip install -r requirements.txt
```

## Kjøre

```bash
python app.py
```

Åpne **http://localhost:5050** i nettleseren.

## Deploy (Render + Google-innlogging)

Sjekkliste og OAuth-oppsett (engelsk, steg-for-steg): **[DEPLOY_RENDER.md](DEPLOY_RENDER.md)**. Repoet inkluderer **`render.yaml`** for Blueprint-deploy. På Render kan du ofte utelate `LEADMAP_PUBLIC_URL` — appen bruker da automatisk **`RENDER_EXTERNAL_URL`**.

Første gang du bruker appen uten eksisterende `data/customers.json`: klikk **Importer** og velg et vilkårlig Excel- eller CSV-ark med kundeliste (kolonne for firmanavn og/eller org.nr.). Etter import: trykk **Kjør analyse** for å berike via Brønnøysund og finne leads — typisk 1–2 minutter for ~200 kunder.

Hvis du tidligere har eksportert kunder fra LeadMap, kan appen ved oppstart automatisk gjenopprette fra `kunder_backup.xlsx` i prosjektmappen (samme mappe som `app.py`).

## Hva appen gjør

- **Lead-tabell** med score, signal, kommune, ansatte. Klikk på kolonner for å filtrere.
- **Paginering**: Velg antall rader per side (25–500) for både leads og kunder — færre DOM-noder gir raskere UI (f.eks. ved temabytte).
- **Status-håndtering**: Ny → Kontaktet → Follow-up / Ikke aktuell / Vunnet. Aktive-filteret skjuler ikke-aktuelle og vunne leads.
- **Notater** per lead — skriv inn i tekstfeltet, lagres automatisk når du klikker ut.
- **Legg til kunde**: paste org.nr eller navn → henter automatisk fra brreg.
- **Markér som vunnet**: lead promoteres til kunde, og du får tilbud om å kjøre ny analyse umiddelbart.
- **Knapper per lead**:
  - 🌐 Hjemmeside
  - B Brønnøysund
  - P Proff (åpner i nettleser)
  - in LinkedIn-søk (selskap, alle ansatte, CEO, IT-sjef, innkjøpssjef)
  - 📊 Hent Proff-data lokalt (henter nøkkeltall + roller via web-scraping)
  - 🏆 Markér som vunnet

## Filer og data

```
leadmap/                 # rotmappen til repoet (mappenavn valgfritt)
├── app.py              # Flask-server + ruter
├── enrichment.py       # Brreg-API + Proff-scraping
├── scoring.py          # Lead-scoring (vekter)
├── data/
│   ├── customers.json  # Eksisterende kunder (ankere)
│   ├── leads.json      # Oppdagede leads med score
│   ├── status.json     # Status per orgnr
│   ├── notes.json      # Notater per orgnr
│   ├── proff_data.json # Proff-scraping-cache
│   └── analysis_log.json
├── templates/index.html
└── static/             # CSS + JS-moduler
```

Dataene er ren JSON — easy å backup'e, committe i git, eller redigere i en editor hvis noe blir tullete.

## Endre vekting / scoring

Bruk **Innstillinger** i appen (eller rediger `data/settings.json` / `scoring.py` for standardverdier). Standardvektene er satt slik at *maks teoretisk score* (sum signalvekter + største kryss + største flere-ankere-bonus) er **100** — i tråd med cap i `scoring.py`. Etter lagring re-scores leads.

## Kjente begrensninger

- **Felles styremedlem-matching** krever Proff-API (ca. 1500–3000 kr/mnd). Inntil videre må du klikke deg igjennom Proff manuelt for det.
- **LinkedIn** scraper vi ikke — knappene åpner søk i din innloggede nettleser.
- **Brreg** har en (mild) ratelimit — appen pauser litt mellom kall, så analyse på 200 kunder tar ~2 minutter.
- Ved ny analyse legges signaler kumulativt på leads, men eksisterende status og notater bevares (matchet på org.nr).

## Hvis noe skjærer seg

- Sjekk `data/analysis_log.json` for siste kjøring.
- Slett `data/leads.json` og kjør analyse på nytt hvis lead-listen blir rar.
- Slett `data/customers.json` og bruk **Importer** på nytt for å laste inn kunder fra et nytt ark.
