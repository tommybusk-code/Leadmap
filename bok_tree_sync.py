"""Legg heleide datterselskaper fra aksjeeierbok inn som manuelle datre i kundens ``related``-tre."""
from __future__ import annotations

from typing import Any, Dict, List

import enrichment as E
from aksjeeierbok_sqlite import connect_readonly, stakes_owned_by_orgnr
from related_tree import (
    find_manual_subsidiary_attachment_list,
    manual_orgnr_exists_in_tree,
    norm_org,
)

# Samme praktiske terskel som eierskap-utvidelse i ownership_signals (avrunding i bok).
WHOLE_OWN_MIN_PCT = 99.0
_DEFAULT_LIMIT = 500


def sync_heleide_subsidiaries_from_bok(
    customers: Dict[str, Any],
    root_orgnr: str,
    *,
    min_whole_pct: float = WHOLE_OWN_MIN_PCT,
    limit: int = _DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """
    For hvert selskap i aksjeeierboka der ``root_orgnr`` eier ≥ ``min_whole_pct`` %:
    hent Brreg-kort + ``fetch_related`` og append som ``manual_subsidiary`` under riktig forelder.

    Hopper over org.nr som allerede finnes som kunde eller i noen kundes tre (inkl. underenheter).
    """
    root = norm_org(root_orgnr)
    out: Dict[str, Any] = {
        "added": 0,
        "skipped_in_tree": 0,
        "skipped_pct": 0,
        "skipped_brreg": 0,
        "skipped_self": 0,
        "considered": 0,
        "brreg_mangler_orgnr": [],
    }
    if not root or len(root) != 9 or not root.isdigit():
        out["error"] = "ugyldig orgnr"
        return out

    conn = connect_readonly()
    if not conn:
        out["error"] = "mangler aksjeeierbok sqlite (bygg med aksjeeierbok_sqlite.py)"
        return out

    try:
        stakes = stakes_owned_by_orgnr(conn, root, float(min_whole_pct), int(limit))
    finally:
        conn.close()

    target_key, manual_list = find_manual_subsidiary_attachment_list(customers, root)
    if not target_key or manual_list is None:
        out["error"] = "fant ikke kunden som toppnode eller som forelder i treet"
        return out

    min_f = float(min_whole_pct)
    brreg_miss: List[str] = []

    for row in stakes:
        out["considered"] += 1
        so = norm_org(row.get("orgnr"))
        if not so or so == root:
            out["skipped_self"] += 1
            continue
        try:
            pct = float(row.get("pct") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        if pct < min_f:
            out["skipped_pct"] += 1
            continue

        if manual_orgnr_exists_in_tree(customers, so):
            out["skipped_in_tree"] += 1
            continue

        sub = E.find_company_by_orgnr(so)
        if not sub:
            out["skipped_brreg"] += 1
            if len(brreg_miss) < 40:
                brreg_miss.append(so)
            continue

        sub["type"] = "manual_subsidiary"
        try:
            sub["related"] = E.fetch_related(
                so,
                (sub.get("navn") or ""),
                sub.get("kommunenummer"),
                existing_related=sub.get("related") if isinstance(sub.get("related"), dict) else None,
            )
        except Exception:
            sub["related"] = {"error": "fetch_related feilet"}

        manual_list.append(sub)
        out["added"] += 1

    out["brreg_mangler_orgnr"] = brreg_miss
    return out
