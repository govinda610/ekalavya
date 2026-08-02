"""Structured read-only views of the learner's state.

Shared by the dashboard (and usable by the TUI/CLI). Pure queries — no writes.
"""

from __future__ import annotations

from . import progress, subjects
from .db import connect
from .scoring import level_of
from .tools import AXES


def grid(subject: str | None = None) -> dict:
    """The mastery grid as {pillar: {axis: {level, rating}}} plus the axis order.

    Subject-aware (subject framework §4.5): without `subject` it returns the whole grid
    across every subject (axes = the union of CORE + every extension seen). With a
    `subject` it filters to that subject's pillars and reports that subject's declared
    axis order (CORE subset + extensions). Legacy single-subject callers keep working —
    with no subject the coding pillars still appear and the coding axes are included.
    """
    conn = connect()
    try:
        if subject:
            rows = conn.execute(
                """SELECT p.name AS pillar, r.axis AS axis, r.rating AS rating
                   FROM ratings r JOIN pillars p ON p.id = r.pillar_id
                   WHERE r.subject = ? ORDER BY p.name""",
                (subject,),
            ).fetchall()
        else:
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
    if subject:
        axes = list(subjects.axes_for(subject))
    else:
        # union: CORE first (canonical order), then any extension axis present, in a
        # stable registry order, so the whole-grid view has a sensible column order.
        seen = {ax for row in pillars.values() for ax in row}
        axes = [ax for ax in subjects.CORE_AXES if ax in seen or not pillars]
        for s in subjects.all_subjects():
            for ax in s.ext_axes:
                if ax in seen and ax not in axes:
                    axes.append(ax)
        if not axes:  # no ratings yet — show the default coding grid shape
            axes = list(subjects.axes_for(subjects.DEFAULT_SUBJECT))
    return {"axes": axes, "pillars": pillars, "subject": subject}


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


def active_pillar() -> str | None:
    """The pillar currently in focus — the most-recently-practised one. Used as a fallback
    to auto-tag an artifact's pillar when the guru saves one without naming it."""
    conn = connect()
    try:
        r = conn.execute(
            "SELECT p.name AS name FROM ratings r JOIN pillars p ON p.id = r.pillar_id "
            "WHERE r.last_practiced IS NOT NULL ORDER BY r.last_practiced DESC LIMIT 1"
        ).fetchone()
        return r["name"] if r else None
    finally:
        conn.close()


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


def ai_gap(subject: str | None = None) -> dict:
    """Unaided vs AI-assisted accuracy — the gap you're closing (Atrophy's idea).

    Returns the overall unaided/assisted success rates and a recent unaided-accuracy
    trend (per-day buckets), so the dashboard can show whether unaided skill is
    actually rising. Scoped to one `subject` when given (per-subject guardrail).
    """
    conn = connect()
    try:
        if subject:
            rows = conn.execute(
                "SELECT ai_off, correct, substr(created_at, 1, 10) AS day FROM attempts "
                "WHERE subject = ? ORDER BY created_at", (subject,)
            ).fetchall()
        else:
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


