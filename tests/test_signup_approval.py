"""Signup approval gate: when on, new signups land 'pending' and can't log in until the
owner approves (`eklavya approve <email>` → auth.approve_user)."""

import os
import tempfile

os.environ["EKLAVYA_HOME"] = tempfile.mkdtemp(prefix="eklavya-appr-home-")

import pytest  # noqa: E402

from eklavya import auth, config  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "MULTIUSER", True)
    monkeypatch.setattr(config, "SIGNUP_APPROVAL", True)
    monkeypatch.setenv("EKLAVYA_SECRET_KEY", "test-secret-please-ignore-0123456789abcdef")
    monkeypatch.setenv("EKLAVYA_INSECURE_COOKIES", "1")
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", tempfile.mkdtemp(prefix="eklavya-appr-root-"))
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app
    return TestClient(create_app())


def test_signup_lands_pending_and_cannot_log_in_until_approved(client):
    # signup does NOT log in — it lands pending and bounces to /login with a notice
    r = client.post("/signup", data={"email": "wild@eklavya.dev", "password": "correcthorse10"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?notice=")
    assert "eklavya_session" not in r.headers.get("set-cookie", "")
    assert {u["email"] for u in auth.list_pending()} == {"wild@eklavya.dev"}

    # correct credentials but still pending → refused, no session
    r2 = client.post("/login", data={"email": "wild@eklavya.dev", "password": "correcthorse10"},
                     follow_redirects=False)
    assert r2.status_code == 303 and "notice=" in r2.headers["location"]
    assert "eklavya_session" not in r2.headers.get("set-cookie", "")

    # owner approves → now login works and a session is issued
    assert auth.approve_user("wild@eklavya.dev") is True
    assert auth.list_pending() == []
    r3 = client.post("/login", data={"email": "wild@eklavya.dev", "password": "correcthorse10"},
                     follow_redirects=False)
    assert r3.status_code == 303 and r3.headers["location"] == "/"
    assert "eklavya_session" in r3.headers.get("set-cookie", "")


def test_pending_cookie_is_rejected_by_middleware(client):
    # a pending user with a validly-signed cookie still can't reach protected APIs
    from eklavya.middleware import issue_session
    from starlette.responses import Response

    uid = auth.create_user("p@eklavya.dev", "correcthorse10", status="pending")
    r = Response(); issue_session(r, uid)
    signed = r.headers["set-cookie"].split("eklavya_session=")[1].split(";")[0]
    client.cookies.set("eklavya_session", signed)
    assert client.get("/api/config").status_code == 401
    client.cookies.clear()


def test_approval_off_logs_in_directly(monkeypatch):
    monkeypatch.setattr(config, "MULTIUSER", True)
    monkeypatch.setattr(config, "SIGNUP_APPROVAL", False)
    monkeypatch.setenv("EKLAVYA_SECRET_KEY", "test-secret-please-ignore-0123456789abcdef")
    monkeypatch.setenv("EKLAVYA_INSECURE_COOKIES", "1")
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", tempfile.mkdtemp(prefix="eklavya-appr2-"))
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app
    c = TestClient(create_app())
    r = c.post("/signup", data={"email": "ok@eklavya.dev", "password": "correcthorse10"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "eklavya_session" in r.headers.get("set-cookie", "")
