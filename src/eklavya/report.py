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
        # Drill-in: one grove's ordered concepts + the prerequisite EDGES between them.
        # Direct prereqs that live in OTHER pillars are surfaced as read-only CONTEXT
        # nodes so the sub-graph shows what unlocked this grove (and where it came from).
        if pillar not in concepts_by_pillar:
            return {"empty": True, "groves": [], "pillars": pillars, "viewbox": [0, 0, 900, 640]}
        cs = concepts_by_pillar[pillar]
        own = set(cs)
        nodes = [{"name": c, "status": concept_status[c],
                  "prereqs": list(prereqs[c]),
                  "unlocks": [d for d in concepts if c in prereqs.get(d, ()) and d in own]}
                 for c in cs]
        # concept→prereq edges within the grove, and external prereqs → context nodes.
        edges: list[dict] = []
        context: list[dict] = []
        seen_ctx: set[str] = set()
        for c in cs:
            for p_ in prereqs[c]:
                if p_ in own:
                    edges.append({"src": p_, "dst": c})            # both live here
                elif p_ in pillar_of:                              # external prereq → context node
                    if p_ not in seen_ctx:
                        seen_ctx.add(p_)
                        context.append({"name": p_, "status": concept_status[p_],
                                        "pillar": pillar_of[p_]})
                    edges.append({"src": p_, "dst": c, "external": True})
        layout = _forest_layout(len(nodes))
        dag = _dag_layout(cs, edges)
        land = _landscape_layout(cs, edges)
        return {
            "empty": False, "pillar": pillar, "pillars": pillars,
            "grove": grove(pillar), "concepts": nodes,
            "edges": edges, "context": context,
            "layout": layout, "viewbox": layout["viewbox"],
            "dag": dag, "land": land,
        }

    groves = [grove(p) for p in pillars]
    # Cross-pillar grove→grove dependency EDGES: pillar A depends on pillar B when any
    # concept in A has a prereq that lives in B (self-loops excluded). De-duplicated,
    # so the overview reads as a true (coarse) DAG over the groves.
    grove_edges: list[dict] = []
    seen_edge: set[tuple] = set()
    for c in concepts:
        a = pillar_of[c]
        for p_ in prereqs.get(c, ()):
            b = pillar_of.get(p_)
            if b and b != a and (b, a) not in seen_edge:
                seen_edge.add((b, a))
                grove_edges.append({"src": b, "dst": a})           # B unlocks → A

    # SEQUENTIAL learning ORDER over the groves — the walkable path the 3D forest lays out.
    # Toposort the coarse grove DAG (foundations first) so a milestone tree only appears
    # after the groves it builds on. Ties break by grove-depth then name, so the sequence
    # is deterministic and stable across loads. Purely additive: each grove gets an `order`.
    grove_order = _toposort_concepts(pillars, {
        p: [e["src"] for e in grove_edges if e["dst"] == p] for p in pillars
    })
    order_of = {p: i for i, p in enumerate(grove_order)}
    # Saved-artifact count per pillar → a subtle lantern/scroll glint on that grove.
    from . import artifacts as _artifacts
    art_counts: dict[str, int] = {}
    try:
        for p in pillars:
            art_counts[p] = len(_artifacts.list_artifacts(pillar=p))
    except Exception:
        art_counts = {p: 0 for p in pillars}
    for g in groves:
        g["order"] = order_of.get(g["pillar"], 0)
        g["artifacts"] = art_counts.get(g["pillar"], 0)
    groves.sort(key=lambda g: g["order"])   # emit in walk order (additive; consumers may re-sort)

    layout = _forest_layout(len(groves))
    dag = _dag_layout(pillars, grove_edges)
    land = _landscape_layout(pillars, grove_edges)
    return {
        "empty": False, "pillars": pillars, "active": active,
        "groves": groves, "edges": grove_edges,
        "layout": layout, "viewbox": layout["viewbox"],
        "dag": dag, "land": land,
    }


