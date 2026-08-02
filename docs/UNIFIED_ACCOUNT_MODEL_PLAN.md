# Unified Account Model — Implementation Plan

> Goal: **one model, accounts always.** Web, CLI, and TUI are just frontends over the same
> core, each operating as a *logged-in account*. Remove the single-user/multi-user duality
> and the dangerous `~/.eklavya` default-home. Local self-host = frictionless default
> account; deployed = enforced auth. The only difference between local and deployed is
> **config** (API keys, host, signup-approval), never a code path.
>
> Non-negotiables for the whole plan: `uv run pytest -q` green at every step; NEVER read/
> write/move real data under `~/.eklavya` or `~/.eklavya-data` (use `mktemp -d` roots);
> keep the destructive-op guard; no AI attribution in commits; commit per phase; STOP at
> each phase gate for review.

---

## Phase 1 — Unify all frontends on the account model (task #82)

**Data layout (single source of truth):** all real data lives at
`$EKLAVYA_DATA_ROOT/users/<uid>/workspace/eklavya.db` (`EKLAVYA_DATA_ROOT` defaults to
`~/.eklavya-data`). The `~/.eklavya` single-user home is retired — never used for real writes.

1. **config.py**
   - Remove the `MULTIUSER` flag concept (treat as always-on). Keep `data_root()`,
     `user_home(uid)`, `set_current_home()`, `paths()`, `run_user_task()` — the bound-home
     contextvar is now the *only* mechanism.
   - Add `resolve_local_user() -> str` (uid) for CLI/TUI startup:
     1. `EKLAVYA_USER` env (email or uid) → that account;
     2. else a stored "default local user" (in a small local config / `users.db` flag);
     3. else if exactly one account exists → it;
     4. else → first-run: create/prompt a local account.
     **Important:** must resolve to the user's EXISTING account (e.g. `1bf17c28114c`), never
     silently create a fresh empty one that hides their data.
   - `_default_home()`/`~/.eklavya`: remove as a real-data path. The destructive guard stays
     as defense-in-depth (now keyed on "no home bound at all").

2. **CLI (cli.py)** — every command that touches state binds the resolved account first:
   `config.set_current_home(config.user_home(resolve_local_user())); config.ensure_home()`.
   - Add `eklavya login` (store a local session/default user), `eklavya whoami`, `--user` flag,
     `eklavya logout`. `eklavya serve` unchanged (launches the web app; accounts always on).

3. **TUI** — bind the resolved account at startup; optional in-app account switch.

4. **webapp.py / middleware.py / chatstore.py / workspace.py** — collapse every
   `if config.MULTIUSER:` branch into the single account path. Web always requires login
   (as multi-user does today). Signup-approval remains a config toggle.

5. **auth.py** — support a frictionless local default account (first-run creates one, or a
   `--local` account with no email ceremony) so solo local users aren't forced through
   email/password every command; deployed installs keep full auth + approval.

6. **Migration / safety** — the user's real data is already in the multi-user layout; ensure
   the default local user maps to their real account (`1bf17c28114c`). Legacy `~/.eklavya`
   stays archived (already backed up); no destructive moves.

7. **Tests** — update any test that assumed the single-user default; add tests for
   `resolve_local_user()` precedence and CLI account binding. Keep 316+ green.

**Phase-1 gate:** web + CLI + TUI all work against accounts; `~/.eklavya` unused; no dual-mode
branches remain; tests green; STOP for review.

---

## Phase 2 — Subject-aware metrics for non-coding subjects (task #86)

Today the 5 axes (`syntax_recall, debugging, code_reading, api_memory, decomposition`) + the
mastery grid + the IRT benchmark are coding-specific, so stats/econ/DS/CS/ML/AI are captured
generically (pillars, curriculum/forest, attempts, XP, streak, AI-gap) but NOT in the per-axis
grid or benchmark.

- Make axes **subject-aware**: either per-subject axis sets, or a generic axis family for
  non-coding pillars (e.g. `recall / application / derivation / interpretation`). The pillar
  carries its axis set; grid, `set_baseline_rating`, ratings, and effectiveness read it.
- Dashboard/Journey/Effectiveness render any subject faithfully (no coding-only assumptions).
- Benchmark: scope the coding IRT set to coding, and allow subject-appropriate assessment
  (or clearly label the benchmark as coding-only) so non-coding effectiveness isn't misread.
- Fold into the unified-overview redesign (#83) where these headline numbers surface.

**Gate:** a statistics/econometrics pillar shows correct axis mastery + effectiveness; green.

---

## Phase 3 — Agent prompts for honest AI/Google use (task #85)

- Prompt/behavior: the tutor gently asks, per drill, whether the learner used AI or Google,
  and records it via the existing `ai_off` per-attempt flag.
- No unfair punishment — penalties apply ONLY when penalty mode is on; otherwise it's purely
  for honest self-tracking of **unassisted** skill (feeds the AI-off vs AI-on gap already
  tracked). Frame it warmly, as helping the learner see real unassisted progress.
- Small, additive: mostly `prompts.py` + ensuring the attempt-recording path carries the flag.

**Gate:** drills capture assisted/unassisted honestly; AI-gap reflects it; green.

---

## Sequencing
Phase 1 (#82) first — it's the structural change everything else rides on. Then Phase 2 (#86)
and the unified overview (#83), then Phase 3 (#85). Each phase: implement → tests green →
manual check on a throwaway root → commit → STOP for review.
