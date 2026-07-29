"""The Journey view — progress over time.

A milestone timeline, an achievements gallery (earned AND locked with progress),
a GitHub-style activity heatmap, and an XP curve. Its own game-styled page that
reuses the dashboard's palette. Data comes from the history we already log.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import progress
from .db import connect
from .dashboard import _BOW, _CSS, _icon, _rank


def _all(sql: str, params=()):
    conn = connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def xp_curve() -> list[tuple[str, int]]:
    """Cumulative XP over time from the rewards ledger."""
    rows = _all("SELECT amount, created_at FROM rewards WHERE kind IN ('xp','penalty') "
                "ORDER BY created_at")
    cum, pts = 0, []
    for r in rows:
        cum = max(0, cum + (r["amount"] or 0))
        pts.append((r["created_at"], cum))
    return pts


def milestones() -> list[tuple[str, str, str]]:
    """(date, icon, label) events: start, level-ups, skills reaching strong."""
    events: list[tuple[str, str, str]] = []
    first = _all("SELECT MIN(created_at) AS m FROM rewards")[0]["m"] \
        or _all("SELECT MIN(started_at) AS m FROM sessions")[0]["m"]
    if first:
        events.append((first[:10], "target", "Began the journey"))

    level = 1
    for stamp, xp in xp_curve():
        new_level = 1 + xp // 100
        while new_level > level:
            level += 1
            events.append((stamp[:10], "star", f"Reached Level {level}"))

    for r in _all("SELECT pillar, axis, MIN(created_at) AS m FROM rating_history "
                  "WHERE new_rating >= 1300 GROUP BY pillar, axis"):
        events.append((r["m"][:10], "gem", f"Mastered {r['pillar']} · {r['axis'].replace('_', ' ')}"))

    events.sort(key=lambda e: e[0])
    return events


def activity() -> dict[str, int]:
    rows = _all("SELECT substr(created_at,1,10) AS d, COUNT(*) AS n FROM attempts GROUP BY d")
    return {r["d"]: r["n"] for r in rows}


def achievements() -> list[dict]:
    s = progress.stats()
    strong = len(_all("SELECT 1 FROM ratings WHERE rating >= 1300"))
    sessions = _all("SELECT COUNT(*) AS n FROM sessions")[0]["n"]
    defs = [
        ("flame", "On Fire", "3-day streak", s["streak"], 3),
        ("calendar", "Week Warrior", "7-day streak", s["streak"], 7),
        ("infinity", "Unbroken", "30-day streak", s["streak"], 30),
        ("star", "Adept", "reach level 5", s["level"], 5),
        ("crown", "Master", "reach level 10", s["level"], 10),
        ("gem", "First Mastery", "one skill to strong", strong, 1),
        ("sword", "Sharpened", "5 skills to strong", strong, 5),
        ("target", "Initiate", "complete a session", sessions, 1),
        ("prayer", "Devoted", "10 sessions", sessions, 10),
    ]
    return [{"icon": i, "title": t, "desc": d, "cur": min(cur, goal), "goal": goal,
             "earned": cur >= goal} for i, t, d, cur, goal in defs]


def render() -> str:
    ms = milestones()
    acts = activity()
    achs = achievements()
    curve = xp_curve()

    # hero stat ribbon — a game-HUD summary of the journey so far
    st = progress.stats()
    strong = _all("SELECT COUNT(*) AS n FROM ratings WHERE rating >= 1300")[0]["n"]
    sessions = _all("SELECT COUNT(*) AS n FROM sessions")[0]["n"]
    cal = st.get("calibration") or {}
    clarity = "—" if cal.get("brier") is None else str(max(0, min(100, round((1 - cal["brier"]) * 100))))
    ribbon_cells = [
        ("layers", "Level", str(st["level"])),
        ("crown", "Rank", _rank(st["level"])),
        ("flame", "Streak", f"{st['streak']}d"),
        ("trend", "Total XP", str(st["xp"])),
        ("scale", "Clarity", clarity),          # the illusion-of-knowing signal, at a glance
        ("gem", "Skills strong", str(strong)),
    ]
    ribbon = "".join(
        f'<div class="rcell"><div class="rico">{_icon(ic, 16)}</div>'
        f'<div class="rval">{val}</div><div class="rlabel">{label}</div></div>'
        for ic, label, val in ribbon_cells
    )

    if ms:
        timeline = "".join(
            f'<div class="mile"><div class="mdot">{_icon(ic, 18)}</div>'
            f'<div class="mbody"><b>{lbl}</b><span class="muted">{dt}</span></div></div>'
            for dt, ic, lbl in reversed(ms[-40:])
        )
    else:
        timeline = '<span class="muted">Your journey begins with your first session.</span>'

    ach_html = ""
    for a in achs:
        if a["earned"]:
            ach_html += (f'<div class="ach"><div class="aico">{_icon(a["icon"], 22)}</div>'
                         f'<div><b>{a["title"]}</b><span class="muted">{a["desc"]}</span></div></div>')
        else:
            pct = round(100 * a["cur"] / a["goal"])
            ach_html += (f'<div class="ach lock"><div class="aico">{_icon("lock", 22)}</div>'
                         f'<div><b>{a["title"]}</b>'
                         f'<span class="muted">{a["desc"]}</span>'
                         f'<div class="pbar"><div class="pfill" style="width:{pct}%"></div></div>'
                         f'<span class="muted">{a["cur"]}/{a["goal"]}</span></div></div>')

    today = date.today()
    start = today - timedelta(days=today.weekday() + 7 * 11)  # Monday ~12 weeks back
    maxn = max(acts.values(), default=1)
    heat, d = "", start
    while d <= today:
        n = acts.get(d.isoformat(), 0)
        op = 0.10 if n == 0 else 0.35 + 0.65 * min(1.0, n / maxn)
        heat += f'<div class="hc" style="background:rgba(231,182,75,{op:.2f})" title="{d.isoformat()}: {n}"></div>'
        d += timedelta(days=1)

    if len(curve) >= 2:
        mx = max(p[1] for p in curve) or 1
        pts = " ".join(f"{i / (len(curve) - 1) * 300:.1f},{60 - (p[1] / mx * 54):.1f}"
                       for i, p in enumerate(curve))
        spark = (f'<svg viewBox="0 0 300 62" class="spark" preserveAspectRatio="none">'
                 f'<polyline points="{pts}" fill="none" stroke="#e7b64b" stroke-width="2"/></svg>'
                 f'<div class="muted" style="font-size:11px;margin-top:6px">total XP over time</div>')
    else:
        spark = ('<svg viewBox="0 0 300 62" class="spark" preserveAspectRatio="none">'
                 '<line x1="0" y1="6" x2="300" y2="6" stroke="#3a2f26" stroke-dasharray="3 4"/>'
                 '<line x1="0" y1="33" x2="300" y2="33" stroke="#3a2f26" stroke-dasharray="3 4"/>'
                 '<line x1="0" y1="60" x2="300" y2="60" stroke="#3a2f26"/>'
                 '<circle cx="3" cy="60" r="3" fill="#e7b64b"/></svg>'
                 '<div class="muted" style="font-size:11px;margin-top:6px">'
                 'your XP curve starts here · dashed lines mark the level 2 &amp; 3 targets</div>')

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Journey</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700;800;900&family=Marcellus&family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Spectral:ital,wght@0,300;0,400;0,500;0,600;1,400&family=Tiro+Devanagari+Hindi:ital@0;1&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{_CSS}{_JCSS}</style></head><body><div class="wrap">
  <header class="jhero">
    <div class="brand"><div class="logo"><span class="bowmark">{_BOW}</span> <span class="g">YOUR JOURNEY</span></div>
      <div class="creed" style="font-family:var(--f-serif);font-style:italic">how far you've come</div></div>
    <div class="ribbon">{ribbon}</div>
  </header>
  <section class="card"><h2>{_icon("hourglass")} Milestones</h2><div class="timeline">{timeline}</div></section>
  <section class="card"><h2>{_icon("medal")} Achievements</h2><div class="achgrid">{ach_html}</div></section>
  <div class="grid2">
    <section class="card"><h2>{_icon("calendar")} Activity</h2><div class="heat">{heat}</div>
      <div class="muted" style="font-size:11px;margin-top:8px">last 12 weeks · brighter = more practice</div></section>
    <section class="card"><h2>{_icon("trend")} XP over time</h2>{spark}</section>
  </div>
</div></body></html>"""


