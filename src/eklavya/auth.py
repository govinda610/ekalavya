"""User accounts for the multi-user (served) deployment.

A small **global** SQLite database — ``$EKLAVYA_DATA_ROOT/users.db`` — holds the account
table, one row per user. It lives at the data-root level, NOT inside any per-user home,
so a user's own workspace can never read or write the account table.

Sessions are signed cookies (no server-side session table — see §0.5 of the deployment
plan); this module only owns *accounts* and *password hashing*. The signing/verifying of
the session cookie lives in ``middleware.py``.

The account model is always on: locally there's a single frictionless default account
(``ensure_local_user``), while a deployed install has one row per real user. Passwords are
hashed with argon2id (``argon2-cffi``).
"""

from __future__ import annotations

import sqlite3
import time
import uuid

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,       -- short slug/uuid; also the on-disk home dir name
    email         TEXT NOT NULL UNIQUE,   -- stored lowercased
    password_hash TEXT NOT NULL,          -- argon2id
    status        TEXT NOT NULL DEFAULT 'active',  -- active | pending (awaiting owner approval)
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    """Open (and create on first use) the shared users.db at the data-root level."""
    root = config.data_root()
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "users.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.executescript(_SCHEMA)
    # additive migration for accounts created before the approval gate existed
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "status" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    return conn


def _hasher():
    """The argon2 PasswordHasher (library defaults are sensible). Imported lazily so the
    dependency is only required in multi-user/served mode."""
    from argon2 import PasswordHasher

    return PasswordHasher()


def create_user(email: str, password: str, status: str = "active") -> str:
    """Create an account and return its uid. Raises ``ValueError`` if the email already
    exists or the password is too short (< 10 chars). The password is argon2-hashed; the
    plaintext is never stored or logged. ``status`` is 'active' normally, or 'pending' when
    the signup-approval gate is on (the owner approves before the account can log in)."""
    email = email.strip().lower()
    if not email or "@" not in email:
        raise ValueError("a valid email is required")
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    uid = uuid.uuid4().hex[:12]
    password_hash = _hasher().hash(password)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO users(id, email, password_hash, status) VALUES(?, ?, ?, ?)",
            (uid, email, password_hash, status),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"an account already exists for {email}") from exc
    finally:
        conn.close()
    return uid


def approve_user(email: str) -> bool:
    """Mark a pending account active. Returns True if a matching account was updated."""
    email = email.strip().lower()
    conn = _connect()
    try:
        cur = conn.execute("UPDATE users SET status='active' WHERE email=?", (email,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_pending() -> list[dict]:
    """Accounts awaiting approval (status != 'active'), oldest first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, email, created_at FROM users WHERE status != 'active' ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def verify_login(email: str, password: str) -> str | None:
    """Return the uid if the email+password match, else None. Constant-time verify is
    handled by argon2; a missing user still runs a dummy verify to avoid leaking (via
    timing) whether the email exists."""
    email = email.strip().lower()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()
    ph = _hasher()
    if row is None:
        # dummy verify so a nonexistent email costs about the same as a wrong password
        try:
            ph.verify("$argon2id$v=19$m=65536,t=3,p=4$AAAAAAAAAAAAAAAAAAAAAA$"
                      "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", password)
        except Exception:
            pass
        return None
    try:
        ph.verify(row["password_hash"], password)
    except Exception:
        return None
    return row["id"]


def get_user_by_email(email: str) -> dict | None:
    """Return {id, email, status, created_at} for an email (lowercased), or None."""
    email = email.strip().lower()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, email, status, created_at FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def resolve_user_ref(ref: str) -> str | None:
    """Resolve a user reference (an email OR a uid) to a uid, or None if no such account.
    Used by ``EKLAVYA_USER`` / the CLI ``--user`` flag."""
    ref = ref.strip()
    if not ref:
        return None
    if "@" in ref:
        u = get_user_by_email(ref)
        return u["id"] if u else None
    return ref if get_user(ref) else None


def ensure_local_user() -> str:
    """Return a frictionless local account's uid, creating one on first run.

    For a solo local self-host we don't want to force email+password on every command. If an
    account already exists we return it (the sole one; or raise if it's ambiguous — the
    caller handles that upstream). Otherwise we mint a low-ceremony local account with a
    synthesised local email and a random password (never shown; login is via the stored
    default, not a form). Deployed installs never call this — they use full signup/login.
    """
    users = list_users()
    if len(users) == 1:
        return users[0]["id"]
    if len(users) > 1:
        raise ValueError("multiple accounts exist — designate one with `eklavya login`.")
    password = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars, never surfaced
    return create_user("local@eklavya.local", password, status="active")


def get_user(uid: str) -> dict | None:
    """Return {id, email, status, created_at} for a uid, or None."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, email, status, created_at FROM users WHERE id = ?", (uid,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_users() -> list[dict]:
    """All accounts (email + created_at), newest last — for the ``listusers`` CLI."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, email, status, created_at FROM users ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# --- login throttle (in-memory, no dependency) -----------------------------
# A deliberately tiny lockout keyed by (email, client-ip): after MAX_FAILS failed logins
# inside WINDOW seconds, further attempts are refused for the rest of the window. It is a
# plain dict of timestamps — it RESETS ON RESTART and is per-process, which is acceptable
# for the small private (2-user) deployment this ships for. The one approved deviation
# from "no rate-limiting" (§0.5), scoped to the public-facing login form only.

MAX_FAILS = 5
WINDOW = 15 * 60  # seconds

_fails: dict[tuple[str, str], list[float]] = {}


def _recent(key: tuple[str, str], now: float) -> list[float]:
    return [t for t in _fails.get(key, []) if now - t < WINDOW]


def is_locked(email: str, ip: str) -> bool:
    """True if this (email, ip) has hit the failed-attempt ceiling within the window."""
    key = (email.strip().lower(), ip or "")
    return len(_recent(key, time.time())) >= MAX_FAILS


def record_failure(email: str, ip: str) -> None:
    """Note a failed login for throttling."""
    now = time.time()
    key = (email.strip().lower(), ip or "")
    _fails[key] = _recent(key, now) + [now]


def reset_failures(email: str, ip: str) -> None:
    """Clear the failed-attempt counter after a successful login."""
    _fails.pop((email.strip().lower(), ip or ""), None)
