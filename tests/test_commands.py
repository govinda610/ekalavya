"""Slash-command routing tests."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-cmd-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

from eklavya.commands import EXIT, handle_slash  # noqa: E402
from eklavya.db import init_db  # noqa: E402

init_db()


def test_plain_text_is_not_a_command():
    assert handle_slash("write a function") is None


def test_exit_aliases():
    assert handle_slash("/exit") == EXIT
    assert handle_slash("/quit") == EXIT
    assert handle_slash("/q") == EXIT


def test_help_lists_commands():
    out = handle_slash("/help")
    assert "/stats" in out and "/goals" in out


def test_prefix_matching_resolves_stats():
    out = handle_slash("/st")  # -> /stats
    assert out is not None and ("streak" in out.lower() or "xp" in out.lower())


def test_unknown_command():
    assert "Unknown" in handle_slash("/zzz")
