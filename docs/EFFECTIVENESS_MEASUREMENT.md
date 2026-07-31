# Measuring Whether Ekalavya Actually Works

> **Purpose.** A rigorous plan for answering one question honestly: *does using
> Ekalavya cause a learner's coding skill to rise?* Not "does the dashboard number
> go up" — that's cheap and circular — but *does unaided ability improve, and is
> the tutor the reason?* This is fundamentally a **causal-inference / experiment-design**
> problem, so it is treated as one. The design is usable today as an **n=1
> self-experiment** for the owner and repeatable for **opted-in users** later.
>
> **Audience note.** The owner has an econometrics background, so this document
> uses the vocabulary directly (counterfactual, fixed effects, regression to the
> mean, IRT/θ, pre-registration, SCED) and keeps the explanations terse.
>
> **Grounding.** Every "already exists" claim below cites the actual function or
> table. What must be *added* is flagged explicitly. Nothing here proposes code —
> this is the design spec that a later build follows.

---

## 1. The two core threats to any effectiveness claim

Every "Ekalavya works" claim dies to one of two objections. The whole design is
organized around neutralizing them.

### 1a. There is no counterfactual — a trend is not an effect

If unaided accuracy rises from 40% to 70% over eight weeks, that is *not* evidence
the tutor worked. All of these produce the same rising line with zero tutor effect:

- **Maturation.** The learner would have improved anyway (they're actively job-hunting,
  reading, coding daily).
- **History / concurrent studying.** They also grind LeetCode, read docs, ship work
  code, watch a course. Any of these could be the real cause.
- **Test–retest practice effects.** Repeatedly answering *the tutor's own* questions
  makes you better at *the tutor's own questions* — item familiarity, not skill.
- **Regression to the mean.** People start using a tutor when they feel *behind*
  (a local low). Measuring again later shows improvement purely because the first
  measurement was an unusually bad draw.

**The fix is structural, not statistical polish: you need a comparison, not a trend.**
A within-person before/after line is the weakest possible design. Credibility comes
from a *counterfactual* — a period, a skill, or a person that did **not** get the
intervention, against which the treated one is compared. Tiers 1–2 below build exactly
those counterfactuals (frozen benchmark over time, staggered skill starts, delayed-start
users, component randomization).

### 1b. The grader is the ruler — circularity

Ekalavya both **teaches** and **measures**. The Elo in `scoring.update_elo`, the
FSRS state in `scheduling.schedule`, the AI-gap trend in `report.ai_gap` — all move
in response to attempts on items the tutor itself chose, generated, and graded. Two
fatal consequences:

- **Gameable / drift.** If the item generator drifts easier, or the grader loosens,
  every metric improves with zero skill change. The ruler is made of rubber and the
  same hand that teaches holds it.
- **Teaching to the test.** Because the tutor optimizes the same signal it reports,
  improvement on that signal is partly an artifact of alignment between teaching and
  measurement, not transfer.

**The fix: an independent measurement instrument the tutor never teaches from and never
adapts to** — a frozen, externally-scored benchmark (Tier 1) plus real-world outcomes
(Tier 3). The internal metrics stay useful as *dense, cheap, high-frequency* signal;
the independent instrument is the *sparse, expensive, trustworthy* anchor that keeps
them honest. Report both, and watch for divergence — internal metric up while the
independent one is flat is the signature of gaming/drift, and is itself a finding.

---

## 2. Tier 0 — what already exists (near-free signal)

The spine already logs the raw material for a real study. This is the cheapest tier:
it's mostly *surfacing and exporting* signal that's already persisted per attempt.

| Signal | What it measures | Where it lives today |
|---|---|---|
| **Unaided (AI-off) accuracy trend** | Does skill *without help* rise? | `report.ai_gap()` returns `unaided_rate`, `unaided_n`, and a per-day `trend` (last 10 active days), filtered on `attempts.ai_off = 1`. |
| **AI-off ↔ AI-on gap** | The dependency you're trying to close | `report.ai_gap()` → `gap = assisted_rate − unaided_rate`. |
| **Per-skill Elo trajectory** | A latent-ability curve per (pillar, axis) | `scoring.update_elo` writes `ratings.rating`; **every** change is appended to `rating_history(pillar, axis, old_rating, new_rating, created_at)` in `tools.record_attempt`. This history table is the raw ability curve over time. |
| **Calibration (Brier / bias / confidently-wrong)** | "Do you know what you know?" | `progress.calibration(window=50)` already computes `brier`, `bias`, and `confidently_wrong` from `attempts.confidence` × `attempts.correct`. Surfaced as "Clarity" in the Journey ribbon. |
| **FSRS retention on due reviews** | Durable memory, not cramming | `scheduling.schedule` persists per-card `stability`, `difficulty`, `due`, `lapses`, `state_json`; `due_now()` lists due cards. Retention = pass rate on cards reviewed at/after their due date. |
| **Dose** | The independent variable for dose-response | `sessions(planned_min, started_at, ended_at, xp, mode)`; per-attempt `attempts.seconds` (wall-clock, stamped by the spine, not the LLM); `attempts.created_at` timestamps; session counts. |
| **Honesty guards** | Keeps the outcome measure trustworthy | `attempts.cheat_flag`, `attempts.hints_used`, and `progress.looks_pasted`; `attempts.ai_off` marks assisted vs unaided. |

