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


def _norm_concept(s: str) -> str:
    """Normalise a concept name for matching curriculum nodes to recorded attempts
    (lower-cased, whitespace-collapsed) so trivial wording drift doesn't leave a
    mastered node stuck 'locked'."""
    return " ".join((s or "").lower().split())


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
        # Match on a normalised key so a correct attempt recorded as e.g. "Async and
        # Event Loops" still marks the node "async and event loops" done. Exact-string
        # matching left every node locked whenever the model's wording drifted at all.
        mastered = {_norm_concept(r["detail"]) for r in
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
        if _norm_concept(c) in mastered:
            return "done"
        return "avail" if all(_norm_concept(p) in mastered for p in prereqs[c]) else "lock"

    def label(c: str) -> str:
        # Sanitize for Mermaid node labels: quotes and brackets break the parser.
        s = (c.replace('"', "'").replace("[", "(").replace("]", ")")
              .replace("{", "(").replace("}", ")"))
        # Wrap a long label onto two lines so nodes stay narrow (no wide tracks).
        if len(s) > 26:
            cut = s.rfind(" ", 0, 30)
            if cut > 12:
                s = s[:cut] + "<br/>" + s[cut + 1:]
        return s

    ramp = [
        # Option-E ramp: gold = mastered, peacock-teal = unlocked, muted stone = locked.
        "  classDef done fill:#2a2012,stroke:#e7b64b,color:#f7d98a;",
        "  classDef avail fill:#0a1a22,stroke:#57d3ce,color:#57d3ce;",
        "  classDef lock fill:#12100c,stroke:#3a2f26,color:#a89670;",
    ]

    # No filter → a legible PILLAR-LEVEL forest map: one node per grove (17, not the 197-node
    # hairball), edges aggregated from cross-pillar concept prereqs. A grove is 'done' when all
    # its concepts are mastered, 'avail' when every unmastered concept is already unlocked, else
    # 'lock'. Reading concept labels is the single-track view's job (chosen from the filter).
    if not pillar:
        pids = {p: f"p{i}" for i, p in enumerate(pillars)}
        edges = set()
        for c in concepts:
            for p in prereqs[c]:
                a, b = pillar_of.get(p, ""), pillar_of[c]
                if a and b and a != b:
                    edges.add((a, b))

        def pillar_status(p: str) -> str:
            cs = [c for c in concepts if pillar_of[c] == p]
            if cs and all(status(c) == "done" for c in cs):
                return "done"
            if all(status(c) != "lock" for c in cs):
                return "avail"
            return "lock"

        lines = ["graph LR"]
        for p in pillars:
            done = sum(1 for c in concepts if pillar_of[c] == p and status(c) == "done")
            total = sum(1 for c in concepts if pillar_of[c] == p)
            lines.append(f'  {pids[p]}["{label(p)}<br/>{done}/{total}"]:::{pillar_status(p)}')
        for a, b in sorted(edges):
            lines.append(f"  {pids[a]} --> {pids[b]}")
        lines += ramp
        return {"empty": False, "mermaid": "\n".join(lines), "pillars": pillars}

    # A single track (+ its direct prereqs) renders TOP-DOWN so a long chain stacks
    # vertically (natural web scroll) instead of overflowing wide to the right.
    shown = {c for c in concepts if pillar_of[c] == pillar}
    for c in list(shown):
        shown.update(prereqs[c])
    render = [c for c in concepts if c in shown]

    lines = ["graph TD"]
    for c in render:
        lines.append(f'  {ids[c]}["{label(c)}"]:::{status(c)}')
    for c in render:
        for p in prereqs[c]:
            if p in ids and p in render:
                lines.append(f"  {ids[p]} --> {ids[c]}")
    lines += ramp
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
