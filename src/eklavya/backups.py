"""Versioned, revertible snapshots of the learner's state.

The agent can write state directly with `run_bash` (sqlite3), so before each such
write we snapshot the small state files into a timestamped folder under
``~/.eklavya/backups``. Any model SQL mistake is then one ``eklavya revert`` away.

Snapshots are cheap (the db + profile are tiny), deduped (unchanged state isn't
re-copied), and pruned to the most recent ``KEEP``. A revert first snapshots the
current state, so reverting is itself undoable.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from . import config

KEEP = 20  # how many snapshots to retain


def _state_files() -> dict[str, Path]:
    """base filename -> its live path (the things we snapshot & restore)."""
    return {
        "eklavya.db": config.DB_PATH,
        "profile.md": config.PROFILE_PATH,
        "checkpoints.sqlite": config.CHECKPOINTS_PATH,
    }


def _with_sidecars(path: Path) -> list[Path]:
    """A sqlite file plus its WAL/SHM sidecars, when present, so the copy is consistent."""
    return [p for p in (path, path.with_name(path.name + "-wal"),
                        path.with_name(path.name + "-shm")) if p.exists()]


def _state_hash() -> str:
    """Fingerprint of the learner STATE (db + profile) — what a bad write corrupts.
    Deliberately excludes checkpoints (chat history changes every turn)."""
    h = hashlib.sha1()
    for name in ("eklavya.db", "profile.md"):
        p = _state_files()[name]
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()


def list_snapshots() -> list[dict]:
    """All snapshots, newest first, as their meta dicts."""
    root = config.BACKUPS_DIR
    if not root.exists():
        return []
    metas = []
    for d in root.iterdir():
        meta = d / "meta.json"
        if d.is_dir() and meta.exists():
            try:
                metas.append(json.loads(meta.read_text()))
            except (ValueError, OSError):
                continue
    return sorted(metas, key=lambda m: m.get("id", ""), reverse=True)


def _prune() -> None:
    for meta in list_snapshots()[KEEP:]:
        shutil.rmtree(config.BACKUPS_DIR / meta["id"], ignore_errors=True)


def snapshot(reason: str = "") -> str:
    """Copy the current state into a new snapshot folder; return its id."""
    snap_id = f"snap_{time.time_ns()}"
    dest = config.BACKUPS_DIR / snap_id
    dest.mkdir(parents=True, exist_ok=True)
    for live in _state_files().values():
        for f in _with_sidecars(live):
            shutil.copy2(f, dest / f.name)
    meta = {"id": snap_id, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason, "state_hash": _state_hash()}
    (dest / "meta.json").write_text(json.dumps(meta, indent=2))
    _prune()
    return snap_id


def snapshot_if_changed(reason: str = "") -> str | None:
    """Snapshot only when the state differs from the most recent snapshot.
    Keeps read-only commands from piling up identical backups. Returns the id or None."""
    latest = list_snapshots()
    if latest and latest[0].get("state_hash") == _state_hash():
        return None
    return snapshot(reason)


def revert(snap_id: str | None = None) -> dict:
    """Restore a snapshot (default: the latest). Snapshots the current state first,
    so the revert can itself be reverted. Returns the restored meta."""
    snaps = list_snapshots()
    if not snaps:
        raise ValueError("No snapshots to revert to.")
    target = snaps[0] if snap_id is None else next((m for m in snaps if m["id"] == snap_id), None)
    if target is None:
        raise ValueError(f"No snapshot named {snap_id!r}.")

    snapshot(reason=f"before revert to {target['id']}")  # make the revert undoable

    src = config.BACKUPS_DIR / target["id"]
    for live in _state_files().values():
        for stale in _with_sidecars(live):  # clear live main + sidecars first
            stale.unlink()
        live.parent.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():             # restore whatever the snapshot captured
            if f.name == live.name or f.name.startswith(live.name + "-"):
                shutil.copy2(f, live.parent / f.name)
    return target
