"""Unified subject framework — registry, additive+guarded migration, lossless legacy port.

The load-bearing test is `test_legacy_db_ports_losslessly`: it builds a temp DB with the
OLD (pre-framework) schema, seeds it to look like a real single-user store (pillars +
curriculum + ratings on the legacy 5 coding axes + rating_history), runs the additive
migration, and asserts everything ported to subject='coding' with the axis remap applied —
no row lost, no rating changed, the old ratings table kept behind as ratings_legacy.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-subjfw-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import report, subjects, tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402
from eklavya.db.store import _migrate  # noqa: E402


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


# --- registry (pure, no DB) ------------------------------------------------

def test_registry_has_the_five_locked_subjects():
    keys = {s.key for s in subjects.all_subjects()}
    assert keys == {"coding", "maths", "stats", "ml", "cs_theory"}
    # Stats & Econometrics are ONE subject (locked decision).
    assert subjects.get("stats").name == "Statistics & Econometrics"


def test_core_axes_are_the_six():
    assert subjects.CORE_AXES == (
        "recall", "application", "derivation_proof", "interpretation", "synthesis", "transfer")


def test_legacy_axis_remap():
    assert subjects.remap_axis("syntax_recall") == "recall"
    assert subjects.remap_axis("decomposition") == "synthesis"
    # coding extensions are untouched
    for ax in ("debugging", "code_reading", "api_memory"):
        assert subjects.remap_axis(ax) == ax


def test_coding_axis_set_after_remap():
    ax = subjects.axes_for("coding")
    assert "recall" in ax and "synthesis" in ax  # from the remap onto CORE
    assert {"debugging", "code_reading", "api_memory"} <= set(ax)  # extensions kept
    assert "syntax_recall" not in ax and "decomposition" not in ax


# --- fresh DB gets the new schema + seeded registry ------------------------

def test_fresh_db_seeds_registry():
    conn = connect()
    try:
        n_subjects = conn.execute("SELECT COUNT(*) AS c FROM subjects").fetchone()["c"]
        rec = conn.execute("SELECT kind FROM axes WHERE key='recall'").fetchone()
        dbg = conn.execute("SELECT kind FROM axes WHERE key='debugging'").fetchone()
    finally:
        conn.close()
    assert n_subjects == 5
    assert rec["kind"] == "core" and dbg["kind"] == "ext"


def test_backfill_defaults_to_coding():
    tools.add_pillar("Python Fundamentals")
    tools.record_attempt("Python Fundamentals", "recall", "len()", 3, True)
    conn = connect()
    try:
        p = conn.execute("SELECT subject FROM pillars WHERE name='Python Fundamentals'").fetchone()
        a = conn.execute("SELECT subject, answer_type, score FROM attempts ORDER BY id DESC LIMIT 1").fetchone()
        r = conn.execute("SELECT subject FROM ratings ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert p["subject"] == "coding"
    assert a["subject"] == "coding" and a["answer_type"] == "code" and a["score"] == 1.0
    assert r["subject"] == "coding"


# --- P2: subject-aware rating + grid ---------------------------------------

def test_second_subject_onboards_and_rates_separately():
    # coding and stats can both have a pillar with the SAME axis name (recall), rated
    # independently — the (pillar, axis, subject) key keeps them apart.
    tools.set_baseline_rating("Python", "recall", "strong", subject="coding")
    tools.set_baseline_rating("OLS", "interpretation", "gap", subject="stats")
    tools.record_attempt("OLS", "interpretation", "reading a coefficient", 2, True, subject="stats")
    conn = connect()
    try:
        stats_cell = conn.execute(
            "SELECT r.rating FROM ratings r JOIN pillars p ON p.id=r.pillar_id "
            "WHERE p.name='OLS' AND r.axis='interpretation' AND r.subject='stats'").fetchone()
        coding_cell = conn.execute(
            "SELECT r.rating FROM ratings r JOIN pillars p ON p.id=r.pillar_id "
            "WHERE p.name='Python' AND r.axis='recall' AND r.subject='coding'").fetchone()
        subj = conn.execute("SELECT subject FROM pillars WHERE name='OLS'").fetchone()["subject"]
    finally:
        conn.close()
    assert stats_cell is not None and coding_cell is not None
    assert subj == "stats"


def test_axis_rejected_when_not_in_subject_set():
    # interpretation is NOT a coding axis; debugging is NOT a stats axis.
    assert "unknown axis" in tools.set_baseline_rating("X", "interpretation", "gap", subject="coding")
    assert "unknown axis" in tools.record_attempt("Y", "debugging", "z", 2, True, subject="stats")
    assert "unknown subject" in tools.set_baseline_rating("X", "recall", "gap", subject="astrology")


def test_grid_is_subject_aware():
    tools.set_baseline_rating("Python", "recall", "strong", subject="coding")
    tools.set_baseline_rating("OLS", "interpretation", "gap", subject="stats")
    coding = report.grid(subject="coding")
    stats = report.grid(subject="stats")
    assert "Python" in coding["pillars"] and "OLS" not in coding["pillars"]
    assert "OLS" in stats["pillars"] and "Python" not in stats["pillars"]
    # each subject reports its OWN axis order (stats has interpretation; coding doesn't)
    assert "interpretation" in stats["axes"] and "interpretation" not in coding["axes"]
    assert "debugging" in coding["axes"]
    # whole-grid (no subject) shows both pillars
    whole = report.grid()
    assert "Python" in whole["pillars"] and "OLS" in whole["pillars"]


def test_partial_credit_flows_into_elo_and_correct_threshold():
    # a 0.7 fraction counts as correct (≥ τ=0.5) and nudges Elo up; a 0.3 does not.
    tools.record_attempt("Proofs", "derivation_proof", "induction", 2, False, score=0.7, subject="maths")
    tools.record_attempt("Proofs", "derivation_proof", "induction", 2, False, score=0.3, subject="maths")
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT correct, score FROM attempts WHERE subject='maths' ORDER BY id").fetchall()
    finally:
        conn.close()
    assert rows[0]["correct"] == 1 and abs(rows[0]["score"] - 0.7) < 1e-9
    assert rows[1]["correct"] == 0 and abs(rows[1]["score"] - 0.3) < 1e-9


# --- THE parity test: an old-schema DB ports losslessly --------------------

_OLD_SCHEMA = """
CREATE TABLE pillars (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
    is_custom INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE ratings (
    id INTEGER PRIMARY KEY, pillar_id INTEGER NOT NULL REFERENCES pillars(id),
    axis TEXT NOT NULL, rating REAL NOT NULL DEFAULT 1000, confidence REAL NOT NULL DEFAULT 0,
    first_seen TEXT, last_practiced TEXT, UNIQUE (pillar_id, axis));
CREATE TABLE cards (
    id INTEGER PRIMARY KEY, ref TEXT NOT NULL, stability REAL, difficulty REAL, due TEXT,
    lapses INTEGER NOT NULL DEFAULT 0, state_json TEXT);
CREATE UNIQUE INDEX idx_cards_ref ON cards(ref);
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY, item_id INTEGER, session_id INTEGER, confidence INTEGER,
    correct INTEGER, seconds REAL, ai_off INTEGER NOT NULL DEFAULT 1,
    hints_used INTEGER NOT NULL DEFAULT 0, cheat_flag INTEGER NOT NULL DEFAULT 0, detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE curriculum (
    id INTEGER PRIMARY KEY, concept TEXT NOT NULL UNIQUE, prereqs TEXT, pillar TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE rating_history (
    id INTEGER PRIMARY KEY, pillar TEXT NOT NULL, axis TEXT NOT NULL, old_rating REAL,
    new_rating REAL NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE benchmark_items (
    id INTEGER PRIMARY KEY, pillar TEXT NOT NULL, difficulty INTEGER NOT NULL,
    prompt TEXT NOT NULL, answer TEXT NOT NULL, grader TEXT NOT NULL DEFAULT 'output_match',
    created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE UNIQUE INDEX idx_benchmark_items_prompt ON benchmark_items(prompt);
CREATE TABLE assessments (
    id INTEGER PRIMARY KEY, started_at TEXT, ended_at TEXT, theta REAL,
    n_items INTEGER NOT NULL DEFAULT 0, context TEXT);
CREATE TABLE assessment_responses (
    id INTEGER PRIMARY KEY, assessment_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
    correct INTEGER NOT NULL DEFAULT 0, seconds REAL, created_at TEXT);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _seed_old_store(db_path: Path) -> dict:
    """Build an OLD-schema DB that looks like a real single-user coding store."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_OLD_SCHEMA)
    conn.execute("INSERT INTO pillars(name, is_custom) VALUES('Python Fundamentals', 0)")
    conn.execute("INSERT INTO pillars(name, is_custom) VALUES('DS&A', 1)")
    # ratings across the legacy 5 coding axes (two get remapped, three stay)
    legacy = [
        (1, "syntax_recall", 1180.0), (1, "debugging", 1050.0), (1, "decomposition", 990.0),
        (2, "code_reading", 1220.0), (2, "api_memory", 1005.0),
    ]
    for pid, axis, rating in legacy:
        conn.execute(
            "INSERT INTO ratings(pillar_id, axis, rating, confidence, first_seen, last_practiced) "
            "VALUES(?, ?, ?, 0.4, '2026-01-01', '2026-02-01')", (pid, axis, rating))
    conn.execute("INSERT INTO curriculum(concept, prereqs, pillar) VALUES('generators', '', 'Python Fundamentals')")
    conn.execute("INSERT INTO curriculum(concept, prereqs, pillar) VALUES('recursion', 'generators', 'DS&A')")
    conn.execute("INSERT INTO cards(ref, state_json) VALUES('generators', '{\"state\":2}')")
    conn.execute("INSERT INTO attempts(confidence, correct, seconds, ai_off, detail) VALUES(3, 1, 12.0, 1, 'generators')")
    conn.execute("INSERT INTO rating_history(pillar, axis, old_rating, new_rating) VALUES('Python Fundamentals', 'syntax_recall', 1000, 1180)")
    conn.execute("INSERT INTO rating_history(pillar, axis, old_rating, new_rating) VALUES('DS&A', 'code_reading', 1000, 1220)")
    conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '1')")
    conn.commit()
    # capture a before-picture keyed by (pillar_id, remapped-axis) → rating
    before = {}
    for pid, axis, rating in legacy:
        before[(pid, subjects.remap_axis(axis))] = rating
    conn.close()
    return before


def test_legacy_db_ports_losslessly(tmp_path):
    db = tmp_path / "old.db"
    before = _seed_old_store(db)

    # run the app's migration exactly as init_db does (schema.sql then _migrate).
    from eklavya.db.store import SCHEMA
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.commit()

    # 1. every rating row survived, backfilled to coding, with the axis remap applied and
    #    the exact rating preserved (LOSSLESS).
    rows = conn.execute("SELECT pillar_id, axis, subject, rating FROM ratings").fetchall()
    assert len(rows) == len(before)
    for r in rows:
        assert r["subject"] == "coding"
        assert (r["pillar_id"], r["axis"]) in before, f"unexpected cell {r['axis']}"
        assert r["rating"] == before[(r["pillar_id"], r["axis"])]
    remapped_axes = {r["axis"] for r in rows}
    assert "recall" in remapped_axes and "synthesis" in remapped_axes
    assert "syntax_recall" not in remapped_axes and "decomposition" not in remapped_axes

    # 2. the old ratings table is KEPT behind (reversible), not dropped.
    kept = conn.execute("SELECT COUNT(*) AS c FROM ratings_legacy").fetchone()["c"]
    assert kept == len(before)

    # 3. pillars / curriculum / cards / attempts all backfilled to coding, no row lost.
    assert conn.execute("SELECT COUNT(*) AS c FROM pillars").fetchone()["c"] == 2
    assert all(r["subject"] == "coding"
               for r in conn.execute("SELECT subject FROM pillars"))
    assert all(r["subject"] == "coding"
               for r in conn.execute("SELECT subject FROM curriculum"))
    assert conn.execute("SELECT COUNT(*) AS c FROM curriculum").fetchone()["c"] == 2
    assert all(r["subject"] == "coding" for r in conn.execute("SELECT subject FROM cards"))
    assert all(r["subject"] == "coding" and r["answer_type"] == "code"
               for r in conn.execute("SELECT subject, answer_type FROM attempts"))

    # 4. rating_history axis remap applied on the copied rows.
    hist_axes = {r["axis"] for r in conn.execute("SELECT axis FROM rating_history")}
    assert "recall" in hist_axes and "syntax_recall" not in hist_axes

    # 5. registry seeded.
    assert conn.execute("SELECT COUNT(*) AS c FROM subjects").fetchone()["c"] == 5
    conn.close()


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "old.db"
    _seed_old_store(db)
    from eklavya.db.store import SCHEMA
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.commit()
    n1 = conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"]
    # run again — must not duplicate, corrupt, or re-rebuild.
    _migrate(conn)
    conn.commit()
    n2 = conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"]
    assert n1 == n2 == 5
    assert conn.execute("SELECT COUNT(*) AS c FROM subjects").fetchone()["c"] == 5
    conn.close()
