"""Learner feedback capture (docs/EFFECTIVENESS_MEASUREMENT.md §7).

A small, pure module that records what the learner thought of a turn — a 1-tap
rating and/or free text, tied to the concept/mode so it's *attributable*, not a
global mood. Every rating is also future fine-tuning / training data, and the
per-concept rating vs later unaided-retention correlation is itself a finding
(desirable-difficulty: a drill users love may teach them less — §7).

Pure and simple, contextvar-aware via ``connect()`` so it always reads/writes the
CURRENT user's own database (each user has their own db → no cross-user risk).
"""

from __future__ import annotations

from .db import connect

_KINDS = ("drill", "session", "freeform")


def record(kind: str, rating: int | None = None, text: str | None = None,
           concept: str | None = None, mode: str | None = None,
           thread: str | None = None) -> None:
    """Insert one feedback row for the current user.

    ``rating`` (1..5) and ``text`` are both optional — a 1-tap rating and an open
    note are equally valid. Unknown ``kind`` values fall back to 'freeform' so a
    stray client can't write garbage into the dimension used for grouping.
    """
    if kind not in _KINDS:
        kind = "freeform"
    if rating is not None:
        rating = max(1, min(5, int(rating)))  # clamp to the 1..5 scale
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO feedback (kind, rating, text, concept, mode, thread) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (kind, rating, text, concept, mode, thread),
        )
        conn.commit()
    finally:
        conn.close()


def recent(limit: int = 50) -> list[dict]:
    """The most recent feedback rows, newest first (a plain list of dicts)."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, kind, rating, text, concept, mode, thread, created_at "
            "FROM feedback ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def summary() -> dict:
    """Counts + average rating, overall and per mode (JSON-serialisable).

    Returns zeros/empty when there's no data yet. The average is over rows that
    actually carry a rating (text-only feedback doesn't drag it toward zero).
    """
    conn = connect()
    try:
        overall = conn.execute(
            "SELECT COUNT(*) AS n, AVG(rating) AS avg_rating FROM feedback"
        ).fetchone()
        rated = conn.execute(
            "SELECT COUNT(*) AS n FROM feedback WHERE rating IS NOT NULL"
        ).fetchone()["n"]
        per_mode = conn.execute(
            "SELECT mode, COUNT(*) AS n, AVG(rating) AS avg_rating "
            "FROM feedback GROUP BY mode ORDER BY n DESC"
        ).fetchall()
    finally:
        conn.close()

    modes = {
        (r["mode"] or "unknown"): {
            "count": r["n"],
            "avg_rating": round(r["avg_rating"], 2) if r["avg_rating"] is not None else None,
        }
        for r in per_mode
    }
    return {
        "total": overall["n"],
        "rated": rated,
        "avg_rating": round(overall["avg_rating"], 2) if overall["avg_rating"] is not None else None,
        "by_mode": modes,
    }
