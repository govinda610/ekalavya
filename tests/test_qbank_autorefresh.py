"""Automatic background question-bank refresh at session start.

Covers the maybe_autorefresh() contract:
  - throttled: a second call inside the window is a no-op;
  - offline-safe: no web-search key → clean no-op (no thread, no error);
  - non-blocking: progress.start_session triggers it on a BACKGROUND thread, never the
    caller's thread, and always returns the session id;
  - multi-user: the background thread runs in the CURRENT user's context, so it writes
    that user's db (throttle stamp + questions), not a global one.

Fully offline, temp homes only — the real ~/.eklavya is never touched.
"""

import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-qa-")
os.environ["EKLAVYA_HOME"] = _TMP

import pytest  # noqa: E402

from eklavya import config, progress, questions_refresh, tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402


@contextmanager
def as_user(home: Path):
    from eklavya.config import _current_home

    token = _current_home.set(home)
    try:
        config.ensure_home()
        init_db()
        yield
    finally:
        _current_home.reset(token)


@pytest.fixture
def home():
    h = Path(tempfile.mkdtemp(prefix="eklavya-qa-user-"))
    with as_user(h):
        yield h


@pytest.fixture(autouse=True)
def _pretend_online(monkeypatch):
    """Default to 'a key is present' so tests exercise the real path; the offline test
    overrides this. No network is ever hit — `refresh` is stubbed in each test."""
    monkeypatch.setattr(tools, "has_web_search_key", lambda: True)
    # Clear any leftover in-flight guard between tests (process-global set).
    with questions_refresh._inflight_lock:
        questions_refresh._inflight.clear()


def _last_stamp():
    conn = connect()
    try:
        return progress._get(conn, questions_refresh._REFRESHED_AT_KEY)
    finally:
        conn.close()


# --- offline safety ---------------------------------------------------------

def test_offline_no_key_is_a_clean_noop(home, monkeypatch):
    monkeypatch.setattr(tools, "has_web_search_key", lambda: False)
    called = threading.Event()
    monkeypatch.setattr(questions_refresh, "refresh",
                        lambda **k: called.set() or {"added": 0})
    assert questions_refresh.maybe_autorefresh() is False
    assert not called.wait(0.5)          # no background work was spawned
    assert _last_stamp() is None         # and nothing was stamped


# --- throttle ---------------------------------------------------------------

def test_throttle_prevents_a_second_refresh_in_the_window(home, monkeypatch):
    calls = []
    done = threading.Event()

    def fake_refresh(**kw):
        calls.append(kw)
        done.set()
        return {"added": 1}

    monkeypatch.setattr(questions_refresh, "refresh", fake_refresh)

    # first call: spawns a refresh and stamps the timestamp
    assert questions_refresh.maybe_autorefresh() is True
    assert done.wait(2.0), "background refresh should have run"
    _join_refresh_threads()
    assert _last_stamp() is not None
    first_count = len(calls)
    assert first_count >= 1

    # second call immediately after: throttled → no-op, no new refresh
    assert questions_refresh.maybe_autorefresh() is False
    assert len(calls) == first_count


def test_expired_throttle_allows_a_refresh_again(home, monkeypatch):
    # stamp a refresh well outside the window
    old = (datetime.now(timezone.utc)
           - timedelta(hours=questions_refresh.REFRESH_INTERVAL_HOURS + 1))
    conn = connect()
    try:
        progress._set(conn, questions_refresh._REFRESHED_AT_KEY,
                      old.isoformat(timespec="seconds"))
        conn.commit()
    finally:
        conn.close()

    done = threading.Event()
    monkeypatch.setattr(questions_refresh, "refresh",
                        lambda **k: done.set() or {"added": 1})
    assert questions_refresh.maybe_autorefresh() is True
    assert done.wait(2.0)


def test_throttled_helper_reads_the_meta_stamp(home):
    assert questions_refresh._throttled() is False           # nothing stamped yet
    questions_refresh._stamp_refreshed()
    assert questions_refresh._throttled() is True            # just stamped → within window


