"""The local web dashboard — a game-styled progress screen.

Dark, RPG/adventure aesthetic (level, XP bar, skill map, quests, achievements),
grounded in dark-UI research: soft-dark surfaces, a small set of desaturated
accents, elevation over decoration, readable categorical chart colors, and —
crucially — a prescriptive "what to do next" quest rather than raw numbers.

`render` is a pure function of the overview dict, so it's easy to test.
"""

from __future__ import annotations

import html

from . import report

# Option-E semantic mastery ramp: gold = mastered, teal = unlocked/familiar,
# vermilion = gap, muted-parch = unknown (the same four hues used everywhere).
LEVEL_COLOR = {
    "unknown": "#a89670",
    "gap": "#ff5a3c",
    "familiar": "#57d3ce",
    "strong": "#e7b64b",
}
AXIS_COLOR = {
    "syntax_recall": "#57d3ce",
    "debugging": "#e7b64b",
    "code_reading": "#52a061",
    "api_memory": "#f7d98a",
    "decomposition": "#d63b2a",
}
_RANKS = [(17, "Grandmaster"), (12, "Master"), (8, "Expert"), (5, "Adept"),
          (3, "Apprentice"), (1, "Novice")]

# --- line icons -------------------------------------------------------------
# A tiny Feather/Lucide-style stroke-icon set. Each value is the inner SVG paths;
# `_icon` wraps them in a 16px <svg> that inherits the current text color, so a
# header's dim color flows straight into the glyph. Emoji retired everywhere
# except the two brand marks (bow logo, death skull) which stay inline.
_ICON_PATHS = {
    "grid":     '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "bars":     '<line x1="4" y1="20" x2="4" y2="12"/><line x1="10" y1="20" x2="10" y2="4"/><line x1="16" y1="20" x2="16" y2="9"/><line x1="22" y1="20" x2="22" y2="14"/>',
    "target":   '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
    "scale":    '<path d="M12 3v18"/><path d="M5 8h14"/><path d="M5 8l-2 5a3 3 0 0 0 6 0z"/><path d="M19 8l-2 5a3 3 0 0 0 6 0z"/>',
    "medal":    '<circle cx="12" cy="15" r="5"/><path d="M9 10L6 3M15 10l3-7"/>',
    "scroll":   '<path d="M6 4h11a2 2 0 0 1 2 2v12a2 2 0 0 0 2 2H8a2 2 0 0 1-2-2z"/><path d="M6 4a2 2 0 0 0-2 2v2h4"/>',
    "sword":    '<path d="M14 3h7v7l-9 9-5-5z"/><line x1="5" y1="14" x2="10" y2="19"/><line x1="3" y1="21" x2="7" y2="17"/>',
    "flame":    '<path d="M12 3c1 4 5 5 5 9a5 5 0 0 1-10 0c0-2 1-3 2-4 0 1 1 2 2 2 0-2-1-4 1-7z"/>',
    "calendar": '<rect x="4" y="5" width="16" height="15" rx="2"/><line x1="4" y1="9" x2="20" y2="9"/><line x1="8" y1="3" x2="8" y2="6"/><line x1="16" y1="3" x2="16" y2="6"/>',
    "infinity": '<path d="M7 12c-2.5 0-4-1.6-4-3.5S4.5 5 7 5s3.5 2 5 3.5c1.5 1.5 2.5 3.5 5 3.5s4-1.6 4-3.5S24.5 8 22 8"/>',
    "star":     '<path d="M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z"/>',
    "crown":    '<path d="M4 18h16M4 18l-1-9 5 4 4-7 4 7 5-4-1 9"/>',
    "gem":      '<path d="M6 3h12l3 6-9 12L3 9z"/><path d="M3 9h18M9 3l-3 6 6 12 6-12-3-6"/>',
    "prayer":   '<circle cx="12" cy="12" r="8"/><path d="M12 6v6l4 2"/>',
    "hourglass": '<path d="M6 3h12M6 21h12"/><path d="M6 3c0 5 6 6 6 9s-6 4-6 9M18 3c0 5-6 6-6 9s6 4 6 9"/>',
    "lock":     '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "trend":    '<path d="M3 17l6-6 4 4 8-8"/><path d="M17 7h4v4"/>',
    "layers":   '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "compass":  '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    "activity": '<path d="M3 12h4l3 8 4-16 3 8h4"/>',
    "user":     '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
    "pencil":   '<path d="M4 20h4L20 8l-4-4L4 16z"/><line x1="14" y1="6" x2="18" y2="10"/>',
}


