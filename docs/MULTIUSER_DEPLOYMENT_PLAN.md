# Ekalavya — Multi-User Hardening & Deployment Plan

> **Status:** PLAN ONLY. No application code has been modified. This document is the
> implementation contract for turning single-user Ekalavya into a secure two-user
> (→ N-user) app deployed privately on AWS Lightsail, while keeping a clean
> single-user open-source self-host path.
>
> Grounded in a full read of: `config.py`, `webapp.py`, `db/store.py`, `db/__init__.py`,
> `chatstore.py`, `workspace.py`, `tools.py`, `sandbox.py`, `mcp_client.py`,
> `settings.py`, `progress.py`, `report.py`, `assist.py`, `backups.py`, `agent.py`,
> `cli.py`, `providers.py`, `db/schema.sql`.

---

## 0. Executive summary

Ekalavya is architected around **module-level global paths** computed once at import
(`config.EKLAVYA_HOME/WORKSPACE/DB_PATH/PROFILE_PATH/CHECKPOINTS_PATH/BACKUPS_DIR`) and
a set of **process-global singletons** (`webapp.agents`, `chatstore._saver`,
`chatstore._reader`, `mcp_client._cached`, the `settings.json` path). Every state
function (`db.connect()`, `tools.*`, `progress.*`, `assist.*`, `backups.*`,
`workspace.build_backend`, `settings.*`) reads those globals directly. For a single
user this is clean; for two users it means **all state is shared** — one DB, one
profile, one checkpointer, one XP ledger — so concurrent use would silently
cross-contaminate and leak data.

**Chosen isolation mechanism: a `contextvar` holding the current user's home,** set by
auth middleware per request, read lazily by a *new* `config.paths()` accessor that every
state function calls instead of importing the module-level constants. This is the
least-invasive robust option (analysis in §3). It requires one structural change —
**config's constants become functions** — plus mechanical replacement of ~10 direct
imports and disciplined use at ~50 call sites.

The other four hard problems are addressed in dedicated phases: **per-user agents /
checkpointer / thread-ownership** (§4), **concurrency** (move blocking `agent.stream`
off the event loop, per-user savers, loop-safe MCP) (§5), **sandbox jailing** of
`run_bash` — the single hardest prerequisite before exposing beyond `127.0.0.1` (§6),
and **auth/session/CSRF** (§7). Deployment is a systemd + Caddy + Lightsail runbook
kept private by a firewall allow-list (§8). Open-source readiness is §9.

**The load-bearing risk is cross-tenant isolation.** A single missed call site that
reads the old global instead of the contextvar writes one user's data into another
user's file — silent corruption or leak. The test strategy (§11) is built to catch
exactly this with a concurrent two-user integration test that asserts zero bleed.

---

## 0.5 Simplicity decisions (AUTHORITATIVE — overrides the heavier options below)

Scope: **two trusted users (him + wife), a private link, plus open-source local self-host.**
Founder directive: no complexity without a clear benefit at *this* scope. Adopt the simpler
path unless/until the app is exposed to untrusted/public users. Simple, readable, debuggable.

**KEEP (needed, and already the simple choice):**
- Contextvar per-user home (§3 Option A) — one `config.paths()` accessor, not per-signature churn.
- Per-user data dirs + per-user agents/checkpointer/settings (§4).
- Thread-ownership check via `chats.user_id` (§4.5) — cheap; blocks cross-user chat access.
- Run the agent turn in a threadpool (§5.1) — required correctness/concurrency fix, small diff.
- SQLite-per-user (§5.4, no Postgres). Caddy + systemd + network allow-list (§8).
- Single-user self-host path unchanged (`EKLAVYA_MULTIUSER=0` default).

