"""Headless TUI tests using Textual's run_test + a stub responder.

use_worker=False makes the responder run synchronously, so the tests are
deterministic (no threads).
"""

from eklavya.tui import EklavyaApp


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        return f"reply to: {text[:24]}"


def _stats():
    return {"xp": 0, "streak": 1, "level": 1}


async def test_kickoff_and_chat():
    rec = Recorder()
    app = EklavyaApp(responder=rec, stats_fn=_stats, kickoff="KICK", use_worker=False)
    async with app.run_test() as pilot:
        # Kickoff was delivered on mount (as a hidden turn).
        assert rec.calls and rec.calls[0] == "KICK"
        assert ("agent", "reply to: KICK") in app.history

        # The learner types a message and submits.
        app.query_one("#msg").focus()
        app.query_one("#msg").value = "hello there"
        await pilot.press("enter")
        assert "hello there" in rec.calls
        assert ("user", "hello there") in app.history


async def test_code_editor_submit_sends_fenced_code():
    rec = Recorder()
    app = EklavyaApp(responder=rec, stats_fn=_stats, use_worker=False)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+e")  # open the editor
        editor = app.query_one("#editor")
        assert editor.has_class("on")

        editor.text = "def f():\n    return 1"
        app.action_submit_code()

        assert any("```python" in c and "def f()" in c for c in rec.calls)
        assert not editor.has_class("on")  # editor closes after submitting