def _icon(name: str, size: int = 16) -> str:
    return (f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" '
            f'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{_ICON_PATHS[name]}</svg>')


def _rank(level: int) -> str:
    for threshold, name in _RANKS:
        if level >= threshold:
            return name
    return "Novice"


def _rank_ring(level: int, into: int) -> str:
    """The template's radial rank-ring (G's ringArcPdash, r=46 → C≈289): XP as a
    continuous ring fill, not a horizontal bar. `into` is 0–100 percent to next rank."""
    C = 289.0
    off = f"{C * (1 - into / 100):.1f}"
    return (
        '<svg class="rank-ring" viewBox="0 0 104 104" aria-label="XP '
        f'{into}% to next rank"><g transform="rotate(-90 52 52)">'
        '<circle cx="52" cy="52" r="46" fill="none" stroke="rgba(231,182,75,.16)" stroke-width="5"/>'
        '<circle class="arc" cx="52" cy="52" r="46" fill="none" stroke="url(#ringGrad)" '
        f'stroke-width="5" stroke-linecap="round" stroke-dasharray="{C}" stroke-dashoffset="{off}"/>'
        '</g><circle cx="52" cy="52" r="34" fill="#101528" stroke="#f7d98a" stroke-width="2"/></svg>'
    )


def _pct(rating: float) -> int:
    return max(4, min(100, round((rating - 800) / (1500 - 800) * 100)))


def _cell(cell: dict | None) -> str:
    if not cell:
        return '<td class="cell empty"></td>'
    c = LEVEL_COLOR.get(cell["level"], "#3a4658")
    return (f'<td class="cell" style="color:{c};border-color:{c}66;background:{c}14;'
            f'box-shadow:0 0 12px {c}22 inset" title="rating {cell["rating"]}">{cell["level"]}</td>')


def _achievements(stats: dict, strong: int, sessions: int) -> str:
    earned = []
    if stats["streak"] >= 3: earned.append(("flame", "On Fire", "3-day streak"))
    if stats["streak"] >= 7: earned.append(("calendar", "Week Warrior", "7-day streak"))
    if stats["streak"] >= 30: earned.append(("infinity", "Unbroken", "30-day streak"))
    if stats["level"] >= 5: earned.append(("star", "Adept", "reached level 5"))
    if stats["level"] >= 10: earned.append(("crown", "Master", "reached level 10"))
    if strong >= 1: earned.append(("gem", "First Mastery", "a skill hit strong"))
    if strong >= 5: earned.append(("sword", "Sharpened", "5 skills at strong"))
    if sessions >= 1: earned.append(("target", "Initiate", "completed a session"))
    if sessions >= 10: earned.append(("prayer", "Devoted", "10 sessions"))
    if not earned:
        return '<span class="muted">No badges yet — your first session earns one.</span>'
    return "".join(
        f'<div class="badge"><div class="bico">{_icon(i, 20)}</div><div><b>{t}</b>'
        f'<span class="muted">{d}</span></div></div>' for i, t, d in earned
    )