def _toposort_concepts(concepts: list[str], prereqs: dict[str, list[str]]) -> list[str]:
    """Order concepts so every prerequisite comes BEFORE what depends on it (Kahn's
    algorithm). Stable in the original order among independents; if the curriculum has a
    prereq cycle, its leftovers keep the original order at the end. Only prereqs that are
    known concept names constrain the order. This is what makes the forest read in true
    learning order (foundations → advanced) instead of raw insertion order."""
    from collections import deque

    known = set(concepts)
    indeg = {c: 0 for c in concepts}
    dependents: dict[str, list[str]] = {c: [] for c in concepts}
    for c in concepts:
        for p in prereqs.get(c, ()):  # p must be learned before c
            if p in known:
                dependents[p].append(c)
                indeg[c] += 1
    ready = deque(c for c in concepts if indeg[c] == 0)  # seed in original order → stable
    order: list[str] = []
    while ready:
        c = ready.popleft()
        order.append(c)
        for d in dependents[c]:
            indeg[d] -= 1
            if indeg[d] == 0:
                ready.append(d)
    if len(order) < len(concepts):  # a cycle left some out — append them as-is
        seen = set(order)
        order += [c for c in concepts if c not in seen]
    return order


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
        # The tutor-defined pillar order (task #89): per-pillar seq hint + the explicit
        # dependency DAG (prereq_pillars). Read here so forest_map can order by the real
        # DAG (topological), not the sparse concept-derived heuristic.
        pillar_seq, pillar_deps = _pillar_order_state(conn)
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
    ordered = _toposort_concepts(concepts, prereqs)  # prereqs before dependents → true order
    concepts_by_pillar: dict[str, list[str]] = {p: [] for p in pillars}
    for c in ordered:
        concepts_by_pillar[pillar_of[c]].append(c)

    def grove_status(p: str) -> str:
        cs = concepts_by_pillar[p]
        if cs and all(concept_status[c] == "done" for c in cs):
            return "blossoming"
        if any(concept_status[c] != "lock" for c in cs):
            return "unlocked"   # has a mastered or available concept, but not all done
        return "locked"

    statuses = {p: grove_status(p) for p in pillars}

    # The pillar dependency DAG (task #89): a pillar depends on another when the tutor marked
    # it a prereq (explicit `prereq_pillars`) OR when a concept in it lists a prereq that lives
    # in the other pillar (the legacy concept-derived edge). Explicit deps draw the branches the
    # tutor intends; concept-derived ones keep older curricula working. Independent pillars
    # (incl. across subjects) depend on nothing → free to sit on parallel branches.
    dep: dict[str, set[str]] = {p: set() for p in pillars}
    for c in concepts:
        pa = pillar_of[c]
        for pr in prereqs[c]:
            pb = pillar_of.get(pr)
            if pb and pb != pa:
                dep[pa].add(pb)                 # A depends on B
    for p in pillars:
        for pb in pillar_deps.get(p, ()):       # explicit tutor-marked prereq pillars
            if pb in dep and pb != p:
                dep[p].add(pb)

    # Deterministic tie-break key for the DAG order: (seq hint, legacy structural depth, name).
    structural_rank = {p: i for i, p in enumerate(
        _grove_order(pillars, concepts_by_pillar, prereqs, pillar_of))}
    # Base journey order with NO active anchoring — used to pick the fallback-active grove so
    # "where the learner should start" follows the tutor's order, not raw alphabetical.
    base_order = _pillar_dag_order(pillars, dep, pillar_seq, structural_rank, active=None)

    # The single ACTIVE grove = the most-recently-practised grove that isn't fully mastered.
    # If nothing's been practised, the FIRST non-locked grove in journey order leads the way.
    non_mastered = [p for p in base_order if statuses[p] != "blossoming"]
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
        # Drill-in: one grove's ordered concepts + the prerequisite EDGES between them.
        # Direct prereqs that live in OTHER pillars are surfaced as read-only CONTEXT
        # nodes so the sub-graph shows what unlocked this grove (and where it came from).
        if pillar not in concepts_by_pillar:
            return {"empty": True, "groves": [], "pillars": pillars, "viewbox": [0, 0, 900, 640]}
        cs = concepts_by_pillar[pillar]
        # dependency-order the concepts (topological within the pillar) so the sub-path
        # reads as a progression, and expose intra-pillar edges for the drill-in graph.
        cs = _topo_order(cs, prereqs)
        nodes = [{"name": c, "status": concept_status[c]} for c in cs]
        idx = {c: i for i, c in enumerate(cs)}
        c_edges = [{"from": pr, "to": c} for c in cs for pr in prereqs[c] if pr in idx]
        layout = _forest_layout(len(nodes))
        return {
            "empty": False, "pillar": pillar, "pillars": pillars,
            "grove": grove(pillar), "concepts": nodes, "edges": c_edges,
            "layout": layout, "viewbox": layout["viewbox"],
        }

    # Journey order: a TOPOLOGICAL sort of the pillar DAG (a pillar comes after all its
    # prereqs), with the ACTIVE pillar anchored at the entrance (index 0) and ties broken
    # deterministically by (seq hint, structural depth, name). Independent pillars are NOT
    # forced into a false linear order. forest2d.js renders groves in this array order.
    ordered_pillars = _pillar_dag_order(pillars, dep, pillar_seq, structural_rank, active)
    index_of = {p: i for i, p in enumerate(ordered_pillars)}

    # Prerequisite EDGES between groves (B → A: prereq → dependent) so the renderer can draw
    # branches for parallel tracks. Combines the concept-derived and explicit tutor deps.
    edge_set = {(b, a) for a in pillars for b in dep[a]}
    edges = [{"from": b, "to": a} for (b, a) in sorted(edge_set, key=lambda e: (index_of.get(e[0], 0), index_of.get(e[1], 0)))]

    groves = [grove(p) for p in ordered_pillars]
    for g in groves:
        g["order"] = index_of[g["pillar"]]
    layout = _forest_layout(len(groves))
    return {
        "empty": False, "pillars": ordered_pillars, "active": active,
        "groves": groves, "edges": edges, "order": ordered_pillars,
        "layout": layout, "viewbox": layout["viewbox"],
    }


def _grove_order(pillars, concepts_by_pillar, prereqs, pillar_of) -> list[str]:
    """Order pillars along the journey: a pillar's 'depth' is how deep its shallowest
    concept sits in the cross-pillar prerequisite chain — root pillars (whose earliest
    concept has no out-of-pillar prereqs) lead, frontier pillars trail. Ties break by a
    small size heuristic (bigger, more foundational pillars earlier) then name, so the
    walk is deterministic and re-derives identically as pillars are added/removed."""
    # cross-pillar dependency between pillars (A depends on B)
    dep: dict[str, set[str]] = {p: set() for p in pillars}
    for p in pillars:
        for c in concepts_by_pillar[p]:
            for pr in prereqs[c]:
                pb = pillar_of.get(pr)
                if pb and pb != p:
                    dep[p].add(pb)
    # longest-path depth in the pillar DAG (memoised; cycles guarded)
    depth: dict[str, int] = {}

    def d(p: str, stack: frozenset) -> int:
        if p in depth:
            return depth[p]
        if p in stack:
            return 0                              # break any accidental cycle
        ds = [d(b, stack | {p}) + 1 for b in dep[p] if b in dep]
        depth[p] = max(ds) if ds else 0
        return depth[p]

    for p in pillars:
        d(p, frozenset())
    return sorted(pillars, key=lambda p: (depth[p], -len(concepts_by_pillar[p]), p))


