"""Tools the tutor's agent calls to drive real, reliable state.

Each function does one obvious thing to the SQLite state or the shared profile.
The agent decides *when* to call them; these decide *what actually happens* — so
the learner's record never depends on the model remembering.

They're plain functions with clear docstrings: deepagents infers the tool schema
from the signature, and we can unit-test them directly without any LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import PROFILE_PATH, ensure_home
from .db import connect

# Atrophy's five cross-cutting skill axes, measured within every pillar.
AXES = ("syntax_recall", "debugging", "code_reading", "api_memory", "decomposition")

# Baseline mastery levels map to starting Elo-style ratings.
LEVELS = {"unknown": 800.0, "gap": 950.0, "familiar": 1150.0, "strong": 1400.0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_profile() -> str:
    """Return the learner's current profile (markdown), or a note if none exists yet."""
    if PROFILE_PATH.exists():
        return PROFILE_PATH.read_text(encoding="utf-8")
    return "(no profile yet — treat this as a first-time learner)"


def save_profile(markdown: str) -> str:
    """Overwrite the learner profile with the given markdown and return a confirmation.

    Use this at the end of onboarding, and whenever the learner model changes.
    """
    ensure_home()
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(markdown, encoding="utf-8")
    return f"saved profile ({len(markdown)} chars) to {PROFILE_PATH}"


def add_pillar(name: str, is_custom: bool = True) -> str:
    """Create a topic pillar such as 'Python idioms' or 'LangGraph'.

    Set is_custom=True for pillars derived from the learner's own goals or repos.
    """
    conn = connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO pillars(name, is_custom) VALUES(?, ?)",
            (name.strip(), int(is_custom)),
        )
        conn.commit()
    finally:
        conn.close()
    return f"pillar '{name}' ready"


