"""Excel/CSV-import av kunder — bakgrunnsjobb."""
import io
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# pandas importeres lat inne i api_import — sparer ~800 ms ved oppstart.
from flask import jsonify, request

import enrichment as E
import users_db as UDB
from blueprints.auth_routes import get_current_user
from blueprints.web_api import web_api as bp
from persist import get_customers, save_customers
from state import _import_state


@bp.route("/import", methods=["POST"])
def api_import():
    import pandas as pd
    preview = request.args.get("preview", "false").lower() == "true"
    if not preview:
        u = get_current_user()
        if not UDB.effective_permissions(u).get("add"):
            return jsonify({"error": "Mangler rettighet til å importere / legge til kunder."}), 403
    if "file" not in request.files:
        return jsonify({"error": "Mangler fil"}), 400
    f = request.files["file"]
    name = f.filename.lower()
    try:
        if name.endswith(".csv"):
            raw = f.read()
            df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding="utf-8-sig")
        elif name.endswith(".xlsx") or name.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(f.read()))
        else:
            return jsonify({"error": "Støtter kun .xlsx, .xls eller .csv"}), 400
    except Exception as e:
        return jsonify({"error": f"Klarte ikke lese fil: {e}"}), 400

    cols = list(df.columns)
    mapping = {}
    NAVN_KEYWORDS = ("firmanavn", "selskapsnavn", "selskap", "bedrift",
                     "kundenavn", "kunde", "company", "name")
    for c in cols:
        lc = str(c).lower().strip()
        if "navn" not in mapping and (lc == "navn" or lc == "name"
                                      or any(k in lc for k in NAVN_KEYWORDS)):
            mapping["navn"] = c
        elif "orgnr" not in mapping and (lc.replace(".", "").replace(" ", "") in ("orgnr", "organisasjonsnummer")
                                          or ("org" in lc and "nr" in lc)):
            mapping["orgnr"] = c
        elif "abonnementer" not in mapping and ("abon" in lc or "abbo" in lc):
            mapping["abonnementer"] = c
        elif "postnummer" not in mapping and ("postn" in lc or "postkode" in lc or "zip" in lc):
            mapping["postnummer"] = c
        elif "sted" not in mapping and ("sted" in lc or "city" in lc or "by" == lc):
            mapping["sted"] = c

    def _to_int(v):
        if v is None or pd.isna(v):
            return None
        try:
            if isinstance(v, str):
                v = v.replace(",", ".").strip().split()[0]
            return int(float(v))
        except Exception:
            return None

    all_rows = []
    for _, r in df.iterrows():
        row = {"raw": {c: (None if pd.isna(r[c]) else r[c]) for c in cols}}
        if "navn" in mapping and pd.notna(r[mapping["navn"]]):
            row["navn"] = str(r[mapping["navn"]]).strip()
        if "orgnr" in mapping and pd.notna(r[mapping["orgnr"]]):
            row["orgnr"] = str(r[mapping["orgnr"]]).strip().split(".")[0]
        if "abonnementer" in mapping:
            ab = _to_int(r[mapping["abonnementer"]])
            if ab is not None:
                row["abonnementer"] = ab
        all_rows.append(row)

    if preview:
        return jsonify({"preview": True, "columns": cols, "mapping": mapping,
                        "rows": all_rows[:50], "total": len(df)})

    if "navn" not in mapping and "orgnr" not in mapping:
        return jsonify({
            "error": (f"Ingen navn- eller org.nr-kolonne gjenkjent. "
                      f"Kolonner i fila: {', '.join(map(str, cols))}. "
                      f"Endre kolonnenavnet til f.eks. 'Firmanavn' eller 'Org.nr' og prøv igjen.")
        }), 400

    if _import_state["running"]:
        return jsonify({"running": True, "error": "import allerede i gang — vent eller restart serveren"}), 409
    _import_state["running"] = True
    _import_state["job"] = "import"
    _import_state["log"] = []
    _import_state["result"] = None
    _import_state["progress"] = "Starter import..."
    _import_state["current"] = 0
    _import_state["total"] = len(all_rows)
    threading.Thread(target=lambda: _do_import(all_rows), daemon=True).start()
    return jsonify({"started": True, "total_rows": len(all_rows)})


