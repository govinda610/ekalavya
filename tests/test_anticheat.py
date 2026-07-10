"""Anti-cheat: the deterministic penalty, and the TUI paste -> 'You Died' flow."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-cheat-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import progress  # noqa: E402
from eklavya.db import init_db  # noqa: E402
from eklavya.tui import EklavyaApp  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def test_penalise_drops_xp_and_breaks_streak():
    progress.award_xp(120)
    progress.touch_streak("2026-07-09")
    lost = progress.penalise("test", xp_loss=50)["lost"]
    assert lost == 50
    s = progress.stats()
    assert s["xp"] == 70 and s["streak"] == 0


def test_penalise_never_goes_negative():
    progress.award_xp(20)
    assert progress.penalise("test", xp_loss=50)["lost"] == 20
    assert progress.stats()["xp"] == 0


async def test_pasted_code_triggers_death_and_is_not_sent():
    sent = []
    app = EklavyaApp(responder=lambda t: sent.append(t) or "ok", use_worker=False, guard=True)
    async with app.run_test():
        progress.award_xp(100)
        app.action_toggle_editor()          # open editor
        app._editor_pasted = True           # simulate a paste
        app.query_one("#editor").text = "def f(): return 1"
        app.action_submit_code()
        # Death recorded, XP dropped, and the pasted code was NOT sent to the agent.
        assert ("death", "code was pasted into the editor") in app.history
        assert progress.stats()["xp"] < 100
        assert not any("def f()" in s for s in sent)


def test_penalise_sets_penance_and_reclaim_restores():
    progress.award_xp(100)
    progress.penalise("t", xp_loss=40)
    assert progress.penance() == 40 and progress.stats()["xp"] == 60
    assert progress.reclaim() == 40
    assert progress.penance() == 0 and progress.stats()["xp"] == 100


async def test_typed_after_death_reclaims_souls():
    sent = []
    app = EklavyaApp(responder=lambda t: sent.append(t) or "ok", use_worker=False, guard=True)
    async with app.run_test():
        progress.award_xp(100)
        # die by pasting
        app.action_toggle_editor()
        app._editor_pasted = True
        app.query_one("#editor").text = "x = 1"
        app.action_submit_code()
        xp_after_death = progress.stats()["xp"]
        assert progress.penance() > 0 and xp_after_death < 100

        # type the next answer yourself -> reclaim
        app.action_toggle_editor()
        app._editor_pasted = False
        app.query_one("#editor").text = "def f(): return 1"
        app.action_submit_code()
        assert progress.penance() == 0
        assert progress.stats()["xp"] > xp_after_death
        assert any(role == "reclaim" for role, _ in app.history)
        assert any("def f()" in s for s in sent)


async def test_typed_code_is_sent_normally():
    sent = []
    app = EklavyaApp(responder=lambda t: sent.append(t) or "ok", use_worker=False, guard=True)
    async with app.run_test():
        app.action_toggle_editor()
        app._editor_pasted = False          # typed, not pasted
        app.query_one("#editor").text = "def f(): return 1"
        app.action_submit_code()
        assert any("def f()" in s for s in sent)
