"""Google OAuth, session og offentlige auth-endepunkter."""
from __future__ import annotations

import os
from urllib.parse import quote

try:
    from authlib.integrations.flask_client import OAuth as _OAuthClient
except ImportError:
    _OAuthClient = None

from flask import Blueprint, jsonify, redirect, render_template, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import users_db as UDB
from users_db import DEFAULT_TENANT

auth_bp = Blueprint("auth_api", __name__, url_prefix="/api/auth")


class _OAuthStub:
    google = None

    def init_app(self, app):
        pass

    def register(self, **kwargs):
        pass


oauth = _OAuthClient() if _OAuthClient else _OAuthStub()


def oauth_google_configured() -> bool:
    """True når Google-klienten er registrert hos Authlib (tilgang til .google kan ellers kaste)."""
    try:
        return bool(oauth.google)
    except Exception:
        return False


def public_base_url() -> str:
    # LEADMAP_PUBLIC_URL: custom domain or explicit base. RENDER_EXTERNAL_URL: set by Render for *.onrender.com.
    base = (
        (os.environ.get("LEADMAP_PUBLIC_URL") or "").strip()
        or (os.environ.get("RENDER_EXTERNAL_URL") or "").strip()
        or (request.host_url or "").strip()
    )
    return base.rstrip("/")


def _state_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="leadmap-oauth-state")


def encode_oauth_state(secret: str, invite_token: str | None) -> str:
    return _state_serializer(secret).dumps({"inv": (invite_token or "").strip()})


