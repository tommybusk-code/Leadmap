"""Brukeradmin: invitasjoner, liste, rettigheter (kun manage_users)."""
from __future__ import annotations

from flask import jsonify, request

import users_db as UDB
from authz import require_perm
from blueprints.auth_routes import get_current_user, public_base_url
from blueprints.web_api import web_api as bp


@bp.route("/admin/users", methods=["GET"])
@require_perm("manage_users")
def admin_list_users():
    u = get_current_user()
    return jsonify({"users": UDB.list_users_tenant(u["tenant_id"])})


@bp.route("/admin/users/<int:uid>", methods=["PATCH"])
@require_perm("manage_users")
def admin_patch_user(uid):
    u = get_current_user()
    body = request.get_json(force=True, silent=True) or {}
    target = UDB.get_user_by_id(uid)
    if not target or target["tenant_id"] != u["tenant_id"]:
        return jsonify({"error": "Bruker ikke funnet"}), 404
    if target["role"] == "owner":
        return jsonify({"error": "Kan ikke endre eierrettigheter her."}), 400
    out = UDB.update_member_permissions(
        uid,
        u["tenant_id"],
        can_add_customers=body.get("can_add_customers"),
        can_full_reanalyze=body.get("can_full_reanalyze"),
        can_delete_customers=body.get("can_delete_customers"),
        can_manage_users=body.get("can_manage_users"),
    )
    return jsonify({"user": out})


@bp.route("/admin/users/<int:uid>", methods=["DELETE"])
@require_perm("manage_users")
def admin_delete_user(uid):
    u = get_current_user()
    if uid == u["id"]:
        return jsonify({"error": "Kan ikke slette deg selv."}), 400
    ok = UDB.deactivate_user(uid, u["tenant_id"])
    if not ok:
        return jsonify({"error": "Kunne ikke deaktivere (eier eller ukjent id)."}), 400
    return jsonify({"ok": True})


@bp.route("/admin/invites", methods=["POST"])
@require_perm("manage_users")
def admin_create_invite():
    u = get_current_user()
    body = request.get_json(force=True, silent=True) or {}
    days = int(body.get("days_valid") or 14)
    days = max(1, min(90, days))
    email_lock = (body.get("email_lock") or "").strip() or None
    can_add = bool(body.get("can_add_customers", True))
    can_full = bool(body.get("can_full_reanalyze", False))
    token, meta = UDB.create_invite(
        u["id"],
        tenant_id=u["tenant_id"],
        days_valid=days,
        email_lock=email_lock,
        can_add_customers=can_add,
        can_full_reanalyze=can_full,
    )
    base = public_base_url()
    url = f"{base}/?invite={token}"
    return jsonify({"invite_url": url, **meta})
