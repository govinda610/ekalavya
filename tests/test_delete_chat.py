"""Deleting a chat removes its sidebar row AND its durable checkpointer state,
leaving other threads untouched (offline — seeds the checkpointer rows directly)."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-delchat-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import chatstore, config  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db = config.paths().db
    if db.exists():
        db.unlink()
    init_db()
    # Reset the checkpointer sqlite too (it survives across tests otherwise): drop the
    # cached savers/readers and the file, then recreate the tables for this temp home.
    chatstore._savers.clear()
    chatstore._readers.clear()
    ck = config.paths().checkpoints
    for suffix in ("", "-wal", "-shm"):
        p = ck.parent / (ck.name + suffix)
        if p.exists():
            p.unlink()
    chatstore.get_checkpointer()
    yield


def _seed_checkpoint_rows(thread_id: str) -> None:
    """Insert minimal valid rows for a thread into both checkpointer tables."""
    cp = connect(config.paths().checkpoints)
    try:
        cp.execute(
            "INSERT INTO checkpoints(thread_id, checkpoint_id) VALUES(?, ?)",
            (thread_id, "ckpt-1"),
        )
        cp.execute(
            "INSERT INTO writes(thread_id, checkpoint_id, task_id, idx, channel) "
            "VALUES(?, ?, ?, ?, ?)",
            (thread_id, "ckpt-1", "task-1", 0, "messages"),
        )
        cp.commit()
    finally:
        cp.close()


def _counts(thread_id: str) -> tuple[int, int]:
    cp = connect(config.paths().checkpoints)
    try:
        n_ck = cp.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0]
        n_wr = cp.execute(
            "SELECT COUNT(*) FROM writes WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0]
    finally:
        cp.close()
    return n_ck, n_wr


def test_delete_chat_removes_row_and_checkpoints():
    chatstore.touch_chat("t-del", mode="practice")
    chatstore.touch_chat("t-keep", mode="onboard")
    _seed_checkpoint_rows("t-del")
    _seed_checkpoint_rows("t-keep")
    assert _counts("t-del") == (1, 1)

    assert chatstore.delete_chat("t-del") is True

    # The deleted thread's chats row and checkpointer rows are gone.
    assert {c["thread_id"] for c in chatstore.list_chats()} == {"t-keep"}
    assert _counts("t-del") == (0, 0)
    # A different thread is untouched.
    assert _counts("t-keep") == (1, 1)


def test_delete_chat_missing_returns_false_and_is_safe():
    chatstore.touch_chat("t-keep", mode="practice")
    _seed_checkpoint_rows("t-keep")

    # No chat row for this thread → returns False, and nothing else is harmed.
    assert chatstore.delete_chat("nope") is False
    assert {c["thread_id"] for c in chatstore.list_chats()} == {"t-keep"}
    assert _counts("t-keep") == (1, 1)
