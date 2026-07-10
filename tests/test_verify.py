"""Self-check (LLM-as-judge) tests — deterministic, with the judge mocked."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-verify-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

from eklavya import verify  # noqa: E402


class _FakeModel:
    def __init__(self, text):
        self._text = text

    def invoke(self, _prompt):
        return type("R", (), {"text": self._text})()


def test_parse_verdict_is_robust():
    assert verify.parse_verdict('noise {"verdict":"ok","issues":[]} tail')["verdict"] == "ok"
    assert verify.parse_verdict("not json at all") == {"verdict": "ok", "issues": []}


def test_worth_checking():
    assert verify.worth_checking("```python\nprint(1)\n```")
    assert verify.worth_checking("a" * 300)
    assert not verify.worth_checking("Nice work! 🔥")


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("EKLAVYA_VERIFY", "0")
    assert verify.selfcheck("x" * 400) is None


def test_selfcheck_flags_a_clear_error(monkeypatch):
    monkeypatch.setenv("EKLAVYA_VERIFY", "1")
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: "glm")
    fake = _FakeModel('{"verdict":"issues","issues":[{"claim":"len() returns bytes",'
                      '"correction":"len() returns the number of items."}]}')
    monkeypatch.setattr("eklavya.providers.build_chat_model", lambda *a, **k: fake)
    note = verify.selfcheck("A long technical explanation. " * 12)
    assert note is not None and "Self-check" in note and "len()" in note


def test_selfcheck_ok_returns_none(monkeypatch):
    monkeypatch.setenv("EKLAVYA_VERIFY", "1")
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: "glm")
    monkeypatch.setattr("eklavya.providers.build_chat_model",
                        lambda *a, **k: _FakeModel('{"verdict":"ok","issues":[]}'))
    assert verify.selfcheck("A long technical explanation. " * 12) is None


def test_selfcheck_fails_open_on_judge_error(monkeypatch):
    monkeypatch.setenv("EKLAVYA_VERIFY", "1")
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: "glm")

    def boom(*a, **k):
        raise RuntimeError("judge down")

    monkeypatch.setattr("eklavya.providers.build_chat_model", boom)
    assert verify.selfcheck("A long technical explanation. " * 12) is None  # never raises
