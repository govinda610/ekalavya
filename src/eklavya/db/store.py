"""Open and initialise the tutor's SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import DB_PATH, ensure_home

SCHEMA = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "1"


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Return a connection with rows accessible by column name."""
    ensure_home()
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Small, additive migrations for databases created by an earlier version."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(cards)")}
    if "state_json" not in cols:
        conn.execute("ALTER TABLE cards ADD COLUMN state_json TEXT")


def init_db(path: Path | None = None) -> Path:
    """Create the schema if needed. Idempotent — safe to call every launch."""
    target = path or DB_PATH
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
    target = path or DB_PATH
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