**Gap to close for Tier 0:**

1. **An Effectiveness metrics module.** A pure read-only aggregator (sibling to
   `report.py`) that turns the tables above into study-ready series: unaided-accuracy
   slope with a confidence interval, per-skill Elo Δ over a window, retention rate on
   due reviews, skill-gain-per-hour, and the guardrail (§9). None of these slopes/CIs
   are computed today — `ai_gap()` gives raw per-day rates but no trend estimate.
2. **A per-user effectiveness dashboard panel.** The current dashboard shows the raw
   AI-gap sparkline and per-axis bars (`dashboard.render`) and the Journey shows
   milestones/heatmap/XP curve (`journey.render`) — see §8 for exactly what's already
   there so we don't duplicate. What's missing is the *slope-with-CI* framing.
3. **A tidy per-attempt event export (CSV / parquet).** One row per attempt with:
   `created_at, session_id, pillar, axis, concept, ai_off, correct, confidence,
   seconds, hints_used, cheat_flag` — everything already in `attempts` joined to
   pillar/axis names. This is the offline-analysis substrate (pandas / R). Without it,
   every causal analysis below has to re-query SQLite ad hoc. **Complexity: low** —
   it's a single JOIN and a `to_csv`/`to_parquet`.

> **Honest limit of Tier 0.** Everything here is still measured by the ruler that
> teaches (threat 1b) and has no counterfactual (threat 1a). Tier 0 is *necessary
> instrumentation*, not *proof*. It tells you the internal story richly; it cannot
> by itself defend a causal claim.

---

## 3. Tier 1 — the credibility unlock: a frozen, IRT-calibrated benchmark

This is the single highest-leverage addition. It directly kills threat 1b and provides
the stable outcome variable that all of Tier 2's causal designs measure.

**The instrument.** A held-out item bank the tutor **never teaches from, never adapts
to, and never sees the answers to** during teaching. Administered:

- at **baseline** (before/at first real use),
- then **every N weeks** (e.g. N=2–4),
- **AI-off**, **timed**, **no teaching, no hints, no feedback** during the sitting,
- **objectively scored** (hidden tests / output-match — the `grader = hidden_tests |
  output_match` machinery in `items` already exists; the benchmark reuses it but the
  bank is walled off),
- with **rotating items** drawn from a calibrated pool so the learner sees fresh items
  each sitting — this defeats the test–retest / memorization confound from §1a.

**Why IRT, and why it matters here.** If you rotate items, raw percent-correct is no
longer comparable across sittings — an easy draw inflates the score, a hard draw
deflates it. **Item Response Theory** solves exactly this. Model the probability that
learner with latent ability θ answers item *i* correctly, e.g. the 2-parameter logistic:

```
P(correct | θ, a_i, b_i) = 1 / (1 + exp(−a_i·(θ − b_i)))
```

where `b_i` is item **difficulty** and `a_i` is item **discrimination**. Once the pool
is calibrated (item parameters estimated from many responses), you can rotate items
freely and still recover a **θ on a common scale** — because the item difficulties are
known and divided out. θ is your stable, drift-proof ability score. The **θ slope over
time (with a CI)** is the primary effectiveness outcome (§9).

For an econometrician: IRT is a nonlinear latent-variable model — θ is the person
random effect, `(a_i, b_i)` are item fixed effects, and estimation is MLE/marginal-ML.
It's the psychometric analogue of a fixed-effects panel where you're separating person
ability from item difficulty. This is precisely what lets a *rotating* test remain a
*ruler with fixed gradations*.

**Calibration bootstrapping (practical).** You don't have a calibrated pool on day one.
Options, cheapest first: (i) start with fixed forms and provisional difficulties (author
estimates or LeetCode-style easy/med/hard), report θ under a fixed-item model, and
recalibrate as response data accrues; (ii) once multiple opted-in users exist, jointly
calibrate `(a_i, b_i)` from pooled responses. n=1 alone can't identify item parameters
well — so for the owner's self-experiment, **fix the form** (same items, or matched
parallel forms) and accept the smaller item pool; save full IRT calibration for the
multi-user phase.

