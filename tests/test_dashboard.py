"""Dashboard tests — the report layer, the pure HTML render, and the live routes.

Isolated to a temp home; seeds a little state and checks it surfaces.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-dash-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import report, tools  # noqa: E402
from eklavya.dashboard import create_app, render  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def seeded_db():
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    tools.set_baseline_rating("FastAPI", "debugging", "gap")
    tools.set_baseline_rating("FastAPI", "api_memory", "strong")
    tools.add_goal("long", "Become an AI engineer")
    yield


def test_report_grid_and_overview():
    ov = report.overview()
    assert "FastAPI" in ov["grid"]["pillars"]
    assert ov["grid"]["pillars"]["FastAPI"]["debugging"]["level"] == "gap"
    assert any("AI engineer" in g["text"] for g in ov["goals"])
    assert set(ov["stats"]) == {"xp", "streak", "level"}


def test_ai_gap_computes_unaided_vs_assisted():
    tools.record_attempt("X", "debugging", "c1", 2, True)                 # unaided, right
    tools.record_attempt("X", "debugging", "c2", 2, False)                # unaided, wrong
    tools.record_attempt("X", "debugging", "c3", 2, True, ai_off=False)   # assisted, right
    ag = report.ai_gap()
    assert ag["unaided_n"] == 2 and ag["unaided_rate"] == 50
    assert ag["assisted_n"] == 1 and ag["assisted_rate"] == 100
    assert ag["gap"] == 50 and len(ag["trend"]) >= 1


def test_render_is_pure_html_with_data():
    html = render(report.overview())
    assert "<!DOCTYPE html>" in html
    assert "FastAPI" in html and "Skill map" in html
    assert "Become an AI engineer" in html


def test_routes_serve():
    from starlette.testclient import TestClient

    client = TestClient(create_app())
    home = client.get("/")
    assert home.status_code == 200 and "FastAPI" in home.text
    api = client.get("/api/overview")
    assert api.status_code == 200 and "FastAPI" in api.json()["grid"]["pillars"]
