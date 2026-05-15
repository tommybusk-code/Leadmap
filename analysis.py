"""analysis.py — run_analysis (full) og run_targeted_analysis (rundt én ny anker).
Registrerer /api/analyze og /api/analyze/status på state.app.
Parallellisering i analysis_parallel.py.
"""
import re
import threading
from datetime import datetime
from flask import jsonify, request

import enrichment as E
import geo_enrichment as GEO
import ownership_signals as OWN
import scoring as S
import users_db as UDB
from analysis_parallel import _parallel_run
from blueprints.auth_routes import get_current_user
from related_tree import iter_tree_company_nodes_with_org, norm_org
from persist import get_customers, get_leads_readonly
from state import (
    app, _analysis, _lock,
    DISCOVERY_CACHE, ROLLER_CACHE, ANSATTE_HISTORY, ANALYSIS_LOG, LEADS_FILE,
    get_customers, get_status,
    save_customers, save_json, load_json,
    import_xlsx_if_empty,
    _effective_ansatte, _enrich_signals_with_anchor_size, _log, _set_phase, _tick_safe, _vekst_check,
    get_jobs_overview,
)


def _merge_preserved_lead_analysis(old, new):
    """Bevar signaler og felles_styre fra disk når ``new`` er bygget fra discovery-cache alene."""
    if not old:
        return
    new_s = list(new.get("signals") or [])
    sk = {(x.get("type"), x.get("anker_orgnr")) for x in new_s}
    for s in old.get("signals") or ():
        key = (s.get("type"), s.get("anker_orgnr"))
        if key not in sk:
            new_s.append(s)
            sk.add(key)
    new["signals"] = new_s

    new_fs = list(new.get("felles_styre") or [])
    seen_ank = {fs.get("anker_orgnr") for fs in new_fs if fs.get("anker_orgnr")}
    for fs in old.get("felles_styre") or ():
        ao = fs.get("anker_orgnr")
        if ao and ao not in seen_ank:
            new_fs.append(fs)
            seen_ank.add(ao)
    new["felles_styre"] = new_fs


def _board_overlap_signal_detail(
    lead_navn: str, anker_navn: str, personer: list, max_chars: int = 320
) -> str:
    """Lesbar forklaring på styre-overlapp — samme ordlyd som «Sterke treff» i lead-detalj."""
    ln = (lead_navn or "").strip() or "lead"
    an = (anker_navn or "").strip() or "kunde"
    parts: list[str] = []
    for p in (personer or [])[:5]:
        navn = (p.get("navn") or "").strip()
        if not navn:
            continue
        rl = (p.get("rolle_lead") or "").strip() or "Styre"
        ra = (p.get("rolle_anker") or "").strip() or "Styre"
        prefix = "👑 " if p.get("power") else "👤 "
        parts.append(f"{prefix}{navn} — {rl} hos {ln}, {ra} hos {an}")
    out = "; ".join(parts)
    if len(out) > max_chars:
        return out[: max_chars - 1].rstrip() + "…"
    return out


def _all_discovery_anchors(customers):
    """Toppkunder + Brreg-underenheter + manuelle datre (hele treet per kunde) som ankere for discovery."""
    anchors: list = []
    seen: set = set()
    for c in customers.values():
        if not isinstance(c, dict):
            continue
        if not norm_org(c.get("orgnr")):
            continue
        for ent, o in iter_tree_company_nodes_with_org(c):
            if o in seen:
                continue
            seen.add(o)
            node = dict(ent)
            if not node.get("naeringskode1") or not node.get("kommunenummer"):
                data = E.find_company_by_orgnr(o)
                if data and isinstance(data, dict):
                    for k, v in data.items():
                        if v is not None and v != "" and node.get(k) in (None, ""):
                            node[k] = v
            node.setdefault("enriched", True)
            node["orgnr"] = o
            anchors.append(node)
    return anchors


