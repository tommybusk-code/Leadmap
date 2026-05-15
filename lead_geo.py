"""lead_geo.py — Utleder geo_tier / geo_label / geo_detail for leads (én «geoscore»-presentasjon)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from related_tree import all_tree_entities_by_orgnr

# Samme prefiks→fylke som i frontend (core.js FYLKE_MAP). Hold disse to stedene i synk.
_FYLKE_BY_KNR_PREFIX = {
    "03": "Oslo",
    "11": "Rogaland",
    "15": "Møre og Romsdal",
    "18": "Nordland",
    "31": "Østfold",
    "32": "Akershus",
    "33": "Buskerud",
    "34": "Innlandet",
    "39": "Vestfold",
    "40": "Telemark",
    "42": "Agder",
    "46": "Vestland",
    "50": "Trøndelag",
    "54": "Troms og Finnmark",  # eldre 54xx-serie (før dagens 55/56-inndeling)
    "55": "Troms",
    "56": "Finnmark",
}


def fylke_for(kommunenummer: Any) -> Optional[str]:
    """Fylkesnavn ut fra kommunenummer — samme sifferlogikk som ``fylkeFor`` i ``static/core.js``."""
    if kommunenummer is None or kommunenummer == "":
        return None
    digits = re.sub(r"\D", "", str(kommunenummer).strip())
    if not digits or len(digits) < 2:
        return None
    kn = digits.zfill(4)[-4:] if len(digits) <= 4 else digits[:4]
    prefix2 = kn[:2]
    if prefix2 == "00":
        return None
    return _FYLKE_BY_KNR_PREFIX.get(prefix2)


def _norm_addr(s: Any) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def attach_postnummer_signal_geo_match_tiers(lead: dict, customers_by_orgnr: Dict[str, dict]) -> None:
    """Sett ``geo_match_tier`` på hvert ``nabobedrift_postnummer``-signal: ``adresse`` vs ``postnr``.

    Brukes i scoring for å veie samme besøksadresse tyngre enn kun samme postnummer (uavhengig av brukervekter).
    """
    la = _norm_addr(lead.get("adresse"))
    lp = (lead.get("postnummer") or "").strip()
    for s in lead.get("signals") or []:
        if s.get("type") != "nabobedrift_postnummer":
            continue
        ao = s.get("anker_orgnr")
        if not ao:
            s["geo_match_tier"] = "postnr"
            continue
        c = customers_by_orgnr.get(str(ao).strip())
        if not c:
            s["geo_match_tier"] = "postnr"
            continue
        ca = _norm_addr(c.get("adresse"))
        cp = (c.get("postnummer") or "").strip()
        if la and lp and ca and la == ca and lp == cp:
            s["geo_match_tier"] = "adresse"
        else:
            s["geo_match_tier"] = "postnr"


def _min_nabobedrift_postnummer_distance_m(lead: dict) -> Optional[int]:
    """Laveste geo_distance_m blant nabobedrift_postnummer-signaler (meter, avrundet)."""
    best: Optional[int] = None
    for s in lead.get("signals") or []:
        if s.get("type") != "nabobedrift_postnummer":
            continue
        d = s.get("geo_distance_m")
        if d is None:
            continue
        try:
            di = int(round(float(d)))
        except (TypeError, ValueError):
            continue
        if di < 0:
            continue
        if best is None or di < best:
            best = di
    return best


# Geoscore-sortering: lavere tall = nærmere. Ikke-geokoordinert geo får store plassholdere.
_GEOSCORE_POSTNR_NO_COORDS = 7_500_000
_GEOSCORE_KOMMUNE = 15_000_000
_GEOSCORE_FYLKE = 40_000_000


def _geoscore_for_lead(lead: dict, tier: Optional[str]) -> Optional[int]:
    """Lav verdi = nærmere anker (meter). None = ingen geo-relatert signal."""
    if not tier:
        return None
    md = _min_nabobedrift_postnummer_distance_m(lead)
    if md is not None:
        return md
    if tier in ("adresse", "postnr"):
        return _GEOSCORE_POSTNR_NO_COORDS
    if tier == "kommune":
        return _GEOSCORE_KOMMUNE
    if tier == "fylke":
        return _GEOSCORE_FYLKE
    return None


def _anchor_orgnrs(lead: dict) -> List[str]:
    out: List[str] = []
    seen = set()
    for s in lead.get("signals") or []:
        ao = s.get("anker_orgnr")
        if ao and ao not in seen:
            seen.add(ao)
            out.append(ao)
    for fs in lead.get("felles_styre") or []:
        ao = fs.get("anker_orgnr")
        if ao and ao not in seen:
            seen.add(ao)
            out.append(ao)
    return out


def enrich_lead_geo(lead: dict, customers_by_orgnr: Dict[str, dict]) -> None:
    """Setter geo_tier, geo_label, geo_detail på lead-dict (API-respons, ikke nødvendigvis lagret).

    geo_detail inneholder navn på berørte kunder (ankre) der det er mulig, ikke bare generisk tekst.
    """
    types = {s.get("type") for s in lead.get("signals") or []}
    has_post = "nabobedrift_postnummer" in types
    has_komm = "nabobedrift_kommune" in types

    tier: Optional[str] = None
    label = ""
    detail = ""
    matched_anker_navn: List[str] = []
    matched_anker_orgnrs: List[str] = []

    if has_post:
        tier = "postnr"
        label = "Postnr"
        names_post_all: List[str] = []
        seen_post_a: set = set()
        for s in lead.get("signals") or []:
            if s.get("type") != "nabobedrift_postnummer":
                continue
            ao = s.get("anker_orgnr")
            if not ao:
                continue
            so = str(ao).strip()
            if so in seen_post_a:
                continue
            seen_post_a.add(so)
            c = customers_by_orgnr.get(so)
            nm = (s.get("anker_navn") or (c.get("navn") if c else "") or so).strip()
            if nm:
                names_post_all.append(nm)

        la = _norm_addr(lead.get("adresse"))
        lp = (lead.get("postnummer") or "").strip()
        if la and lp:
            for s in lead.get("signals") or []:
                if s.get("type") != "nabobedrift_postnummer":
                    continue
                ao = s.get("anker_orgnr")
                c = customers_by_orgnr.get(str(ao).strip()) if ao else None
                if not c:
                    continue
                ca = _norm_addr(c.get("adresse"))
                cp = (c.get("postnummer") or "").strip()
                if ca and la == ca and cp and lp == cp:
                    tier = "adresse"
                    label = "Adresse"
                    so = str(ao).strip()
                    nm = (c.get("navn") or "").strip() or so or "kunde"
                    if so and so not in matched_anker_orgnrs:
                        matched_anker_orgnrs.append(so)
                    if nm not in matched_anker_navn:
                        matched_anker_navn.append(nm)

        if matched_anker_navn:
            detail = "Samme besøksadresse og postnummer som: " + ", ".join(matched_anker_navn[:10])
            if len(matched_anker_navn) > 10:
                detail += f" (+{len(matched_anker_navn) - 10} til)"
        elif names_post_all:
            detail = "Samme postnummer som: " + ", ".join(names_post_all[:10])
            if len(names_post_all) > 10:
                detail += f" (+{len(names_post_all) - 10} til)"
        else:
            detail = "Samme postnummer som minst én kunde (scoring)"

        md = _min_nabobedrift_postnummer_distance_m(lead)
        if md is not None:
            detail = f"{detail} Ca. {md} m luftlinje til nærmeste anker (Kartverket)."
    elif has_komm:
        tier = "kommune"
        label = "Kommune"
        names_k: List[str] = []
        seen_k: set = set()
        for s in lead.get("signals") or []:
            if s.get("type") != "nabobedrift_kommune":
                continue
            ao = s.get("anker_orgnr")
            if not ao:
                continue
            so = str(ao).strip()
            if so in seen_k:
                continue
            seen_k.add(so)
            c = customers_by_orgnr.get(so)
            nm = (s.get("anker_navn") or (c.get("navn") if c else "") or so).strip()
            if nm:
                names_k.append(nm)
        if names_k:
            detail = "Samme kommune som: " + ", ".join(names_k[:10])
            if len(names_k) > 10:
                detail += f" (+{len(names_k) - 10} til)"
        else:
            detail = "Samme kommune som minst én kunde (scoring)"
    else:
        lf = fylke_for(lead.get("kommunenummer"))
        if lf:
            names_f: List[str] = []
            seen_f: set = set()
            for ao in _anchor_orgnrs(lead):
                c = customers_by_orgnr.get(str(ao).strip()) if ao else None
                if not c:
                    continue
                if fylke_for(c.get("kommunenummer")) != lf:
                    continue
                so = str(ao).strip()
                if so in seen_f:
                    continue
                seen_f.add(so)
                nm = (c.get("navn") or "").strip() or so
                names_f.append(nm)
            if names_f:
                tier = "fylke"
                label = "Fylke"
                detail = f"Samme fylke ({lf}) som: " + ", ".join(names_f[:10])
                if len(names_f) > 10:
                    detail += f" (+{len(names_f) - 10} til)"

    if tier:
        lead["geo_tier"] = tier
        lead["geo_label"] = label
        lead["geo_detail"] = detail
        gs = _geoscore_for_lead(lead, tier)
        if gs is not None:
            lead["geoscore"] = gs
        else:
            lead.pop("geoscore", None)
        if matched_anker_navn:
            lead["geo_match_anker_navn"] = matched_anker_navn
        else:
            lead.pop("geo_match_anker_navn", None)
        if matched_anker_orgnrs:
            lead["geo_match_anker_orgnrs"] = matched_anker_orgnrs
        else:
            lead.pop("geo_match_anker_orgnrs", None)
    else:
        lead.pop("geo_tier", None)
        lead.pop("geo_label", None)
        lead.pop("geo_detail", None)
        lead.pop("geoscore", None)
        lead.pop("geo_match_anker_navn", None)
        lead.pop("geo_match_anker_orgnrs", None)


def customers_by_orgnr_map(customers: Dict[str, Any]) -> Dict[str, dict]:
    """Toppkunder + tre-noder (samme som geo_enrichment.customers_by_orgnr)."""
    out: Dict[str, dict] = {}
    for o, ent in all_tree_entities_by_orgnr(customers).items():
        out[str(o).strip()] = ent
    return out
