"""Lead-relaterte API-ruter under /api/leads."""
import hashlib
import json
import threading
import traceback
import urllib.parse
from datetime import datetime
from io import BytesIO

import pandas as pd
from flask import jsonify, request, send_file

import enrichment as E
import scoring as S
import geo_enrichment as GEO
from authz import require_perm
from blueprints.auth_routes import get_current_user
from blueprints.web_api import web_api as bp
from paths import LEAD_RELATIONS, LEADS_FILE, NOTES_FILE, STATUS_FILE
from lead_geo import customers_by_orgnr_map, enrich_lead_geo
from lead_promote_whole_owned import promote_whole_owned_leads_from_pool
from persist import (
    get_customers,
    get_leads,
    get_leads_readonly,
    get_notes,
    get_status,
    save_customers,
)
from related_tree import norm_org
from json_store import load_json, save_json
from state import migrate_lead, _enrich_signals_with_anchor_size, _import_state
from user_scoring_profile import load_merged_user_settings


def _lead_scoring_persist_signature(L: dict) -> bytes:
    """Felt score_lead oppdaterer — brukes til å vite om GET /api/leads skal skrive leads.json.

    score og score_breakdown kan divergere (f.eks. gammel breakdown med feil tall mens score
    ble rescored); da må vi lagre selv om toppscore er uendret.
    """
    o = norm_org(L.get("orgnr")) or ""
    bd = json.dumps(L.get("score_breakdown") or {}, sort_keys=True, ensure_ascii=False)
    mac = L.get("multi_anchor_count")
    mac_s = str(int(mac)) if mac is not None else ""
    line = f"{o}\t{int(L.get('score') or 0)}\t{bd}\t{mac_s}\n"
    return line.encode("utf-8", errors="replace")


def _leads_scoring_state_fingerprint(leads):
    h = hashlib.sha256()
    for L in leads:
        h.update(_lead_scoring_persist_signature(L))
    return h.digest()


@bp.route("/leads")
def api_leads():
    leads = get_leads()
    migrated = False
    for L in leads:
        if migrate_lead(L):
            migrated = True
    S._reload()
    sys_set = S.load_settings()
    sys_w, sys_t = sys_set["weights"], sys_set["thresholds"]
    cust = get_customers()
    _enrich_signals_with_anchor_size(leads, sys_t)
    # Fyll geo for avstand/meter — kun relevante ankere (ikke hele kundelisten per request).
    GEO.hydrate_geo_distance_factors_for_leads(leads, cust)
    fp_before = _leads_scoring_state_fingerprint(leads)
    for L in leads:
        S.score_lead(L, sys_w, sys_t)
    leads.sort(key=lambda x: (-x.get("score", 0), -(x.get("antallAnsatte") or 0)))
    fp_after = _leads_scoring_state_fingerprint(leads)
    if migrated or fp_before != fp_after:
        save_json(LEADS_FILE, leads)

    u = get_current_user()
    merged = load_merged_user_settings(u["id"], u["tenant_id"])
    uw, ut = merged["weights"], merged["thresholds"]

    status = get_status()
    notes = get_notes()
    relations = load_json(LEAD_RELATIONS, {})
    cust_by_o = customers_by_orgnr_map(cust)
    out_leads = []
    for L in leads:
        Lr = dict(L)
        S.score_lead(Lr, uw, ut)
        org_key = norm_org(Lr.get("orgnr"))
        Lr["status"] = status.get(org_key, "new") if org_key else "new"
        Lr["note"] = notes.get(org_key, "") if org_key else ""
        rel = relations.get(org_key) if org_key else None
        if rel:
            Lr["parent_lead_orgnr"] = rel.get("parent_orgnr")
            Lr["parent_lead_navn"] = rel.get("parent_navn")
        enrich_lead_geo(Lr, cust_by_o)
        out_leads.append(Lr)
    out_leads.sort(key=lambda x: (-x.get("score", 0), -(x.get("antallAnsatte") or 0)))
    lo_ob, hi_ob = S.ownership_signal_pct_bounds(ut)
    return jsonify(
        {
            "leads": out_leads,
            "count": len(out_leads),
            "thresholds": {
                "kunde_aksjeeierbok_min_pct": lo_ob,
                "kunde_aksjeeierbok_max_pct": hi_ob,
            },
        }
    )


