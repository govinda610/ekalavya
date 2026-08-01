"""Effectiveness Tier 2 (v1) — support for the owner's n=1 single-case self-experiment.

Deliberately minimal and NON-speculative: with ~1 real user, multi-user cohort/randomization
infrastructure would be dead weight, so this ships only what's usable now:

  - research CONSENT (a per-user opt-in flag, off by default) — the gate for ever using a
    learner's data in research (matters once there are many users);
  - per-skill INTERVENTION STARTS — the backbone of a multiple-baseline single-case design:
    record the date you *deliberately began* working each pillar, so later you can check that
    each skill's ability curve bends upward only AFTER its own start (and not before) — the
    within-person evidence that the tutoring, not maturation, drove the gain;
  - PRE-REGISTRATIONS — commit to a metric + expected effect BEFORE seeing results, so you
    can't rationalise the outcome after the fact.

# TODO (multi-user, when N grows): cohort assignment, delayed-start/waitlist control,
# component-ablation randomization, dose-response — none of it is meaningful at N=1.

All reads/writes go through the contextvar-aware db, so everything is per-user.
"""

from __future__ import annotations

from . import settings
from .db import connect


# --- research consent -------------------------------------------------------

def is_consented() -> bool:
    """True if the learner opted in to having their data used for effectiveness research."""
    return settings.get_research_consent()


def set_consent(on: bool) -> None:
    settings.set_research_consent(bool(on))


# --- multiple-baseline intervention starts ----------------------------------

def log_intervention_start(pillar: str, note: str = "") -> str:
    """Record (or update the note of) the day deliberate practice on `pillar` began.

    One row per pillar (re-logging updates the note, not the start date), so each skill has
    a single, stable baseline→intervention boundary for the multiple-baseline analysis.
    """
    pillar = pillar.strip()
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO intervention_starts(pillar, note) VALUES(?, ?) "
            "ON CONFLICT(pillar) DO UPDATE SET note = excluded.note",
            (pillar, note.strip()),
        )
        conn.commit()
    finally:
        conn.close()
    return f"intervention start logged for '{pillar}'"


def intervention_starts() -> list[dict]:
    """Every logged per-pillar intervention start, oldest first."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT pillar, started_at, note FROM intervention_starts ORDER BY started_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# --- pre-registration -------------------------------------------------------

def prereg(metric: str, hypothesis: str) -> str:
    """Commit to a metric + expected effect before seeing results (pre-registration)."""
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO preregistrations(metric, hypothesis) VALUES(?, ?)",
            (metric.strip(), hypothesis.strip()),
        )
        conn.commit()
    finally:
        conn.close()
    return "pre-registration recorded"


def preregistrations() -> list[dict]:
    """Every pre-registration, oldest first."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT metric, hypothesis, created_at FROM preregistrations ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# --- Tier 3: real-world outcomes (ecological validity) ----------------------

OUTCOME_KINDS = ("interview", "offer", "assessment", "solved_unaided", "confidence", "other")


def record_outcome(kind: str, label: str, value: str = "", occurred_at: str = "",
                   note: str = "") -> str:
    """Log a real-world outcome — the proof the tutoring matters beyond the app's own metrics.

    kind: interview | offer | assessment | solved_unaided | confidence | other (unknown → other).
    value/occurred_at/note are optional (e.g. a score, a date, context).
    """
    kind = kind.strip().lower()
    if kind not in OUTCOME_KINDS:
        kind = "other"
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO external_outcomes(kind, label, value, occurred_at, note) VALUES(?,?,?,?,?)",
            (kind, label.strip(), value.strip() or None, occurred_at.strip() or None,
             note.strip() or None),
        )
        conn.commit()
    finally:
        conn.close()
    return f"outcome recorded ({kind})"


def outcomes() -> list[dict]:
    """Every recorded real-world outcome, most recent first (by when it happened, else logged)."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT kind, label, value, occurred_at, note, created_at FROM external_outcomes "
            "ORDER BY COALESCE(occurred_at, created_at) DESC, id DESC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
