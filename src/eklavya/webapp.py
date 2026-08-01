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
            "aiinterview": prompts.AI_INTERVIEW, "gauntlet": prompts.GAUNTLET,
            "blitz": prompts.BLITZ, "boss": prompts.BOSS,
            "takehome": prompts.TAKEHOME, "onboard": prompts.ONBOARDING}
_KICKOFF = {
    "practice": "Start today's practice session. I have 30 minutes.",
    "mock": "Start a mock interview. I have 45 minutes.",
    "aiinterview": "Start an AI-assisted mock interview. I have 45 minutes.",
    "gauntlet": "Enter the Gauntlet. Throw challenges at me until I break.",
    "blitz": "Start a Blitz round. Fire fast recall questions at me.",
    "boss": "I'm ready for a boss fight — pick the pillar and let's go.",
    "takehome": "Give me a take-home assignment. I have 90 minutes.",
    "onboard": "Begin my first-time onboarding — I'm brand new here.",
}
_SESSION_MIN = {"practice": 30, "mock": 45, "aiinterview": 45, "takehome": 90,
                "gauntlet": 20, "blitz": 7, "boss": 30}
_SESSION_MODES = ("practice", "mock", "aiinterview", "takehome", "gauntlet", "blitz", "boss")
_MODE_LABEL = {"practice": "Practice session", "mock": "Mock interview",
               "aiinterview": "AI-enabled interview", "gauntlet": "The Gauntlet",
               "blitz": "Blitz", "boss": "Boss fight",
               "takehome": "Take-home", "onboard": "Onboarding"}


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

    def _current_email() -> str | None:
        """The logged-in user's email (multi-user only) — for the account menu."""
        if not config.MULTIUSER:
            return None
        from . import auth
        u = auth.get_user(_current_user_id())
        return u.get("email") if u else None

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
        from . import settings

        mode = mode if mode in _PROMPTS else "practice"
        uid = user_id or _current_user_id()
        tools = _TOOLS.get(mode, SESSION_TOOLS)
        if settings.get_provider() == "auto":
            # Balanced: no pinned lead — the entry provider rotates across configured keys
            # (still falls back on error). Rebuilds cache-independently of any single key.
            key = (uid, mode, "auto")
            if key not in agents:
                agents[key] = build_agent(_PROMPTS[mode], tools, provider=None, balance=True)
            return agents[key]
        prov = _active_provider()
        key = (uid, mode, prov.key)   # provider in the key → switching rebuilds the agent
        if key not in agents:
            agents[key] = build_agent(_PROMPTS[mode], tools, provider=prov.key)
        return agents[key]

    app = FastAPI(title="Ekalavya", docs_url=None, redoc_url=None)

    # Shared design-system stylesheet (Option E cinematic-forest) — one served file that
    # every screen (SPA, dashboard, journey, profile in their iframes, login) links to.
    _STATIC_DIR = Path(__file__).parent / "static"

    class _CorsStatic(StaticFiles):
        """Serve /static with `Access-Control-Allow-Origin: *`. These are public assets, and the
        sandboxed viz iframe (an opaque 'null' origin) must be able to load them — fonts in
        particular are CORS-checked, so KaTeX's webfonts fail there without this header."""

        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            response.headers.setdefault("Access-Control-Allow-Origin", "*")
            return response

    app.mount("/static", _CorsStatic(directory=str(_STATIC_DIR)), name="static")

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

    # Client-only SPA views (Forest / Library / Settings have no server render) used to 404 on a
    # direct URL or refresh. Serve the SPA for them too; a small on-load hook reads the path and
    # opens the matching view. (Dashboard/Journey/Effectiveness/Profile already have real routes.)
    @app.get("/forest", response_class=HTMLResponse)
    @app.get("/library", response_class=HTMLResponse)
    @app.get("/settings", response_class=HTMLResponse)
    def spa_view() -> str:
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

    @app.get("/effectiveness", response_class=HTMLResponse)
    def effectiveness() -> str:
        from .effectiveness import render as render_effectiveness

        return render_effectiveness()

    @app.get("/api/effectiveness")
    def effectiveness_api() -> dict:
        from .effectiveness import summary

        return summary()

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
        from . import providers, settings

        if settings.get_provider() == "auto":
            configured = providers.configured_providers()
            return {"provider": "Auto (balanced)",
                    "model": "rotates across " + str(len(configured)) + " provider(s)",
                    "kickoff": _KICKOFF, "configured": bool(configured),
                    "first_run": report.is_first_run(), "email": _current_email(),
                    "death_on_cheat": settings.get_death_on_cheat()}
        prov = _active_provider()
        return {"provider": prov.label, "model": prov.default_model,
                "kickoff": _KICKOFF, "configured": prov.is_configured(),
                "first_run": report.is_first_run(), "email": _current_email(),
                "death_on_cheat": settings.get_death_on_cheat()}

    @app.get("/api/settings")
    def settings_get() -> dict:
        from . import providers, settings

        s = settings.get_all()
        # the full provider catalogue (key + label + whether a key is set), so the
        # selector can list glm/minimax/qwen/kimi and mark the configured ones.
        provs = [{"key": p.key, "label": p.label, "configured": p.is_configured()}
                 for p in providers.PROVIDERS.values()]
        active = "auto" if settings.get_provider() == "auto" else _active_provider().key
        return {**s, "providers": provs, "active_provider": active}

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
        active = "auto" if settings.get_provider() == "auto" else _active_provider().key
        return {**updated, "active_provider": active}

    def _events(agent, config, thread, inputs):
        """One agent run (a new turn OR a resume): route tool activity to the trace,
        stream the reply, and pause for run_bash approval (auto-approving safe read-only ones)."""
        from langgraph.types import Command

        from .agent import is_safe_bash
        from .verify import selfcheck

        try:  # the learner's message (a fresh turn) → context for the judge; "" on resume
            user_context = inputs["messages"][0]["content"] if isinstance(inputs, dict) else ""
        except (KeyError, IndexError, TypeError):
            user_context = ""
        buf = []
        run_outputs = []  # actual sandbox/run tool results this turn → context for the judge
        _RUN_TOOLS = {"run_bash", "grade_and_record"}  # tools whose output is real execution
        # Loop the run so a run_bash that pauses for approval can be AUTO-APPROVED when it's a
        # safe, read-only command (whitelist) — resume in place and keep streaming — while any
        # other command still stops for the learner's explicit yes/no.
        current = inputs
        while True:
            try:
                for chunk, _meta in agent.stream(current, config=config, stream_mode="messages"):
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
            if not approval:
                break
            if is_safe_bash(approval.get("command", "")):  # safe read-only → run without asking
                yield json.dumps({"autorun": approval}) + "\n"  # trace shows it ran, no prompt
                current = Command(resume={"decisions": [{"type": "approve"}]})
                continue
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
        if mode in _SESSION_MODES:
            # A practice session is beginning: kick off a throttled, background,
            # offline-safe refresh of this user's question bank toward their targets.
            # Non-blocking and never-raising — it can't delay the stream or the first token.
            from .questions_refresh import maybe_autorefresh

            try:
                maybe_autorefresh()
            except Exception:
                pass
            progress.ensure_session(_SESSION_MIN.get(mode, 30), mode)  # open/reuse this sitting
        # Temporal awareness: prepend a fresh, private clock/recap line each turn (elapsed,
        # gap since last visit, last-time topics, due reviews, today's date). Also gives the
        # otherwise-dateless onboarding agent today's date. Shared with CLI/TUI for parity.
        text = report.with_session_context(text)
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

    @app.post("/api/feedback")
    async def feedback_submit(request: Request):
        """Record one learner-feedback tap (rating and/or text). Writes to the current
        user's own db via the contextvar, so there is no cross-user risk."""
        from . import feedback

        body = await request.json()
        feedback.record(
            kind=body.get("kind") or "freeform",
            rating=body.get("rating"),
            text=body.get("text"),
            concept=body.get("concept"),
            mode=body.get("mode"),
            thread=body.get("thread"),
        )
        return {"ok": True}

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

    @app.delete("/api/chats/{thread_id}")
    def chat_delete(thread_id: str) -> dict:
        from .chatstore import delete_chat

        _require_owner(thread_id)
        delete_chat(thread_id)
        return {"deleted": True}

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

    def _auth_page(start: str, error: str, notice: str = "") -> str:
        # one themed template serves both tabs; `start` picks which is active on load.
        # `start_is_signup` lets the client reveal the auth card + jump to it straightaway when
        # the visitor arrives on /signup (or bounces back with an error), skipping the hero scroll.
        return (_LOGIN.replace("{{start}}", start)
                .replace("{{start_is_signup}}", "true" if start == "signup" else "false")
                .replace("{{error}}", error and f'<div class="err">{error}</div>' or "")
                .replace("{{notice}}", notice and f'<div class="notice">{notice}</div>' or ""))

    def _begin_session(uid: str):
        """Create the user's home/db on first entry and hand back a logged-in redirect."""
        config.set_current_home(config.user_home(uid))
        config.ensure_home()
        init_db()
        resp = RedirectResponse("/", status_code=303)
        issue_session(resp, uid)
        return resp

    @app.get("/login", response_class=HTMLResponse)
    def login_form(error: str = "", notice: str = "") -> str:
        return _auth_page("login", error, notice)

    @app.get("/signup", response_class=HTMLResponse)
    def signup_form(error: str = "", notice: str = "") -> str:
        return _auth_page("signup", error, notice)

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
        # credentials are right, but an unapproved account can't enter yet
        user = auth.get_user(uid)
        if user and user.get("status") != "active":
            return RedirectResponse(
                "/login?notice=Your+account+is+awaiting+approval+by+the+owner.",
                status_code=303)
        return _begin_session(uid)

    @app.post("/signup")
    async def signup_submit(request: Request):
        from urllib.parse import quote

        form = await request.form()
        email = (form.get("email") or "").strip()
        password = form.get("password") or ""
        # when the approval gate is on, new accounts land pending and must be approved
        # (`eklavya approve <email>`) before they can log in — no self-service access.
        pending = config.MULTIUSER and config.SIGNUP_APPROVAL
        try:
            uid = auth.create_user(email, password, status="pending" if pending else "active")
        except ValueError as exc:
            return RedirectResponse(f"/signup?error={quote(str(exc))}", status_code=303)
        if pending:
            return RedirectResponse(
                "/login?notice=" + quote("Account created — the owner must approve it before you can sign in."),
                status_code=303)
        return _begin_session(uid)

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
<link rel="stylesheet" href="/static/katex/katex.min.css">
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
/* cinematic app-bar — warm indigo with a hairline-gold underline + faint top glow,
   so the chrome reads as the same crafted world as /welcome (not a flat toolbar). */
header{display:flex;align-items:center;gap:12px;padding:13px 22px;position:relative;
background:linear-gradient(120deg,rgba(35,29,24,.66),rgba(12,10,20,.78));
box-shadow:inset 0 1px 0 rgba(231,182,75,.08),0 10px 30px -22px #000}
header::after{content:"";position:absolute;left:0;right:0;bottom:0;height:1px;
background:linear-gradient(90deg,transparent,var(--line-gold) 22%,var(--line-gold) 78%,transparent)}
.brand{display:flex;flex-direction:column;gap:2px}
.logo{font-family:var(--f-display);font-weight:800;font-size:20px;letter-spacing:.12em;display:flex;align-items:center;gap:9px}
.logo .bowmark{filter:drop-shadow(0 2px 8px rgba(231,182,75,.4))}
.logo .g{color:transparent;background:linear-gradient(180deg,#fff6df,var(--gold-bright) 45%,var(--gold) 75%,var(--gold-deep));-webkit-background-clip:text;background-clip:text}
.creed{font-family:var(--f-deva);color:var(--gold-bright);font-size:12px;letter-spacing:.02em;opacity:.85}
.tab{font-family:var(--f-mono);letter-spacing:.1em;text-transform:uppercase;font-size:11px;color:var(--parch-dim);
background:none;border:1px solid transparent;padding:7px 13px;border-radius:4px;cursor:pointer;transition:.16s}
.tab:hover{color:var(--gold-bright)}
.tab.on{color:var(--gold-bright);border-color:var(--line-gold);background:rgba(231,182,75,.08)}
.spacer{flex:1}
/* provider chip — compact pill, not raw wrapped debug text */
.who{font-family:var(--f-mono);font-size:10px;letter-spacing:.06em;color:var(--parch-dim);text-transform:uppercase;
 background:rgba(6,9,20,.5);border:1px solid var(--line-gold);border-radius:999px;padding:5px 11px;
 white-space:nowrap;flex:none;cursor:default}
.who:empty{display:none}
main{flex:1;min-height:0;display:grid;grid-template-columns:auto 1fr}
/* ashram left rail — the SINGLE desktop nav (top tabs removed). Warm indigo panel with a
   hairline-gold right edge + faint atmospheric glow, grouped Practice / Progress. */
#prail{width:190px;padding:20px 14px 16px;display:flex;flex-direction:column;gap:3px;position:relative;
 background:linear-gradient(175deg,rgba(35,29,24,.34),rgba(8,11,26,.5));
 box-shadow:inset -1px 0 0 var(--line-soft),inset 0 20px 60px -50px rgba(231,182,75,.5)}
#prail::after{content:"";position:absolute;top:0;bottom:0;right:0;width:1px;
 background:linear-gradient(180deg,transparent,var(--line-gold) 30%,var(--line-gold) 70%,transparent)}
#prail .rail-group{font-family:var(--f-mono);font-size:9.5px;letter-spacing:.24em;text-transform:uppercase;
 color:var(--gold);opacity:.7;margin:14px 12px 7px;display:flex;align-items:center;gap:8px}
