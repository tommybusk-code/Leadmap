"""Nested related.manual_subsidiaries, merge ved Brreg-refresh, oppslag for add/remove."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


def norm_org(o: Any) -> str:
    """Sammenlignbar org.nr-streng (JSON/Brreg kan gi int, float eller streng med mellomrom)."""
    if o is None:
        return ""
    if isinstance(o, bool):
        return ""
    if isinstance(o, int):
        return str(o).strip()
    if isinstance(o, float):
        if o != o:  # NaN
            return ""
        i = int(round(o))
        if abs(o - i) < 1e-6 and 10**8 <= i < 10**9:
            return str(i)
    s = str(o).strip().replace(" ", "")
    if len(s) >= 11 and s.endswith(".0") and s[:-2].isdigit() and len(s[:-2]) == 9:
        return s[:-2]
    return s


def find_related_node_by_orgnr(
    related: dict, target_orgnr: str, root_orgnr: str, root_navn: Optional[str]
) -> Optional[dict]:
    """Finn underenhet eller manuell node (rekursivt) under én kundes ``related``."""
    if not target_orgnr or not related:
        return None
    rn = root_navn or ""
    t = norm_org(target_orgnr)

    for ue in related.get("underenheter") or []:
        if norm_org(ue.get("orgnr")) == t:
            return {
                "node": ue,
                "subsidiary_kind": "Avdeling/underenhet",
                "root_customer_orgnr": root_orgnr,
                "parent_orgnr": root_orgnr,
                "parent_navn": rn,
            }
        hit = _find_in_manual_tree(
            ue.get("manual_subsidiaries") or [], t, root_orgnr, ue
        )
        if hit:
            return hit

    for ms in related.get("manual_subsidiaries") or []:
        if norm_org(ms.get("orgnr")) == t:
            return {
                "node": ms,
                "subsidiary_kind": "Datter (manuell)",
                "root_customer_orgnr": root_orgnr,
                "parent_orgnr": root_orgnr,
                "parent_navn": rn,
            }
        hit = _find_below_manual_entity(ms, t, root_orgnr)
        if hit:
            return hit

    return None


def _find_below_manual_entity(m: dict, target_orgnr_norm: str, root_orgnr: str) -> Optional[dict]:
    """Brreg-avdelinger og manuelle barn under én manuell node (sjekk ikke m.orgnr)."""
    rel = m.get("related") or {}
    for ue in rel.get("underenheter") or []:
        if norm_org(ue.get("orgnr")) == target_orgnr_norm:
            return {
                "node": ue,
                "subsidiary_kind": "Avdeling/underenhet",
                "root_customer_orgnr": root_orgnr,
                "parent_orgnr": m.get("orgnr"),
                "parent_navn": m.get("navn"),
            }
        hit = _find_in_manual_tree(
            ue.get("manual_subsidiaries") or [], target_orgnr_norm, root_orgnr, ue
        )
        if hit:
            return hit
    return _find_in_manual_tree(
        m.get("manual_subsidiaries") or [], target_orgnr_norm, root_orgnr, m
    )


def _find_in_manual_tree(
    items: list, target_orgnr_norm: str, root_orgnr: str, immediate_parent: dict
) -> Optional[dict]:
    for m in items or []:
        if norm_org(m.get("orgnr")) == target_orgnr_norm:
            return {
                "node": m,
                "subsidiary_kind": "Datter (manuell)",
                "root_customer_orgnr": root_orgnr,
                "parent_orgnr": immediate_parent.get("orgnr"),
                "parent_navn": immediate_parent.get("navn"),
            }
        hit = _find_below_manual_entity(m, target_orgnr_norm, root_orgnr)
        if hit:
            return hit
    return None


def merge_fetch_related(existing: Optional[dict], fresh: dict) -> dict:
    """Slå sammen Brreg-fersk data med eksisterende related — beholder alltid manuelle datre."""
    out = dict(fresh) if isinstance(fresh, dict) else {}
    if existing and isinstance(existing, dict):
        ms = existing.get("manual_subsidiaries")
        if ms:
            out["manual_subsidiaries"] = ms
    return out


def find_manual_subsidiary_attachment_list(
    customers: Dict[str, Any], parent_orgnr: str
) -> Tuple[Optional[str], Optional[list]]:
    """Finn listen der nye manuelle datre skal appendes: toppkunde eller nested entitet."""
    p = norm_org(parent_orgnr)
    for key, c in customers.items():
        if norm_org(c.get("orgnr")) == p:
            rel = c.setdefault("related", {})
            return key, rel.setdefault("manual_subsidiaries", [])
        rel = c.get("related") or {}
        lst = _find_attachment_in_related(rel, p)
        if lst is not None:
            return key, lst
    return None, None


def _find_attachment_in_related(rel: dict, parent_orgnr_norm: str) -> Optional[list]:
    for bucket in ("underenheter", "manual_subsidiaries"):
        for ent in rel.get(bucket) or []:
            if norm_org(ent.get("orgnr")) == parent_orgnr_norm:
                return ent.setdefault("manual_subsidiaries", [])
            inner = _find_attachment_in_entity(ent, parent_orgnr_norm)
            if inner is not None:
                return inner
    return None


def _find_attachment_in_entity(ent: dict, parent_orgnr_norm: str) -> Optional[list]:
    inner_rel = ent.get("related")
    if isinstance(inner_rel, dict):
        lst = _find_attachment_in_related(inner_rel, parent_orgnr_norm)
        if lst is not None:
            return lst
    for ch in ent.get("manual_subsidiaries") or []:
        if norm_org(ch.get("orgnr")) == parent_orgnr_norm:
            return ch.setdefault("manual_subsidiaries", [])
        inner = _find_attachment_in_entity(ch, parent_orgnr_norm)
        if inner is not None:
            return inner
    return None


def manual_orgnr_exists_in_tree(customers: Dict[str, Any], orgnr: str) -> bool:
    o = norm_org(orgnr)
    if not o:
        return False
    for c in customers.values():
        if norm_org(c.get("orgnr")) == o:
            return True
        rel = c.get("related") or {}
        if _walk_any_orgnr(rel.get("manual_subsidiaries") or [], o):
            return True
        for ue in rel.get("underenheter") or []:
            if norm_org(ue.get("orgnr")) == o:
                return True
            if _walk_any_orgnr(ue.get("manual_subsidiaries") or [], o):
                return True
    return False


def _walk_any_orgnr(items: list, orgnr_norm: str) -> bool:
    for m in items or []:
        if norm_org(m.get("orgnr")) == orgnr_norm:
            return True
        rel = m.get("related") or {}
        for ue in rel.get("underenheter") or []:
            if norm_org(ue.get("orgnr")) == orgnr_norm:
                return True
            if _walk_any_orgnr(ue.get("manual_subsidiaries") or [], orgnr_norm):
                return True
        if _walk_any_orgnr(m.get("manual_subsidiaries") or [], orgnr_norm):
            return True
    return False


def find_customer_entity_by_orgnr(
    customers: Dict[str, Any], orgnr: Any
) -> Tuple[Optional[str], Optional[dict]]:
    """Lagringsnøkkel for toppkunde + entitets-dict (toppkunde eller node i ``related``-tre)."""
    n = norm_org(orgnr)
    if not n:
        return None, None
    for key, c in customers.items():
        if norm_org(c.get("orgnr")) == n:
            return key, c
        ro = c.get("orgnr")
        if not ro:
            continue
        hit = find_related_node_by_orgnr(c.get("related") or {}, orgnr, ro, c.get("navn"))
        if hit:
            return key, hit["node"]
    return None, None


def iter_tree_company_nodes_with_org(root_customer: dict):
    """DFS: ``(mutable dict, norm_org)`` for roten og alle underenheter/manuelle datre med gyldig org.nr."""
    seen: set = set()
    stack = [root_customer]
    while stack:
        ent = stack.pop()
        o = norm_org(ent.get("orgnr"))
        if not o or len(o) != 9 or not o.isdigit():
            continue
        if o in seen:
            continue
        seen.add(o)
        yield ent, o
        rel = ent.get("related") or {}
        for ue in rel.get("underenheter") or []:
            stack.append(ue)
        for m in rel.get("manual_subsidiaries") or []:
            stack.append(m)


def flatten_all_customer_tree_refresh_tasks(customers: Dict[str, Any]) -> List[Tuple[str, str]]:
    """``(toppkunde_lagringsnøkkel, org.nr)`` for hver selskapsnode i alle kundetrær (unik per tre)."""
    out: List[Tuple[str, str]] = []
    for root_key, c in customers.items():
        for _ent, o in iter_tree_company_nodes_with_org(c):
            out.append((root_key, o))
    return out


def all_tree_entities_by_orgnr(customers: Dict[str, Any]) -> Dict[str, dict]:
    """Alle tre-noder med gyldig org.nr → entitetsdict (samme referanse som i lagret JSON). Første tre vinner ved kollisjon."""
    out: Dict[str, dict] = {}
    for c in customers.values():
        for ent, o in iter_tree_company_nodes_with_org(c):
            if o not in out:
                out[o] = ent
    return out


def collect_manual_subsidiary_anchors(
    customers: Dict[str, Any], enrich_fn: Optional[Callable[[str], Optional[dict]]] = None
) -> List[dict]:
    """Alle manuelle datre (rekursivt), også under avdelinger, som egne ankere for discovery."""
    seen: set = set()
    out: List[dict] = []

    def walk(items: list):
        for m in items or []:
            o = norm_org(m.get("orgnr"))
            if not o or o in seen:
                continue
            seen.add(o)
            node = dict(m)
            if enrich_fn and (not node.get("naeringskode1") or not node.get("kommunenummer")):
                data = enrich_fn(o)
                if data and isinstance(data, dict):
                    for k, v in data.items():
                        if v is not None and v != "" and not node.get(k):
                            node[k] = v
            node.setdefault("enriched", True)
            out.append(node)
            walk(m.get("manual_subsidiaries") or [])
            for ue in (m.get("related") or {}).get("underenheter") or []:
                walk(ue.get("manual_subsidiaries") or [])

    for c in customers.values():
        rel = c.get("related") or {}
        walk(rel.get("manual_subsidiaries") or [])
        for ue in rel.get("underenheter") or []:
            walk(ue.get("manual_subsidiaries") or [])
    return out


def remove_manual_orgnr_from_related(related: dict, sub_orgnr: str) -> bool:
    """Fjern én manuell kobling fra related-tre; barnebarn løftes ett nivå opp."""
    changed = False
    ms = related.get("manual_subsidiaries") or []
    new_ms, ch = _filter_manual_list_remove(ms, sub_orgnr)
    if ch:
        related["manual_subsidiaries"] = new_ms
        changed = True
    for ue in related.get("underenheter") or []:
        if _remove_manual_from_entity(ue, sub_orgnr):
            changed = True
    return changed


def remove_manual_orgnr_from_customers(customers: Dict[str, Any], sub_orgnr: str) -> bool:
    """Søk alle kunder og fjern sub_orgnr fra første treff."""
    any_changed = False
    for key, c in customers.items():
        rel = c.get("related")
        if not rel:
            continue
        if remove_manual_orgnr_from_related(rel, sub_orgnr):
            any_changed = True
            customers[key] = c
    return any_changed


def _filter_manual_list_remove(ms: list, sub_orgnr: str) -> Tuple[list, bool]:
    new: List[dict] = []
    changed = False
    sub_n = norm_org(sub_orgnr)
    for m in ms or []:
        if norm_org(m.get("orgnr")) == sub_n:
            orphans = m.get("manual_subsidiaries") or []
            new.extend(orphans)
            changed = True
            continue
        if _remove_manual_from_entity(m, sub_orgnr):
            changed = True
        new.append(m)
    return new, changed


def _remove_manual_from_entity(ent: dict, sub_orgnr: str) -> bool:
    changed = False
    inner = ent.get("related")
    if isinstance(inner, dict):
        if remove_manual_orgnr_from_related(inner, sub_orgnr):
            changed = True
    ms = ent.get("manual_subsidiaries") or []
    new_ms, ch = _filter_manual_list_remove(ms, sub_orgnr)
    if ch:
        ent["manual_subsidiaries"] = new_ms
        changed = True
    return changed
