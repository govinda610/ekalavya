"""Tools the tutor's agent calls to drive real, reliable state.

Each function does one obvious thing to the SQLite state or the shared profile.
The agent decides *when* to call them; these decide *what actually happens* — so
the learner's record never depends on the model remembering.

They're plain functions with clear docstrings: deepagents infers the tool schema
from the signature, and we can unit-test them directly without any LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import config
from .config import ensure_home
from .db import connect

# Atrophy's five cross-cutting skill axes, measured within every pillar.
AXES = ("syntax_recall", "debugging", "code_reading", "api_memory", "decomposition")

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


def add_curriculum(concept: str, prereqs: str = "", pillar: str = "") -> str:
    """Add a concept to the learner's curriculum graph (a skill tree). `prereqs` is a
    PIPE-delimited (|) list of EXACT concept names to master first — concept names can
    contain commas, so never comma-join. Empty for a starting concept.
    """
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO curriculum(concept, prereqs, pillar) VALUES(?, ?, ?) "
            "ON CONFLICT(concept) DO UPDATE SET prereqs=excluded.prereqs, pillar=excluded.pillar",
            (concept.strip(), prereqs.strip(), pillar.strip()),
        )
        conn.commit()
    finally:
        conn.close()
    return f"curriculum: '{concept}' added"


def clear_curriculum() -> str:
    """Wipe the curriculum graph — use before drafting a fresh one."""
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

    - pillars:    list of pillar names, e.g. ["Python Fundamentals", "DS&A"]
    - ratings:    list of {"pillar","axis","level"} — axis in syntax_recall/debugging/
                  code_reading/api_memory/decomposition; level in unknown/gap/familiar/strong
    - goals:      list of {"horizon","text","deadline"?} — horizon in long/medium/short/adhoc
    - curriculum: list of {"concept","prereqs"?,"pillar"?} — prereqs a PIPE-delimited (|) list of exact concept names
    - replace_curriculum: True to clear the existing curriculum tree before adding
    """
    n = {"pillars": 0, "ratings": 0, "goals": 0, "curriculum": 0}
    for p in pillars or []:
        add_pillar(p)
        n["pillars"] += 1
    for r in ratings or []:
        set_baseline_rating(r["pillar"], r["axis"], r["level"])
        n["ratings"] += 1
    for g in goals or []:
        add_goal(g["horizon"], g["text"], g.get("deadline", ""))
        n["goals"] += 1
    if curriculum is not None:
        if replace_curriculum:
            clear_curriculum()
        for c in curriculum:
            add_curriculum(c["concept"], c.get("prereqs", ""), c.get("pillar", ""))
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
            "INSERT INTO rating_history(pillar, axis, old_rating, new_rating) VALUES(?, ?, ?, ?)",
            (pillar.strip(), axis, current, new_rating),
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


def assessment_items(n: int = 8) -> str:
    """Draw a fresh rotating set of ~n items from the FROZEN benchmark for an assessment.

    Tier-1 only (the `eklavya assess` loop). Returns the items to administer AI-off — each
    with its id, difficulty (1..5), the prompt to pose, and the private `answer` KEY you
    grade against. The key is for YOUR grading ONLY — never reveal, hint at, or teach it
    during the sitting. Items are spread across difficulty and pillar and avoid ones seen in
    the last couple of sittings. Pose them one at a time, record correctness with
    `record_assessment` at the end.
    """
    import json

    from . import benchmark

    conn = connect()
    try:
        items = benchmark.select_items(conn, n=n)
    finally:
        conn.close()
    if not items:
        return "no benchmark items available"
    return json.dumps([
        {"item_id": it["id"], "difficulty": it["difficulty"],
         "pillar": it["pillar"], "prompt": it["prompt"], "answer": it["answer"]}
        for it in items
    ])


def record_assessment(outcomes: list, context: str = "") -> str:
    """Persist a completed frozen assessment and compute the ability score θ (Tier-1).

    Call this ONCE, at the very end of an `assess` sitting, after every item has been posed
    and objectively judged. `outcomes` is a list of dicts, one per administered item:
    {"item_id": <int>, "difficulty": <1..5>, "correct": <true|false>, "seconds": <float>}.
    `context` is an optional short note ("baseline", "week 4"). Returns the θ estimate and
    the score. Never teach or hint during the sitting — this only records what happened.
    """
    from . import benchmark

    norm = [
        {"item_id": int(o["item_id"]), "difficulty": int(o["difficulty"]),
         "correct": bool(o["correct"]), "seconds": o.get("seconds")}
        for o in outcomes
    ]
    if not norm:
        return "no outcomes to record"
    res = benchmark.record_assessment(norm, context=context)
    theta = res["theta"]
    theta_txt = f"{theta:+.2f}" if theta is not None else "—"
    return (f"assessment #{res['assessment_id']} recorded: θ = {theta_txt} "
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
    grade_and_record, web_search, read_github, read_resume, get_questions, add_question,
    record_attempt, save_baseline, suggest_focus,
    review_ai_usage, record_bug_verdict, save_artifact, run_bash,
]

# Same tools in every mode; the prompt decides how to use them.
ONBOARDING_TOOLS = AGENT_TOOLS
SESSION_TOOLS = AGENT_TOOLS
AIINTERVIEW_TOOLS = AGENT_TOOLS

# Tier-1 assessment: a DELIBERATELY MINIMAL toolset — pull frozen items, grade code if
# needed, record the sitting. No suggest_focus, no teaching aids: the assessment must not
# adapt to or teach the learner (that's what keeps the benchmark a non-circular ruler).
ASSESSMENT_TOOLS = [assessment_items, grade_and_record, record_assessment]
