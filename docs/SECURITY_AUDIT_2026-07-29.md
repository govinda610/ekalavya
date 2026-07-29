# Ekalavya — Security Audit (2026-07-29)

> Scope: `main` (shipping single-user baseline) + the in-flight multi-user branches
> `feat/multiuser-isolation` (contextvar isolation — landed) and `feat/multiuser-auth`
> (argon2 + signed-cookie sessions + login throttle — in progress). Target deployment:
> 2–3 trusted users on an AWS Lightsail VPS behind public HTTPS, signup disabled, accounts
> via CLI. Also stays open-source for single-user local self-host.
>
> Audit method: full read of `config.py`, `webapp.py`, `workspace.py`, `tools.py`,
> `sandbox.py`, `chatstore.py`, `auth.py`, `middleware.py`, `db/store.py`, `backups.py`,
> `assist.py`, `providers.py`, `report.py`, `profileview.py`, `dashboard.py`, `cli.py`,
> `mcp_client.py`, `agent.py`, `settings.py`, `docs/MULTIUSER_DEPLOYMENT_PLAN.md`, plus
> `tests/test_auth.py`/`test_isolation.py`; git-history and working-tree secret scans;
> and small reproductions of the env-scrub regex and path-prefix checks.
>
> **No application code was modified in producing this report.** This file is the only write.

---

## Executive summary

The single-user local path is in good shape: no secrets are committed or in git history,
`.env` is git-ignored, the env-scrub on `run_bash` catches the important provider/cloud
key names, `run_python` grading uses a genuinely isolated subprocess (clean env, throwaway
cwd, CPU + wall limits), all HTML sinks route model/DB strings through `html.escape` or
DOMPurify, and every SQL query is parameterized. For a single user running against their
own box and their own keys, the current posture is acceptable — matching the owner's stated
"full-capability `run_bash`, gated" intent.

The multi-user work is thoughtfully designed. The contextvar isolation, the per-user
DB/checkpointer/saver/agent caches keyed correctly, the `owns_thread`/`_require_owner`
404-not-403 guard, argon2id hashing with a dummy-verify timing defense, fail-loud secret
key, and `HttpOnly`+`SameSite=Strict`+`Secure` cookies are all correct and well-tested.

**However, two structural items from the plan's own §6.3 are NOT yet implemented and are
hard gates before any exposure beyond `127.0.0.1`:**

1. **The agent's read filesystem backend is still rooted at `Path.home()`** (`workspace.py:81`).
   On a shared host this lets any logged-in user read **other users' workspaces, other users'
   checkpoint DBs, and the shared `users.db` containing argon2 password hashes** — via the
   ordinary deepagents `read_file`/`glob`/`grep` tools, with **no approval gate** (only
   `run_bash` is interrupt-gated). This is a cross-tenant data breach independent of `run_bash`.
