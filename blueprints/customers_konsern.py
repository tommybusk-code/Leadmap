"""Konsern, datterselskaper, morselskap-import og bulk refresh."""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from flask import jsonify, request

import enrichment as E
from authz import require_perm
from blueprints.web_api import web_api as bp
from json_store import load_json, save_json
from paths import AKSJONAERINFO_BULK_STATE
from persist import get_customers, save_customers
from related_tree import (
    find_customer_entity_by_orgnr,
    find_manual_subsidiary_attachment_list,
    flatten_all_customer_tree_refresh_tasks,
    manual_orgnr_exists_in_tree,
    norm_org,
    remove_manual_orgnr_from_customers,
    remove_manual_orgnr_from_related,
)
from state import _import_state
from bok_tree_sync import sync_heleide_subsidiaries_from_bok
from blueprints.customers_crud import _top_customer_key_for_orgnr, apply_brreg_refresh_to_entity


def _load_aksjonaerinfo_bulk_known() -> set:
    raw = load_json(AKSJONAERINFO_BULK_STATE, {})
    out: set = set()
    for x in raw.get("known_orgnrs") or []:
        n = norm_org(x)
        if n:
            out.add(n)
    return out


def _save_aksjonaerinfo_bulk_snapshot_from_customers(customers: dict) -> None:
    flat = flatten_all_customer_tree_refresh_tasks(customers)
    snap = {norm_org(o) for _, o in flat}
    save_json(
        AKSJONAERINFO_BULK_STATE,
        {
            "known_orgnrs": sorted(snap),
            "updated": datetime.now().isoformat(timespec="seconds"),
        },
    )


@bp.route("/customers/<orgnr>/add-subsidiary", methods=["POST"])
@require_perm("add")
def api_add_subsidiary(orgnr):
    body = request.get_json(force=True, silent=True) or {}
    sub_orgnr = (body.get("orgnr") or "").strip()
    if not sub_orgnr:
        return jsonify({"error": "mangler orgnr"}), 400
    customers = get_customers()
    if manual_orgnr_exists_in_tree(customers, sub_orgnr):
        return jsonify({"error": "allerede koblet (kunde eller i struktur)"}), 400
    target_key, manual_list = find_manual_subsidiary_attachment_list(customers, orgnr)
    if not target_key or manual_list is None:
        return jsonify({"error": "forelder ikke funnet (toppkunde, avdeling eller manuell datter)"}), 404
    sub = E.find_company_by_orgnr(sub_orgnr)
    if not sub:
        return jsonify({"error": "datterselskap ikke funnet i brreg"}), 404
    sub["type"] = "manual_subsidiary"
    # Hent underenheter + konsern-info for dette orgnr (barn vises under manuell datter).
    sub["related"] = E.fetch_related(
        sub_orgnr,
        (sub.get("navn") or ""),
        sub.get("kommunenummer"),
        existing_related=sub.get("related") if isinstance(sub.get("related"), dict) else None,
    )
    manual_list.append(sub)
    save_customers(customers)
    c = customers[target_key]
    return jsonify({"added": True, "subsidiary": sub, "customer": c})


@bp.route("/customers/<orgnr>/sync-heleide-fra-bok", methods=["POST"])
@require_perm("add")
def api_sync_heleide_fra_bok(orgnr):
    """Legg inn manuelle datre for selskaper der kunden eier ≥99 % i aksjeeierbok (uten full Brreg-refresh av roten)."""
    customers = get_customers()
    stats = sync_heleide_subsidiaries_from_bok(customers, orgnr)
    if stats.get("error") == "ugyldig orgnr":
        return jsonify(stats), 400
    if stats.get("error") == "fant ikke kunden som toppnode eller som forelder i treet":
        return jsonify(stats), 404
    save_customers(customers)
    return jsonify(stats)


