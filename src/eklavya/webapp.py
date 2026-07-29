"""The full browser UI — for people who don't live in a terminal.

Folds the dashboard in and adds the whole practice experience: a streaming chat, a
real in-browser code editor (Monaco), and rendered visuals (Mermaid diagrams,
highlighted code). It reuses the exact same agent + tools + verified grading as
the TUI, so state stays in one place.

Backend is a thin FastAPI layer; the agent streams tokens over a POST stream.
"""

import json
import logging
import uuid

from . import prompts, report

_log = logging.getLogger("eklavya")

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


def _pending_approval(agent, config) -> dict | None:
    """If the agent paused for run_bash approval, return the command + explanation."""
    try:
        interrupts = getattr(agent.get_state(config), "interrupts", None) or ()
    except Exception:
        return None
    if not interrupts:
        return None
    reqs = (interrupts[0].value or {}).get("action_requests") or []
    if not reqs:
        return None
    args = reqs[0].get("args") or {}
    return {"tool": reqs[0].get("name", "run_bash"),
            "command": args.get("command", ""),
            "explanation": args.get("explanation", "")}


def create_app():
    from pathlib import Path

    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles

    from . import progress
    from .agent import build_agent
    from .dashboard import render as render_dashboard
    from .db import init_db
    from .providers import pick
    from .tools import AIINTERVIEW_TOOLS, ONBOARDING_TOOLS, SESSION_TOOLS
    from .tui import _chunk_text

    from . import config

    # Single-user: initialise the one implicit user's db up front, as before. Multi-user:
    # there is no single home at construction time — each user's db is initialised on their
    # first login (see _mount_auth), so we must NOT touch the default home here.
    if not config.MULTIUSER:
        init_db()
    provider = pick(None)
    # Agents cached per (user_id, mode). In single-user mode user_id is a constant, so
    # this is one agent per mode exactly as before; in multi-user each user gets their own
    # (built against their own checkpointer/workspace via the contextvar at build time).
    agents: dict = {}
    _TOOLS = {"onboard": ONBOARDING_TOOLS, "aiinterview": AIINTERVIEW_TOOLS}

    _SINGLE_USER = "_single"  # the implicit single-user id in single-user mode

    def _current_user_id() -> str:
        return config.paths().home.name if config.MULTIUSER else _SINGLE_USER

    def agent_for(mode: str, user_id: str | None = None):
        mode = mode if mode in _PROMPTS else "practice"
        uid = user_id or _current_user_id()
        key = (uid, mode)
        if key not in agents:
            tools = _TOOLS.get(mode, SESSION_TOOLS)
            agents[key] = build_agent(_PROMPTS[mode], tools, provider=provider.key)
        return agents[key]

    app = FastAPI(title="Ekalavya", docs_url=None, redoc_url=None)

    # Shared design-system stylesheet (Option E cinematic-forest) — one served file that
    # every screen (SPA, dashboard, journey, profile in their iframes, login) links to.
    _STATIC_DIR = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    def _require_owner(thread_id: str) -> None:
        """404 if the current user doesn't own this thread (no-op in single-user mode).
        404, not 403, so we never confirm another user's thread exists."""
        from fastapi import HTTPException

        from .chatstore import owns_thread

        if thread_id and not owns_thread(thread_id):
            raise HTTPException(status_code=404)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX

    @app.get("/welcome", response_class=HTMLResponse)
    def welcome() -> str:
        # Public marketing landing (brand mode). The primary CTA points at the app root;
        # in multi-user mode the auth middleware then bounces the unauthenticated visitor
        # to /login, so a single "Enter the forest" button works for both deployments.
        return _LANDING

    @app.get("/canvas", response_class=HTMLResponse)
    def canvas() -> str:
        # Canvas & Artifacts shell (product mode). A styled scaffold today — the guru
        # authors durable artifacts (lessons, code, framed HTML, interactive visuals) with
        # a highlight-to-ask popover. Full wiring to the agent is a later task.
        return _CANVAS

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> str:
        return render_dashboard(report.overview())

    @app.get("/journey", response_class=HTMLResponse)
    def journey() -> str:
        from .journey import render as render_journey

        return render_journey()

    @app.get("/profile", response_class=HTMLResponse)
    def profile_page() -> str:
        from .profileview import render as render_profile

        return render_profile()

    @app.get("/api/profile")
    def profile_get() -> dict:
        from .profileview import read_profile

        return {"text": read_profile()}

    @app.put("/api/profile")
    async def profile_put(request: Request):
        from .profileview import write_profile

        body = await request.json()
        write_profile(body.get("text", ""))
        return {"ok": True}

    @app.get("/api/overview")
    def overview() -> dict:
        return report.overview()

    @app.get("/api/curriculum")
    def curriculum(pillar: str = "") -> dict:
        return report.curriculum_mermaid(pillar or None)

    @app.get("/api/config")
    def cfg() -> dict:
        from . import settings

        return {"provider": provider.label, "model": provider.default_model,
                "kickoff": _KICKOFF, "configured": provider.is_configured(),
                "first_run": report.is_first_run(),
                "death_on_cheat": settings.get_death_on_cheat()}

    @app.put("/api/settings")
    async def settings_put(request: Request):
        from . import settings

        body = await request.json()
        settings.set_death_on_cheat(bool(body.get("death_on_cheat", True)))
        return {"death_on_cheat": settings.get_death_on_cheat()}

    def _events(agent, config, thread, inputs):
        """One agent run (a new turn OR a resume): route tool activity to the trace,
        stream the reply, and pause for run_bash approval."""
        from .verify import selfcheck

        try:  # the learner's message (a fresh turn) → context for the judge; "" on resume
            user_context = inputs["messages"][0]["content"] if isinstance(inputs, dict) else ""
        except (KeyError, IndexError, TypeError):
            user_context = ""
        buf = []
        try:
            for chunk, _meta in agent.stream(inputs, config=config, stream_mode="messages"):
                # deepagents' documented routing: tool result / tool call → trace;
                # the assistant's own text (an AI chunk with no tool call) → the bubble.
                if getattr(chunk, "type", None) == "tool":
                    yield json.dumps({"result": {"name": getattr(chunk, "name", "") or "",
                                                 "content": str(chunk.content)[:400]}}) + "\n"
                elif getattr(chunk, "tool_call_chunks", None):
                    for tc in chunk.tool_call_chunks:
                        if tc.get("name"):
                            yield json.dumps({"tool": tc["name"]}) + "\n"
                else:
                    tok = _chunk_text(chunk)
                    if tok:
                        buf.append(tok)
                        yield json.dumps({"t": tok}) + "\n"
        except Exception:  # surface a generic error to the UI; log detail server-side
            _log.exception("stream error")
            yield json.dumps({"t": "\n\n_(something went wrong — please try again.)_"}) + "\n"

        approval = _pending_approval(agent, config)  # paused for run_bash?
        if approval:
            yield json.dumps({"approval": approval}) + "\n"
            yield json.dumps({"done": True, "paused": True}) + "\n"
            return

        note = selfcheck("".join(buf), context=user_context)  # context-aware second-model review
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

    @app.post("/api/stream")
    async def stream(request: Request):
        body = await request.json()
        mode = body.get("mode", "practice")
        thread = body.get("thread") or str(uuid.uuid4())
        _require_owner(thread)  # a thread you don't own → 404 (no-op single-user)
        text = body.get("text", "")
        code = (body.get("code") or "").strip()  # editor contents, when changed
        if code:  # let the agent see what's in the editor, as labeled context
            text = (f"{text}\n\n(For context — my code editor currently contains:)\n"
                    f"```python\n{code[:8000]}\n```")
        if mode == "aiinterview":
            from .assist import mark_interview

            mark_interview(thread)  # scope AI-usage grading to this interview
        from .chatstore import touch_chat

        touch_chat(thread, mode=mode)  # persist/refresh this chat in the history
        config = {"configurable": {"thread_id": thread}}
        inputs = {"messages": [{"role": "user", "content": text}]}
        return StreamingResponse(_events(agent_for(mode), config, thread, inputs),
                                 media_type="application/x-ndjson")

    @app.post("/api/run")
    async def run_code(request: Request):
        """Run the editor's code in the isolated sandbox and return its output.
        No agent, no grading — a plain run→output loop the learner can lean on."""
        from starlette.concurrency import run_in_threadpool

        from .sandbox import run_python

        body = await request.json()
        r = await run_in_threadpool(run_python, body.get("code", ""))
        return {"ok": r.ok, "stdout": r.stdout, "stderr": r.stderr,
                "exit_code": r.exit_code, "seconds": r.seconds}

    @app.post("/api/resume")
    async def resume(request: Request):
        from langgraph.types import Command

        body = await request.json()
        mode = body.get("mode", "practice")
        thread = body.get("thread") or ""
        _require_owner(thread)
        decision = "approve" if body.get("decision") == "approve" else "reject"
        config = {"configurable": {"thread_id": thread}}
        cmd = Command(resume={"decisions": [{"type": decision}]})
        return StreamingResponse(_events(agent_for(mode), config, thread, cmd),
                                 media_type="application/x-ndjson")

    @app.post("/api/assist")
    async def assist(request: Request):
        from starlette.concurrency import run_in_threadpool

        from .assist import respond

        body = await request.json()
        thread = body.get("thread") or ""
        _require_owner(thread)
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

        _require_owner(thread_id)
        meta = get_chat(thread_id) or {}
        return {"thread_id": thread_id, "mode": meta.get("mode"),
                "title": meta.get("title") or _MODE_LABEL.get(meta.get("mode"), "Chat"),
                "transcript": transcript(thread_id)}

    @app.patch("/api/chats/{thread_id}")
    async def chat_rename(thread_id: str, request: Request):
        from .chatstore import rename_chat

        _require_owner(thread_id)
        body = await request.json()
        rename_chat(thread_id, body.get("title", ""))
        return {"ok": True}

    # --- auth (multi-user only) --------------------------------------------
    # Everything below is mounted ONLY when EKLAVYA_MULTIUSER is on. In single-user mode
    # nothing here runs, no middleware is added, and the app is byte-for-byte as before.
    if config.MULTIUSER:
        _mount_auth(app)

    return app