def _dag_layout(names: list[str], edges: list[dict]) -> dict:
    """Layered ('Sugiyama-lite') coordinates for a prerequisite DAG.

    Every node lands in a LAYER equal to its longest prerequisite chain depth (so
    foundations sit at the top and advanced work flows downward), then nodes spread
    evenly across their layer. Wide layers wrap onto stacked sub-rows so a 43-node
    grove still fits without clipping. Returns {viewbox, pos:{name:{x,y}}, layers:N}
    — the render threads organic branch/vine paths through these points.

    Only edges whose endpoints are both in `names` constrain the layering; unknown
    endpoints (external context) are ignored here and placed by the caller.
    """
    known = set(names)
    deps: dict[str, list[str]] = {n: [] for n in names}   # n depends on deps[n]
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if s in known and d in known and s != d:
            deps[d].append(s)

    # longest-path depth = layer (memoised; cycle-safe via a visiting guard).
    depth: dict[str, int] = {}
    visiting: set[str] = set()

    def layer_of(n: str) -> int:
        if n in depth:
            return depth[n]
        if n in visiting:          # a cycle — break it so we never recurse forever
            return 0
        visiting.add(n)
        d = 0
        for p in deps[n]:
            d = max(d, layer_of(p) + 1)
        visiting.discard(n)
        depth[n] = d
        return d

    for n in names:
        layer_of(n)

    # group by layer, preserving the input (topo) order within each layer
    by_layer: dict[int, list[str]] = {}
    for n in names:
        by_layer.setdefault(depth[n], []).append(n)
    n_layers = (max(by_layer) + 1) if by_layer else 0

    import math

    W = 1200
    margin_x, margin_top = 120, 90
    col_w = 210                     # horizontal spacing between nodes in a layer
    sub_h = 98                      # vertical spacing between wrapped sub-rows (denser)
    layer_gap = 16                  # extra breathing room between layers (tightened)
    max_per_row = max(1, (W - 2 * margin_x) // col_w + 1)

    pos: dict[str, dict] = {}
    y = margin_top
    for li in range(n_layers):
        nodes = by_layer.get(li, [])
        if not nodes:
            continue
        sub_rows = math.ceil(len(nodes) / max_per_row)
        idx = 0
        for sr in range(sub_rows):
            row = nodes[sr * max_per_row:(sr + 1) * max_per_row]
            span = (len(row) - 1) * col_w
            x0 = (W - span) / 2                       # centre each sub-row
            for j, name in enumerate(row):
                pos[name] = {"x": round(x0 + j * col_w, 1), "y": round(y, 1)}
                idx += 1
            y += sub_h
        y += layer_gap

    H = max(560, round(y + 60))
    return {"viewbox": [0, 0, W, H], "pos": pos, "layers": n_layers}


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


def _landscape_layout(names: list[str], edges: list[dict]) -> dict:
    """Place nodes as an ORGANIC WOODLAND, not a grid — a wide landscape the render
    paints groves onto with real depth.

    We still respect prerequisite order (roots at the back, dependents flowing toward
    the viewer) so the map stays truthful, but the placement is deliberately un-gridlike:

      • DEPTH BAND — a node's longest prereq-chain length maps to a back→front band.
        Fewer bands than raw layers (so a deep tree still reads as far / mid / near),
        which drives parallax and how big/lush a tree is drawn.
      • ROW = band → a horizontal ribbon of the scene, back bands higher & shorter,
        near bands lower & wider (a receding ground plane).
      • X within a band spreads the band's nodes across the ribbon, then each node gets
        a SMALL DETERMINISTIC jitter (seeded by name) in x and y so the treeline waves
        and never lines up in columns. Same input → same scene every load.

    Returns {viewbox, pos:{name:{x,y}}, band:{name:0..B-1}, bands:B, ground:y} — purely
    additive alongside the existing `dag`/`layout` payloads; the render chooses this one.
    """
    import hashlib
    import math

    known = set(names)
    deps: dict[str, list[str]] = {n: [] for n in names}
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if s in known and d in known and s != d:
            deps[d].append(s)

    # longest-path depth (cycle-safe), exactly as the dag layering does.
    depth: dict[str, int] = {}
    visiting: set[str] = set()

    def depth_of(n: str) -> int:
        if n in depth:
            return depth[n]
        if n in visiting:
            return 0
        visiting.add(n)
        d = 0
        for p in deps[n]:
            d = max(d, depth_of(p) + 1)
        visiting.discard(n)
        depth[n] = d
        return d

    for n in names:
        depth_of(n)
    max_depth = max(depth.values()) if depth else 0

    # Collapse raw layers into a handful of depth BANDS (far → near). A single-layer
    # forest still gets one nice mid band; a deep one gets up to 5 receding ribbons.
    n_bands = max(1, min(5, max_depth + 1))
    band: dict[str, int] = {}
    for n in names:
        band[n] = 0 if max_depth == 0 else min(n_bands - 1, round(depth[n] / max_depth * (n_bands - 1)))

    by_band: dict[int, list[str]] = {}
    for n in names:
        by_band.setdefault(band[n], []).append(n)

    # A wide, cinematic canvas — landscape, not portrait: width dominates so the whole
    # vista reads as a horizon, not a column. Height stays close to a 16:10 frame so a
    # width-fit shows the full scene (far treeline → near foreground) without cropping.
    W = 1680
    sky = 140                       # sky / horizon band above the treeline
    band_gap = 150                  # vertical spacing between depth ribbons (kept tight)
    ground = 300 + (n_bands - 1) * band_gap   # near-band baseline
    H = ground + 170
    margin_x = 150

    def jitter(name: str, salt: str, span: float) -> float:
        # deterministic per-name jitter in [-span, +span]
        h = int(hashlib.md5((name + salt).encode()).hexdigest()[:8], 16)
        return (h / 0xFFFFFFFF - 0.5) * 2 * span

    pos: dict[str, dict] = {}
    for b in range(n_bands):
        nodes = by_band.get(b, [])
        if not nodes:
            continue
        # back bands sit high (just under the treeline) & narrower; near bands sit low & wide.
        t = b / max(1, n_bands - 1)                 # 0 far … 1 near
        top = sky + 130                              # first grove ribbon rests below the horizon
        row_y = top + t * (ground - top)
        inset = (1 - t) * 120                        # far ribbons are inset (perspective)
        x0, x1 = margin_x + inset, W - margin_x - inset
        # order nodes within a band by x-jitter so neighbours don't always share prereqs
        nodes = sorted(nodes, key=lambda nm: jitter(nm, "order", 1.0))
        span = x1 - x0
        for i, nm in enumerate(nodes):
            frac = (i + 0.5) / len(nodes) if len(nodes) > 1 else 0.5
            x = x0 + frac * span + jitter(nm, "x", span / max(3, len(nodes) * 2))
            y = row_y + jitter(nm, "y", 46)          # wave the treeline
            pos[nm] = {"x": round(max(60, min(W - 60, x)), 1), "y": round(y, 1)}

    return {"viewbox": [0, 0, W, round(H)], "pos": pos, "band": band,
            "bands": n_bands, "ground": round(ground), "sky": sky}


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
