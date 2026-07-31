# Ekalavya — Four-Surface Parity & Consistency Audit

**Date:** 2026-08-01 · **Scope:** CLI (`cli.py`), TUI (`tui.py`), Web (`webapp.py`), MCP (`mcp_server.py`)
and the shared spine (`agent.py`, `tools.py`, `prompts.py`, `progress.py`, `report.py`, `db/`).
**Method:** read-only source review + full test suite. **Tests:** `uv run pytest -q` → **260 passed, 1 warning** (deprecation only).

The four surfaces are genuinely one app for the CLI/TUI/Web trio (same `build_agent`, same `AGENT_TOOLS`,
same prompts, same SQLite state via the contextvar). The MCP surface is a **deliberately different, thinner**
integration (host agent is the brain; Ekalavya is only the state spine). The real gaps are in **session
lifecycle** (TUI/CLI/MCP don't get the temporal awareness the web now has) and a handful of **surface-coverage**
asymmetries.

---

## 1. Feature Parity Matrix

Legend: ✅ present · ➖ intentionally absent (by design) · ⚠️ missing where it arguably should exist · — n/a

| Capability | CLI | TUI | Web | MCP | Notes |
|---|:--:|:--:|:--:|:--:|---|
| Onboarding mode | ✅ | ➖ | ✅ | ➖ | CLI `onboard`; web `onboard`. TUI only launches `practice` (`cli.py:187`); no way to onboard from the TUI. MCP: host agent drives. |
| Practice mode | ✅ | ✅ | ✅ | ➖ | `cli.py:142` / `cli.py:170` (tui) / `webapp.py:19`. |
| Mock interview | ✅ | ⚠️ | ✅ | ➖ | CLI `mock` (`cli.py:116`), web `mock`. TUI is hard-wired to `prompts.SESSION` — no mock/takehome/aiinterview. |
| Take-home | ✅ | ⚠️ | ✅ | ➖ | `cli.py:208`, web. Not reachable from TUI. |
| **AI-enabled interview** (`aiinterview`) | ⚠️ | ⚠️ | ✅ | ➖ | **Web-only mode.** No CLI command exists (only appears in `_mode_agent` resume table, `cli.py:243`). See P1-A. |
| Dashboard | ➖ | ➖ | ✅ | ➖ | `/dashboard` (`webapp.py:173`). CLI/TUI expose only `/stats` slash (`commands.py:52`). |
| Journey view | ➖ | ➖ | ✅ | ➖ | `/journey` (`webapp.py:177`). |
| Profile view / edit | partial | ➖ | ✅ | ➖ | Web: `/profile` + GET/PUT `/api/profile` (`webapp.py:183-201`). CLI `doctor` only reports the path exists. No CLI/TUI profile view/edit. |
| Canvas / artifacts | ➖ | ➖ | ✅ | ➖ | Full CRUD API + `save_artifact` tool (`webapp.py:509-555`). The `save_artifact` *tool* is in `AGENT_TOOLS`, so CLI/TUI agents CAN write artifacts, but there is no CLI/TUI viewer. |
| Persistent chats (list/resume) | ✅ | ⚠️ | ✅ | ➖ | CLI `chats`/`resume` (`cli.py:251,271`); web `/api/chats`. **TUI can neither list nor resume** — `cli.py:191` always mints a fresh thread via `new_thread()`. |
| Code-context: scan local repo | ✅ | ➖ | ➖ | ➖ | CLI `scan` (`cli.py:471`). Web relies on `read_github` tool instead (no local FS on server). |
| Code-context: `read_github` (tool) | ✅ | ✅ | ✅ | ⚠️ | In `AGENT_TOOLS` → available to CLI/TUI/Web agents. **Not exposed by MCP** (`mcp_server.py` omits it). |
| Résumé PDF intake | ✅ | ➖ | ✅ | ➖ | CLI `onboard --resume` (`cli.py:82`); web `/api/upload-resume` (`webapp.py:450`). `read_resume` tool available to all agents; no TUI upload path. |
| Provider settings / fallback | partial | ➖ | ✅ | — | Fallback chain is universal (`agent.py:85`). Web reads the user's **saved** provider (`webapp.py:108 _active_provider`). CLI/TUI honor only the `--provider` flag / env default, **never the saved Settings choice** — see P1-B. |
| Conversation controls (Esc-cancel) | ➖ | ✅ | ✅ | — | TUI `action_cancel` (`tui.py:271`); web has stop. CLI has no cancel (blocking `invoke`). |
| Conversation controls (rewind/edit) | ➖ | ➖ | ✅ | — | Web `/api/truncate` (`webapp.py:381`). Not in CLI/TUI. |
| run_bash approval UX | ✅ | ✅ | ✅ | ➖ | CLI y/N (`chat.py:23`), TUI modal (`tui.py:52`), web card (`webapp.py:282`). MCP has no run_bash tool at all. |
| Skill-tree / forest map | ➖ | ➖ | ✅ | ➖ | `/api/forest` + `report.forest_map` (`webapp.py:207`). No terminal rendering. |
| Anti-cheat (paste penalty) | ➖ | ✅ | ✅ | — | TUI `_flag_cheat` (`tui.py:356`); web `/api/penalise`. CLI has no editor, so n/a. |
| Self-check (LLM judge) | ✅ | ✅ | ✅ | ➖ | `verify.selfcheck` in `run_turn` (`chat.py:50`), TUI worker (`tui.py:215`), web `_events` (`webapp.py:298`). MCP: host agent is the brain, no selfcheck. |

**Parity gaps worth flagging:**
- **P1-A** `aiinterview` is a first-class web mode with a full prompt (`prompts.AI_INTERVIEW`), a dedicated
  toolset (`AIINTERVIEW_TOOLS`), a DB table (`ai_assists`), and interview-scoping (`mark_interview`) — but has
  **no CLI command**. A learner can start it in the browser but never from the terminal. (The `_mode_agent`
  table can *resume* one, `cli.py:243`, but `mark_interview` is never called on the CLI path, so the
  `interview_thread` pointer is never set and `review_ai_usage` would read a stale/empty scope.)
- The **TUI is the weakest surface**: only `practice`, no mode selection, no chat list/resume, no onboarding,
  no résumé upload. Everything funnels through `cli.py tui()` → `prompts.SESSION`.

---

## 2. Session Lifecycle Consistency  — **the biggest real inconsistency**

Three different lifecycle behaviors across four surfaces:

| Surface | Opens a session? | How | Injects `session_context_line`? |
|---|---|---|---|
| CLI (`practice`/`mock`/`takehome`) | ✅ | `progress.start_session()` in a `try/finally` with `end_session()` (`cli.py:134,162,226`) | ❌ **No** |
| CLI (`onboard`, `resume`) | ❌ | — | ❌ No |
| TUI | ✅ | `progress.start_session(minutes)` + `end_session()` (`cli.py:203-205`) | ❌ **No** |
| Web (session modes) | ✅ | `progress.ensure_session()` **every turn** (`webapp.py:333`) | ✅ **Yes, every turn** (`webapp.py:337-341`) |
| MCP | ❌ **Never** | — | ❌ No |

### 2a. TUI *does* open a session — but never sees the context (**P1**)
Contrary to the concern, the TUI **does** open a session: `cli.py:203` wraps `tui_app.run()` in
`start_session`/`end_session`. So `session_context()` elapsed/gap/`sessions_total` are *recorded* for the TUI.
**However**, the TUI reply path (`tui.py make_stream_responder` → `agent.stream`) **never injects
`session_context_line()`**. It also does not call `maybe_autorefresh()`. So the agent has no temporal awareness
in the TUI even though the row exists.

### 2b. `session_context_line` is injected for **web only** (**P1**)
The temporal-briefing line (elapsed / gap-since-last-visit / last-time topics / due reviews / today's date —
issue #59) is prepended **only** in `webapp.py:338`. Neither `chat.run_turn` (CLI + `make_responder` fallback)
nor `tui.make_stream_responder` nor the MCP tools inject it. Consequences on CLI/TUI:
- the agent has **no idea what today's date is** (the system prompt is cached and dateless);
- **no "welcome back, it's been N days" / gap awareness**;
- **no "last time we did X" recap**;
- **no due-review count** surfaced to the model at turn start.

This silently degrades the temporal-awareness feature on every terminal surface. The right fix is to move the
`session_context_line` prepend into the shared turn path (`chat.run_turn` and `tui.make_stream_responder`), not
duplicate it in each command.

### 2c. Two different session models (**P2, by design but undocumented**)
CLI/TUI use **fixed-boundary** sessions (`start_session`/`end_session` bracket the process). Web uses
**idle-gap** sessions (`ensure_session`, reuse within `IDLE_GAP_MIN=45`, `progress.py:279`). A learner who uses
both surfaces gets inconsistent session counting (each CLI run = one session; a web burst = one session across
many turns). Acceptable, but the `mode` label defaults differ: CLI `practice` passes no mode →
`start_session` defaults to `"guided"` (`progress.py:219`), while web passes `"practice"`. So the same activity
is labeled **`guided`** in CLI vs **`practice`** in web — a real mismatch in `sessions.mode` and the dashboard.
(`cli.py:162` calls `start_session(minutes)` with no mode; `mock`/`takehome`/`tui` pass their mode, but plain
`practice` does not, and neither does the TUI which is a practice session.)

### 2d. MCP opens no session at all (**P2, expected**)
`mcp_server.py` never calls `start_session`/`ensure_session`. Its `record_attempt`/`grade_and_record` therefore
write `session_id = current_session(conn)` which may be **NULL or a stale session from a previous CLI run**
(`tools.py:358`). Attempts recorded via MCP land in whatever session pointer happens to be set — cross-run
contamination of `session_id`. Low impact (MCP is host-driven), but the attribution is wrong.

---

## 3. Agent / Harness Logic

- **`execute` floor tool excluded everywhere:** ✅. `build_agent` calls `_exclude_execute_tool()`
  unconditionally at `agent.py:71`, registering a `HarnessProfile(excluded_tools={"execute"})` keyed on
  `"fallbackchatmodel"` — and the fallback model always reports that provider (`agent.py:19-22` comment). Since
  **all four surfaces build agents through `build_agent`** (CLI/TUI/Web) or don't build an agent at all (MCP),
  the builtin shell is dropped uniformly. The chatstore `_reader_agent` (`chatstore.py:172`) also goes through
  `build_agent`, so even the read-only reconstruction agent has it excluded. Consistent.
- **`grade_and_record` is the only grading path:** ✅. Grading = sandbox execution in `tools.grade_and_record`
  (`tools.py:377`), which self-checks the reference against the tests before grading the learner, then calls
  `record_attempt`. `verify.selfcheck` is a **fact-check note only** — it never writes state or records an
  attempt (`verify.py:193`). No self-grading path exists. MCP exposes the same `grade_and_record`
  (`mcp_server.py:40`), delegating to the identical function.
- **Toolset identical across CLI/TUI/Web:** ✅. All three use `SESSION_TOOLS`/`ONBOARDING_TOOLS`/
  `AIINTERVIEW_TOOLS`, which are all **aliases of the same `AGENT_TOOLS` list** (`tools.py:620-622`) — so the
  mode-specific tool tables are cosmetic; every mode gets every tool, and the prompt differentiates behavior.
  `build_agent` then appends `cached_mcp_tools()` for all (`agent.py:88`).
- **MCP exposes a strict subset (`P2`, by design):** MCP registers only 7 tools (`get_progress`,
  `suggest_focus`, `list_goals`, `grade_and_record`, `record_attempt`, `review_ai_usage`, `record_bug_verdict`,
  `web_search`) and **omits** `read_github`, `read_resume`, `get_questions`, `add_question`, `save_baseline`,
  `save_artifact`, and `run_bash` (`mcp_server.py:24-77`). This is intentional (the host agent brings its own
  editor/shell/search), but it's an undocumented capability gap: an MCP host cannot draw from the curated
  question bank or ground onboarding in a résumé/GitHub the way the native agent can.
- **No surface builds the agent differently** in a way that changes safety posture. Backend
  (`build_backend`), interrupt gating (`interrupt_on run_bash`), and checkpointer are set once in `build_agent`.

---

## 4. Security

- **Multi-user isolation via contextvar:** ✅ solid. Every state reader goes through `config.paths()` /
  `db.connect()` (which resolves paths at call time, `db/store.py:38`). Verified: `tools.py`, `progress.py`,
  `report.py`, `chatstore.py`, `settings.py`, `resume.py`, `artifacts`, `assist.py`, `backups` all resolve
  through the contextvar. `test_isolation.py` proves per-user paths, ratings/XP, chats, settings, backups, and
  read-confinement. No module-level cached DB path leaks — the old constants are dynamic shims
  (`config.py:151-165`).
  - **One caching subtlety (not a leak):** `webapp.agents`, `chatstore._savers`, and `chatstore._readers` are
    **keyed by user id / checkpoints-path** (`webapp.py:127`, `chatstore.py:23,160`), so caches don't cross
    users. The agent's `build_backend` root_dir is captured at build time but is per-user because the cache key
    includes the uid — correct.
  - **Streaming context propagation:** the web agent stream runs inside the `StreamingResponse` async generator
    (`webapp.py:351`), which executes in the request context where `AuthMiddleware` bound the contextvar
    (`middleware.py:101`) — so tool DB access during streaming resolves to the right user. `/api/run`,
    `/api/assist`, `/api/truncate`, `/api/upload-resume` use `run_in_threadpool`, which **copies the context**
    (documented, `config.py:130-135`). No manually-spawned threads bypass this in the web path. ✅
- **`run_bash` gating:** ✅. Approval interrupt (`agent.py:92`), denylist regex (`tools.py:281`), secret-scrubbed
  child env (`tools.py:298`), 60s timeout, workspace cwd, pre-run snapshot. MCP has no `run_bash` at all.
- **Per-user read confinement (`workspace._is_forbidden`):** ✅. Workspace always allowed; `.env` always denied;
  anything under the home (backups/checkpoints) denied; **multi-user denies everything outside the user's own
  tree** (`workspace.py:48-52`); single-user reads host minus secret dirs. `is_relative_to` (not prefix
  string) blocks the `workspace-evil` sibling bypass (`workspace.py:42`), and `test_isolation` covers it.
- **Thread ownership:** ✅. `_require_owner` → `owns_thread` on every thread-scoped web route
  (`webapp.py:140`, used by `/api/stream`, `/api/resume`, `/api/truncate`, `/api/assist`, `/api/chats/*`).
  Returns **404 not 403** to avoid confirming a foreign thread exists. No-op in single-user. Covered by
  `test_webapp_returns_404_for_foreign_thread`.
- **Web XSS in `_INDEX` rendering of agent output:** ✅ handled. All model output is rendered through
  `DOMPurify.sanitize(marked.parse(...))` (`webapp.py:1764`, streaming `:1836`; artifacts `:1399-1403`).
  DOMPurify + marked are loaded (`webapp.py:1243-1244`). Trace/tool text uses `textContent`. The one
  `art-html` artifact path sanitizes with default profile; `art-viz` uses the SVG profile deliberately.
  No unsanitized `innerHTML` of model/user text found.
- **Secrets:** ⚠️ **flag, not a tracked-file leak.** `.env` at the repo root contains **live API keys**
  (GLM/MiniMax/Qwen/Kimi) and `EKLAVYA_SECRET_KEY`. It is **not** tracked (this dir is not a git repo yet) and
  **is** listed in `.gitignore` (`.gitignore:2`), and `.env.example` is placeholder-only. **Action before this
  becomes a git repo / before any push:** confirm `.env` never gets force-added, and treat these keys as
  live — they are real, high-value secrets sitting in a plaintext file (mode 0600). No secret appears in any
  `.py` source. `run_bash` scrubs `*KEY*/*TOKEN*/*SECRET*` from the child env so the model can't exfiltrate
  them (`tools.py:298`).

---

## 5. Logical Inconsistencies / Bugs

- **P1 — `session_context_line` web-only** (see §2b). The headline temporal-awareness feature is silently
  absent on CLI/TUI/MCP. This is the single most impactful consistency bug: same "one app," different sense of
  time depending on surface.
- **P1 — session `mode` label mismatch: `guided` vs `practice`** (see §2c). `cli.py:162` and the TUI
  (`cli.py:203`) open practice sessions **without a mode**, so `start_session` stamps them `"guided"`
  (`progress.py:219` default), while the web stamps `"practice"`. The dashboard's `recent_sessions` and any
  mode-based analytics will show two different labels for the identical activity.
- **P1 — `aiinterview` has no terminal entry point + `mark_interview` never called off-web** (see §1 P1-A).
  Resuming an `aiinterview` chat from the CLI (`cli.py:243`) rebuilds the agent with the interview prompt/tools
  but never calls `assist.mark_interview`, so `review_ai_usage`/`record_bug_verdict` operate on whatever
  `interview_thread` pointer was last set (possibly a *different* thread) — wrong-scope grading.
- **P2 — `_mode_agent` duplication acknowledged in-code.** `cli.py:234` mirrors `webapp._PROMPTS`/`_TOOLS` with
  a `# (Temporary duplication with webapp; #40 unifies the agent across interfaces.)` note. Two mode→(prompt,
  tools) tables that must be kept in sync; already a latent drift risk (the mode-specific tool aliases are all
  the same list, so it happens to be harmless today).
- **P2 — MCP `record_attempt`/`grade_and_record` write into a stale/NULL `session_id`** (see §2d).
- **P2 — `assist.respond` ignores the user's provider preference.** `assist.py:142` builds its model from
  `config.DEFAULT_PROVIDER` directly, not `_active_provider()`/the fallback chain. If the default provider is
  down, the in-interview AI assistant fails (returns "unavailable") even when the user has a working provider
  configured. `verify.selfcheck` similarly pins to a non-default provider (`verify.py:127`) — but that's a
  deliberate anti-self-bias choice, not a bug.
- **P2 — TUI cannot resume/list chats.** Every TUI launch mints a fresh thread (`cli.py:188 new_thread()`), so
  the "persistent chats" pillar that the CLI and web share is inaccessible from the immersive surface, even
  though the chat is registered in history (`cli.py:191 touch_chat`).
- **No crashing error paths found** in the reviewed surfaces: `run_turn` and `_events` both wrap the model call
  and fail soft; `selfcheck`, `ground_docs`, `maybe_autorefresh`, `web_search`, résumé/GitHub intake are all
  fail-open. No unset-contextvar code path found on the web surface (middleware binds it before any app route;
  single-user leaves it unset by design, which `paths()` handles).

---

## Prioritized Fix List

**P0 (breaks users):** none found. All 260 tests pass; no crash paths; isolation and XSS are sound.

**P1 (real bug / parity gap):**
1. **Inject `session_context_line()` on every surface**, not just web. Move the prepend into the shared turn
   path — `chat.run_turn` (`chat.py:33`, covers CLI + TUI `make_responder`) and `tui.make_stream_responder`
   (`tui.py:412`). Also call `maybe_autorefresh()` there for the TUI. Removes the temporal-awareness (#59)
   inconsistency in one place.
2. **Fix the session `mode` label.** Pass `mode="practice"` from `cli.py:162` and from the TUI launch
   (`cli.py:203`), or change `start_session`'s default from `"guided"` to `"practice"`. Align CLI/TUI/web
   labeling.
3. **Give `aiinterview` a CLI command** (`eklavya aiinterview`) that calls `assist.mark_interview(thread)` like
   the web does (`webapp.py:342`), OR explicitly document it as web-only and drop it from `_mode_agent` resume
   to avoid mis-scoped grading.

**P2 (polish / by-design gaps to document):**
4. Let the TUI select mode (mock/takehome/aiinterview) and list/resume chats, so it isn't a practice-only shell.
5. Have MCP open/reuse a session (call `ensure_session`) before `record_attempt`/`grade_and_record`, so MCP
   attempts don't inherit a stale `session_id`.
6. Point `assist.respond` at `_active_provider()` + the fallback chain instead of `config.DEFAULT_PROVIDER`.
7. Unify the `_mode_agent`/`_PROMPTS` tables (issue #40 already noted in code) to kill the CLI↔web duplication.
8. Document the intentional MCP tool subset and the CLI/TUI absence of dashboard/journey/forest/canvas viewers.
9. Confirm `.env` (live keys + secret) is never staged when this directory becomes a git repo; rotate keys if
   the file has ever been shared.
