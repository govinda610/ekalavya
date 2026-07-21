"""Terminal chat parity: `eklavya chats`, `eklavya resume`, and the /chats slash
command — all offline, reusing the chatstore verified elsewhere."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-clichat-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from eklavya import chatstore  # noqa: E402
from eklavya.cli import app  # noqa: E402
from eklavya.commands import handle_slash  # noqa: E402
from eklavya.db import init_db  # noqa: E402

runner = CliRunner()


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_chats_empty():
    r = runner.invoke(app, ["chats"])
    assert r.exit_code == 0 and "No past chats yet" in r.output


def test_chats_lists_seeded():
    chatstore.touch_chat("t1", mode="practice")
    chatstore.rename_chat("t1", "Lists deep dive")
    r = runner.invoke(app, ["chats"])
    assert r.exit_code == 0
    assert "Lists deep dive" in r.output and "practice" in r.output


def test_resume_out_of_range():
    chatstore.touch_chat("t1", mode="practice")
    r = runner.invoke(app, ["resume", "9"])
    assert r.exit_code == 1 and "between 1 and 1" in r.output


def test_resume_none_to_resume():
    r = runner.invoke(app, ["resume"])
    assert r.exit_code == 0 and "No past chats to resume" in r.output


def test_slash_chats():
    chatstore.touch_chat("t1", mode="mock")
    chatstore.rename_chat("t1", "My mock chat")
    out = handle_slash("/chats")
    assert "My mock chat" in out and "mock" in out


def test_slash_chats_prefix_matches():
    out = handle_slash("/ch")            # prefix → chats
    assert "No past chats yet" in out
