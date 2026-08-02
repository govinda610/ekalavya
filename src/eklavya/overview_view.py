"""The unified Overview — one cohesive progress screen (task #83).

A COMPLETE SUPERSET of the three former screens (Dashboard, Journey, Effectiveness):
every metric, number, chart, and list any of them rendered still appears here — just
regrouped into one beautiful, bento-laid page so the learner sees the headline numbers
without hunting through tabs. Nothing is dropped; where two pages showed the same signal
it is shown once.

Bands, top to bottom:
  1. HEADLINE — rank + XP ring, streak, groves mastered, and the credibility trio
     (unaided trend, AI-off↔AI-on gap, calibration clarity).
  2. TODAY'S QUEST + active quests (goals) + due reviews.
  3. SKILL MASTERY — the calibration "illusion of knowing" card, the per-pillar×axis
     skill map, and the per-axis mastery bars.
  4. EFFECTIVENESS — the verdict banner, the aggregate cards (benchmark θ, unaided-over-
     time, dependency gap, Elo trajectory, retention, calibration, dose, strengths /
     weaknesses, outcomes) AND one per-subject strip per active subject.
  5. JOURNEY — milestone timeline, achievements (earned + locked), activity heatmap,
     XP-over-time curve, and the session chronicle.

Composition + layout + surfacing only: every number comes from the existing metric
functions (``report`` / ``effectiveness`` / ``journey`` / ``progress`` / ``benchmark``).
The dashboard's own render helpers (skill map cells, axis bars, calibration card,
achievements) are reused verbatim so the look and the numbers stay identical.
"""

from __future__ import annotations

import bisect
import html
from datetime import date, timedelta

from . import effectiveness, journey, report
from .dashboard import (
    AXIS_COLOR, _BOW, _CSS, _achievements, _calibration, _cell, _icon,
    _pct, _rank, _rank_ring,
)
from .db import connect


# --- badge tiers -------------------------------------------------------------
# Each achievement earns a rarity from how hard its goal is — rendered as a
# distinct emblem colour + border/glow. Earned badges bloom to full colour; the
# rest stay dim silhouettes with a live progress ring toward the next unlock.
_TIER = {
    "On Fire":       ("common", "streak"),
    "Week Warrior":  ("rare",   "streak"),
    "Unbroken":      ("epic",   "streak"),
    "Adept":         ("rare",   "level"),
    "Master":        ("epic",   "level"),
    "First Mastery": ("common", "mastery"),
    "Sharpened":     ("epic",   "mastery"),
    "Initiate":      ("common", "session"),
    "Devoted":       ("rare",   "session"),
}
_TIER_RANK = {"epic": 0, "rare": 1, "common": 2}
_TIER_COLOR = {                       # (rim, glow) on-brand: gold=epic, teal=rare, bronze=common
    "epic":   ("#f7d98a", "231,182,75"),
    "rare":   ("#57d3ce", "87,211,206"),
    "common": ("#c98b4b", "201,139,75"),
}

# session-mode → (icon, styled label) for the chronicle activity feed
_MODE_META = {
    "practice":   ("target",  "Practice"),
    "mock":       ("user",    "Mock interview"),
    "aiinterview": ("scale",  "AI-on interview"),
    "gauntlet":   ("sword",   "The Gauntlet"),
    "blitz":      ("flame",   "Blitz"),
    "boss":       ("crown",   "Boss fight"),
    "takehome":   ("scroll",  "Take-home"),
    "onboard":    ("compass", "Onboarding"),
}


