# Mode Research — the "Gauntlet" and what else is worth building

**Date:** 2026-08-01
**Question:** Is the proposed endless, escalating, weakness-targeting "gauntlet" mode genuinely valuable and distinct, or redundant with what Ekalavya already has? And what *other* modes/features from games and learning platforms would add real impact without unnecessary complexity?
**Method:** Web research across coding/learning platforms (boot.dev, Codewars, Exercism, LeetCode, Codecrafters, Execute Program, Duolingo), game-design patterns (roguelite, AI Director, Nemesis, DDA), and the learning-science literature (desirable difficulties, spacing/interleaving/retrieval, mastery learning, deliberate practice, flow/ZPD, adaptive testing/IRT, self-determination theory).

---

## TL;DR verdict

**Build the gauntlet — but build the *right* one.** The core idea (adaptive, weakness-targeting, escalating, teaches-as-it-goes) is squarely on-thesis and reuses ~90% of infrastructure Ekalavya already has (Elo per skill, weak-cell tracking, verified grader, FSRS, death retheme). Its distinctiveness is real: no competitor combines *adaptive difficulty + explicit weakness-targeting + a single continuous session + teaching in the loop*. The one genuine risk — the "makes them restart on failure" part — is the exact mechanic the motivation literature warns kills competence and drives churn. So the verdict is: **build it, but make the restart a *fresh attainable challenge*, not a punishment that erases progress.** Details below.

The gauntlet should be one of the first new things you build. But it is not the only high-value thing, and a couple of the obvious adjacent ideas (a Nemesis system, PvP leagues) are traps.

---

## Part A — The Gauntlet: verdict, rationale, reuse vs. new complexity

### Is it distinct, or redundant?

Ekalavya already has: **daily practice** (gated, FSRS-scheduled review), **story/skill-tree** (structured progression), and **mock/interview modes** (timed, evaluative). Where does an endless gauntlet fit?

It is genuinely distinct because it occupies a slot none of those fill: a **single, continuous, self-selected "sharpen me on my weak spots right now" session with rising stakes.** This is the exact slot that boot.dev calls "sharpen your skills," that Codewars fills with a rank-appropriate kata stream, and that Zetamac/typing sites fill with escalating-speed runs. It's the "I have 25 focused minutes and want to be pushed" mode. Daily practice is *obligation-shaped* (a to-do list gated by the FSRS scheduler); the gauntlet is *appetite-shaped* (an on-demand challenge you reach for). Those are different psychological products even if they share a grader.

Two things make Ekalavya's version better than any competitor's "sharpen" mode:

1. **It targets recorded weaknesses.** Deliberate-practice research (Ericsson) is unambiguous that the thing that separates expert-producing practice from mere repetition is *ruthless focus on identified weaknesses* — the very thing casual practice avoids because it isn't fun. Ekalavya already records weak cells; a mode that *forces* the learner into their weak cells is the single most evidence-aligned feature you could ship. No mainstream platform does deliberate weakness-targeting well — they let you pick, and people pick what they're already good at.

2. **It's adaptive in a Left-4-Dead-AI-Director sense.** The AI Director keeps a hidden difficulty value that rises when you do well and falls when you struggle, spawning relief (items, weaker hordes) when you're low and pressure when you're cruising — explicitly to hold players in *flow*. Ekalavya's per-skill Elo is functionally the same hidden difficulty value. A gauntlet that picks each next challenge by Elo-matching (with a slight upward bias) *is* an AI Director for skill acquisition, and it is also, formally, **computerized adaptive testing** (CAT/IRT): pick the most informative next item for the current ability estimate, update the estimate on each response. You already have the ability estimate. This is the cheapest, most principled difficulty engine you could build, and it's already 80% built.

### The one real danger: "restart on failure"

