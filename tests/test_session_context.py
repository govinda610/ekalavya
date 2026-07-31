"""Temporal awareness: sitting reuse-vs-new, and the session-context recap line."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-sesctx-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import progress, report, tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh():
    from eklavya import config
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    init_db()
    yield


def test_ensure_session_reuses_active_sitting_then_opens_new_after_idle_gap():
    s1 = progress.ensure_session(30, "practice")
    assert progress.ensure_session(30, "practice") == s1  # still active → reuse

    # simulate leaving: push last_active well past the idle window
    conn = connect()
    conn.execute("UPDATE sessions SET last_active = '2020-01-01T00:00:00+00:00' WHERE id=?", (s1,))
    conn.commit()
    conn.close()

    s2 = progress.ensure_session(30, "practice")
    assert s2 != s1  # a new sitting
    # the stale one was closed out so the gap is measurable
    ended = connect().execute("SELECT ended_at FROM sessions WHERE id=?", (s1,)).fetchone()["ended_at"]
    assert ended is not None


def test_session_context_reports_gap_and_last_topics():
    # session 1: practise a concept, then go idle
    s1 = progress.ensure_session(30, "practice")
    tools.add_pillar("Python Fundamentals")
    tools.record_attempt("Python Fundamentals", "syntax_recall", "list comprehensions", 3, True)
    conn = connect()
    conn.execute("UPDATE sessions SET last_active = '2020-01-01T00:00:00+00:00' WHERE id=?", (s1,))
    conn.commit()
    conn.close()

    # session 2 opens → context should see a big gap and recall session 1's topic
    progress.ensure_session(30, "practice")
    ctx = report.session_context()
    assert ctx["sessions_total"] == 2
    assert ctx["gap_days"] is not None and ctx["gap_days"] > 300
    assert "list comprehensions" in ctx["last_topics"]
    line = report.session_context_line()
    assert line.startswith("[session context —") and "last time:" in line and "today is" in line


def test_with_session_context_prepends_the_line_for_every_surface():
    # the shared helper (used by web + CLI + TUI) prefixes the private briefing to a turn
    out = report.with_session_context("write a generator")
    assert out.startswith("[session context —")
    assert out.rstrip().endswith("write a generator")
    # empty turn (e.g. a kickoff resume) still yields just the line, never a crash
    assert report.with_session_context("").startswith("[session context —")


def test_session_context_empty_when_no_sessions():
    ctx = report.session_context()
    assert ctx["sessions_total"] == 0
    assert ctx["session_elapsed_min"] is None and ctx["gap_days"] is None
    # still yields today's date, so the onboarding agent is never dateless
    assert "today is" in report.session_context_line()
