"""Atomisk JSON les/skriv med mtime-basert cache."""
import copy
import json
import os
import tempfile
import threading
from pathlib import Path

_json_cache = {}
_json_cache_lock = threading.Lock()


def load_json(p, default, *, deep_copy=True):
    """Les JSON. deep_copy=True (standard): mtime-cache + deepcopy (trygg deling mellom kall).

    deep_copy=False: alltid fersk les fra disk, ingen cache-oppdatering — sparer deepcopy når data
    kun brukes i én request og evt. skrives tilbake via save_json (som oppdaterer cache).

    (Ikke kall parameteren «copy» — den overskygger ``import copy`` og knekker ``copy.deepcopy``.)
    """
    p = Path(p)
    if not p.exists():
        return default
    key = str(p)
    if not deep_copy:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default
    try:
        mtime = p.stat().st_mtime
    except Exception:
        mtime = None
    with _json_cache_lock:
        cached = _json_cache.get(key)
        if cached and mtime is not None and cached[0] == mtime:
            return copy.deepcopy(cached[1])
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default
    with _json_cache_lock:
        _json_cache[key] = (mtime, data)
    return copy.deepcopy(data)


def save_json(p, data):
    """Atomisk JSON-save. Invaliderer mtime-cache slik at neste load_json leser fra disk."""
    # Cache oppdateres ikke her: tidligere variant `deepcopy(data)` i write-pathen var dyr
    # for store filer (leads.json) og ble bortkastet ved write-only sekvenser (f.eks. periodiske
    # save under analyse/geo). Invalidering er trygt fordi disk er kilden — neste load_json
    # leser via json.loads (C) og repopulerer cachen.
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass
    with _json_cache_lock:
        _json_cache.pop(str(p), None)
