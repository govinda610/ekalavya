"""The shipped starter question bank loads into new accounts, never clobbers existing ones."""

import sqlite3

from eklavya import seed_questions
from eklavya.db import store


def test_seed_loads_into_new_db(tmp_path):
    db = tmp_path / "eklavya.db"
    store.init_db(db)  # init runs ensure_seeded on the fresh, empty questions table
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    assert n > 100, f"expected the shipped seed bank, got {n}"


def test_seed_is_idempotent(tmp_path):
    db = tmp_path / "eklavya.db"
    store.init_db(db)
    conn = sqlite3.connect(db)
    before = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    # a second pass over a non-empty bank adds nothing (no dupes)
    assert seed_questions.ensure_seeded(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == before


def test_seed_skips_nonempty_bank(tmp_path):
    db = tmp_path / "eklavya.db"
    store.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM questions")
    conn.execute("INSERT INTO questions(question) VALUES('a pre-existing question')")
    conn.commit()
    assert seed_questions.ensure_seeded(conn) == 0  # table has a row → leave it alone
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1


def test_seed_missing_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_questions, "_SEED_FILE", tmp_path / "absent.json")
    db = tmp_path / "eklavya.db"
    store.init_db(db)  # seed file absent → questions stays empty, no error
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0


def test_seed_json_is_honest_and_covers_domains():
    """The shipped bank: honest company tags (each tagged Q has a source) + broad coverage."""
    import json
    from eklavya import seed_questions
    items = json.loads(seed_questions._SEED_FILE.read_text())
    assert len(items) >= 200
    # honest tagging: a company tag must carry a source for attribution
    tagged = [q for q in items if (q.get("company") or "").strip()]
    assert tagged, "expected some honestly company-attributed questions"
    for q in tagged:
        assert (q.get("source") or "").strip(), "a company-tagged question must carry a source"
    # broad coverage across the app's audience
    topics = " ".join((q.get("topic") or "").lower() for q in items)
    for needed in ("system-design", "behavioral", "sql"):
        assert needed in topics, f"seed bank missing '{needed}'"
    assert any(t in topics for t in ("ml", "llm", "rag", "deep-learning")), "missing ML/LLM coverage"
    assert any(t in topics for t in ("arrays", "graphs", "dynamic-programming", "trees")), "missing DSA coverage"
