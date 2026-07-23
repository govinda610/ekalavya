"""Skill-tree graph: pipe-delimited prereq edges + per-pillar filtering."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-curr-")
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
    conn = connect()
    conn.execute("DELETE FROM curriculum")
    conn.commit()
    conn.close()
    yield


def test_pipe_prereqs_build_edges_and_pillar_filter_narrows():
    # a foundation concept with commas in its name, and dependents via pipe-delimited prereqs
    tools.add_curriculum("Basics: variables, types, control flow", "", "Python Fundamentals")
    tools.add_curriculum("Embeddings: cosine, dot, norms", "Basics: variables, types, control flow", "RAG & Vector Retrieval")
    tools.add_curriculum("Re-ranking with cross-encoders", "Embeddings: cosine, dot, norms", "RAG & Vector Retrieval")

    full = report.curriculum_mermaid()
    assert full["empty"] is False
    # edges must be recovered despite the comma-in-name (2 edges), not shredded to 0
    assert full["mermaid"].count("-->") == 2
    assert set(full["pillars"]) == {"Python Fundamentals", "RAG & Vector Retrieval"}

    # filter to one track -> only its concepts (+ direct prereqs) render, left-to-right
    rag = report.curriculum_mermaid("RAG & Vector Retrieval")
    assert rag["mermaid"].splitlines()[0] == "graph LR"
    nodes = sum(1 for ln in rag["mermaid"].splitlines() if '["' in ln)
    assert nodes == 3  # 2 RAG concepts + 1 prereq foundation for context
