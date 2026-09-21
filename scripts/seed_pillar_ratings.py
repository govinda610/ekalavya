"""Seed baseline ratings for every pillar that has curriculum nodes but no ratings rows.

This fixes the repetitiveness bug: suggest_focus only surfaces pillars that appear in the
ratings table. Pillars added by seed_parity_from_vault.py (CS Fundamentals, Software
Engineering, Computer Vision & Multimodal, Indic & Speech AI, Startup & Product,
Research & Frontier, Deep Learning, LLMs & Agents, MLOps & Systems) have zero ratings
rows, so the agent never drills them. This script inserts 'unknown' baseline rows
(Elo ~800) for every unrated (pillar, axis, subject) combination.

Each subject uses the axes appropriate to it:
  - coding pillars: coding × {api_memory, code_reading, debugging, recall, synthesis}
  - ml pillars:    ml × {application, derivation_proof, failure_diagnosis, interpretation,
                         metric_selection, recall, synthesis, experimental_design}
  - stats pillars: stats × {application, assumption_checking, derivation_proof,
                             inference_validity, interpretation, model_specification, recall}
  - maths pillars: maths × {application, derivation_proof, recall, symbolic_manipulation}
  - cs_theory:     cs_theory × {application, complexity_analysis, recall}

For new/mixed pillars (CV, Indic, Startup, Research, etc.) we insert both coding and ml
axes so the agent can surface them for any drill type.

Run:
  uv run python scripts/seed_pillar_ratings.py          (dry run — print counts, no writes)
  uv run python scripts/seed_pillar_ratings.py --apply  (write to live DB)

Safe: INSERT ... ON CONFLICT DO NOTHING — re-runs are idempotent.
Snapshots the DB before any write (Eklavya's own backup mechanism).
"""

from __future__ import annotations

import sys

from eklavya.db import connect, init_db

# Axes per subject (mirrors what seed_ai_curriculum.py seeded originally).
AXES_BY_SUBJECT: dict[str, list[str]] = {
    "coding": ["api_memory", "code_reading", "debugging", "recall", "synthesis"],
    "ml": ["application", "derivation_proof", "failure_diagnosis",
           "interpretation", "metric_selection", "recall", "synthesis", "experimental_design"],
    "stats": ["application", "assumption_checking", "derivation_proof",
              "inference_validity", "interpretation", "model_specification", "recall"],
    "maths": ["application", "derivation_proof", "recall", "symbolic_manipulation"],
    "cs_theory": ["application", "complexity_analysis", "recall"],
}

# Baseline Elo for "unknown" level (matches tools.LEVELS["unknown"]).
BASELINE_ELO = 800.0

# Maps pillar names → which subjects to seed. "coding" is always present for all AI/ML
# pillars so the coding axes appear; for maths/stats/theory pillars we seed subject-specific
# axes too.  We use the exact names from the pillars table.
PILLAR_SUBJECTS: dict[str, list[str]] = {
    # Brand-new pillars from seed_parity_from_vault (0 ratings each)
    "CS Fundamentals":             ["coding", "cs_theory"],
    "Software Engineering":        ["coding"],
    "Computer Vision & Multimodal": ["coding", "ml"],
    "Indic & Speech AI":           ["coding", "ml"],
    "Startup & Product":           ["coding"],       # concept-heavy, use coding axes
    "Research & Frontier":         ["coding", "ml"],
    # Legacy pillars that ended up with 0 ratings
    "Deep Learning":               ["coding", "ml"],
    "LLMs & Agents":               ["coding", "ml"],
    "MLOps & Systems":             ["coding"],
    # Pillars with only 1 rating row (Machine Learning pillar 18 has 1 ml row)
    "Machine Learning":            ["coding", "ml"],
}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(apply: bool) -> None:
    init_db()
    conn = connect()
    try:
        before = conn.execute("SELECT COUNT(*) AS n FROM ratings").fetchone()["n"]

        rows_to_insert: list[tuple] = []
        for pillar_name, subjects in PILLAR_SUBJECTS.items():
            row = conn.execute(
                "SELECT id FROM pillars WHERE name = ?", (pillar_name,)
            ).fetchone()
            if row is None:
                print(f"  SKIP (no pillar row): {pillar_name}")
                continue
            pid = row["id"]
            for subject in subjects:
                axes = AXES_BY_SUBJECT.get(subject, [])
                for axis in axes:
                    rows_to_insert.append((pid, axis, subject))

        # Remove (pillar_id, axis, subject) combos that already exist.
        existing = {
            (r["pillar_id"], r["axis"], r["subject"])
            for r in conn.execute("SELECT pillar_id, axis, subject FROM ratings")
        }
        new_rows = [(pid, axis, subj) for (pid, axis, subj) in rows_to_insert
                    if (pid, axis, subj) not in existing]

        ts = _now()
        print(f"ratings before: {before}")
        print(f"rows to consider: {len(rows_to_insert)}")
        print(f"already present: {len(rows_to_insert) - len(new_rows)}")
        print(f"net new rows:    {len(new_rows)}")

        if not apply:
            print("\nDRY RUN — no writes. Re-run with --apply to seed.")
            conn.close()
            return

        # Snapshot before writing.
        from eklavya.backups import snapshot
        snap_id = snapshot("before seed_pillar_ratings --apply")
        print(f"\nSnapshot taken: {snap_id}")

        conn.executemany(
            """INSERT INTO ratings(pillar_id, axis, subject, rating, confidence, first_seen, last_practiced)
               VALUES(?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(pillar_id, axis, subject) DO NOTHING""",
            [(pid, axis, subj, BASELINE_ELO, 0.0, ts, None) for (pid, axis, subj) in new_rows],
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) AS n FROM ratings").fetchone()["n"]
        print(f"ratings after:  {after}  (+{after - before} new rows inserted)")
    finally:
        conn.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