_JSON_NESTED = frozenset({"signals", "score_breakdown", "felles_styre"})
_LIST_JOIN_KEYS = frozenset({"anker_navn", "anker_orgnrs"})


def _truncate_cell(s: str, max_len: int = 31000) -> str:
    if s is None:
        return ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 100] + "\n… (avkortet — Excel maks ~32k tegn; bruk *_json-kolonner for mer)"


def _signals_readable(signals) -> str:
    lines = []
    for s in signals or []:
        if not isinstance(s, dict):
            continue
        line = " | ".join(
            [
                str(s.get("type") or ""),
                str(s.get("anker_orgnr") or ""),
                str(s.get("anker_navn") or "").replace("\n", " "),
                str(s.get("detail") or "").replace("\n", " "),
            ]
        )
        lines.append(line)
    return "\n".join(lines)


def _flatten_lead_row(L: dict) -> dict:
    row = {}
    for k, v in (L or {}).items():
        if k in _JSON_NESTED:
            continue
        if k in _LIST_JOIN_KEYS and isinstance(v, list):
            row[k] = "; ".join(str(x) for x in v if x is not None and str(x).strip() != "")
            continue
        if isinstance(v, bool):
            row[k] = "ja" if v else "nei"
        elif isinstance(v, (dict, list)):
            row[k] = _truncate_cell(json.dumps(v, ensure_ascii=False))
        elif v is None:
            row[k] = ""
        else:
            row[k] = v
    sigs = L.get("signals") if isinstance(L.get("signals"), list) else []
    row["signals_antall"] = len(sigs)
    row["signals_json"] = _truncate_cell(json.dumps(sigs, ensure_ascii=False))
    row["signaler_lesbar"] = _truncate_cell(_signals_readable(sigs))
    row["score_breakdown_json"] = _truncate_cell(
        json.dumps(L.get("score_breakdown") or {}, ensure_ascii=False)
    )
    fs = L.get("felles_styre")
    row["felles_styre_json"] = _truncate_cell(
        json.dumps(fs if isinstance(fs, list) else [], ensure_ascii=False)
    )
    return row


_EXPORT_COL_PRIORITY = (
    "rank_i_eksport",
    "orgnr",
    "navn",
    "score",
    "status",
    "note",
    "postnummer",
    "poststed",
    "kommune",
    "kommunenummer",
    "adresse",
    "naeringskode1",
    "nace_beskr",
    "antallAnsatte",
    "hjemmeside",
    "telefon",
    "epost",
    "konkurs",
    "underAvvikling",
    "erIKonsern",
    "organisasjonsform_kode",
    "geo_tier",
    "geo_label",
    "geoscore",
    "geo_detail",
    "parent_lead_orgnr",
    "parent_lead_navn",
    "multi_anchor_count",
    "anker_navn",
    "anker_orgnrs",
    "signals_antall",
    "signaler_lesbar",
    "signals_json",
    "score_breakdown_json",
    "felles_styre_json",
)


