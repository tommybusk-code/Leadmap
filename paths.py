"""Filstier og datakatalog for LeadMap (lokal lead-app)."""
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

CUSTOMERS_BACKUP = ROOT.parent / "kunder_backup.xlsx"

CUSTOMERS_FILE = DATA / "customers.json"
LEADS_FILE = DATA / "leads.json"
STATUS_FILE = DATA / "status.json"
NOTES_FILE = DATA / "notes.json"
ANALYSIS_LOG = DATA / "analysis_log.json"
DISCOVERY_CACHE = DATA / "discovery_cache.json"
ROLLER_CACHE = DATA / "roller_cache.json"
ANSATTE_HISTORY = DATA / "ansatte_history.json"
LEAD_RELATIONS = DATA / "lead_relations.json"
GEO_CACHE = DATA / "geo_cache.json"
OWNERSHIP_MOR_CACHE = DATA / "ownership_mor_cache.json"
# Snapshot av org.nr i alle kundetrær etter siste vellykkede «aksjonærinfo»-bulk (inkrementell neste gang).
AKSJONAERINFO_BULK_STATE = DATA / "aksjonaerinfo_bulk_state.json"
# Brukerstyring (Google OAuth + invitasjoner). Multi-tenant: nøkkel «default» inntil flere leietakere.
USERS_DB = DATA / "app_users.sqlite"
TENANTS_DIR = DATA / "tenants"


def tenant_user_settings_path(tenant_id: str, user_id: int) -> Path:
    d = TENANTS_DIR / tenant_id / "user_settings"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{user_id}.json"

# Aksjeeierbok (offisiell CSV) → bygg SQLite med aksjeeierbok_sqlite.py (kun 2024 i bruk nå).
AKSJEBOK_CSV_2024 = ROOT / "Aksjeeierbok" / "aksjeeiebok_2024.csv"
AKSJEBOK_DB_2024 = DATA / "aksjeeierbok_2024.sqlite"
