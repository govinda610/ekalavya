"""First-class PREFERENCES memory (task #88): remember/recall + per-session injection."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-prefs-")
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


def test_remember_and_recall_roundtrip():
    tools.remember_preference("teaching_style", "teach by typing code in, not pasting")
    tools.remember_preference("spoilers", "no spoilers")
    out = tools.recall_preferences()
    assert "teaching_style: teach by typing code in, not pasting" in out
    assert "spoilers: no spoilers" in out


def test_remember_is_an_upsert_on_key():
    tools.remember_preference("pace", "slow")
    tools.remember_preference("pace", "fast, one drill after another")
    conn = connect()
    rows = conn.execute("SELECT key, value FROM learning_prefs").fetchall()
    conn.close()
    assert len(rows) == 1                                   # updated, not duplicated
    assert rows[0]["value"] == "fast, one drill after another"


def test_empty_key_ignored():
    tools.remember_preference("   ", "whatever")
    assert tools.recall_preferences() == "(no learning preferences saved yet)"


def test_recall_when_none():
    assert tools.recall_preferences() == "(no learning preferences saved yet)"


def test_tools_registered_in_shared_toolset():
    assert tools.remember_preference in tools.AGENT_TOOLS
    assert tools.recall_preferences in tools.AGENT_TOOLS


def test_preferences_injected_into_session_context():
    # no prefs yet → no preferences block, session context unaffected
    assert report.preferences_block() == ""
    plain = report.with_session_context("write a generator")
    assert "[Learner preferences" not in plain

    tools.remember_preference("examples", "examples-first")
    tools.remember_preference("spoilers", "no spoilers")
    block = report.preferences_block()
    assert block.startswith("[Learner preferences —")
    assert "examples: examples-first" in block and "spoilers: no spoilers" in block

    # every surface's turn now carries the prefs block right after the session-context line
    turn = report.with_session_context("write a generator")
    assert turn.startswith("[session context —")
    assert "[Learner preferences —" in turn
    assert turn.rstrip().endswith("write a generator")


def test_injected_block_is_stripped_from_transcript_and_titles():
    """The private preferences block, like the session-context line, must never leak into the
    learner-visible transcript or a chat title."""
    from eklavya import chatstore
    ctx = "[session context — session #3 · today is Fri 2026-08-01]"
    prefs = "[Learner preferences — examples: examples-first]"
    combined = ctx + "\n" + prefs + "\n\nExplain closures."
    assert chatstore._strip_ctx(combined) == "Explain closures."
    # prefs-only (no session line) is also stripped
    assert chatstore._strip_ctx(prefs + "\n\nExplain closures.") == "Explain closures."
