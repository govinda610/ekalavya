"""Spaced repetition via FSRS.

Each concept is a "card." We map how the attempt went to an FSRS rating, review
the card, and persist its state so future sessions surface it exactly when it's
about to be forgotten. The full card is stored as JSON so no state is lost.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fsrs import Card, Rating, Scheduler

from .db import connect

_scheduler = Scheduler()


def _rating(correct: bool, confidence: int) -> Rating:
    if not correct:
        return Rating.Again
    # Correct: reward calibrated confidence, but don't over-reward a lucky guess.
    if confidence >= 3:
        return Rating.Easy
    if confidence == 2:
        return Rating.Good
    return Rating.Hard


def schedule(concept: str, correct: bool, confidence: int = 2) -> str:
    """Review the concept's card and persist it. Returns the next due date (ISO)."""
    conn = connect()
    try:
        row = conn.execute("SELECT state_json FROM cards WHERE ref = ?", (concept,)).fetchone()
        card = Card.from_json(row["state_json"]) if row and row["state_json"] else Card()
        card, _ = _scheduler.review_card(card, _rating(correct, confidence))
        due = card.due.astimezone(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            """INSERT INTO cards(ref, stability, difficulty, due, lapses, state_json)
               VALUES(?, ?, ?, ?, ?, ?)
               ON CONFLICT(ref) DO UPDATE SET
                 stability=excluded.stability, difficulty=excluded.difficulty,
                 due=excluded.due, lapses=cards.lapses + (CASE WHEN ?=0 THEN 1 ELSE 0 END),
                 state_json=excluded.state_json""",
            (concept, card.stability, card.difficulty, due, 0 if correct else 1,
             card.to_json(), int(correct)),
        )
        conn.commit()
    finally:
        conn.close()
    return due


def due_now() -> list[str]:
    """Concept refs whose review is due (or overdue) as of now."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = connect()
    try:
        rows = conn.execute("SELECT ref FROM cards WHERE due IS NOT NULL AND due <= ?", (now,)).fetchall()
    finally:
        conn.close()
    return [r["ref"] for r in rows]