def _mount_auth(app) -> None:
    """Add the login/logout routes + the auth middleware. Multi-user mode only."""
    from starlette.responses import HTMLResponse, RedirectResponse

    from . import auth, config
    from .db import init_db
    from .middleware import AuthMiddleware, clear_session, issue_session

    from fastapi import Request

    # Fail loudly now (at app construction) if the signing secret is missing — better than
    # a first-request 500.
    from .middleware import _secret

    _secret()

    @app.get("/login", response_class=HTMLResponse)
    def login_form(error: str = "") -> str:
        return _LOGIN.replace("{{error}}", error and f'<div class="err">{error}</div>' or "")

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        email = (form.get("email") or "").strip()
        password = form.get("password") or ""
        ip = request.client.host if request.client else ""
        if auth.is_locked(email, ip):
            return RedirectResponse("/login?error=Too+many+attempts.+Try+again+later.",
                                    status_code=303)
        uid = auth.verify_login(email, password)
        if uid is None:
            auth.record_failure(email, ip)
            return RedirectResponse("/login?error=Invalid+email+or+password.",
                                    status_code=303)
        auth.reset_failures(email, ip)
        # ensure the user's home + per-user db exist within their own context on first login
        config.set_current_home(config.user_home(uid))
        config.ensure_home()
        init_db()
        resp = RedirectResponse("/", status_code=303)
        issue_session(resp, uid)
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        clear_session(resp)
        return resp

    # Middleware runs on EVERY request: resolve the session → set the per-user contextvar
    # → gate unauthenticated access.
    app.add_middleware(AuthMiddleware)


# --- the single-page front-end ---------------------------------------------

_INDEX = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ekalavya</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700;800;900&family=Marcellus&family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Spectral:ital,wght@0,300;0,400;0,500;0,600;1,400&family=Tiro+Devanagari+Hindi:ital@0;1&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css">
<style>
/* ===== Option E · cinematic-forest practice arena (product mode) =====
   The full palette + fonts of the shared design system, inlined here (the SPA is a single
   served string). Same class/id hooks the JS drives — only the look changes. */