**Complexity: medium-high.** New: a walled item bank, an assessment-mode run loop
(timed, no-teach, no-hint — distinct from the normal tutoring loop), a scorer that
reuses existing graders, and a θ estimator (a small library dependency, e.g. `girth`
/ `py-irt`, rather than hand-rolled). The `items` schema and objective graders already
exist; the *isolation guarantee* and the *assessment loop* are the real new work.

---

## 4. Tier 2 — causal designs as the user base grows

With the frozen benchmark (θ) as the outcome, we can now build actual counterfactuals.
Ordered from "works at n=1 today" to "needs a cohort."

### 4a. Rigorous n=1 — multiple-baseline single-case experimental design (SCED)

The gold standard for a single subject. Instead of one before/after, you **stagger the
start of the intervention across several skills**:

- Pick k skills (pillars/axes). Measure all of them repeatedly during a **baseline**
  phase (θ or unaided accuracy per skill).
- Begin *focused Ekalavya intervention* on skill 1 while skills 2..k **stay in
  baseline** (untreated → they are the concurrent control).
- Later, start skill 2; then skill 3; and so on — **staggered starts**.

The causal signature: each skill's trajectory should **bend upward only after its own
intervention begins, and not before**. Because the untreated skills are measured over
the same calendar time, maturation and history (§1a) would lift *all* skills together —
so a change that tracks the *staggered* start times, skill by skill, is very hard to
explain by anything but the intervention. This is a genuine within-subject
counterfactual with n=1.

**Pre-registration is mandatory.** Before starting, write down (timestamped, e.g. a
committed `preregistration_YYYY-MM-DD.md`): the skills, the phase-change dates, the
outcome (θ vs unaided accuracy), and the decision rule. Without pre-registration, SCED
degrades into story-telling — you'll unconsciously call the bend wherever it flatters
the tutor. `sessions.started_at` and per-attempt timestamps already date every phase.

### 4b. Delayed-start / waitlist control across users

The between-person analogue. Randomly assign opted-in users to **immediate access** vs
**delayed start** (waitlisted N weeks). Both are benchmarked on the same schedule.
During the delay window, the waitlist group is a clean control: if the immediate group's
θ rises faster, that difference *is* the tutor effect, net of maturation/history (both
groups live in the same calendar). Ethical bonus: everyone gets access eventually, so
no one is denied the tool — you just randomize *when*.

### 4c. Component / ablation randomization

Which *parts* of Ekalavya carry the effect? Randomize individual mechanisms on/off,
per-user or per-period:

- **AI-off gating** (forced unaided practice) on vs off,
- **the Gauntlet** (assessment/pressure mode) on vs off,
- **spaced repetition** (FSRS `scheduling`) on vs off (e.g. reviews surfaced at FSRS-due
  time vs massed/random).

Each toggle is a mini-RCT that attributes effect to a component, not just the bundle —
and tells you what to keep. `sessions.mode` already records the mode per session, which
is the hook for logging the assigned condition.

### 4d. Dose–response with person fixed effects

Using the per-attempt export (§2) across many person-weeks, regress skill gain on dose
(minutes/attempts) with **person fixed effects** to absorb time-invariant confounders
(baseline ability, grit, background):

```
Δskill_{i,t} = α_i + β·dose_{i,t} + γ·X_{i,t} + ε_{i,t}
```

