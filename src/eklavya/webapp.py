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


def client_ip(request) -> str:
    """The client IP to key login throttling on.

    Behind a trusted reverse proxy (EKLAVYA_TRUST_PROXY set), ``request.client.host`` is
    the proxy's own address, so every user would share one throttle bucket. In that case we
    read the real client from the left-most entry of ``X-Forwarded-For`` (the original
    client; each hop appends its own). We only trust the header when the flag is set —
    otherwise a direct client could spoof it — and fall back to ``request.client.host``
    whenever the header is absent or empty.
    """
    from . import config

    direct = request.client.host if request.client else ""
    if config.TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for", "")
        first = xff.split(",")[0].strip()
        if first:
            return first
    return direct


def create_app():
    from pathlib import Path

    from fastapi import FastAPI, File, Request, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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

    def _active_provider():
        """The provider to use for this user: their saved Settings choice if it's
        configured, else the constructed default (auto-picked)."""
        from . import settings

        chosen = settings.get_provider()
        if chosen:
            try:
                p = pick(chosen)
                if p.is_configured():
                    return p
            except KeyError:
                pass
        return provider

    def agent_for(mode: str, user_id: str | None = None):
        mode = mode if mode in _PROMPTS else "practice"
        uid = user_id or _current_user_id()
        prov = _active_provider()
        key = (uid, mode, prov.key)   # provider in the key → switching rebuilds the agent
        if key not in agents:
            tools = _TOOLS.get(mode, SESSION_TOOLS)
            agents[key] = build_agent(_PROMPTS[mode], tools, provider=prov.key)
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

    @app.get("/favicon.ico")
    def favicon():
        from starlette.responses import Response
        return Response(status_code=204)  # no icon yet; silence the browser's auto-404

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

    @app.get("/api/forest")
    def forest(pillar: str = "") -> dict:
        return report.forest_map(pillar or None)

    @app.get("/api/config")
    def cfg() -> dict:
        from . import settings

        prov = _active_provider()
        return {"provider": prov.label, "model": prov.default_model,
                "kickoff": _KICKOFF, "configured": prov.is_configured(),
                "first_run": report.is_first_run(),
                "death_on_cheat": settings.get_death_on_cheat()}

    @app.get("/api/settings")
    def settings_get() -> dict:
        from . import providers, settings

        s = settings.get_all()
        # the full provider catalogue (key + label + whether a key is set), so the
        # selector can list glm/minimax/qwen/kimi and mark the configured ones.
        provs = [{"key": p.key, "label": p.label, "configured": p.is_configured()}
                 for p in providers.PROVIDERS.values()]
        return {**s, "providers": provs, "active_provider": _active_provider().key}

    @app.put("/api/settings")
    async def settings_put(request: Request):
        from . import settings

        body = await request.json()
        # legacy shape ({"death_on_cheat": bool}) still works; new keys are optional.
        updated = settings.update(
            death_on_cheat=body.get("death_on_cheat"),
            reduced_motion=body.get("reduced_motion"),
            guru_voice=body.get("guru_voice"),
            provider=body.get("provider"),
        )
        return {**updated, "active_provider": _active_provider().key}

    def _events(agent, config, thread, inputs):
        """One agent run (a new turn OR a resume): route tool activity to the trace,
        stream the reply, and pause for run_bash approval."""
        from .verify import selfcheck

        try:  # the learner's message (a fresh turn) → context for the judge; "" on resume
            user_context = inputs["messages"][0]["content"] if isinstance(inputs, dict) else ""
        except (KeyError, IndexError, TypeError):
            user_context = ""
        buf = []
        run_outputs = []  # actual sandbox/run tool results this turn → context for the judge
        _RUN_TOOLS = {"run_bash", "grade_and_record"}  # tools whose output is real execution
        try:
            for chunk, _meta in agent.stream(inputs, config=config, stream_mode="messages"):
                # deepagents' documented routing: tool result / tool call → trace;
                # the assistant's own text (an AI chunk with no tool call) → the bubble.
                if getattr(chunk, "type", None) == "tool":
                    name = getattr(chunk, "name", "") or ""
                    content = str(chunk.content)
                    if name in _RUN_TOOLS:  # capture what the code actually printed/returned
                        run_outputs.append(f"[{name}] {content[:1000]}")
                    yield json.dumps({"result": {"name": name,
                                                 "content": content[:400]}}) + "\n"
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

        # Enrich the judge's context with what the code ACTUALLY did this turn, so it can
        # catch a reply that contradicts the real run output (e.g. "this prints 5" when the
        # sandbox printed 6). The run output leads, so it survives selfcheck's own context
        # truncation; each tool result is already capped above.
        judge_context = user_context
        if run_outputs:
            judge_context = ("ACTUAL CODE EXECUTION OUTPUT THIS TURN (from the sandbox — "
                             "trust this over the tutor's claims):\n"
                             + "\n".join(run_outputs)
                             + f"\n\nLEARNER MESSAGE / SITUATION:\n{user_context}")
        note = selfcheck("".join(buf), context=judge_context)  # context-aware second-model review
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
        if mode in ("practice", "mock", "aiinterview", "takehome"):
            # A practice session is beginning: kick off a throttled, background,
            # offline-safe refresh of this user's question bank toward their targets.
            # Non-blocking and never-raising — it can't delay the stream or the first token.
            from .questions_refresh import maybe_autorefresh

            try:
                maybe_autorefresh()
            except Exception:
                pass
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

    @app.post("/api/truncate")
    async def truncate(request: Request):
        """Rewind a thread's conversation to keep only the first N user turns.

        Backs the arena's rewind + edit controls: to drop the last exchange the client
        asks to keep (user_turns-1); to edit turn k it asks to keep k-1, then re-streams
        the edited message. We remove every message from the (keep+1)-th human message
        onward via the add_messages reducer's RemoveMessage, so the durable checkpointer
        state matches what the learner now sees. Idempotent; a no-op if nothing to drop.
        """
        from starlette.concurrency import run_in_threadpool

        from langchain_core.messages import RemoveMessage

        body = await request.json()
        mode = body.get("mode", "practice")
        thread = body.get("thread") or ""
        _require_owner(thread)
        keep = max(0, int(body.get("keep_user_turns", 0)))
        agent = agent_for(mode)
        config = {"configurable": {"thread_id": thread}}

        def _do():
            state = agent.get_state(config)
            messages = (state.values or {}).get("messages", []) or []
            seen = 0
            cut = None  # index of the first message to drop
            for i, m in enumerate(messages):
                if getattr(m, "type", None) == "human":
                    seen += 1
                    if seen == keep + 1:
                        cut = i
                        break
            if cut is None:
                return 0  # fewer turns than asked to keep → nothing to remove
            drop = [RemoveMessage(id=m.id) for m in messages[cut:] if getattr(m, "id", None)]
            if drop:
                agent.update_state(config, {"messages": drop})
            return len(drop)

        removed = await run_in_threadpool(_do)
        return {"ok": True, "removed": removed}

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

    @app.post("/api/upload-resume")
    async def upload_resume(file: UploadFile = File(...)):
        """Accept a résumé / LinkedIn PDF, extract its text, and store it in the current
        user's workspace so onboarding can ground itself in real experience.

        Untrusted input: we enforce a content-type + size cap, extract TEXT ONLY (never
        execute anything), cap the stored length, and write into the per-user workspace
        (auth middleware binds the contextvar in multi-user mode)."""
        from starlette.concurrency import run_in_threadpool

        from . import resume

        _MAX_BYTES = 8 * 1024 * 1024  # 8 MB cap
        ctype = (file.content_type or "").lower()
        name = (file.filename or "").lower()
        if ctype != "application/pdf" and not name.endswith(".pdf"):
            return JSONResponse({"ok": False, "error": "Please upload a PDF file."},
                                status_code=415)
        data = await file.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            return JSONResponse({"ok": False, "error": "File too large (max 8 MB)."},
                                status_code=413)

        text = await run_in_threadpool(resume.extract_pdf_text, data)
        if text.startswith("error:"):
            return JSONResponse({"ok": False, "error": text[len("error:"):].strip()},
                                status_code=422)
        await run_in_threadpool(resume.save_resume, text)
        return {"ok": True, "chars": len(text)}

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

    # --- canvas artifacts (per-user) ---------------------------------------
    # The tutor's durable lessons/code/HTML/visuals. Per-user via the contextvar the auth
    # middleware binds (single-user resolves to the one implicit user). All CRUD.
    @app.get("/api/artifacts")
    def artifacts_list(kind: str = "", q: str = "") -> list:
        from . import artifacts

        return artifacts.list_artifacts(kind=kind or None, query=q or None)

    @app.post("/api/artifacts")
    async def artifacts_create(request: Request):
        from . import artifacts

        body = await request.json()
        return artifacts.create(body.get("title", "Untitled"),
                                body.get("kind", "markdown"), body.get("content", ""))

    @app.get("/api/artifacts/{artifact_id}")
    def artifacts_get(artifact_id: int):
        from fastapi import HTTPException

        from . import artifacts

        a = artifacts.get(artifact_id)
        if a is None:
            raise HTTPException(status_code=404)
        return a

    @app.patch("/api/artifacts/{artifact_id}")
    async def artifacts_update(artifact_id: int, request: Request):
        from fastapi import HTTPException

        from . import artifacts

        body = await request.json()
        a = artifacts.update(artifact_id, title=body.get("title"), kind=body.get("kind"),
                             content=body.get("content"), pinned=body.get("pinned"))
        if a is None:
            raise HTTPException(status_code=404)
        return a

    @app.delete("/api/artifacts/{artifact_id}")
    def artifacts_delete(artifact_id: int):
        from fastapi import HTTPException

        from . import artifacts

        if not artifacts.delete(artifact_id):
            raise HTTPException(status_code=404)
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
        ip = client_ip(request)  # real client behind a trusted proxy; else request.client.host
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
<link rel="stylesheet" href="/static/fonts.css">
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
main{flex:1;min-height:0;display:grid;grid-template-columns:auto 1fr}
/* ashram left rail (template D): Practice/Progress/Forest Map/Library/Settings + mini-HUD title */
#prail{width:168px;border-right:1px solid var(--line-soft);padding:16px 12px;display:flex;flex-direction:column;gap:4px;background:rgba(6,9,20,.4)}
#prail .rail-item{display:flex;align-items:center;gap:10px;font-family:var(--f-title);font-size:14px;color:var(--parch-dim);
 padding:9px 11px;border-radius:6px;cursor:pointer;border:1px solid transparent;transition:.14s}
