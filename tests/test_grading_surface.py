"""The tamper-proof grading contract.

The model must NOT be able to stamp a rating/attempt directly: `record_attempt` (which
takes a model-supplied `correct` boolean) is an INTERNAL function only the graders call,
so it is deliberately absent from every agent-facing toolset. The graded wrappers
(grade_and_record / grade_and_record_subject / grade_rubric) are the only write path.
"""

import json
import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-grade-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import tools  # noqa: E402


@pytest.fixture
def fresh_db_for_assessment():
    """A clean, seeded DB so the assessment-isolation test starts from zero state."""
    from eklavya import config as _cfg
    from eklavya.db import init_db

    db = _cfg.DB_PATH
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            p.unlink()
    init_db()  # seeds the frozen benchmark banks
    yield


def _tool_names(toolset):
    names = set()
    for t in toolset:
        names.add(getattr(t, "name", None) or getattr(t, "__name__", None))
    return names


def test_record_attempt_not_agent_facing():
    names = _tool_names(tools.AGENT_TOOLS)
    assert "record_attempt" not in names
    # It stays importable as an internal function the graders call.
    assert callable(tools.record_attempt)


def test_agent_facing_write_path_is_only_graders():
    names = _tool_names(tools.AGENT_TOOLS)
    assert {"grade_and_record", "grade_and_record_subject", "grade_rubric"} <= names


def test_shared_mode_toolsets_also_exclude_record_attempt():
    for toolset in (tools.ONBOARDING_TOOLS, tools.SESSION_TOOLS, tools.AIINTERVIEW_TOOLS):
        assert "record_attempt" not in _tool_names(toolset)


# --- P0-C: the frozen benchmark must not contaminate the teaching grid --------

def test_assessment_toolset_excludes_the_teaching_graders():
    names = _tool_names(tools.ASSESSMENT_TOOLS)
    # The objective, grid-free grader is present; the Elo/XP/streak-awarding graders are not.
    assert "grade_assessment_item" in names
    assert "grade_and_record" not in names
    assert "grade_and_record_subject" not in names
    assert "grade_rubric" not in names


def _grid_snapshot():
    """Everything a sitting must NOT move: ratings, XP, streak, attempts."""
    from eklavya import progress
    from eklavya.db import connect

    conn = connect()
    try:
        ratings = conn.execute(
            "SELECT pillar_id, axis, subject, rating FROM ratings ORDER BY pillar_id, axis"
        ).fetchall()
        n_attempts = conn.execute("SELECT COUNT(*) c FROM attempts").fetchone()["c"]
    finally:
        conn.close()
    s = progress.stats()
    return {"ratings": [tuple(r) for r in ratings], "attempts": n_attempts,
            "xp": s["xp"], "streak": s["streak"]}


def test_sitting_an_assessment_does_not_touch_ratings_xp_streak(fresh_db_for_assessment):
    from eklavya import progress
    from eklavya.db import connect

    # Give the grid some real state first, so "unchanged" is a meaningful assertion.
    tools.record_attempt("Python", "recall", "warm-up", 3, True)
    progress.touch_streak()
    before = _grid_snapshot()
    assert before["attempts"] >= 1 and before["xp"] > 0

    # Draw + objectively grade a few frozen items (deterministic ones), then record the sitting.
    conn = connect()
    try:
        from eklavya import benchmark
        items = benchmark.select_items(conn, n=4, subject="maths")
    finally:
        conn.close()
    assert items, "expected seeded maths benchmark items"

    outcomes = []
    for it in items:
        verdict = json.loads(tools.grade_assessment_item(
            answer=str(it["answer"]), answer_type=it["answer_type"],
            key=str(it["answer"]), tolerance=it["tolerance"] or ""))
        outcomes.append({"item_id": it["id"], "difficulty": it["difficulty"],
                         "correct": verdict["correct"], "seconds": 5.0,
                         "score": verdict["score"]})
    out = tools.record_assessment(outcomes, context="baseline", subject="maths")
    assert "θ" in out

    after = _grid_snapshot()
    assert after["ratings"] == before["ratings"]
    assert after["attempts"] == before["attempts"]
    assert after["xp"] == before["xp"]
    assert after["streak"] == before["streak"]

    # And the sitting DID land in the assessment tables (it's recorded, just not on the grid).
    conn = connect()
    try:
        n_assess = conn.execute("SELECT COUNT(*) c FROM assessments").fetchone()["c"]
        n_resp = conn.execute("SELECT COUNT(*) c FROM assessment_responses").fetchone()["c"]
    finally:
        conn.close()
    assert n_assess == 1 and n_resp == len(outcomes)