def _session_ledger_xp(rows: list[dict]) -> dict[str, int]:
    """XP actually earned during each session, straight from the rewards ledger.

    ``sessions.xp`` is only backfilled when a sitting is explicitly wrapped up
    (``end_session``); an open or never-wrapped sitting stores 0 even though the
    learner earned XP — which is why the chronicle showed "+0 XP" on live rows.
    Here we sum the XP rewards whose timestamp falls inside each sitting's window
    [started_at, next-session-start) so every row shows real earned XP. Keyed by
    ``started_at`` (what the chronicle already has in hand).

    Timestamps are PARSED, not string-compared: sessions store an aware ISO stamp
    (``...T..+00:00``) while rewards default to SQLite ``datetime('now')`` (naive,
    space-separated) — comparing those as strings misattributes rewards, so we sort
    on parsed UTC datetimes."""
    from .progress import _parse_ts

    conn = connect()
    try:
        sess = conn.execute(
            "SELECT started_at FROM sessions WHERE started_at IS NOT NULL"
        ).fetchall()
        rewards = conn.execute(
            "SELECT amount, created_at FROM rewards WHERE kind IN ('xp','penalty') "
            "AND created_at IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    # sorted (parsed-datetime, raw-start-string) bounds; skip unparseable stamps
    bounds = sorted((dt, s["started_at"]) for s in sess
                    if (dt := _parse_ts(s["started_at"])) is not None)
    starts_dt = [b[0] for b in bounds]
    earned: dict[str, int] = {s["started_at"]: 0 for s in sess}
    for r in rewards:
        ts = _parse_ts(r["created_at"])
        if ts is None:
            continue
        # the sitting a reward belongs to is the latest one that started at or before it
        i = bisect.bisect_right(starts_dt, ts) - 1
        if i >= 0:
            earned[bounds[i][1]] += (r["amount"] or 0)
    return earned


def _clarity(cal: dict) -> int | None:
    """0–100 'clarity' from a calibration bundle (lower Brier → higher clarity)."""
    if not cal or cal.get("brier") is None:
        return None
    return max(0, min(100, round((1 - cal["brier"]) * 100)))


def _spark(points: list[float], color: str, empty: str = "not enough data yet") -> str:
    """A tiny inline SVG line — the same idiom the effectiveness view uses."""
    pts = [p for p in points if p is not None]
    if len(pts) < 2:
        return f'<div class="ov-spark-empty muted">{empty}</div>'
    mx, mn = max(pts), min(pts)
    rng = (mx - mn) or 1
    poly = " ".join(f"{i/(len(pts)-1)*300:.1f},{58-((v-mn)/rng*50):.1f}"
                    for i, v in enumerate(pts))
    return (f'<svg viewBox="0 0 300 62" class="ov-spark" preserveAspectRatio="none">'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2"/></svg>')


# --- headline band ----------------------------------------------------------

def _headline(ov: dict, eff: dict, strong: int) -> str:
    s = ov["stats"]
    level, xp, streak = s["level"], s["xp"], s["streak"]
    into = xp % 100
    rank = _rank(level)

    u = eff["unaided"]
    clarity = _clarity(eff["calibration"])

    if u["unaided_n"] and u["unaided_slope"] is not None:
        if u["rising"]:
            uv_cls, uv_word, uv_sub = "rising", "rising", f'{u["unaided_slope"]:+.1f}%/day'
        elif u["unaided_slope"] < 0:
            uv_cls, uv_word, uv_sub = "falling", "slipping", f'{u["unaided_slope"]:+.1f}%/day'
        else:
            uv_cls, uv_word, uv_sub = "flat", "steady", "holding"
    else:
        uv_cls, uv_word, uv_sub = "flat", "—", "no data yet"

    gap_val = f'{u["gap"]:+d}' if u["gap"] is not None else "—"
    gap_sub = (("closing" if u["closing"] else "still open") if u["gap"] is not None
               else "run an AI-on check")

    creds = (
        f'<div class="ov-cred {uv_cls}"><div class="ovc-k">Unaided ability</div>'
        f'<div class="ovc-v">{uv_word}</div><div class="ovc-s">{uv_sub}</div></div>'
        f'<div class="ov-cred"><div class="ovc-k">AI-off vs AI-on</div>'
        f'<div class="ovc-v">{gap_val}</div><div class="ovc-s">{gap_sub}</div></div>'
        f'<div class="ov-cred"><div class="ovc-k">Calibration</div>'
        f'<div class="ovc-v">{clarity if clarity is not None else "—"}</div>'
        f'<div class="ovc-s">{"clarity" if clarity is not None else "add confidence"}</div></div>'
    )

    return f"""
  <header class="ov-hero">
    <div class="ov-hero-l">
      <div class="rank-medallion">{_rank_ring(level, into)}
        <div class="rmlabel"><div class="rmnum">{level}</div><div class="rmtag">RANK</div></div>
      </div>
      <div class="ov-hero-id">
        <div class="rank">{rank}</div>
        <div class="prog-line">Lv <b>{level}</b> · <b>{into}%</b> → R{level + 1}
          <span class="prog-xp">{xp:,} total XP</span></div>
        <div class="chips">
          <span class="chip flame">{_icon("flame")} {streak} day streak</span>
          <span class="chip">{_icon("gem")} {strong} groves mastered</span>
          <span class="chip">✦ {into} / 100 XP to next</span>
        </div>
      </div>
    </div>
    <div class="ov-creds">{creds}</div>
  </header>"""


# --- quest banner + goals ---------------------------------------------------

def _quest_band(ov: dict) -> str:
    # weakest cell → today's quest (the dashboard's prescriptive line)
    weakest = None
    for pillar, cells in ov["grid"]["pillars"].items():
        for axis, cell in cells.items():
            if weakest is None or cell["rating"] < weakest[2]:
                weakest = (pillar, axis, cell["rating"])
    if weakest:
        quest = (f"Sharpen <b>{html.escape(weakest[0])} · "
                 f"{html.escape(weakest[1].replace('_', ' '))}</b> — your weakest skill.")
    else:
        quest = "Run <code>eklavya onboard</code> to map your skills, then your quests appear here."
    due = (f"<span class='due'>{ov['due']} review(s) due</span>" if ov.get("due")
           else "<span class='muted'>no reviews due — learn something new</span>")

    goals = "".join(
        f'<div class="quest" onclick="this.classList.toggle(\'open\')" title="click to expand">'
        f'<span class="hz {html.escape(x["horizon"])}">{html.escape(x["horizon"])}</span>'
        f'<span class="qtext">{html.escape(x["text"])}</span>'
        + (f'<span class="muted qd">· {html.escape(x["deadline"])}</span>' if x.get("deadline") else "")
        + "</div>"
        for x in ov["goals"]
    ) or '<span class="muted">No quests yet.</span>'

    return f"""
  <section class="quest-banner">
    <div class="qtitle">{_icon("sword")} TODAY'S QUEST</div>
    <div class="qbody">{quest}</div>
    <div class="qmeta">{due}</div>
  </section>
  <section class="card ov-quests"><h2>{_icon("target")} Active quests</h2>
    <div class="quests">{goals}</div></section>"""


# --- skill-mastery band (calibration card + skill map + axis bars) ----------

def _mastery_band(ov: dict) -> str:
    g = ov["grid"]
    axes = g["axes"]
    calibration = _calibration(ov["stats"].get("calibration") or {})

    axis_head = "".join(f'<th class="ax">{a.replace("_", " ")}</th>' for a in axes)
    if g["pillars"]:
        rows = "".join(
            f"<tr><th class='pillar'>{html.escape(p)}</th>"
            + "".join(_cell(cells.get(a)) for a in axes) + "</tr>"
            for p, cells in g["pillars"].items()
        )
    else:
        rows = f'<tr><td colspan="{len(axes)+1}" class="muted">No skills yet — run onboarding.</td></tr>'

    sums: dict[str, list] = {a: [] for a in axes}
    for cells in g["pillars"].values():
        for a, cell in cells.items():
            sums[a].append(cell["rating"])
    bars = ""
    for a in axes:
        vals = sums[a]
        avg = sum(vals) / len(vals) if vals else 800
        col = AXIS_COLOR.get(a, "#5ef2b8")
        bars += (f'<div class="barwrap"><div class="barlabel">{a.replace("_", " ")}</div>'
                 f'<div class="bartrack"><div class="bar" style="width:{_pct(avg)}%;'
                 f'background:linear-gradient(90deg,{col}55,{col});box-shadow:0 0 10px {col}66">'
                 f'</div></div></div>')

    return f"""
  <section class="ov-band">
    <div class="ov-band-head"><span class="ov-band-t">{_icon("grid")} Skill mastery</span>
      <span class="muted ov-band-s">what you know, how well you know you know it</span></div>
    <div class="ov-mgrid">
      <section class="card b-cal ov-cal"><h2>{_icon("scale")} The illusion of knowing</h2>
        {calibration}</section>
      <section class="card ov-map"><h2>{_icon("grid")} Skill map</h2>
        <table class="heat"><tr><th class="pillar"></th>{axis_head}</tr>{rows}</table>
        <div class="legend">
          <span><i style="background:#a89670"></i>unknown</span>
          <span><i style="background:#ff5a3c"></i>gap</span>
          <span><i style="background:#57d3ce"></i>familiar</span>
          <span><i style="background:#e7b64b"></i>strong</span>
        </div></section>
      <section class="card ov-axes"><h2>{_icon("bars")} Skill axes</h2>
        <div class="bars">{bars}</div></section>
    </div>
  </section>"""


# --- effectiveness band (aggregate cards + per-subject strips) ---------------

def _effectiveness_band(eff: dict) -> str:
    u, el, cal, ret, ds = (eff["unaided"], eff["elo"], eff["calibration"],
                           eff["retention"], eff["dose"])
    bm = eff["benchmark"]

    # verdict banner (the guardrail headline)
    if u["unaided_n"] and u["unaided_slope"] is not None:
        if u["rising"]:
            vcls, vtitle = "rising", "Unaided skill is RISING"
            vbody = (f"Your AI-off accuracy is trending up ({u['unaided_slope']:+.1f}%/active day). "
                     "Real ability, not dependency — the guardrail is passing.")
        elif u["unaided_slope"] < 0:
            vcls, vtitle = "falling", "Unaided skill is slipping"
            vbody = (f"Your AI-off accuracy is trending down ({u['unaided_slope']:+.1f}%/active day). "
                     "Practise more with the AI off — this is the number that matters.")
        else:
            vcls, vtitle = "flat", "Unaided skill is holding steady"
            vbody = "Your AI-off accuracy is flat. Keep the streak — more unaided reps move it."
    else:
        vcls, vtitle = "flat", "Not enough unaided data yet"
        vbody = "Answer a few drills with the AI off and your true, unaided trend appears here."

    unaided_spark = _spark([t["rate"] for t in u["trend"]], "#57d3ce")
    elo_spark = _spark([e["rating"] for e in el["series"]], "#e7b64b")

    # benchmark θ (frozen ruler)
    if bm["n_assessments"] >= 1 and bm["current_theta"] is not None:
        theta_spark = _spark([p["theta"] for p in bm["series"]], "#c9a24b")
        delta = None
        if bm["baseline_theta"] is not None and bm["n_assessments"] >= 2:
            delta = bm["current_theta"] - bm["baseline_theta"]
        slope_txt = (f"{bm['slope']:+.2f}/sitting" if bm["slope"] is not None else "one sitting so far")
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
        bm_html = ('<div class="ov-empty"><span class="ov-dash">—</span>'
                   f'<span>No benchmark sittings yet · run <code>eklavya assess</code> '
                   f'({bm["bank_size"]} frozen, AI-off items) to fix a baseline θ.</span></div>')

    # dependency gap
    if u["gap"] is not None:
        gap_word = "closing" if u["closing"] else ("still open" if u["gap"] > 0 else "no gap")
        gap_html = (
            f'<div class="efrow">'
            f'  <div class="efstat"><b>{u["unaided_rate"]}%</b><span>unaided</span></div>'
            f'  <div class="efstat"><b>{u["assisted_rate"] if u["assisted_rate"] is not None else "—"}%</b>'
            f'    <span>with AI</span></div>'
            f'  <div class="efstat gap"><b>{u["gap"]:+d}</b><span>gap · {gap_word}</span></div>'
            f'</div>'
        )
    else:
        gap_html = ('<div class="ov-empty"><span class="ov-dash">—</span>'
                    '<span>Do an "AI-on check" to measure the gap between your assisted '
                    'and unaided accuracy.</span></div>')

    # strengths / weaknesses (aggregate per-pillar Elo)
    def _pill_rows(items: list[dict], cls: str) -> str:
        if not items:
            return '<div class="muted">No pillars rated yet.</div>'
        return "".join(
            f'<div class="efpill {cls}"><span class="efpn">{html.escape(p["pillar"])}</span>'
            f'<span class="efpr">{p["rating"]}</span></div>' for p in items
        )
    strengths = _pill_rows(el["strengths"], "strong")
    weaknesses = _pill_rows(el["weaknesses"], "weak")

    # retention
    if ret["rate"] is not None:
        ret_html = (f'<div class="efbig">{ret["rate"]}%</div>'
                    f'<div class="muted">recalled on due reviews · {ret["recalled"]}/{ret["n"]} graduated cards</div>')
    else:
        ret_html = ('<div class="ov-empty"><span class="ov-dash">—</span>'
                    '<span>No cards have survived a review interval yet · keep practising.</span></div>')

    # calibration (clarity headline)
    if cal.get("brier") is not None:
        clarity = max(0, min(100, round((1 - cal["brier"]) * 100)))
        cw = cal.get("confidently_wrong", 0)
        cal_html = (f'<div class="efbig">{clarity}</div>'
                    f'<div class="muted">clarity · {cw} confidently wrong · Brier {cal["brier"]:.2f}</div>')
    else:
        cal_html = ('<div class="ov-empty"><span class="ov-dash">—</span>'
                    '<span>Answer drills with a confidence level to see how well you know '
                    'what you know.</span></div>')

    # dose / effort
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

    # per-subject strips
    per = eff["per_subject"]
    if per:
        strips = "".join(_subject_strip(subj, d) for subj, d in per.items())
        subjects_html = f'<div class="ov-subjects">{strips}</div>'
    else:
        subjects_html = ('<div class="ov-empty"><span class="ov-dash">—</span>'
                         '<span>Practise in a subject with the AI off and its per-subject strip '
                         '(θ, unaided verdict, strengths &amp; weaknesses) appears here.</span></div>')

    # real-world outcomes
    outs = eff.get("outcomes") or []
    if outs:
        outcomes = "".join(
            f'<div class="ocrow"><span class="ockind">{html.escape(o["kind"])}</span>'
            f'<span class="oclabel">{html.escape(o["label"])}'
            + (f' · {html.escape(o["value"])}' if o.get("value") else "")
            + '</span>'
            + f'<span class="ocwhen">{html.escape((o.get("occurred_at") or o["created_at"])[:10])}</span>'
            + '</div>'
            for o in outs
        )
    else:
        outcomes = ('<div class="ov-empty"><span class="ov-dash">—</span>'
                    '<span>Log real wins as they happen — an interview passed, an offer, a '
                    'problem solved unaided at work — with <code>eklavya outcome</code>.</span></div>')

    return f"""
  <section class="ov-band">
    <div class="ov-band-head"><span class="ov-band-t">{_icon("trend")} Am I actually getting better?</span>
      <span class="muted ov-band-s">the honest mirror · unaided, not assisted</span></div>
    <section class="verdict {vcls}">
      <div class="vtitle">{_icon("trend")} {vtitle}</div>
      <div class="vbody">{vbody}</div>
    </section>
    <div class="efgrid">
      <section class="card ef-bench"><h2>{_icon("trend")} Benchmark ability (θ)</h2>{bm_html}</section>
      <section class="card ef-unaided"><h2>{_icon("trend")} Unaided accuracy over time</h2>
        {unaided_spark}
        <div class="muted" style="font-size:11px;margin-top:6px">AI-off success rate · recent active days · {u["unaided_n"]} attempts</div></section>
      <section class="card ef-gap"><h2>{_icon("scale")} The dependency gap</h2>{gap_html}</section>
      <section class="card ef-elo"><h2>{_icon("bars")} Ability trajectory (Elo)</h2>
        {elo_spark}
        <div class="muted" style="font-size:11px;margin-top:6px">mean rating over time · overall {el["overall_rating"] if el["overall_rating"] is not None else "—"} across {el["n_pillars"]} pillars</div></section>
      <section class="card ef-strong"><h2>{_icon("gem")} Strengths</h2><div class="efpills">{strengths}</div></section>
      <section class="card ef-weak"><h2>{_icon("target")} Where to invest</h2><div class="efpills">{weaknesses}</div></section>
      <section class="card ef-ret"><h2>{_icon("prayer")} Retention</h2>{ret_html}</section>
      <section class="card ef-cal"><h2>{_icon("scale")} Calibration</h2>{cal_html}</section>
      <section class="card ef-dose"><h2>{_icon("flame")} Effort so far</h2><div class="drow">{dose_html}</div></section>
      <section class="card ef-out"><h2>{_icon("medal")} Real-world outcomes</h2>{outcomes}</section>
    </div>
    <div class="ov-sub-head"><span class="ov-band-t sm">{_icon("layers")} By subject</span>
      <span class="muted ov-band-s">each subject on its own frozen ruler — never cross-comparable</span></div>
    {subjects_html}
  </section>"""


def _subject_strip(subject: str, d: dict) -> str:
    u = d["unaided"]
    el = d["elo"]
    bm = d["benchmark"]
    clarity = _clarity(d["calibration"])
    ret = d["retention"]
    dz = d["dose"]

    if bm["n_assessments"] >= 1 and bm["current_theta"] is not None:
        theta_spark = _spark([p["theta"] for p in bm["series"]], "#c9a24b",
                             empty="one sitting so far")
        theta_head = (f'<span class="ss-theta">θ {bm["current_theta"]:+.2f}</span>'
                      f'<span class="muted ss-theta-s">{bm["n_assessments"]} sittings · {bm["bank_size"]} frozen items</span>')
    else:
        theta_spark = ('<div class="ov-spark-empty muted">no benchmark sittings yet — '
                       'run <code>eklavya assess</code></div>')
        theta_head = '<span class="ss-theta muted">θ —</span>'

    if u["unaided_n"] and u["unaided_slope"] is not None:
        if u["rising"]:
            v_cls, v_word = "rising", "rising"
        elif u["unaided_slope"] < 0:
            v_cls, v_word = "falling", "slipping"
        else:
            v_cls, v_word = "flat", "steady"
        v_detail = f'{u["unaided_rate"]}% unaided · {u["unaided_slope"]:+.1f}%/day'
    else:
        v_cls, v_word, v_detail = "flat", "—", "not enough unaided reps yet"

    gap_txt = (f'{u["gap"]:+d} gap · ' + ("closing" if u["closing"] else "open")
               if u["gap"] is not None else "gap not measured")
    ret_txt = (f'{ret["rate"]}% retained' if ret["rate"] is not None else "retention pending")
    clar_txt = (f'{clarity} clarity' if clarity is not None else "add confidence")
    dose_txt = f'{dz["attempts"]} attempts · {dz["active_days"]}d'

    def _pills(items: list[dict], cls: str) -> str:
        if not items:
            return '<span class="muted" style="font-size:12px">—</span>'
        return "".join(
            f'<span class="ss-pill {cls}">{html.escape(p["pillar"])} '
            f'<b>{p["rating"]}</b></span>' for p in items[:3]
        )

    return f"""
    <section class="card subject-strip">
      <div class="ss-head">
        <div class="ss-name">{_icon("layers")} {html.escape(subject)}</div>
        <div class="ss-verdict {v_cls}"><span class="ss-vword">{v_word}</span>
          <span class="muted ss-vdetail">{v_detail}</span></div>
      </div>
      <div class="ss-theta-row">{theta_head}</div>
      {theta_spark}
      <div class="ss-meta"><span class="ss-tag {v_cls}">{gap_txt}</span>
        <span class="ss-tag">{ret_txt}</span><span class="ss-tag">{clar_txt}</span>
        <span class="ss-tag">{dose_txt}</span></div>
      <div class="ss-elo">
        <div class="ss-elo-col"><div class="ss-elo-k">{_icon("gem")} Strengths</div>
          <div class="ss-pills">{_pills(el["strengths"], "strong")}</div></div>
        <div class="ss-elo-col"><div class="ss-elo-k">{_icon("target")} Invest here</div>
          <div class="ss-pills">{_pills(el["weaknesses"], "weak")}</div></div>
      </div>
    </section>"""


# --- achievement badges + chronicle feed ------------------------------------

def _badge_ring(pct: int, rgb: str) -> str:
    """A circular progress ring (r=26, C≈163) — richer than the old thin bar."""
    C = 163.4
    off = f"{C * (1 - pct / 100):.1f}"
    return (
        f'<svg class="bring" viewBox="0 0 60 60" aria-hidden="true">'
        f'<circle cx="30" cy="30" r="26" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="4"/>'
        f'<circle class="bring-arc" cx="30" cy="30" r="26" fill="none" stroke="rgba({rgb},.85)" '
        f'stroke-width="4" stroke-linecap="round" stroke-dasharray="{C}" stroke-dashoffset="{off}" '
        f'transform="rotate(-90 30 30)"/></svg>'
    )


def _badges(achs: list[dict]) -> str:
    """Achievements as real game BADGES: a distinctive emblem, a rarity tier
    (epic/rare/common via colour + glow), a circular progress ring for the locked
    ones, and an obviously-different full-colour "unlocked" state. Earned float to
    the front, then hardest tier first — so the trophy shelf reads at a glance."""
    if not achs:
        return '<div class="bempty muted">No badges yet — your first session earns one.</div>'

    def _sortkey(a):
        tier, _ = _TIER.get(a["title"], ("common", ""))
        return (0 if a["earned"] else 1, _TIER_RANK[tier], -(a["cur"] / max(a["goal"], 1)))

    n_earned = sum(1 for a in achs if a["earned"])
    cells = ""
    for a in sorted(achs, key=_sortkey):
        tier, _ = _TIER.get(a["title"], ("common", ""))
        rim, rgb = _TIER_COLOR[tier]
        title = html.escape(a["title"])
        desc = html.escape(a["desc"])
        if a["earned"]:
            cells += (
                f'<div class="badge earned tier-{tier}" style="--rim:{rim};--rgb:{rgb}" '
                f'title="{title} · {desc} · {tier}">'
                f'<div class="bemblem"><div class="bemblem-in">{_icon(a["icon"], 26)}</div>'
                f'<span class="btick">{_icon("trend", 11)}</span></div>'
                f'<div class="bmeta"><b>{title}</b><span class="bdesc">{desc}</span>'
                f'<span class="btag">{tier} · unlocked</span></div></div>'
            )
        else:
            pct = round(100 * a["cur"] / a["goal"]) if a["goal"] else 0
            cells += (
                f'<div class="badge locked tier-{tier}" style="--rim:{rim};--rgb:{rgb}" '
                f'title="{title} · {desc} · {a["cur"]}/{a["goal"]} · {tier}">'
                f'<div class="bemblem">{_badge_ring(pct, rgb)}'
                f'<div class="bemblem-in">{_icon(a["icon"], 24)}</div></div>'
                f'<div class="bmeta"><b>{title}</b><span class="bdesc">{desc}</span>'
                f'<span class="btag">{a["cur"]}/{a["goal"]} · {pct}%</span></div></div>'
            )
    total = len(achs)
    tally = (f'<div class="btally"><b>{n_earned}</b> of {total} unlocked · '
             '<span class="muted">gold epic · teal rare · bronze common</span></div>')
    return f'{tally}<div class="badgegrid">{cells}</div>'


def _chronicle(sessions: list[dict]) -> str:
    """A richer activity feed (not a bare table): a session-type emblem per row,
    the mode name styled, XP as a prominent pill, plus tags — duration, the day,
    and how the XP was sourced. XP is taken LIVE from the rewards ledger so open /
    never-wrapped sittings no longer show a false "+0 XP"."""
    if not sessions:
        return '<div class="chron-empty muted">No sessions yet — your first sitting appears here.</div>'

    ledger = _session_ledger_xp(sessions)
    rows = ""
    for x in sessions:
        mode = x["mode"] or "practice"
        icon, label = _MODE_META.get(mode, ("target", mode.capitalize()))
        started = (x["started_at"] or "")
        day = html.escape(started[:10])
        clock = html.escape(started[11:16])
        planned = x["planned_min"]
        dur = f'{int(planned)} min' if planned else "—"

        stored = int(x["xp"] or 0)
        live = int(ledger.get(started, 0))
        xp = live if live else stored          # live ledger wins; stored is the fallback
        # note when the row is showing live-ledger XP a still-open sitting never stored
        live_flag = (live and not stored)
        xp_cls = "xp-pos" if xp > 0 else ("xp-neg" if xp < 0 else "xp-zero")
        sign = "+" if xp >= 0 else ""

        tags = (f'<span class="ctag">{_icon("hourglass", 11)} {dur}</span>'
                f'<span class="ctag">{_icon("calendar", 11)} {day}</span>')
        if live_flag:
            tags += '<span class="ctag ctag-live" title="counted live from the XP ledger">live</span>'

        rows += (
            f'<div class="crow">'
            f'  <div class="cemblem mode-{mode}">{_icon(icon, 18)}</div>'
            f'  <div class="cbody">'
            f'    <div class="cline"><span class="cmode">{html.escape(label)}</span>'
            f'      <span class="cwhen">{clock}</span></div>'
            f'    <div class="ctags">{tags}</div>'
            f'  </div>'
            f'  <div class="cxp {xp_cls}">{sign}{xp}<span>XP</span></div>'
            f'</div>'
        )
    return f'<div class="chronfeed">{rows}</div>'


# --- journey band (timeline + achievements + heatmap + XP curve + chronicle) -

def _journey_band(ov: dict) -> str:
    ms = journey.milestones()
    acts = journey.activity()
    achs = journey.achievements()
    curve = journey.xp_curve()

    if ms:
        timeline = "".join(
            f'<div class="mile"><div class="mdot">{_icon(ic, 18)}</div>'
            f'<div class="mbody"><b>{html.escape(lbl)}</b><span class="muted">{dt}</span></div></div>'
            for dt, ic, lbl in reversed(ms[-30:])
        )
    else:
        timeline = '<span class="muted">Your journey begins with your first session.</span>'

    ach_html = _badges(achs)

    today = date.today()
    start = today - timedelta(days=today.weekday() + 7 * 11)
    maxn = max(acts.values(), default=1)
    heat, d = "", start
    while d <= today:
        n = acts.get(d.isoformat(), 0)
        op = 0.10 if n == 0 else 0.35 + 0.65 * min(1.0, n / maxn)
        heat += f'<div class="hc" style="background:rgba(231,182,75,{op:.2f})" title="{d.isoformat()}: {n}"></div>'
        d += timedelta(days=1)

    spark = _spark([p[1] for p in curve], "#e7b64b",
                   empty="your XP curve starts with your first graded drill")

    chronicle = _chronicle(ov["sessions"])

    return f"""
  <section class="ov-band">
    <div class="ov-band-head"><span class="ov-band-t">{_icon("hourglass")} Your journey</span>
      <span class="muted ov-band-s">milestones · achievements · the rhythm of your practice</span></div>
    <div class="ov-jgrid">
      <section class="card ov-timeline"><h2>{_icon("hourglass")} Milestones</h2>
        <div class="timeline">{timeline}</div></section>
      <div class="ov-jright">
        <section class="card"><h2>{_icon("calendar")} Activity</h2><div class="heat">{heat}</div>
          <div class="muted" style="font-size:11px;margin-top:8px">last 12 weeks · brighter = more practice</div></section>
        <section class="card"><h2>{_icon("trend")} XP over time</h2>{spark}
          <div class="muted" style="font-size:11px;margin-top:6px">total XP earned across your practice</div></section>
      </div>
      <section class="card ov-ach"><h2>{_icon("medal")} Achievements</h2>
        <div class="achgrid">{ach_html}</div></section>
      <section class="card ov-chron"><h2>{_icon("scroll")} Chronicle</h2>
        {chronicle}</section>
    </div>
  </section>"""


def render() -> str:
    ov = report.overview()
    eff = effectiveness.summary()
    strong = sum(1 for cells in ov["grid"]["pillars"].values()
                 for c in cells.values() if c["level"] == "strong")

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Overview · Ekalavya</title>
<link rel="stylesheet" href="/static/fonts.css">
<style>{_CSS}{journey._JCSS}{effectiveness._EFCSS}{_OVCSS}</style></head><body><div class="wrap ov-wrap">
  <header class="ov-title">
    <div class="brand"><div class="logo"><span class="bowmark">{_BOW}</span> <span class="g">YOUR PROGRESS</span></div>
      <div class="creed" style="font-family:var(--f-serif);font-style:italic">one glance · how far you've come, and whether it's real</div></div>
  </header>
  {_headline(ov, eff, strong)}
  {_quest_band(ov)}
  {_mastery_band(ov)}
  {_effectiveness_band(eff)}
  {_journey_band(ov)}
  <footer class="foot">Ekalavya · the archer who mastered it alone</footer>
</div></body></html>"""


_OVCSS = """
/* ===== Unified Overview (#83) — a COMPLETE SUPERSET of Dashboard + Journey + Effectiveness ===== */
.ov-wrap{gap:24px}
.ov-title .brand{display:flex;flex-direction:column;gap:2px}

/* headline: rank/XP identity on the left, the credibility trio on the right */
.ov-hero{background:var(--hero-aura),linear-gradient(120deg,rgba(46,38,30,.85),rgba(12,10,20,.92));
  border:var(--card-edge);border-radius:12px;padding:22px 26px;
  box-shadow:var(--card-lift),0 0 70px -34px rgba(231,182,75,.5),var(--sh-carve);
  display:flex;justify-content:space-between;align-items:center;gap:24px;flex-wrap:wrap;position:relative}
.ov-hero::before,.ov-hero::after{content:"";position:absolute;width:15px;height:15px;border:1.5px solid var(--gold);opacity:.6}
.ov-hero::before{top:8px;left:8px;border-right:0;border-bottom:0}
.ov-hero::after{bottom:8px;right:8px;border-left:0;border-top:0}
.ov-hero-l{display:flex;align-items:center;gap:18px}
.ov-hero-id{min-width:220px}
.ov-creds{display:grid;grid-template-columns:repeat(3,minmax(120px,1fr));gap:12px;flex:1;min-width:300px}
.ov-cred{background:var(--panel-inner);box-shadow:var(--panel-inner-lift);border:1px solid var(--line-soft);
  border-radius:12px;padding:12px 15px;display:flex;flex-direction:column;gap:3px;border-top:2px solid var(--gold-deep)}
.ov-cred.rising{border-top-color:var(--forest-lit)}
.ov-cred.falling{border-top-color:var(--vermilion-glow)}
.ov-cred.flat{border-top-color:var(--peacock-bright)}
.ovc-k{font-family:var(--f-mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--parch-mute)}
.ovc-v{font-family:var(--f-display);font-size:26px;font-weight:800;line-height:1;color:var(--gold-bright);
  font-variant-numeric:tabular-nums;text-transform:capitalize}
.ov-cred.rising .ovc-v{color:var(--forest-lit)}
.ov-cred.falling .ovc-v{color:var(--vermilion-glow)}
.ov-cred.flat .ovc-v{color:var(--peacock-bright)}
.ovc-s{font-family:var(--f-mono);font-size:11px;color:var(--parch-dim)}
@media(max-width:820px){.ov-hero-id{min-width:0}.ov-creds{grid-template-columns:repeat(3,1fr);min-width:0;width:100%}}
@media(max-width:520px){.ov-creds{grid-template-columns:1fr}.ov-hero-l{width:100%}}

.ov-quests{display:flex;flex-direction:column}

/* labelled band: groups a section of cards under one gold rule */
.ov-band{display:flex;flex-direction:column;gap:16px}
.ov-band-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
  padding-bottom:10px;border-bottom:1px solid var(--line-soft)}
.ov-band-t{font-family:var(--f-title);font-size:19px;color:var(--parch);display:flex;align-items:center;gap:10px}
.ov-band-t.sm{font-size:16px}
.ov-band-t .ic{color:var(--gold-bright);width:18px;height:18px}
.ov-band-s{font-family:var(--f-body);font-style:italic;font-size:13.5px}
.ov-sub-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-top:4px}

