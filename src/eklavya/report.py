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


def _parse_prereqs_factory(concepts: list[str]):
    """Build a prereq parser closed over the known concept names.

    Prereqs are stored as free text that names other concepts. Concept names can
    contain commas (e.g. "Core data structures (list, dict, set, tuple)"), so we
    can't split on ",". The new format is pipe-delimited EXACT names; the legacy
    format is free text in which we detect known concept names (longest first, so
    a short name can't shadow a longer one).
    """
    by_len = sorted(concepts, key=len, reverse=True)

    def parse(text: str, own: str) -> list[str]:
        text = (text or "").strip()
        if "|" in text:
            return [p.strip() for p in text.split("|") if p.strip() and p.strip() != own]
        found: list[str] = []
        for name in by_len:
            if name != own and name in text and name not in found:
                found.append(name)
        return found

    return parse


def forest_map(pillar: str | None = None) -> dict:
    """The curriculum as a DATA-DRIVEN forest map, derived live from the db.

    Everything here comes from the curriculum + attempts — nothing is hard-coded,
    so the map auto-updates as pillars/concepts are added and as the learner
    progresses. A concept is:
      • done   — it has a correct attempt (matched on a normalised name so trivial
                 wording drift doesn't leave a mastered node stuck locked);
      • avail  — not done, but all its prereqs are done (so it's unlocked);
      • lock   — some prereq isn't done yet.

    Each pillar becomes a GROVE with a status:
      • blossoming — every concept done;
      • active     — the current focus: the most-recently-practised grove that
                     isn't fully mastered (falls back to the first grove that has
                     any unlocked concept when nothing has been practised);
      • unlocked   — has at least one available (unlocked) concept but isn't active;
      • locked     — a bare sapling: no concept is unlocked yet.

    Without `pillar` this returns the full forest (one grove per pillar) plus a
    winding-path layout that scales/wraps for any number of groves. With `pillar`
    it returns that one grove's ordered concepts as a sub-path (same data shape,
    for the drill-in).
    """
    conn = connect()
    try:
        rows = conn.execute("SELECT concept, prereqs, pillar FROM curriculum ORDER BY id").fetchall()
        mastered = {_norm_concept(r["detail"]) for r in
                    conn.execute("SELECT DISTINCT detail FROM attempts WHERE correct = 1")}
        # Recency of practice per pillar → which grove is the current focus. We take
        # the newest of (a) a rating's last_practiced and (b) an attempt whose concept
        # maps into that pillar, so a fresh attempt lights the right grove immediately.
        recency: dict[str, str] = {}
        for r in conn.execute(
            "SELECT p.name AS pillar, MAX(r.last_practiced) AS ts FROM ratings r "
            "JOIN pillars p ON p.id = r.pillar_id WHERE r.last_practiced IS NOT NULL "
            "GROUP BY p.name"
        ):
            if r["ts"]:
                recency[(r["pillar"] or "").strip()] = r["ts"]
    finally:
        conn.close()

    pillars = sorted({(r["pillar"] or "").strip() for r in rows} - {""})
    if not rows or not pillars:
        return {"empty": True, "groves": [], "pillars": pillars, "viewbox": [0, 0, 900, 640]}

    concepts = [r["concept"] for r in rows]
    pillar_of = {r["concept"]: (r["pillar"] or "").strip() for r in rows}
    parse_prereqs = _parse_prereqs_factory(concepts)
    prereqs = {r["concept"]: parse_prereqs(r["prereqs"], r["concept"]) for r in rows}

    def status(c: str) -> str:
        if _norm_concept(c) in mastered:
            return "done"
        return "avail" if all(_norm_concept(p) in mastered for p in prereqs[c]) else "lock"

    concept_status = {c: status(c) for c in concepts}
    concepts_by_pillar: dict[str, list[str]] = {p: [] for p in pillars}
    for c in concepts:
        concepts_by_pillar[pillar_of[c]].append(c)

    def grove_status(p: str) -> str:
        cs = concepts_by_pillar[p]
        if cs and all(concept_status[c] == "done" for c in cs):
            return "blossoming"
        if any(concept_status[c] != "lock" for c in cs):
            return "unlocked"   # has a mastered or available concept, but not all done
        return "locked"

    statuses = {p: grove_status(p) for p in pillars}

    # The single ACTIVE grove = the most-recently-practised grove that isn't fully
    # mastered. If nothing's been practised, the first non-locked grove leads the way.
    non_mastered = [p for p in pillars if statuses[p] != "blossoming"]
    active = None
    practised = [p for p in non_mastered if p in recency]
    if practised:
        active = max(practised, key=lambda p: recency[p])
    else:
        unlocked = [p for p in non_mastered if statuses[p] == "unlocked"]
        active = unlocked[0] if unlocked else (non_mastered[0] if non_mastered else None)

    def grove(p: str) -> dict:
        cs = concepts_by_pillar[p]
        done = sum(1 for c in cs if concept_status[c] == "done")
        st = "active" if p == active else statuses[p]
        return {
            "pillar": p,
            "status": st,
            "done": done,
            "total": len(cs),
            "concepts": [{"name": c, "status": concept_status[c]} for c in cs],
        }

    if pillar:
        # Drill-in: one grove's ordered concepts (+ direct-prereq context concepts
        # that live in other pillars, so the sub-path shows what unlocked it).
        if pillar not in concepts_by_pillar:
            return {"empty": True, "groves": [], "pillars": pillars, "viewbox": [0, 0, 900, 640]}
        cs = concepts_by_pillar[pillar]
        nodes = [{"name": c, "status": concept_status[c]} for c in cs]
        layout = _forest_layout(len(nodes))
        return {
            "empty": False, "pillar": pillar, "pillars": pillars,
            "grove": grove(pillar), "concepts": nodes,
            "layout": layout, "viewbox": layout["viewbox"],
        }

    groves = [grove(p) for p in pillars]
    layout = _forest_layout(len(groves))
    return {
        "empty": False, "pillars": pillars, "active": active,
        "groves": groves, "layout": layout, "viewbox": layout["viewbox"],
    }


