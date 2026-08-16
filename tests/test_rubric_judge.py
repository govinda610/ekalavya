"""Constrained rubric judge (k=1) + partial-credit → axis mapping (subject framework §5.2–5.4).

The judge is mocked (a fake model returns a fixed per-criterion verdict JSON) so these are
deterministic. We assert: reference + rubric reach the judge, per-criterion pass/partial/fail
map to a weighted fraction, criteria map onto the right axis cells, deterministic sub-checks
OVERRIDE the judge, and the judge is fail-open (unavailable → nothing recorded, no fake score).
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-rubric-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import tools, verify  # noqa: E402
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


class _FakeModel:
    def __init__(self, text):
        self._text = text
        self.seen_prompt = None

    def invoke(self, prompt, *args, **kwargs):
        self.seen_prompt = prompt
        return type("R", (), {"text": self._text})()


def _mock_judge(monkeypatch, verdict_json, capture=None):
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: "glm")
    monkeypatch.setattr(verify, "ground_docs", lambda *a, **k: "")  # skip MCP
    fake = _FakeModel(verdict_json)
    if capture is not None:
        capture.append(fake)
    monkeypatch.setattr("eklavya.providers.build_chat_model", lambda *a, **k: fake)
    return fake


RUBRIC = [
    {"id": "direction", "description": "correct sign/direction of the effect",
     "weight": 2, "axis": "interpretation"},
    {"id": "assumption", "description": "checked the key OLS assumption",
     "weight": 1, "axis": "assumption_checking"},
]


def test_rubric_judge_weighted_fraction_and_reference_reaches_judge(monkeypatch):
    cap = []
    _mock_judge(monkeypatch,
                '{"criteria":[{"id":"direction","verdict":"pass"},'
                '{"id":"assumption","verdict":"fail"}]}', cap)
    res = verify.rubric_judge(
        prompt="Interpret the coefficient", answer="It is positive and significant",
        reference="The coefficient is positive; check homoskedasticity", rubric=RUBRIC,
        subject="stats")
    assert res["ok"] is True
    # weighted: (2*1.0 + 1*0.0) / 3 = 0.667
    assert abs(res["score"] - 0.667) < 0.01
    # the REFERENCE and rubric were put in front of the judge (reference-bound).
    assert "homoskedasticity" in cap[0].seen_prompt
    assert "correct sign/direction" in cap[0].seen_prompt


def test_rubric_judge_routes_through_fallback_model(monkeypatch):
    """The judge must be built via fallback.build_fallback_chat_model (temperature=0
    preserved) so a transient outage of the judge provider fails over."""
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: "glm")
    monkeypatch.setattr(verify, "ground_docs", lambda *a, **k: "")
    seen = {}

    def spy(provider_key=None, *a, **k):
        seen["provider_key"] = provider_key
        seen["temperature"] = k.get("temperature")
        return _FakeModel('{"criteria":[{"id":"direction","verdict":"pass"},'
                          '{"id":"assumption","verdict":"pass"}]}')

    monkeypatch.setattr("eklavya.fallback.build_fallback_chat_model", spy)
    res = verify.rubric_judge("q", "a", "ref", RUBRIC, subject="stats")
    assert res["ok"] is True
    assert seen.get("provider_key") == "glm"     # judge provider leads
    assert seen.get("temperature") == 0          # deterministic grade preserved


def test_partial_verdict_is_half(monkeypatch):
    _mock_judge(monkeypatch, '{"criteria":[{"id":"direction","verdict":"partial"},'
                             '{"id":"assumption","verdict":"partial"}]}')
    res = verify.rubric_judge("q", "a", "ref", RUBRIC, subject="stats")
    assert abs(res["score"] - 0.5) < 1e-9


def test_grade_rubric_maps_criteria_to_distinct_axis_cells(monkeypatch):
    _mock_judge(monkeypatch, '{"criteria":[{"id":"direction","verdict":"pass"},'
                             '{"id":"assumption","verdict":"partial"}]}')
    out = tools.grade_rubric(
        pillar="OLS", axis="interpretation", concept="reading a coefficient",
        prompt="Interpret β", answer="positive, significant", reference="positive; check homoskedasticity",
        rubric=RUBRIC, confidence=2, subject="stats", answer_type="interpretation")
    assert "score" in out.lower() or "PASS" in out or "PARTIAL" in out
    conn = connect()
    try:
        rows = {r["axis"]: r["rating"] for r in conn.execute(
            "SELECT r.axis, r.rating FROM ratings r JOIN pillars p ON p.id=r.pillar_id "
            "WHERE p.name='OLS' AND r.subject='stats'")}
    finally:
        conn.close()
    # both axes got a cell — interpretation (pass) and assumption_checking (partial)
    assert "interpretation" in rows and "assumption_checking" in rows


def test_deterministic_subcheck_overrides_judge(monkeypatch):
    # The judge says PASS, but the objective numeric sub-check is WRONG → fraction 0 wins.
    _mock_judge(monkeypatch, '{"criteria":[{"id":"value","verdict":"pass"}]}')
    rubric = [{"id": "value", "description": "the computed t-stat", "weight": 1,
               "axis": "application",
               "check": {"answer_type": "numeric", "answer": "2.5", "value": "9.9"}}]
    tools.grade_rubric(
        pillar="Inference", axis="application", concept="t-stat", prompt="compute t",
        answer="t = 9.9", reference="t = 2.5", rubric=rubric, confidence=3, subject="stats",
        answer_type="explanation")
    conn = connect()
    try:
        a = conn.execute(
            "SELECT correct, score FROM attempts WHERE subject='stats' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    # deterministic sub-check failed → recorded as fail despite the judge's "pass".
    assert a["correct"] == 0 and a["score"] == 0.0


def test_same_model_judge_flagged_and_temperature_zero(monkeypatch):
    from eklavya import config

    cap = []
    _mock_judge(monkeypatch, '{"criteria":[{"id":"direction","verdict":"pass"},'
                             '{"id":"assumption","verdict":"pass"}]}', cap)
    kwargs_seen = {}
    monkeypatch.setattr("eklavya.providers.build_chat_model",
                        lambda *a, **k: (kwargs_seen.update(k), cap[0])[1])
    # judge provider == tutor default provider → self-grading → must be flagged.
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: config.DEFAULT_PROVIDER)
    res = verify.rubric_judge("q", "a", "ref", RUBRIC, subject="stats")
    assert res["same_model_judge"] is True
    assert kwargs_seen.get("temperature") == 0


def test_distinct_provider_judge_not_flagged(monkeypatch):
    from eklavya import config

    _mock_judge(monkeypatch, '{"criteria":[{"id":"direction","verdict":"pass"},'
                             '{"id":"assumption","verdict":"pass"}]}')
    other = "minimax" if config.DEFAULT_PROVIDER != "minimax" else "glm"
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: other)
    res = verify.rubric_judge("q", "a", "ref", RUBRIC, subject="stats")
    assert res["same_model_judge"] is False


def test_rubric_judge_fail_open_records_nothing(monkeypatch):
    monkeypatch.setattr(verify, "_judge_provider_key", lambda: None)  # no judge available
    out = tools.grade_rubric(
        pillar="OLS", axis="interpretation", concept="c", prompt="p", answer="a",
        reference="r", rubric=RUBRIC, confidence=2, subject="stats")
    assert "unavailable" in out.lower()
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM attempts").fetchone()["c"]
    finally:
        conn.close()
    assert n == 0  # nothing fabricated when the judge can't run