/* skill-mastery bento: calibration is the hero, map + axes beside/below it */
.ov-mgrid{display:grid;gap:16px;grid-template-columns:repeat(6,1fr);align-items:stretch;
  grid-template-areas:"cal cal cal cal cal cal" "map map map map axes axes";}
.ov-cal{grid-area:cal}
.ov-map{grid-area:map;max-height:560px;overflow:auto}
.ov-axes{grid-area:axes;display:flex;flex-direction:column}
.ov-axes .bars{flex:1;justify-content:center}
@media(max-width:820px){.ov-mgrid{grid-template-columns:1fr;grid-template-areas:"cal" "map" "axes"}.ov-map{max-height:none}}

/* effectiveness grid inherits .efgrid areas from _EFCSS; the per-subject strips sit below */
.ov-subjects{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.subject-strip{display:flex;flex-direction:column;gap:10px}
.ss-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.ss-name{font-family:var(--f-title);font-size:18px;color:var(--parch);display:flex;align-items:center;gap:9px;text-transform:capitalize}
.ss-name .ic{color:var(--gold-bright)}
.ss-verdict{display:flex;flex-direction:column;align-items:flex-end;gap:1px;text-align:right}
.ss-vword{font-family:var(--f-title);font-size:15px;color:var(--gold-bright);text-transform:capitalize}
.ss-verdict.rising .ss-vword{color:var(--forest-lit)}
.ss-verdict.falling .ss-vword{color:var(--vermilion-glow)}
.ss-verdict.flat .ss-vword{color:var(--peacock-bright)}
.ss-vdetail{font-family:var(--f-mono);font-size:10.5px}
.ss-theta-row{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.ss-theta{font-family:var(--f-display);font-size:18px;font-weight:700;color:var(--gold-bright);font-variant-numeric:tabular-nums}
.ss-theta.muted{color:var(--parch-mute)}
.ss-theta-s{font-family:var(--f-mono);font-size:10.5px}
.ov-spark{width:100%;height:52px}
.ov-spark-empty{display:flex;align-items:center;min-height:52px;font-family:var(--f-mono);font-size:11.5px;
  background:var(--panel-inner);box-shadow:var(--panel-inner-lift);border-radius:8px;padding:0 14px}
.ss-meta{display:flex;flex-wrap:wrap;gap:8px}
.ss-tag{font-family:var(--f-mono);font-size:10.5px;letter-spacing:.02em;color:var(--parch-dim);
  background:var(--panel-inner);box-shadow:var(--panel-inner-lift);border:1px solid var(--line-soft);
  border-radius:20px;padding:4px 11px}
.ss-tag.rising{color:var(--forest-lit);border-color:rgba(82,160,97,.4)}
.ss-tag.falling{color:var(--vermilion-glow);border-color:rgba(214,59,42,.4)}
.ss-elo{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:2px}
.ss-elo-k{font-family:var(--f-mono);font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--parch-mute);
  display:flex;align-items:center;gap:6px;margin-bottom:7px}
.ss-elo-k .ic{width:13px;height:13px;color:var(--gold-bright)}
.ss-pills{display:flex;flex-direction:column;gap:6px}
.ss-pill{font-family:var(--f-title);font-size:12.5px;color:var(--parch-dim);background:var(--panel-inner);
  box-shadow:var(--panel-inner-lift);border:1px solid var(--line-soft);border-radius:7px;padding:6px 10px;
  display:flex;justify-content:space-between;gap:8px}
.ss-pill b{font-family:var(--f-mono);font-variant-numeric:tabular-nums;flex:none}
.ss-pill.strong{border-color:rgba(231,182,75,.28)}.ss-pill.strong b{color:var(--gold-bright)}
.ss-pill.weak{border-color:rgba(214,59,42,.28)}.ss-pill.weak b{color:var(--vermilion-glow)}
@media(max-width:520px){.ss-elo{grid-template-columns:1fr}}

/* journey bento inside the band (timeline · heatmap+curve · achievements · chronicle) */
.ov-jgrid{display:grid;gap:16px;grid-template-columns:repeat(6,1fr);align-items:stretch;
  grid-template-areas:"tl tl tl jr jr jr" "ach ach ach chron chron chron";}
.ov-timeline{grid-area:tl;max-height:460px;overflow:auto}
.ov-jright{grid-area:jr;display:flex;flex-direction:column;gap:16px}
.ov-jright .card{flex:1}
.ov-ach{grid-area:ach}
.ov-chron{grid-area:chron;max-height:340px;overflow:auto}
@media(max-width:820px){.ov-jgrid{grid-template-columns:1fr;grid-template-areas:"tl" "jr" "ach" "chron"}.ov-timeline,.ov-chron{max-height:none}}

/* empty-state pill shared across the effectiveness + subject cards */
.ov-empty{display:flex;align-items:center;gap:14px;min-height:52px;padding:12px 16px;
  background:var(--panel-inner);box-shadow:var(--panel-inner-lift);border:1px solid var(--line-soft);border-radius:9px}
.ov-empty .ov-dash{font-family:var(--f-display);font-weight:800;font-size:34px;color:var(--parch-mute);line-height:1;flex:none}
.ov-empty>span:last-child{font-family:var(--f-body);font-size:13px;line-height:1.45;color:var(--parch-dim)}

/* ===== HUD polish: hero medallion pulse + credibility hover ===== */
.ov-hero{overflow:hidden}
.ov-hero .rank-medallion{position:relative}
.ov-hero .rank-medallion::after{content:"";position:absolute;inset:-6px;border-radius:50%;
  background:radial-gradient(circle,rgba(231,182,75,.22),transparent 70%);z-index:-1;
  animation:ovHalo 4.5s ease-in-out infinite}
@keyframes ovHalo{0%,100%{opacity:.5;transform:scale(1)}50%{opacity:.9;transform:scale(1.06)}}
.ov-cred{transition:transform .2s cubic-bezier(.22,.7,.25,1),border-color .2s,box-shadow .2s}
.ov-cred:hover{transform:translateY(-2px);box-shadow:var(--panel-inner-lift),0 10px 22px -14px rgba(0,0,0,.7)}
.chip{transition:transform .18s cubic-bezier(.22,.7,.25,1),border-color .18s,color .18s}
.chip:hover{transform:translateY(-1px);border-color:var(--gold-deep);color:var(--gold-bright)}

/* ===== Achievement BADGES — a trophy shelf, not a checklist ===== */
.ov-ach .btally{font-family:var(--f-mono);font-size:12px;color:var(--parch-dim);margin:-4px 0 14px}
.ov-ach .btally b{font-family:var(--f-display);font-size:16px;color:var(--gold-bright);font-weight:800}
.badgegrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(196px,1fr));gap:13px}
.badge{position:relative;display:flex;gap:13px;align-items:center;border-radius:14px;padding:13px 15px;
  background:var(--panel-inner);box-shadow:var(--panel-inner-lift);border:1px solid var(--line-soft);
  transition:transform .2s cubic-bezier(.22,.7,.25,1),box-shadow .2s,border-color .2s;overflow:hidden}
