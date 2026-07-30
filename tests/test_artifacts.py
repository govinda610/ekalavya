"""Canvas artifacts store — CRUD, pin, filter/search (offline)."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-art-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import artifacts  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_create_and_get():
    a = artifacts.create("Recursion, illustrated", "markdown", "# base case\n")
    assert a["id"] > 0
    assert a["title"] == "Recursion, illustrated"
    assert a["kind"] == "markdown"
    assert a["pinned"] is False
    got = artifacts.get(a["id"])
    assert got["content"] == "# base case\n"


def test_get_missing_returns_none():
    assert artifacts.get(9999) is None


def test_kind_is_normalised():
    a = artifacts.create("x", "CODE", "print(1)")
    assert a["kind"] == "code"
    b = artifacts.create("y", "nonsense", "z")
    assert b["kind"] == "markdown"  # unknown → markdown


def test_list_orders_pinned_then_newest():
    a = artifacts.create("first", "markdown", "a")
    b = artifacts.create("second", "code", "b")
    artifacts.pin(a["id"], True)
    ids = [x["id"] for x in artifacts.list_artifacts()]
    assert ids[0] == a["id"]  # pinned floats to the top
    assert b["id"] in ids


def test_list_filter_by_kind():
    artifacts.create("lesson", "markdown", "m")
    c = artifacts.create("snippet", "code", "print(1)")
    only_code = artifacts.list_artifacts(kind="code")
    assert [x["id"] for x in only_code] == [c["id"]]


def test_list_search_title_and_content():
    artifacts.create("Big-O felt", "viz", "complexity chart")
    artifacts.create("Two pointers", "markdown", "converge and chase")
    hits = artifacts.list_artifacts(query="converge")
    assert len(hits) == 1
    assert hits[0]["title"] == "Two pointers"
    hits2 = artifacts.list_artifacts(query="Big-O")
    assert len(hits2) == 1


def test_update_patches_only_given_fields():
    a = artifacts.create("t", "markdown", "old")
    updated = artifacts.update(a["id"], content="new")
    assert updated["content"] == "new"
    assert updated["title"] == "t"  # untouched
    assert updated["updated_at"] >= a["updated_at"]


def test_update_missing_returns_none():
    assert artifacts.update(9999, title="x") is None


def test_pin_toggles():
    a = artifacts.create("t", "markdown", "x")
    assert artifacts.pin(a["id"], True)["pinned"] is True
    assert artifacts.pin(a["id"], False)["pinned"] is False


def test_delete():
    a = artifacts.create("t", "markdown", "x")
    assert artifacts.delete(a["id"]) is True
    assert artifacts.get(a["id"]) is None
    assert artifacts.delete(a["id"]) is False  # already gone


def test_save_artifact_tool_creates_and_is_registered():
    from eklavya import tools

    out = tools.save_artifact("Recursion", "markdown", "# the return upon itself")
    assert "saved artifact" in out
    rows = artifacts.list_artifacts()
    assert any(r["title"] == "Recursion" and r["kind"] == "markdown" for r in rows)
    assert tools.save_artifact in tools.AGENT_TOOLS
