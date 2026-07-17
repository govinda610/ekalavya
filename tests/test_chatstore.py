"""Chats-index metadata (offline). Transcript reconstruction is verified live
(needs a real agent + checkpointer) — see the persistence checks in scripts/manual runs."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-chat-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import chatstore  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_touch_creates_and_lists():
    chatstore.touch_chat("t1", mode="practice")
    chatstore.touch_chat("t2", mode="onboard")
    chats = {c["thread_id"]: c for c in chatstore.list_chats()}
    assert set(chats) == {"t1", "t2"}
    assert chats["t2"]["mode"] == "onboard"
    assert chats["t1"]["title"] is None


def test_rename_and_get_title():
    chatstore.touch_chat("t1", mode="practice")
    assert chatstore.get_title("t1") is None
    chatstore.rename_chat("t1", "  Data structures deep dive  ")
    assert chatstore.get_title("t1") == "Data structures deep dive"


def test_touch_is_idempotent_and_preserves_title():
    chatstore.touch_chat("t1", mode="practice")
    chatstore.rename_chat("t1", "My chat")
    chatstore.touch_chat("t1", mode="practice")            # a later turn bumps updated_at
    assert chatstore.get_title("t1") == "My chat"          # title is not clobbered
    assert len(chatstore.list_chats()) == 1                # still one row
