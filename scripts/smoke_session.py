"""Live end-to-end practice smoke: the agent grades code and records an attempt.

Isolated to a temp home. Run: uv run python scripts/smoke_session.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-sess-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

from eklavya import progress, prompts  # noqa: E402
from eklavya.agent import build_agent  # noqa: E402
from eklavya.chat import new_thread, run_turn  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402
from eklavya.tools import SESSION_TOOLS  # noqa: E402

# One turn that exercises the graded loop: the learner submits a correct solution.
TURN = (
    "Here is my solution to 'write is_even(n)':\n"
    "    def is_even(n):\n        return n % 2 == 0\n"
    "Please grade it with hidden tests using grade_code, and if it passes, "
    "record the attempt with record_attempt(pillar='Python idioms', axis='debugging', "
    "concept='modulo', confidence=3, correct=True, seconds=20, ai_off=True). "
    "Then call progress_report and reply DONE."
)


def main() -> None:
    init_db()
    agent = build_agent(prompts.SESSION, SESSION_TOOLS)
    reply = run_turn(agent, new_thread(), TURN)
    print("agent reply (tail):", reply.strip()[-160:])

    c = connect()
    attempt = c.execute("SELECT correct FROM attempts WHERE detail='modulo'").fetchone()
    rating = c.execute(
        "SELECT r.rating FROM ratings r JOIN pillars p ON p.id=r.pillar_id "
        "WHERE p.name='Python idioms' AND r.axis='debugging'"
    ).fetchone()
    c.close()
    xp = progress.stats()["xp"]

    checks = {
        "attempt logged": attempt is not None,
        "rating updated": rating is not None and rating["rating"] != 1000.0,
        "xp awarded": xp > 0,
    }
    print()
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")
    print("\n" + ("ALL GREEN — graded practice loop works end to end."
                  if all(checks.values()) else "SOME CHECKS FAILED."))


if __name__ == "__main__":
    main()