`α_i` = person FE. A positive, significant β is dose-response evidence. This is
observational (dose isn't randomized), so it's weaker than 4a–4c — but it's *free* once
the export exists, and it's a useful triangulation. Be explicit that reverse causality
(motivated learners both practice more *and* improve faster) is not fully solved by FE;
the randomized designs above are what close that gap.

---

## 5. Tier 3 — external / ecological validity

Even a rising θ on our benchmark is *our* benchmark. The final anchor is whether skill
shows up **in the world**. Track, per opted-in user (self-reported or verified):

- **Interviews passed** / technical-screen pass rate before vs after.
- **Unaided problems solved at work** — real tasks shipped without leaning on AI
  (self-logged; ties directly to the anti-atrophy thesis).
- **An external standardized coding assessment** (e.g. a HackerRank/CodeSignal-style
  test, or a fixed public problem set) taken **before and after** — a third-party ruler
  that shares nothing with Ekalavya's internals.
- **Offers received.**
- **Self-rated confidence** (short scale) — subjective, but it's the felt outcome the
  learner actually cares about.

These are sparse, noisy, and partly self-reported — but they're the only signals
immune to threat 1b, and a correlation between θ-gain and real-world outcomes is what
converts "the number went up" into "the skill is real."

---

## 6. Comparison to other methods

"Does Ekalavya work?" is weaker than "does Ekalavya work **better than the
alternatives**?" The clean design here is an **alternating-treatments single-case
design** across **matched topic blocks**:

- Split the curriculum into matched-difficulty topic blocks.
- Randomly assign each block to a method: **Ekalavya** vs **LeetCode-grind** vs
  **plain-LLM** (just ask ChatGPT/Claude) vs **passive course** (watch/read).
- Study each block under its assigned method for a fixed dose.
- **Measure unaided RETENTION ~1 week later** (AI-off, on held-out items for that block)
  — not immediate performance. Retention-a-week-later is the outcome that actually
  matters and the one where desirable-difficulty methods should win.

The right headline comparison metric is **skill-gain-per-hour** (efficiency), not raw
gain — a method that wins only by consuming more hours hasn't won. Matched blocks +
randomized method assignment + delayed retention test = a fair, within-person bake-off
that most edtech never runs.

---

## 7. The feedback loop (which doubles as training data)

Every effectiveness signal below is also product-improvement and future fine-tuning
data. Two channels:

**Explicit (asked):**
- **1-tap post-drill rating (1–5) + optional text**, tied to the specific
  concept/mode/item — so ratings are attributable, not a global mood. (There is no
  feedback table today; this is new — a small `feedback(attempt_id, concept, mode,
  rating, text, created_at)` table.)
- **Periodic NPS + an open "what's frustrating?"** prompt (e.g. every N sessions).

**Implicit / behavioral (observed, already largely logged):**
- **Return rate** and gap between sessions — derivable from `sessions.started_at`
  / `ended_at`; `report.session_context` already computes `gap_days`.
- **Session length** — `sessions` timestamps + `attempts.seconds`.
- **Drop-off** — sessions abandoned mid-drill.
- **Streak survival** — `progress` streak counters already track this.

**The subtle, important insight.** "Felt good" (explicit satisfaction) can correlate
**inversely** with "actually learned." This is **desirable difficulties** (Bjork):
the practice that produces durable learning — retrieval, spacing, interleaving, being
made to struggle unaided — often feels *harder and less pleasant* in the moment than
re-reading or being handed the answer. So a drill users *love* may be teaching them
less, and a drill they *resent* may be exactly what works. **Do not optimize the tutor
for satisfaction alone.** Instead, *measure that correlation itself* — regress
per-concept explicit rating against later unaided retention for that concept. A negative
coefficient is not noise; it's evidence the desirable-difficulty mechanisms are firing,
and it's a genuine finding worth surfacing. (It also warns against a naive RLHF-style
loop that would sand off the productive friction.)

---

## 8. What to show the user (motivation + self-knowledge)

A **personal effectiveness dashboard**. This serves two ends: motivation (visible
progress sustains the streak) and self-knowledge (an honest mirror). Contents:

- **Unaided-skill trend** — the AI-off accuracy / θ line over time.
- **The closing AI-off ↔ AI-on gap** — the dependency shrinking.
- **Per-pillar strengths / weaknesses** — where you're strong vs where to invest.
- **Retention** — FSRS pass rate on due reviews.
- **Calibration** — Brier / confidently-wrong ("do you know what you know?").
- **Streaks / milestones** — the game HUD.

**What already exists — do not rebuild it:**

- `dashboard.render` already shows: the skill grid (per pillar × axis, from
  `report.grid`), per-axis mastery bars (average rating), the **AI-gap sparkline**
  (unaided-accuracy `trend` bars + the gap), the weakest-cell "quest," due-review count,
  and XP/level/streak.
- `journey.render` already shows: a **milestone timeline**, an **achievements gallery**
  (earned + locked with progress), a 12-week **activity heatmap**, an **XP curve**
  sparkline, and a stat ribbon that already surfaces **calibration as "Clarity"**.

**So the only genuinely new user-facing pieces are:** (1) the **θ / frozen-benchmark
line** from Tier 1, (2) the **slope-with-CI** framing on the unaided trend (today it's
raw per-day bars, no trend estimate), and (3) **retention rate** as an explicit number
(the FSRS state is stored but not summarized as a headline). Everything else is a
re-layout of data already rendered — reuse, don't duplicate.

---

## 9. Numerical measures (the concrete list)

