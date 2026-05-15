"""Lead-discovery per anker (NACE/kommune/postnr)."""
import time

from brreg_api import search_kommune, search_nace, search_postnummer

SKIP_NACE_PREFIXES = ("84.", "85.", "86.", "87.", "88.", "94.", "91.", "93.")
MIN_ANSATTE_DEFAULT = 4


def _current_min_ansatte():
    try:
        import scoring as S
        return int(S.THRESHOLDS.get("min_lead_ansatte", MIN_ANSATTE_DEFAULT))
    except Exception:
        return MIN_ANSATTE_DEFAULT


def is_lead_candidate(e: dict) -> bool:
    if e.get("konkurs") or e.get("underAvvikling"):
        return False
    nk = e.get("naeringskode1") or ""
    if any(nk.startswith(p) for p in SKIP_NACE_PREFIXES):
        return False
    if (e.get("antallAnsatte") or 0) < _current_min_ansatte():
        return False
    return True


def discover_leads_for_anchor(anchor: dict, throttle: float = 0.15) -> list:
    found = {}
    a_navn = anchor.get("navn") or anchor.get("orgnr") or "?"
    a_orgnr = anchor.get("orgnr")
    a_kommune = anchor.get("kommune") or ""
    a_postnr = anchor.get("postnummer") or ""
    a_nace = anchor.get("naeringskode1") or ""
    a_nace_b = anchor.get("nace_beskr") or ""

    def add(cand, signal_type, detail=None):
        orgnr = cand.get("orgnr")
        if not orgnr or orgnr == a_orgnr:
            return
        if not is_lead_candidate(cand):
            return
        if orgnr not in found:
            found[orgnr] = dict(cand)
            found[orgnr]["signals"] = []
        sig = {"type": signal_type, "anker_orgnr": a_orgnr, "anker_navn": a_navn}
        if detail:
            sig["detail"] = detail
        existing = found[orgnr]["signals"]
        if not any(s["type"] == signal_type and s["anker_orgnr"] == a_orgnr for s in existing):
            existing.append(sig)

    knr = anchor.get("kommunenummer")
    pnr = anchor.get("postnummer")
    nace = a_nace

    if knr:
        for c in search_kommune(knr, size=20):
            add(c, "nabobedrift_kommune", f"Samme kommune: {a_kommune}")
            if nace and c.get("naeringskode1") == nace:
                add(c, "samme_bransje", f"Samme NACE {nace} — {a_nace_b[:40]}")
        time.sleep(throttle)

    if pnr:
        for c in search_postnummer(pnr, size=20):
            add(c, "nabobedrift_postnummer", f"Samme postnummer: {pnr}")
            if nace and c.get("naeringskode1") == nace:
                add(c, "samme_bransje", f"Samme NACE {nace} — {a_nace_b[:40]}")
        time.sleep(throttle)

    if nace:
        for c in search_nace(nace, size=15):
            add(c, "samme_bransje", f"Samme NACE {nace} — {a_nace_b[:40]}")
        time.sleep(throttle)

    return list(found.values())
