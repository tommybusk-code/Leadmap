"""Brreg REST-API: enheter, underenheter, søk."""
import re
from typing import Optional

import requests

BRREG = "https://data.brreg.no/enhetsregisteret/api/enheter"
BRREG_UNDER = "https://data.brreg.no/enhetsregisteret/api/underenheter"
BRREG_REGNSKAP = "https://data.brreg.no/regnskapsregisteret/regnskap"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,text/html;q=0.8,*/*;q=0.5",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
}
TIMEOUT = 10


def _get(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _extract(enhet):
    fa = enhet.get("forretningsadresse") or {}
    pa = enhet.get("postadresse") or {}
    nk1 = enhet.get("naeringskode1") or {}
    orgform = enhet.get("organisasjonsform") or {}
    raw_org = enhet.get("organisasjonsnummer")
    org_str = str(raw_org).strip().replace(" ", "") if raw_org is not None else ""
    return {
        "orgnr": org_str or None,
        "navn": enhet.get("navn"),
        "postnummer": fa.get("postnummer") or pa.get("postnummer"),
        "poststed": fa.get("poststed") or pa.get("poststed"),
        "kommune": fa.get("kommune") or pa.get("kommune"),
        "kommunenummer": fa.get("kommunenummer") or pa.get("kommunenummer"),
        "adresse": " ".join(fa.get("adresse") or pa.get("adresse") or []),
        "naeringskode1": nk1.get("kode"),
        "nace_beskr": nk1.get("beskrivelse"),
        "antallAnsatte": enhet.get("antallAnsatte") or 0,
        "hjemmeside": enhet.get("hjemmeside"),
        "telefon": enhet.get("telefon"),
        "epost": enhet.get("epostadresse"),
        "konkurs": enhet.get("konkurs", False),
        "underAvvikling": enhet.get("underAvvikling", False),
        "erIKonsern": enhet.get("erIKonsern", False),
        "organisasjonsform_kode": orgform.get("kode") or None,
    }


def search_by_name(q: str, size: int = 10) -> list:
    """Søk etter enheter; inkluderer flere orgformer (f.eks. DA) — ikke bare AS/ASA/SA."""
    if not q:
        return []
    qs = (q or "").strip().replace(" ", "")
    if len(qs) < 2 and not re.fullmatch(r"\d{9}", qs):
        return []
    if re.fullmatch(r"\d{9}", qs):
        one = find_company_by_orgnr(qs)
        if one and one.get("orgnr"):
            return [{
                "orgnr": one.get("orgnr"),
                "navn": one.get("navn"),
                "ansatte": one.get("antallAnsatte") or 0,
                "kommune": one.get("kommune"),
                "poststed": one.get("poststed"),
            }]
        return []
    try:
        data = _get(BRREG, {"navn": q.strip(), "size": max(size, 20)})
    except Exception:
        return []
    enheter = (data.get("_embedded") or {}).get("enheter") or []
    out = []
    for e in enheter:
        if e.get("konkurs") or e.get("underAvvikling"):
            continue
        adr = e.get("forretningsadresse") or {}
        ro = e.get("organisasjonsnummer")
        o_str = str(ro).strip().replace(" ", "") if ro is not None else ""
        out.append({
            "orgnr": o_str or None,
            "navn": e.get("navn"),
            "ansatte": e.get("antallAnsatte") or 0,
            "kommune": adr.get("kommune"),
            "poststed": adr.get("poststed"),
        })
        if len(out) >= size:
            break
    return out


def find_company_by_name(name: str) -> Optional[dict]:
    name_clean = re.sub(r"\s+(AS|ASA|SA|HF|IKS)\b", "", name, flags=re.I).strip()
    try:
        data = _get(BRREG, {"navn": name_clean, "size": 5})
    except Exception:
        return None
    enheter = (data.get("_embedded") or {}).get("enheter") or []
    if not enheter:
        return None

    def score(e):
        form = (e.get("organisasjonsform") or {}).get("kode", "")
        s = 0
        if form in ("AS", "ASA"):
            s += 10
        if form in ("ENK", "NUF"):
            s -= 5
        if e.get("konkurs") or e.get("underAvvikling"):
            s -= 100
        ne = (e.get("navn") or "").upper()
        target = name_clean.upper()
        if ne == target:
            s += 30
        elif target in ne:
            s += 15
        s += min(int((e.get("antallAnsatte") or 0) ** 0.5), 30)
        return s

    enheter.sort(key=score, reverse=True)
    return _extract(enheter[0])


def find_company_by_orgnr(orgnr: str) -> Optional[dict]:
    orgnr = orgnr.strip().replace(" ", "")
    try:
        data = _get(f"{BRREG}/{orgnr}")
    except Exception:
        return None
    return _extract(data)


def search_kommune(kommunenummer: str, size: int = 20) -> list:
    try:
        data = _get(BRREG, {
            "forretningsadresse.kommunenummer": kommunenummer,
            "size": size, "konkurs": "false",
            "sort": "antallAnsatte,desc",
        })
    except Exception:
        return []
    enheter = (data.get("_embedded") or {}).get("enheter") or []
    return [_extract(e) for e in enheter]


def search_postnummer(postnummer: str, size: int = 20) -> list:
    try:
        data = _get(BRREG, {
            "forretningsadresse.postnummer": postnummer,
            "size": size, "konkurs": "false",
            "sort": "antallAnsatte,desc",
        })
    except Exception:
        return []
    enheter = (data.get("_embedded") or {}).get("enheter") or []
    return [_extract(e) for e in enheter]


def search_nace(naeringskode: str, size: int = 20) -> list:
    try:
        data = _get(BRREG, {
            "naeringskode": naeringskode,
            "size": size, "konkurs": "false",
            "sort": "antallAnsatte,desc",
        })
    except Exception:
        return []
    enheter = (data.get("_embedded") or {}).get("enheter") or []
    return [_extract(e) for e in enheter]


def _extract_under(e):
    fa = e.get("beliggenhetsadresse") or e.get("forretningsadresse") or {}
    nk = e.get("naeringskode1") or {}
    uo = e.get("organisasjonsnummer")
    u_str = str(uo).strip().replace(" ", "") if uo is not None else ""
    return {
        "orgnr": u_str or None,
        "navn": e.get("navn"),
        "antallAnsatte": e.get("antallAnsatte") or 0,
        "kommune": fa.get("kommune"),
        "kommunenummer": fa.get("kommunenummer"),
        "naeringskode1": nk.get("kode"),
        "nace_beskr": nk.get("beskrivelse"),
        "type": "underenhet",
    }


def fetch_underenheter(orgnr: str) -> list:
    if not orgnr:
        return []
    out = []
    page = 0
    while True:
        try:
            data = _get(BRREG_UNDER, {"overordnetEnhet": orgnr, "size": 100, "page": page})
        except Exception:
            break
        items = (data.get("_embedded") or {}).get("underenheter") or []
        if not items:
            break
        out.extend(_extract_under(e) for e in items)
        page_info = data.get("page") or {}
        total_pages = page_info.get("totalPages", 1)
        if page + 1 >= total_pages:
            break
        page += 1
        if page > 20:
            break
    return out
