"""The "My Profile" page — what Ekalavya has saved about the learner.

Shows the full profile.md (viewable and editable), the exact active goals with
their deadlines, and the mastery map. A plain page like the dashboard/journey,
loaded in an iframe by the web UI. Editing writes straight back to profile.md.
"""

from __future__ import annotations

import html

from . import config, report
from .dashboard import _BOW, _CSS, _cell, _icon


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
            f'<div class="quest" onclick="this.classList.toggle(\'open\')" title="click to expand">'
            f'<span class="hz {g["horizon"]}">{g["horizon"]}</span>'
            f'<span class="qtext">{html.escape(g["text"])}</span>'
            + (f'<span class="muted qd">· {html.escape(g["deadline"])}</span>' if g.get("deadline") else "")
            + "</div>"
            for g in goals
        )
    else:
        goal_html = '<span class="muted">No goals yet — set some during onboarding or ask Ekalavya.</span>'

    raw = html.escape(profile)  # embedded in a <textarea>; .value recovers the original

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>My Profile</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700;800;900&family=Marcellus&family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Spectral:ital,wght@0,300;0,400;0,500;0,600;1,400&family=Tiro+Devanagari+Hindi:ital@0;1&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<style>{_CSS}{_PCSS}</style></head><body><div class="wrap">
  <header class="hero"><div class="brand"><div class="logo"><span class="bowmark">{_BOW}</span> <span class="g">MY PROFILE</span></div>
    <div class="creed" style="font-family:var(--f-serif);font-style:italic">what Ekalavya knows about you</div></div></header>

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
        <span><i style="background:#a89670"></i>unknown</span>
        <span><i style="background:#ff5a3c"></i>gap</span>
        <span><i style="background:#57d3ce"></i>familiar</span>
        <span><i style="background:#e7b64b"></i>strong</span>
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
.pbtn{font-family:var(--f-mono);font-size:12px;color:var(--parch-dim);background:rgba(6,9,20,.5);border:1px solid var(--line-soft);
  border-radius:6px;padding:6px 12px;cursor:pointer;display:inline-flex;align-items:center;gap:5px;text-transform:none;letter-spacing:0}
.pbtn:hover{color:var(--gold-bright);border-color:var(--gold-deep)}
.pbtn.ok{color:var(--gold-bright);border-color:var(--gold-deep)}
.prose{font-size:15px;line-height:1.65}
.prose h1,.prose h2,.prose h3{font-family:var(--f-display);letter-spacing:.01em;text-transform:none;color:var(--parch);
  margin:16px 0 6px;font-size:18px;font-weight:700}
.prose ul,.prose ol{margin:8px 0;padding-left:20px;color:var(--parch-dim)}.prose li{margin:4px 0}
.prose p{margin:8px 0;color:var(--parch-dim)}.prose strong{color:var(--parch)}
.prose code{font-family:var(--f-mono);font-size:13px}
#pedit{width:100%;min-height:340px;background:rgba(6,9,16,.85);color:var(--peacock-bright);border:1px solid var(--line-gold);
  border-radius:10px;padding:14px 16px;font-family:var(--f-mono);font-size:13px;line-height:1.7;resize:vertical}
.hidden{display:none!important}
.saved{color:var(--gold-bright);font-family:var(--f-mono);font-size:12px;margin-top:8px}
"""
