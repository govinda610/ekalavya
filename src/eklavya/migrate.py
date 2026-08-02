"""One-shot, guarded migration of the single-user home into the multi-user layout.

Copies ``~/.eklavya`` (the single-user home) into ``$EKLAVYA_DATA_ROOT/users/<uid>/``,
verifies row-for-row parity, stamps chat ownership, and NEVER touches the original — so
it is fully reversible (just keep using ``~/.eklavya`` if anything looks wrong). Stop the
app before running it, so the database isn't being written mid-copy. Run once per account.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from . import config

# Row counts that MUST match exactly after the copy (every table that holds learner state).
_PARITY_TABLES = (
    "pillars", "ratings", "attempts", "goals", "goal_reviews", "curriculum",
    "rating_history", "rewards", "cards", "items", "concepts", "misconceptions",
    "learning_prefs", "chats", "sessions", "repos", "questions", "ai_assists", "meta",
    # Unified subject framework (registry tables carry learner-relevant config).
    "subjects", "axes",
)


def _counts(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        present = {r["name"] for r in
                   conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {t: conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
                for t in _PARITY_TABLES if t in present}
    finally:
        conn.close()


def migrate_single_user(uid: str, source: Path | None = None,
                        dest: Path | None = None, dry_run: bool = False) -> dict:
    """Copy the single-user home at `source` (default ~/.eklavya) into the per-user home
    at `dest` (default $EKLAVYA_DATA_ROOT/users/<uid>), verify parity, and stamp chat
    ownership to `uid`. Returns a report dict. Raises (and cleans up the partial copy,
    leaving the original untouched) if anything fails the parity check. With dry_run=True
    it does the full copy+verify+stamp, then removes the copy — a real rehearsal.
    """
    source = Path(source) if source else config._default_home()
    dest = Path(dest) if dest else config.user_home(uid)

    src_db = source / "workspace" / "eklavya.db"
    if not src_db.exists():
        raise FileNotFoundError(f"no single-user database at {src_db}")
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(
            f"destination {dest} already exists and is non-empty — refusing to overwrite")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest)  # COPY, never move — the original stays put

    try:
        dst_db = dest / "workspace" / "eklavya.db"
        # copytree can capture a LIVE WAL db in a torn state (its committed data may still be
        # in the -wal sidecar), which made the parity check flaky. Re-copy the db as a
        # CONSISTENT snapshot via SQLite's read-only .backup (the source is only READ, never
        # touched), then drop the now-stale WAL sidecars so the copy is self-contained.
        _s = sqlite3.connect(str(src_db)); _d = sqlite3.connect(str(dst_db))
        try:
            _s.backup(_d)
        finally:
            _d.close(); _s.close()
        for _sfx in ("-wal", "-shm"):
            _side = dst_db.parent / (dst_db.name + _sfx)
            if _side.exists():
                _side.unlink()
        before, after = _counts(src_db), _counts(dst_db)
        src_profile = source / "workspace" / "profile.md"
        dst_profile = dest / "workspace" / "profile.md"
        profile_ok = (not src_profile.exists()) or (
            dst_profile.exists() and src_profile.read_bytes() == dst_profile.read_bytes())
        checkpoints_ok = ((source / "checkpoints.sqlite").exists()
                          == (dest / "checkpoints.sqlite").exists())

        if not (before == after and profile_ok and checkpoints_ok):
            raise RuntimeError(
                f"parity check FAILED — counts before={before} after={after} "
                f"profile_ok={profile_ok} checkpoints_ok={checkpoints_ok}")

        # stamp chat ownership (single-user rows had user_id NULL). A pre-multi-user
        # database won't have the column yet, so add it first — the same additive
        # migration the app applies on open — then stamp.
        conn = sqlite3.connect(str(dst_db))
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(chats)")}
            if "user_id" not in cols:
                conn.execute("ALTER TABLE chats ADD COLUMN user_id TEXT")
            conn.execute("UPDATE chats SET user_id = ? WHERE user_id IS NULL", (uid,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)  # abort: leave the original untouched
        raise

    report = {"uid": uid, "source": str(source), "dest": str(dest),
              "tables": after, "profile_ok": profile_ok,
              "checkpoints_ok": checkpoints_ok, "dry_run": dry_run}
    if dry_run:
        shutil.rmtree(dest, ignore_errors=True)  # rehearsal only — remove the copy
    return report