def _pillar_order_state(conn) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Read the tutor-defined pillar ordering (task #89) from the pillars table:
    {name: seq} (the tackle-order HINT; missing when unset) and {name: [prereq pillar names]}
    (the explicit dependency DAG). Guarded — tolerates databases that predate these columns."""
    seq: dict[str, int] = {}
    deps: dict[str, list[str]] = {}
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pillars)")}
    has_seq = "seq" in cols
    has_deps = "prereq_pillars" in cols
    if not (has_seq or has_deps):
        return seq, deps
    sel = "name" + (", seq" if has_seq else "") + (", prereq_pillars" if has_deps else "")
    for r in conn.execute(f"SELECT {sel} FROM pillars"):
        name = (r["name"] or "").strip()
        if has_seq and r["seq"] is not None:
            seq[name] = r["seq"]
        if has_deps and r["prereq_pillars"]:
            deps[name] = [p.strip() for p in r["prereq_pillars"].split("|")
                          if p.strip() and p.strip() != name]
    return seq, deps


def _pillar_dag_order(pillars, dep, pillar_seq, structural_rank, active) -> list[str]:
    """Topological order of the pillar dependency DAG, anchored so the ACTIVE pillar is the
    entrance (index 0). A pillar is emitted only after all its (in-set) prereq pillars; among
    the pillars whose prereqs are all satisfied we pick deterministically by
    (NOT-active, seq hint, structural depth, name) — so the active pillar wins the very first
    pick, and independents keep a stable order without being forced into a false line.

    Kahn's algorithm with a sorted 'ready' frontier. Cycles (shouldn't happen) are broken by
    dropping the offending back-edges: any pillar left unemitted is appended in the same
    deterministic key order, so the function is total and never loses a pillar."""
    _BIG = len(pillars) + 1

    def key(p: str) -> tuple:
        return (0 if p == active else 1,
                pillar_seq.get(p, _BIG),
                structural_rank.get(p, _BIG),
                p)

    remaining = set(pillars)
    indeg = {p: len({b for b in dep[p] if b in remaining}) for p in pillars}
    order: list[str] = []
    while remaining:
        ready = [p for p in remaining if indeg[p] == 0]
        if not ready:                              # cycle: force the best-keyed one through
            ready = list(remaining)
        nxt = min(ready, key=key)
        order.append(nxt)
        remaining.discard(nxt)
        for p in remaining:
            if nxt in dep[p]:
                indeg[p] -= 1
    return order


def legacy_grove_order(conn) -> list[str]:
    """The PRE-#89 structural journey order over EVERY pillar — used once, by the migration,
    to backfill `seq` so a database created before task #89 reproduces its old map order until
    the tutor sets an explicit one. Derives the concept DAG from the curriculum, orders the
    pillars that have concepts via `_grove_order`, then appends any pillar with no curriculum
    rows (ordered by name) so the result covers the whole pillars table deterministically."""
    rows = conn.execute("SELECT concept, prereqs, pillar FROM curriculum ORDER BY id").fetchall()
    all_pillars = [(r["name"] or "").strip() for r in
                   conn.execute("SELECT name FROM pillars ORDER BY id")]
    curric_pillars = sorted({(r["pillar"] or "").strip() for r in rows} - {""})
    concepts = [r["concept"] for r in rows]
    pillar_of = {r["concept"]: (r["pillar"] or "").strip() for r in rows}
    parse = _parse_prereqs_factory(concepts)
    prereqs = {r["concept"]: parse(r["prereqs"], r["concept"]) for r in rows}
    concepts_by_pillar: dict[str, list[str]] = {p: [] for p in curric_pillars}
    for c in concepts:
        p = pillar_of[c]
        if p in concepts_by_pillar:
            concepts_by_pillar[p].append(c)
    ordered = _grove_order(curric_pillars, concepts_by_pillar, prereqs, pillar_of)
    seen = set(ordered)
    ordered += sorted(p for p in all_pillars if p and p not in seen)
    return ordered


def _topo_order(items: list[str], prereqs: dict[str, list[str]]) -> list[str]:
    """Stable topological order of `items` by their (in-set) prereqs — a concept comes
    after every prereq that is also in `items`. Preserves original order among peers and
    is robust to cycles (falls back to original position). Used for the grove drill-in."""
    inset = set(items)
    pos = {c: i for i, c in enumerate(items)}
    out: list[str] = []
    seen: set[str] = set()

    def visit(c: str, stack: frozenset) -> None:
        if c in seen or c in stack:
            return
        for pr in sorted((p for p in prereqs.get(c, []) if p in inset), key=lambda p: pos[p]):
            visit(pr, stack | {c})
        seen.add(c)
        out.append(c)

    for c in items:
        visit(c, frozenset())
    return out



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
