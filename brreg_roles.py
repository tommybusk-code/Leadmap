"""Roller fra Brreg enhetsregisteret."""
import requests

from brreg_api import BRREG, HEADERS, TIMEOUT

HIGH_POWER_ROLES = (
    "Styrets leder", "Daglig leder", "Administrerende direktør",
    "Nestleder", "Innehaver", "Forretningsfører",
)


def roller_identity_match(a: dict, b: dict) -> bool:
    """True når to roller-rader sannsynligvis er samme entitet (ikke bare homonym navn).

    Brreg gir fødselsdato for fysiske personer. Mangler den på begge sider, antas juridisk
    person / eldre data — da matches kun på navn (som før). Mangler den på én side, avvises:
    unngår «OLE OLSEN» vs annen OLE OLSEN der den ene raden mangler dato.
    """
    d1 = (a.get("fodselsdato") or "").strip()
    d2 = (b.get("fodselsdato") or "").strip()
    if d1 and d2:
        return d1 == d2
    if not d1 and not d2:
        return True
    return False


def roller_rows_identity_ready(rows: list) -> bool:
    """False hvis cachet roller mangler fodselsdato-felt (må hentes på nytt)."""
    if not rows:
        return True
    return all(isinstance(r, dict) and "fodselsdato" in r for r in rows)


def fetch_brreg_roller(orgnr: str) -> dict:
    if not orgnr:
        return {}
    url = f"{BRREG}/{orgnr}/roller"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": f"brreg roller: {e}"[:140]}

    out = {"roller_kilde": "brreg", "roller_url": url, "roller": []}
    for grp in data.get("rollegrupper") or []:
        rtype = (grp.get("type") or {}).get("beskrivelse", "")
        for r in grp.get("roller", []):
            if r.get("fratraadt"):
                continue
            person = r.get("person") or {}
            navn_obj = person.get("navn") or {}
            full = f"{navn_obj.get('fornavn','')} {navn_obj.get('etternavn','')}".strip()
            if not full:
                v = r.get("virksomhet") or {}
                full = (v.get("navn") or [None])[0] if v else None
                if not full:
                    continue
            rolle_type = (r.get("type") or {}).get("beskrivelse", "")
            fd = (person.get("fodselsdato") or "").strip() if person else ""
            out["roller"].append({
                "navn": full,
                "rolle": rolle_type,
                "gruppe": rtype,
                "fodselsdato": fd or None,
            })
    return out


def extract_roller_names(roller_data: dict) -> list:
    out = []
    seen = set()
    for r in (roller_data.get("roller") or []):
        navn = (r.get("navn") or "").upper().strip()
        rolle = r.get("rolle") or ""
        fd_raw = r.get("fodselsdato")
        fd = (fd_raw or "").strip() if fd_raw else ""
        if not navn or len(navn) < 4:
            continue
        is_power = any(hp.upper() in rolle.upper() for hp in HIGH_POWER_ROLES)
        dedupe_key = (navn, fd)
        if dedupe_key in seen:
            for x in out:
                xfd = (x.get("fodselsdato") or "").strip()
                if x["name"] == navn and xfd == fd and is_power and not x["power"]:
                    x["power"] = True
                    x["rolle"] = rolle
            continue
        seen.add(dedupe_key)
        out.append({"name": navn, "rolle": rolle, "power": is_power, "fodselsdato": fd or None})
    return out


def matched_board_persons(lead_roller: list, anchor_roller: list) -> list:
    """Kryss-match styre-rader mellom lead og anker med samme navn og gyldig identitet (fødselsdato)."""
    personer = []
    for a_r in anchor_roller:
        for c_r in lead_roller:
            if c_r["name"] != a_r["name"]:
                continue
            if not roller_identity_match(c_r, a_r):
                continue
            is_power = c_r["power"] or a_r["power"]
            personer.append({
                "navn": c_r["name"].title(),
                "rolle_anker": a_r["rolle"],
                "rolle_lead": c_r["rolle"],
                "power": is_power,
            })
    return personer