/* the emblem: a coin-like disc that carries the tier colour */
.bemblem{position:relative;width:52px;height:52px;flex:none;display:grid;place-items:center}
.bemblem-in{position:absolute;inset:9px;border-radius:50%;display:grid;place-items:center;
  border:1.5px solid var(--rim);background:radial-gradient(circle at 50% 32%,rgba(var(--rgb),.18),rgba(6,9,20,.55));}
.bemblem-in .ic{color:var(--rim)}
.bring{position:absolute;inset:0;width:52px;height:52px}
.bring-arc{transition:stroke-dashoffset .8s cubic-bezier(.22,.7,.25,1)}
/* LOCKED: dim silhouette + the progress ring toward the next unlock */
.badge.locked{filter:grayscale(.35);opacity:.82}
.badge.locked .bemblem-in{background:rgba(6,9,20,.5)}
.badge.locked .bemblem-in .ic{color:var(--parch-mute)}
.badge.locked .btag{color:var(--parch-mute)}
/* EARNED: full colour, a tier-tinted rim glow, and an unlocked flourish tick */
.badge.earned{border-color:color-mix(in srgb,var(--rim) 55%,transparent);
  background:linear-gradient(150deg,rgba(var(--rgb),.14),var(--panel-inner));
  box-shadow:var(--panel-inner-lift),0 0 22px -8px rgba(var(--rgb),.55),inset 0 0 24px -18px rgba(var(--rgb),.9)}
