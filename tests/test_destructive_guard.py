"""The destructive-op guard: never wipe the real store unbound, always snapshot first.

This locks in the fix for the incident where an unscoped ``save_baseline(
replace_curriculum=True)`` clobbered the real single-user curriculum with no backup.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-guard-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import backups, config, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db = config.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_clear_curriculum_snapshots_before_wiping():
    """A wipe against a (temp) bound-by-env home is allowed AND backed up first."""
    tools.add_curriculum("generators", "", "Python")
    before = len(backups.list_snapshots())
    tools.clear_curriculum()
    after = backups.list_snapshots()
    assert len(after) == before + 1, "a snapshot must be taken before the delete"
    assert "no curriculum" in tools.get_curriculum()
    # the snapshot captured the pre-wipe state (its db still has the concept)
    assert after[0]["reason"].startswith("before clear_curriculum")


def test_save_baseline_replace_snapshots_before_wiping():
    tools.add_curriculum("old-concept", "", "Python")
    before = len(backups.list_snapshots())
    tools.save_baseline(curriculum=[{"concept": "new-concept"}], replace_curriculum=True)
    assert len(backups.list_snapshots()) == before + 1
    out = tools.get_curriculum()
    assert "new-concept" in out and "old-concept" not in out


def test_guard_refuses_real_home_when_unbound(monkeypatch):
    """The exact incident: no user home bound + resolving to the real ~/.eklavya.

    Must raise BEFORE any delete or snapshot, so the real store is never touched.
    """
    # Simulate the unscoped-script situation: default home == the real ~/.eklavya.
    monkeypatch.setattr(config, "_default_home", lambda: Path.home() / ".eklavya")
    monkeypatch.delenv("EKLAVYA_ALLOW_DESTRUCTIVE", raising=False)
    config._current_home.set(None)  # nothing bound
    with pytest.raises(RuntimeError, match="Refusing"):
        tools.clear_curriculum()


def test_guard_allows_real_home_with_explicit_flag(monkeypatch, tmp_path):
    """With the explicit override flag the op proceeds (pointed at a temp dir, not real)."""
    monkeypatch.setattr(config, "_default_home", lambda: tmp_path)  # not the real home
    monkeypatch.setenv("EKLAVYA_ALLOW_DESTRUCTIVE", "1")
    config._current_home.set(None)
    (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)
    init_db()
    tools.clear_curriculum()  # should not raise
