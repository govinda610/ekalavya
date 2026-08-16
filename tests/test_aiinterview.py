"""AI-enabled interview mode — the imperfect assistant, its logging, and grading.

All offline: the assistant's model call is mocked, so no API key or network is used.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-ai-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import assist  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


class _Reply:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, text):
        self._text = text

    def invoke(self, messages, *args, **kwargs):
        return _Reply(self._text)


def _mock_model(monkeypatch, text):
    monkeypatch.setattr("eklavya.providers.build_chat_model", lambda *a, **k: _FakeModel(text))


def test_substantive_gate():
    assert assist._substantive("write a function that reverses a list")
    assert assist._substantive("x" * 50)
    assert not assist._substantive("thanks!")
    assert not assist._substantive("what's your name")


def test_help_behavior_logs_plainly(monkeypatch):
    _mock_model(monkeypatch, "Here is a clean solution.")
    out = assist.respond("t1", "hi", behavior="help")
    assert out == "Here is a clean solution."
    from eklavya.db import connect
    row = connect().execute("SELECT behavior, planted_bug FROM ai_assists").fetchone()
    assert row["behavior"] == "help" and row["planted_bug"] is None


def test_plant_strips_marker_and_records_bug(monkeypatch):
    reply = "def f(n):\n    return n * 2\n<<BUG: uses *2 instead of **2>>"
    _mock_model(monkeypatch, reply)
    out = assist.respond("t1", "write a square function", behavior="plant")
    assert "<<BUG" not in out and "BUG:" not in out          # candidate never sees it
    assert out.strip().endswith("return n * 2")
    from eklavya.db import connect
    row = connect().execute("SELECT behavior, planted_bug FROM ai_assists").fetchone()
    assert row["behavior"] == "plant"
    assert "**2" in row["planted_bug"]                        # ground truth captured


def test_plant_without_marker_falls_back(monkeypatch):
    _mock_model(monkeypatch, "def f(n): return n")           # model forgot the marker
    assist.respond("t1", "write code", behavior="plant")
    from eklavya.db import connect
    bug = connect().execute("SELECT planted_bug FROM ai_assists").fetchone()["planted_bug"]
    assert bug and "identify it" in bug                       # still flagged for the grader


def test_review_scopes_to_marked_interview(monkeypatch):
    _mock_model(monkeypatch, "reply A")
    assist.respond("old-thread", "write code", behavior="help")   # a previous interview
    assist.mark_interview("cur-thread")                            # current interview starts
    _mock_model(monkeypatch, "reply B<<BUG: off-by-one in the range>>")
    assist.respond("cur-thread", "implement pagination", behavior="plant")

    out = assist.review_ai_usage()
    assert "1 assistant exchange" in out                      # only the current thread
    assert "off-by-one" in out and "reply A" not in out


def test_review_empty_when_unused():
    assist.mark_interview("lonely-thread")
    assert "did not use the AI assistant" in assist.review_ai_usage()


def test_forced_plant_after_substantive_asks_without_a_plant(monkeypatch):
    """The guarantee: after enough substantive asks in a thread with NOTHING planted,
    the next substantive reply is forced to plant — so every interview has a bug."""
    # Auto-pick would normally leave this to chance; pin randomness to NEVER plant so we
    # prove the FORCE path (not luck) is what plants the bug.
    monkeypatch.setattr(assist.random, "random", lambda: 0.99)  # >0.50 → always "help"
    _mock_model(monkeypatch, "reply<<BUG: forced subtle off-by-one>>")

    for _ in range(assist._FORCE_PLANT_AFTER):
        assert assist._pick_behavior("write a function to do the thing", "t1") == "help"
        assist.respond("t1", "write a function to do the thing")  # auto behavior

    from eklavya.db import connect
    assert connect().execute(
        "SELECT COUNT(*) c FROM ai_assists WHERE thread='t1' AND behavior='plant'"
    ).fetchone()["c"] == 0                                       # nothing planted yet

    # The next substantive ask must be forced to plant despite randomness saying "help".
    assert assist._pick_behavior("implement the pagination helper", "t1") == "plant"
    assist.respond("t1", "implement the pagination helper")      # auto behavior
    bug = connect().execute(
        "SELECT planted_bug FROM ai_assists WHERE thread='t1' AND behavior='plant'"
    ).fetchone()
    assert bug and "off-by-one" in bug["planted_bug"]            # a real bug got planted


def test_forced_plant_surfaces_in_review(monkeypatch):
    """review_ai_usage() must surface the guaranteed bug for the current interview."""
    monkeypatch.setattr(assist.random, "random", lambda: 0.99)   # random never plants
    assist.mark_interview("cur")
    _mock_model(monkeypatch, "here you go<<BUG: wrong default value>>")
    for _ in range(assist._FORCE_PLANT_AFTER + 1):
        assist.respond("cur", "write the function that solves this")

    out = assist.review_ai_usage()
    assert "1 planted bug" in out
    assert "wrong default value" in out
    assert "assist_id=" in out                                   # stable key for verdicts


def test_record_bug_verdict_is_queryable(monkeypatch):
    monkeypatch.setattr(assist.random, "random", lambda: 0.99)
    assist.mark_interview("cur")
    _mock_model(monkeypatch, "solution<<BUG: inverted boundary check>>")
    for _ in range(assist._FORCE_PLANT_AFTER + 1):
        assist.respond("cur", "write code to solve the interview problem")

    from eklavya.db import connect
    assist_id = connect().execute(
        "SELECT id FROM ai_assists WHERE behavior='plant' AND planted_bug IS NOT NULL"
    ).fetchone()["id"]

    msg = assist.record_bug_verdict(assist_id, "caught", "candidate spotted the flipped <=")
    assert "recorded" in msg and "caught" in msg

    row = connect().execute(
        "SELECT bug_verdict, verdict_note FROM ai_assists WHERE id=?", (assist_id,)
    ).fetchone()
    assert row["bug_verdict"] == "caught"                        # persisted, queryable
    assert "flipped" in row["verdict_note"]
    assert "recorded verdict: caught" in assist.review_ai_usage()  # shows in the review


def test_record_bug_verdict_rejects_bad_input(monkeypatch):
    _mock_model(monkeypatch, "clean reply")
    assist.respond("t1", "hi", behavior="help")                  # a non-plant row
    from eklavya.db import connect
    help_id = connect().execute("SELECT id FROM ai_assists").fetchone()["id"]

    assert "unknown verdict" in assist.record_bug_verdict(help_id, "nope")
    assert "no planted bug" in assist.record_bug_verdict(help_id, "caught")
    assert "no assistant exchange" in assist.record_bug_verdict(99999, "caught")


def test_respond_routes_through_fallback_model(monkeypatch):
    """assist.respond must build via fallback.build_fallback_chat_model (sticky-auto,
    no explicit provider) so a transient provider outage fails over instead of
    returning the 'unavailable' note."""
    called = {}

    def spy(provider_key=None, *a, **k):
        called["provider_key"] = provider_key
        return _FakeModel("route reply")

    monkeypatch.setattr("eklavya.fallback.build_fallback_chat_model", spy)
    out = assist.respond("t-fb", "help me", behavior="help")
    assert out == "route reply"
    assert called.get("provider_key") is None    # sticky-auto over configured providers


def test_assist_route(monkeypatch):
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    monkeypatch.setattr("eklavya.providers.build_chat_model",
                        lambda *a, **k: _FakeModel("route reply"))
    c = TestClient(create_app())
    r = c.post("/api/assist", json={"thread": "t9", "text": "help me"})
    assert r.status_code == 200 and r.json()["reply"] == "route reply"
