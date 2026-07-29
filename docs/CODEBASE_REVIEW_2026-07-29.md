# Ekalavya — Full Codebase Review (`feat/multiuser-auth`)

_Date: 2026-07-29 · Scope: the entire tree on `feat/multiuser-auth` (per-user isolation + email/password auth, GLM/MiniMax/Qwen/Kimi providers, the recent security fixes, and the just-reworked agent toolset). Method: full read of `src/eklavya/*`, `tests/*`, `docs/*`; `uv run pytest -q` (140 passed); read-only greps and one-off `uv run python` probes. **No application code was modified — this file is the only write.**_

This review verifies the three design decisions the task named, then hunts for real problems across correctness, security, the agent harness, and complexity, and finally surfaces the high-leverage easy wins for the agent.

---

## Executive summary

**The three headline decisions were implemented correctly.** This branch closes the P0 gaps the two prior reviews found:

1. **Minimal toolset, grader wired, no prompt/tool mismatch.** `AGENT_TOOLS` is now exactly `[grade_and_record, web_search, record_attempt, save_baseline, suggest_focus, review_ai_usage, run_bash]` (`tools.py:569-572`) plus the deepagents floor (`read_file/write_file/edit_file/ls/glob/grep/write_todos/task`) and Context7 docs when warmed. I checked every tool name the prompts mention against what the agent actually has: **no prompt references a tool the agent lacks.** The removed tools (`tavily_search`, `tavily_extract`, `diff_code`, `get_questions`, `add_question`, `progress_report`) appear in **no prompt** as a callable — the two lingering mentions are `diff` used *via* `run_bash` prose (`prompts.py:82`) and a defensive "NEVER call `execute`" (`prompts.py:115`). `web_search` is in the toolset on **every** interface, and the CLI/TUI now warm Context7 too (`cli.py:54`), so the old "terminal has no web search / no docs" P0 is gone. MCP-*consumer* is Context7-only; Tavily MCP was dropped as redundant with the local `web_search` (`mcp_client.py:17-26`). ✅

2. **`grade_and_record` is the grading path and is genuinely tamper-proof.** The prompts route every code drill through it (`prompts.py:72, 105, 157-169, 183`); `record_attempt` is explicitly reserved for non-code drills. The flow (`tools.py:418-451`) first runs the tutor's `reference` against the tutor's `tests` and **refuses to grade the learner if the reference fails** (catches bogus tests), then runs the learner's code in the sandbox and records the **real** `r.ok`. The model cannot claim PASS when the sandbox says FAIL — it never gets to pass a `correct` boolean. Tests confirm both the verified-verdict path and the reference-sanity veto (`test_practice.py:154-199`). ✅

3. **Multi-user isolation + auth are correct and gated.** `config.paths()` is contextvar-driven (`config.py:76-100`); every store (`db.connect`, `chatstore`, `settings`, `backups`, `tools.read/save_profile`) resolves through it at call time. Auth is argon2id with a dummy-verify timing defense (`auth.py:77-102`), fail-loud `EKLAVYA_SECRET_KEY` (`middleware.py:38-45`), `HttpOnly`+`SameSite=Strict`+`Secure` cookies (`middleware.py:59-66`), 404-not-403 thread ownership (`webapp.py:93-101`), and an in-memory login throttle (`auth.py:129-161`). Everything is behind `EKLAVYA_MULTIUSER`; single-user is byte-for-byte unchanged. The real `TestClient` isolation test drives the full middleware and passes (`test_isolation.py:187-229`), which also confirms the contextvar set in `AuthMiddleware.dispatch` **does** propagate to endpoints on this Starlette version. ✅

**The two prior audits' still-open P0/P1 items are fixed on this branch:**
- **F1/F4 (cross-tenant read)** — fixed. In multi-user, reads are confined to the user's own home twice over: `_is_forbidden` denies anything outside the user's own workspace (`workspace.py:48-52`), and the read backend is rooted at `config.paths().home`, not `Path.home()` (`workspace.py:91`). Tested (`test_isolation.py:244-260`).
- **F5 (`startswith` path boundary)** — fixed, now `Path.is_relative_to` (`workspace.py:42,46,55`). Tested with a `workspace-evil` sibling (`test_isolation.py:263-273`).
- **F7 (exception leakage)** — fixed. `webapp.py:188-190` logs server-side, streams a generic message; `assist.py:114-116` returns a generic string.
- **`_log` shadowing bug in `assist.py`** — fixed (logger renamed `_logger`, `tools.py`… `assist.py:25,115`).

