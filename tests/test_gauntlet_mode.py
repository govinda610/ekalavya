"""The Gauntlet mode is wired uniformly (prompt + every mode map + SPA option + config)."""

import os
import tempfile

os.environ["EKLAVYA_HOME"] = tempfile.mkdtemp(prefix="eklavya-gaunt-")

from eklavya import prompts, webapp  # noqa: E402


def test_gauntlet_prompt_has_the_run_mechanics():
    g = prompts.GAUNTLET
    assert "THE GAUNTLET" in g
    assert "streak" in g                                   # the run score
    assert "resets the RUN, never the LEARNING" in g       # the non-negotiable constraint
    assert "grade_and_record" in g and "suggest_focus" in g  # reuses grader + weak-cell aim


def test_gauntlet_registered_in_every_mode_map():
    assert webapp._PROMPTS["gauntlet"] is prompts.GAUNTLET
    assert "gauntlet" in webapp._KICKOFF
    assert "gauntlet" in webapp._MODE_LABEL
    assert "gauntlet" in webapp._SESSION_MODES          # opens a session + gets the clock
    assert webapp._SESSION_MIN["gauntlet"] == 20
    assert 'value="gauntlet"' in webapp._INDEX          # selectable in the SPA


def test_config_route_exposes_gauntlet_kickoff():
    from starlette.testclient import TestClient

    cfg = TestClient(webapp.create_app()).get("/api/config").json()
    assert "gauntlet" in cfg["kickoff"]