Here is where the design has to be careful. The literature is blunt: **punishment-based, controlling mechanics thwart the need for competence and produce durable demotivation** (self-determination theory). Repeated failure that erases accumulated progress undermines perceived competence and pushes learners toward amotivation and heightened punishment-sensitivity. A gauntlet where death wipes a long run and dumps you at zero is a competence-crushing machine — it will feel great for the top 5% and drive everyone else away.

But the same literature offers the escape hatch, and it's exactly what you asked for ("keeps them hopeful, teaches as it goes"):

- **Competence *frustration* followed by an attainable competence-supportive opportunity actually *strengthens* motivation.** Failure re-energizes rather than demotivates *when the next thing is a genuine, winnable challenge.* So the restart must reset into something clearly beatable, not a wall.
- **Shadow of Mordor's key insight**: player death is not an end-state, it's an *opportunity to avenge* — the game turns your failure into the next story beat. Ekalavya's Souls-like death retheme is already philosophically here. Lean into "you died to closures again; here's your rematch," not "run over, -3 lives."
- **Roguelite meta-progression** exists precisely to make permadeath tolerable: you lose the run but keep *something* (knowledge, unlocks, a sense of progress). Hades-style "you learn a bit each death, and the story acknowledges it" is the tone. Pure roguelike permadeath is niche; roguelite-with-progression is the mass-market winner, and the research on 20-30-minute-session players ("if I only have 30 min I want to make *some* progress") is decisive.

**Design the restart as:** run ends → you keep the diagnostic (which weak cells cratered you), the death screen *teaches* the concept you failed on, FSRS schedules that concept for tomorrow, and the *next* run starts at a difficulty you can win. Restart the *run*, never the *learning*. That converts the Souls-death from punishment into the retrieval-practice + spaced-repetition loop that the evidence says actually builds durable skill.

### Reuse vs. new complexity

| Component | Status | Notes |
|---|---|---|
| Per-skill difficulty engine | **Reuse Elo as-is** | Elo-match next challenge + small upward bias = the AI Director / CAT item-selection loop. No new model. |
| Weakness targeting | **Reuse weak-cell tracking** | Bias item selection toward low-Elo / high-FSRS-difficulty cells. The whole point of the mode. |
| Grading | **Reuse verified grader** | Tamper-proof grader already gates pass/fail per challenge. Zero new work. |
| Failure/stakes theme | **Reuse Souls death retheme** | Retheme the death screen as "teach + rematch," not a new penalty system. |
| Spaced review of failures | **Reuse FSRS** | Failed concepts feed straight into tomorrow's review. This is the anti-demotivation glue. |
| Teaching in the loop | **Reuse AI tutor** | On death, tutor explains the failed concept Socratically (you already do this). |
| **New:** run/session state machine | **Small new** | "Run" object: streak within run, escalation curve, current run difficulty, run summary. Modest. |
| **New:** slash-command trigger + run UI | **Small new** | `/gauntlet`. Run HUD (depth, current difficulty, weak-cells being probed). |
| **New:** escalation curve tuning | **Small new** | How fast difficulty ramps; when to grant a "relief" easier item (Director-style pacing). Needs playtesting, not much code. |

**Net:** the gauntlet is ~90% integration of existing systems and ~10% new state-machine + UI. It is one of the *cheapest* high-impact modes you can ship precisely because Ekalavya already built the hard parts (verified grading, Elo, FSRS, weak cells, death theme). This is the strongest argument for building it: maximal thesis-alignment and distinctiveness at minimal marginal complexity.

### Two guardrails so it doesn't dilute the moat

1. **Do not make it the primary loop.** Daily FSRS practice is what produces retention; the gauntlet is the *pull* that gets people to open the app and the deliberate-practice engine for weaknesses. Keep it as the on-demand "I want to be pushed" mode, feeding failures back into the daily/FSRS loop.
2. **Keep grading honest.** The gauntlet's stakes only mean something because the grader is real (test harness, not model opinion). Don't let "endless content pressure" tempt you into LLM-graded slop challenges — that's the exact thing your guardrail says the market fakes.

---

## Part B — Ranked shortlist of *other* modes/features worth adding