def _calibration(cal: dict) -> str:
    """The 'illusion of knowing' card — the product's headline metric.
    cal = {n, brier, bias, confidently_wrong}; brier/bias are None until there's data."""
    n = cal.get("n") or 0
    if not n or cal.get("brier") is None:
        return ('<div class="cal-empty muted">Answer a few drills with a confidence level and '
                'your calibration appears here — how well what you <i>think</i> you know matches '
                'what you can <i>actually</i> do.</div>')
    brier = cal["brier"]          # 0 = perfect, 1 = worst
    bias = cal["bias"]            # >0 overconfident, <0 underconfident
    cw = cal.get("confidently_wrong", 0)
    # a friendly 0-100 "clarity" score: lower brier -> higher clarity
    clarity = max(0, min(100, round((1 - brier) * 100)))
    if abs(bias) < 0.08:
        lean, leancls = "well-calibrated", "ok"
    elif bias > 0:
        lean, leancls = "overconfident", "warn"
    else:
        lean, leancls = "underconfident", "cool"
    ring = f"conic-gradient(var(--gold) {clarity*3.6:.0f}deg, rgba(231,182,75,.12) 0)"
    return (
        f'<div class="cal-row">'
        f'  <div class="cal-ring" style="background:{ring}"><div class="cal-ring-in">'
        f'    <div class="cal-score">{clarity}</div><div class="cal-score-k">clarity</div></div></div>'
        f'  <div class="cal-facts">'
        f'    <div class="cal-fact"><b class="{leancls}">{lean}</b>'
        f'      <span class="muted">bias {bias:+.2f} · Brier {brier:.2f}</span></div>'
        f'    <div class="cal-fact"><b class="{"warn" if cw else "ok"}">{cw}</b>'
        f'      <span class="muted">confidently wrong — sure, yet wrong</span></div>'
        f'    <div class="cal-fact"><b>{n}</b><span class="muted">recent graded drills</span></div>'
        f'  </div>'
        f'</div>'
        f'<div class="cal-caption muted">The gap between what you <i>think</i> you know and what '
        f'you can <i>actually</i> do — the illusion of knowing, made visible.</div>'
    )


