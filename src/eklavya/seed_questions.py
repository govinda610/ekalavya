"""Ship a starter interview-question bank so a fresh account isn't empty.

`ensure_seeded(conn)` loads the curated `data/seed_questions.json` into a user's
`questions` table — but ONLY when that table is currently empty, so it never
touches an existing bank (e.g. the migrated owner account with its own questions).
It dedupes on the question text (the table's UNIQUE index), no-ops if the seed file
is absent, and never raises: seeding is a nicety, not something that may break login.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("eklavya.seed_questions")

_SEED_FILE = Path(__file__).parent / "data" / "seed_questions.json"
_FIELDS = ("question", "topic", "difficulty", "role", "company", "source")


def _load_file() -> list[dict]:
    try:
        data = json.loads(_SEED_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def ensure_seeded(conn: sqlite3.Connection) -> int:
    """Load the shipped seed bank iff the questions table is empty. Returns #inserted.

    Idempotent and safe to call on every launch: once the table has any rows it's a
    no-op, so it seeds exactly once (a brand-new account) and never re-adds or clobbers.
    """
    try:
        row = conn.execute("SELECT COUNT(*) FROM questions").fetchone()
        if row and row[0]:  # already has questions → leave it alone
            return 0
    except sqlite3.Error:
        return 0

    items = _load_file()
    if not items:
        return 0

    inserted = 0
    cur = conn.cursor()
    for q in items:
        text = str(q.get("question", "")).strip()
        if not text:
            continue
        try:
            cur.execute(
                "INSERT OR IGNORE INTO questions(question, topic, difficulty, role, company, source) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    text,
                    str(q.get("topic", "")).strip(),
                    str(q.get("difficulty", "")).strip().lower(),
                    str(q.get("role", "")).strip(),
                    str(q.get("company", "")).strip(),
                    str(q.get("source", "")).strip(),
                ),
            )
            inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        except sqlite3.Error:
            continue
    try:
        conn.commit()
    except sqlite3.Error:
        return 0
    if inserted:
        log.info("seeded %d starter interview questions into a new question bank", inserted)
    return inserted
