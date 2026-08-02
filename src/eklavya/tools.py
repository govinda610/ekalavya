"""Tools the tutor's agent calls to drive real, reliable state.

Each function does one obvious thing to the SQLite state or the shared profile.
The agent decides *when* to call them; these decide *what actually happens* — so
the learner's record never depends on the model remembering.

They're plain functions with clear docstrings: deepagents infers the tool schema
from the signature, and we can unit-test them directly without any LLM.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import subjects
from .config import ensure_home
from .db import connect

# Legacy coding axes — kept as the module-level name many callers/tests still import.
# The subject-aware axis sets now live in the registry (subjects.py); coding's current
# axis set is recall/application/transfer + debugging/code_reading/api_memory. This tuple
# is retained for back-compat (the old grid/prompts/tests reference it).
AXES = ("syntax_recall", "debugging", "code_reading", "api_memory", "decomposition")

DEFAULT_SUBJECT = subjects.DEFAULT_SUBJECT

# Baseline mastery levels map to starting Elo-style ratings.
LEVELS = {"unknown": 800.0, "gap": 950.0, "familiar": 1150.0, "strong": 1400.0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_profile() -> str:
    """Return the learner's current profile (markdown), or a note if none exists yet."""
    profile = config.paths().profile
    if profile.exists():
        return profile.read_text(encoding="utf-8")
    return "(no profile yet — treat this as a first-time learner)"


def save_profile(markdown: str) -> str:
    """Overwrite the learner profile with the given markdown and return a confirmation.

    Use this at the end of onboarding, and whenever the learner model changes.
    """
    ensure_home()
    profile = config.paths().profile
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(markdown, encoding="utf-8")
    return f"saved profile ({len(markdown)} chars) to {profile}"


def add_pillar(name: str, is_custom: bool = True, subject: str = DEFAULT_SUBJECT,
               seq: int | None = None, prereq_pillars: list | str | None = None) -> str:
    """Create a topic pillar such as 'Python idioms' or 'LangGraph'.

    Set is_custom=True for pillars derived from the learner's own goals or repos.
    subject is the registry key this pillar belongs to (defaults to coding).
    seq is the tackle-order HINT (foundational first); it's a deterministic tie-break, NOT a
    forced total order — the real journey order is a topological sort of the dependency DAG.
    prereq_pillars are the pillars that must be tackled BEFORE this one (a list of exact pillar
    names, or a pipe-delimited string); leave it empty for an independent pillar that can be
    pursued in parallel (incl. across subjects). Re-runnable — updates seq/prereqs when given.
    """
    subject = (subject or DEFAULT_SUBJECT).strip()
    if not subjects.exists(subject):
        subject = DEFAULT_SUBJECT
    if isinstance(prereq_pillars, (list, tuple)):
        deps = "|".join(str(p).strip() for p in prereq_pillars if str(p).strip())
    else:
        deps = (prereq_pillars or "").strip()
    conn = connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO pillars(name, is_custom, subject) VALUES(?, ?, ?)",
            (name.strip(), int(is_custom), subject),
        )
        # Re-runnable order/dep update: set seq / prereq_pillars only when the caller passed
        # them, so a bare add_pillar() never wipes an order the tutor already set.
        if seq is not None:
            conn.execute("UPDATE pillars SET seq = ? WHERE name = ?", (int(seq), name.strip()))
        if prereq_pillars is not None:
            conn.execute("UPDATE pillars SET prereq_pillars = ? WHERE name = ?", (deps, name.strip()))
        conn.commit()
    finally:
        conn.close()
    return f"pillar '{name}' ready"