@bp.route("/leads/export-filtered", methods=["POST"])
def api_export_filtered_leads():
    """Én rad per lead som i gjeldende filter (klient sender JSON fra samme filterlogikk som tabellen)."""
    body = request.get_json(force=True, silent=True) or {}
    leads = body.get("leads")
    if not isinstance(leads, list) or not leads:
        return jsonify({"error": "leads må være en ikke-tom liste"}), 400
    rows = [_flatten_lead_row(L) for L in leads]
    df = pd.DataFrame(rows)
    cols = list(df.columns)
    ordered = [c for c in _EXPORT_COL_PRIORITY if c in cols] + sorted(c for c in cols if c not in _EXPORT_COL_PRIORITY)
    df = df[ordered]
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
    bio.seek(0)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fn = f"leadmap-filter-{stamp}.xlsx"
    return send_file(
        bio,
        as_attachment=True,
        download_name=fn,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/leads/search")
def api_search_leads():
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify({"results": []})
    leads = get_leads_readonly()
    out = []
    for L in leads:
        navn = (L.get("navn") or "").lower()
        orgnr = norm_org(L.get("orgnr")) or str(L.get("orgnr") or "")
        if q in navn or q in orgnr.lower():
            out.append({"orgnr": orgnr, "navn": L.get("navn"),
                        "kommune": L.get("kommune"), "score": L.get("score", 0)})
        if len(out) >= 15:
            break
    return jsonify({"results": out})


@bp.route("/leads/<orgnr>/parent-lead", methods=["POST"])
def api_set_parent_lead(orgnr):
    body = request.get_json(force=True, silent=True) or {}
    parent_orgnr = body.get("parent_orgnr")
    parent_navn = body.get("parent_navn")
    lead_key = norm_org(orgnr) or orgnr.strip()
    relations = load_json(LEAD_RELATIONS, {})
    if parent_orgnr:
        if norm_org(parent_orgnr) == lead_key:
            return jsonify({"error": "kan ikke knytte lead til seg selv"}), 400
        relations[lead_key] = {"parent_orgnr": parent_orgnr, "parent_navn": parent_navn}
    else:
        relations.pop(lead_key, None)
    save_json(LEAD_RELATIONS, relations)
    return jsonify({"orgnr": lead_key, "parent_orgnr": parent_orgnr, "parent_navn": parent_navn})


@bp.route("/leads/<orgnr>/status", methods=["POST"])
def api_set_status(orgnr):
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "ugyldig JSON"}), 400
    new_status = (body.get("status") or "new").strip()
    valid = {"new", "kontaktet", "ikke_aktuell", "vunnet", "follow_up",
             "eksisterende_kunde", "datterselskap", "konsern_kunde"}
    if new_status not in valid:
        return jsonify({"error": "ugyldig status"}), 400
    org_key = norm_org(orgnr) or orgnr.strip()
    status = get_status()
    if new_status == "new":
        status.pop(org_key, None)
    else:
        status[org_key] = new_status
    save_json(STATUS_FILE, status)
    return jsonify({"orgnr": org_key, "status": new_status})


@bp.route("/leads/<orgnr>/note", methods=["POST"])
def api_set_note(orgnr):
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "ugyldig JSON"}), 400
    note = (body.get("note") or "").strip()
    org_key = norm_org(orgnr) or orgnr.strip()
    notes = get_notes()
    if note:
        notes[org_key] = note
    else:
        notes.pop(org_key, None)
    save_json(NOTES_FILE, notes)
    return jsonify({"orgnr": org_key, "note": note})


@bp.route("/leads/<orgnr>/linkedin/<role>")
def api_linkedin(orgnr, role):
    leads = get_leads_readonly()
    url_key = norm_org(orgnr)
    lead = next((L for L in leads if norm_org(L.get("orgnr")) == url_key), None)
    if not lead:
        return jsonify({"error": "lead ikke funnet"}), 404
    name = lead["navn"]
    queries = {
        "company": f"https://www.linkedin.com/search/results/companies/?keywords={urllib.parse.quote(name)}",
        "people": f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(name)}",
        "ceo": f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(name + ' CEO daglig leder')}",
        "it": f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(name + ' IT-sjef CIO')}",
        "innkjop": f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(name + ' innkjøp')}",
    }
    url = queries.get(role, queries["company"])
    return jsonify({"url": url})


