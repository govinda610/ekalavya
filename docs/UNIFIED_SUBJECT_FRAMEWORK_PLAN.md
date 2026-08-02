# Unified Subject Framework — Design Plan

> Status: **PLAN ONLY** (no code changes). Author-facing design doc for making Eklavya's
> effectiveness measurement, scoring, mastery tracking, and journey faithfully span **all
> subjects** — maths, statistics, data science, machine learning, econometrics, CS theory,
> coding today; physics/chemistry/biology/non-sciences later — inside one coherent framework.
>
> Supersedes and expands the subject-aware-axes work (tracker task **#86**); plugs into the
> unified Dashboard/Journey/Effectiveness overview page (task **#83**) and the AI-honesty
> prompt (task **#85**). Read `docs/EFFECTIVENESS_MEASUREMENT.md` first — this plan generalises
> its three-tier credibility spine to every subject without weakening it.

---

## 0. TL;DR

- **~80% of the substrate is already subject-generic.** Pillars, curriculum/forest, attempts,
  XP/streak/level, per-pillar Elo, the AI-off↔AI-on gap, FSRS retention, calibration, dose,
  Tier-2 self-experiment, and Tier-3 outcomes make **no assumption about coding**. They key off
  `(pillar, axis, concept, correct, confidence, ai_off, seconds)` — a subject-neutral event.
- **The coding-specific parts are three, and they are load-bearing:** (1) the frozen 5-axis
  taxonomy `AXES` in `tools.py:20`, hard-wired into the DB, dashboard grid, prompts, and MCP
  tool; (2) the **grading engine** — today grading is either code-execution (`grade_and_record`,
  the tamper-proof spine) or a soft LLM `rubric`, and there is **no principled way to grade a
  derivation, a proof, an econometrics interpretation, or a numeric answer with tolerance**;
  (3) the frozen IRT **benchmark bank** (`benchmark.py:_STARTER_ITEMS`) is entirely coding/CS/SQL.
- **Recommended shape: Option C — Hybrid.** A small **universal competency core**
  (`recall · application · derivation/proof · interpretation · synthesis · transfer`) that every
  subject shares (so cross-subject comparability survives), plus **per-subject axis extensions**
  and, critically, **per-subject grading + benchmark** declared in a `subjects` registry. Never
  force coding axes onto econometrics; never invent a bespoke ruler per subject where a shared
  one is honest.
- **Grading is the crux and gets its own first-class section (§5).** Deterministic graders where
  truth is checkable (code execution, numeric tolerance, symbolic equivalence via SymPy, unit/
  dimensional checks, MCQ keys); a **credible, constrained LLM-judge** — reference-grounded,
  rubric-driven, doc-grounded, self-consistent — where it isn't (proofs, interpretation, essays);
  **partial credit** via rubric points that map into Elo/IRT. This must **not reopen the
  self-grading trust hole** (`EFFECTIVENESS_MEASUREMENT.md §1b`): the judge is a *different* model
  than the tutor, reference-bound, and its verdicts are logged and auditable.
- **All migrations additive + guarded** (mirroring `db/store.py:_migrate`): create-table /
  add-column / seed only. **Never** a `DROP`/`DELETE`/hard wipe. Backfill legacy coding data into
  `subject='coding'` so nothing existing breaks.

---

## 1. Current-state analysis — generic vs coding-specific

Evidence is `file:line` in the worktree at
`/Users/govindmittal/datascience-setup/eklavya-ai-coding-tutor/.claude/worktrees/agent-a4af20edc84f867f7`.

### 1.1 Already SUBJECT-GENERIC (reusable as-is)

| Capability | Where | Why it's generic |
|---|---|---|
| **Pillars** (topic buckets, default + custom from onboarding/repos) | `tools.py:50` `add_pillar`; `schema.sql:9` `pillars` | A pillar is just a named topic — "Econometrics" works as well as "Python idioms". `is_custom` already lets any subject spawn pillars. |
| **Curriculum graph / forest** (concept ← prereqs, per pillar) | `tools.py:151` `add_curriculum`; `schema.sql:136` `curriculum`; `report.py:149` `forest_map` | Pure concept-map with prerequisites and per-pillar groves; nothing coding-specific. `forest_map` derives "done" from *any* correct attempt on a concept name. |
| **Attempts** (the raw learning event) | `schema.sql:54` `attempts`; `tools.py:311` `record_attempt` | Columns are `confidence, correct, seconds, ai_off, hints_used, cheat_flag, detail(concept)` — subject-neutral. The only coding coupling is the **axis** value it stores. |
| **Per-pillar Elo rating + history** | `schema.sql:17` `ratings`, `:145` `rating_history`; `scoring.py:20` `update_elo`; `effectiveness.py:66` `elo` | Elo maths is calibration-driven and difficulty-agnostic; keys off `(pillar, axis)` cells. Works for any axis label. |
| **XP / streak / level / rewards** | `progress.py:48` `award_xp`, `:120` `touch_streak`, `:43` `level_for`; `schema.sql:155` `rewards` | Gamification ledger is subject-blind. |
| **AI-off ↔ AI-on gap** (the guardrail) | `report.py:80` `ai_gap`; `effectiveness.py:42` `unaided` | Filters attempts on `ai_off`; "unaided accuracy rising?" is meaningful for every subject. |
| **FSRS spaced-repetition + retention** | `schema.sql:30` `cards`; `scheduling.py`; `effectiveness.py:105` `retention` | Cards key on a `ref` slug; retention is a pass-rate over graduated cards. Subject-neutral. |
| **Calibration / illusion-of-knowing** | `progress.py:145` `calibration` | Brier/bias/confidently-wrong over `(confidence, correct)` — applies to any graded item. |
| **Dose / effort** | `effectiveness.py:143` `dose` | Minutes/sessions/attempts/active-days — subject-blind. |
| **Tier-2 self-experiment** (intervention starts, prereg) | `experiments.py:40,74`; `schema.sql:284,291` | Keyed by pillar name; multiple-baseline works across subjects. |
| **Tier-3 real-world outcomes** | `experiments.py:105` `record_outcome`; `schema.sql:302` | `kind/label/value/occurred_at` — an econ exam pass logs identically to a coding interview. |
| **Journey / dashboard / effectiveness views** (frames) | `journey.py`, `dashboard.py`, `effectiveness.py:283` `render` | The *scaffolding* (hero, ribbon, sparklines, forest layout) is subject-blind; only the **mastery grid** hard-codes axes. |
| **Attempt export** (offline analysis substrate) | `effectiveness.py:191` `attempt_rows`, `:234` `export_attempts` | Tidy one-row-per-attempt; add a `subject` column and it's fully general. |

### 1.2 CODING-SPECIFIC (must be generalised)

| Coupling | Where | The coding assumption |
|---|---|---|
| **The 5 fixed axes** | `tools.py:20` `AXES = (syntax_recall, debugging, code_reading, api_memory, decomposition)` | These are *coding* competencies. `set_baseline_rating` (`tools.py:74`) and `record_attempt` (`tools.py:330`) hard-reject any axis not in this tuple. |
| Axis coupling radiates outward | `schema.sql:20` (comment enumerates them), `report.py:11` `from .tools import AXES` → `grid()`, `dashboard.py:26` axis→colour map + grid render, `prompts.py:130,310,614` (onboarding/session instructions), `mcp_server.py` | The mastery grid, the tutor's prompts, and the MCP surface all name the five axes literally. |
| **Grading = code-execution or soft rubric only** | `tools.py:377` `grade_and_record` (sandbox tests, tamper-proof); `sandbox.py:75` `run_tests`; `schema.sql:48,241` `grader ∈ {hidden_tests, output_match, rubric, teachback}` | The only **tamper-proof** grader runs *Python tests*. `output_match`/`rubric` are graded by the agent in-prompt (soft). **No** numeric-tolerance, symbolic-equivalence, proof, or interpretation grader exists. This is the single biggest gap for non-coding subjects. |
| **Frozen IRT benchmark bank** | `benchmark.py:55` `_STARTER_ITEMS` (Python, Algorithms, SQL, Data Structures only); `schema.sql:235` `benchmark_items` | The non-circular ruler exists **only for coding/CS**. θ is subject-blind maths, but there are no maths/stats/econ items, and no `subject` column to keep per-subject θ separate. |
| **Verification / self-check judge is coding-framed** | `verify.py:29` `_JUDGE_PROMPT` ("reviewing a CODING TUTOR"), `:86` `_KNOWN_LIBS` (all code libs) | The credibility layer that catches tutor errors is worded and doc-grounded for code/APIs, not proofs or derivations. |
| **XP/level thresholds & rank flavour** | `progress.py:43`, `journey.py:_rank` | Cosmetic, not blocking — but worth a subject-neutral pass. |

**Verdict:** the spine is subject-generic; the *taxonomy*, the *grading engine*, and the *benchmark
bank* are the three things that are coding-shaped and must be lifted into a subject-aware layer.

---

## 2. Design principles

1. **Measure genuine learning honestly, per subject.** The headline stays the guardrail from
   `EFFECTIVENESS_MEASUREMENT.md §9`: *unaided* ability rising, not *assisted* accuracy. This is
   subject-independent and must hold for a proof as much as for a function.
2. **Comparability where meaningful; never forced.** A shared **universal competency core** lets
   "application" or "transfer" be compared across maths and ML. But we **never** score an
   econometrics interpretation on `syntax_recall`. Subjects declare which core axes apply and add
   their own.
3. **Preserve the credibility spine, generalised.** The three tiers survive intact:
   Tier-0 internal signals (Elo/FSRS/gap/calibration), Tier-1 **frozen benchmark → θ** (now
   per-subject), Tier-3 real-world outcomes. The frozen-benchmark firewall
   (`benchmark.py` never feeds teaching) is preserved per subject.
4. **Grading truth-first.** Prefer a deterministic ground-truth grader (execution, numeric
   tolerance, symbolic equivalence, unit check, MCQ key) over an LLM-judge. Use the judge only
   where truth is genuinely non-deterministic (proofs, interpretation, essays), and constrain it
   hard (reference-bound, rubric-driven, doc-grounded, different model) so we **do not reopen the
   self-grading trust hole** (`EFFECTIVENESS_MEASUREMENT.md §1b`).
5. **Partial credit is first-class.** Non-coding items are rarely binary. Rubric-point scoring
   (0..1 fractional) must flow into Elo/IRT without breaking the existing 0/1 pipeline.
6. **Additive + reversible only.** Every schema change is create-table / add-column / seed, guarded
   like `db/store.py:_migrate`. **No destructive op.** Backfill legacy rows to `subject='coding'`.
7. **Simplicity first.** One `subjects` registry + one `subject` tag on the existing event tables
   does most of the work. No per-subject table zoo. Reuse the existing Elo/θ/FSRS engines verbatim.

---

## 3. Options & recommendation

### Option A — One universal axis taxonomy for all subjects
Single fixed axis set (`recall · application · derivation/proof · interpretation · synthesis ·
transfer`) applied to every subject; grading + benchmark generalised behind it.

- **Pros:** maximal cross-subject comparability; smallest schema change (swap the 5 axes for 6);
  one mastery grid shape; trivial dashboard.
- **Cons:** procrustean — "derivation/proof" is dead weight for pure coding practice;
  "syntax_recall" (a genuinely useful coding signal) is lost or crushed into "recall"; can't
  capture subject-idiosyncratic skills (e.g. "assumption-checking" in econometrics, "experimental
  design" in ML). Forces one taxonomy onto domains that legitimately differ.

### Option B — Per-subject axis sets on a shared engine
Each subject declares its own axes, assessment types, and benchmark; the scoring/effectiveness
engine is shared but there is **no** common axis vocabulary.

- **Pros:** maximal fidelity per subject; nothing forced.
- **Cons:** kills cross-subject comparability (no shared axis to compare "application" in maths vs
  ML); dashboard becomes N disjoint grids; harder to answer "where should I invest across
  everything?". More authoring burden and drift risk.

### Option C — Hybrid: universal core + per-subject extensions  ✅ RECOMMENDED
A small **universal competency core** every subject shares, PLUS optional **subject-specific axes**.
Each subject is a row in a `subjects` registry declaring: its core-axis subset, its extension axes,
its allowed **answer types + graders**, and its **benchmark tag**.

- **Universal core (6):** `recall`, `application`, `derivation_proof`, `interpretation`,
  `synthesis`, `transfer`. (Definitions in §4.1.)
- **Per-subject extensions (examples):** coding adds `debugging`, `code_reading`, `api_memory`;
  econometrics adds `assumption_checking`, `model_specification`; ML adds `experimental_design`,
  `failure_diagnosis`.
- **Pros:** keeps cross-subject comparability on the 6 core axes (the dashboard can always compare
  "application" everywhere) **and** subject fidelity via extensions; the existing 5 coding axes map
  cleanly (`syntax_recall/api_memory→recall`-family kept as coding extensions, `debugging` etc.
  retained); one engine, one grid shape (core columns always present, extension columns shown only
  for that subject); smallest honest schema surface.
- **Cons:** slightly more registry machinery than A; must define a clean **mapping** from the legacy
  5 axes to the new core (given below) so history stays interpretable.

**RECOMMENDATION: Option C.** It's the only option that satisfies *both* invariants in Principle 2 —
comparability **and** non-coercion — while reusing the existing Elo/θ/FSRS spine unchanged. A is
too rigid for econometrics/proof-heavy subjects; B throws away the cross-subject "where do I invest?"
question the effectiveness view exists to answer.

---

## 4. Per-dimension design under Option C

### 4.1 Competency model (axes) per subject

**Universal core axes (shared vocabulary, always comparable):**

| Core axis | Meaning (subject-independent) |
|---|---|
| `recall` | Retrieve a fact/definition/formula/API from memory. |
| `application` | Apply a known method to a standard problem. |
| `derivation_proof` | Derive a result / construct or critique a proof / show steps rigorously. |
| `interpretation` | Read a result/output/dataset/model and say what it *means* (the crux for stats/econ). |
| `synthesis` | Combine multiple ideas into a novel solution / design. |
| `transfer` | Apply a skill in an unfamiliar context (the anti-atrophy, real-learning signal). |

**Subject axis maps (core subset + extensions):**

| Subject | Core axes used | Subject extensions |
|---|---|---|
| **Coding** | recall, application, transfer | `debugging`, `code_reading`, `api_memory` *(legacy `syntax_recall`→`recall`, `decomposition`→`synthesis`)* |
| **Mathematics** | recall, application, derivation_proof, transfer | `symbolic_manipulation`, `counterexample_construction` |
| **Statistics / Econometrics** | recall, application, derivation_proof, interpretation, transfer | `assumption_checking`, `model_specification`, `inference_validity` |
| **ML / DS theory** | recall, application, derivation_proof, interpretation, synthesis, transfer | `experimental_design`, `failure_diagnosis`, `metric_selection` |
| **CS theory** | recall, application, derivation_proof, transfer | `complexity_analysis`, `reduction_construction` |
| **Physics/Chem/Bio (later)** | recall, application, derivation_proof, interpretation, transfer | e.g. `dimensional_analysis`, `mechanism_reasoning` (declared when added) |

**Legacy migration mapping (coding axes → new world):** keep `debugging`, `code_reading`,
`api_memory` verbatim as coding **extensions**; map `syntax_recall → recall` and
`decomposition → synthesis` (both keep their historical ratings by writing the mapped axis name at
migration). This preserves every existing rating and history row (§6).

### 4.2 Mastery & scoring (Elo / IRT), per subject

- **Elo (Tier-0 grid):** unchanged maths (`scoring.py:update_elo`), now keyed on
  `(subject, pillar, axis)` instead of `(pillar, axis)`. Difficulty stays calibration-driven
  (confidence-vs-outcome surprise) — no code assumption. **Partial credit** feeds in by replacing
  the binary `score ∈ {0,1}` with `score ∈ [0,1]` (the rubric fraction); the update formula already
  uses `score - _TARGET`, so a 0.7 works natively. `_CONFIDENCE_P` and calibration stay as-is.
- **IRT / θ (Tier-1 benchmark):** the Rasch estimator (`benchmark.py:estimate_theta`) is already
  subject-blind — it only consumes `(difficulty_logit, correct∈{0,1})`. Generalise by:
  (a) tagging benchmark items and assessments with `subject`, computing **θ per subject** (one ruler
  per subject — you cannot compare a maths θ to a coding θ, and shouldn't); (b) for partial-credit
  benchmark items, threshold the rubric fraction at a declared cutoff (default ≥ 0.5 = correct) to
  keep the 1PL binary, **or** later upgrade to a graded-response model — v1 uses the threshold
  (documented, extensible, mirrors the existing "fixed-difficulty v1" pragmatism).
- **Per-subject item difficulty:** authored `1..5` as today (`benchmark.py:_b_of`), independent per
  subject bank. No cross-subject difficulty comparison is implied or shown.

### 4.3 Effectiveness metrics, generalised

Every Tier-0/1/3 metric already reads generic event columns; adding a `subject` tag lets each be
computed **overall and per-subject**:

- **Unaided vs assisted gap** (`report.ai_gap`, `effectiveness.unaided`): group by `subject`; the
  guardrail verdict banner (`effectiveness.render`) gains a per-subject breakdown ("unaided rising in
  Stats, flat in ML").
- **Retention / spacing** (`effectiveness.retention`): cards already carry a `ref`; add subject to the
  card so retention is reportable per subject.
- **Transfer:** a first-class core axis (§4.1) — surface `transfer`-axis unaided accuracy as its own
  effectiveness line per subject (this is the anti-atrophy proof).
- **Calibration / illusion-of-knowing** (`progress.calibration`): filter by `subject`; a learner may
  be well-calibrated in coding but overconfident in econometrics — exactly the insight this unlocks.
- **Dose** (`effectiveness.dose`): per-subject minutes/attempts, so dose-response can be read per
  subject.
- **θ trajectory** (`benchmark.history`): per-subject θ series; the effectiveness view shows one θ
  sparkline per active subject.

### 4.4 Assessment / benchmarks, per subject (credible without code execution)

Each subject ships a **frozen, walled item bank** (never taught from) tagged with `subject`. The
firewall property (`benchmark.py` is the only reader; teaching loops never draw from
`benchmark_items`) is preserved per subject. Keeping them credible **without code execution**:

- **Objective-key items** (numeric/symbolic/MCQ/short-answer with a canonical answer) graded by the
  **deterministic** graders in §5 — these are as tamper-proof as code tests.
- **Reference-solution rubric items** (proofs, derivations, interpretation) graded by the constrained
  LLM-judge (§5.2) against a stored reference + rubric; the judge is a *different* model, its verdict
  and per-criterion scores are logged in `assessment_responses`, and periodic **human spot-audit**
  (owner reviews a sample) keeps drift honest — mirroring the Tier-1 "trust but audit" stance.
- **Rotation + freshness** (`benchmark.select_items`) works unchanged per subject bank (avoid
  recently-seen items → defeats memorisation).
- **Starter banks to author** (small, like the coding one): Maths (algebra/calculus/linear algebra),
  Stats/Econometrics (probability, inference, OLS assumptions, interpretation), ML/DS theory
  (bias-variance, regularisation, evaluation), CS theory (complexity, computability). ~15–25 items
  each, difficulty 1..5, half objective-key + half reference-rubric.

### 4.5 Journey / timeline / dashboard / forest surfacing

- **Forest map** (`report.forest_map`): already per-pillar groves. Group groves **by subject** into
  labelled regions ("the Coding grove", "the Econometrics grove"). No layout rewrite — add a subject
  band; the winding-path layout (`_forest_layout`) scales as-is.
- **Mastery grid** (`report.grid`, `dashboard`): render **core axes always** + the active subject's
  extension axes; switchable per subject. The grid stops being a single 5-column table and becomes a
  per-subject grid with a shared 6-column core.
- **Journey** (`journey.milestones`): "Mastered {subject} · {pillar} · {axis}" — already string-built
  from `rating_history`; just include subject. XP/streak/achievements stay global (one journey across
  all subjects) — that's a feature, not a bug: the learner sees one unified arc.
- **Effectiveness view** (`effectiveness.render`): a per-subject strip (θ sparkline + unaided verdict
  + gap) under the global verdict banner. This *is* the surface for task #83 (§7).

---

## 5. GRADING ENGINE (the crux for non-coding subjects)

> You cannot unit-test a proof or an econometrics interpretation. Grading is therefore the pivotal
> design problem for going beyond coding. This section is first-class and reconciles with the
> existing trust model so we **never reopen the self-grading trust hole**
> (`EFFECTIVENESS_MEASUREMENT.md §1b`; `tools.py:377` `grade_and_record`).

### 5.0 The trust hole we must not reopen

The whole credibility argument (`EFFECTIVENESS_MEASUREMENT.md §1b`) is: *the hand that teaches must
not be the hand that grades the ruler*. Today the tamper-proof grader
(`grade_and_record`) side-steps this by running **objective sandbox tests** validated against the
tutor's own reference — the *outcome is not the model's opinion*. For non-coding answers we have no
sandbox, so the guiding rule is:

> **Deterministic-first.** Grade with a ground-truth checker whenever the answer type admits one.
> Only fall back to an LLM-judge when truth is genuinely non-deterministic — and then constrain the
> judge so hard (reference-bound, rubric-driven, doc-grounded, *different model*, logged, auditable)
> that it can't silently drift the ruler. The judge scores *against a stored reference*, it does not
> invent the truth.

### 5.1 Grading matrix — per subject × answer type

| Answer type | Example subjects | Grader (preferred → fallback) | Ground truth? |
|---|---|---|---|
| **Code (execution/tests)** | coding, ML impl | `grade_and_record` sandbox (unchanged, `tools.py:377`) | Yes (deterministic) |
| **Numeric answer** | maths, stats, physics | **numeric checker**: exact, else abs/rel **tolerance**; scientific-notation & unit-aware | Yes |
| **Symbolic / algebraic answer** | maths, ML derivations | **SymPy equivalence**: parse both sides, `simplify(a-b)==0` / `equals()`; accepts equivalent forms | Yes |
| **Unit / dimensional** | physics, econ (units) | **dimensional check**: `pint`/SymPy units — right magnitude *and* dimension | Yes |
| **MCQ / true-false / cloze** | any | **key match** | Yes |
| **Short-answer (canonical key)** | any | **normalised key match** (case/whitespace/synonym-lenient) → judge only if near-miss | Mostly |
| **Derivation / worked multi-step** | maths, stats, ML | **step rubric**: deterministic checks on key intermediate results where possible + judge on reasoning steps | Partial |
| **Proof** | maths, CS theory | **LLM-judge (constrained)** against reference proof + rubric (structure, validity, no gaps) | No → judged |
| **Statistical/econometric interpretation** | stats, econ | **LLM-judge (constrained)** against reference interpretation + rubric (correct direction, magnitude, caveat/assumption) | No → judged |
| **ML/DS conceptual explanation** | ML, DS theory | **LLM-judge (constrained)** against reference + rubric (correctness, completeness, no misconception) | No → judged |
| **Open-ended essay** | non-sciences, design | **LLM-judge (rubric only)**, lower stakes; excluded from Tier-1 θ by default (too noisy for the ruler) | No → judged |

### 5.2 The grading engine design

A single **`grade()` dispatcher** picks a grader from the item's declared `answer_type` + subject.
Two tiers of grader:

**(a) Deterministic graders (ground-truth, tamper-proof — the strong path):**
- **Code execution** — reuse `sandbox.run_tests` verbatim; keep the reference-validates-tests
  self-check (`grade_and_record`) that makes it tamper-proof.
- **Numeric checker** — parse the learner's numeric answer, compare to the key with configurable
  absolute/relative tolerance (declared per item); handle sig-figs, `%`, scientific notation, and an
  optional unit. Deterministic → as trustworthy as code tests.
- **Symbolic checker (SymPy)** — `sympify` both expressions; verdict = `simplify(lhs-rhs)==0` (or
  `.equals()` for transcendental cases), so `sin^2+cos^2` == `1` and `(x+1)^2` == `x^2+2x+1`. Accepts
  **equivalent forms** — the classic "is my algebra right?" grader.
- **Unit / dimensional checker** — verify dimension and magnitude (SymPy units / `pint`).
- **Key match** — MCQ / cloze / canonical short-answer, with a normalisation pass.

These are **new tools with no LLM in the loop**, so they extend the tamper-proof guarantee to maths
and stats. They are the preferred path and the backbone of per-subject Tier-1 benchmarks.

**(b) Constrained LLM-judge (only where truth is non-deterministic):**
Built on the *existing* verification layer (`verify.py` — v3 doc-grounded, context-aware, different
model, fail-open) rather than a new ungrounded judge. Concretely, a **`rubric_judge()`** that:
1. is given the **item prompt, the learner's answer, a stored reference solution, and an explicit
   structured rubric** (list of criteria, each with a point weight and a pass/partial/fail
   description) — it scores *against the reference*, it does not decide truth from its own memory;
2. runs on a **different provider than the tutor** (reuse `verify._judge_provider_key` — cuts
   self-preference bias, the same defence `verify.py:127` already uses);
3. is **doc-grounded** where the claim is checkable (reuse `verify.ground_docs` via Context7 for a
   library/statistical-method claim);
4. uses **self-consistency**: sample the judge k=3 times at low temperature and take the median /
   majority per criterion — reduces judge variance, a standard LLM-judge reliability tactic;
5. returns **structured per-criterion scores** (JSON, like `verify.parse_verdict`) → a rubric
   fraction in `[0,1]`, **not** a bare pass/fail;
6. is **biased toward the reference**: if the deterministic checks on any objective sub-part fail,
   those points are lost regardless of the judge's prose verdict (deterministic overrides judge on
   the parts it can check);
7. **logs everything** (prompt, reference, rubric, per-criterion verdict, model used, k-sample raw)
   for **human spot-audit** — the auditability that keeps the ruler honest without a sandbox.

**Reconciliation with the trust model:** the judge never grades a *frozen benchmark* item that a
deterministic grader could handle; for the reference-rubric benchmark items it can't avoid, the
different-model + reference-bound + logged + human-audited stance is the documented substitute for the
sandbox. In *teaching* loops (Tier-0), a judged rubric score is allowed but is clearly a softer signal
than a deterministic one — and the guardrail metric (unaided θ on the frozen bank) is what the product
ultimately trusts, exactly as today.

### 5.3 Partial credit → Elo / IRT / axes

- Grading returns a **rubric fraction `score ∈ [0,1]`** plus a per-criterion breakdown, not just a
  bool. Store both: `attempts.correct` stays (thresholded, e.g. `score ≥ 0.5`, for backward compat and
  binary Tier-1), and a new `attempts.score REAL` holds the fraction.
- **Elo** consumes the fraction directly (`update_elo` already computes `score - _TARGET`), so a
  0.7 on a hard proof nudges the rating proportionally.
- **Axes:** a rubric's criteria can be **axis-tagged** (e.g. a stats item's "correct sign/direction"
  criterion → `interpretation`, its "checked OLS assumptions" criterion → `assumption_checking`), so
  one multi-part answer can update several axis cells with the right partial weights. This is how a
  worked econometrics solution faithfully feeds *multiple* competencies at once.
- **IRT/θ:** binary per §4.2 (threshold the fraction); documented v1, upgradeable to a graded-response
  model later.

### 5.4 Per-subject anti-cheat + AI-honesty (generalising #85)

The honesty spine today keys on code-specific tells (`progress.looks_pasted`, `attempts.hints_used`,
`attempts.cheat_flag`, `attempts.ai_off`) plus the AI-interview planted-bug review
(`assist.py`). Generalising to non-coding answers:

- **Unassisted (AI-off/on) tracking is already subject-neutral** — `ai_off` is a flag on the attempt.
  The honesty prompt of task **#85** ("did you use AI / Google / a solver for this?") is asked the same
  way for a proof or a numeric answer as for code; the learner's self-report sets `ai_off`. This is the
  primary, subject-independent honesty signal and it needs *no* change — just apply it to every subject.
- **Cheat heuristics per answer type:** `looks_pasted` (large paste with no edit history) generalises
  from code to any text answer (a pasted full proof / interpretation). Add cheap tells: an answer that
  arrives implausibly fast for its rubric complexity (`seconds` vs difficulty), or a symbolic answer in
  a canonical form no human derivation-in-progress would produce. All soft flags → `cheat_flag`, never
  a hard block (mirrors the current stance).
- **Benchmark integrity:** frozen items are AI-off by protocol (Tier-1); the honesty prompt + rotation
  (avoid recently-seen items) is the same defence per subject.
- **Judge as an anti-cheat aid:** the rubric-judge can flag "this answer restates the reference verbatim
  without derivation" as a partial/withhold signal — useful for proofs/essays where paste-detection is
  otherwise weak.

### 5.5 Answer→grade→mastery→journey pipeline (unified across subjects)

```
learner submits answer
  → dispatcher reads item {subject, answer_type, grader, reference, rubric, tolerance}
  → DETERMINISTIC grader if answer_type admits one (code/numeric/symbolic/unit/key)
       else CONSTRAINED rubric_judge (different model, reference+rubric, doc-grounded, k-sample)
  → returns {score∈[0,1], per_criterion[], verdict}
  → record: attempts(subject, pillar, axis, concept, correct=score≥τ, score, confidence, seconds,
             ai_off, hints_used, cheat_flag)                       [tamper-proof: score set by grader]
  → per axis-tagged criterion: update_elo(subject,pillar,axis, score_fraction) + rating_history
  → FSRS schedule(concept) ; award XP ; touch streak
  → (if a frozen-benchmark sitting) record_assessment(subject, outcomes) → per-subject θ
  → effectiveness.* (gap/retention/calibration/θ) and journey/forest read it, grouped by subject
```

Every arrow already exists for coding (`grade_and_record → record_attempt → scoring → progress →
effectiveness`); the plan **inserts the dispatcher + non-code graders at the front** and **threads
`subject` through**, leaving the downstream spine intact.

### 5.6 Grader infrastructure / tools (plug into `AGENT_TOOLS`)

New tools, added to the unified toolset (`tools.py:666 AGENT_TOOLS`), each doing one deterministic
thing (like the existing spine tools) so the model can't fake the outcome:

| Tool | Does | Depends on |
|---|---|---|
| `grade_numeric(answer, key, tol, rel, unit)` | tolerance/unit-aware numeric verdict + fraction | stdlib / `pint` (optional) |
| `grade_symbolic(answer, reference)` | SymPy equivalence verdict | `sympy` (new dep) |
| `grade_units(answer, reference)` | dimensional + magnitude verdict | `sympy`/`pint` |
| `grade_choice(answer, key)` | MCQ/cloze/short-answer key match | stdlib |
| `grade_rubric(answer, reference, rubric, subject, context)` | constrained judge → per-criterion fractions | `verify.py` layer, providers |
| `grade_and_record_subject(...)` | dispatcher: pick grader, then record via the unified pipeline (tamper-proof, subject-aware) | all of the above |

`grade_and_record` (code) stays as the code path; `grade_and_record_subject` generalises it. SymPy is
the one genuinely new runtime dependency (small, pure-Python, well-documented); `pint` is optional for
units. The rubric-judge reuses the existing provider + Context7 plumbing — no new infra.

---

## 6. Data model changes (all ADDITIVE + guarded)

Mirror `db/store.py:_migrate` exactly: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN`
(guarded by a `PRAGMA table_info` check), and idempotent seeds. **No `DROP`, no `DELETE`, no hard
wipe.** Backfill legacy rows to `subject='coding'`. Bump `SCHEMA_VERSION` and extend
`migrate.py:_PARITY_TABLES` with the new tables so the multi-user copy still verifies parity.

**New tables:**

```sql
-- The subject registry: one row per subject, declaring its axes, answer types, and benchmark tag.
CREATE TABLE IF NOT EXISTS subjects (
    id           INTEGER PRIMARY KEY,
    key          TEXT NOT NULL UNIQUE,     -- 'coding' | 'maths' | 'stats' | 'ml' | 'cs_theory' | ...
    name         TEXT NOT NULL,
    core_axes    TEXT NOT NULL,            -- pipe-list of universal-core axes this subject uses
    ext_axes     TEXT,                     -- pipe-list of subject-specific extension axes
    answer_types TEXT,                     -- pipe-list of allowed answer types (code|numeric|symbolic|...)
    is_custom    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Optional: an explicit axis catalog (label → kind core|ext, description) for UI/validation.
CREATE TABLE IF NOT EXISTS axes (
    id      INTEGER PRIMARY KEY,
    key     TEXT NOT NULL UNIQUE,          -- 'recall' | 'derivation_proof' | 'debugging' | ...
    kind    TEXT NOT NULL DEFAULT 'core',  -- core | ext
    label   TEXT
);
```

**Additive columns (guarded add-column, default backfill to keep legacy valid):**

| Table | New column | Default / backfill |
|---|---|---|
| `attempts` | `subject TEXT` | `'coding'` on legacy rows |
| `attempts` | `score REAL` | `NULL` legacy; equals `correct` where only binary known |
| `attempts` | `answer_type TEXT` | `'code'` on legacy |
| `ratings` | `subject TEXT` | `'coding'`; **relax** `UNIQUE(pillar_id,axis)` → `UNIQUE(pillar_id,axis,subject)` via additive new-table copy (guarded, non-destructive: create new, copy, keep old until verified — never a drop) |
| `rating_history` | `subject TEXT` | `'coding'` |
| `pillars` | `subject TEXT` | `'coding'` |
| `curriculum` | `subject TEXT` | `'coding'` |
| `cards` | `subject TEXT` | `'coding'` |
| `benchmark_items` | `subject TEXT` | `'coding'`; θ computed per subject |
| `benchmark_items` | `answer_type TEXT`, `tolerance TEXT`, `rubric TEXT` | for numeric/symbolic/rubric graders |
| `assessments` | `subject TEXT` | `'coding'` (per-subject θ) |
| `assessment_responses` | `score REAL`, `criteria_json TEXT` | partial-credit + judge audit trail |

> **Note on `ratings` uniqueness:** adding `subject` to the key requires a table rebuild (SQLite can't
> alter a UNIQUE constraint in place). Do it the **reversible** way used elsewhere in this codebase:
> create `ratings_v2` with the new constraint, `INSERT ... SELECT` (stamping `subject='coding'`),
> verify row parity (like `migrate.py`), then swap names — **keeping the old table** until parity is
> confirmed. No data is ever deleted; a failed migration leaves the original intact.

**Legacy axis remap at migration:** when stamping `subject='coding'`, also remap axis labels per §4.1
(`syntax_recall→recall`, `decomposition→synthesis`) so historical ratings land on the new core;
`debugging/code_reading/api_memory` stay as coding extensions. This is a value update on copied rows,
fully reversible.

**Seeds (idempotent, like `benchmark.seed_items`):** insert the `subjects` rows, the `axes` catalog,
and the per-subject frozen starter item banks — only if absent (matched on `key`/`prompt`), never
overwriting.

---

## 7. Plugging into tasks #83 and #86

### Task #83 — unified Dashboard / Journey / Effectiveness overview page
This plan is the **data backbone** for #83. Once every metric carries `subject`, the overview page
renders:
- a **global** verdict banner + θ/gap/calibration (all subjects), then
- a **per-subject strip**: for each active subject, its θ sparkline (frozen-bench, non-circular),
  unaided-rising verdict, gap, and top strengths/weaknesses — reusing `effectiveness.render`'s existing
  card/sparkline idioms (`effectiveness.py:317 _spark`), just iterated per subject;
- the **forest** grouped into per-subject regions (§4.5), and a **journey** that stays one unified arc
  with subject-tagged milestones.
No new view engine — #83 becomes "iterate the existing cards over `subjects`".

### Task #86 — subject-aware axes (this plan supersedes/expands it)
#86 (make axes subject-aware) is the **first slice** of this plan. This document expands it from "let
axes vary by subject" to the full framework: the universal-core+extension taxonomy (§4.1), the grading
engine that makes non-coding axes *measurable* (§5), per-subject benchmarks/θ (§4.4), and the additive
data model (§6). Implementing #86 should follow §4.1 + §6's `subjects`/`axes` tables rather than a
narrower one-off, so it doesn't need redoing.

### Task #85 — AI-honesty prompt
Generalised in §5.4: the "did you use AI/Google/a solver?" self-report drives `ai_off` identically for
every subject and answer type; no coding assumption. #85's prompt should be asked subject-agnostically.

---

## 8. Phasing / sequencing

1. **P1 — Registry + tagging (additive, no behaviour change).** Add `subjects`/`axes` tables; add
   `subject` columns (guarded, backfill `'coding'`); remap legacy coding axes; extend
   `migrate._PARITY_TABLES`; bump `SCHEMA_VERSION`. *Verify:* all existing tests pass, coding data
   intact, parity check green. **Nothing user-visible yet.**
2. **P2 — Universal-core axes + subject-aware Elo/grid.** Introduce the 6 core axes; make
   `record_attempt`/`set_baseline_rating` accept `(subject, axis)` validated against the registry;
   `report.grid`/dashboard render core + active-subject extensions. *Verify:* coding still shows its
   axes; a second subject can be onboarded and rated.
3. **P3 — Deterministic graders.** Ship `grade_numeric`, `grade_symbolic` (SymPy), `grade_units`,
   `grade_choice`, and `grade_and_record_subject` dispatcher + `attempts.score`. *Verify:* a maths
   numeric item and a symbolic item grade tamper-proof end-to-end and update the right axis cells.
4. **P4 — Constrained rubric-judge + partial credit.** Build `grade_rubric` on the `verify.py` layer
   (different model, reference+rubric, doc-grounded, k-sample, logged); wire per-criterion axis-tagged
   partial credit. *Verify:* a proof and an econ-interpretation item produce stable, auditable
   fractional scores; human spot-audit sample looks right.
5. **P5 — Per-subject frozen benchmarks + θ.** Author starter banks (maths/stats/ML/CS); tag items;
   compute per-subject θ; effectiveness view shows per-subject θ. *Verify:* per-subject `assess` loop
   yields a θ; frozen firewall holds (teaching never draws from `benchmark_items`).
6. **P6 — Surfacing (task #83).** Per-subject strips on the effectiveness/overview page; subject-banded
   forest; subject-tagged journey milestones; per-subject calibration/gap/retention.
7. **P7 — Honesty generalisation (task #85) + non-coding anti-cheat tells.** Subject-agnostic AI-use
   prompt; generalise `looks_pasted`; speed/formality soft-flags.

Each phase ends at a real gate (tests green, data reversible) before the next — matching the project's
phase-gate working method.

---

## 9. Risks & open questions

**Risks / mitigations:**
- **LLM-judge drift reopening the trust hole.** *Mitigation:* deterministic-first; judge only for
  genuinely open answers; reference-bound + different model + k-sample + logged + human spot-audit; the
  product's trusted headline stays the deterministic/objective θ. (§5.0, §5.2)
- **SymPy false negatives** (two correct answers it can't prove equal). *Mitigation:* numeric spot-check
  fallback (evaluate both at random points) before declaring "wrong"; allow author to store multiple
  accepted forms.
- **`ratings` UNIQUE rebuild.** *Mitigation:* the copy-verify-swap, keep-old pattern (§6) — never a drop.
- **Benchmark authoring burden.** *Mitigation:* small starter banks (like coding's ~20 items); grow over
  time; rubric items reuse reference+rubric authoring the tutor already does for lessons.
- **Cross-subject θ misread as comparable.** *Mitigation:* never place two subjects' θ on one axis; label
  each ruler by subject.

**Open questions for the user:**
1. **Subject taxonomy granularity:** is "Stats/Econometrics" one subject or two? Is "ML/DS theory"
   separate from "coding-for-DS"? (Affects the registry rows and benchmark banks.)
2. **Judge cost tolerance:** k=3 self-consistency triples judge calls on open-ended items — acceptable,
   or k=1 with human-audit-only for the ruler?
3. **SymPy as a hard dependency** vs optional (numeric-only maths grading if absent)? Recommend hard —
   it's the backbone of maths grading.
4. **Partial-credit threshold τ** for the binary `correct`/Tier-1 (default 0.5) — one global value or
   per-subject?
5. **Essay/open-ended in Tier-1 θ:** keep excluded (too noisy) or include with a wide rubric? Recommend
   exclude from the ruler, keep in Tier-0 teaching.
6. **Legacy axis remap:** OK to map `syntax_recall→recall` / `decomposition→synthesis` (preserving
   ratings), or keep all five as coding extensions and leave the core empty for coding? (Recommend the
   remap — it makes coding comparable on the core.)

---

*End of plan. No application code or tests were modified; the only file written is this document.*
