"""resolve_local_user() precedence + the frictionless local default account.

Fully offline, throwaway data roots only — the real ~/.eklavya-data is never touched. Each
test pins its own EKLAVYA_DATA_ROOT so accounts + the stored default are isolated.
"""

import tempfile
from pathlib import Path

import pytest

from eklavya import auth, config


@pytest.fixture
def root(monkeypatch):
    """An isolated data root; also clears any EKLAVYA_USER override."""
    d = Path(tempfile.mkdtemp(prefix="eklavya-resolve-"))
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(d))
    monkeypatch.delenv("EKLAVYA_USER", raising=False)
    yield d


def test_first_run_creates_a_frictionless_local_account(root):
    assert auth.list_users() == []
    uid = config.resolve_local_user()
    # an EXISTING account now backs it, and it's remembered as the default
    assert auth.get_user(uid) is not None
    assert config.stored_default_user() == uid
    # idempotent: a second resolve returns the same account, no new one created
    assert config.resolve_local_user() == uid
    assert len(auth.list_users()) == 1


def test_sole_account_is_picked_without_a_stored_default(root):
    uid = auth.create_user("solo@example.com", "passwordlong1")
    assert config.stored_default_user() is None
    assert config.resolve_local_user() == uid


def test_stored_default_wins_over_other_accounts(root):
    a = auth.create_user("a@example.com", "passwordlong1")
    auth.create_user("b@example.com", "passwordlong1")
    config.set_default_user(a)
    assert config.resolve_local_user() == a


def test_env_user_by_email_overrides_stored_default(root, monkeypatch):
    a = auth.create_user("a@example.com", "passwordlong1")
    b = auth.create_user("b@example.com", "passwordlong1")
    config.set_default_user(a)
    monkeypatch.setenv("EKLAVYA_USER", "B@Example.com")  # email, mixed case
    assert config.resolve_local_user() == b


def test_env_user_by_uid_resolves(root, monkeypatch):
    a = auth.create_user("a@example.com", "passwordlong1")
    monkeypatch.setenv("EKLAVYA_USER", a)
    assert config.resolve_local_user() == a


def test_unknown_env_user_raises(root, monkeypatch):
    auth.create_user("a@example.com", "passwordlong1")
    monkeypatch.setenv("EKLAVYA_USER", "ghost@example.com")
    with pytest.raises(LookupError):
        config.resolve_local_user()


def test_ambiguous_accounts_without_default_raises(root):
    auth.create_user("a@example.com", "passwordlong1")
    auth.create_user("b@example.com", "passwordlong1")
    assert config.stored_default_user() is None
    with pytest.raises(LookupError):
        config.resolve_local_user()


def test_stale_stored_default_falls_through(root):
    """A stored default pointing at a since-gone uid is ignored (falls to sole/first-run)."""
    config.set_default_user("deadbeef0000")
    uid = auth.create_user("only@example.com", "passwordlong1")
    # the stale default doesn't resolve; the sole real account wins
    assert config.resolve_local_user() == uid


def test_login_logout_default_roundtrip(root):
    uid = auth.create_user("x@example.com", "passwordlong1")
    config.set_default_user(uid)
    assert config.stored_default_user() == uid
    config.clear_default_user()
    assert config.stored_default_user() is None