:root{
--indigo-night:#101528;--indigo-deep:#0b1122;--void:#0a0d1c;
--stone:#231d18;--stone-dark:#181310;--stone-warm:#3a2f26;
--parch:#e8dcc0;--parch-dim:#cfc0a0;--parch-mute:#a89670;
--gold:#e7b64b;--gold-bright:#f7d98a;--gold-deep:#b8862f;--gold-ember:#8a5e1f;
--vermilion:#d63b2a;--vermilion-deep:#8f2318;--vermilion-glow:#ff5a3c;
--peacock:#2ea3a0;--peacock-bright:#57d3ce;--peacock-deep:#124d4c;
--forest:#2f6b3c;--forest-lit:#52a061;
--line-gold:rgba(231,182,75,.28);--line-soft:rgba(231,182,75,.14);--ink:#0a0c18;
--f-display:'Cinzel',serif;--f-title:'Marcellus',serif;--f-body:'Spectral',serif;
--f-serif:'Cormorant Garamond',serif;--f-deva:'Tiro Devanagari Hindi',serif;
--f-mono:'JetBrains Mono',ui-monospace,monospace;
/* aliases so the arena markup's colour intents map onto the semantic ramp */
--bg:var(--void);--panel:rgba(35,29,24,.5);--panel2:rgba(6,9,20,.5);--line:var(--line-soft);
--ink2:var(--parch);--dim:var(--parch-dim);--acc:var(--gold);--cyan:var(--peacock-bright);
--violet:var(--gold-bright);--amber:var(--gold-bright);--mono:var(--f-mono)}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font-family:var(--f-body);color:var(--parch);-webkit-font-smoothing:antialiased;
background-color:var(--indigo-night);
background-image:radial-gradient(1200px 700px at 78% 2%,rgba(46,163,160,.08),transparent 60%),radial-gradient(900px 600px at 12% 6%,rgba(231,182,75,.07),transparent 55%);
background-attachment:fixed;display:flex;flex-direction:column;height:100vh;overflow:hidden}
header{display:flex;align-items:center;gap:14px;padding:12px 20px;border-bottom:1px solid var(--line-soft);
background:linear-gradient(120deg,rgba(35,29,24,.6),rgba(12,10,20,.7))}
.logo{font-family:var(--f-display);font-weight:800;font-size:19px;letter-spacing:.1em;display:flex;align-items:center;gap:8px}
.logo .bowmark{filter:drop-shadow(0 2px 8px rgba(231,182,75,.4))}
.logo .g{color:transparent;background:linear-gradient(180deg,#fff6df,var(--gold-bright) 45%,var(--gold) 75%,var(--gold-deep));-webkit-background-clip:text;background-clip:text}
.creed{font-family:var(--f-deva);color:var(--gold-bright);font-size:12px;letter-spacing:.02em;opacity:.9}
.tabs{display:flex;gap:4px;margin-left:10px}
.tab{font-family:var(--f-mono);letter-spacing:.1em;text-transform:uppercase;font-size:11px;color:var(--parch-dim);
background:none;border:1px solid transparent;padding:7px 13px;border-radius:4px;cursor:pointer;transition:.16s}
.tab:hover{color:var(--gold-bright)}
.tab.on{color:var(--gold-bright);border-color:var(--line-gold);background:rgba(231,182,75,.08)}
.spacer{flex:1}.who{font-family:var(--f-mono);font-size:11px;color:var(--parch-mute)}
main{flex:1;min-height:0}
#practice{display:grid;grid-template-columns:1fr 1fr;height:100%}
@media(max-width:900px){#practice{grid-template-columns:1fr;grid-template-rows:1fr 1fr}}
#practice.nocode{grid-template-columns:1fr;grid-template-rows:1fr}       /* editor hidden → chat full width */
#practice.nocode > .col:not(.chat){display:none}
#practice.nocode > .col.chat{border-right:none}
.col{display:flex;flex-direction:column;min-height:0;min-width:0}
.col.chat{border-right:1px solid var(--line-soft)}
.log{flex:1;overflow-y:auto;padding:18px 20px;display:flex;flex-direction:column;gap:14px}
.msg{max-width:92%;padding:14px 17px;line-height:1.55;font-size:15px;overflow-wrap:anywhere;font-family:var(--f-body)}
/* the guru speaks on aged Pithora paper (light bubble → dark text) */
.msg.ai{align-self:flex-start;background:linear-gradient(180deg,#ead9b6,#dfcaa0);border:1px solid #c6ac7d;
 border-radius:4px 12px 12px 12px;color:#2a2010;box-shadow:var(--sh-deep);position:relative}
.msg.ai::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:.5;border-radius:inherit;
 background-image:radial-gradient(rgba(87,67,38,.16) 1px,transparent 1.3px);background-size:14px 14px}
.msg.ai>*{position:relative;z-index:1}
.msg.you{align-self:flex-end;background:linear-gradient(160deg,rgba(18,77,76,.4),rgba(8,20,20,.6));
 border:1px solid rgba(46,163,160,.35);border-radius:12px 4px 12px 12px;color:var(--parch)}
.msg.ai .who{font-family:var(--f-mono);letter-spacing:.16em;font-size:10px;color:var(--gold-ember);text-transform:uppercase;margin-bottom:5px}
.msg.you .who{font-family:var(--f-mono);letter-spacing:.16em;font-size:10px;color:var(--peacock-bright);text-transform:uppercase;margin-bottom:5px}
.msg pre{background:rgba(20,15,8,.9) !important;border:1px solid rgba(231,182,75,.2);border-radius:8px;padding:12px;overflow-x:auto}
.msg.you pre{background:rgba(6,9,20,.7) !important;border-color:var(--line-soft)}
.msg code{font-family:var(--f-mono);font-size:13px}
.msg.ai pre code{color:var(--peacock-bright)}
.msg p{margin:6px 0}.msg h1,.msg h2,.msg h3{font-family:var(--f-display);margin:10px 0 4px;color:inherit;font-weight:700}
.msg.ai a{color:#7a4e10}
.msg blockquote{border-left:3px solid var(--gold);margin:8px 0;padding:2px 12px;color:#6b4710;font-style:italic}
.msg.you blockquote{border-left-color:var(--peacock);color:var(--parch-dim)}
.mermaid{background:rgba(6,9,16,.85);border:1px solid var(--line-soft);border-radius:8px;padding:10px;text-align:center}
.inbar{display:flex;gap:8px;padding:12px;border-top:1px solid var(--line-soft);background:rgba(6,9,20,.5)}
.inbar textarea{flex:1;background:rgba(6,9,20,.6);border:1px solid var(--line-gold);border-radius:6px;color:var(--parch);
padding:11px 14px;font-family:var(--f-body);font-size:14px;resize:none;max-height:150px;line-height:1.45;overflow-y:auto;outline:none;transition:.2s}
.inbar textarea:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(231,182,75,.14)}
.inbar textarea::placeholder{color:var(--parch-mute)}
button.send{font-family:var(--f-title);letter-spacing:.04em;font-size:15px;
background:linear-gradient(180deg,var(--gold-bright),var(--gold) 55%,var(--gold-deep));
color:#2a1c07;border:none;border-radius:4px;padding:0 20px;font-weight:600;cursor:pointer;
box-shadow:0 6px 20px -6px rgba(231,182,75,.55),inset 0 1px 0 rgba(255,255,255,.4);transition:.2s}
button.send:hover{transform:translateY(-1px)}
.edtoolbar{display:flex;gap:8px;align-items:center;padding:9px 14px;border-bottom:1px solid var(--line-soft);background:rgba(6,9,20,.5)}
.edtoolbar select{background:rgba(6,9,20,.7);color:var(--parch);border:1px solid var(--line-gold);border-radius:5px;padding:6px 9px;font-family:var(--f-mono);font-size:11px}
.edtoolbar .grow{flex:1}
button.submit{font-family:var(--f-title);letter-spacing:.02em;font-size:13px;background:rgba(231,182,75,.08);color:var(--gold-bright);border:1px solid var(--gold-deep);
border-radius:4px;padding:8px 15px;font-weight:600;cursor:pointer;transition:.16s}
button.submit:hover{background:rgba(231,182,75,.16)}
button.ghost{background:rgba(6,9,20,.5);color:var(--parch-dim);border:1px solid var(--line-gold);border-radius:4px;padding:8px 13px;cursor:pointer;font-family:var(--f-title);font-size:13px;transition:.16s}
button.ghost:hover{color:var(--gold-bright);border-color:var(--gold-deep)}
button.ghost.run{color:var(--peacock-bright);border-color:rgba(46,163,160,.4)}
button.ghost.run:hover{color:var(--peacock-bright);border-color:var(--peacock)}
button:disabled{opacity:.42;cursor:default}
#editor{flex:1;min-height:0;min-width:0}
/* run output block (Run button → sandbox stdout/stderr) */
.runout{align-self:stretch;border:1px solid var(--line-soft);border-radius:10px;background:rgba(6,9,16,.8);overflow:hidden}
.runout .rohead{font-family:var(--f-mono);font-size:11px;letter-spacing:.02em;color:var(--parch-dim);
 padding:8px 13px;border-bottom:1px solid var(--line-soft);display:flex;align-items:center;gap:7px}
.runout .rohead .ok{color:var(--peacock-bright)} .runout .rohead .bad{color:var(--vermilion-glow)}
.runout pre{margin:0;padding:11px 13px;font-family:var(--f-mono);font-size:12.5px;line-height:1.5;
 white-space:pre-wrap;word-break:break-word;overflow-x:auto;color:var(--parch)}
.runout pre.roerr{color:#ff9aa9;border-top:1px solid var(--line-soft)}
.runout .roempty{padding:11px 13px;font-family:var(--f-mono);font-size:12px;color:var(--parch-mute)}
#dash,#journey,#profile{display:none;height:100%}
#dash iframe,#journey iframe,#profile iframe{width:100%;height:100%;border:0;background:var(--indigo-night)}
#tree{display:none;height:100%;overflow:auto;padding:24px}
.treehead{font-family:var(--f-display);font-weight:700;letter-spacing:.02em;font-size:18px;margin-bottom:14px;color:var(--parch)}
#treefilter{margin-left:12px;background:rgba(6,9,20,.7);color:var(--parch);border:1px solid var(--line-gold);border-radius:5px;padding:6px 10px;font-family:var(--f-mono);font-size:12px;letter-spacing:0}
.treehead .g{color:transparent;background:linear-gradient(180deg,#fff6df,var(--gold-bright) 45%,var(--gold) 75%,var(--gold-deep));-webkit-background-clip:text;background-clip:text}
#treediagram{display:block}   /* not flex — flex crushed the SVG; loadTree() sets natural px size, #tree scrolls */
.hidden{display:none !important}
.dim{color:var(--parch-dim)} .typing:after{content:'▍';color:var(--gold);animation:blink 1s steps(2) infinite}
@keyframes blink{50%{opacity:0}}
/* thinking trace (tool calls/results, collapsed by default) — the guru at work */
.trace{margin:0 0 8px;border:1px solid var(--line-soft);border-radius:9px;background:rgba(6,9,20,.55);overflow:hidden}
.trace .tsum{list-style:none;cursor:pointer;padding:8px 13px;font-family:var(--f-mono);font-size:11px;
 letter-spacing:.02em;color:var(--peacock-bright);user-select:none;display:flex;align-items:center;gap:6px}
.trace .tsum::-webkit-details-marker{display:none}
.trace .tsum:before{content:'▸';color:var(--gold);font-size:10px}
.trace[open] .tsum:before{content:'▾'}
.trace[open] .tsum{border-bottom:1px solid var(--line-soft);color:var(--gold-bright)}
.trace .tbody{padding:8px 13px;display:flex;flex-direction:column;gap:4px}
.tline{font-family:var(--f-mono);font-size:11px;color:var(--parch-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tline.call{color:var(--gold-bright)} .tline.res{color:var(--peacock-bright)}
/* bash approval card */
.approve{margin:2px 0 8px;border:1px solid var(--gold);border-radius:11px;background:linear-gradient(160deg,rgba(35,29,24,.9),rgba(20,15,8,.92));padding:14px 16px;box-shadow:0 10px 30px -12px rgba(231,182,75,.4)}
.approve .ah{font-family:var(--f-title);letter-spacing:.02em;color:var(--gold-bright);font-size:13px;margin-bottom:8px}
.approve .acmd{font-family:var(--f-mono);font-size:12px;background:rgba(6,9,20,.75);border:1px solid var(--line-soft);border-radius:6px;
 padding:9px 11px;color:var(--peacock-bright);white-space:pre-wrap;word-break:break-all;margin-bottom:8px}
.approve .awhy{font-family:var(--f-body);font-size:13px;color:var(--parch-dim);margin-bottom:12px}
.approve .abtns{display:flex;gap:9px}
.approve button{font-family:var(--f-title);letter-spacing:.02em;border-radius:4px;padding:9px 18px;cursor:pointer;font-weight:600;border:1px solid;font-size:13px}
.approve .ok{background:rgba(231,182,75,.1);color:var(--gold-bright);border-color:var(--gold-deep)}
.approve .no{background:rgba(143,35,24,.2);color:var(--vermilion-glow);border-color:rgba(214,59,42,.5)}
/* chats drawer */
#chatsbtn{font-family:var(--f-mono);letter-spacing:.08em;font-size:11px;text-transform:uppercase;color:var(--parch-dim);background:rgba(6,9,20,.5);
 border:1px solid var(--line-gold);border-radius:4px;padding:8px 12px;cursor:pointer;margin-left:4px;transition:.16s}
#chatsbtn:hover{color:var(--gold-bright);border-color:var(--gold-deep)}
#penaltybtn{font-family:var(--f-mono);font-size:11px;color:var(--parch-dim);background:rgba(6,9,20,.5);border:1px solid var(--line-gold);
 border-radius:4px;padding:7px 11px;cursor:pointer;margin-right:4px;transition:.16s}
#penaltybtn:hover{border-color:var(--gold-deep)}
#penaltybtn.off{color:var(--vermilion-glow);border-color:rgba(214,59,42,.5)}
#drawerscrim{position:fixed;inset:0;z-index:110;background:rgba(2,6,12,.6);opacity:0;pointer-events:none;transition:opacity .22s}
#drawerscrim.open{opacity:1;pointer-events:auto}
#drawer{position:fixed;top:0;left:0;bottom:0;width:300px;z-index:120;transform:translateX(-105%);
 transition:transform .22s ease;display:flex;flex-direction:column;
 background:linear-gradient(180deg,rgba(35,29,24,.6),rgba(12,10,20,.85));border-right:1px solid var(--line-gold);box-shadow:2px 0 30px #0008}
#drawer.open{transform:translateX(0)}
.drawerhead{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line-soft)}
.drawerhead .t{font-family:var(--f-mono);letter-spacing:.16em;font-size:12px;color:var(--gold-bright);text-transform:uppercase}
.drawerhead .x{margin-left:auto;background:none;border:none;color:var(--parch-dim);cursor:pointer;font-size:18px}
.newchat{margin:12px;font-family:var(--f-title);letter-spacing:.02em;font-size:13px;background:rgba(231,182,75,.08);color:var(--gold-bright);
 border:1px solid var(--gold-deep);border-radius:8px;padding:10px 13px;cursor:pointer;text-align:left}
.newchat:hover{background:rgba(231,182,75,.16)}
.chatlist{flex:1;overflow-y:auto;padding:4px 8px}
.chatitem{display:flex;align-items:center;gap:9px;padding:10px 12px;border-radius:8px;cursor:pointer;border:1px solid transparent;transition:.14s}
.chatitem:hover{background:rgba(6,9,20,.4);border-color:var(--line-soft)}
.chatitem.active{background:rgba(6,9,20,.4);border-color:var(--line-gold)}
.chatitem .ci{flex:1;min-width:0}
.chatitem .ct{font-family:var(--f-body);font-size:13px;color:var(--parch);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chatitem:hover .ct{color:var(--gold-bright)}
.chatitem .cm{font-family:var(--f-mono);font-size:10px;color:var(--parch-mute);margin-top:2px}
.chatitem .cedit{opacity:0;color:var(--parch-mute);background:none;border:none;cursor:pointer;font-size:12px;flex:none}
.chatitem:hover .cedit{opacity:1}
/* AI-assistant drawer (AI-enabled interview mode) */
#assistpanel{display:flex;flex-direction:column;height:42%;border-bottom:1px solid var(--line-soft);background:linear-gradient(180deg,rgba(20,28,40,.55),rgba(10,14,26,.7))}
.asshead{font-family:var(--f-title);font-size:13px;color:var(--peacock-bright);
 padding:9px 13px;border-bottom:1px solid var(--line-soft);display:flex;gap:8px;align-items:center}
.asslog{flex:1;min-height:0;overflow-y:auto;padding:11px 13px;display:flex;flex-direction:column;gap:8px;font-size:13.5px;line-height:1.5;font-family:var(--f-body)}
.asslog .am{padding:8px 11px;border-radius:9px;max-width:92%}
.asslog .am.you{align-self:flex-end;background:rgba(22,32,46,.8);border:1px solid rgba(140,170,200,.3);color:var(--parch)}
.asslog .am.bot{align-self:flex-start;background:rgba(18,20,40,.7);border:1px solid rgba(87,101,120,.4);color:var(--parch-dim)}
.asslog .am pre{background:rgba(6,9,16,.85) !important;border:1px solid var(--line-soft);border-radius:8px;padding:9px;overflow-x:auto}
.asslog .am code{font-family:var(--f-mono);font-size:12.5px}
.asshint{color:var(--parch-mute);font-weight:400;font-size:11px;font-family:var(--f-mono)}
.assbar{display:flex;gap:6px;padding:8px 12px;border-top:1px solid var(--line-soft)}
.assbar input{flex:1;background:rgba(6,9,20,.6);border:1px solid var(--line-gold);border-radius:6px;color:var(--parch);padding:9px 11px;font-size:13px;font-family:var(--f-body);outline:none}
.assbar input:focus{border-color:var(--gold)}
/* game HUD */
.hud{display:flex;align-items:center;gap:11px;font-family:var(--f-mono);font-size:12px}
.hud .flame{color:var(--gold-bright)} .hud .lvl{color:var(--gold);font-weight:600}
.hud .rank{color:var(--peacock-bright);font-family:var(--f-title);font-size:13px}
.hud .xpbar{width:88px;height:9px;border-radius:999px;background:rgba(6,9,20,.7);border:1px solid var(--line-gold);overflow:hidden}
.hud .xpfill{height:100%;background:linear-gradient(90deg,var(--gold-deep),var(--gold-bright));box-shadow:0 0 8px rgba(231,182,75,.6)}
/* death / loss overlay — the archer's fall, re-themed to sindoor vermilion + gold merit */
#death{position:fixed;inset:0;z-index:100;display:none;place-items:center;
 background:radial-gradient(circle at 50% 42%,rgba(60,14,10,.72),rgba(6,4,10,.97) 72%);backdrop-filter:blur(3px)}
#death.on{display:grid;animation:fadein .5s ease}
@keyframes fadein{from{opacity:0}to{opacity:1}}
.deathcard{text-align:center;max-width:540px;padding:30px}
.youdied{font-family:var(--f-display);font-size:clamp(48px,8vw,72px);font-weight:800;letter-spacing:.1em;
 color:transparent;background:linear-gradient(180deg,#ffb9ac,var(--vermilion) 55%,var(--vermilion-deep));
 -webkit-background-clip:text;background-clip:text;text-shadow:0 0 40px rgba(214,59,42,.45);animation:dpulse 2.4s ease infinite}
@keyframes dpulse{50%{opacity:.86}}
.deathsub{font-family:var(--f-serif);font-style:italic;color:var(--parch-dim);margin:16px auto;font-size:16px;line-height:1.6;max-width:440px}
.deathsub b{color:var(--vermilion-glow);font-style:normal}
#death button{font-family:var(--f-title);letter-spacing:.04em;margin-top:14px;background:rgba(143,35,24,.2);color:var(--vermilion-glow);
 border:1px solid rgba(214,59,42,.55);border-radius:4px;padding:11px 26px;cursor:pointer;font-weight:600;font-size:14px}
#death button:hover{background:rgba(143,35,24,.35)}
/* reclaim toast — merit reclaimed, gold sheen */
#reclaim{position:fixed;top:66px;left:50%;transform:translateX(-50%);z-index:90;display:none;
 background:linear-gradient(120deg,rgba(35,29,24,.95),rgba(20,15,10,.95));border:1px solid var(--gold);color:var(--gold-bright);
 font-family:var(--f-title);letter-spacing:.04em;
 padding:13px 26px;border-radius:5px;box-shadow:0 12px 40px -10px rgba(231,182,75,.4);font-weight:600}
#reclaim.on{display:block;animation:pop .4s ease}
@keyframes pop{from{opacity:0;transform:translateX(-50%) translateY(-8px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
*:focus-visible{outline:2px solid var(--gold-bright);outline-offset:2px;border-radius:3px}
.sh-deep{--sh-deep:0 24px 60px -20px rgba(0,0,0,.8)}
:root{--sh-deep:0 24px 60px -20px rgba(0,0,0,.8)}
/* mobile: header wraps, tabs scroll, creed hides so the HUD + tabs fit */
@media(max-width:900px){
 header{flex-wrap:wrap;gap:10px;padding:10px 14px}
 .creed{display:none}
 .tabs{margin-left:0;overflow-x:auto;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}
 .hud{font-size:11px;gap:8px}.hud .xpbar{width:60px}
}
</style></head><body>
<header>
  <div><div class="logo"><span class="bowmark"><svg width="17" height="22" viewBox="0 0 58 76" aria-hidden="true"><path d="M14 6 C40 24 40 52 14 70" stroke="#e7b64b" stroke-width="4" stroke-linecap="round" fill="none"/><line x1="14" y1="6" x2="14" y2="70" stroke="#57d3ce" stroke-width="1.6"/><line x1="14" y1="38" x2="50" y2="38" stroke="#f7d98a" stroke-width="2.4"/><path d="M50 38 l-7 -5 M50 38 l-7 5" stroke="#f7d98a" stroke-width="2.4" stroke-linecap="round"/></svg></span> <span class="g">EKALAVYA</span></div><div class="creed">स्वाध्याय · साधना · सिद्धि</div></div>
  <button id="chatsbtn" onclick="openDrawer()">☰ Chats</button>
  <div class="tabs">
    <button class="tab on" data-view="practice">Practice</button>
    <button class="tab" data-view="dash">Progress</button>
    <button class="tab" data-view="journey">Journey</button>
    <button class="tab" data-view="profile">Profile</button>
    <button class="tab" data-view="tree">Skill Tree</button>
  </div>
  <button class="tab on" id="edtoggle" onclick="toggleEditor()" title="Show or hide the code editor">▤ Editor</button>
  <div class="spacer"></div>
  <button id="penaltybtn" onclick="togglePenalty()" title="Turn the cheat penalty on or off">☠ penalty on</button>
  <div class="hud" id="hud"></div>
  <div class="who" id="who"></div>
</header>
<main>
  <div id="practice">
    <div class="col chat">
      <div class="log" id="log"></div>
      <div class="inbar">
        <textarea id="chatin" rows="1" placeholder="type your answer…  (Shift+Enter for a new line)" autocomplete="off"></textarea>
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
        <button class="ghost run" onclick="runCode()">▶ Run</button>
        <button class="submit" onclick="submitCode()">✓ Submit code</button>
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
  <div id="profile"><iframe id="pframe" src="/profile"></iframe></div>
  <div id="tree">
    <div class="treehead"><span class="g">Skill Tree</span> — <span class="dim">green = mastered · cyan = unlocked · dim = locked</span>
      <select id="treefilter" onchange="loadTree(this.value)"></select></div>
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
let thread = crypto.randomUUID(), mode = 'practice', editor = null, streaming = false;
let biggestPaste = 0, deathOnCheat = true;   // anti-cheat: size of the largest paste; whether a trigger penalises
const STUB = "# write your solution here\n";
// mirror of progress.looks_pasted — only a big paste dominating a code-like solution counts
function looksPasted(code, biggest){
  code=(code||'').trim();
  if(!code || biggest < 240) return false;
  if(biggest < 0.6*code.length) return false;
  return /\b(def|return|for|while|class|import)\b|[={}()]/.test(code);
}
let lastSentCode = '';   // editor code the agent has already seen this chat — avoids re-sending unchanged code
function editorCode(){ if(!editor) return ''; const c=editor.getValue(); return c.trim()===STUB.trim()?'':c; }

// tabs
document.querySelectorAll('.tab[data-view]').forEach(t=>t.onclick=()=>{  // [data-view] excludes the editor toggle
  document.querySelectorAll('.tab[data-view]').forEach(x=>x.classList.remove('on')); t.classList.add('on');
  const v=t.dataset.view;
  document.getElementById('practice').style.display = v==='practice'?'grid':'none';
  document.getElementById('dash').style.display = v==='dash'?'block':'none';
  document.getElementById('journey').style.display = v==='journey'?'block':'none';
  document.getElementById('profile').style.display = v==='profile'?'block':'none';
  document.getElementById('tree').style.display = v==='tree'?'block':'none';
  if(v==='dash') document.getElementById('dashframe').src='/dashboard';
  if(v==='journey') document.getElementById('jframe').src='/journey';
  if(v==='profile') document.getElementById('pframe').src='/profile';  // reload → latest profile/goals
  if(v==='tree') loadTree();
});
// editor show/hide toggle (canvas-style) — persisted; Submit never hides it
function toggleEditor(){
  const hidden=document.getElementById('practice').classList.toggle('nocode');
  document.getElementById('edtoggle').classList.toggle('on', !hidden);
  localStorage.setItem('ek_nocode', hidden?'1':'0');
  if(editor && !hidden) setTimeout(()=>editor.layout(),60);  // Monaco needs a relayout when reshown
}
if(localStorage.getItem('ek_nocode')==='1'){
  document.getElementById('practice').classList.add('nocode');
  document.getElementById('edtoggle').classList.remove('on');
}

let _treeDefaulted=false;
async function loadTree(pillar){
  const d=document.getElementById('treediagram');
  d.innerHTML='<div class="dim">loading…</div>';
  const track = pillar && pillar!=='__all__';
  try{
    const c=await (await fetch('/api/curriculum'+(track?('?pillar='+encodeURIComponent(pillar)):''))).json();
    const sel=document.getElementById('treefilter');   // populate the filter once
    if(sel && !sel.dataset.filled && c.pillars){ sel.dataset.filled='1';
      sel.innerHTML='<option value="__all__">All tracks (overview)</option>'+
        c.pillars.map(p=>'<option>'+p.replace(/</g,'&lt;')+'</option>').join(''); }
    // First impression = a legible single track, not the 197-node overview hairball.
    if(!track && !_treeDefaulted && c.pillars && c.pillars.length){
      _treeDefaulted=true; if(sel) sel.value=c.pillars[0]; return loadTree(c.pillars[0]);
    }
    if(c.empty){ d.innerHTML='<div class="dim" style="padding:50px;text-align:center;max-width:440px">No skill tree yet — finish onboarding and Ekalavya will draft a skill tree you can approve.</div>'; return; }
    d.innerHTML=''; const m=document.createElement('div'); m.className='mermaid'; m.textContent=c.mermaid; d.appendChild(m);
    await mermaid.run({nodes:[m]});
    const svg=m.querySelector('svg'); const vb=svg&&svg.viewBox&&svg.viewBox.baseVal;
    if(svg&&vb){
      if(track){ svg.style.width=vb.width+'px'; svg.style.height=vb.height+'px'; svg.style.maxWidth='none'; }  // one track: natural, legible
      else { svg.style.width='100%'; svg.style.height='auto'; svg.style.maxWidth='none'; }                     // all: fit-width overview
    }
  }catch(e){ d.innerHTML='<div class="dim">could not load the skill tree.</div>'; }
}

require.config({paths:{vs:'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs'}});
require(['vs/editor/editor.main'], function(){
  monaco.editor.defineTheme('ek',{base:'vs-dark',inherit:true,rules:[],colors:{'editor.background':'#0a1018'}});
  editor = monaco.editor.create(document.getElementById('editor'),
    {value:"# write your solution here\n",language:'python',theme:'ek',fontSize:14,minimap:{enabled:false},
     scrollBeyondLastLine:false,automaticLayout:true,fontFamily:"'JetBrains Mono',monospace"});
  editor.onDidPaste(e=>{  // measure the paste; only a big one that dominates the solution counts
    try{ const n=editor.getModel().getValueLengthInRange(e.range); if(n>biggestPaste) biggestPaste=n; }catch(_){}
  });
  editor.onDidChangeModelContent(()=>{  // pasted block deleted → forget it (avoids false positives)
    if(editor.getValue().length < biggestPaste) biggestPaste = 0;
  });
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
function flagCheat(reason){
  // NEVER wipe the editor — the learner's work always stays.
  if(!deathOnCheat){                 // penalty disabled → a quiet note, no punishment
    addMsg('ai','<span class="dim">⚠ '+reason+" — noticed, but the penalty is off, so nothing happens.</span>");
    return;
  }
  fetch('/api/penalise',{method:'POST'}).then(r=>r.json()).then(d=>{
    document.getElementById('deathsub').innerHTML =
      reason+".<br>Souls dropped: <b>-"+d.lost+" XP</b>. Streak broken.<br>"+
      "<span class='dim'>Your code is untouched. Type your next answer yourself to reclaim your souls.</span>";
    setHud(d.stats); document.getElementById('death').classList.add('on');
  });
}
function dismissDeath(){ document.getElementById('death').classList.remove('on'); }
function updatePenaltyBtn(){ const b=document.getElementById('penaltybtn');
  b.textContent = deathOnCheat ? '☠ penalty on' : '☠ penalty off'; b.classList.toggle('off', !deathOnCheat); }
function togglePenalty(){ deathOnCheat=!deathOnCheat; updatePenaltyBtn();
  fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({death_on_cheat:deathOnCheat})}).catch(()=>{}); }

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

function prettyTool(name){
  const M={save_baseline:'Saving your baseline',record_attempt:'Recording the attempt',
    suggest_focus:'Choosing what to practise',review_ai_usage:'Reviewing AI usage',
    run_bash:'Running a command',tavily_search:'Searching the web',tavily_extract:'Reading a page',
    'resolve-library-id':'Finding the docs','query-docs':'Reading the docs',read_file:'Reading a file',
    write_file:'Writing a file',edit_file:'Editing a file',ls:'Listing files',glob:'Finding files',
    grep:'Searching files',write_todos:'Planning'};
  return M[name]||name;
}
function addAiMsg(){
  const m=el('msg ai'); const who=el('who'); who.textContent='Ekalavya';
  const trace=document.createElement('details'); trace.className='trace'; trace.style.display='none';
  const sum=document.createElement('summary'); sum.className='tsum'; sum.textContent='working…';
  const tb=el('tbody'); trace.appendChild(sum); trace.appendChild(tb);
  const reply=el('reply'); reply.classList.add('typing');
  m.appendChild(who); m.appendChild(trace); m.appendChild(reply);
  document.getElementById('log').appendChild(m); scroll();
  return {m,trace,sum,tb,reply,buf:'',steps:0};
}
function traceLine(tb,cls,text){ const d=el('tline '+cls); d.textContent=text; tb.appendChild(d); }
function finalizeMsg(ui){
  ui.reply.classList.remove('typing');
  ui.reply.innerHTML=renderMd(ui.buf||'');  // renderMd already highlights code blocks
  try{ mermaid.run({nodes:ui.reply.querySelectorAll('.mermaid')}); }catch(e){}
  if(ui.steps>0){ ui.sum.textContent=ui.steps+' step'+(ui.steps>1?'s':'')+' · tap to view'; }
  else { ui.trace.style.display='none'; }
  scroll();
}
function askApproval(ui, req){
  return new Promise(resolve=>{
    ui.trace.style.display='block';
    traceLine(ui.tb,'call','⏸ awaiting approval — '+req.command);
    const card=el('approve');
    card.innerHTML='<div class="ah">⏻ RUN THIS COMMAND?</div><div class="acmd"></div>'+
      '<div class="awhy"></div><div class="abtns">'+
      '<button class="ok">Approve &amp; run</button><button class="no">Reject</button></div>';
    card.querySelector('.acmd').textContent=req.command||'(no command)';
    card.querySelector('.awhy').textContent=req.explanation||'';
    ui.m.insertBefore(card, ui.reply); scroll();
    const finish=async(decision)=>{
      card.remove();
      traceLine(ui.tb,'res',(decision==='approve'?'✓ approved: ':'✗ rejected: ')+req.command);
      try{
        const res=await fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({thread,mode,decision})});
        await consume(res, ui);
      }catch(e){}
      resolve();
    };
    card.querySelector('.ok').onclick=()=>finish('approve');
    card.querySelector('.no').onclick=()=>finish('reject');
  });
}
async function consume(res, ui){
  const reader=res.body.getReader(); const dec=new TextDecoder(); let partial='';
  while(true){
    const {value,done}=await reader.read(); if(done) break;
    partial += dec.decode(value,{stream:true}); const lines=partial.split('\n'); partial=lines.pop();
    for(const line of lines){ if(!line.trim())continue;
      let o; try{o=JSON.parse(line);}catch(e){continue;}
      if(o.t){ ui.buf+=o.t; const now=Date.now();
        if(now-(ui._lr||0)>100){ ui._lr=now; ui.reply.innerHTML=DOMPurify.sanitize(marked.parse(ui.buf)); }
        scroll(); }
      else if(o.tool){ ui.steps++; ui.trace.style.display='block';
        traceLine(ui.tb,'call','→ '+prettyTool(o.tool)); ui.sum.textContent=prettyTool(o.tool)+'…'; scroll(); }
      else if(o.result){ traceLine(ui.tb,'res','✓ '+prettyTool(o.result.name)); }
      else if(o.approval){ await askApproval(ui, o.approval); }
    }
  }
}
let queued=null, queuedSubmit=false;
function setBusy(on){ const b=document.querySelector('.inbar .send'); if(b){b.disabled=on;b.style.opacity=on?'.45':'';b.textContent=on?'…':'Send';} }
async function stream(text, code){
  if(streaming) return; streaming=true; setBusy(true);
  const ui=addAiMsg();
  try{
    const res=await fetch('/api/stream',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({thread,mode,text,code:code||undefined})});
    await consume(res, ui);
  }catch(e){ ui.buf+='\n\n_(connection error)_'; }
  finalizeMsg(ui); streaming=false; setBusy(false); refreshHud();
  if(queued){ const q=queued; queued=null; stream(q); }        // a message typed mid-stream
  else if(queuedSubmit){ queuedSubmit=false; submitCode(); }   // a code submit clicked mid-stream
}

function sendChat(){
  const inp=document.getElementById('chatin'); const t=inp.value.trim(); if(!t)return;
  inp.value=''; inp.style.height='auto'; addMsg('you', renderMd(t));
  if(streaming){ queued=t; return; }   // queue it; it fires when the current turn ends
  const code=editorCode();                                  // let the agent see the editor,
  const attach=(code && code!==lastSentCode)?code:null;     // but only when it changed
  if(attach) lastSentCode=code;
  stream(t, attach);
}

function addRunOut(label){
  const d=el('runout'); d.innerHTML='<div class="rohead">'+label+'</div>';
  document.getElementById('log').appendChild(d); scroll(); return d;
}
function esc(s){ return (s||'').replace(/</g,'&lt;'); }
function renderRunOut(box, r){
  const head = r.ok ? '<span class="ok">▶ ran</span>' : '<span class="bad">▶ exit '+r.exit_code+'</span>';
  let html = '<div class="rohead">'+head+' · '+r.seconds+'s</div>';
  if(r.stdout) html += '<pre class="rostd">'+esc(r.stdout)+'</pre>';
  if(r.stderr) html += '<pre class="roerr">'+esc(r.stderr)+'</pre>';
  if(!r.stdout && !r.stderr) html += '<div class="roempty">(no output)</div>';
  box.innerHTML = html; scroll();
}
async function runCode(){
  if(!editor) return; const code=editor.getValue(); if(!code.trim()) return;
  const box=addRunOut('<span class="dim">▶ running…</span>');
  try{
    const r=await (await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code})})).json();
    renderRunOut(box, r);
  }catch(e){ box.innerHTML='<div class="rohead bad">▶ could not run</div>'; }
}
(function(){const ta=document.getElementById('chatin');
  ta.addEventListener('input',()=>{ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,150)+'px';});
  ta.addEventListener('keydown',e=>{ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat();} });
})();

