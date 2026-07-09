"""Repo-awareness tests — detection from dependency files + imports, and grant."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-repos-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import repos  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db = Path(_TMP) / "eklavya.db"
    if db.exists():
        db.unlink()
    init_db()
    yield


def _make_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="fake-repo-"))
    (repo / "requirements.txt").write_text("langgraph>=0.2\nfastapi==0.115\n# a comment\n")
    (repo / "app.py").write_text("import numpy as np\nfrom pandas import DataFrame\n")
    return repo


def test_detect_maps_stacks_to_pillars():
    found = repos.detect(_make_repo())
    assert "LangChain / LangGraph" in found["pillars"]
    assert "FastAPI / backend" in found["pillars"]
    assert "pandas / numpy / viz" in found["pillars"]  # from imports
    assert "langgraph" in found["stacks"]


def test_detect_empty_repo():
    empty = Path(tempfile.mkdtemp(prefix="empty-repo-"))
    found = repos.detect(empty)
    assert found["pillars"] == [] and found["stacks"] == []


def test_grant_records_repo():
    repo = _make_repo()
    repos.grant(repo, "langgraph,fastapi", "LangChain / LangGraph")
    c = connect()
    row = c.execute("SELECT stacks FROM repos WHERE path = ?", (str(repo),)).fetchone()
    c.close()
    assert row is not None and "langgraph" in row["stacks"]