2. **`run_bash` has no jail** (bubblewrap #49 deferred). `shell=True` with only a
   trivially-bypassable denylist and an env-scrub means a user (or the model) can read
   `~/.ssh`, other users' data, and exfiltrate over the network. The env-scrub stops
   `echo $X_API_KEY` but does **not** stop `cat`-ing a key file (e.g. the `.env`, another
   user's files), so provider keys can still leak into model context / the transcript that way.

For the **private 2-user stage specifically** (both users trusted, IP allow-list, signup
off), the plan's decision to defer bubblewrap is defensible — the realistic threat is a
trusted user harming their own box. But finding #1 (cross-user reads) is **not** covered by
"trusted users" reasoning: it lets one trusted user silently read the other's private data
and the password-hash DB, which violates isolation goal (b). It should be fixed before two
real users share the box, and it is cheap (re-root the read backend + fix the forbidden-path
boundary).

No Critical issues exist on the single-user `main` baseline. The Criticals below are all
multi-user / public-exposure items.

---

## Findings

| # | Sev | Area | Location | Impact (one line) | Fix |
|---|-----|------|----------|-------------------|-----|
| F1 | **Critical** (multi-user) | Cross-tenant read | `workspace.py:81` (`root_dir=str(Path.home())`) | Any logged-in user's agent can `read_file`/`glob`/`grep` other users' workspaces, checkpoint DBs, and the shared `users.db` (argon2 hashes) — no approval gate on these tools. | Gate on `config.MULTIUSER`: root the read backend at the **current user's own home** (`config.paths().home`), not `Path.home()`. Do this before two real users share the box. |
| F2 | **Critical** (public) | Sandbox escape / host + tenant compromise | `tools.py:284-321` (`run_bash`, `shell=True`) | Denylist is trivially bypassable (`python -c 'import os;os.system(...)'`, base64, `$HOME` vars, reverse shells); nothing confines the process to the workspace → read `~/.ssh`, other users' dirs, network exfiltration. | Implement bubblewrap jail (#49) with FS + `--unshare-net` confinement; fail-closed startup gate (`EKLAVYA_JAIL=1` + `bwrap` present) before any non-loopback bind. Acceptable to defer ONLY for the private 2-user stage per plan §0.5(4). |
| F3 | **High** (multi-user) | Secret leak via file read | `tools.py:308-312` + `workspace.py` | Env-scrub blocks `echo $..._KEY` but NOT `cat`-ing key files. `run_bash cwd=workspace`, but read tools + `run_bash` can still reach any readable file. Combined with F1, provider keys in `.env` and other users' secrets can enter model context/transcript. | Confine reads (F1) + jail `run_bash` (F2). Additionally consider forbidding reads of the project `.env` regardless of cwd (already partly done: `_is_forbidden` blocks `name==".env"`, but `run_bash` bypasses the backend entirely). |
| F4 | **High** (public) | Missing forbidden-path for other tenants | `workspace.py:34-47` (`_is_forbidden`) | The forbidden set covers the *current* user's home and `~/.ssh`/`.aws`/etc under `Path.home()`, but NOT sibling users' homes under `$EKLAVYA_DATA_ROOT/users/<other>`. So even with reads "broad", other tenants aren't denied. | When F1 re-roots the backend per-user this is moot for reads; keep an explicit deny for anything under `data_root()` outside the current user's home as defense-in-depth. |
| F5 | **Medium** | Path-prefix boundary bug | `workspace.py:40,44,47` (`str.startswith` on paths) | `startswith` matches sibling dirs sharing a name prefix (`/…/workspace-evil` passes the `/…/workspace` check; `/…/alice2` passes an `/…/alice` home check). Lets a crafted path slip past confinement/forbidden checks. | Compare on resolved `Path` boundaries (`Path.is_relative_to`) or append `os.sep` before `startswith`. Applies to the workspace-allow, home-forbidden, and `_FORBIDDEN` checks. |
| F6 | **Medium** | Env-scrub misses some sensitive vars | `tools.py:311` (`KEY\|TOKEN\|SECRET\|PASSWORD\|CREDENTIAL`) | Verified coverage of AWS_*, OPENAI_*, ANTHROPIC_*, provider keys, EKLAVYA_SECRET_KEY (all contain KEY/TOKEN/SECRET). Misses `DATABASE_URL`, `REDIS_URL`, `SENTRY_DSN`, `MYSQL_PWD`, `AWS_PROFILE/REGION`. Low value today (none set), but `DATABASE_URL`/`MYSQL_PWD` can carry creds. | Add `URL`, `PWD`, `DSN`, `CONN` to the pattern, or (better) switch `run_bash` to an **allow-list** env (like `sandbox._CLEAN_ENV`) once jailed — deny-by-default beats scrub-by-pattern. |
| F7 | **Medium** (public) | Verbose error leakage to client | `webapp.py:186` (`{"t": f"\n\n_(error: {exc})_"}`), `assist.py:112` (`f"...unavailable right now: {exc}"`) | Raw exception text (which may include provider URLs, internal paths, key-not-configured provider names, stack-ish detail) is streamed to the browser. | Log the exception server-side; send a generic "something went wrong" to the client. Keep the detailed message only in single-user/local dev. |
| F8 | **Low/Info** | Session cookie has no server-side revocation | `middleware.py` (signed cookie, no sessions table — plan §0.5) | Logout only clears the client cookie; a stolen/leaked cookie stays valid until `max_age` (14d). Acceptable for 2 trusted users per the plan's explicit simplification. | Fine for the private stage. If ever public, add a revocation/`token_version` check. Consider shortening `COOKIE_MAX_AGE`. |
| F9 | **Low** | Login throttle is per-process, in-memory, resets on restart | `auth.py:129-161` | A restart clears lockouts; a multi-worker deploy wouldn't share counts. Bypassable by forcing restarts or spreading across workers. | Acceptable for single-worker 2-user box (plan §0.5(3)). Run uvicorn single-worker in prod; note this in the runbook. If scaled, move to a shared store. |
| F10 | **Low** | No password-strength check beyond length ≥10 | `auth.py:59` | Accepts weak long passwords (e.g. `aaaaaaaaaa`). Low risk given signup-disabled + IP allow-list + throttle. | Optional: reject a small common-password list at `adduser` time. |
| F11 | **Low/Info** | Client-generated `thread_id` trusted as identifier | `webapp.py:212`, JS `crypto.randomUUID()` | Ownership is enforced (`owns_thread`) + per-user checkpointer, so this is contained. A brand-new unknown `thread_id` is allowed (correct — caller owns it on first touch). No fix needed; noted for completeness. | None. Design is sound. |
| F12 | **Low** | CSRF relies solely on `SameSite=Strict` (no tokens) | `middleware.py`, all mutating routes | Plan §0.5(2) drops CSRF tokens. `SameSite=Strict` + same-origin JSON `fetch` is adequate for these routes and modern browsers. Residual risk: very old browsers ignoring SameSite. | Adequate for the private stage. If ever embedding/cross-site is needed, add a double-submit token. Add `X-Frame-Options: DENY`/CSP (Caddy already sets `X-Frame-Options DENY` in the plan — verify it ships). |
| F13 | **Info** | Third-party CDN scripts loaded without SRI | `webapp.py` `_INDEX`, `profileview.py` (marked, DOMPurify, mermaid, highlight.js, Monaco from jsDelivr) | A jsDelivr compromise could inject script into the app (the app relies on DOMPurify itself being intact to sanitize model output). Low likelihood, but DOMPurify is the XSS backstop. | Pin versions (mostly done) + add `integrity`/`crossorigin` SRI hashes, or vendor the scripts locally for the served deployment. |
| F14 | **Info** | Dependency versions — no pinned lower bounds on security-relevant libs | `pyproject.toml` | `argon2-cffi>=23.1`, `itsdangerous>=2.0`, `fastapi>=0.115`, `langchain*` are current/fine; no known-exploitable CVEs relevant to this app's usage were identified. `uv.lock` pins exact versions. | None blocking. Run `uv pip list --outdated` / `pip-audit` before publishing; keep `itsdangerous`/`argon2-cffi`/`fastapi` current. |

---

## Detail on the load-bearing items

### F1 — read backend rooted at `Path.home()` (cross-tenant read)

`workspace.build_backend()` (`workspace.py:80-83`) returns a `CompositeBackend` whose
**default** (everything outside `/workspace/`) is `ReadOnlyHost(root_dir=str(Path.home()))`.
In multi-user mode `Path.home()` is the **service account** home (e.g. `/var/lib/eklavya`
or `/home/svc`), which contains `$EKLAVYA_DATA_ROOT/users/<every-uid>/…` and the shared
`users.db`. `_is_forbidden` only denies the *current* user's own home subtree, `name==".env"`,
and `~/.ssh`/`.aws`/etc. It does **not** deny other users' homes (F4). Verified:
`/home/svc/.eklavya-data/users/B/workspace/eklavya.db` and `/home/svc/.eklavya-data/users.db`
are both *not* forbidden to user A.

These reads go through the deepagents floor tools (`read_file`, `glob`, `grep`) which are
**not** behind the `run_bash` approval interrupt — so it is a silent, unprompted read of
another tenant's data and the password-hash store. The deployment plan calls for exactly this
fix (§4.3, §6.3(3): "read-confined to the user's own tree… gate on `EKLAVYA_MULTIUSER`") but
neither branch implements it yet. This is the single most important pre-two-user change and
is small.

### F2/F3 — `run_bash` containment

`run_bash` is intentionally full-capability + approval-gated (owner's directive). The
containment analysis:
- **Denylist** (`tools.py:294-298`) blocks a handful of literal destructive patterns; it is
  not a security boundary (bypass via `python -c`, subshells, encodings).
- **Env-scrub** (`tools.py:311-312`) is a real, useful mitigation for `echo $KEY`-style
  exfiltration and covers the important names (F6 lists the gaps). It does **not** stop
  reading secrets from **files** (`.env`, other users' files) — which is why F1's read
  confinement and a real jail matter.
- **`cwd=workspace`** does not confine anything; absolute paths and `..` in the *command*
  (as opposed to the backend-mediated file tools) reach the whole FS.
- **Approval** protects the approving user's own understanding, not the host or other tenants.

For the **private 2-user stage**, deferring bubblewrap is acceptable per plan §0.5(4). Before
any public/untrusted exposure, the bubblewrap jail + fail-closed `EKLAVYA_JAIL` startup gate
(plan §6.3) is mandatory.

### Auth design review (`feat/multiuser-auth`) — concrete must-haves

Already correct (keep): argon2id via `argon2-cffi` defaults; dummy-verify on missing user
(`auth.py:90-97`) for timing; email lowercased + uniqueness; password ≥10; **fail-loud**
`EKLAVYA_SECRET_KEY` at app construction (`webapp.py:333`, `middleware.py:38-45`) with no
hardcoded default; cookie `HttpOnly`+`SameSite=Strict`+`Secure` (toggleable only via explicit
`EKLAVYA_INSECURE_COOKIES=1` for local http); `TimestampSigner` with `max_age` enforced;
unauth app route → 303 `/login`, unauth `/api/*` → 401; logout clears cookie; signup route
does not exist (accounts only via `adduser` CLI) — no-signup is enforced by absence, good.
Tests cover all of these plus cross-user thread 404 and throttle lockout.

Must-haves to close before the auth phase ships:
1. **Session fixation:** login issues a fresh signed cookie (good). Ensure no pre-login cookie
   value is honored post-login — since the cookie *is* the identity and is re-signed on login,
   this is satisfied; just don't add a server-side session id that survives login.
2. **`request.client.host` for throttle/IP** (`webapp.py:344`): behind Caddy this will be the
   proxy IP unless `X-Forwarded-For` is trusted. Decide deliberately — either key throttle on
   email only, or configure uvicorn `--proxy-headers` + trusted hosts so per-IP is real. As-is,
   all users may share one IP (the proxy), making the per-IP part of the throttle a per-email
   throttle in practice (acceptable, but know it).
3. **Generic login error** (already done — "Invalid email or password", no enumeration). Good.
4. **Single uvicorn worker** in prod so the in-memory throttle (F9) is coherent; document it.
5. Confirm Caddy sets `Strict-Transport-Security`, `X-Frame-Options: DENY`, `X-Content-Type-Options`
   (present in the plan's Caddyfile — verify it actually ships) since the app sets no security
   headers itself.

### Isolation correctness (`feat/multiuser-isolation`)

The contextvar approach is implemented correctly at the points reviewed:
- `config.paths()` is contextvar-aware; module constants are dynamic shims (`config.py:138-152`).
- `db.connect()`, `chatstore.get_checkpointer()`/`_reader_agent()`, `backups._state_files()`,
  `settings._path()`, `tools.read_profile/save_profile` all resolve via `config.paths()` at
  call time — no stale value-binding imports remain in the audited code.
- `webapp.agents` keyed by `(uid, mode)` (`webapp.py:82-86`); `chatstore._savers`/`_readers`
  keyed by the resolved checkpoints path — correct per-user caching.
- `owns_thread`/`_require_owner` enforce ownership with 404 (not 403); thread routes call it.

Two residual risks to watch (both flagged in the plan's own risk register):
- **Background/raw threads must copy context.** `config.run_user_task()` exists for this, but
  it is only useful if every off-loop dispatch uses it or Starlette's context-copying
  `run_in_threadpool`. The streaming turn (`/api/stream` → `_events` → `agent.stream`) currently
  runs the blocking generator **on the event loop** (plan §5.1 not yet done); when moved to a
  worker, it MUST use a context-copying primitive or the wrong user's home leaks. Add the t2
  propagation test when P1 lands. (Not a bug today, but a trap for the concurrency phase.)
- **`profileview.read_profile/write_profile` still reference `config.PROFILE_PATH`**
  (`profileview.py:18,24`). That resolves through the shim (contextvar-aware), so it is correct
  today — but it relies on the shim; prefer `config.paths().profile` for consistency with the
  rest of the refactor.

### Data safety (backups / migration)

- `backups.py` snapshots (db + profile + checkpoints, with WAL/SHM sidecars) and
  `snapshot_if_changed` before each `run_bash` are a solid safety net; `revert` snapshots
  first (undoable). Per-user via `config.paths()`. Good.
- **`_migrate_home_to_workspace` MOVES (renames) files** (`db/store.py:22-28`), not copies —
  but only when the destination doesn't exist (idempotent) and only for a legacy layout. The
  migration is guarded and reversible-in-practice, but note it deviates from the "copy-not-move"
  principle in issue #51; since it's move-if-absent it won't destroy an existing workspace DB.
  Confirm #51's copy-based user migration follows the copy rule when built.
- WAL is enabled and `busy_timeout=5000` is set in `connect()` — good for per-user contention.

### Secret handling — clean

- `.env` is git-ignored (`.gitignore:2`) and only `.env.example` is tracked (verified via
  `git ls-files`). `git log -p --all` and a name-only history scan show **no `.env` ever
  committed and no key-pattern lines added** in history. Working-tree grep for hardcoded
  `sk-…`/`AKIA…`/inline `api_key=`/passwords found nothing.
- Provider keys (`EKLAVYA_GLM/MINIMAX/QWEN/KIMI_API_KEY`) live only in `.env`, read via
  `os.environ` in `providers.py`; never logged, never returned in API responses, never written
  to `profile.md`/db/backups. The one place a key transits a URL is the Tavily MCP server URL
  (`mcp_client.py:26`, key as query param) and the legacy `web_search` POST body
  (`tools.py:523`) — both server-to-provider, not exposed to the client, but be aware the Tavily
  key sits in a URL that could appear in outbound request logs. `.env` value names were inspected
  with values redacted; no value is echoed anywhere.

---

## Prioritized action list

**Must fix before two real users share the Lightsail box (private stage):**
1. **F1/F4** — Re-root the agent read backend to the current user's own home in multi-user mode,
   and deny any path under `data_root()` outside that home. (Small, high-impact; closes the
   cross-tenant read + password-hash-DB read.)
2. **F5** — Replace `str.startswith` path checks with `Path.is_relative_to` (or `os.sep`-terminated
   prefixes) in `workspace._is_forbidden`.
3. **F7** — Stop streaming raw `{exc}` to the browser (`webapp.py:186`, `assist.py:112`); log
   server-side, return generic text.
4. Auth-phase must-haves: single uvicorn worker (F9), deliberate throttle IP handling behind
   Caddy, confirm Caddy security headers ship, confirm HSTS/`X-Frame-Options`.

**Must fix before any public / untrusted exposure (gate, per plan §6):**
5. **F2/F3** — Bubblewrap jail for `run_bash` **and** `run_python`, with `--unshare-net` default
   and FS confined to the user's `/workspace`; fail-closed `EKLAVYA_JAIL=1` startup precondition
   that refuses a non-loopback bind otherwise.
6. **F6** — Move `run_bash` to an allow-list env (deny-by-default) once jailed.
7. **F13** — Add SRI/vendor CDN scripts (DOMPurify is the XSS backstop).
8. Pre-publish: `pip-audit` / `uv pip list --outdated`; keep the `git grep`/history scan in the
   release checklist (currently clean).

**Fine for the private 2-user stage (documented, revisit if scaling/public):**
- F8 (no server-side session revocation), F9 (in-memory throttle), F10 (password strength),
  F12 (SameSite-only CSRF), F11 (thread_id design — already sound).

---

*End of audit. No application code was modified.*