_JCSS = """
/* journey hero + stat ribbon (game HUD) */
.jhero{background:linear-gradient(120deg,rgba(35,29,24,.82),rgba(12,10,20,.9));border:1px solid var(--line-gold);
  border-radius:6px;padding:22px 26px;box-shadow:var(--sh-carve),var(--sh-deep);
  display:flex;flex-direction:column;gap:18px;position:relative}
.jhero::before,.jhero::after{content:"";position:absolute;width:15px;height:15px;border:1.5px solid var(--gold);opacity:.6}
.jhero::before{top:8px;left:8px;border-right:0;border-bottom:0}
.jhero::after{bottom:8px;right:8px;border-left:0;border-top:0}
.jhero .brand{display:flex;flex-direction:column;gap:2px}
.ribbon{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.rcell{background:rgba(6,9,20,.4);border:1px solid var(--line-soft);border-radius:12px;padding:13px 15px;
  display:flex;flex-direction:column;gap:2px;transition:transform .2s cubic-bezier(.22,.7,.25,1),border-color .2s}
.rcell:hover{transform:translateY(-2px);border-color:var(--gold-deep)}
.rico{color:var(--gold-bright);margin-bottom:3px}.rico .ic{color:var(--gold-bright)}
.rval{font-family:var(--f-display);font-size:22px;font-weight:700;line-height:1;color:var(--parch);
  font-variant-numeric:tabular-nums}
.rlabel{font-family:var(--f-mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--parch-mute)}
@media(max-width:820px){.ribbon{grid-template-columns:repeat(3,1fr)}}
@media(max-width:520px){.ribbon{grid-template-columns:repeat(2,1fr)}}

.timeline{display:flex;flex-direction:column;position:relative}
.mile{display:flex;gap:14px;align-items:flex-start;padding:9px 0;position:relative}
.mile::before{content:"";position:absolute;left:19px;top:0;bottom:0;width:2px;background:var(--line-soft)}
.mdot{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--stone-dark);
  border:1px solid var(--line-gold);z-index:1;color:var(--gold-bright);box-shadow:0 0 0 4px var(--void)}
.mdot .ic{color:var(--gold-bright)}
.mbody b{display:block;font-size:14px;font-family:var(--f-title);color:var(--parch)}.mbody .muted{font-family:var(--f-mono);font-size:11px}
.achgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
.ach{display:flex;gap:12px;align-items:center;background:rgba(6,9,20,.4);border:1px solid var(--line-soft);border-radius:11px;
  padding:11px 14px;transition:transform .2s cubic-bezier(.22,.7,.25,1),border-color .2s}
.ach:hover{transform:translateY(-2px);border-color:var(--gold-deep)}
.ach.lock{filter:grayscale(.7);opacity:.75}
.ach.lock .aico{color:var(--parch-mute)}
.aico{display:grid;place-items:center;width:36px;height:36px;flex:none;border-radius:10px;
  color:var(--gold-bright);background:rgba(231,182,75,.08);border:1px solid var(--gold-deep)}
.aico .ic{color:var(--gold-bright)}
.ach.lock .aico{background:rgba(6,9,20,.5);border-color:var(--line-soft)}
.ach b{display:block;font-size:13px;font-family:var(--f-title);color:var(--parch)}.ach .muted{font-size:11px;font-family:var(--f-mono)}
.pbar{height:6px;background:rgba(6,9,20,.7);border-radius:999px;margin:5px 0 2px;overflow:hidden;width:130px}
.pfill{height:100%;background:linear-gradient(90deg,var(--gold-deep),var(--gold-bright))}
.heat{display:grid;grid-template-rows:repeat(7,13px);grid-auto-flow:column;grid-auto-columns:13px;gap:3px}
.hc{width:13px;height:13px;border-radius:2px;border:1px solid rgba(231,182,75,.08)}
.spark{width:100%;height:70px}
"""