@bp.route("/leads/<orgnr>/website")
def api_website(orgnr):
    leads = get_leads_readonly()
    url_key = norm_org(orgnr)
    lead = next((L for L in leads if norm_org(L.get("orgnr")) == url_key), None)
    if not lead:
        return jsonify({"error": "lead ikke funnet"}), 404
    url = lead.get("hjemmeside")
    if not url:
        url = f"https://www.google.com/search?q={urllib.parse.quote(lead['navn'])}"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return jsonify({"url": url})


@bp.route("/leads/<orgnr>/proff")
def api_proff(orgnr):
    url = f"https://www.proff.no/bransjes%C3%B8k?q={orgnr}"
    return jsonify({"url": url})


@bp.route("/leads/<orgnr>/proff-data", methods=["POST"])
def api_proff_data(orgnr):
    leads = get_leads_readonly()
    url_key = norm_org(orgnr)
    lead = next((L for L in leads if norm_org(L.get("orgnr")) == url_key), None)
    if not lead:
        return jsonify({"error": "lead ikke funnet"}), 404
    data = E.fetch_proff_data(orgnr)
    return jsonify({"orgnr": orgnr, "proff": data})


def _worker_promote_whole_owned_to_customers():
    try:
        customers = get_customers()
        leads = get_leads_readonly()
        if not isinstance(leads, list):
            _import_state["result"] = {"error": "leads.json er ikke en liste — kan ikke flytte."}
            _import_state["progress"] = "Avbrutt: ugyldig leads-format."
            return
        pool: dict = {}
        for L in leads:
            if not isinstance(L, dict):
                continue
            o = norm_org(L.get("orgnr"))
            if o:
                pool[o] = L
        total_n = len(pool)
        _import_state["total"] = max(1, total_n)
        _import_state["current"] = 0
        _import_state["progress"] = "Starter sjekk mot aksjeeierbok…"

        def _tick(i: int, tot: int, msg: str) -> None:
            _import_state["current"] = i
            _import_state["total"] = max(1, tot)
            _import_state["progress"] = msg or f"{i}/{tot}"

        n = promote_whole_owned_leads_from_pool(
            pool,
            customers,
            tick_fn=_tick,
            rebuild_anchor_each_move=False,
        )
        out = list(pool.values())
        if n:
            save_customers(customers)
            for L in out:
                try:
                    S.score_lead(L)
                except Exception:
                    pass
            out.sort(key=lambda x: (-x.get("score", 0), -(x.get("antallAnsatte") or 0)))
            save_json(LEADS_FILE, out)
        _import_state["result"] = {"moved": n, "remaining": len(out)}
        _import_state["progress"] = f"✅ Ferdig: flyttet {n} lead(s). {len(out)} gjenstår."
        _import_state.setdefault("log", []).append(
            {"t": datetime.now().isoformat(timespec="seconds"), "msg": _import_state["progress"]}
        )
    except Exception as ex:
        tb = traceback.format_exc()
        print("[promote_whole_owned]", tb, flush=True)
        _import_state["result"] = {"error": str(ex)}
        _import_state["progress"] = f"Feil: {ex}"
        _import_state.setdefault("log", []).append(
            {"t": datetime.now().isoformat(timespec="seconds"), "msg": _import_state["progress"]}
        )
    finally:
        _import_state["running"] = False
        _import_state["job"] = ""


@bp.route("/leads/promote-whole-owned-to-customers", methods=["POST"])
@require_perm("add")
def api_promote_whole_owned_to_customers():
    """Flytt leads som er ≥99 % eid (aksjeeierbok) av org.nr i kundetre inn som manuelle datre (bakgrunn + fremdrift)."""
    try:
        if _import_state["running"]:
            return jsonify({"running": True, "error": "annen jobb kjører — vent"}), 409
        leads = get_leads_readonly()
        if not isinstance(leads, list):
            return jsonify({"error": "leads.json er ikke en liste"}), 400
        total = sum(1 for L in leads if isinstance(L, dict) and norm_org(L.get("orgnr")))
        if total == 0:
            return jsonify({"error": "ingen leads med gyldig org.nr"}), 400
        _import_state["running"] = True
        _import_state["job"] = "promote_whole_owned"
        _import_state["log"] = []
        _import_state["result"] = None
        _import_state["progress"] = "Køer heleid-lead → kunde…"
        _import_state["current"] = 0
        _import_state["total"] = max(1, total)
        threading.Thread(target=_worker_promote_whole_owned_to_customers, daemon=True).start()
        return jsonify({"started": True, "total": total})
    except Exception as ex:
        _import_state["running"] = False
        _import_state["job"] = ""
        print("[api_promote_whole_owned]", traceback.format_exc(), flush=True)
        return jsonify({"error": str(ex)}), 500


