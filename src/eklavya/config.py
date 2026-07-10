"""Where Ekalavya keeps its state, and how it reads configuration.

Two stores, one truth (see PLAN §12):
  - profile.md  → the human-readable learner model, SHARED with Teacher Mode
  - eklavya.db  → the structured state (ratings, cards, goals, ...)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env if present, so credentials don't have to live in the shell.
load_dotenv()

# The tutor's own home.
EKLAVYA_HOME = Path(os.environ.get("EKLAVYA_HOME", Path.home() / ".eklavya"))
DB_PATH = EKLAVYA_HOME / "eklavya.db"

# Ekalavya keeps its own learner profile inside its home, so it never overwrites a
# teacher-mode profile you may already have. Point EKLAVYA_PROFILE at
# ~/.ai-teacher/profile.md yourself if you want them shared.
PROFILE_PATH = Path(os.environ.get("EKLAVYA_PROFILE", EKLAVYA_HOME / "profile.md"))

# Which provider/model to teach with by default (overridable via env).
DEFAULT_PROVIDER = os.environ.get("EKLAVYA_PROVIDER", "glm")


def ensure_home() -> Path:
    """Create the tutor's home directory if it doesn't exist yet."""
    EKLAVYA_HOME.mkdir(parents=True, exist_ok=True)
    return EKLAVYA_HOME
