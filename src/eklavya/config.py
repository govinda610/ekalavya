"""Where Ekalavya keeps its state, and how it reads configuration.

Two stores, one truth (see PLAN §12):
  - profile.md  → the human-readable learner model, SHARED with Teacher Mode
  - eklavya.db  → the structured state (ratings, cards, goals, ...)

Path resolution goes through a single accessor — ``paths()`` — so the app can be
made per-user without touching every reader (see docs/MULTIUSER_DEPLOYMENT_PLAN.md §3).
A ``ContextVar`` holds the *current* user's home; when it is unset (the single-user
default) ``paths()`` resolves exactly as it always has, honouring the EKLAVYA_HOME /
EKLAVYA_WORKSPACE / EKLAVYA_PROFILE environment overrides. The module-level constants
(``EKLAVYA_HOME``, ``WORKSPACE``, ``DB_PATH``, ...) are kept as thin, dynamic shims via
``__getattr__`` so existing readers keep working while transparently becoming per-user.
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

# Multi-user is opt-in; the default (0) is the single-user self-host path, byte-for-byte
# identical to before. Phase 1 only adds the plumbing — no auth/middleware is mounted.
MULTIUSER = os.environ.get("EKLAVYA_MULTIUSER", "0") not in ("0", "", "false", "False")

# Which provider/model to teach with by default (overridable via env).
DEFAULT_PROVIDER = os.environ.get("EKLAVYA_PROVIDER", "glm")


# --- the current user's home (contextvar) ----------------------------------

# Holds the resolved home for the request/task currently in flight. Unset (None) means
# "single-user default" → resolve from the environment exactly as the original code did.
_current_home: ContextVar[Path | None] = ContextVar("eklavya_home", default=None)


def set_current_home(home: Path | str) -> None:
    """Bind the current context to a user's home dir. Read lazily by ``paths()``.

    In single-user mode this is pre-seeded once with ``~/.eklavya`` (or the env override)
    so behaviour is unchanged. In multi-user mode auth middleware (Phase 3) sets it per
    request. Must be set on the same context that reads paths — see ``run_user_task``.
    """
    _current_home.set(Path(home))


def _default_home() -> Path:
    """The single-user home, from the environment (the pre-contextvar behaviour)."""
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

    When the contextvar is unset (single-user default) the EKLAVYA_WORKSPACE /
    EKLAVYA_PROFILE env overrides are honoured, matching the original constants exactly.
    When a specific home is bound (multi-user), paths follow the fixed per-user layout
    rooted at that home — env overrides that point at the single-user home don't apply.
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
    """The multi-user data root (``$EKLAVYA_DATA_ROOT``): parent of ``users/`` and of the
    shared ``users.db``. Not used in single-user mode."""
    return Path(os.environ.get("EKLAVYA_DATA_ROOT", Path.home() / ".eklavya-data"))


def user_home(uid: str) -> Path:
    """The on-disk home for a given user id in multi-user mode:
    ``$EKLAVYA_DATA_ROOT/users/<uid>``. Not used in single-user mode."""
    return data_root() / "users" / uid


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
