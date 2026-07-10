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
    if stats["streak"] >= 3: earned.append(("🔥", "On Fire", "3-day streak"))
    if stats["streak"] >= 7: earned.append(("🗓️", "Week Warrior", "7-day streak"))
    if stats["streak"] >= 30: earned.append(("♾️", "Unbroken", "30-day streak"))
    if stats["level"] >= 5: earned.append(("⭐", "Adept", "reached level 5"))
    if stats["level"] >= 10: earned.append(("👑", "Master", "reached level 10"))
    if strong >= 1: earned.append(("💎", "First Mastery", "a skill hit strong"))
    if strong >= 5: earned.append(("🗡️", "Sharpened", "5 skills at strong"))
    if sessions >= 1: earned.append(("🏹", "Initiate", "completed a session"))
    if sessions >= 10: earned.append(("📿", "Devoted", "10 sessions"))
    if not earned:
        return '<span class="muted">No badges yet — your first session earns one.</span>'
    return "".join(
        f'<div class="badge"><div class="bico">{i}</div><div><b>{t}</b>'
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

    goals = "".join(
        f'<div class="quest"><span class="hz {x["horizon"]}">{x["horizon"]}</span>'
        f'<span>{x["text"]}</span>'
        + (f'<span class="muted">· {x["deadline"]}</span>' if x.get("deadline") else "") + "</div>"
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
    <div class="qtitle">⚔ TODAY'S QUEST</div>
    <div class="qbody">{quest}</div>
    <div class="qmeta">{due_line}</div>
  </section>

  <div class="grid2">
    <section class="card">
      <h2>◈ Skill map</h2>
      <table class="heat"><tr><th class="pillar"></th>{axis_head}</tr>{rows}</table>
      <div class="legend">
        <span><i style="background:#3a4658"></i>unknown</span>
        <span><i style="background:#ff6b6b"></i>gap</span>
        <span><i style="background:#ffcf6b"></i>familiar</span>
        <span><i style="background:#5ef2b8"></i>strong</span>
      </div>
    </section>
    <section class="card">
      <h2>▲ Skill axes</h2>
      <div class="bars">{bars}</div>
    </section>
  </div>

  <section class="card">
    <h2>✦ Active quests</h2>
    <div class="quests">{goals}</div>
  </section>

  <div class="grid2">
    <section class="card">
      <h2>🏅 Achievements</h2>
      <div class="badges">{badges}</div>
    </section>
    <section class="card">
      <h2>📜 Chronicle</h2>
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
h2{font-family:var(--disp);font-size:15px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--acc);margin:0 0 14px;font-weight:700}

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
.qtitle{font-family:var(--disp);letter-spacing:.2em;color:var(--acc);font-size:13px;font-weight:700}
.qbody{font-size:17px;margin:4px 0 6px}
.qmeta .due{color:var(--amber);font-family:var(--mono);font-size:13px}

/* cards */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:820px){.grid2{grid-template-columns:1fr}.char{width:100%}}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
  border-radius:16px;padding:18px 20px;box-shadow:0 18px 50px -34px #000}

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

/* quests / goals */
.quests{display:flex;flex-direction:column;gap:9px}
.quest{display:flex;align-items:center;gap:10px;background:#0c1622;border:1px solid var(--line);
  border-radius:10px;padding:10px 13px;font-size:14px}
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
.badge .bico{font-size:22px;filter:drop-shadow(0 0 8px #0008)}
.badge b{display:block;font-size:13px}.badge .muted{font-size:11px}

/* chronicle */
.chron td{padding:7px 8px;border-bottom:1px solid var(--line);font-size:13px}
.chron .xp{color:var(--acc);text-align:right;font-family:var(--mono)}

.foot{text-align:center;color:var(--faint);font-family:var(--mono);font-size:12px;margin-top:8px}
"""
