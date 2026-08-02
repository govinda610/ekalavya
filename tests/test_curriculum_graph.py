"""Forest map: pipe-delimited prereq edges, grove statuses, active grove, layout."""

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


def _grove(fm, name):
    return next(g for g in fm["groves"] if g["pillar"] == name)


def test_forest_groves_counts_and_statuses():
    # a comma-named foundation, and dependents via pipe-delimited prereqs across pillars
    tools.add_curriculum("Basics: variables, types, control flow", "", "Python Fundamentals")
    tools.add_curriculum("Embeddings: cosine, dot, norms",
                         "Basics: variables, types, control flow", "RAG & Vector Retrieval")
    tools.add_curriculum("Re-ranking with cross-encoders",
                         "Embeddings: cosine, dot, norms", "RAG & Vector Retrieval")

    fm = report.forest_map()
    assert fm["empty"] is False
    assert len(fm["groves"]) == 2  # two pillars → two groves
    pf = _grove(fm, "Python Fundamentals")
    rag = _grove(fm, "RAG & Vector Retrieval")
    assert pf["total"] == 1 and rag["total"] == 2
    # nothing mastered yet: Python Fundamentals' one concept is unlocked (no prereqs) → its
    # grove is the current focus (active); RAG's concepts are all locked → a bare sapling.
    assert pf["status"] == "active"
    assert rag["status"] == "locked"
    assert fm["active"] == "Python Fundamentals"


def test_grove_status_progresses_to_blossoming_and_active_moves():
    tools.add_curriculum("Basics: variables, types, control flow", "", "Python Fundamentals")
    tools.add_curriculum("Embeddings: cosine, dot, norms",
                         "Basics: variables, types, control flow", "RAG & Vector Retrieval")

    # master the foundation → Python Fundamentals fully done (blossoming); it also unlocks
    # the Embeddings concept, so RAG becomes the newly-active grove.
    tools.record_attempt("Python Fundamentals", "syntax_recall",
                         "Basics: variables, types, control flow", 3, True)
    fm = report.forest_map()
    assert _grove(fm, "Python Fundamentals")["status"] == "blossoming"
    assert _grove(fm, "Python Fundamentals")["done"] == 1
    # RAG now has an unlocked concept and is the most-recently-relevant non-mastered grove
    rag = _grove(fm, "RAG & Vector Retrieval")
    assert rag["status"] in ("active", "unlocked")
    # after practising RAG, it is unambiguously the active grove
    tools.record_attempt("RAG & Vector Retrieval", "code_reading",
                         "Embeddings: cosine, dot, norms", 2, False)
    fm2 = report.forest_map()
    assert fm2["active"] == "RAG & Vector Retrieval"
    assert _grove(fm2, "RAG & Vector Retrieval")["status"] == "active"


def test_node_is_done_despite_concept_wording_drift():
    """A concept counts mastered when a correct attempt's recorded name differs only by
    case/whitespace from the curriculum name — exact-match left it locked."""
    tools.add_pillar("Python Fundamentals")
    tools.add_curriculum("Async and Event Loops", "", "Python Fundamentals")
    tools.add_curriculum("Structured concurrency", "Async and Event Loops", "Python Fundamentals")
    tools.record_attempt("Python Fundamentals", "syntax_recall",
                         "  async and event LOOPS ", 3, True)
    fm = report.forest_map("Python Fundamentals")
    st = {c["name"]: c["status"] for c in fm["concepts"]}
    assert st["Async and Event Loops"] == "done"      # mastered despite wording drift…
    assert st["Structured concurrency"] == "avail"    # …and its dependent is now unlocked


def test_forest_exposes_journey_order_and_cross_pillar_edges():
    """The 2D map needs a deterministic walk order (foundations→frontier) and grove-level
    prerequisite edges. Both are additive on forest_map()."""
    tools.add_curriculum("Basics: variables, types, control flow", "", "Python Fundamentals")
    tools.add_curriculum("Embeddings: cosine, dot, norms",
                         "Basics: variables, types, control flow", "RAG & Vector Retrieval")
    tools.add_curriculum("Re-ranking with cross-encoders",
                         "Embeddings: cosine, dot, norms", "RAG & Vector Retrieval")
    fm = report.forest_map()
    # order lists every pillar once, with the root (no cross-pillar prereqs) first
    assert set(fm["order"]) == {"Python Fundamentals", "RAG & Vector Retrieval"}
    assert fm["order"][0] == "Python Fundamentals"
    # each grove carries its index in the walk
    assert {g["pillar"]: g["order"] for g in fm["groves"]}["Python Fundamentals"] == 0
    # a cross-pillar edge Python Fundamentals → RAG (prereq lives in another pillar)
    assert {"from": "Python Fundamentals", "to": "RAG & Vector Retrieval"} in fm["edges"]


def test_grove_drilldown_exposes_ordered_concepts_and_edges():
    tools.add_curriculum("A start", "", "Python Fundamentals")
    tools.add_curriculum("B needs A", "A start", "Python Fundamentals")
    tools.add_curriculum("C needs B", "B needs A", "Python Fundamentals")
    fm = report.forest_map("Python Fundamentals")
    names = [c["name"] for c in fm["concepts"]]
    assert names == ["A start", "B needs A", "C needs B"]        # topological within the grove
    assert {"from": "A start", "to": "B needs A"} in fm["edges"]
    assert {"from": "B needs A", "to": "C needs B"} in fm["edges"]


def test_layout_scales_and_wraps_for_varying_pillar_counts():
    # 5 pillars and 40 pillars both lay out on a winding path with a taller-when-needed canvas
    for n, min_h in ((5, 560), (40, 900)):
        lay = report._forest_layout(n)
        assert len(lay["points"]) == n
        vb = lay["viewbox"]
        assert vb[2] == 900                    # fixed width → no horizontal overflow
        assert vb[3] >= min_h                  # canvas grows taller as groves multiply
        # points stay inside the canvas bounds
        assert all(0 <= p["x"] <= vb[2] for p in lay["points"])
        assert all(0 <= p["y"] <= vb[3] for p in lay["points"])
    # many groves wrap into multiple rows (not one endless line off the right edge)
    assert report._forest_layout(40)["rows"] > 1
