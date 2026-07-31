# Ekalavya — Security Audit (2026-08-01b)

> Scope: current working tree of the multi-user webapp before exposing it as a login-gated
> server with real accounts (owner + 1 test account) on localhost / a private VPS.
> Focus: multi-user isolation, auth, code execution, secrets, web.
>
> Method: full read of `config.py`, `workspace.py`, `webapp.py`, `tools.py`, `sandbox.py`,
> `auth.py`, `middleware.py`, `chatstore.py`, `artifacts.py`, `github.py`, `resume.py`,
> `assist.py`, `mcp_client.py`, `agent.py`, `db/store.py`; the vendored deepagents
> `CompositeBackend` + `FilesystemBackend`; git-history + working-tree secret scans; and a
> **live reproduction** proving the P0 below (script output inline).
>
> Cross-referenced against `docs/SECURITY_AUDIT_2026-07-29.md`; regression status of each
> prior finding is tracked in the table.
>
> **No application code was modified. This file is the only write.**

---

## Executive summary

Most of the prior audit's findings are genuinely fixed. `_is_forbidden` was rewritten to
use `Path.is_relative_to` (closing prior **F5**), the multi-user branch now denies any read
outside the current user's own tree (prior **F1/F4** intent), the read backend re-roots to
`config.paths().home` in multi-user (prior **F1**), raw exceptions are no longer streamed to
the browser (prior **F7** — `webapp.py:278-280`, `assist.py:143-145`), and the throttle now
handles the proxy IP deliberately (prior audit note 2, `webapp.py:53-71` + `EKLAVYA_TRUST_PROXY`).
Secrets remain clean: `.env` git-ignored, only `.env.example` tracked, nothing in git history
or the working tree. Auth (argon2id, dummy-verify, fail-loud secret, `HttpOnly`+`SameSite=Strict`+
`Secure` cookie, no signup route, CLI-only accounts) is sound. XSS is well-handled — every
agent/markdown sink routes through `DOMPurify.sanitize(marked.parse(...))`.

**But the prior **F1** fix is incomplete, and that reopens a P0 cross-tenant breach.** The
re-root and the `_is_forbidden` guard only protect the **`read_file`** tool. The agent's
other floor tools — **`ls`, `glob`, `grep`** (and `download_files`) — are inherited unchanged
from `FilesystemBackend` on the `ReadOnlyHost` default backend, which runs with
`virtual_mode=False`. Per deepagents' own docs, `virtual_mode=False` provides **no** path
confinement: absolute paths bypass `root_dir` entirely. `ReadOnlyHost` overrides only
`read`/`aread` to call `_is_forbidden`; it does **not** override `ls`/`glob`/`grep`. So in
multi-user mode the agent can `grep`/`glob`/`ls` any absolute path on the host — including
`$EKLAVYA_DATA_ROOT/users.db` (the argon2 password-hash store) and every other user's
workspace/DB — with **no approval gate** (only `run_bash` is interrupt-gated). This is a
silent, unprompted cross-tenant read of the password DB and other tenants' data. **Verified
by live reproduction** (below).

### Verdict

**Not safe to run for two real logged-in users as-is** — even both-trusted. The realistic
threat here isn't a malicious user; it's that the *model itself* (or a prompt-injected repo /
résumé / chat) issues a `grep`/`glob` over the data root and pulls another user's data or the
password-hash DB into the transcript, unprompted. That is a P0 isolation break, and it is the
single thing that MUST be fixed before the owner and a second account share the box.

- **Single trusted user on localhost (multi-user OFF):** safe now. This path is unchanged and
  the read backend intentionally spans your own `$HOME` minus secret dirs — that's the design.
- **Two users, multi-user ON, private VPS:** **fix N1 first** (below). N2–N4 are cheap and
  should ride along. After N1, the residual `run_bash` risk (no jail, prior F2/F3) is
  acceptable **only** because both users are trusted and signup is off — a trusted user can
  still trash their own box and read the host, but not the *other* tenant's data once N1 lands.
