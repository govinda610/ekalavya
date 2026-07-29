"""Interview question-bank: seed loads, get_questions filters, refresh is offline-safe.

Points EKLAVYA_HOME at a temp dir BEFORE importing eklavya so the real ~/.eklavya db is
never touched.
"""

import importlib.util
import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-q-")
os.environ["EKLAVYA_HOME"] = _TMP

import pytest  # noqa: E402

from eklavya import questions_refresh, tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402


def _load_seed():
    """Load scripts/seed_questions.py as a module (it's not an installed package)."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_questions.py"
    spec = importlib.util.spec_from_file_location("seed_questions", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    if _cfg.DB_PATH.exists():
        _cfg.DB_PATH.unlink()
    init_db()
    yield


def _count():
    c = connect()
    try:
        return c.execute("SELECT COUNT(*) n FROM questions").fetchone()["n"]
    finally:
        c.close()


def test_seed_loads_a_few_hundred_questions():
    seed = _load_seed()
    assert len(seed.QUESTIONS) >= 200, "expected a few hundred curated questions"
    seed.main(count_only=False)
    n = _count()
    assert n >= 200
    assert n == len(seed.QUESTIONS)  # all distinct, all inserted on a fresh db


def test_seed_is_idempotent():
    seed = _load_seed()
    seed.main(count_only=False)
    first = _count()
    seed.main(count_only=False)  # re-run
    assert _count() == first  # INSERT OR IGNORE — no dupes


def test_seed_covers_the_required_domains():
    seed = _load_seed()
    seed.main(count_only=False)
    c = connect()
    try:
        topics = {r["topic"] for r in c.execute("SELECT DISTINCT topic FROM questions")}
    finally:
        c.close()
    joined = " ".join(topics)
    # DSA, system/ML-system design, ML/AI-engineering, behavioral all present.
    assert "algorithms" in joined
    assert "system-design" in joined
    assert "ml-system-design" in joined
    assert any(t in joined for t in ("rag", "agents", "llm-internals", "ai-engineering"))
    assert "behavioral" in joined


def test_seed_never_fabricates_company_tags():
    """A company tag must only appear on questions whose source attributes it."""
    seed = _load_seed()
    seed.main(count_only=False)
    c = connect()
    try:
        tagged = c.execute(
            "SELECT company, source FROM questions WHERE company IS NOT NULL"
        ).fetchall()
    finally:
        c.close()
    assert tagged, "some questions should be honestly company-tagged"
    for r in tagged:
        assert r["source"], "a company-tagged question must carry a source for attribution"


def test_add_and_get_question_roundtrip_and_dedup():
    assert tools.add_question("Reverse a linked list", topic="linked-list",
                              difficulty="easy", role="swe", source="test").startswith("added")
    # dedup on the question text
    assert "skipped" in tools.add_question("Reverse a linked list", topic="linked-list")
    out = tools.get_questions(topic="linked")
    assert "Reverse a linked list" in out


def test_get_questions_filters_by_each_field():
    tools.add_question("Design a URL shortener", topic="system-design",
                       difficulty="hard", role="swe", company="", source="test")
    tools.add_question("Explain self-attention", topic="llm-internals",
                       difficulty="hard", role="ai-eng", source="test")
    tools.add_question("Tell me about a failure", topic="behavioral",
                       role="any", company="Amazon", source="test")

    assert "URL shortener" in tools.get_questions(topic="system-design")
    assert "URL shortener" not in tools.get_questions(topic="llm-internals")
    assert "self-attention" in tools.get_questions(role="ai-eng")
    assert "failure" in tools.get_questions(company="amazon")  # case-insensitive
    assert "self-attention" in tools.get_questions(difficulty="hard")
    assert "URL shortener" in tools.get_questions(difficulty="hard")


def test_get_questions_respects_n_limit():
    for i in range(10):
        tools.add_question(f"Question number {i}?", topic="misc", source="test")
    out = tools.get_questions(topic="misc", n=3)
    assert out.count("\n- ") + out.startswith("- ") - 0 <= 3  # at most 3 lines
    assert len([ln for ln in out.splitlines() if ln.startswith("- ")]) == 3


def test_get_questions_empty_bank_gives_a_helpful_note():
    out = tools.get_questions(topic="nonexistent-topic")
    assert "no questions" in out.lower()
    assert "web_search" in out


def test_add_question_ignores_empty():
    assert "empty" in tools.add_question("   ")
    assert _count() == 0


def test_add_question_cleans_unknown_difficulty():
    tools.add_question("Some question?", topic="misc", difficulty="trivial", source="test")
    c = connect()
    try:
        row = c.execute("SELECT difficulty FROM questions WHERE question='Some question?'").fetchone()
    finally:
        c.close()
    assert row["difficulty"] is None  # unknown difficulty stored blank, not fabricated


def test_refresh_is_offline_safe(monkeypatch):
    """With no web-search key (raw search returns []), refresh must not crash and must
    report that it did not search."""
    monkeypatch.setattr(tools, "_web_search_raw", lambda *a, **k: [])
    result = questions_refresh.refresh(role="AI engineer", topic="RAG")
    assert result["searched"] is False
    assert result["added"] == 0
    assert _count() == 0


def test_refresh_extracts_and_adds_from_search(monkeypatch):
    """With a stubbed search result, refresh extracts question-shaped lines and adds them,
    tagging the company only when the source mentions it."""
    fake = [
        {"title": "Top Google interview questions",
         "content": "Design a URL shortener. How does consistent hashing work? just some filler text.",
         "url": "https://example.com/google-questions"},
    ]
    monkeypatch.setattr(tools, "_web_search_raw", lambda *a, **k: fake)
    result = questions_refresh.refresh(company="Google", role="swe", topic="system-design")
    assert result["searched"] is True
    assert result["added"] >= 2
    c = connect()
    try:
        rows = c.execute("SELECT question, company, source FROM questions").fetchall()
    finally:
        c.close()
    qs = {r["question"] for r in rows}
    assert any("URL shortener" in q for q in qs)
    # company tagged because the source URL/title mentioned Google — honest attribution
    assert any(r["company"] == "Google" for r in rows)


def test_refresh_does_not_tag_company_when_source_absent(monkeypatch):
    """If the caller passed a company but no result mentions it, no company tag is applied."""
    fake = [
        {"title": "Generic interview questions",
         "content": "Explain the bias-variance tradeoff. What is overfitting?",
         "url": "https://example.com/generic"},
    ]
    monkeypatch.setattr(tools, "_web_search_raw", lambda *a, **k: fake)
    questions_refresh.refresh(company="Netflix", role="ml")
    c = connect()
    try:
        tagged = c.execute("SELECT COUNT(*) n FROM questions WHERE company='Netflix'").fetchone()["n"]
    finally:
        c.close()
    assert tagged == 0  # never fabricate the attribution