| Role | Metric | Source / status |
|---|---|---|
| **Primary** | **Unaided-accuracy / θ slope on the frozen benchmark, with a CI** | Tier 1 (new). The one trustworthy number. |
| Secondary | AI-off ↔ AI-on **gap** (should shrink) | `report.ai_gap().gap` (exists; needs trend/CI). |
| Secondary | **Per-skill Elo Δ** over a window | `rating_history` deltas (exists; needs aggregation). |
| Secondary | **Calibration (Brier)**, + confidently-wrong count | `progress.calibration` (exists). |
| Secondary | **FSRS retention rate** on due reviews | derive from `cards` + review outcomes (data exists; not summarized). |
| Secondary | **Time-to-mastery** per concept (attempts/days from first-seen to `strong`) | derive from `rating_history` + `ratings.first_seen` (exists). |
| **Efficiency** | **Skill-gain per hour** | Δoutcome ÷ dose (`sessions` minutes + `attempts.seconds`). The right cross-method comparison metric (§6). |
| **Guardrail** | **Does UNAIDED ability rise?** (atrophy check) | `report.ai_gap().unaided_rate` trend / θ. |

**On the guardrail.** This is the project's whole thesis: a tutor that makes *assisted*
performance soar while *unaided* ability stagnates or drops has **failed** — it's
built dependency, i.e. atrophy. The unaided/θ trend must be the metric that can *veto*
a "we're winning" claim. Never let assisted-accuracy or XP stand in for it.

---

## 10. Privacy & ethics for opt-in users

- **Explicit research consent, separate from using the app.** Measurement-for-research
  (pooling data across users, calibrating IRT, running the delayed-start randomization)
  requires an opt-in that is clearly distinct from ordinary use. State what's collected,
  why, and that they can withdraw. The app already has a consent-gating pattern for
  running code (`tui.py`, `cli.py`) — the research consent is the same idea, a new
  scope.
- **Anonymized / aggregated for any cross-user analysis.** IRT calibration and
  dose-response run on de-identified rows; nothing that identifies a user leaves their
  own store without consent.
- **Per-user isolation is already built.** Each user has their **own database** (see the
  per-user `artifacts`/`chats` design and `MULTIUSER_DEPLOYMENT_PLAN.md`), so the
  default posture is isolation; cross-user pooling is an explicit, consented,
  export-time operation — not the norm.
- **Waitlist ethics (Tier 2b).** Randomizing *when* users get access (not *whether*)
  keeps the delayed-start control ethical: no one is denied the tool.

---

## 11. Recommended build sequence

Ordered by leverage-per-unit-effort. Each step notes rough complexity and what the
codebase already covers.

1. **Tier-0 effectiveness module + dashboard panel + per-attempt export.**
   **Complexity: low.** ~90% of the data exists (`report.ai_gap`, `rating_history`,
   `progress.calibration`, `cards`, `sessions`, `attempts`). New work = slope/CI math,
   a summary panel that reuses existing dashboard components, and one JOIN → CSV/parquet
   exporter. *Ship this first — it's cheap and makes everything else analyzable.*

2. **Tier-1 frozen IRT benchmark + assessment mode.**
   **Complexity: medium-high.** The credibility unlock. New = walled item bank, a timed
   no-teach/no-hint assessment loop, θ estimation (small library dep). Reuses existing
   objective graders (`hidden_tests`/`output_match`) and the `items` schema. Start with
   fixed forms + provisional difficulties; add full calibration once multi-user.

3. **Feedback capture.**
   **Complexity: low.** New `feedback` table + a 1-tap post-drill rating and periodic
   NPS. Behavioral signals (return rate, session length, streak survival) are already
   logged — just aggregate them. Doubles as fine-tuning data (§7).

4. **Experiment scaffolding (consent + cohort / delayed-start assignment).**
   **Complexity: medium.** New = a research-consent scope, a condition/assignment record
   per user, and pre-registration hygiene (a committed prereg file per experiment).
   Enables the n=1 SCED (4a), delayed-start (4b), and component ablations (4c). Per-user
   isolation and a consent-gating pattern already exist to build on.

5. **External-outcome tracking.**
   **Complexity: low mechanically, high to collect.** New = a small self-report/verified
   log for interviews, offers, external-assessment scores, confidence. The engineering
   is trivial; the value is entirely in actually gathering it. This is what earns the
   right to say the skill is *real*, not just internal.

> **The through-line:** steps 1 and 5 are cheap and give you the honest internal picture
> and the honest external picture. Step 2 is the expensive middle that makes the internal
> picture *trustworthy*. Steps 3–4 turn a self-experiment into a repeatable study. Build
> in this order and you can make a defensible effectiveness claim at every stage instead
> of waiting for all of it.
