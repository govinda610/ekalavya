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
    import shutil

    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    # Clear the file-based artifacts drop-folder too, so file-import tests are isolated.
    art_root = _cfg.paths().workspace / "artifacts"
    if art_root.exists():
        shutil.rmtree(art_root)
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


def test_save_artifact_tool_is_gone():
    # The explicit save tool is replaced by automatic, file-based persistence.
    from eklavya import tools

    assert not hasattr(tools, "save_artifact")
    assert not any(getattr(t, "__name__", "") == "save_artifact" for t in tools.AGENT_TOOLS)


def _artifacts_root():
    from eklavya import config

    root = config.paths().workspace / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_import_bridge_imports_file_with_title_kind_pillar():
    from eklavya import artifact_import

    root = _artifacts_root()
    (root / "python-fundamentals").mkdir(parents=True, exist_ok=True)
    (root / "python-fundamentals" / "copy-vs-deepcopy.html").write_text(
        "<!doctype html><html><head><title>Copy vs Deepcopy</title></head>"
        "<body><h1>hi</h1></body></html>", encoding="utf-8")

    n = artifact_import.import_new()
    assert n == 1
    rows = artifacts.list_artifacts()
    a = next(r for r in rows if r["rel_path"] == "artifacts/python-fundamentals/copy-vs-deepcopy.html")
    assert a["title"] == "Copy vs Deepcopy"          # from <title>
    assert a["kind"] == "html"                        # from extension
    assert a["pillar"] == "Python Fundamentals"       # from folder slug


def test_import_bridge_dedupes_unchanged_and_updates_changed():
    from eklavya import artifact_import

    root = _artifacts_root()
    f = root / "note.md"
    f.write_text("# First heading\nbody", encoding="utf-8")

    assert artifact_import.import_new() == 1       # imported
    assert artifact_import.import_new() == 0       # unchanged → skipped (no duplicate)
    rows = artifacts.list_artifacts(query="First heading")
    assert len(rows) == 1
    a = rows[0]
    assert a["title"] == "First heading"           # markdown first heading
    assert a["kind"] == "markdown"
    assert a["pillar"] is None                     # dropped at the root → no pillar

    f.write_text("# Second heading\nnew body", encoding="utf-8")
    assert artifact_import.import_new() == 1        # changed → updated (still one row)
    same = artifacts.get(a["id"])
    assert same["title"] == "Second heading"
    assert same["content"] == "# Second heading\nnew body"


def test_import_bridge_title_from_filename_for_code():
    from eklavya import artifact_import

    root = _artifacts_root()
    (root / "two_sum_solution.py").write_text("def two_sum(): pass\n", encoding="utf-8")
    artifact_import.import_new()
    rows = artifacts.list_artifacts(kind="code")
    a = next(r for r in rows if r["rel_path"] == "artifacts/two_sum_solution.py")
    assert a["title"] == "Two Sum Solution"        # prettified filename
    assert a["kind"] == "code"
