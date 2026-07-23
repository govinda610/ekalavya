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


def curriculum_mermaid(pillar: str | None = None) -> dict:
    """The curriculum graph as a Mermaid diagram, nodes coloured by mastery.

    A concept is 'done' if it has a correct attempt, 'avail' if all its prereqs are
    done (so it's unlocked), else 'lock'. `pillar` filters to one track (its concepts
    plus their direct prereqs for context) so a large tree stays readable; the full
    list of pillars is returned for a filter control.
    """
    conn = connect()
    try:
        rows = conn.execute("SELECT concept, prereqs, pillar FROM curriculum ORDER BY id").fetchall()
        mastered = {r["detail"] for r in
                    conn.execute("SELECT DISTINCT detail FROM attempts WHERE correct = 1")}
    finally:
        conn.close()
    pillars = sorted({(r["pillar"] or "").strip() for r in rows} - {""})
    if not rows:
        return {"empty": True, "mermaid": "", "pillars": pillars}

    concepts = [r["concept"] for r in rows]
    pillar_of = {r["concept"]: (r["pillar"] or "").strip() for r in rows}
    ids = {c: f"n{i}" for i, c in enumerate(concepts)}
    # Prereqs are stored as free text that names other concepts. Concept names can
    # contain commas (e.g. "Core data structures (list, dict, set, tuple)"), so we
    # can't split on ",". Instead, detect which known concept names occur in the
    # prereq text (longest first, so a short name can't shadow a longer one).
    by_len = sorted(concepts, key=len, reverse=True)

    def parse_prereqs(text: str, own: str) -> list[str]:
        text = (text or "").strip()
        if "|" in text:  # new format: pipe-delimited EXACT concept names (unambiguous)
            return [p.strip() for p in text.split("|") if p.strip() and p.strip() != own]
        found: list[str] = []  # legacy free-text: detect known concept names (longest first)
        for name in by_len:
            if name != own and name in text and name not in found:
                found.append(name)
        return found

    prereqs = {r["concept"]: parse_prereqs(r["prereqs"], r["concept"]) for r in rows}

    def status(c: str) -> str:
        if c in mastered:
            return "done"
        return "avail" if all(p in mastered for p in prereqs[c]) else "lock"

    def label(c: str) -> str:
        # Sanitize for Mermaid node labels: quotes and brackets break the parser.
        return (c.replace('"', "'").replace("[", "(").replace("]", ")")
                 .replace("{", "(").replace("}", ")"))

    # which concepts to draw: one track (+ its direct prereqs) when filtered, else all
    if pillar:
        shown = {c for c in concepts if pillar_of[c] == pillar}
        for c in list(shown):
            shown.update(prereqs[c])
        render = [c for c in concepts if c in shown]
        direction = "graph LR"  # a single track reads as a left→right path
    else:
        render = concepts
        direction = "graph TD"

    lines = [direction]
    for c in render:
        lines.append(f'  {ids[c]}["{label(c)}"]:::{status(c)}')
    for c in render:
        for p in prereqs[c]:
            if p in ids and p in render:
                lines.append(f"  {ids[p]} --> {ids[c]}")
    lines += [
        "  classDef done fill:#0e2a1f,stroke:#5ef2b8,color:#5ef2b8;",
        "  classDef avail fill:#0a1a22,stroke:#57d3ff,color:#57d3ff;",
        "  classDef lock fill:#0e1622,stroke:#2b3a4d,color:#5a6b80;",
    ]
    return {"empty": False, "mermaid": "\n".join(lines), "pillars": pillars}


def overview() -> dict:
    return {
        "stats": progress.stats(),
        "grid": grid(),
        "goals": goals(),
        "sessions": recent_sessions(),
        "due": due_count(),
        "ai_gap": ai_gap(),
    }
