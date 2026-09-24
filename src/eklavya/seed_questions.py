"""Ship a starter interview-question bank so a fresh account isn't empty.

`data/seed_questions.json` includes 218 questions from the learning-system parity work
(recovered from `scripts/seed_questions_expansion.py` on a stale branch — MCP/DSPy/
LangGraph internals, evals engineering, mechanistic interpretability, and more), on top
of the original starter bank, so every new account ships with the full breadth.

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


def _insert_items(conn: sqlite3.Connection, items: list[dict]) -> int:
    """INSERT OR IGNORE each item (deduped on the question text UNIQUE index). Returns
    #inserted. Never raises; a bad row is skipped, not fatal. Caller commits.

    Also used standalone (bypassing `ensure_seeded`'s empty-table gate) to bring an
    already-seeded account's bank up to date with a newer `seed_questions.json` — see
    the module docstring for the exact command.
    """
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
    return inserted


def ensure_seeded(conn: sqlite3.Connection) -> int:
    """Load the shipped seed bank iff the questions table is empty. Returns #inserted.

    Idempotent and safe to call on every launch: once the table has any rows it's a
    no-op, so it seeds exactly once (a brand-new account) and never re-adds or clobbers.
    An already-seeded (or hand-curated) account is deliberately left alone here — to
    bring an EXISTING account's bank up to date with a newer seed file, call
    `_insert_items(conn, _load_file())` directly (dedupes on question text; additive only).
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

    inserted = _insert_items(conn, items)
    if inserted:
        log.info("seeded %d starter interview questions into a new question bank", inserted)
    return inserted
