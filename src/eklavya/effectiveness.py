"""Tier-0 effectiveness metrics — is the learner actually getting better UNAIDED?

A pure, read-only aggregator (sibling to ``report.py``), contextvar-aware via the
shared ``db.connect`` + ``config.paths``, so it always reads the CURRENT user's own
database. It does NOT compute new learning signal — it *surfaces and reshapes* what
the spine already logs (see docs/EFFECTIVENESS_MEASUREMENT.md §2). Every number
carries an ``n`` so a caller can show confidence; a signal with no data yet returns
``None``/``0`` with ``n = 0`` rather than a fabricated value.

The through-line (the project's whole thesis, §9 guardrail): a tutor that lifts
*assisted* accuracy while *unaided* ability stagnates has FAILED. So the headline is
the unaided trend and whether the AI-off ↔ AI-on gap is closing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import progress, report
from .db import connect


def _slope(points: list[tuple[float, float]]) -> float | None:
    """Ordinary-least-squares slope of y on x (or None for < 2 points).

    Used to turn a per-day rate/rating series into a single "rising or falling"
    number. x is a day index (0,1,2,…), so the slope reads as "points per active day".
    """
    n = len(points)
    if n < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def unaided() -> dict:
    """Unaided (AI-off) accuracy, its trend, and the AI-off↔AI-on gap.

    Reuses ``report.ai_gap()`` wholesale for the rates/trend, then adds the one thing
    it doesn't compute: whether the unaided trend is *rising* (a slope over the per-day
    series) and whether the gap is *closing* (unaided climbing toward assisted).
    """
    g = report.ai_gap()
    trend = [t for t in g["trend"] if t["rate"] is not None]
    slope = _slope([(i, t["rate"]) for i, t in enumerate(trend)])
    return {
        "unaided_rate": g["unaided_rate"],
        "unaided_n": g["unaided_n"],
        "assisted_rate": g["assisted_rate"],
        "assisted_n": g["assisted_n"],
        "gap": g["gap"],
        "trend": trend,
        # rising unaided accuracy is the guardrail passing; a shrinking gap follows.
        "unaided_slope": round(slope, 2) if slope is not None else None,
        "rising": (slope is not None and slope > 0),
        "closing": (slope is not None and slope > 0 and (g["gap"] is None or g["gap"] > 0)),
    }


def elo() -> dict:
    """Per-pillar Elo: current mean rating per pillar, the overall trajectory, and the
    strongest / weakest pillars.

    ``ratings`` holds the current rating per (pillar, axis); ``rating_history`` holds
    every change with a timestamp — the raw ability curve. We surface the pillar means
    (STRENGTHS vs WEAKNESSES) and an overall mean-rating time series (daily).
    """
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT p.name AS pillar, AVG(r.rating) AS rating, COUNT(*) AS n "
            "FROM ratings r JOIN pillars p ON p.id = r.pillar_id "
            "GROUP BY p.name ORDER BY rating DESC"
        ).fetchall()
        # overall mean of new_rating per active day, from the history curve
        daily = conn.execute(
            "SELECT substr(created_at,1,10) AS day, AVG(new_rating) AS rating, COUNT(*) AS n "
            "FROM rating_history GROUP BY day ORDER BY day"
        ).fetchall()
        hist_n = conn.execute("SELECT COUNT(*) AS c FROM rating_history").fetchone()["c"]
    finally:
        conn.close()

    pillars = [{"pillar": r["pillar"], "rating": round(r["rating"]), "n": r["n"]} for r in cur]
    series = [{"day": r["day"], "rating": round(r["rating"], 1), "n": r["n"]} for r in daily]
    overall = round(sum(p["rating"] for p in pillars) / len(pillars)) if pillars else None
    slope = _slope([(i, s["rating"]) for i, s in enumerate(series)])
    return {
        "n_pillars": len(pillars),
        "history_n": hist_n,
        "overall_rating": overall,
        "series": series,
        "slope": round(slope, 2) if slope is not None else None,
        "strengths": pillars[:3],
        "weaknesses": list(reversed(pillars[-3:])) if pillars else [],
    }


def retention() -> dict:
    """FSRS retention — durable memory, not cramming.

    A card is only evidence of *retention* once it has graduated out of initial learning
    — i.e. it survived at least one real interval. In FSRS that's ``state`` 2 (Review) or
    3 (Relearning): a still-Learning card (state 1) hasn't been tested across an interval
    yet, so it can't speak to durable memory. Among the graduated cards, "recalled" = the
    card is currently in Review (2), not Relearning (3, meaning it lapsed on a due review).
    Retention is the pass rate over those graduated cards, ``n`` = how many qualify;
    n=0 ⇒ None (no verdict yet).
    """
    import json

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT lapses, due, state_json FROM cards WHERE state_json IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    graduated, recalled = 0, 0
    for r in rows:
        try:
            st = json.loads(r["state_json"])
        except (TypeError, ValueError):
            continue
        state = int(st.get("state", 0))
        if state not in (2, 3):   # still in initial learning → no interval survived yet
            continue
        graduated += 1
        if state == 2:            # in Review, not fallen back to Relearning
            recalled += 1

    rate = round(100 * recalled / graduated) if graduated else None
    return {"n": graduated, "recalled": recalled, "rate": rate, "cards_total": len(rows)}


def dose() -> dict:
    """Dose / effort — the independent variable for any dose-response story.

    Total practice minutes (from ``sessions``), session count, attempt count, active
    days, and the current streak. Minutes prefer each session's wall-clock span
    (started→ended); falls back to ``planned_min`` for sessions still open.
    """
    from .progress import _parse_ts

    conn = connect()
    try:
        srows = conn.execute(
            "SELECT planned_min, started_at, ended_at, last_active FROM sessions"
        ).fetchall()
        attempts_n = conn.execute("SELECT COUNT(*) AS c FROM attempts").fetchone()["c"]
        active_days = conn.execute(
            "SELECT COUNT(DISTINCT substr(created_at,1,10)) AS d FROM attempts"
        ).fetchone()["d"]
    finally:
        conn.close()

    minutes = 0.0
    for s in srows:
        start = _parse_ts(s["started_at"])
        end = _parse_ts(s["ended_at"] or s["last_active"])
        if start and end and end > start:
            minutes += (end - start).total_seconds() / 60
        elif s["planned_min"]:
            minutes += s["planned_min"]

    return {
        "minutes": round(minutes),
        "sessions": len(srows),
        "attempts": attempts_n,
        "active_days": active_days,
        "streak": progress.stats()["streak"],
    }


# --- per-attempt event export (offline-analysis substrate, §2.3) -----------

# The tidy one-row-per-attempt schema. Fixed order so CSV headers and JSONL keys match.
EXPORT_COLUMNS = [
    "attempt_id", "created_at", "pillar", "axis", "concept", "confidence",
    "correct", "ai_off", "seconds", "session_id", "rating_before", "rating_after",
]


def attempt_rows() -> list[dict]:
    """One tidy dict per attempt for offline analysis (pandas / R).

    ``attempts`` stores the concept in ``detail`` but not the pillar/axis or the rating
    change; ``rating_history`` stores ``(pillar, axis, old_rating, new_rating)`` but not
    the concept. They have no shared key — however ``tools.record_attempt`` inserts one
    ``rating_history`` row and one ``attempts`` row in lockstep, in the same order. So we
    pair them by insertion order (both ordered by id) to recover pillar/axis and the
    rating_before/rating_after for each attempt. Attempts with no paired history row (e.g.
    graded rows written by another path) still export, with those four fields left null.
    """
    conn = connect()
    try:
        attempts = conn.execute(
            "SELECT id, created_at, detail, confidence, correct, ai_off, seconds, session_id "
            "FROM attempts ORDER BY id"
        ).fetchall()
        history = conn.execute(
            "SELECT pillar, axis, old_rating, new_rating FROM rating_history ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    rows: list[dict] = []
    for i, a in enumerate(attempts):
        h = history[i] if i < len(history) else None
        rows.append({
            "attempt_id": a["id"],
            "created_at": a["created_at"],
            "pillar": h["pillar"] if h else None,
            "axis": h["axis"] if h else None,
            "concept": a["detail"],
            "confidence": a["confidence"],
            "correct": a["correct"],
            "ai_off": a["ai_off"],
            "seconds": a["seconds"],
            "session_id": a["session_id"],
            "rating_before": round(h["old_rating"], 1) if h and h["old_rating"] is not None else None,
            "rating_after": round(h["new_rating"], 1) if h and h["new_rating"] is not None else None,
        })
    return rows


def export_attempts(out_path, fmt: str = "csv") -> int:
    """Write the per-attempt table to ``out_path`` as ``csv`` or ``jsonl`` (stdlib only).

    Exports the CURRENT user's data (contextvar-aware, per-user-safe). Returns the row
    count written (a header line always goes out even when there are zero attempts).
    """
    import csv
    import json
    from pathlib import Path

    rows = attempt_rows()
    out = Path(out_path)
    if fmt == "jsonl":
        with out.open("w", encoding="utf-8", newline="") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    else:
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
            w.writeheader()
            w.writerows(rows)
    return len(rows)


def summary() -> dict:
    """The whole Tier-0 picture as small, JSON-serialisable numbers with counts.

    Bundles the guardrail (unaided trend + gap), per-skill Elo (strengths/weaknesses),
    calibration (reused from ``progress``), retention, and dose — everything the
    effectiveness view and offline analysis need in one read.
    """
    from . import benchmark

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "unaided": unaided(),
        "elo": elo(),
        "calibration": progress.calibration(),
        "retention": retention(),
        "dose": dose(),
        # Tier-1: the frozen, non-circular ability score θ over time (the trustworthy anchor).
        "benchmark": benchmark.history(),
    }


# --- the user-facing Effectiveness view (§8: motivation + self-knowledge) --

def render() -> str:
    """Server-side HTML for the Effectiveness screen.

    The angle the dashboard/journey don't answer: *are you actually getting better
    UNAIDED?* Reuses the shared cinematic-forest design system (dashboard ``_CSS``) and
    lightweight inline SVG sparklines — no duplicate of the skill grid or the XP curve.
    """
    import html as _html

    from .dashboard import _BOW, _CSS, _icon

    s = summary()
    u, el, cal, ret, ds = s["unaided"], s["elo"], s["calibration"], s["retention"], s["dose"]
    bm = s["benchmark"]

    # --- verdict banner: the guardrail (does unaided ability rise?) ---
    if u["unaided_n"] and u["unaided_slope"] is not None:
        if u["rising"]:
            verdict = ("rising", "Unaided skill is RISING",
                       f"Your AI-off accuracy is trending up ({u['unaided_slope']:+.1f}%/active day). "
                       "This is the guardrail passing — real ability, not dependency.")
        elif u["unaided_slope"] < 0:
            verdict = ("falling", "Unaided skill is slipping",
                       f"Your AI-off accuracy is trending down ({u['unaided_slope']:+.1f}%/active day). "
                       "Practice more with the AI off — this is the number that matters.")
        else:
            verdict = ("flat", "Unaided skill is holding steady",
                       "Your AI-off accuracy is flat. Keep the streak — more unaided reps move it.")
    else:
        verdict = ("flat", "Not enough unaided data yet",
                   "Answer a few drills with the AI off and your true, unaided trend appears here.")
    vcls, vtitle, vbody = verdict

    # --- unaided trend sparkline (AI-off accuracy over active days) ---
    def _spark(points: list[float], color: str) -> str:
        if len(points) < 2:
            return ('<div class="muted" style="font-family:var(--f-mono);font-size:12px">'
                    'not enough points yet</div>')
        mx, mn = max(points), min(points)
        rng = (mx - mn) or 1
        pts = " ".join(f"{i/(len(points)-1)*300:.1f},{58-((v-mn)/rng*50):.1f}"
                       for i, v in enumerate(points))
        return (f'<svg viewBox="0 0 300 62" class="efspark" preserveAspectRatio="none">'
                f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/></svg>')

    unaided_spark = _spark([t["rate"] for t in u["trend"]], "#57d3ce")
    elo_spark = _spark([e["rating"] for e in el["series"]], "#e7b64b")

    # --- Tier-1 benchmark ability (θ): the frozen, non-circular ruler over time ---
    if bm["n_assessments"] >= 1 and bm["current_theta"] is not None:
        theta_spark = _spark([p["theta"] for p in bm["series"]], "#c9a24b")
        delta = None
        if bm["baseline_theta"] is not None and bm["n_assessments"] >= 2:
            delta = bm["current_theta"] - bm["baseline_theta"]
        slope_txt = (f"{bm['slope']:+.2f}/sitting" if bm["slope"] is not None
                     else "one sitting so far")
        delta_txt = (f' · Δ {delta:+.2f} vs baseline' if delta is not None else "")
        bm_html = (
            f'{theta_spark}'
            f'<div class="efrow" style="margin-top:8px">'
            f'  <div class="efstat"><b>{bm["current_theta"]:+.2f}</b><span>θ ability</span></div>'
            f'  <div class="efstat"><b>{bm["n_assessments"]}</b><span>sittings</span></div>'
            f'  <div class="efstat"><b>{bm["bank_size"]}</b><span>frozen items</span></div>'
            f'</div>'
            f'<div class="muted" style="font-size:11px;margin-top:6px">'
            f'Rasch θ on a frozen, AI-off benchmark · {slope_txt}{delta_txt} · '
            f'the ruler the tutor never teaches from</div>'
        )
    else:
        bm_html = (
            '<div class="efbig">—</div>'
            '<div class="muted">No benchmark sittings yet. Run <code>eklavya assess</code> '
            f'(AI-off, {bm["bank_size"]} frozen items) to fix a baseline θ — the honest, '
            'non-circular measure of whether your skill is really rising.</div>'
        )

    # --- gap card (AI-off ↔ AI-on, and whether it's closing) ---
    if u["gap"] is not None:
        gap_state = "closing" if u["closing"] else ("open" if u["gap"] > 0 else "none")
        gap_word = {"closing": "closing", "open": "still open", "none": "no gap"}[gap_state]
        gap_html = (
            f'<div class="efrow">'
            f'  <div class="efstat"><b>{u["unaided_rate"]}%</b><span>unaided</span></div>'
            f'  <div class="efstat"><b>{u["assisted_rate"] if u["assisted_rate"] is not None else "—"}%</b>'
            f'    <span>with AI</span></div>'
            f'  <div class="efstat gap"><b>{u["gap"]:+d}</b><span>gap · {gap_word}</span></div>'
            f'</div>'
        )
    else:
        gap_html = ('<div class="muted">Do an "AI-on check" sometime to measure the gap '
                    'between your assisted and unaided accuracy.</div>')

    # --- strengths vs weaknesses (per-pillar Elo) ---
    def _pill_rows(items: list[dict], cls: str) -> str:
        if not items:
            return '<div class="muted">No pillars rated yet.</div>'
        return "".join(
            f'<div class="efpill {cls}"><span class="efpn">{_html.escape(p["pillar"])}</span>'
            f'<span class="efpr">{p["rating"]}</span></div>' for p in items
        )
    strengths = _pill_rows(el["strengths"], "strong")
    weaknesses = _pill_rows(el["weaknesses"], "weak")

    # --- retention ---
    if ret["rate"] is not None:
        ret_html = (f'<div class="efbig">{ret["rate"]}%</div>'
                    f'<div class="muted">recalled on due reviews · {ret["recalled"]}/{ret["n"]} graduated cards</div>')
    else:
        ret_html = ('<div class="efbig">—</div><div class="muted">no cards have survived a review '
                    'interval yet · keep practising and retention appears here</div>')

    # --- calibration (reused signal, shown as the clarity headline) ---
    if cal.get("brier") is not None:
        clarity = max(0, min(100, round((1 - cal["brier"]) * 100)))
        cw = cal.get("confidently_wrong", 0)
        cal_html = (f'<div class="efbig">{clarity}</div>'
                    f'<div class="muted">clarity · {cw} confidently wrong · Brier {cal["brier"]:.2f}</div>')
    else:
        cal_html = ('<div class="efbig">—</div><div class="muted">answer drills with a confidence '
                    'level to see how well you know what you know</div>')

    # --- dose / effort ---
    dose_cells = [
        ("hourglass", "Minutes", f'{ds["minutes"]:,}'),
        ("target", "Sessions", str(ds["sessions"])),
        ("activity", "Attempts", str(ds["attempts"])),
        ("calendar", "Active days", str(ds["active_days"])),
        ("flame", "Streak", f'{ds["streak"]}d'),
    ]
    dose_html = "".join(
        f'<div class="dcell"><div class="dico">{_icon(ic, 16)}</div>'
        f'<div class="dval">{val}</div><div class="dlabel">{lbl}</div></div>'
        for ic, lbl, val in dose_cells
    )

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Effectiveness</title>
<link rel="stylesheet" href="/static/fonts.css">
<style>{_CSS}{_EFCSS}</style></head><body><div class="wrap">
  <header class="jhero">
    <div class="brand"><div class="logo"><span class="bowmark">{_BOW}</span>
      <span class="g">AM I GETTING BETTER?</span></div>
      <div class="creed" style="font-family:var(--f-serif);font-style:italic">the honest mirror · unaided, not assisted</div></div>
  </header>

  <section class="verdict {vcls}">
    <div class="vtitle">{_icon("trend")} {vtitle}</div>
    <div class="vbody">{vbody}</div>
  </section>

  <div class="efgrid">
    <section class="card ef-bench">
      <h2>{_icon("trend")} Benchmark ability (θ)</h2>
      {bm_html}
    </section>
    <section class="card ef-unaided">
      <h2>{_icon("trend")} Unaided accuracy over time</h2>
      {unaided_spark}
      <div class="muted" style="font-size:11px;margin-top:6px">AI-off success rate · recent active days · {u["unaided_n"]} attempts</div>
    </section>
    <section class="card ef-gap">
      <h2>{_icon("scale")} The dependency gap</h2>
      {gap_html}
    </section>
    <section class="card ef-elo">
      <h2>{_icon("bars")} Ability trajectory (Elo)</h2>
      {elo_spark}
      <div class="muted" style="font-size:11px;margin-top:6px">mean rating over time · overall {el["overall_rating"] if el["overall_rating"] is not None else "—"} across {el["n_pillars"]} pillars</div>
    </section>
    <section class="card ef-strong">
      <h2>{_icon("gem")} Strengths</h2>
      <div class="efpills">{strengths}</div>
    </section>
    <section class="card ef-weak">
      <h2>{_icon("target")} Where to invest</h2>
      <div class="efpills">{weaknesses}</div>
    </section>
    <section class="card ef-ret">
      <h2>{_icon("prayer")} Retention</h2>
      {ret_html}
    </section>
    <section class="card ef-cal">
      <h2>{_icon("scale")} Calibration</h2>
      {cal_html}
    </section>
    <section class="card ef-dose">
      <h2>{_icon("flame")} Effort so far</h2>
      <div class="drow">{dose_html}</div>
    </section>
  </div>
</div></body></html>"""