def render(ov: dict) -> str:
    s = ov["stats"]
    g = ov["grid"]
    axes = g["axes"]
    level, xp, streak = s["level"], s["xp"], s["streak"]
    into = xp % 100  # level up every 100 XP
    rank = _rank(level)

    # weakest cell -> today's quest (prescriptive)
    weakest = None
    strong = 0
    for pillar, cells in g["pillars"].items():
        for axis, cell in cells.items():
            if cell["level"] == "strong":
                strong += 1
            if weakest is None or cell["rating"] < weakest[2]:
                weakest = (pillar, axis, cell["rating"])
    if weakest:
        quest = (f"Sharpen <b>{html.escape(weakest[0])} · "
                 f"{html.escape(weakest[1].replace('_', ' '))}</b> — your weakest skill.")
    else:
        quest = "Run <code>eklavya onboard</code> to map your skills, then your quests appear here."
    due_line = (f"<span class='due'>⚡ {ov['due']} review(s) due</span>" if ov.get("due") else
                "<span class='muted'>no reviews due — learn something new</span>")

    # skill map
    axis_head = "".join(f'<th class="ax">{a.replace("_", " ")}</th>' for a in axes)
    if g["pillars"]:
        rows = "".join(
            f"<tr><th class='pillar'>{html.escape(p)}</th>" + "".join(_cell(cells.get(a)) for a in axes) + "</tr>"
            for p, cells in g["pillars"].items()
        )
    else:
        rows = f'<tr><td colspan="{len(axes)+1}" class="muted">No skills yet — run onboarding.</td></tr>'

    # per-axis mastery bars (average rating across pillars)
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

    # unaided vs AI-assisted gap
    ag = ov.get("ai_gap", {})
    if not ag.get("unaided_n"):
        aigap = '<span class="muted">No attempts yet — practice to watch your unaided accuracy climb.</span>'
    else:
        tbars = "".join(
            f'<div class="tbar" style="height:{max(6, t["rate"] or 0)}%" '
            f'title="{t["day"]}: {t["rate"]}% ({t["n"]})"></div>' for t in ag["trend"]
        )
        if ag.get("assisted_n"):
            extra = (f'<div class="agstat"><b>{ag["assisted_rate"]}%</b><span>with AI</span></div>'
                     f'<div class="agstat gap"><b>{ag["gap"]:+d}</b><span>gap to close</span></div>')
        else:
            extra = '<div class="agnote muted">Do an "AI-on check" sometime to measure your gap.</div>'
        aigap = (f'<div class="agrow"><div class="agstat"><b>{ag["unaided_rate"]}%</b>'
                 f'<span>unaided</span></div>{extra}</div>'
                 f'<div class="trend">{tbars}</div>'
                 f'<div class="muted" style="font-size:11px;margin-top:6px">unaided accuracy · recent days</div>')

    goals = "".join(
        f'<div class="quest" onclick="this.classList.toggle(\'open\')" title="click to expand">'
        f'<span class="hz {html.escape(x["horizon"])}">{html.escape(x["horizon"])}</span>'
        f'<span class="qtext">{html.escape(x["text"])}</span>'
        + (f'<span class="muted qd">· {html.escape(x["deadline"])}</span>' if x.get("deadline") else "") + "</div>"
        for x in ov["goals"]
    ) or '<span class="muted">No quests yet.</span>'

    sessions = "".join(
        f'<tr><td>{html.escape((x["started_at"] or "")[:16])}</td><td>{html.escape(x["mode"] or "practice")}</td>'
        f'<td>{html.escape(str(x["planned_min"] or ""))} min</td><td class="xp">+{int(x["xp"] or 0)} XP</td></tr>'
        for x in ov["sessions"]
    ) or '<tr><td colspan="4" class="muted">No sessions yet.</td></tr>'

    badges = _achievements(s, strong, len(ov["sessions"]))
    calibration = _calibration(s.get("calibration") or {})

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ekalavya</title>
<link rel="stylesheet" href="/static/fonts.css">
<style>{_CSS}</style></head><body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#b8862f"/><stop offset="1" stop-color="#f7d98a"/></linearGradient></defs></svg>
<div class="wrap">

  <header class="hero">
    <div class="brand">
      <div class="logo"><span class="bowmark">{_BOW}</span> <span class="g">EKALAVYA</span></div>
      <div class="creed">स्वाध्याय · साधना · सिद्धि</div>
    </div>
    <div class="char">
      <div class="rank-medallion">{_rank_ring(level, into)}
        <div class="rmlabel"><div class="rmnum">{level}</div><div class="rmtag">RANK</div></div>
      </div>
      <div class="charmid">
        <div class="rank">{rank}</div>
        <div class="prog-line">Lv <b>{level}</b> · <b>{into}%</b> → R{level + 1}
          <span class="prog-xp">{xp:,} total XP</span></div>
        <div class="chips"><span class="chip flame">{_icon("flame")} {streak} day streak</span>
          <span class="chip">✦ {into} / 100 XP to next</span></div>
      </div>
    </div>
  </header>

  <section class="quest-banner">
    <div class="qtitle">{_icon("sword")} TODAY'S QUEST</div>
    <div class="qbody">{quest}</div>
    <div class="qmeta">{due_line}</div>
  </section>

  <div class="bento">
    <section class="card b-cal">
      <h2>{_icon("scale")} The illusion of knowing</h2>
      {calibration}
    </section>
    <section class="card b-map">
      <h2>{_icon("grid")} Skill map</h2>
      <table class="heat"><tr><th class="pillar"></th>{axis_head}</tr>{rows}</table>
      <div class="legend">
        <span><i style="background:#a89670"></i>unknown</span>
        <span><i style="background:#ff5a3c"></i>gap</span>
        <span><i style="background:#57d3ce"></i>familiar</span>
        <span><i style="background:#e7b64b"></i>strong</span>
      </div>
    </section>
    <section class="card b-axes">
      <h2>{_icon("bars")} Skill axes</h2>
      <div class="bars">{bars}</div>
    </section>
    <section class="card b-quests">
      <h2>{_icon("target")} Active quests</h2>
      <div class="quests">{goals}</div>
    </section>
    <section class="card b-gap">
      <h2>{_icon("scale")} Unaided vs AI-assisted</h2>
      {aigap}
    </section>
    <section class="card b-ach">
      <h2>{_icon("medal")} Achievements</h2>
      <div class="badges">{badges}</div>
    </section>
    <section class="card b-chron">
      <h2>{_icon("scroll")} Chronicle</h2>
      <table class="chron">{sessions}</table>
    </section>
  </div>

  <footer class="foot">Ekalavya · the archer who mastered it alone</footer>
