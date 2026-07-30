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


def test_profile_view_and_edit_roundtrip():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    # the page renders with the editor textarea + the mastery map (seeded FastAPI pillar)
    page = c.get("/profile")
    assert page.status_code == 200
    assert 'id="pedit"' in page.text and "Mastery map" in page.text and "FastAPI" in page.text
    # starts empty, saves, and reads back
    assert c.get("/api/profile").json()["text"] == ""
    c.put("/api/profile", json={"text": "# Me\n\n- goal: **PhD at ETH**"})
    assert "ETH" in c.get("/api/profile").json()["text"]
    # the rendered page embeds the saved markdown (recoverable from the textarea)
    assert "PhD at ETH" in c.get("/profile").text


def test_settings_toggle_persists_and_shows_in_config():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    assert c.get("/api/config").json()["death_on_cheat"] is True  # default on
    assert c.put("/api/settings", json={"death_on_cheat": False}).json()["death_on_cheat"] is False
    assert c.get("/api/config").json()["death_on_cheat"] is False  # persisted
    c.put("/api/settings", json={"death_on_cheat": True})          # restore for other tests


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


def test_artifacts_crud_endpoints():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    # empty to start
    assert c.get("/api/artifacts").json() == []
    # create
    a = c.post("/api/artifacts", json={"title": "Recursion", "kind": "markdown",
                                       "content": "# base case"}).json()
    aid = a["id"]
    assert a["title"] == "Recursion" and a["kind"] == "markdown"
    # get
    got = c.get(f"/api/artifacts/{aid}").json()
    assert got["content"] == "# base case"
    assert c.get("/api/artifacts/99999").status_code == 404
    # list + filter + search
    c.post("/api/artifacts", json={"title": "tree.py", "kind": "code", "content": "def f(): pass"})
    assert len(c.get("/api/artifacts").json()) == 2
    assert [x["kind"] for x in c.get("/api/artifacts?kind=code").json()] == ["code"]
    assert len(c.get("/api/artifacts?q=Recursion").json()) == 1
    # patch (pin)
    patched = c.patch(f"/api/artifacts/{aid}", json={"pinned": True, "content": "# updated"}).json()
    assert patched["pinned"] is True and patched["content"] == "# updated"
    assert c.patch("/api/artifacts/99999", json={"title": "x"}).status_code == 404
    # pinned floats first
    assert c.get("/api/artifacts").json()[0]["id"] == aid
    # delete
    assert c.delete(f"/api/artifacts/{aid}").json() == {"ok": True}
    assert c.get(f"/api/artifacts/{aid}").status_code == 404
    assert c.delete(f"/api/artifacts/{aid}").status_code == 404


def test_settings_get_and_put():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    s = c.get("/api/settings").json()
    assert "death_on_cheat" in s and "reduced_motion" in s and "guru_voice" in s
    assert isinstance(s["providers"], list) and s["providers"]
    keys = {p["key"] for p in s["providers"]}
    assert {"glm", "minimax", "qwen", "kimi"} <= keys
    # update several prefs at once
    r = c.put("/api/settings", json={"reduced_motion": True, "guru_voice": False}).json()
    assert r["reduced_motion"] is True and r["guru_voice"] is False
    assert c.get("/api/settings").json()["reduced_motion"] is True   # persisted
    # legacy shape still works
    c.put("/api/settings", json={"death_on_cheat": True, "reduced_motion": False, "guru_voice": True})
