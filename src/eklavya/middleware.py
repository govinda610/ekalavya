"""Request-time auth for the multi-user (served) deployment.

The web app is always account-backed, so this middleware runs on every deployment. It does
two things per request:

  1. **Resolve the user.** Read the signed session cookie (it carries just the uid),
     verify its signature, and bind that user's home into ``config.set_current_home`` for
     the request's context — so every Phase-1 per-user path (`config.paths()`) resolves to
     the right user's DB / profile / checkpoints / settings.
  2. **Gate access.** Unauthenticated requests to app routes redirect to ``/login``;
     unauthenticated ``/api/*`` requests get a 401. The login/logout routes and any static
     bits stay open.

Sessions are signed cookies — there is no server-side sessions table (§0.5). The signing
secret comes from ``EKLAVYA_SECRET_KEY``; the web app fails loudly at startup if it is unset. The cookie is ``HttpOnly`` + ``SameSite=Strict`` (which stands in for CSRF
tokens, §0.5) + ``Secure`` (togglable off for local http dev via ``EKLAVYA_INSECURE_COOKIES=1``).
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from . import config

COOKIE_NAME = "eklavya_session"
COOKIE_MAX_AGE = 14 * 24 * 3600  # 14 days

# routes reachable without a session (the login + signup forms and their POSTs, the logout
# POST, and the public marketing landing + About pages)
_OPEN_PATHS = {"/login", "/signup", "/logout", "/welcome", "/about"}

# Baseline security headers (SECURITY_AUDIT_2026-08-01b N5). SAMEORIGIN, not DENY, because
# the SPA embeds its own dashboard/journey/profile routes in same-origin iframes. CSP is
# deliberately left for the pre-public hardening pass (needs SRI-pinned CDN scripts first).
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def _secret() -> str:
    """The cookie-signing secret.

    Deployed: ``EKLAVYA_SECRET_KEY`` is mandatory (fail loudly at startup if unset). Local
    self-host: if unset we persist a random machine-local secret at the data root so the
    solo user isn't forced to configure one — sessions still survive restarts.
    """
    secret = os.environ.get("EKLAVYA_SECRET_KEY", "")
    if secret:
        return secret
    if config.DEPLOYED:
        raise RuntimeError(
            "EKLAVYA_SECRET_KEY must be set when EKLAVYA_DEPLOYED is on "
            "(a 32+ byte random value used to sign session cookies)."
        )
    return _local_secret()


def _local_secret() -> str:
    """A stable, random secret for local self-host, created once and persisted at the data
    root (so it survives restarts). Never used when a real EKLAVYA_SECRET_KEY is set."""
    import secrets

    path = config.data_root() / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    path.write_text(value, encoding="utf-8")
    return value


def _signer():
    from itsdangerous import TimestampSigner

    return TimestampSigner(_secret())


def secure_cookies() -> bool:
    """True unless local http dev explicitly opts out (``EKLAVYA_INSECURE_COOKIES=1``)."""
    return os.environ.get("EKLAVYA_INSECURE_COOKIES", "0") in ("0", "", "false", "False")


def issue_session(response, uid: str) -> None:
    """Sign ``uid`` into the session cookie on ``response`` (called by the login route)."""
    token = _signer().sign(uid.encode()).decode()
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=COOKIE_MAX_AGE, httponly=True, samesite="strict",
        secure=secure_cookies(), path="/",
    )


def clear_session(response) -> None:
    """Drop the session cookie (called by the logout route)."""
    response.delete_cookie(COOKIE_NAME, path="/")


def read_uid(request: Request) -> str | None:
    """The verified uid from the request's session cookie, or None if absent/invalid."""
    from itsdangerous import BadSignature, SignatureExpired

    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        uid = _signer().unsign(raw, max_age=COOKIE_MAX_AGE).decode()
    except (BadSignature, SignatureExpired):
        return None
    return uid or None


class AuthMiddleware(BaseHTTPMiddleware):
    """Resolve the session → set the per-user contextvar → gate unauthenticated access."""

    async def dispatch(self, request: Request, call_next):
        from . import auth

        path = request.url.path
        uid = read_uid(request)

        # A signature-valid cookie only grants access to an existing, ACTIVE account —
        # a since-deleted user (N4) or one still awaiting approval is treated as
        # unauthenticated.
        if uid is not None:
            u = auth.get_user(uid)
            if u is None or u.get("status") != "active":
                uid = None

        if uid is not None:
            # bind this user's home for the whole request context (per-user isolation)
            config.set_current_home(config.user_home(uid))
            return self._secure(await call_next(request))

        # Local self-host (not deployed): no session yet → auto-log-in so a solo user isn't
        # forced through the login form. Deployed skips this and enforces the full auth flow.
        #   - EKLAVYA_HOME override present → bind that home directly (the "which home" knob
        #     tests + ad-hoc runs use); no account lookup, no cookie.
        #   - else → bind the resolved local default account and remember it via a cookie.
        if not config.DEPLOYED:
            if os.environ.get("EKLAVYA_HOME"):
                config.set_current_home(config._default_home())
                config.ensure_home()
                self._init_db()
                return self._secure(await call_next(request))
            local_uid = self._local_uid()
            if local_uid is not None:
                config.set_current_home(config.user_home(local_uid))
                config.ensure_home()
                self._init_db()
                resp = await call_next(request)
                issue_session(resp, local_uid)  # remember it for subsequent requests
                return self._secure(resp)

        # unauthenticated
        if path in _OPEN_PATHS or path.startswith("/static/"):
            return self._secure(await call_next(request))
        if path.startswith("/api/"):
            return self._secure(JSONResponse({"detail": "authentication required"}, status_code=401))
        return self._secure(RedirectResponse("/login", status_code=303))

    @staticmethod
    def _init_db() -> None:
        from .db import init_db

        init_db()

    @staticmethod
    def _local_uid() -> str | None:
        """Resolve the local default account for auto-login, or None if it can't be
        determined unambiguously (e.g. several accounts, none designated) — then the normal
        login form is shown instead of guessing."""
        try:
            return config.resolve_local_user()
        except (LookupError, ValueError):
            return None

    @staticmethod
    def _secure(response):
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        # Never cache the SPA HTML — a normal refresh must always get the current UI (stale
        # cached pages made fixed bugs look unfixed). Static assets (fonts/js/css) still cache.
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