Ranked by (impact × evidence-alignment) ÷ complexity. Each notes whether Ekalavya already partly covers it.

### 1. Company-tagged / role-specific problem bank with fresh problems — **HIGH impact, LOW-MED complexity**
- **What:** A bank of problems tagged by company/role, pulling fresh role-specific problems (Tavily/Serper already wired).
- **Why (evidence):** This is LeetCode's single strongest hook and the one thing Ekalavya's roadmap flags it *lacks*. Retrieval practice and interleaving need *volume and variety* to work; a thin static bank caps how much interleaving you can do. Fresh, role-tagged content also directly serves the user's job goal, which is the autonomy/relevance driver SDT says sustains motivation ("I value this").
- **Partly covered?** Infra (search) is wired; the bank itself is not. This is a prerequisite that *makes the gauntlet and daily practice better* — more items = better adaptive selection and interleaving. **Build this alongside or just before the gauntlet.**

### 2. Debugging + code-reading + "you're the TA" drill types — **HIGH impact, LOW-MED complexity**
- **What:** Planted-bug debugging drills, predict-the-output / explain-unfamiliar-code drills, and "debug the AI's buggy code."
- **Why (evidence):** These are distinct trainable skills that plain "write a function" katas never exercise, and they're the *highest-value axis for the AI-atrophy thesis* — reading and debugging unfamiliar code is exactly what atrophies when you lean on an AI. "You're the TA" (HypoCompass-style) has measured learning gains. Interleaving *different task types* (not just different topics) is a documented desirable difficulty. This widens what the gauntlet and daily practice can throw at you.
- **Partly covered?** On the roadmap already; not built. Reuses grader + Elo + FSRS. This is the best *content-type* investment and it compounds with everything else.

### 3. AI-off vs AI-on gap tracking with a dashboard chart — **HIGH strategic impact, LOW complexity**
- **What:** Track and visualize the delta between AI-assisted and unassisted performance over time.
- **Why (evidence):** This is Ekalavya's *unique differentiator* — nobody else measures atrophy. Making the gap *visible* is a competence-feedback signal (SDT: seeing your unassisted skill rise is intrinsic-motivation fuel) and a loss-aversion hook (watching the gap widen is a "your skill is eroding" alarm, the same asymmetric-loss lever Duolingo rides). Cheap: you already have both signals; this is mostly a chart + a metric.
- **Partly covered?** Data exists; the tracking + chart is the roadmap's own "Atrophy's best idea, on-thesis" item. Ship it. It also gives the gauntlet a natural scoring axis ("gauntlet is AI-off by definition — watch your unassisted rating climb").

### 4. A weekly/seasonal "boss" or timed challenge event — **MED impact, LOW-MED complexity**
- **What:** A recurring, time-boxed hard challenge (weekly boss / seasonal gauntlet ladder) — LeetCode-contest / Codewars-clan energy, single-player.
- **Why (evidence):** LeetCode contests and Codewars ranks show recurring *events* drive return visits beyond daily habit. A *scheduled* hard event creates anticipation and a natural retrieval-practice checkpoint. Slay-the-Spire-style *escalating difficulty tiers* (Ascension) give skilled users a long-term ladder after they've "beaten" the base content — the roadmap's own "the first win is just the tutorial" insight. Reuses the gauntlet engine with a fixed seed + leaderboard-of-one (your past selves).
- **Partly covered?** No. But it's a thin layer on top of the gauntlet once that exists — build it *after* the gauntlet, as a scheduled variant. **Avoid live head-to-head PvP** (see anti-recs).

### 5. Voice / AI-enabled mock interview realism — **MED-HIGH impact, HIGH complexity**
- **What:** Spoken mock interviews and the Meta-2026-style "talk to an AI assistant *and* the interviewer simultaneously" format.
- **Why (evidence):** Text mocks miss the cognitive load of speaking under pressure; realism is the documented #1 mock-interview gap, and the AI-enabled format is a skill almost nobody teaches — a genuine moat. Directly serves the job goal. Ranked lower only because it's *high complexity* (voice I/O, latency, new eval rubric) and orthogonal to the gauntlet.
- **Partly covered?** Mock + AI-enabled interview modes exist in text; voice is net-new. Do it, but *after* the cheaper wins above — it's a bigger lift.