_EFCSS = """
/* effectiveness view — reuses jhero/card/ribbon idioms from the design system */
.jhero{background:linear-gradient(120deg,rgba(35,29,24,.82),rgba(12,10,20,.9));border:1px solid var(--line-gold);
  border-radius:6px;padding:22px 26px;box-shadow:var(--sh-carve),var(--sh-deep);
  display:flex;flex-direction:column;gap:8px;position:relative}
.jhero::before,.jhero::after{content:"";position:absolute;width:15px;height:15px;border:1.5px solid var(--gold);opacity:.6}
.jhero::before{top:8px;left:8px;border-right:0;border-bottom:0}
.jhero::after{bottom:8px;right:8px;border-left:0;border-top:0}
.jhero .brand{display:flex;flex-direction:column;gap:2px}

/* the verdict banner — the guardrail's headline */
.verdict{border:1px solid var(--line-gold);border-left:3px solid var(--gold);border-radius:6px;
  padding:18px 24px;box-shadow:var(--sh-carve);
  background:linear-gradient(100deg,rgba(35,29,24,.7),rgba(12,10,20,.85))}
.verdict.rising{border-left-color:var(--forest-lit)}
.verdict.falling{border-left-color:var(--vermilion-glow)}
.verdict.flat{border-left-color:var(--peacock-bright)}
.vtitle{font-family:var(--f-mono);letter-spacing:.14em;font-size:12px;font-weight:500;text-transform:uppercase;
  display:flex;align-items:center;gap:8px;color:var(--gold-bright)}
.verdict.rising .vtitle{color:var(--forest-lit)}
.verdict.falling .vtitle{color:var(--vermilion-glow)}
.verdict.flat .vtitle{color:var(--peacock-bright)}
.vtitle .ic{width:16px;height:16px;color:currentColor}
.vbody{font-family:var(--f-body);font-size:15px;margin-top:8px;color:var(--parch-dim);line-height:1.55}

.efgrid{display:grid;gap:18px;grid-template-columns:repeat(6,1fr);align-items:start;
  grid-template-areas:
    "bench bench bench bench bench bench"
    "unaided unaided unaided gap gap gap"
    "elo elo elo elo elo elo"
    "strong strong strong weak weak weak"
    "ret ret cal cal dose dose";}
.ef-bench{grid-area:bench;border-left:3px solid var(--gold)}
.ef-unaided{grid-area:unaided}.ef-gap{grid-area:gap}.ef-elo{grid-area:elo}
.ef-strong{grid-area:strong}.ef-weak{grid-area:weak}
.ef-ret{grid-area:ret}.ef-cal{grid-area:cal}.ef-dose{grid-area:dose}
@media(max-width:820px){
  .efgrid{grid-template-columns:1fr;grid-template-areas:"bench" "unaided" "gap" "elo" "strong" "weak" "ret" "cal" "dose"}
}
.efspark{width:100%;height:64px}
.efrow{display:flex;gap:22px;align-items:flex-end;flex-wrap:wrap}
.efstat b{display:block;font-family:var(--f-display);font-weight:700;font-size:28px;color:var(--gold-bright);line-height:1}
.efstat span{color:var(--parch-mute);font-size:10px;text-transform:uppercase;letter-spacing:.05em;font-family:var(--f-mono)}
.efstat.gap b{color:var(--peacock-bright)}
.efbig{font-family:var(--f-display);font-weight:800;font-size:40px;color:var(--gold-bright);line-height:1;margin-bottom:4px}
.efpills{display:flex;flex-direction:column;gap:8px}
.efpill{display:flex;justify-content:space-between;align-items:center;gap:12px;background:rgba(6,9,20,.4);
  border:1px solid var(--line-soft);border-radius:8px;padding:9px 13px}
.efpill.strong{border-color:rgba(231,182,75,.3)}
.efpill.weak{border-color:rgba(214,59,42,.3)}
.efpn{font-family:var(--f-title);font-size:14px;color:var(--parch);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.efpr{font-family:var(--f-mono);font-size:14px;font-variant-numeric:tabular-nums;flex:none}
.efpill.strong .efpr{color:var(--gold-bright)}.efpill.weak .efpr{color:var(--vermilion-glow)}
.drow{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.dcell{background:rgba(6,9,20,.4);border:1px solid var(--line-soft);border-radius:12px;padding:12px 10px;
  display:flex;flex-direction:column;gap:2px;min-width:0}
.dico{color:var(--gold-bright)}.dico .ic{color:var(--gold-bright)}
.dval{font-family:var(--f-display);font-size:20px;font-weight:700;color:var(--parch);font-variant-numeric:tabular-nums}
.dlabel{font-family:var(--f-mono);font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--parch-mute)}
@media(max-width:560px){.drow{grid-template-columns:repeat(2,1fr)}.card{max-width:100%;min-width:0}}
"""

