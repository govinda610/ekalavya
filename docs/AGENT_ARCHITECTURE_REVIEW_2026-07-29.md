# Ekalavya — Agent Architecture, Prompts & Tools Review

_Date: 2026-07-29 · Scope: the teaching agent (prompts, structure, tools, modes), the verify/judge layer, the AI-interview assistant, and a lighter backend pass. Grounded in a full read of `src/eklavya/*` and current (2025–2026) literature on tutoring agents, LLM-as-judge reliability, and reward-hacking of AI graders. **No code was modified.**_

This review deliberately does **not** re-litigate the findings already captured in `CRITIQUE.md` (sandbox isolation, single-user web state, XSS, fabricated citations, in-memory checkpointer). Several of those have since been addressed (DOMPurify is now wired in `webapp.py:618`; a SQLite checkpointer is now the default in `agent.py:42–45`; multi-user auth is on branches). This document focuses on the **agent/prompt/tool layer** the task asked for, and surfaces issues `CRITIQUE.md` did not.

---

## Executive summary

Ekalavya's design intent is excellent and the prompts are unusually literate about the learning science. But the **agent-tool contract has drifted badly from the prompts**, and that drift silently defeats the product's central moat ("verified grading, not model opinion").

The three highest-impact findings:

1. **The verified-grading path is not wired in.** `grade_and_record` (tools.py:418) is a genuinely tamper-proof grader — it validates the tutor's tests against the tutor's own reference before recording, so the model *cannot* fake the pass/fail that hits Elo/FSRS/XP. **It is not in `AGENT_TOOLS` (tools.py:543), so the agent can never call it.** Instead every prompt tells the agent to "run it with `run_bash`… then record it" (prompts.py:157–159), which routes the whole loop through `record_attempt(correct=<model-decided bool>)`. The moat exists in the codebase but is disconnected from the agent. **P0.**

2. **The prompts reference a dozen tools the agent does not have.** `TOOLS_GUIDE` and the drill/mode prompts name `read_file`, `write_file`, `edit_file`, `diff` (diff_code), `tavily_search`, `tavily_extract`, `resolve-library-id`, `query-docs`, `sqlite3 via run_bash` — but `AGENT_TOOLS` is only `[record_attempt, save_baseline, suggest_focus, review_ai_usage, run_bash]` plus deepagents' filesystem floor and *optionally* the MCP tools. In the **TUI and CLI paths the MCP tools are never warmed** (`load_mcp_tools()` is called only in `serve` and `doctor`, cli.py:54/329), so in the terminal the agent is told five times to `tavily_search` for real interview questions and **has no such tool** — it will hallucinate "company X asks…" questions, the exact failure the prompt warns against. **P0.**

3. **A single deep-agent doing planning + Socratic dialogue + grading + judging is the wrong shape for the reliability the product promises.** State that must be deterministic (correctness → rating) is decided by the model; the grader, the examiner, and the tutor are the same context; and there are no role boundaries. The 2025–2026 literature (below) is converging on **explicit role separation** (a deterministic verifier feeding a scaffolding tutor) precisely because single-agent Socratic tutors suffer *scaffolding collapse* — they drift into giving answers under student pressure. **P1.**

There is also a **live bug**: `assist.py` defines `_log` as a logger (line 25) then rebinds it as a function (line 86), so the error handler `_log.exception(...)` at line 115 raises `AttributeError` whenever the AI-interview assistant's model call fails. **P1.**

---

## 1. Prompts

### 1.1 The gate elicits confidence, but the *scoring* never sees it as a first-class attempt-then-reveal → weak calibration signal — P1
**Current** (prompts.py:145–160): the loop is confidence-gate → attempt → verify → debrief → `record_attempt`. Good. And `scoring.update_elo` (scoring.py:20–32) genuinely amplifies the rating swing on miscalibration — one of the best-implemented ideas in the repo.

**Problem:** the calibration signal stops at a single Elo nudge. There is no **Brier score** and no calibration *feedback to the learner*, which the 2025–2026 metacognition literature treats as the actual training mechanism (confidence-elicitation + Brier + periodic reliability feedback — Onco-Shikshak 2026, medRxiv; Zollo et al. 2025). The learner never sees "you said '3/certain' and were wrong 40% of the time — you're overconfident on recursion," which is the Dunning-Kruger correction the README sells as the headline signal.