### 6. Streak-freeze / forgiveness layer on the daily loop — **MED impact, LOW complexity**
- **What:** A Duolingo-style streak freeze *already in the user's pocket* before they miss, plus milestone-granted freezes.
- **Why (evidence):** Streaks are the single biggest retention lever Duolingo has (7+ day streakers retain ~2.4x), *but* the freeze is what makes them sustainable instead of a burnout/quit-on-first-miss trap — and the freeze only works if it's granted *before* the miss (the user who missed is, by definition, not in the app). This is a small, well-evidenced polish on the streak system you already have that prevents the "broke my streak, why bother" churn cliff.
- **Partly covered?** You have XP/streaks; the *forgiveness* layer is missing. Very cheap; do it whenever.

---

## Part C — Skip these (low value / high complexity / redundant / off-thesis)

- **A true Nemesis system (enemies that name themselves and remember you).** Seductive and thematically perfect for "weaknesses that haunt you," but: (a) Warner Bros. holds the patent through 2036 — literal legal risk; and (b) the *learning payload* of "an enemy remembers you" is already delivered, for free, by weak-cell tracking + FSRS resurfacing your failed concepts. You get the Nemesis *feeling* ("closures came back for you") by rethemeing the gauntlet's death screen and the FSRS resurface — without building or infringing the system. **Build the vibe, not the mechanic.**

- **Live PvP leagues / real-time competitive leaderboards.** Duolingo's leagues work because of *massive matched populations* and *sophisticated matchmaking* — with a small user base you get demoralizing mismatches (the exact opposite of the "feels winnable" condition that makes leagues motivating). SDT: comparison against stronger peers thwarts competence for most users. The roadmap already deprioritizes leaderboards; keep it deprioritized. If you want competition, use *async, self-referential* competition (your past runs, personal Elo climb) — all the upside, none of the population problem.

- **Global honor/karma points (Codewars-style activity score).** Codewars deliberately *separates* rank (skill) from honor (activity/contribution), and honor mostly rewards community participation you don't have (writing/translating/voting on katas). An activity-points score that isn't skill decouples the number from actual learning — "decorative numbers" the gamification research explicitly warns tell you nothing about learning. Ekalavya's Elo already *is* the honest skill signal. Don't add a vanity currency next to it.

- **Human-mentor / community layer (Exercism-style) — not now.** Genuinely valuable pedagogically, but it's an operations problem (mentor recruitment, latency, quality variance is Exercism's own biggest weakness), not a code problem, and it fights the "AI tutor + verified grader" moat rather than reinforcing it. Correctly parked as "nice-to-have" on the roadmap. Revisit only at scale.

- **Lives/HP-that-drains-and-blocks-you penalty (naive boot.dev-style read).** Note: the research could *not* confirm boot.dev actually has a punitive HP-drain-blocks-progress mechanic — that appears to be a misconception; boot.dev lets you retry freely and gains come from *passing* checks. Don't import a punishment mechanic that the reference platform doesn't even use and that SDT says backfires. The Souls death theme should gate *runs*, never *learning* or daily access.

- **Full generalize-to-all-subjects (math/physics/…) right now.** On the roadmap as "later," correctly. It's a large pluggable-grader lift (SymPy pipelines, rubric graders) that dilutes focus while the AI/ML-engineer niche is still being nailed. The gauntlet and the content-type/bank work above deepen the *current* moat; subject expansion widens the surface before the moat is finished. Keep it later.

---

## One-paragraph synthesis

