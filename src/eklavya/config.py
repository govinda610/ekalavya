"""Where Ekalavya keeps its state, and how it reads configuration.

Two stores, one truth (see PLAN §12):
  - profile.md  → the human-readable learner model, SHARED with Teacher Mode
  - eklavya.db  → the structured state (ratings, cards, goals, ...)

Path resolution goes through a single accessor — ``paths()`` — so every reader is per-user
without threading a user through each call. A ``ContextVar`` holds the *current* account's
home, which the CLI/TUI (``resolve_local_user``) and the web (the session's user) bind
before touching state. When it is unset ``paths()`` falls back to the EKLAVYA_HOME /
EKLAVYA_WORKSPACE / EKLAVYA_PROFILE overrides (a "which home" knob for tests + ad-hoc runs),
else the retired ``~/.eklavya`` — never written to for real data. The module-level constants
(``EKLAVYA_HOME``, ``WORKSPACE``, ``DB_PATH``, ...) are thin dynamic shims via ``__getattr__``
so existing readers resolve per-account for free.
"""

from __future__ import annotations

import contextvars
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env if present, so credentials don't have to live in the shell.
load_dotenv()

# The account model is ALWAYS on now — web, CLI, and TUI all operate as a logged-in
# account, data always living at $EKLAVYA_DATA_ROOT/users/<uid>/... . The only axis left is
# the DEPLOYMENT POSTURE: a local self-host (default) vs a hosted, public deployment. They
# differ only by config, never by code path:
#   - local (DEPLOYED off): a frictionless default account (no email/password ceremony per
#     command), broad host reads so you can point the tutor at your real code, no signup gate;
#   - deployed (DEPLOYED on): full email+password auth, reads confined to the tenant's tree,
#     optional signup-approval gate.
DEPLOYED = os.environ.get("EKLAVYA_DEPLOYED", "0") not in ("0", "", "false", "False")

# Trust the reverse proxy's forwarded client IP for login throttling. OFF by default:
# when the app is exposed directly, request.client.host is the real client and a header
# could be spoofed. Turn this ON *only* behind a trusted proxy (e.g. Caddy), which sets
# X-Forwarded-For — then the throttle keys on the left-most (original client) IP instead
# of the proxy's own address.
TRUST_PROXY = os.environ.get("EKLAVYA_TRUST_PROXY", "0") not in ("0", "", "false", "False")

# Which provider/model to teach with by default (overridable via env).
DEFAULT_PROVIDER = os.environ.get("EKLAVYA_PROVIDER", "glm")

# Opt-in round-robin load-balancing of the ENTRY provider across configured keys
# (only when no explicit provider is requested). Off by default, so single-key and
# explicit-provider setups are unchanged. The cross-provider fallback chain is
# always active regardless of this flag.
BALANCE_PROVIDERS = os.environ.get("EKLAVYA_BALANCE", "0") not in ("0", "", "false", "False")

# When on, a self-service signup creates a PENDING account that the owner must approve
# (`eklavya approve <email>`) before it can log in — so opening registration in the wild
# can't be abused by anyone who just types an email + password. Off by default.
SIGNUP_APPROVAL = os.environ.get("EKLAVYA_SIGNUP_APPROVAL", "0") not in ("0", "", "false", "False")


# --- the current user's home (contextvar) ----------------------------------

# Holds the resolved home for the request/task currently in flight. Unset (None) → fall back
# to the environment override (EKLAVYA_HOME) / the retired ~/.eklavya (never real data).
_current_home: ContextVar[Path | None] = ContextVar("eklavya_home", default=None)


def set_current_home(home: Path | str) -> None:
    """Bind the current context to an account's home dir. Read lazily by ``paths()``.

    The CLI/TUI bind the resolved local account at startup; the web auth middleware binds
    the session's user per request. Must be set on the same context that reads paths — see
    ``run_user_task``.
    """
    _current_home.set(Path(home))


# --- the current chat thread (contextvar) ----------------------------------
# The web app binds this to the chat thread in flight before it runs the agent, so a tool
# called mid-turn (e.g. save_artifact) can associate what it saves with the originating chat
# without threading the id through every call. Unset (None) in the CLI/TUI / ad-hoc contexts.
_current_thread: ContextVar[str | None] = ContextVar("eklavya_thread", default=None)


def set_current_thread(thread_id: str | None) -> None:
    """Bind the current context to a chat thread (or None to clear)."""
    _current_thread.set(thread_id or None)


def current_thread() -> str | None:
    """The chat thread in flight for this context, or None."""
    return _current_thread.get()


def _default_home() -> Path:
    """The home used when NO account is bound to the current context.

    This is a fallback only — real reads/writes always run under a bound account (the CLI/
    TUI bind the resolved local user; the web binds the session's user). The ``EKLAVYA_HOME``
    override is honoured here so tests (and ad-hoc scripts) can pin a throwaway home without
    going through the account layer. Absent that override it resolves to the retired
    ``~/.eklavya`` path, which is NEVER written to for real data — the destructive-op guard
    (tools.py) refuses any wipe that would land there with no account bound.
    """
    return Path(os.environ.get("EKLAVYA_HOME", Path.home() / ".eklavya"))


def _home() -> Path:
    h = _current_home.get()
    return h if h is not None else _default_home()


@dataclass(frozen=True)
class Paths:
    """The six state paths for one user, resolved together and immutable."""

    home: Path
    workspace: Path
    db: Path
    profile: Path
    backups: Path
    checkpoints: Path