#prail .rail-group:first-child{margin-top:2px}
#prail .rail-group::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,var(--line-soft),transparent)}
#prail .rail-item{display:flex;align-items:center;gap:11px;font-family:var(--f-title);font-size:14.5px;color:var(--parch-dim);
 padding:10px 12px;border-radius:7px;cursor:pointer;border:1px solid transparent;transition:.16s;position:relative}
#prail .rail-item:hover{color:var(--gold-bright);background:rgba(231,182,75,.05)}
#prail .rail-item.on{color:var(--gold-bright);background:linear-gradient(90deg,rgba(231,182,75,.14),rgba(231,182,75,.02));border-color:var(--line-gold)}
#prail .rail-item.on::before{content:"";position:absolute;left:0;top:8px;bottom:8px;width:2px;border-radius:2px;
 background:linear-gradient(180deg,var(--gold-bright),var(--gold-deep));box-shadow:0 0 8px rgba(231,182,75,.5)}
#prail .rail-item svg{flex:none}
#prail .rail-mini-hud{margin-top:auto;padding:14px 10px 4px;position:relative;display:flex;align-items:center;gap:9px;cursor:pointer;border-radius:9px;transition:background .15s}
#prail .rail-mini-hud:hover{background:rgba(231,182,75,.06)}
#prail .rail-mini-hud::before{content:"";position:absolute;left:12px;right:12px;top:0;height:1px;
 background:linear-gradient(90deg,transparent,var(--line-gold),transparent)}
#prail .rmh-meta{flex:1;min-width:0}
#prail .rmh-name{font-family:var(--f-title);font-size:14px;color:var(--parch);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#prail .rmh-title{font-family:var(--f-mono);font-size:10px;color:var(--gold-ember);letter-spacing:.1em;text-transform:uppercase;margin-top:3px}
#prail .rmh-caret{color:var(--parch-dim);font-size:9px;flex:none}
.acctmenu{position:absolute;left:12px;right:12px;bottom:72px;z-index:80;padding:13px 13px 12px;border-radius:11px;
 background:linear-gradient(160deg,rgba(30,24,18,.98),rgba(16,12,7,.98));border:1px solid var(--line-gold);box-shadow:0 18px 44px -12px rgba(0,0,0,.78)}
.acctmenu[hidden]{display:none}
.acctmenu .am-hd{font-family:var(--f-mono);font-size:8.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--parch-dim);margin-bottom:5px}
.acctmenu .am-email{font-family:var(--f-body);font-size:12.5px;color:var(--parch);word-break:break-all;line-height:1.35;margin-bottom:11px}
.acctmenu .am-logout{width:100%;background:rgba(214,59,42,.13);color:var(--vermilion-glow);border:1px solid rgba(214,59,42,.5);border-radius:7px;padding:9px;font-family:var(--f-title);font-size:13px;letter-spacing:.02em;cursor:pointer;transition:background .15s}
.acctmenu .am-logout:hover{background:rgba(214,59,42,.24)}
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
.msg.ai .who{font-family:var(--f-mono);letter-spacing:.16em;font-size:10px;color:#5f3d10;font-weight:600;text-transform:uppercase;margin-bottom:5px}
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
/* ===== visual game-mode chooser ===== */
.modelaunch{background:linear-gradient(180deg,rgba(231,182,75,.14),rgba(20,15,10,.5));color:var(--gold-bright);
  border:1px solid var(--line-gold);border-radius:6px;padding:7px 12px;font-family:var(--f-title);font-size:12px;
  cursor:pointer;display:flex;align-items:center;gap:7px;transition:.15s;min-height:34px}
.modelaunch:hover{border-color:var(--gold);background:linear-gradient(180deg,rgba(231,182,75,.22),rgba(20,15,10,.5))}
.modelaunch .ml-g{font-size:13px}.modelaunch .ml-caret{opacity:.6;font-size:10px}
.modes-ov{position:fixed;inset:0;z-index:1200;display:none;align-items:center;justify-content:center;
  background:rgba(6,8,18,.72);backdrop-filter:blur(4px);padding:24px}
.modes-ov.on{display:flex}
.modes-card{width:100%;max-width:720px;max-height:88vh;overflow:auto;background:var(--card-surface);
  border:var(--card-edge);border-radius:14px;box-shadow:var(--card-lift),0 40px 90px -30px rgba(0,0,0,.8);padding:26px}
.modes-h{font-family:var(--f-display);font-weight:700;font-size:22px;color:var(--parch);margin:0 0 18px;text-align:center;letter-spacing:.02em}
.modes-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.modetile{display:flex;gap:13px;align-items:flex-start;text-align:left;padding:15px 16px;border-radius:11px;cursor:pointer;
  background:var(--panel-inner);border:1px solid var(--line-soft);box-shadow:var(--panel-inner-lift);transition:.15s;color:var(--parch)}
.modetile:hover{border-color:var(--gold);transform:translateY(-2px)}
.modetile.cur{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold) inset}
.modetile .mt-g{font-size:26px;line-height:1;flex:none}
.mt-body{display:flex;flex-direction:column;gap:3px}
.mt-t{font-family:var(--f-title);font-size:14px;color:var(--parch)}
.mt-d{font-family:var(--f-body);font-size:12px;color:var(--parch-dim);line-height:1.4}
.modetile.red .mt-g{color:var(--vermilion-glow)} .modetile.red:hover{border-color:var(--vermilion-glow)}
.modetile.gold .mt-g{color:var(--gold-bright)}
.modetile.dragon .mt-g{color:#e7b64b;text-shadow:0 0 10px rgba(231,182,75,.55)} .modetile.dragon:hover{border-color:#e7b64b}
.modetile.teal .mt-g,.modetile.peacock .mt-g{color:var(--peacock-bright)}
.modetile.forest .mt-g{color:var(--forest-lit)}
@media(max-width:600px){.modes-grid{grid-template-columns:1fr}}
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
/* Run output, shown in the editor pane below the code (NOT the chat) — persists across
   messages, and the output body scrolls instead of clipping. */
.ed-run{border-bottom:1px solid var(--line-gold)}
.ed-run[hidden]{display:none}
.ed-run .rohead{font-family:var(--f-mono);font-size:11px;letter-spacing:.02em;color:var(--parch-dim);
 padding:9px 14px;display:flex;align-items:center;gap:7px}
.ed-run .rohead .ok{color:var(--peacock-bright)} .ed-run .rohead .bad{color:var(--vermilion-glow)}
.ed-run pre{margin:0;padding:0 14px 11px;font-family:var(--f-mono);font-size:12.5px;line-height:1.5;
 white-space:pre-wrap;word-break:break-word;color:var(--parch);max-height:34vh;overflow:auto}
.ed-run pre.roerr{color:#ff9aa9}
.ed-run .roempty{padding:0 14px 11px;font-family:var(--f-mono);font-size:12px;color:var(--parch-mute)}
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
.ed-tests{border-top:1px solid var(--line-gold);background:rgba(6,9,20,.62);display:flex;flex-direction:column;flex:none;max-height:60%;overflow-y:auto}
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
.art-vizframe{width:100%;min-height:74vh;border:1px solid var(--line-soft);border-radius:8px;background:#0b0f17;display:block}
.canvas-empty{color:var(--parch-dim);font-family:var(--f-body);text-align:center;padding:50px 20px}
/* highlight-to-ask echo in chat (template D's .art-echo) */
.art-echo{display:flex;gap:8px;align-items:flex-start;border-left:2px solid var(--gold);padding:8px 12px;background:rgba(231,182,75,.06);border-radius:0 6px 6px 0;margin-bottom:8px;max-width:86%;align-self:flex-end}
.art-echo .lbl{font-family:var(--f-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--gold);margin-bottom:3px}
.art-echo .q{font-family:var(--f-serif);font-style:italic;font-size:13px;color:var(--parch)}
#dash,#journey,#effect,#profile{display:none;height:100%}
#dash iframe,#journey iframe,#effect iframe,#profile iframe{width:100%;height:100%;border:0;background:var(--indigo-night)}
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
 border:1px solid rgba(231,182,75,.22);border-radius:10px;
 background:linear-gradient(168deg,rgba(46,38,30,.72) 0%,rgba(28,26,42,.7) 34%,rgba(13,14,28,.82) 100%);
 box-shadow:inset 0 1px 0 rgba(247,217,138,.14),0 20px 44px -30px rgba(0,0,0,.7),0 3px 10px -6px rgba(0,0,0,.5);transition:.16s}
.artcard:hover{border-color:rgba(231,182,75,.4);box-shadow:inset 0 1px 0 rgba(247,217,138,.2),0 14px 34px -16px rgba(231,182,75,.4),0 20px 44px -28px rgba(0,0,0,.75)}
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
 box-shadow:0 24px 60px -30px rgba(0,0,0,.7);display:flex;background:#101528;position:relative}
.mapframe svg{display:block;width:100%;height:100%;flex:1;min-height:0;transform-origin:top left}
/* zoom controls (usable on touch too) — the forest map was tiny/unreadable on mobile */
.mapzoom{position:absolute;top:10px;right:10px;display:flex;flex-direction:column;gap:6px;z-index:5}
.mapzoom button{width:36px;height:36px;border-radius:9px;border:1px solid var(--line-gold);
  background:rgba(6,9,20,.82);color:var(--gold-bright);font-size:17px;line-height:1;cursor:pointer;
  display:grid;place-items:center;backdrop-filter:blur(3px)}
.mapzoom button:hover{border-color:var(--gold)}
@media(max-width:820px){.mapframe{min-height:64vh}}
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
/* 1-tap learner feedback ("did that land?") — unobtrusive, after the guru's reply */
.fbrow{display:flex;align-items:center;gap:8px;margin:8px 0 2px;font-family:var(--f-mono);font-size:11px;color:var(--parch-mute)}
.fbrow .fblbl{letter-spacing:.04em}
.fbrow button{cursor:pointer;background:rgba(6,9,20,.5);border:1px solid var(--line-soft);border-radius:7px;
 padding:2px 8px;font-size:13px;line-height:1;color:var(--parch-dim);transition:border-color .12s,transform .08s}
.fbrow button:hover{border-color:var(--gold);transform:translateY(-1px)}
.fbrow.done{color:var(--forest-lit)}
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
.timerwrap{position:relative;display:inline-flex}
#timerbtn,#wrapbtn{font-family:var(--f-mono);font-size:11px;color:var(--parch-dim);background:rgba(6,9,20,.5);border:1px solid var(--line-gold);border-radius:4px;padding:7px 11px;cursor:pointer;margin-right:4px;transition:.16s}
#timerbtn:hover,#wrapbtn:hover{color:var(--gold-bright);border-color:var(--gold-deep)}
#timerbtn.on{color:var(--gold-bright);border-color:var(--gold)}
.tmenu{position:absolute;top:calc(100% + 6px);right:0;z-index:80;min-width:186px;padding:11px;border-radius:10px;
 background:linear-gradient(160deg,rgba(30,24,18,.98),rgba(16,12,7,.98));border:1px solid var(--line-gold);box-shadow:0 16px 40px -12px rgba(0,0,0,.75)}
.tmenu[hidden]{display:none}
.tmenu .tm-h{font-family:var(--f-mono);font-size:8.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--parch-dim);margin-bottom:8px}
.tmenu .tm-row{display:flex;gap:6px;margin-bottom:8px}
.tmenu .tm-row button{flex:1;font-family:var(--f-mono);font-size:12px;color:var(--parch);background:rgba(231,182,75,.08);border:1px solid var(--line-soft);border-radius:6px;padding:7px 0;cursor:pointer}
.tmenu .tm-row button:hover{background:rgba(231,182,75,.2);border-color:var(--gold-deep)}
.tmenu .tm-custom{width:100%;font-family:var(--f-body);font-size:12px;color:var(--parch-dim);background:none;border:1px dashed var(--line-soft);border-radius:6px;padding:7px;cursor:pointer;margin-bottom:6px}
.tmenu .tm-custom:hover{color:var(--parch);border-color:var(--gold-deep)}
.tmenu .tm-stop{width:100%;font-family:var(--f-mono);font-size:11px;color:var(--vermilion-glow);background:rgba(214,59,42,.1);border:1px solid rgba(214,59,42,.4);border-radius:6px;padding:7px;cursor:pointer}
.sysline{align-self:center;font-family:var(--f-mono);font-size:11.5px;color:var(--gold-ember);background:rgba(231,182,75,.06);border:1px solid var(--line-soft);border-radius:20px;padding:6px 16px;margin:4px 0}
#penaltybtn.off{color:var(--vermilion-glow);border-color:rgba(214,59,42,.5)}
#drawerscrim{position:fixed;inset:0;z-index:900;background:rgba(2,6,12,.62);opacity:0;pointer-events:none;transition:opacity .22s;backdrop-filter:blur(1.5px)}
#drawerscrim.open{opacity:1;pointer-events:auto}
#drawer{position:fixed;top:0;left:0;bottom:0;width:300px;max-width:88vw;z-index:910;transform:translateX(-105%);
 transition:transform .22s ease;display:flex;flex-direction:column;
 background:linear-gradient(180deg,#1c1712,#0b0912);border-right:1px solid var(--line-gold);box-shadow:2px 0 30px #000c}
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
.chatitem .cdel:hover{color:#e05252}
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
/* win-pulse — a ~1.3s felt moment for every real win (audit: rewards weren't felt) */
#winpulse{position:fixed;top:46%;left:50%;transform:translate(-50%,-50%);z-index:95;display:none;
  flex-direction:column;align-items:center;gap:5px;pointer-events:none;padding:22px 40px;border-radius:18px;
  background:radial-gradient(circle,rgba(231,182,75,.2),rgba(6,9,20,0) 72%)}
#winpulse.on{display:flex;animation:winpop 1.3s cubic-bezier(.2,.7,.3,1) both}
@keyframes winpop{0%{opacity:0;transform:translate(-50%,-50%) scale(.5)}22%{opacity:1;transform:translate(-50%,-50%) scale(1.06)}
  70%{opacity:1;transform:translate(-50%,-50%) scale(1)}100%{opacity:0;transform:translate(-50%,-56%) scale(1)}}
#winpulse .wp-spark{font-size:46px;line-height:1;color:var(--gold-bright);text-shadow:0 0 22px rgba(231,182,75,.75)}
#winpulse .wp-t{font-family:var(--f-display);font-weight:700;font-size:19px;color:var(--parch)}
#winpulse .wp-n{font-family:var(--f-mono);font-size:13px;letter-spacing:.05em;color:var(--gold-bright)}
.reduce-motion #winpulse.on{animation:none;opacity:1}
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
#mnav .ni{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:4px;font-family:var(--f-mono);font-size:10px;
 letter-spacing:.06em;color:var(--parch-dim);text-transform:uppercase;background:none;border:none;cursor:pointer;
 padding:6px 8px;min-width:56px;min-height:48px}
#mnav .ni.on{color:var(--gold-bright)}
#mnav .ni.center{margin-top:-24px}
#mnav .ni.center .orb{width:52px;height:52px;border-radius:50%;background:radial-gradient(circle at 40% 35%,var(--gold-bright),var(--gold-deep));
 display:flex;align-items:center;justify-content:center;box-shadow:0 8px 22px -6px rgba(231,182,75,.7),inset 0 1px 0 rgba(255,255,255,.5);border:2px solid rgba(255,246,223,.3)}