The gauntlet is the rare feature that is simultaneously the most **evidence-aligned** (forced deliberate practice on recorded weaknesses + adaptive flow-matched difficulty, i.e. an AI Director / CAT loop you've already built) and the **cheapest to ship** (90% reuse of Elo, weak cells, grader, FSRS, and the Souls death theme). Build it — with the single non-negotiable design constraint that failure restarts the *run*, not the *learning*: on death you teach the failed concept, schedule it in FSRS, and drop the learner into a winnable next run, converting Souls-death from a competence-crushing punishment into the retrieval + spacing loop that actually builds durable skill. Pair it with a real role-tagged problem bank and new drill types (debugging, code-reading, TA-mode) so it has enough varied, honestly-graded content to interleave against, surface the AI-off/AI-on gap as its scoring axis, and resist the tempting traps (patented Nemesis mechanic, PvP leagues, vanity honor points, punitive HP) that add complexity or off-thesis motivation without adding learning.

---

## Sources

Platforms & gamification:
- boot.dev / RPG-style courses & retention — coddy.tech review; indiehackers ($10M ARR); boot.dev homepage (Boots Socratic tutor, XP/streaks/quests/boss battles)
- Streaks / loss aversion / retention data — Duolingo breakdowns (strivecloud, deconstructoroffun, justanotherpm, digia.tech); Sam Liberty, "Streaks" (Medium); Plotline
- Codewars ranks vs. honor — docs.codewars.com/gamification/ranks, /honor; Codewars vs. Exercism comparisons (slashdot, algocademy, geniusfirms)
- Exercism mentored tracks — Exercism comparisons; Medium (Kekukh) Exercism vs. LeetCode
- Execute Program spaced repetition — notes.andymatuschak.org; mike.place/2020/executeprogram; Brett Chalupa review
- LeetCode contests / daily / LeetCoins — leetcode.com/contest, discuss threads; badges
- Codecrafters build-from-scratch — codecrafters.io; github codecrafters-io/build-your-own-x

Game design:
- L4D AI Director / DDA — left4dead.fandom.com/wiki/The_Director; Steam Community guides; xengamer; HP Tech Takes (adaptive AI / flow)
- Nemesis system — gamedeveloper.com "Designing Shadow of Mordor's Nemesis system" (de Plater, SDT, death-as-revenge); cbr.com; netbooknews; pushsquare (patent to 2036)
- Roguelite meta-progression / escalating difficulty — ResetEra meta-progression thread; Hades reverse-progression; Slay the Spire Ascension discussions

Learning science:
- Desirable difficulties / spacing / interleaving / retrieval — Bjork & Bjork (UNH PDF); Soderstrom & Bjork 2015; Cepeda et al. 2006 meta-analysis; Kornell & Bjork 2008; Roediger & Karpicke 2006
- Mastery learning / two-sigma — Bloom 1984; Wikipedia mastery learning & 2-sigma; Nintil systematic review (VanLehn d=0.79; Nickow/Oreopoulos/Quan ~0.29); Codewars "What is Mastery Learning"; NTNU intro-programming mastery course
- Deliberate practice / flow / ZPD — Ericsson et al. 1993 & 2008 overview; commoncog critique; Csikszentmihalyi flow; Vygotsky ZPD; "Zones of Proximal Flow" (ICER 2013)
- Computerized adaptive testing / IRT — ScienceDirect CAT overview; ERIC EJ1148445; MDPI time-sensitive IRT
- Self-determination theory / failure & demotivation — Ryan & Deci; urmc.rochester.edu SDT; PMC "Prior Competence Frustration Strengthens Motivation"; suebehaviouraldesign SDT explainer

*Note on evidence quality: several precise retention statistics (e.g., "2.4x," "40-60% higher DAU") come from vendor/consultancy blogs, not peer-reviewed sources — directionally reliable, treat exact figures with caution. The learning-science effect sizes (spacing, mastery learning, tutoring) are from peer-reviewed meta-analyses and are solid. The original Bloom "two sigma" figure was never replicated; modern mastery-learning/tutoring effects are smaller (~0.3-0.8 SD) but real.*
