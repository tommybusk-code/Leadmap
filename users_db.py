"""SQLite-lagring for brukere og invitasjonslenker (tenant_id = «default» inntil multi-tenant)."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from paths import USERS_DB

DEFAULT_TENANT = "default"


def _conn() -> sqlite3.Connection:
    USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(USERS_DB), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_users_db() -> None:
    with _conn() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                google_sub TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                name TEXT,
                role TEXT NOT NULL DEFAULT 'member',
                can_add_customers INTEGER NOT NULL DEFAULT 0,
                can_full_reanalyze INTEGER NOT NULL DEFAULT 0,
                can_delete_customers INTEGER NOT NULL DEFAULT 0,
                can_manage_users INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                last_login TEXT
            );
            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                email_lock TEXT,
                can_add_customers INTEGER NOT NULL DEFAULT 1,
                can_full_reanalyze INTEGER NOT NULL DEFAULT 0,
                created_by_user_id INTEGER,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            """
        )


def _row_user(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "tenant_id": r["tenant_id"],
        "google_sub": r["google_sub"],
        "email": r["email"],
        "name": r["name"],
        "role": r["role"],
        "can_add_customers": bool(r["can_add_customers"]),
        "can_full_reanalyze": bool(r["can_full_reanalyze"]),
        "can_delete_customers": bool(r["can_delete_customers"]),
        "can_manage_users": bool(r["can_manage_users"]),
        "active": bool(r["active"]),
        "created_at": r["created_at"],
        "last_login": r["last_login"],
    }


def effective_permissions(u: dict[str, Any] | None) -> dict[str, bool]:
    if not u or not u.get("active"):
        return {k: False for k in ("add", "full_reanalyze", "delete_customers", "manage_users")}
    if u.get("role") == "owner":
        return {
            "add": True,
            "full_reanalyze": True,
            "delete_customers": True,
            "manage_users": True,
        }
    return {
        "add": bool(u.get("can_add_customers")),
        "full_reanalyze": bool(u.get("can_full_reanalyze")),
        "delete_customers": bool(u.get("can_delete_customers")),
        "manage_users": bool(u.get("can_manage_users")),
    }


def count_users() -> int:
    with _conn() as db:
        row = db.execute("SELECT COUNT(*) AS c FROM users WHERE active = 1").fetchone()
        return int(row["c"]) if row else 0


def get_user_by_id(uid: int) -> dict[str, Any] | None:
    with _conn() as db:
        r = db.execute("SELECT * FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
        return _row_user(r) if r else None


def get_user_by_google_sub(sub: str) -> dict[str, Any] | None:
    with _conn() as db:
        r = db.execute(
            "SELECT * FROM users WHERE google_sub = ? AND active = 1", (sub,)
        ).fetchone()
        return _row_user(r) if r else None


def touch_login(uid: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as db:
        db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, uid))


