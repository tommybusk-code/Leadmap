"""state.py — Flask-app, global state, lead-hjelpere, analyse-logging.
Filstier/JSON/kunder ligger i paths.py, json_store.py og persist.py.
"""
import threading
from datetime import datetime, date

from flask import Flask

import scoring as S
from lead_geo import attach_postnummer_signal_geo_match_tiers, customers_by_orgnr_map
from json_store import load_json, save_json
from related_tree import norm_org
from paths import (
    ANSATTE_HISTORY,
    ANALYSIS_LOG,
    DISCOVERY_CACHE,
    LEAD_RELATIONS,
    LEADS_FILE,
    NOTES_FILE,
    ROOT,
    ROLLER_CACHE,
    STATUS_FILE,
)
from persist import (
    _effective_ansatte,
    get_customers,
    get_leads_readonly,
    get_notes,
    get_status,
    import_xlsx_if_empty,
    save_customers,
)

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))

_analysis = {"running": False, "progress": "", "log": [], "current": 0, "total": 0, "phase": "", "job": ""}
_import_state = {
    "running": False, "progress": "", "log": [], "result": None,
    "current": 0, "total": 0, "job": "",
}
_lock = threading.Lock()


def _enrich_signals_with_anchor_size(leads, thresholds=None):
    """Sett anker_ansatte (effektivt = inkl. underenheter) på hvert signal.

    Signal fra anker under min_anchor_ansatte (innstilling) droppes — unntatt nabobedrift_postnummer
    og nabobedrift_kommune, som er geografiske og skal beholde Kartverket-avstand/score.
    """
    thr = thresholds if thresholds is not None else S.THRESHOLDS
    customers = get_customers()
    eff_by_orgnr = {}
    for c in customers.values():
        o = c.get("orgnr")
        if o:
            eff_by_orgnr[str(o).strip()] = _effective_ansatte(c)
    min_anchor = int(thr.get("min_anchor_ansatte", 0) or 0)
    by_org = customers_by_orgnr_map(customers)
    for L in leads:
        sigs = L.get("signals", []) or []
        kept = []
        for s in sigs:
            ao = s.get("anker_orgnr")
            if ao:
                key = str(ao).strip()
                if key in eff_by_orgnr:
                    eff = eff_by_orgnr[key]
                    s["anker_ansatte"] = eff
                    if min_anchor > 0 and eff < min_anchor:
                        # Behold geo-signaler: små ankere skal fortsatt kunne få meter/avstand og riktig geo-score.
                        if s.get("type") not in S.GEO_SIGNALS:
                            continue
            kept.append(s)
        L["signals"] = kept
        L["anker_orgnrs"] = list({s["anker_orgnr"] for s in kept if s.get("anker_orgnr")})
        L["anker_navn"] = list({s["anker_navn"] for s in kept if s.get("anker_navn")})
        attach_postnummer_signal_geo_match_tiers(L, by_org)


def _remove_anchor_from_leads(orgnrs_to_remove):
    if not orgnrs_to_remove:
        return
    rm = set(orgnrs_to_remove)
    leads = get_leads_readonly()
    if not leads:
        return
    status = get_status()
    PROMOTED = {"eksisterende_kunde", "datterselskap", "vunnet", "konsern_kunde"}
    out = []
    for L in leads:
        if status.get(norm_org(L.get("orgnr"))) in PROMOTED:
            continue
        L["signals"] = [s for s in L.get("signals", []) if s.get("anker_orgnr") not in rm]
        if L.get("felles_styre"):
            L["felles_styre"] = [fs for fs in L["felles_styre"] if fs.get("anker_orgnr") not in rm]
        L["anker_orgnrs"] = [a for a in L.get("anker_orgnrs", []) if a not in rm]
        L["anker_navn"] = list({s["anker_navn"] for s in L["signals"] if s.get("anker_navn")})
        if L["signals"]:
            S.score_lead(L)
            out.append(L)
    out.sort(key=lambda x: (-x.get("score", 0), -(x.get("antallAnsatte") or 0)))
    save_json(LEADS_FILE, out)


def migrate_lead(L):
    """Konverter eldre single-signal leads til nytt multi-signal format."""
    if L.get("signals") and isinstance(L["signals"], list) and len(L["signals"]) > 0:
        return False
    old_sig = L.get("signal", "")

    anker_orgnrs = L.get("anker_orgnrs") or []
    raw_navn = L.get("anker_navn")
    if isinstance(raw_navn, list):
        anker_navn_list = [n for n in raw_navn if n]
    elif raw_navn:
        anker_navn_list = [raw_navn]
    else:
        anker_navn_list = [""]

    ankers = []
    for i, navn in enumerate(anker_navn_list):
        org = anker_orgnrs[i] if i < len(anker_orgnrs) else None
        ankers.append((org, navn))
    if not ankers:
        ankers = [(None, "")]

    def types_for(old):
        if old == "konsernselskap":
            return [("felles_styreleder", "Konsernselskap (migrert)")]
        elif old == "felles_styreleder":
            return [("felles_styreleder", None)]
        elif old in ("felles_styremedlem", "felles_styre"):
            return [("felles_styremedlem", None)]
        elif "_postnummer+samme_bransje" in old:
            return [("nabobedrift_postnummer", "Samme postnummer (migrert)"),
                    ("samme_bransje", "Samme NACE (migrert)")]
        elif "_kommune+samme_bransje" in old:
            return [("nabobedrift_kommune", "Samme kommune (migrert)"),
                    ("samme_bransje", "Samme NACE (migrert)")]
        elif old == "nabobedrift_postnummer":
            return [("nabobedrift_postnummer", "Samme postnummer (migrert)")]
        elif old == "nabobedrift_kommune":
            return [("nabobedrift_kommune", "Samme kommune (migrert)")]
        elif old == "samme_bransje":
            return [("samme_bransje", "Samme NACE (migrert)")]
        return [("samme_bransje", "Migrert fra eldre data")]

    type_list = types_for(old_sig)
    sigs = []
    for org, navn in ankers:
        for t, det in type_list:
            sigs.append({"type": t, "anker_orgnr": org, "anker_navn": navn, "detail": det})

    L["signals"] = sigs
    for k in ("signal_score", "ansatte_score"):
        L.pop(k, None)
    return True


