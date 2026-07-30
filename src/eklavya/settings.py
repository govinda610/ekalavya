"""User settings that persist across web and TUI — a tiny JSON store.

Kept outside the workspace (the agent never touches it). Holds the small preferences
the Settings screen exposes: the anti-cheat toggle, reduced-motion, guru-voice, and the
chosen model provider. Per-user (contextvar-aware) in multi-user mode.
"""

from __future__ import annotations

import json

from . import config

# provider defaults to None → "use the env default / auto-pick" (providers.pick).
_DEFAULTS = {
    "death_on_cheat": True,
    "reduced_motion": False,
    "guru_voice": True,
    "provider": None,
}


def _path():
    """The current user's settings file (contextvar-aware, so per-user in multi-user)."""
    return config.paths().home / "settings.json"


def _load() -> dict:
    try:
        return {**_DEFAULTS, **json.loads(_path().read_text())}
    except (FileNotFoundError, ValueError):
        return dict(_DEFAULTS)


def _save(data: dict) -> None:
    home = config.paths().home
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps(data, indent=2))


def get_all() -> dict:
    """Every setting, defaults merged. Safe to expose to the client."""
    return _load()


def update(**changes) -> dict:
    """Patch the given settings and return the full merged set. Unknown keys are ignored."""
    data = _load()
    for key in _DEFAULTS:
        if key in changes and changes[key] is not None:
            if key == "provider":
                data[key] = str(changes[key]) or None
            elif key in ("death_on_cheat", "reduced_motion", "guru_voice"):
                data[key] = bool(changes[key])
    _save(data)
    return data


def get_death_on_cheat() -> bool:
    return bool(_load()["death_on_cheat"])


def set_death_on_cheat(on: bool) -> None:
    data = _load()
    data["death_on_cheat"] = bool(on)
    _save(data)


def get_provider() -> str | None:
    return _load().get("provider")