- **Any public / untrusted exposure:** additionally requires the deferred bubblewrap jail
  (#49, prior F2/F3) with `--unshare-net`, plus SRI on the CDN scripts.

---

## Regression status of the 2026-07-29 findings

| Prior | Status now | Evidence |
|---|---|---|
| **F1** cross-tenant read via read backend rooted at `Path.home()` | **PARTIALLY FIXED → REOPENED as N1.** Read backend re-rooted to `config.paths().home` in multi-user (`workspace.py:91`) and `_is_forbidden` denies out-of-tree reads for `read_file`. **But** `ls`/`glob`/`grep`/`download_files` bypass `_is_forbidden` and, with `virtual_mode=False`, escape the root on absolute paths → cross-tenant read of other users + `users.db` still possible. | `workspace.py:58-95`; deepagents `filesystem.py:143-147` (virtual_mode=False = no security); repro below |
| **F4** other tenants not in forbidden set | Effectively fixed for `read_file` (multi-user branch `_is_forbidden` returns True for anything outside the user's tree, `workspace.py:48-52`). Still bypassed by `ls`/`glob`/`grep` (see N1). | `workspace.py:48-52` |
| **F5** `str.startswith` path-prefix bug | **FIXED.** Now `Path.is_relative_to` throughout `_is_forbidden`. | `workspace.py:42,46,55` |
| **F7** raw `{exc}` streamed to client | **FIXED.** Stream handler logs server-side, sends generic text; assist returns generic string. | `webapp.py:278-280`; `assist.py:143-145` |
| **F2/F3** `run_bash` no jail / secret-file read | **NOT FIXED (deferred #49, by design).** Denylist + env-scrub unchanged (`tools.py:281-308`). Accepted for the private 2-user stage; mandatory before public. Env-scrub still can't stop `cat`-ing a key file, but N1's fix + trusted-only reduces the multi-user angle. | `tools.py:271-308` |
| **F6** env-scrub misses `URL`/`PWD`/`DSN` | **NOT FIXED.** Pattern still `KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL` (`tools.py:298`). Low value today. | `tools.py:298` |
| **F8** no server-side session revocation | Unchanged (accepted for private stage). Plus N4: a *deleted* user's still-valid cookie keeps access up to `COOKIE_MAX_AGE` (14d) — middleware never checks the uid still exists. | `middleware.py:95-109` |
| **F9** in-memory per-process throttle | Unchanged (accepted; run single-worker). | `auth.py:129-161` |
| **F10** weak-password acceptance (len ≥10 only) | Unchanged (accepted; signup off). | `auth.py:59-60` |
| **F11** client `thread_id` trusted | Unchanged — sound (ownership enforced). | `chatstore.py:78-96` |
| **F12** SameSite-only CSRF | Unchanged (accepted for private stage). No app-level `X-Frame-Options`/CSP — relies on proxy. | `middleware.py:60-67` |
| **F13** no SRI on CDN scripts | **NOT FIXED, slightly worse.** `marked` fully unpinned, `dompurify@3`/`mermaid@10` floating majors; DOMPurify is the XSS backstop. | `webapp.py:1243-1247,625` |
| **F14** dep pinning | `uv.lock` pins; run `pip-audit` before publishing. | `pyproject.toml:30-33` |

---

## New / active findings (this audit)

| # | Sev | Area | Location | Impact | Fix |
|---|-----|------|----------|--------|-----|
| **N1** | **P0 (multi-user)** | Cross-tenant read via `ls`/`glob`/`grep` | `workspace.py:58-95` (`ReadOnlyHost` overrides only `read`/`aread`); deepagents `CompositeBackend` routes non-`/workspace/` `ls`/`glob`/`grep` to that default backend, which is `FilesystemBackend(virtual_mode=False)`. | The agent's `grep`/`glob`/`ls`/`download_files` tools reach ANY absolute path on the host in multi-user mode, bypassing `_is_forbidden` — reading `$EKLAVYA_DATA_ROOT/users.db` (argon2 hashes) and every other tenant's workspace/checkpoint DB. **No approval gate** (only `run_bash` is gated). Model- or injection-triggered, silent. **Reproduced live.** | Override `ls`/`als`/`glob`/`aglob`/`grep`/`agrep`/`download_files`/`adownload_files` on `ReadOnlyHost` to reject any path failing `_is_forbidden` (and per-result filter grep/glob output); OR run the default read backend with `virtual_mode=True` rooted at the user's home in multi-user so `..`/absolute escapes are blocked at the backend. Either closes it. |
| **N2** | **P1 (multi-user)** | `_is_forbidden` not consulted by the same tools even single-user's secret-dir denial | `workspace.py:34-55` | Same root cause as N1: even in single-user mode, the `~/.ssh`/`.aws`/`.env` denials only apply to `read_file`. `grep`/`glob` can still read those secret files. Single-user = your own box, so lower impact, but it defeats the stated secret-dir protection and can surface your `.env`/keys into the transcript. | Fixed by the same override as N1 (apply the guard to all read-shaped ops, both modes). |
| **N3** | **P2** | No SRI + floating CDN versions | `webapp.py:1243-1247,625` | DOMPurify (the XSS backstop), marked, mermaid, hljs, Monaco loaded from jsDelivr with no `integrity=`; `marked` is unpinned. A CDN compromise or a bad `marked` release injects script / defeats sanitization. | Pin exact versions + add SRI hashes, or vendor into `/static`. Required before any public exposure; recommended now. |
| **N4** | **P2** | Deleted-user cookie still valid | `middleware.py:95-109` | `AuthMiddleware` binds `config.user_home(uid)` from a signature-valid cookie without confirming the uid still exists in `users.db`. A user deleted via CLI keeps access (to their own now-orphaned home) until the 14-day cookie expiry. Not a cross-tenant leak (uid is cryptographically bound), but revocation is impossible. | Cheap: in the middleware, after `read_uid`, call `auth.get_user(uid)` and reject (redirect/401) if None. Also lets you enforce account disable. |
| **N5** | **P2** | No app-level security headers | `webapp.py` (only `AuthMiddleware` added) | App sets no `X-Frame-Options`/CSP/`X-Content-Type-Options`/HSTS; entirely dependent on the reverse proxy shipping them. Clickjacking / MIME-sniff exposure if proxy config drifts. | Add a tiny middleware setting `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and a CSP; or verify+pin the Caddy/Nginx headers in the runbook. |

---

## Detail on the load-bearing item (N1)

`build_backend()` (`workspace.py:58-95`) builds:

```
CompositeBackend(
    default = ReadOnlyHost(root_dir=config.paths().home,  # multi-user
                           virtual_mode=False),
    routes  = {"/workspace/": FilesystemBackend(virtual_mode=True)})
```

`ReadOnlyHost` subclasses `FilesystemBackend` and overrides **only** `read`/`aread` (and
write/edit to deny). `read` calls `_is_forbidden` first — correct, and verified:

```
read_file /etc/hosts forbidden?: True
read_file $DATAROOT/users.db forbidden?: True
read_file own workspace forbidden?: False   # allowed, as intended
```

But `ls`, `glob`, `grep`, `download_files` are **not** overridden, so they run the base
`FilesystemBackend` implementations. Deepagents' own docstring
(`backends/filesystem.py:143-147`):

> When `False` (default), absolute paths are used as-is ... **This provides no security
> against an agent choosing paths outside `root_dir`.** Absolute paths (e.g. `/etc/passwd`)
> bypass `root_dir` entirely.

The deepagents floor exposes `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
tools that call `backend.ls/read/glob/grep` (`middleware/filesystem.py:983,1175,1445,1608`).
None but `read` is guarded. Live reproduction against `FilesystemBackend(virtual_mode=False)`
rooted at a fake user home, targeting a secret file OUTSIDE that home:

```
LS /etc exists?: True
GREP found secret outside root: [{'path': '/tmp/.../dataroot-.../users.db',
                                  'line': 1, 'text': 'PASSWORD_HASH_argon2id_secret_value'}]
GLOB found db outside root: ['/tmp/.../dataroot-.../users.db']
```

So in a 2-user deployment, either user's agent can `grep argon2 $EKLAVYA_DATA_ROOT` and read
the other user's password hash and data — no prompt, no gate. Only `run_bash` pauses for
approval; the file-search tools do not. This is the substance of prior F1, still open through
a different door. It is the one true blocker for two real users.

## What is genuinely fine

- **Isolation plumbing (contextvar):** `db.connect`, `chatstore.get_checkpointer`/`_reader_agent`
  (keyed per checkpoints path), `webapp.agent_for` (cache key `(uid, mode, provider)`),
  `artifacts`/`resume`/`profileview`/`settings`, `tools.*` all resolve via `config.paths()` at
  call time. No import-time or build-time home capture leaks across users. `read_file` reads,
  DB reads/writes, checkpointer, and per-user agent cache are correctly isolated.
- **Thread ownership:** `owns_thread`/`_require_owner` (404, not 403) enforced on stream,
  resume, truncate, assist, chat get/rename (`webapp.py`). Artifacts are isolated by the
  per-user DB (numeric ids are per-user), so no `_require_owner` is needed there — correct.
- **Auth:** argon2id defaults, dummy-verify timing defense (`auth.py:90-97`), generic login
  error (no enumeration), email uniqueness, fail-loud `EKLAVYA_SECRET_KEY` at construction
  (`middleware.py:39-46`, `webapp.py:580`), `HttpOnly`+`SameSite=Strict`+`Secure` cookie with
  `TimestampSigner` max-age, no signup route (CLI-only, `cli.py:360`), login throttle with a
  deliberate proxy-IP decision (`webapp.py:53-71`, `EKLAVYA_TRUST_PROXY` off by default).
- **Grading sandbox (`sandbox.py`):** clean env (`_CLEAN_ENV`, no inherited keys), `-I`
  isolated interpreter, throwaway cwd, `HOME`/`TMPDIR` redirected, `RLIMIT_CPU`+wall timeout,
  no core dumps. Solid process isolation for the learner's own code (not a jail — fine as-is
  for trusted; swap in bwrap for untrusted).
- **`read_github` SSRF:** host-locked to `github.com` via `_GH_HOST` regex; clones with hooks
  off, creds off, `GIT_TERMINAL_PROMPT=0`, clean env, size+time caps, deleted after; never
  executes fetched code. `web_search` hits only fixed Tavily/Serper endpoints (no user URL).
  No SSRF surface.
- **Secrets:** `.env` git-ignored (`.gitignore`), only `.env.example` tracked; git-history and
  working-tree scans clean; provider keys read from `os.environ`, never logged or returned.
  Tavily/Serper keys sit in provider request bodies/headers server-side only.
- **XSS:** all model/markdown output → `DOMPurify.sanitize(marked.parse(...))`
  (`webapp.py:1763-1764,1797,1836,1403`); code via `esc()`; HTML/SVG artifacts sanitized.
- **PDF résumé intake:** content-type + 8MB cap, text-only extraction (never executes),
  control-char strip, length cap, per-user workspace write (`resume.py`, `webapp.py:450-478`).

---

## Prioritized action list

**MUST fix before two real users share the box (multi-user private stage):**
1. **N1** — Guard `ls`/`glob`/`grep`/`download_files` on `ReadOnlyHost` with `_is_forbidden`
   (and filter grep/glob results), or run the default read backend `virtual_mode=True` rooted
   at the user's home in multi-user. This closes the cross-tenant + password-hash-DB read.
   Add a test: user A's agent `grep`/`glob`/`ls` over `$EKLAVYA_DATA_ROOT` returns nothing.
2. **N4** — Reject a session whose uid no longer exists (`auth.get_user(uid)` check in the
   middleware) so CLI account deletion actually revokes access.
3. **N5** — Ship `X-Frame-Options`/`nosniff`/CSP either app-side or verified in the proxy runbook.
4. Operational: single uvicorn worker (coherent throttle), confirm `EKLAVYA_TRUST_PROXY` matches
   the actual proxy, `EKLAVYA_SECRET_KEY` set (32+ random bytes), `EKLAVYA_INSECURE_COOKIES` unset.

**MUST fix before any public / untrusted exposure:**
5. **N3** — Pin + SRI (or vendor) the CDN scripts, especially DOMPurify.
6. **F2/F3/F6** — bubblewrap jail for `run_bash` (+ `--unshare-net`, allow-list env), fail-closed
   `EKLAVYA_JAIL` gate that refuses a non-loopback bind without it.
7. Pre-publish `pip-audit` / `uv pip list --outdated`; keep the secret-scan in the release checklist.

**Fine for the private 2-user stage (documented, revisit if scaling/public):**
- F8/F9/F10/F11/F12, and N2 (single-user secret-dir read via grep — your own box).

---

*End of audit. No application code was modified.*