#prail .rail-item:hover{color:var(--gold-bright);background:rgba(6,9,20,.4)}
#prail .rail-item.on{color:var(--gold-bright);background:rgba(231,182,75,.08);border-color:var(--line-gold)}
#prail .rail-item svg{flex:none}
#prail .rail-mini-hud{margin-top:auto;padding:12px 11px 4px;border-top:1px solid var(--line-soft)}
#prail .rmh-name{font-family:var(--f-title);font-size:13px;color:var(--parch)}
#prail .rmh-title{font-family:var(--f-mono);font-size:10px;color:var(--parch-mute);letter-spacing:.1em;text-transform:uppercase;margin-top:2px}
#content{min-height:0;min-width:0;position:relative}
#practice{display:grid;grid-template-columns:1fr 1fr;height:100%}
@media(max-width:900px){#practice{grid-template-columns:1fr;grid-template-rows:1fr 1fr}}
#practice.nocode{grid-template-columns:1fr;grid-template-rows:1fr}       /* editor hidden → chat full width */
#practice.nocode > .col:not(.chat){display:none}
#practice.nocode > .col.chat{border-right:none}
.col{display:flex;flex-direction:column;min-height:0;min-width:0}
.col.chat{border-right:1px solid var(--line-soft)}
.log{flex:1;overflow-y:auto;padding:18px 20px;display:flex;flex-direction:column;gap:14px}
/* empty/loading state for the chat column — never a blank void before the first drill */
.arena-welcome{margin:auto;max-width:340px;text-align:center;padding:32px 20px;animation:fadein .6s ease}
.arena-welcome .aw-mark{opacity:.9;filter:drop-shadow(0 0 14px rgba(231,182,75,.25))}
.arena-welcome .aw-deva{font-family:var(--f-deva);font-size:26px;color:var(--gold);letter-spacing:.08em;margin:10px 0 2px}
.arena-welcome .aw-title{font-family:var(--f-display);font-weight:700;font-size:18px;color:var(--parch);letter-spacing:.03em}
.arena-welcome .aw-sub{font-family:var(--f-body);font-size:13.5px;color:var(--parch-mute);margin-top:8px;line-height:1.5}
.arena-welcome .aw-dots{display:flex;gap:6px;justify-content:center;margin-top:16px}
.arena-welcome .aw-dots span{width:6px;height:6px;border-radius:50%;background:var(--gold);opacity:.35;animation:awpulse 1.2s ease-in-out infinite}
.arena-welcome .aw-dots span:nth-child(2){animation-delay:.2s}
.arena-welcome .aw-dots span:nth-child(3){animation-delay:.4s}
@keyframes awpulse{0%,100%{opacity:.25;transform:scale(.85)}50%{opacity:1;transform:scale(1)}}
/* onboarding threshold (template C) — a framed "Cross the threshold / प्रवेश" intro */
.onb-threshold{position:relative;text-align:center;margin:6px 0 4px;padding:30px 26px 26px;border:1px solid var(--line-gold);border-radius:8px;
 background:linear-gradient(160deg,rgba(35,29,24,.55),rgba(10,14,26,.65));box-shadow:var(--sh-deep);overflow:hidden;animation:fadein .6s ease}
.onb-threshold::before,.onb-threshold::after{content:"";position:absolute;width:16px;height:16px;border:1.5px solid var(--gold);opacity:.6}
.onb-threshold::before{top:9px;left:9px;border-right:0;border-bottom:0}
.onb-threshold::after{bottom:9px;right:9px;border-left:0;border-top:0}
.onb-threshold .onb-eye{font-family:var(--f-mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--peacock-bright);margin-bottom:12px}
.onb-threshold .onb-h{font-family:var(--f-display);font-weight:800;font-size:clamp(24px,4vw,34px);color:var(--parch);line-height:1.08}
.onb-threshold .onb-h .em{color:var(--gold-bright)}
.onb-threshold .onb-deva{font-family:var(--f-deva);font-size:20px;color:var(--gold-bright);margin-top:8px}
.onb-threshold .onb-sub{font-family:var(--f-body);font-size:14.5px;color:var(--parch-dim);max-width:52ch;margin:14px auto 0;line-height:1.55}
.onb-steps{display:flex;gap:8px;justify-content:center;margin:16px auto 0}
.onb-steps i{width:34px;height:4px;border-radius:2px;background:var(--line-soft)}
.onb-steps i.on{background:linear-gradient(90deg,var(--gold-deep),var(--gold-bright))}
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
.mermaid svg{max-width:100% !important;height:auto}
#tree .mermaid{background:transparent;border:0}#tree .mermaid svg{max-width:100% !important;height:auto}
.resumebar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:9px 12px 0}
.resumebar.hidden{display:none}
.resumehint{font-family:var(--f-body);font-size:11.5px;color:var(--parch-mute);opacity:.85}
.resumehint.ok{color:var(--peacock-bright);opacity:1}
.resumehint.bad{color:#e08a7a;opacity:1}
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
/* conversation controls (#36): rewind button + per-message edit + Esc-cancel note */
button.rewind{font-family:var(--f-mono);letter-spacing:.08em;text-transform:uppercase;font-size:11px;
 background:rgba(6,9,20,.5);color:var(--parch-dim);border:1px solid var(--line-gold);border-radius:4px;
 padding:0 12px;cursor:pointer;transition:.16s;white-space:nowrap}
button.rewind:hover{color:var(--gold-bright);border-color:var(--gold-deep);background:rgba(231,182,75,.08)}
button.rewind:disabled{opacity:.4;cursor:default}
.msg.you{position:relative}
.msg.you .editbtn{position:absolute;top:-9px;right:8px;font-family:var(--f-mono);font-size:10px;letter-spacing:.08em;
 text-transform:uppercase;color:var(--peacock-bright);background:rgba(6,9,20,.9);border:1px solid rgba(46,163,160,.4);
 border-radius:4px;padding:2px 8px;cursor:pointer;opacity:0;transition:.16s}
.msg.you:hover .editbtn{opacity:1}
.msg.you .editbtn:hover{color:var(--peacock-bright);border-color:var(--peacock)}
.msg.you.editing{outline:1px dashed var(--gold-deep);outline-offset:3px}
.msg.you .editarea{width:100%;min-height:60px;background:rgba(6,9,20,.7);border:1px solid var(--line-gold);border-radius:6px;
 color:var(--parch);padding:9px 11px;font-family:var(--f-body);font-size:14px;resize:vertical;outline:none}
.msg.you .editbtns{display:flex;gap:8px;margin-top:8px}
.msg.you .editbtns button{font-family:var(--f-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;
 border-radius:4px;padding:5px 12px;cursor:pointer;border:1px solid var(--line-gold);background:rgba(6,9,20,.5);color:var(--parch-dim)}
.msg.you .editbtns button.save{color:var(--gold-bright);border-color:var(--gold-deep);background:rgba(231,182,75,.1)}
.cancelnote{font-family:var(--f-mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--parch-mute);margin-top:8px;opacity:.75}
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
/* themed error card (template §5): "The arrow found no wind" + Retry */
.errcard{align-self:stretch;display:flex;flex-direction:column;align-items:center;text-align:center;gap:8px;
 border:1px solid rgba(214,59,42,.4);border-radius:12px;background:rgba(20,8,6,.55);padding:20px 18px}
.errcard svg{opacity:.9}
.errcard .ek{font-family:var(--f-mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--vermilion-glow)}
.errcard .et{font-family:var(--f-display);font-weight:700;font-size:17px;color:var(--parch)}
.errcard .ed{font-family:var(--f-body);font-size:13px;color:var(--parch-dim);max-width:320px;line-height:1.5}
.errcard button{margin-top:4px;font-family:var(--f-title);font-size:13px;letter-spacing:.02em;color:var(--gold-bright);
 background:rgba(231,182,75,.08);border:1px solid var(--gold-deep);border-radius:4px;padding:8px 18px;cursor:pointer}
.errcard button:hover{background:rgba(231,182,75,.16)}
/* live test-arrow panel (template D's .ed-tests) — per-check pass/fail below the editor */
.ed-tests{border-top:1px solid var(--line-gold);background:rgba(6,9,20,.62);display:flex;flex-direction:column;flex:none;max-height:38%;overflow-y:auto}
.ed-tests-h{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;
 font-family:var(--f-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--parch-dim)}
.ed-tests-h .et-count{color:var(--peacock-bright);letter-spacing:.06em}
.ed-tests-h .et-count b{color:var(--gold-bright);font-size:12px}
.ed-test{display:flex;align-items:center;gap:11px;padding:9px 16px;border-top:1px solid var(--line-soft)}
.ed-test .et-i{flex:none;width:20px;height:20px;border-radius:50%;display:grid;place-items:center}
.ed-test.pass .et-i{color:#2a1c07;background:radial-gradient(circle,var(--gold-bright),var(--gold-deep));box-shadow:0 0 10px rgba(231,182,75,.35)}
.ed-test.fail .et-i{color:var(--vermilion-glow);border:1px solid rgba(214,59,42,.55);background:rgba(143,35,24,.22)}
.ed-test .et-n{flex:1;font-family:var(--f-body);font-size:14px;color:var(--parch)}
.ed-test.fail .et-n{color:var(--parch-dim)}
.ed-test .et-t{font-family:var(--f-mono);font-size:10px;letter-spacing:.06em;color:var(--parch-mute)}
.ed-test.fail .et-t{color:var(--vermilion-glow)}
.ed-tests-f{display:flex;align-items:center;gap:12px;padding:12px 16px;border-top:1px solid var(--line-soft);flex-wrap:wrap}
.ed-tests-f .et-hint{flex:1;min-width:180px;font-family:var(--f-serif);font-style:italic;font-size:14px;color:var(--parch-dim)}
.ed-tests-f .et-hint code{font-family:var(--f-mono);font-size:12px;color:var(--peacock-bright);font-style:normal}
/* Editor↔Canvas segmented control (template D) */
.seg{display:flex;gap:3px;border:1px solid var(--line-soft);border-radius:6px;padding:3px;background:rgba(6,9,20,.5)}
.seg span{font-family:var(--f-mono);font-size:11px;letter-spacing:.06em;padding:6px 13px;border-radius:4px;color:var(--parch-dim);display:flex;align-items:center;gap:6px;cursor:pointer}
.seg span.on{background:linear-gradient(180deg,rgba(231,182,75,.16),rgba(20,15,10,.7));color:var(--gold-bright)}
/* Canvas panel — the guru's rendered artifact (template E), inside the right pane */
#canvaspane{flex:1;display:none;flex-direction:column;min-height:0}
.col.canvasmode #editor,.col.canvasmode #edtests{display:none}
.col.canvasmode #canvaspane{display:flex}
.canvas-tabs{display:flex;gap:4px;padding:8px 12px;border-bottom:1px solid var(--line-soft);align-items:center;overflow-x:auto}
.artpill{font-family:var(--f-mono);font-size:11px;padding:5px 11px;border-radius:20px;border:1px solid var(--line-soft);color:var(--parch-dim);white-space:nowrap;display:inline-flex;gap:6px;align-items:center;cursor:pointer}
.artpill:hover{color:var(--gold-bright)} .artpill.on{border-color:var(--gold-deep);color:var(--gold-bright);background:rgba(231,182,75,.08)}
.artpill .k{opacity:.6}
.canvas-body{flex:1;padding:20px 24px;overflow:auto;position:relative}
.art-md h3{font-family:var(--f-display);font-weight:700;font-size:22px;color:var(--parch);margin:0 0 4px}
.art-md .adeva{font-family:var(--f-deva);font-size:15px;color:var(--gold-bright);margin-bottom:16px}
.art-md p{font-family:var(--f-body);font-size:15px;color:var(--parch-dim);line-height:1.65;margin:0 0 14px}
.art-md p b{color:var(--parch)} .art-md h1,.art-md h2{font-family:var(--f-display);color:var(--parch);margin:14px 0 6px}
.art-md .callout,.art-md blockquote{border-left:2px solid var(--gold);padding:10px 16px;background:rgba(231,182,75,.05);border-radius:0 6px 6px 0;font-family:var(--f-serif);font-style:italic;color:var(--parch);margin:14px 0}
.art-md pre{background:rgba(6,9,16,.85) !important;border:1px solid var(--line-soft);border-radius:8px;padding:12px;overflow-x:auto}
.art-md code{font-family:var(--f-mono);font-size:13px;color:var(--peacock-bright)}
.selpop{position:absolute;z-index:5;background:linear-gradient(180deg,var(--stone-warm),var(--stone-dark));border:1px solid var(--gold);border-radius:20px;padding:7px 14px;font-family:var(--f-title);font-size:13px;color:var(--gold-bright);box-shadow:0 10px 26px -8px rgba(0,0,0,.7);display:none;gap:8px;align-items:center;white-space:nowrap;cursor:pointer}
.selpop.on{display:inline-flex;animation:pop .18s ease}
.selpop::after{content:"";position:absolute;bottom:-6px;left:26px;width:10px;height:10px;background:var(--stone-dark);border-right:1px solid var(--gold);border-bottom:1px solid var(--gold);transform:rotate(45deg)}
.art-code{font-family:var(--f-mono);font-size:13px;line-height:1.7;background:rgba(6,9,16,.85);border:1px solid var(--line-soft);border-radius:8px;padding:16px;white-space:pre-wrap;overflow:auto;color:var(--parch)}
.art-html{border:1px solid var(--line-gold);border-radius:8px;overflow:hidden;background:#fff}
.art-htmlbar{font-family:var(--f-mono);font-size:10px;letter-spacing:.06em;color:var(--parch-dim);padding:6px 12px;background:rgba(6,9,20,.7);border-bottom:1px solid var(--line-soft)}
.art-htmlprev{padding:20px;background:linear-gradient(160deg,#fbf6ea,#efe4c9);color:#2a2010;font-family:var(--f-serif)}
.art-viz{border:1px solid var(--line-soft);border-radius:8px;background:rgba(6,9,20,.5);padding:14px}
.art-viz svg{width:100%;height:auto}
.canvas-empty{color:var(--parch-dim);font-family:var(--f-body);text-align:center;padding:50px 20px}
/* highlight-to-ask echo in chat (template D's .art-echo) */
.art-echo{display:flex;gap:8px;align-items:flex-start;border-left:2px solid var(--gold);padding:8px 12px;background:rgba(231,182,75,.06);border-radius:0 6px 6px 0;margin-bottom:8px;max-width:86%;align-self:flex-end}
.art-echo .lbl{font-family:var(--f-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--gold);margin-bottom:3px}
.art-echo .q{font-family:var(--f-serif);font-style:italic;font-size:13px;color:var(--parch)}
#dash,#journey,#profile{display:none;height:100%}
#dash iframe,#journey iframe,#profile iframe{width:100%;height:100%;border:0;background:var(--indigo-night)}
#library,#settings{display:none;height:100%;overflow-y:auto}
/* settings screen (template K) — setrows + toggles */
.settings{padding:26px 26px 60px;max-width:720px;margin:0 auto}
.settings .stitle{font-family:var(--f-display);font-weight:700;font-size:24px;color:var(--parch);margin-bottom:4px}
.settings .ssub{font-family:var(--f-serif);font-style:italic;font-size:14px;color:var(--parch-dim);margin-bottom:16px}
.setrow{display:flex;align-items:center;gap:18px;padding:18px 4px;border-bottom:1px solid var(--line-soft)}
.setrow:last-child{border-bottom:0}
.setrow .si{flex:1}
.setrow .st{font-family:var(--f-title);font-size:16px;color:var(--parch)}
.setrow .sd{font-family:var(--f-body);font-size:13px;color:var(--parch-dim);margin-top:2px}
.toggle{width:52px;height:28px;border-radius:20px;background:rgba(6,9,20,.7);border:1px solid var(--line-gold);position:relative;flex:none;cursor:pointer}
.toggle.on{background:linear-gradient(90deg,var(--gold-deep),var(--gold));border-color:var(--gold)}
.toggle i{position:absolute;top:2px;left:2px;width:22px;height:22px;border-radius:50%;background:var(--parch);transition:.2s}
.toggle.on i{left:26px;background:#2a1c07}
.toggle.danger.on{background:linear-gradient(90deg,var(--vermilion-deep),var(--vermilion));border-color:var(--vermilion)}
.setrow select{background:rgba(6,9,20,.7);color:var(--parch);border:1px solid var(--line-gold);border-radius:5px;padding:8px 11px;font-family:var(--f-mono);font-size:12px;cursor:pointer}
.setrow select:disabled{opacity:.5}
/* reduced-motion: still the celebratory/ambient animations (respects the toggle + OS) */
body.reduce-motion *{animation:none !important}
@media(prefers-reduced-motion:reduce){.cerbox .rays,.cerbox .flick,#achtoast::after{animation:none !important}}
/* Artifacts Library — the Scriptorium (template F) */
.lib{padding:26px 26px 60px;max-width:1080px;margin:0 auto}
.lib-top{display:flex;align-items:center;gap:14px;margin-bottom:20px;flex-wrap:wrap}
.lib-top .lt-title{font-family:var(--f-display);font-weight:700;font-size:26px;color:var(--parch);line-height:1.1}
.lib-top .lt-sub{font-family:var(--f-serif);font-style:italic;font-size:15px;color:var(--parch-dim)}
.lib-search{flex:1;min-width:220px;position:relative}
.lib-search input{width:100%;background:rgba(6,9,20,.6);border:1px solid var(--line-gold);border-radius:6px;color:var(--parch);
 padding:11px 38px 11px 14px;font-family:var(--f-body);font-size:14px;outline:none}
.lib-search input:focus{border-color:var(--gold)}
.lib-search .ls-ic{position:absolute;right:12px;top:11px;color:var(--gold)}
.lib-filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.lib-pill{font-family:var(--f-mono);font-size:11px;letter-spacing:.04em;color:var(--parch-dim);background:rgba(6,9,20,.5);
 border:1px solid var(--line-soft);border-radius:999px;padding:5px 14px;cursor:pointer;transition:.14s}
.lib-pill:hover{color:var(--gold-bright)} .lib-pill.on{color:var(--gold-bright);border-color:var(--gold-deep);background:rgba(231,182,75,.1)}
.lib-grid{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:16px;grid-auto-rows:min-content}
@media(max-width:900px){.lib-grid{grid-template-columns:1fr}}
.artcard{position:relative;padding:18px 20px;display:flex;flex-direction:column;gap:8px;cursor:pointer;
 border:1px solid var(--line-gold);border-radius:8px;background:linear-gradient(165deg,rgba(35,29,24,.7),rgba(12,10,20,.85));transition:.16s}
.artcard:hover{border-color:var(--gold-deep);box-shadow:0 12px 30px -14px rgba(231,182,75,.4)}
.artcard.feat{grid-row:span 2;background:linear-gradient(165deg,rgba(35,29,24,.92),rgba(12,10,20,.94))}
.artcard .atype{font-family:var(--f-mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;display:inline-flex;gap:6px;align-items:center}
.artcard .atype.markdown{color:var(--peacock-bright)}.artcard .atype.code{color:var(--gold-bright)}.artcard .atype.html{color:var(--forest-lit)}.artcard .atype.viz{color:var(--vermilion-glow)}
.artcard h4{font-family:var(--f-title);font-size:17px;color:var(--parch);margin:2px 0}
.artcard p{font-family:var(--f-body);font-size:13px;color:var(--parch-dim);margin:0;line-height:1.5;
 display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.artcard .ameta{font-family:var(--f-mono);font-size:10px;color:var(--parch-mute);margin-top:auto;padding-top:8px;letter-spacing:.04em;display:flex;gap:12px;flex-wrap:wrap}
.artcard .apin{position:absolute;top:12px;right:12px;background:none;border:none;cursor:pointer;font-size:14px;color:var(--parch-mute);opacity:.6}
.artcard .apin.on{color:var(--gold-bright);opacity:1}
.lib-empty{grid-column:1/-1;text-align:center;padding:50px 20px;color:var(--parch-dim);font-family:var(--f-body)}
.lib-newbtn{font-family:var(--f-title);font-size:13px;background:linear-gradient(180deg,var(--gold-bright),var(--gold) 55%,var(--gold-deep));
 color:#2a1c07;border:none;border-radius:4px;padding:10px 18px;font-weight:600;cursor:pointer}
/* ===== Skill Tree — D's data-driven FOREST MAP (groves on a winding path) =====
   Art lifted from Ekalavya-Template-v2 §4; the SVG is now generated from live data. */
#tree{display:none;height:100%;padding:20px 24px;flex-direction:column;min-height:0}   /* tab switch toggles display:flex */
.treehead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px;flex:none}
.treehead .ttitle{font-family:var(--f-display);font-weight:700;letter-spacing:.02em;font-size:18px;color:var(--parch)}
.treehead .tsub{font-family:var(--f-mono);font-size:11px;color:var(--parch-mute);letter-spacing:.02em}
.treehead .g{color:transparent;background:linear-gradient(180deg,#fff6df,var(--gold-bright) 45%,var(--gold) 75%,var(--gold-deep));-webkit-background-clip:text;background-clip:text}
.treehead .grow{flex:1}
/* two tabs: overview / single track (drill-in) — the template's .treetabs */
.treetabs{display:flex;gap:6px}
.ttab{font-family:var(--f-mono);letter-spacing:.06em;font-size:11px;color:var(--parch-dim);
 background:rgba(6,9,20,.5);border:1px solid var(--line-soft);padding:6px 12px;border-radius:5px;cursor:pointer;transition:.16s}
.ttab:hover{color:var(--gold-bright)} .ttab.on{color:var(--gold-bright);border-color:var(--line-gold);background:rgba(231,182,75,.08)}
.ttab:disabled{opacity:.4;cursor:default}
/* the map fills the pane in a gold-hairline frame; the SVG scales to width (no overflow) */
.mapframe{flex:1;min-height:0;border-radius:6px;overflow:hidden;border:1px solid var(--line-gold);
 box-shadow:0 24px 60px -30px rgba(0,0,0,.7);display:flex;background:#101528}
.mapframe svg{display:block;width:100%;height:100%;flex:1;min-height:0}
.grove{cursor:pointer;transition:.25s}
.grove:hover{filter:brightness(1.22) drop-shadow(0 0 12px rgba(231,182,75,.5))}
.grove.locked{cursor:default}.grove.locked:hover{filter:none}
.treeempty{margin:auto;padding:50px;text-align:center;max-width:440px;color:var(--parch-dim)}
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
/* game HUD — the template's radial rank-ring (XP as a continuous ring, not an emoji+bar) */
.hud{display:flex;align-items:center;gap:11px;font-family:var(--f-mono);font-size:12px}
.hud .rank-ring{transform:rotate(-90deg)}
.hud .rank-ring .arc{transition:stroke-dashoffset 1s cubic-bezier(.22,.7,.25,1)}
.hud .flame{color:var(--gold-bright)}
.hud .rank{color:var(--peacock-bright);font-family:var(--f-title);font-size:13px}
.hud .prog{color:var(--parch-dim)} .hud .prog b{color:var(--gold-bright)}
/* death / loss overlay — re-themed from Dark-Souls to epic-not-punitive (template §5):
   "YOUR AIM FALTERED / पुण्य क्षीण", vermilion stone-cracks, a gold Merit badge. */
#death{position:fixed;inset:0;z-index:100;display:none;place-items:center;
 background:radial-gradient(circle at 50% 42%,rgba(60,14,10,.72),rgba(6,4,10,.97) 72%);backdrop-filter:blur(3px)}
#death.on{display:grid;animation:fadein .5s ease}
@keyframes fadein{from{opacity:0}to{opacity:1}}
.deathcard{position:relative;text-align:center;max-width:540px;padding:30px;overflow:hidden}
.deathcard .cracks{position:absolute;inset:0;pointer-events:none;opacity:.5}
.deathcard .dcontent{position:relative;z-index:2}
.deathcard .de{font-family:var(--f-mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--vermilion-glow);margin-bottom:12px}
.dbig{font-family:var(--f-display);font-weight:800;font-size:clamp(34px,6vw,64px);letter-spacing:.1em;line-height:1.05;
 color:transparent;background:linear-gradient(180deg,#ffb9ac,var(--vermilion) 55%,var(--vermilion-deep));
 -webkit-background-clip:text;background-clip:text;text-shadow:0 0 40px rgba(214,59,42,.45);animation:dpulse 2.4s ease infinite}
@keyframes dpulse{50%{opacity:.86}}
.ddeva{font-family:var(--f-deva);font-size:22px;color:var(--vermilion-glow);margin-top:6px}
.deathsub{font-family:var(--f-serif);font-style:italic;color:var(--parch-dim);margin:16px auto 0;font-size:16px;line-height:1.6;max-width:440px}
.deathsub b{color:var(--vermilion-glow);font-style:normal}
.dnote{font-family:var(--f-body);font-size:13.5px;color:var(--parch-mute);margin-top:10px}
.lmerit{margin:22px auto 0;display:inline-flex;align-items:center;gap:12px;padding:12px 22px;border:1px solid var(--gold);border-radius:4px;background:rgba(231,182,75,.08)}
.lmerit .deva{font-family:var(--f-deva);font-size:18px;color:var(--gold)}
.lmerit .mn{font-family:var(--f-display);font-weight:700;font-size:20px;color:var(--gold-bright)}
.lmerit .ml{font-family:var(--f-mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--parch-dim);text-align:left}
#death button{font-family:var(--f-title);letter-spacing:.04em;margin-top:18px;background:rgba(143,35,24,.2);color:var(--vermilion-glow);
 border:1px solid rgba(214,59,42,.55);border-radius:4px;padding:11px 26px;cursor:pointer;font-weight:600;font-size:14px}
#death button:hover{background:rgba(143,35,24,.35)}
/* reclaim toast — merit reclaimed, teal-bordered sheen (template's .toast) */
#reclaim{position:fixed;top:66px;left:50%;transform:translateX(-50%);z-index:90;display:none;
 gap:14px;align-items:center;
 background:linear-gradient(120deg,rgba(35,29,24,.96),rgba(20,15,10,.96));border:1px solid var(--peacock);color:var(--parch);
 padding:13px 22px;border-radius:5px;box-shadow:0 12px 40px -10px rgba(46,163,160,.4)}
#reclaim.on{display:flex;animation:pop .4s ease}
#reclaim .rc-badge{flex:none;color:var(--peacock-bright)}
#reclaim .rc-info .rc-e{font-family:var(--f-mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--peacock-bright);margin-bottom:2px}
#reclaim .rc-info .rc-n{font-family:var(--f-display);font-weight:700;font-size:16px;color:var(--gold-bright)}
#reclaim .rc-info .rc-d{font-family:var(--f-body);font-size:12.5px;color:var(--parch-dim)}
@keyframes pop{from{opacity:0;transform:translateX(-50%) translateY(-8px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
/* achievement toast (template §5) — transient, top-centre, gold-leaf sheen */
#achtoast{position:fixed;top:66px;left:50%;transform:translateX(-50%);z-index:95;display:none;gap:16px;align-items:center;
 padding:16px 20px;border:1px solid var(--gold);border-radius:5px;overflow:hidden;max-width:min(440px,92vw);
 background:linear-gradient(120deg,rgba(35,29,24,.96),rgba(20,15,10,.96));box-shadow:0 12px 40px -10px rgba(231,182,75,.5)}
#achtoast.on{display:flex;animation:pop .45s ease}
#achtoast::after{content:"";position:absolute;top:0;left:-40%;width:40%;height:100%;
 background:linear-gradient(100deg,transparent,rgba(255,246,223,.25),transparent);animation:sheen 3.2s ease-in-out 2}
@keyframes sheen{0%{left:-40%}60%,100%{left:120%}}
#achtoast .badge{flex:0 0 auto}
#achtoast .tinfo .te{font-family:var(--f-mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);margin-bottom:3px}
#achtoast .tinfo .tn{font-family:var(--f-display);font-weight:700;font-size:18px;color:var(--parch)}
#achtoast .tinfo .td{font-family:var(--f-body);font-size:14px;color:var(--parch-dim)}
/* level-up ceremony (template §5) — gold bloom + spinning chakra rays + twin diyas */
#ceremony{position:fixed;inset:0;z-index:101;display:none;place-items:center;
 background:radial-gradient(circle at 50% 45%,rgba(30,24,14,.92),rgba(6,4,10,.97) 72%);backdrop-filter:blur(3px)}
#ceremony.on{display:grid;animation:fadein .5s ease}
.cerbox{position:relative;min-height:340px;min-width:min(520px,92vw);border-radius:6px;overflow:hidden;display:flex;align-items:center;justify-content:center;
 background:radial-gradient(circle at center,rgba(30,24,14,.9),var(--void) 70%);border:1px solid var(--gold)}
.cerbox .rays{position:absolute;top:50%;left:50%;width:640px;height:640px;transform:translate(-50%,-50%);opacity:.6;animation:slowspin 40s linear infinite}
@keyframes slowspin{to{transform:translate(-50%,-50%) rotate(360deg)}}
.cerbox .ccontent{position:relative;text-align:center;z-index:2;padding:24px}
.cerbox .bloom{animation:bloom 1.5s cubic-bezier(.2,.7,.3,1) both}
@keyframes bloom{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:scale(1)}}
.cerbox .ce{font-family:var(--f-mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--peacock-bright);margin-bottom:8px}
.cerbox .clvl{font-family:var(--f-display);font-weight:900;font-size:64px;line-height:1;color:transparent;
 background:linear-gradient(180deg,#fff6df,var(--gold) 55%,var(--gold-deep));-webkit-background-clip:text;background-clip:text;text-shadow:0 4px 30px rgba(231,182,75,.5)}
.cerbox .cdeva{font-family:var(--f-deva);font-size:20px;color:var(--parch);opacity:.92;margin-top:6px}
.cerbox .ctitle{font-family:var(--f-serif);font-style:italic;font-size:18px;color:var(--parch);margin-top:8px}
.cerbox .ctitle b{color:var(--gold-bright);font-style:normal}
.cerbox .diya{position:absolute;bottom:26px}.cerbox .diya.d1{left:60px}.cerbox .diya.d2{right:60px}
.cerbox .flick{animation:flick 1.6s ease-in-out infinite;transform-origin:center bottom}
@keyframes flick{0%,100%{transform:scale(1) rotate(-2deg)}50%{transform:scale(1.08) rotate(2deg)}}
#ceremony button{position:absolute;bottom:18px;left:50%;transform:translateX(-50%);font-family:var(--f-title);letter-spacing:.04em;
 background:rgba(231,182,75,.1);color:var(--gold-bright);border:1px solid var(--gold-deep);border-radius:4px;padding:9px 22px;cursor:pointer;font-weight:600}
*:focus-visible{outline:2px solid var(--gold-bright);outline-offset:2px;border-radius:3px}
.sh-deep{--sh-deep:0 24px 60px -20px rgba(0,0,0,.8)}
:root{--sh-deep:0 24px 60px -20px rgba(0,0,0,.8)}
/* mobile radial bottom-nav (template §7): a centre 'practice' orb + four sections */
#mnav{display:none;justify-content:space-around;align-items:flex-end;padding:8px 10px 12px;
 border-top:1px solid var(--line-gold);background:linear-gradient(180deg,rgba(35,29,24,.6),rgba(8,11,32,.95));
 position:sticky;bottom:0;z-index:80}
#mnav .ni{display:flex;flex-direction:column;align-items:center;gap:4px;font-family:var(--f-mono);font-size:10px;
 letter-spacing:.06em;color:var(--parch-dim);text-transform:uppercase;background:none;border:none;cursor:pointer;padding:0}
#mnav .ni.on{color:var(--gold-bright)}
#mnav .ni.center{margin-top:-24px}
#mnav .ni.center .orb{width:52px;height:52px;border-radius:50%;background:radial-gradient(circle at 40% 35%,var(--gold-bright),var(--gold-deep));
 display:flex;align-items:center;justify-content:center;box-shadow:0 8px 22px -6px rgba(231,182,75,.7),inset 0 1px 0 rgba(255,255,255,.5);border:2px solid rgba(255,246,223,.3)}
/* mobile: header wraps, tabs scroll, creed hides so the HUD + tabs fit */
@media(max-width:900px){
 header{flex-wrap:wrap;gap:10px;padding:10px 14px}
 .creed{display:none}
 .tabs{margin-left:0;overflow-x:auto;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}
 .hud{font-size:11px;gap:8px}
 #prail{display:none}                 /* the rail is desktop-only; mobile uses the radial nav */
 main{grid-template-columns:1fr}
 body{overflow:auto}
 #mnav{display:flex}
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
  <nav id="prail" aria-label="Sections">
    <div class="rail-item on" data-rail="practice" onclick="railGo('practice')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M4 12 C10 7 14 7 20 12 C14 17 10 17 4 12" stroke="currentColor" stroke-width="1.6"/><line x1="4" y1="12" x2="20" y2="12" stroke="currentColor" stroke-width="1.6"/></svg> Practice</div>
    <div class="rail-item" data-rail="dash" onclick="railGo('dash')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M3 11 L12 4 L21 11 V21 H3 Z" stroke="currentColor" stroke-width="1.6"/></svg> Progress</div>
    <div class="rail-item" data-rail="tree" onclick="railGo('tree')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M12 21V11M12 11a5 5 0 100-8 5 5 0 000 8z" stroke="currentColor" stroke-width="1.5"/></svg> Forest Map</div>
    <div class="rail-item" data-rail="library" onclick="railGo('library')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M6 4h11a2 2 0 0 1 2 2v14H8a2 2 0 0 1-2-2z" stroke="currentColor" stroke-width="1.6"/></svg> Library</div>
    <div class="rail-item" data-rail="settings" onclick="railGo('settings')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M12 15a3 3 0 100-6 3 3 0 000 6z" stroke="currentColor" stroke-width="1.5"/><path d="M19 12a7 7 0 00-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 00-1.7-1L16.5 2h-9l-.4 2.6a7 7 0 00-1.7 1l-2.3-1-2 3.4 2 1.5a7 7 0 000 2l-2 1.5 2 3.4 2.3-1a7 7 0 001.7 1L7.5 22h9l.4-2.6a7 7 0 001.7-1l2.3 1 2-3.4-2-1.5c.1-.3.1-.7.1-1z" stroke="currentColor" stroke-width="1.2"/></svg> Settings</div>
    <div class="rail-mini-hud"><div class="rmh-name" id="railname">Devotee</div><div class="rmh-title">Vana-Dhanurdhara</div></div>
  </nav>
  <div id="content">
  <div id="practice">
    <div class="col chat">
      <div class="log" id="log"><div class="arena-welcome" id="arenawelcome">
        <div class="aw-mark"><svg width="46" height="58" viewBox="0 0 58 76" aria-hidden="true"><path d="M14 6 C40 24 40 52 14 70" stroke="#e7b64b" stroke-width="4" stroke-linecap="round" fill="none"/><line x1="14" y1="6" x2="14" y2="70" stroke="#57d3ce" stroke-width="1.6"/><line x1="14" y1="38" x2="50" y2="38" stroke="#f7d98a" stroke-width="2.4"/><path d="M50 38 l-7 -5 M50 38 l-7 5" stroke="#f7d98a" stroke-width="2.4" stroke-linecap="round"/></svg></div>
        <div class="aw-deva">एकलव्य</div>
        <div class="aw-title">Nock the first arrow</div>
        <div class="aw-sub" id="awsub">Your first drill is loading — Ekalavya is drawing the bow…</div>
        <div class="aw-dots"><span></span><span></span><span></span></div>
      </div></div>
      <div class="resumebar hidden" id="resumebar">
        <input type="file" id="resumefile" accept="application/pdf,.pdf" hidden onchange="uploadResume()">
        <button class="ghost" onclick="document.getElementById('resumefile').click()">📄 Upload résumé / LinkedIn PDF (optional)</button>
        <span class="resumehint" id="resumehint">grounds your setup in your real experience · export LinkedIn via “Save to PDF”</span>
      </div>
      <div class="inbar">
        <button class="rewind" id="rewindbtn" title="Rewind — drop the last exchange and try again (its message returns to the box)" onclick="rewind()" hidden>↶ Rewind</button>
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
        <div class="seg" id="rightseg" role="tablist" aria-label="Right pane">
          <span class="on" data-pane="editor" onclick="showPane('editor')" role="tab">▤ Editor</span>
          <span data-pane="canvas" onclick="showPane('canvas')" role="tab">✦ Canvas</span>
        </div>
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
      <div class="ed-tests hidden" id="edtests">
        <div class="ed-tests-h"><span>Test arrows</span><span class="et-count" id="etcount"><b>0</b> / 0 strike</span></div>
        <div class="et-list" id="etlist"></div>
        <div class="ed-tests-f"><span class="et-hint" id="ethint">Run your code — each check becomes an arrow that strikes or misses.</span>
          <button class="submit" style="flex:none" onclick="submitCode()">✓ Submit</button></div>
      </div>
      <div id="canvaspane">
        <div class="canvas-tabs" id="canvastabs"></div>
        <div class="canvas-body" id="canvasbody"><div class="canvas-empty">No artifact selected. When the guru writes a lesson and you save it to your Canvas, it renders here.</div></div>
        <div class="selpop" id="selpop" onclick="askSelection()">Ask about this ✦</div>
      </div>
    </div>
  </div>
  <div id="dash"><iframe id="dashframe" src="/dashboard"></iframe></div>
  <div id="journey"><iframe id="jframe" src="/journey"></iframe></div>
  <div id="profile"><iframe id="pframe" src="/profile"></iframe></div>
  <div id="tree">
    <div class="treehead">
      <span class="ttitle"><span class="g">The Forest of Mastery</span></span>
      <span class="tsub" id="treesub">groves on a winding path · a tap enters a grove</span>
      <span class="grow"></span>
      <div class="treetabs">
        <button class="ttab on" id="tabForest" onclick="showForest()">◆ Forest-map overview</button>
        <button class="ttab" id="tabTrack" onclick="showGrove()" disabled>→ Single track</button>
      </div>
    </div>
    <div class="mapframe"><svg id="forestsvg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Forest map of learning groves on a winding path."></svg></div>
  </div>
  <div id="library"></div>
  <div id="settings"></div>
  </div>
</main>
<nav id="mnav" aria-label="Sections">
  <button class="ni" data-rail="dash" onclick="railGo('dash')"><svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M3 11 L12 4 L21 11 V21 H3 Z" stroke="currentColor" stroke-width="1.6"/></svg>Ashram</button>
  <button class="ni" data-rail="tree" onclick="railGo('tree')"><svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 21V11M12 11a5 5 0 100-8 5 5 0 000 8z" stroke="currentColor" stroke-width="1.5"/></svg>Forest</button>
  <button class="ni center" data-rail="practice" onclick="railGo('practice')"><span class="orb"><svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M4 12 C10 7 14 7 20 12 C14 17 10 17 4 12" stroke="#2a1c07" stroke-width="2"/><line x1="4" y1="12" x2="20" y2="12" stroke="#2a1c07" stroke-width="2"/></svg></span><span style="margin-top:2px">Practice</span></button>
  <button class="ni" data-rail="library" onclick="railGo('library')"><svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M6 4h11a2 2 0 0 1 2 2v14H8a2 2 0 0 1-2-2z" stroke="currentColor" stroke-width="1.6"/></svg>Library</button>
  <button class="ni" data-rail="settings" onclick="railGo('settings')"><svg width="20" height="20" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M12 4v3M12 17v3M4 12h3M17 12h3" stroke="currentColor" stroke-width="1.5"/></svg>Settings</button>
</nav>

<div id="drawerscrim" onclick="closeDrawer()"></div>
<div id="drawer">
  <div class="drawerhead"><span class="t">Chats</span><button class="x" onclick="closeDrawer()">×</button></div>
  <button class="newchat" onclick="newChat()">+ New chat</button>
  <div class="chatlist" id="chatlist"></div>
</div>

<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#b8862f"/><stop offset="1" stop-color="#f7d98a"/></linearGradient></defs></svg>

<div id="death"><div class="deathcard">
  <svg class="cracks" viewBox="0 0 400 360" preserveAspectRatio="none"><g stroke="#d63b2a" stroke-width="1" fill="none" opacity=".7"><path d="M200 0 L190 90 L230 150 L200 220 L240 300 L210 360"/><path d="M190 90 L120 130 L60 110"/><path d="M230 150 L310 140 L360 180"/><path d="M200 220 L130 250 L70 240"/></g></svg>
  <div class="dcontent">
    <div class="de">◆ The round is lost</div>
    <div class="dbig">YOUR AIM<br>FALTERED</div>
    <div class="ddeva">पुण्य क्षीण</div>
    <div class="deathsub" id="deathsub"></div>
    <div class="lmerit"><span class="deva">पुण्य</span><span class="mn" id="deathmerit">−0 XP</span><span class="ml">merit lost ·<br>every miss teaches</span></div>
    <div class="dnote">Type your next answer yourself to reclaim your merit.</div>
    <button onclick="dismissDeath()">Continue</button>
  </div>
</div></div>
<div id="achtoast"><span class="badge"><svg width="46" height="46" viewBox="0 0 52 52" fill="none"><path d="M26 3 L48 15 V37 L26 49 L4 37 V15 Z" fill="#231d18" stroke="#e7b64b" stroke-width="1.5"/><path d="M26 9 L43 18 V34 L26 43 L9 34 V18 Z" fill="none" stroke="#f7d98a" stroke-width="1" opacity=".6"/><path d="M26 16 v14 M22 30 h8 M26 16 c-3 2 -3 6 0 8 c3 -2 3 -6 0 -8" stroke="#f7d98a" stroke-width="1.6" fill="none"/><circle cx="26" cy="24" r="2" fill="#d63b2a"/></svg></span><div class="tinfo"><div class="te">◆ Achievement unlocked</div><div class="tn" id="achname">—</div><div class="td" id="achdesc">—</div></div></div>

<div id="ceremony"><div class="cerbox">
  <svg class="rays" viewBox="0 0 200 200" fill="none"><g id="ceremonyrays" stroke="#f7d98a" stroke-width=".7"></g></svg>
  <div class="ccontent bloom">
    <div class="ce">◆ Ascension · siddhi</div>
    <div class="clvl" id="cerlvl">RANK</div>
    <div class="cdeva">दीप प्रज्वलित — एक और दीया जला</div>
    <div class="ctitle" id="certitle">You are now <b>—</b></div>
  </div>
  <svg class="diya d1" width="46" height="34" viewBox="0 0 46 34"><path d="M4 20 Q23 34 42 20 L38 24 Q23 30 8 24 Z" fill="#b8862f"/><ellipse cx="23" cy="20" rx="20" ry="6" fill="#3a2f26"/><g class="flick"><path d="M23 4 C27 12 25 17 23 18 C21 17 19 12 23 4Z" fill="#f7d98a"/></g></svg>
  <svg class="diya d2" width="46" height="34" viewBox="0 0 46 34"><path d="M4 20 Q23 34 42 20 L38 24 Q23 30 8 24 Z" fill="#b8862f"/><ellipse cx="23" cy="20" rx="20" ry="6" fill="#3a2f26"/><g class="flick"><path d="M23 4 C27 12 25 17 23 18 C21 17 19 12 23 4Z" fill="#f7d98a"/></g></svg>
  <button onclick="dismissCeremony()">Continue</button>
</div></div>

<div id="reclaim"><span class="rc-badge"><svg width="34" height="34" viewBox="0 0 24 24" fill="none"><path d="M14 3h7v7l-9 9-5-5z" stroke="currentColor" stroke-width="1.6"/><line x1="5" y1="14" x2="10" y2="19" stroke="currentColor" stroke-width="1.6"/><line x1="3" y1="21" x2="7" y2="17" stroke="currentColor" stroke-width="1.6"/></svg></span><div class="rc-info"><div class="rc-e">◆ Merit reclaimed</div><div class="rc-n" id="reclaimn">+0 XP restored</div><div class="rc-d">The forest forgives the honest.</div></div></div>

<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"></script>
<script>
mermaid.initialize({startOnLoad:false, theme:'dark', securityLevel:'loose',
  flowchart:{useMaxWidth:true, htmlLabels:true}});
let thread = crypto.randomUUID(), mode = 'practice', editor = null, streaming = false;
let streamAbort = null;   // AbortController for the in-flight /api/stream (Esc cancels)
let turns = [];           // one entry per user turn: {text, you, ai} DOM handles, for rewind/edit
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

// view switching — driven by BOTH the header tabs and the ashram left rail.
// The rail carries Practice/Progress/Forest Map(tree)/Library/Settings; the header
// tabs carry Practice/Progress/Journey/Profile/Skill Tree — they share these targets.
function showView(v){
  const DISP={practice:'grid',dash:'block',journey:'block',profile:'block',tree:'flex',library:'flex',settings:'block'};
  for(const id of Object.keys(DISP)){ const el=document.getElementById(id); if(el) el.style.display = (id===v)?DISP[id]:'none'; }
  // keep both nav surfaces in sync with the active view
  document.querySelectorAll('.tab[data-view]').forEach(x=>x.classList.toggle('on', x.dataset.view===v));
  document.querySelectorAll('#prail .rail-item,#mnav .ni').forEach(x=>x.classList.toggle('on', x.dataset.rail===v));
  if(v==='dash') document.getElementById('dashframe').src='/dashboard';
  if(v==='journey') document.getElementById('jframe').src='/journey';
  if(v==='profile') document.getElementById('pframe').src='/profile';  // reload → latest profile/goals
  if(v==='tree') showForest();
  if(v==='library') loadLibrary();
  if(v==='settings') loadSettings();
}
document.querySelectorAll('.tab[data-view]').forEach(t=>t.onclick=()=>showView(t.dataset.view));  // [data-view] excludes the editor toggle
function railGo(v){ showView(v); }

/* ===== Settings screen (template K) — setrows + toggles + provider selector ===== */
function applyReducedMotion(on){ document.body.classList.toggle('reduce-motion', !!on); }
function saveSetting(patch){
  return fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(patch)}).then(r=>r.json());
}
function loadSettings(){
  fetch('/api/settings').then(r=>r.json()).then(s=>{
    applyReducedMotion(s.reduced_motion);
    const provOpts=(s.providers||[]).map(p=>
      "<option value='"+p.key+"'"+(p.key===s.active_provider?" selected":"")+(p.configured?"":" disabled")+">"+
      p.label+(p.configured?"":" · no key")+"</option>").join('');
    const tog=(on,danger)=>"<div class='toggle"+(danger?" danger":"")+(on?" on":"")+"' role='switch' tabindex='0' aria-checked='"+(!!on)+"'><i></i></div>";
    document.getElementById('settings').innerHTML=
     "<div class='settings'>"+
     "<div class='stitle'>Settings</div><div class='ssub'>How the guru of stone teaches, and how it grades.</div>"+
     "<div class='setrow' id='sr-cheat'><div class='si'><div class='st'>Cheat penalty</div><div class='sd'>Paste a full solution and the round is lost — merit drops, the streak breaks. Type it yourself to reclaim.</div></div>"+tog(s.death_on_cheat,true)+"</div>"+
     "<div class='setrow' id='sr-motion'><div class='si'><div class='st'>Reduced motion</div><div class='sd'>Stills the ceremony, bloom, and flame animations. Respects your OS setting by default.</div></div>"+tog(s.reduced_motion,false)+"</div>"+
     "<div class='setrow' id='sr-voice'><div class='si'><div class='st'>Guru voice</div><div class='sd'>Stone guru (stern, epic) vs. plain mentor. Same grading either way.</div></div>"+tog(s.guru_voice,false)+"</div>"+
     "<div class='setrow' id='sr-prov'><div class='si'><div class='st'>Provider</div><div class='sd'>Which model powers the tutor. Only providers with a key set are selectable.</div></div>"+
     "<select id='provselect'>"+provOpts+"</select></div>"+
     "</div>";
    // wire the toggles
    const wire=(sel,key,after)=>{ const t=document.querySelector(sel+' .toggle');
      const flip=()=>{ const on=!t.classList.contains('on'); t.classList.toggle('on',on); t.setAttribute('aria-checked',on);
        saveSetting({[key]:on}).then(()=>after&&after(on)); };
      t.onclick=flip; t.onkeydown=e=>{ if(e.key===' '||e.key==='Enter'){e.preventDefault();flip();} }; };
    wire('#sr-cheat','death_on_cheat',on=>{ deathOnCheat=on; updatePenaltyBtn(); });
    wire('#sr-motion','reduced_motion',on=>applyReducedMotion(on));
    wire('#sr-voice','guru_voice');
    document.getElementById('provselect').onchange=e=>{
      saveSetting({provider:e.target.value}).then(()=>{
        fetch('/api/config').then(r=>r.json()).then(c=>{
          document.getElementById('who').textContent = c.configured ? (c.provider+' · '+c.model) : 'no provider key set'; });
      });
    };
  }).catch(()=>{ document.getElementById('settings').innerHTML="<div class='settings'><div class='ssub'>could not load settings.</div></div>"; });
}
/* ===== Artifacts Library — the Scriptorium (template F) ===== */
let _libFilter='', _libQuery='';
const KIND_GLYPH={markdown:'◆',code:'▶',viz:'◈',html:'□'};
const KIND_LABEL={markdown:'lesson',code:'code',viz:'visual',html:'html'};
function libCard(a, feat){
  const glyph=KIND_GLYPH[a.kind]||'◆', klabel=KIND_LABEL[a.kind]||a.kind;
  const preview=(a.content||'').replace(/[#*`>_]/g,'').replace(/<[^>]+>/g,' ').trim().slice(0,160);
  const when=(a.updated_at||'').replace('T',' ').slice(0,16);
  return "<div class='artcard"+(feat?' feat':'')+"' onclick='openArtifact("+a.id+")'>"+
    "<button class='apin"+(a.pinned?' on':'')+"' title='"+(a.pinned?'Unpin':'Pin')+"' onclick='event.stopPropagation();togglePin("+a.id+","+(a.pinned?0:1)+")'>"+(a.pinned?'★':'☆')+"</button>"+
    "<div class='atype "+a.kind+"'>"+glyph+" "+klabel+(a.pinned?' · pinned':'')+"</div>"+
    "<h4>"+esc(a.title)+"</h4><p>"+esc(preview||'—')+"</p>"+
    "<div class='ameta'><span>"+klabel+"</span><span>updated "+esc(when)+"</span></div></div>";
}
function loadLibrary(){
  const url='/api/artifacts?'+(_libFilter?'kind='+encodeURIComponent(_libFilter)+'&':'')+(_libQuery?'q='+encodeURIComponent(_libQuery):'');
  fetch(url).then(r=>r.json()).then(list=>{
    const filters=['','markdown','code','viz','html'];
    const flabels={'':'All',markdown:'Lessons',code:'Code',viz:'Visuals',html:'HTML'};
    const pills=filters.map(f=>"<span class='lib-pill"+(f===_libFilter?' on':'')+"' onclick=\"setLibFilter('"+f+"')\">"+flabels[f]+"</span>").join('');
    let cards;
    if(!list.length){ cards="<div class='lib-empty'>The Scriptorium is quiet — the guru hasn't written anything here yet. Ask for a lesson and save it to your Canvas.</div>"; }
    else { cards=list.map((a,i)=>libCard(a, a.pinned && i===0)).join(''); }
    document.getElementById('library').innerHTML=
     "<div class='lib'><div class='lib-top'>"+
     "<div><div class='lt-title'>The Scriptorium</div><div class='lt-sub'>Everything you and the guru have written — kept for revision.</div></div>"+
     "<span style='flex:1'></span>"+
     "<div class='lib-search'><input id='libsearch' placeholder='Search artifacts — recursion, SQL…' value='"+esc(_libQuery)+"'>"+
     "<span class='ls-ic'><svg width='16' height='16' viewBox='0 0 24 24' fill='none'><circle cx='11' cy='11' r='7' stroke='#e7b64b' stroke-width='1.8'/><line x1='16' y1='16' x2='21' y2='21' stroke='#e7b64b' stroke-width='1.8'/></svg></span></div></div>"+
     "<div class='lib-filters'>"+pills+"</div>"+
     "<div class='lib-grid'>"+cards+"</div></div>";
    const si=document.getElementById('libsearch');
    si.oninput=()=>{ _libQuery=si.value; clearTimeout(si._t); si._t=setTimeout(loadLibrary,220); };
    si.focus(); si.setSelectionRange(si.value.length, si.value.length);
  }).catch(()=>{ document.getElementById('library').innerHTML="<div class='lib'><div class='lib-empty'>could not load the library.</div></div>"; });
}
function setLibFilter(f){ _libFilter=f; loadLibrary(); }
function togglePin(id, on){ fetch('/api/artifacts/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({pinned:!!on})}).then(()=>loadLibrary()).catch(()=>{}); }
// openArtifact(id) — opens the artifact in the arena's Canvas tab.
function openArtifact(id){ showView('practice'); openCanvas(id); }

/* ===== Canvas — the Editor↔Canvas tab (template E) ===== */
let _artifacts=[], _curArt=null, _selText='';
function showPane(p){
  const col=document.querySelector('#practice .col:not(.chat)');
  const isCanvas=(p==='canvas'); col.classList.toggle('canvasmode', isCanvas);
  document.querySelectorAll('#rightseg span').forEach(s=>s.classList.toggle('on', s.dataset.pane===p));
  if(isCanvas){ loadCanvas(); }
  else if(editor){ setTimeout(()=>editor.layout(),60); }
}
function artGlyph(k){ return KIND_GLYPH[k]||'◆'; }
function loadCanvas(select){
  return fetch('/api/artifacts').then(r=>r.json()).then(list=>{
    _artifacts=list;
    const tabs=document.getElementById('canvastabs');
    if(!list.length){ tabs.innerHTML=''; document.getElementById('canvasbody').innerHTML=
      "<div class='canvas-empty'>No artifacts yet. Ask the guru for a lesson and save it to your Canvas — it renders here.</div>"; _curArt=null; return; }
    if(select!=null) _curArt=select;
    if(_curArt==null || !list.find(a=>a.id===_curArt)) _curArt=list[0].id;
    tabs.innerHTML=list.map(a=>"<span class='artpill"+(a.id===_curArt?' on':'')+"' onclick='selectArtifact("+a.id+")'><span class='k'>"+
      artGlyph(a.kind)+"</span> "+esc(a.title)+"</span>").join('');
    renderArtifact(list.find(a=>a.id===_curArt));
  }).catch(()=>{});
}
function selectArtifact(id){ _curArt=id;
  document.querySelectorAll('#canvastabs .artpill').forEach((p,i)=>p.classList.toggle('on',_artifacts[i]&&_artifacts[i].id===id));
  const a=_artifacts.find(x=>x.id===id); if(a) renderArtifact(a);
}
function renderArtifact(a){
  const body=document.getElementById('canvasbody');
  if(!a){ body.innerHTML="<div class='canvas-empty'>—</div>"; return; }
  if(a.kind==='code'){
    body.innerHTML="<div class='art-code' data-selectable='1'>"+esc(a.content)+"</div>";
  } else if(a.kind==='html'){
    body.innerHTML="<div class='art-html'><div class='art-htmlbar'>"+esc(a.title)+" · rendered</div>"+
      "<div class='art-htmlprev'>"+DOMPurify.sanitize(a.content)+"</div></div>";
  } else if(a.kind==='viz'){
    body.innerHTML="<div class='art-viz'>"+DOMPurify.sanitize(a.content,{USE_PROFILES:{svg:true,svgFilters:true,html:true}})+"</div>";
  } else {  // markdown lesson
    body.innerHTML="<div class='art-md' data-selectable='1'>"+DOMPurify.sanitize(marked.parse(a.content||''))+"</div>";
    body.querySelectorAll('pre code').forEach(c=>{try{hljs.highlightElement(c);}catch(e){}});
  }
  body.appendChild(document.getElementById('selpop'));  // keep the popover inside the scroll box
}
function openCanvas(id){ showPane('canvas'); loadCanvas(id); }
// highlight-to-ask: selecting text in a renderable artifact raises the "Ask about this ✦"
// popover; clicking it sends the selection to the guru as labelled context.
function onCanvasSelect(){
  const pop=document.getElementById('selpop'); const sel=window.getSelection();
  const body=document.getElementById('canvasbody');
  const txt=(sel&&sel.toString()||'').trim();
  const inCanvas=sel && sel.anchorNode && body.contains(sel.anchorNode);
  if(!txt || !inCanvas || txt.length<2){ pop.classList.remove('on'); _selText=''; return; }
  _selText=txt;
  const rect=sel.getRangeAt(0).getBoundingClientRect(), br=body.getBoundingClientRect();
  pop.style.left=Math.max(6,(rect.left-br.left+body.scrollLeft))+'px';
  pop.style.top=Math.max(6,(rect.top-br.top+body.scrollTop-40))+'px';
  pop.classList.add('on');
}
document.addEventListener('selectionchange',()=>{ if(document.querySelector('#practice .col.canvasmode')) onCanvasSelect(); });
function askSelection(){
  if(!_selText) return;
  const art=_artifacts.find(a=>a.id===_curArt);
  document.getElementById('selpop').classList.remove('on');
  // echo the asked-about selection in chat (template's .art-echo), then ask the guru
  clearWelcome();
  const echo=el('art-echo');
  echo.innerHTML="<div><div class='lbl'>◆ asking about a selection in the canvas</div><div class='q'>"+esc(_selText.slice(0,180))+"</div></div>";
  document.getElementById('log').appendChild(echo); scroll();
  const q="About the canvas"+(art?" artifact \""+art.title+"\"":"")+", I'm asking about this part:\n\n> "+_selText.slice(0,600)+"\n\nCan you explain it?";
  const sel=window.getSelection(); if(sel) sel.removeAllRanges(); _selText='';
  stream(q);
}
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

/* ===== Data-driven FOREST MAP (replaces the Mermaid skill tree) =====
   Renders the /api/forest data as the template's forest map: groves as trees on a
   winding path, styled by mastery, with a gold 'travelled' path up to the active
   grove and the clay statue of Droṇa overseeing. Clicking a grove drills into that
   pillar's concepts as a smaller sub-forest (same visual language). */
const SVGNS='http://www.w3.org/2000/svg';
let _curFocus=null;             // active pillar name, for the drill-in default
function _svgEl(t,a){const e=document.createElementNS(SVGNS,t);for(const k in a)e.setAttribute(k,a[k]);return e;}
function _esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function _short(s,n){s=s||'';return s.length>n?s.slice(0,n-1)+'…':s;}

// A cubic path threading the layout points bottom→top (Catmull-Rom → Bézier), so
// the trail winds smoothly whatever the point count. `upto` clips it to the first
// `upto` points (the travelled/gold portion).
function _pathThrough(pts,upto){
  const p=(upto==null?pts:pts.slice(0,upto));
  if(p.length<1) return '';
  if(p.length<2) return 'M'+p[0].x+','+p[0].y;
  let d='M'+p[0].x+','+p[0].y;
  for(let i=0;i<p.length-1;i++){
    const p0=p[i-1]||p[i], p1=p[i], p2=p[i+1], p3=p[i+2]||p2;
    const c1x=p1.x+(p2.x-p0.x)/6, c1y=p1.y+(p2.y-p0.y)/6;
    const c2x=p2.x-(p3.x-p1.x)/6, c2y=p2.y-(p3.y-p1.y)/6;
    d+=' C'+c1x.toFixed(1)+','+c1y.toFixed(1)+' '+c2x.toFixed(1)+','+c2y.toFixed(1)+' '+p2.x+','+p2.y;
  }
  return d;
}

// One grove tree (art lifted from Ekalavya-Template-v2 §4), colored by status.
function _groveNode(g,pt,opts){
  opts=opts||{};
  const label=opts.label!=null?opts.label:g.pillar;
  const meta=opts.meta!=null?opts.meta:(g.status==='blossoming'?'◆ MASTERED · '+g.done+'/'+g.total
    :g.status==='active'?'○ ACTIVE · '+g.done+'/'+g.total
    :g.status==='locked'?'— LOCKED':(g.done+'/'+g.total));
  const grp=_svgEl('g',{transform:'translate('+pt.x+','+pt.y+')','class':'grove '+g.status});
  if(!opts.clickable===false && g.status!=='locked' && opts.onClick) grp.style.cursor='pointer';
  const st=g.status;
  if(st==='blossoming'){
    grp.appendChild(_svgEl('circle',{r:44,fill:'url(#glampM)',opacity:.75}));
    grp.appendChild(_svgEl('path',{d:'M0 34V6',stroke:'#7a4a2c','stroke-width':5}));
    grp.appendChild(_svgEl('circle',{cx:0,cy:-6,r:15,fill:'#2f6b3c'}));
    grp.appendChild(_svgEl('circle',{cx:-13,cy:5,r:9,fill:'#52a061'}));
    grp.appendChild(_svgEl('circle',{cx:13,cy:5,r:9,fill:'#52a061'}));
    grp.appendChild(_svgEl('circle',{cx:0,cy:-6,r:4,fill:'#f7d98a'}));           // blossoms
    grp.appendChild(_svgEl('circle',{cx:-10,cy:-2,r:2.4,fill:'#d63b2a'}));
    grp.appendChild(_svgEl('circle',{cx:10,cy:-2,r:2.4,fill:'#f7d98a'}));
  }else if(st==='active'){
    grp.appendChild(_svgEl('circle',{r:50,fill:'none',stroke:'#57d3ce','stroke-width':2,'stroke-dasharray':'4 6',opacity:.9}));  // ring
    grp.appendChild(_svgEl('circle',{r:44,fill:'#2ea3a0',opacity:.10}));
    grp.appendChild(_svgEl('path',{d:'M0 34V4',stroke:'#7a4a2c','stroke-width':5}));
    grp.appendChild(_svgEl('circle',{cx:0,cy:-8,r:15,fill:'#2f6b3c'}));
    grp.appendChild(_svgEl('circle',{cx:-13,cy:4,r:8,fill:'#2ea3a0'}));
    grp.appendChild(_svgEl('circle',{cx:13,cy:4,r:8,fill:'#52a061'}));
    grp.appendChild(_svgEl('circle',{cx:0,cy:-8,r:4,fill:'#57d3ce'}));
  }else if(st==='unlocked'){
    grp.appendChild(_svgEl('path',{d:'M0 34V6',stroke:'#7a4a2c','stroke-width':5}));
    grp.appendChild(_svgEl('circle',{cx:0,cy:-6,r:14,fill:'#2f6b3c'}));
    grp.appendChild(_svgEl('circle',{cx:-12,cy:5,r:8,fill:'#52a061'}));
    grp.appendChild(_svgEl('circle',{cx:12,cy:5,r:8,fill:'#52a061'}));
  }else{                                                                          // locked bare sapling
    grp.setAttribute('opacity',.5);
    grp.appendChild(_svgEl('path',{d:'M0 30V6',stroke:'#5a4a34','stroke-width':4}));
    grp.appendChild(_svgEl('path',{d:'M0 12l-10-8M0 12l10-8M0 20l-8-6M0 20l8-6',stroke:'#5a4a34','stroke-width':3}));
  }
  const lc=(st==='blossoming')?'#f0e3c6':(st==='active')?'#dcefe6':(st==='unlocked')?'#f0e3c6':'#a89670';
  const mc=(st==='blossoming')?'#e7b64b':(st==='active')?'#57d3ce':(st==='unlocked')?'#52a061':'#a89670';
  const t1=_svgEl('text',{x:0,y:st==='locked'?50:66,'text-anchor':'middle','font-family':'Marcellus','font-size':14,fill:lc});
  t1.textContent=_short(label,20); grp.appendChild(t1);
  const t2=_svgEl('text',{x:0,y:st==='locked'?66:82,'text-anchor':'middle','font-family':'JetBrains Mono','font-size':9.5,fill:mc});
  t2.textContent=meta; grp.appendChild(t2);
  const tt=_svgEl('title'); tt.textContent=g.pillar+' — '+g.done+'/'+g.total+' · '+st; grp.appendChild(tt);
  if(opts.onClick && st!=='locked') grp.addEventListener('click',opts.onClick);
  return grp;
}

// Statue of Droṇa (upper-right ridge) — lifted verbatim.
function _statue(x,y){
  const g=_svgEl('g',{transform:'translate('+x+','+y+')',opacity:.85});
  g.appendChild(_svgEl('rect',{x:-26,y:86,width:52,height:14,rx:3,fill:'#7a4a2c'}));
  g.appendChild(_svgEl('path',{d:'M0,6 C-16,6 -22,24 -20,44 L-18,84 L18,84 L20,44 C22,24 16,6 0,6Z',fill:'#a8482a'}));
  g.appendChild(_svgEl('circle',{cx:0,cy:-6,r:13,fill:'#b9764a'}));
  const dots=_svgEl('g',{fill:'#f2e7cc',opacity:.7});
  [[-8,34],[8,34],[0,52],[-9,66],[9,66]].forEach(([cx,cy])=>dots.appendChild(_svgEl('circle',{cx,cy,r:1.3})));
  g.appendChild(dots);
  const t=_svgEl('text',{x:0,y:112,'text-anchor':'middle','font-family':'Tiro Devanagari Hindi','font-size':13,fill:'#e7b64b'});
  t.textContent='गुरु द्रोण'; g.appendChild(t);
  return g;
}

function _mapDefs(){
  const defs=_svgEl('defs',{});
  defs.innerHTML=
    '<linearGradient id="mapbg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#122019"/><stop offset=".6" stop-color="#101528"/><stop offset="1" stop-color="#1a1305"/></linearGradient>'
   +'<pattern id="mdot" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="8" cy="8" r="1" fill="#f2e7cc" opacity="0.09"/></pattern>'
   +'<radialGradient id="glampM" cx="50%" cy="40%" r="60%"><stop offset="0" stop-color="#ffe9a8"/><stop offset="1" stop-color="#e7b64b" stop-opacity="0"/></radialGradient>';
  return defs;
}

function _paintMap(svg,pts,travelledUpto){
  const vb=svg.viewBox.baseVal, W=vb.width, H=vb.height;
  svg.textContent='';
  svg.appendChild(_mapDefs());
  svg.appendChild(_svgEl('rect',{width:W,height:H,fill:'url(#mapbg)'}));
  svg.appendChild(_svgEl('rect',{width:W,height:H,fill:'url(#mdot)'}));
  // full winding path (dashed clay), then the travelled gold portion up to the active grove
  const full=_pathThrough(pts,null);
  if(full) svg.appendChild(_svgEl('path',{d:full,fill:'none',stroke:'#a8482a','stroke-width':6,'stroke-linecap':'round','stroke-dasharray':'2 14',opacity:.55}));
  if(travelledUpto>=1){
    const gold=_pathThrough(pts,travelledUpto);
    if(gold) svg.appendChild(_svgEl('path',{d:gold,fill:'none',stroke:'#e7b64b','stroke-width':4,'stroke-linecap':'round','stroke-dasharray':'2 14'}));
  }
  svg.appendChild(_statue(W-140,90));
}

function _legend(svg,items){
  const vb=svg.viewBox.baseVal;
  const g=_svgEl('g',{transform:'translate(28,'+(vb.height-18)+')','font-family':'JetBrains Mono','font-size':10});
  let x=0;
  items.forEach(([col,lab])=>{
    g.appendChild(_svgEl('circle',{cx:x+6,cy:-3,r:5,fill:col}));
    const t=_svgEl('text',{x:x+16,y:1,fill:'#c3b291'});t.textContent=lab;g.appendChild(t);
    x+=16+lab.length*7+34;
  });
  svg.appendChild(g);
}

async function showForest(){
  const svg=document.getElementById('forestsvg');
  document.getElementById('tabForest').classList.add('on');
  document.getElementById('tabTrack').classList.remove('on');
  document.getElementById('treesub').textContent='groves on a winding path · a tap enters a grove';
  svg.setAttribute('viewBox','0 0 900 640'); svg.textContent='';
  try{
    const c=await (await fetch('/api/forest')).json();
    if(c.empty){ _emptyMap(svg); document.getElementById('tabTrack').disabled=true; return; }
    _curFocus=c.active;
    document.getElementById('tabTrack').disabled=!_curFocus;
    const pts=c.layout.points, vb=c.viewbox;
    svg.setAttribute('viewBox',vb.join(' '));
    // travelled = up to and including the active grove along the walk order
    let upto=c.groves.findIndex(g=>g.status==='active')+1;
    if(upto<=0) upto=c.groves.filter(g=>g.status==='blossoming').length;
    _paintMap(svg,pts,upto);
    c.groves.forEach((g,i)=>{
      if(!pts[i]) return;
      svg.appendChild(_groveNode(g,pts[i],{onClick:()=>showGrove(g.pillar)}));
    });
    _legend(svg,[['#e7b64b','mastered'],['#57d3ce','active'],['#52a061','unlocked'],['#5a4a34','locked']]);
  }catch(e){ _emptyMap(svg,'could not load the forest map.'); }
}

// Drill-in: one grove's concepts as a smaller sub-forest (same visual language).
async function showGrove(pillar){
  pillar=pillar||_curFocus;
  if(!pillar) return showForest();
  const svg=document.getElementById('forestsvg');
  document.getElementById('tabForest').classList.remove('on');
  document.getElementById('tabTrack').classList.add('on');
  document.getElementById('tabTrack').disabled=false;
  svg.textContent='';
  try{
    const c=await (await fetch('/api/forest?pillar='+encodeURIComponent(pillar))).json();
    if(c.empty){ _emptyMap(svg); return; }
    document.getElementById('treesub').textContent='◆ '+pillar+' · '+c.grove.done+'/'+c.grove.total+' concepts · ← overview to return';
    const pts=c.layout.points, vb=c.viewbox;
    svg.setAttribute('viewBox',vb.join(' '));
    const done=c.concepts.filter(x=>x.status==='done').length;
    _paintMap(svg,pts,done);
    // map a concept's status onto a grove-status so the same tree art applies
    const S={done:'blossoming',avail:'active',lock:'locked'};
    c.concepts.forEach((cc,i)=>{
      if(!pts[i]) return;
      const g={pillar:cc.name,status:S[cc.status]||'locked',done:cc.status==='done'?1:0,total:1};
      const meta=cc.status==='done'?'◆ MASTERED':cc.status==='avail'?'○ AVAILABLE':'— LOCKED';
      svg.appendChild(_groveNode(g,pts[i],{label:cc.name,meta:meta}));
    });
    // a back-to-overview control drawn in-canvas (also on the ◆ tab)
    const back=_svgEl('g',{transform:'translate(70,40)','class':'grove',style:'cursor:pointer'});
    back.addEventListener('click',showForest);
    const bt=_svgEl('text',{x:0,y:0,'font-family':'JetBrains Mono','font-size':12,fill:'#e7b64b'});
    bt.textContent='← overview'; back.appendChild(bt); svg.appendChild(back);
    _legend(svg,[['#e7b64b','mastered'],['#57d3ce','available'],['#5a4a34','locked']]);
  }catch(e){ _emptyMap(svg,'could not load this grove.'); }
}

function _emptyMap(svg,msg){
  svg.setAttribute('viewBox','0 0 900 560'); svg.textContent='';
  svg.appendChild(_mapDefs());
  svg.appendChild(_svgEl('rect',{width:900,height:560,fill:'url(#mapbg)'}));
  const t=_svgEl('text',{x:450,y:270,'text-anchor':'middle','font-family':'Marcellus','font-size':18,fill:'#cfc0a0'});
  t.textContent=msg||'No forest yet — finish onboarding and Ekalavya will plant your groves.';
  svg.appendChild(t);
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
// XP is a continuous rank-ring fill (template's headline: a ring, not an emoji/bar).
// C = 2πr for r=47 ≈ 295.3; the arc's dash-offset shrinks from C (empty) to (1-p)·C (p full).
const RING_C=295.3;
function rankRingSVG(level,pct){
  const off=(RING_C*(1-pct)).toFixed(1);
  return "<svg class='rank-ring' width='34' height='34' viewBox='0 0 104 104' aria-label='XP "+
    Math.round(pct*100)+"% to next rank'>"+
    "<circle cx='52' cy='52' r='47' fill='none' stroke='rgba(231,182,75,.16)' stroke-width='7'/>"+
    "<circle class='arc' cx='52' cy='52' r='47' fill='none' stroke='url(#ringGrad)' stroke-width='7' "+
    "stroke-linecap='round' stroke-dasharray='"+RING_C+"' stroke-dashoffset='"+off+"'/>"+
    "<circle cx='52' cy='52' r='32' fill='#101528' stroke='#f7d98a' stroke-width='2' transform='rotate(90 52 52)'/>"+
    "<text x='52' y='60' text-anchor='middle' font-family='Cinzel' font-weight='800' font-size='30' fill='#f7d98a' transform='rotate(90 52 52)'>"+level+"</text></svg>";
}
function setHud(s){const pct=(s.xp%100)/100, next=s.level+1;
  document.getElementById('hud').innerHTML =
   rankRingSVG(s.level, pct)+
   "<span class='flame'><svg width='11' height='14' viewBox='0 0 46 58' style='vertical-align:-2px'><path d='M23 4 C31 18 40 22 38 36 C37 49 30 54 23 54 C16 54 8 48 8 36 C8 27 16 24 18 14 C22 20 20 26 24 30 C28 24 24 16 23 4Z' fill='#e7b64b'/></svg> <b>"+s.streak+"</b>d</span>"+
   "<span class='rank'>"+rank(s.level)+"</span>"+
   "<span class='prog'>Lv <b>"+s.level+"</b> · <b>"+Math.round(pct*100)+"%</b> → R"+next+"</span>";}
function refreshHud(){ fetch('/api/stats').then(r=>r.json()).then(s=>{ setHud(s); celebrate(s); }).catch(()=>{}); }

/* ===== celebration moments (template §5): level-up ceremony + achievement toast =====
   The app exposes level + streak; we mirror the dashboard's achievement rules client-side
   and fire a moment the first time the level rises or a new achievement is earned. Prior
   state is remembered in localStorage so a moment fires once, not on every refresh. */
function rankTitle(l){const T=[[17,'Grandmaster of the Forest'],[12,'Master Archer'],[8,'Archer of the Deep Forest'],[5,'Adept of the String'],[3,'Apprentice Archer'],[1,'Novice of the Grove']];
  for(const [t,n] of T) if(l>=t) return n; return 'Novice of the Grove';}
function earnedAchievements(s){
  const a=[];
  if(s.streak>=3) a.push(['On Fire','A 3-day streak — the string stays warm.']);
  if(s.streak>=7) a.push(['Week Warrior','Seven days unbroken.']);
  if(s.streak>=30) a.push(['Unbroken','A 30-day streak. The forest remembers.']);
  if(s.level>=5) a.push(['Adept','Reached level 5.']);
  if(s.level>=10) a.push(['Master','Reached level 10.']);
  return a;
}
function showAchievement(name, desc){
  document.getElementById('achname').textContent=name;
  document.getElementById('achdesc').textContent=desc;
  const t=document.getElementById('achtoast'); t.classList.add('on');
  setTimeout(()=>t.classList.remove('on'),4200);
}
function _ceremonyRays(){ const g=document.getElementById('ceremonyrays'); if(g.childElementCount) return;
  for(let i=0;i<40;i++){ const a=i*9*Math.PI/180, x2=100+96*Math.cos(a), y2=100+96*Math.sin(a);
    const l=document.createElementNS(SVGNS,'line'); l.setAttribute('x1',100);l.setAttribute('y1',100);
    l.setAttribute('x2',x2.toFixed(1));l.setAttribute('y2',y2.toFixed(1)); g.appendChild(l);} }
function showCeremony(level){
  _ceremonyRays();
  document.getElementById('cerlvl').textContent='RANK '+level;
  document.getElementById('certitle').innerHTML='You are now <b>'+rankTitle(level)+'</b>';
  const box=document.querySelector('#ceremony .ccontent'); box.classList.remove('bloom'); void box.offsetWidth; box.classList.add('bloom');
  document.getElementById('ceremony').classList.add('on');
}
function dismissCeremony(){ document.getElementById('ceremony').classList.remove('on'); }
let _celebReady=false;   // don't fire on the very first load (that's the returning state, not a change)
function celebrate(s){
  const prevLvl=parseInt(localStorage.getItem('ek_lvl')||'0',10);
  const prevAch=JSON.parse(localStorage.getItem('ek_ach')||'[]');
  const nowAch=earnedAchievements(s).map(a=>a[0]);
  if(_celebReady){
    if(s.level>prevLvl) showCeremony(s.level);
    const fresh=earnedAchievements(s).find(a=>!prevAch.includes(a[0]));
    if(fresh && !(s.level>prevLvl)) showAchievement(fresh[0], fresh[1]);   // one moment at a time
  }
  localStorage.setItem('ek_lvl', s.level); localStorage.setItem('ek_ach', JSON.stringify(nowAch));
  _celebReady=true;
}
function showReclaim(amt){ const r=document.getElementById('reclaim');
  document.getElementById('reclaimn').textContent="+"+amt+" XP restored"; r.classList.add('on');
  setTimeout(()=>r.classList.remove('on'),2800); }
function flagCheat(reason){
  // NEVER wipe the editor — the learner's work always stays.
  if(!deathOnCheat){                 // penalty disabled → a quiet note, no punishment
    addMsg('ai','<span class="dim">⚠ '+reason+" — noticed, but the penalty is off, so nothing happens.</span>");
    return;
  }
  fetch('/api/penalise',{method:'POST'}).then(r=>r.json()).then(d=>{
    document.getElementById('deathsub').innerHTML =
      reason+". Streak broken. <span class='dim'>Your code is untouched.</span>";
    document.getElementById('deathmerit').textContent = "−"+d.lost+" XP";
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
const WELCOME_HTML=document.getElementById('arenawelcome') ? document.getElementById('arenawelcome').outerHTML : '';
function clearWelcome(){ const w=document.getElementById('arenawelcome'); if(w) w.remove();
  const th=document.getElementById('onbthreshold'); if(th) th.remove(); }  // threshold recedes once teaching begins
function showWelcome(sub){ const l=document.getElementById('log'); if(!document.getElementById('arenawelcome')) l.insertAdjacentHTML('afterbegin', WELCOME_HTML);
  if(sub){ const s=document.getElementById('awsub'); if(s) s.textContent=sub; } }
function addMsg(role, html){
  clearWelcome();
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
  if(document.getElementById('arenawelcome')) m.style.display='none';  // stay hidden behind the welcome until first content
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
      if(o.t){ clearWelcome(); ui.m.style.display=''; ui.buf+=o.t; const now=Date.now();
        if(now-(ui._lr||0)>100){ ui._lr=now; ui.reply.innerHTML=DOMPurify.sanitize(marked.parse(ui.buf)); }
        scroll(); }
      else if(o.tool){ clearWelcome(); ui.m.style.display=''; ui.steps++; ui.trace.style.display='block';
        traceLine(ui.tb,'call','→ '+prettyTool(o.tool)); ui.sum.textContent=prettyTool(o.tool)+'…'; scroll(); }
      else if(o.result){ traceLine(ui.tb,'res','✓ '+prettyTool(o.result.name)); }
      else if(o.approval){ await askApproval(ui, o.approval); }
    }
  }
}
let queued=null, queuedSubmit=false;
function setBusy(on){ const b=document.querySelector('.inbar .send'); if(b){b.disabled=on;b.style.opacity=on?'.45':'';b.textContent=on?'…':'Send';} renderTurnCtl(); }
// themed error card (template §5) — "The arrow found no wind" + Retry
function addErrorCard(desc, onRetry){
  clearWelcome();
  const d=el('errcard');
  d.innerHTML='<svg width="40" height="40" viewBox="0 0 24 24" fill="none"><path d="M12 3 L21 20 H3 Z" stroke="#ff5a3c" stroke-width="1.6"/>'+
    '<line x1="12" y1="10" x2="12" y2="14" stroke="#ff5a3c" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17" r="1" fill="#ff5a3c"/></svg>'+
    '<div class="ek">◆ something went awry</div><div class="et">The arrow found no wind</div>'+
    '<div class="ed">'+desc+'</div><button>↻ Retry</button>';
  d.querySelector('button').onclick=()=>{ d.remove(); onRetry(); };
  document.getElementById('log').appendChild(d); scroll(); return d;
}
async function stream(text, code){
  if(streaming) return; streaming=true; setBusy(true);
  const ui=addAiMsg();
  if(turns.length && !turns[turns.length-1].ai) turns[turns.length-1].ai=ui.m;  // pair with its user turn
  let failed=false, aborted=false;
  streamAbort=new AbortController();          // Esc → abort this fetch (server stops on disconnect)
  try{
    const res=await fetch('/api/stream',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({thread,mode,text,code:code||undefined}),signal:streamAbort.signal});
    await consume(res, ui);
  }catch(e){ if(e&&e.name==='AbortError'){ aborted=true; } else { failed=true; } }
  streamAbort=null; streaming=false; setBusy(false);
  if(aborted){                                               // learner pressed Esc — stop cleanly
    if(ui.buf.trim() || ui.steps>0){ ui.m.style.display=''; finalizeMsg(ui);
      const n=el('cancelnote'); n.textContent='◦ stopped'; ui.reply.appendChild(n); }
    else { ui.m.remove(); }
    if(queued && queued.you){ queued.you.remove(); }         // drop the message typed mid-stream, unsent
    queued=null; queuedSubmit=false; renderTurnCtl(); refreshHud(); return;
  }
  if(failed && !ui.buf.trim() && ui.steps===0){             // couldn't reach the guru at all
    ui.m.remove();
    addErrorCard("Couldn't reach the guru. Check the connection and loose again.", ()=>stream(text, code));
    return;
  }
  if(!ui.buf.trim() && ui.steps===0){                       // the turn produced nothing (e.g. no provider key)
    ui.m.remove(); showWelcome('Nothing came back — check that a provider key is set, then hit ↻ New.');
  } else { ui.m.style.display=''; finalizeMsg(ui); }
  refreshHud();
  if(queued){ const q=queued; queued=null;                     // a message typed mid-stream
    turns.push(q); attachEdit(q); renderTurnCtl(); stream(q.text); }
  else if(queuedSubmit){ queuedSubmit=false; submitCode(); }   // a code submit clicked mid-stream
}
function cancelStream(){ if(streaming && streamAbort){ streamAbort.abort(); } }

// --- rewind + edit (conversation controls, #36) ---------------------------
// The visible transcript and the server's checkpointed thread are kept in lock-step:
// dropping/editing a turn removes it (and everything after) from both. `turns` records
// one entry per learner turn with handles to its "you" + "ai" bubbles.
function renderTurnCtl(){
  const b=document.getElementById('rewindbtn'); if(!b) return;
  b.hidden = turns.length===0;                       // nothing to rewind yet
  b.disabled = streaming;                            // never rewind mid-reply
}
function attachEdit(turn){
  if(!turn.you || turn.code || turn.you.querySelector('.editbtn')) return;   // code submits: no inline edit
  const btn=el('editbtn'); btn.textContent='edit';
  btn.onclick=()=>{ const i=turns.indexOf(turn); if(i>=0) startEdit(i); };   // index resolved live (shifts on rewind)
  turn.you.appendChild(btn);
}
async function truncateServer(keepUserTurns){
  try{ await fetch('/api/truncate',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({thread,mode,keep_user_turns:keepUserTurns})}); }catch(e){}
}
async function rewind(){
  if(streaming || !turns.length) return;
  const last=turns.pop();                            // drop the last exchange from the UI…
  if(last.you) last.you.remove(); if(last.ai) last.ai.remove();
  await truncateServer(turns.length);                // …and from the server thread
  renderTurnCtl();
  if(!last.code){                                    // restore the prior input for a quick redo
    const inp=document.getElementById('chatin');
    inp.value=last.text; inp.style.height='auto'; inp.style.height=Math.min(inp.scrollHeight,150)+'px'; inp.focus();
  }
  if(!turns.length) showWelcome();
}
function startEdit(idx){
  if(streaming) return; const turn=turns[idx]; if(!turn || turn.code) return;   // code submits aren't inline-editable
  const you=turn.you; if(!you || you.classList.contains('editing')) return;
  you.classList.add('editing');
  const body=you.querySelector('.body'); const orig=body.innerHTML;
  body.innerHTML='';
  const ta=el('editarea'); ta.value=turn.text;
  const bar=el('editbtns');
  const save=document.createElement('button'); save.className='save'; save.textContent='Re-run';
  const cancel=document.createElement('button'); cancel.textContent='Cancel';
  bar.appendChild(save); bar.appendChild(cancel);
  body.appendChild(ta); body.appendChild(bar); ta.focus();
  cancel.onclick=()=>{ you.classList.remove('editing'); body.innerHTML=orig; };
  save.onclick=async()=>{
    const t=ta.value.trim(); if(!t){ cancel.onclick(); return; }
    // drop this turn and everything after it, on both sides, then re-run from the edit
    for(let i=turns.length-1;i>=idx;i--){ const tt=turns[i]; if(tt.you) tt.you.remove(); if(tt.ai) tt.ai.remove(); }
    turns.length=idx;
    await truncateServer(idx);
    const you=addMsg('you', renderMd(t)).closest('.msg');
    const turn={text:t, you, ai:null}; turns.push(turn); attachEdit(turn); renderTurnCtl();
    stream(t);
  };
}

function sendChat(){
  const inp=document.getElementById('chatin'); const t=inp.value.trim(); if(!t)return;
  inp.value=''; inp.style.height='auto'; const you=addMsg('you', renderMd(t)).closest('.msg');
  const turn={text:t, you, ai:null};
  if(streaming){ queued=turn; return; }   // queue it; it fires (and is tracked) when the current turn ends
  turns.push(turn); attachEdit(turn); renderTurnCtl();
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
// Parse a run's output into "test arrows" for the .ed-tests panel. Recognises the common
// self-check shapes learners print: "✓/✗ name", "PASS/FAIL: name", "name ... ok",
// assertion lines. Falls back to a single pass/fail from the exit code so the panel is
// always meaningful after a Run.
const ET_PASS='<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M5 13 l4 4 L19 7" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"/></svg>';
const ET_FAIL='<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M6 6 l12 12 M18 6 l-12 12" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>';
function parseTests(r){
  const out=[]; const lines=((r.stdout||'')+'\n'+(r.stderr||'')).split('\n');
  for(let ln of lines){ const s=ln.trim(); if(!s) continue;
    let m;
    if((m=s.match(/^(?:✓|PASS(?:ED)?[:\s])\s*(.+)$/i))) out.push({pass:true, name:m[1].trim()});
    else if((m=s.match(/^(?:✗|✕|x|FAIL(?:ED)?[:\s])\s*(.+)$/i))) out.push({pass:false, name:m[1].trim()});
    else if((m=s.match(/^(.+?)\s*(?:\.\.\.|:)\s*(ok|pass(?:ed)?)$/i))) out.push({pass:true, name:m[1].trim()});
    else if((m=s.match(/^(.+?)\s*(?:\.\.\.|:)\s*(fail(?:ed)?|error)$/i))) out.push({pass:false, name:m[1].trim()});
    else if(/AssertionError|Traceback|Error:/.test(s) && out.length) out[out.length-1].pass=false;
  }
  if(!out.length) out.push({pass:r.ok, name:r.ok?'code ran without error':'run failed'});
  return out;
}
function renderTests(r){
  const tests=parseTests(r);
  const panel=document.getElementById('edtests'), list=document.getElementById('etlist');
  const passed=tests.filter(t=>t.pass).length;
  list.innerHTML=tests.map(t=>
    '<div class="ed-test '+(t.pass?'pass':'fail')+'"><span class="et-i">'+(t.pass?ET_PASS:ET_FAIL)+
    '</span><span class="et-n">'+esc(t.name)+'</span><span class="et-t">'+(t.pass?'strike':'miss')+'</span></div>').join('');
  document.getElementById('etcount').innerHTML='<b>'+passed+'</b> / '+tests.length+' strike';
  const miss=tests.find(t=>!t.pass);
  document.getElementById('ethint').innerHTML = miss
    ? 'One arrow fell short — <code>'+esc(miss.name)+'</code>. Fix it, then loose again.'
    : (passed>1 ? 'Every arrow struck. Submit when you are ready.' : 'The arrow flew — write a few checks to grade it truly.');
  panel.classList.remove('hidden');
}
async function runCode(){
  if(!editor) return; const code=editor.getValue(); if(!code.trim()) return;
  const box=addRunOut('<span class="dim">▶ running…</span>');
  try{
    const r=await (await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code})})).json();
    renderRunOut(box, r); renderTests(r);
  }catch(e){ box.remove(); addErrorCard("Couldn't run your code — the sandbox didn't answer. Try again.", runCode); }
}
(function(){const ta=document.getElementById('chatin');
  ta.addEventListener('input',()=>{ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,150)+'px';});
  ta.addEventListener('keydown',e=>{ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat();} });
  // Esc anywhere in the arena cancels an in-flight reply (never while editing a past turn).
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape' && streaming && !document.querySelector('.msg.editing')){ e.preventDefault(); cancelStream(); }
  });
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
  turns.push({text:msg, you:body.closest('.msg'), ai:null, code:true}); renderTurnCtl();  // code submit: no inline edit
  lastSentCode = editor.getValue();   // the agent just saw this code — don't re-attach it next chat
  stream(msg);
}

// --- AI assistant panel (AI-enabled interview mode) ---
let assbusy=false;
function applyMode(){  // show the AI-assistant drawer only in aiinterview mode
  document.getElementById('assistpanel').classList.toggle('hidden', mode!=='aiinterview');
  document.getElementById('resumebar').classList.toggle('hidden', mode!=='onboard');  // résumé upload only during onboarding
  showThreshold();  // the framed "Cross the threshold" intro shows only at the start of onboarding
}
// Onboarding threshold (template C) — a framed "Cross the threshold / प्रवेश" intro at the
// head of the chat when a first-time setup begins. It stays above the log until the guru's
// first message arrives, then recedes (clearWelcome removes it with the welcome block).
function showThreshold(){
  const existing=document.getElementById('onbthreshold'); if(existing) existing.remove();
  const log=document.getElementById('log');
  if(mode!=='onboard' || log.querySelector('.msg')) return;  // only before the first real message
  log.insertAdjacentHTML('afterbegin',
    "<div class='onb-threshold' id='onbthreshold'>"+
    "<div class='onb-eye'>◆ Cross the threshold</div>"+
    "<div class='onb-h'>You stand at the forest's edge, <span class='em'>unnamed</span>.</div>"+
    "<div class='onb-deva'>प्रवेश · the entering</div>"+
    "<div class='onb-sub'>Before the guru of stone can teach you, it must learn who you are — your goal, your ground, your honest edge. Answer a few questions. Nothing here is a test.</div>"+
    "<div class='onb-steps'><i class='on'></i><i></i><i></i><i></i><i></i></div></div>");
}
function uploadResume(){
  const inp=document.getElementById('resumefile'); const hint=document.getElementById('resumehint');
  const f=inp.files&&inp.files[0]; if(!f) return;
  hint.className='resumehint'; hint.textContent='reading '+f.name+'…';
  const fd=new FormData(); fd.append('file', f);
  fetch('/api/upload-resume',{method:'POST',body:fd})
    .then(r=>r.json().then(d=>({ok:r.ok,d})))
    .then(({ok,d})=>{
      if(ok&&d.ok){ hint.className='resumehint ok'; hint.textContent='✓ résumé read ('+d.chars+' chars) — Ekalavya will use it'; }
      else { hint.className='resumehint bad'; hint.textContent=(d&&d.error)||'could not read that PDF'; }
    })
    .catch(()=>{ hint.className='resumehint bad'; hint.textContent='upload failed — please try again'; })
    .finally(()=>{ inp.value=''; });
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
  turns=[]; renderTurnCtl();
  if(editor) editor.setValue(STUB);
  document.getElementById('log').innerHTML=''; document.getElementById('asslog').innerHTML=''; showWelcome();
  showPane('editor');  // a fresh session starts on the editor, not a stale canvas
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
    const log=document.getElementById('log'); log.innerHTML=''; turns=[];
    for(const m of (c.transcript||[])){
      const b=addMsg(m.role==='you'?'you':'ai',''); b.innerHTML=renderMd(m.text);  // renderMd already highlights
      // rebuild turn pairs so rewind/edit work on a loaded chat too
      if(m.role==='you'){ const turn={text:m.text, you:b.closest('.msg'), ai:null}; turns.push(turn); attachEdit(turn); }
      else if(turns.length && !turns[turns.length-1].ai){ turns[turns.length-1].ai=b.closest('.msg'); }
      try{ await mermaid.run({nodes:b.querySelectorAll('.mermaid')}); }catch(e){}
    }
    renderTurnCtl();
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
<link rel="stylesheet" href="/static/fonts.css">
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
    <div class="auth-tabs" role="tablist" aria-label="Authentication mode">
      <span class="on" id="tab-login" role="tab" tabindex="0" aria-selected="true" onclick="authMode('login')">Log in</span>
      <span id="tab-signup" role="tab" tabindex="0" aria-selected="false" onclick="authMode('signup')">Sign up</span>
    </div>
    <div class="ah" id="auth-h">Welcome back, devotee</div>
    <div class="asub" id="auth-sub">The forest remembers where you left the string.</div>
    {{error}}
    <div class="signup-note" id="signup-note" style="display:none;font-family:var(--f-serif);font-style:italic;font-size:13.5px;color:var(--parch-dim);border:1px solid var(--line-soft);background:rgba(6,9,20,.4);border-radius:6px;padding:11px 13px;margin:0 0 14px">
      New statues are raised from the terminal for now — ask your guru to run <code style="font-family:var(--f-mono);color:var(--peacock-bright);font-style:normal">eklavya adduser</code>, then log in here.
    </div>
    <form method="post" action="/login">
      <div class="field"><label class="field-lbl" for="email">Email</label>
        <input id="email" class="inp" name="email" type="email" autocomplete="username" required autofocus></div>
      <div class="field"><label class="field-lbl" for="password">Password</label>
        <input id="password" class="inp" name="password" type="password" autocomplete="current-password" required></div>
      <button type="submit" class="btn btn-gold" id="auth-submit" style="width:100%;justify-content:center;margin-top:8px">Sign in — draw the string</button>
    </form>
  </div>
</div>
</div>
<script>
// Visual Log-in ↔ Sign-up toggle. Auth is email/password only (no OAuth); sign-ups are
// created from the CLI (eklavya adduser), so the Sign-up tab explains that and keeps the
// same working login form — it never posts a signup.
function authMode(m){
  const login=m==='login';
  document.getElementById('tab-login').classList.toggle('on',login);
  document.getElementById('tab-login').setAttribute('aria-selected',login);
  document.getElementById('tab-signup').classList.toggle('on',!login);
  document.getElementById('tab-signup').setAttribute('aria-selected',!login);
  document.getElementById('auth-h').textContent = login ? 'Welcome back, devotee' : 'Raise your own statue';
  document.getElementById('auth-sub').textContent = login
    ? 'The forest remembers where you left the string.'
    : 'The one refused a teacher taught himself. Begin the same way.';
  document.getElementById('signup-note').style.display = login ? 'none' : 'block';
  document.getElementById('auth-submit').textContent = login ? 'Sign in — draw the string' : 'Log in to your statue';
}
</script>
</body></html>"""


# --- public landing (brand mode, marketing) --------------------------------
# Reuses the Option-E landing markup: the outsider pitch as the anchor, one hero
# illustration (lone archer before the stone idol), one clear CTA, varied-weight feature
# cards. Sparing gold on the uniform indigo ground.
_HEAD = (
    '<link rel="stylesheet" href="/static/fonts.css">'
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
          <!-- highlight-to-ask: selecting any phrase raises this popover to ask the guru about it -->
          <div class="selpop selpop-below" style="left:34px;top:190px">Ask about this ✦</div>
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