@bp.route("/customers/<orgnr>/remove-subsidiary", methods=["POST"])
@require_perm("delete_customers")
def api_remove_subsidiary(orgnr):
    body = request.get_json(force=True, silent=True) or {}
    sub_orgnr = (body.get("orgnr") or "").strip()
    customers = get_customers()
    target_key = _top_customer_key_for_orgnr(customers, orgnr)
    if target_key:
        rel = customers[target_key].setdefault("related", {})
        if remove_manual_orgnr_from_related(rel, sub_orgnr):
            save_customers(customers)
            return jsonify({"removed": True})
    if remove_manual_orgnr_from_customers(customers, sub_orgnr):
        save_customers(customers)
        return jsonify({"removed": True})
    return jsonify({"error": "kobling ikke funnet"}), 404


@bp.route("/konsern-overview")
def api_konsern_overview():
    customers = get_customers()
    by_orgnr = {c.get("orgnr"): c for c in customers.values() if c.get("orgnr")}
    groups = {}
    for c in customers.values():
        rel = c.get("related") or {}
        mor_orgnr = rel.get("mor_orgnr")
        if rel.get("konsern_kilde") == "eget" and c.get("orgnr"):
            mor_id = c["orgnr"]
            if mor_id not in groups:
                groups[mor_id] = {
                    "mor_orgnr": mor_id,
                    "mor_navn": c.get("navn"),
                    "mor_er_kunde": True,
                    "mor_konsern_ansatte": rel.get("konsern_ansatte"),
                    "mor_periode": rel.get("konsern_periode"),
                    "mor_konsern_sum_eiendeler": rel.get("konsern_sum_eiendeler"),
                    "dattere": [],
                }
            continue
        if not mor_orgnr:
            continue
        if mor_orgnr not in groups:
            mor_in_customers = by_orgnr.get(mor_orgnr)
            groups[mor_orgnr] = {
                "mor_orgnr": mor_orgnr,
                "mor_navn": rel.get("mor_navn") or (mor_in_customers.get("navn") if mor_in_customers else None),
                "mor_er_kunde": bool(mor_in_customers),
                "mor_konsern_ansatte": rel.get("konsern_ansatte"),
                "mor_periode": rel.get("konsern_periode"),
                "mor_konsern_sum_eiendeler": rel.get("konsern_sum_eiendeler"),
                "dattere": [],
            }
        else:
            ke = rel.get("konsern_sum_eiendeler")
            if ke and not groups[mor_orgnr].get("mor_konsern_sum_eiendeler"):
                groups[mor_orgnr]["mor_konsern_sum_eiendeler"] = ke
        groups[mor_orgnr]["dattere"].append({
            "orgnr": c.get("orgnr"),
            "navn": c.get("navn"),
            "antallAnsatte": c.get("antallAnsatte") or 0,
            "kommune": c.get("kommune"),
            "abonnementer": c.get("abonnementer") or 0,
            "parent_orgnr_set": bool(c.get("parent_orgnr")),
            "selskap_sum_eiendeler": rel.get("selskap_sum_eiendeler"),
            "rapporterer_til_konsern": rel.get("rapporterer_til_konsern"),
        })
    out = sorted(groups.values(), key=lambda g: (-len(g["dattere"]),
                                                  -(g.get("mor_konsern_ansatte") or 0)))
    return jsonify({"groups": out, "total_groups": len(out)})