def create_owner_user(
    google_sub: str, email: str, name: str | None, tenant_id: str = DEFAULT_TENANT
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as db:
        cur = db.execute(
            """INSERT INTO users (tenant_id, google_sub, email, name, role,
                can_add_customers, can_full_reanalyze, can_delete_customers, can_manage_users,
                active, created_at, last_login)
               VALUES (?, ?, ?, ?, 'owner', 1, 1, 1, 1, 1, ?, ?)""",
            (tenant_id, google_sub, email.lower(), name or "", now, now),
        )
        uid = int(cur.lastrowid)
    return get_user_by_id(uid)  # type: ignore


def create_member_user(
    google_sub: str,
    email: str,
    name: str | None,
    *,
    tenant_id: str = DEFAULT_TENANT,
    can_add_customers: bool = True,
    can_full_reanalyze: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as db:
        cur = db.execute(
            """INSERT INTO users (tenant_id, google_sub, email, name, role,
                can_add_customers, can_full_reanalyze, can_delete_customers, can_manage_users,
                active, created_at, last_login)
               VALUES (?, ?, ?, ?, 'member', ?, ?, 0, 0, 1, ?, ?)""",
            (
                tenant_id,
                google_sub,
                email.lower(),
                name or "",
                1 if can_add_customers else 0,
                1 if can_full_reanalyze else 0,
                now,
                now,
            ),
        )
        uid = int(cur.lastrowid)
    return get_user_by_id(uid)  # type: ignore


def list_users_tenant(tenant_id: str = DEFAULT_TENANT) -> list[dict[str, Any]]:
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM users WHERE tenant_id = ? ORDER BY active DESC, id ASC",
            (tenant_id,),
        ).fetchall()
    return [_row_user(r) for r in rows]


def deactivate_user(uid: int, tenant_id: str = DEFAULT_TENANT) -> bool:
    with _conn() as db:
        cur = db.execute(
            "UPDATE users SET active = 0 WHERE id = ? AND tenant_id = ? AND role != 'owner'",
            (uid, tenant_id),
        )
        return cur.rowcount > 0


def update_member_permissions(
    uid: int,
    tenant_id: str,
    *,
    can_add_customers: bool | None = None,
    can_full_reanalyze: bool | None = None,
    can_delete_customers: bool | None = None,
    can_manage_users: bool | None = None,
) -> dict[str, Any] | None:
    u = get_user_by_id(uid)
    if not u or u["tenant_id"] != tenant_id or u["role"] == "owner":
        return u
    sets = []
    vals: list[Any] = []
    if can_add_customers is not None:
        sets.append("can_add_customers = ?")
        vals.append(1 if can_add_customers else 0)
    if can_full_reanalyze is not None:
        sets.append("can_full_reanalyze = ?")
        vals.append(1 if can_full_reanalyze else 0)
    if can_delete_customers is not None:
        sets.append("can_delete_customers = ?")
        vals.append(1 if can_delete_customers else 0)
    if can_manage_users is not None:
        sets.append("can_manage_users = ?")
        vals.append(1 if can_manage_users else 0)
    if not sets:
        return u
    vals.extend([uid, tenant_id])
    with _conn() as db:
        db.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE id = ? AND tenant_id = ?",
            vals,
        )
    return get_user_by_id(uid)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_invite(
    created_by_user_id: int,
    *,
    tenant_id: str = DEFAULT_TENANT,
    days_valid: int = 14,
    email_lock: str | None = None,
    can_add_customers: bool = True,
    can_full_reanalyze: bool = False,
) -> tuple[str, dict[str, Any]]:
    token = secrets.token_urlsafe(32)
    th = _hash_token(token)
    exp = (datetime.now(timezone.utc) + timedelta(days=days_valid)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    el = email_lock.strip().lower() if email_lock else None
    with _conn() as db:
        cur = db.execute(
            """INSERT INTO invites (tenant_id, token_hash, expires_at, used_at, email_lock,
                can_add_customers, can_full_reanalyze, created_by_user_id, created_at)
               VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
            (
                tenant_id,
                th,
                exp,
                el,
                1 if can_add_customers else 0,
                1 if can_full_reanalyze else 0,
                created_by_user_id,
                now,
            ),
        )
        iid = int(cur.lastrowid)
    return token, {
        "id": iid,
        "expires_at": exp,
        "email_lock": el,
        "can_add_customers": can_add_customers,
        "can_full_reanalyze": can_full_reanalyze,
    }


def get_invite_by_token_plain(token: str) -> dict[str, Any] | None:
    th = _hash_token(token)
    with _conn() as db:
        r = db.execute("SELECT * FROM invites WHERE token_hash = ?", (th,)).fetchone()
    if not r:
        return None
    return {
        "id": r["id"],
        "tenant_id": r["tenant_id"],
        "expires_at": r["expires_at"],
        "used_at": r["used_at"],
        "email_lock": r["email_lock"],
        "can_add_customers": bool(r["can_add_customers"]),
        "can_full_reanalyze": bool(r["can_full_reanalyze"]),
    }


def consume_invite_and_create_user(
    token: str,
    google_sub: str,
    email: str,
    name: str | None,
) -> dict[str, Any] | None:
    """Oppretter medlem, eller reaktiverer tidligere fjernet bruker (samme Google-konto + tenant)."""
    inv = get_invite_by_token_plain(token)
    if not inv or inv.get("used_at"):
        return None
    exp = datetime.fromisoformat(inv["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > exp:
        return None
    el = inv.get("email_lock")
    if el and el != email.lower():
        return None
    th = _hash_token(token)
    now = datetime.now(timezone.utc).isoformat()
    tenant_id = inv["tenant_id"]
    can_add = 1 if inv["can_add_customers"] else 0
    can_full = 1 if inv["can_full_reanalyze"] else 0
    em = email.lower()
    nm = name or ""

    with _conn() as db:
        cur = db.execute(
            "UPDATE invites SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
            (now, th),
        )
        if cur.rowcount != 1:
            return None

        row = db.execute(
            "SELECT id, active, role FROM users WHERE google_sub = ? AND tenant_id = ?",
            (google_sub, tenant_id),
        ).fetchone()

        if row:
            uid = int(row["id"])
            if not row["active"] and row["role"] != "owner":
                db.execute(
                    """UPDATE users SET active = 1, email = ?, name = ?,
                       can_add_customers = ?, can_full_reanalyze = ?,
                       last_login = ?
                       WHERE id = ? AND tenant_id = ?""",
                    (em, nm, can_add, can_full, now, uid, tenant_id),
                )
            # Allerede aktiv medlem/eier: invitasjon er markert brukt; innlogging håndteres i callback.
        else:
            cur2 = db.execute(
                """INSERT INTO users (tenant_id, google_sub, email, name, role,
                    can_add_customers, can_full_reanalyze, can_delete_customers, can_manage_users,
                    active, created_at, last_login)
                   VALUES (?, ?, ?, ?, 'member', ?, ?, 0, 0, 1, ?, ?)""",
                (tenant_id, google_sub, em, nm, can_add, can_full, now, now),
            )
            uid = int(cur2.lastrowid)

    return get_user_by_id(uid)
