"""Authentication + session → user isolation (multi-user Phase 2).

Fully offline. Every test forces multi-user mode with a throwaway EKLAVYA_DATA_ROOT and a
test signing secret, so the real ~/.eklavya and the user's real accounts are never touched.
Proves: accounts + argon2 hashing, signed-cookie login/logout, that a logged-in request's
context resolves to that user's home (Phase-1 isolation), cross-user thread access is 404,
the login throttle locks after N failures, and that single-user mode bypasses all of it.
"""

import os
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def mu(monkeypatch):
    """Multi-user mode with an isolated data root + test secret. Yields (data_root)."""
    from eklavya import auth, config

    root = Path(tempfile.mkdtemp(prefix="eklavya-auth-"))
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(root))
    monkeypatch.setenv("EKLAVYA_SECRET_KEY", "test-secret-please-ignore-0123456789abcdef")
    monkeypatch.setenv("EKLAVYA_INSECURE_COOKIES", "1")  # TestClient uses http, not https
    monkeypatch.setattr(config, "MULTIUSER", True)
    auth._fails.clear()  # throttle is process-global; start clean
    yield root
    auth._fails.clear()


def _app():
    from eklavya.webapp import create_app

    return create_app()


# --- account store + argon2 -------------------------------------------------

def test_create_and_verify_user(mu):
    from eklavya import auth

    uid = auth.create_user("Alice@Example.com", "correcthorsebattery")
    assert uid and isinstance(uid, str)
    # email is stored lowercased; verify round-trips
    assert auth.verify_login("alice@example.com", "correcthorsebattery") == uid
    assert auth.verify_login("alice@example.com", "wrongpassword!") is None
    u = auth.get_user(uid)
    assert u["email"] == "alice@example.com"


def test_password_is_hashed_not_plaintext(mu):
    from eklavya import auth

    auth.create_user("bob@example.com", "hunter2hunter2")
    conn = auth._connect()
    try:
        row = conn.execute("SELECT password_hash FROM users WHERE email='bob@example.com'").fetchone()
    finally:
        conn.close()
    assert "hunter2hunter2" not in row["password_hash"]
    assert row["password_hash"].startswith("$argon2")


def test_duplicate_email_rejected(mu):
    from eklavya import auth

    auth.create_user("dup@example.com", "passwordlong1")
    with pytest.raises(ValueError):
        auth.create_user("dup@example.com", "anotherpassword")


def test_short_password_rejected(mu):
    from eklavya import auth

    with pytest.raises(ValueError):
        auth.create_user("short@example.com", "tiny")


def test_users_db_lives_outside_any_user_home(mu):
    from eklavya import auth, config

    uid = auth.create_user("iso@example.com", "passwordlong1")
    assert (config.data_root() / "users.db").exists()
    # not inside the user's per-user home
    assert not (config.user_home(uid) / "users.db").exists()


# --- login / session / logout ----------------------------------------------

def test_login_sets_httponly_session_and_redirects(mu):
    from eklavya import auth

    auth.create_user("carol@example.com", "passwordlong1")
    c = TestClient(_app(), follow_redirects=False)
    r = c.post("/login", data={"email": "carol@example.com", "password": "passwordlong1"})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    cookie = r.headers.get("set-cookie", "")
    assert "eklavya_session=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=strict" in cookie.lower()


def test_bad_password_does_not_authenticate(mu):
    from eklavya import auth

    auth.create_user("dave@example.com", "passwordlong1")
    c = TestClient(_app(), follow_redirects=False)
    r = c.post("/login", data={"email": "dave@example.com", "password": "nope-nope-nope"})
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    assert "set-cookie" not in {k.lower() for k in r.headers}


def test_unauthenticated_app_route_redirects_to_login(mu):
    c = TestClient(_app(), follow_redirects=False)
    r = c.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_unauthenticated_api_route_returns_401(mu):
    c = TestClient(_app(), follow_redirects=False)
    assert c.get("/api/stats").status_code == 401


