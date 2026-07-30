"""Headless TUI tests using Textual's run_test + a stub responder.

use_worker=False makes the responder run synchronously, so the tests are
deterministic (no threads).
"""

from langgraph.types import Command

from eklavya.tui import ApprovalScreen, EklavyaApp, make_stream_responder


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


async def test_streaming_accumulates_then_finalizes():
    def stream_fn(_text):
        yield from ["Hel", "lo ", "wor", "ld"]

    app = EklavyaApp(responder=lambda t: "unused", stream_fn=stream_fn, use_worker=False)
    async with app.run_test() as pilot:
        app.query_one("#msg").focus()
        app.query_one("#msg").value = "hi"
        await pilot.press("enter")
        # Streamed tokens were assembled into one final reply, and the live pane closed.
        assert ("agent", "Hello world") in app.history
        assert not app.query_one("#streaming").has_class("live")


class _FakeAgentWithBash:
    """Streams tokens, then pauses on a run_bash interrupt on the first turn.

    A resume Command clears the interrupt so the loop terminates. Records the
    resume decisions it received so tests can assert the approve/reject wiring."""

    def __init__(self):
        self._pending = True
        self.resumed = []

    def stream(self, inputs, config=None, stream_mode=None):
        if isinstance(inputs, Command):
            self._pending = False  # resume clears the interrupt
            self.resumed.append(inputs.resume)
            return iter([])
        return iter([(_Chunk("running your code…"), {})])

    def get_state(self, config):
        if self._pending:
            interrupt = _Interrupt({"action_requests": [
                {"name": "run_bash", "args": {"command": "python sol.py",
                                              "explanation": "runs your solution"}}]})
            return _State((interrupt,))
        return _State(())


class _Chunk:
    def __init__(self, text):
        self.content = text


class _Interrupt:
    def __init__(self, value):
        self.value = value


class _State:
    def __init__(self, interrupts):
        self.interrupts = interrupts


def test_stream_responder_approve_resumes_with_approve():
    agent = _FakeAgentWithBash()
    approvals = []

    def approve(command, explanation):
        approvals.append((command, explanation))
        return True

    stream = make_stream_responder(agent, {}, approve=approve)
    out = "".join(stream("go"))

    assert approvals == [("python sol.py", "runs your solution")]
    assert agent.resumed == [{"decisions": [{"type": "approve"}]}]
    assert "rejected" not in out


def test_stream_responder_reject_resumes_with_reject():
    agent = _FakeAgentWithBash()
    stream = make_stream_responder(agent, {}, approve=lambda c, e: False)
    out = "".join(stream("go"))

    assert agent.resumed == [{"decisions": [{"type": "reject"}]}]
    assert "rejected" in out


def test_stream_responder_no_approve_callback_rejects():
    agent = _FakeAgentWithBash()
    stream = make_stream_responder(agent, {})  # no approve callback → safe default
    list(stream("go"))
    assert agent.resumed == [{"decisions": [{"type": "reject"}]}]


async def test_approval_modal_approve_and_reject():
    """The ApprovalScreen dismisses True on Approve and False on Reject/Esc."""
    app = EklavyaApp(responder=lambda t: "x", use_worker=False)
    async with app.run_test() as pilot:
        results = []
        app.push_screen(ApprovalScreen("ls -la", "lists files"), results.append)
        await pilot.pause()
        await pilot.click("#approve-yes")
        await pilot.pause()
        assert results == [True]

        app.push_screen(ApprovalScreen("rm x", "removes"), results.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert results == [True, False]


async def test_esc_cancels_in_flight_response():
    """Esc cancels an in-flight response: closes the stream pane, re-enables input."""
    app = EklavyaApp(responder=lambda t: "x", stats_fn=_stats, use_worker=False)
    async with app.run_test() as pilot:
        # Simulate an in-flight streaming turn.
        app._in_flight = True
        app.query_one("#streaming").add_class("live")
        app.query_one("#msg").disabled = True

        await pilot.press("escape")

        assert app._in_flight is False
        assert not app.query_one("#streaming").has_class("live")
        assert app.query_one("#msg").disabled is False


async def test_esc_noop_when_idle():
    """Esc does nothing when no response is in flight (doesn't clobber the UI)."""
    app = EklavyaApp(responder=lambda t: "x", stats_fn=_stats, use_worker=False)
    async with app.run_test() as pilot:
        assert app._in_flight is False
        # Input is enabled when idle; Esc must leave it that way.
        await pilot.press("escape")
        assert app._in_flight is False
        assert app.query_one("#msg").disabled is False


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
