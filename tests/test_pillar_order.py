"""Agent-defined pillar ORDER (task #89): a dependency DAG, topologically sorted, with the
active pillar anchored at the entrance — and a lossless backfill for pre-#89 databases."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-porder-")
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
    conn.execute("DELETE FROM pillars")
    conn.commit()
    conn.close()
    yield


def _order(fm):
    return fm["order"]


def test_save_baseline_list_order_roundtrips_into_forest_map():
    """A pillars=[...] list order round-trips into forest_map's journey order: index 0 is the
    first-listed pillar. Deps: OOP after Python Fundamentals; DS&A after OOP."""
    tools.save_baseline(pillars=[
        {"name": "Python Fundamentals"},
        {"name": "OOP", "prereq_pillars": ["Python Fundamentals"]},
        {"name": "DS&A", "prereq_pillars": ["OOP"]},
    ])
    # give each pillar a concept so it becomes a grove on the map
    tools.add_curriculum("vars", "", "Python Fundamentals")
    tools.add_curriculum("classes", "", "OOP")
    tools.add_curriculum("bigO", "", "DS&A")

    fm = report.forest_map()
    order = _order(fm)
    assert order[0] == "Python Fundamentals"          # first listed → entrance (index 0)
    assert order.index("OOP") > order.index("Python Fundamentals")   # dependent comes after
    assert order.index("DS&A") > order.index("OOP")
    # the active grove is the entrance
    assert fm["active"] == "Python Fundamentals"
    assert next(g for g in fm["groves"] if g["order"] == 0)["pillar"] == "Python Fundamentals"


def test_dependency_dag_parallel_tracks_and_active_at_start():
    """Given deps [PythonFund→none, OOP→PythonFund, NLP→ML Theory, Stats→none] with active
    = PythonFund: the map starts with PythonFund, OOP follows PythonFund, NLP follows ML Theory,
    and independent Stats is NOT forced before/after unrelated pillars. Dependency edges present."""
    tools.save_baseline(pillars=[
        {"name": "Python Fundamentals"},
        {"name": "OOP", "prereq_pillars": ["Python Fundamentals"]},
        {"name": "ML Theory"},
        {"name": "NLP", "prereq_pillars": ["ML Theory"]},
        {"name": "Stats"},
    ])
    for p, c in [("Python Fundamentals", "vars"), ("OOP", "classes"),
                 ("ML Theory", "loss"), ("NLP", "tokens"), ("Stats", "mean")]:
        tools.add_curriculum(c, "", p)
    # a 2nd Python Fundamentals concept so it stays non-mastered (thus eligible to be active)
    tools.add_curriculum("loops", "", "Python Fundamentals")

    # make Python Fundamentals the active (currently-studied) pillar
    tools.record_attempt("Python Fundamentals", "syntax_recall", "vars", 3, True)

    fm = report.forest_map()
    order = _order(fm)
    assert fm["active"] == "Python Fundamentals"
    assert order[0] == "Python Fundamentals"                       # active anchored at start
    assert order.index("OOP") > order.index("Python Fundamentals")
    assert order.index("NLP") > order.index("ML Theory")
    # Stats is independent: its only constraint is that it isn't forced relative to unrelated
    # pillars. It must NOT be wedged before ML Theory/NLP by a false prereq.
    assert "Stats" in order
    # dependency EDGES exist for the two real prereqs (prereq → dependent), and NOT for Stats
    assert {"from": "Python Fundamentals", "to": "OOP"} in fm["edges"]
    assert {"from": "ML Theory", "to": "NLP"} in fm["edges"]
    assert not any(e["to"] == "Stats" or e["from"] == "Stats" for e in fm["edges"])


def test_reordering_reassigns_seq():
    """Re-sending the pillars list in a new order updates the stored seq hint (re-runnable)."""
    tools.save_baseline(pillars=["A", "B", "C"])
    conn = connect()
    seq = {r["name"]: r["seq"] for r in conn.execute("SELECT name, seq FROM pillars")}
    conn.close()
    assert seq == {"A": 0, "B": 1, "C": 2}
    tools.save_baseline(pillars=["C", "A", "B"])
    conn = connect()
    seq2 = {r["name"]: r["seq"] for r in conn.execute("SELECT name, seq FROM pillars")}
    conn.close()
    assert seq2 == {"C": 0, "A": 1, "B": 2}


def test_seq_hint_breaks_ties_for_independent_pillars():
    """Two independent pillars (no deps) keep the tutor's list order via the seq tie-break."""
    tools.save_baseline(pillars=["Stats", "Python Fundamentals"])
    tools.add_curriculum("mean", "", "Stats")
    tools.add_curriculum("vars", "", "Python Fundamentals")
    fm = report.forest_map()
    # Stats was listed first (seq 0) → it leads the independents (no active pillar practised yet)
    assert fm["order"].index("Stats") < fm["order"].index("Python Fundamentals")