</div></body></html>"""


def create_app():
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="Ekalavya", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return render(report.overview())

    @app.get("/api/overview")
    def overview() -> dict:
        return report.overview()

    return app


# The gold bow brand-mark (Option-E), used in place of the emoji everywhere the logo appears.
_BOW = ('<svg width="20" height="26" viewBox="0 0 58 76" aria-hidden="true" '
        'style="vertical-align:-4px"><path d="M14 6 C40 24 40 52 14 70" stroke="#e7b64b" '
        'stroke-width="4" stroke-linecap="round" fill="none"/>'
        '<line x1="14" y1="6" x2="14" y2="70" stroke="#57d3ce" stroke-width="1.6"/>'
        '<line x1="14" y1="38" x2="50" y2="38" stroke="#f7d98a" stroke-width="2.4"/>'
        '<path d="M50 38 l-7 -5 M50 38 l-7 5" stroke="#f7d98a" stroke-width="2.4" '
        'stroke-linecap="round"/></svg>')


# Option-E "cinematic forest" design system, mapped onto the dashboard/journey/profile
# markup. Same class hooks the Python render already emits — only the look changes (gold
# on uniform indigo-night, Cinzel/Marcellus/Spectral/Tiro-Devanagari/JetBrains-Mono, the
# Raji-style gold hairline frames, semantic mastery ramp gold/teal/vermilion).
_CSS = """
:root{
  --indigo-night:#101528; --indigo-deep:#0b1122; --void:#0a0d1c;
  --stone:#231d18; --stone-dark:#181310; --stone-warm:#3a2f26;
  --parch:#e8dcc0; --parch-dim:#cfc0a0; --parch-mute:#a89670;
  --gold:#e7b64b; --gold-bright:#f7d98a; --gold-deep:#b8862f; --gold-ember:#8a5e1f;
  --vermilion:#d63b2a; --vermilion-deep:#8f2318; --vermilion-glow:#ff5a3c;
  --peacock:#2ea3a0; --peacock-bright:#57d3ce; --peacock-deep:#124d4c;
  --forest:#2f6b3c; --forest-lit:#52a061;
  --line-gold:rgba(231,182,75,.28); --line-soft:rgba(231,182,75,.14); --ink:#0a0c18;
  --f-display:'Cinzel',serif; --f-title:'Marcellus',serif; --f-body:'Spectral',serif;
  --f-serif:'Cormorant Garamond',serif; --f-deva:'Tiro Devanagari Hindi',serif;
  --f-mono:'JetBrains Mono',ui-monospace,monospace;
  --sh-deep:0 24px 60px -20px rgba(0,0,0,.8);
  --sh-carve:inset 0 1px 0 rgba(231,182,75,.10), inset 0 -18px 40px -20px rgba(0,0,0,.7);
  /* aliases so the existing markup's color intents map to the semantic ramp */
  --acc:var(--gold); --cyan:var(--peacock-bright); --violet:var(--gold-bright);
  --amber:var(--gold-bright); --dim:var(--parch-dim); --ink2:var(--parch);
}
*{box-sizing:border-box}
body{margin:0;font-family:var(--f-body);color:var(--parch);line-height:1.6;
  -webkit-font-smoothing:antialiased;
  background-color:var(--indigo-night);
  background-image:
    radial-gradient(1200px 700px at 78% 2%, rgba(46,163,160,.08), transparent 60%),
    radial-gradient(900px 600px at 12% 6%, rgba(231,182,75,.07), transparent 55%);
  background-attachment:fixed;
  padding:26px 20px 60px;min-height:100vh}
