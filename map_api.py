"""map_api.py — /api/leads/map for kart-visning (Leaflet).

Registrert i app.py med:  import map_api  # noqa: F401
"""
from flask import jsonify
from state import app
from json_store import load_json
from paths import LEADS_FILE, CUSTOMERS_FILE, STATUS_FILE


@app.route("/api/leads/map")
def api_leads_map():
    """Returnerer alle leads + kunder med koordinater til Leaflet-kartet."""
    leads = load_json(LEADS_FILE, [])
    customers = load_json(CUSTOMERS_FILE, {})
    status_map = load_json(STATUS_FILE, {})

    if isinstance(leads, dict):
        leads = list(leads.values())

    lead_list = []
    for lead in leads:
        lat = lead.get("geo_lat")
        lon = lead.get("geo_lon")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue

        orgnr = str(lead.get("orgnr") or "")
        st = status_map.get(orgnr) or {}
        kommune = (
            lead.get("forretningsadresse_kommune")
            or lead.get("kommunenavn")
            or ""
        )
        signal_types = sorted({
            s.get("type")
            for s in (lead.get("signals") or [])
            if s.get("type")
        })
        lead_list.append({
            "orgnr": orgnr,
            "navn": lead.get("navn") or "",
            "score": round(float(lead.get("score") or 0), 1),
            "lat": lat,
            "lon": lon,
            "antallAnsatte": lead.get("antallAnsatte"),
            "kommune": kommune,
            "status": st.get("status") or "Ny",
            "geo_tier": lead.get("geo_tier") or "",
            "geo_detail": lead.get("geo_detail") or "",
            "geoscore": lead.get("geoscore"),
            "signals": signal_types,
        })

    anchor_list = []
    if isinstance(customers, dict):
        for orgnr, c in customers.items():
            if not isinstance(c, dict):
                continue
            lat = c.get("geo_lat")
            lon = c.get("geo_lon")
            if lat is None or lon is None:
                continue
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            anchor_list.append({
                "orgnr": str(orgnr),
                "navn": c.get("navn") or "",
                "lat": lat,
                "lon": lon,
                "adresse": c.get("adresse") or "",
            })

    return jsonify({"leads": lead_list, "anchors": anchor_list})