def test_legacy_backfill_is_lossless_when_seq_unset():
    """Existing pillars with NO seq/deps (pre-#89 shape) still order via the structural
    fallback — the migration backfilled seq from the legacy _grove_order, so the map order is
    unchanged. We simulate a legacy DB by clearing the columns after inserting."""
    # Insert pillars + a cross-pillar curriculum WITHOUT using the new order API.
    tools.add_curriculum("Basics", "", "Python Fundamentals")
    tools.add_curriculum("Embeddings", "Basics", "RAG")
    tools.add_curriculum("Re-rank", "Embeddings", "RAG")
    # blank out the #89 columns to mimic a database created before the migration
    conn = connect()
    conn.execute("UPDATE pillars SET seq = NULL, prereq_pillars = ''")
    conn.commit()
    conn.close()

    # forest_map falls back to the structural heuristic → root pillar (Python Fundamentals) leads
    fm = report.forest_map()
    assert fm["order"][0] == "Python Fundamentals"
    assert fm["order"].index("RAG") > fm["order"].index("Python Fundamentals")
    # and the concept-derived cross-pillar edge still surfaces
    assert {"from": "Python Fundamentals", "to": "RAG"} in fm["edges"]


def test_migration_backfills_seq_from_legacy_order(tmp_path, monkeypatch):
    """init_db()'s migration deterministically backfills seq for rows that have none, using the
    legacy structural order — so a fresh migrate reproduces today's behaviour."""
    db = tmp_path / "legacy.db"
    conn = connect(str(db))
    # create just the pillars table in its pre-#89 shape (no seq / prereq_pillars) + curriculum
    conn.execute("CREATE TABLE pillars (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
                 "is_custom INTEGER NOT NULL DEFAULT 0, subject TEXT NOT NULL DEFAULT 'coding', "
                 "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.execute("CREATE TABLE curriculum (id INTEGER PRIMARY KEY, concept TEXT NOT NULL UNIQUE, "
                 "prereqs TEXT, pillar TEXT, subject TEXT NOT NULL DEFAULT 'coding', "
                 "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.execute("INSERT INTO pillars(name) VALUES('RAG')")
    conn.execute("INSERT INTO pillars(name) VALUES('Python Fundamentals')")
    conn.execute("INSERT INTO curriculum(concept, prereqs, pillar) VALUES('Basics','','Python Fundamentals')")
    conn.execute("INSERT INTO curriculum(concept, prereqs, pillar) VALUES('Embeddings','Basics','RAG')")
    conn.commit()
    conn.close()

    init_db(str(db))  # runs the guarded migration + backfill

    conn = connect(str(db))
    rows = {r["name"]: r["seq"] for r in conn.execute("SELECT name, seq FROM pillars")}
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pillars)")}
    conn.close()
    assert "seq" in cols and "prereq_pillars" in cols            # columns added
    assert rows["Python Fundamentals"] is not None and rows["RAG"] is not None  # backfilled
    # the root pillar ranks before the dependent one (legacy structural order preserved)
    assert rows["Python Fundamentals"] < rows["RAG"]
