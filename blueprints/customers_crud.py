"""Kunde-CRUD, søk og enkeltoppdateringer — /api/customers/* m.m."""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import jsonify, request

import enrichment as E
import scoring as S
from aksjeeierbok_sqlite import connect_readonly, ownership_pct_in_company, stakes_owned_by_orgnr
from blueprints.web_api import web_api as bp
from bok_tree_sync import sync_heleide_subsidiaries_from_bok
from paths import DISCOVERY_CACHE, LEADS_FILE, CUSTOMERS_FILE, CUSTOMERS_BACKUP
from persist import get_customers, get_leads_readonly, save_customers
from json_store import load_json, save_json
from related_tree import (
    find_customer_entity_by_orgnr,
    find_related_node_by_orgnr,
    flatten_all_customer_tree_refresh_tasks,
    norm_org,
)
from authz import require_perm
from blueprints.auth_routes import get_current_user
import geo_enrichment as GEO
from user_scoring_profile import load_merged_user_settings


def _top_customer_key_for_orgnr(customers: Dict[str, Any], orgnr: Any) -> Optional[str]:
    """Lagringsnøkkel for toppkunde der ``v['orgnr']`` matcher (tall/streng-normalisert)."""
    n = norm_org(orgnr)
    if not n:
        return None
    for k, v in customers.items():
        if norm_org(v.get("orgnr")) == n:
            return k
    return None


def _norm_o(o: Any) -> str:
    return norm_org(o)


def _morselskap_children(view_orgnr: str, customers: Dict[str, Any], leads: List[dict], conn) -> List[dict]:
    """Selskap som rapporterer denne kunden som regnskapsmessig mor, er koblet som datter, eller lead med morselskap-signal."""
    view = _norm_o(view_orgnr)
    if not view:
        return []
    seen: Dict[str, dict] = {}
    for c in customers.values():
        if not isinstance(c, dict):
            continue
        o = _norm_o(c.get("orgnr"))
        if not o or o == view:
            continue
        mor = _norm_o((c.get("related") or {}).get("mor_orgnr"))
        parent = _norm_o(c.get("parent_orgnr"))
        if mor == view:
            seen[o] = {"orgnr": o, "navn": (c.get("navn") or o).strip(), "kilde": "regnskap"}
        elif parent == view and o not in seen:
            seen[o] = {"orgnr": o, "navn": (c.get("navn") or o).strip(), "kilde": "koblet"}

    for L in leads:
        if not isinstance(L, dict):
            continue
        o = _norm_o(L.get("orgnr"))
        if not o or o == view:
            continue
        for s in L.get("signals") or []:
            if s.get("type") != "kunde_morselskap":
                continue
            if _norm_o(s.get("anker_orgnr")) != view:
                continue
            if o not in seen:
                seen[o] = {"orgnr": o, "navn": (L.get("navn") or o).strip(), "kilde": "lead"}
            break

    lo, hi = S.ownership_signal_pct_bounds()
    rows = sorted(seen.values(), key=lambda x: (x.get("navn") or "").lower())
    for r in rows:
        p = ownership_pct_in_company(conn, r["orgnr"], view) if conn else None
        r["pct"] = round(p, 1) if p is not None and lo <= p <= hi else None
    return rows


def _ownership_payload(view_orgnr: str, customers: Dict[str, Any], leads: List[dict]) -> Dict[str, Any]:
    lo, hi = S.ownership_signal_pct_bounds()
    conn = connect_readonly()
    try:
        stakes = stakes_owned_by_orgnr(conn, view_orgnr, lo, 250) if conn else []
        stakes = [x for x in stakes if float(x.get("pct") or 0) <= hi]
        mor = _morselskap_children(view_orgnr, customers, leads, conn)
        return {
            "ownership_aksjonaer": stakes,
            "ownership_morselskap": mor,
            "ownership_stake_pct_limits": {"min": lo, "max": hi},
        }
    finally:
        if conn:
            conn.close()


@bp.route("/customers")
def api_customers():
    customers = get_customers()
    return jsonify({"customers": list(customers.values()), "count": len(customers)})


