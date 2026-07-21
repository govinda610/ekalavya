"""The "My Profile" page — what Ekalavya has saved about the learner.

Shows the full profile.md (viewable and editable), the exact active goals with
their deadlines, and the mastery map. A plain page like the dashboard/journey,
loaded in an iframe by the web UI. Editing writes straight back to profile.md.
"""

from __future__ import annotations

import html

from . import config, report
from .dashboard import _CSS, _cell, _icon


def read_profile() -> str:
    try:
        return config.PROFILE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def write_profile(text: str) -> None:
    config.PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.PROFILE_PATH.write_text(text, encoding="utf-8")


def render() -> str:
    profile = read_profile()
    ov = report.overview()
    goals, grid = ov["goals"], ov["grid"]

    # mastery map (reuses the dashboard's coloured cells)
    axes = grid["axes"]
    axis_head = "".join(f'<th class="ax">{a.replace("_", " ")}</th>' for a in axes)
    if grid["pillars"]:
        rows = "".join(
            f"<tr><th class='pillar'>{html.escape(p)}</th>"
            + "".join(_cell(cells.get(a)) for a in axes) + "</tr>"
            for p, cells in grid["pillars"].items()
        )
    else:
        rows = f'<tr><td colspan="{len(axes) + 1}" class="muted">No skills yet — run onboarding.</td></tr>'

    # goals with deadlines
    if goals:
        goal_html = "".join(
            f'<div class="quest"><span class="hz {g["horizon"]}">{g["horizon"]}</span>'
            f'<span>{html.escape(g["text"])}</span>'
            + (f'<span class="muted">· {html.escape(g["deadline"])}</span>' if g.get("deadline") else "")
            + "</div>"
            for g in goals
        )
    else:
        goal_html = '<span class="muted">No goals yet — set some during onboarding or ask Ekalavya.</span>'

    raw = html.escape(profile)  # embedded in a <textarea>; .value recovers the original

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>My Profile</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<style>{_CSS}{_PCSS}</style></head><body><div class="wrap">
  <header class="hero"><div class="brand"><div class="logo">🏹 <span class="g">MY PROFILE</span></div>
    <div class="creed">what Ekalavya knows about you</div></div></header>

  <section class="card">
    <h2>{_icon("user")} Your profile
      <span class="grow"></span>
      <button id="pedbtn" class="pbtn" onclick="editProfile()">{_icon("pencil", 13)} Edit</button>
      <button id="psave" class="pbtn ok hidden" onclick="saveProfile()">Save</button>
      <button id="pcancel" class="pbtn hidden" onclick="cancelProfile()">Cancel</button>
    </h2>
    <div id="pview" class="prose"></div>
    <textarea id="pedit" class="hidden" spellcheck="false">{raw}</textarea>
    <div id="psaved" class="saved hidden">saved ✓</div>
  </section>

  <div class="grid2">
    <section class="card"><h2>{_icon("target")} Goals</h2><div class="quests">{goal_html}</div></section>
    <section class="card"><h2>{_icon("grid")} Mastery map</h2>
      <table class="heat"><tr><th class="pillar"></th>{axis_head}</tr>{rows}</table>
      <div class="legend">
        <span><i style="background:#3a4658"></i>unknown</span>
        <span><i style="background:#ff6b6b"></i>gap</span>
        <span><i style="background:#ffcf6b"></i>familiar</span>
        <span><i style="background:#5ef2b8"></i>strong</span>
      </div>
    </section>
  </div>
</div>
<script>
const ta=document.getElementById('pedit'), view=document.getElementById('pview');
function paint(){{
  const md=ta.value.trim();
  view.innerHTML = md ? DOMPurify.sanitize(marked.parse(md))
    : '<span class="muted">No profile yet. Click Edit to write one, or finish onboarding and Ekalavya fills it in.</span>';
}}
paint();
function editProfile(){{
  view.classList.add('hidden'); ta.classList.remove('hidden');
  document.getElementById('pedbtn').classList.add('hidden');
  document.getElementById('psave').classList.remove('hidden');
  document.getElementById('pcancel').classList.remove('hidden');
  ta.focus();
}}
function stopEdit(){{
  ta.classList.add('hidden'); view.classList.remove('hidden');
  document.getElementById('pedbtn').classList.remove('hidden');
  document.getElementById('psave').classList.add('hidden');
  document.getElementById('pcancel').classList.add('hidden');
}}
function cancelProfile(){{ location.reload(); }}
async function saveProfile(){{
  try{{
    await fetch('/api/profile',{{method:'PUT',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{text:ta.value}})}});
    paint(); stopEdit();
    const s=document.getElementById('psaved'); s.classList.remove('hidden');
    setTimeout(()=>s.classList.add('hidden'),1800);
  }}catch(e){{ alert('Could not save your profile.'); }}
}}
</script>
</body></html>"""


_PCSS = """
h2 .grow{flex:1}
.pbtn{font-family:var(--mono);font-size:12px;color:var(--dim);background:#0c1622;border:1px solid var(--line);
  border-radius:8px;padding:5px 11px;cursor:pointer;display:inline-flex;align-items:center;gap:5px;text-transform:none;letter-spacing:0}
.pbtn:hover{color:var(--acc);border-color:#1c3d30}
.pbtn.ok{color:var(--acc);border-color:#1c3d30}
.prose{font-size:14.5px;line-height:1.6}
.prose h1,.prose h2,.prose h3{font-family:var(--disp);letter-spacing:.02em;text-transform:none;color:var(--ink);
  margin:14px 0 6px;font-size:16px;font-weight:600}
.prose ul,.prose ol{margin:6px 0;padding-left:20px}.prose li{margin:3px 0}
.prose p{margin:7px 0}.prose strong{color:#eaf2fb}
.prose code{font-family:var(--mono);font-size:13px}
#pedit{width:100%;min-height:340px;background:#0a1018;color:var(--ink);border:1px solid var(--line);
  border-radius:12px;padding:14px 16px;font-family:var(--mono);font-size:13px;line-height:1.6;resize:vertical}
.hidden{display:none!important}
.saved{color:var(--acc);font-family:var(--mono);font-size:12px;margin-top:8px}
"""