def run_analysis(
    full_rebuild: bool = False,
    skip_geocode: bool = False,
    geo_only_new_leads: bool = True,
):
    with _lock:
        if _analysis["running"]:
            return False
        _analysis["running"] = True
        _analysis["log"] = []
        _analysis["current"] = 0
        _analysis["total"] = 0
        _analysis["phase"] = "Starter..."
        _analysis["job"] = "analyze"
    try:
        S._reload()
        customers = import_xlsx_if_empty()
        if not customers:
            _log("Ingen kunder funnet.")
            return

        # 1) Berikning — parallelt
        _set_phase(f"Beriker {len(customers)} kunder", total=len(customers))
        _log(f"Beriker {len(customers)} kunder via Brønnøysund (parallelt)...")
        cust_lock = threading.Lock()
        save_counter = {"n": 0}

        def _enrich_one(key):
            c = customers[key]
            changed = False
            # Slå opp navn hvis ikke beriket
            if not c.get("enriched") or not c.get("orgnr"):
                data = E.find_company_by_name(c["navn"])
                with cust_lock:
                    if data:
                        c.update(data)
                        c["enriched"] = True
                    else:
                        c["enriched"] = False
                        c["enrich_error"] = "ikke funnet i brreg"
                    customers[key] = c
                    changed = True
            # Hent related hvis ikke satt
            if c.get("enriched") and c.get("orgnr") and not c.get("related"):
                try:
                    related = E.fetch_related(
                        c["orgnr"], c.get("navn"), c.get("kommunenummer"),
                        existing_related=c.get("related"),
                    )
                    with cust_lock:
                        c["related"] = related
                        customers[key] = c
                        changed = True
                except Exception:
                    pass
            with cust_lock:
                if changed:
                    save_counter["n"] += 1
                    if save_counter["n"] % 50 == 0:
                        save_customers(customers)
            _tick_safe()

        _parallel_run(list(customers.keys()), _enrich_one)
        save_customers(customers)
        _log(f"Berikning ferdig: {sum(1 for c in customers.values() if c.get('enriched'))} totalt beriket.")

        anchors = _all_discovery_anchors(customers)

        # Filtrer bort ankere som er for små (basert på effektive ansatte)
        min_anchor = int(S.THRESHOLDS.get("min_anchor_ansatte", 0) or 0)
        if min_anchor > 0:
            before = len(anchors)
            anchors = [a for a in anchors if _effective_ansatte(a) >= min_anchor]
            _log(f"Anker-filter: {len(anchors)}/{before} ankere har ≥{min_anchor} effektive ansatte.")

        # 2) Lead-discovery (per-anker cache)
        cache = {} if full_rebuild else load_json(DISCOVERY_CACHE, {})
        anchors_to_run = [a for a in anchors if full_rebuild or a["orgnr"] not in cache]

        if anchors_to_run:
            _set_phase(f"Søker leads for {len(anchors_to_run)} ankere", total=len(anchors_to_run))
            _log(f"Søker etter leads for {len(anchors_to_run)} ankere parallelt ({'full rebuild' if full_rebuild else 'inkrementell'})...")
            cache_lock = threading.Lock()
            save_counter = {"n": 0}

            def _discover_one(anchor):
                try:
                    cands = E.discover_leads_for_anchor(anchor)
                    with cache_lock:
                        cache[anchor["orgnr"]] = cands
                        save_counter["n"] += 1
                        if save_counter["n"] % 50 == 0:
                            save_json(DISCOVERY_CACHE, cache)
                except Exception:
                    pass
                _tick_safe()

            _parallel_run(anchors_to_run, _discover_one)
            save_json(DISCOVERY_CACHE, cache)
        else:
            _log("Bruker cache for alle ankere.")

        # Aggreger
        all_leads = {}
        active_orgnrs = {a["orgnr"] for a in anchors}
        for orgnr, cands in cache.items():
            if orgnr not in active_orgnrs:
                continue
            for c in cands:
                key = c["orgnr"]
                if key not in all_leads:
                    all_leads[key] = dict(c)
                    all_leads[key]["signals"] = list(c.get("signals", []))
                else:
                    existing = all_leads[key]["signals"]
                    for s in c.get("signals", []):
                        if not any(x["type"] == s["type"] and x["anker_orgnr"] == s["anker_orgnr"] for x in existing):
                            existing.append(s)
        _log(f"Funnet {len(all_leads)} unike kandidater.")

        # 3) Vekst-deteksjon — laster historikk én gang, oppdaterer in-memory, lagrer én gang
        history = load_json(ANSATTE_HISTORY, {})
        first_run = len(history) == 0
        n_vekst = 0
        if first_run:
            _log("Første kjøring — registrerer baseline for vekst-måling (ingen deteksjon ennå).")
            for orgnr, lead in all_leads.items():
                _vekst_check(orgnr, lead.get("antallAnsatte") or 0, history)
            for c in anchors:
                _vekst_check(c.get("orgnr"), c.get("antallAnsatte") or 0, history)
            _log(f"Baseline lagret for {len(all_leads)} leads + {len(anchors)} kunder. Vekst beregnes ved neste analyse.")
        else:
            _log("Sjekker selskap_i_vekst...")
            for orgnr, lead in all_leads.items():
                ansatte = lead.get("antallAnsatte") or 0
                vekst_pct, basis = _vekst_check(orgnr, ansatte, history)
                if vekst_pct:
                    lead["signals"].append({
                        "type": "selskap_i_vekst",
                        "anker_orgnr": None,
                        "anker_navn": "Vekst (intern måling)",
                        "detail": f"+{vekst_pct}% (fra {basis} til {ansatte} ansatte)",
                    })
                    lead["vekst_pct"] = vekst_pct
                    n_vekst += 1
            for c in anchors:
                _vekst_check(c.get("orgnr"), c.get("antallAnsatte") or 0, history)
            _log(f"Vekst-treff: {n_vekst} leads med ≥15% økning siden første måling.")
        save_json(ANSATTE_HISTORY, history)  # ÉN skriving i stedet for tusenvis

        # 4) Felles styre — parallelt
        _log("Sjekker felles styremedlemmer mot ALLE kunder...")
        roller_cache = load_json(ROLLER_CACHE, {})
        roller_lock = threading.Lock()
        save_counter_r = {"n": 0}

        def get_roller(orgnr):
            with roller_lock:
                if orgnr in roller_cache:
                    cached = roller_cache[orgnr]
                    if E.roller_rows_identity_ready(cached):
                        return cached
                    del roller_cache[orgnr]
            data = E.fetch_brreg_roller(orgnr)
            names = E.extract_roller_names(data) if "roller" in data else []
            with roller_lock:
                roller_cache[orgnr] = names
                save_counter_r["n"] += 1
                if save_counter_r["n"] % 100 == 0:
                    save_json(ROLLER_CACHE, roller_cache)
            return names

        # Hent roller for alle ankere parallelt
        _set_phase(f"Henter roller for {len(anchors)} kunder", total=len(anchors))
        anchor_roller = {}
        def _fetch_anchor_roller(anchor):
            anchor_roller[anchor["orgnr"]] = get_roller(anchor["orgnr"])
            _tick_safe()
        _parallel_run(anchors, _fetch_anchor_roller)
        save_json(ROLLER_CACHE, roller_cache)

        for L in all_leads.values():
            S.score_lead(L)
        scored_pre = sorted(all_leads.values(), key=lambda x: -x["score"])
        top_for_roller = scored_pre
        _set_phase(f"Henter roller for {len(top_for_roller)} kandidater", total=len(top_for_roller))
        _log(f"Henter roller for {len(top_for_roller)} kandidater parallelt...")

        anchor_navn_by_orgnr = {a["orgnr"]: a["navn"] for a in anchors}

        def _match_lead(c):
            c_roller = get_roller(c["orgnr"])
            felles_data = []
            for a_orgnr, a_roller in anchor_roller.items():
                if not a_roller:
                    continue
                personer = E.matched_board_persons(c_roller, a_roller)
                if not personer:
                    continue
                felles_data.append({"anker_navn": anchor_navn_by_orgnr.get(a_orgnr, a_orgnr),
                                    "anker_orgnr": a_orgnr, "personer": personer})
            if felles_data:
                c["felles_styre"] = felles_data
                for s in felles_data:
                    has_power = any(p["power"] for p in s["personer"])
                    sig_type = "felles_styreleder" if has_power else "felles_styremedlem"
                    if not any(x["type"] == sig_type and x["anker_orgnr"] == s["anker_orgnr"] for x in c["signals"]):
                        det = _board_overlap_signal_detail(
                            c.get("navn") or "",
                            s.get("anker_navn") or "",
                            s.get("personer") or [],
                        )
                        c["signals"].append({
                            "type": sig_type,
                            "anker_orgnr": s["anker_orgnr"],
                            "anker_navn": s["anker_navn"],
                            "detail": det,
                        })
            _tick_safe()

        _parallel_run(top_for_roller, _match_lead)
        save_json(ROLLER_CACHE, roller_cache)

        _log("Kobler leads mot kunders konsern (regnskap mor + kundetre)...")
        _set_phase("Konsern/eierskap (Brreg)", total=max(1, len(all_leads)))
        OWN.enrich_leads_with_customer_ownership(all_leads, customers, tick=_tick_safe)

        from lead_promote_whole_owned import promote_whole_owned_leads_from_pool

        n_whole = promote_whole_owned_leads_from_pool(
            all_leads, customers, log_fn=_log, rebuild_anchor_each_move=False
        )
        if n_whole:
            save_customers(customers)
            _log(f"Aksjeeierbok: {n_whole} heleid(e) lead(s) flyttet inn som datre i kundetrær.")

        # 5) Filter ut eksisterende kunder + tidligere promoterte
        # Alle org.nr i kundetrær (topp + underenheter + manuelle datre), ikke bare toppkunde.
        existing_orgnrs: set[str] = set()
        for c in customers.values():
            if not isinstance(c, dict):
                continue
            for _ent, o in iter_tree_company_nodes_with_org(c):
                if o:
                    existing_orgnrs.add(o)
        existing_names = set()
        for c in customers.values():
            n = (c.get("navn") or "").upper().strip()
            n = re.sub(r"\s+(AS|ASA|SA|HF|IKS)$", "", n)
            if n: existing_names.add(n)
        status = get_status()
        PROMOTED_STATUSES = {"eksisterende_kunde", "datterselskap", "vunnet", "konsern_kunde"}
        promoted_orgnrs = {
            norm_org(oid) for oid, st in status.items()
            if st in PROMOTED_STATUSES and norm_org(oid)
        }

        def is_existing(L):
            lo = norm_org(L.get("orgnr"))
            if lo and lo in existing_orgnrs:
                return True
            if lo and lo in promoted_orgnrs:
                return True
            n = (L["navn"] or "").upper().strip()
            n_clean = re.sub(r"\s+(AS|ASA|SA|HF|IKS)$", "", n)
            if n_clean in existing_names: return True
            for en in existing_names:
                if len(en) > 6 and (en in n_clean or n_clean in en):
                    return True
            return False

        leads = [L for L in all_leads.values() if not is_existing(L)]
        prev_leads_snapshot = load_json(LEADS_FILE, [], deep_copy=False)
        prev_lead_orgnrs = {
            GEO.normalize_lead_orgnr(L.get("orgnr")) for L in prev_leads_snapshot if L.get("orgnr")
        }
        new_geo_orgnrs = {
            GEO.normalize_lead_orgnr(L.get("orgnr"))
            for L in leads
            if L.get("orgnr") and GEO.normalize_lead_orgnr(L.get("orgnr")) not in prev_lead_orgnrs
        }

        # 6) Anker-info + scoring
        anchors_by_orgnr = {a["orgnr"]: a for a in anchors}
        for L in leads:
            ankr_orgs, ankr_navn = [], []
            for s in L.get("signals", []):
                ao = s.get("anker_orgnr")
                if ao and ao not in ankr_orgs:
                    ankr_orgs.append(ao)
                if s.get("anker_navn") and s["anker_navn"] not in ankr_navn:
                    ankr_navn.append(s["anker_navn"])
                if ao and ao in anchors_by_orgnr:
                    s["anker_ansatte"] = _effective_ansatte(anchors_by_orgnr[ao])
            L["anker_orgnrs"] = ankr_orgs
            L["anker_navn"] = ankr_navn
            S.score_lead(L)

        leads.sort(key=lambda x: (-x["score"], -(x.get("antallAnsatte") or 0)))
        save_json(LEADS_FILE, leads)
        _log(
            f"Lagret {len(leads)} leads med første scoring (filtrert liste). "
            "Neste steg oppdaterer koordinater/avstand der mulig og kjører scoring på nytt "
            "slik at geo-relaterte signaler telles med."
        )

        if skip_geocode:
            _set_phase(f"Oppdaterer geo uten Kartverket ({len(leads)} leads)", total=0)
            _log("Hopper over Kartverket — bruker geo-cache og lagrede koordinater for luftlinje.")
            GEO.hydrate_geo_distance_factors_for_leads(leads, customers)
            save_customers(customers)
            for L in leads:
                S.score_lead(L)
            leads.sort(key=lambda x: (-x["score"], -(x.get("antallAnsatte") or 0)))
            save_json(LEADS_FILE, leads)
            _log(
                f"Oppdatert {len(leads)} leads etter geo-hydrate fra cache og ny scoring "
                "(ingen Kartverket-kall)."
            )
        else:
            # Geokoding sist — da kan UI allerede hente listen; Kartverket-treff bruker geo_cache.json.
            leads_by_org = {str(L["orgnr"]): L for L in leads}
            n_cust_g = sum(1 for c in customers.values() if c.get("orgnr"))
            incremental_geo = bool(
                geo_only_new_leads and not full_rebuild and len(prev_lead_orgnrs) > 0
            )
            if incremental_geo:
                n_new = len(new_geo_orgnrs)
                _set_phase(
                    f"Geokoding — {n_new} nye leads (hopper {n_cust_g} kunder og "
                    f"{max(0, len(leads) - n_new)} eksisterende leads)",
                    total=n_new,
                )
                _log(
                    "Inkrementell geo: Kartverket kun for nylig oppdagede leads "
                    f"({n_new} org.nr). Eksisterende leads og kunder hoppes over — "
                    "bruk «Geo + score» for full Kartverket-runde."
                )
                nc, nl = GEO.run_geocode_and_attach(
                    customers,
                    leads_by_org,
                    tick=_tick_safe,
                    geocode_customers=False,
                    lead_orgnrs_to_geocode=new_geo_orgnrs,
                )
            else:
                _set_phase(
                    f"Geokoding ({n_cust_g} kunder + {len(leads)} leads) "
                    f"(fremdriftslinjen viser hele analysen, ikke bare geokoding)",
                    total=n_cust_g + len(leads),
                )
                _log("Geokoder besøksadresser (Kartverket/Geonorge) og kobler avstand på postnr-signaler...")
                nc, nl = GEO.run_geocode_and_attach(customers, leads_by_org, tick=_tick_safe)
            save_customers(customers)
            _log(f"Geokoding ferdig: {nc} kunder og {nl} leads med nye/oppdaterte koordinater.")
            for L in leads:
                S.score_lead(L)
            leads.sort(key=lambda x: (-x["score"], -(x.get("antallAnsatte") or 0)))
            save_json(LEADS_FILE, leads)
            _log(f"Oppdatert {len(leads)} leads etter geokoding, avstand og ny scoring.")

        history = load_json(ANALYSIS_LOG, [])
        history.append({
            "ran_at": datetime.now().isoformat(timespec="seconds"),
            "customers": len(customers),
            "leads_after_filter": len(leads),
            "vekst_count": n_vekst,
            "full_rebuild": full_rebuild,
            "skip_geocode": skip_geocode,
            "geo_only_new_leads": geo_only_new_leads,
        })
        save_json(ANALYSIS_LOG, history)
        _log("Analyse fullført.")
    finally:
        with _lock:
            _analysis["running"] = False
            _analysis["job"] = ""