**What is still genuinely wrong or missing** is smaller but real: a curriculum-mastery string-matching desync that makes the skill tree's colouring unreliable, a stale docstring that contradicts the onboarding prompt, an undeclared `requests` dependency, an unbounded per-user agent cache, a couple of deliberately-deferred sandbox items, and — most importantly for teaching quality — **the adaptivity the README sells still runs on model memory, not on tool calls.** The single biggest lever left is wiring the already-written curriculum graph + a mastery lookup + a calibration readout into the agent. Details and ranked easy wins below.

Deferred-by-plan (acceptable for the private 2-user stage, must fix before public): `run_bash` has no jail (F2/F3), env-scrub is denylist-based (F6), no server-side session revocation (F8), in-memory throttle (F9), CDN scripts without SRI (F13).

---

## Findings (severity-tagged)

| # | Sev | Area | Location | Problem | Fix |
|---|-----|------|----------|---------|-----|
| C1 | **Critical (public only)** | Sandbox / `run_bash` jail | `tools.py:284-321` | `run_bash` is `shell=True` with a bypassable denylist + env-scrub and no FS/network confinement. `cwd=workspace` doesn't contain absolute paths or `python -c`. Env-scrub blocks `echo $KEY` but not `cat`-ing a key file. On a shared/public host this reads `~/.ssh`, other trees, and exfiltrates over the net. | Bubblewrap jail (#49): FS confined to the user's `/workspace`, `--unshare-net`, fail-closed `EKLAVYA_JAIL=1` startup gate that refuses a non-loopback bind. **Acceptable to defer for the private 2-user stage only** (both trusted, IP-allow-listed, signup off) per the plan. Do NOT expose publicly without it. |
| H1 | **High** | Skill-tree correctness | `report.py:129-131`, `tools.py:386` | The curriculum graph colours a node "done" only when a curriculum concept string **exactly equals** an `attempts.detail` value. `record_attempt` stores whatever free-form `concept` the model passed per drill; those rarely equal the curriculum node names the model wrote at onboarding. So most nodes stay `avail`/`lock` forever, `status()`'s prereq-unlock logic never fires, and the "teach only after prereqs" promise + the skill-tree mastery view are effectively non-functional. This also silently breaks the pedagogy the README advertises. | Give drills a stable concept key that maps to curriculum nodes: have the agent pass the exact curriculum concept name (add a `next_concepts()` tool — see easy wins — so it *has* the names), or add a `curriculum_concept` column linking attempts to nodes. Minimum: normalize (casefold/strip) both sides of the match in `report.py:159-161`. |
| H2 | **High (multi-user, at scale)** | Unbounded cache | `webapp.py:74,82-89` | `agents` is an unbounded `dict` keyed by `(uid, mode)`; each value is a deepagents agent holding a model client + a SqliteSaver handle. Similarly `chatstore._savers`/`_readers` (`chatstore.py:23,160`) grow one entry per distinct user file and are never evicted. Two trusted users are fine; any real multi-tenancy leaks handles and memory until restart. | Add an LRU bound (e.g. `functools`-style or a small capped dict) on `agents`, `_savers`, `_readers`. Cheap; do it before scaling past a handful of users. Not needed for the 2-user launch. |
| M1 | **Medium** | Prompt/docstring contradiction | `tools.py:151-154, 203` vs `prompts.py:400-414` | `add_curriculum` and `save_baseline` docstrings (which the model reads) say prereqs are **comma-separated**; the ONBOARDING prompt (also read by the model) mandates **pipe-delimited** because concept names contain commas. `report.parse_prereqs` prefers pipe but falls back to fuzzy substring matching on comma text — which is lossy and can wire wrong edges. The two instructions the model sees disagree. | Change both docstrings to say pipe-delimited (`|`) exact concept names, matching the prompt. One-line fix each. |
| M2 | **Medium** | Adaptivity not enforced | `tools.py:240-267` (`suggest_focus`), `get_curriculum` unwired | `suggest_focus` returns only the 5 weakest **ratings** cells; it ignores the curriculum DAG entirely. `get_curriculum` exists (`tools.py:179-191`) but is **not in AGENT_TOOLS**, so the practice agent can't read the skill tree to pick the next unlocked concept or respect prereqs. Expertise-reversal ("show a worked example only for weak concepts") likewise has no per-drill mastery lookup — the model guesses from memory. The one adaptivity the README claims runs on vibes. | See easy wins EW-1/EW-2: add `next_concepts()` and `concept_level()` and reference them in the SESSION prompt. Small tools, big pedagogy payoff. |
| M3 | **Medium** | Dead/duplicated tool surfaces | `tools.py:270,324,404,454,465,491`; `mcp_server.py:40-47` | `run_code`, `grade_code`, `diff_code`, `get_questions`, `add_question` are defined but not in `AGENT_TOOLS` — dead for the in-process agent. `run_code`/`grade_code` are still used by the **MCP server** (`mcp_server.py`), and `progress_report` by the `/stats` slash command (`commands.py:53`), and `diff_code`/`get_questions`/`add_question` by tests only. So the MCP server exposes a *different, smaller, partly-dead-elsewhere* toolset than the in-process agent (it has `run_code`/`grade_code` but not `grade_and_record`, `save_baseline`, `review_ai_usage`, `web_search`). Reader-confusing and drift-prone. | Decide per tool: delete the truly-dead ones (`diff_code` is only tested; the RE-SOLVE→DIFF drill uses `run_bash` diff prose now) or promote them. For MCP, either expose `grade_and_record` there too or document that the MCP surface is intentionally a thinner "external-brain" spine. At minimum add a one-line comment on each unwired `def` saying who still calls it. |
| M4 | **Medium** | Undeclared dependency | `tools.py:517`, `pyproject.toml` | `web_search` does `import requests`, but `requests` is declared **nowhere** in `pyproject.toml` (only present transitively; `httpx` is the declared HTTP client, in the `web` extra). If the transitive pin drops, `web_search` raises `ImportError` at call time — swallowed by the agent, so it silently loses web search. | Either add `requests` to the base deps, or (better, one fewer dep) rewrite `web_search` on `httpx`, which is already pulled in. |
| L1 | **Low** | `ai_off` is model-owned | `prompts.py:55-58`, `tools.py:345` | The headline "unaided-vs-assisted gap" metric (`report.ai_gap`) depends on the model *inferring* `ai_off` from whether the learner "can defend their reasoning." Subjective and gameable. `grade_and_record` hardcodes `ai_off=True`, which is right for a typed drill, but the AI-interview path passes `ai_off=False` by prompt instruction. | Derive `ai_off` from mode (aiinterview ⇒ False) + the deterministic paste signal (`progress.looks_pasted`) instead of model judgment. Keeps the gap metric honest. |
| L2 | **Low** | Judge cross-family independence | `verify.py:127-135` | `_judge_provider_key` picks "any configured provider ≠ tutor default." With GLM+MiniMax (or Qwen/Kimi) the judge may share training lineage with the tutor, weakening the self-preference defense the docstring implies is solved. | Prefer a genuinely different-lineage judge when Claude/Gemini are configured; note the residual risk in the docstring. Advisory-only judge, so low sev. |
| L3 | **Low** | Streaming blocks the event loop | `webapp.py:162-233` | `_events` consumes the blocking `agent.stream` generator inside an async `StreamingResponse` handler — it runs on the event loop, serializing all users' turns. Not an isolation bug (contextvar is right), but a throughput ceiling and a latency multiplier once >1 user is active. | Move the blocking generator to `run_in_threadpool` (context-copying) when concurrency matters; the plan already reserves `config.run_user_task` for the manual-thread case. Fine for 2 users. |
| L4 | **Low/Info** | Deferred security items | `tools.py:311` (F6 denylist env-scrub), `middleware.py` (F8 no revocation), `auth.py:129-161` (F9 in-mem throttle), `webapp.py:617-621` (F13 CDN no SRI) | All accepted for the private stage in the security audit; re-flagged so they're not forgotten. F6: a var like `DATABASE_URL`/`MYSQL_PWD` isn't scrubbed. F8: a stolen cookie is valid for 14d. F9: throttle resets on restart / not shared across workers. F13: a jsDelivr compromise defeats the DOMPurify XSS backstop. | Before any public exposure: allow-list `run_bash` env (deny-by-default), add token-version revocation + shorter `COOKIE_MAX_AGE`, single uvicorn worker (document it) or shared throttle store, SRI-pin or vendor the CDN scripts. |

