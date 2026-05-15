"""Per-bruker scoring-innstillinger (vekter + terskler), med fallback til systemfil data/settings.json."""
from __future__ import annotations

import json
from typing import Any

import scoring as S
from paths import tenant_user_settings_path


def load_merged_user_settings(user_id: int, tenant_id: str = "default") -> dict[str, Any]:
    """Full «weights» + «thresholds» slått sammen med systemstandard (data/settings.json)."""
    if user_id == 0:
        return S.load_settings()
    base = S.load_settings()
    path = tenant_user_settings_path(tenant_id, user_id)
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return base
    return {
        "weights": {**base["weights"], **(raw.get("weights") or {})},
        "thresholds": {**base["thresholds"], **(raw.get("thresholds") or {})},
    }


def save_user_scoring_profile(
    user_id: int,
    tenant_id: str,
    weights: dict | None,
    thresholds: dict | None,
) -> dict[str, Any]:
    """Oppdater brukerfil; tom dict = ingen endring på den delen."""
    if user_id == 0:
        merged = S.load_settings()
        if weights is not None:
            merged["weights"].update(weights)
        if thresholds is not None:
            merged["thresholds"].update(thresholds)
        return merged
    merged = load_merged_user_settings(user_id, tenant_id)
    if weights is not None:
        merged["weights"].update(weights)
    if thresholds is not None:
        merged["thresholds"].update(thresholds)
    path = tenant_user_settings_path(tenant_id, user_id)
    path.write_text(
        json.dumps(
            {"weights": merged["weights"], "thresholds": merged["thresholds"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return merged
