"""User settings that persist across web and TUI — a tiny JSON store.

Kept outside the workspace (the agent never touches it). Currently just the
anti-cheat toggle, but any small preference can live here.
"""

from __future__ import annotations

import json

from . import config

_PATH = config.EKLAVYA_HOME / "settings.json"
_DEFAULTS = {"death_on_cheat": True}


def _load() -> dict:
    try:
        return {**_DEFAULTS, **json.loads(_PATH.read_text())}
    except (FileNotFoundError, ValueError):
        return dict(_DEFAULTS)


def _save(data: dict) -> None:
    config.EKLAVYA_HOME.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2))


def get_death_on_cheat() -> bool:
    return bool(_load()["death_on_cheat"])


def set_death_on_cheat(on: bool) -> None:
    data = _load()
    data["death_on_cheat"] = bool(on)
    _save(data)