@bp.route("/customers/<orgnr>", methods=["GET"])
def api_get_customer(orgnr):
    customers = get_customers()
    all_leads = get_leads_readonly()
    n_req = norm_org(orgnr)
    cust = next((c for c in customers.values() if norm_org(c.get("orgnr")) == n_req), None)
    if cust:
        u = get_current_user()
        merged = load_merged_user_settings(u["id"], u["tenant_id"])
        uw, ut = merged["weights"], merged["thresholds"]
        cust_by_o = customers_by_orgnr_map(customers)
        related = [L for L in all_leads if n_req in {norm_org(x) for x in (L.get("anker_orgnrs") or [])}]
        GEO.hydrate_geo_distance_factors_for_leads(related, customers)
        related_leads = []
        for L in related:
            Lc = dict(L)
            S.score_lead(Lc, uw, ut)
            enrich_lead_geo(Lc, cust_by_o)
            related_leads.append(
                {
                    "orgnr": Lc.get("orgnr"),
                    "navn": Lc.get("navn"),
                    "score": Lc.get("score", 0),
                    "antallAnsatte": Lc.get("antallAnsatte", 0),
                    "kommune": Lc.get("kommune"),
                    "signal_types": list(
                        {
                            s.get("type")
                            for s in Lc.get("signals", [])
                            if norm_org(s.get("anker_orgnr")) == n_req
                        }
                    ),
                    "signals": Lc.get("signals") or [],
                    "score_breakdown": Lc.get("score_breakdown") or {},
                    "geo_label": Lc.get("geo_label"),
                    "geo_tier": Lc.get("geo_tier"),
                    "geo_detail": Lc.get("geo_detail"),
                    "geoscore": Lc.get("geoscore"),
                    "geo_match_anker_navn": Lc.get("geo_match_anker_navn"),
                    "geo_match_anker_orgnrs": Lc.get("geo_match_anker_orgnrs"),
                }
            )
        related_leads.sort(key=lambda x: -x["score"])
        eff = _effective_ansatte(cust)
        own = _ownership_payload(orgnr, customers, all_leads)
        return jsonify(
            {
                "customer": cust,
                "effective_ansatte": eff,
                "related_leads": related_leads[:50],
                "total_leads": len(related_leads),
                **own,
            }
        )

    for parent in customers.values():
        ro = parent.get("orgnr")
        if not ro:
            continue
        hit = find_related_node_by_orgnr(parent.get("related") or {}, orgnr, ro, parent.get("navn"))
        if hit:
            sub = hit["node"]
            own = _ownership_payload(orgnr, customers, all_leads)
            return jsonify(
                {
                    "customer": sub,
                    "is_subsidiary": True,
                    "subsidiary_kind": hit["subsidiary_kind"],
                    "parent_orgnr": hit.get("parent_orgnr"),
                    "parent_navn": hit.get("parent_navn"),
                    "root_customer_orgnr": hit.get("root_customer_orgnr"),
                    "effective_ansatte": sub.get("antallAnsatte", 0),
                    "related_leads": [],
                    "total_leads": 0,
                    **own,
                }
            )

    try:
        sub = E.find_company_by_orgnr(orgnr)
        if sub:
            own = _ownership_payload(orgnr, customers, all_leads)
            return jsonify(
                {
                    "customer": sub,
                    "is_subsidiary": True,
                    "subsidiary_kind": "Selskap (hentet fra Brønnøysund)",
                    "parent_orgnr": None,
                    "parent_navn": None,
                    "effective_ansatte": sub.get("antallAnsatte", 0),
                    "related_leads": [],
                    "total_leads": 0,
                    **own,
                }
            )
        import requests
        r = requests.get(f"https://data.brreg.no/enhetsregisteret/api/underenheter/{orgnr}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            sub = E._extract_under(data) if hasattr(E, "_extract_under") else {
                "orgnr": data.get("organisasjonsnummer"),
                "navn": data.get("navn"),
                "antallAnsatte": data.get("antallAnsatte") or 0,
            }
            own = _ownership_payload(orgnr, customers, all_leads)
            return jsonify(
                {
                    "customer": sub,
                    "is_subsidiary": True,
                    "subsidiary_kind": "Avdeling/underenhet (hentet fra Brønnøysund)",
                    "parent_orgnr": (data.get("overordnetEnhet") or None),
                    "parent_navn": None,
                    "effective_ansatte": sub.get("antallAnsatte", 0),
                    "related_leads": [],
                    "total_leads": 0,
                    **own,
                }
            )
    except Exception as e:
        print(f"[customer fallback] {e}")
    return jsonify({"error": "ikke funnet"}), 404


