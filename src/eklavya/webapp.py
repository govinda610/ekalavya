"""The full browser UI — for people who don't live in a terminal.

Folds the dashboard in and adds the whole practice experience: a streaming chat, a
real in-browser code editor (Monaco), and rendered visuals (Mermaid diagrams,
highlighted code). It reuses the exact same agent + tools + verified grading as
the TUI, so state stays in one place.

Backend is a thin FastAPI layer; the agent streams tokens over a POST stream.
"""

import json
import uuid

from . import prompts, report

_PROMPTS = {"practice": prompts.SESSION, "mock": prompts.MOCK,
            "aiinterview": prompts.AI_INTERVIEW,
            "takehome": prompts.TAKEHOME, "onboard": prompts.ONBOARDING}
_KICKOFF = {
    "practice": "Start today's practice session. I have 30 minutes.",
    "mock": "Start a mock interview. I have 45 minutes.",
    "aiinterview": "Start an AI-assisted mock interview. I have 45 minutes.",
    "takehome": "Give me a take-home assignment. I have 90 minutes.",
    "onboard": "Begin my first-time onboarding — I'm brand new here.",
}
_MODE_LABEL = {"practice": "Practice session", "mock": "Mock interview",
               "aiinterview": "AI-enabled interview", "takehome": "Take-home",
               "onboard": "Onboarding"}


