"""Learner feedback capture — record() then recent()/summary() shape + values."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-feedback-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import feedback  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_summary_empty_db():
    """No data yet → zeros/empty, and JSON-serialisable (no None-crashes downstream)."""
    s = feedback.summary()
    assert s["total"] == 0
    assert s["rated"] == 0
    assert s["avg_rating"] is None
    assert s["by_mode"] == {}
    assert feedback.recent() == []


def test_record_then_recent_shape():
    feedback.record("drill", rating=5, concept="list comprehension", mode="practice", thread="t1")
    rows = feedback.recent()
    assert len(rows) == 1
    r = rows[0]
    assert set(r) >= {"id", "kind", "rating", "text", "concept", "mode", "thread", "created_at"}
    assert r["kind"] == "drill"
    assert r["rating"] == 5
    assert r["concept"] == "list comprehension"
    assert r["mode"] == "practice"
    assert r["thread"] == "t1"


def test_summary_average_across_ratings():
    """Two ratings (5 and 1) → overall average 3.0, counted per mode."""
    feedback.record("drill", rating=5, mode="practice")
    feedback.record("drill", rating=1, mode="practice")
    s = feedback.summary()
    assert s["total"] == 2
    assert s["rated"] == 2
    assert s["avg_rating"] == 3.0
    assert s["by_mode"]["practice"]["count"] == 2
    assert s["by_mode"]["practice"]["avg_rating"] == 3.0


def test_text_only_does_not_drag_average():
    """A text-only note (no rating) counts toward total but not the average."""
    feedback.record("freeform", text="loved it")
    feedback.record("drill", rating=4, mode="blitz")
    s = feedback.summary()
    assert s["total"] == 2
    assert s["rated"] == 1
    assert s["avg_rating"] == 4.0
    assert "blitz" in s["by_mode"]


def test_rating_clamped_and_unknown_kind():
    feedback.record("drill", rating=99, mode="practice")   # clamped to 5
    feedback.record("bogus", rating=2)                    # kind → freeform
    rows = {r["kind"]: r["rating"] for r in feedback.recent()}
    assert rows["drill"] == 5
    assert rows["freeform"] == 2


def test_recent_order_and_limit():
    for i in range(5):
        feedback.record("drill", rating=(i % 5) + 1, mode="practice")
    rows = feedback.recent(limit=3)
    assert len(rows) == 3
    # newest first
    assert rows[0]["id"] > rows[-1]["id"]