def apply_brreg_refresh_to_entity(entity: Dict[str, Any], orgnr: str) -> None:
    """Hent Brreg-kjernekort + ``fetch_related`` inn i én kunde-/tre-node (muterer ``entity``)."""
    o = norm_org(orgnr)
    data = E.find_company_by_orgnr(o)
    if data:
        for k, v in data.items():
            entity[k] = v
        entity["enriched"] = True
    try:
        entity["related"] = E.fetch_related(
            o,
            entity.get("navn"),
            entity.get("kommunenummer"),
            existing_related=entity.get("related"),
        )
    except Exception as ex:
        entity["related"] = {"error": str(ex)}


@bp.route("/customers/<orgnr>/refresh", methods=["POST"])
def api_refresh_customer(orgnr):
    customers = get_customers()
    root_key, ent = find_customer_entity_by_orgnr(customers, orgnr)
    if not ent or root_key is None:
        return jsonify({"error": "ikke funnet"}), 404
    o = norm_org(orgnr)
    apply_brreg_refresh_to_entity(ent, o)
    sync_stats: Dict[str, Any] = {}
    if ent is customers.get(root_key):
        sync_stats = sync_heleide_subsidiaries_from_bok(customers, o)
    save_customers(customers)
    return jsonify({"updated": True, "customer": ent, "sync_heleide_bok": sync_stats, "is_nested": ent is not customers.get(root_key)})


@bp.route("/customers/<orgnr>", methods=["PATCH"])
def api_patch_customer(orgnr):
    body = request.get_json(force=True, silent=True) or {}
    customers = get_customers()
    target_key = _top_customer_key_for_orgnr(customers, orgnr)
    if not target_key:
        return jsonify({"error": "ikke funnet"}), 404
    c = customers[target_key]

    int_fields = ["abonnementer", "antallAnsatte_override"]
    for f in int_fields:
        if f in body:
            try:
                v = body[f]
                c[f] = int(v) if v not in (None, "", "null") else None
            except Exception:
                return jsonify({"error": f"ugyldig {f}"}), 400

    text_fields = ["navn", "telefon", "epost", "hjemmeside", "adresse",
                   "postnummer", "poststed", "kommune", "naeringskode1",
                   "nace_beskr", "notater", "parent_orgnr", "parent_navn",
                   "promotion_mode"]
    for f in text_fields:
        if f in body:
            v = body[f]
            c[f] = (str(v).strip() if v is not None else "") or None

    if "parent_orgnr" in body:
        po = c.get("parent_orgnr")
        if po:
            par = next((x for x in customers.values() if norm_org(x.get("orgnr")) == norm_org(po)), None)
            if par:
                c["parent_navn"] = par.get("navn") or c.get("parent_navn")
                c["promotion_mode"] = c.get("promotion_mode") or "datterselskap"
        else:
            c["parent_navn"] = None
            if c.get("promotion_mode") == "datterselskap":
                c["promotion_mode"] = None

    customers[target_key] = c
    save_customers(customers)
    return jsonify({"updated": True, "customer": c})


@bp.route("/customers/<orgnr>", methods=["DELETE"])
@require_perm("delete_customers")
def api_delete_customer(orgnr):
    customers = get_customers()
    n_del = norm_org(orgnr)
    new_customers = {k: v for k, v in customers.items() if norm_org(v.get("orgnr")) != n_del}
    if len(new_customers) == len(customers):
        return jsonify({"error": "ikke funnet"}), 404
    save_customers(new_customers)
    cache = load_json(DISCOVERY_CACHE, {})
    for ck in list(cache.keys()):
        if norm_org(ck) == n_del:
            cache.pop(ck, None)
    save_json(DISCOVERY_CACHE, cache)
    _remove_anchor_from_leads([n_del])
    return jsonify({"deleted": orgnr})


@bp.route("/customers/delete-all", methods=["POST"])
@require_perm("delete_customers")
def api_delete_all_customers():
    save_json(CUSTOMERS_FILE, {})
    save_json(DISCOVERY_CACHE, {})
    save_json(LEADS_FILE, [])
    try:
        if CUSTOMERS_BACKUP.exists():
            CUSTOMERS_BACKUP.unlink()
    except Exception:
        pass
    return jsonify({"deleted_all": True})


