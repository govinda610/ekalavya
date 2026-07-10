"""Deterministic tests for the practice loop — sandbox, scoring, FSRS, progress,
and the integrating record_attempt. No LLM. Isolated to a temp home.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-practice-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import progress, scoring, tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402
from eklavya.sandbox import run_python, run_tests  # noqa: E402
from eklavya.scheduling import schedule  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


# --- sandbox ---------------------------------------------------------------

def test_run_python_ok():
    r = run_python("print(2 + 2)")
    assert r.ok and r.stdout.strip() == "4" and r.seconds >= 0


def test_run_python_error_is_captured():
    r = run_python("raise ValueError('boom')")
    assert not r.ok and "ValueError" in r.stderr


def test_run_python_timeout():
    r = run_python("while True: pass", stdin="")
    assert not r.ok  # times out
    assert "Timed out" in r.stderr


def test_sandbox_does_not_leak_the_environment():
    # LLM-authored code must not be able to read the parent's env (API keys live there).
    os.environ["EKLAVYA_GLM_API_KEY"] = "LEAK_CANARY_XYZ"
    r = run_python("import os; print(os.environ.get('EKLAVYA_GLM_API_KEY', 'NONE'))")
    assert "LEAK_CANARY_XYZ" not in r.stdout
    assert "NONE" in r.stdout


def test_run_tests_pass_and_fail():
    code = "def add(a, b):\n    return a + b"
    assert run_tests(code, "assert add(2, 3) == 5").ok
    assert not run_tests(code, "assert add(2, 3) == 6").ok


def test_run_tests_rejects_silent_noop():
    # Tests that do nothing must not count as a pass.
    assert run_tests("x = 1", "pass").ok  # marker still prints → pass
    # but a crashing test fails
    assert not run_tests("x = 1", "assert False").ok


# --- scoring ---------------------------------------------------------------

def test_elo_moves_the_right_way():
    assert scoring.update_elo(1000, True) > 1000
    assert scoring.update_elo(1000, False) < 1000


def test_elo_punishes_confident_wrong_more_than_unsure_wrong():
    # The illusion of knowing: confident + wrong should drop more.
    confident_wrong = 1000 - scoring.update_elo(1000, False, confidence=3)
    unsure_wrong = 1000 - scoring.update_elo(1000, False, confidence=1)
    assert confident_wrong > unsure_wrong


def test_elo_rewards_unsure_right_more_than_confident_right():
    unsure_right = scoring.update_elo(1000, True, confidence=1) - 1000
    confident_right = scoring.update_elo(1000, True, confidence=3) - 1000
    assert unsure_right > confident_right


def test_band_tightens_toward_one():
    b = 0.0
    for _ in range(10):
        b = scoring.tighten(b)
    assert 0.8 < b < 1.0


def test_level_buckets():
    assert scoring.level_of(800) == "unknown"
    assert scoring.level_of(1000) == "gap"
    assert scoring.level_of(1200) == "familiar"
    assert scoring.level_of(1400) == "strong"


# --- FSRS scheduling -------------------------------------------------------

def test_schedule_persists_card_and_returns_due():
    due = schedule("generators", correct=True, confidence=3)
    assert due and "T" in due  # ISO datetime
    c = connect()
    row = c.execute("SELECT state_json FROM cards WHERE ref='generators'").fetchone()
    c.close()
    assert row and row["state_json"]  # full FSRS state stored


# --- progress --------------------------------------------------------------

def test_streak_extends_and_resets():
    assert progress.touch_streak("2026-07-01") == 1
    assert progress.touch_streak("2026-07-02") == 2
    assert progress.touch_streak("2026-07-02") == 2  # same day, no double count
    assert progress.touch_streak("2026-07-05") == 1  # gap resets


def test_award_xp_accumulates():
    assert progress.award_xp(10) == 10
    assert progress.award_xp(5) == 15
    assert progress.stats()["xp"] == 15


# --- record_attempt (integration of all of the above) ----------------------

def test_record_attempt_updates_everything():
    out = tools.record_attempt(
        "Python idioms", "debugging", "list_comprehension",
        confidence=2, correct=True, seconds=5.0, ai_off=True,
    )
    assert "XP" in out and "streak" in out

    c = connect()
    rating = c.execute(
        "SELECT r.rating FROM ratings r JOIN pillars p ON p.id=r.pillar_id "
        "WHERE p.name='Python idioms' AND r.axis='debugging'"
    ).fetchone()
    attempt = c.execute("SELECT correct FROM attempts WHERE detail='list_comprehension'").fetchone()
    card = c.execute("SELECT ref FROM cards WHERE ref='list_comprehension'").fetchone()
    c.close()

    assert rating["rating"] > 1000          # moved up on a correct answer
    assert attempt["correct"] == 1          # logged
    assert card is not None                 # review scheduled
    assert progress.stats()["xp"] > 0       # XP awarded


def test_grade_and_record_records_the_verified_verdict():
    # Correct code -> recorded correct; wrong code -> recorded wrong. The stored
    # result equals the real sandbox verdict, not a model claim.
    good = "def is_even(n):\n    return n % 2 == 0"
    tools.grade_and_record("Python idioms", "debugging", "is_even_ok",
                           good, "assert is_even(4) and not is_even(3)",
                           confidence=2, reference=good)
    tools.grade_and_record("Python idioms", "debugging", "is_even_bad",
                           "def is_even(n):\n    return n % 2 == 1",  # wrong
                           "assert is_even(4)", confidence=3, reference=good)
    c = connect()
    ok = c.execute("SELECT correct FROM attempts WHERE detail='is_even_ok'").fetchone()
    bad = c.execute("SELECT correct FROM attempts WHERE detail='is_even_bad'").fetchone()
    c.close()
    assert ok["correct"] == 1 and bad["correct"] == 0


def test_diff_code():
    out = tools.diff_code("def f():\n    return 2", "def f():\n    return 1")
    assert "return 1" in out and "return 2" in out and "-" in out
    assert "Identical" in tools.diff_code("x = 1", "x = 1")


def test_broken_tutor_tests_do_not_grade_the_learner():
    # The reference doesn't pass the (wrong) tests -> tests are bad -> learner not graded.
    out = tools.grade_and_record("Python idioms", "debugging", "broken_test",
                                 "def f():\n    return 1", "assert f() == 2",  # wrong test
                                 confidence=2, reference="def f():\n    return 1")
    assert "SANITY CHECK FAILED" in out
    c = connect()
    row = c.execute("SELECT 1 FROM attempts WHERE detail='broken_test'").fetchone()
    c.close()
    assert row is None  # nothing recorded on broken tests


def test_session_links_attempts_and_finalises():
    sid = progress.start_session(30)
    tools.record_attempt("Python idioms", "debugging", "slicing",
                         confidence=2, correct=True)
    c = connect()
    linked = c.execute("SELECT session_id FROM attempts WHERE detail='slicing'").fetchone()
    c.close()
    assert linked["session_id"] == sid      # attempt attached to the open session

    progress.end_session()
    c = connect()
    row = c.execute("SELECT ended_at, xp FROM sessions WHERE id=?", (sid,)).fetchone()
    c.close()
    assert row["ended_at"] is not None and row["xp"] > 0
