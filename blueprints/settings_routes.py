"""Innstillinger, re-score og statistikk — per-bruker vekter; systemfil ved eier."""
from flask import jsonify, request

import scoring as S
import geo_enrichment as GEO
import ownership_signals as OWN
from blueprints.auth_routes import get_current_user
from blueprints.web_api import web_api as bp
from paths import ANALYSIS_LOG, LEADS_FILE
from persist import get_customers, get_leads_readonly, get_status, save_customers
from json_store import load_json, save_json
from related_tree import norm_org
from state import _enrich_signals_with_anchor_size
from user_scoring_profile import load_merged_user_settings, save_user_scoring_profile
import users_db as UDB


@bp.route("/settings", methods=["GET"])
def api_get_settings():
    u = get_current_user()
    merged = load_merged_user_settings(u["id"], u["tenant_id"])
    perms = UDB.effective_permissions(u)
    merged = dict(merged)
    merged["me"] = {
        "id": u["id"],
        "role": u["role"],
        "email": u["email"],
        "permissions": perms,
    }
    return jsonify(merged)


@bp.route("/settings", methods=["POST"])
def api_save_settings():
    u = get_current_user()
    body = request.get_json(force=True, silent=True) or {}
    weights = body.get("weights")
    thresholds = body.get("thresholds")

    if u["id"] == 0:
        pre = S.load_settings()
        pre_thr = pre.get("thresholds") or {}
        pre_lo = float(pre_thr.get("kunde_aksjeeierbok_min_pct", 5.0) or 5.0)
        pre_hi = float(pre_thr.get("kunde_aksjeeierbok_max_pct", 100.0) or 100.0)
        out = S.save_settings(weights=weights, thresholds=thresholds)
        S._reload()
        post_thr = S.THRESHOLDS
        post_lo = float(post_thr.get("kunde_aksjeeierbok_min_pct", 5.0) or 5.0)
        post_hi = float(post_thr.get("kunde_aksjeeierbok_max_pct", 100.0) or 100.0)
        customers = get_customers()
        leads = get_leads_readonly()
        if (round(pre_lo, 4), round(pre_hi, 4)) != (round(post_lo, 4), round(post_hi, 4)):
            OWN.refresh_customer_ownership_signals_on_leads(leads, customers)
        min_ans = int(S.THRESHOLDS.get("min_lead_ansatte", 4))
        GEO.hydrate_geo_distance_factors_for_leads(leads, customers)
        _enrich_signals_with_anchor_size(leads, S.THRESHOLDS)
        hidden_below_threshold = sum(1 for L in leads if (L.get("antallAnsatte") or 0) < min_ans)
        hidden_without_signals = sum(1 for L in leads if not L.get("signals"))
        for L in leads:
            S.score_lead(L)
        leads.sort(key=lambda x: (-x.get("score", 0), -(x.get("antallAnsatte") or 0)))
        save_json(LEADS_FILE, leads)
        return jsonify(
            {
                "saved": True,
                "settings": out,
                "rescored": len(leads),
                "hidden_below_threshold": hidden_below_threshold,
                "hidden_without_signals": hidden_without_signals,
            }
        )

    save_user_scoring_profile(u["id"], u["tenant_id"], weights=weights, thresholds=thresholds)

    if u.get("role") == "owner":
        pre = S.load_settings()
        pre_thr = pre.get("thresholds") or {}
        pre_lo = float(pre_thr.get("kunde_aksjeeierbok_min_pct", 5.0) or 5.0)
        pre_hi = float(pre_thr.get("kunde_aksjeeierbok_max_pct", 100.0) or 100.0)
        out = S.save_settings(weights=weights, thresholds=thresholds)
        S._reload()
        post_thr = S.THRESHOLDS
        post_lo = float(post_thr.get("kunde_aksjeeierbok_min_pct", 5.0) or 5.0)
        post_hi = float(post_thr.get("kunde_aksjeeierbok_max_pct", 100.0) or 100.0)
        customers = get_customers()
        leads = get_leads_readonly()
        if (round(pre_lo, 4), round(pre_hi, 4)) != (round(post_lo, 4), round(post_hi, 4)):
            OWN.refresh_customer_ownership_signals_on_leads(leads, customers)
        min_ans = int(S.THRESHOLDS.get("min_lead_ansatte", 4))
        GEO.hydrate_geo_distance_factors_for_leads(leads, customers)
        _enrich_signals_with_anchor_size(leads, S.THRESHOLDS)
        hidden_below_threshold = sum(1 for L in leads if (L.get("antallAnsatte") or 0) < min_ans)
        hidden_without_signals = sum(1 for L in leads if not L.get("signals"))
        for L in leads:
            S.score_lead(L)
        leads.sort(key=lambda x: (-x.get("score", 0), -(x.get("antallAnsatte") or 0)))
        save_json(LEADS_FILE, leads)
        return jsonify(
            {
                "saved": True,
                "settings": load_merged_user_settings(u["id"], u["tenant_id"]),
                "rescored": len(leads),
                "hidden_below_threshold": hidden_below_threshold,
                "hidden_without_signals": hidden_without_signals,
            }
        )

    return jsonify(
        {
            "saved": True,
            "settings": load_merged_user_settings(u["id"], u["tenant_id"]),
            "rescored": 0,
            "hidden_below_threshold": 0,
            "hidden_without_signals": 0,
        }
    )


@bp.route("/rescore", methods=["POST"])
def api_rescore():
    S._reload()
    customers = get_customers()
    leads = get_leads_readonly()
    OWN.refresh_customer_ownership_signals_on_leads(leads, customers)
    GEO.refresh_geo_scoring_for_leads(leads, customers)
    GEO.finalize_leads_scoring_after_geo_refresh(leads, customers)
    return jsonify({"rescored": len(leads)})


@bp.route("/stats")
def api_stats():
    leads = get_leads_readonly()
    status = get_status()
    customers_dict = get_customers()
    by_status = {}
    for L in leads:
        st = status.get(norm_org(L.get("orgnr")), "new")
        by_status[st] = by_status.get(st, 0) + 1
    history = load_json(ANALYSIS_LOG, [])
    return jsonify(
        {
            "total_leads": len(leads),
            "total_customers": len(customers_dict),
            "enriched_customers": sum(1 for c in customers_dict.values() if c.get("enriched")),
            "by_status": by_status,
            "last_run": history[-1] if history else None,
        }
    )
