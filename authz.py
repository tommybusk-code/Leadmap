"""Dekoratorer for API-rettigheter (etter innlogging)."""
from __future__ import annotations

from functools import wraps

from flask import jsonify

import users_db as UDB
from blueprints.auth_routes import get_current_user


def require_perm(perm_key: str):
    """perm_key: add | full_reanalyze | delete_customers | manage_users"""

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            u = get_current_user()
            p = UDB.effective_permissions(u)
            if not p.get(perm_key):
                return jsonify({"error": "Mangler rettighet for denne handlingen."}), 403
            return fn(*args, **kwargs)

        return wrapped

    return decorator
