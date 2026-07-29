"""Guarded single-user → multi-user migration: copy, verify parity, stamp, don't destroy.

Uses per-test monkeypatch env isolation (NOT module-level os.environ) so it can't leak
EKLAVYA_HOME/PROFILE into other test modules.
"""

import pytest

from eklavya import migrate, tools
from eklavya.db import init_db


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    home = tmp_path / "eklavya"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("EKLAVYA_HOME", str(home))
    monkeypatch.setenv("EKLAVYA_PROFILE", str(home / "workspace" / "profile.md"))
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(tmp_path / "data"))
    init_db()
    tools.add_pillar("Python")
    tools.set_baseline_rating("Python", "debugging", "strong")
    tools.add_goal("short", "ace the interview")
    tools.add_curriculum("Recursion", "", "Python")
    tools.save_profile("# me\nhello")
    return home


def test_migration_copies_verifies_and_stamps(seeded, tmp_path):
    uid = "user123abc"
    report = migrate.migrate_single_user(uid)
    dest = tmp_path / "data" / "users" / uid
    assert (seeded / "workspace" / "eklavya.db").exists()  # original untouched
    assert dest.exists()
    assert report["tables"]["pillars"] == 1
    assert report["tables"]["ratings"] == 1
    assert report["tables"]["curriculum"] == 1
    assert report["profile_ok"] and report["checkpoints_ok"]
    assert (dest / "workspace" / "profile.md").read_text() == "# me\nhello"


def test_refuses_to_overwrite_nonempty_dest(seeded, tmp_path):
    uid = "u2"
    dest = tmp_path / "data" / "users" / uid
    dest.mkdir(parents=True)
    (dest / "x").write_text("existing")
    with pytest.raises(FileExistsError):
        migrate.migrate_single_user(uid)


def test_dry_run_leaves_no_dest(seeded, tmp_path):
    uid = "u3"
    report = migrate.migrate_single_user(uid, dry_run=True)
    assert report["dry_run"] is True
    assert not (tmp_path / "data" / "users" / uid).exists()