**SIMPLIFY (cut complexity that doesn't pay for itself here):**
1. **Sessions → signed-cookie only.** Use Starlette `SessionMiddleware` (signed cookie holding
   `user_id`); **DROP the server-side `sessions` table + opaque-token indirection** (§7.1/§7.3).
   Logout clears the cookie. (Add a revocation table only if server-side session-kill is ever needed.)
2. **CSRF → rely on `SameSite=Strict` + same-origin JSON `fetch` (no CORS).** **DROP the custom
   double-submit token + per-session `csrf_secret`** (§7.4). Our mutating routes are all
   same-origin `fetch` POST/PUT/PATCH; SameSite=Strict is sufficient. Revisit only for a real
   cross-site/embed need.
3. **Rate limiting → drop the `slowapi`/token-bucket dependency** (§7.6). Signup disabled +
   allow-listed + strong passwords makes it unnecessary for a private 2-user box. (Optional: a
   ~5-line in-memory login delay.)
4. **Sandbox → DEFER bubblewrap for the private 2-user launch** (§6). Both users are trusted;
   the realistic threat (a trusted user crafting a malicious `run_bash`) only harms their own box.
   Do the cheap structural wins instead: **confine the READ backend to the user's own tree** on the
   server (drop the read-broad host backend), keep `run_bash` approval-gated + env-scrubbed +
   `cwd=workspace`, + network allow-list. **KEEP bubblewrap as the documented, required "before you
   make the link public/untrusted" step — build it then, not now.** (One security tradeoff to confirm.)
5. **Agent cache → skip the speculative LRU cap** (§4.1) for 2 users; add only if going N-user.

Net: no sessions table, no CSRF-token plumbing, no rate-limit dep, no bubblewrap dep/wrapper at
launch, no speculative caches — a much smaller, simpler diff that's still correct and safe for two
trusted users on a private link, with a clear "harden here before public" checklist.

---

## 1. Current architecture (as read)

```
CLI (cli.py, typer)                      Web (webapp.py, FastAPI)         TUI (tui.py)
      │                                        │                              │
      └──────────────── build_agent (agent.py) ┴──────────────────────────────┘
                              │  create_deep_agent(model, tools, backend, checkpointer)
                              │
        ┌─────────────────────┼──────────────────────────────┬───────────────────────┐
   providers.py          workspace.py                    chatstore.py            tools.py
 build_chat_model    build_backend (CompositeBackend)  get_checkpointer()   record_attempt,
 (ChatAnthropic →    read-broad host + /workspace RW    _saver singleton     save_baseline,
  GLM/MiniMax)                                          _reader singleton    run_bash, ...
                                                                                  │
                                              ┌───────────────────────────────────┤
                                        db.connect() ──► DB_PATH (global)   sandbox.py
                                        progress.*, assist.*, report.*      run_python (subprocess,
                                        backups.*, settings.*                clean env, tmp cwd)
                                                                                  │
                                              config.py (module-level globals, computed at import)
                                              EKLAVYA_HOME / WORKSPACE / DB_PATH /
                                              PROFILE_PATH / CHECKPOINTS_PATH / BACKUPS_DIR
```

**Everything funnels through `config`'s globals.** That is the leverage point and the
danger point.

### Global / singleton state inventory (every one must change or be keyed per-user)

| # | Global / singleton | Where | Today | Multi-user requirement |
|---|---|---|---|---|
| G1 | `EKLAVYA_HOME` | `config.py:19` | one dir | per-user root `data/users/<uid>/` |
| G2 | `WORKSPACE` | `config.py:25` | one dir | per-user `.../workspace/` |
| G3 | `DB_PATH` | `config.py:26` | one file | per-user `.../workspace/eklavya.db` |
| G4 | `PROFILE_PATH` | `config.py:30` | one file | per-user `.../workspace/profile.md` |
| G5 | `BACKUPS_DIR` | `config.py:33` | one dir | per-user `.../backups/` |
| G6 | `CHECKPOINTS_PATH` | `config.py:34` | one file | per-user `.../checkpoints.sqlite` |
| G7 | `settings._PATH` | `settings.py:13` | one JSON | per-user `.../settings.json` |
| S1 | `webapp.agents` dict | `webapp.py:62` | keyed by **mode only** | keyed by `(uid, mode)` |
| S2 | `chatstore._saver` | `chatstore.py:21` | one SqliteSaver | per-user saver (cache keyed by uid) |
| S3 | `chatstore._reader` | `chatstore.py:116` | one reader agent | per-user reader (keyed by uid) |
| S4 | `mcp_client._cached` | `mcp_client.py:14` | one tool list | **safe to share** (stateless, no user data) — keep global |
| S5 | `assist` interview marker | stored in per-user `meta` table | already in DB | becomes per-user automatically once DB is per-user |

### Direct-binding import hazards (highest corruption risk)

These import the global **by value at module load**, so they will NOT see a contextvar
change unless refactored to call an accessor:

- `db/store.py:8` — `from ..config import DB_PATH, ensure_home` → `connect()` and
  `init_db()` default to this frozen `DB_PATH`.
- `tools.py:15` — `from .config import PROFILE_PATH, ensure_home` → `read_profile()` /
  `save_profile()` read/write the frozen `PROFILE_PATH`.
- `db/store.py:18` — `_migrate_home_to_workspace` re-imports globals inside the function
  (safer, but still single-user semantics).

Every other module (`backups.py`, `chatstore.py`, `profileview.py`, `verify.py`,
`settings.py`, `workspace.py`) uses the `config.X` *attribute* form, which a contextvar
accessor can intercept if we convert those attributes to functions.

**43 `connect()` call sites** across `tools.py`, `progress.py`, `assist.py`, `report.py`,
`repos.py`, `journey.py`, `dashboard.py`, `scheduling.py`, `verify.py`, `chatstore.py`
each rely on `connect()` defaulting to the right DB. Making `connect()` resolve the DB
from the contextvar fixes all 43 at once — the reason the contextvar approach wins.

---

## 2. Target architecture

```
                         Caddy (TLS, Let's Encrypt, HTTP→HTTPS)
                                        │  reverse proxy, private (firewall allow-list)
                                        ▼
        ┌──────────────────────  FastAPI app (uvicorn, systemd)  ──────────────────────┐
        │                                                                               │
        │  auth middleware ──► verify signed HttpOnly session cookie                    │
        │        │             load user_id ──► set current_user contextvar             │
        │        │             CSRF check on POST/PUT/PATCH/DELETE                       │
        │        ▼                                                                       │
        │  route handler ──► run_in_threadpool(agent turn)   ◄── agent no longer runs    │
        │        │                on the event loop (concurrency fix)                    │
        │        ▼                                                                       │
        │  config.paths()  reads contextvar ──► data/users/<uid>/{workspace,backups,...} │
        │        │                                                                       │
        │  per-user: DB, profile.md, checkpoints.sqlite, settings.json, agents, backups │
        └───────────────────────────────────────────────────────────────────────────────┘
                                        │
                          run_bash / run_python ──► SANDBOX JAIL (bubblewrap/nsjail)
                                        confined to that user's /workspace only
```

**On-disk layout (server, multi-user):**

```
$EKLAVYA_DATA_ROOT/                     # e.g. /var/lib/eklavya  (env: EKLAVYA_DATA_ROOT)
├── auth.db                             # SHARED users table (accounts, sessions) — see §7
└── users/
    ├── <uid-a>/
    │   ├── workspace/  eklavya.db  profile.md
    │   ├── backups/
    │   ├── checkpoints.sqlite
    │   └── settings.json
    └── <uid-b>/ ...
```

**Single-user self-host (open-source, unchanged UX):** no auth, one implicit user whose
home is `~/.eklavya` exactly as today. Achieved with a `EKLAVYA_MULTIUSER=0` (default)
flag: the contextvar is pre-seeded with the single home and no auth middleware is
mounted. The two code paths diverge only at app construction and the middleware.

---

## 3. Isolation mechanism: contextvar vs explicit-param (analysis + decision)

### Option A — `contextvar` holding the current user's home (CHOSEN)

Add to `config.py`:

```python
from contextvars import ContextVar

_current_home: ContextVar[Path | None] = ContextVar("eklavya_home", default=None)

def set_current_home(home: Path) -> None:
    _current_home.set(Path(home))

def _home() -> Path:
    h = _current_home.get()
    return h if h is not None else Path(os.environ.get("EKLAVYA_HOME", Path.home() / ".eklavya"))

def paths() -> "Paths":                      # small frozen dataclass of the six paths
    home = _home()
    ws = home / "workspace"
    return Paths(home=home, workspace=ws, db=ws / "eklavya.db",
                 profile=ws / "profile.md", backups=home / "backups",
                 checkpoints=home / "checkpoints.sqlite")
```

Every module calls `config.paths().db` etc. instead of reading a module constant.

- **Pros:** One change fixes all 43 `connect()` call sites and every `config.X` reader at
  once. No signature churn across ~15 modules and the tool functions (whose signatures
  are the LLM tool schema — adding a `user_id` param there would pollute the schema and
  confuse the model). `contextvars` propagate correctly into `run_in_threadpool` /
  `asyncio.to_thread` **when the context is copied** (Starlette's `run_in_threadpool`
  uses `anyio.to_thread.run_sync`, which copies the context — verified requirement, see
  §5). Matches the existing lazy-accessor style already used by `workspace.workspace_dir()`
  and `chatstore.get_checkpointer()`.
- **Cons:** Implicit — a reader must remember the contextvar exists. Any code that spawns
  a **raw `threading.Thread` or a bare `asyncio.create_task`** does NOT inherit the value
  unless we copy the context explicitly. Mitigation: forbid raw threads for agent work;
  centralize all off-loop execution in one helper that copies context (§5). The
  direct-binding imports (`db/store.py`, `tools.py`) must be refactored to accessor calls
  or they silently keep single-user behavior — this is the #1 audited risk.

### Option B — thread an explicit `user_id` / `home` parameter everywhere

Pass `home` (or a `Ctx` object) into `connect(home)`, `record_attempt(..., home)`,
`build_agent(..., home)`, etc.

- **Pros:** Explicit, statically greppable, no hidden state, trivially correct under any
  concurrency model.
- **Cons:** Enormous, invasive churn: ~43 `connect()` sites, all tool functions
  (`record_attempt`, `save_baseline`, `run_bash`, `read_profile`, …) — **and tool
  function signatures are the model-facing schema**, so every tool would need a hidden
  first arg that deepagents would try to expose to the LLM (requires wrapping each tool
  in a closure that injects `home` — itself a per-request agent rebuild). `progress.*`,
  `assist.*`, `backups.*`, `report.*` all grow a param. High risk of a **missed
  parameter defaulting to the global** — same failure mode as A but spread across 15
  files instead of 1 accessor.

### Decision

**Option A (contextvar).** It concentrates the risk into one place (`config.paths()` and
two import refactors) instead of scattering it across every signature, and it keeps the
LLM tool schema clean. The residual risk (raw threads not inheriting context) is real but
**bounded and centrally controllable**: we route every off-loop execution through a
single `run_user_task()` helper that does `contextvars.copy_context().run(...)`. Explicit
params would trade one well-understood risk for dozens of easy-to-forget ones.

---

## 4. Per-user agents, checkpointer, workspace, settings, thread ownership

### 4.1 Agents (`webapp.agents`, `webapp.py:62–70`)
- Change the cache key from `mode` to `(user_id, mode)`. `agent_for(user_id, mode)`.
- Each agent is built with that user's checkpointer (via the contextvar at build time)
  and that user's `build_backend()` (rooted at the user's `/workspace`).
