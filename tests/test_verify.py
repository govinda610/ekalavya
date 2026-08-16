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
        self.seen_prompt = None

    def invoke(self, prompt, *args, **kwargs):
        self.seen_prompt = prompt  # capture, so tests can assert context/docs were passed
        return type("R", (), {"text": self._text})()


class _FakeTool:
    def __init__(self, name, out):
        self.name = name
        self._out = out

    def invoke(self, _args):
        return self._out


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


def test_selfcheck_routes_through_fallback_model(monkeypatch):
    """selfcheck must build the model via fallback.build_fallback_chat_model so a
    transient outage of the judge provider fails over instead of failing the check."""
    monkeypatch.setenv("EKLAVYA_VERIFY", "1")
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: "glm")
    seen = {}

    def spy(provider_key=None, *a, **k):
        seen["provider_key"] = provider_key
        return _FakeModel('{"verdict":"ok","issues":[]}')

    monkeypatch.setattr("eklavya.fallback.build_fallback_chat_model", spy)
    verify.selfcheck("A long technical explanation. " * 12)
    assert seen.get("provider_key") == "glm"   # judge provider leads, with failover behind it


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


def test_selfcheck_passes_context_and_docs_into_the_prompt(monkeypatch):
    monkeypatch.setenv("EKLAVYA_VERIFY", "1")
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: "glm")
    monkeypatch.setattr(verify, "ground_docs", lambda reply: "PANDAS DOCS: read_csv reads a CSV.")
    fake = _FakeModel('{"verdict":"ok","issues":[]}')
    monkeypatch.setattr("eklavya.providers.build_chat_model", lambda *a, **k: fake)
    verify.selfcheck("Use pandas.read_csv to load data. " * 10, context="how do I load a CSV?")
    assert "how do I load a CSV?" in fake.seen_prompt          # context threaded in
    assert "PANDAS DOCS" in fake.seen_prompt                    # grounded docs threaded in


def test_selfcheck_threads_learner_profile_so_it_isnt_flagged(monkeypatch):
    monkeypatch.setenv("EKLAVYA_VERIFY", "1")
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: "glm")
    monkeypatch.setattr(verify, "ground_docs", lambda reply: "")
    monkeypatch.setattr(verify, "learner_profile", lambda: "Govind is a Senior Data Scientist at Gartner.")
    fake = _FakeModel('{"verdict":"ok","issues":[]}')
    monkeypatch.setattr("eklavya.providers.build_chat_model", lambda *a, **k: fake)
    verify.selfcheck("You work at Gartner as a senior DS. " * 10, context="who am I?")
    assert "Senior Data Scientist at Gartner" in fake.seen_prompt  # profile fed to the judge


def test_candidate_library_targets_known_libs_only():
    assert verify.candidate_library("import pandas as pd\npd.read_csv('x')") == "pandas"
    assert verify.candidate_library("We'll use FastAPI for the endpoint.") == "fastapi"
    # local/stdlib modules are never grounded
    assert verify.candidate_library("import os\nimport my_helpers") is None
    assert verify.candidate_library("just a plain sentence") is None


def test_first_library_id_extraction():
    out = "Found: /pandas-dev/pandas (trust 9.8), /other/pandas-stubs"
    assert verify._first_library_id(out) == "/pandas-dev/pandas"
    assert verify._first_library_id("no id here") is None


def test_ground_docs_uses_context7_tools(monkeypatch):
    resolve = _FakeTool("resolve-library-id", "Best match: /pandas-dev/pandas")
    docs = _FakeTool("get-library-docs", "read_csv(filepath) -> DataFrame. Reads a CSV file.")
    monkeypatch.setattr("eklavya.mcp_client.cached_mcp_tools", lambda: [resolve, docs])
    out = verify.ground_docs("import pandas as pd  # loading data")
    assert "read_csv" in out


def test_ground_docs_empty_when_tools_not_warmed(monkeypatch):
    monkeypatch.setattr("eklavya.mcp_client.cached_mcp_tools", lambda: [])
    assert verify.ground_docs("import pandas as pd") == ""
    assert verify.ground_docs("no library here at all") == ""