/* mobile: header stays a single compact bar; the bottom radial nav is the primary nav */
@media(max-width:900px){
 header{flex-wrap:wrap;gap:10px;padding:10px 14px}
 .creed{display:none}
 .tab{padding:14px 13px}                 /* >=44px hit area */
 .hud{font-size:11px;gap:8px}
 #prail{display:none}                 /* the rail is desktop-only; mobile uses the radial nav */
 main{grid-template-columns:1fr;overflow-x:hidden}
 #content{overflow-x:hidden}
 body{overflow:auto}
 #mnav{display:flex}
 /* the editor toolbar must wrap on narrow screens — root cause of the horizontal overflow */
 .edtoolbar{flex-wrap:wrap}
 .edtoolbar .grow{flex-basis:100%;height:0}
 #chatsbtn,#penaltybtn{padding:14px 12px}   /* >=44px hit area */
 .edtoolbar select{padding:14px 10px}
 .seg span{padding:14px 12px}
 .edtoolbar button{padding-top:12px;padding-bottom:12px}
}
</style></head><body>
<header>
  <div class="brand"><div class="logo"><span class="bowmark"><svg width="18" height="23" viewBox="0 0 58 76" aria-hidden="true"><path d="M14 6 C40 24 40 52 14 70" stroke="#e7b64b" stroke-width="4" stroke-linecap="round" fill="none"/><line x1="14" y1="6" x2="14" y2="70" stroke="#57d3ce" stroke-width="1.6"/><line x1="14" y1="38" x2="50" y2="38" stroke="#f7d98a" stroke-width="2.4"/><path d="M50 38 l-7 -5 M50 38 l-7 5" stroke="#f7d98a" stroke-width="2.4" stroke-linecap="round"/></svg></span> <span class="g">EKALAVYA</span></div><div class="creed">स्वाध्याय · साधना · सिद्धि</div></div>
  <div class="spacer"></div>
  <button id="chatsbtn" onclick="openDrawer()">☰ Chats</button>
  <button class="tab on" id="edtoggle" onclick="toggleEditor()" title="Show or hide the code editor">▤ Editor</button>
  <button id="penaltybtn" onclick="togglePenalty()" title="Turn the cheat penalty on or off">☠ penalty on</button>
  <span class="timerwrap">
    <button id="timerbtn" onclick="toggleTimerMenu(event)" title="Optional focus timer — never ends the session on its own">⏱ Timer</button>
    <div id="timermenu" class="tmenu" hidden>
      <div class="tm-h">Focus timer · optional</div>
      <div class="tm-row"><button onclick="startTimer(15)">15m</button><button onclick="startTimer(25)">25m</button><button onclick="startTimer(45)">45m</button><button onclick="startTimer(60)">60m</button></div>
      <button class="tm-custom" onclick="customTimer()">Custom…</button>
      <button class="tm-stop" onclick="stopTimer()">Stop timer</button>
    </div>
  </span>
  <button id="wrapbtn" onclick="endSession()" title="Finish this session — the guru summarizes and saves your progress">⏹ Wrap up</button>
  <div class="hud" id="hud"></div>
  <div class="who" id="who"></div>
</header>
<main>
  <nav id="prail" aria-label="Sections">
    <div class="rail-group">Practice</div>
    <div class="rail-item on" data-rail="practice" onclick="railGo('practice')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M4 12 C10 7 14 7 20 12 C14 17 10 17 4 12" stroke="currentColor" stroke-width="1.6"/><line x1="4" y1="12" x2="20" y2="12" stroke="currentColor" stroke-width="1.6"/></svg> Arena</div>
    <div class="rail-item" data-rail="tree" onclick="railGo('tree')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M12 21V11M12 11a5 5 0 100-8 5 5 0 000 8z" stroke="currentColor" stroke-width="1.5"/></svg> Forest Map</div>
    <div class="rail-item" data-rail="library" onclick="railGo('library')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M6 4h11a2 2 0 0 1 2 2v14H8a2 2 0 0 1-2-2z" stroke="currentColor" stroke-width="1.6"/></svg> Library</div>
    <div class="rail-group">Progress</div>
    <div class="rail-item" data-rail="dash" onclick="railGo('dash')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M3 11 L12 4 L21 11 V21 H3 Z" stroke="currentColor" stroke-width="1.6"/></svg> Dashboard</div>
    <div class="rail-item" data-rail="journey" onclick="railGo('journey')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M4 20 C8 8 16 8 20 4 M4 20 h4 M4 20 v-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg> Journey</div>
    <div class="rail-item" data-rail="effect" onclick="railGo('effect')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M3 12 h4 l3 7 4-14 3 7 h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg> Effectiveness</div>
    <div class="rail-item" data-rail="profile" onclick="railGo('profile')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M12 12a4 4 0 100-8 4 4 0 000 8z" stroke="currentColor" stroke-width="1.5"/><path d="M5 20c0-3.3 3.1-6 7-6s7 2.7 7 6" stroke="currentColor" stroke-width="1.5"/></svg> Profile</div>
    <div class="rail-item rail-settings" data-rail="settings" onclick="railGo('settings')"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M12 15a3 3 0 100-6 3 3 0 000 6z" stroke="currentColor" stroke-width="1.5"/><path d="M19 12a7 7 0 00-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 00-1.7-1L16.5 2h-9l-.4 2.6a7 7 0 00-1.7 1l-2.3-1-2 3.4 2 1.5a7 7 0 000 2l-2 1.5 2 3.4 2.3-1a7 7 0 001.7 1L7.5 22h9l.4-2.6a7 7 0 001.7-1l2.3 1 2-3.4-2-1.5c.1-.3.1-.7.1-1z" stroke="currentColor" stroke-width="1.2"/></svg> Settings</div>
    <div class="rail-mini-hud" id="acctbtn" role="button" tabindex="0" title="Account & sign out" onclick="toggleAcct(event)">
      <div class="rmh-meta"><div class="rmh-name" id="railname">Devotee</div><div class="rmh-title" id="railtitle">Vana-Dhanurdhara</div></div>
      <span class="rmh-caret">▴</span>
    </div>
    <div class="acctmenu" id="acctmenu" hidden>
      <div class="am-hd">Signed in as</div>
      <div class="am-email" id="am_email">—</div>
      <form method="post" action="/logout"><button type="submit" class="am-logout">⎋ Log out</button></form>
    </div>
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
        <button class="modelaunch" onclick="openModes()" title="Choose a mode"><span class="ml-g">◈</span> <span id="modelabel">Daily practice</span> <span class="ml-caret">▾</span></button>
        <select id="mode" onchange="newSession()" style="display:none">
          <option value="practice">Daily practice</option>
          <option value="mock">Mock interview</option>
          <option value="aiinterview">AI-enabled interview</option>
          <option value="gauntlet">⚔ The Gauntlet</option>
          <option value="blitz">⚡ Blitz</option>
          <option value="boss">🐉 Boss fight</option>
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
      <div id="modes" class="modes-ov" onclick="if(event.target===this)closeModes()">
        <div class="modes-card">
          <div class="modes-h">Choose your trial</div>
          <div class="modes-grid" id="modesgrid"></div>
        </div>
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
        <div class="ed-run" id="edrun" hidden></div>
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
  <div id="effect"><iframe id="effectframe" src="/effectiveness"></iframe></div>
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
    <div class="mapframe"><svg id="forestsvg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Forest map of learning groves on a winding path."></svg>
      <div class="mapzoom"><button onclick="forestZoom(1.3)" title="Zoom in">＋</button><button onclick="forestZoom(0.77)" title="Zoom out">−</button><button onclick="forestZoomReset()" title="Reset">⟲</button></div>
    </div>
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
<div id="winpulse"><span class="wp-spark">✦</span><span class="wp-t">Struck true</span><span class="wp-n">+0 XP</span></div>

<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>
<!-- KaTeX must run BEFORE Monaco's AMD loader defines define.amd, or its UMD registers as an
     AMD module instead of setting window.katex — so: no defer, and above the loader. -->