- Bound cache: LRU-evict least-recently-used agents past a cap (e.g. 32) so N users don't
  grow memory unboundedly. For 2 users this is a non-issue; add the cap now for N-user.

### 4.2 Checkpointer (`chatstore._saver`, `chatstore.py:21–35`)
- Replace the single `_saver` with a **dict cache keyed by `user_id`** →
  `SqliteSaver(sqlite3.connect(config.paths().checkpoints))`. Same for `_reader`
  (`chatstore.py:116`).
- `get_checkpointer()` reads the contextvar, resolves the user's checkpoints path,
  returns (and caches) that user's saver.

### 4.3 Workspace (`workspace.build_backend`, `workspace.py:48–81`)
- `workspace_dir()` already reads `config.WORKSPACE`; convert to `config.paths().workspace`
  so it becomes per-user automatically.
- `_is_forbidden` compares against `config.WORKSPACE`/`config.EKLAVYA_HOME`; convert to
  `config.paths().workspace` / `.home`. **Critical:** the read-broad host backend
  (`root_dir=Path.home()`) must be replaced on the server (see §6) — on a shared host a
  user must NOT be able to read `Path.home()` of the service account or another user's
  dir.

### 4.4 Settings (`settings.py:13`)
- `_PATH` becomes `config.paths().home / "settings.json"`. `_load`/`_save` read it
  per-call (already do). The `death_on_cheat` toggle becomes per-user for free.

### 4.5 Thread-ownership (guessable-UUID risk) — **security-critical**
Today `thread_id` is a client-generated UUID (`webapp.py:186`, JS `crypto.randomUUID()`).
Any endpoint that takes a `thread`/`thread_id` (`/api/stream`, `/api/resume`,
`/api/assist`, `/api/chats/{thread_id}` GET/PATCH) trusts it blindly. In multi-user this
means **User B who learns/guesses User A's thread_id can read or resume A's chat.**

