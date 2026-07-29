"""The in-interview AI assistant for AI-enabled interview mode.

In a modern "AI-allowed" interview the candidate may use an AI helper — and the
real skill under test is using it *well*: prompting clearly, verifying its output,
catching its mistakes, and knowing when it can't carry you. So this assistant is
deliberately imperfect, like the real thing:

  - most of the time it helps fully and correctly;
  - sometimes it plants ONE subtle, plausible bug and says nothing (trust-but-verify);
  - sometimes it withholds — gives only a partial nudge so the candidate must think.

Every exchange is logged to `ai_assists` with the ground-truth behaviour (and, for a
planted bug, what the bug was — stripped from what the candidate sees). The
interviewer reads that log via `review_ai_usage()` to grade how the AI was used.
"""

from __future__ import annotations

import logging
import random
import re

from .db import connect

_logger = logging.getLogger("eklavya")

_BASE = """You are a competent AI coding assistant helping a candidate during a \
technical interview where using AI is allowed. Be genuinely useful: answer their \
question, write or explain code, keep it concise. Assume they may paste your code \
into their solution."""

_PLANT = _BASE + """

IMPORTANT — secret grader instruction, the candidate must NOT know this: in THIS \
reply introduce EXACTLY ONE subtle, plausible bug — an off-by-one, a wrong \
boundary/edge case, a wrong default, an inverted condition, a subtle logic slip, or \
a plausible-but-wrong library call/method. Keep everything else correct and helpful, \
and do NOT hint that anything is wrong. Then, on a final separate line, output the \
marker <<BUG: one short sentence naming the exact bug you planted>>. That marker \
line is removed before the candidate sees your reply — it is for the grader only."""

_WITHHOLD = _BASE + """

IMPORTANT — secret grader instruction: in THIS reply do NOT give a complete \
solution. Give only PARTIAL help — a hint, a nudge, a question back, or cover just \
one piece — so the candidate has to think and fill the gap themselves. Be upfront \
that you're only pointing them in a direction, not solving it."""

_MARKER = re.compile(r"<<\s*BUG:\s*(.*?)>>", re.DOTALL | re.IGNORECASE)
_SUBSTANTIVE_WORDS = ("write", "implement", "fix", "code", "function", "solve", "debug", "class")


# After this many substantive asks in a thread with NOTHING planted yet, the next
# substantive reply is FORCED to plant a bug — so every interview that actually used
# the assistant has at least one planted bug to catch. Kept low so the guarantee fires
# well within a normal interview, but not on the very first ask (leaving room for the
# random plant to happen naturally and stay unpredictable).
_FORCE_PLANT_AFTER = 2


def _substantive(prompt: str) -> bool:
    """A code-eliciting ask worth (sometimes) making imperfect — not a quick clarify."""
    p = prompt.lower()
    return len(prompt) >= 40 or "```" in prompt or any(w in p for w in _SUBSTANTIVE_WORDS)