<script src="/static/katex/katex.min.js"></script>
<script src="/static/katex/contrib/auto-render.min.js"></script>
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
  const DISP={practice:'grid',dash:'block',journey:'block',effect:'block',profile:'block',tree:'flex',library:'flex',settings:'block'};
  for(const id of Object.keys(DISP)){ const el=document.getElementById(id); if(el) el.style.display = (id===v)?DISP[id]:'none'; }
  // keep both nav surfaces in sync with the active view
  document.querySelectorAll('.tab[data-view]').forEach(x=>x.classList.toggle('on', x.dataset.view===v));
  document.querySelectorAll('#prail .rail-item,#mnav .ni').forEach(x=>x.classList.toggle('on', x.dataset.rail===v));
  if(v==='dash') document.getElementById('dashframe').src='/dashboard';
  if(v==='journey') document.getElementById('jframe').src='/journey';
  if(v==='effect') document.getElementById('effectframe').src='/effectiveness';  // reload → latest metrics
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
    const autoOpt="<option value='auto'"+(s.active_provider==='auto'?" selected":"")+">Auto (balanced) · load-balances across your keys</option>";
    const provOpts=autoOpt+(s.providers||[]).map(p=>
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
        fetch('/api/config').then(r=>r.json()).then(c=>setWho(c));
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
let _artifacts=[], _curArt=null, _selText='', _maxArtId=0;
// When the guru saves a NEW artifact during a turn, surface it: swap the right pane from the
// editor to the Canvas and open it. The learner can toggle back to the editor any time (the
// ▤ Editor / ✦ Canvas control is unchanged). Baseline _maxArtId at load so pre-existing
// artifacts don't trigger a switch; only something created after this point does.
function pingCanvas(){
  fetch('/api/artifacts').then(r=>r.json()).then(list=>{
    const top=list.length?Math.max.apply(null,list.map(a=>a.id)):0;
    if(top>_maxArtId){ _maxArtId=top; _artifacts=list; _curArt=top; showPane('canvas'); }
  }).catch(()=>{});
}
fetch('/api/artifacts').then(r=>r.json()).then(l=>{ _maxArtId=l.length?Math.max.apply(null,l.map(a=>a.id)):0; }).catch(()=>{});
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
// vizShell — wrap a bare viz fragment in a self-contained doc that preloads Chart.js (from
// our OWN /static, so it works offline and inside the opaque-origin sandbox — a same-origin
// subresource load is allowed even without allow-same-origin) and themes it to the Canvas.
function vizShell(bodyHtml){
  var origin=location.origin;
  return "<!doctype html><html><head><meta charset='utf-8'>"
   +"<meta name='viewport' content='width=device-width,initial-scale=1'>"
   +"<link rel='stylesheet' href='"+origin+"/static/katex/katex.min.css'>"
   +"<script src='"+origin+"/static/chart.umd.min.js'><\/script>"
   +"<script defer src='"+origin+"/static/katex/katex.min.js'><\/script>"
   +"<script defer src='"+origin+"/static/katex/contrib/auto-render.min.js'><\/script>"
   +"<script>try{Chart.defaults.color='#cfc9ba';Chart.defaults.borderColor='rgba(255,255,255,.09)';"
   +"Chart.defaults.maintainAspectRatio=false;Chart.defaults.animation=false;}catch(e){}<\/script>"
   +"<style>:root{color-scheme:dark}*{box-sizing:border-box}.katex{color:#f2ede0}"
   +"body{margin:0;padding:16px 18px;background:#0b0f17;color:#e8e6df;"
   +"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:14px;line-height:1.5}"
   +"h1,h2,h3{font-weight:700;color:#f2ede0;margin:.1em 0 .5em;letter-spacing:-.01em}"
   +"p{color:#b9b3a3;margin:6px 0 14px;line-height:1.6}p em,p b{color:#e8e6df}"
   +"label{color:#e7b64b;font-size:12px;letter-spacing:.03em;margin-right:8px}"
   +"input[type=range]{accent-color:#e7b64b;max-width:340px;height:20px;vertical-align:middle}"
   +"button{background:rgba(231,182,75,.14);color:#f2ede0;border:1px solid rgba(231,182,75,.4);"
   +"border-radius:7px;padding:6px 14px;font-size:13px;cursor:pointer;font-family:inherit;margin:4px 6px 4px 0}"
   +"button:hover{background:rgba(231,182,75,.24)}a{color:#7fd7c4}"
   +"</style></head><body>"+bodyHtml
   +"<script>window.addEventListener('load',function(){try{renderMathInElement(document.body,"
   +"{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}],throwOnError:false});}catch(e){}});<\/script>"
   +"</body></html>";
}
function renderArtifact(a){
  const body=document.getElementById('canvasbody');
  if(!a){ body.innerHTML="<div class='canvas-empty'>—</div>"; return; }
  if(a.kind==='code'){
    body.innerHTML="<div class='art-code' data-selectable='1'>"+esc(a.content)+"</div>";
  } else if(a.kind==='viz' || a.kind==='html'){
    // Render in a LOCKED sandbox iframe: scripts run (Chart.js sliders, an HTML page's own JS)
    // but 'allow-scripts' WITHOUT 'allow-same-origin' means an opaque origin, so the content's
    // JS can't touch the app's cookies, storage, or same-origin API. A full HTML doc is used
    // as-is (so 'html' artifacts are real, self-contained HTML files/pages); a bare 'viz'
    // fragment is wrapped in the Chart.js shell.
    var raw=a.content||'';
    var full=/<!doctype|<html[\\s>]/i.test(raw);
    var doc=(a.kind==='viz' && !full) ? vizShell(raw) : raw;
    var f=document.createElement('iframe');
    f.className='art-vizframe'; f.setAttribute('sandbox','allow-scripts');
    f.setAttribute('referrerpolicy','no-referrer'); f.setAttribute('loading','lazy');
    body.innerHTML=''; body.appendChild(f); f.srcdoc=doc;
    return;  // no highlight-to-ask inside the cross-origin frame; keep the popover out
  } else {  // markdown lesson
    body.innerHTML="<div class='art-md' data-selectable='1'>"+DOMPurify.sanitize(marked.parse(a.content||''))+"</div>";
    body.querySelectorAll('pre code').forEach(c=>{try{hljs.highlightElement(c);}catch(e){}});
    typesetMath(body);  // render LaTeX in a saved lesson
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
    const nMast=c.groves.filter(g=>g.status==='blossoming').length;
    document.getElementById('treesub').textContent=
      c.groves.length+' groves · '+nMast+' mastered · a tap enters a grove';
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
function refreshHud(){ fetch('/api/stats').then(r=>r.json()).then(s=>{ window._lastStats=s; setHud(s); celebrate(s); }).catch(()=>{}); }

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
  const prevXp=parseInt(localStorage.getItem('ek_xp')||'0',10);
  if(_celebReady){   // one moment at a time: level-up > new achievement > an ordinary win
    if(s.level>prevLvl){ showCeremony(s.level); }
    else { const fresh=earnedAchievements(s).find(a=>!prevAch.includes(a[0]));
      if(fresh) showAchievement(fresh[0], fresh[1]);
      else if(s.xp>prevXp) winPulse(s.xp-prevXp);   // a FELT moment for every real win
    }
  }
  localStorage.setItem('ek_lvl', s.level); localStorage.setItem('ek_ach', JSON.stringify(nowAch));
  localStorage.setItem('ek_xp', s.xp);
  _celebReady=true;
}
function winPulse(amt){
  const p=document.getElementById('winpulse'); if(!p) return;
  p.querySelector('.wp-n').textContent='+'+amt+' XP';
  p.classList.remove('on'); void p.offsetWidth; p.classList.add('on');
  setTimeout(()=>p.classList.remove('on'),1400);
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
  const st=window._lastStats;   // returning learner → a warm, personalised greeting
  if(st && (st.streak>0 || st.level>1)){
    const t=document.querySelector('#arenawelcome .aw-title'); if(t) t.textContent='Welcome back, devotee';
    const s2=document.getElementById('awsub');
    if(s2) s2.textContent=(st.streak>0?('Your '+st.streak+'-day streak is warm — '):'')+'Ekalavya is drawing your next drill…';
  }
  if(sub){ const s=document.getElementById('awsub'); if(s) s.textContent=sub; } }
function addMsg(role, html){
  clearWelcome();
  const m=el('msg '+role); const who=el('who'); who.textContent = role==='you'?'you':'Ekalavya';
  const body=el('body'); body.innerHTML=html; m.appendChild(who); m.appendChild(body);
  document.getElementById('log').appendChild(m); scroll(); return body;
}
function scroll(){const l=document.getElementById('log'); l.scrollTop=l.scrollHeight;}
// Typeset LaTeX math ($…$ inline, $$…$$ / \[…\] display) with KaTeX — the tutor teaches
// math/stats/ML, so equations must render, not show as raw source. Skips code/pre so a '$'
// in code isn't mangled. Works on a detached element (KaTeX walks text nodes).
function typesetMath(el){
  if(!el || !window.renderMathInElement) return;
  try{ renderMathInElement(el, {delimiters:[
    {left:'$$',right:'$$',display:true}, {left:'\\[',right:'\\]',display:true},
    {left:'\\(',right:'\\)',display:false}, {left:'$',right:'$',display:false}
  ], throwOnError:false, ignoredTags:['script','noscript','style','textarea','pre','code']}); }catch(e){}
}
function renderMd(text){
  const html = DOMPurify.sanitize(marked.parse(text));  // never trust model output in the DOM
  const tmp=document.createElement('div'); tmp.innerHTML=html;
  tmp.querySelectorAll('pre code').forEach(c=>{
    if(c.className.includes('mermaid')||c.className.includes('language-mermaid')){
      const d=el('mermaid'); d.textContent=c.textContent; c.closest('pre').replaceWith(d);
    } else { try{hljs.highlightElement(c);}catch(e){} }
  });
  typesetMath(tmp);  // render any LaTeX before returning the HTML
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
  attachFeedback(ui);
  scroll();
}
function attachFeedback(ui){
  if(ui.m.querySelector('.fbrow')) return;                 // one prompt per reply
  const row=el('fbrow');
  row.innerHTML='<span class="fblbl">Did that land?</span>'+
    '<button data-r="5" title="yes, helpful" aria-label="helpful">\uD83D\uDC4D</button>'+
    '<button data-r="1" title="not really" aria-label="not helpful">\uD83D\uDC4E</button>';
  row.querySelectorAll('button').forEach(b=>{
    b.onclick=()=>{
      fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({kind:'drill',rating:+b.dataset.r,mode,thread})});
      row.innerHTML='<span class="fblbl">thanks \u2726</span>'; row.classList.add('done');
      setTimeout(()=>{ row.style.transition='opacity .5s'; row.style.opacity='0';
        setTimeout(()=>row.remove(), 520); }, 900);
    };
  });
  ui.m.appendChild(row); scroll();
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
      else if(o.autorun){ clearWelcome(); ui.m.style.display=''; ui.steps++; ui.trace.style.display='block';
        traceLine(ui.tb,'call','⚡ ran (auto) · '+((o.autorun.command||'command').slice(0,80))); ui.sum.textContent='ran a safe command…'; scroll(); }
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
  pingCanvas();  // if the guru saved a new artifact this turn, surface it in the Canvas
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

function esc(s){ return (s||'').replace(/</g,'&lt;'); }
// Run output renders in the editor pane (#edrun, below the code) — it persists across chat
// messages and its body scrolls (max-height) instead of being clipped or lost in the log.
function showRunPane(headHtml){
  const box=document.getElementById('edrun');
  box.innerHTML='<div class="rohead">'+headHtml+'</div>'; box.hidden=false;
  document.getElementById('edtests').classList.remove('hidden');
}
function renderRunPane(r){
  const head = r.ok ? '<span class="ok">▶ ran</span>' : '<span class="bad">▶ exit '+r.exit_code+'</span>';
  let html='<div class="rohead">'+head+' · '+(r.seconds||'0')+'s</div>';
  if(r.stdout) html+='<pre class="rostd">'+esc(r.stdout)+'</pre>';
  if(r.stderr) html+='<pre class="roerr">'+esc(r.stderr)+'</pre>';
  if(!r.stdout && !r.stderr) html+='<div class="roempty">(no output)</div>';
  const box=document.getElementById('edrun'); box.innerHTML=html; box.hidden=false;
  document.getElementById('edtests').classList.remove('hidden');
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
  showRunPane('<span class="dim">▶ running…</span>');
  try{
    const r=await (await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code})})).json();
    renderRunPane(r); renderTests(r);
  }catch(e){ renderRunPane({ok:false, exit_code:'—', seconds:'0', stderr:"Couldn't reach the sandbox — try again."}); }
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
  const et=document.getElementById('edtests'); if(et) et.classList.add('hidden');   // drop stale run output
  const er=document.getElementById('edrun'); if(er){ er.hidden=true; er.innerHTML=''; }
  document.getElementById('log').innerHTML=''; document.getElementById('asslog').innerHTML=''; showWelcome();
  showPane('editor');  // a fresh session starts on the editor, not a stale canvas
  applyMode(); syncModeLabel();
  fetch('/api/config').then(r=>r.json()).then(c=>{ stream(c.kickoff[mode]); });
}

// ===== visual game-mode chooser (the modes were buried in a 30px dropdown) =====
const MODES=[
 {v:'practice',   g:'◑', t:'Daily practice',       d:'Gated drills tuned to your weakest spots.',                 c:'teal'},
 {v:'gauntlet',   g:'⚔', t:'The Gauntlet',          d:'Endless, escalating. It hunts your weaknesses and uses them against you. Die, learn, rematch.', c:'red'},
 {v:'blitz',      g:'⚡', t:'Blitz',                 d:'Rapid-fire recall against the clock — fluency under pressure.', c:'gold'},
 {v:'boss',       g:'🐉', t:'Boss fight',            d:'One brutal, multi-part problem. Beat it to conquer a whole pillar.', c:'dragon'},
 {v:'mock',       g:'◆', t:'Mock interview',        d:'A realistic loop with an honest, specific scorecard.',       c:'peacock'},
 {v:'aiinterview',g:'◈', t:'AI-enabled interview',  d:'The 2026 format — graded on HOW you wield the AI, not just the answer.', c:'teal'},
 {v:'takehome',   g:'▤', t:'Take-home',             d:'A longer, build-something assignment on your own time.',      c:'forest'},
];
function syncModeLabel(){ const m=MODES.find(x=>x.v===mode); if(m) document.getElementById('modelabel').textContent=m.t; }
function openModes(){
  document.getElementById('modesgrid').innerHTML = MODES.map(m=>
    `<button class="modetile ${m.c}${m.v===mode?' cur':''}" onclick="pickMode('${m.v}')">`+
    `<span class="mt-g">${m.g}</span><span class="mt-body"><span class="mt-t">${m.t}</span>`+
    `<span class="mt-d">${m.d}</span></span></button>`).join('');
  document.getElementById('modes').classList.add('on');
}
function closeModes(){ document.getElementById('modes').classList.remove('on'); }
function pickMode(v){ document.getElementById('mode').value=v; closeModes(); newSession(); }
document.addEventListener('keydown',e=>{ if(e.key==='Escape') closeModes(); });

