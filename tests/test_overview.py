"""Unified Overview (#83) — the /progress route and the superset render.

The Overview must be a COMPLETE SUPERSET of the three former views (Dashboard, Journey,
Effectiveness): every metric/chart/list they showed still appears in one page. These tests
guard the route, the pure render, and that each band's headline landmarks are present.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-overview-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import overview_view, progress, report, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402
from eklavya.webapp import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def _seed():
    tools.add_pillar("Python")
    tools.add_pillar("SQL", subject="coding")
    progress.start_session(30)
    tools.record_attempt("Python", "recall", "list comprehension", 3, True, 12.0)
    tools.record_attempt("Python", "debugging", "off-by-one", 2, True, 20.0)
    tools.record_attempt("SQL", "recall", "group by", 1, False, 30.0)
    tools.record_attempt("Python", "recall", "list comprehension", 2, False, 15.0, ai_off=False)
    tools.add_goal("short", "Solve 3 problems unaided")


# -- landmarks that prove each former view's content is present in the one page --
DASHBOARD_LANDMARKS = ["illusion of knowing", "Skill map", "Skill axes",
                       "Unaided", "Achievements", "Chronicle", "TODAY'S QUEST", "Active quests"]
JOURNEY_LANDMARKS = ["Milestones", "Activity", "XP over time", "last 12 weeks"]
EFFECTIVENESS_LANDMARKS = ["Benchmark ability", "dependency gap", "Ability trajectory",
                           "Retention", "Calibration", "Effort so far", "Real-world outcomes",
                           "By subject"]


def test_render_is_pure_html_superset():
    _seed()
    html = overview_view.render()
    assert html.startswith("<!DOCTYPE html>")
    assert "YOUR PROGRESS" in html
    assert "/static/fonts.css" in html            # vendored fonts, no CDN (#35)
    assert "fonts.googleapis.com" not in html
    for tok in DASHBOARD_LANDMARKS + JOURNEY_LANDMARKS + EFFECTIVENESS_LANDMARKS:
        assert tok in html, f"unified overview dropped: {tok!r}"


def test_per_subject_strip_appears():
    _seed()
    html = overview_view.render()
    # at least one active subject → at least one per-subject strip with its θ/verdict/strengths
    assert "subject-strip" in html
    assert "Strengths" in html and "Invest here" in html


def test_badges_and_chronicle_are_richer():
    """The journey band renders game BADGES (tier + ring) and a chronicle FEED
    (not a bare table) — the superset landmarks still pass, just richer markup."""
    _seed()
    html = overview_view.render()
    assert "badgegrid" in html and "chronfeed" in html
    assert "tier-" in html          # rarity treatment present
    assert "cxp" in html            # XP shown as a prominent pill, not a table cell


def test_chronicle_xp_is_live_not_stored_zero():
    """The chronicle credits XP from the rewards ledger, so an OPEN sitting that
    never called end_session (stored xp=0) still shows the XP it earned — the
    "+0 XP on every row" bug. Also guards the session/reward timestamp-format
    mismatch (aware ISO vs SQLite datetime('now')) that a naive string compare
    would get wrong."""
    tools.add_pillar("Python")
    progress.start_session(30, "boss")           # a sitting we deliberately never wrap up
    tools.record_attempt("Python", "recall", "generators", 3, True, 10.0)
    tools.record_attempt("Python", "debugging", "closures", 2, True, 20.0)

    sessions = report.recent_sessions()
    assert sessions and int(sessions[0]["xp"] or 0) == 0   # stored xp not backfilled yet
    ledger = overview_view._session_ledger_xp(sessions)
    live = ledger.get(sessions[0]["started_at"], 0)
    assert live > 0, "open sitting should surface its ledger XP, not a false +0"


def test_progress_route_serves():
    from starlette.testclient import TestClient

    _seed()
    c = TestClient(create_app())
    r = c.get("/progress")
    assert r.status_code == 200
    assert "YOUR PROGRESS" in r.text and "Skill map" in r.text


def test_legacy_routes_still_serve():
    """The three legacy pages stay reachable (back-compat) even though the nav unified them."""
    from starlette.testclient import TestClient

    _seed()
    c = TestClient(create_app())
    for path in ("/dashboard", "/journey", "/effectiveness"):
        assert c.get(path).status_code == 200


def test_spa_nav_has_one_progress_entry_not_three():
    """The left rail collapses Dashboard+Journey+Effectiveness into ONE 'Overview' entry."""
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    spa = c.get("/").text
    assert 'data-rail="prog"' in spa
    assert 'src="/progress"' in spa
    # the three old rail targets are gone from the SPA
    assert 'data-rail="dash"' not in spa
    assert 'data-rail="journey"' not in spa
    assert 'data-rail="effect"' not in spa
