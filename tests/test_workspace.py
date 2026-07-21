"""The agent's filesystem backend: read-broad, write/edit confined to /workspace.
Cross-platform, zero-dep confinement via deepagents' CompositeBackend."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-ws-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya.workspace import build_backend, workspace_dir  # noqa: E402


def _denied(fn) -> bool:
    """A write is confined whether the backend raises or returns an error result."""
    try:
        return getattr(fn(), "error", None) is not None
    except Exception:
        return True


@pytest.fixture
def be():
    return build_backend()


def test_write_inside_workspace_works(be):
    r = be.write("/workspace/note.txt", "hi")
    assert getattr(r, "error", None) is None
    assert (workspace_dir() / "note.txt").read_text() == "hi"


def test_write_cannot_escape_via_traversal(be):
    assert _denied(lambda: be.write("/workspace/../escape.txt", "x"))


def test_write_cannot_touch_host_paths(be):
    assert _denied(lambda: be.write("/etc/evil.txt", "x"))
    home_file = Path.home() / "eklavya_ws_escape_test.txt"
    assert _denied(lambda: be.write(str(home_file), "x"))
    assert not home_file.exists()


def test_read_is_broad(be):
    readme = Path(__file__).resolve().parents[1] / "README.md"
    assert "Ekalavya" in str(be.read(str(readme)))


def test_forbidden_reads_denied(be):
    assert "not allowed" in str(be.read(str(Path.home() / ".ssh" / "id_rsa")))
