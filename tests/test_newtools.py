"""The consolidated spine tools: save_baseline (upserts state) + run_bash (workspace)."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-nt-")
os.environ["EKLAVYA_HOME"] = _TMP

import pytest  # noqa: E402

from eklavya import tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402
from eklavya.workspace import workspace_dir  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    if _cfg.DB_PATH.exists():
        _cfg.DB_PATH.unlink()
    init_db()
    yield


def test_save_baseline_persists_all_kinds():
    out = tools.save_baseline(
        pillars=["Python Fundamentals", "DS&A"],
        ratings=[{"pillar": "Python Fundamentals", "axis": "syntax_recall", "level": "familiar"}],
        goals=[{"horizon": "short", "text": "interview ready", "deadline": "2 months"}],
        curriculum=[{"concept": "lists", "pillar": "Python Fundamentals"},
                    {"concept": "dicts", "prereqs": "lists"}],
    )
    assert "2 pillars" in out and "1 ratings" in out and "1 goals" in out and "2 curriculum" in out
    c = connect()
    try:
        assert c.execute("SELECT COUNT(*) n FROM pillars").fetchone()["n"] == 2
        assert c.execute("SELECT COUNT(*) n FROM goals").fetchone()["n"] == 1
        assert c.execute("SELECT COUNT(*) n FROM curriculum").fetchone()["n"] == 2
        assert c.execute("SELECT COUNT(*) n FROM ratings").fetchone()["n"] == 1
    finally:
        c.close()


def test_run_bash_runs_in_the_workspace():
    tools.run_bash("echo hi > marker.txt", "create a marker file to prove cwd")
    assert (workspace_dir() / "marker.txt").exists()


def test_run_bash_can_query_the_db():
    tools.save_baseline(goals=[{"horizon": "short", "text": "crack leetcode"}])
    out = tools.run_bash("sqlite3 eklavya.db 'SELECT text FROM goals'", "read the goals")
    assert "crack leetcode" in out


def test_run_bash_refuses_destructive():
    assert "Refused" in tools.run_bash("rm -rf ~/", "totally not malicious")