**Fix:** add a `user_id` column to the `chats` table (§10) and enforce ownership on every
thread-scoped request:
- On first touch (`touch_chat`), stamp `user_id = current user`.
- Before serving/resuming/renaming a thread, `SELECT user_id FROM chats WHERE thread_id=?`
  and 404 (not 403 — don't confirm existence) if it isn't the caller's.
- The checkpointer is already per-user (separate `checkpoints.sqlite`), so even a
  correctly-owned thread_id from another user resolves against the wrong DB and returns
  empty — but the DB-level ownership check is the primary, explicit guard.

---

## 5. Concurrency

### 5.1 The blocking-stream problem (`webapp.py:182–202`)
`/api/stream` is `async def` and iterates `agent.stream(...)` (a **synchronous**, blocking
generator that makes network calls to the model) **directly inside the event loop**. While
one user streams a turn, the single event loop is blocked → every other user's requests
stall. This serializes all users.

**Fix:** run each agent turn in a worker thread and bridge its output back to the async
response.
- Move the `_events(...)` generator body into a **sync generator** and drive it from the
  async handler via `starlette.concurrency.iterate_in_threadpool(...)` (or push chunks
  through an `asyncio.Queue` fed by a `run_in_threadpool` worker). `/api/run` and
  `/api/assist` already correctly use `run_in_threadpool` — extend the same pattern to
  streaming.
- **Contextvar propagation:** `run_in_threadpool` / `iterate_in_threadpool` use
  `anyio.to_thread.run_sync`, which **copies the current context** into the worker — so
  the `current_user` contextvar set by middleware is visible inside the agent turn.
  Verify with an explicit test (§11). For any manual thread we ever add, wrap the target
  in `contextvars.copy_context().run(fn)` via a single `run_user_task()` helper.

### 5.2 MCP tools calling `asyncio.run` inside a thread (`mcp_client.py:47–63`)
`_sync_wrap._run` does `asyncio.run(async_tool.ainvoke(...))`. `asyncio.run` **fails if a
loop is already running in that thread** and creates a fresh loop otherwise. Today the
agent runs on the event-loop thread (bad — see 5.1), so this can raise "asyncio.run()
cannot be called from a running event loop." Once agent turns run in a **worker thread
with no loop** (5.1 fix), `asyncio.run` there is safe — which is exactly the comment's
stated assumption ("the agent executes in a threadpool/worker with no running event
loop"). So **the MCP wrapper becomes correct precisely because we do the 5.1 fix.**
Add a defensive fallback: if `asyncio.get_running_loop()` succeeds, use a dedicated
loop/thread executor instead of `asyncio.run`.

### 5.3 SqliteSaver / SQLite concurrency
- Per-user SQLite files mean **no cross-user lock contention** — each user's DB and
  checkpointer are separate files. This is the main win for the 2-user case.
- Within one user, concurrent turns on the same DB can hit SQLite write locks. WAL is
  already enabled (`schema.sql:5`). Set a `busy_timeout` PRAGMA in `connect()` (e.g.
  5000ms) so brief contention retries instead of erroring. `SqliteSaver` is opened
  `check_same_thread=False` (`chatstore.py:32`) — keep that.

### 5.4 SQLite-per-user vs shared Postgres (2 → N)
| | SQLite-per-user | Shared Postgres |
|---|---|---|
| 2 users | **Ideal** — zero shared state, trivial ops, per-user backup = copy a folder | Overkill |
| ~dozens | Fine (files scale, backups are per-folder) | Fine |
| 100s–1000s concurrent | File-handle / fanout pressure; cross-user analytics hard | **Better** — pooling, one schema with `user_id` FK, row-level isolation |
| LangGraph checkpointer | `SqliteSaver` per file | `PostgresSaver` (official) with `thread_id` namespacing |

**Recommendation:** **stay SQLite-per-user for now** (2 users, and the open-source
self-host story is *inherently* SQLite/local). Design the DB access so a future Postgres
swap is a `connect()`-layer change: keep all SQL ANSI-ish, route every connection through
`db.connect()`, and add a `user_id` column to the multi-user `chats`/`auth` tables so a
future consolidation into one Postgres DB is mechanical. Do **not** adopt Postgres now —
it complicates the open-source local path for no current benefit.

---

## 6. Sandbox hardening — **hard prerequisite before any non-loopback bind**

### 6.1 What's exposed today
- `tools.run_bash` (`tools.py:281–318`): `subprocess.run(command, shell=True, ...)` with:
  - a **denylist regex** (`tools.py:291`) that is trivially bypassable (e.g.
    `python -c 'import os; os.system(...)'`, base64-decoded payloads, `rm -rf /$HOME` via
    a var, reverse shells not matching the pattern);
  - a **scrubbed env** (`tools.py:308–309`) — good, stops `echo $..._API_KEY`, but does
    not stop reading key files on disk;
  - `cwd = workspace_dir()` — but **nothing confines the process to it**: `cat
    ~/.ssh/id_rsa`, `curl` exfiltration, reading another user's `data/users/<other>/…`
    are all possible.
  - Human-in-the-loop approval (`interrupt_on run_bash`, `agent.py:57`) is a real
    mitigation for the *single* trusted user, but on a shared host the approving user is
    the attacker's victim's own account — it does not protect **the host** or **other
    tenants**, and the AI-interview/onboard flows can call tools too.
- `workspace.build_backend` read-broad host backend (`workspace.py:79`,
  `root_dir=Path.home()`) exposes the entire service-account home for **reads** (minus the
  `_FORBIDDEN` list) — on a shared host that includes other users' data dirs unless
  reworked.
- `sandbox.run_python` (`sandbox.py`) is the *good* citizen: clean env, throwaway cwd,
  CPU rlimit, wall timeout. But it is still **not a jail** (no filesystem/network
  namespace) — its own docstring says so ("process-level isolation, not a jail").

**Verdict:** As-is, on any host reachable beyond `127.0.0.1`, `run_bash` is a
host-compromise + cross-tenant read primitive. **Jailing is a gate, not a nice-to-have.**

### 6.2 Options (compare)
| Option | Confines FS | Confines net | Deps | Portable | Effort | Notes |
|---|---|---|---|---|---|---|
| **A. bubblewrap (`bwrap`)** | ✅ bind-mount only the user's `/workspace` rw, `/usr` ro, nothing else | ✅ `--unshare-net` | `bubblewrap` apt pkg, no daemon | Linux only | **Low–Med** | Rootless, per-call, minimal. **Recommended for Lightsail.** |
| B. nsjail | ✅ | ✅ | build/install nsjail | Linux only | Med | More knobs (rlimits, seccomp) than needed for 2 users. |
| C. firejail | ✅ profiles | ✅ | `firejail` apt pkg | Linux only | Low | Profile-based; slightly less precise than bwrap bind-mounts. |
| D. Docker-per-exec / gVisor | ✅ | ✅ | Docker/runsc daemon | Yes | High | Heaviest; conflicts with the repo's "no Docker" deploy ethos. |
| E. restrict-to-workspace + allow-list reads (no jail) | ⚠️ app-level only | ❌ | none | Yes | Low | Cheap but **defeated by any subprocess** the model spawns; insufficient alone for `shell=True`. |

### 6.3 Recommendation (layered)
1. **Keep `run_bash` behind human approval AND jail it.** On the server (Linux), execute
   the command via **bubblewrap** (Option A):
   - bind `--ro-bind /usr /usr`, `/bin`, `/lib*` read-only; `--bind
     <user>/workspace /workspace` read-write; `--tmpfs /tmp`; `--dev /dev`;
     `--unshare-all` then `--share-net` only if a task legitimately needs net (default:
     `--unshare-net`); `--die-with-parent`; drop the scrubbed env (already done).
   - `cwd = /workspace`. Nothing outside the user's workspace is visible → cross-tenant
     read is structurally impossible.
2. **Route `sandbox.run_python` / `run_tests` through the same jail** on the server (it's
   already the well-behaved path; add the bwrap wrapper so untrusted LLM code can't reach
   the FS either).
3. **Rework `workspace.build_backend` for the server:** the "read-broad host" backend must
   become **read-confined to the user's own tree** (root_dir = that user's home, not
   `Path.home()`), keeping the `_FORBIDDEN` deny for `.env` etc. The broad-read behavior
   is a *local-only convenience*; gate it on `EKLAVYA_MULTIUSER`.
4. **Provide a jail shim with a no-op fallback** so the **open-source local path stays
   dependency-free**: `sandbox.jail(cmd)` returns the bwrap-wrapped argv when
   `EKLAVYA_JAIL=1` and `bwrap` exists, else the current behavior. Server sets
   `EKLAVYA_JAIL=1`; local users run unjailed against their own machine (acceptable —
   it's their own box and own keys).

**Gate:** `EKLAVYA_JAIL=1` with `bwrap` present is a **launch precondition** checked at
startup in multi-user mode; refuse to bind to a non-loopback host otherwise (fail closed).

---

## 7. Auth, sessions, CSRF

Keep it minimal but correct. Email+password now; Google OAuth designed-for, not built.

### 7.1 Users store (shared `auth.db`, new module `auth.py` + `authstore.py`)
New `auth.db` (separate from per-user `eklavya.db`) with:

```sql
CREATE TABLE users (
    id            TEXT PRIMARY KEY,          -- uuid4, also the on-disk dir name
    email         TEXT NOT NULL UNIQUE,      -- stored lowercased
    password_hash TEXT,                      -- argon2id; NULL for OAuth-only (future)
    google_sub    TEXT UNIQUE,               -- reserved for Google sign-in (future); NULL now
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);
CREATE TABLE sessions (
    id            TEXT PRIMARY KEY,          -- opaque random 256-bit token id (not the cookie value itself)
    user_id       TEXT NOT NULL REFERENCES users(id),
    csrf_secret   TEXT NOT NULL,             -- per-session CSRF secret
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at    TEXT NOT NULL,
    revoked       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
```

### 7.2 Password hashing
- **argon2id** via `argon2-cffi` (preferred) — or bcrypt via `passlib` if a lighter dep
  is wanted. Add to a new `[project.optional-dependencies].server` group.
- Never log or return the hash. Enforce a minimum length (≥10) and reject the top common
  passwords list. Constant-time verify (library handles it).

### 7.3 Sessions & cookies
- On login: create a `sessions` row; the cookie carries a **signed** session token
  (`itsdangerous.TimestampSigner` or a signed JWT-lite) referencing `sessions.id`. Signing
  key = `EKLAVYA_SESSION_SECRET` (server env, 32+ random bytes; never in repo).
- Cookie flags: `HttpOnly`, `Secure` (TLS-only), `SameSite=Lax`, `Path=/`, sensible
  `Max-Age` (e.g. 14 days sliding). `Lax` still allows top-level GET navigation while
  blocking cross-site POST — combined with the CSRF token below.
- Logout: mark `sessions.revoked=1` and clear the cookie.
- Session lookup on each request → sets the `current_user` contextvar → `config.paths()`
  resolves that user's home. **This is the join point between auth and isolation.**

### 7.4 CSRF (all mutating routes)
Mutating routes today: `PUT /api/profile`, `PUT /api/settings`, `POST /api/stream`,
`POST /api/run`, `POST /api/resume`, `POST /api/assist`, `POST /api/penalise`,
`POST /api/reclaim`, `PATCH /api/chats/{id}`.
- **Double-submit + per-session secret:** issue a `csrf_token` (HMAC of `sessions.id`
  with `csrf_secret`) to the page; the client sends it in an `X-CSRF-Token` header on
  every POST/PUT/PATCH/DELETE; the server recomputes and compares (constant-time).
- With `SameSite=Lax` cookies + a required custom header (which browsers won't attach
  cross-site without CORS), this is defense-in-depth. Reject missing/invalid token with
  403.
- The single-page `_INDEX` (`webapp.py:284`) must be updated to read the token from a
  meta tag / cookie and attach the header in its `fetch()` calls. (Front-end change is in
  scope; the plan does not modify it here.)

### 7.5 Auth routes (new)
- `GET /login`, `GET /signup` (minimal HTML forms, same theme).
- `POST /api/signup` (email, password) → create user + user dir (`config` sets up
  `data/users/<uid>/`), auto-login. **Signup is gated** (see §7.7) so it's not open to
  the world.
- `POST /api/login` → verify, create session, set cookie.
- `POST /api/logout` → revoke + clear.
- `GET /api/me` → `{email}` for the header "who" display.

### 7.6 Rate limiting on auth
- Per-IP + per-email throttle on `/api/login` and `/api/signup` (e.g. 5 attempts / 15 min,
  exponential backoff / lockout). Implement with `slowapi` (Starlette-friendly) or a small
  in-memory token-bucket keyed by IP+email (sufficient for a 2-user private box; note it
  resets on restart — acceptable here). Return generic "invalid credentials" (no
  user-enumeration).

### 7.7 Keeping it private / two known users
- **Signup disabled by default** in production (`EKLAVYA_ALLOW_SIGNUP=0`). Seed the two
  accounts via a one-off admin CLI command `eklavya adduser <email>` (prompts for
  password, argon2-hashes, creates the user dir). This is how "him + his wife" get
  accounts without exposing public signup.
- Combined with the network allow-list (§8), the URL is private at two layers (network +
  no open registration).

### 7.8 Per-request authorization
- Every state route resolves data **only** via the contextvar-scoped `config.paths()` →
  a user can only ever touch their own DB/profile/workspace/checkpointer.
- Thread-scoped routes additionally enforce `chats.user_id` ownership (§4.5).
- No route accepts a `user_id` from the client — it comes **only** from the verified
  session. (Audit: grep for any handler reading `user_id`/`uid` from the body; there must
  be none.)

---

## 8. Lightsail deployment runbook (private)

Assumes an Ubuntu LTS Lightsail instance, a domain you control, and a subdomain like
`ekalavya.<yourdomain>`.

### 8.1 Provision
1. Create Lightsail instance (Ubuntu 22.04+, at least 1–2 GB RAM for the model client +
   bwrap execs). Attach a **static IP**. Point `ekalavya.<domain>` A-record → static IP.
2. Lightsail firewall (instance networking): allow **22 (SSH)** and **443 (HTTPS)** only.
   **80** only transiently for the ACME HTTP-01 challenge (or use DNS-01 and keep 80
   closed).

### 8.2 Keep it private (network allow-list)
- In the Lightsail firewall, **restrict 443 (and 22) to specific source IPs** — the two
  users' home/office IPs. This is the primary privacy gate.
- Belt-and-suspenders: Caddy `@allowed` matcher on `remote_ip` for the same IPs, plus HTTP
  Basic Auth at the proxy as an outer gate before the app's own login (optional; the app
  login already gates access). If IPs are dynamic, prefer a WireGuard/Tailscale private
  network and bind the app to the tailnet interface only.

### 8.3 System setup
```bash
sudo apt update && sudo apt install -y bubblewrap git curl
# uv (no system Python pollution)
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo useradd --system --create-home --home-dir /var/lib/eklavya --shell /usr/sbin/nologin eklavya
sudo -u eklavya git clone <repo> /var/lib/eklavya/app
cd /var/lib/eklavya/app
sudo -u eklavya ~/.local/bin/uv sync --extra agent --extra web --extra server
```

### 8.4 Secrets (server env only — never in repo)
Create `/etc/eklavya.env` (root-owned, `chmod 600`):
```
EKLAVYA_MULTIUSER=1
EKLAVYA_JAIL=1
EKLAVYA_DATA_ROOT=/var/lib/eklavya/data
EKLAVYA_SESSION_SECRET=<`openssl rand -hex 32`>
EKLAVYA_ALLOW_SIGNUP=0
EKLAVYA_GLM_API_KEY=<...>
# EKLAVYA_MINIMAX_API_KEY=<...>
# TAVILY_API_KEY=<...>
```

### 8.5 systemd unit `/etc/systemd/system/eklavya.service`
```ini
[Unit]
Description=Ekalavya tutor
After=network.target

[Service]
User=eklavya
Group=eklavya
WorkingDirectory=/var/lib/eklavya/app
EnvironmentFile=/etc/eklavya.env
ExecStart=/var/lib/eklavya/.local/bin/uv run eklavya serve --host 127.0.0.1 --port 4646 --no-open
Restart=on-failure
# hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/eklavya/data
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
```
> Note: `bwrap` needs user namespaces; if `NoNewPrivileges`/`ProtectSystem` conflict with
> bwrap on the host kernel, relax the specific directive after testing `run_bash` in the
> jail. Verify `eklavya serve` gains a `--no-open` flag / respects it in headless mode
> (today `serve` defaults `open_browser=True`; multi-user server must not try to open a
> browser — add `--no-open`, already present as `--no-open` per `cli.py:320`).

App binds **127.0.0.1 only**; Caddy terminates TLS and proxies to it.

### 8.6 Reverse proxy + TLS (Caddy — simplest)
`/etc/caddy/Caddyfile`:
```
ekalavya.<domain> {
    @allowed remote_ip <ip1> <ip2>       # network allow-list (optional 2nd layer)
    handle @allowed { reverse_proxy 127.0.0.1:4646 }
    respond "not available" 403
    encode zstd gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy no-referrer
    }
}
```
Caddy auto-provisions Let's Encrypt certs. (Nginx + certbot is the alternative if
preferred; Caddy is fewer moving parts.)