def paths() -> Paths:
    """Resolve the current user's state paths (contextvar-aware).

    When the contextvar is unset the EKLAVYA_WORKSPACE / EKLAVYA_PROFILE env overrides are
    honoured (the "which home" knob). When an account's home is bound, paths follow the
    fixed per-account layout rooted at that home — the env overrides don't apply.
    """
    bound = _current_home.get()
    home = bound if bound is not None else _default_home()
    if bound is None:
        # single-user: preserve the original env-override semantics
        workspace = Path(os.environ.get("EKLAVYA_WORKSPACE", home / "workspace"))
        profile = Path(os.environ.get("EKLAVYA_PROFILE", workspace / "profile.md"))
    else:
        workspace = home / "workspace"
        profile = workspace / "profile.md"
    return Paths(
        home=home,
        workspace=workspace,
        db=workspace / "eklavya.db",
        profile=profile,
        backups=home / "backups",
        checkpoints=home / "checkpoints.sqlite",
    )


def data_root() -> Path:
    """The data root (``$EKLAVYA_DATA_ROOT``, default ``~/.eklavya-data``): parent of
    ``users/`` and of the shared ``users.db``. All real data lives beneath here."""
    return Path(os.environ.get("EKLAVYA_DATA_ROOT", Path.home() / ".eklavya-data"))


def user_home(uid: str) -> Path:
    """The on-disk home for a given user id: ``$EKLAVYA_DATA_ROOT/users/<uid>``."""
    return data_root() / "users" / uid


# --- resolving which local account the CLI/TUI runs as ----------------------

def _default_user_file() -> Path:
    """Where the stored "default local user" (a uid) is remembered, at the data-root level
    (alongside ``users.db``), so it survives across CLI invocations."""
    return data_root() / "default_user"


def stored_default_user() -> str | None:
    """The uid of the machine's remembered default local account, or None."""
    f = _default_user_file()
    if not f.exists():
        return None
    uid = f.read_text(encoding="utf-8").strip()
    return uid or None


def set_default_user(uid: str) -> None:
    """Remember ``uid`` as this machine's default local account (used by ``eklavya login``)."""
    data_root().mkdir(parents=True, exist_ok=True)
    _default_user_file().write_text(uid.strip(), encoding="utf-8")


def clear_default_user() -> None:
    """Forget the remembered default local account (used by ``eklavya logout``)."""
    f = _default_user_file()
    if f.exists():
        f.unlink()


def resolve_local_user(user: str | None = None) -> str:
    """The uid the CLI/TUI should run as, resolved in precedence order:

      1. an explicit ``user`` ref (the ``--user`` flag) or ``EKLAVYA_USER`` (email or uid)
         → that existing account;
      2. else the stored default local user (``eklavya login`` writes it);
      3. else if exactly one account exists → it;
      4. else → first-run: create/pick a frictionless local account.

    Always resolves to an EXISTING account — it never silently creates a fresh empty one
    when real accounts already exist (that would hide the learner's data). Ambiguity (2+
    accounts, none designated) raises so the caller can prompt with ``--user`` / ``login``.
    """
    from . import auth

    # 1. explicit override — email or uid (the flag wins over the env var)
    requested = (user or os.environ.get("EKLAVYA_USER", "")).strip()
    if requested:
        uid = auth.resolve_user_ref(requested)
        if uid is None:
            raise LookupError(f"no account for EKLAVYA_USER={requested!r}")
        return uid

    # 2. stored default
    stored = stored_default_user()
    if stored and auth.get_user(stored):
        return stored

    users = auth.list_users()
    # 3. the sole account
    if len(users) == 1:
        return users[0]["id"]
    if len(users) > 1:
        raise LookupError(
            "multiple accounts exist and none is designated — pick one with "
            "`eklavya login` / `--user <email>`, or set EKLAVYA_USER."
        )

    # 4. first run — create a frictionless local account and remember it
    uid = auth.ensure_local_user()
    set_default_user(uid)
    return uid


def run_user_task(fn, *args, **kwargs):
    """Run ``fn`` in a copy of the current context so the ``_current_home`` contextvar
    propagates when work is dispatched off the event loop (raw threads / executors that
    don't copy context themselves). Starlette's ``run_in_threadpool`` already copies the
    context, so this is only needed for manually-spawned threads — it is the single
    chokepoint the plan (§3, §5) reserves for that. Used from Phase 3 onward.
    """
    return contextvars.copy_context().run(fn, *args, **kwargs)


def ensure_home() -> Path:
    """Create the current user's home + workspace if they don't exist yet."""
    p = paths()
    p.home.mkdir(parents=True, exist_ok=True)
    p.workspace.mkdir(parents=True, exist_ok=True)
    return p.home


# --- backwards-compatible module constants (dynamic shims) ------------------
# These used to be computed once at import. They are now thin, contextvar-aware wrappers
# so every existing ``config.X`` reader keeps working AND becomes per-user for free.
# Accessing them still returns a Path, identical to before in single-user mode.

_SHIMS = {
    "EKLAVYA_HOME": lambda: paths().home,
    "WORKSPACE": lambda: paths().workspace,
    "DB_PATH": lambda: paths().db,
    "PROFILE_PATH": lambda: paths().profile,
    "BACKUPS_DIR": lambda: paths().backups,
    "CHECKPOINTS_PATH": lambda: paths().checkpoints,
}


def __getattr__(name: str):
    shim = _SHIMS.get(name)
    if shim is not None:
        return shim()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
