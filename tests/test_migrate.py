"""Guarded single-user → multi-user migration: copy, verify parity, stamp, don't destroy."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-mig-src-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "workspace" / "profile.md")

import pytest  # noqa: E402

from eklavya import config, migrate, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def seeded_single_user():
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    init_db()
    tools.add_pillar("Python")
    tools.set_baseline_rating("Python", "debugging", "strong")
    tools.add_goal("short", "ace the interview")
    tools.add_curriculum("Recursion", "", "Python")
    tools.save_profile("# me\nhello")
    yield


def test_migration_copies_verifies_and_stamps(monkeypatch, tmp_path):
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(tmp_path / "data"))
    uid = "user123abc"
    source = config._default_home()
    report = migrate.migrate_single_user(uid)
    dest = tmp_path / "data" / "users" / uid
    # original untouched
    assert (source / "workspace" / "eklavya.db").exists()
    # dest carries identical data
    assert dest.exists()
    assert report["tables"]["pillars"] == 1
    assert report["tables"]["ratings"] == 1
    assert report["tables"]["curriculum"] == 1
    assert report["profile_ok"] and report["checkpoints_ok"]
    assert (dest / "workspace" / "profile.md").read_text() == "# me\nhello"


def test_refuses_to_overwrite_nonempty_dest(monkeypatch, tmp_path):
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(tmp_path / "data"))
    uid = "u2"
    dest = tmp_path / "data" / "users" / uid
    dest.mkdir(parents=True)
    (dest / "x").write_text("existing")
    with pytest.raises(FileExistsError):
        migrate.migrate_single_user(uid)


def test_dry_run_leaves_no_dest(monkeypatch, tmp_path):
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(tmp_path / "data"))
    uid = "u3"
    report = migrate.migrate_single_user(uid, dry_run=True)
    assert report["dry_run"] is True
    assert not (tmp_path / "data" / "users" / uid).exists()