**Recommend:** (a) store enough to compute a running Brier score per pillar (`confidence∈{1,2,3}→p∈{.25,.6,.9}` already exists in scoring.py:17); (b) add a deterministic `calibration_report()` tool and have the debrief surface it every ~10 attempts. Add to `TEACHING_PRINCIPLES`:
> - CALIBRATION FEEDBACK: every ~10 drills, call `calibration_report()` and tell them plainly where their confidence and their accuracy diverge (e.g. "you're overconfident on X, well-calibrated on Y"). Use growth framing, never deficit framing.

### 1.2 "Verify with run_bash before you teach" is the wrong deterministic primitive — P0
**Current** (prompts.py:48–52, 148–152): "never present code as correct unless you have run it with `run_bash`… the moment a drill is judged you MUST call `record_attempt`."

**Problem:** this makes the model the grader of record. `run_bash` returns free text the model then *interprets* into a `correct` boolean it passes to `record_attempt`. Nothing links the two. This is textbook **reward-hacking surface**: the LLM writes the drill, writes the "hidden" tests, runs them, and self-reports the grade (Reward Hacking in Rubric-Based RL, arXiv 2605.12474; He et al. anti-hacking rubrics). The deterministic fix already exists unused (`grade_and_record`).

**Recommend:** wire `grade_and_record` into `AGENT_TOOLS` and rewrite the loop step (prompts.py:157–159) to:
> d. GRADE DETERMINISTICALLY — for any code drill, call `grade_and_record(pillar, axis, concept, code, tests, confidence, reference)`. You supply your own `reference` solution and `tests`; the sandbox first proves your reference passes your tests (catching *your* mistakes), then runs the learner's code and records the **real sandbox verdict** — you cannot override it. Use `run_bash` only for exploration, never as the source of a grade.

Keep `record_attempt` reachable only for non-code drills (design, behavioral, teach-back), and note that explicitly so the model doesn't reach for it to bypass the grader.

### 1.3 Expertise-reversal is stated but not enforced — the agent can't see mastery at drill time — P1
**Current** (prompts.py:30–33): "for a NEW/weak concept you may show a worked example; for STRONG concepts withhold it."

**Problem:** the agent has no cheap way to know a concept's current level mid-session. `suggest_focus` returns weakest cells as prose at session start, but per-drill the model is guessing at mastery from memory. Expertise-reversal (the one adaptivity the README claims) therefore runs on vibes.

