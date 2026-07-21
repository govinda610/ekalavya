"""The local web dashboard — a game-styled progress screen.

Dark, RPG/adventure aesthetic (level, XP bar, skill map, quests, achievements),
grounded in dark-UI research: soft-dark surfaces, a small set of desaturated
accents, elevation over decoration, readable categorical chart colors, and —
crucially — a prescriptive "what to do next" quest rather than raw numbers.

`render` is a pure function of the overview dict, so it's easy to test.
"""

from __future__ import annotations

from . import report

LEVEL_COLOR = {
    "unknown": "#3a4658",
    "gap": "#ff6b6b",
    "familiar": "#ffcf6b",
    "strong": "#5ef2b8",
}
AXIS_COLOR = {
    "syntax_recall": "#57d3ff",
    "debugging": "#ffcf6b",
    "code_reading": "#5ef2b8",
    "api_memory": "#b48cff",
    "decomposition": "#ff7ab6",
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
        quest = f"Sharpen <b>{weakest[0]} · {weakest[1].replace('_', ' ')}</b> — your weakest skill."
    else:
        quest = "Run <code>eklavya onboard</code> to map your skills, then your quests appear here."
    due_line = (f"<span class='due'>⚡ {ov['due']} review(s) due</span>" if ov.get("due") else
                "<span class='muted'>no reviews due — learn something new</span>")

    # skill map
    axis_head = "".join(f'<th class="ax">{a.replace("_", " ")}</th>' for a in axes)
    if g["pillars"]:
        rows = "".join(
            f"<tr><th class='pillar'>{p}</th>" + "".join(_cell(cells.get(a)) for a in axes) + "</tr>"
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
        f'<span class="hz {x["horizon"]}">{x["horizon"]}</span>'
        f'<span class="qtext">{x["text"]}</span>'
        + (f'<span class="muted qd">· {x["deadline"]}</span>' if x.get("deadline") else "") + "</div>"
        for x in ov["goals"]
    ) or '<span class="muted">No quests yet.</span>'

    sessions = "".join(
        f'<tr><td>{(x["started_at"] or "")[:16]}</td><td>{x["mode"] or "practice"}</td>'
        f'<td>{x["planned_min"] or ""} min</td><td class="xp">+{x["xp"] or 0} XP</td></tr>'
        for x in ov["sessions"]
    ) or '<tr><td colspan="4" class="muted">No sessions yet.</td></tr>'

    badges = _achievements(s, strong, len(ov["sessions"]))

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ekalavya</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{_CSS}</style></head><body><div class="wrap">

  <header class="hero">
    <div class="brand">
      <div class="logo">🏹 <span class="g">EKALAVYA</span></div>
      <div class="creed">स्वाध्याय · साधना · सिद्धि</div>
    </div>
    <div class="char">
      <div class="lvl"><div class="lvlnum">{level}</div><div class="lvllabel">LEVEL</div></div>
      <div class="charmid">
        <div class="rank">{rank}</div>
        <div class="xpbar"><div class="xpfill" style="width:{into}%"></div>
          <span class="xptext">{into} / 100 XP to next level</span></div>
        <div class="chips"><span class="chip flame">🔥 {streak} day streak</span>
          <span class="chip">✦ {xp} total XP</span></div>
      </div>
    </div>
  </header>

  <section class="quest-banner">
    <div class="qtitle">{_icon("sword")} TODAY'S QUEST</div>
    <div class="qbody">{quest}</div>
    <div class="qmeta">{due_line}</div>
  </section>

  <div class="bento">
    <section class="card b-map">
      <h2>{_icon("grid")} Skill map</h2>
      <table class="heat"><tr><th class="pillar"></th>{axis_head}</tr>{rows}</table>
      <div class="legend">
        <span><i style="background:#3a4658"></i>unknown</span>
        <span><i style="background:#ff6b6b"></i>gap</span>
        <span><i style="background:#ffcf6b"></i>familiar</span>
        <span><i style="background:#5ef2b8"></i>strong</span>
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


_CSS = """
:root{
  --bg:#080b11; --bg2:#0d1420; --panel:#111a28; --panel2:#0e1622; --line:#1d2a3c;
  --ink:#d6e2f0; --dim:#7d8da5; --faint:#4a5768;
  --acc:#5ef2b8; --cyan:#57d3ff; --violet:#b48cff; --amber:#ffcf6b; --pink:#ff7ab6; --red:#ff5c7a;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --disp:'Rajdhani',var(--mono); --sans:'Inter',system-ui,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;font-family:var(--sans);color:var(--ink);
  background:
    radial-gradient(1100px 620px at 82% -12%,#152740 0%,transparent 60%),
    radial-gradient(900px 520px at 0% 108%,#171033 0%,transparent 55%),
    var(--bg);
  padding:26px 20px 60px;min-height:100vh}
.wrap{max-width:1080px;margin:0 auto;display:flex;flex-direction:column;gap:18px}
.g{background:linear-gradient(100deg,var(--acc),var(--cyan) 60%,var(--violet));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.muted{color:var(--dim)} code{font-family:var(--mono);color:var(--acc);background:#0c1622;
  padding:1px 6px;border-radius:5px;border:1px solid var(--line)}
h2{font-family:var(--mono);font-size:11px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--dim);margin:0 0 14px;font-weight:500;display:flex;align-items:center;gap:8px}
.ic{flex:none;opacity:.85}
h2 .ic{width:15px;height:15px}

/* hero / character */
.hero{display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap;
  background:linear-gradient(120deg,var(--panel),var(--panel2));border:1px solid var(--line);
  border-radius:18px;padding:20px 24px;box-shadow:0 20px 60px -30px #000}
.logo{font-family:var(--disp);font-size:30px;font-weight:700;letter-spacing:.14em}
.creed{font-family:var(--mono);color:var(--cyan);font-size:13px;letter-spacing:.1em;margin-top:2px}
.char{display:flex;align-items:center;gap:18px}
.lvl{width:78px;height:78px;border-radius:50%;display:grid;place-items:center;text-align:center;
  background:radial-gradient(circle at 50% 30%,#12324a,#0b1420);
  border:2px solid var(--acc);box-shadow:0 0 26px -4px var(--acc),0 0 0 4px #0b142055}
.lvlnum{font-family:var(--disp);font-size:30px;font-weight:700;line-height:1;color:#eafff6}
.lvllabel{font-family:var(--mono);font-size:9px;letter-spacing:.2em;color:var(--dim)}
.charmid{min-width:260px}
.rank{font-family:var(--disp);font-size:20px;font-weight:600;letter-spacing:.1em;color:var(--amber)}
.xpbar{position:relative;height:20px;border-radius:999px;background:#0b1420;border:1px solid var(--line);
  margin:7px 0;overflow:hidden}
.xpfill{height:100%;background:linear-gradient(90deg,var(--acc),var(--cyan));
  box-shadow:0 0 16px var(--acc)}
.xptext{position:absolute;inset:0;display:grid;place-items:center;font-family:var(--mono);
  font-size:11px;color:#dff}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{font-family:var(--mono);font-size:12px;color:var(--dim);background:#0c1622;
  border:1px solid var(--line);border-radius:999px;padding:4px 11px}
.chip.flame{color:var(--amber);border-color:#3d3116}

/* today's quest */
.quest-banner{background:linear-gradient(100deg,#13233a,#0e1622);border:1px solid #244;
  border-left:3px solid var(--acc);border-radius:14px;padding:16px 22px;
  box-shadow:0 0 40px -20px var(--acc)}
.qtitle{font-family:var(--disp);letter-spacing:.2em;color:var(--acc);font-size:13px;font-weight:700;
  display:flex;align-items:center;gap:8px}
.qtitle .ic{width:16px;height:16px;opacity:1}
.qbody{font-size:17px;margin:4px 0 6px}
.qmeta .due{color:var(--amber);font-family:var(--mono);font-size:13px}

/* cards */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
@media(max-width:820px){.grid2{grid-template-columns:1fr}.char{width:100%}}

/* bento — asymmetric, skill map is the hero */
.bento{display:grid;gap:18px;grid-template-columns:repeat(6,1fr);align-items:start;
  grid-template-areas:
    "map map map map axes axes"
    "quests quests gap gap gap gap"
    "ach ach ach ach chron chron";}
.b-map{grid-area:map}
.b-axes{grid-area:axes}
.b-quests{grid-area:quests}
.b-gap{grid-area:gap}
.b-ach{grid-area:ach}
.b-chron{grid-area:chron}
.bento .card{margin:0}
@media(max-width:820px){
  .bento{grid-template-columns:1fr;
    grid-template-areas:"map" "axes" "quests" "gap" "ach" "chron";}
}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
  border-radius:16px;padding:18px 20px;box-shadow:0 1px 0 #ffffff0d inset,0 18px 50px -34px #000;
  transition:transform .22s cubic-bezier(.22,.61,.36,1),border-color .22s,box-shadow .22s}
.card:hover{transform:translateY(-2px);border-color:#2a3a52;
  box-shadow:0 1px 0 #ffffff14 inset,0 22px 54px -30px #000c}

/* skill map */
table{width:100%;border-collapse:separate;border-spacing:5px}
.heat th.ax{color:var(--dim);font-family:var(--mono);font-weight:400;text-align:center;
  font-size:10px;text-transform:uppercase;letter-spacing:.06em;padding-bottom:4px}
.heat th.pillar{text-align:left;color:#eaf2fb;white-space:nowrap;font-size:13px;font-weight:600;padding-right:8px}
.cell{text-align:center;border:1px solid var(--line);border-radius:8px;padding:9px 6px;font-size:10.5px;
  font-family:var(--mono);text-transform:uppercase;letter-spacing:.04em;transition:transform .1s}
.cell:hover{transform:translateY(-1px)}
.cell.empty{border-style:dashed;border-color:#1a2534}.cell.empty::after{content:"·";color:#2b3a4d}
.legend{display:flex;gap:16px;margin-top:12px;font-family:var(--mono);font-size:11px;color:var(--dim)}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:middle}

/* axis bars */
.bars{display:flex;flex-direction:column;gap:13px;margin-top:4px}
.barlabel{font-family:var(--mono);font-size:11px;color:var(--dim);text-transform:uppercase;
  letter-spacing:.06em;margin-bottom:4px}
.bartrack{height:12px;border-radius:999px;background:#0b1420;border:1px solid var(--line);overflow:hidden}
.bar{height:100%;border-radius:999px;transition:width .5s}

/* quests / goals — long text is clamped to 2 lines and expands on click */
.quests{display:flex;flex-direction:column;gap:9px}
.quest{display:flex;align-items:flex-start;gap:10px;background:#0c1622;border:1px solid var(--line);
  border-radius:10px;padding:10px 13px;font-size:14px;cursor:pointer}
.quest:hover{border-color:#2a3a52}
.quest .hz,.quest .qd{flex:none;margin-top:1px}
.quest .qtext{flex:1;min-width:0;line-height:1.45;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.quest.open .qtext{-webkit-line-clamp:unset;overflow:visible}
.hz{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.08em;
  padding:2px 8px;border-radius:5px;border:1px solid}
.hz.long{color:var(--violet);border-color:#3a2c55;background:#160f22}
.hz.medium{color:var(--cyan);border-color:#1c3a48;background:#0a1a22}
.hz.short{color:var(--acc);border-color:#1c3d30;background:#0a1a14}
.hz.adhoc{color:var(--amber);border-color:#3d3116;background:#1a1408}

/* achievements */
.badges{display:flex;flex-wrap:wrap;gap:10px}
.badge{display:flex;align-items:center;gap:10px;background:#0c1622;border:1px solid #24344a;
  border-radius:12px;padding:9px 13px;min-width:150px}
.badge .bico{display:grid;place-items:center;width:34px;height:34px;flex:none;border-radius:9px;
  color:var(--acc);background:#0a1a14;border:1px solid #1c3d30}
.badge .bico .ic{opacity:1}
.badge b{display:block;font-size:13px}.badge .muted{font-size:11px}

/* ai gap */
.agrow{display:flex;gap:22px;align-items:flex-end;margin-bottom:12px}
.agstat b{display:block;font-family:var(--disp);font-size:30px;color:var(--acc);line-height:1}
.agstat span{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.agstat.gap b{color:var(--amber)}
.trend{display:flex;align-items:flex-end;gap:5px;height:56px;padding:4px 0;border-bottom:1px solid var(--line)}
.tbar{flex:1;min-width:6px;border-radius:4px 4px 0 0;background:linear-gradient(180deg,var(--acc),#2f7d5e);
  box-shadow:0 0 8px var(--acc)44}
.agnote{align-self:center;font-size:13px}

/* chronicle */
.chron td{padding:7px 8px;border-bottom:1px solid var(--line);font-size:13px}
.chron .xp{color:var(--acc);text-align:right;font-family:var(--mono)}

.foot{text-align:center;color:var(--faint);font-family:var(--mono);font-size:12px;margin-top:8px}

/* polish: tabular numerals, styled scrollbars, selection, reduced-motion */
.lvlnum,.xptext,.agstat b,.chron .xp,.chip,.num{font-variant-numeric:tabular-nums}
::selection{background:#5ef2b855;color:#04120c}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#1f2c3e;border-radius:999px;border:2px solid var(--bg)}
::-webkit-scrollbar-thumb:hover{background:#2a3a52}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""
