"""Versioned state snapshots — dedup, revert (undoable), and pruning."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-bk-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "workspace" / "profile.md")

import shutil  # noqa: E402

import pytest  # noqa: E402

from eklavya import backups as bk  # noqa: E402
from eklavya import config  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    config.WORKSPACE.mkdir(parents=True, exist_ok=True)
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    init_db()
    shutil.rmtree(config.BACKUPS_DIR, ignore_errors=True)  # deterministic counts
    original = config.PROFILE_PATH.read_text() if config.PROFILE_PATH.exists() else None
    config.PROFILE_PATH.write_text("V1")
    yield
    # restore the shared profile so we don't pollute other test files
    shutil.rmtree(config.BACKUPS_DIR, ignore_errors=True)
    if original is None:
        config.PROFILE_PATH.unlink(missing_ok=True)
    else:
        config.PROFILE_PATH.write_text(original)


def test_snapshot_and_dedup():
    first = bk.snapshot("initial")
    assert first and (config.BACKUPS_DIR / first).exists()
    # nothing changed → snapshot_if_changed is a no-op
    assert bk.snapshot_if_changed("again") is None
    assert len(bk.list_snapshots()) == 1
    # change the profile → a new snapshot is taken
    config.PROFILE_PATH.write_text("V2")
    second = bk.snapshot_if_changed("after edit")
    assert second and second != first
    assert len(bk.list_snapshots()) == 2


def test_revert_restores_and_is_itself_undoable():
    bk.snapshot("state V1")            # captures profile == "V1"
    config.PROFILE_PATH.write_text("V2 corrupted by the model")
    before = len(bk.list_snapshots())

    target = bk.revert()  # default: most recent snapshot (the V1 one)
    assert config.PROFILE_PATH.read_text() == "V1"          # rolled back
    assert target["reason"] == "state V1"
    # revert first snapshotted the current (V2) state, so it grew by one and is undoable
    snaps = bk.list_snapshots()
    assert len(snaps) == before + 1
    assert any("before revert" in s["reason"] for s in snaps)

    bk.revert(snaps[0]["id"])  # the "before revert" snapshot holds V2
    assert "V2 corrupted" in config.PROFILE_PATH.read_text()


def test_prune_keeps_only_last_KEEP():
    for i in range(bk.KEEP + 5):
        config.PROFILE_PATH.write_text(f"state {i}")
        bk.snapshot(f"s{i}")
    assert len(bk.list_snapshots()) == bk.KEEP


def test_run_bash_snapshots_before_executing():
    from eklavya import tools

    assert bk.list_snapshots() == []
    out = tools.run_bash("echo hello", "print a greeting")
    assert "hello" in out
    assert len(bk.list_snapshots()) == 1  # a pre-write snapshot was taken