function flashSubmit(t){ const b=document.querySelector('button.submit'); if(b) b.textContent=t; }
function submitCode(){
  if(!editor) return; const code=editor.getValue().trim(); if(!code)return;
  if(streaming){ queuedSubmit=true; flashSubmit('✓ queued…'); return; }  // sends after the current reply, not silently dropped
  flashSubmit('✓ Submit code');
  const guarded = (mode!=='aiinterview' && mode!=='onboard');  // no anti-cheat in AI-interview or onboarding
  if(guarded && looksPasted(code, biggestPaste)){             // a big paste dominates → flag, but keep the code
    flagCheat('A full solution was pasted into the editor'); return;
  }
  if(guarded){
    fetch('/api/reclaim',{method:'POST'}).then(r=>r.json()).then(d=>{  // typed it yourself → reclaim
      if(d.reclaimed>0) showReclaim(d.reclaimed); setHud(d.stats); }).catch(()=>{});
  }
  biggestPaste = 0;
  const msg="Here is my code:\n```python\n"+code+"\n```";
  const body=addMsg('you','<pre><code class="language-python">'+code.replace(/</g,'&lt;')+'</code></pre>');
  body.querySelectorAll('pre code').forEach(c=>{try{hljs.highlightElement(c);}catch(e){}});  // only the new bubble
  lastSentCode = editor.getValue();   // the agent just saw this code — don't re-attach it next chat
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
  mode=document.getElementById('mode').value; thread=crypto.randomUUID(); biggestPaste=0; lastSentCode='';
  if(editor) editor.setValue(STUB);
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
    thread=id; mode=c.mode||mode; lastSentCode=''; document.getElementById('mode').value=mode; applyMode();
    const log=document.getElementById('log'); log.innerHTML='';
    for(const m of (c.transcript||[])){
      const b=addMsg(m.role==='you'?'you':'ai',''); b.innerHTML=renderMd(m.text);  // renderMd already highlights
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
  deathOnCheat = c.death_on_cheat !== false; updatePenaltyBtn();
  if(c.first_run){ mode='onboard'; document.getElementById('mode').value='onboard'; }  // new user → onboard, not "welcome back"
  applyMode();
  stream(c.kickoff[mode]);
});
</script></body></html>"""


# --- login page (multi-user) -----------------------------------------------
# Option E "cinematic forest" auth screen: a calm brand panel (the guru's vow + the lone
# archer silhouette) on the left, a focused email/password form on the right. Reuses the
# shared design system (/static/eklavya.css). The form action, field names, autofocus,
# {{error}} slot and "Sign in" affordance are all preserved for the auth flow + tests.
_LOGIN = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ekalavya — Sign in</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700;800;900&family=Marcellus&family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Spectral:ital,wght@0,300;0,400;0,500;0,600;1,400&family=Tiro+Devanagari+Hindi:ital@0;1&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/eklavya.css">
<style>
body{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:26px}
.authwrap{width:100%;max-width:960px;min-width:0}
.auth{border-radius:8px;overflow:hidden;border:1px solid var(--line-gold);box-shadow:var(--sh-deep);min-height:520px;min-width:0}
.auth>*{min-width:0}
.auth-form{max-width:none}
.auth-form form{display:flex;flex-direction:column}
.err{font-family:var(--f-mono);font-size:12px;letter-spacing:.02em;color:var(--vermilion-glow);
  border:1px solid rgba(214,59,42,.4);background:rgba(143,35,24,.16);border-radius:4px;
  padding:9px 12px;margin:0 0 16px}
@media(max-width:1000px){.auth{grid-template-columns:1fr}.auth-art{display:none}}
@media(max-width:560px){.auth-form .ah{font-size:24px}.authwrap{padding:0}}
</style></head><body>
<div class="authwrap">
<div class="auth">
  <div class="auth-art">
    <svg viewBox="0 0 400 560" preserveAspectRatio="xMidYMid slice" style="position:absolute;inset:0;width:100%;height:100%" aria-hidden="true">
      <defs>
        <linearGradient id="authbg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#0d1226"/><stop offset=".45" stop-color="#12172c"/>
          <stop offset=".78" stop-color="#0e1324"/><stop offset="1" stop-color="#0a0d1c"/>
        </linearGradient>
        <radialGradient id="authhaze" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#f7d98a" stop-opacity=".42"/><stop offset="1" stop-color="#e7b64b" stop-opacity="0"/></radialGradient>
        <radialGradient id="authhorizon" cx="50%" cy="100%" r="72%"><stop offset="0" stop-color="#26304f" stop-opacity=".55"/><stop offset="1" stop-color="#101528" stop-opacity="0"/></radialGradient>
        <linearGradient id="authridge" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1a2138"/><stop offset="1" stop-color="#0c1020"/></linearGradient>
        <linearGradient id="authskin" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c9855a"/><stop offset="1" stop-color="#9d6440"/></linearGradient>
        <radialGradient id="sunE" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#fff3c8"/><stop offset=".55" stop-color="#f7d98a"/><stop offset="1" stop-color="#b8862f"/></radialGradient>
        <radialGradient id="groundglow" cx="50%" cy="30%" r="70%"><stop offset="0" stop-color="rgba(231,182,75,.28)"/><stop offset="1" stop-color="rgba(231,182,75,0)"/></radialGradient>
        <linearGradient id="goldStroke" x1="0" x2="1"><stop offset="0" stop-color="#b8862f"/><stop offset=".5" stop-color="#f7d98a"/><stop offset="1" stop-color="#b8862f"/></linearGradient>
      </defs>
      <rect width="400" height="560" fill="url(#authbg)"/>
      <rect y="290" width="400" height="270" fill="url(#authhorizon)"/>
      <g fill="#f2e7cc">
        <circle cx="46" cy="62" r="1.5" opacity=".55"/><circle cx="112" cy="34" r="1.1" opacity=".38"/>
        <circle cx="168" cy="96" r="1.3" opacity=".45"/><circle cx="72" cy="146" r="1" opacity=".3"/>
        <circle cx="242" cy="42" r="1.2" opacity=".34"/><circle cx="352" cy="188" r="1.3" opacity=".4"/>
        <circle cx="24" cy="214" r="1" opacity=".26"/><circle cx="196" cy="168" r="1" opacity=".28"/>
        <circle cx="330" cy="252" r="1.1" opacity=".24"/><circle cx="128" cy="222" r="1.2" opacity=".3"/>
      </g>
      <g stroke="#8fa3c4" fill="none" opacity=".13" stroke-linecap="round">
        <path d="M-10 128 q60 -12 120 0 q54 11 108 -2" stroke-width="9"/>
        <path d="M150 206 q70 -14 140 2" stroke-width="7"/>
        <path d="M-20 262 q80 -10 150 4" stroke-width="6"/>
      </g>
      <circle cx="300" cy="78" r="92" fill="url(#authhaze)"/>
      <circle cx="300" cy="78" r="42" fill="url(#sunE)" opacity=".95"/>
      <g stroke="#f7d98a" stroke-width="1.6" opacity=".5" fill="none">
        <circle cx="300" cy="78" r="62"/><circle cx="300" cy="78" r="76" stroke-dasharray="3 8"/>
      </g>
      <path d="M-10 372 L58 330 L104 356 L152 318 L214 358 L268 332 L330 364 L410 336 L410 560 L-10 560 Z" fill="url(#authridge)" opacity=".85"/>
      <g stroke="#1d2b28" stroke-width="3" opacity=".7" fill="none">
        <path d="M40 372 v-26 M40 356 l-9 -8 M40 356 l9 -8 M40 344 l-7 -6 M40 344 l7 -6"/>
        <path d="M232 380 v-30 M232 362 l-10 -9 M232 362 l10 -9 M232 350 l-8 -7 M232 350 l8 -7"/>
        <path d="M352 386 v-24 M352 370 l-8 -7 M352 370 l8 -7"/>
      </g>
      <ellipse cx="200" cy="470" rx="210" ry="46" fill="url(#groundglow)" opacity=".5"/>
      <g stroke="#e7b64b" stroke-width="1" opacity=".16" fill="none"><circle cx="180" cy="404" r="150"/><circle cx="180" cy="404" r="108"/><circle cx="180" cy="404" r="66"/></g>
      <g transform="translate(150,366) scale(1.34)">
        <ellipse cx="4" cy="106" rx="30" ry="6" fill="#000" opacity=".38"/>
        <g transform="translate(-19,-6) rotate(-16)" opacity=".95">
          <path d="M0,3 l-6,38 l11,0 l6,-38 z" fill="#3a2f26" stroke="#b8862f" stroke-width=".7"/>
          <line x1="1" y1="1" x2="-1" y2="-13" stroke="#e8dcc0" stroke-width="1.4"/><path d="M-1 -13 l4 3 M-1 -13 l4 -1" stroke="#f7d98a" stroke-width="1.2" stroke-linecap="round"/>
          <line x1="6" y1="1" x2="5" y2="-11" stroke="#e8dcc0" stroke-width="1.4"/><path d="M5 -11 l4 3 M5 -11 l4 -1" stroke="#f7d98a" stroke-width="1.2" stroke-linecap="round"/>
        </g>
        <path d="M-2,0 C-16,1 -19,17 -17,35 L-14,80 L18,80 L19,35 C20,17 13,0 -2,0 Z" fill="#2f6b3c" stroke="#b8862f" stroke-width=".7"/>
        <g fill="#f2e7cc" opacity=".7"><circle cx="-5" cy="28" r="1.2"/><circle cx="7" cy="28" r="1.2"/><circle cx="1" cy="47" r="1.2"/><circle cx="-5" cy="60" r="1.2"/><circle cx="9" cy="60" r="1.2"/></g>
        <path d="M-9,78 C-12,92 -16,100 -20,104" stroke="#2a5c35" stroke-width="7" stroke-linecap="round" fill="none"/>
        <path d="M12,78 C15,92 19,98 24,102" stroke="#2f6b3c" stroke-width="7" stroke-linecap="round" fill="none"/>
        <path d="M-10,-13 C-11,-22 -5,-27 3,-27 C11,-27 16,-21 16,-13 C16,-7 12,-2 5,-1 L7,3 L2,2 C-5,1 -10,-6 -10,-13 Z" fill="url(#authskin)" stroke="#e7b64b" stroke-width=".8"/>
        <path d="M16,-14 l3.4,2.6 l-3.4,2.6" fill="none" stroke="#8f5432" stroke-width="1.1" stroke-linecap="round"/>
        <circle cx="9" cy="-15" r="1.7" fill="#241a0e"/>
        <path d="M5,-19 q4,-2 7,0" fill="none" stroke="#3a2f26" stroke-width="1.2" stroke-linecap="round"/>
        <path d="M-5,-24 C-14,-31 -21,-35 -28,-39 C-21,-35 -16,-29 -9,-26 Z" fill="#d63b2a" stroke="#8a5e1f" stroke-width=".5"/>
        <path d="M-3,-26 C-11,-35 -16,-39 -22,-43 C-15,-37 -11,-31 -5,-28 Z" fill="#e7b64b" stroke="#8a5e1f" stroke-width=".45" opacity=".9"/>
        <path d="M-8,-21 q8,-4 16,-2" fill="none" stroke="#8a5e1f" stroke-width="1.2"/>
        <path d="M4,17 C24,13 40,14 51,15" fill="none" stroke="#2f6b3c" stroke-width="7" stroke-linecap="round"/>
        <path d="M53,-38 C84,-21 84,52 53,68" fill="none" stroke="url(#goldStroke)" stroke-width="4.2"/>
        <circle cx="53" cy="15" r="4.4" fill="#b9764a" stroke="#8a5e1f" stroke-width=".5"/>
        <path d="M53,-38 L14,15 L53,68" fill="none" stroke="#f2e7cc" stroke-width="1.4"/>
        <line x1="6" y1="15" x2="74" y2="15" stroke="#e8dcc0" stroke-width="2.1"/>
        <path d="M80 15 l-10 -4 l2 4 l-2 4 z" fill="#f7d98a" stroke="#b8862f" stroke-width=".5"/>
        <path d="M6 15 l-9 -5 l4 5 l-4 5 z" fill="#57d3ce"/>
        <path d="M12 15 l-8 -4 M12 15 l-8 4" stroke="#f7d98a" stroke-width="1.4" stroke-linecap="round"/>
        <path d="M-2,21 C5,19 10,17 14,15" fill="none" stroke="#2f6b3c" stroke-width="7" stroke-linecap="round"/>
        <circle cx="14" cy="15" r="3.6" fill="#b9764a" stroke="#8a5e1f" stroke-width=".5"/>
      </g>
    </svg>
    <div class="aq">"You were refused a teacher. So become one to yourself — and shoot truer than the princes." <b>— The stone guru</b></div>
  </div>
  <div class="auth-form">
    <div class="ah">Welcome back, devotee</div>
    <div class="asub">The forest remembers where you left the string.</div>
    {{error}}
    <form method="post" action="/login">
      <div class="field"><label class="field-lbl" for="email">Email</label>
        <input id="email" class="inp" name="email" type="email" autocomplete="username" required autofocus></div>
      <div class="field"><label class="field-lbl" for="password">Password</label>
        <input id="password" class="inp" name="password" type="password" autocomplete="current-password" required></div>
      <button type="submit" class="btn btn-gold" style="width:100%;justify-content:center;margin-top:8px">Sign in — draw the string</button>
    </form>
  </div>
</div>
</div>
</body></html>"""


