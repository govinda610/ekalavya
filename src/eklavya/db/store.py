"""Open and initialise the tutor's SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import config

SCHEMA = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "2"


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
    # Associate each artifact with the chat that made it (thread_id) and the pillar it belongs
    # to (for a pillar-grouped Scriptorium). Additive; NULL on artifacts made before this.
    art_cols = {r["name"] for r in conn.execute("PRAGMA table_info(artifacts)")}
    if "thread_id" not in art_cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN thread_id TEXT")
    if "pillar" not in art_cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN pillar TEXT")

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
    # === Unified Subject Framework (docs/UNIFIED_SUBJECT_FRAMEWORK_PLAN.md) ===
    # Additive + guarded + reversible: create the registry tables, add `subject`/answer_type/
    # score columns (backfilling legacy rows to 'coding'), and rebuild `ratings` (UNIQUE change +
    # legacy axis remap) via copy-verify-swap that KEEPS the old table until parity is confirmed.
    _migrate_subject_framework(conn)

    from .. import benchmark
    benchmark.seed_items(conn)


def _add_col(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    """Guarded ADD COLUMN — only if the table exists and the column is absent (idempotent)."""
    present = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in present:
        return
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _seed_registry(conn: sqlite3.Connection) -> None:
    """Idempotently seed the `subjects` + `axes` catalog from subjects.py (the authoritative
    in-code definition). Matched on `key`; never overwrites an existing (possibly custom) row."""
    from .. import subjects
    for s in subjects.all_subjects():
        conn.execute(
            "INSERT OR IGNORE INTO subjects(key, name, core_axes, ext_axes, answer_types, is_custom) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (s.key, s.name, "|".join(s.core_axes), "|".join(s.ext_axes),
             "|".join(s.answer_types), int(s.is_custom)),
        )
    for key, kind, label in subjects.all_axis_catalog():
        conn.execute("INSERT OR IGNORE INTO axes(key, kind, label) VALUES(?, ?, ?)", (key, kind, label))


def _rebuild_ratings_with_subject(conn: sqlite3.Connection) -> None:
    """Relax ratings' UNIQUE(pillar_id, axis) → UNIQUE(pillar_id, axis, subject) and apply the
    legacy axis remap — the reversible copy-verify-swap used elsewhere in this codebase.

    SQLite can't ALTER a UNIQUE constraint in place, so: build ratings_v2 with the new
    constraint, INSERT ... SELECT (stamping subject='coding' and remapping legacy axes),
    verify row parity, then swap names KEEPING the original as ratings_legacy until the
    next run — never a DROP of live data, so a failed migration leaves the original intact.
    """
    from .. import subjects
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(ratings)")}
    if not cols or "subject" in cols:
        return  # already migrated (fresh DB gets the new schema straight from schema.sql)

    conn.execute("DROP TABLE IF EXISTS ratings_v2")
    conn.execute(
        "CREATE TABLE ratings_v2 ("
        "  id INTEGER PRIMARY KEY, pillar_id INTEGER NOT NULL REFERENCES pillars(id), "
        "  axis TEXT NOT NULL, subject TEXT NOT NULL DEFAULT 'coding', "
        "  rating REAL NOT NULL DEFAULT 1000, confidence REAL NOT NULL DEFAULT 0, "
        "  first_seen TEXT, last_practiced TEXT, UNIQUE (pillar_id, axis, subject))"
    )
    # Copy every legacy row, remapping the axis label (syntax_recall→recall,
    # decomposition→synthesis) so historical ratings land on the new CORE losslessly.
    old_rows = conn.execute(
        "SELECT id, pillar_id, axis, rating, confidence, first_seen, last_practiced FROM ratings"
    ).fetchall()
    for r in old_rows:
        conn.execute(
            "INSERT INTO ratings_v2(id, pillar_id, axis, subject, rating, confidence, "
            "first_seen, last_practiced) VALUES(?, ?, ?, 'coding', ?, ?, ?, ?)",
            (r["id"], r["pillar_id"], subjects.remap_axis(r["axis"]), r["rating"],
             r["confidence"], r["first_seen"], r["last_practiced"]),
        )
    before = conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"]
    after = conn.execute("SELECT COUNT(*) AS c FROM ratings_v2").fetchone()["c"]
    if before != after:
        conn.execute("DROP TABLE ratings_v2")  # abort: leave the original untouched
        raise RuntimeError(f"ratings rebuild parity FAILED — before={before} after={after}")
    # Swap: keep the original as ratings_legacy (reversible), promote the new table.
    conn.execute("DROP TABLE IF EXISTS ratings_legacy")
    conn.execute("ALTER TABLE ratings RENAME TO ratings_legacy")
    conn.execute("ALTER TABLE ratings_v2 RENAME TO ratings")


def _migrate_subject_framework(conn: sqlite3.Connection) -> None:
    """Additive, guarded migration for the unified subject framework (plan §6)."""
    # New registry tables (belt-and-braces; init_db also runs schema.sql's CREATEs).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS subjects ("
        "id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, name TEXT NOT NULL, "
        "core_axes TEXT NOT NULL, ext_axes TEXT, answer_types TEXT, "
        "is_custom INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS axes ("
        "id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, "
        "kind TEXT NOT NULL DEFAULT 'core', label TEXT)"
    )
    # Additive `subject`/answer_type/score columns, backfilling legacy rows to 'coding'.
    _add_col(conn, "pillars", "subject", "TEXT NOT NULL DEFAULT 'coding'")
    _add_col(conn, "curriculum", "subject", "TEXT NOT NULL DEFAULT 'coding'")
    _add_col(conn, "cards", "subject", "TEXT NOT NULL DEFAULT 'coding'")
    _add_col(conn, "rating_history", "subject", "TEXT NOT NULL DEFAULT 'coding'")
    _add_col(conn, "attempts", "subject", "TEXT NOT NULL DEFAULT 'coding'")
    _add_col(conn, "attempts", "answer_type", "TEXT NOT NULL DEFAULT 'code'")
    _add_col(conn, "attempts", "score", "REAL")
    _add_col(conn, "benchmark_items", "subject", "TEXT NOT NULL DEFAULT 'coding'")
    _add_col(conn, "benchmark_items", "answer_type", "TEXT NOT NULL DEFAULT 'code'")
    _add_col(conn, "benchmark_items", "tolerance", "TEXT")
    _add_col(conn, "benchmark_items", "rubric", "TEXT")
    _add_col(conn, "assessments", "subject", "TEXT NOT NULL DEFAULT 'coding'")
    _add_col(conn, "assessment_responses", "score", "REAL")
    _add_col(conn, "assessment_responses", "criteria_json", "TEXT")
    # Legacy attempts: remap the axis stored in rating_history (attempts store concept in
    # `detail`, axis lives in rating_history). Value updates on existing rows, fully reversible.
    _remap_legacy_axes(conn)
    # Rebuild ratings for the UNIQUE(...,subject) change + axis remap (copy-verify-swap).
    _rebuild_ratings_with_subject(conn)
    # Seed the registry (subjects + axes catalog) from the authoritative in-code definition.
    _seed_registry(conn)
    # Agent-defined pillar order + dependency DAG (task #89). Additive + guarded + backfilled.
    _migrate_pillar_order(conn)


def _migrate_pillar_order(conn: sqlite3.Connection) -> None:
    """Additive pillar-ordering columns (task #89): `seq` (tutor's tackle-order hint) and
    `prereq_pillars` (a '|'-list of pillar names that block this one → the dependency DAG).

    Guarded + reversible: ADD COLUMN only when absent, then BACKFILL existing rows so
    today's behaviour is preserved until the tutor sets an order —
      • prereq_pillars → '' (no pillar is falsely blocked);
      • seq → the rank each pillar has under the CURRENT structural ordering
        (report._grove_order over the curriculum-derived DAG), so the legacy map order
        is reproduced exactly on databases created before this migration.
    Backfill only touches rows whose seq is still NULL, so it never clobbers an order the
    tutor has since set."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pillars)")}
    if not cols:
        return
    if "seq" not in cols:
        conn.execute("ALTER TABLE pillars ADD COLUMN seq INTEGER")
    if "prereq_pillars" not in cols:
        conn.execute("ALTER TABLE pillars ADD COLUMN prereq_pillars TEXT NOT NULL DEFAULT ''")
    # Backfill seq for legacy rows from the current structural order (deterministic).
    unset = [r["name"] for r in conn.execute(
        "SELECT name FROM pillars WHERE seq IS NULL")]
    if unset:
        from ..report import legacy_grove_order
        order = legacy_grove_order(conn)  # every pillar, in the pre-#89 structural order
        rank = {name: i for i, name in enumerate(order)}
        # Any pillar the structural order didn't cover (e.g. no curriculum rows) trails,
        # ranked after the covered ones by name so the backfill is fully deterministic.
        for name in sorted(n for n in unset if n not in rank):
            rank[name] = len(rank)
        for name in unset:
            conn.execute("UPDATE pillars SET seq = ? WHERE name = ? AND seq IS NULL",
                         (rank[name], name))


def _remap_legacy_axes(conn: sqlite3.Connection) -> None:
    """Apply the legacy coding-axis remap to rating_history rows (idempotent value update)."""
    from .. import subjects
    for old, new in subjects.LEGACY_AXIS_REMAP.items():
        conn.execute("UPDATE rating_history SET axis = ? WHERE axis = ?", (new, old))


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