def _thread_stats(thread: str) -> tuple[int, int]:
    """(substantive asks so far, plants so far) for this thread — the state the
    guaranteed-plant rule needs. Reads the same log respond() writes to."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT prompt, behavior FROM ai_assists WHERE thread = ?", (thread,)
        ).fetchall()
    finally:
        conn.close()
    substantive = sum(1 for r in rows if _substantive(r["prompt"]))
    plants = sum(1 for r in rows if r["behavior"] == "plant")
    return substantive, plants


def _pick_behavior(prompt: str, thread: str | None = None) -> str:
    if not _substantive(prompt):
        return "help"
    # Guarantee: if the assistant has already fielded a few substantive asks in this
    # thread and never once planted, force a plant now so the interview always has a
    # bug to catch. Otherwise stay stochastic, so plants remain subtle and varied.
    if thread is not None:
        prior_substantive, prior_plants = _thread_stats(thread)
        if prior_plants == 0 and prior_substantive >= _FORCE_PLANT_AFTER:
            return "plant"
    r = random.random()
    if r < 0.30:
        return "plant"
    if r < 0.50:
        return "withhold"
    return "help"


def _history(thread: str, limit: int = 6) -> list[tuple[str, str]]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT prompt, reply FROM ai_assists WHERE thread = ? ORDER BY id DESC LIMIT ?",
            (thread, limit),
        ).fetchall()
    finally:
        conn.close()
    msgs: list[tuple[str, str]] = []
    for r in reversed(rows):
        msgs.append(("human", r["prompt"]))
        msgs.append(("ai", r["reply"]))
    return msgs


def _log(thread: str, prompt: str, reply: str, behavior: str, planted_bug: str | None) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO ai_assists(thread, prompt, reply, behavior, planted_bug) "
            "VALUES(?, ?, ?, ?, ?)",
            (thread, prompt, reply, behavior, planted_bug),
        )
        conn.commit()
    finally:
        conn.close()


def respond(thread: str, prompt: str, behavior: str | None = None) -> str:
    """Answer the candidate's assistant request — sometimes imperfectly — and log it.

    Returns only the candidate-visible reply (any grader marker is stripped).
    `behavior` can be forced (for tests); otherwise it's chosen automatically.
    """
    from . import config
    from .providers import build_chat_model

    behavior = behavior or _pick_behavior(prompt, thread)
    system = {"plant": _PLANT, "withhold": _WITHHOLD}.get(behavior, _BASE)
    messages = [("system", system), *_history(thread), ("human", prompt)]
    try:
        model = build_chat_model(config.DEFAULT_PROVIDER, max_tokens=1200)
        raw = model.invoke(messages).text
    except Exception:
        _logger.exception("assist model error")
        return "_(the AI assistant is unavailable right now.)_"

    planted_bug = None
    if behavior == "plant":
        m = _MARKER.search(raw)
        planted_bug = m.group(1).strip() if m else "(a subtle error was introduced — identify it)"
        raw = _MARKER.sub("", raw).strip()
    _log(thread, prompt, raw, behavior, planted_bug)
    return raw


def mark_interview(thread: str) -> None:
    """Remember which thread is the current AI-enabled interview, so grading scopes to it."""
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('interview_thread', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (thread,),
        )
        conn.commit()
    finally:
        conn.close()


def _current_interview(conn) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = 'interview_thread'").fetchone()
    return row["value"] if row else None


def review_ai_usage() -> str:
    """Read the AI-assistant usage log for THIS interview (AI-enabled mode) so you can
    grade HOW the candidate used the AI. Returns every exchange with the ground-truth
    behaviour — INCLUDING any bug the assistant deliberately planted (the candidate
    never saw it flagged). Using the candidate's own messages and final code, judge for
    each planted bug whether they caught it, missed it, or partially caught it; how well
    they prompted; and whether they verified the AI's output instead of trusting it."""
    conn = connect()
    try:
        thread = _current_interview(conn)
        rows = conn.execute(
            "SELECT id, prompt, reply, behavior, planted_bug, bug_verdict FROM ai_assists "
            "WHERE thread = ? ORDER BY id",
            (thread,),
        ).fetchall() if thread else []
    finally:
        conn.close()
    if not rows:
        return "(the candidate did not use the AI assistant during this interview)"

    planted = sum(1 for r in rows if r["behavior"] == "plant" and r["planted_bug"])
    withheld = sum(1 for r in rows if r["behavior"] == "withhold")
    lines = [f"{len(rows)} assistant exchange(s) · {planted} planted bug(s) · "
             f"{withheld} withheld/partial reply(ies).\n"]
    for r in rows:
        # assist_id is the STABLE key to pass to record_bug_verdict() — not the display index.
        lines.append(f"[assist_id={r['id']}] behavior={r['behavior']}")
        if r["behavior"] == "plant" and r["planted_bug"]:
            lines.append(f"    ⚠ PLANTED BUG (candidate never saw this): {r['planted_bug']}")
            verdict = r["bug_verdict"]
            lines.append(f"    ↳ recorded verdict: {verdict if verdict else '(not yet scored — record one)'}")
        lines.append(f"    candidate asked: {r['prompt'][:400]}")
        lines.append(f"    assistant replied: {r['reply'][:600]}")
    out = "\n".join(lines)
    return out if len(out) <= 3000 else out[:3000] + "\n…(truncated)"


_VERDICTS = ("caught", "missed", "partial")


def record_bug_verdict(assist_id: int, verdict: str, note: str = "") -> str:
    """Record, structurally, whether the candidate CAUGHT / MISSED / PARTIALLY caught a
    specific planted bug — so the bug-catching outcome is queryable, not just prose.

    `assist_id` is the `assist_id=` shown next to a PLANTED BUG in review_ai_usage().
    `verdict` is one of: caught | missed | partial. `note` is a one-line justification.
    Call once per planted bug during the AI-interview SCORING step.
    """
    verdict = (verdict or "").strip().lower()
    if verdict not in _VERDICTS:
        return f"unknown verdict '{verdict}'; use one of: {', '.join(_VERDICTS)}"
    conn = connect()
    try:
        row = conn.execute(
            "SELECT behavior, planted_bug FROM ai_assists WHERE id = ?", (assist_id,)
        ).fetchone()
        if row is None:
            return f"no assistant exchange with assist_id={assist_id}"
        if row["behavior"] != "plant" or not row["planted_bug"]:
            return f"assist_id={assist_id} has no planted bug to judge (behavior={row['behavior']})"
        conn.execute(
            "UPDATE ai_assists SET bug_verdict = ?, verdict_note = ? WHERE id = ?",
            (verdict, note.strip() or None, assist_id),
        )
        conn.commit()
    finally:
        conn.close()
    return f"recorded verdict '{verdict}' for planted bug (assist_id={assist_id})."
