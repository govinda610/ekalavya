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

# The agent's WORKSPACE — its own read/write area. The learner db and profile live
# here so the agent can manage them with its own file tools; the agent's writes are
# confined to it. Backups and the chat checkpointer stay OUTSIDE it (see below), so a
# mistaken write is always recoverable and secrets are never in reach.
WORKSPACE = Path(os.environ.get("EKLAVYA_WORKSPACE", EKLAVYA_HOME / "workspace"))
DB_PATH = WORKSPACE / "eklavya.db"

# Ekalavya keeps its own learner profile inside the workspace. Point EKLAVYA_PROFILE
# elsewhere yourself if you want it shared (e.g. ~/.ai-teacher/profile.md).
PROFILE_PATH = Path(os.environ.get("EKLAVYA_PROFILE", WORKSPACE / "profile.md"))

# App internals the agent must never touch — kept OUTSIDE the workspace.
BACKUPS_DIR = EKLAVYA_HOME / "backups"
CHECKPOINTS_PATH = EKLAVYA_HOME / "checkpoints.sqlite"

# Which provider/model to teach with by default (overridable via env).
DEFAULT_PROVIDER = os.environ.get("EKLAVYA_PROVIDER", "glm")


def ensure_home() -> Path:
    """Create the tutor's home + workspace if they don't exist yet."""
    EKLAVYA_HOME.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return EKLAVYA_HOME
