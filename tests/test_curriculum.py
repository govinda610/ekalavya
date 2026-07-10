"""Curriculum graph tests — tools, the Mermaid render with mastery colouring, route."""

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


def test_mermaid_empty():
    assert report.curriculum_mermaid()["empty"] is True


def test_mermaid_status_colours_by_mastery():
    tools.add_curriculum("generators", "")
    tools.add_curriculum("async", "generators")
    m = report.curriculum_mermaid()["mermaid"]
    assert "graph TD" in m and ":::avail" in m and ":::lock" in m  # gen avail, async locked
    # master generators (a correct attempt named 'generators')
    tools.record_attempt("Python idioms", "syntax_recall", "generators", 2, True)
    m2 = report.curriculum_mermaid()["mermaid"]
    assert ":::done" in m2  # generators is now mastered → async unlocks


def test_route():
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    r = TestClient(create_app()).get("/api/curriculum")
    assert r.status_code == 200 and "empty" in r.json()
