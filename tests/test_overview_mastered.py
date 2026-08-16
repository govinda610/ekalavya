"""Overview 'groves mastered' must equal the forest's blossoming grove count.

Regression for the reported mismatch: the Overview showed '0 groves mastered' while
the forest map showed blossoming (mastered) groves. The Overview counted strong grid
CELLS (rating-based, per axis) — a different aggregation from the forest's blossoming
grove (every concept in the grove has a correct attempt). They must agree.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-ovmaster-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import report, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    if _cfg.DB_PATH.exists():
        _cfg.DB_PATH.unlink()
    init_db()
    yield


def _blossoming_count() -> int:
    fm = report.forest_map()
    if fm.get("empty"):
        return 0
    # 'active' is a rendering overlay on a non-mastered grove; blossoming == done==total.
    return sum(1 for g in fm["groves"] if g["total"] > 0 and g["done"] == g["total"])


def test_overview_mastered_matches_forest_blossoming():
    # One grove fully mastered (every concept has a correct attempt), one only partial.
    tools.add_pillar("Recursion")
    tools.add_curriculum("base case", "", "Recursion")
    tools.add_curriculum("recursive step", "base case", "Recursion")
    tools.add_pillar("Graphs")
    tools.add_curriculum("BFS", "", "Graphs")
    tools.add_curriculum("DFS", "", "Graphs")

    # Recursion → all concepts correct → blossoming.
    tools.record_attempt("Recursion", "application", "base case", 2, True, 5.0)
    tools.record_attempt("Recursion", "application", "recursive step", 2, True, 5.0)
    # Graphs → only one concept correct → NOT blossoming.
    tools.record_attempt("Graphs", "application", "BFS", 2, True, 5.0)

    blossoming = _blossoming_count()
    assert blossoming == 1, "exactly one grove should be fully mastered"

    ov = report.overview()
    assert ov["mastered_groves"] == blossoming
    assert report.mastered_groves() == blossoming


def test_overview_mastered_is_zero_when_nothing_blossoms():
    tools.add_pillar("Trees")
    tools.add_curriculum("traversal", "", "Trees")
    # A rating that reads 'strong' on the grid but NO correct attempt → the grove does not
    # blossom, and the Overview mastered count must be 0 (not counting strong cells).
    tools.set_baseline_rating("Trees", "syntax_recall", "strong")

    assert _blossoming_count() == 0
    assert report.overview()["mastered_groves"] == 0
