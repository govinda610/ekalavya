"""Deterministic graders + the subject-aware record dispatcher (subject framework §5).

These graders have NO LLM in the loop, so they must be exactly as tamper-proof as the
code sandbox: the grader decides truth, the model can't. We test the maths cases that
matter (tolerance, symbolic equivalence of different-looking-but-equal forms) and the
end-to-end grade_and_record_subject path that lands a fractional score on the right cell.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-graders-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import graders, tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            p.unlink()
    init_db()
    yield


# --- numeric ---------------------------------------------------------------

def test_numeric_exact_and_tolerance():
    assert graders.grade_numeric("42", "42").score == 1.0
    assert graders.grade_numeric("42.0001", "42").score == 0.0          # exact, no tol
    assert graders.grade_numeric("42.0001", "42", tol=0.001).score == 1.0
    assert graders.grade_numeric("3.14", "3.14159", rel=0.01).score == 1.0
    assert graders.grade_numeric("100", "3.14159").score == 0.0


def test_numeric_percent_and_scientific_and_words():
    assert graders.grade_numeric("50%", "0.5").score == 1.0
    assert graders.grade_numeric("1.5e3", "1500").score == 1.0
    assert graders.grade_numeric("the answer is 7", "7").score == 1.0
    assert graders.grade_numeric("no number here", "7").score == 0.0


# --- symbolic --------------------------------------------------------------

def test_symbolic_accepts_equivalent_forms():
    assert graders.grade_symbolic("(x+1)^2", "x^2 + 2*x + 1").score == 1.0
    assert graders.grade_symbolic("sin(x)^2 + cos(x)^2", "1").score == 1.0
    assert graders.grade_symbolic("2*x + 2", "2*(x+1)").score == 1.0


def test_symbolic_rejects_wrong_answer():
    assert graders.grade_symbolic("x^2 + 2*x + 2", "x^2 + 2*x + 1").score == 0.0
    assert graders.grade_symbolic("nonsense((", "x").score == 0.0


# --- units -----------------------------------------------------------------

def test_units_dimension_and_magnitude():
    assert graders.grade_units("300 cm", "3 m").score == 1.0        # same magnitude, diff unit
    assert graders.grade_units("3 meter/second", "3 m/s").score == 1.0
    assert graders.grade_units("3 m", "3 s").score == 0.0           # dimension mismatch
    assert graders.grade_units("5 m", "3 m").score == 0.0           # magnitude mismatch


# --- choice ----------------------------------------------------------------

def test_choice_key_match_lenient_and_pipe_list():
    assert graders.grade_choice("B", "b").score == 1.0
    assert graders.grade_choice("WHERE.", "where").score == 1.0
    assert graders.grade_choice("beta", "b|B|beta").score == 1.0
    assert graders.grade_choice("q", "b|beta").score == 0.0


# --- dispatcher ------------------------------------------------------------

def test_dispatch_routes_by_answer_type():
    assert graders.grade("42", {"answer_type": "numeric", "answer": "42"}).score == 1.0
    assert graders.grade("x+x", {"answer_type": "symbolic", "answer": "2*x"}).score == 1.0
    assert graders.grade("a", {"answer_type": "choice", "answer": "a"}).score == 1.0
    with pytest.raises(ValueError):
        graders.grade("a proof", {"answer_type": "proof", "answer": "ref"})


def test_dispatch_numeric_tolerance_from_json():
    r = graders.grade("42.05", {"answer_type": "numeric", "answer": "42", "tolerance": '{"abs": 0.1}'})
    assert r.score == 1.0


# --- end-to-end tamper-proof record ---------------------------------------

def test_grade_and_record_subject_lands_on_the_right_cell():
    out = tools.grade_and_record_subject(
        "Algebra", "symbolic_manipulation", "expand a square",
        answer="x^2 + 2*x + 1", key="(x+1)^2", answer_type="symbolic",
        confidence=2, subject="maths")
    assert "PASS" in out
    conn = connect()
    try:
        a = conn.execute(
            "SELECT subject, answer_type, correct, score FROM attempts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        r = conn.execute(
            "SELECT r.subject, r.axis FROM ratings r JOIN pillars p ON p.id=r.pillar_id "
            "WHERE p.name='Algebra'").fetchone()
    finally:
        conn.close()
    assert a["subject"] == "maths" and a["answer_type"] == "symbolic"
    assert a["correct"] == 1 and a["score"] == 1.0
    assert r["subject"] == "maths" and r["axis"] == "symbolic_manipulation"


def test_grade_and_record_subject_records_a_fail_the_model_cannot_fake():
    # The grader says wrong; the recorded outcome is FAIL regardless of any claim.
    out = tools.grade_and_record_subject(
        "Algebra", "application", "add", answer="5", key="7",
        answer_type="numeric", confidence=3, subject="maths")
    assert "FAIL" in out
    conn = connect()
    try:
        a = conn.execute("SELECT correct, score FROM attempts ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert a["correct"] == 0 and a["score"] == 0.0


def test_grade_and_record_subject_threads_ai_off():
    """ai_off must be recorded, not hardcoded: an assisted non-code answer records
    ai_off=0 so it isn't miscounted as unaided; the default stays ai_off=1."""
    tools.grade_and_record_subject(
        "Algebra", "application", "add", answer="7", key="7",
        answer_type="numeric", confidence=2, subject="maths", ai_off=False)
    conn = connect()
    try:
        assisted = conn.execute(
            "SELECT ai_off FROM attempts ORDER BY id DESC LIMIT 1").fetchone()["ai_off"]
    finally:
        conn.close()
    assert assisted == 0    # honestly tagged as assisted

    tools.grade_and_record_subject(
        "Algebra", "application", "add", answer="7", key="7",
        answer_type="numeric", confidence=2, subject="maths")  # default
    conn = connect()
    try:
        unaided = conn.execute(
            "SELECT ai_off FROM attempts ORDER BY id DESC LIMIT 1").fetchone()["ai_off"]
    finally:
        conn.close()
    assert unaided == 1    # default is unaided


def test_grade_and_record_subject_rejects_non_deterministic_type():
    out = tools.grade_and_record_subject(
        "Proofs", "derivation_proof", "induction", answer="...", key="...",
        answer_type="proof", confidence=2, subject="maths")
    assert "deterministic" in out.lower()


def test_symbolic_grader_refuses_over_long_input():
    # A symbolic bomb (huge/nested expression) is refused before parsing, not stalled.
    bomb = "(" * 300 + "x" + ")" * 300
    res = graders.grade_symbolic(bomb, "x")
    assert res.score == 0.0
    assert "could not parse" in res.detail


def test_symbolic_grader_still_grades_normal_answers():
    # The guard doesn't break ordinary, short equivalence checks.
    assert graders.grade_symbolic("(x+1)^2", "x^2 + 2*x + 1").score == 1.0
    assert graders.grade_symbolic("x + 1", "x + 2").score == 0.0