def decode_oauth_state(secret: str, raw: str | None, max_age: int = 900) -> dict:
    if not raw:
        return {}
    try:
        return _state_serializer(secret).loads(raw, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return {}


def init_oauth(app) -> None:
    cid_raw = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    csec_raw = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    cid = (cid_raw or "").strip()
    csec = (csec_raw or "").strip()
    # Startup-diagnose: synlig i Render-logs uten å lekke verdier
    print(
        f"[oauth-init] authlib_available={bool(_OAuthClient)} "
        f"client_id_present={cid_raw is not None} client_id_len={len(cid)} "
        f"client_secret_present={csec_raw is not None} client_secret_len={len(csec)} "
        f"render_service={os.environ.get('RENDER_SERVICE_NAME') or '-'} "
        f"render_external_url={os.environ.get('RENDER_EXTERNAL_URL') or '-'}",
        flush=True,
    )
    if not _OAuthClient:
        print("[oauth-init] authlib not installed — skipping", flush=True)
        return
    if not cid or not csec:
        print("[oauth-init] missing client_id or client_secret — OAuth disabled", flush=True)
        return
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=cid,
        client_secret=csec,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    print("[oauth-init] Google OAuth registered OK", flush=True)


def init_auth(app) -> None:
    secret = os.environ.get("FLASK_SECRET_KEY") or "dev-only-insecure-change-FLASK_SECRET_KEY"
    app.secret_key = secret
    UDB.init_users_db()
    init_oauth(app)


def session_user_id() -> int | None:
    try:
        v = session.get("uid")
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def auth_relaxed_mode() -> bool:
    """Sant når innlogging ikke håndheves: LEADMAP_AUTH_DISABLED=1 eller OAuth ikke konfigurert ennå."""
    if (os.environ.get("LEADMAP_AUTH_DISABLED") or "").strip() == "1":
        return True
    return not oauth_google_configured()


def get_current_user():
    if auth_relaxed_mode():
        return {
            "id": 0,
            "tenant_id": DEFAULT_TENANT,
            "google_sub": "__dev__",
            "email": "dev@local",
            "name": "Utvikling (ingen OAuth)",
            "role": "owner",
            "can_add_customers": True,
            "can_full_reanalyze": True,
            "can_delete_customers": True,
            "can_manage_users": True,
            "active": True,
            "created_at": None,
            "last_login": None,
        }
    uid = session_user_id()
    if uid is None:
        return None
    return UDB.get_user_by_id(uid)


@auth_bp.route("/me", methods=["GET"])
def api_auth_me():
    u = get_current_user()
    relaxed = auth_relaxed_mode()
    user_out = None
    if u:
        user_out = {
            "id": u["id"],
            "email": u["email"],
            "name": u["name"],
            "role": u["role"],
            "tenant_id": u["tenant_id"],
            "permissions": UDB.effective_permissions(u),
        }
    cid_raw = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    csec_raw = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    return jsonify(
        {
            "authenticated": u is not None,
            "user": user_out,
            "oauth_configured": oauth_google_configured(),
            "auth_relaxed": relaxed,
            "diagnostic": {
                "authlib_available": bool(_OAuthClient),
                "client_id_present": cid_raw is not None,
                "client_id_len": len((cid_raw or "").strip()),
                "client_secret_present": csec_raw is not None,
                "client_secret_len": len((csec_raw or "").strip()),
                "render_service_name": os.environ.get("RENDER_SERVICE_NAME") or None,
                "render_service_id": os.environ.get("RENDER_SERVICE_ID") or None,
                "render_external_url": os.environ.get("RENDER_EXTERNAL_URL") or None,
                "public_base_url": (os.environ.get("LEADMAP_PUBLIC_URL") or "").strip()
                or (os.environ.get("RENDER_EXTERNAL_URL") or "").strip()
                or None,
                "auth_disabled_flag": (os.environ.get("LEADMAP_AUTH_DISABLED") or "").strip() == "1",
            },
        }
    )


@auth_bp.route("/google/start")
def auth_google_start():
    from flask import current_app

    if not oauth_google_configured():
        return jsonify(
            {
                "error": "Google OAuth er ikke konfigurert (GOOGLE_OAUTH_CLIENT_ID/SECRET).",
            }
        ), 503
    invite = (request.args.get("invite") or "").strip()
    st = encode_oauth_state(current_app.secret_key, invite or None)
    if invite:
        session["pending_invite"] = invite
    redirect_uri = public_base_url() + "/api/auth/google/callback"
    return oauth.google.authorize_redirect(redirect_uri, state=st, prompt="select_account")


@auth_bp.route("/google/callback")
def auth_google_callback():
    from flask import current_app

    if not oauth_google_configured():
        return redirect("/?auth_error=oauth_not_configured")
    try:
        token = oauth.google.authorize_access_token()
    except Exception as ex:
        return redirect("/?auth_error=" + quote(str(ex)[:200]))

    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = oauth.google.parse_id_token(token, nonce=None)
    if not userinfo:
        return redirect("/?auth_error=no_userinfo")

    sub = str(userinfo.get("sub") or "")
    email = (userinfo.get("email") or "").strip().lower()
    name = userinfo.get("name") or ""
    if not sub or not email:
        return redirect("/?auth_error=missing_claims")

    st = decode_oauth_state(current_app.secret_key, request.args.get("state"))
    invite_plain = (st.get("inv") or "").strip() or (session.pop("pending_invite", None) or "").strip()

    bootstrap_email = (os.environ.get("LEADMAP_BOOTSTRAP_OWNER_EMAIL") or "").strip().lower()

    existing = UDB.get_user_by_google_sub(sub)
    if existing:
        session["uid"] = existing["id"]
        UDB.touch_login(existing["id"])
        return redirect("/")

    if UDB.count_users() == 0:
        if bootstrap_email and email != bootstrap_email:
            return redirect("/?auth_error=not_bootstrap_email")
        u = UDB.create_owner_user(sub, email, name, tenant_id=DEFAULT_TENANT)
        session["uid"] = u["id"]
        return redirect("/")

    if invite_plain:
        u = UDB.consume_invite_and_create_user(invite_plain, sub, email, name)
        if not u:
            return redirect("/?auth_error=invite_invalid")
        session["uid"] = u["id"]
        UDB.touch_login(u["id"])
        return redirect("/")

    return redirect("/?auth_error=no_access")


@auth_bp.route("/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


def register_auth(app) -> None:
    init_auth(app)
    app.register_blueprint(auth_bp)

    @app.route("/login")
    def login_page():
        invite = (request.args.get("invite") or "").strip()
        if auth_relaxed_mode():
            return render_template(
                "login.html",
                relaxed=True,
                oauth_ok=oauth_google_configured(),
                invite=invite,
            )
        if get_current_user() is not None:
            return redirect("/")
        return render_template(
            "login.html",
            relaxed=False,
            oauth_ok=oauth_google_configured(),
            invite=invite,
        )

    @app.before_request
    def _require_api_login():
        if auth_relaxed_mode():
            return None
        path = request.path or ""
        if not path.startswith("/api/"):
            return None
        exempt_prefixes = (
            "/api/auth/me",
            "/api/auth/google/start",
            "/api/auth/google/callback",
        )
        if any(path.startswith(p) for p in exempt_prefixes):
            return None
        if get_current_user() is None:
            return jsonify({"error": "Innlogging påkrevd.", "authenticated": False}), 401
        return None