def set_baseline_rating(pillar: str, axis: str, level: str, subject: str = DEFAULT_SUBJECT) -> str:
    """Record a baseline mastery level for one (subject, pillar, axis) cell of the grid.

    subject: one of the registry keys (coding, maths, stats, ml, cs_theory). Defaults to coding.
    axis:    a CORE axis (recall/application/derivation_proof/interpretation/synthesis/transfer)
             or one of the subject's extensions. Legacy coding names (syntax_recall,
             decomposition) are accepted and remapped losslessly.
    level:   one of unknown, gap, familiar, strong. Creates the pillar if it doesn't exist yet.
    """
    subject = (subject or DEFAULT_SUBJECT).strip()
    if not subjects.exists(subject):
        return f"unknown subject '{subject}'; use one of: {', '.join(s.key for s in subjects.all_subjects())}"
    axis = subjects.remap_axis(axis)  # legacy syntax_recall→recall / decomposition→synthesis
    if not subjects.valid_axis(subject, axis):
        return f"unknown axis '{axis}' for {subject}; use one of: {', '.join(subjects.axes_for(subject))}"
    if level not in LEVELS:
        return f"unknown level '{level}'; use one of: {', '.join(LEVELS)}"
    conn = connect()
    try:
        conn.execute("INSERT OR IGNORE INTO pillars(name, is_custom, subject) VALUES(?, 1, ?)",
                     (pillar.strip(), subject))
        pid = conn.execute("SELECT id FROM pillars WHERE name = ?", (pillar.strip(),)).fetchone()["id"]
        conn.execute(
            """INSERT INTO ratings(pillar_id, axis, subject, rating, confidence, first_seen, last_practiced)
               VALUES(?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(pillar_id, axis, subject)
               DO UPDATE SET rating = excluded.rating, last_practiced = excluded.last_practiced""",
            (pid, axis, subject, LEVELS[level], 0.3, _now(), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return f"{subject} / {pillar} / {axis} = {level}"


def remember_preference(key: str, value: str) -> str:
    """Persist ONE durable learning preference so every future session honours it.

    Use this for stable facts about HOW the learner wants to be taught — not per-drill state.
    Examples: key "teaching_style" value "teach by typing code in, not pasting"; key "examples"
    value "examples-first"; key "spoilers" value "no spoilers — let me struggle"; key "pace"
    value "fast, one drill after another". Upserts on `key` (re-remembering a key updates it),
    so the set of preferences stays small and current. These are resurfaced to you automatically
    at the top of every session's context — so save the durable ones here rather than hoping
    they survive in the transcript.
    """
    key = (key or "").strip()
    if not key:
        return "remember_preference: empty key ignored"
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO learning_prefs(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, (value or "").strip(), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return f"remembered preference: {key} = {value}"


def recall_preferences() -> str:
    """Return every saved learning preference (key = value), or a note if none are set yet.

    These are the durable teaching preferences the learner has stated (style, pace, spoilers,
    examples-first, …). Honour them. They're also injected into your session context each turn,
    so this tool is for an explicit re-read when you want the full current list.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT key, value FROM learning_prefs ORDER BY key"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return "(no learning preferences saved yet)"
    return "\n".join(f"- {r['key']}: {r['value']}" for r in rows)


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


def add_curriculum(concept: str, prereqs: str = "", pillar: str = "",
                   subject: str = DEFAULT_SUBJECT) -> str:
    """Add a concept to the learner's curriculum graph (a skill tree). `prereqs` is a
    PIPE-delimited (|) list of EXACT concept names to master first — concept names can
    contain commas, so never comma-join. Empty for a starting concept. `subject` is the
    registry key this concept belongs to (defaults to coding).
    """
    subject = (subject or DEFAULT_SUBJECT).strip()
    if not subjects.exists(subject):
        subject = DEFAULT_SUBJECT
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO curriculum(concept, prereqs, pillar, subject) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(concept) DO UPDATE SET prereqs=excluded.prereqs, pillar=excluded.pillar, "
            "subject=excluded.subject",
            (concept.strip(), prereqs.strip(), pillar.strip(), subject),
        )
        conn.commit()
    finally:
        conn.close()
    return f"curriculum: '{concept}' added"


def _guard_destructive(op: str) -> None:
    """Protect the learner's real store from accidental wipes by stray scripts or agents.

    Two layers, in order:
      1. REFUSE when NO account is bound to the context and the op would land on the retired
         ``~/.eklavya`` fallback home — the exact way an unscoped script clobbers real data —
         unless ``EKLAVYA_ALLOW_DESTRUCTIVE=1`` signals deliberate intent. Real runs always
         bind an account first (CLI/TUI resolve one; the web binds the session's user); test
         runs that pin a temp ``EKLAVYA_HOME``/``EKLAVYA_DATA_ROOT`` never match, so they pass.
      2. ALWAYS take a recovery snapshot first, so any authorised destructive change is
         one ``eklavya revert`` away. Best-effort: a backup failure must never itself
         block a legitimate op, but a hard refusal above always wins.
    """
    bound = config._current_home.get() is not None
    home = config.paths().home
    allow = os.environ.get("EKLAVYA_ALLOW_DESTRUCTIVE", "0") not in ("0", "", "false", "False")
    if not bound and home == (Path.home() / ".eklavya") and not allow:
        raise RuntimeError(
            f"Refusing {op}: it would modify the real single-user store at {home} with no "
            "user home bound. Bind a user home / set EKLAVYA_DATA_ROOT (multi-user), or set "
            "EKLAVYA_ALLOW_DESTRUCTIVE=1 to override deliberately."
        )
    try:
        from .backups import snapshot
        snapshot(f"before {op}")  # unconditional: always back up before a destructive wipe
    except Exception:
        pass  # never let a backup hiccup block a legitimate operation


def clear_curriculum() -> str:
    """Wipe the curriculum graph — use before drafting a fresh one.

    Guarded: refuses to touch the real single-user store unbound, and snapshots first."""
    _guard_destructive("clear_curriculum")
    conn = connect()
    try:
        conn.execute("DELETE FROM curriculum")
        conn.commit()
    finally:
        conn.close()
    return "curriculum cleared"


def get_curriculum() -> str:
    """Return the current curriculum graph as text (concept ← prerequisites)."""
    conn = connect()
    try:
        rows = conn.execute("SELECT concept, prereqs FROM curriculum ORDER BY id").fetchall()
    finally:
        conn.close()
    if not rows:
        return "(no curriculum yet — draft one with add_curriculum, then confirm it with the learner)"
    return "\n".join(
        f"- {r['concept']}" + (f" ← {r['prereqs']}" if r["prereqs"] else " (start here)")
        for r in rows
    )


def save_baseline(pillars: list | None = None, ratings: list | None = None,
                  goals: list | None = None, curriculum: list | None = None,
                  replace_curriculum: bool = False) -> str:
    """Persist onboarding results (or later edits) in ONE call — upserts any subset.

    - pillars:    the pillars in the intended TACKLE ORDER (foundational first). The LIST ORDER
                  is stored as each pillar's `seq` hint, so pass them ordered. Each item is a
                  name string, or a dict {"name","subject"?,"prereq_pillars"?} where
                  `prereq_pillars` is a list of exact pillar names that must come first (leave it
                  out / empty for an independent pillar that can be pursued in parallel, incl.
                  across subjects). The real journey order is a topological sort of these
                  dependencies; `seq` only breaks ties. Re-runnable — resend the list to re-order.
    - ratings:    list of {"pillar","axis","level"} — axis in syntax_recall/debugging/
                  code_reading/api_memory/decomposition; level in unknown/gap/familiar/strong
    - goals:      list of {"horizon","text","deadline"?} — horizon in long/medium/short/adhoc
    - curriculum: list of {"concept","prereqs"?,"pillar"?} — prereqs a PIPE-delimited (|) list of exact concept names
    - replace_curriculum: True to clear the existing curriculum tree before adding
    """
    n = {"pillars": 0, "ratings": 0, "goals": 0, "curriculum": 0}
    for i, p in enumerate(pillars or []):
        if isinstance(p, dict):
            add_pillar(p["name"], subject=p.get("subject", DEFAULT_SUBJECT), seq=i,
                       prereq_pillars=p.get("prereq_pillars"))
        else:
            add_pillar(p, seq=i)
        n["pillars"] += 1
    for r in ratings or []:
        set_baseline_rating(r["pillar"], r["axis"], r["level"], r.get("subject", DEFAULT_SUBJECT))
        n["ratings"] += 1
    for g in goals or []:
        add_goal(g["horizon"], g["text"], g.get("deadline", ""))
        n["goals"] += 1
    if curriculum is not None:
        if replace_curriculum:
            clear_curriculum()
        for c in curriculum:
            add_curriculum(c["concept"], c.get("prereqs", ""), c.get("pillar", ""),
                           c.get("subject", DEFAULT_SUBJECT))
            n["curriculum"] += 1
    return (f"saved: {n['pillars']} pillars, {n['ratings']} ratings, "
            f"{n['goals']} goals, {n['curriculum']} curriculum nodes")


# The unified toolset is defined once at the bottom of this module — see AGENT_TOOLS.
# (add_pillar/set_baseline_rating/add_goal/add_curriculum/clear_curriculum remain as
# helpers that save_baseline reuses; list_goals/progress_report back the slash commands.)


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


def run_bash(command: str, explanation: str) -> str:
    """Run a shell command in the learner's workspace. Use it to run/verify code,
    inspect files, or query the learner db with sqlite3 (the db is `eklavya.db` in the
    workspace). You MUST pass `explanation`: one plain sentence saying what the command
    does and why it's safe — the learner sees it and approves before it runs. The
    command runs with the workspace as its working directory.
    """
    import re
    import subprocess

    deny = re.compile(
        r"rm\s+-rf\s+[~/]|:\s*\(\)\s*\{|\bmkfs\b|\bdd\s+if=|>\s*/dev/(sd|disk)|"
        r"(curl|wget)[^|]*\|\s*(sh|bash)|chmod\s+-R\s+777\s+/",
        re.IGNORECASE,
    )
    if deny.search(command):
        return "Refused: this command matches a blocked destructive pattern."

    from .backups import snapshot_if_changed

    snapshot_if_changed(f"before run_bash: {command[:80]}")  # safety net for model SQL

    from .workspace import workspace_dir

    # Scrub secrets from the child env so a command can't read/exfiltrate API keys
    # (echo $..._API_KEY, env, etc.) into the model or the transcript.
    import os
    _secret = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)
    safe_env = {k: v for k, v in os.environ.items() if not _secret.search(k)}
    try:
        r = subprocess.run(command, shell=True, cwd=str(workspace_dir()), env=safe_env,
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "Command timed out (60s)."
    out = (r.stdout or "").strip()
    if r.stderr.strip():
        out += "\n[stderr]\n" + r.stderr.strip()
    return _clip(out or f"(exit {r.returncode}, no output)")


# Partial-credit pass threshold: a fractional score ≥ τ counts as `correct` (binary
# back-compat + Tier-1). Global (locked decision), plan §5.3.
PASS_THRESHOLD = 0.5


def record_attempt(
    pillar: str,
    axis: str,
    concept: str,
    confidence: int,
    correct: bool,
    seconds: float = 0.0,
    ai_off: bool = True,
    subject: str = DEFAULT_SUBJECT,
    score: float | None = None,
    answer_type: str = "code",
) -> str:
    """Record one graded attempt: updates the rating, schedules the review, logs
    it, awards XP, and extends the streak. Call this after each drill is judged.

    subject: registry key (coding/maths/stats/ml/cs_theory); defaults to coding.
    axis: a CORE axis or a subject extension (legacy coding names remapped losslessly).
    confidence: the learner's stated 1 (guessing) / 2 (pretty sure) / 3 (certain).
    score: optional partial-credit fraction ∈ [0,1]. When given, Elo consumes the fraction
           and `correct` is derived as score ≥ τ (0.5); otherwise the passed `correct` is used
           and score is stored as its 0/1 equivalent.
    """
    from . import progress
    from .scheduling import schedule
    from .scoring import level_of, tighten, update_elo

    subject = (subject or DEFAULT_SUBJECT).strip()
    if not subjects.exists(subject):
        return f"unknown subject '{subject}'; use one of: {', '.join(s.key for s in subjects.all_subjects())}"
    axis = subjects.remap_axis(axis)
    if not subjects.valid_axis(subject, axis):
        return f"unknown axis '{axis}' for {subject}; use one of: {', '.join(subjects.axes_for(subject))}"

    # Resolve the score fraction + the binary correct (thresholded at τ) coherently.
    if score is not None:
        frac = max(0.0, min(1.0, float(score)))
        correct_bool = frac >= PASS_THRESHOLD
    else:
        correct_bool = bool(correct)
        frac = 1.0 if correct_bool else 0.0

    conn = connect()
    try:
        conn.execute("INSERT OR IGNORE INTO pillars(name, is_custom, subject) VALUES(?, 1, ?)",
                     (pillar.strip(), subject))
        pid = conn.execute("SELECT id FROM pillars WHERE name = ?", (pillar.strip(),)).fetchone()["id"]
        row = conn.execute(
            "SELECT rating, confidence FROM ratings WHERE pillar_id = ? AND axis = ? AND subject = ?",
            (pid, axis, subject),
        ).fetchone()
        current = row["rating"] if row else 1000.0
        band = row["confidence"] if row else 0.0
        new_rating = update_elo(current, frac, int(confidence))
        conn.execute(
            """INSERT INTO ratings(pillar_id, axis, subject, rating, confidence, first_seen, last_practiced)
               VALUES(?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(pillar_id, axis, subject)
               DO UPDATE SET rating = excluded.rating, confidence = excluded.confidence,
                             last_practiced = excluded.last_practiced""",
            (pid, axis, subject, new_rating, tighten(band), _now(), _now()),
        )
        conn.execute(
            "INSERT INTO rating_history(pillar, axis, subject, old_rating, new_rating) VALUES(?, ?, ?, ?, ?)",
            (pillar.strip(), axis, subject, current, new_rating),
        )
        conn.execute(
            """INSERT INTO attempts(item_id, session_id, confidence, correct, seconds, ai_off,
                                    detail, subject, answer_type, score)
               VALUES(NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (progress.current_session(conn), int(confidence), int(correct_bool),
             float(seconds), int(bool(ai_off)), concept, subject, answer_type, frac),
        )
        conn.commit()
    finally:
        conn.close()

    correct = correct_bool
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


def grade_and_record_subject(
    pillar: str,
    axis: str,
    concept: str,
    answer: str,
    key: str,
    answer_type: str,
    confidence: int,
    subject: str = DEFAULT_SUBJECT,
    tolerance: str = "",
    seconds: float = 0.0,
) -> str:
    """Grade a NON-CODE drill deterministically and record the VERIFIED result — the
    tamper-proof, subject-aware generalisation of grade_and_record (plan §5.5).

    Picks a ground-truth grader from `answer_type` (numeric | symbolic | units | choice),
    runs it against `key` (the objective reference), and records the outcome via the
    subject-aware pipeline. The GRADER sets the score — you cannot fake it. Use this for
    every objective non-code drill (maths numeric/symbolic answers, MCQs, unit answers).

    - answer:      the learner's answer, verbatim.
    - key:         the objective reference answer to grade against.
    - answer_type: numeric | symbolic | units | choice.
    - tolerance:   optional JSON for numeric, e.g. '{"abs": 0.01}' or '{"rel": 0.02}'.
    - subject:     registry key (maths/stats/ml/...); axis a CORE axis or subject extension.
    For code drills use grade_and_record (sandbox) instead.
    """
    from . import graders

    atype = (answer_type or "").strip()
    if atype not in graders.DETERMINISTIC_TYPES:
        return (f"grade_and_record_subject handles only deterministic types "
                f"({', '.join(sorted(graders.DETERMINISTIC_TYPES))}); got '{atype}'. "
                "Use grade_rubric for proofs/interpretation, grade_and_record for code.")
    try:
        res = graders.grade(answer, {"answer_type": atype, "answer": key, "tolerance": tolerance})
    except ValueError as e:
        return f"grading error: {e}"
    verdict = "PASS ✓" if res.score >= PASS_THRESHOLD else "FAIL ✗"
    summary = record_attempt(pillar, axis, concept, confidence, res.score >= PASS_THRESHOLD,
                             seconds, ai_off=True, subject=subject, score=res.score,
                             answer_type=atype)
    return _clip(f"{verdict} ({atype} grader, deterministic: {res.detail})\n\n{summary}")


def grade_rubric(
    pillar: str,
    axis: str,
    concept: str,
    prompt: str,
    answer: str,
    reference: str,
    rubric: list,
    confidence: int,
    subject: str = DEFAULT_SUBJECT,
    answer_type: str = "proof",
    seconds: float = 0.0,
) -> str:
    """Grade a NON-DETERMINISTIC answer (proof / interpretation / explanation) with the
    constrained rubric judge and record the partial-credit result (plan §5.2–5.4).

    The judge is a DIFFERENT model than the tutor, grades the learner's `answer` ONLY
    against the stored `reference` + the structured `rubric`, is doc-grounded, and runs
    k=1 (single pass; the raw verdict is logged for optional human audit). It returns a
    per-criterion breakdown → a weighted fraction ∈ [0,1]. Criteria may be axis-tagged
    ({"axis": "interpretation"}), so one multi-part answer updates several axis cells with
    the right partial weights; the fallback `axis` catches untagged criteria.

    `rubric` is a list of {"id", "description", "weight"?, "axis"?}. Fail-open: if the judge
    is unavailable, nothing is recorded and a note is returned (never a fabricated score).
    """
    import json

    from . import verify

    subject = (subject or DEFAULT_SUBJECT).strip()
    if not subjects.exists(subject):
        return f"unknown subject '{subject}'"
    rubric_list = list(rubric or [])
    res = verify.rubric_judge(prompt, answer, reference, rubric_list, subject=subject)
    if not res.get("ok") or res.get("score") is None:
        return (f"rubric grading unavailable ({res.get('reason', 'judge error')}); "
                "nothing recorded — configure a second provider to enable judged grading.")

    # Deterministic sub-checks OVERRIDE the judge on the parts a ground-truth grader can
    # check (plan §5.2.6). A rubric criterion may carry {"check": {"answer_type", "answer",
    # "value"}} — an objective sub-part; if so, that grader's fraction replaces the judge's
    # for that criterion, so the model can't talk its way past a checkable fact.
    from . import graders
    det_index = {c.get("id"): c for c in rubric_list if c.get("check")}

    # Group per-criterion fractions by their axis (untagged criteria fall to `axis`), so a
    # multi-part answer updates each competency cell with its own weighted partial credit.
    by_axis: dict[str, list[tuple[float, float]]] = {}
    for c in res["criteria"]:
        frac = float(c["fraction"])
        spec = det_index.get(c["id"])
        if spec:
            chk = spec["check"]
            try:
                dres = graders.grade(chk.get("value", ""),
                                     {"answer_type": chk.get("answer_type"),
                                      "answer": chk.get("answer"), "tolerance": chk.get("tolerance", "")})
                frac = dres.score  # deterministic verdict wins on this criterion
            except ValueError:
                pass
        ax = subjects.remap_axis(c.get("axis") or axis)
        if not subjects.valid_axis(subject, ax):
            ax = subjects.remap_axis(axis)  # keep the record on a valid cell
        by_axis.setdefault(ax, []).append((float(c["weight"]), frac))

    recorded: list[str] = []
    first_axis = subjects.remap_axis(axis)
    for ax, parts in by_axis.items():
        w = sum(p[0] for p in parts) or 1.0
        frac = sum(p[0] * p[1] for p in parts) / w
        record_attempt(pillar, ax, concept, confidence, frac >= PASS_THRESHOLD, seconds,
                       ai_off=True, subject=subject, score=frac, answer_type=answer_type)
        recorded.append(f"{ax} {frac:.2f}")

    verdict = "PASS ✓" if res["score"] >= PASS_THRESHOLD else "PARTIAL"
    detail = json.dumps({"score": res["score"], "model": res["model"],
                         "criteria": [{k: c[k] for k in ("id", "axis", "verdict", "fraction")}
                                      for c in res["criteria"]]})
    return _clip(f"{verdict} (rubric judge, k=1, score {res['score']:.2f}; "
                 f"axes: {', '.join(recorded)})\naudit: {detail}")


def progress_report() -> str:
    """Return the learner's streak, XP, level, and current mastery grid."""
    from . import progress

    s = progress.stats()
    return (
        f"🔥 streak {s['streak']} · ⭐ level {s['level']} · {s['xp']} XP\n\n"
        f"Mastery:\n{mastery_summary()}"
    )


def _web_search_raw(query: str, max_results: int = 6) -> list[dict]:
    """Run one web search and return normalised {title, content, url} dicts.

    Offline-safe: returns [] when no provider key is set or the request fails, so callers
    (web_search, refresh-questions) never crash without a key. Tavily → Serper fallback.
    """
    import os

    import requests

    tavily = os.environ.get("TAVILY_API_KEY") or os.environ.get("EKLAVYA_TAVILY_API_KEY")
    serper = os.environ.get("SERPER_API_KEY") or os.environ.get("EKLAVYA_SERPER_API_KEY")
    if not (tavily or serper):
        return []
    try:
        if tavily:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily, "query": query, "max_results": max_results},
                timeout=25,
            )
            results = resp.json().get("results", [])
            if results:
                return [{"title": r.get("title", ""), "content": str(r.get("content", "")),
                         "url": r.get("url", "")} for r in results[:max_results]]
        if serper:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
                timeout=25,
            )
            results = resp.json().get("organic", [])
            if results:
                return [{"title": r.get("title", ""), "content": str(r.get("snippet", "")),
                         "url": r.get("link", "")} for r in results[:max_results]]
    except Exception:
        return []
    return []


def has_web_search_key() -> bool:
    """True when a web-search provider key (Tavily or Serper) is configured.

    The single source of truth for "is web search available?" — used by `web_search`
    and by the background question-bank auto-refresh to stay offline-safe.
    """
    import os

    return bool(os.environ.get("TAVILY_API_KEY") or os.environ.get("EKLAVYA_TAVILY_API_KEY")
                or os.environ.get("SERPER_API_KEY") or os.environ.get("EKLAVYA_SERPER_API_KEY"))


def web_search(query: str) -> str:
    """Search the web for real, current interview questions, references, or role
    requirements — e.g. company/role-specific questions, or researching a target role's
    stack. Uses Tavily if TAVILY_API_KEY is set, otherwise falls back to Serper
    (SERPER_API_KEY). Returns "unavailable" only if neither key is present."""
    if not has_web_search_key():
        return ("Web search unavailable — set TAVILY_API_KEY (or SERPER_API_KEY) to "
                "enable fresh questions and role research.")
    results = _web_search_raw(query)
    if not results:
        return "No results."
    return _clip("\n".join(
        f"- {r['title']}: {r['content'][:220]} ({r['url']})" for r in results
    ))


def add_question(question: str, topic: str = "", difficulty: str = "", role: str = "",
                 company: str = "", source: str = "") -> str:
    """Add ONE real interview question to the growing bank so it's reusable later.

    Use this when `web_search` surfaces a genuine, current interview question worth
    keeping. HONESTY RULE: set `company` ONLY when the question is genuinely attributed
    to that company by the source — never guess or fabricate a company tag. Leave it ""
    if unknown. `topic` is a free-form tag (e.g. 'arrays', 'system-design', 'RAG',
    'behavioral'); `difficulty` is easy/medium/hard when known; `source` is where it
    came from (a URL or list name) for attribution. Deduped on the question text.
    """
    q = (question or "").strip()
    if not q:
        return "add_question: empty question ignored"
    diff = (difficulty or "").strip().lower()
    if diff and diff not in ("easy", "medium", "hard"):
        diff = ""  # keep the tag clean; unknown difficulties are just blank
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO questions(company, role, topic, difficulty, question, source) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            ((company or "").strip() or None, (role or "").strip() or None,
             (topic or "").strip() or None, diff or None, q, (source or "").strip() or None),
        )
        conn.commit()
        added = cur.rowcount
    finally:
        conn.close()
    return f"added question ({q[:60]}…)" if added else "already in the bank (skipped)"


def get_questions(topic: str = "", company: str = "", role: str = "",
                  difficulty: str = "", n: int = 3) -> str:
    """Pull a few REAL interview questions from the bank, filtered to a target.

    Use this instead of inventing questions: filter to the learner's target role/company
    and their weak topics. All filters are optional and matched loosely (case-insensitive
    substring) so 'design' finds 'system-design'. Returns up to `n` questions (randomised
    so you don't repeat the same ones), each with its tags and source. If the bank is thin
    for a target, use `web_search` for fresh ones and `add_question` the good finds.
    """
    n = max(1, min(int(n or 3), 20))
    where, params = [], []
    for col, val in (("topic", topic), ("company", company), ("role", role), ("difficulty", difficulty)):
        val = (val or "").strip()
        if val:
            where.append(f"LOWER({col}) LIKE ?")
            params.append(f"%{val.lower()}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = connect()
    try:
        rows = conn.execute(
            f"SELECT company, role, topic, difficulty, question, source FROM questions"
            f"{clause} ORDER BY RANDOM() LIMIT ?",
            (*params, n),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        tgt = ", ".join(f"{k}={v}" for k, v in
                        (("topic", topic), ("company", company), ("role", role), ("difficulty", difficulty)) if v)
        return (f"(no questions in the bank for {tgt or 'that filter'} — "
                "use web_search for real current ones, then add_question the good ones)")
    lines = []
    for r in rows:
        tags = " · ".join(t for t in (r["topic"], r["difficulty"], r["role"], r["company"]) if t)
        line = f"- {r['question']}"
        if tags:
            line += f"  [{tags}]"
        if r["source"]:
            line += f"  (src: {r['source']})"
        lines.append(line)
    return _clip("\n".join(lines))


def save_artifact(title: str, kind: str, content: str, pillar: str = "") -> str:
    """Save a durable artifact to the learner's Canvas / Scriptorium library.

    Use this to keep something the learner will want to revisit: a written lesson, a
    reference code file, a framed HTML page, or an interactive visual. Offer it naturally
    ("want me to save this to your Canvas?") rather than saving silently.

    kind is one of: 'markdown' (a written lesson), 'code' (a code file/snippet),
    'html' (a self-contained HTML page/widget), or 'viz' (an SVG/interactive visual).
    content is the raw artifact body (markdown text, source code, or HTML/SVG markup).
    pillar is the pillar/topic this belongs to (e.g. "Python Fundamentals", "LLM & Deep
    Learning Internals") — pass it so the artifact files under the right pillar in the
    library; it's auto-linked to the current chat either way. Returns a confirmation with the id.
    """
    from . import artifacts, report

    # If the guru didn't name a pillar, fall back to the one currently in focus, so artifacts
    # still file themselves correctly instead of landing under "General".
    tag = (pillar or "").strip() or report.active_pillar()
    a = artifacts.create(title, kind, content, pillar=tag)
    return f"saved artifact #{a['id']} '{a['title']}' ({a['kind']}) to the Canvas library"


def assessment_items(n: int = 8, subject: str = DEFAULT_SUBJECT) -> str:
    """Draw a fresh rotating set of ~n items from ONE subject's FROZEN benchmark for an
    assessment.

    Tier-1 only (the `eklavya assess` loop). Returns the items to administer AI-off — each
    with its id, difficulty (1..5), answer_type (code|numeric|symbolic|choice|...), the
    prompt to pose, the private `answer` KEY, and any tolerance/rubric for grading. The key
    is for YOUR grading ONLY — never reveal, hint at, or teach it during the sitting. Items
    are spread across difficulty and pillar and avoid ones seen in the last couple of
    sittings. Grade objective items with grade_and_record_subject; record the whole sitting
    with `record_assessment` at the end. `subject` defaults to coding.
    """
    import json

    from . import benchmark

    subject = (subject or DEFAULT_SUBJECT).strip()
    conn = connect()
    try:
        items = benchmark.select_items(conn, n=n, subject=subject)
    finally:
        conn.close()
    if not items:
        return f"no benchmark items available for subject '{subject}'"
    return json.dumps([
        {"item_id": it["id"], "difficulty": it["difficulty"], "subject": it["subject"],
         "answer_type": it["answer_type"], "pillar": it["pillar"], "prompt": it["prompt"],
         "answer": it["answer"], "tolerance": it["tolerance"], "rubric": it["rubric"]}
        for it in items
    ])


def record_assessment(outcomes: list, context: str = "", subject: str = DEFAULT_SUBJECT) -> str:
    """Persist a completed frozen assessment for ONE subject and compute its ability score θ.

    Call this ONCE, at the very end of an `assess` sitting, after every item has been posed
    and objectively judged. `outcomes` is a list of dicts, one per administered item:
    {"item_id": <int>, "difficulty": <1..5>, "correct": <true|false>, "seconds": <float>,
    "score": <0..1, optional partial credit>}. θ is per-subject (one ruler per subject).
    `context` is an optional short note ("baseline", "week 4"). Returns the θ estimate and
    the score. Never teach or hint during the sitting — this only records what happened.
    """
    from . import benchmark

    subject = (subject or DEFAULT_SUBJECT).strip()
    norm = [
        {"item_id": int(o["item_id"]), "difficulty": int(o["difficulty"]),
         "correct": bool(o["correct"]), "seconds": o.get("seconds"), "score": o.get("score"),
         "criteria_json": o.get("criteria_json")}
        for o in outcomes
    ]
    if not norm:
        return "no outcomes to record"
    res = benchmark.record_assessment(norm, context=context, subject=subject)
    theta = res["theta"]
    theta_txt = f"{theta:+.2f}" if theta is not None else "—"
    return (f"assessment #{res['assessment_id']} recorded ({subject}): θ = {theta_txt} "
            f"({res['n_correct']}/{res['n_items']} correct on the frozen benchmark)")


from .assist import record_bug_verdict, review_ai_usage  # noqa: E402
from .github import read_github  # noqa: E402
from .resume import read_resume  # noqa: E402

# The unified toolset — one small spine every interface's agent shares. deepagents adds
# the floor tools (read_file/write_file/edit_file/ls/glob/grep/write_todos/task) on our
# confined backend; build_agent appends the MCP web-search + docs tools. Everything else
# (running/verifying code, reading state, searching the web) goes through those.
# The 4 floor tools (read_file / write_file / edit_file + run_bash) already do most of the
# work, so we add ONLY what they genuinely can't. The two real value-adds:
#   • grade_and_record — tamper-proof grading (validates the tutor's tests against its own
#     reference, runs the learner's code in the sandbox, records the real verdict atomically).
#   • web_search — reach the live web (Tavily → Serper fallback) for real interview
#     questions and target-role research; the base tools can't touch the network.
#   • read_github — ground practice in the learner's REAL code on a deployed server, where
#     their repo isn't on the box: they hand over a GitHub repo/profile link and we
#     shallow-clone (read-only, capped) or read public API metadata to infer their stack.
#   • read_resume — pull the learner's uploaded résumé / LinkedIn PDF text (extracted, capped,
#     untrusted) so onboarding grounds the background + competency map in real experience.
#   • get_questions / add_question — draw REAL interview questions from the curated bank
#     (filtered to the learner's target role/company/weak topic) instead of inventing them,
#     and grow the bank from good web_search finds (honest company tagging only).
# Plus the small state spine that encodes non-trivial logic (Elo/FSRS/upsert/AI-review) which
# bash-SQL should not reimplement. Everything else goes through the floor tools + run_bash.
#   • save_artifact — keep a durable lesson/code/HTML/visual in the learner's Canvas
#     library (the Scriptorium) so a good explanation the guru writes isn't lost. For
#     interactive 3B1B-style visuals the guru authors a self-contained viz artifact; the
#     Canvas renders it in a sandboxed iframe that preloads Plotly + KaTeX.
AGENT_TOOLS = [
    grade_and_record, grade_and_record_subject, grade_rubric, web_search, read_github,
    read_resume, get_questions, add_question, record_attempt, save_baseline, suggest_focus,
    review_ai_usage, record_bug_verdict, save_artifact, run_bash,
    remember_preference, recall_preferences,
]

# Same tools in every mode; the prompt decides how to use them.
ONBOARDING_TOOLS = AGENT_TOOLS
SESSION_TOOLS = AGENT_TOOLS
AIINTERVIEW_TOOLS = AGENT_TOOLS

# Tier-1 assessment: a DELIBERATELY MINIMAL toolset — pull frozen items, grade code if
# needed, record the sitting. No suggest_focus, no teaching aids: the assessment must not
# adapt to or teach the learner (that's what keeps the benchmark a non-circular ruler).
ASSESSMENT_TOOLS = [assessment_items, grade_and_record, grade_and_record_subject, record_assessment]
