"""Curriculum tools + the data-driven forest map (groves, statuses, route)."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-curric-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import report, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_add_get_clear():
    tools.add_curriculum("generators", "", "Python")
    tools.add_curriculum("async", "generators", "Python")
    out = tools.get_curriculum()
    assert "generators" in out and "async ← generators" in out
    tools.clear_curriculum()
    assert "no curriculum" in tools.get_curriculum()


def test_forest_empty():
    assert report.forest_map()["empty"] is True


def test_forest_concept_statuses_track_mastery():
    tools.add_curriculum("generators", "", "Python Fundamentals")
    tools.add_curriculum("async", "generators", "Python Fundamentals")
    fm = report.forest_map("Python Fundamentals")
    st = {c["name"]: c["status"] for c in fm["concepts"]}
    assert st["generators"] == "avail" and st["async"] == "lock"  # gen unlocked, async locked
    # master generators (a correct attempt named 'generators')
    tools.record_attempt("Python idioms", "syntax_recall", "generators", 2, True)
    fm2 = report.forest_map("Python Fundamentals")
    st2 = {c["name"]: c["status"] for c in fm2["concepts"]}
    assert st2["generators"] == "done" and st2["async"] == "avail"  # gen done → async unlocks


def test_route():
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    r = TestClient(create_app()).get("/api/forest")
    assert r.status_code == 200 and "empty" in r.json()
