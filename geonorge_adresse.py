"""Geokoding via Kartverket/Geonorge Adresse-API (åpent REST, ingen nøkkel)."""
import hashlib
import threading
import time
from typing import Any, Dict, Optional, Tuple

import requests

from paths import GEO_CACHE
from json_store import load_json, save_json

GEONORGE_SOK = "https://ws.geonorge.no/adresser/v1/sok"
TIMEOUT = 12
SLEEP_S = 0.08

_SESSION = requests.Session()
_SESSION.headers.update({
    # HTTP headers must be encodable as latin-1; non-ASCII here breaks every request silently.
    "User-Agent": "LeadMap/1.0 (adresse til koordinater)",
    "Accept": "application/json",
})

_file_lock = threading.Lock()
# Når flere tråder deler samme disk_cache-in-memory (parallell geokoding), må oppslag/oppdatering synkroniseres.
_mem_cache_lock = threading.Lock()
_session_lock = threading.Lock()


def normalize_kommunenummer(k: Any) -> str:
    if k is None:
        return ""
    s = str(k).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit():
        return s.zfill(4)
    return s


def normalize_postnummer(p: Any) -> str:
    if p is None:
        return ""
    s = str(p).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit():
        return s.zfill(4)
    return s


def cache_key(adresse: str, postnummer: str, kommunenummer: str) -> str:
    raw = f"{(adresse or '').strip().lower()}|{postnummer}|{kommunenummer}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_disk_cache() -> Dict[str, Any]:
    with _file_lock:
        return dict(load_json(GEO_CACHE, {}))


def _write_disk_cache(cache: Dict[str, Any]) -> None:
    with _file_lock:
        save_json(GEO_CACHE, cache)


def flush_shared_geo_cache(disk_cache: Dict[str, Any]) -> None:
    """
    Skriv in-memory batch-cache til geo_cache.json uten å miste pågående parallell-skriving.
    Brukes under lang geokoding slik at avbrudd gir gjenopptak fra cache og UI kan lese fila underveis.

    Slår alltid sammen med innhold som allerede ligger på disk, så vi aldri tømmer fila med en tom
    snapshot (f.eks. før første Kartverket-svar er skrevet inn i dict).
    """
    with _mem_cache_lock:
        snapshot = dict(disk_cache)
    with _file_lock:
        existing = dict(load_json(GEO_CACHE, {}))
        merged = {**existing, **snapshot}
        save_json(GEO_CACHE, merged)


def peek_coords_in_disk_cache(
    adresse: str,
    postnummer: str,
    kommunenummer: str,
    disk_cache: Dict[str, Any],
) -> Optional[Tuple[float, float]]:
    """Kun lesing fra disk_cache — ingen HTTP (trygt for /api/leads m.m.)."""
    pnr = normalize_postnummer(postnummer)
    knr = normalize_kommunenummer(kommunenummer)
    adr = (adresse or "").strip()
    if not adr or not pnr or not knr:
        return None
    key = cache_key(adr, pnr, knr)
    with _mem_cache_lock:
        hit = disk_cache.get(key)
    if hit == "MISS":
        return None
    if isinstance(hit, dict) and "lat" in hit and "lon" in hit:
        return float(hit["lat"]), float(hit["lon"])
    return None


def lookup_coords(
    adresse: str,
    postnummer: str,
    kommunenummer: str,
    disk_cache: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[float, float]]:
    """
    Returnerer (lat, lon) i WGS84 (EPSG:4258) eller None.
    Krever minst gateadresse + postnummer + kommunenummer for presis treff.
    """
    pnr = normalize_postnummer(postnummer)
    knr = normalize_kommunenummer(kommunenummer)
    adr = (adresse or "").strip()
    if not adr or not pnr or not knr:
        return None

    key = cache_key(adr, pnr, knr)
    if disk_cache is not None:
        with _mem_cache_lock:
            hit0 = disk_cache.get(key)
        if hit0 == "MISS":
            return None
        if isinstance(hit0, dict) and "lat" in hit0 and "lon" in hit0:
            return float(hit0["lat"]), float(hit0["lon"])

        params = {
            "adressetekst": adr,
            "postnummer": pnr,
            "kommunenummer": knr,
            "treffPerSide": 5,
        }
        data = None
        try:
            with _session_lock:
                r = _SESSION.get(GEONORGE_SOK, params=params, timeout=TIMEOUT)
                r.raise_for_status()
                data = r.json()
        except Exception:
            time.sleep(SLEEP_S)
            return None
        time.sleep(SLEEP_S)

        rows = (data or {}).get("adresser") or []
        with _mem_cache_lock:
            hit1 = disk_cache.get(key)
            if hit1 == "MISS":
                return None
            if isinstance(hit1, dict) and "lat" in hit1 and "lon" in hit1:
                return float(hit1["lat"]), float(hit1["lon"])
            if not rows:
                disk_cache[key] = "MISS"
                return None
            pt = (rows[0].get("representasjonspunkt") or {})
            lat, lon = pt.get("lat"), pt.get("lon")
            if lat is None or lon is None:
                disk_cache[key] = "MISS"
                return None
            out = (float(lat), float(lon))
            disk_cache[key] = {"lat": out[0], "lon": out[1]}
            return out

    use_local = _read_disk_cache()
    hit = use_local.get(key)
    if hit == "MISS":
        return None
    if isinstance(hit, dict) and "lat" in hit and "lon" in hit:
        return float(hit["lat"]), float(hit["lon"])

    params = {
        "adressetekst": adr,
        "postnummer": pnr,
        "kommunenummer": knr,
        "treffPerSide": 5,
    }
    data = None
    try:
        with _session_lock:
            r = _SESSION.get(GEONORGE_SOK, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
    except Exception:
        time.sleep(SLEEP_S)
        return None
    time.sleep(SLEEP_S)

    rows = (data or {}).get("adresser") or []
    if not rows:
        _store_miss(key, disk_cache)
        return None

    pt = (rows[0].get("representasjonspunkt") or {})
    lat, lon = pt.get("lat"), pt.get("lon")
    if lat is None or lon is None:
        _store_miss(key, disk_cache)
        return None
    out = (float(lat), float(lon))
    c = _read_disk_cache()
    c[key] = {"lat": out[0], "lon": out[1]}
    _write_disk_cache(c)
    return out


def _store_miss(key: str, disk_cache: Optional[Dict[str, Any]]) -> None:
    if disk_cache is not None:
        disk_cache[key] = "MISS"
    else:
        c = _read_disk_cache()
        c[key] = "MISS"
        _write_disk_cache(c)