// ===== forest-map zoom/pan (it was tiny/unreadable on mobile) =====
let _fz=1;
function _applyFz(){
  const s=document.getElementById('forestsvg'); if(!s) return;
  s.style.transform='scale('+_fz+')';
  const f=s.closest('.mapframe'); if(f) f.style.overflow=_fz>1.01?'auto':'hidden';
}
function forestZoom(m){ _fz=Math.max(1,Math.min(4,_fz*m)); _applyFz(); }
function forestZoomReset(){ _fz=1; _applyFz(); }

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
      const del=document.createElement('button'); del.className='cedit cdel'; del.textContent='🗑'; del.title='delete';
      it.appendChild(ci); it.appendChild(ed); it.appendChild(del);
      ci.onclick=()=>openChat(c.thread_id);
      ed.onclick=(e)=>{ e.stopPropagation(); renameChat(c.thread_id, c.title); };
      del.onclick=(e)=>{ e.stopPropagation(); deleteChat(c.thread_id, c.title); };
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
function deleteChat(id, title){
  if(!window.confirm('Delete "'+(title||'untitled')+'"? This removes the chat and its history.')) return;
  fetch('/api/chats/'+id,{method:'DELETE'}).then(()=>loadChats()).catch(()=>{});
}

// render the provider chip as a compact label (verbose "rotates across N" → tooltip only)
function setWho(c){
  const ae=document.getElementById('am_email'); if(ae) ae.textContent=c.email||'(local session)';
  const el=document.getElementById('who'); if(!el) return;
  if(!c.configured){ el.textContent='no provider key'; el.title='no provider key set'; return; }
  const short=(c.provider||'').replace(/\s*\(.*?\)\s*/,'').trim()||'Auto';
  el.textContent=short; el.title=c.provider+' · '+c.model;
}
// bottom-left account menu: who you're signed in as + Log out
function toggleAcct(e){ if(e) e.stopPropagation(); const m=document.getElementById('acctmenu'); if(m) m.hidden=!m.hidden; }
document.addEventListener('click', function(e){ const m=document.getElementById('acctmenu'), b=document.getElementById('acctbtn');
  if(m && !m.hidden && b && !b.contains(e.target) && !m.contains(e.target)) m.hidden=true; });

// ===== optional focus timer (cosmetic — a self-discipline aid; NEVER auto-ends the session) =====
let _timerLeft=0, _timerId=null;
function _fmtT(s){ const m=Math.floor(s/60), ss=s%60; return m+':'+(ss<10?'0':'')+ss; }
function toggleTimerMenu(e){ if(e) e.stopPropagation(); const m=document.getElementById('timermenu'); if(m) m.hidden=!m.hidden; }
function _updTimer(){ document.getElementById('timerbtn').innerHTML='⏱ '+_fmtT(Math.max(0,_timerLeft)); }
function startTimer(mins){
  document.getElementById('timermenu').hidden=true;
  clearInterval(_timerId); _timerLeft=Math.round(mins*60); _updTimer();
  document.getElementById('timerbtn').classList.add('on');
  _timerId=setInterval(function(){ _timerLeft--; _updTimer();
    if(_timerLeft<=0){ clearInterval(_timerId); _timerId=null; _timerDone(); } }, 1000);
}
function stopTimer(){ clearInterval(_timerId); _timerId=null; _timerLeft=0;
  const b=document.getElementById('timerbtn'); b.innerHTML='⏱ Timer'; b.classList.remove('on');
  document.getElementById('timermenu').hidden=true; }
function customTimer(){ const v=prompt('Focus timer — how many minutes?','25'); const m=parseInt(v,10);
  if(m>0 && m<=240) startTimer(m); }
function _timerDone(){
  const b=document.getElementById('timerbtn'); b.innerHTML='⏱ time’s up'; b.classList.remove('on');
  clearWelcome(); const n=el('sysline');
  n.textContent='⏱ Your focus timer is up — keep going, or hit ⏹ Wrap up (or say “I’m done”) whenever you’re ready.';
  document.getElementById('log').appendChild(n); scroll();
}
document.addEventListener('click', function(e){ const m=document.getElementById('timermenu'), w=document.querySelector('.timerwrap');
  if(m && !m.hidden && w && !w.contains(e.target)) m.hidden=true; });
