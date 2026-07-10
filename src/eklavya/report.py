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


def due_count() -> int:
    from .scheduling import due_now

    return len(due_now())


def is_first_run() -> bool:
    """True when Ekalavya has no ratings yet — i.e. the learner hasn't onboarded
    to Ekalavya (keyed off our own state, not a shared teacher-mode profile)."""
    from .db import connect, schema_version

    if schema_version() is None:
        return True
    conn = connect()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"] == 0
    finally:
        conn.close()


def ai_gap() -> dict:
    """Unaided vs AI-assisted accuracy — the gap you're closing (Atrophy's idea).

    Returns the overall unaided/assisted success rates and a recent unaided-accuracy
    trend (per-day buckets), so the dashboard can show whether unaided skill is
    actually rising.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT ai_off, correct, substr(created_at, 1, 10) AS day FROM attempts "
            "ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()

    def rate(items):
        return round(100 * sum(r["correct"] for r in items) / len(items)) if items else None

    unaided = [r for r in rows if r["ai_off"]]
    assisted = [r for r in rows if not r["ai_off"]]

    # recent unaided accuracy per day (last 10 active days)
    days: dict[str, list] = {}
    for r in unaided:
        days.setdefault(r["day"], []).append(r)
    trend = [{"day": d, "rate": rate(days[d]), "n": len(days[d])}
             for d in sorted(days)][-10:]

    ur, ar = rate(unaided), rate(assisted)
    return {
        "unaided_rate": ur, "unaided_n": len(unaided),
        "assisted_rate": ar, "assisted_n": len(assisted),
        "gap": (ar - ur) if (ur is not None and ar is not None) else None,
        "trend": trend,
    }


def curriculum_mermaid() -> dict:
    """The curriculum graph as a Mermaid diagram, nodes coloured by mastery.

    A concept is 'done' if it has a correct attempt, 'avail' if all its prereqs are
    done (so it's unlocked), else 'lock'.
    """
    conn = connect()
    try:
        rows = conn.execute("SELECT concept, prereqs FROM curriculum ORDER BY id").fetchall()
        mastered = {r["detail"] for r in
                    conn.execute("SELECT DISTINCT detail FROM attempts WHERE correct = 1")}
    finally:
        conn.close()
    if not rows:
        return {"empty": True, "mermaid": ""}

    concepts = [r["concept"] for r in rows]
    ids = {c: f"n{i}" for i, c in enumerate(concepts)}
    prereqs = {r["concept"]: [p.strip() for p in (r["prereqs"] or "").split(",") if p.strip()]
               for r in rows}

    def status(c: str) -> str:
        if c in mastered:
            return "done"
        return "avail" if all(p in mastered for p in prereqs[c]) else "lock"

    lines = ["graph TD"]
    for c in concepts:
        label = c.replace('"', "'")
        lines.append(f'  {ids[c]}["{label}"]:::{status(c)}')
    for c in concepts:
        for p in prereqs[c]:
            if p in ids:
                lines.append(f"  {ids[p]} --> {ids[c]}")
    lines += [
        "  classDef done fill:#0e2a1f,stroke:#5ef2b8,color:#5ef2b8;",
        "  classDef avail fill:#0a1a22,stroke:#57d3ff,color:#57d3ff;",
        "  classDef lock fill:#0e1622,stroke:#2b3a4d,color:#5a6b80;",
    ]
    return {"empty": False, "mermaid": "\n".join(lines)}


def overview() -> dict:
    return {
        "stats": progress.stats(),
        "grid": grid(),
        "goals": goals(),
        "sessions": recent_sessions(),
        "due": due_count(),
        "ai_gap": ai_gap(),
    }