# --- public landing (brand mode, marketing) --------------------------------
# Reuses the Option-E landing markup: the outsider pitch as the anchor, one hero
# illustration (lone archer before the stone idol), one clear CTA, varied-weight feature
# cards. Sparing gold on the uniform indigo ground.
_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700;800;900'
    '&family=Marcellus&family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500'
    '&family=Spectral:ital,wght@0,300;0,400;0,500;0,600;1,400&family=Tiro+Devanagari+Hindi:ital@0;1'
    '&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
    '<link rel="stylesheet" href="/static/eklavya.css">'
)

_LANDING = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ekalavya — the archer who taught himself</title>
""" + _HEAD + r"""
<style>body{padding:0;min-height:100vh}.landing{min-height:100vh}</style></head><body>
<div class="landing">
  <div class="land-nav">
    <div class="brand"><svg width="22" height="26" viewBox="0 0 58 76"><path d="M14 6 C40 24 40 52 14 70" stroke="#e7b64b" stroke-width="3.4" stroke-linecap="round" fill="none"/><line x1="14" y1="6" x2="14" y2="70" stroke="#57d3ce" stroke-width="1.4"/><line x1="14" y1="38" x2="50" y2="38" stroke="#f7d98a" stroke-width="2"/><path d="M50 38 l-7 -5 M50 38 l-7 5" stroke="#f7d98a" stroke-width="2" stroke-linecap="round"/></svg> EKALAVYA</div>
    <div class="links"><span>The Method</span><span>Skill Forest</span><span>Manifesto</span></div>
    <span style="flex:1"></span>
    <a class="btn btn-ghost" style="padding:9px 18px" href="/login">Log in</a>
    <a class="btn btn-stone" style="padding:9px 20px" href="/">Begin your svādhyāya</a>
  </div>
  <div class="land-hero">
    <div>
      <div class="hero-tag" style="margin-bottom:16px">एकलव्य · the archer who taught himself</div>
      <h1 class="land-h1">The hall was closed to him.<br><span class="em">So he taught himself to outshoot the princes.</span></h1>
      <p class="land-lead">An AI coding tutor for <b>the self-taught, the boundary-crossers, the ones told they couldn't be taught.</b> It grades what you can do <i>unaided</i> — no hints you didn't earn, no pasted answers, just the string drawn until the arrow flies true.</p>
      <div class="btn-row">
        <a class="btn btn-gold" href="/">Enter the forest — free</a>
        <a class="btn btn-stone" href="/welcome#method">See the method</a>
      </div>
      <div class="land-proof">
        <div class="pp"><div class="v">197</div><div class="k">skill nodes</div></div>
        <div class="pp"><div class="v">unaided</div><div class="k">honest grading</div></div>
        <div class="pp"><div class="v">17</div><div class="k">learning groves</div></div>
      </div>
    </div>
    <div class="land-art">
      <svg viewBox="0 0 460 340" preserveAspectRatio="xMidYMid slice" style="width:100%;height:100%;display:block" aria-label="A lone archer before a stone idol under a spinning sun.">
        <defs><linearGradient id="lskyA" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#101528"/><stop offset="1" stop-color="#0a0d1c"/></linearGradient>
          <radialGradient id="lsunA" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#fff3c8"/><stop offset=".6" stop-color="#f7d98a"/><stop offset="1" stop-color="#b8862f"/></radialGradient>
          <radialGradient id="groundglow" cx="50%" cy="30%" r="70%"><stop offset="0" stop-color="rgba(231,182,75,.28)"/><stop offset="1" stop-color="rgba(231,182,75,0)"/></radialGradient>
          <linearGradient id="goldStroke" x1="0" x2="1"><stop offset="0" stop-color="#b8862f"/><stop offset=".5" stop-color="#f7d98a"/><stop offset="1" stop-color="#b8862f"/></linearGradient></defs>
        <rect width="460" height="340" fill="url(#lskyA)"/>
        <circle cx="380" cy="72" r="40" fill="url(#lsunA)"/>
        <g stroke="#f7d98a" stroke-width="1.6" opacity=".7"><path d="M380 18 v14 M380 112 v14 M326 72 h14 M420 72 h14 M342 34 l10 10 M408 100 l10 10 M418 34 l-10 10 M352 100 l-10 10"/></g>
        <ellipse cx="230" cy="272" rx="230" ry="42" fill="url(#groundglow)" opacity=".8"/>
        <g transform="translate(96,150)"><rect x="-22" y="76" width="44" height="14" rx="2" fill="#4a3f36"/><path d="M0,4 C-13,4 -18,20 -16,38 L-14,74 L14,74 L16,38 C18,20 13,4 0,4Z" fill="#7e6a5a"/><circle cx="0" cy="-8" r="12" fill="#9a8574"/></g>
        <g transform="translate(210,170)"><path d="M-1,0 C-11,0 -13,12 -11,24 L-9,58 L13,58 L13,24 C14,12 9,0 -1,0Z" fill="#2f6b3c"/><path d="M-7,-9 C-8,-16 -3,-19 3,-19 C9,-19 11,-14 11,-9 C11,-4 7,0 1,0 C-4,0 -7,-4 -7,-9Z" fill="#b9764a"/><circle cx="6" cy="-10" r="1.3" fill="#241a0e"/><path d="M-4,-17 C-11,-22 -16,-25 -20,-28" stroke="#d63b2a" stroke-width="2.4" stroke-linecap="round"/><path d="M40,-28 C66,-5 66,33 40,50" fill="none" stroke="url(#goldStroke)" stroke-width="3"/><line x1="40" y1="-28" x2="40" y2="50" stroke="#f2e7cc" stroke-width="1"/><path d="M2,14 C22,10 34,10 40,12" stroke="#2f6b3c" stroke-width="5.5" stroke-linecap="round"/></g>
        <g transform="translate(410,190)"><line x1="0" y1="10" x2="0" y2="90" stroke="#b8862f" stroke-width="2.4"/><circle r="24" fill="#151b0f" stroke="#e7b64b" stroke-width="1.6"/><circle r="16" fill="none" stroke="#f2e7cc" stroke-width="1.4"/><circle r="7" fill="#d63b2a"/><g><line x1="-52" y1="0" x2="-2" y2="0" stroke="#e8dcc0" stroke-width="1.8"/><path d="M2 0 l-8 -4 l2 4 l-2 4z" fill="#f7d98a"/><path d="M-52 0 l-7 -4 l3 4 l-3 4z" fill="#57d3ce"/></g></g>
      </svg>
    </div>
  </div>
  <div class="land-feats" id="method">
    <div class="frame feat big"><div class="corner-tr"></div><div class="corner-bl"></div>
      <div class="fi"><svg width="26" height="26" viewBox="0 0 24 24" fill="none"><path d="M4 12 C10 7 14 7 20 12 C14 17 10 17 4 12" stroke="#f7d98a" stroke-width="1.6"/><line x1="4" y1="12" x2="20" y2="12" stroke="#f7d98a" stroke-width="1.6"/><path d="M20 12 l-5 -3 M20 12 l-5 3" stroke="#f7d98a" stroke-width="1.6"/></svg></div>
      <h4>Grades what you can do alone</h4><p>Ekalavya measures your <b>unaided</b> accuracy and separates it from AI-assisted — so you always know your real, portable skill. Paste a full answer and the round is lost; type it yourself and reclaim your merit.</p></div>
    <div class="frame feat"><div class="corner-tr"></div><div class="corner-bl"></div>
      <div class="fi"><svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M12 3 L20 8 V16 L12 21 L4 16 V8 Z" stroke="#e7b64b" stroke-width="1.6"/></svg></div>
      <h4>A forest to walk</h4><p>17 learning groves on a winding path — not a 197-node hairball. Master one, the next lights up.</p></div>
    <div class="frame feat"><div class="corner-tr"></div><div class="corner-bl"></div>
      <div class="fi"><svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M6 4h11a2 2 0 0 1 2 2v14H8a2 2 0 0 1-2-2z" stroke="#57d3ce" stroke-width="1.6"/></svg></div>
      <h4>A guru that writes</h4><p>Lessons, diagrams, and interactive visuals authored right in your canvas — and saved to a library you revisit.</p></div>
  </div>
