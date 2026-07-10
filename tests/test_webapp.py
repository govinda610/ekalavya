"""Web app route tests (no live model — just wiring + rendering)."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-web-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402
from eklavya.webapp import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def seeded():
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    tools.set_baseline_rating("FastAPI", "debugging", "gap")
    yield


def test_index_serves_the_spa():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    r = c.get("/")
    assert r.status_code == 200
    assert "EKALAVYA" in r.text and "Practice" in r.text and "monaco-editor" in r.text


def test_dashboard_and_apis():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    assert c.get("/dashboard").status_code == 200
    assert "FastAPI" in c.get("/dashboard").text
    ov = c.get("/api/overview")
    assert ov.status_code == 200 and "FastAPI" in ov.json()["grid"]["pillars"]
    cfg = c.get("/api/config").json()
    assert "practice" in cfg["kickoff"] and "provider" in cfg


def test_config_includes_first_run_and_onboard():
    from starlette.testclient import TestClient

    from eklavya import config
    from eklavya.db import connect

    client = TestClient(create_app())
    # seeded fixture added a rating -> not a first run
    assert client.get("/api/config").json()["first_run"] is False
    assert "onboard" in client.get("/api/config").json()["kickoff"]
    # wipe ratings + profile -> first run
    conn = connect()
    conn.execute("DELETE FROM ratings")
    conn.commit()
    conn.close()
    if config.PROFILE_PATH.exists():
        config.PROFILE_PATH.unlink()
    assert client.get("/api/config").json()["first_run"] is True


def test_death_and_reclaim_endpoints():
    from starlette.testclient import TestClient

    from eklavya import progress

    c = TestClient(create_app())
    progress.award_xp(80)
    st = c.get("/api/stats").json()
    assert st["xp"] >= 80
    pen = c.post("/api/penalise").json()
    assert pen["lost"] > 0 and pen["stats"]["streak"] == 0  # souls dropped, streak broken
    rec = c.post("/api/reclaim").json()
    assert rec["reclaimed"] == pen["lost"]  # typed-it-yourself reclaims the drop
