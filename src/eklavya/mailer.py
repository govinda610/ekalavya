"""Optional, pluggable email notifications (Gmail SMTP by default).

The app must work FULLY without email: if SMTP isn't configured, ``send_email`` is a safe
no-op that logs at debug and returns False. When configured it sends over STARTTLS via the
stdlib ``smtplib`` — no third-party dependency.

Two safety rules baked in:
  - the SMTP password is NEVER logged (we only ever log the host/port/recipient);
  - every send is wrapped so a mail failure can never break the caller (signup/approval).

The actual SMTP send is behind ``_smtp_send`` so tests can mount a fake and assert on it
without touching the network.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

_log = logging.getLogger("eklavya.mailer")


def _cfg() -> dict:
    """Read the SMTP config from the environment (live, so tests can set it per-case)."""
    user = os.environ.get("SMTP_USER", "")
    return {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": user,
        "password": os.environ.get("SMTP_PASS", ""),
        "from": os.environ.get("EMAIL_FROM", "") or user,
    }


def email_enabled() -> bool:
    """True only when credentials are present (both user and password). Absent → email off."""
    cfg = _cfg()
    return bool(cfg["user"] and cfg["password"])


def _smtp_send(cfg: dict, msg: EmailMessage) -> None:
    """The real SMTP send (STARTTLS). Mounted over by tests so no network is touched.

    NOTE: never log cfg['password'] — only host/port/recipient are ever surfaced.
    """
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
        server.starttls()
        server.login(cfg["user"], cfg["password"])
        server.send_message(msg)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if a send was attempted successfully.

    Safe no-op (returns False, logs at debug) when SMTP is unconfigured. Any error during the
    send is swallowed and logged (WITHOUT the password) so the caller — signup / approval —
    is never broken by a mail problem.
    """
    if not email_enabled():
        _log.debug("email disabled (SMTP not configured) — skipping message to %s", to)
        return False
    cfg = _cfg()
    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        _smtp_send(cfg, msg)
        _log.debug("sent email to %s via %s:%s", to, cfg["host"], cfg["port"])
        return True
    except Exception:  # noqa: BLE001 — mail must never break the app; log without secrets
        _log.warning("failed to send email to %s via %s:%s", to, cfg["host"], cfg["port"])
        return False