def set_baseline_rating(pillar: str, axis: str, level: str) -> str:
    """Record a baseline mastery level for one (pillar, axis) cell of the grid.

    axis:  one of syntax_recall, debugging, code_reading, api_memory, decomposition.
    level: one of unknown, gap, familiar, strong.
    Creates the pillar if it doesn't exist yet.
    """
    if axis not in AXES:
        return f"unknown axis '{axis}'; use one of: {', '.join(AXES)}"
    if level not in LEVELS:
        return f"unknown level '{level}'; use one of: {', '.join(LEVELS)}"
    conn = connect()
    try:
        conn.execute("INSERT OR IGNORE INTO pillars(name, is_custom) VALUES(?, 1)", (pillar.strip(),))
        pid = conn.execute("SELECT id FROM pillars WHERE name = ?", (pillar.strip(),)).fetchone()["id"]
        conn.execute(
            """INSERT INTO ratings(pillar_id, axis, rating, confidence, first_seen, last_practiced)
               VALUES(?, ?, ?, ?, ?, ?)
               ON CONFLICT(pillar_id, axis)
               DO UPDATE SET rating = excluded.rating, last_practiced = excluded.last_practiced""",
            (pid, axis, LEVELS[level], 0.3, _now(), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return f"{pillar} / {axis} = {level}"


def add_goal(horizon: str, text: str, deadline: str = "") -> str:
    """Record a goal the learner stated. horizon: long, medium, short, or adhoc.

    deadline is optional (free-form, e.g. '2026-08-01' or 'interview in 3 days').
    """
    horizon = horizon.strip().lower()
    if horizon not in ("long", "medium", "short", "adhoc"):
        return "horizon must be one of: long, medium, short, adhoc"
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO goals(horizon, text, deadline) VALUES(?, ?, ?)",
            (horizon, text.strip(), deadline.strip() or None),
        )
        conn.commit()
    finally:
        conn.close()
    return f"goal ({horizon}) saved"


def mastery_summary() -> str:
    """Return the current mastery grid (pillar / axis / level) as readable text."""
    inv = {v: k for k, v in LEVELS.items()}
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT p.name AS pillar, r.axis AS axis, r.rating AS rating
               FROM ratings r JOIN pillars p ON p.id = r.pillar_id
               ORDER BY p.name, r.axis"""
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return "(no ratings yet)"
    lines = [f"- {r['pillar']} / {r['axis']}: {inv.get(r['rating'], round(r['rating']))}" for r in rows]
    return "\n".join(lines)


def list_goals() -> str:
    """Return the learner's active goals grouped by horizon."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT horizon, text, deadline FROM goals WHERE status = 'active' ORDER BY "
            "CASE horizon WHEN 'long' THEN 0 WHEN 'medium' THEN 1 WHEN 'short' THEN 2 ELSE 3 END"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return "(no goals yet)"
    return "\n".join(
        f"- [{r['horizon']}] {r['text']}" + (f" (by {r['deadline']})" if r["deadline"] else "")
        for r in rows
    )


# The tools exposed to the onboarding agent.
ONBOARDING_TOOLS = [
    read_profile,
    save_profile,
    add_pillar,
    set_baseline_rating,
    add_goal,
    mastery_summary,
    list_goals,
]


# --- Practice-session tools -------------------------------------------------

_MAX_OUT = 2000  # cap tool output so a runaway print can't flood the context


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_OUT else text[:_MAX_OUT] + "\n…(output truncated)"


def suggest_focus(minutes: int = 30) -> str:
    """Suggest what to work on now: weakest grid cells + any reviews due.

    Use this at the start of a session to plan. `minutes` hints how much to fit.
    """
    from .scheduling import due_now
    from .scoring import level_of

    conn = connect()
    try:
        weak = conn.execute(
            """SELECT p.name AS pillar, r.axis AS axis, r.rating AS rating
               FROM ratings r JOIN pillars p ON p.id = r.pillar_id
               ORDER BY r.rating ASC LIMIT 5"""
        ).fetchall()
    finally:
        conn.close()
    n_items = max(1, min(6, minutes // 10))
    lines = [f"Time budget: ~{minutes} min → aim for about {n_items} item(s)."]
    if weak:
        lines.append("Weakest cells (target these):")
        lines += [f"  - {r['pillar']} / {r['axis']} ({level_of(r['rating'])})" for r in weak]
    else:
        lines.append("No ratings yet — run onboarding first, or start with a fundamentals drill.")
    due = due_now()
    if due:
        lines.append("Reviews due (spaced repetition): " + ", ".join(due[:8]))
    return "\n".join(lines)


def run_code(code: str) -> str:
    """Run the learner's Python in a sandbox and return output + timing."""
    from .sandbox import run_python

    r = run_python(code)
    head = "ran OK" if r.ok else f"exited with code {r.exit_code}"
    out = f"[{head} in {r.seconds:.2f}s]\n"
    if r.stdout:
        out += f"stdout:\n{r.stdout}\n"
    if r.stderr:
        out += f"stderr:\n{r.stderr}\n"
    return _clip(out.strip())


def grade_code(code: str, tests: str) -> str:
    """Grade learner `code` against hidden `tests` (assert-based). Returns pass/fail + output."""
    from .sandbox import run_tests

    r = run_tests(code, tests)
    verdict = "PASS ✓" if r.ok else "FAIL ✗"
    out = f"{verdict} (ran in {r.seconds:.2f}s)\n"
    if r.stdout.strip():
        out += f"stdout:\n{r.stdout.strip()}\n"
    if not r.ok and r.stderr.strip():
        out += f"error:\n{r.stderr.strip()}\n"
    return _clip(out.strip())


def record_attempt(
    pillar: str,
    axis: str,
    concept: str,
    confidence: int,
    correct: bool,
    seconds: float = 0.0,
    ai_off: bool = True,
) -> str:
    """Record one graded attempt: updates the rating, schedules the review, logs
    it, awards XP, and extends the streak. Call this after each drill is judged.

    axis: one of syntax_recall, debugging, code_reading, api_memory, decomposition.
    confidence: the learner's stated 1 (guessing) / 2 (pretty sure) / 3 (certain).
    """
    from . import progress
    from .scheduling import schedule
    from .scoring import level_of, tighten, update_elo

    if axis not in AXES:
        return f"unknown axis '{axis}'; use one of: {', '.join(AXES)}"

    conn = connect()
    try:
        conn.execute("INSERT OR IGNORE INTO pillars(name, is_custom) VALUES(?, 1)", (pillar.strip(),))
        pid = conn.execute("SELECT id FROM pillars WHERE name = ?", (pillar.strip(),)).fetchone()["id"]
        row = conn.execute(
            "SELECT rating, confidence FROM ratings WHERE pillar_id = ? AND axis = ?", (pid, axis)
        ).fetchone()
        current = row["rating"] if row else 1000.0
        band = row["confidence"] if row else 0.0
        new_rating = update_elo(current, bool(correct), int(confidence))
        conn.execute(
            """INSERT INTO ratings(pillar_id, axis, rating, confidence, first_seen, last_practiced)
               VALUES(?, ?, ?, ?, ?, ?)
               ON CONFLICT(pillar_id, axis)
               DO UPDATE SET rating = excluded.rating, confidence = excluded.confidence,
                             last_practiced = excluded.last_practiced""",
            (pid, axis, new_rating, tighten(band), _now(), _now()),
        )
        conn.execute(
            """INSERT INTO attempts(item_id, session_id, confidence, correct, seconds, ai_off, detail)
               VALUES(NULL, ?, ?, ?, ?, ?, ?)""",
            (progress.current_session(conn), int(confidence), int(bool(correct)),
             float(seconds), int(bool(ai_off)), concept),
        )
        conn.commit()
    finally:
        conn.close()

    due = schedule(concept, bool(correct), int(confidence))
    xp = (12 if correct else 3) + (5 if ai_off else 0) + (2 if correct and confidence >= 3 else 0)
    total_xp = progress.award_xp(xp, label=concept, cause="attempt")
    streak = progress.touch_streak()
    lvl = progress.level_for(total_xp)
    return (
        f"{pillar}/{axis}: {level_of(current)}→{level_of(new_rating)} "
        f"(rating {new_rating}). +{xp} XP (total {total_xp}, level {lvl}). "
        f"streak {streak}. next review: {due[:10]}."
    )


def grade_and_record(pillar: str, axis: str, concept: str, code: str, tests: str,
                     confidence: int, reference: str, seconds: float = 0.0) -> str:
    """Grade a code drill and record the VERIFIED result in one tamper-proof step.

    You MUST pass `reference` — your own correct solution. Before grading the
    learner, the sandbox checks that YOUR reference passes YOUR tests. If it
    doesn't, the tests are wrong and the learner is NOT graded (this catches your
    own mistakes, which the learner can't). Only when the reference passes do we
    run the learner's `code` and record the real sandbox pass/fail — you cannot
    fake the outcome. Use this for EVERY code drill.

    axis: one of syntax_recall, debugging, code_reading, api_memory, decomposition.
    confidence: the learner's stated 1 (guessing) / 2 (pretty sure) / 3 (certain).
    """
    from .sandbox import run_tests

    # Self-check: the tests must be valid — your reference solution must pass them.
    ref = run_tests(reference, tests)
    if not ref.ok:
        return _clip(
            "⚠ TEST SANITY CHECK FAILED — your reference solution does not pass your "
            f"own tests, so the tests are wrong. Fix them before grading.\nerror:\n"
            f"{(ref.stderr or ref.stdout).strip()}\n(The learner was NOT graded.)"
        )

    r = run_tests(code, tests)
    verdict = "PASS ✓" if r.ok else "FAIL ✗"
    summary = record_attempt(pillar, axis, concept, confidence, bool(r.ok), seconds, ai_off=True)
    out = f"{verdict} (verified in sandbox, {r.seconds:.2f}s; tests validated against reference)\n"
    if r.stdout.strip():
        out += f"stdout:\n{r.stdout.strip()}\n"
    if not r.ok and r.stderr.strip():
        out += f"error:\n{r.stderr.strip()}\n"
    return _clip(out.strip() + "\n\n" + summary)


def progress_report() -> str:
    """Return the learner's streak, XP, level, and current mastery grid."""
    from . import progress

    s = progress.stats()
    return (
        f"🔥 streak {s['streak']} · ⭐ level {s['level']} · {s['xp']} XP\n\n"
        f"Mastery:\n{mastery_summary()}"
    )


# The tools exposed to the practice-session agent.
SESSION_TOOLS = [
    read_profile,
    list_goals,
    suggest_focus,
    run_code,
    grade_code,
    grade_and_record,
    record_attempt,
    progress_report,
]
