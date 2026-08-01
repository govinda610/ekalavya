"""Open and initialise the tutor's SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import config

SCHEMA = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "1"


def _migrate_home_to_workspace() -> None:
    """Move a db/profile created by an earlier version (at the EKLAVYA_HOME root) into
    the workspace, so existing learners keep their data. Moves (not copies), and only
    when the workspace copy doesn't exist yet — safe and idempotent."""
    config.ensure_home()
    p = config.paths()
    old_db = p.home / "eklavya.db"
    if old_db.exists() and not p.db.exists():
        for suffix in ("", "-wal", "-shm"):  # move the WAL sidecars too
            src = old_db.parent / (old_db.name + suffix)
            if src.exists():
                src.rename(p.db.parent / (p.db.name + suffix))
    old_profile = p.home / "profile.md"
    if old_profile.exists() and not p.profile.exists() and p.profile.parent == p.workspace:
        old_profile.rename(p.profile)


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Return a connection with rows accessible by column name.

    Resolves the DB from ``config.paths()`` at call time (contextvar-aware) so every
    caller lands in the current user's database without threading a path through.
    """
    config.ensure_home()
    conn = sqlite3.connect(path or config.paths().db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")  # brief write contention retries, not errors
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Small, additive migrations for databases created by an earlier version."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(cards)")}
    if "state_json" not in cols:
        conn.execute("ALTER TABLE cards ADD COLUMN state_json TEXT")
    # Thread ownership (multi-user): stamp who owns each chat. NULL for legacy/single-user
    # rows — no ownership enforcement when there's only one user.
    chat_cols = {r["name"] for r in conn.execute("PRAGMA table_info(chats)")}
    if chat_cols and "user_id" not in chat_cols:
        conn.execute("ALTER TABLE chats ADD COLUMN user_id TEXT")
    # Structured bug-catching verdict for AI-enabled interviews (caught|missed|partial).
    assist_cols = {r["name"] for r in conn.execute("PRAGMA table_info(ai_assists)")}
    if assist_cols and "bug_verdict" not in assist_cols:
        conn.execute("ALTER TABLE ai_assists ADD COLUMN bug_verdict TEXT")
    if assist_cols and "verdict_note" not in assist_cols:
        conn.execute("ALTER TABLE ai_assists ADD COLUMN verdict_note TEXT")
    # Temporal awareness: track each sitting's last activity (to reuse/measure it).
    # Additive; NULL on legacy rows.
    session_cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    if session_cols and "last_active" not in session_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN last_active TEXT")
    # Canvas artifacts (per-user). Additive: create the table on databases made by a
    # version that predates the Scriptorium. `init_db` also runs the CREATE from schema.sql,
    # so this is a belt-and-braces guard that keeps _migrate self-contained.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS artifacts ("
        "id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'markdown', "
        "content TEXT NOT NULL DEFAULT '', pinned INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_updated ON artifacts(updated_at DESC)")

    # Tier-1 effectiveness: the FROZEN benchmark tables (see schema.sql). Additive — create
    # them on databases made by a version that predates the benchmark, then seed the starter
    # item bank idempotently. `init_db` also runs these CREATEs from schema.sql, so this is a
    # belt-and-braces guard that keeps _migrate self-contained. seed_items() is imported here
    # (not at module top) to avoid a circular import: benchmark imports from this package's db.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS benchmark_items ("
        "id INTEGER PRIMARY KEY, pillar TEXT NOT NULL, difficulty INTEGER NOT NULL, "
        "prompt TEXT NOT NULL, answer TEXT NOT NULL, "
        "grader TEXT NOT NULL DEFAULT 'output_match', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_benchmark_items_prompt ON benchmark_items(prompt)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS assessments ("
        "id INTEGER PRIMARY KEY, started_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "ended_at TEXT, theta REAL, n_items INTEGER NOT NULL DEFAULT 0, context TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS assessment_responses ("
        "id INTEGER PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessments(id), "
        "item_id INTEGER NOT NULL REFERENCES benchmark_items(id), "
        "correct INTEGER NOT NULL DEFAULT 0, seconds REAL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assessment_responses_a ON assessment_responses(assessment_id)")
    # Learner feedback capture (docs/EFFECTIVENESS_MEASUREMENT.md §7). Additive: create
    # the table on databases made by a version that predates feedback. `init_db` also runs
    # the CREATE from schema.sql, so this is a belt-and-braces guard that keeps _migrate
    # self-contained (create-table only; no cross-module import here).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feedback ("
        "id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'freeform', rating INTEGER, "
        "text TEXT, concept TEXT, mode TEXT, thread TEXT, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    # Effectiveness Tier 2 (§4): n=1 self-experiment tables. Additive; create-table only.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS intervention_starts ("
        "id INTEGER PRIMARY KEY, pillar TEXT NOT NULL UNIQUE, "
        "started_at TEXT NOT NULL DEFAULT (datetime('now')), note TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS preregistrations ("
        "id INTEGER PRIMARY KEY, metric TEXT NOT NULL, hypothesis TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    # Effectiveness Tier 3 (§5): real-world outcomes. Additive; create-table only.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS external_outcomes ("
        "id INTEGER PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL, value TEXT, "
        "occurred_at TEXT, note TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    from .. import benchmark
    benchmark.seed_items(conn)


def init_db(path: Path | None = None) -> Path:
    """Create the schema if needed. Idempotent — safe to call every launch."""
    if path is None:
        _migrate_home_to_workspace()  # bring pre-workspace data forward
    target = path or config.paths().db
    conn = connect(target)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        _migrate(conn)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()
    return target


def schema_version(path: Path | None = None) -> str | None:
    target = path or config.paths().db
    if not Path(target).exists():
        return None
    conn = connect(target)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return row["value"] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
