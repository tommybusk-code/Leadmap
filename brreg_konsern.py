"""Konsern/regnskap fra Brreg (koblet til brreg_api)."""
import re
from typing import Any, Dict, Optional

import requests

from brreg_api import BRREG_REGNSKAP, fetch_underenheter, find_company_by_orgnr
from related_tree import merge_fetch_related


def _regnskaps_dato(r: dict) -> str:
    return ((r.get("regnskapsperiode") or {}).get("fraDato") or "")


def _nokkeltall_fra_regnskap_row(row: Optional[dict]) -> Dict[str, int]:
    """Utvalgte tall fra ett regnskapsdokument (Brreg JSON)."""
    if not row:
        return {}
    out: Dict[str, int] = {}
    ei = row.get("eiendeler") or {}
    se = ei.get("sumEiendeler")
    if se is not None:
        out["sum_eiendeler"] = int(float(se))
    egbl = row.get("egenkapitalGjeld") or {}
    eg = egbl.get("egenkapital") or {}
    seg = eg.get("sumEgenkapital")
    if seg is not None:
        out["sum_egenkapital"] = int(float(seg))
    rr = row.get("resultatregnskapResultat") or {}
    ar = rr.get("aarsresultat")
    if ar is not None:
        out["aarsresultat"] = int(float(ar))
    drb = rr.get("driftsresultat") or {}
    dr = drb.get("driftsresultat")
    if dr is not None:
        out["driftsresultat"] = int(float(dr))
    return out


def _siste_ikke_konsern_regnskap(regnskap_list: list) -> Optional[dict]:
    """Nyeste årsregnskap som ikke er konsolidert konsern (typisk SELSKAP)."""
    rows = [
        r for r in (regnskap_list or [])
        if r and "KONSERN" not in (r.get("regnskapstype") or "").upper()
    ]
    if not rows:
        return None
    rows.sort(key=_regnskaps_dato, reverse=True)
    return rows[0]


def _regnskap_tillegg_selskap(regnskap_list: list) -> dict:
    """Flagg og nøkkeltall fra eget selskapsregnskap (alltid fra denne enhetens orgnr)."""
    if not regnskap_list:
        return {}
    row = _siste_ikke_konsern_regnskap(regnskap_list)
    if not row:
        return {}
    out: Dict[str, Any] = {}
    periode = (row.get("regnskapsperiode") or {}).get("fraDato") or ""
    if periode:
        out["regnskap_siste_aar"] = periode[:4]
    vir = row.get("virksomhet") or {}
    ms = vir.get("morselskap")
    if ms is True:
        out["rapporterer_til_konsern"] = True
    elif ms is False:
        out["rapporterer_til_konsern"] = False
    for k, v in _nokkeltall_fra_regnskap_row(row).items():
        out[f"selskap_{k}"] = v
    return out


def _fetch_regnskap_raw(orgnr: str) -> list:
    if not orgnr:
        return []
    try:
        url = f"{BRREG_REGNSKAP}/{orgnr}"
        r = requests.get(url, timeout=10, headers={"Accept": "application/json"})
        if r.status_code != 200:
            return []
        data = r.json()
        return data if isinstance(data, list) else ([data] if data else [])
    except Exception:
        return []


def _extract_konsern_info(regnskap_list: list) -> dict:
    konsern_only = [r for r in regnskap_list
                    if "KONSERN" in (r.get("regnskapstype") or "").upper()]
    if not konsern_only:
        return {}

    konsern_only.sort(key=_regnskaps_dato, reverse=True)
    latest = konsern_only[0]
    ansatte = int(latest.get("antallAnsatte") or 0)
    period = (latest.get("regnskapsperiode") or {}).get("fraDato") or ""
    tall = _nokkeltall_fra_regnskap_row(latest)
    if not ansatte and not tall.get("sum_eiendeler"):
        return {}
    info: Dict[str, Any] = {
        "konsern_ansatte": ansatte,
        "konsern_periode": period[:4] if period else None,
    }
    for k, v in tall.items():
        info[f"konsern_{k}"] = v
    return info


def _find_mor_orgnr(regnskap_list: list) -> Optional[str]:
    for r in regnskap_list:
        for key in ("morselskap", "morselskapOrgnr", "morOrgnr"):
            v = r.get(key)
            if isinstance(v, str) and re.fullmatch(r"\d{9}", v):
                return v
            if isinstance(v, dict):
                ron = v.get("organisasjonsnummer") or v.get("orgnr")
                if ron and re.fullmatch(r"\d{9}", str(ron)):
                    return str(ron)
        virk = r.get("virksomhet") or {}
        for key in ("morselskap", "morselskapOrgnr"):
            v = virk.get(key)
            if isinstance(v, str) and re.fullmatch(r"\d{9}", v):
                return v
            if isinstance(v, dict):
                ron = v.get("organisasjonsnummer") or v.get("orgnr")
                if ron and re.fullmatch(r"\d{9}", str(ron)):
                    return str(ron)
    return None


def fetch_konsern_ansatte(orgnr: str) -> dict:
    if not orgnr:
        return {}
    own_regnskap = _fetch_regnskap_raw(orgnr)
    if not own_regnskap:
        return {}
    out: Dict[str, Any] = dict(_regnskap_tillegg_selskap(own_regnskap))
    info = _extract_konsern_info(own_regnskap)
    if info:
        info["konsern_kilde"] = "eget"
        out.update(info)
        return out
    mor_orgnr = _find_mor_orgnr(own_regnskap)
    if mor_orgnr and mor_orgnr != orgnr:
        mor_regnskap = _fetch_regnskap_raw(mor_orgnr)
        info = _extract_konsern_info(mor_regnskap)
        if info:
            info["konsern_kilde"] = "morselskap"
            info["mor_orgnr"] = mor_orgnr
            mor_enhet = find_company_by_orgnr(mor_orgnr)
            if mor_enhet:
                info["mor_navn"] = mor_enhet.get("navn")
            out.update(info)
            return out
    return out


def resolve_mor_orgnr_from_regnskap(orgnr: str) -> Optional[str]:
    """Organisasjonsnummer til rapportert morselskap i regnskap (konsern), om satt."""
    if not orgnr:
        return None
    rows = _fetch_regnskap_raw(orgnr.strip().replace(" ", ""))
    if not rows:
        return None
    return _find_mor_orgnr(rows)


def fetch_related(
    orgnr: str, navn: str, kommunenummer: str = None, existing_related: dict = None
) -> dict:
    under = fetch_underenheter(orgnr)
    out = {"underenheter": under, "underenheter_antall": len(under)}
    konsern = fetch_konsern_ansatte(orgnr)
    if konsern:
        out.update(konsern)
    return merge_fetch_related(existing_related, out)