@bp.route("/customers/delete-bulk", methods=["POST"])
@require_perm("delete_customers")
def api_delete_bulk():
    body = request.get_json(force=True) or {}
    orgnrs = list(body.get("orgnrs") or [])
    customers = get_customers()
    n_set = {norm_org(o) for o in orgnrs if norm_org(o)}
    new_customers = {k: v for k, v in customers.items() if norm_org(v.get("orgnr")) not in n_set}
    save_customers(new_customers)
    cache = load_json(DISCOVERY_CACHE, {})
    for ck in list(cache.keys()):
        if norm_org(ck) in n_set:
            cache.pop(ck, None)
    save_json(DISCOVERY_CACHE, cache)
    _remove_anchor_from_leads([norm_org(o) or o for o in orgnrs])
    return jsonify({"deleted": orgnrs, "remaining": len(new_customers)})


@bp.route("/customers/deduplicate", methods=["POST"])
@require_perm("delete_customers")
def api_deduplicate_customers():
    customers = get_customers()
    by_orgnr = {}
    for k, v in customers.items():
        ron = v.get("orgnr")
        if not ron:
            by_orgnr.setdefault("__no_orgnr__", []).append(k)
            continue
        by_orgnr.setdefault(ron, []).append(k)

    merged = 0
    removed_keys = []
    for ron, keys in by_orgnr.items():
        if ron == "__no_orgnr__" or len(keys) < 2:
            continue
        keys.sort(key=lambda k: (
            -(customers[k].get("abonnementer") or 0),
            -sum(1 for v in customers[k].values() if v),
        ))
        winner_key = keys[0]
        for loser_key in keys[1:]:
            loser = customers[loser_key]
            for field, val in loser.items():
                if val and not customers[winner_key].get(field):
                    customers[winner_key][field] = val
            del customers[loser_key]
            removed_keys.append(loser_key)
            merged += 1

    if merged:
        save_customers(customers)
    return jsonify({"merged": merged, "removed_keys": removed_keys[:50],
                    "remaining": len(customers)})


@bp.route("/search-brreg")
def api_search_brreg():
    q = (request.args.get("q") or "").strip()
    return jsonify({"results": E.search_by_name(q, size=25)})


@bp.route("/customers/search")
def api_search_customers():
    q = (request.args.get("q") or "").strip().lower()
    customers = get_customers()
    out = []
    for c in customers.values():
        navn = (c.get("navn") or "").lower()
        orgnr_s = str(c.get("orgnr") or "").replace(" ", "").lower()
        if q in navn or (orgnr_s and q in orgnr_s):
            out.append({"orgnr": str(c.get("orgnr") or ""), "navn": c.get("navn"), "kommune": c.get("kommune")})
        if len(out) >= 10:
            break
    return jsonify({"results": out})


@bp.route("/customers/add", methods=["POST"])
@require_perm("add")
def api_add_customer():
    body = request.get_json(force=True)
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Mangler navn eller org.nr"}), 400
    if re.fullmatch(r"\d{9}", query):
        data = E.find_company_by_orgnr(query)
    else:
        data = E.find_company_by_name(query)
    if not data:
        return jsonify({"error": f"Fant ikke selskap for '{query}'"}), 404

    if data.get("orgnr") is not None:
        data["orgnr"] = str(data["orgnr"]).strip().replace(" ", "")

    customers = get_customers()
    key = data.get("orgnr") or data["navn"]
    existing_key = _top_customer_key_for_orgnr(customers, data.get("orgnr"))
    if existing_key:
        return jsonify({"already_exists": True, "customer": customers[existing_key]})

    customers[key] = {
        **data, "enriched": True,
        "abonnementer": int(body.get("abonnementer") or 0),
        "added_manually": True,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        customers[key]["related"] = E.fetch_related(
            data.get("orgnr"), data.get("navn"), data.get("kommunenummer"),
            existing_related=customers[key].get("related"),
        )
    except Exception as e:
        print(f"[related] feilet: {e}")
    save_customers(customers)
    try:
        from analysis import schedule_targeted_analysis_for_new_customer

        schedule_targeted_analysis_for_new_customer(str(customers[key].get("orgnr") or ""))
    except Exception as ex:
        print("[api_add_customer] schedule targeted:", ex, flush=True)
    return jsonify({"added": True, "customer": customers[key], "targeted_analysis_queued": True})
