"""Structured read-only views of the learner's state.

Shared by the dashboard (and usable by the TUI/CLI). Pure queries — no writes.
"""

from __future__ import annotations

from . import progress
from .db import connect
from .scoring import level_of
from .tools import AXES


def grid() -> dict:
    """The mastery grid as {pillar: {axis: {level, rating}}} plus the axis order."""
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT p.name AS pillar, r.axis AS axis, r.rating AS rating
               FROM ratings r JOIN pillars p ON p.id = r.pillar_id
               ORDER BY p.name"""
        ).fetchall()
    finally:
        conn.close()
    pillars: dict[str, dict] = {}
    for r in rows:
        pillars.setdefault(r["pillar"], {})[r["axis"]] = {
            "level": level_of(r["rating"]),
            "rating": round(r["rating"]),
        }
    return {"axes": list(AXES), "pillars": pillars}


def goals() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT horizon, text, deadline FROM goals WHERE status='active' "
            "ORDER BY CASE horizon WHEN 'long' THEN 0 WHEN 'medium' THEN 1 "
            "WHEN 'short' THEN 2 ELSE 3 END"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def recent_sessions(limit: int = 10) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT planned_min, xp, mode, started_at, ended_at "
            "FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def overview() -> dict:
    return {
        "stats": progress.stats(),
        "grid": grid(),
        "goals": goals(),
        "sessions": recent_sessions(),
    }
