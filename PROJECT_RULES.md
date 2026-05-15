# PROJECT_RULES.md — retningslinjer for AI-agenter og utviklere

Disse reglene gjelder endringer i **LeadMap**-kodebasen. Avvik krever **eksplisitt beskjed** fra eier av repoet.

---

## 1. Ikke redesign UI uten beskjed

- Ikke endre layout, visuell hierarki, farger, typografi, komponentstruktur eller brukerflyt med mindre brukeren ber om det.
- Små tekst- eller tilgjengelighetsfiks (f.eks. `aria-`, tydeligere knappetekst) er OK når de er direkte knyttet til en annen godkjent oppgave — men unngå «oppussing» av hele skjermbilder.

---

## 2. Ikke refaktorer fungerende kode unødvendig

- Endre bare det som trengs for oppgaven. Ingen «mens vi er her»-omskrivninger, ingen flytting av kode til nye filer uten behov.
- Hvis noe er rotete men virker: la det stå med mindre feilen eller ytelsen krever inngrep.

---

## 3. Behold eksisterende database-struktur hvis mulig

- Prosjektet bruker **JSON-filer og kontrakter** under `data/` (se `AI_HANDOVER.md`). Ikke innfør nye skjemaer, nøkkelnavn eller filformater uten at det er nødvendig og avtalt.
- Når du må utvide data: **bakoverkompatibel** tillegg (valgfrie felt, defensiv lesing), ikke masse omdøping som knekker eksisterende installasjoner.

---

## 4. Små iterative endringer

- Lever i **små steg**: én logisk endring (eller tett relaterte endringer) per runde, med tydelig diff og forklaring.
- Unngå store «alt på en gang»-PR-er som blander feature, refaktor og formattering.

---

## 5. Maks 3–5 filer per refaktor-runde

- Når oppgaven er **refaktor eller strukturflytting**: begrens omfanget til **3–5 filer** per runde. Fullfør, verifiser, deretter neste runde hvis mer gjenstår.
- Unntak: rene bugfiks der færre filer ikke er realistisk — fortsatt hold endringene så lokale som mulig.

---

## 6. Alltid kjør lint/build etter endringer

- Prosjektet har **ingen** sentral `package.json` / CI-definisjon i repoet som standard. Gjør minst:
  - **Python:** `python -m compileall .` fra prosjektroten (eller tilsvarende syntaksjekk), og fiks feil som introduseres.
  - **IDE/linter:** kjør tilgjengelig linter på endrede filer (f.eks. Cursor diagnostics / `read_lints`) og rett nye feil du har skapt.
- Hvis prosjektet senere får `ruff`, `pytest`, e.l.: bruk det som **obligatorisk** etter endringer.

---

## 7. Forklar hvorfor endringer gjøres

- I commit-beskrivelse, PR-tekst eller svar til bruker: **kort «hvorfor»** (problem → løsning), ikke bare «hva» som ble endret.
- Unngå endringer uten sporbar begrunnelse.

---

## 8. Prioriter ytelse og stabilitet fremfor «clean code»

- Foretrekk forutsigbar oppførsel, færre nettverkskall der det gir mening, trygg håndtering av korrupte/manglende JSON-felt og tydelige feilmeldinger — fremfor «penere» abstraksjoner som øker risiko eller kostnad.
- Optimaliser eller forenkle **når det er målt behov eller konkret bug**, ikke for estetikk alene.

---

## Oppsummering for agenter

| Gjør | Ikke gjør |
|------|-----------|
| Små, målrettede diffs | UI-redesign uten avtale |
| Bakoverkompatible dataendringer | Unødvendig refaktor av stabil kode |
| Verifikasjon etter endring | Store refaktorer på mange filer i én runde |
| Forklar årsak | «Clean code» på bekostning av stabilitet/ytelse |

Ved tvil: **spør brukeren** før du utvider omfanget.
