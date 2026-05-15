"""Haversine-avstand og nedskalering av nabobedrift_postnummer basert på meter (Geonorge-koordinater)."""
import math
from typing import Any, Callable, Dict, List, Optional, Set

import scoring as S
from analysis_parallel import _parallel_run
from geonorge_adresse import (
    flush_shared_geo_cache,
    lookup_coords,
    normalize_kommunenummer,
    normalize_postnummer,
    peek_coords_in_disk_cache,
)
from json_store import load_json, save_json
from paths import GEO_CACHE, LEADS_FILE
from persist import save_customers
from related_tree import all_tree_entities_by_orgnr
from state import _enrich_signals_with_anchor_size

# Under lang geokoding: periodisk lagring så avbrudd kan gjenopptas fra geo_cache + delvis oppdaterte JSON-filer.
_GEO_CACHE_FLUSH_EVERY = 15
_ENTITY_DATA_FLUSH_EVERY = 120


def normalize_lead_orgnr(o: Any) -> str:
    """Org.nr som sammenlignbar streng (unngår int/str-mismatch)."""
    if o is None:
        return ""
    return str(o).strip().replace(" ", "")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Avstand på jordoverflate i meter (WGS84-grader inn)."""
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _entity_address_key(e: Dict[str, Any]) -> str:
    adr = (e.get("adresse") or "").strip()
    pnr = normalize_postnummer(e.get("postnummer"))
    knr = normalize_kommunenummer(e.get("kommunenummer"))
    return f"{adr}|{pnr}|{knr}"


def _fill_entity_coords_from_disk_only(entity: Dict[str, Any], disk: Dict[str, Any]) -> None:
    """Fyll geo_lat/geo_lon fra geo_cache uten nettverk. Mangler cache-treff → ingen koordinater."""
    key = _entity_address_key(entity)
    if not key.split("|")[0]:
        entity.pop("geo_lat", None)
        entity.pop("geo_lon", None)
        entity.pop("geo_addr_key", None)
        return
    coords = peek_coords_in_disk_cache(
        entity.get("adresse"),
        entity.get("postnummer"),
        entity.get("kommunenummer"),
        disk,
    )
    if coords:
        entity["geo_lat"], entity["geo_lon"] = coords[0], coords[1]
        entity["geo_addr_key"] = key
    else:
        # Bevar koordinater som allerede ligger på entiteten (lagret fra analyse) når
        # geo_cache mangler treff — ellers blir luftlinje/filter tomme til tross for gyldig data.
        same_key = entity.get("geo_addr_key") == key
        has_coords = entity.get("geo_lat") is not None and entity.get("geo_lon") is not None
        if not (same_key and has_coords):
            entity.pop("geo_lat", None)
            entity.pop("geo_lon", None)
        entity["geo_addr_key"] = key


def ensure_entity_coords(entity: Dict[str, Any], disk_cache: Dict[str, Any]) -> bool:
    """
    Fyller geo_lat, geo_lon, geo_addr_key på entity ved behov.
    Returnerer True hvis koordinater ble satt eller oppdatert.
    """
    key = _entity_address_key(entity)
    if not key.split("|")[0]:
        entity.pop("geo_lat", None)
        entity.pop("geo_lon", None)
        entity.pop("geo_addr_key", None)
        return False

    if entity.get("geo_addr_key") == key and entity.get("geo_lat") is not None and entity.get("geo_lon") is not None:
        return False

    coords = lookup_coords(
        entity.get("adresse"),
        entity.get("postnummer"),
        entity.get("kommunenummer"),
        disk_cache=disk_cache,
    )
    if coords:
        entity["geo_lat"], entity["geo_lon"] = coords[0], coords[1]
        entity["geo_addr_key"] = key
        return True

    entity.pop("geo_lat", None)
    entity.pop("geo_lon", None)
    entity["geo_addr_key"] = key
    return False


def _make_geocode_progress_hook(
    disk: Dict[str, Any],
    tick: Optional[Callable[[], None]],
    *,
    customers: Optional[Dict[str, Any]] = None,
    leads: Optional[List[Dict[str, Any]]] = None,
    geo_every: int = _GEO_CACHE_FLUSH_EVERY,
    entity_every: int = _ENTITY_DATA_FLUSH_EVERY,
) -> Callable[[], None]:
    """Tell fullførte oppslag på tvers av flere _geocode_many_entities-kall; flush cache og ev. kunde/lead-JSON."""
    state = {"n": 0}

    def hook() -> None:
        if tick:
            tick()
        state["n"] += 1
        n = state["n"]
        if geo_every > 0 and (n % geo_every == 0 or n == 1):
            flush_shared_geo_cache(disk)
        if (
            entity_every > 0
            and customers is not None
            and leads is not None
            and n % entity_every == 0
        ):
            save_customers(customers)
            save_json(LEADS_FILE, leads)

    return hook


def _geocode_many_entities(
    entities: List[Dict[str, Any]],
    disk: Dict[str, Any],
    tick: Optional[Callable[[], None]] = None,
    max_workers: int = 8,
) -> int:
    """Parallell Geonorge-geokoding. Returnerer antall entiteter som fikk nye koordinater."""
    if not entities:
        return 0

    def work(ent: Dict[str, Any]) -> bool:
        return ensure_entity_coords(ent, disk)

    if len(entities) == 1:
        n = 1 if work(entities[0]) else 0
        if tick:
            tick()
        return n
    n_ok = 0
    for _, ok in _parallel_run(entities, work, on_progress=tick, max_workers=max_workers):
        if ok:
            n_ok += 1
    return n_ok


def run_geocode_and_attach(
    customers: Dict[str, Any],
    all_leads: Dict[str, Any],
    tick=None,
    *,
    geocode_customers: bool = True,
    lead_orgnrs_to_geocode: Optional[Set[str]] = None,
    persist_geo_cache_every: int = _GEO_CACHE_FLUSH_EVERY,
    persist_entities_every: int = _ENTITY_DATA_FLUSH_EVERY,
) -> tuple:
    """
    Geokoder kunder og leads (delt disk-cache), lagrer geo_cache,
    setter avstandsfaktorer på nabobedrift_postnummer-signaler.
    Returnerer (antall_kunder_oppdatert, antall_leads_oppdatert).

    lead_orgnrs_to_geocode: None = alle leads (som før). Ellers bare leads der normalisert org.nr
    finnes i mengden (typisk nylig oppdaget). Avstandsfaktorer beregnes fortsatt for alle leads.

    Underveis skrives geo_cache.json periodisk (persist_geo_cache_every), og kunder/leads til disk
    periodisk (persist_entities_every; sett 0 for å bare flushe geo_cache, ikke JSON for entiteter).
    """
    S._reload()
    disk = dict(load_json(GEO_CACHE, {}))
    cust_ents = list(all_tree_entities_by_orgnr(customers).values())
    all_lead_list = list(all_leads.values())
    if lead_orgnrs_to_geocode is not None:
        fs = {normalize_lead_orgnr(x) for x in lead_orgnrs_to_geocode}
        lead_ents_to_geo = [L for L in all_lead_list if normalize_lead_orgnr(L.get("orgnr")) in fs]
    else:
        lead_ents_to_geo = all_lead_list
    prog = _make_geocode_progress_hook(
        disk,
        tick,
        customers=customers,
        leads=all_lead_list,
        geo_every=persist_geo_cache_every,
        entity_every=persist_entities_every,
    )
    nc = 0
    if geocode_customers and cust_ents:
        nc = _geocode_many_entities(cust_ents, disk, tick=prog)
    flush_shared_geo_cache(disk)
    if persist_entities_every > 0:
        save_customers(customers)
        save_json(LEADS_FILE, all_lead_list)
    nl = _geocode_many_entities(lead_ents_to_geo, disk, tick=prog)
    flush_shared_geo_cache(disk)
    if persist_entities_every > 0:
        save_customers(customers)
        save_json(LEADS_FILE, all_lead_list)
    save_json(GEO_CACHE, disk)
    by_org = customers_by_orgnr(customers)
    for L in all_leads.values():
        attach_nabobedrift_distance_factors(L, by_org)
    return nc, nl


def customers_by_orgnr(customers: Dict[str, Any]) -> Dict[str, Any]:
    """Org.nr som strengnøkkel — toppkunder og alle noder i kundetrær (for anker-signaler fra datre)."""
    out: Dict[str, Any] = {}
    for o, ent in all_tree_entities_by_orgnr(customers).items():
        out[str(o).strip()] = ent
    return out


def _postnummer_anchor_orgnrs(leads: List[Dict[str, Any]]) -> set:
    """Org.nr som trengs som geokoordinerte ankere for nabobedrift_postnummer-avstand."""
    out: set = set()
    for L in leads:
        for s in L.get("signals") or []:
            if s.get("type") != "nabobedrift_postnummer":
                continue
            ao = s.get("anker_orgnr")
            if ao:
                out.add(str(ao).strip())
    return out


def _lead_has_postnummer_geo_signal(lead: Dict[str, Any]) -> bool:
    """True bare om lead har postnr-signal som kan få meter-avstand (spar unødig geooppslag)."""
    for s in lead.get("signals") or []:
        if s.get("type") == "nabobedrift_postnummer":
            return True
    return False


def hydrate_geo_distance_factors_for_leads(leads: List[Dict[str, Any]], customers: Dict[str, Any]) -> None:
    """
    For API-visning: fyll inn koordinater og avstandsfaktorer uten Geonorge-kall.
    Bruker kun data som allerede ligger i geo_cache (fyllt ved analyse / re-score).
    """
    disk = dict(load_json(GEO_CACHE, {}))
    by_org = customers_by_orgnr(customers)
    for ao in _postnummer_anchor_orgnrs(leads):
        c = by_org.get(ao)
        if c:
            _fill_entity_coords_from_disk_only(c, disk)
    for L in leads:
        if not _lead_has_postnummer_geo_signal(L):
            continue
        _fill_entity_coords_from_disk_only(L, disk)
    for L in leads:
        attach_nabobedrift_distance_factors(L, by_org)


def attach_nabobedrift_distance_factors(lead: Dict[str, Any], by_org: Dict[str, Any]) -> None:
    """
    For hvert nabobedrift_postnummer-signal: sett geo_distance_m og geo_distance_factor (0–1)
    når både lead og anker har koordinater. Ellers fjernes faktorene (full postnr-vekt).
    Mangler koordinater i denne omgangen, men JSON har lagrede meter fra siste analyse:
    gjenopprett dem (slik at /api/leads og filtre fungerer uten fersk geo_cache).
    """
    dmax = float(S.THRESHOLDS.get("nabobedrift_postnr_distance_max_m") or 8000)
    if dmax <= 0:
        dmax = 8000.0

    def _restore_prev(sig: Dict[str, Any], prev_m: Any, prev_f: Any) -> None:
        if prev_m is None:
            return
        try:
            di = float(prev_m)
            sig["geo_distance_m"] = int(round(di))
            if prev_f is not None:
                try:
                    sig["geo_distance_factor"] = max(0.0, min(1.0, float(prev_f)))
                except (TypeError, ValueError):
                    sig["geo_distance_factor"] = max(0.0, min(1.0, 1.0 - (di / dmax)))
            else:
                sig["geo_distance_factor"] = max(0.0, min(1.0, 1.0 - (di / dmax)))
        except (TypeError, ValueError):
            pass

    llat = lead.get("geo_lat")
    llon = lead.get("geo_lon")
    for s in lead.get("signals") or []:
        if s.get("type") != "nabobedrift_postnummer":
            continue
        prev_m = s.get("geo_distance_m")
        prev_f = s.get("geo_distance_factor")
        s.pop("geo_distance_m", None)
        s.pop("geo_distance_factor", None)
        ao = s.get("anker_orgnr")
        if not ao or llat is None or llon is None:
            _restore_prev(s, prev_m, prev_f)
            continue
        cust = by_org.get(str(ao).strip())
        if not cust:
            _restore_prev(s, prev_m, prev_f)
            continue
        clat, clon = cust.get("geo_lat"), cust.get("geo_lon")
        if clat is None or clon is None:
            _restore_prev(s, prev_m, prev_f)
            continue
        d = haversine_m(float(llat), float(llon), float(clat), float(clon))
        factor = max(0.0, min(1.0, 1.0 - (d / dmax)))
        s["geo_distance_m"] = round(d)
        s["geo_distance_factor"] = factor


def refresh_geo_scoring_for_leads(
    leads: List[Dict[str, Any]],
    customers: Dict[str, Any],
    tick: Optional[Callable[[], None]] = None,
    *,
    geocode_customers: bool = True,
    lead_orgnrs_to_geocode: Optional[Set[str]] = None,
    persist_geo_cache_every: int = _GEO_CACHE_FLUSH_EVERY,
    persist_entities_every: int = _ENTITY_DATA_FLUSH_EVERY,
) -> None:
    """
    Geokod kunder + leads og koble avstandsfaktorer (til re-score / innstillinger / analyse).

    lead_orgnrs_to_geocode: None = alle leads. Ellers kun matchende org.nr (f.eks. nye etter målrettet analyse).

    persist_geo_cache_every: lagre geo_cache.json til disk så ofte (0 = aldri underveis, kun ved fase-slutt).
    persist_entities_every: lagre customers + leads.json så ofte (0 = ikke underveis; geo_cache flushes fortsatt).
    """
    S._reload()
    disk = dict(load_json(GEO_CACHE, {}))
    cust_ents = list(all_tree_entities_by_orgnr(customers).values())
    if lead_orgnrs_to_geocode is not None:
        fs = {normalize_lead_orgnr(x) for x in lead_orgnrs_to_geocode}
        leads_to_geo = [L for L in leads if normalize_lead_orgnr(L.get("orgnr")) in fs]
    else:
        leads_to_geo = leads
    prog = _make_geocode_progress_hook(
        disk,
        tick,
        customers=customers,
        leads=leads,
        geo_every=persist_geo_cache_every,
        entity_every=persist_entities_every,
    )
    if geocode_customers and cust_ents:
        _geocode_many_entities(cust_ents, disk, tick=prog)
        flush_shared_geo_cache(disk)
        if persist_entities_every > 0:
            save_customers(customers)
            save_json(LEADS_FILE, leads)
    if leads_to_geo:
        _geocode_many_entities(leads_to_geo, disk, tick=prog)
        flush_shared_geo_cache(disk)
        if persist_entities_every > 0:
            save_customers(customers)
            save_json(LEADS_FILE, leads)
    save_json(GEO_CACHE, disk)
    by_org = customers_by_orgnr(customers)
    for L in leads:
        attach_nabobedrift_distance_factors(L, by_org)


def finalize_leads_scoring_after_geo_refresh(
    leads: List[Dict[str, Any]],
    customers: Dict[str, Any],
    tick: Optional[Callable[[], None]] = None,
) -> None:
    """Etter refresh_geo_scoring_for_leads: lagre kunder, filtrer signaler på anker-størrelse, score og lagre leads."""
    S._reload()
    save_customers(customers)
    _enrich_signals_with_anchor_size(leads)
    by_org = customers_by_orgnr(customers)
    for L in leads:
        attach_nabobedrift_distance_factors(L, by_org)
    for L in leads:
        S.score_lead(L)
        if tick:
            tick()
    leads.sort(key=lambda x: (-x.get("score", 0), -(x.get("antallAnsatte") or 0)))
    save_json(LEADS_FILE, leads)
