"""Journey view tests — data functions + render + route."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-journey-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import journey, progress, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_achievements_earned_and_locked():
    achs = journey.achievements()
    titles = {a["title"] for a in achs}
    assert "On Fire" in titles and "Devoted" in titles
    # Initiate not earned until a session exists
    assert not [a for a in achs if a["title"] == "Initiate"][0]["earned"]
    progress.start_session(30)
    progress.end_session()
    assert [a for a in journey.achievements() if a["title"] == "Initiate"][0]["earned"]


def test_milestones_and_xp_curve():
    progress.award_xp(120)  # crosses into level 2
    assert any("Level 2" in label for _d, _i, label in journey.milestones())
    assert journey.xp_curve()[-1][1] == 120


def test_activity_counts_attempts():
    tools.record_attempt("X", "debugging", "c", 2, True)
    assert sum(journey.activity().values()) >= 1


def test_render_and_route():
    html = journey.render()
    assert "YOUR JOURNEY" in html and "Achievements" in html
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    assert TestClient(create_app()).get("/journey").status_code == 200
