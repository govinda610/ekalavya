"""The Journey view — progress over time.

A milestone timeline, an achievements gallery (earned AND locked with progress),
a GitHub-style activity heatmap, and an XP curve. Its own game-styled page that
reuses the dashboard's palette. Data comes from the history we already log.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import progress
from .db import connect
from .dashboard import _CSS


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
        events.append((first[:10], "🏹", "Began the journey"))

    level = 1
    for stamp, xp in xp_curve():
        new_level = 1 + xp // 100
        while new_level > level:
            level += 1
            events.append((stamp[:10], "⭐", f"Reached Level {level}"))

    for r in _all("SELECT pillar, axis, MIN(created_at) AS m FROM rating_history "
                  "WHERE new_rating >= 1300 GROUP BY pillar, axis"):
        events.append((r["m"][:10], "💎", f"Mastered {r['pillar']} · {r['axis'].replace('_', ' ')}"))

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
        ("🔥", "On Fire", "3-day streak", s["streak"], 3),
        ("🗓️", "Week Warrior", "7-day streak", s["streak"], 7),
        ("♾️", "Unbroken", "30-day streak", s["streak"], 30),
        ("⭐", "Adept", "reach level 5", s["level"], 5),
        ("👑", "Master", "reach level 10", s["level"], 10),
        ("💎", "First Mastery", "one skill to strong", strong, 1),
        ("🗡️", "Sharpened", "5 skills to strong", strong, 5),
        ("🏹", "Initiate", "complete a session", sessions, 1),
        ("📿", "Devoted", "10 sessions", sessions, 10),
    ]
    return [{"icon": i, "title": t, "desc": d, "cur": min(cur, goal), "goal": goal,
             "earned": cur >= goal} for i, t, d, cur, goal in defs]


def render() -> str:
    ms = milestones()
    acts = activity()
    achs = achievements()
    curve = xp_curve()

    if ms:
        timeline = "".join(
            f'<div class="mile"><div class="mdot">{ic}</div>'
            f'<div class="mbody"><b>{lbl}</b><span class="muted">{dt}</span></div></div>'
            for dt, ic, lbl in reversed(ms[-40:])
        )
    else:
        timeline = '<span class="muted">Your journey begins with your first session.</span>'

    ach_html = ""
    for a in achs:
        if a["earned"]:
            ach_html += (f'<div class="ach"><div class="aico">{a["icon"]}</div>'
                         f'<div><b>{a["title"]}</b><span class="muted">{a["desc"]}</span></div></div>')
        else:
            pct = round(100 * a["cur"] / a["goal"])
            ach_html += (f'<div class="ach lock"><div class="aico">🔒</div><div><b>{a["title"]}</b>'
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
        heat += f'<div class="hc" style="background:rgba(94,242,184,{op:.2f})" title="{d.isoformat()}: {n}"></div>'
        d += timedelta(days=1)

    if len(curve) >= 2:
        mx = max(p[1] for p in curve) or 1
        pts = " ".join(f"{i / (len(curve) - 1) * 300:.1f},{60 - (p[1] / mx * 54):.1f}"
                       for i, p in enumerate(curve))
        spark = (f'<svg viewBox="0 0 300 62" class="spark" preserveAspectRatio="none">'
                 f'<polyline points="{pts}" fill="none" stroke="#5ef2b8" stroke-width="2"/></svg>'
                 f'<div class="muted" style="font-size:11px;margin-top:6px">total XP over time</div>')
    else:
        spark = '<span class="muted">Your XP curve appears as you practise.</span>'

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Journey</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{_CSS}{_JCSS}</style></head><body><div class="wrap">
  <header class="hero"><div class="brand"><div class="logo">🏹 <span class="g">YOUR JOURNEY</span></div>
    <div class="creed">how far you've come</div></div></header>
  <section class="card"><h2>⏳ Milestones</h2><div class="timeline">{timeline}</div></section>
  <section class="card"><h2>🏅 Achievements</h2><div class="achgrid">{ach_html}</div></section>
  <div class="grid2">
    <section class="card"><h2>🗓️ Activity</h2><div class="heat">{heat}</div>
      <div class="muted" style="font-size:11px;margin-top:8px">last 12 weeks · brighter = more practice</div></section>
    <section class="card"><h2>📈 XP over time</h2>{spark}</section>
  </div>
</div></body></html>"""


_JCSS = """
.timeline{display:flex;flex-direction:column}
.mile{display:flex;gap:14px;align-items:flex-start;padding:7px 0;position:relative}
.mile::before{content:"";position:absolute;left:19px;top:0;bottom:0;width:2px;background:var(--line)}
.mdot{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--panel);
  border:1px solid var(--line);z-index:1;font-size:17px;box-shadow:0 0 0 4px var(--bg)}
.mbody b{display:block;font-size:14px}.mbody .muted{font-family:var(--mono);font-size:11px}
.achgrid{display:flex;flex-wrap:wrap;gap:12px}
.ach{display:flex;gap:12px;align-items:center;background:#0c1622;border:1px solid #24344a;border-radius:12px;
  padding:11px 14px;min-width:210px}
.ach.lock{opacity:.6;border-style:dashed}
.aico{font-size:25px;filter:drop-shadow(0 0 8px #0008)}
.ach b{display:block;font-size:13px}.ach .muted{font-size:11px}
.pbar{height:6px;background:#0b1420;border-radius:999px;margin:5px 0 2px;overflow:hidden;width:130px}
.pfill{height:100%;background:linear-gradient(90deg,var(--acc),var(--cyan))}
.heat{display:grid;grid-template-rows:repeat(7,13px);grid-auto-flow:column;grid-auto-columns:13px;gap:3px}
.hc{width:13px;height:13px;border-radius:3px;border:1px solid #10203044}
.spark{width:100%;height:70px}
"""