def test_login_form_is_reachable_without_session(mu):
    c = TestClient(_app(), follow_redirects=False)
    r = c.get("/login")
    assert r.status_code == 200
    assert "Sign in" in r.text


def test_logout_clears_session(mu):
    from eklavya import auth

    auth.create_user("erin@example.com", "passwordlong1")
    c = TestClient(_app(), follow_redirects=False)
    c.post("/login", data={"email": "erin@example.com", "password": "passwordlong1"})
    assert c.get("/api/stats").status_code == 200  # cookie now on the client
    c.post("/logout")
    # after logout the cookie is cleared → back to 401
    assert c.get("/api/stats").status_code == 401


# --- session → per-user isolation (the join point) -------------------------

def test_logged_in_request_resolves_that_users_home(mu):
    from eklavya import auth, config

    uid = auth.create_user("frank@example.com", "passwordlong1")
    c = TestClient(_app(), follow_redirects=False)
    c.post("/login", data={"email": "frank@example.com", "password": "passwordlong1"})
    # the login flow initialised the user's per-user db under their home
    assert (config.user_home(uid) / "workspace" / "eklavya.db").exists()
    # and an authenticated api call succeeds against that home
    assert c.get("/api/stats").status_code == 200


def test_user_a_cannot_read_user_b_thread(mu):
    """Through the authenticated web path, a thread A doesn't own is 404, not readable.

    Per-user DBs already mean A's queries can't reach B's rows; the explicit ownership
    guard (`_require_owner`) is the defense-in-depth layer for a foreign-owned row that
    *does* resolve in the current DB (a future shared/consolidated table). We seed exactly
    that — a row stamped with uid-b sitting in A's own db — and prove A gets a 404.
    """
    from eklavya import auth, config
    from eklavya.config import _current_home
    from eklavya.db import connect

    uid_a = auth.create_user("a@example.com", "passwordlong1")
    uid_b = auth.create_user("b@example.com", "passwordlong1")

    c = TestClient(_app(), follow_redirects=False)
    c.post("/login", data={"email": "a@example.com", "password": "passwordlong1"})  # inits A's db

    # plant a row owned by B inside A's own db (the consolidated-table threat model)
    token = _current_home.set(config.user_home(uid_a))
    try:
        conn = connect()
        conn.execute("INSERT INTO chats(thread_id, user_id) VALUES('theirs', ?)", (uid_b,))
        conn.commit()
        conn.close()
    finally:
        _current_home.reset(token)

    # A queries it over the authenticated web path → 404 (not 403, not the content)
    assert c.get("/api/chats/theirs").status_code == 404
    assert c.patch("/api/chats/theirs", json={"title": "hijack"}).status_code == 404


# --- login throttle ---------------------------------------------------------

def test_throttle_locks_after_max_failures(mu):
    from eklavya import auth

    auth.create_user("grace@example.com", "passwordlong1")
    c = TestClient(_app(), follow_redirects=False)
    for _ in range(auth.MAX_FAILS):
        r = c.post("/login", data={"email": "grace@example.com", "password": "wrong-wrong-1"})
        assert "Invalid" in r.headers["location"]
    # next attempt (even the CORRECT password) is refused for the window
    r = c.post("/login", data={"email": "grace@example.com", "password": "passwordlong1"})
    assert "Too+many+attempts" in r.headers["location"]
    assert "set-cookie" not in {k.lower() for k in r.headers}


def test_throttle_resets_on_success(mu):
    from eklavya import auth

    auth.create_user("heidi@example.com", "passwordlong1")
    c = TestClient(_app(), follow_redirects=False)
    for _ in range(auth.MAX_FAILS - 1):  # 4 fails, one under the ceiling
        c.post("/login", data={"email": "heidi@example.com", "password": "wrong-wrong-1"})
    # a success clears the counter
    r = c.post("/login", data={"email": "heidi@example.com", "password": "passwordlong1"})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert not auth.is_locked("heidi@example.com", "testclient")