def create_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, StreamingResponse

    from . import progress
    from .agent import build_agent
    from .dashboard import render as render_dashboard
    from .db import init_db
    from .providers import pick
    from .tools import AIINTERVIEW_TOOLS, ONBOARDING_TOOLS, SESSION_TOOLS
    from .tui import _chunk_text

    init_db()
    provider = pick(None)
    agents: dict = {}  # mode -> agent (one per mode, threads keyed per browser session)
    _TOOLS = {"onboard": ONBOARDING_TOOLS, "aiinterview": AIINTERVIEW_TOOLS}

    def agent_for(mode: str):
        mode = mode if mode in _PROMPTS else "practice"
        if mode not in agents:
            tools = _TOOLS.get(mode, SESSION_TOOLS)
            agents[mode] = build_agent(_PROMPTS[mode], tools, provider=provider.key)
        return agents[mode]

    app = FastAPI(title="Ekalavya", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> str:
        return render_dashboard(report.overview())

    @app.get("/journey", response_class=HTMLResponse)
    def journey() -> str:
        from .journey import render as render_journey

        return render_journey()

    @app.get("/api/overview")
    def overview() -> dict:
        return report.overview()

    @app.get("/api/curriculum")
    def curriculum() -> dict:
        return report.curriculum_mermaid()

    @app.get("/api/config")
    def cfg() -> dict:
        return {"provider": provider.label, "model": provider.default_model,
                "kickoff": _KICKOFF, "configured": provider.is_configured(),
                "first_run": report.is_first_run()}

    @app.post("/api/stream")
    async def stream(request: Request):
        body = await request.json()
        mode = body.get("mode", "practice")
        thread = body.get("thread") or str(uuid.uuid4())
        text = body.get("text", "")
        if mode == "aiinterview":
            from .assist import mark_interview

            mark_interview(thread)  # scope AI-usage grading to this interview
        from .chatstore import touch_chat

        touch_chat(thread, mode=mode)  # persist/refresh this chat in the history
        agent = agent_for(mode)
        config = {"configurable": {"thread_id": thread}}

        def gen():
            from .verify import selfcheck

            buf = []
            try:
                for chunk, _meta in agent.stream(
                    {"messages": [{"role": "user", "content": text}]},
                    config=config, stream_mode="messages",
                ):
                    tok = _chunk_text(chunk)
                    if tok:
                        buf.append(tok)
                        yield json.dumps({"t": tok}) + "\n"
            except Exception as exc:  # surface errors to the UI instead of hanging
                yield json.dumps({"t": f"\n\n_(error: {exc})_"}) + "\n"
            note = selfcheck("".join(buf))  # a second model reviews the reply
            if note:
                yield json.dumps({"t": note}) + "\n"
            try:  # auto-name the chat from the learner's first real message
                from .chatstore import auto_title, get_title, rename_chat

                if get_title(thread) is None:
                    title = auto_title(thread, skip=set(_KICKOFF.values()))
                    if title:
                        rename_chat(thread, title)
            except Exception:
                pass
            yield json.dumps({"done": True}) + "\n"

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.post("/api/assist")
    async def assist(request: Request):
        from starlette.concurrency import run_in_threadpool

        from .assist import respond

        body = await request.json()
        thread = body.get("thread") or ""
        prompt = body.get("text", "")
        reply = await run_in_threadpool(respond, thread, prompt)
        return {"reply": reply}

    @app.get("/api/stats")
    def stats() -> dict:
        return progress.stats()

    @app.post("/api/penalise")
    def penalise() -> dict:
        result = progress.penalise("pasted code in the web editor")
        return {"lost": result["lost"], "stats": progress.stats()}

    @app.post("/api/reclaim")
    def reclaim() -> dict:
        return {"reclaimed": progress.reclaim(), "stats": progress.stats()}

    @app.get("/api/chats")
    def chats_list() -> list:
        from .chatstore import list_chats

        return [{**c, "title": c["title"] or _MODE_LABEL.get(c["mode"], "Chat")}
                for c in list_chats()]

    @app.get("/api/chats/{thread_id}")
    def chat_get(thread_id: str) -> dict:
        from .chatstore import get_chat, transcript

        meta = get_chat(thread_id) or {}
        return {"thread_id": thread_id, "mode": meta.get("mode"),
                "title": meta.get("title") or _MODE_LABEL.get(meta.get("mode"), "Chat"),
                "transcript": transcript(thread_id)}

    @app.patch("/api/chats/{thread_id}")
    async def chat_rename(thread_id: str, request: Request):
        from .chatstore import rename_chat

        body = await request.json()
        rename_chat(thread_id, body.get("title", ""))
        return {"ok": True}

    return app


# --- the single-page front-end ---------------------------------------------

_INDEX = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ekalavya</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css">
<style>
:root{--bg:#080b11;--panel:#111a28;--panel2:#0e1622;--line:#1d2a3c;--ink:#d6e2f0;--dim:#7d8da5;
--acc:#5ef2b8;--cyan:#57d3ff;--violet:#b48cff;--amber:#ffcf6b;--mono:'JetBrains Mono',ui-monospace,monospace;
--disp:'Rajdhani',sans-serif;--sans:'Inter',system-ui,sans-serif}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font-family:var(--sans);color:var(--ink);
background:radial-gradient(1100px 600px at 82% -12%,#152740,transparent 60%),radial-gradient(900px 520px at 0% 108%,#171033,transparent 55%),var(--bg);
display:flex;flex-direction:column;height:100vh;overflow:hidden}
header{display:flex;align-items:center;gap:18px;padding:12px 20px;border-bottom:1px solid var(--line);
background:linear-gradient(120deg,var(--panel),var(--panel2))}
.logo{font-family:var(--disp);font-weight:700;font-size:22px;letter-spacing:.14em}
.logo .g{background:linear-gradient(100deg,var(--acc),var(--cyan) 60%,var(--violet));-webkit-background-clip:text;background-clip:text;color:transparent}
.creed{font-family:var(--mono);color:var(--cyan);font-size:11px;letter-spacing:.1em}
.tabs{display:flex;gap:6px;margin-left:12px}
.tab{font-family:var(--disp);letter-spacing:.1em;text-transform:uppercase;font-size:13px;color:var(--dim);
background:none;border:1px solid transparent;padding:6px 14px;border-radius:9px;cursor:pointer}
.tab.on{color:var(--acc);border-color:var(--line);background:#0c1622}
.spacer{flex:1}.who{font-family:var(--mono);font-size:11px;color:var(--dim)}
main{flex:1;min-height:0}
#practice{display:grid;grid-template-columns:1fr 1fr;height:100%}
@media(max-width:900px){#practice{grid-template-columns:1fr;grid-template-rows:1fr 1fr}}
.col{display:flex;flex-direction:column;min-height:0}
.col.chat{border-right:1px solid var(--line)}
.log{flex:1;overflow-y:auto;padding:18px 20px;display:flex;flex-direction:column;gap:14px}
.msg{max-width:92%;padding:12px 15px;border-radius:14px;line-height:1.55;font-size:14.5px}
.msg.you{align-self:flex-end;background:#0c1f18;border:1px solid #1c3d30}
.msg.ai{align-self:flex-start;background:var(--panel);border:1px solid var(--line)}
.msg.ai .who,.msg.you .who{font-family:var(--disp);letter-spacing:.1em;font-size:11px;color:var(--acc);text-transform:uppercase;margin-bottom:4px}
.msg pre{background:#0a1018 !important;border:1px solid var(--line);border-radius:10px;padding:12px;overflow-x:auto}
.msg code{font-family:var(--mono);font-size:13px}
.msg p{margin:6px 0}.msg h1,.msg h2,.msg h3{font-family:var(--disp);margin:10px 0 4px}
.msg blockquote{border-left:3px solid var(--acc);margin:8px 0;padding:2px 12px;color:var(--dim)}
.mermaid{background:#0a1018;border:1px solid var(--line);border-radius:10px;padding:10px;text-align:center}
.inbar{display:flex;gap:8px;padding:12px;border-top:1px solid var(--line);background:var(--panel2)}
.inbar input{flex:1;background:var(--bg);border:1px solid var(--line);border-radius:10px;color:var(--ink);
padding:11px 13px;font-family:var(--sans);font-size:14px}
button.send{font-family:var(--disp);letter-spacing:.08em;background:linear-gradient(100deg,var(--acc),var(--cyan));
color:#04120c;border:none;border-radius:10px;padding:0 18px;font-weight:700;cursor:pointer}
.edtoolbar{display:flex;gap:8px;align-items:center;padding:9px 12px;border-bottom:1px solid var(--line);background:var(--panel2)}
.edtoolbar select{background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-family:var(--mono);font-size:12px}
.edtoolbar .grow{flex:1}
button.submit{font-family:var(--disp);letter-spacing:.06em;background:#0c1f18;color:var(--acc);border:1px solid #1c3d30;
border-radius:8px;padding:7px 14px;font-weight:600;cursor:pointer}
button.ghost{background:#0c1622;color:var(--dim);border:1px solid var(--line);border-radius:8px;padding:7px 12px;cursor:pointer;font-family:var(--mono);font-size:12px}
#editor{flex:1;min-height:0}
#dash,#journey{display:none;height:100%}#dash iframe,#journey iframe{width:100%;height:100%;border:0;background:var(--bg)}
#tree{display:none;height:100%;overflow:auto;padding:24px}
.treehead{font-family:var(--disp);letter-spacing:.06em;font-size:16px;margin-bottom:14px}
.treehead .g{background:linear-gradient(100deg,var(--acc),var(--cyan) 60%,var(--violet));-webkit-background-clip:text;background-clip:text;color:transparent}
#treediagram{display:flex;justify-content:center}
.hidden{display:none !important}
.dim{color:var(--dim)} .typing:after{content:'▍';color:var(--acc);animation:blink 1s steps(2) infinite}
@keyframes blink{50%{opacity:0}}
/* chats drawer */
#chatsbtn{font-family:var(--disp);letter-spacing:.08em;font-size:12px;color:var(--dim);background:#0c1622;
 border:1px solid var(--line);border-radius:9px;padding:7px 12px;cursor:pointer;margin-left:4px}
#chatsbtn:hover{color:var(--acc);border-color:#1c3d30}
#drawerscrim{position:fixed;inset:0;z-index:110;background:rgba(2,6,12,.55);opacity:0;pointer-events:none;transition:opacity .22s}
#drawerscrim.open{opacity:1;pointer-events:auto}
#drawer{position:fixed;top:0;left:0;bottom:0;width:300px;z-index:120;transform:translateX(-105%);
 transition:transform .22s ease;display:flex;flex-direction:column;
 background:linear-gradient(180deg,var(--panel),var(--panel2));border-right:1px solid var(--line);box-shadow:2px 0 30px #0008}
#drawer.open{transform:translateX(0)}
.drawerhead{display:flex;align-items:center;gap:10px;padding:14px;border-bottom:1px solid var(--line)}
.drawerhead .t{font-family:var(--disp);letter-spacing:.12em;font-size:14px;color:var(--acc);text-transform:uppercase}
.drawerhead .x{margin-left:auto;background:none;border:none;color:var(--dim);cursor:pointer;font-size:18px}
.newchat{margin:10px 12px 6px;font-family:var(--disp);letter-spacing:.06em;background:#0c1f18;color:var(--acc);
 border:1px solid #1c3d30;border-radius:9px;padding:9px 12px;cursor:pointer;text-align:left}
.newchat:hover{background:#0f2a20}
.chatlist{flex:1;overflow-y:auto;padding:6px 8px}
.chatitem{display:flex;align-items:center;gap:8px;padding:9px 11px;border-radius:9px;cursor:pointer;border:1px solid transparent}
.chatitem:hover{background:#0c1622;border-color:var(--line)}
.chatitem.active{background:#0c1622;border-color:#1c3d30}
.chatitem .ci{flex:1;min-width:0}
.chatitem .ct{font-size:13px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chatitem .cm{font-family:var(--mono);font-size:10px;color:var(--dim);margin-top:2px}
.chatitem .cedit{opacity:0;color:var(--dim);background:none;border:none;cursor:pointer;font-size:12px;flex:none}
.chatitem:hover .cedit{opacity:1}
/* AI-assistant drawer (AI-enabled interview mode) */
#assistpanel{display:flex;flex-direction:column;height:42%;border-bottom:1px solid var(--line);background:#0c1322}
.asshead{font-family:var(--disp);letter-spacing:.06em;font-size:12px;color:var(--violet);
 padding:8px 12px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:center}
.asslog{flex:1;min-height:0;overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column;gap:8px;font-size:13.5px;line-height:1.5}
.asslog .am{padding:8px 11px;border-radius:10px;max-width:92%}
.asslog .am.you{align-self:flex-end;background:#131a2a;border:1px solid var(--line)}
.asslog .am.bot{align-self:flex-start;background:#0e1830;border:1px solid #26325a}
.asslog .am pre{background:#0a1018 !important;border:1px solid var(--line);border-radius:8px;padding:9px;overflow-x:auto}
.asslog .am code{font-family:var(--mono);font-size:12.5px}
.asshint{color:var(--dim);font-weight:400;font-size:11px}
.assbar{display:flex;gap:6px;padding:8px;border-top:1px solid var(--line)}
.assbar input{flex:1;background:var(--bg);border:1px solid var(--line);border-radius:8px;color:var(--ink);padding:8px 10px;font-size:13px;font-family:var(--sans)}
/* game HUD */
.hud{display:flex;align-items:center;gap:12px;font-family:var(--mono);font-size:12px}
.hud .flame{color:var(--amber)} .hud .lvl{color:var(--acc);font-weight:600}
.hud .rank{color:var(--violet)}
.hud .xpbar{width:88px;height:9px;border-radius:999px;background:#0b1420;border:1px solid var(--line);overflow:hidden}
.hud .xpfill{height:100%;background:linear-gradient(90deg,var(--acc),var(--cyan));box-shadow:0 0 8px var(--acc)}
/* death overlay */
#death{position:fixed;inset:0;z-index:100;display:none;place-items:center;
 background:radial-gradient(circle at 50% 42%,rgba(70,0,12,.9),rgba(2,0,1,.97));backdrop-filter:blur(3px)}
#death.on{display:grid;animation:fadein .5s ease}
@keyframes fadein{from{opacity:0}to{opacity:1}}
.deathcard{text-align:center;max-width:540px;padding:30px}
.youdied{font-family:var(--disp);font-size:76px;font-weight:700;letter-spacing:.16em;color:#c9182b;
 text-shadow:0 0 30px #ff2d4a99,0 0 70px #ff2d4a55;animation:dpulse 2.4s ease infinite}
@keyframes dpulse{50%{opacity:.8;text-shadow:0 0 22px #ff2d4a77}}
.deathsub{color:#e7c9cf;margin:16px 0;font-size:16px;line-height:1.7}
.deathsub b{color:#ff5c7a}
#death button{font-family:var(--disp);letter-spacing:.12em;margin-top:12px;background:#1a0508;color:#ff8a9c;
 border:1px solid #5a1520;border-radius:11px;padding:11px 26px;cursor:pointer;font-weight:600;font-size:14px}
#death button:hover{background:#260a0f;color:#ffb3bf}
/* reclaim toast */
#reclaim{position:fixed;top:66px;left:50%;transform:translateX(-50%);z-index:90;display:none;
 background:#0c1f18;border:1px solid #1c3d30;color:var(--acc);font-family:var(--disp);letter-spacing:.08em;
 padding:12px 24px;border-radius:12px;box-shadow:0 0 34px #5ef2b855;font-weight:600}
#reclaim.on{display:block;animation:pop .4s ease}
@keyframes pop{from{opacity:0;transform:translateX(-50%) translateY(-8px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
</style></head><body>
<header>
  <div><div class="logo">🏹 <span class="g">EKALAVYA</span></div><div class="creed">स्वाध्याय · साधना · सिद्धि</div></div>
  <button id="chatsbtn" onclick="openDrawer()">☰ Chats</button>
  <div class="tabs">
    <button class="tab on" data-view="practice">Practice</button>
    <button class="tab" data-view="dash">Progress</button>
    <button class="tab" data-view="journey">Journey</button>
    <button class="tab" data-view="tree">Skill Tree</button>
  </div>
  <div class="spacer"></div>
  <div class="hud" id="hud"></div>
  <div class="who" id="who"></div>
</header>
<main>
  <div id="practice">
    <div class="col chat">
      <div class="log" id="log"></div>
      <div class="inbar">
        <input id="chatin" placeholder="type your answer… (or write code on the right →)" autocomplete="off">
        <button class="send" onclick="sendChat()">Send</button>
      </div>
    </div>
    <div class="col">
      <div class="edtoolbar">
        <select id="mode" onchange="newSession()">
          <option value="practice">Daily practice</option>
          <option value="mock">Mock interview</option>
          <option value="aiinterview">AI-enabled interview</option>
          <option value="takehome">Take-home</option>
          <option value="onboard">First-time setup</option>
        </select>
        <span class="grow"></span>
        <button class="ghost" onclick="newSession()">↻ New</button>
        <button class="submit" onclick="submitCode()">▶ Submit code</button>
      </div>
      <div id="assistpanel" class="hidden">
        <div class="asshead">🤖 AI Assistant <span class="asshint">— allowed here, but it's imperfect. Verify it.</span></div>
        <div class="asslog" id="asslog"></div>
        <div class="assbar">
          <input id="assin" placeholder="ask the AI assistant for help…" autocomplete="off">
          <button class="ghost" onclick="sendAssist()">Ask</button>
        </div>
      </div>
      <div id="editor"></div>
    </div>
  </div>
  <div id="dash"><iframe id="dashframe" src="/dashboard"></iframe></div>
  <div id="journey"><iframe id="jframe" src="/journey"></iframe></div>
  <div id="tree">
    <div class="treehead"><span class="g">Skill Tree</span> — <span class="dim">green = mastered · cyan = unlocked · dim = locked</span></div>
    <div id="treediagram"></div>
  </div>
</main>

<div id="drawerscrim" onclick="closeDrawer()"></div>
<div id="drawer">
  <div class="drawerhead"><span class="t">Chats</span><button class="x" onclick="closeDrawer()">×</button></div>
  <button class="newchat" onclick="newChat()">+ New chat</button>
  <div class="chatlist" id="chatlist"></div>
</div>

<div id="death"><div class="deathcard">
  <div class="youdied">YOU DIED</div>
  <div class="deathsub" id="deathsub"></div>
  <button onclick="dismissDeath()">CONTINUE</button>
</div></div>
<div id="reclaim"></div>

<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"></script>
<script>
mermaid.initialize({startOnLoad:false, theme:'dark'});
let thread = crypto.randomUUID(), mode = 'practice', editor = null, streaming = false, pasted = false;

// tabs
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on')); t.classList.add('on');
  const v=t.dataset.view;
  document.getElementById('practice').style.display = v==='practice'?'grid':'none';
  document.getElementById('dash').style.display = v==='dash'?'block':'none';
  document.getElementById('journey').style.display = v==='journey'?'block':'none';
  document.getElementById('tree').style.display = v==='tree'?'block':'none';
  if(v==='dash') document.getElementById('dashframe').src='/dashboard';
  if(v==='journey') document.getElementById('jframe').src='/journey';
  if(v==='tree') loadTree();
});
async function loadTree(){
  const d=document.getElementById('treediagram');
  d.innerHTML='<div class="dim">loading…</div>';
  try{
    const c=await (await fetch('/api/curriculum')).json();
    if(c.empty){ d.innerHTML='<div class="dim" style="padding:50px;text-align:center;max-width:440px">No skill tree yet — finish onboarding and Ekalavya will draft a skill tree you can approve.</div>'; return; }
    d.innerHTML=''; const m=document.createElement('div'); m.className='mermaid'; m.textContent=c.mermaid; d.appendChild(m);
    await mermaid.run({nodes:[m]});
  }catch(e){ d.innerHTML='<div class="dim">could not load the skill tree.</div>'; }
}

require.config({paths:{vs:'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs'}});
require(['vs/editor/editor.main'], function(){
  monaco.editor.defineTheme('ek',{base:'vs-dark',inherit:true,rules:[],colors:{'editor.background':'#0a1018'}});
  editor = monaco.editor.create(document.getElementById('editor'),
    {value:"# write your solution here\n",language:'python',theme:'ek',fontSize:14,minimap:{enabled:false},
     scrollBeyondLastLine:false,automaticLayout:true,fontFamily:"'JetBrains Mono',monospace"});
  editor.onDidPaste(()=>{ pasted = true; });  // anti-cheat: the editor is our honest-signal surface
});

function rank(l){const R=[[17,'Grandmaster'],[12,'Master'],[8,'Expert'],[5,'Adept'],[3,'Apprentice'],[1,'Novice']];
  for(const [t,n] of R) if(l>=t) return n; return 'Novice';}
function setHud(s){const into=s.xp%100;
  document.getElementById('hud').innerHTML =
   "<span class='flame'>🔥 "+s.streak+"</span><span class='lvl'>⭐ Lv "+s.level+"</span>"+
   "<span class='rank'>"+rank(s.level)+"</span>"+
   "<span class='xpbar'><span class='xpfill' style='width:"+into+"%'></span></span>";}
function refreshHud(){ fetch('/api/stats').then(r=>r.json()).then(setHud).catch(()=>{}); }
function showReclaim(amt){ const r=document.getElementById('reclaim');
  r.textContent="⚔ SOULS RECLAIMED  +"+amt+" XP"; r.classList.add('on');
  setTimeout(()=>r.classList.remove('on'),2600); }
function death(){
  fetch('/api/penalise',{method:'POST'}).then(r=>r.json()).then(d=>{
    document.getElementById('deathsub').innerHTML =
      "Code was pasted into the editor — that's not practice.<br>"+
      "Souls dropped: <b>-"+d.lost+" XP</b>. Streak broken.<br>"+
      "<span class='dim'>Type your next answer yourself to reclaim your souls.</span>";
    setHud(d.stats); document.getElementById('death').classList.add('on');
  });
  if(editor) editor.setValue("# write your solution here\n"); pasted=false;
}
function dismissDeath(){ document.getElementById('death').classList.remove('on'); }

function el(cls){const d=document.createElement('div');d.className=cls;return d;}
function addMsg(role, html){
  const m=el('msg '+role); const who=el('who'); who.textContent = role==='you'?'you':'Ekalavya';
  const body=el('body'); body.innerHTML=html; m.appendChild(who); m.appendChild(body);
  document.getElementById('log').appendChild(m); scroll(); return body;
}
function scroll(){const l=document.getElementById('log'); l.scrollTop=l.scrollHeight;}
function renderMd(text){
  const html = DOMPurify.sanitize(marked.parse(text));  // never trust model output in the DOM
  const tmp=document.createElement('div'); tmp.innerHTML=html;
  tmp.querySelectorAll('pre code').forEach(c=>{
    if(c.className.includes('mermaid')||c.className.includes('language-mermaid')){
      const d=el('mermaid'); d.textContent=c.textContent; c.closest('pre').replaceWith(d);
    } else { try{hljs.highlightElement(c);}catch(e){} }
  });
  return tmp.innerHTML;
}

async function stream(text){
  if(streaming) return; streaming=true;
  const body = addMsg('ai',''); body.classList.add('typing'); let buf='';
  try{
    const res = await fetch('/api/stream',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({thread,mode,text})});
    const reader=res.body.getReader(); const dec=new TextDecoder(); let partial='';
    while(true){
      const {value,done}=await reader.read(); if(done) break;
      partial += dec.decode(value,{stream:true}); const lines=partial.split('\n'); partial=lines.pop();
      for(const line of lines){ if(!line.trim())continue; const o=JSON.parse(line);
        if(o.t){ buf+=o.t; body.textContent=buf; scroll(); } }
    }
  }catch(e){ buf+='\n\n_(connection error)_'; }
  body.classList.remove('typing'); body.innerHTML=renderMd(buf);
  try{ await mermaid.run({nodes:body.querySelectorAll('.mermaid')}); }catch(e){}
  scroll(); streaming=false; refreshHud();
}

function sendChat(){
  const inp=document.getElementById('chatin'); const t=inp.value.trim(); if(!t||streaming)return;
  inp.value=''; addMsg('you', renderMd(t)); stream(t);
}
document.getElementById('chatin').addEventListener('keydown',e=>{if(e.key==='Enter')sendChat();});

function submitCode(){
  if(!editor||streaming)return; const code=editor.getValue().trim(); if(!code)return;
  if(mode!=='aiinterview'){                              // AI is allowed in aiinterview — no death
    if(pasted){ death(); return; }                      // caught — you die
    fetch('/api/reclaim',{method:'POST'}).then(r=>r.json()).then(d=>{  // typed it yourself
      if(d.reclaimed>0) showReclaim(d.reclaimed); setHud(d.stats); }).catch(()=>{});
  } else { pasted=false; }
  const msg="Here is my code:\n```python\n"+code+"\n```";
  addMsg('you','<pre><code class="language-python">'+code.replace(/</g,'&lt;')+'</code></pre>');
  document.querySelectorAll('.msg.you pre code').forEach(c=>{try{hljs.highlightElement(c);}catch(e){}});
  stream(msg);
}

// --- AI assistant panel (AI-enabled interview mode) ---
let assbusy=false;
function applyMode(){  // show the AI-assistant drawer only in aiinterview mode
  document.getElementById('assistpanel').classList.toggle('hidden', mode!=='aiinterview');
}
function addAssist(role, html){
  const d=document.createElement('div'); d.className='am '+role; d.innerHTML=html;
  const log=document.getElementById('asslog'); log.appendChild(d); log.scrollTop=log.scrollHeight; return d;
}
function sendAssist(){
  const inp=document.getElementById('assin'); const t=inp.value.trim(); if(!t||assbusy)return;
  inp.value=''; addAssist('you', t.replace(/</g,'&lt;'));
  const b=addAssist('bot','<span class="dim">thinking…</span>'); assbusy=true;
  fetch('/api/assist',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({thread,text:t})})
   .then(r=>r.json()).then(d=>{ b.innerHTML=renderMd(d.reply||'');
     b.querySelectorAll('pre code').forEach(c=>{try{hljs.highlightElement(c);}catch(e){}});
     assbusy=false; document.getElementById('asslog').scrollTop=1e9; })
   .catch(()=>{ b.innerHTML='<span class="dim">assistant unavailable.</span>'; assbusy=false; });
}
document.getElementById('assin').addEventListener('keydown',e=>{if(e.key==='Enter')sendAssist();});

function newSession(){
  mode=document.getElementById('mode').value; thread=crypto.randomUUID(); pasted=false;
  if(editor) editor.setValue("# write your solution here\n");
  document.getElementById('log').innerHTML=''; document.getElementById('asslog').innerHTML='';
  applyMode();
  fetch('/api/config').then(r=>r.json()).then(c=>{ stream(c.kickoff[mode]); });
}

// --- chats drawer (persistent history) ---
function rel(s){ return (s||'').replace('T',' ').slice(0,16); }
async function loadChats(){
  const box=document.getElementById('chatlist');
  try{
    const l=await (await fetch('/api/chats')).json();
    box.innerHTML='';
    if(!l.length){ box.innerHTML='<div class="dim" style="padding:14px;font-size:12px">No past chats yet.</div>'; return; }
    for(const c of l){
      const it=el('chatitem'); if(c.thread_id===thread) it.classList.add('active');
      const ci=el('ci'), ct=el('ct'), cm=el('cm');
      ct.textContent=c.title||'(untitled)'; cm.textContent=(c.mode||'')+' · '+rel(c.updated_at);
      ci.appendChild(ct); ci.appendChild(cm);
      const ed=document.createElement('button'); ed.className='cedit'; ed.textContent='✎'; ed.title='rename';
      it.appendChild(ci); it.appendChild(ed);
      ci.onclick=()=>openChat(c.thread_id);
      ed.onclick=(e)=>{ e.stopPropagation(); renameChat(c.thread_id, c.title); };
      box.appendChild(it);
    }
  }catch(e){ box.innerHTML='<div class="dim" style="padding:14px">could not load chats.</div>'; }
}
function openDrawer(){ loadChats(); document.getElementById('drawer').classList.add('open'); document.getElementById('drawerscrim').classList.add('open'); }
function closeDrawer(){ document.getElementById('drawer').classList.remove('open'); document.getElementById('drawerscrim').classList.remove('open'); }
async function openChat(id){
  if(streaming) return;
  try{
    const c=await (await fetch('/api/chats/'+id)).json();
    thread=id; mode=c.mode||mode; document.getElementById('mode').value=mode; applyMode();
    const log=document.getElementById('log'); log.innerHTML='';
    for(const m of (c.transcript||[])){
      const b=addMsg(m.role==='you'?'you':'ai',''); b.innerHTML=renderMd(m.text);
      b.querySelectorAll('pre code').forEach(x=>{try{hljs.highlightElement(x);}catch(e){}});
      try{ await mermaid.run({nodes:b.querySelectorAll('.mermaid')}); }catch(e){}
    }
    document.getElementById('asslog').innerHTML=''; closeDrawer(); scroll(); refreshHud();
  }catch(e){}
}
function newChat(){ closeDrawer(); newSession(); }
function renameChat(id, cur){
  const t=prompt('Rename chat:', cur||''); if(t==null) return;
  fetch('/api/chats/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t})})
   .then(()=>loadChats()).catch(()=>{});
}

refreshHud();
fetch('/api/config').then(r=>r.json()).then(c=>{
  document.getElementById('who').textContent = c.configured ? (c.provider+' · '+c.model) : 'no provider key set';
  if(c.first_run){ mode='onboard'; document.getElementById('mode').value='onboard'; }  // new user → onboard, not "welcome back"
  applyMode();
  stream(c.kickoff[mode]);
});
</script></body></html>"""