def run_targeted_analysis(target_orgnr: str) -> bool:
    """Kjør målrettet analyse rundt EN ny anker — mye raskere enn full analyse.

    Returnerer ``True`` når jobben ble startet og fullført (eller hoppet over fordi anker mangler),
    ``False`` hvis en annen analyse-jobb allerede holdt låsen (prøv igjen senere).
    """
    with _lock:
        if _analysis["running"]:
            return False
        _analysis["running"] = True
        _analysis["log"] = []
        _analysis["current"] = 0
        _analysis["total"] = 0
        _analysis["phase"] = ""
        _analysis["job"] = "analyze"
    try:
        S._reload()
        to = norm_org(target_orgnr)
        if not to or len(to) != 9 or not to.isdigit():
            _log(f"Ugyldig org.nr for målrettet analyse: {target_orgnr!r}")
            return True
        customers = get_customers()
        target = next((c for c in customers.values() if norm_org(c.get("orgnr")) == to), None)
        if not target or not target.get("enriched"):
            _log(f"Ankerkunde {to} ikke beriket — hopper over.")
            return True

        _log(f"Målrettet analyse for {target['navn']}...")

        # 1) Discovery for ny anker
        cands = E.discover_leads_for_anchor(target)
        cache = load_json(DISCOVERY_CACHE, {})
        cache[to] = cands
        save_json(DISCOVERY_CACHE, cache)
        _log(f"Fant {len(cands)} kandidater rundt ny anker.")

        # 2) Re-aggreger fra full cache
        anchors = _all_discovery_anchors(customers)
        min_anchor = int(S.THRESHOLDS.get("min_anchor_ansatte", 0) or 0)
        if min_anchor > 0:
            anchors = [a for a in anchors if _effective_ansatte(a) >= min_anchor]
        active_orgnrs = {norm_org(a.get("orgnr")) for a in anchors if norm_org(a.get("orgnr"))}
        all_leads = {}
        for orgnr, cs in cache.items():
            if norm_org(orgnr) not in active_orgnrs:
                continue
            for c in cs:
                key = c["orgnr"]
                if key not in all_leads:
                    all_leads[key] = dict(c)
                    all_leads[key]["signals"] = list(c.get("signals", []))
                else:
                    existing = all_leads[key]["signals"]
                    for s in c.get("signals", []):
                        if not any(x["type"] == s["type"] and x["anker_orgnr"] == s["anker_orgnr"] for x in existing):
                            existing.append(s)

        prev_by_orgnr = {}
        for x in load_json(LEADS_FILE, [], deep_copy=False):
            ko = norm_org(x.get("orgnr"))
            if ko:
                prev_by_orgnr[ko] = x
        prev_lead_orgnrs_norm = {GEO.normalize_lead_orgnr(o) for o in prev_by_orgnr}
        for L in all_leads.values():
            _merge_preserved_lead_analysis(prev_by_orgnr.get(norm_org(L.get("orgnr"))), L)

        # 3) Roller for ny anker
        _log("Henter styre for ny anker...")
        roller_cache = load_json(ROLLER_CACHE, {})
        target_roller_data = E.fetch_brreg_roller(to)
        target_roller = E.extract_roller_names(target_roller_data) if "roller" in target_roller_data else []
        roller_cache[to] = target_roller
        save_json(ROLLER_CACHE, roller_cache)

        # 4) Match ny ankers roller mot eksisterende leads (kun cache hits)
        if target_roller:
            _log("Matcher mot eksisterende leads (kun cachet styre)...")
            n_match = 0
            for L in all_leads.values():
                lo = norm_org(L.get("orgnr"))
                if not lo or lo not in roller_cache:
                    continue
                lead_roller = roller_cache[lo]
                if not E.roller_rows_identity_ready(lead_roller):
                    continue
                personer = E.matched_board_persons(lead_roller, target_roller)
                if not personer:
                    continue
                best_is_power = any(p["power"] for p in personer)
                L.setdefault("felles_styre", [])
                L["felles_styre"] = [fs for fs in L["felles_styre"] if norm_org(fs.get("anker_orgnr")) != to]
                L["felles_styre"].append({
                    "anker_navn": target["navn"],
                    "anker_orgnr": to,
                    "personer": personer,
                })
                sig_type = "felles_styreleder" if best_is_power else "felles_styremedlem"
                L["signals"] = [s for s in L.get("signals", [])
                                if not (s["type"] in ("felles_styreleder", "felles_styremedlem")
                                        and norm_org(s.get("anker_orgnr")) == to)]
                det = _board_overlap_signal_detail(
                    L.get("navn") or "",
                    target.get("navn") or "",
                    personer,
                )
                L["signals"].append({
                    "type": sig_type,
                    "anker_orgnr": to,
                    "anker_navn": target["navn"],
                    "detail": det,
                })
                n_match += 1
            _log(f"Felles styre-treff: {n_match} leads.")

        _log("Kobler leads mot kunders konsern (regnskap mor + kundetre)...")
        _set_phase("Konsern/eierskap (Brreg)", total=max(1, len(all_leads)))
        OWN.enrich_leads_with_customer_ownership(all_leads, customers, tick=_tick_safe)

        # 5) Filter, score, save
        existing_orgnrs: set[str] = set()
        for c in customers.values():
            if not isinstance(c, dict):
                continue
            for _ent, o in iter_tree_company_nodes_with_org(c):
                if o:
                    existing_orgnrs.add(o)
        existing_names = set()
        for c in customers.values():
            n = (c.get("navn") or "").upper().strip()
            n = re.sub(r"\s+(AS|ASA|SA|HF|IKS)$", "", n)
            if n: existing_names.add(n)
        status = get_status()
        PROMOTED_STATUSES = {"eksisterende_kunde", "datterselskap", "vunnet", "konsern_kunde"}
        promoted_orgnrs = {
            norm_org(oid) for oid, st in status.items()
            if st in PROMOTED_STATUSES and norm_org(oid)
        }

        def is_existing(L):
            lo = norm_org(L.get("orgnr"))
            if lo and lo in existing_orgnrs:
                return True
            if lo and lo in promoted_orgnrs:
                return True
            n = (L["navn"] or "").upper().strip()
            n_clean = re.sub(r"\s+(AS|ASA|SA|HF|IKS)$", "", n)
            if n_clean in existing_names:
                return True
            for en in existing_names:
                if len(en) > 6 and (en in n_clean or n_clean in en):
                    return True
            return False

        leads = [L for L in all_leads.values() if not is_existing(L)]
        new_geo_orgnrs = {
            GEO.normalize_lead_orgnr(L.get("orgnr"))
            for L in leads
            if L.get("orgnr") and GEO.normalize_lead_orgnr(L.get("orgnr")) not in prev_lead_orgnrs_norm
        }
        _enrich_signals_with_anchor_size(leads)
        for L in leads:
            ankr_orgs, ankr_navn = [], []
            for s in L.get("signals", []):
                if s.get("anker_orgnr") and s["anker_orgnr"] not in ankr_orgs:
                    ankr_orgs.append(s["anker_orgnr"])
                if s.get("anker_navn") and s["anker_navn"] not in ankr_navn:
                    ankr_navn.append(s["anker_navn"])
            L["anker_orgnrs"] = ankr_orgs
            L["anker_navn"] = ankr_navn
            S.score_lead(L)

        leads.sort(key=lambda x: (-x["score"], -(x.get("antallAnsatte") or 0)))
        save_json(LEADS_FILE, leads)
        _log(f"Lagret {len(leads)} leads til visning (geokoding gjenstår).")

        _log("Geokoding og avstand for leads (siste steg)...")
        n_c_g = sum(1 for c in customers.values() if c.get("orgnr"))
        if not prev_lead_orgnrs_norm:
            _set_phase(
                f"Geokoding — {n_c_g} kunder + {len(leads)} leads",
                total=n_c_g + len(leads),
            )
            GEO.refresh_geo_scoring_for_leads(leads, customers, tick=_tick_safe)
        else:
            n_new = len(new_geo_orgnrs)
            _set_phase(
                f"Geokoding — {n_new} nye leads (hopper kunder og eksisterende leads)",
                total=n_new,
            )
            _log(
                f"Inkrementell geo etter målrettet analyse: Kartverket for {n_new} nye org.nr "
                "(resten uendret)."
            )
            GEO.refresh_geo_scoring_for_leads(
                leads,
                customers,
                tick=_tick_safe,
                geocode_customers=False,
                lead_orgnrs_to_geocode=new_geo_orgnrs,
            )
        save_customers(customers)
        _enrich_signals_with_anchor_size(leads)
        for L in leads:
            ankr_orgs, ankr_navn = [], []
            for s in L.get("signals", []):
                if s.get("anker_orgnr") and s["anker_orgnr"] not in ankr_orgs:
                    ankr_orgs.append(s["anker_orgnr"])
                if s.get("anker_navn") and s["anker_navn"] not in ankr_navn:
                    ankr_navn.append(s["anker_navn"])
            L["anker_orgnrs"] = ankr_orgs
            L["anker_navn"] = ankr_navn
            S.score_lead(L)

        leads.sort(key=lambda x: (-x["score"], -(x.get("antallAnsatte") or 0)))
        save_json(LEADS_FILE, leads)
        _log(f"Oppdatert {len(leads)} leads etter geokoding. Målrettet analyse ferdig.")
        return True
    finally:
        with _lock:
            _analysis["running"] = False
            _analysis["job"] = ""


