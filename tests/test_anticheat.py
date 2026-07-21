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


# a large, code-like solution — the only thing that should ever be flagged
BIG_SOLUTION = (
    "def solution(nums):\n"
    "    total = 0\n"
    "    for n in nums:\n"
    "        total += n * n\n"
    "    return total\n"
) * 3


def test_looks_pasted_only_flags_a_big_dominating_paste():
    # big paste that IS the solution → flagged
    assert progress.looks_pasted(BIG_SOLUTION, len(BIG_SOLUTION)) is True
    # a small agent-provided dict pasted to test → NOT flagged (below the size floor)
    assert progress.looks_pasted("prices = {'a': 1, 'b': 2}", 25) is False
    # a big solution the learner TYPED (no big paste) → NOT flagged
    assert progress.looks_pasted(BIG_SOLUTION, 0) is False
    # a big paste of prose (dictation) into a mostly-typed answer → not dominant/among code
    assert progress.looks_pasted("just some notes about my approach here", 300) is False


async def test_pasted_solution_triggers_death_keeps_code_and_is_not_sent():
    sent = []
    app = EklavyaApp(responder=lambda t: sent.append(t) or "ok", use_worker=False, guard=True)
    async with app.run_test():
        progress.award_xp(100)
        app.action_toggle_editor()               # open editor
        app.query_one("#editor").text = BIG_SOLUTION
        app._biggest_paste = len(BIG_SOLUTION)   # simulate the whole thing pasted
        app.action_submit_code()
        # Death recorded, XP dropped, pasted code NOT sent — and the editor is NOT wiped.
        assert ("death", "a full solution was pasted into the editor") in app.history
        assert progress.stats()["xp"] < 100
        assert not any("solution(nums)" in s for s in sent)
        assert app.query_one("#editor").text == BIG_SOLUTION  # work preserved


async def test_small_paste_is_not_flagged():
    sent = []
    app = EklavyaApp(responder=lambda t: sent.append(t) or "ok", use_worker=False, guard=True)
    async with app.run_test():
        progress.award_xp(100)
        app.action_toggle_editor()
        app.query_one("#editor").text = "prices = {'a': 1}\nprint(sum(prices.values()))"
        app._biggest_paste = 17                  # a small agent-provided snippet
        app.action_submit_code()
        assert not any(role == "death" for role, _ in app.history)
        assert progress.stats()["xp"] == 100     # untouched
        assert any("prices" in s for s in sent)  # sent normally


async def test_penalty_off_shows_note_without_dropping_xp():
    sent = []
    app = EklavyaApp(responder=lambda t: sent.append(t) or "ok", use_worker=False, guard=True)
    async with app.run_test():
        progress.award_xp(100)
        app.death_on_cheat = False               # user turned the penalty off
        app.action_toggle_editor()
        app.query_one("#editor").text = BIG_SOLUTION
        app._biggest_paste = len(BIG_SOLUTION)
        app.action_submit_code()
        assert not any(role == "death" for role, _ in app.history)  # no penalty
        assert progress.stats()["xp"] == 100                        # XP untouched
        assert app.query_one("#editor").text == BIG_SOLUTION        # code kept


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
        # die by pasting a full solution
        app.action_toggle_editor()
        app.query_one("#editor").text = BIG_SOLUTION
        app._biggest_paste = len(BIG_SOLUTION)
        app.action_submit_code()
        xp_after_death = progress.stats()["xp"]
        assert progress.penance() > 0 and xp_after_death < 100

        # type the next answer yourself -> reclaim
        app.action_toggle_editor()
        app._biggest_paste = 0
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
        app._biggest_paste = 0              # typed, not pasted
        app.query_one("#editor").text = "def f(): return 1"
        app.action_submit_code()
        assert any("def f()" in s for s in sent)