</div>
</body></html>"""


# --- canvas / artifacts shell (product mode, scaffold) ---------------------
_CANVAS = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ekalavya — Canvas</title>
""" + _HEAD + r"""
<style>body{padding:26px 20px 60px}.canvas-wrap{max-width:1080px;margin:0 auto}
.pa-right{border:1px solid var(--line-gold);border-radius:8px;overflow:hidden;box-shadow:var(--sh-deep)}</style></head><body>
<div class="canvas-wrap">
  <div class="screen-label" style="margin-bottom:12px">Canvas &amp; Artifacts <b>· the guru writes, you keep it</b> <span class="mode-badge product">product mode</span></div>
  <div class="pa-right">
    <div class="pa-toolbar">
      <div class="seg" role="tablist" aria-label="Right pane"><span role="tab">▤ Editor</span><span class="on" role="tab" aria-selected="true">✦ Canvas</span></div>
      <span class="grow"></span>
      <span class="tbtn">+ New artifact</span><span class="tbtn submit">↓ Save to library</span>
    </div>
    <div class="canvas">
      <div class="canvas-tabs">
        <span class="artpill on"><span class="k">◆</span> Recursion, illustrated</span>
        <span class="artpill"><span class="k">▶</span> tree_traversal.py</span>
        <span class="artpill"><span class="k">◈</span> call-stack visual</span>
        <span class="artpill"><span class="k">□</span> preview.html</span>
      </div>
      <div class="canvas-body">
        <div class="art-md">
          <h3>Recursion, illustrated</h3>
          <div class="adeva">पुनरावृत्ति · the return upon itself</div>
          <p>A recursive function trusts a <b>smaller copy of itself</b> to solve the smaller problem, then combines. Every recursion needs two things: a <b>base case</b> that stops the descent, and a step that moves <b>toward</b> it.</p>
          <p>In tree traversal, the <i>order</i> you visit the parent decides everything. In post-order you defer the parent until <span class="selraw">both children are done</span> — which is how you free a subtree or compute its size bottom-up.</p>
          <div class="callout">"You are not writing a loop that repeats. You are writing a promise that trusts a smaller you." — the stone guru</div>
          <div style="margin:18px 0 6px;font-family:var(--f-mono);font-size:10px;letter-spacing:var(--ls-label);text-transform:uppercase;color:var(--vermilion-glow)">◈ interactive · call-depth vs. work</div>
          <svg viewBox="0 0 460 170" style="width:100%;border:1px solid var(--line-soft);border-radius:8px;background:rgba(6,9,20,.5)" aria-label="An interactive chart of recursion call depth versus total work.">
            <defs><linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f7d98a"/><stop offset="1" stop-color="#b8862f"/></linearGradient></defs>
            <g stroke="rgba(231,182,75,.12)" stroke-width="1"><line x1="30" y1="30" x2="440" y2="30"/><line x1="30" y1="80" x2="440" y2="80"/><line x1="30" y1="130" x2="440" y2="130"/></g>
            <g fill="url(#barGrad)"><rect x="46" y="118" width="26" height="12" rx="3"/><rect x="106" y="100" width="26" height="30" rx="3"/><rect x="166" y="74" width="26" height="56" rx="3"/><rect x="226" y="52" width="26" height="78" rx="3"/><rect x="286" y="66" width="26" height="64" rx="3"/><rect x="346" y="96" width="26" height="34" rx="3"/><rect x="406" y="116" width="26" height="14" rx="3"/></g>
            <path d="M59 120 C120 92 150 60 239 44 C300 34 340 70 419 118" fill="none" stroke="#57d3ce" stroke-width="2"/>
            <circle cx="239" cy="44" r="5" fill="#f7d98a" stroke="#101528" stroke-width="1.5"/>
            <text x="239" y="30" text-anchor="middle" font-family="JetBrains Mono" font-size="9" fill="#f7d98a">n=4 · peak depth</text>
            <g font-family="JetBrains Mono" font-size="8" fill="#a89670"><text x="59" y="148">n1</text><text x="239" y="148">n4</text><text x="419" y="148">n7</text></g>
          </svg>
          <p style="font-family:var(--f-mono);font-size:12px;color:var(--parch-dim);margin-top:8px">Charts, diagrams, and interactive widgets render right here — so Ekalavya can teach a subject <b style="color:var(--gold-bright);font-family:var(--f-body)">visually</b>, not just in prose. <i>(Full authoring wiring lands in a later task.)</i></p>
        </div>
      </div>
    </div>
  </div>
</div>
</body></html>"""
