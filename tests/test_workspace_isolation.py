"""Security regression (SECURITY_AUDIT_2026-08-01b N1): in multi-user mode the agent's
read backend must confine ls/glob/grep/read — not just `read` — to the current tenant's
own home, so an absolute-path search can't escape to the shared users.db or another
tenant's files. Before the fix the default backend ran virtual_mode=False, so ls/glob/grep
ignored root_dir and read the whole host.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-wsiso-")
os.environ["EKLAVYA_HOME"] = _TMP

import pytest  # noqa: E402

from eklavya import config, workspace  # noqa: E402

SENTINEL = "argon2-hash-SECRET-do-not-leak-4b1f"


@pytest.fixture
def two_tenants(monkeypatch):
    """A data root with tenant A's home, a sibling secret (fake users.db), bound to A."""
    root = Path(tempfile.mkdtemp(prefix="eklavya-dataroot-"))
    (root / "users.db").write_text(SENTINEL)                     # shared secret, outside A
    home_a = root / "users" / "A"
    (home_a / "workspace").mkdir(parents=True)
    (home_a / "workspace" / "mine.txt").write_text("tenant A's own file")

    monkeypatch.setattr(config, "MULTIUSER", True)
    from eklavya.config import _current_home
    token = _current_home.set(home_a)
    try:
        yield root, home_a
    finally:
        _current_home.reset(token)


def test_multiuser_grep_and_ls_cannot_escape_tenant_home(two_tenants):
    root, _home_a = two_tenants
    backend = workspace.build_backend()

    # grep for the secret across the data root (an absolute path OUTSIDE tenant A's home)
    grep_out = str(backend.grep(SENTINEL, path=str(root)))
    assert SENTINEL not in grep_out, "grep escaped the tenant home and read users.db"

    # ls of the data root must not enumerate the sibling secret either
    ls_out = str(backend.ls(str(root)))
    assert "users.db" not in ls_out or SENTINEL not in ls_out

    # and a direct read of the secret is denied by the _is_forbidden guard
    assert SENTINEL not in str(backend.read(str(root / "users.db")))


def test_multiuser_backend_is_virtual_mode_confined(two_tenants):
    # the root-cause assertion: the default read backend is confined (virtual_mode) in
    # multi-user, so the confinement can't be bypassed by non-read ops.
    backend = workspace.build_backend()
    assert backend.default.virtual_mode is True


def test_single_user_backend_stays_read_broad():
    # single-user (owner's own machine) keeps virtual_mode=False so you can point it at
    # your real code anywhere on the host — unchanged behaviour.
    from eklavya.config import _current_home
    token = _current_home.set(None)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(config, "MULTIUSER", False)
            backend = workspace.build_backend()
            assert backend.default.virtual_mode is False
    finally:
        _current_home.reset(token)