def _imp_log(msg):
    print(msg, flush=True)
    _import_state["log"].append({"t": datetime.now().isoformat(timespec="seconds"), "msg": msg})
    _import_state["progress"] = msg


def _do_import(all_rows):
    try:
        customers = get_customers()
        added, skipped, duplicates, not_found = 0, 0, 0, 0
        total = len(all_rows)
        _imp_log(f"Behandler {total} rader (parallelle brreg-oppslag)...")

        def _lookup(row):
            navn = row.get("navn")
            orgnr = row.get("orgnr")
            if not navn and not orgnr:
                return None
            data = None
            if orgnr and re.fullmatch(r"\d{9}", orgnr):
                data = E.find_company_by_orgnr(orgnr)
            if not data and navn:
                data = E.find_company_by_name(navn)
            return data

        progress_lock = threading.Lock()
        progress = {"i": 0}
        looked_up = [None] * total

        def _process_row(idx):
            looked_up[idx] = _lookup(all_rows[idx])
            with progress_lock:
                progress["i"] += 1
                _import_state["current"] = progress["i"]
                if progress["i"] % 25 == 0:
                    _imp_log(f"  Brreg-oppslag {progress['i']}/{total}...")

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(as_completed([ex.submit(_process_row, i) for i in range(total)]))

        _imp_log("Aggregerer resultater...")
        for i, row in enumerate(all_rows):
            navn = row.get("navn")
            orgnr = row.get("orgnr")
            if not navn and not orgnr:
                skipped += 1
                continue
            data = looked_up[i]
            if data:
                existing_key = next((k for k, v in customers.items() if v.get("orgnr") == data["orgnr"]), None)
                if existing_key:
                    if row.get("abonnementer"):
                        customers[existing_key]["abonnementer"] = row.get("abonnementer", 0)
                    duplicates += 1
                else:
                    key = data["navn"]
                    if key in customers and customers[key].get("orgnr") != data["orgnr"]:
                        key = f"{data['navn']} ({data['orgnr']})"
                    customers[key] = {
                        **data, "enriched": True,
                        "abonnementer": row.get("abonnementer", 0),
                        "imported_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    added += 1
            elif navn:
                key = navn
                counter = 1
                while key in customers and customers[key].get("orgnr") != orgnr:
                    counter += 1
                    key = f"{navn} ({counter})"
                customers[key] = {
                    "navn": navn, "orgnr": orgnr,
                    "abonnementer": row.get("abonnementer", 0),
                    "enriched": False,
                    "imported_at": datetime.now().isoformat(timespec="seconds"),
                    "enrich_error": "ikke funnet i brreg ved import",
                }
                added += 1
                not_found += 1
            else:
                skipped += 1

        save_customers(customers)
        _import_state["result"] = {
            "imported": True, "added": added, "duplicates": duplicates,
            "not_found_in_brreg": not_found, "skipped_empty": skipped,
            "total_rows": total, "total_customers": len(customers),
        }
        _imp_log(f"✅ Ferdig: {added} lagt til, {duplicates} duplikater, {not_found} ikke funnet, {skipped} tomme.")
    finally:
        _import_state["running"] = False
        _import_state["job"] = ""


@bp.route("/import/status")
def api_import_status():
    log = _import_state.get("log")
    if not isinstance(log, list):
        log = []
    return jsonify({
        "running": _import_state["running"],
        "job": _import_state.get("job") or "",
        "progress": _import_state.get("progress") or "",
        "log_tail": log[-30:],
        "result": _import_state.get("result"),
        "current": int(_import_state.get("current") or 0),
        "total": int(_import_state.get("total") or 0),
    })
