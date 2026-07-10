"""Unit tests for the state tools — no LLM, fully deterministic.

We point EKLAVYA_HOME/PROFILE at a temp dir BEFORE importing eklavya, so the real
~/.eklavya database and the shared profile are never touched.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-test-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    # Recreate a clean database before each test.
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_profile_roundtrip():
    assert "first-time" in tools.read_profile()
    tools.save_profile("# Profile\nhello")
    assert tools.read_profile() == "# Profile\nhello"


def test_add_pillar_is_idempotent():
    from eklavya.db import connect

    tools.add_pillar("FastAPI")
    tools.add_pillar("FastAPI")  # second call must not duplicate
    c = connect()
    n = c.execute("SELECT COUNT(*) AS n FROM pillars WHERE name='FastAPI'").fetchone()["n"]
    c.close()
    assert n == 1


def test_set_baseline_rating_creates_pillar_and_cell():
    out = tools.set_baseline_rating("LangGraph", "debugging", "gap")
    assert "LangGraph" in out and "gap" in out
    from eklavya.db import connect

    c = connect()
    row = c.execute(
        "SELECT r.rating FROM ratings r JOIN pillars p ON p.id=r.pillar_id "
        "WHERE p.name='LangGraph' AND r.axis='debugging'"
    ).fetchone()
    c.close()
    assert row["rating"] == tools.LEVELS["gap"]


def test_set_baseline_rating_rejects_bad_axis_and_level():
    assert "unknown axis" in tools.set_baseline_rating("X", "not_an_axis", "gap")
    assert "unknown level" in tools.set_baseline_rating("X", "debugging", "wizardly")


def test_add_goal_and_list():
    tools.add_goal("long", "Become an AI engineer")
    tools.add_goal("short", "Master generators this week", deadline="2026-07-16")
    listed = tools.list_goals()
    assert "Become an AI engineer" in listed
    assert "2026-07-16" in listed
    assert tools.add_goal("someday", "nope").startswith("horizon must be")


def test_mastery_summary_reads_back_levels():
    tools.set_baseline_rating("Python idioms", "syntax_recall", "familiar")
    summary = tools.mastery_summary()
    assert "Python idioms / syntax_recall: familiar" in summary