### Things I checked and found correct (no action)
- Sandbox `run_python`/`run_tests` isolation: clean env (no parent API keys), throwaway cwd, `-I` isolated mode, CPU + wall limits, pass-marker so a no-op test can't fake success (`sandbox.py`). Solid.
- SQL is parameterized everywhere; all HTML sinks route model/DB strings through `html.escape`/DOMPurify (`webapp.py:742`, `report`/`dashboard`/`profileview`).
- Contextvar isolation across db/profile/ratings/XP/chats/settings/backups — all tested and passing (`test_isolation.py`).
- No secrets in the tree or git history (confirmed by the prior audit's scans; `.env` git-ignored, only `.env.example` tracked).
- The `grade_and_record` tamper-proof flow, the anti-cheat paste heuristic (mirrored server/client), and the AI-interview planted-bug logging + `review_ai_usage` — all sound and tested.

---

## High-leverage easy wins (agent teaching quality — ranked)

These are small, mostly-additive changes that would give a large jump in the agent's teaching quality/reliability. Most of the machinery already exists in the repo — it's disconnected, not unwritten.

**EW-1 — Wire the curriculum graph into practice with a `next_concepts()` tool. (Biggest lever, ~15 lines.)**
Today onboarding writes a rich skill tree that the practice agent can never read (`get_curriculum` is unwired; `suggest_focus` ignores the DAG). Add a tool that returns the *unlocked-but-unmastered* nodes (prereqs satisfied), reusing `report.py`'s existing prereq-parse + status logic, and name it in the SESSION prompt's warm-up step. This turns the skill tree from a display artifact into an actual planner and makes "teach only after prereqs" real. It also fixes the root cause of H1 (the agent would pass exact curriculum concept names, so mastery colouring starts working). **This is the single highest-value change on the list.**

**EW-2 — Add `concept_level(pillar, axis)` so expertise-reversal is enforced, not guessed. (~6 lines.)**
A one-line read of the ratings table via `scoring.level_of`. Instruct the SESSION prompt to call it before deciding whether to show a worked example. Right now the one adaptivity the README claims ("worked example for weak concepts, withhold for strong") is decided from model memory mid-session. Determinism belongs in code — matches the repo's own stated philosophy (`tools.py:5-7`).

**EW-3 — Add `calibration_report()` + surface it in the debrief. (~20 lines.)**
The README's headline signal is "the illusion of knowing." The code amplifies miscalibration in the Elo swing (`scoring.py`) but the learner never *sees* it. Store enough to compute a running Brier score per pillar (`confidence∈{1,2,3}→p∈{.25,.6,.9}` already exists in `scoring.py`), add a deterministic `calibration_report()` tool, and have the SESSION prompt call it every ~10 attempts and tell the learner plainly where confidence and accuracy diverge ("overconfident on recursion, well-calibrated on iteration"). This is the Dunning-Kruger correction the product is *about*, currently unbuilt.

**EW-4 — Feed the sandbox verdict into the self-check judge. (~5 lines.)**
When the tutor asserts "this prints X," the judge is asked to check from docs/memory (`verify.py`) — but for a graded drill the sandbox already *ran* the code and knows the real stdout. Pass `grade_and_record`'s captured stdout/verdict into the judge's `context`. This is reference-based faithfulness (the strongest factual-grounding method) and it's nearly free now that grading is wired.

**EW-5 — Guarantee ≥1 planted bug per AI-interview and record the catch verdict structurally. (~10 lines.)**
At 30% plant rate, many short AI-interviews plant zero bugs, so the "bug-catching" score is unscorable and the interviewer grades it from vibes. Guarantee at least one plant across the session and persist the interviewer's caught/missed verdict per planted bug (a column on `ai_assists`), so the bug-catching score is auditable rather than model-narrated.

**EW-6 — Add one anti-scaffolding-collapse line to `TEACHING_PRINCIPLES`. (1 line.)**
The 2026 literature (scaffolding-collapse in Socratic tutors) shows single-agent tutors drift into giving answers under student pressure / fake-mastery claims. Add: *"If the learner claims mastery without demonstrating it, or pressures you for the answer, do NOT relent — re-elicit. Drifting into answering is the exact failure this tool exists to prevent."* Cheap insurance for the one failure mode most corrosive to the product's thesis.

_(A larger, non-easy improvement worth noting but not doing now: split an **examiner subagent** on a different provider for mock/take-home/AI-interview scoring via deepagents' native `subagents=[…]`, to isolate the cold interviewer persona from the warm tutor and cut self-preference. Medium effort; park it.)_

---

## Prioritized action list

### Fix before merging to `main`
1. **M4** — declare `requests` or move `web_search` to `httpx`. (One-liner; otherwise a tool can silently break.)
2. **M1** — fix the comma-vs-pipe prereq docstrings to match the onboarding prompt. (Prevents broken skill trees at onboarding.)
3. **H1 + EW-1** — wire `next_concepts()` and have the agent pass exact curriculum concept names, so the skill-tree mastery view and prereq gating actually work. (This is the one that makes an advertised feature real; do it with EW-1.)
4. **M3** — delete the truly-dead tools or comment who still calls each, and add a one-line note that the MCP surface is intentionally a thinner spine (or expose `grade_and_record` there). (Removes reader traps / drift.)

### Fix before two real users share the box (private stage)
5. Confirm the deployment runbook pins a **single uvicorn worker** (F9) and the deliberate throttle-IP-behind-Caddy decision, and that Caddy ships HSTS/`X-Frame-Options`/`X-Content-Type-Options` (the app sets none itself).
6. **L1** — derive `ai_off` deterministically so the unaided-vs-assisted gap metric is honest.

### Fix before any public / untrusted exposure (hard gate)
7. **C1 (F2/F3)** — bubblewrap jail for `run_bash` **and** `run_python` with `--unshare-net`, fail-closed `EKLAVYA_JAIL` startup gate.
8. **L4** — allow-list `run_bash` env (F6), session revocation + shorter cookie max-age (F8), SRI/vendor CDN scripts (F13); run `pip-audit` pre-publish.

### Later (quality / scale)
9. **EW-2 / EW-3 / EW-4 / EW-5 / EW-6** — the adaptivity + calibration + judge-grounding + AI-interview + anti-collapse wins (ranked above). EW-2/EW-3 are the highest-value of these.
10. **H2** — LRU-bound `agents`/`_savers`/`_readers` before scaling past a handful of users.
11. **L3** — move the streaming generator off the event loop when concurrency matters.
12. **L2** — prefer a different-lineage judge when Claude/Gemini land; soften the "self-bias solved" docstring.

**One-line version:** the P0 wiring the prior reviews flagged is now correct — grader wired and tamper-proof, no prompt/tool mismatch, minimal toolset, cross-tenant reads confined, auth solid, 140 tests green. The remaining real bug is the skill-tree mastery string-match desync (H1); the remaining big *opportunity* is that the adaptivity and calibration the README sells still live in the model's head instead of in the three small tools (EW-1/2/3) that would make them real.

---

_Tests: `uv run pytest -q` → **140 passed, 1 warning** (a Starlette/httpx deprecation in `test_auth.py`, cosmetic). Coverage is strong on isolation, auth, grading, anti-cheat, and the tool spine; the notable gap is that **no test asserts curriculum nodes ever reach `done`** (which is exactly why H1 went unnoticed) — add one that records an attempt with a curriculum concept name and checks `curriculum_mermaid` colours it `done`._
