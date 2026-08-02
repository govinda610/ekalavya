"""CLI account binding — `login` / `whoami` / `logout`, the `--user` flag, and the fact
that a bound command routes per-account state to that account's home.

Fully offline, throwaway data roots only — the real ~/.eklavya-data is never touched. Each
test pins its own EKLAVYA_DATA_ROOT and clears the EKLAVYA_HOME "which home" override so the
real data-root account path (not the direct-home shim) is exercised.
"""

import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eklavya import auth, config
from eklavya.cli import app

runner = CliRunner()


@pytest.fixture
def root(monkeypatch):
    """An isolated data root with the EKLAVYA_HOME/USER overrides cleared, so the CLI resolves
    a real data-root account rather than binding a pinned home directly."""
    d = Path(tempfile.mkdtemp(prefix="eklavya-cliacct-"))
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(d))
    monkeypatch.delenv("EKLAVYA_HOME", raising=False)
    monkeypatch.delenv("EKLAVYA_PROFILE", raising=False)
    monkeypatch.delenv("EKLAVYA_USER", raising=False)
    yield d


def test_login_first_run_creates_and_remembers_a_local_account(root):
    assert auth.list_users() == []
    r = runner.invoke(app, ["login"])
    assert r.exit_code == 0, r.output
    users = auth.list_users()
    assert len(users) == 1
    assert config.stored_default_user() == users[0]["id"]
    assert "logged in" in r.output


def test_whoami_reports_the_bound_account(root):
    uid = auth.create_user("solo@example.com", "passwordlong1")
    r = runner.invoke(app, ["whoami"])
    assert r.exit_code == 0, r.output
    assert uid in r.output
    assert "solo@example.com" in r.output
    # the account's data-root home is shown, never ~/.eklavya
    assert str(config.user_home(uid)) in r.output


def test_logout_clears_the_stored_default(root):
    uid = auth.create_user("solo@example.com", "passwordlong1")
    config.set_default_user(uid)
    r = runner.invoke(app, ["logout"])
    assert r.exit_code == 0, r.output
    assert config.stored_default_user() is None


def test_user_flag_selects_the_account_and_wins_over_stored_default(root):
    a = auth.create_user("a@example.com", "passwordlong1")
    b = auth.create_user("b@example.com", "passwordlong1")
    config.set_default_user(a)
    r = runner.invoke(app, ["--user", "b@example.com", "whoami"])
    assert r.exit_code == 0, r.output
    assert b in r.output and "b@example.com" in r.output


def test_ambiguous_accounts_fail_cleanly_without_a_default(root):
    auth.create_user("a@example.com", "passwordlong1")
    auth.create_user("b@example.com", "passwordlong1")
    r = runner.invoke(app, ["whoami"])
    assert r.exit_code == 1
    assert "multiple accounts" in r.output


def test_bound_command_routes_state_to_the_selected_account_home(root):
    """A per-account command binds the resolved account, so state lands under THAT account's
    data-root home — isolated between accounts, never in ~/.eklavya."""
    a = auth.create_user("a@example.com", "passwordlong1")
    b = auth.create_user("b@example.com", "passwordlong1")

    r = runner.invoke(app, ["--user", "a@example.com", "init"])
    assert r.exit_code == 0, r.output

    a_db = config.user_home(a) / "workspace" / "eklavya.db"
    b_db = config.user_home(b) / "workspace" / "eklavya.db"
    assert a_db.exists()
    # b's home was never created by a's command
    assert not b_db.exists()
