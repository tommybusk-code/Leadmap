"""Lead-signaler når et lead hører til en kunde via regnskap (mor), Brreg/kundetre eller aksjeeierbok.

Merk: Vi bruker:
- morselskap fra regnskapsregisteret (samme logikk som konsern-visning på kunde),
- org.nr som finnes under kundens ``related`` (underenheter + manuelle datre), og
- aksjeeierbok 2024 som indeksert SQLite (``data/aksjeeierbok_2024.sqlite``) — bygges fra CSV med
  ``python aksjeeierbok_sqlite.py``. Kun juridiske aksjonærer (ni sifre i «Fødselsår/orgnr»).

I tillegg: selskap som i aksjeeierboka er **99–100 % eid** av et org.nr som allerede «hører til»
kunden (toppkunde, tre-underenhet eller tidligere utvidet datter), mappes inn som samme anker.
Da får f.eks. Tess treff når **TESS Øst** står som direkte aksjonær i et lead, og
``kunde_konserntre`` utvides til disse datter-/datterdatter-selskapene.

Eksempel: Eiva-Safex kan ha ``virksomhet.morselskap: false`` i regnskap selv om Tess eier aksjer —
da treffer ikke ``kunde_morselskap``, men ``kunde_aksjeeierbok`` når databasen er bygget.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable, Dict, List, Optional, Set

import scoring as S
from analysis_parallel import _parallel_run
from aksjeeierbok_sqlite import (
    connect_readonly,
    ownership_pct_in_company,
    shareholder_hits_for_company,
    stakes_owned_by_orgnr,
)
from brreg_konsern import resolve_mor_orgnr_from_regnskap
from json_store import load_json, save_json
from paths import OWNERSHIP_MOR_CACHE

_CACHE_MISS = ""

# Aksjeeierbok: rekursiv utvidelse av «kunde-siden» når et org.nr eier 99–100 % av et annet selskap.
BOOK_WHOLE_OWN_MIN_PCT = 99.0
BOOK_WHOLE_OWN_MAX_PCT = 100.01
BOOK_EXPAND_STAKES_LIMIT = 2000


def _norm_orgnr(o: Any) -> str:
    if o is None:
        return ""
    return str(o).strip().replace(" ", "")


def _collect_tree_orgnrs(rel: Dict[str, Any], acc: Set[str]) -> None:
    """Alle org.nr i treet under kunde (ikke selve kunden)."""
    if not rel or not isinstance(rel, dict):
        return
    for ue in rel.get("underenheter") or []:
        o = _norm_orgnr(ue.get("orgnr"))
        if o:
            acc.add(o)
        _collect_manual_subs(ue.get("manual_subsidiaries") or [], acc)
        _collect_tree_orgnrs(ue.get("related") or {}, acc)
    _collect_manual_subs(rel.get("manual_subsidiaries") or [], acc)


def _collect_manual_subs(items: List[Dict[str, Any]], acc: Set[str]) -> None:
    for m in items or []:
        o = _norm_orgnr(m.get("orgnr"))
        if o:
            acc.add(o)
        _collect_tree_orgnrs(m.get("related") or {}, acc)
        _collect_manual_subs(m.get("manual_subsidiaries") or [], acc)


def _customer_orgnr_index(customers: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """orgnr -> {navn, orgnr} for alle berikede kunder (toppnoder)."""
    out: Dict[str, Dict[str, str]] = {}
    for c in customers.values():
        if not isinstance(c, dict):
            continue
        o = _norm_orgnr(c.get("orgnr"))
        if not o or not c.get("enriched"):
            continue
        out[o] = {"orgnr": o, "navn": (c.get("navn") or o).strip()}
    return out


def _tree_index(customers: Dict[str, Any]) -> List[tuple]:
    """Liste av (kunde_orgnr, kunde_navn, sett_med_orgnr_i_tre)."""
    rows: List[tuple] = []
    for c in customers.values():
        if not isinstance(c, dict):
            continue
        root = _norm_orgnr(c.get("orgnr"))
        if not root or not c.get("enriched"):
            continue
        bag: Set[str] = set()
        _collect_tree_orgnrs(c.get("related") or {}, bag)
        if bag:
            rows.append((root, (c.get("navn") or root).strip(), frozenset(bag)))
    return rows


def _build_orgnr_to_anchor_map(
    customers: Dict[str, Any],
    conn: Optional[Any],
) -> Dict[str, Dict[str, str]]:
    """org.nr → {anker_orgnr, anker_navn} for toppkunde + Brreg-tre + bok-utvidelse (99–100 % eid kjede).

    To kunder som begge krever samme org.nr: første vinner (ikke overskriv).
    Selskap som er **annen kunde** (toppnivå-org.nr) tas ikke inn som datter via bok.
    """
    out: Dict[str, Dict[str, str]] = {}
    cust_by_o = _customer_orgnr_index(customers)
    all_roots = frozenset(cust_by_o.keys())

    for c in customers.values():
        if not isinstance(c, dict):
            continue
        root = _norm_orgnr(c.get("orgnr"))
        if not root or not c.get("enriched"):
            continue
        navn = (c.get("navn") or root).strip()
        anchor = {"orgnr": root, "navn": navn}
        if root not in out:
            out[root] = anchor
        bag: Set[str] = set()
        _collect_tree_orgnrs(c.get("related") or {}, bag)
        for o in bag:
            if not o:
                continue
            if o not in out:
                out[o] = anchor

    if not conn:
        return out

    stakes_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _stakes99(owner: str) -> List[Dict[str, Any]]:
        if owner not in stakes_cache:
            stakes_cache[owner] = stakes_owned_by_orgnr(
                conn, owner, BOOK_WHOLE_OWN_MIN_PCT, BOOK_EXPAND_STAKES_LIMIT
            )
        return stakes_cache[owner]

    q = deque(out.keys())
    queued = set(out.keys())
    while q:
        o = q.popleft()
        anchor = out.get(o)
        if not anchor:
            continue
        root_anchor = anchor["orgnr"]
        for row in _stakes99(o):
            try:
                pct = float(row.get("pct") or 0)
            except (TypeError, ValueError):
                continue
            if pct < BOOK_WHOLE_OWN_MIN_PCT or pct > BOOK_WHOLE_OWN_MAX_PCT:
                continue
            so = _norm_orgnr(row.get("orgnr"))
            if not so or so == root_anchor:
                continue
            if so in all_roots and so != root_anchor:
                continue
            if so in out:
                continue
            out[so] = anchor
            if so not in queued:
                q.append(so)
                queued.add(so)
    return out


def _konsern_rows_from_anchor_map(
    cust_by_o: Dict[str, Dict[str, str]],
    orgnr_to_anchor: Dict[str, Dict[str, str]],
) -> List[tuple]:
    """(kunde_orgnr, kunde_navn, frozenset av org.nr i «utvidet tre» uten roten)."""
    rows: List[tuple] = []
    for root_o, meta in cust_by_o.items():
        bag = {o for o, a in orgnr_to_anchor.items() if a["orgnr"] == root_o}
        bag.discard(root_o)
        if not bag:
            continue
        rows.append((root_o, meta["navn"], frozenset(bag)))
    return rows


def _aksjeeierbok_detail(aksjer: int, tot: int) -> str:
    if tot <= 0:
        return "Aksjeeierbok 2024: registrert som aksjonær med org.nr."
    ratio = aksjer / float(tot)
    if ratio >= 0.995 or aksjer >= tot:
        return f"Aksjeeierbok 2024: eier {aksjer:,} av {tot:,} aksjer (heleid).".replace(",", " ")
    pct = ratio * 100.0
    return f"Aksjeeierbok 2024: eier {aksjer:,} av {tot:,} aksjer (ca. {pct:.1f} %).".replace(",", " ")


def _append_signal(
    lead: Dict[str, Any],
    sig_type: str,
    anker: Dict[str, str],
    detail: str,
    ownership_pct: Optional[float] = None,
    *,
    ownership_aksjer: Optional[int] = None,
    ownership_aksjer_tot: Optional[int] = None,
) -> None:
    ao = anker["orgnr"]
    sigs = lead.setdefault("signals", [])
    if any(s.get("type") == sig_type and _norm_orgnr(s.get("anker_orgnr")) == ao for s in sigs):
        return
    row: Dict[str, Any] = {
        "type": sig_type,
        "anker_orgnr": ao,
        "anker_navn": anker.get("navn") or ao,
        "detail": detail[:220],
    }
    if ownership_pct is not None:
        try:
            v = float(ownership_pct)
            if v == v:  # not NaN
                row["ownership_pct"] = round(v, 1)
        except (TypeError, ValueError):
            pass
    if ownership_aksjer is not None:
        try:
            row["ownership_aksjer"] = int(ownership_aksjer)
        except (TypeError, ValueError):
            pass
    if ownership_aksjer_tot is not None:
        try:
            row["ownership_aksjer_tot"] = int(ownership_aksjer_tot)
        except (TypeError, ValueError):
            pass
    sigs.append(row)


def _load_mor_cache() -> Dict[str, str]:
    raw = dict(load_json(OWNERSHIP_MOR_CACHE, {}))
    out: Dict[str, str] = {}
    for k, v in raw.items():
        if not k:
            continue
        if v is None or v == _CACHE_MISS:
            out[str(k).strip()] = _CACHE_MISS
        else:
            out[str(k).strip()] = str(v).strip()
    return out


def _save_mor_cache(disk: Dict[str, str]) -> None:
    save_json(OWNERSHIP_MOR_CACHE, disk)


def enrich_leads_with_customer_ownership(
    leads_by_orgnr: Dict[str, Dict[str, Any]],
    customers: Dict[str, Any],
    tick: Optional[Callable[[], None]] = None,
) -> None:
    """
    Legg til signaler ``kunde_morselskap``, ``kunde_konserntre`` og ``kunde_aksjeeierbok`` der det treffer.
    ``leads_by_orgnr``: orgnr -> lead-dict (samme som ``all_leads`` i analyse).
    """
    cust_by_o = _customer_orgnr_index(customers)
    if not cust_by_o:
        return
    bok = connect_readonly()
    orgnr_to_anchor = _build_orgnr_to_anchor_map(customers, bok)
    cust_keys = frozenset(orgnr_to_anchor.keys())
    try:
        tree_rows = _konsern_rows_from_anchor_map(cust_by_o, orgnr_to_anchor)

        lead_orgnrs = [_norm_orgnr(o) for o in leads_by_orgnr.keys() if _norm_orgnr(o)]
        lead_orgnrs = [o for o in lead_orgnrs if o not in cust_by_o]

        disk = _load_mor_cache()
        mor_by_lead: Dict[str, Optional[str]] = {}

        def fetch_one(lo: str) -> Optional[str]:
            if lo in disk:
                v = disk[lo]
                return None if v == _CACHE_MISS else v
            return resolve_mor_orgnr_from_regnskap(lo)

        def on_prog():
            if tick:
                tick()

        pairs = _parallel_run(lead_orgnrs, fetch_one, on_progress=on_prog if tick else None)
        dirty = False
        for lo, mor in pairs:
            prev = disk.get(lo)
            if mor:
                disk[lo] = mor
                mor_by_lead[lo] = mor
                if prev != mor:
                    dirty = True
            else:
                disk[lo] = _CACHE_MISS
                mor_by_lead[lo] = None
                if prev != _CACHE_MISS:
                    dirty = True

        if dirty:
            _save_mor_cache(disk)

        for lo, L in leads_by_orgnr.items():
            lo = _norm_orgnr(lo)
            if not L or lo in cust_by_o:
                continue

            mor = mor_by_lead.get(lo)
            if mor and mor in cust_by_o:
                anker = cust_by_o[mor]
                mor_pct = None
                if bok:
                    mor_pct = ownership_pct_in_company(bok, lo, mor)
                # Ikke vis/registrer bok-andel under 5 % på morselskap-signalet (struktur-treff beholdes).
                mor_pct_sig = None
                lo_m, hi_m = S.ownership_signal_pct_bounds()
                if mor_pct is not None and lo_m <= mor_pct <= hi_m:
                    mor_pct_sig = mor_pct
                _append_signal(
                    L,
                    "kunde_morselskap",
                    anker,
                    f"Regnskapsmessig morselskap (org.nr {mor}) er kunde «{anker['navn']}».",
                    ownership_pct=mor_pct_sig,
                )

            for root_o, root_navn, bag in tree_rows:
                if lo in bag:
                    anker = {"orgnr": root_o, "navn": root_navn}
                    _append_signal(
                        L,
                        "kunde_konserntre",
                        anker,
                        "Selskapet finnes i kundens konsern (Brreg-tre og/eller nesten heleide datterselskap i aksjeeierbok).",
                    )

            if bok:
                lo_a, hi_a = S.ownership_signal_pct_bounds()
                hits = shareholder_hits_for_company(bok, lo, cust_keys)
                for ao, info in hits.items():
                    anker = orgnr_to_anchor.get(ao)
                    if not anker:
                        continue
                    ak = int(info.get("aksjer") or 0)
                    tot = int(info.get("tot") or 0)
                    ak_pct = (100.0 * ak / float(tot)) if tot > 0 else None
                    if ak_pct is None or ak_pct < lo_a or ak_pct > hi_a:
                        continue
                    _append_signal(
                        L,
                        "kunde_aksjeeierbok",
                        anker,
                        _aksjeeierbok_detail(ak, tot),
                        ownership_pct=ak_pct,
                        ownership_aksjer=ak,
                        ownership_aksjer_tot=tot,
                    )
    finally:
        if bok:
            bok.close()


_OWNERSHIP_SIGNAL_TYPES = frozenset({"kunde_morselskap", "kunde_konserntre", "kunde_aksjeeierbok"})


def refresh_customer_ownership_signals_on_leads(
    leads: List[Dict[str, Any]],
    customers: Dict[str, Any],
    tick: Optional[Callable[[], None]] = None,
) -> None:
    """Fjern kunde-eierskap-signaler og bygg dem på nytt etter endrede terskler i settings."""
    by_o: Dict[str, Dict[str, Any]] = {}
    for L in leads:
        if not isinstance(L, dict):
            continue
        o = _norm_orgnr(L.get("orgnr"))
        if o:
            by_o[o] = L
    for L in leads:
        if not isinstance(L, dict):
            continue
        sigs = L.get("signals") or []
        L["signals"] = [s for s in sigs if s.get("type") not in _OWNERSHIP_SIGNAL_TYPES]
    enrich_leads_with_customer_ownership(by_o, customers, tick=tick)