def _forest_layout(n: int) -> dict:
    """Place N nodes along a winding path that CLIMBS and WRAPS as N grows.

    Returns {viewbox:[x,y,w,h], points:[{x,y}...] bottom→top in walk order}. The
    path serpentines up the canvas in horizontal rows (boustrophedon), so it reads
    as one continuous trail whether there are 5 groves or 50 — the canvas just gets
    taller. Column count adapts to N so a handful of groves don't sprawl.
    """
    W = 900
    if n <= 0:
        return {"viewbox": [0, 0, W, 640], "points": [], "rows": 0, "cols": 0}
    # Aim for a comfortable density: ~3–5 groves per row.
    import math

    cols = max(2, min(5, math.ceil(math.sqrt(n * 1.4))))
    rows = math.ceil(n / cols)
    row_h = 180                      # vertical spacing between rows
    margin_x, margin_top, margin_bot = 130, 90, 120
    H = margin_top + margin_bot + (rows - 1) * row_h
    H = max(H, 560)
    usable_w = W - 2 * margin_x
    points: list[dict] = []
    for i in range(n):
        row = i // cols
        col = i % cols
        # bottom row is the start of the walk → invert row index for y (climb up)
        y = H - margin_bot - row * row_h
        # serpentine: even rows L→R, odd rows R→L
        in_row = min(cols, n - row * cols)     # groves on this row (last row may be short)
        span = usable_w if in_row > 1 else 0
        t = col / (in_row - 1) if in_row > 1 else 0.5
        x = margin_x + (t if row % 2 == 0 else (1 - t)) * span
        if in_row == 1:
            x = W / 2
        points.append({"x": round(x, 1), "y": round(y, 1)})
    return {"viewbox": [0, 0, W, round(H)], "points": points, "rows": rows, "cols": cols}