### 8.7 Seed accounts & launch
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now eklavya
sudo -u eklavya EnvironmentFile-equivalent... eklavya adduser him@example.com
sudo -u eklavya ...                              eklavya adduser her@example.com
```

### 8.8 Backups (server)
- Per-user data is `data/users/<uid>/` (self-contained). Nightly `tar`/`rsync` of
  `$EKLAVYA_DATA_ROOT` to Lightsail snapshots or an off-box target (encrypted). The app's
  own `backups.py` snapshots remain per-user under each user's `backups/`.
- Enable Lightsail automatic instance snapshots as a coarse safety net.

### 8.9 Preconditions before exposing (fail-closed checklist)
- `EKLAVYA_JAIL=1` and `bwrap` present (startup asserts this in multi-user mode).
- App bound to `127.0.0.1`; only Caddy faces the network.
- Firewall restricts 443/22 to allow-listed IPs.
- `npm`/build N/A (no JS build), but `uv run eklavya doctor` passes and providers
  configured.
- `EKLAVYA_SESSION_SECRET` set and strong; `EKLAVYA_ALLOW_SIGNUP=0`.

---

## 9. Open-source self-host (local, single-user)

Goal: `git clone`, add own key, run — no auth, no jail deps, identical UX to today.

### 9.1 Quickstart (README section)
```bash
git clone <repo> && cd eklavya
uv sync --extra agent            # + --extra web for the browser UI, --extra tui for the terminal UI
cp .env.example .env             # add your own EKLAVYA_GLM_API_KEY (or MiniMax) + optional TAVILY_API_KEY
uv run eklavya doctor            # verify Python, deps, provider
uv run eklavya                   # onboards on first run, else practice
uv run eklavya serve             # or the browser app at http://127.0.0.1:4646
```
- Default mode `EKLAVYA_MULTIUSER=0`: no login, single implicit user, home = `~/.eklavya`
  (exactly current behavior). `serve` stays bound to `127.0.0.1`.
- Jail optional: `EKLAVYA_JAIL=0` default locally (runs against your own machine with your
  own keys — the existing clean-env sandbox + approval remains).

### 9.2 What to add for a public repo
- `README.md` — already substantial; add a "Run locally (single user)" and "Deploy
  multi-user (private)" section pointing at this doc.
- `LICENSE` — MIT already present (`pyproject.toml:8`, `LICENSE` file). Confirm it's the
  intended license.
- `.env.example` — already present and clean; add the new server-only vars **commented
  out** with a note "server deployment only": `EKLAVYA_MULTIUSER`, `EKLAVYA_JAIL`,
  `EKLAVYA_DATA_ROOT`, `EKLAVYA_SESSION_SECRET`, `EKLAVYA_ALLOW_SIGNUP`.
- `docs/DEPLOY.md` — extract §8 into a standalone deploy guide.
- `docs/CONFIG.md` — table of every env var, default, and single-user vs server scope.
- `CONTRIBUTING.md` (optional) + a security note: "run locally against your own keys; the
  bash/code sandbox is not a jail unless `EKLAVYA_JAIL=1`."

### 9.3 Secret hygiene (confirm before publishing)
- `.env` is git-ignored (`.gitignore:2`) and **not** tracked (verified: `git ls-files`
  shows only `.env.example`). Good.
- `*.key`, `*.db`, `.eklavya/` are ignored — good.
- **Action before first public push:** `git log -p` / `git grep` scan for any historical
  key commit; if the repo has history with a leaked key, rotate the key and consider a
  history rewrite (`git filter-repo`) before making public. (Global rule #7.)
- `ROADMAP.md` / `CRITIQUE.md` are git-ignored (`.gitignore:23-24`) — keep internal notes
  out of the public repo, or move them under `docs/internal/`.

---

## 10. Schema / DB changes (exact)

### 10.1 New shared `auth.db`
Tables `users`, `sessions` as in §7.1 (new file `src/eklavya/authstore.py` owns them,
opened via a dedicated `connect_auth()` that resolves `$EKLAVYA_DATA_ROOT/auth.db`).

### 10.2 Per-user `eklavya.db` — `chats` table gets an owner
Additive migration in `db/store._migrate` (mirrors the existing `state_json` pattern at
`store.py:41–45`):
```sql
ALTER TABLE chats ADD COLUMN user_id TEXT;   -- NULL for legacy single-user rows
```
- Single-user/local: `user_id` stays NULL; no ownership enforcement (one user).
- Multi-user: `touch_chat` stamps `current_user`; thread routes enforce it (§4.5).
- Because each user has a **separate** `eklavya.db`, `user_id` here is defense-in-depth /
  future-Postgres-ready rather than the sole isolation boundary.

### 10.3 No change to the other tables
`pillars`, `ratings`, `attempts`, `goals`, `rewards`, `questions`, `ai_assists`, `meta`,
etc. remain **per-user by virtue of the per-user DB file** — no `user_id` columns needed
while we stay SQLite-per-user. (If we ever consolidate into one Postgres, every table
gains a `user_id` FK; noted for the future, not now.)

---

## 11. Per-file change list

| File | Change | Risk |
|---|---|---|
| `config.py` | Add `current_user` contextvar, `set_current_home()`, `_home()`, `Paths` dataclass, `paths()`; keep module constants as **deprecated shims** that call `paths()` (or remove and fix all readers). Add `EKLAVYA_MULTIUSER`/`EKLAVYA_DATA_ROOT` resolution + `user_home(uid)`. | **Highest** — the linchpin. |
| `db/store.py` | Remove `from ..config import DB_PATH` value-binding; make `connect()`/`init_db()` default to `config.paths().db`. Add `busy_timeout` PRAGMA. `connect_auth()` for `auth.db`. | High (43 callers depend on this). |
| `db/__init__.py` | Re-export `connect_auth` if added. | Low. |
| `chatstore.py` | `_saver`/`_reader` → per-user caches keyed by uid; `get_checkpointer()` reads `config.paths().checkpoints`. Add `user_id` stamping in `touch_chat`; ownership check helper `owns_thread(thread_id)`. | High. |
| `tools.py` | Remove `from .config import PROFILE_PATH` value-binding; `read_profile`/`save_profile` call `config.paths().profile`. Route `run_bash` (and `run_code`→sandbox) through the jail shim. | High (LLM tool schema must NOT change — no new params). |
| `sandbox.py` | Add `jail(argv)` bwrap wrapper (env-gated), wrap `run_python`/`run_tests`. | Med. |
| `workspace.py` | `workspace_dir()`/`_is_forbidden`/`build_backend` read `config.paths()`; server variant confines host read backend to the user's own tree (gate on `EKLAVYA_MULTIUSER`). | High (cross-tenant read). |
| `settings.py` | `_PATH` → `config.paths().home / settings.json`. | Low. |
| `backups.py` | `_state_files`/`BACKUPS_DIR` → `config.paths()`. | Med (must snapshot the right user). |
| `webapp.py` | `agents` cache keyed by `(uid, mode)`; mount auth middleware (contextvar set from session); CSRF check on mutating routes; thread-ownership checks on `/api/stream|resume|assist|chats/{id}`; move streaming turn off the event loop (§5.1); add `/login`,`/signup`,`/api/login|signup|logout|me`; update `_INDEX` to send CSRF header + show who. | **Highest** (auth + isolation + concurrency all here). |
| `mcp_client.py` | Defensive loop check in `_sync_wrap._run` (§5.2). `_cached` stays global (no user data). | Low. |
| `assist.py` | No structural change — uses `connect()` and per-user `meta`, so per-user for free. Verify `mark_interview`/`_current_interview` land in the right user's DB. | Low. |
| `cli.py` | Add `adduser` admin command; ensure `serve --no-open` used in server mode; local path unchanged (pre-seed contextvar with `~/.eklavya`). | Med. |
| `agent.py` | `build_agent` picks up per-user checkpointer/backend via contextvar at build time (called within request context). No signature change. | Med. |
| `providers.py` | No change (keys from env; shared). | None. |
| **NEW** `auth.py` | Signup/login/logout, password hashing (argon2), session issue/verify, CSRF token issue/verify, rate limiting. | New. |
| **NEW** `authstore.py` | `users`/`sessions` schema + queries on `auth.db`. | New. |
| **NEW** `middleware.py` | Starlette middleware: read cookie → verify session → set `current_user` contextvar → enforce CSRF on mutating methods. | New. |
| `pyproject.toml` | Add `[project.optional-dependencies].server = ["argon2-cffi", "itsdangerous", "slowapi"]`. | Low. |
| `.env.example`, `README.md`, `docs/DEPLOY.md`, `docs/CONFIG.md` | §9.2. | Low. |
| `db/schema.sql` (or migration) | `chats.user_id`; new `auth.db` schema. | Low. |

---

## 12. Phased plan (ordered, with effort & verify gate)

Effort in ideal engineer-days for one developer; assumes tests written alongside.

| Phase | Scope | Effort | Verify gate |
|---|---|---|---|
| **P0. Contextvar isolation core** | `config.paths()` + contextvar; refactor `db/store.py` & `tools.py` value-imports; convert all `config.X` readers to `paths()`; per-user `chatstore`/`settings`/`backups`/`workspace`. Single-user still default. | 2–3 d | All existing tests green; **new test:** two contextvar homes → two DBs, no bleed (§11 t1). |
| **P1. Concurrency** | Move streaming turn off event loop; per-user savers; MCP loop-safe fallback; `busy_timeout`. | 1.5–2 d | **Test:** two users stream concurrently, both complete, no serialization stall (timing), contextvar visible in worker (t2). |
| **P2. Sandbox jail** | `sandbox.jail()` bwrap shim; wrap `run_bash`/`run_python`; server read-confined backend; startup precondition (`EKLAVYA_JAIL` gate). | 2–3 d | **Test (on Linux):** `run_bash "cat ~/.ssh/id_rsa"` and cross-user read both denied; `run_python` FS escape denied; local no-jail path still works (t3). |
| **P3. Auth + sessions + CSRF** | `authstore.py`, `auth.py`, `middleware.py`; login/signup/logout routes; cookies; CSRF; rate-limit; `adduser` CLI; thread-ownership enforcement; `_INDEX` CSRF header. | 3–4 d | **Tests:** unauth → 401; wrong CSRF → 403; user B cannot read/resume user A's thread → 404; rate-limit trips (t4–t7). |
| **P4. Deploy** | Lightsail provision; systemd + Caddy + TLS; firewall allow-list; secrets; seed 2 accounts; backups. | 1–2 d | Live private URL reachable only from allow-listed IPs; both users log in; concurrent use works; `doctor` green on box. |
| **P5. Open-source polish** | README sections, `docs/DEPLOY.md`, `docs/CONFIG.md`, `.env.example` additions; secret-history scan; move internal notes. | 1 d | Fresh clone → `uv sync --extra agent` → `uv run eklavya` works with only a provider key; `git grep`/history shows no secrets. |

**Total:** ~11–15 engineer-days. P0→P2 are the security-load-bearing core; **P4 must not
ship before P2 and P3 pass** (fail-closed).

---

## 13. Test strategy

Extend the existing `pytest` suite (`tests/`, `asyncio_mode = "auto"`). Key new tests:

- **t1 Isolation unit** (`tests/test_isolation.py`): set contextvar to home A, write a
  profile + record an attempt; set to home B, assert B sees none of A's data; assert the
  files live in different dirs. Loop over `connect()`, `read_profile/save_profile`,
  `progress.award_xp/stats`, `backups.snapshot`, `settings` — each must land per-user.
- **t2 Concurrency** (`tests/test_concurrency.py`): two `TestClient`/httpx requests with
  distinct sessions hit `/api/stream` concurrently (mock the model to sleep); assert both
  return, assert the contextvar seen inside the worker equals the request's user (patch a
  probe into the turn), assert no wall-clock serialization.
- **t3 Sandbox** (`tests/test_jail.py`, skip if not Linux/`bwrap`): `run_bash`/`run_python`
  cannot read a file outside `/workspace` (create a decoy `~/secret`), cannot read another
  user's workspace; local no-jail mode still executes normally.
- **t4–t7 Auth** (`tests/test_auth.py`): signup→login→cookie set with HttpOnly/Secure/
  SameSite; mutating route without CSRF → 403; unauth mutating route → 401; user B GET/
  PATCH/POST-resume on user A's `thread_id` → 404; login rate-limit lockout after N tries;
  logout revokes session.
- **Regression:** the full existing suite (`test_webapp`, `test_chatstore`, `test_tools`,
  `test_mcp`, `test_backups`, …) must stay green with `EKLAVYA_MULTIUSER=0` (single-user
  path unchanged) — this is the guarantee the open-source UX doesn't regress.
- **CI matrix:** run once single-user (no auth), once multi-user (auth + two seeded users).

---

## 14. Risk register (prioritized)

| # | Risk | Sev | Likelihood | Mitigation | Owner gate |
|---|---|---|---|---|---|
| R1 | **Cross-tenant data bleed** — a missed call site reads the old global instead of the contextvar → one user's write lands in another's DB/profile. | **Critical** | Med (many call sites) | Convert config constants to functions so a stale read fails loudly; t1 isolation test over every state fn; grep audit for `config.DB_PATH`/`PROFILE_PATH`/value-imports; forbid raw threads (§5). | P0 gate. |
| R2 | **Sandbox escape / host compromise** via `run_bash shell=True` on a shared host. | **Critical** | High if unjailed | bwrap jail (§6); refuse non-loopback bind unless `EKLAVYA_JAIL=1`; read-confined backend. | P2 gate; blocks P4. |
| R3 | **Thread hijack** via guessable UUID (resume/read another user's chat). | High | Med | `chats.user_id` ownership check + per-user checkpointer; 404 on mismatch. | P3 gate. |
| R4 | **Session/CSRF weakness** — stolen or forged mutating request. | High | Med | HttpOnly+Secure+SameSite cookie, signed token, per-session CSRF, rate limit. | P3 gate. |
| R5 | **Contextvar not propagated** into a worker thread → wrong user or crash. | High | Med | Use only `run_in_threadpool`/`iterate_in_threadpool` (context-copying) or `copy_context().run`; t2 asserts propagation. | P1 gate. |
| R6 | **Public URL not actually private** (firewall misconfig). | High | Med | IP allow-list on 443/22 + signup disabled + app login; verify from a non-allowed IP. | P4 gate. |
| R7 | **Secret leaked in repo/history** when going public. | High | Low–Med | `.env` untracked (verified); pre-publish `git grep`/history scan; rotate if found. | P5 gate. |
| R8 | **Per-user SQLite write contention** within one user's concurrent turns. | Med | Low | WAL (already) + `busy_timeout`; agents serialized per thread anyway. | P1. |
| R9 | **Backups snapshot the wrong user** (backups.py reads globals). | Med | Med | Route `backups.py` through `config.paths()`; covered by t1. | P0. |
| R10 | **MCP `asyncio.run` in a running loop** raises. | Med | Med (until P1) | P1 moves agent to a loop-free worker; add defensive loop check. | P1. |
| R11 | **Open-source UX regresses** (auth/jail leaks into local path). | Med | Med | `EKLAVYA_MULTIUSER=0` default; single-user regression suite; jail no-op fallback. | P5. |
| R12 | Memory growth from unbounded per-user agent/saver caches at N users. | Low (2 users) | Low | LRU cap on agent/saver caches. | P1. |

---

## 15. Open questions for the founder (resolve before P3/P4)

1. **Dynamic IPs?** If the two users' IPs change, the firewall allow-list breaks — prefer
   Tailscale/WireGuard? (Changes §8.2.)
2. **Google sign-in timing:** confirm it's post-launch. Schema reserves `google_sub`; the
   OAuth callback route and `authlib` dep are deferred. OK?
3. **Signup policy:** confirm signup stays **disabled** in prod (accounts via `adduser`
   only). If they want to add a few friends later, we flip `EKLAVYA_ALLOW_SIGNUP=1` behind
   the IP gate.
4. **License:** confirm MIT is intended for the public repo.
5. **`run_bash` on the server:** keep it enabled (jailed + approval) or disable it entirely
   in multi-user mode for extra safety? (It's powerful; the AI-interview/onboard flows can
   invoke tools.) Recommendation: keep jailed + approval; revisit if unused.
6. **Region/instance size:** which Lightsail region (latency to the model API + to the two
   users) and RAM (bwrap execs + model client)?

---

*End of plan. No application code was modified in producing this document.*