// ⏹ Wrap up — let the learner end the session on demand; the guru summarizes + saves for next time
function endSession(){
  if(streaming){ return; }
  clearWelcome();
  stream("I'm done for today. Please wrap up the session: summarize what we covered and what I "
    +"learned, note where I struggled, save my progress and a hook for next time, then sign off warmly.");
}
refreshHud();
fetch('/api/config').then(r=>r.json()).then(c=>{
  setWho(c);
  deathOnCheat = c.death_on_cheat !== false; updatePenaltyBtn();
  if(c.first_run){ mode='onboard'; document.getElementById('mode').value='onboard'; }  // new user → onboard, not "welcome back"
  applyMode();
  stream(c.kickoff[mode]);
});
// deep-link: if the URL points at a client-only view, open it (matches the /forest,/library,/settings routes)
{const _dl={'/forest':'tree','/library':'library','/settings':'settings'}[location.pathname]; if(_dl) showView(_dl);}
</script></body></html>"""


# --- shared cinematic hero scene (Option E) --------------------------------
# The lone Bhil archer repeatedly drawing and loosing arrows at a distant target beside the
# clay statue of Droṇa under a spinning sun (MISS, MISS, then HIT + a celebration burst).
# The SVG below is copied VERBATIM from docs/design/E_merged/index.html (scene lines 913–1156);
# only `preserveAspectRatio` is parameterised so the same scene fills a full-viewport slice.
# `_HERO_JS` is the verbatim driving IIFE (source lines 2620–2755) wrapped in a <script>.
# One scene instance per page → no duplicate-id collisions across pages.
def _hero_scene(preserve: str) -> str:
    return (
        '<svg viewBox="0 0 1180 620" preserveAspectRatio="' + preserve + '" role="img"'
        + r"""
      aria-label="Ekalavya, the lone forest archer, repeatedly draws and looses arrows at a distant target beside the clay statue of Drona, under a spinning sun, in a cinematic gold-lit forest at night.">
      <defs>
        <!-- ONE uniform indigo-night ground, top to bottom (C's cinematic ground).
             Barely-there horizon warmth stays inside the SAME indigo family — no grey plane. -->
        <linearGradient id="skyE" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#0c1226"/><stop offset=".42" stop-color="#101528"/>
          <stop offset=".72" stop-color="#0c1122"/><stop offset="1" stop-color="#0a0d1c"/>
        </linearGradient>
        <!-- a whisper-thin horizon glow in the indigo/gold key, not a distinct band -->
        <radialGradient id="horizonE" cx="50%" cy="100%" r="80%">
          <stop offset="0" stop-color="#1a2340" stop-opacity=".55"/><stop offset=".6" stop-color="#141a30" stop-opacity=".2"/><stop offset="1" stop-color="#101528" stop-opacity="0"/>
        </radialGradient>
        <radialGradient id="sunE" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#fff3c8"/><stop offset=".55" stop-color="#f7d98a"/><stop offset="1" stop-color="#b8862f"/></radialGradient>
        <radialGradient id="sunhaze" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#f7d98a" stop-opacity=".55"/><stop offset="1" stop-color="#e7b64b" stop-opacity="0"/></radialGradient>
        <radialGradient id="groundglow" cx="50%" cy="30%" r="70%"><stop offset="0" stop-color="rgba(231,182,75,.28)"/><stop offset="1" stop-color="rgba(231,182,75,0)"/></radialGradient>
        <pattern id="dotfieldE" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="8" cy="8" r="1.1" fill="#f2e7cc" opacity="0.13"/></pattern>
        <linearGradient id="goldStroke" x1="0" x2="1"><stop offset="0" stop-color="#b8862f"/><stop offset=".5" stop-color="#f7d98a"/><stop offset="1" stop-color="#b8862f"/></linearGradient>
      </defs>

      <!-- FLAT indigo scene ground — exactly the page's #101528, no vertical gradient, no
           horizon band, and NO full-rect dot texture (that textured band was reading as a faint
           dulled rectangle against the plain copy area below). The scene is now identical to the
           page ground, so no tonal seam can ever show through the title. -->
      <rect width="1180" height="620" fill="#101528"/>

      <!-- SPINNING + GLOWING SUN, top-right — nudged DOWN & IN so the whole disc, rays and dashed
           rings render COMPLETE inside the scene (no clipping at the top or right edge). -->
      <g transform="translate(-20,44)">
        <circle id="sun-glow" cx="1040" cy="150" r="120" fill="url(#sunhaze)"/>
        <circle cx="1040" cy="150" r="52" fill="url(#sunE)"/>
        <g id="sun-spin">
          <g stroke="#f7d98a" stroke-width="2.4" opacity=".9">
            <path d="M1040 60 V80 M1040 220 V240 M950 150 H970 M1110 150 H1130 M976 86 l14 14 M1090 200 l14 14 M1104 86 l-14 14 M990 200 l-14 14"/>
          </g>
          <g stroke="#e7b64b" stroke-width="1.4" opacity=".55">
            <circle cx="1040" cy="150" r="86" fill="none"/>
            <circle cx="1040" cy="150" r="104" fill="none" stroke-dasharray="3 8"/>
          </g>
        </g>
      </g>

      <!-- (removed the faint upper-left Pithora animal motif — at this scale it read as a
           malformed bird rather than a horse, and it clipped at the top edge.) -->

      <!-- forest trees (D's tree-of-life), re-lit in gold-green -->
      <g stroke="#52a061" stroke-width="4" fill="none" opacity="0.9">
        <g transform="translate(80,400)">
          <line x1="0" y1="0" x2="0" y2="170"/>
          <path d="M0,20 C-34,10 -44,-18 -38,-42 M0,20 C34,10 44,-18 38,-42 M0,58 C-30,50 -38,28 -34,6 M0,58 C30,50 38,28 34,6"/>
          <circle cx="-38" cy="-42" r="8" fill="#e7b64b" stroke="none"/><circle cx="38" cy="-42" r="8" fill="#d63b2a" stroke="none"/><circle cx="0" cy="-20" r="9" fill="#2ea3a0" stroke="none"/>
        </g>
        <g transform="translate(1140,430)" opacity=".85">
          <line x1="0" y1="0" x2="0" y2="150"/>
          <path d="M0,10 C-28,2 -36,-20 -32,-42 M0,10 C28,2 36,-20 32,-42"/>
          <circle cx="-32" cy="-42" r="7" fill="#f7d98a" stroke="none"/><circle cx="32" cy="-42" r="7" fill="#2ea3a0" stroke="none"/>
        </g>
        <g transform="translate(250,450)" opacity=".6" stroke-width="3">
          <line x1="0" y1="0" x2="0" y2="120"/>
          <path d="M0,14 C-24,6 -30,-14 -26,-30 M0,14 C24,6 30,-14 26,-30"/>
          <circle cx="0" cy="-16" r="6" fill="#2f6b3c" stroke="none"/>
        </g>
      </g>

      <!-- NO ground-glow ellipses: at low opacity over the dark indigo the gold radial read as a
           muddy, desaturated horizontal smudge (not a glow). The ground stays flat uniform indigo. -->

      <!-- ACTION BAND — sits in the clear upper-middle of the scene, above the copy;
           statue FAR-LEFT shrine · archer left-of-centre · target FAR-RIGHT (long distance) -->
      <g transform="translate(0,0)">

      <!-- ========================================================
           STONE/CLAY STATUE OF DROṆA (idol) — D's design, but rendered
           as an unmistakable CARVED STONE-CLAY IDOL: matte, desaturated
           terracotta-stone, monumental on a clear stepped PEDESTAL, static.
           It is the shrine the self-taught archer practises before.
           Placed FAR-LEFT.
           ======================================================== -->
      <g transform="translate(140,182)">
        <defs>
          <linearGradient id="stoneBody" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#9a8574"/><stop offset=".5" stop-color="#7e6a5a"/><stop offset="1" stop-color="#584a3f"/>
          </linearGradient>
          <linearGradient id="stonePlinth" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#8b7868"/><stop offset="1" stop-color="#4a3f36"/>
          </linearGradient>
        </defs>
        <!-- cast shadow -->
        <ellipse cx="0" cy="226" rx="80" ry="14" fill="#000" opacity=".4"/>
        <!-- stepped stone PEDESTAL / plinth -->
        <rect x="-56" y="192" width="112" height="34" rx="3" fill="url(#stonePlinth)" stroke="#3a3128" stroke-width="1"/>
        <rect x="-46" y="158" width="92" height="36" rx="2" fill="url(#stonePlinth)" stroke="#3a3128" stroke-width="1"/>
        <line x1="-46" y1="176" x2="46" y2="176" stroke="#3a3128" stroke-width=".6" opacity=".5"/>
        <!-- rigid monumental body (D's silhouette), carved stone -->
        <path d="M0,12 C-26,12 -36,38 -34,66 L-32,128 L32,128 L34,66 C36,38 26,12 0,12 Z" fill="url(#stoneBody)" stroke="#4a3f36" stroke-width="1.2"/>
        <!-- carved/chiselled shading strokes on the robe (matte, not flat) -->
        <g stroke="#3d3229" stroke-width="1" opacity=".45" fill="none">
          <path d="M-20,40 C-14,70 -14,100 -18,124"/>
          <path d="M20,40 C14,70 14,100 18,124"/>
          <path d="M0,34 V126"/>
        </g>
        <!-- head — same stone material -->
        <circle cx="0" cy="-10" r="21" fill="url(#stoneBody)" stroke="#4a3f36" stroke-width="1.2"/>
        <path d="M-21,-16 C-14,-32 14,-32 21,-16" fill="none" stroke="#3d3229" stroke-width="4"/>
        <!-- carved brow + eyes (idol, not living face) -->
        <path d="M-11,-12 h7 M4,-12 h7" stroke="#3d3229" stroke-width="1.4" stroke-linecap="round"/>
        <!-- faint ivory dotwork carved into the robe (D's Pithora signature) -->
        <g fill="#efe6d2" opacity="0.5">
          <circle cx="-14" cy="52" r="1.5"/><circle cx="0" cy="48" r="1.5"/><circle cx="14" cy="52" r="1.5"/>
          <circle cx="-18" cy="78" r="1.5"/><circle cx="-6" cy="74" r="1.5"/><circle cx="6" cy="74" r="1.5"/><circle cx="18" cy="78" r="1.5"/>
          <circle cx="-14" cy="102" r="1.5"/><circle cx="0" cy="98" r="1.5"/><circle cx="14" cy="102" r="1.5"/>
        </g>
        <!-- carved blessing arm (stone) -->
        <path d="M30,44 C50,36 56,48 46,64" fill="none" stroke="url(#stoneBody)" stroke-width="9" stroke-linecap="round"/>
        <!-- faint gold rim-light from the scene, keeps it in C's cinematic key -->
        <path d="M0,12 C-26,12 -36,38 -34,66 L-32,128" fill="none" stroke="#b8862f" stroke-width=".8" opacity=".5"/>
      </g>

      <!-- lit diya at the statue's feet (D) -->
      <g transform="translate(140,322)">
        <ellipse cx="0" cy="4" rx="19" ry="5" fill="#9c6f1c"/>
        <path d="M-17 2 Q0 12 17 2 Q11 -3 0 -3 Q-11 -3 -17 2Z" fill="#e7b64b"/>
        <path class="flick" d="M0 -3 C-2 -9 3 -13 0 -20 C-3 -13 2 -9 0 -3Z" fill="#f7d98a"/>
        <circle cx="0" cy="-9" r="11" fill="rgba(247,217,138,.3)"/>
      </g>

      <!-- DISTANT TARGET — FAR RIGHT (long distance from the archer) -->
      <g transform="translate(1070,268)">
        <line x1="0" y1="16" x2="0" y2="150" stroke="#3a2f26" stroke-width="7" stroke-linecap="round"/>
        <line x1="0" y1="16" x2="0" y2="150" stroke="#b8862f" stroke-width="2.4"/>
        <circle cx="0" cy="0" r="42" fill="#151b0f" stroke="#e7b64b" stroke-width="2"/>
        <circle cx="0" cy="0" r="31" fill="none" stroke="#f2e7cc" stroke-width="2" opacity=".8"/>
        <circle cx="0" cy="0" r="20" fill="none" stroke="#d63b2a" stroke-width="2.4"/>
        <circle cx="0" cy="0" r="8" fill="#d63b2a"/>
        <!-- (No separate "landed" arrow — there is only ONE arrow (#fly-arrow). On a hit it
             simply STOPS in the bullseye and stays; on a miss it drops short and fades. This
             is why there is never a second arrow appearing in the target.) -->
        <!-- container for the "progress trail": at most a couple of arrows that truly stuck near
             the mark on earlier hits. JS appends correctly-placed single arrows here; never overlaps
             into a fake bullseye. -->
        <g id="stuck-arrows"></g>
        <!-- reduced-motion resolved state: ONE arrow buried head-first in the bullseye -->
        <g id="rest-stuck-arrow">
          <line x1="-70" y1="0" x2="-2" y2="0" stroke="#e8dcc0" stroke-width="2.6"/>
          <path d="M4 0 l-11 -5 l3 5 l-3 5 z" fill="#f7d98a" stroke="#b8862f" stroke-width=".6"/>
          <path d="M-70 0 l-12 -6 l6 6 l-6 6 z" fill="#57d3ce"/>
          <path d="M-63 0 l-10 -5 M-63 0 l-10 5" stroke="#f7d98a" stroke-width="1.8" stroke-linecap="round"/>
        </g>
        <!-- HIT burst (gold ripple) -->
        <g id="hit-burst" transform="translate(0,0)">
          <circle cx="0" cy="0" r="18" fill="none" stroke="#f7d98a" stroke-width="3"/>
          <circle cx="0" cy="0" r="30" fill="none" stroke="#e7b64b" stroke-width="1.6" opacity=".7"/>
          <g stroke="#fff6df" stroke-width="2.2" stroke-linecap="round">
            <path d="M0 -26 V-40 M0 26 V40 M-26 0 H-40 M26 0 H40 M-19 -19 l-9 -9 M19 19 l9 9 M19 -19 l9 -9 M-19 19 l-9 9"/>
          </g>
        </g>
        <!-- soft chime flash -->
        <circle id="chime-flash" cx="0" cy="0" r="52" fill="url(#sunhaze)"/>
      </g>

      <!-- (THE ONE ARROW is rendered AFTER the archer/bow below, so its shaft crosses IN FRONT of the
           bowstring and projects past the bow — never tucked behind the string.) -->

      <!-- ============ EKALAVYA — lone Bhil learner, left-of-centre, FACING RIGHT toward the target ============
           Head is a right-facing PROFILE: a small nose/brow juts right (toward the target), the eye sits on the
           right of the face and gazes at the mark, the single feather sweeps BACK (left) as a head facing right would. -->
      <g transform="translate(330,218)"><g id="archer">
        <!-- back quiver of arrows (behind the torso, on the far shoulder) -->
        <g transform="translate(-20,-8) rotate(-16)" opacity=".92">
          <path d="M0,4 l-7,44 l13,0 l7,-44 z" fill="#3a2f26" stroke="#b8862f" stroke-width=".8"/>
          <line x1="1" y1="2" x2="-1" y2="-14" stroke="#e8dcc0" stroke-width="1.6"/><path d="M-1 -14 l4 3 M-1 -14 l4 -1" stroke="#f7d98a" stroke-width="1.4" stroke-linecap="round"/>
          <line x1="6" y1="2" x2="5" y2="-12" stroke="#e8dcc0" stroke-width="1.6"/><path d="M5 -12 l4 3 M5 -12 l4 -1" stroke="#f7d98a" stroke-width="1.4" stroke-linecap="round"/>
        </g>
        <!-- torso — a slight forward lean toward the target -->
        <path d="M-2,0 C-18,1 -22,20 -19,40 L-16,92 L20,92 L21,40 C22,20 15,0 -2,0 Z" fill="#2f6b3c" stroke="#b8862f" stroke-width=".8"/>
        <g fill="#f2e7cc" opacity="0.72"><circle cx="-6" cy="32" r="1.4"/><circle cx="8" cy="32" r="1.4"/><circle cx="2" cy="54" r="1.4"/><circle cx="-6" cy="68" r="1.4"/><circle cx="10" cy="68" r="1.4"/></g>
        <!-- HEAD (right-facing profile): the face-mass leans right, a small nose juts toward the target -->
        <path d="M-11,-15 C-13,-25 -6,-31 3,-31 C13,-31 18,-24 18,-15 C18,-8 14,-2 6,-1 L8,3 L2,2 C-6,1 -11,-6 -11,-15 Z" fill="#b9764a" stroke="#e7b64b" stroke-width=".9"/>
        <!-- nose ridge jutting to the right (points at the mark) -->
        <path d="M18,-16 l4,3 l-4,3" fill="none" stroke="#a05a35" stroke-width="1.2" stroke-linecap="round"/>
        <!-- EYE on the right of the face, gaze toward the target -->
        <circle cx="10" cy="-17" r="1.9" fill="#241a0e"/>
        <path d="M6,-21 q4,-2 8,0" fill="none" stroke="#3a2f26" stroke-width="1.4" stroke-linecap="round"/>
        <!-- single Bhil feather sweeping BACK-LEFT from the crown (natural for a head facing right) -->
        <path d="M-6,-28 C-16,-36 -24,-40 -32,-44 C-24,-40 -18,-33 -10,-30 Z" fill="#d63b2a" stroke="#8a5e1f" stroke-width=".6"/>
        <line x1="-8" y1="-29" x2="-30" y2="-43" stroke="#8a5e1f" stroke-width=".8"/>
        <!-- a second short feather + a dotwork hair-band -->
        <path d="M-4,-30 C-12,-40 -18,-44 -24,-49 C-17,-42 -12,-35 -6,-32 Z" fill="#e7b64b" stroke="#8a5e1f" stroke-width=".5" opacity=".85"/>
        <path d="M-9,-24 q9,-5 18,-2" fill="none" stroke="#8a5e1f" stroke-width="1.4"/>
        <!-- ===== SHOOTING RIG (rebuilt) =====
             A symmetric bow whose BOTH limbs curve evenly and bulge RIGHT toward the target,
             its tips at (58,-42) and (58,76). The BOWSTRING is a chord that meets those exact tips
             (JS swaps its `d` between the resting chord and the drawn V). The BOW HAND grips the
             riser at the bow's middle; the DRAW HAND holds the nock and pulls the string back. -->
        <g id="shoot-arms">
          <!-- bow-arm: shoulder → riser grip (holds the bow out toward the mark) -->
          <path d="M4,20 C26,15 44,16 56,17" fill="none" stroke="#2f6b3c" stroke-width="8" stroke-linecap="round"/>
          <!-- symmetric bow: both limbs curve evenly, bulging right; tips at (58,-42) & (58,76) -->
          <path d="M58,-42 C92,-24 92,58 58,76" fill="none" stroke="url(#goldStroke)" stroke-width="4.8"/>
          <!-- bow hand gripping the middle (riser). NOTE: no inner "riser highlight" curve —
               it read as a spurious second bow-limb between the string and the bow. -->
          <circle cx="58" cy="17" r="5" fill="#b9764a" stroke="#8a5e1f" stroke-width=".6"/>
          <!-- BOWSTRING — chord meeting the two tips; JS sets its `d` (rest = straight, drawn = V) -->
          <path id="bowstring" d="M58,-42 L16,17 L58,76" fill="none" stroke="#f2e7cc" stroke-width="1.5"/>
          <!-- DRAW HAND — grips the nock at the string (moves with the draw, JS repositions) -->
          <g id="draw-arm">
            <path d="M-2,24 C6,22 12,20 16,17" fill="none" stroke="#2f6b3c" stroke-width="8" stroke-linecap="round"/>
            <circle cx="16" cy="17" r="4.2" fill="#b9764a" stroke="#8a5e1f" stroke-width=".6"/>
          </g>
        </g>
        <!-- CELEBRATION: both arms thrown UP in triumph, bow held aloft overhead (only on a HIT) -->
        <g id="celebrate-arm">
          <!-- right arm flung high, gripping the bow aloft -->
          <path d="M6,18 C24,-4 34,-34 40,-62" fill="none" stroke="#2f6b3c" stroke-width="8" stroke-linecap="round"/>
          <circle cx="40" cy="-62" r="4.5" fill="#b9764a"/>
          <!-- left arm raised high in a triumphant fist -->
          <path d="M-4,18 C-20,-4 -30,-34 -34,-62" fill="none" stroke="#2f6b3c" stroke-width="8" stroke-linecap="round"/>
          <circle cx="-34" cy="-64" r="4.5" fill="#b9764a"/>
          <!-- the bow, lifted horizontally above the head in triumph (clearly overhead) -->
          <g transform="translate(4,-74)">
            <path d="M-40,0 C-16,-24 16,-24 40,0" fill="none" stroke="url(#goldStroke)" stroke-width="4.8"/>
            <line x1="-40" y1="0" x2="40" y2="0" stroke="#f2e7cc" stroke-width="1.4"/>
          </g>
          <!-- little joy-sparks -->
          <g fill="#f7d98a"><circle cx="-46" cy="-40" r="2"/><circle cx="50" cy="-44" r="2"/><circle cx="0" cy="-92" r="2.4"/></g>
        </g>
      </g></g>

      <!-- ================= THE ONE ARROW (rendered on TOP of the bow — never behind the string) =================
           At rest: nock/fletching (~x=366) sits ON the string (scene-x≈388); the shaft CROSSES the string and
           the single arrowHEAD (~x=474) projects PAST the bow toward the target. JS gives it ONE transform per
           shot — a hit buries it in the bullseye; a miss drops it short/below and it fades. Never two arrows. -->
      <g id="fly-arrow">
        <!-- shaft: from the nock (left), across the string, projecting past the bow (right) -->
        <line x1="366" y1="235" x2="466" y2="235" stroke="#e8dcc0" stroke-width="2.6"/>
        <!-- single solid arrowhead at the FRONT (right), leading the flight -->
        <path d="M476 235 l-13 -5 l3 5 l-3 5 z" fill="#f7d98a" stroke="#b8862f" stroke-width=".7"/>
        <!-- fletching (the nock end): swept feathers at the TAIL -->
        <path d="M366 235 l-12 -6 l6 6 l-6 6 z" fill="#57d3ce"/>
        <path d="M374 235 l-11 -5" stroke="#f7d98a" stroke-width="1.8" stroke-linecap="round"/>
        <path d="M374 235 l-11 5" stroke="#f7d98a" stroke-width="1.8" stroke-linecap="round"/>
      </g>
      </g><!-- /action band lift -->
    </svg>"""
    )


# The verbatim shot-loop IIFE (docs/design/E_merged/index.html lines 2620–2755), wrapped in a
# <script>. Drives the draw → loose → fly → hit/miss cycle via the Web Animations API.
_HERO_JS = r"""<script>
(function(){
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- the progression knob -------------------------------------------
  var LEVEL = 24, MAX_LEVEL = 40;           // illustrative current rank
  // beginners land ~1 in 5 (0.20); masters land ~9 in 10 (0.90)
  var HIT_MIN = 0.20, HIT_MAX = 0.90;
  var t = Math.max(0, Math.min(1, LEVEL / MAX_LEVEL));
  var hitRate = HIT_MIN + (HIT_MAX - HIT_MIN) * t;   // e.g. Lvl 24/40 -> 0.62

  // Deterministic "n hits per window" schedule so it reads as skill, not luck.
  // Round hitRate to k hits out of WINDOW shots, spread as evenly as possible.
  var WINDOW = 5;
  var hits = Math.round(hitRate * WINDOW);          // Lvl 24 -> 3 of 5
  var schedule = [];
  for (var i=0;i<WINDOW;i++){
    // Bresenham-style even spread of `hits` true values across WINDOW slots
    schedule.push(Math.floor((i+1)*hits/WINDOW) - Math.floor(i*hits/WINDOW) > 0);
  }
  // put an early miss first so the "struggle then succeed" story is legible
  if (schedule[0] === true && hits < WINDOW){
    var j = schedule.indexOf(false); schedule[0]=false; schedule[j]=true;
  }

  var arrow   = document.getElementById('fly-arrow');
  var drawArm = document.getElementById('draw-arm');
  var bowstr  = document.getElementById('bowstring');   // the string path (d swapped: chord vs drawn V)
  var shootArms = document.getElementById('shoot-arms');
  var celeb   = document.getElementById('celebrate-arm');
  var archer  = document.getElementById('archer');
  var burst   = document.getElementById('hit-burst');
  var chime   = document.getElementById('chime-flash');
  var stuck   = document.getElementById('stuck-arrows'); // container for arrows that truly stuck near the mark
  if(!arrow) return;

  // reduced motion: rest on the resolved frame (ONE arrow already stuck in the bullseye)
  if (reduce){ arrow.style.opacity=0; return; }

  // string shapes (archer-local coords): rest = straight chord tip-to-tip; drawn = V pulled to the cheek
  var STRING_REST = 'M58,-42 L58,76';
  var STRING_DRAWN = 'M58,-42 L16,17 L58,76';
  if(bowstr) bowstr.setAttribute('d', STRING_REST);

  var shot = 0, hitsShown = 0;
  // The arrow's HEAD tip sits at scene ~(476,235); the bullseye centre is at scene ~(1070,268).
  // So to bury the head in the bullseye the arrow travels dx≈594, dy≈33.
  var HIT = {x:594, y:33};
  // Misses land visibly SHORT or BELOW and stay there briefly, then fade. They never reach the target.
  var MISSES = [
    {x:300, y:150},   // falls short, into the near ground
    {x:470, y:120},   // half-way, drops low
    {x:560, y:150},   // close but drops well BELOW the bullseye
    {x:200, y:70}     // a weak early release, barely past the bow
  ];
  var EASE_FLY = 'cubic-bezier(.30,.02,.34,1)';   // a smooth, weighty flight arc
  function anim(el, frames, opts){ return el.animate(frames, Object.assign({fill:'forwards'}, opts)); }

  function shoot(){
    var isHit = schedule[shot % WINDOW];
    var missIdx = shot % MISSES.length;
    shot++;

    // Hard reset — guarantee exactly ONE live arrow, nocked, before every shot.
    if(celeb) celeb.style.opacity = 0; if(shootArms) shootArms.style.opacity = 1;
    arrow.style.opacity = 0;
    arrow.style.transform = 'translate(0,0)';

    // 1) DRAW — string bends into the V, the draw hand + nocked arrow pull back to the cheek (~ -34px)
    if(bowstr) setTimeout(function(){ bowstr.setAttribute('d', STRING_DRAWN); }, 40);
    arrow.style.opacity = 1;
    if(arrow)   anim(arrow,   [{transform:'translate(0,0)'},{transform:'translate(-34px,0)'}], {duration:560, easing:'cubic-bezier(.4,0,.5,1)'});
    if(drawArm) anim(drawArm, [{transform:'translate(0,0)'},{transform:'translate(-34px,0)'}], {duration:560, easing:'cubic-bezier(.4,0,.5,1)'});
    if(archer)  anim(archer,  [{transform:'translateX(0)'},{transform:'translateX(-2px)'}], {duration:560, easing:'ease-out'});

    setTimeout(function(){
      // 2) LOOSE — string snaps to the resting chord, the draw hand releases, a crisp recoil
      if(bowstr) bowstr.setAttribute('d', STRING_REST);
      if(drawArm) anim(drawArm, [{transform:'translate(-34px,0)'},{transform:'translate(2px,0)'},{transform:'translate(0,0)'}], {duration:150, easing:'ease-out'});
      if(archer)  anim(archer, [{transform:'translateX(-2px)'},{transform:'translateX(3px)'},{transform:'translateX(0)'}], {duration:260, easing:'ease-out'});

      // 3) THE ONE ARROW FLIES — from the drawn (-34) position, in a gravity-touched arc to its destination.
      var dest = isHit ? HIT : MISSES[missIdx];
      var midX = -34 + (dest.x+34)*0.52, midY = dest.y*0.5 - (isHit?24:10);   // apex, lifted
      var flight = anim(arrow, [
        {transform:'translate(-34px,0) rotate(-4deg)', opacity:1, offset:0},
        {transform:'translate('+midX+'px,'+midY+'px) rotate(1deg)', opacity:1, offset:0.5},
        {transform:'translate('+dest.x+'px,'+dest.y+'px) rotate('+(isHit?4:16)+'deg)', opacity:1, offset:1}
      ], {duration: isHit?700:560, easing:EASE_FLY});

      flight.onfinish = function(){
        if (isHit){
          // 4a) HIT — the SAME arrow is now buried in the bullseye. Celebrate ONLY here.
          //     Freeze the arrow stuck in the mark, fire the burst/chime, raise the bow, jump.
          arrow.style.transform = 'translate('+HIT.x+'px,'+HIT.y+'px) rotate(4deg)';  // stays stuck
          if(burst){ burst.style.opacity=1; anim(burst,[{transform:'scale(.2)',opacity:1},{transform:'scale(1)',opacity:1,offset:.4},{transform:'scale(1.6)',opacity:0}],{duration:760,easing:'ease-out'}); }
          if(chime){ chime.style.opacity=0; anim(chime,[{opacity:0},{opacity:.6,offset:.3},{opacity:0}],{duration:760,easing:'ease-out'}); }
          if(shootArms) shootArms.style.opacity = 0;
          if(celeb){ celeb.style.opacity=1; }
          if(archer) anim(archer, [
            {transform:'translateY(0)'},{transform:'translateY(-22px)',offset:.34},
            {transform:'translateY(-26px)',offset:.5},{transform:'translateY(-4px)',offset:.8},{transform:'translateY(0)'}
          ], {duration:1000, easing:'cubic-bezier(.3,.7,.35,1)'});
          setTimeout(function(){
            // leave a small "progress trail": keep this hit as a stuck arrow near the mark, then hide the live arrow.
            if(stuck && hitsShown < 2){
              var s = document.createElementNS('http://www.w3.org/2000/svg','g');
              // place trail arrows in the OUTER rings (never the dead-centre bullseye) so they read as
              // "arrows from earlier hits" and can never be mistaken for a second live centre hit.
              var ty = hitsShown ? -24 : 22;
              s.setAttribute('transform','translate(-8,'+ty+') rotate('+(hitsShown?-8:8)+')');
              s.innerHTML='<line x1="-58" y1="0" x2="-8" y2="0" stroke="#e8dcc0" stroke-width="2.2" opacity=".7"/>'+
                '<path d="M-4 0 l-9 -4 l2 4 l-2 4 z" fill="#e7b64b" opacity=".8"/>'+
                '<path d="M-58 0 l-10 -5 l5 5 l-5 5 z" fill="#3fa39f" opacity=".7"/>';
              stuck.appendChild(s); hitsShown++;
            }
            if(celeb) celeb.style.opacity=0; if(shootArms) shootArms.style.opacity=1;
            arrow.style.opacity=0; arrow.style.transform='translate(0,0)';
            next();
          }, 1600);
        } else {
          // 4b) MISS — the SAME arrow lies short/below where it fell; NO celebration.
          //     A brief stick, then it fades, and the archer simply re-nocks and tries again.
          setTimeout(function(){
            anim(arrow, [{opacity:1},{opacity:0}], {duration:340, easing:'ease-in'}).onfinish=function(){
              arrow.style.opacity=0; arrow.style.transform='translate(0,0)';
            };
            setTimeout(next, 360);
          }, 360);
        }
      };
    }, 620);
  }
  function next(){ setTimeout(shoot, 480); }
  // kick off after fonts/paint settle
  setTimeout(shoot, 800);
})();
</script>"""


# --- login page (multi-user) -----------------------------------------------
# Apple-style scroll auth: the page OPENS on the RICH Option E hero (giant gold wordmark, the
# poetic outsider tagline, the four chips — identical to /welcome) over a FIXED animated Option E
# scene (the lone archer looses arrows at a distant target — miss, miss, hit + celebration). The
# scene keeps running behind everything and NEVER reloads; scrolling down (or clicking ↓ enter the
# forest / the nav "Log in") slides a GLASSMORPHIC login/signup card UP over the SAME still-visible
# scene. Reuses the shared design system (/static/eklavya.css) and the Option E hero classes.
# The form action, field names, {{start}}/{{error}} slots and the Log in / Sign up tab toggle are
# all preserved for the auth flow + tests. The scene JS is injected before </body>.
_LOGIN = (r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ekalavya — Sign in</title>
<link rel="stylesheet" href="/static/fonts.css">
<link rel="stylesheet" href="/static/eklavya.css">
<style>
/* Apple-style scroll: a FIXED full-viewport animated Option E scene, content scrolls above it.
   The hero opens on the RICH brand (Option E hero); scrolling slides a glassmorphic auth card UP
   over the SAME still-running scene (visible around/through the frosted glass). ONE .scene-fixed
   instance is rendered → the background is byte-identical in both states and never reloads. */
html{scroll-behavior:smooth}
body{min-height:100vh;margin:0;padding:0;background:var(--void)}
/* 1) FIXED background layer — the animated scene fills the viewport and stays put on scroll */
.scene-fixed{position:fixed;inset:0;z-index:0;overflow:hidden}
.scene-fixed svg{position:absolute;inset:0;width:100%;height:100%;display:block}
/* dark-indigo scrim over the scene for legibility (keeps the artwork readable behind glass) */
.scene-scrim{position:fixed;inset:0;z-index:0;pointer-events:none;
  background:linear-gradient(180deg,rgba(10,13,28,.34) 0%,rgba(10,13,28,.20) 42%,rgba(10,13,28,.58) 100%)}
/* 2) scrolling content above the scene */
.scroll{position:relative;z-index:1}
/* a thin brand bar floating over the top of the hero (transparent, never competes with the wordmark) */
.land-nav{position:absolute;top:0;left:0;right:0;z-index:5;border-bottom:0;background:transparent;padding:20px clamp(26px,6vw,90px)}
/* HERO — the rich Option E hero, full-viewport, copy pinned to the bottom-left like docs/design/E_merged */
.auth-hero{position:relative;min-height:100svh;display:flex;flex-direction:column;justify-content:flex-end}
.auth-hero .hero-copy{max-width:1000px}
/* AUTH — a full-viewport section that slides its glassmorphic card UP over the same scene */
.auth-sec{min-height:100svh;display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:56px 22px;text-align:center}
.glass{width:100%;max-width:460px;text-align:left;
  background:rgba(10,13,28,.55);backdrop-filter:blur(16px) saturate(1.25);-webkit-backdrop-filter:blur(16px) saturate(1.25);
  border:1px solid var(--line-gold);border-radius:18px;
  box-shadow:0 24px 70px -20px rgba(0,0,0,.7),0 1px 0 rgba(247,217,138,.08) inset;
  padding:34px 34px 30px;
  /* rest state for the slide-up reveal (JS toggles .in when the card scrolls into view) */
  opacity:0;transform:translateY(38px);transition:opacity .7s cubic-bezier(.2,.7,.3,1),transform .7s cubic-bezier(.2,.7,.3,1)}
.glass.in{opacity:1;transform:none}
.glass form{display:flex;flex-direction:column}
.err{font-family:var(--f-mono);font-size:12px;letter-spacing:.02em;color:var(--vermilion-glow);
  border:1px solid rgba(214,59,42,.4);background:rgba(143,35,24,.16);border-radius:4px;
  padding:9px 12px;margin:0 0 16px}
/* honour reduced-motion: no slide, no bob — the card is simply present */
@media(prefers-reduced-motion:reduce){.glass{opacity:1;transform:none;transition:none}}
@media(max-width:560px){.glass{padding:26px 20px 24px}.glass .ah{font-size:24px}.auth-sec{padding:44px 16px}}
</style></head><body>
<div class="scene-fixed">""" + _hero_scene("xMidYMid slice") + r"""</div>
<div class="scene-scrim"></div>
<div class="scroll">
  <!-- thin brand bar; "Log in" scrolls to the auth card over the same scene -->
  <div class="land-nav">
    <div class="brand"><svg width="22" height="26" viewBox="0 0 58 76"><path d="M14 6 C40 24 40 52 14 70" stroke="#e7b64b" stroke-width="3.4" stroke-linecap="round" fill="none"/><line x1="14" y1="6" x2="14" y2="70" stroke="#57d3ce" stroke-width="1.4"/><line x1="14" y1="38" x2="50" y2="38" stroke="#f7d98a" stroke-width="2"/><path d="M50 38 l-7 -5 M50 38 l-7 5" stroke="#f7d98a" stroke-width="2" stroke-linecap="round"/></svg> EKALAVYA</div>
    <div class="links"><a href="/about" style="color:inherit;text-decoration:none">The Method</a><a href="/about" style="color:inherit;text-decoration:none">Manifesto</a></div>
    <span style="flex:1"></span>
    <a class="btn btn-ghost" style="padding:9px 18px" href="#auth">Log in</a>
  </div>

  <!-- ============================================================
       HERO — the RICH Option E hero (identical to /welcome), over the
       FIXED animated scene. docs/design/E_merged/index.html · hero-copy.
       ============================================================ -->
  <header class="auth-hero" id="hero">
    <!-- rotating yantra behind (from Option E) -->
    <svg class="hero-yantra" viewBox="0 0 400 400" aria-hidden="true">
      <g class="spin" fill="none" stroke="#e7b64b" stroke-width="1">
        <circle cx="200" cy="200" r="190"/><circle cx="200" cy="200" r="150"/><circle cx="200" cy="200" r="110"/><circle cx="200" cy="200" r="70"/>
      </g>
    </svg>
    <div class="hero-copy">
      <div class="hero-tag">The Merge — Cinematic Forest</div>
      <h1 class="eka">EKALAVYA</h1>
      <div class="eka-deva">एकलव्य · स्वाध्याय</div>
      <p class="hero-sub">The <b>hall was closed</b> to him — so he walked into the forest, raised a statue of the guru who refused him, and taught himself to outshoot the princes. An AI coding tutor for <b>the self-taught, the boundary-crossers, the ones told they couldn't be taught.</b></p>
      <div class="hero-meta">
        <span>Guru: <b>the statue</b></span>
        <span>Arena: <b>the forest</b></span>
        <span>Path: <b>svādhyāya</b> · self-study</span>
        <span>Dakshinā: <b>the thumb</b></span>
      </div>
    </div>
    <!-- ↓ scrolls the auth card UP over the same scene (no page/scene reload) -->
    <a class="scrollcue" href="#auth" style="text-decoration:none">↓ enter the forest</a>
  </header>
  <section class="auth-sec" id="auth">
    <div class="glass auth-form">
      <div class="auth-tabs" role="tablist" aria-label="Authentication mode">
        <span class="on" id="tab-login" role="tab" tabindex="0" aria-selected="true" onclick="authMode('login')">Log in</span>
        <span id="tab-signup" role="tab" tabindex="0" aria-selected="false" onclick="authMode('signup')">Sign up</span>
      </div>
      <div class="ah" id="auth-h">Welcome back, devotee</div>
      <div class="asub" id="auth-sub">The forest remembers where you left the string.</div>
      {{notice}}
      {{error}}
      <div class="err" id="client-err" style="display:none"></div>
      <form method="post" action="/login" id="authform">
        <div class="field"><label class="field-lbl" for="email">Email</label>
          <input id="email" class="inp" name="email" type="email" autocomplete="username" required></div>
        <div class="field"><label class="field-lbl" for="password">Password</label>
          <input id="password" class="inp" name="password" type="password" autocomplete="current-password" required></div>
        <div class="field" id="confirm-field" style="display:none"><label class="field-lbl" for="confirm">Confirm password</label>
          <input id="confirm" class="inp" name="confirm" type="password" autocomplete="new-password"></div>
        <div class="signup-note" id="pw-hint" style="display:none;font-family:var(--f-serif);font-style:italic;font-size:13px;color:var(--parch-dim);margin:-2px 0 14px">At least 10 characters. Your password is hashed with argon2 — never stored in the clear.</div>
        <button type="submit" class="btn btn-gold" id="auth-submit" style="width:100%;justify-content:center;margin-top:8px">Sign in — draw the string</button>
      </form>
    </div>
  </section>
</div>
<script>
// Visual Log-in ↔ Sign-up toggle. Auth is email/password only (no OAuth). Both tabs post a
// REAL form — login → /login, signup → /signup (which creates the account) — sharing one
// themed form; the signup tab reveals a confirm field + a password hint.
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
  document.getElementById('confirm-field').style.display = login ? 'none' : 'block';
  document.getElementById('pw-hint').style.display = login ? 'none' : 'block';
  document.getElementById('confirm').required = !login;
  document.getElementById('password').setAttribute('autocomplete', login ? 'current-password' : 'new-password');
  document.getElementById('authform').setAttribute('action', login ? '/login' : '/signup');
  document.getElementById('auth-submit').textContent = login ? 'Sign in — draw the string' : 'Raise your statue — begin';
  document.getElementById('client-err').style.display='none';
}
// client-side guard on signup: length + match, so obvious mistakes never round-trip.
document.getElementById('authform').addEventListener('submit',function(e){
  if((this.getAttribute('action')||'').indexOf('/signup')>=0){
    const p=document.getElementById('password').value, c=document.getElementById('confirm').value;
    const msg = p.length<10 ? 'Password must be at least 10 characters.' : (p!==c ? 'Passwords do not match.' : '');
    if(msg){ e.preventDefault(); const el=document.getElementById('client-err'); el.textContent=msg; el.style.display='block'; }
  }
});
// Slide-up reveal: the glass card fades + rises the first time it scrolls into view — the
// FIXED scene behind it never moves or reloads. If the page should open ON the auth card
// (arriving on /signup, an explicit #auth link, or a bounced-back error/notice), reveal it
// straightaway, scroll it into view over the same scene, and focus the first field.
(function(){
  const card=document.querySelector('.glass');
  const auth=document.getElementById('auth');
  // a SERVER-rendered error/notice means the visitor already submitted — jump to the card.
  // (Ignore the always-present, hidden #client-err validation placeholder.)
  const hasMsg=[...card.querySelectorAll('.err, .notice')].some(el=>el.id!=='client-err' && el.textContent.trim());
  const openOnAuth = location.hash==='#auth' || {{start_is_signup}} || hasMsg;
  if(openOnAuth){
    card.classList.add('in');
    auth.scrollIntoView({block:'center'});   // over the SAME fixed scene — no reload
    document.getElementById('email').focus({preventScroll:true});
  } else if('IntersectionObserver' in window){
    const io=new IntersectionObserver(function(es){
      es.forEach(function(en){ if(en.isIntersecting){ card.classList.add('in'); io.disconnect(); } });
    },{threshold:.35});
    io.observe(card);
  } else { card.classList.add('in'); }  // no-IO fallback: just show it
})();
authMode('{{start}}');
</script>
""" + _HERO_JS + r"""
</body></html>""")


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
<style>body{padding:0;min-height:100vh}
/* the landing sits ON the hero itself — the animated Option E scene fills the hero band,
   the copy is pinned to the bottom, exactly as in docs/design/E_merged/index.html. The
   shared .landing indigo ground carries the section below the hero (feature cards). */
/* a fixed brand bar floats over the top of the full-bleed hero (Option E has no nav; we add a
   thin one for auth entry, kept transparent so it never competes with the giant wordmark) */
.land-nav{position:absolute;top:0;left:0;right:0;z-index:5;border-bottom:0;background:transparent;padding:20px clamp(26px,6vw,90px)}
</style></head><body>
<div class="landing">
  <div class="land-nav">
    <div class="brand"><svg width="22" height="26" viewBox="0 0 58 76"><path d="M14 6 C40 24 40 52 14 70" stroke="#e7b64b" stroke-width="3.4" stroke-linecap="round" fill="none"/><line x1="14" y1="6" x2="14" y2="70" stroke="#57d3ce" stroke-width="1.4"/><line x1="14" y1="38" x2="50" y2="38" stroke="#f7d98a" stroke-width="2"/><path d="M50 38 l-7 -5 M50 38 l-7 5" stroke="#f7d98a" stroke-width="2" stroke-linecap="round"/></svg> EKALAVYA</div>
    <div class="links"><a href="#method" style="color:inherit;text-decoration:none">The Method</a><a href="#method" style="color:inherit;text-decoration:none">Skill Forest</a><a href="#method" style="color:inherit;text-decoration:none">Manifesto</a></div>
    <span style="flex:1"></span>
    <a class="btn btn-ghost" style="padding:9px 18px" href="/login">Log in</a>
    <a class="btn btn-stone" style="padding:9px 20px" href="/signup">Begin your svādhyāya</a>
  </div>

  <!-- ============================================================
       HERO — FULL-BLEED · DYNAMIC (Option E, ported verbatim)
       docs/design/E_merged/index.html · <header class="hero"> …
       ============================================================ -->
  <header class="hero">
    <!-- rotating yantra behind (from Option E) -->
    <svg class="hero-yantra" viewBox="0 0 400 400" aria-hidden="true">
      <g class="spin" fill="none" stroke="#e7b64b" stroke-width="1">
        <circle cx="200" cy="200" r="190"/><circle cx="200" cy="200" r="150"/><circle cx="200" cy="200" r="110"/><circle cx="200" cy="200" r="70"/>
      </g>
    </svg>

    <!-- the full-bleed cinematic scene: lone Bhil archer + clay Droṇa + spinning sun + flying
         arrow + target. Top-anchored (xMidYMin slice) so more of the scene reads, like Option E. -->
    <div class="hero-scene">""" + _hero_scene("xMidYMin slice") + r"""</div>

    <!-- feathers the scene into the copy ground (Option E's hero-scrim) -->
    <div class="hero-scrim"></div>

    <div class="hero-copy">
      <div class="hero-tag">The Merge — Cinematic Forest</div>
      <h1 class="eka">EKALAVYA</h1>
      <div class="eka-deva">एकलव्य · स्वाध्याय</div>
      <p class="hero-sub">The <b>hall was closed</b> to him — so he walked into the forest, raised a statue of the guru who refused him, and taught himself to outshoot the princes. An AI coding tutor for <b>the self-taught, the boundary-crossers, the ones told they couldn't be taught.</b></p>
      <div class="hero-meta">
        <span>Guru: <b>the statue</b></span>
        <span>Arena: <b>the forest</b></span>
        <span>Path: <b>svādhyāya</b> · self-study</span>
        <span>Dakshinā: <b>the thumb</b></span>
      </div>
    </div>
    <!-- the CTA: "enter the forest" leads into the app (multi-user → /login) -->
    <a class="scrollcue" href="/" style="text-decoration:none">↓ enter the forest</a>
  </header>
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
""" + _HERO_JS + r"""
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