.badge.earned .bemblem-in{border-width:2px;background:radial-gradient(circle at 50% 30%,rgba(var(--rgb),.34),rgba(6,9,20,.55));
  box-shadow:0 0 16px -4px rgba(var(--rgb),.7),inset 0 0 10px -4px rgba(var(--rgb),.9)}
.badge.earned .btag{color:var(--rim)}
.btick{position:absolute;right:-1px;bottom:-1px;width:17px;height:17px;border-radius:50%;
  display:grid;place-items:center;background:var(--rim);box-shadow:0 0 8px -1px rgba(var(--rgb),.9)}
.btick .ic{color:#12100a;width:11px;height:11px;stroke-width:2.4}
.badge:hover{transform:translateY(-3px);border-color:var(--rim);
  box-shadow:var(--panel-inner-lift),0 10px 24px -12px rgba(var(--rgb),.6)}
.bmeta{min-width:0;display:flex;flex-direction:column;gap:1px}
.bmeta b{font-family:var(--f-title);font-size:13.5px;color:var(--parch);line-height:1.15}
.badge.earned .bmeta b{color:var(--gold-bright)}
.bdesc{font-family:var(--f-mono);font-size:10.5px;color:var(--parch-dim);line-height:1.3}
.btag{font-family:var(--f-mono);font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;margin-top:3px}
.bempty{font-family:var(--f-mono);font-size:12px;padding:14px 0}
/* a gentle sheen crossing the epic earned coins — pure flourish, motion-gated */
.badge.earned.tier-epic .bemblem::before{content:"";position:absolute;inset:0;border-radius:50%;
  background:conic-gradient(from 0deg,transparent 0deg,rgba(255,255,255,.28) 24deg,transparent 60deg);
  animation:ovSheen 5s linear infinite;pointer-events:none;mix-blend-mode:screen}
@keyframes ovSheen{to{transform:rotate(360deg)}}

/* ===== Chronicle — a richer activity feed ===== */
.chronfeed{display:flex;flex-direction:column;gap:9px}
.crow{display:flex;align-items:center;gap:13px;padding:10px 13px;border-radius:12px;
  background:var(--panel-inner);box-shadow:var(--panel-inner-lift);border:1px solid var(--line-soft);
  border-left:3px solid var(--gold-deep);transition:transform .16s cubic-bezier(.22,.7,.25,1),border-color .16s}
.crow:hover{transform:translateX(2px);border-left-color:var(--gold)}
.cemblem{width:38px;height:38px;flex:none;border-radius:10px;display:grid;place-items:center;
  color:var(--gold-bright);background:radial-gradient(circle at 50% 32%,rgba(231,182,75,.16),rgba(6,9,20,.5));
  border:1px solid var(--line-gold)}
.cemblem .ic{color:var(--gold-bright)}
/* mode-tinted emblems so the feed reads by shape AND colour */
.cemblem.mode-boss{color:var(--vermilion-glow);border-color:rgba(214,59,42,.4);
  background:radial-gradient(circle at 50% 32%,rgba(214,59,42,.16),rgba(6,9,20,.5))}
.cemblem.mode-boss .ic{color:var(--vermilion-glow)}
.cemblem.mode-blitz,.cemblem.mode-gauntlet{color:var(--peacock-bright);border-color:rgba(87,211,206,.4);
  background:radial-gradient(circle at 50% 32%,rgba(87,211,206,.15),rgba(6,9,20,.5))}
.cemblem.mode-blitz .ic,.cemblem.mode-gauntlet .ic{color:var(--peacock-bright)}
.cbody{flex:1;min-width:0}
.cline{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.cmode{font-family:var(--f-title);font-size:13.5px;color:var(--parch)}
.cwhen{font-family:var(--f-mono);font-size:10.5px;color:var(--parch-mute);flex:none}
.ctags{display:flex;flex-wrap:wrap;gap:6px;margin-top:5px}
.ctag{font-family:var(--f-mono);font-size:10px;color:var(--parch-dim);display:inline-flex;align-items:center;gap:4px;
  background:rgba(6,9,20,.4);border:1px solid var(--line-soft);border-radius:20px;padding:2px 8px}
.ctag .ic{width:11px;height:11px;color:var(--parch-mute)}
.ctag-live{color:var(--peacock-bright);border-color:rgba(87,211,206,.4)}
/* XP: a prominent pill, not a table cell */
.cxp{flex:none;font-family:var(--f-display);font-size:19px;font-weight:800;font-variant-numeric:tabular-nums;
  line-height:1;padding:8px 12px;border-radius:10px;display:flex;align-items:baseline;gap:3px;
  color:var(--gold-bright);background:rgba(231,182,75,.10);border:1px solid var(--line-gold)}
.cxp span{font-family:var(--f-mono);font-size:9px;font-weight:500;letter-spacing:.08em;color:var(--parch-mute)}
.cxp.xp-neg{color:var(--vermilion-glow);background:rgba(214,59,42,.10);border-color:rgba(214,59,42,.35)}
.cxp.xp-zero{color:var(--parch-mute);background:rgba(6,9,20,.4);border-color:var(--line-soft)}
.chron-empty{font-family:var(--f-mono);font-size:12px;padding:14px 0}
@media(max-width:420px){.cxp{font-size:16px;padding:7px 10px}.cemblem{width:34px;height:34px}}
"""