# --- non-blocking session start ---------------------------------------------

def test_start_session_triggers_refresh_on_a_background_thread(home, monkeypatch):
    seen = {}
    done = threading.Event()

    def fake_refresh(**kw):
        seen["thread"] = threading.current_thread()
        done.set()
        return {"added": 0}

    monkeypatch.setattr(questions_refresh, "refresh", fake_refresh)

    sid = progress.start_session(30, mode="practice")
    assert isinstance(sid, int) and sid > 0        # session opened, not blocked

    assert done.wait(2.0), "start_session should have kicked off a background refresh"
    assert seen["thread"] is not threading.main_thread()   # ran OFF the caller's thread


def test_start_session_never_raises_if_refresh_explodes(home, monkeypatch):
    def boom(**kw):
        raise RuntimeError("search provider down")

    monkeypatch.setattr(questions_refresh, "refresh", boom)
    # even though every target's refresh raises, the session still starts cleanly
    sid = progress.start_session(30, mode="practice")
    assert isinstance(sid, int) and sid > 0
    _join_refresh_threads()   # let the daemon finish swallowing the error


# --- multi-user context propagation -----------------------------------------

def test_background_thread_writes_the_current_users_db():
    """The refresh must stamp + write the db of the user who started the session, not a
    global one. We run maybe_autorefresh under user A's context and assert A's db got the
    stamp while user B's db stays untouched."""
    home_a = Path(tempfile.mkdtemp(prefix="eklavya-qa-A-"))
    home_b = Path(tempfile.mkdtemp(prefix="eklavya-qa-B-"))

    seen_db = {}
    done = threading.Event()

    def fake_refresh(**kw):
        # capture which user's db this thread resolves to
        seen_db["path"] = str(config.paths().db)
        done.set()
        return {"added": 0}

    import unittest.mock as mock
    with mock.patch.object(questions_refresh, "refresh", fake_refresh), \
         mock.patch.object(tools, "has_web_search_key", lambda: True):
        with questions_refresh._inflight_lock:
            questions_refresh._inflight.clear()
        with as_user(home_a):
            assert questions_refresh.maybe_autorefresh() is True
            assert done.wait(2.0)
            _join_refresh_threads()
            # the thread saw A's db, and A's stamp is set
            assert seen_db["path"] == str((home_a / "workspace" / "eklavya.db"))
            conn = connect()
            try:
                stamp_a = progress._get(conn, questions_refresh._REFRESHED_AT_KEY)
            finally:
                conn.close()
            assert stamp_a is not None

    # B's db was never stamped by A's refresh
    with as_user(home_b):
        conn = connect()
        try:
            stamp_b = progress._get(conn, questions_refresh._REFRESHED_AT_KEY)
        finally:
            conn.close()
        assert stamp_b is None


# --- target derivation -------------------------------------------------------

def test_derive_targets_falls_back_to_generic_when_no_profile(home):
    targets = questions_refresh.derive_targets()
    assert targets, "must always yield at least one target"
    assert len(targets) <= questions_refresh._MAX_TARGETS
    # generic fallback → an AI-engineer-flavoured pull
    assert any("engineer" in (t["role"] or "").lower() for t in targets)


def test_derive_targets_picks_up_company_role_and_level(home):
    tools.save_profile(
        "# Learner\nTarget: senior AI engineer at Anthropic, also research engineer roles."
    )
    targets = questions_refresh.derive_targets()
    companies = {(t["company"] or "").lower() for t in targets}
    roles = " ".join((t["role"] or "").lower() for t in targets)
    assert "anthropic" in companies
    assert "senior" in roles          # level encoded into the role tag
    assert "engineer" in roles


# --- helpers ----------------------------------------------------------------

def _join_refresh_threads(timeout: float = 2.0):
    for t in threading.enumerate():
        if t.name == "eklavya-qbank-refresh":
            t.join(timeout)
