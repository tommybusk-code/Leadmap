"""Kunde- og lead-filer: Excel-import, backup, get/save."""
import pandas as pd

from paths import (
    CUSTOMERS_BACKUP,
    CUSTOMERS_FILE,
    NOTES_FILE,
    STATUS_FILE,
)
from json_store import load_json, save_json

from persist_leads import get_leads, get_leads_readonly  # noqa: F401 — re-eksport for import fra persist


def get_customers():
    return load_json(CUSTOMERS_FILE, {})


def get_status():
    return load_json(STATUS_FILE, {})


def get_notes():
    return load_json(NOTES_FILE, {})


def _save_customers_backup(customers):
    if not customers:
        return
    rows = []
    for navn_key, c in customers.items():
        rows.append({
            "Navn": c.get("navn", navn_key),
            "Org.nr": c.get("orgnr"),
            "Postnummer": c.get("postnummer") or c.get("postnummer_orig"),
            "Poststed": c.get("poststed") or c.get("sted_orig"),
            "Kommune": c.get("kommune"),
            "Kommunenummer": c.get("kommunenummer"),
            "Adresse": c.get("adresse"),
            "NACE": c.get("naeringskode1"),
            "Bransje": c.get("nace_beskr"),
            "Ansatte": c.get("antallAnsatte") or 0,
            "Hjemmeside": c.get("hjemmeside"),
            "Telefon": c.get("telefon"),
            "E-post": c.get("epost"),
            "Abonnementer": c.get("abonnementer") or 0,
            "Beriket": "Ja" if c.get("enriched") else "Nei",
            "Lagt til manuelt": "Ja" if c.get("added_manually") else "",
            "Parent navn": c.get("parent_navn"),
            "Parent orgnr": c.get("parent_orgnr"),
            "Promotion mode": c.get("promotion_mode"),
        })
    try:
        df = pd.DataFrame(rows)
        df.to_excel(CUSTOMERS_BACKUP, index=False)
    except Exception as e:
        print(f"[backup] feilet: {e}")


def save_customers(customers):
    save_json(CUSTOMERS_FILE, customers)
    _save_customers_backup(customers)


def _load_from_backup_xlsx(xlsx_path):
    df = pd.read_excel(xlsx_path)
    out = {}

    def _str(v):
        if pd.isna(v):
            return None
        s = str(v).strip()
        return s if s else None

    def _int(v):
        if pd.isna(v):
            return 0
        try:
            return int(float(v))
        except Exception:
            return 0

    for _, row in df.iterrows():
        navn = _str(row.get("Navn")) or _str(row.get("Firmanavn"))
        if not navn:
            continue
        orgnr = _str(row.get("Org.nr")) or _str(row.get("Orgnr"))
        if orgnr and orgnr.endswith(".0"):
            orgnr = orgnr[:-2]
        postnr = _str(row.get("Postnummer"))
        if postnr and postnr.endswith(".0"):
            postnr = postnr[:-2]
        knr = _str(row.get("Kommunenummer"))
        if knr and knr.endswith(".0"):
            knr = knr[:-2]
        out[navn] = {
            "navn": navn, "orgnr": orgnr, "postnummer": postnr,
            "poststed": _str(row.get("Poststed")),
            "kommune": _str(row.get("Kommune")),
            "kommunenummer": knr,
            "adresse": _str(row.get("Adresse")),
            "naeringskode1": _str(row.get("NACE")),
            "nace_beskr": _str(row.get("Bransje")),
            "antallAnsatte": _int(row.get("Ansatte")),
            "hjemmeside": _str(row.get("Hjemmeside")),
            "telefon": _str(row.get("Telefon")),
            "epost": _str(row.get("E-post")),
            "abonnementer": _int(row.get("Abonnementer")),
            "enriched": (str(row.get("Beriket", "")).strip().lower() == "ja") and bool(orgnr),
            "added_manually": str(row.get("Lagt til manuelt", "")).strip().lower() == "ja",
            "parent_navn": _str(row.get("Parent navn")),
            "parent_orgnr": _str(row.get("Parent orgnr")),
            "promotion_mode": _str(row.get("Promotion mode")),
            "restored_from_backup": True,
        }
    return out


def import_xlsx_if_empty():
    """Les kunder fra JSON. Ved tomt datasett forsøk kun gjenoppretting fra appens backup-Excel."""
    cust = get_customers()
    if cust:
        return cust
    if CUSTOMERS_BACKUP.exists():
        try:
            cust = _load_from_backup_xlsx(str(CUSTOMERS_BACKUP))
            if cust:
                save_json(CUSTOMERS_FILE, cust)
                print(f"[init] Gjenopprettet {len(cust)} kunder fra backup ({CUSTOMERS_BACKUP.name}).")
                return cust
        except Exception as e:
            print(f"[init] Klarte ikke lese backup: {e}")
    return {}


def _effective_ansatte(c):
    """Effektivt antall ansatte (override, konsern, underenheter)."""
    override = c.get("antallAnsatte_override")
    if override is not None and override > 0:
        return override
    direct = c.get("antallAnsatte") or 0
    related = c.get("related") or {}

    konsern_total = related.get("konsern_ansatte") or 0
    if konsern_total > direct:
        return konsern_total

    seen = set()
    if c.get("orgnr"):
        seen.add(c["orgnr"])
    related_total = 0

    def _sum_manual_tree(items, acc):
        for r in items or []:
            ron = r.get("orgnr")
            if ron and ron in seen:
                continue
            if ron:
                seen.add(ron)
            acc[0] += r.get("antallAnsatte") or 0
            for ue in (r.get("related") or {}).get("underenheter") or []:
                uon = ue.get("orgnr")
                if uon and uon in seen:
                    continue
                if uon:
                    seen.add(uon)
                acc[0] += ue.get("antallAnsatte") or 0
                _sum_manual_tree(ue.get("manual_subsidiaries") or [], acc)
            _sum_manual_tree(r.get("manual_subsidiaries") or [], acc)

    for r in related.get("underenheter", []) or []:
        ron = r.get("orgnr")
        if ron and ron in seen:
            continue
        if ron:
            seen.add(ron)
        related_total += r.get("antallAnsatte") or 0
        acc = [0]
        _sum_manual_tree(r.get("manual_subsidiaries") or [], acc)
        related_total += acc[0]

    acc_root = [0]
    _sum_manual_tree(related.get("manual_subsidiaries") or [], acc_root)
    related_total += acc_root[0]

    return max(direct, direct + related_total) if related_total > 0 else direct