def schedule_targeted_analysis_for_new_customer(orgnr: str) -> None:
    """Start bakgrunnstråd: kjør målrettet analyse for én toppkunde når analyselåsen er ledig.

    Brukes etter manuelt lagt til kunde eller lead → kunde. Prøver på nytt kort tid hvis full analyse
    eller geo-jobb nettopp kjører (samme ``_analysis``-lås).
    """
    o = norm_org(orgnr)
    if not o or len(o) != 9 or not o.isdigit():
        return

    def worker():
        import time as _time

        for _ in range(150):
            if run_targeted_analysis(o):
                return
            _time.sleep(0.45)

    threading.Thread(target=worker, daemon=True).start()


def run_geo_rescore_only() -> None:
    """Kartverket-geokoding for kunder + leads, avstandsfaktorer og lagring (egen jobb, deler analyse-status)."""
    with _lock:
        if _analysis["running"]:
            return
        _analysis["running"] = True
        _analysis["log"] = []
        _analysis["current"] = 0
        _analysis["total"] = 0
        _analysis["phase"] = "Starter geo..."
        _analysis["job"] = "geo"
    try:
        S._reload()
        customers = get_customers()
        leads = get_leads_readonly()
        n_cust = sum(1 for c in customers.values() if c.get("orgnr"))
        n_lead = len(leads)
        _log(f"Geo + score: geokoder {n_cust} kunder og {n_lead} leads (Kartverket, parallelt)...")
        _set_phase(f"Geokoding (Kartverket) — {n_cust} kunder + {n_lead} leads", total=n_cust + n_lead)
        GEO.refresh_geo_scoring_for_leads(leads, customers, tick=_tick_safe)
        _log("Geokoding ferdig — scorer og lagrer leads.")
        _set_phase("Scorer og lagrer leads", total=len(leads))
        GEO.finalize_leads_scoring_after_geo_refresh(leads, customers, tick=_tick_safe)
        _log(f"Ferdig: {len(leads)} leads oppdatert med geo og score.")
    finally:
        with _lock:
            _analysis["running"] = False
            _analysis["job"] = ""