def _log(msg):
    print(msg, flush=True)
    with _lock:
        _analysis["log"].append({"t": datetime.now().isoformat(timespec="seconds"), "msg": msg})
        _analysis["progress"] = msg


def _set_phase(phase, total=0):
    """Utvid total med antall enheter i denne fasen; nullstill ikke current (kumulativ fremdrift)."""
    with _lock:
        cur = int(_analysis.get("current") or 0)
        add = int(total or 0)
        _analysis["phase"] = phase
        _analysis["total"] = cur + add
        _analysis["progress"] = phase


def _tick(n=1):
    with _lock:
        _analysis["current"] = int(_analysis.get("current") or 0) + n


def _tick_safe(n=1):
    """Trådsikker tick — brukes fra ThreadPoolExecutor-arbeidere."""
    _tick(n)


def get_jobs_overview():
    """
    Oversikt over bakgrunnsjobber for UI og API.

    To uavhengige «sluser»:
    - analyse/geo/målrettet deler _analysis (maks én; ny start avvises — ingen kø).
    - Excel-import og «oppdater alle relaterte» deler _import_state (maks én av disse).
    De to slusene kan være aktive samtidig (da kan samme kundedata skrives fra begge).
    """
    with _lock:
        pipe_running = bool(_analysis["running"])
        pipe_job = (_analysis.get("job") or "").strip()

    cust_running = bool(_import_state.get("running"))
    cust_job = (_import_state.get("job") or "").strip()

    def _pipe_label() -> str:
        if not pipe_running:
            return ""
        if pipe_job == "geo":
            return "Geo + score"
        if pipe_job == "analyze":
            return "Analyse (full eller målrettet)"
        return "Analyse / geo (starter…)"

    def _cust_label() -> str:
        if not cust_running:
            return ""
        if cust_job == "import":
            return "Kundeimport (Excel/CSV)"
        if cust_job == "refresh_related":
            return "Oppdater alle relaterte"
        if cust_job == "aksjonaerinfo":
            return "Oppdater alle (aksjonærinfo / tre)"
        if cust_job == "promote_whole_owned":
            return "Heleide leads → kundetrær"
        return "Import eller relaterte (starter…)"

    p_label = _pipe_label()
    c_label = _cust_label()
    both = pipe_running and cust_running
    concurrent_hint = None
    if both and p_label and c_label:
        concurrent_hint = (
            f"Samtidig aktivitet: «{p_label}» og «{c_label}». "
            "Ulike jobb-køer, men begge kan skrive kunde- og lead-filer. "
            "Vent gjerne med nye store operasjoner til begge er ferdige."
        )

    rules = [
        "Analyse, geo+score og målrettet analyse kan ikke kjøre samtidig — "
        "pågår en allerede, avvises en ny (ingen automatisk kø).",
        "Excel-import og «oppdater alle relaterte» kan ikke kjøre samtidig med hverandre.",
        "Import/oppdater-relaterte og analyse/geo kan startes samtidig (to uavhengige jobber).",
    ]

    return {
        "analysis": {
            "running": pipe_running,
            "job": pipe_job,
            "label": p_label,
        },
        "customer_sync": {
            "running": cust_running,
            "job": cust_job,
            "label": c_label,
        },
        "active_channels": int(pipe_running) + int(cust_running),
        "both_running": both,
        "concurrent_hint": concurrent_hint,
        "rules": rules,
    }


def _vekst_check(orgnr, ansatte, history):
    if not orgnr:
        return None, None
    today = date.today().isoformat()
    series = history.get(orgnr, [])
    vekst_pct, basis_ansatte = None, None
    if series and ansatte:
        first = next((p for p in series if p.get("ansatte")), None)
        if first and first["ansatte"] > 0:
            change = (ansatte - first["ansatte"]) / first["ansatte"]
            if change >= 0.15:
                vekst_pct = round(change * 100, 1)
                basis_ansatte = first["ansatte"]
    if not series or series[-1]["date"] != today:
        series.append({"date": today, "ansatte": ansatte or 0})
        series = series[-12:]
    history[orgnr] = series
    return vekst_pct, basis_ansatte


def _track_employee_history(orgnr, ansatte):
    if not orgnr:
        return None, None
    history = load_json(ANSATTE_HISTORY, {})
    vekst_pct, basis_ansatte = _vekst_check(orgnr, ansatte, history)
    save_json(ANSATTE_HISTORY, history)
    return vekst_pct, basis_ansatte


# web_api (/api/leads, eksport, kunder, innstillinger, …) — må registreres også når app lastes som `state:app` utenom app.py
import customers  # noqa: E402, F401