**Recommend:** add a `concept_level(pillar, axis)` tool (a one-line read of the ratings table via `scoring.level_of`) and instruct the model to call it before deciding whether to show a worked example. This is a 6-line tool; the determinism belongs in code, not model memory (matches the repo's own stated philosophy, tools.py:5–7).

### 1.4 "NEVER show raw tool output" is repeated 3× but structurally unenforceable — P2
**Current** (prompts.py:44–47, 124–129, 320–322). Heavy prompt pressure against leaking `suggest_focus`/profile dumps.

**Problem:** relying on a prompt to hide tool output is fragile, and the web UI *already* renders tool activity in a collapsed trace (webapp.py:815–817) — so the leak channel the prompt fears is partly by-design elsewhere. This is fine, but the triple-repetition wastes prompt budget and caching.

**Recommend:** low priority — trust the UI trace, cut two of the three repetitions, keep one crisp line. Consolidating also helps prompt-cache stability (the GoPenAI/deepagents note: dynamic/bloated system prompts kill caching).

### 1.5 Onboarding prompt is strong; one gap — no persistence of the *assessment transcript* — P2
The onboarding prompt (prompts.py:315–414) is the best-designed in the file: it grills for target roles, mandates web research for unknown-unknowns, treats self-reported weakness as a floor, and demands a full skill-tree curriculum. This is genuinely good pedagogy. The one gap: baseline judgments ("wrong = gap") are collapsed straight into a rating; the *evidence* (what they answered) is only written into `profile.md` prose at the model's discretion. Consider a structured `record_baseline_evidence` so a later session can revisit a shaky "familiar."

---

## 2. Agent structure

### 2.1 Single agent for tutor+grader+examiner+planner → scaffolding collapse risk — P1
**Current** (agent.py:32–58): one `create_deep_agent` per mode, same model, all roles fused.

**Problem:** the 2026 literature names the exact failure mode. *Mitigating Scaffolding Collapse in Socratic Tutors* (arXiv 2607.19371) shows single-agent Socratic tutors "gradually abandon their instructional role, directly reveal answers, or fail to correct erroneous student statements" under sustained student pressure/fake-mastery — a trajectory-level drift that a single fused agent cannot self-arrest. *Planning-Guided Tutoring with Assessment-Driven* (ACL 2026 long 325) proposes the now-standard two-step: a **deterministic assessor** (PASS/FAIL on the learner's utterance) gates a **separate scaffolding responder** — the tutor only teaches *after* the assessor rules. Ekalavya fuses assess + scaffold in one turn.

**Recommend (P1, incremental):** deepagents natively supports this via `subagents=[{name, description, system_prompt, tools, model}]` passed to `create_deep_agent` (confirmed via Context7 `/langchain-ai/deepagents`; `SubAgentMiddleware` is always added and exposes a `task` tool). Introduce two subagents without rebuilding the app:
- an **examiner** subagent for mock/take-home/AI-interview scoring (own rubric prompt, own `tavily_search`), so the interviewer persona is isolated from the warm tutor persona and can't be softened mid-interview;
- a **grader** subagent is unnecessary once §1.2 lands (the deterministic tool *is* the grader).

Cross-model is a bonus: run the examiner on a *different provider* than the tutor to blunt self-preference in scoring (see §4).

### 2.2 State ownership is mostly clean, with two leaks — P1
**Good:** ratings/FSRS/XP/streak all live in tools writing SQLite (tools.py, progress.py, scheduling.py) — the model decides *when*, code decides *what*. This is the right architecture and it's well executed.

**Leak 1 (the big one):** `correct` is model-owned in the wired path (§1.2). **Leak 2:** `ai_off` is model-owned (prompts.py:55–58 asks the model to *infer* AI-assistance from whether the learner can defend their reasoning, then pass `ai_off=False`). That's a subjective judgment feeding the headline "unaided-vs-assisted gap" metric (report.py:80–115). It will be noisy and gameable. Consider deriving `ai_off` from mode + the anti-cheat paste signal (which is already deterministic, progress.py:20–27) rather than model inference.

### 2.3 The `run_bash` approval gate is real, but grading rides on an ungated read path — P2
`run_bash` is interrupt-gated (agent.py:57) — good. But the filesystem floor tools (`read_file`/`ls`/`glob`/`grep`) are **not** gated and read the whole host home in single-user mode (workspace.py:88–95). The prompts actively encourage this ("`read_file`/`ls`/`glob`/`grep` reach their real machine… ground drills in their code," prompts.py:116). The `_is_forbidden` denylist (workspace.py:22–23) blocks `.ssh/.aws/.env` etc., which is reasonable, but a prompt-injected file in a scanned repo could still steer the agent to read and echo arbitrary non-secret host files into the transcript. Low likelihood, worth a note; the denylist is allowlist-inverted, which is the weaker posture.

---

## 3. Tools

### 3.1 Dead / unreachable tools — P0/P1
Defined in tools.py but **absent from `AGENT_TOOLS`**, so the agent can never call them:
`grade_and_record` (418) **[P0 — this is the moat]**, `grade_code` (324), `run_code` (270), `diff_code` (404) **[the prompt's RE-SOLVE→DIFF drill, prompts.py:80–82, is impossible without it]**, `get_questions` (465), `add_question` (491), `web_search` (509) **[the CLI/TUI's only real search path when MCP is cold]**.

Meanwhile `add_pillar`/`set_baseline_rating`/`add_goal`/`add_curriculum`/`clear_curriculum` are correctly kept as internal helpers behind `save_baseline` — that part is clean.

**Recommend:** decide per tool — wire in (`grade_and_record`, `diff_code`, and either `web_search` or the MCP `tavily_search`) or delete (`grade_code`/`run_code` are redundant once `grade_and_record` + `run_bash` exist). Right now they're neither, which misleads every future reader.

### 3.2 Prompt/tool mismatch on web search across interfaces — P0
The prompts assume `tavily_search` always exists (prompts.py:113, 204, 280, 363, and the ONBOARDING competency-research step 3b which is called "critical — do NOT skip"). But:
- **TUI/CLI:** MCP never warmed → no `tavily_search`, and `web_search` (the local Tavily tool) isn't in `AGENT_TOOLS` either → **zero web capability**, despite being told to research real roles/questions.
- **serve:** MCP warmed → `tavily_search` exists; `web_search` still dead.

So the single most important onboarding step (grounding the competency map in real 2026 role requirements) **silently no-ops in the terminal**. **Recommend:** either add `web_search` to `AGENT_TOOLS` (works everywhere, needs only `TAVILY_API_KEY`) and align the prompt to name `web_search`, or warm MCP in the CLI/TUI paths too. Pick one search tool and reference exactly that name everywhere.

### 3.3 The curriculum/skill-graph is written but never read by the tutor — P1
Onboarding builds a rich curriculum graph (`save_baseline(curriculum=…)`, tools.py:194) and `report.curriculum_mermaid` renders it. But **no tool lets the practice agent read the graph** to pick the next unlocked concept or respect prereqs. `suggest_focus` (tools.py:240) only queries weakest *ratings*, ignoring the DAG entirely. So the "teach only after prereqs" promise (prompts.py:402) has no runtime enforcement, and the skill tree is a display artifact, not a planner. **Recommend:** add `next_concepts(n)` that returns unlocked-but-unmastered curriculum nodes (prereqs satisfied), and have `SESSION`/`suggest_focus` consult it. This is the missing link between onboarding and daily practice.

### 3.4 MCP server exposes a *different, smaller* tool set than the in-process agent — P2
`mcp_server.py:24–55` exposes `get_progress, suggest_focus, list_goals, run_code, grade_code, record_attempt` — note it exposes `grade_code` and `run_code` (the ones dead in-process) but **not** `save_baseline`, `review_ai_usage`, or `grade_and_record`. So an external Claude-Code "tutor brain" can grade but cannot onboard, cannot do AI-interview review, and cannot use the tamper-proof grader. The two surfaces have diverged. **Recommend:** define one canonical tool list and generate both the in-process `AGENT_TOOLS` and the MCP registration from it, so they can't drift.

### 3.5 `save_baseline` prereq format is a footgun — P2
`add_curriculum`'s docstring says prereqs are **comma-separated** (tools.py:151–153), but the ONBOARDING prompt mandates **pipe-delimited** (prompts.py:400–403) because concept names contain commas, and `report.parse_prereqs` handles both (report.py:146–154). The tool docstring the model reads contradicts the prompt the model reads. Fix the docstring to say pipe-delimited; the ambiguity will produce broken graphs.

---

## 4. The verify / judge layer

**Sound parts:** context-aware judging (killing the "list.append returns None" false alarm), a *different provider* than the tutor to cut self-preference, doc-grounding via Context7, fail-open, precision-biased, and only running on substantive replies. This is a thoughtfully built judge (verify.py) and matches 2025 guidance well.

### 4.1 Cross-family independence is weaker than assumed — P2
`_judge_provider_key` (verify.py:127–135) picks "any provider ≠ the tutor's default." With only GLM and MiniMax configured, the judge is one of two models with overlapping training lineage. The 2025 self-preference literature (arXiv 2604.22891; ACL EMNLP 2025 main.86; the r/AIEval thread) shows "different families isn't real independence" — cross-family ensembling helps only to the degree judges are actually uncorrelated. **Recommend:** when Claude/Gemini become available, prefer a genuinely different-lineage judge; and note the residual risk in the docstring rather than implying self-bias is solved.

### 4.2 Single judge, no order/self-enhancement controls — P2
2026 best practice (futureagi, emergentmind LLM-as-judge) for release-grade judging: pairwise with **order alternation**, verbosity penalty, and calibrate to human labels (target Cohen's κ > 0.6). Ekalavya's judge is a single absolute-verdict pass. For a *self-check nag* this is acceptable (precision-biased, advisory), but if the judge's verdict ever gates anything (it currently only appends a note — good), upgrade to alternation. **Recommend:** keep it advisory; do **not** let it gate grades. Add one line to the judge prompt penalizing verbosity-based agreement.

### 4.3 The judge doesn't see the sandbox result — P1
When the tutor asserts "this prints X," the judge is asked to check from docs/memory (verify.py) — but the deterministic sandbox already *ran* the code and knows the real output. The most reliable fact-check (actual stdout) is not fed to the judge. **Recommend:** once §1.2 lands, pass the sandbox verdict/stdout into the judge context so it grounds output claims against ground truth, not model memory. This directly implements the "reference-based faithfulness" pattern the 2026 survey calls the best method for factual grounding.

---

## 5. Modes

Each mode has a distinct, fit-for-purpose prompt (SESSION/MOCK/TAKEHOME/AI_INTERVIEW/ONBOARDING) — genuinely differentiated, not copy-paste. Notes:

### 5.1 AI-interview: imperfection is well-designed but the scoring is fully model-trusted, and there's a live bug — P1
**Good:** `assist.py` plants exactly one bug (30%) or withholds (20%), strips the `<<BUG:…>>` marker before the candidate sees it, logs ground truth, and `review_ai_usage` hands the interviewer the planted-bug list to grade catch/miss. This is a genuinely novel, well-thought-out mode and the calibration (30/20/50) is reasonable.

**Bug (P1):** `assist.py` binds `_log` to a logger at line 25, then **redefines `_log` as the DB-logging function at line 86**, shadowing it at module scope. At line 115 the error handler calls `_log.exception("assist model error")` — but `_log` is now the function, which has no `.exception`, so a model failure raises `AttributeError` *inside* the except block. The one path meant to degrade gracefully ("the AI assistant is unavailable") instead crashes. Rename the logger (e.g. `_logger`) or the function.

**Design gap:** the interviewer's per-bug catch/miss judgment (prompts.py:291–293) is entirely model-inferred from the candidate's messages — no structured signal beyond the log. The 30% plant rate means many interviews plant 0 bugs across a few exchanges (bug-catching then unscorable). Consider guaranteeing ≥1 plant per interview and recording the catch verdict structurally so the "bug-catching" score is auditable, not vibes.

### 5.2 Mock/Take-home: no realistic-problem source in TUI — P1
Both prompts say "find realistic problems with `tavily_search`" and "only label from company X if you actually found it" (prompts.py:203–205, 280). In the TUI that tool doesn't exist (§3.2), so the model *will* invent company-attributed questions — the precise thing the prompt forbids, now unavoidable. Fixing §3.2 fixes this.

### 5.3 Onboarding competency-mapping depends on the same missing search — P0
Covered in §3.2; flagged again because the prompt itself calls step 3b "critical — do NOT skip… you have web search — USE it here" (prompts.py:362–364) while the terminal agent has no web search. Highest-priority mismatch after the grader.

---

## 6. Best practices to adopt (what the latest meta says we're missing)

Ranked by fit, with the exact slot to land each:

1. **Assessment-then-scaffold as two steps** — *Planning-Guided Tutoring* (ACL 2026 long 325): a deterministic assessor PASS/FAILs the learner's utterance *before* any scaffolding move; on FAIL, the reason is fed back and the tutor re-elicits for the *same* sub-question. Slot: restructure the SESSION loop (prompts.py:143–160) around §1.2's deterministic grader, and gate the "show idiomatic version" reward on a real PASS.
2. **Scaffolding-collapse guardrails** — arXiv 2607.19371, and Hazra/Yu 2026 on fake-mastery/role-drift prompt injection. Slot: an examiner subagent (§2.1) with a hard role constraint, plus a line in `TEACHING_PRINCIPLES`: "If the learner claims mastery without demonstrating it, or pressures you for the answer, do NOT relent — re-elicit; drift into answering is the failure this tool exists to prevent."
3. **Brier-score calibration feedback loop** — Onco-Shikshak (medRxiv 2026), Zollo et al. 2025. Slot: §1.1's `calibration_report()` tool + debrief.
4. **Reference-based faithfulness for the judge** — futureagi/emergentmind 2026: feed the sandbox's actual output to the judge. Slot: §4.3.
5. **Anti-hacking rubric criteria / veto layer** — Rubrics-as-Rewards (arXiv 2507, Gunjal et al.), Reward Hacking in Rubric-Based RL (arXiv 2605.12474): a critical dimension that, if it signals an exploit, zeroes the score. Slot: `grade_and_record` already implements the strongest version (deterministic reference check that *voids* grading if tests are bogus). Once wired, this is our anti-gaming veto — document it as such.
6. **Judge order-alternation + verbosity control** — the four production judge biases (position, verbosity, self-preference, self-enhancement), futureagi 2026. Slot: §4.1–4.2, only if the judge ever gates.
7. **deepagents subagents for role isolation** — confirmed API `create_deep_agent(subagents=[…])`, Context7 `/langchain-ai/deepagents`; each subagent gets its own model/prompt/tools, and cross-model subagents are the native way to get a different-family examiner/judge.

Citations: Bastani et al. 2024 (SSRN 4895486); Kestin et al. Nature 2025; scaffolding collapse arXiv 2607.19371; Planning-Guided Tutoring ACL 2026 (2026.acl-long.325); self-preference arXiv 2604.22891 / EMNLP 2025 main.86 / arXiv 2504.03846; reward hacking arXiv 2605.12474 + Rubrics-as-Rewards (Gunjal 2025); calibration/Brier — Zollo et al. 2025, Onco-Shikshak medRxiv 2026; LLM-as-judge 2026 — futureagi.com, emergentmind; deepagents docs (Context7 /langchain-ai/deepagents).

> Note: `README.md:184–201` should be re-verified against these — `CRITIQUE.md` flagged a malformed arXiv id and unverified RCT figures; treat every cited number as suspect until checked, since a technical evaluator will discount the whole "science-backed" claim on one bad link.

---

## 7. Backend (lighter pass)

- **Provider fallback is absent.** `build_chat_model` (providers.py:83–103) builds one client; there's no retry-to-another-provider on 5xx/ratelimit. With Qwen+Kimi being added (not yet in `providers.py` on any branch I could see — only GLM/MiniMax are present, providers.py:39–56; confirm they landed), a small `with_fallbacks` wrapper (LangChain native) around the tutor model would materially improve reliability. **P1.**
- **Streaming + self-check latency.** `selfcheck` runs a *second* full model call *after* the stream completes (webapp.py:198, chat.py:50), adding a serial round-trip (+ possibly a Context7 fetch) to every substantive turn before the note appears. Consider running it concurrently and appending late, or skipping it when the reply contained no asserted-fact code. **P2.**
- **Agent cache keyed by (user, mode) holds a model client per mode indefinitely** (webapp.py:74, 82–89). Fine at small scale; at multi-user scale this is an unbounded dict of agents (each with a checkpointer handle). Add an LRU bound before the multi-user launch. **P1 at scale.**
- **Multi-user contextvar isolation looks correct** (config.py:41–122, `run_user_task` chokepoint, `owns_thread` 404s in webapp.py:93–101). The one thing to test hard: `agent_for` builds the agent under whatever context is current at *first* call and caches it — verify the workspace/checkpointer captured at build time matches the requesting user for every cached entry (the key includes `uid`, so likely fine, but the backend is resolved via contextvar inside `build_agent`, not the key). **P1 — add an isolation test that builds two users' agents interleaved.**
- **`run_bash` secret-scrub is good** (tools.py:308–312) but pattern-based; a var named `OPENAI_ACCESS` (no KEY/TOKEN/SECRET) would leak. Prefer an allowlist of vars to pass, not a denylist. **P2.**

---

## Prioritized action list

**P0 — do first (they break the core promise):**
1. Wire `grade_and_record` into `AGENT_TOOLS`; rewrite SESSION step (d) to use it; forbid `record_attempt` for code grades (§1.2, §3.1).
2. Fix the web-search prompt/tool mismatch: add `web_search` to `AGENT_TOOLS` (or warm MCP in CLI/TUI) and name one search tool consistently in all prompts (§3.2, §5.2, §5.3).
3. Remove or wire the other dead tools (`diff_code` for the DIFF drill; delete `grade_code`/`run_code` if superseded) (§3.1).

**P1 — high value:**
4. Fix the `_log` shadowing bug in `assist.py` (§5.1).
5. Add `next_concepts()` / curriculum-aware `suggest_focus` so the skill tree actually plans practice (§3.3).
6. Add `concept_level()` so expertise-reversal is enforced, not guessed (§1.3).
7. Add `calibration_report()` + Brier feedback in the debrief (§1.1).
8. Split out an **examiner subagent** (different model) for mock/take-home/AI-interview; add anti-collapse guardrail lines (§2.1, §6.2).
9. Feed the sandbox verdict into the judge (§4.3). Derive `ai_off` deterministically (§2.2).
10. Provider fallback wrapper; LRU-bound the agent cache; add interleaved multi-user isolation test (§7).

**P2 — cleanup / polish:**
11. Reconcile MCP-server vs in-process tool sets from one source (§3.4).
12. Fix the comma-vs-pipe prereq docstring (§3.5).
13. Trim the triple "never show tool output" repetition for prompt-cache stability (§1.4).
14. Judge: verbosity control + note residual self-preference risk; allowlist the bash env (§4.1–4.2, §7).

**The one-line version:** the prompts describe a rigorous, verified, adaptive tutor; the tool wiring currently delivers a model-graded, non-adaptive, web-search-less one in the terminal. Closing the prompt-tool gap (P0 items) turns the existing code into the product the README promises — most of the missing machinery is already written, just disconnected.