/* film grain */
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:9999;opacity:.05;mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
.wrap{max-width:1080px;margin:0 auto;display:flex;flex-direction:column;gap:18px;position:relative;z-index:1}
.g{color:transparent;background:linear-gradient(180deg,#fff6df 0%,var(--gold-bright) 40%,var(--gold) 70%,var(--gold-deep) 100%);
  -webkit-background-clip:text;background-clip:text}
.bowmark{filter:drop-shadow(0 2px 10px rgba(231,182,75,.35))}
.muted{color:var(--parch-dim)}
code{font-family:var(--f-mono);color:var(--gold-bright);background:rgba(6,9,20,.6);
  padding:1px 6px;border-radius:4px;border:1px solid var(--line-soft)}
h2{font-family:var(--f-mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--parch-mute);margin:0 0 14px;font-weight:500;display:flex;align-items:center;gap:8px}
.ic{flex:none;color:var(--gold-bright)}
h2 .ic{width:15px;height:15px}

/* hero / character */
.hero{display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap;
  background:linear-gradient(120deg,rgba(35,29,24,.82),rgba(12,10,20,.9));border:1px solid var(--line-gold);
  border-radius:6px;padding:22px 26px;box-shadow:var(--sh-carve),var(--sh-deep);position:relative}
.hero::before,.hero::after{content:"";position:absolute;width:15px;height:15px;border:1.5px solid var(--gold);opacity:.6}
.hero::before{top:8px;left:8px;border-right:0;border-bottom:0}
.hero::after{bottom:8px;right:8px;border-left:0;border-top:0}
.logo{font-family:var(--f-display);font-size:28px;font-weight:800;letter-spacing:.14em;display:flex;align-items:center;gap:10px}
.creed{font-family:var(--f-deva);color:var(--gold-bright);font-size:15px;letter-spacing:.04em;margin-top:4px;opacity:.92}
.char{display:flex;align-items:center;gap:18px}
/* rank-ring medallion (template G): XP is a continuous ring fill, not a bar */
.rank-medallion{position:relative;width:84px;height:84px;flex:none}
.rank-medallion .rank-ring{width:84px;height:84px;display:block;filter:drop-shadow(0 0 18px rgba(231,182,75,.4))}
.rank-medallion .rank-ring .arc{transition:stroke-dashoffset 1.2s cubic-bezier(.22,.7,.25,1)}
.rank-medallion .rmlabel{position:absolute;inset:0;display:grid;place-items:center;text-align:center}
.rank-medallion .rmnum{font-family:var(--f-display);font-size:30px;font-weight:800;line-height:1;color:var(--gold-bright);text-shadow:0 2px 8px rgba(231,182,75,.4)}
.rank-medallion .rmtag{font-family:var(--f-mono);font-size:9px;letter-spacing:.2em;color:var(--parch-mute);margin-top:1px}
.charmid{min-width:260px}
.rank{font-family:var(--f-title);font-size:22px;font-weight:600;letter-spacing:.06em;color:var(--gold-bright)}
.prog-line{font-family:var(--f-mono);font-size:13px;color:var(--parch-dim);margin:8px 0 10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.prog-line b{color:var(--gold-bright)}
.prog-xp{font-family:var(--f-mono);font-size:11px;color:var(--parch-mute)}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{font-family:var(--f-mono);font-size:12px;color:var(--parch-dim);background:rgba(6,9,20,.5);
  border:1px solid var(--line-soft);border-radius:999px;padding:4px 12px}
.chip.flame{color:var(--gold-bright);border-color:var(--gold-deep)}

/* today's quest — the boss objective */
.quest-banner{background:linear-gradient(100deg,rgba(35,29,24,.7),rgba(12,10,20,.85));border:1px solid var(--line-gold);
  border-left:3px solid var(--gold);border-radius:6px;padding:18px 24px;box-shadow:var(--sh-carve)}
.qtitle{font-family:var(--f-mono);letter-spacing:.16em;color:var(--vermilion-glow);font-size:12px;font-weight:500;
  text-transform:uppercase;display:flex;align-items:center;gap:8px}
.qtitle .ic{width:16px;height:16px;color:var(--vermilion-glow)}
.qbody{font-family:var(--f-title);font-size:20px;margin:6px 0 6px;color:var(--parch)}
.qmeta .due{color:var(--gold-bright);font-family:var(--f-mono);font-size:13px}

/* cards */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
@media(max-width:820px){.grid2{grid-template-columns:1fr}.char{width:100%}}

/* bento — asymmetric, skill map is the hero */
.bento{display:grid;gap:18px;grid-template-columns:repeat(6,1fr);align-items:start;
  grid-template-areas:
    "cal cal cal cal cal cal"
    "map map map map axes axes"
    "quests quests gap gap gap gap"
    "ach ach ach ach chron chron";}
.b-cal{grid-area:cal}
.b-map{grid-area:map}.b-axes{grid-area:axes}.b-quests{grid-area:quests}
.b-gap{grid-area:gap}.b-ach{grid-area:ach}.b-chron{grid-area:chron}
.bento .card{margin:0}
@media(max-width:820px){
  .bento{grid-template-columns:1fr;grid-template-areas:"cal" "map" "axes" "quests" "gap" "ach" "chron"}
}
/* the illusion-of-knowing card — the product's headline signal */
.b-cal{background:linear-gradient(150deg,rgba(35,29,24,.72),rgba(12,10,20,.85));border-color:var(--line-gold)}
.cal-row{display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.cal-ring{width:104px;height:104px;border-radius:50%;flex:none;display:grid;place-items:center;
  box-shadow:0 0 24px -6px rgba(231,182,75,.4)}
.cal-ring-in{width:82px;height:82px;border-radius:50%;background:var(--indigo-night);display:grid;place-items:center;text-align:center}
.cal-score{font-family:var(--f-display);font-weight:800;font-size:30px;color:var(--gold-bright);line-height:1}
.cal-score-k{font-family:var(--f-mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--parch-mute);margin-top:2px}
.cal-facts{display:flex;gap:30px;flex-wrap:wrap}
.cal-fact{display:flex;flex-direction:column;gap:2px}
.cal-fact b{font-family:var(--f-display);font-size:22px;font-weight:700;color:var(--parch)}
.cal-fact b.ok{color:var(--forest-lit)}.cal-fact b.cool{color:var(--peacock-bright)}
.cal-fact b.warn{color:var(--vermilion-glow)}
.cal-fact .muted{font-family:var(--f-mono);font-size:10.5px;letter-spacing:.03em;max-width:20ch}
.cal-caption{margin-top:14px;font-family:var(--f-body);font-size:13px;line-height:1.5}
.cal-empty{font-family:var(--f-body);font-size:14px;line-height:1.55;padding:6px 0}
.card{background:linear-gradient(160deg,rgba(35,29,24,.6),rgba(12,10,20,.75));border:1px solid var(--line-gold);
  border-radius:6px;padding:20px 22px;box-shadow:var(--sh-carve),0 18px 50px -34px #000;
  transition:transform .22s cubic-bezier(.22,.7,.25,1),border-color .22s,box-shadow .22s}
.card:hover{transform:translateY(-2px);border-color:var(--gold-deep);
  box-shadow:var(--sh-carve),0 22px 54px -30px #000c}

/* skill map */
table{width:100%;border-collapse:separate;border-spacing:5px}
.heat th.ax{color:var(--parch-mute);font-family:var(--f-mono);font-weight:400;text-align:center;
  font-size:10px;text-transform:uppercase;letter-spacing:.05em;padding-bottom:4px}
.heat th.pillar{text-align:left;color:var(--parch);white-space:nowrap;font-size:13px;font-weight:400;
  font-family:var(--f-title);padding-right:8px}
.cell{text-align:center;border:1px solid var(--line-soft);border-radius:7px;padding:9px 6px;font-size:10px;
  font-family:var(--f-mono);text-transform:uppercase;letter-spacing:.03em;transition:transform .1s}
.cell:hover{transform:translateY(-1px)}
.cell.empty{border-style:dashed;border-color:var(--line-soft)}.cell.empty::after{content:"·";color:var(--parch-mute)}
.legend{display:flex;gap:16px;margin-top:12px;font-family:var(--f-mono);font-size:10px;color:var(--parch-dim);
  letter-spacing:.06em;text-transform:uppercase;flex-wrap:wrap}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:middle}

/* axis bars */
.bars{display:flex;flex-direction:column;gap:13px;margin-top:4px}
.barlabel{font-family:var(--f-mono);font-size:10px;color:var(--parch-mute);text-transform:uppercase;
  letter-spacing:.05em;margin-bottom:4px}
.bartrack{height:12px;border-radius:999px;background:rgba(6,9,20,.7);border:1px solid var(--line-soft);overflow:hidden}
.bar{height:100%;border-radius:999px;transition:width .5s}

/* quests / goals */
.quests{display:flex;flex-direction:column;gap:9px}
.quest{display:flex;align-items:flex-start;gap:10px;background:rgba(6,9,20,.4);border:1px solid var(--line-soft);
  border-radius:8px;padding:10px 13px;font-size:14px;cursor:pointer;transition:border-color .18s}
.quest:hover{border-color:var(--gold-deep)}
.quest .hz,.quest .qd{flex:none;margin-top:1px}
.quest .qtext{flex:1;min-width:0;line-height:1.45;color:var(--parch-dim);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.quest.open .qtext{-webkit-line-clamp:unset;overflow:visible}
.hz{font-family:var(--f-mono);font-size:10px;text-transform:uppercase;letter-spacing:.06em;
  padding:3px 8px;border-radius:5px;border:1px solid}
.hz.long{color:var(--vermilion-glow);border-color:rgba(214,59,42,.4);background:rgba(143,35,24,.12)}
.hz.medium{color:var(--peacock-bright);border-color:rgba(46,163,160,.4);background:rgba(18,77,76,.18)}
.hz.short{color:var(--gold-bright);border-color:var(--gold-deep);background:rgba(231,182,75,.08)}
.hz.adhoc{color:var(--parch-mute);border-color:var(--line-gold);background:rgba(6,9,20,.4)}

/* achievements */
.badges{display:flex;flex-wrap:wrap;gap:10px}
.badge{display:flex;align-items:center;gap:10px;background:rgba(6,9,20,.4);border:1px solid var(--line-soft);
  border-radius:11px;padding:9px 13px;min-width:150px}
.badge .bico{display:grid;place-items:center;width:34px;height:34px;flex:none;border-radius:9px;
  color:var(--gold-bright);background:rgba(231,182,75,.08);border:1px solid var(--gold-deep)}
.badge .bico .ic{color:var(--gold-bright)}
.badge b{display:block;font-size:13px;font-family:var(--f-title);color:var(--parch)}.badge .muted{font-size:11px;font-family:var(--f-mono)}

/* ai gap */
.agrow{display:flex;gap:22px;align-items:flex-end;margin-bottom:12px}
.agstat b{display:block;font-family:var(--f-display);font-weight:700;font-size:28px;color:var(--gold-bright);line-height:1}
.agstat span{color:var(--parch-mute);font-size:10px;text-transform:uppercase;letter-spacing:.05em;font-family:var(--f-mono)}
.agstat.gap b{color:var(--peacock-bright)}
.trend{display:flex;align-items:flex-end;gap:5px;height:56px;padding:4px 0;border-bottom:1px solid var(--line-soft)}
.tbar{flex:1;min-width:6px;border-radius:4px 4px 0 0;background:linear-gradient(180deg,var(--gold-bright),var(--gold-deep))}
.agnote{align-self:center;font-size:13px}

/* chronicle */
.chron td{padding:8px;border-bottom:1px solid var(--line-soft);font-size:12px;font-family:var(--f-mono);color:var(--parch-dim)}
.chron .xp{color:var(--gold-bright);text-align:right;font-family:var(--f-mono)}

.foot{text-align:center;color:var(--parch-mute);font-family:var(--f-mono);font-size:11px;letter-spacing:.06em;margin-top:8px}

/* mobile: keep the wide skill-map table inside its card (scroll there, never the page),
   and let the XP-bar readout shrink so it never overflows the hero */
@media(max-width:560px){
  .b-map,.card:has(.heat){overflow-x:auto}
  .heat{min-width:340px}
  .xptext{font-size:10px}
  .charmid{min-width:0;width:100%}
  .hero{padding:18px}
  /* never let a card or its rows push past the viewport (verification #55: +42px overflow) */
  .card{max-width:100%;min-width:0}
  .cal-facts{gap:16px}
  .cal-fact,.badge,.pill,.quest,.quest .qtext{min-width:0}
  .cal-fact{flex:1 1 auto}
}

/* polish */
.lvlnum,.xptext,.agstat b,.chron .xp,.chip,.num{font-variant-numeric:tabular-nums}
::selection{background:var(--gold);color:var(--ink)}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:var(--stone-warm);border-radius:999px;border:2px solid var(--void)}
::-webkit-scrollbar-thumb:hover{background:var(--gold-deep)}
*:focus-visible{outline:2px solid var(--gold-bright);outline-offset:2px;border-radius:3px}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""