def _gap_phrase(days: float) -> str:
    if days < 0.5:
        return "last visit a few hours ago"
    if days < 1.5:
        return "last visit yesterday"
    if days < 14:
        return f"last visit {round(days)} days ago"
    if days < 60:
        return f"last visit ~{round(days / 7)} weeks ago"
    return f"last visit ~{round(days / 30)} months ago"


def session_context() -> dict:
    """Temporal state for the tutor: current-sitting clock, gap since last visit, and a
    recap of last time (topics derived from the previous session's recorded attempts).

    Everything is derived live from the sessions/attempts tables — no clock is baked into
    the (cached) system prompt, so injecting this each turn keeps the agent's sense of time
    fresh. `last_topics` uses the previous session's `session_id`-tagged attempts, which
    sidesteps timestamp-format mismatches entirely. (Richer narrative continuity lives in
    the learner's profile.md, which the tutor reads each session.)
    """
    from datetime import datetime, timezone

    from .progress import _parse_ts, stats
    from .scheduling import due_now

    conn = connect()
    try:
        cur = conn.execute(
            "SELECT id, planned_min, started_at, last_active FROM sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
        prev = conn.execute(
            "SELECT id, started_at, last_active, ended_at FROM sessions "
            "WHERE id < ? ORDER BY id DESC LIMIT 1", (cur["id"],)
        ).fetchone() if cur else None
        last_topics: list[str] = []
        if prev:
            last_topics = [r["detail"] for r in conn.execute(
                "SELECT DISTINCT detail FROM attempts WHERE session_id = ? "
                "AND detail IS NOT NULL AND detail != '' ORDER BY id DESC LIMIT 6", (prev["id"],)
            )]
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    elapsed = None
    if cur and (st := _parse_ts(cur["started_at"])):
        elapsed = max(0, round((now - st).total_seconds() / 60))
    gap_days = None
    if prev and (pt := _parse_ts(prev["ended_at"] or prev["last_active"] or prev["started_at"])):
        gap_days = (now - pt).total_seconds() / 86400
    s = stats()
    return {
        "date": now.strftime("%Y-%m-%d"), "weekday": now.strftime("%a"),
        "session_elapsed_min": elapsed,
        "planned_min": cur["planned_min"] if cur else None,
        "gap_days": round(gap_days, 1) if gap_days is not None else None,
        "sessions_total": total, "streak": s["streak"],
        "last_topics": last_topics, "due_count": len(due_now()),
    }


def session_context_line() -> str:
    """A compact one-line temporal briefing to prepend to the tutor's turn context."""
    c = session_context()
    parts: list[str] = []
    if c["session_elapsed_min"] is not None and c["planned_min"]:
        parts.append(f"{c['session_elapsed_min']}m elapsed of a planned {c['planned_min']}m")
    if c["gap_days"] is not None:
        parts.append(_gap_phrase(c["gap_days"]))
    if c["sessions_total"]:
        parts.append(f"session #{c['sessions_total']}")
    if c["streak"]:
        parts.append(f"{c['streak']}-day streak")
    if c["last_topics"]:
        parts.append("last time: " + ", ".join(c["last_topics"][:5])[:160])
    if c["due_count"]:
        parts.append(f"{c['due_count']} review(s) due")
    parts.append(f"today is {c['weekday']} {c['date']}")
    return "[session context — " + " · ".join(parts) + "]"


def with_session_context(text: str) -> str:
    """Prepend the fresh private session-context briefing to a user turn (no-op on error).

    Shared by every surface (web/CLI/TUI) so temporal awareness is uniform — the same
    `[session context — …]` line the web injects also reaches CLI and TUI turns.
    """
    try:
        line = session_context_line()
    except Exception:
        return text
    return f"{line}\n\n{text}" if (text and text.strip()) else line


def overview() -> dict:
    return {
        "stats": progress.stats(),
        "grid": grid(),
        "goals": goals(),
        "sessions": recent_sessions(),
        "due": due_count(),
        "ai_gap": ai_gap(),
    }
