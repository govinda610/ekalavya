"""Live integration test: can the agent actually drive our tools via GLM?

Isolated to a temp home so it never touches the real ~/.eklavya DB or the shared
profile. Gives the agent an explicit instruction and checks the state changed.

Run:  uv run python scripts/smoke_agent.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-smoke-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

from eklavya.agent import build_agent  # noqa: E402
from eklavya.chat import new_thread, run_turn  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402
from eklavya.prompts import PERSONA  # noqa: E402
from eklavya.tools import ONBOARDING_TOOLS  # noqa: E402

INSTRUCTION = (
    "Set me up using your tools, right now, without asking questions: "
    "1) add a long-term goal 'Become an AI engineer'; "
    "2) create a pillar 'FastAPI'; "
    "3) set the baseline rating for FastAPI debugging to 'gap'; "
    "4) save a one-line profile that says '# Test learner'. "
    "Then reply with the word DONE."
)


def main() -> None:
    init_db()
    agent = build_agent(PERSONA + "\nUse your tools exactly as the user asks.", ONBOARDING_TOOLS)
    reply = run_turn(agent, new_thread(), INSTRUCTION)
    print("agent reply:", reply.strip()[:200])

    c = connect()
    goals = c.execute("SELECT text FROM goals WHERE horizon='long'").fetchall()
    pillar = c.execute("SELECT id FROM pillars WHERE name='FastAPI'").fetchone()
    rating = c.execute(
        "SELECT r.rating FROM ratings r JOIN pillars p ON p.id=r.pillar_id "
        "WHERE p.name='FastAPI' AND r.axis='debugging'"
    ).fetchone()
    c.close()
    profile = Path(os.environ["EKLAVYA_PROFILE"])

    checks = {
        "goal saved": any("AI engineer" in g["text"] for g in goals),
        "pillar created": pillar is not None,
        "baseline rating set": rating is not None and rating["rating"] == 950.0,
        "profile written": profile.exists() and "Test learner" in profile.read_text(),
    }
    print()
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")
    print("\n" + ("ALL GREEN — agent drives the tools." if all(checks.values())
                   else "SOME CHECKS FAILED — see above."))


if __name__ == "__main__":
    main()
