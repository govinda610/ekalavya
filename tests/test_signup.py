"""Self-service web signup (multi-user): the /signup form creates an account + logs in."""

import os
import tempfile

os.environ["EKLAVYA_HOME"] = tempfile.mkdtemp(prefix="eklavya-signup-home-")

import pytest  # noqa: E402

from eklavya import auth, config  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "DEPLOYED", True)
    monkeypatch.setenv("EKLAVYA_SECRET_KEY", "test-secret-please-ignore-0123456789abcdef")
    monkeypatch.setenv("EKLAVYA_INSECURE_COOKIES", "1")
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", tempfile.mkdtemp(prefix="eklavya-signup-root-"))
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app
    return TestClient(create_app())


def test_signup_page_is_reachable_without_a_session(client):
    r = client.get("/signup")
    assert r.status_code == 200
    assert "Raise your own statue" in r.text or "Sign up" in r.text
    # it starts on the signup tab and posts to /signup
    assert "authMode('signup')" in r.text and 'id="authform"' in r.text


def test_signup_creates_account_and_logs_in(client):
    r = client.post("/signup", data={"email": "new@eklavya.dev", "password": "correcthorse10"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "eklavya_session" in r.headers.get("set-cookie", "")   # logged straight in
    assert auth.verify_login("new@eklavya.dev", "correcthorse10") is not None


def test_signup_rejects_short_password_and_duplicate_email(client):
    short = client.post("/signup", data={"email": "x@eklavya.dev", "password": "short"},
                        follow_redirects=False)
    assert short.status_code == 303 and "/signup?error=" in short.headers["location"]
    assert auth.verify_login("x@eklavya.dev", "short") is None   # not created

    client.post("/signup", data={"email": "dup@eklavya.dev", "password": "correcthorse10"})
    again = client.post("/signup", data={"email": "dup@eklavya.dev", "password": "another10chars"},
                        follow_redirects=False)
    assert again.status_code == 303 and "/signup?error=" in again.headers["location"]


def test_login_page_still_works(client):
    r = client.get("/login")
    assert r.status_code == 200 and "Welcome back" in r.text
