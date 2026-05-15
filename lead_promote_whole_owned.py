"""Flytt leads som er heleid i aksjeeierbok av org.nr som finnes i kundetre inn som manuelle datre.

Bruker samme praktiske terskel som ``bok_tree_sync.WHOLE_OWN_MIN_PCT`` (99 %).
Krever at én aksjonær i kundesiden dominerer (to med ≥ terskel og < 0,05 %-poeng mellom = uavgjort).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, MutableMapping, Optional

import enrichment as E
from aksjeeierbok_sqlite import connect_readonly, shareholder_hits_for_company
from bok_tree_sync import WHOLE_OWN_MIN_PCT
from json_store import load_json, save_json
from paths import LEAD_RELATIONS, NOTES_FILE, STATUS_FILE
from ownership_signals import _build_orgnr_to_anchor_map
from related_tree import find_manual_subsidiary_attachment_list, manual_orgnr_exists_in_tree, norm_org


def _resolve_manual_subsidiary_list(
    customers: Dict[str, Any],
    orgnr_to_anchor: Dict[str, Dict[str, str]],
    owner_ao: str,
) -> Optional[list]:
    """Liste å appende manuell datter til: under ``owner_ao`` i treet, eller under toppanker hvis eier kun finnes i bok-utvidelsen."""
    o = norm_org(owner_ao)
    if not o:
        return None
    _k, lst = find_manual_subsidiary_attachment_list(customers, o)
    if lst is not None:
        return lst
    meta = orgnr_to_anchor.get(o)
    if not meta:
        return None
    root_o = norm_org(meta.get("orgnr"))
    if not root_o or root_o == o:
        return None
    _k2, lst2 = find_manual_subsidiary_attachment_list(customers, root_o)
    return lst2


def _pick_whole_owner_orgnr(
    conn,
    selskap_orgnr: str,
    customers: Dict[str, Any],
    orgnr_to_anchor: Dict[str, Dict[str, str]],
    cust_keys: frozenset,
    min_pct: float,
) -> Optional[str]:
    """Én aksjonær-org.nr i kundesiden med ≥ min_pct; uavgjort bare hvis nr.2 også ≥ terskel og nesten lik nr.1."""
    hits = shareholder_hits_for_company(conn, selskap_orgnr, cust_keys)
    if not hits:
        return None
    scored: list[tuple[str, float]] = []
    for ao, info in hits.items():
        ao_n = norm_org(ao)
        if not ao_n:
            continue
        if _resolve_manual_subsidiary_list(customers, orgnr_to_anchor, ao_n) is None:
            continue
        tot = int(info.get("tot") or 0)
        ak = int(info.get("aksjer") or 0)
        if tot <= 0:
            continue
        pct = 100.0 * ak / float(tot)
        scored.append((ao_n, pct))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[1])
    best_o, best_p = scored[0]
    if best_p < float(min_pct):
        return None
    if len(scored) >= 2:
        second_p = scored[1][1]
        if second_p >= float(min_pct) and (best_p - second_p) < 0.05:
            return None
    return best_o


def _lead_to_subsidiary_dict(lead: Dict[str, Any], lo: str) -> Optional[Dict[str, Any]]:
    sub = E.find_company_by_orgnr(lo)
    if not sub:
        sub = {
            "orgnr": lo,
            "navn": lead.get("navn") or lo,
            "postnummer": lead.get("postnummer"),
            "poststed": lead.get("poststed"),
            "kommune": lead.get("kommune"),
            "kommunenummer": lead.get("kommunenummer"),
            "adresse": lead.get("adresse"),
            "naeringskode1": lead.get("naeringskode1"),
            "nace_beskr": lead.get("nace_beskr"),
            "antallAnsatte": lead.get("antallAnsatte"),
            "hjemmeside": lead.get("hjemmeside"),
            "telefon": lead.get("telefon"),
            "epost": lead.get("epost"),
        }
    sub["type"] = "manual_subsidiary"
    sub["promoted_from_lead"] = True
    sub["promotion_mode"] = "datterselskap_bok_auto"
    sub["promoted_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        sub["related"] = E.fetch_related(
            lo,
            (sub.get("navn") or ""),
            sub.get("kommunenummer"),
            existing_related=sub.get("related") if isinstance(sub.get("related"), dict) else None,
        )
    except Exception:
        sub["related"] = sub.get("related") or {"error": "fetch_related feilet"}
    return sub


def promote_whole_owned_leads_from_pool(
    leads_pool: MutableMapping[Any, Dict[str, Any]],
    customers: Dict[str, Any],
    *,
    min_pct: float = WHOLE_OWN_MIN_PCT,
    log_fn: Optional[Callable[[str], None]] = None,
    tick_fn: Optional[Callable[[int, int, str], None]] = None,
    rebuild_anchor_each_move: bool = True,
) -> int:
    """
    Fjern fra ``leads_pool`` og legg inn under eier i ``customers`` når aksjeeierbok viser heleie
    av org.nr som faktisk finnes som toppkunde eller node i tre (kan få ``manual_subsidiaries``).
    Returnerer antall flyttinger.
    """
    bok = connect_readonly()
    if not bok:
        if log_fn:
            log_fn("Hopper heleid-lead→kunde: mangler aksjeeierbok SQLite.")
        return 0

    moved = 0
    status = load_json(STATUS_FILE, {})
    notes = load_json(NOTES_FILE, {})
    relations = load_json(LEAD_RELATIONS, {})
    if not isinstance(status, dict):
        status = {}
    if not isinstance(notes, dict):
        notes = {}
    if not isinstance(relations, dict):
        relations = {}

    try:
        orgnr_to_anchor = _build_orgnr_to_anchor_map(customers, bok)
        cust_keys = frozenset(orgnr_to_anchor.keys())
        if not cust_keys:
            return 0

        keys_snapshot = list(leads_pool.keys())
        total_n = len(keys_snapshot)
        for i, lo_key in enumerate(keys_snapshot):
            if tick_fn:
                tick_fn(i + 1, total_n, f"Sjekker lead {i + 1}/{total_n}")
            L = leads_pool.get(lo_key)
            if not isinstance(L, dict):
                continue
            lo = norm_org(L.get("orgnr"))
            if not lo or len(lo) != 9 or not lo.isdigit():
                continue
            if manual_orgnr_exists_in_tree(customers, lo):
                continue

            owner = _pick_whole_owner_orgnr(
                bok, lo, customers, orgnr_to_anchor, cust_keys, min_pct
            )
            if not owner or owner == lo:
                continue

            manual_list = _resolve_manual_subsidiary_list(customers, orgnr_to_anchor, owner)
            if manual_list is None:
                continue

            sub = _lead_to_subsidiary_dict(L, lo)
            if not sub:
                continue

            manual_list.append(sub)
            del leads_pool[lo_key]
            status[str(lo)] = "datterselskap"
            notes.pop(str(lo), None)
            notes.pop(lo, None)
            relations.pop(str(lo), None)
            relations.pop(lo, None)
            moved += 1
            if rebuild_anchor_each_move:
                orgnr_to_anchor = _build_orgnr_to_anchor_map(customers, bok)
                cust_keys = frozenset(orgnr_to_anchor.keys())
            if log_fn:
                anker = orgnr_to_anchor.get(owner, {"orgnr": owner, "navn": owner})
                log_fn(
                    f"Heleid lead → tre: {L.get('navn') or lo} ({lo}) under "
                    f"{anker.get('navn') or owner} ({owner})."
                )
    finally:
        bok.close()

    if moved:
        save_json(STATUS_FILE, status)
        save_json(NOTES_FILE, notes)
        save_json(LEAD_RELATIONS, relations)

    return moved
