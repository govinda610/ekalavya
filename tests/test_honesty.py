"""AI/Google honesty tracking (task #85): the assisted/unassisted flag is captured on recorded
attempts via the existing ai_off flag, feeding the AI-off vs AI-on gap — with NO penalty."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-honesty-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import report, tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh():
    from eklavya import config
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    init_db()
    yield


def _ai_off(concept):
    c = connect()
    row = c.execute("SELECT ai_off FROM attempts WHERE detail = ?", (concept,)).fetchone()
    c.close()
    return row["ai_off"]


def test_record_attempt_captures_assisted_flag():
    tools.add_pillar("Python Fundamentals")
    tools.record_attempt("Python Fundamentals", "syntax_recall", "unaided_drill", 3, True,
                         ai_off=True)
    tools.record_attempt("Python Fundamentals", "syntax_recall", "googled_drill", 2, True,
                         ai_off=False)
    assert _ai_off("unaided_drill") == 1        # solved on their own
    assert _ai_off("googled_drill") == 0        # admitted AI/Google → assisted


def test_grade_and_record_threads_ai_off_flag():
    """The code-drill path now carries the honesty flag through to the recorded attempt,
    so 'I looked it up' is captured even for a graded code drill (default stays unaided)."""
    good = "def is_even(n):\n    return n % 2 == 0"
    # default: unaided
    tools.grade_and_record("Python idioms", "debugging", "code_unaided",
                           good, "assert is_even(4) and not is_even(3)",
                           confidence=2, reference=good)
    # learner admitted they used AI → ai_off=False
    tools.grade_and_record("Python idioms", "debugging", "code_assisted",
                           good, "assert is_even(4) and not is_even(3)",
                           confidence=2, reference=good, ai_off=False)
    assert _ai_off("code_unaided") == 1
    assert _ai_off("code_assisted") == 0


def test_assisted_attempts_feed_the_ai_gap_without_penalty():
    """Honest 'I used AI' flags land in the unaided-vs-assisted gap, and carry no XP penalty —
    an assisted correct attempt still awards (non-negative) XP, just tagged assisted."""
    tools.add_pillar("Python Fundamentals")
    # unaided correct + assisted correct
    tools.record_attempt("Python Fundamentals", "syntax_recall", "u1", 3, True, ai_off=True)
    xp_before = tools.progress_report()  # noqa: F841 (just ensure no crash)
    tools.record_attempt("Python Fundamentals", "syntax_recall", "a1", 3, True, ai_off=False)

    gap = report.ai_gap()
    assert gap["unaided_n"] == 1 and gap["assisted_n"] == 1     # both tracked separately
    assert gap["unaided_rate"] == 100 and gap["assisted_rate"] == 100

    # no penalty ledger entry was created by an honest assisted attempt
    c = connect()
    penalties = c.execute("SELECT COUNT(*) n FROM rewards WHERE kind='penalty'").fetchone()["n"]
    c.close()
    assert penalties == 0
