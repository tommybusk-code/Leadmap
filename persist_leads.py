"""Kun leads.json — utskilt fra persist.py (kunder/Excel/backup)."""
from json_store import load_json
from paths import LEADS_FILE


def get_leads():
    """Les leads med mtime-cache og deepcopy (isolert kopi for mutasjon som skal påvirke cache-konsistens)."""
    return load_json(LEADS_FILE, [])


def get_leads_readonly():
    """Les leads uten cache/deepcopy — fersk parse fra disk. Bruk ved request-lokal lesing/scoring som lagres tilbake."""
    return load_json(LEADS_FILE, [], deep_copy=False)
