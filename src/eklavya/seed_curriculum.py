"""Ship the parity curriculum (6 new pillars + concepts) and their baseline ratings so
every account gets them, not just the one account this was originally hand-seeded onto.

Source: the learning-system vault parity work (`scripts/seed_parity_from_vault.py` +
`scripts/seed_pillar_ratings.py`, recovered from a stale branch) — CS Fundamentals,
Software Engineering, Computer Vision & Multimodal, Indic & Speech AI, Startup &
Product, Research & Frontier, plus depth extensions to several existing pillars.

`ensure_curriculum_seeded(conn)` is additive + idempotent, safe to call on EVERY launch
(new accounts and existing ones alike, unlike the one-shot `scripts/seed_*.py`):
  - pillars:   INSERT OR IGNORE, keyed on the pillars.name UNIQUE constraint.
  - concepts:  INSERT OR IGNORE, keyed on the curriculum.concept UNIQUE constraint — an
               existing account's own curriculum (agent-drafted or hand-edited) is never
               touched, only rows that are still missing get added.
  - ratings:   INSERT ... ON CONFLICT DO NOTHING, keyed on ratings' (pillar_id, axis,
               subject) UNIQUE constraint — a baseline is only added where none exists.
Never raises: seeding is a nicety, not something that may break login.

GATED ON ONBOARDING BEING ALREADY COMPLETE (profile.md exists + at least one rating already
saved — the same two facts `report.is_first_run()` checks). This is deliberate: `curriculum`/
`pillars`/`ratings` genuinely start EMPTY for a brand-new account until the learner's own
onboarding populates them — that emptiness IS the "first run" signal the whole app (and its
test suite) relies on. Seeding ahead of onboarding would make every new signup look
"already onboarded" and would resurrect ratings that a deliberate reset just wiped. So: a
not-yet-onboarded account is left untouched (exactly as before this change), and an
ALREADY-onboarded account — new or long-existing — gets this enrichment layered on top the
next time `init_db()` runs for it (next login/session), which is exactly how the one
manually-seeded account originally got it (onboarded first, enrichment run against it after).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

log = logging.getLogger("eklavya.seed_curriculum")

_SEED_FILE = Path(__file__).parent / "data" / "seed_curriculum.json"


def _load_file() -> dict:
    try:
        data = json.loads(_SEED_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _onboarding_complete(conn: sqlite3.Connection) -> bool:
    """Mirrors `report.is_first_run()`'s completion check, read straight off the connection
    already open in this migration step (no second connection mid-transaction)."""
    try:
        if not config.paths().profile.exists():
            return False
        row = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def ensure_curriculum_seeded(conn: sqlite3.Connection) -> dict:
    """Idempotently insert the shipped parity pillars/concepts/ratings; return counts.

    No-ops until onboarding is complete (see module docstring), then safe to call on every
    launch after that — nothing here can duplicate or clobber a row that's already there
    (pillars/concepts dedup on their UNIQUE column, ratings dedup on the (pillar_id, axis,
    subject) UNIQUE constraint). Uses the passed-in connection (does not commit; the caller
    does) — this runs inside `_migrate`'s SAVEPOINT.
    """
    counts = {"pillars": 0, "concepts": 0, "ratings": 0}
    if not _onboarding_complete(conn):
        return counts
    data = _load_file()
    if not data:
        return counts

    try:
        for name in data.get("pillars", []):
            name = str(name).strip()
            if not name:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO pillars(name, is_custom, subject) VALUES(?, 1, 'coding')",
                (name,),
            )
            if cur.rowcount and cur.rowcount > 0:
                counts["pillars"] += 1

        for c in data.get("concepts", []):
            concept = str(c.get("concept", "")).strip()
            if not concept:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO curriculum(concept, prereqs, pillar, subject) "
                "VALUES(?, ?, ?, 'coding')",
                (concept, str(c.get("prereqs", "")).strip(), str(c.get("pillar", "")).strip()),
            )
            if cur.rowcount and cur.rowcount > 0:
                counts["concepts"] += 1

        baseline = float(data.get("baseline_rating", 800.0))
        ts = _now()
        for r in data.get("ratings", []):
            pillar = str(r.get("pillar", "")).strip()
            axis = str(r.get("axis", "")).strip()
            subject = str(r.get("subject", "")).strip()
            if not (pillar and axis and subject):
                continue
            row = conn.execute("SELECT id FROM pillars WHERE name = ?", (pillar,)).fetchone()
            if row is None:
                continue  # pillar wasn't seeded (missing from data file) — skip gracefully
            pid = row[0]
            cur = conn.execute(
                "INSERT INTO ratings(pillar_id, axis, subject, rating, confidence, first_seen) "
                "VALUES(?, ?, ?, ?, 0.0, ?) "
                "ON CONFLICT(pillar_id, axis, subject) DO NOTHING",
                (pid, axis, subject, baseline, ts),
            )
            if cur.rowcount and cur.rowcount > 0:
                counts["ratings"] += 1
    except sqlite3.Error:
        log.warning("curriculum seed step failed partway — serving degraded", exc_info=True)
        return counts

    if any(counts.values()):
        log.info("seeded curriculum parity: +%d pillars, +%d concepts, +%d ratings",
                  counts["pillars"], counts["concepts"], counts["ratings"])
    return counts
