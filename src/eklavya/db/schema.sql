-- Ekalavya structured state (PLAN §12). The profile.md holds the prose model of
-- the learner; this DB holds the numbers the prose can't. Kept deliberately lean
-- for P0 — columns grow as phases land.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Topic pillars (default + agent-created custom ones from onboarding/repo study).
CREATE TABLE IF NOT EXISTS pillars (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    is_custom   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Elo-style rating per (pillar, axis) cell — the mastery grid.
CREATE TABLE IF NOT EXISTS ratings (
    id            INTEGER PRIMARY KEY,
    pillar_id     INTEGER NOT NULL REFERENCES pillars(id),
    axis          TEXT NOT NULL,   -- syntax_recall | debugging | code_reading | api_memory | decomposition
    rating        REAL NOT NULL DEFAULT 1000,
    confidence    REAL NOT NULL DEFAULT 0,  -- band width; shrinks with evidence
    first_seen    TEXT,
    last_practiced TEXT,
    UNIQUE (pillar_id, axis)
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
    state_json  TEXT
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
    ended_at      TEXT
);

-- Repos the learner has explicitly allow-listed for scanning.
CREATE TABLE IF NOT EXISTS repos (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    stacks      TEXT,
    focus       TEXT,
    granted_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every rating change over time, so the Journey view can show "then vs now".
CREATE TABLE IF NOT EXISTS rating_history (
    id          INTEGER PRIMARY KEY,
    pillar      TEXT NOT NULL,
    axis        TEXT NOT NULL,
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

-- Single-row key/value for app metadata (schema version, streak counters, ...).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