# --- X-Forwarded-For throttle IP (#52) --------------------------------------

def test_throttle_uses_xff_client_when_proxy_trusted(mu, monkeypatch):
    """Behind a trusted proxy, the throttle keys on the real client (X-Forwarded-For),
    so two different clients hitting through the same proxy get independent buckets."""
    from eklavya import auth, config

    monkeypatch.setattr(config, "TRUST_PROXY", True)
    auth.create_user("ivan@example.com", "passwordlong1")
    c = TestClient(_app(), follow_redirects=False)
    # client A exhausts its attempts…
    for _ in range(auth.MAX_FAILS):
        c.post("/login", data={"email": "ivan@example.com", "password": "wrong-wrong-1"},
               headers={"X-Forwarded-For": "1.1.1.1"})
    a = c.post("/login", data={"email": "ivan@example.com", "password": "passwordlong1"},
               headers={"X-Forwarded-For": "1.1.1.1"})
    assert "Too+many+attempts" in a.headers["location"]   # A is locked
    # …but a different client IP through the same proxy is unaffected
    b = c.post("/login", data={"email": "ivan@example.com", "password": "passwordlong1"},
               headers={"X-Forwarded-For": "2.2.2.2"})
    assert b.status_code == 303 and b.headers["location"] == "/"


def test_throttle_ignores_xff_when_proxy_not_trusted(mu, monkeypatch):
    """Default (not behind a trusted proxy): the X-Forwarded-For header is ignored, so a
    client cannot spoof it to dodge the throttle — all attempts share the connection IP."""
    from eklavya import auth, config

    monkeypatch.setattr(config, "TRUST_PROXY", False)
    auth.create_user("judy@example.com", "passwordlong1")
    c = TestClient(_app(), follow_redirects=False)
    # rotate a spoofed header on every failed attempt…
    for i in range(auth.MAX_FAILS):
        c.post("/login", data={"email": "judy@example.com", "password": "wrong-wrong-1"},
               headers={"X-Forwarded-For": f"9.9.9.{i}"})
    # …still locked, because the header was never trusted (bucket = the real connection IP)
    r = c.post("/login", data={"email": "judy@example.com", "password": "passwordlong1"},
               headers={"X-Forwarded-For": "9.9.9.250"})
    assert "Too+many+attempts" in r.headers["location"]


# --- single-user mode stays auth-free --------------------------------------

def test_single_user_mode_has_no_auth(monkeypatch):
    """Default (MULTIUSER off): no middleware, no /login, routes work without a session."""
    from eklavya import config

    assert config.MULTIUSER is False
    tmp = tempfile.mkdtemp(prefix="eklavya-su-")
    monkeypatch.setenv("EKLAVYA_HOME", tmp)
    c = TestClient(_app(), follow_redirects=False)
    assert c.get("/").status_code == 200            # no redirect to /login
    assert c.get("/api/stats").status_code == 200   # no 401
    assert c.get("/login").status_code == 404        # the login route isn't mounted


async def test_contextvar_propagates_into_threadpool():
    """The per-user home set by middleware must be visible inside run_in_threadpool
    (where blocking agent/sandbox work runs), or a worker would touch the wrong user."""
    from pathlib import Path

    from starlette.concurrency import run_in_threadpool

    from eklavya import config
    from eklavya.config import _current_home

    home = Path("/tmp/eklavya-ctxtest/users/uid-z")
    token = _current_home.set(home)
    try:
        seen = await run_in_threadpool(lambda: str(config.paths().home))
        assert seen == str(home)
    finally:
        _current_home.reset(token)


def test_secret_required_in_multiuser(monkeypatch):
    """Multi-user with no EKLAVYA_SECRET_KEY fails loudly at app construction."""
    from eklavya import config

    monkeypatch.setattr(config, "MULTIUSER", True)
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", tempfile.mkdtemp(prefix="eklavya-nosecret-"))
    monkeypatch.delenv("EKLAVYA_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        _app()
