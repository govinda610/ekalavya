"""Optional email notifications (Gmail SMTP), no real network.

The real SMTP send is mounted over with a fake (mailer._smtp_send) so nothing leaves the
process. Proves: send_email no-ops when unconfigured; when configured a real send is
attempted; a raised SMTP error is swallowed (returns False, never raises); the SMTP password
never appears in logs; and the webapp hooks fire (signup → admin email, approval → user
email) without breaking signup/approval even when the mailer raises.
"""

import logging
import os
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from eklavya import mailer


@pytest.fixture(autouse=True)
def _clean_smtp(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "EMAIL_FROM"):
        monkeypatch.delenv(k, raising=False)
    yield


def _configure_smtp(monkeypatch, password="hunter2-secret-pw"):
    monkeypatch.setenv("SMTP_USER", "bot@eklavya.dev")
    monkeypatch.setenv("SMTP_PASS", password)
    monkeypatch.setenv("EMAIL_FROM", "bot@eklavya.dev")


# --- send_email directly ----------------------------------------------------


def test_noop_when_unconfigured(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "_smtp_send", lambda cfg, msg: sent.append(msg))
    assert mailer.email_enabled() is False
    assert mailer.send_email("a@b.c", "hi", "body") is False
    assert sent == []  # nothing was attempted


def test_sends_when_configured(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "_smtp_send", lambda cfg, msg: sent.append((cfg, msg)))
    _configure_smtp(monkeypatch)
    assert mailer.email_enabled() is True
    assert mailer.send_email("user@eklavya.dev", "Subject line", "the body") is True
    assert len(sent) == 1
    cfg, msg = sent[0]
    assert msg["To"] == "user@eklavya.dev"
    assert msg["Subject"] == "Subject line"
    assert msg["From"] == "bot@eklavya.dev"


def test_smtp_error_is_swallowed(monkeypatch):
    def boom(cfg, msg):
        raise OSError("smtp exploded")

    monkeypatch.setattr(mailer, "_smtp_send", boom)
    _configure_smtp(monkeypatch)
    # must NOT raise; returns False
    assert mailer.send_email("user@eklavya.dev", "s", "b") is False


def test_password_never_logged(monkeypatch, caplog):
    def boom(cfg, msg):
        raise OSError("smtp exploded")

    monkeypatch.setattr(mailer, "_smtp_send", boom)
    _configure_smtp(monkeypatch, password="SUPERSECRETPW123")
    with caplog.at_level(logging.DEBUG, logger="eklavya.mailer"):
        mailer.send_email("user@eklavya.dev", "s", "b")
    assert "SUPERSECRETPW123" not in caplog.text


# --- webapp hooks -----------------------------------------------------------


@pytest.fixture
def deployed(monkeypatch):
    from eklavya import auth, config

    root = Path(tempfile.mkdtemp(prefix="eklavya-mailer-"))
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(root))
    monkeypatch.setenv("EKLAVYA_SECRET_KEY", "test-secret-please-ignore-0123456789abcdef")
    monkeypatch.setenv("EKLAVYA_INSECURE_COOKIES", "1")
    monkeypatch.setattr(config, "DEPLOYED", True)
    monkeypatch.setattr(config, "SIGNUP_APPROVAL", True)
    monkeypatch.setattr(config, "ADMIN_EMAIL", "owner@eklavya.dev")
    _configure_smtp(monkeypatch)
    auth._fails.clear()
    yield
    auth._fails.clear()


def _app():
    from eklavya.webapp import create_app

    return create_app()


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "_smtp_send", lambda cfg, msg: sent.append(msg))
    return sent


def test_signup_emails_the_admin(deployed, monkeypatch):
    sent = _capture(monkeypatch)
    c = TestClient(_app())
    r = c.post("/signup", data={"email": "wild@eklavya.dev", "password": "correcthorse10"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?notice=")
    admin_msgs = [m for m in sent if m["To"] == "owner@eklavya.dev"]
    assert len(admin_msgs) == 1
    assert "wild@eklavya.dev" in admin_msgs[0].get_content()


def test_approval_emails_the_user(deployed, monkeypatch):
    from eklavya import auth

    sent = _capture(monkeypatch)
    auth.create_user("owner@eklavya.dev", "correcthorse10", status="active")
    auth.create_user("wild@eklavya.dev", "correcthorse10", status="pending")
    c = TestClient(_app())
    c.post("/login", data={"email": "owner@eklavya.dev", "password": "correcthorse10"},
           follow_redirects=False)
    c.post("/api/admin/approve", json={"email": "wild@eklavya.dev"})
    user_msgs = [m for m in sent if m["To"] == "wild@eklavya.dev"]
    assert len(user_msgs) == 1
    assert "approved" in user_msgs[0]["Subject"].lower()


def test_mail_failure_does_not_break_signup_or_approval(deployed, monkeypatch):
    from eklavya import auth

    monkeypatch.setattr(mailer, "_smtp_send", lambda cfg, msg: (_ for _ in ()).throw(OSError("nope")))

    # signup still succeeds (lands pending) despite the admin email raising
    c = TestClient(_app())
    r = c.post("/signup", data={"email": "wild@eklavya.dev", "password": "correcthorse10"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?notice=")
    assert {u["email"] for u in auth.list_pending()} == {"wild@eklavya.dev"}

    # approval still succeeds despite the user email raising
    auth.create_user("owner@eklavya.dev", "correcthorse10", status="active")
    a = TestClient(_app())
    a.post("/login", data={"email": "owner@eklavya.dev", "password": "correcthorse10"},
           follow_redirects=False)
    assert a.post("/api/admin/approve", json={"email": "wild@eklavya.dev"}).json()["ok"] is True
    assert auth.get_user_by_email("wild@eklavya.dev")["status"] == "active"
