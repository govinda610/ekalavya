"""Request-time auth for the multi-user (served) deployment.

One Starlette middleware does two things per request, and only when ``config.MULTIUSER``
is on (in single-user mode it is never mounted, so the code path is byte-for-byte the
old one):

  1. **Resolve the user.** Read the signed session cookie (it carries just the uid),
     verify its signature, and bind that user's home into ``config.set_current_home`` for
     the request's context — so every Phase-1 per-user path (`config.paths()`) resolves to
     the right user's DB / profile / checkpoints / settings.
  2. **Gate access.** Unauthenticated requests to app routes redirect to ``/login``;
     unauthenticated ``/api/*`` requests get a 401. The login/logout routes and any static
     bits stay open.

Sessions are signed cookies — there is no server-side sessions table (§0.5). The signing
secret comes from ``EKLAVYA_SECRET_KEY``; in multi-user mode we fail loudly at startup if
it is unset. The cookie is ``HttpOnly`` + ``SameSite=Strict`` (which stands in for CSRF
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

# routes reachable without a session (the login form + its POST, the logout POST, and the
# public marketing landing page)
_OPEN_PATHS = {"/login", "/logout", "/welcome"}

# Baseline security headers (SECURITY_AUDIT_2026-08-01b N5). SAMEORIGIN, not DENY, because
# the SPA embeds its own dashboard/journey/profile routes in same-origin iframes. CSP is
# deliberately left for the pre-public hardening pass (needs SRI-pinned CDN scripts first).
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def _secret() -> str:
    secret = os.environ.get("EKLAVYA_SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "EKLAVYA_SECRET_KEY must be set in multi-user mode "
            "(a 32+ byte random value used to sign session cookies)."
        )
    return secret


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
    """Resolve the session → set the per-user contextvar → gate unauthenticated access.

    Only mounted when ``config.MULTIUSER`` is on.
    """

    async def dispatch(self, request: Request, call_next):
        from . import auth

        path = request.url.path
        uid = read_uid(request)

        # A signature-valid cookie for a since-deleted user must not still grant access
        # (SECURITY_AUDIT_2026-08-01b N4) — treat it as unauthenticated.
        if uid is not None and auth.get_user(uid) is None:
            uid = None

        if uid is not None:
            # bind this user's home for the whole request context (Phase 1 isolation)
            config.set_current_home(config.user_home(uid))
            return self._secure(await call_next(request))

        # unauthenticated
        if path in _OPEN_PATHS or path.startswith("/static/"):
            return self._secure(await call_next(request))
        if path.startswith("/api/"):
            return self._secure(JSONResponse({"detail": "authentication required"}, status_code=401))
        return self._secure(RedirectResponse("/login", status_code=303))

    @staticmethod
    def _secure(response):
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response
