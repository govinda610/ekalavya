"""Owner-only admin approval page + routes.

Fully offline. Multi-user mode with a throwaway EKLAVYA_DATA_ROOT + test secret, so the real
~/.eklavya-data and real accounts are never touched. Proves: admin gating (non-admin and
logged-out get 404 on every admin route + no Admin nav flag), the admin can list pending,
approve flips status→active (the user can then log in), reject removes the pending account,
and an ACTIVE account is never affected by reject.
"""

import os
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def env(monkeypatch):
    """Multi-user, deployed, with the owner set to owner@eklavya.dev. Yields nothing."""
    from eklavya import auth, config

    root = Path(tempfile.mkdtemp(prefix="eklavya-admin-"))
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(root))
    monkeypatch.setenv("EKLAVYA_SECRET_KEY", "test-secret-please-ignore-0123456789abcdef")
    monkeypatch.setenv("EKLAVYA_INSECURE_COOKIES", "1")
    monkeypatch.setattr(config, "DEPLOYED", True)
    monkeypatch.setattr(config, "SIGNUP_APPROVAL", True)
    monkeypatch.setattr(config, "ADMIN_EMAIL", "owner@eklavya.dev")
    auth._fails.clear()
    yield
    auth._fails.clear()


def _app():
    from eklavya.webapp import create_app

    return create_app()


def _login(client, email, password):
    r = client.post("/login", data={"email": email, "password": password},
                    follow_redirects=False)
    return r


def _make_active(email, password):
    from eklavya import auth

    return auth.create_user(email, password, status="active")


# --- is_admin helper --------------------------------------------------------


def test_is_admin_case_insensitive_and_empty(monkeypatch):
    from eklavya import config

    monkeypatch.setattr(config, "ADMIN_EMAIL", "Owner@Eklavya.dev")
    assert config.is_admin("owner@eklavya.dev")
    assert config.is_admin("OWNER@EKLAVYA.DEV")
    assert not config.is_admin("someone@else.dev")
    assert not config.is_admin(None)
    monkeypatch.setattr(config, "ADMIN_EMAIL", "")
    assert not config.is_admin("owner@eklavya.dev")  # empty → nobody is admin


# --- gating -----------------------------------------------------------------


def test_logged_out_gets_401_on_admin_routes(env):
    c = TestClient(_app())
    assert c.get("/api/admin/pending").status_code == 401
    assert c.post("/api/admin/approve", json={"email": "x@y.z"}).status_code == 401
    assert c.post("/api/admin/reject", json={"email": "x@y.z"}).status_code == 401


def test_non_admin_gets_404_on_admin_routes_and_no_nav_flag(env):
    _make_active("owner@eklavya.dev", "correcthorse10")
    _make_active("plain@eklavya.dev", "correcthorse10")
    c = TestClient(_app())
    _login(c, "plain@eklavya.dev", "correcthorse10")
    assert c.get("/api/config").json()["is_admin"] is False
    assert c.get("/api/admin/pending").status_code == 404
    assert c.post("/api/admin/approve", json={"email": "x@y.z"}).status_code == 404
    assert c.post("/api/admin/reject", json={"email": "x@y.z"}).status_code == 404


def test_admin_sees_flag_and_pending(env):
    from eklavya import auth

    _make_active("owner@eklavya.dev", "correcthorse10")
    auth.create_user("wild1@eklavya.dev", "correcthorse10", status="pending")
    auth.create_user("wild2@eklavya.dev", "correcthorse10", status="pending")
    c = TestClient(_app())
    _login(c, "owner@eklavya.dev", "correcthorse10")
    assert c.get("/api/config").json()["is_admin"] is True
    emails = {u["email"] for u in c.get("/api/admin/pending").json()["pending"]}
    assert emails == {"wild1@eklavya.dev", "wild2@eklavya.dev"}


# --- approve / reject -------------------------------------------------------


def test_admin_approve_flips_to_active_and_user_can_log_in(env):
    from eklavya import auth

    _make_active("owner@eklavya.dev", "correcthorse10")
    auth.create_user("wild@eklavya.dev", "correcthorse10", status="pending")
    c = TestClient(_app())
    _login(c, "owner@eklavya.dev", "correcthorse10")

    # before approval the pending user cannot log in
    pre = TestClient(_app())
    r = _login(pre, "wild@eklavya.dev", "correcthorse10")
    assert "eklavya_session" not in r.headers.get("set-cookie", "")

    assert c.post("/api/admin/approve", json={"email": "wild@eklavya.dev"}).json()["ok"] is True
    assert auth.get_user_by_email("wild@eklavya.dev")["status"] == "active"

    # now the (approved) user can log in
    post = TestClient(_app())
    r2 = _login(post, "wild@eklavya.dev", "correcthorse10")
    assert r2.status_code == 303 and r2.headers["location"] == "/"
    assert "eklavya_session" in r2.headers.get("set-cookie", "")


def test_admin_reject_removes_pending_account(env):
    from eklavya import auth

    _make_active("owner@eklavya.dev", "correcthorse10")
    auth.create_user("wild@eklavya.dev", "correcthorse10", status="pending")
    c = TestClient(_app())
    _login(c, "owner@eklavya.dev", "correcthorse10")

    assert c.post("/api/admin/reject", json={"email": "wild@eklavya.dev"}).json()["ok"] is True
    assert auth.get_user_by_email("wild@eklavya.dev") is None
    assert auth.list_pending() == []


def test_reject_never_touches_an_active_account(env):
    from eklavya import auth

    _make_active("owner@eklavya.dev", "correcthorse10")
    _make_active("active@eklavya.dev", "correcthorse10")
    c = TestClient(_app())
    _login(c, "owner@eklavya.dev", "correcthorse10")

    # rejecting an ACTIVE account is a no-op — the account survives untouched
    assert c.post("/api/admin/reject", json={"email": "active@eklavya.dev"}).json()["ok"] is False
    assert auth.get_user_by_email("active@eklavya.dev")["status"] == "active"
    # and reject_user directly is likewise inert against active accounts
    assert auth.reject_user("active@eklavya.dev") is False
    assert auth.get_user_by_email("active@eklavya.dev") is not None