@bp.route("/leads/<orgnr>/promote", methods=["POST"])
def api_promote_lead(orgnr):
    body = request.get_json(force=True, silent=True) or {}
    abonnementer = int(body.get("abonnementer") or 0)
    auto_analyze = bool(body.get("auto_analyze", True))
    mode = body.get("mode", "vunnet")
    parent_orgnr = body.get("parent_orgnr")
    parent_navn = body.get("parent_navn")

    leads = get_leads_readonly()
    url_key = norm_org(orgnr)
    lead = next((L for L in leads if norm_org(L.get("orgnr")) == url_key), None)
    if not lead:
        return jsonify({"error": "lead ikke funnet"}), 404

    customers_dict = get_customers()
    lead_org = norm_org(lead.get("orgnr")) or lead.get("orgnr")
    new_customer = {
        "orgnr": lead_org, "navn": lead["navn"],
        "postnummer": lead.get("postnummer"), "poststed": lead.get("poststed"),
        "kommune": lead.get("kommune"), "kommunenummer": lead.get("kommunenummer"),
        "adresse": lead.get("adresse"),
        "naeringskode1": lead.get("naeringskode1"), "nace_beskr": lead.get("nace_beskr"),
        "antallAnsatte": lead.get("antallAnsatte"),
        "hjemmeside": lead.get("hjemmeside"),
        "telefon": lead.get("telefon"), "epost": lead.get("epost"),
        "abonnementer": abonnementer,
        "enriched": True, "promoted_from_lead": True,
        "promotion_mode": mode,
        "promoted_at": datetime.now().isoformat(timespec="seconds"),
    }
    if mode == "datterselskap" and parent_orgnr:
        new_customer["parent_orgnr"] = parent_orgnr
        new_customer["parent_navn"] = parent_navn
    # Hent konsern/underenheter fra Brreg — lead-raden hadde ikke nødvendigvis «related».
    try:
        new_customer["related"] = E.fetch_related(
            str(new_customer["orgnr"]),
            new_customer.get("navn"),
            new_customer.get("kommunenummer"),
            existing_related=None,
        )
    except Exception:
        new_customer["related"] = new_customer.get("related") or {}
    customer_key = new_customer.get("orgnr") or new_customer.get("navn")
    old_name_key = lead.get("navn")
    if old_name_key and old_name_key != customer_key:
        customers_dict.pop(old_name_key, None)
    customers_dict[customer_key] = new_customer
    save_customers(customers_dict)

    status = get_status()
    st_key = norm_org(orgnr) or orgnr.strip()
    status[st_key] = mode if mode in ("vunnet", "eksisterende_kunde", "datterselskap") else "vunnet"
    save_json(STATUS_FILE, status)

    leads = [L for L in leads if norm_org(L.get("orgnr")) != url_key]
    save_json(LEADS_FILE, leads)

    targeted_queued = False
    if auto_analyze:
        try:
            from analysis import schedule_targeted_analysis_for_new_customer

            schedule_targeted_analysis_for_new_customer(str(new_customer["orgnr"]))
            targeted_queued = True
        except Exception as ex:
            print("[api_promote_lead] schedule targeted:", ex, flush=True)
    return jsonify({"promoted": True, "customer": new_customer, "targeted_analysis_queued": targeted_queued})
