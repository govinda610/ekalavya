"""The local web dashboard — a read-only view of progress.

Server-rendered HTML (no JS framework needed). `render` is pure and testable;
`create_app` wires it to FastAPI.
"""

from __future__ import annotations

from . import report

LEVEL_COLOR = {
    "unknown": "#3a4658",
    "gap": "#ff6b6b",
    "familiar": "#ffcf6b",
    "strong": "#5ef2b8",
}


def _cell(cell: dict | None) -> str:
    if not cell:
        return '<td class="cell empty"></td>'
    color = LEVEL_COLOR.get(cell["level"], "#3a4658")
    return (
        f'<td class="cell" style="color:{color};border-color:{color}66;'
        f'background:{color}1a" title="rating {cell["rating"]}">{cell["level"]}</td>'
    )


def render(ov: dict) -> str:
    s = ov["stats"]
    g = ov["grid"]
    axes = g["axes"]

    axis_head = "".join(f'<th class="ax">{a.replace("_", " ")}</th>' for a in axes)
    if g["pillars"]:
        rows = ""
        for pillar, cells in g["pillars"].items():
            tds = "".join(_cell(cells.get(a)) for a in axes)
            rows += f"<tr><th class='pillar'>{pillar}</th>{tds}</tr>"
    else:
        rows = f'<tr><td colspan="{len(axes) + 1}" class="muted">No ratings yet — run <code>eklavya onboard</code>.</td></tr>'

    goals = "".join(
        f'<li><span class="hz">{x["horizon"]}</span> {x["text"]}'
        + (f' <span class="muted">· {x["deadline"]}</span>' if x.get("deadline") else "")
        + "</li>"
        for x in ov["goals"]
    ) or '<li class="muted">No goals yet.</li>'

    sessions = "".join(
        f'<tr><td>{(x["started_at"] or "")[:16]}</td><td>{x["planned_min"] or ""} min</td>'
        f'<td>{x["xp"] or 0} XP</td><td>{x["mode"] or ""}</td></tr>'
        for x in ov["sessions"]
    ) or '<tr><td colspan="4" class="muted">No sessions yet.</td></tr>'

    return _PAGE.format(
        streak=s["streak"], level=s["level"], xp=s["xp"],
        axis_head=axis_head, rows=rows, goals=goals, sessions=sessions,
    )


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


_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Ekalavya</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root{{--bg:#0a0e14;--panel:#121a26;--line:#1e2a3a;--ink:#c9d6e4;--dim:#7c8ba1;--acc:#5ef2b8;--cyan:#57d3ff}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:radial-gradient(1000px 600px at 80% -10%,#122033,#0a0e14 55%);
    color:var(--ink);font-family:ui-monospace,'SF Mono',Menlo,monospace;padding:32px}}
  .wrap{{max-width:1000px;margin:0 auto}}
  h1{{margin:0;font-size:26px}} h1 .g{{color:var(--acc)}}
  .creed{{color:var(--cyan);font-size:13px;letter-spacing:.12em;margin:2px 0 22px}}
  .stats{{display:flex;gap:14px;margin-bottom:26px}}
  .stat{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 20px;flex:1}}
  .stat b{{display:block;font-size:26px;color:var(--acc)}} .stat span{{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.1em}}
  h2{{font-size:14px;color:var(--acc);text-transform:uppercase;letter-spacing:.12em;margin:26px 0 10px}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  .heat th.ax{{color:var(--dim);font-weight:400;text-align:center;padding:6px;font-size:11px}}
  .heat th.pillar{{text-align:left;padding:8px 10px;color:#eaf2fb;white-space:nowrap}}
  .cell{{text-align:center;border:1px solid var(--line);border-radius:6px;padding:8px 6px;font-size:11px}}
  .cell.empty{{color:#2a3547}} .cell.empty::after{{content:"·"}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:16px}}
  ul{{list-style:none;padding:0;margin:0}} li{{padding:6px 0;border-bottom:1px dashed var(--line)}}
  .hz{{color:var(--cyan);font-size:11px;text-transform:uppercase;margin-right:6px}}
  .sess td{{padding:6px 8px;border-bottom:1px solid var(--line)}}
  .muted{{color:var(--dim)}} code{{color:var(--acc)}}
  .legend{{display:flex;gap:14px;margin-top:10px;font-size:11px;color:var(--dim)}}
  .dot{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:middle}}
</style></head><body><div class="wrap">
  <h1>🏹 <span class="g">Ekalavya</span></h1>
  <div class="creed">स्वाध्याय · साधना · सिद्धि</div>
  <div class="stats">
    <div class="stat"><b>🔥 {streak}</b><span>day streak</span></div>
    <div class="stat"><b>⭐ {level}</b><span>level</span></div>
    <div class="stat"><b>{xp}</b><span>total xp</span></div>
  </div>

  <h2>Mastery map</h2>
  <div class="card">
    <table class="heat"><tr><th class="pillar"></th>{axis_head}</tr>{rows}</table>
    <div class="legend">
      <span><span class="dot" style="background:#3a4658"></span>unknown</span>
      <span><span class="dot" style="background:#ff6b6b"></span>gap</span>
      <span><span class="dot" style="background:#ffcf6b"></span>familiar</span>
      <span><span class="dot" style="background:#5ef2b8"></span>strong</span>
    </div>
  </div>

  <h2>Goals</h2>
  <div class="card"><ul>{goals}</ul></div>

  <h2>Recent sessions</h2>
  <div class="card"><table class="sess">{sessions}</table></div>
</div></body></html>"""