# ===== Routes =====
@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    if _analysis["running"]:
        return jsonify({"running": True, "progress": _analysis["progress"]})
    body = request.get_json(force=True, silent=True) or {}
    full_rebuild = bool(body.get("full_rebuild", False))
    if full_rebuild:
        u = get_current_user()
        if not UDB.effective_permissions(u).get("full_reanalyze"):
            return jsonify({"error": "Du har ikke rettighet til full re-analyse."}), 403
    skip_geocode = bool(body.get("skip_geocode", False))
    geo_only_new_leads = bool(body.get("geo_only_new_leads", True))
    threading.Thread(
        target=lambda: run_analysis(
            full_rebuild=full_rebuild,
            skip_geocode=skip_geocode,
            geo_only_new_leads=geo_only_new_leads,
        ),
        daemon=True,
    ).start()
    return jsonify({
        "started": True,
        "full_rebuild": full_rebuild,
        "skip_geocode": skip_geocode,
        "geo_only_new_leads": geo_only_new_leads,
    })


@app.route("/api/geo-rescore", methods=["POST"])
def api_geo_rescore():
    if _analysis["running"]:
        return jsonify({"running": True, "progress": _analysis["progress"], "started": False})
    threading.Thread(target=run_geo_rescore_only, daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/jobs/overview")
def api_jobs_overview():
    """Samlet status for analyse/geo-jobb og import/refresh-jobb (to køer, ev. samtidig)."""
    return jsonify(get_jobs_overview())


@app.route("/api/analyze/status")
def api_analyze_status():
    with _lock:
        running = _analysis["running"]
        progress = _analysis.get("phase") or _analysis["progress"]
        current = int(_analysis.get("current") or 0)
        total = int(_analysis.get("total") or 0)
        log_tail = list(_analysis["log"][-30:])
        job = _analysis.get("job") or ""
    return jsonify({
        "running": running,
        "progress": progress,
        "current": current,
        "total": total,
        "log_tail": log_tail,
        "job": job,
    })
