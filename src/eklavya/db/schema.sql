-- Ekalavya structured state (PLAN §12). The profile.md holds the prose model of
-- the learner; this DB holds the numbers the prose can't. Kept deliberately lean
-- for P0 — columns grow as phases land.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- The subject registry: one row per subject, declaring its axes, answer types, and
-- benchmark tag. Seeded idempotently from subjects.py (the authoritative in-code
-- definition). See docs/UNIFIED_SUBJECT_FRAMEWORK_PLAN.md §6.
CREATE TABLE IF NOT EXISTS subjects (
    id           INTEGER PRIMARY KEY,
    key          TEXT NOT NULL UNIQUE,     -- 'coding' | 'maths' | 'stats' | 'ml' | 'cs_theory' | ...
    name         TEXT NOT NULL,
    core_axes    TEXT NOT NULL,            -- pipe-list of universal-core axes this subject uses
    ext_axes     TEXT,                     -- pipe-list of subject-specific extension axes
    answer_types TEXT,                     -- pipe-list of allowed answer types (code|numeric|...)
    is_custom    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The axis catalog (label → kind core|ext) for UI/validation. Seeded from subjects.py.
CREATE TABLE IF NOT EXISTS axes (
    id      INTEGER PRIMARY KEY,
    key     TEXT NOT NULL UNIQUE,          -- 'recall' | 'derivation_proof' | 'debugging' | ...
    kind    TEXT NOT NULL DEFAULT 'core',  -- core | ext
    label   TEXT
);

-- Topic pillars (default + agent-created custom ones from onboarding/repo study).
CREATE TABLE IF NOT EXISTS pillars (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    is_custom   INTEGER NOT NULL DEFAULT 0,
    subject     TEXT NOT NULL DEFAULT 'coding',  -- which subject this pillar belongs to
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Elo-style rating per (subject, pillar, axis) cell — the mastery grid.
CREATE TABLE IF NOT EXISTS ratings (
    id            INTEGER PRIMARY KEY,
    pillar_id     INTEGER NOT NULL REFERENCES pillars(id),
    axis          TEXT NOT NULL,   -- recall | application | derivation_proof | ... | debugging | ...
    subject       TEXT NOT NULL DEFAULT 'coding',
    rating        REAL NOT NULL DEFAULT 1000,
    confidence    REAL NOT NULL DEFAULT 0,  -- band width; shrinks with evidence
    first_seen    TEXT,
    last_practiced TEXT,
    UNIQUE (pillar_id, axis, subject)
);

-- Spaced-repetition cards (concept or problem) with FSRS scheduling state.
-- state_json holds the full serialized FSRS card so no scheduling state is lost.
CREATE TABLE IF NOT EXISTS cards (
    id          INTEGER PRIMARY KEY,
    ref         TEXT NOT NULL,   -- concept slug or item id
    stability   REAL,
    difficulty  REAL,
    due         TEXT,
    lapses      INTEGER NOT NULL DEFAULT 0,
    state_json  TEXT,
    subject     TEXT NOT NULL DEFAULT 'coding'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cards_ref ON cards(ref);

-- Drill/lesson definitions (from static bank, generated, or the learner's repos).
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY,
    pillar_id   INTEGER REFERENCES pillars(id),
    axis        TEXT,
    difficulty  INTEGER,
    prompt      TEXT,
    grader      TEXT,            -- hidden_tests | output_match | rubric | teachback
    source      TEXT,            -- bank | generated | repo
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every attempt — the raw signal, including timing and honesty.
CREATE TABLE IF NOT EXISTS attempts (
    id          INTEGER PRIMARY KEY,
    item_id     INTEGER REFERENCES items(id),
    session_id  INTEGER REFERENCES sessions(id),
    confidence  INTEGER,         -- 1 guessing | 2 pretty sure | 3 certain
    correct     INTEGER,
    seconds     REAL,            -- wall-clock, stamped by the spine (not the LLM)
    ai_off      INTEGER NOT NULL DEFAULT 1,
    hints_used  INTEGER NOT NULL DEFAULT 0,
    cheat_flag  INTEGER NOT NULL DEFAULT 0,
    detail      TEXT,
    subject     TEXT NOT NULL DEFAULT 'coding',
    answer_type TEXT NOT NULL DEFAULT 'code',
    score       REAL,            -- partial-credit fraction ∈ [0,1]; correct = score ≥ τ
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- What the learner has actually learned, and the evidence for it.
CREATE TABLE IF NOT EXISTS concepts (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    state       TEXT NOT NULL DEFAULT 'unknown',  -- unknown | gap | familiar | strong
    evidence    TEXT,            -- teachback done? transfer solved?
    goal_id     INTEGER REFERENCES goals(id),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS misconceptions (
    id          INTEGER PRIMARY KEY,
    concept     TEXT,
    wrong_model TEXT,
    identified  TEXT,
    resolved    TEXT
);

-- How the learner learns best — so teaching adapts.
CREATE TABLE IF NOT EXISTS learning_prefs (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Goals come from the learner: long / medium / short / ad-hoc.
CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY,
    horizon     TEXT NOT NULL,   -- long | medium | short | adhoc
    text        TEXT NOT NULL,
    deadline    TEXT,
    status      TEXT NOT NULL DEFAULT 'active',   -- active | met | dropped
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Periodic goal check-ins — the system evolving with the learner.
CREATE TABLE IF NOT EXISTS goal_reviews (
    id          INTEGER PRIMARY KEY,
    goal_id     INTEGER REFERENCES goals(id),
    progress    TEXT,
    adjustments TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY,
    planned_min   INTEGER,
    actual_sec    REAL,
    goal_set      TEXT,
    goal_met      INTEGER,
    xp            INTEGER NOT NULL DEFAULT 0,
    mode          TEXT,          -- guided | yolo | auto
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at      TEXT,
    last_active   TEXT           -- bumped each turn; lets us reuse an open sitting / measure elapsed
);

-- Repos the learner has explicitly allow-listed for scanning.
CREATE TABLE IF NOT EXISTS repos (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    stacks      TEXT,
    focus       TEXT,
    granted_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The curriculum graph: a concept map with prerequisites the agent drafts and the
-- planner navigates. prereqs is a comma-separated list of concept names.
CREATE TABLE IF NOT EXISTS curriculum (
    id          INTEGER PRIMARY KEY,
    concept     TEXT NOT NULL UNIQUE,
    prereqs     TEXT,
    pillar      TEXT,
    subject     TEXT NOT NULL DEFAULT 'coding',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every rating change over time, so the Journey view can show "then vs now".
CREATE TABLE IF NOT EXISTS rating_history (
    id          INTEGER PRIMARY KEY,
    pillar      TEXT NOT NULL,
    axis        TEXT NOT NULL,
    subject     TEXT NOT NULL DEFAULT 'coding',
    old_rating  REAL,
    new_rating  REAL NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Gamification ledger: XP, streak, level, badges — and Souls-like penalties.
CREATE TABLE IF NOT EXISTS rewards (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,   -- xp | streak | level | badge | penalty
    amount      INTEGER,
    label       TEXT,
    cause       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A growing bank of interview questions, tagged by company/role/topic. The agent
-- pulls from it and adds fresh ones it finds via web search.
CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY,
    company     TEXT,
    role        TEXT,
    topic       TEXT,
    difficulty  TEXT,
    question    TEXT NOT NULL,
    source      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_questions_q ON questions(question);

-- AI-enabled interview mode: every exchange with the in-interview AI assistant,
-- logged so the interviewer can grade HOW the candidate used it. `behavior` is
-- help | plant | withhold; `planted_bug` is the ground-truth flaw when we
-- deliberately made the assistant subtly wrong (the candidate never saw this).
-- `bug_verdict` is the interviewer's structured grade of whether the candidate
-- caught that planted bug: caught | missed | partial (NULL until scored), with
-- `verdict_note` holding the one-line justification. This makes the bug-catching
-- outcome queryable, not just prose buried in the transcript.
CREATE TABLE IF NOT EXISTS ai_assists (
    id           INTEGER PRIMARY KEY,
    thread       TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    reply        TEXT NOT NULL,
    behavior     TEXT NOT NULL DEFAULT 'help',
    planted_bug  TEXT,
    bug_verdict  TEXT,   -- caught | missed | partial (scored after the interview)
    verdict_note TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_assists_thread ON ai_assists(thread);

-- The chats index for the chats window (history / continue / rename). The actual
-- conversation state lives in the LangGraph SQLite checkpointer
-- (~/.eklavya/checkpoints.sqlite), keyed by the same thread_id; this table just
-- holds the sidebar metadata so we can list, title, and order past chats.
CREATE TABLE IF NOT EXISTS chats (
    thread_id   TEXT PRIMARY KEY,
    title       TEXT,
    mode        TEXT,
    user_id     TEXT,   -- owner (multi-user); NULL for single-user/legacy rows
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(updated_at DESC);

-- Canvas artifacts — durable lessons/code/HTML/visuals the guru authors and the
-- learner keeps. Per-user (each user has their own db); the Scriptorium library reads
-- from here. `kind` is one of markdown | code | html | viz.
CREATE TABLE IF NOT EXISTS artifacts (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'markdown',   -- markdown | code | html | viz
    content     TEXT NOT NULL DEFAULT '',
    pinned      INTEGER NOT NULL DEFAULT 0,
    thread_id   TEXT,                               -- the chat that created it (NULL = ad-hoc)
    pillar      TEXT,                               -- the pillar it belongs to (for grouping)
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_artifacts_updated ON artifacts(updated_at DESC);

-- === Tier-1 effectiveness: a FROZEN benchmark the tutor never teaches from ===
-- (docs/EFFECTIVENESS_MEASUREMENT.md §3). A walled item bank + periodic AI-off
-- sittings yield a stable ability score θ — the non-circular "am I really improving?"
-- ruler. The tutor's teaching loops NEVER draw drills from benchmark_items; only
-- benchmark.py reads it. Seeded idempotently by benchmark.seed_items from _migrate.

-- The frozen item bank. difficulty is authored on a 1..5 scale; answer is the objective
-- key the assessment agent grades against (never shown as a hint). Frozen once seeded.
CREATE TABLE IF NOT EXISTS benchmark_items (
    id          INTEGER PRIMARY KEY,
    pillar      TEXT NOT NULL,
    difficulty  INTEGER NOT NULL,          -- 1 (easy) .. 5 (hard)
    prompt      TEXT NOT NULL,
    answer      TEXT NOT NULL,             -- objective key / reference (private)
    grader      TEXT NOT NULL DEFAULT 'output_match',  -- output_match | hidden_tests | rubric
    subject     TEXT NOT NULL DEFAULT 'coding',        -- which subject's ruler this item is on
    answer_type TEXT NOT NULL DEFAULT 'code',          -- code | numeric | symbolic | ... (grader dispatch)
    tolerance   TEXT,                       -- JSON for numeric graders: {"abs":..,"rel":..,"unit":..}
    rubric      TEXT,                       -- JSON rubric for judged items (criteria + axis tags)
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_benchmark_items_prompt ON benchmark_items(prompt);

-- One completed sitting: θ estimated (Rasch/1PL) from the items' difficulties + outcomes.
CREATE TABLE IF NOT EXISTS assessments (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at    TEXT,
    theta       REAL,                      -- latent ability on the logit scale
    n_items     INTEGER NOT NULL DEFAULT 0,
    subject     TEXT NOT NULL DEFAULT 'coding',  -- θ is per-subject (one ruler per subject)
    context     TEXT                        -- free note, e.g. "baseline", "week 4"
);

-- Per-item response within a sitting — objectively scored, timed.
CREATE TABLE IF NOT EXISTS assessment_responses (
    id             INTEGER PRIMARY KEY,
    assessment_id  INTEGER NOT NULL REFERENCES assessments(id),
    item_id        INTEGER NOT NULL REFERENCES benchmark_items(id),
    correct        INTEGER NOT NULL DEFAULT 0,
    score          REAL,               -- partial-credit fraction ∈ [0,1] (judge/rubric items)
    criteria_json  TEXT,               -- per-criterion judge verdict, for human spot-audit
    seconds        REAL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assessment_responses_a ON assessment_responses(assessment_id);

-- Learner feedback (docs/EFFECTIVENESS_MEASUREMENT.md §7): a 1-tap post-drill
-- rating (1..5) and/or free text, tied to the concept/mode so it's attributable —
-- not a global mood. Doubles as future fine-tuning / training data. kind is one of
-- drill | session | freeform; rating/text/concept/mode/thread are all optional.
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL DEFAULT 'freeform',   -- drill | session | freeform
    rating      INTEGER,            -- 1..5, nullable (a text-only note is valid)
    text        TEXT,
    concept     TEXT,
    mode        TEXT,
    thread      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Effectiveness Tier 2 (§4): n=1 single-case (multiple-baseline) self-experiment support.
-- One intervention-start per pillar = the baseline→intervention boundary for that skill.
CREATE TABLE IF NOT EXISTS intervention_starts (
    id          INTEGER PRIMARY KEY,
    pillar      TEXT NOT NULL UNIQUE,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    note        TEXT
);
-- Pre-registrations: commit to a metric + expected effect before seeing the result.
CREATE TABLE IF NOT EXISTS preregistrations (
    id          INTEGER PRIMARY KEY,
    metric      TEXT NOT NULL,
    hypothesis  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Effectiveness Tier 3 (§5): real-world OUTCOMES — the ecological-validity proof that the
-- tutoring matters beyond the app's own metrics (interviews, offers, external assessments,
-- problems solved unaided at work, confidence, ...). kind categorizes it; value is optional
-- (a score/pass etc.); occurred_at is when it happened (may differ from logging time).
CREATE TABLE IF NOT EXISTS external_outcomes (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,        -- interview | offer | assessment | solved_unaided | confidence | other
    label       TEXT NOT NULL,
    value       TEXT,                 -- optional: score / pass|fail / number
    occurred_at TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Single-row key/value for app metadata (schema version, streak counters, ...).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
