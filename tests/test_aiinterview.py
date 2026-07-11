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

    def invoke(self, messages):
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


def test_assist_route(monkeypatch):
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    monkeypatch.setattr("eklavya.providers.build_chat_model",
                        lambda *a, **k: _FakeModel("route reply"))
    c = TestClient(create_app())
    r = c.post("/api/assist", json={"thread": "t9", "text": "help me"})
    assert r.status_code == 200 and r.json()["reply"] == "route reply"