@bp.route("/customers/import-morselskap/<orgnr>", methods=["POST"])
@require_perm("add")
def api_import_morselskap(orgnr):
    customers = get_customers()
    if any(c.get("orgnr") == orgnr for c in customers.values()):
        return jsonify({"error": "morselskapet er allerede kunde"}), 400
    data = E.find_company_by_orgnr(orgnr)
    if not data:
        return jsonify({"error": "ikke funnet i brreg"}), 404
    key = data.get("navn") or orgnr
    while key in customers:
        key = f"{key} ({orgnr})"
    customers[key] = {
        **data,
        "enriched": True,
        "abonnementer": 0,
        "promotion_mode": "morselskap_auto",
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        customers[key]["related"] = E.fetch_related(
            orgnr, data.get("navn"), data.get("kommunenummer"),
            existing_related=customers[key].get("related"),
        )
    except Exception:
        pass
    linked = 0
    for c in customers.values():
        if c is customers[key]:
            continue
        rel = c.get("related") or {}
        if rel.get("mor_orgnr") == orgnr and not c.get("parent_orgnr"):
            c["parent_orgnr"] = orgnr
            c["parent_navn"] = data.get("navn")
            c["promotion_mode"] = c.get("promotion_mode") or "datterselskap"
            linked += 1
    save_customers(customers)
    return jsonify({"added": True, "customer": customers[key], "dattere_linked": linked})


@bp.route("/customers/import-all-morselskaper", methods=["POST"])
@require_perm("add")
def api_import_all_morselskaper():
    customers = get_customers()
    existing = {c.get("orgnr") for c in customers.values() if c.get("orgnr")}
    mor_orgnrs = set()
    for c in customers.values():
        mo = (c.get("related") or {}).get("mor_orgnr")
        if mo and mo not in existing:
            mor_orgnrs.add(mo)
    added, failed = 0, 0
    for mo in mor_orgnrs:
        data = E.find_company_by_orgnr(mo)
        if not data:
            failed += 1
            continue
        key = data.get("navn") or mo
        while key in customers:
            key = f"{key} ({mo})"
        customers[key] = {
            **data, "enriched": True, "abonnementer": 0,
            "promotion_mode": "morselskap_auto",
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            customers[key]["related"] = E.fetch_related(
                mo, data.get("navn"), data.get("kommunenummer"),
                existing_related=customers[key].get("related"),
            )
        except Exception:
            pass
        for c in customers.values():
            if c is customers[key]:
                continue
            rel = c.get("related") or {}
            if rel.get("mor_orgnr") == mo and not c.get("parent_orgnr"):
                c["parent_orgnr"] = mo
                c["parent_navn"] = data.get("navn")
                c["promotion_mode"] = c.get("promotion_mode") or "datterselskap"
        added += 1
    save_customers(customers)
    return jsonify({"added": added, "failed": failed, "total_detected": len(mor_orgnrs)})


@bp.route("/customers/refresh-all-related", methods=["POST"])
@require_perm("add")
def api_refresh_all_related():
    if _import_state["running"]:
        return jsonify({"running": True, "error": "annen jobb kjører — vent"}), 409
    customers = get_customers()
    target_orgnrs = [c.get("orgnr") for c in customers.values() if c.get("orgnr") and c.get("enriched")]
    _import_state["running"] = True
    _import_state["job"] = "refresh_related"
    _import_state["log"] = []
    _import_state["result"] = None
    _import_state["progress"] = "Starter oppdatering..."
    _import_state["current"] = 0
    _import_state["total"] = len(target_orgnrs)
    threading.Thread(target=lambda: _do_refresh_all_related(target_orgnrs), daemon=True).start()
    return jsonify({"started": True, "total": len(target_orgnrs)})


@bp.route("/customers/refresh-all-aksjonaerinfo", methods=["POST"])
@require_perm("add")
def api_refresh_all_aksjonaerinfo():
    """Brreg berikelse per tre-node. Som standard kun org.nr som ikke var med ved forrige vellykkede kjøring."""
    if _import_state["running"]:
        return jsonify({"running": True, "error": "annen jobb kjører — vent"}), 409
    body = request.get_json(force=True, silent=True) or {}
    force_full = bool(body.get("full"))
    customers = get_customers()
    flat = flatten_all_customer_tree_refresh_tasks(customers)
    if not flat:
        return jsonify({"error": "ingen kunder"}), 400
    current_org = {norm_org(o) for _, o in flat}
    known = _load_aksjonaerinfo_bulk_known()
    if force_full or not known:
        to_run = flat
        mode = "full"
    else:
        to_run = [p for p in flat if norm_org(p[1]) not in known]
        mode = "incremental"
    if not to_run:
        _save_aksjonaerinfo_bulk_snapshot_from_customers(customers)
        return jsonify(
            {
                "started": False,
                "mode": mode,
                "message": "Ingen nye org.nr i kundetrær siden forrige vellykkede kjøring. Snapshot er oppdatert til dagens tre.",
                "new_count": 0,
                "total_in_trees": len(current_org),
                "previously_known": len(known),
            }
        )
    _import_state["running"] = True
    _import_state["job"] = "aksjonaerinfo"
    _import_state["log"] = []
    _import_state["result"] = None
    _import_state["progress"] = (
        "Starter berikelse (alle tre-noder)…" if mode == "full" else f"Starter berikelse av {len(to_run)} nye tre-noder…"
    )
    _import_state["current"] = 0
    _import_state["total"] = len(to_run)
    trees_total = len(flat)
    threading.Thread(
        target=lambda: _do_refresh_all_aksjonaerinfo(to_run, mode, trees_total),
        daemon=True,
    ).start()
    return jsonify(
        {
            "started": True,
            "total": len(to_run),
            "mode": mode,
            "trees_total_nodes": trees_total,
            "skipped_already_known": trees_total - len(to_run),
        }
    )


def _aksj_log(msg: str) -> None:
    print(msg, flush=True)
    _import_state["log"].append({"t": datetime.now().isoformat(timespec="seconds"), "msg": msg})
    _import_state["progress"] = msg


def _do_refresh_all_aksjonaerinfo(flat_tasks, mode: str, trees_total: int):
    try:
        customers = get_customers()
        save_lock = threading.Lock()
        counters = {"done": 0, "failed": 0, "i": 0}
        total = len(flat_tasks)
        _aksj_log(f"Modus {mode}: beriker {total} noder (totalt {trees_total} noder i alle tre).")

        def _one(pair):
            _root_key, o = pair
            _, ent = find_customer_entity_by_orgnr(customers, o)
            if not ent:
                return False
            try:
                apply_brreg_refresh_to_entity(ent, o)
                return True
            except Exception as ex:
                print(f"[aksjonaerinfo] feil {o}: {ex}", flush=True)
                return False

        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = [ex.submit(_one, p) for p in flat_tasks]
            for fut in as_completed(futures):
                ok = fut.result()
                with save_lock:
                    counters["i"] += 1
                    if ok:
                        counters["done"] += 1
                    else:
                        counters["failed"] += 1
                    _import_state["current"] = counters["i"]
                    _import_state["progress"] = f"Beriker tre {counters['i']}/{total}"
                    if counters["i"] % 20 == 0:
                        save_customers(customers)
                        _aksj_log(f"  Mellomlagring etter {counters['i']} noder")

        save_customers(customers)
        _save_aksjonaerinfo_bulk_snapshot_from_customers(get_customers())
        _import_state["result"] = {
            "refreshed": counters["done"],
            "failed": counters["failed"],
            "total": total,
            "mode": mode,
            "trees_total_nodes": trees_total,
        }
        _aksj_log(f"✅ Ferdig: {counters['done']} noder beriket, {counters['failed']} feilet.")
    finally:
        _import_state["running"] = False
        _import_state["job"] = ""


def _do_refresh_all_related(orgnrs):
    try:
        customers = get_customers()
        key_by_orgnr = {v.get("orgnr"): k for k, v in customers.items() if v.get("orgnr")}
        save_lock = threading.Lock()
        counters = {"done": 0, "failed": 0, "i": 0}

        def _refresh_one(ron):
            key = key_by_orgnr.get(ron)
            if not key:
                return
            c = customers[key]
            try:
                related = E.fetch_related(
                    ron, c.get("navn"), c.get("kommunenummer"),
                    existing_related=customers[key].get("related"),
                )
                with save_lock:
                    customers[key]["related"] = related
                    counters["done"] += 1
            except Exception as e:
                with save_lock:
                    counters["failed"] += 1
                print(f"[refresh] feil for {c.get('navn')}: {e}")
            with save_lock:
                counters["i"] += 1
                _import_state["current"] = counters["i"]
                _import_state["progress"] = f"Oppdaterer {counters['i']}/{len(orgnrs)}"
                if counters["i"] % 50 == 0:
                    save_customers(customers)

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(as_completed([ex.submit(_refresh_one, ron) for ron in orgnrs]))

        save_customers(customers)
        _import_state["result"] = {"refreshed": counters["done"],
                                    "failed": counters["failed"],
                                    "total": len(orgnrs)}
        _import_state["progress"] = f"✅ Ferdig: {counters['done']} oppdatert, {counters['failed']} feilet."
    finally:
        _import_state["running"] = False
        _import_state["job"] = ""
