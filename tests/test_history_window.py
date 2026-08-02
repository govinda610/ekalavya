"""History budgeting: the model's replayed transcript is windowed to a bounded size.

The checkpointer replays the whole growing thread every turn; without a window a long
session re-sends an ever-larger history (cost/latency/context-window risk). The
history-window middleware trims the messages the MODEL sees to the most recent N, always
keeping the system prompt and never orphaning a tool message.
"""

import os
import tempfile

os.environ["EKLAVYA_HOME"] = tempfile.mkdtemp(prefix="eklavya-hist-")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402

from eklavya import agent as ag  # noqa: E402


class _Req:
    def __init__(self, messages):
        self.messages = messages

    def override(self, messages):
        return _Req(messages)


def _run(messages):
    mw = ag._build_history_window_middleware()
    captured = {}

    def handler(req):
        captured["messages"] = req.messages
        return "ok"

    assert mw.wrap_model_call(_Req(messages), handler) == "ok"
    return captured["messages"]


def test_long_history_is_windowed_and_keeps_system():
    msgs = [SystemMessage("sys")]
    for i in range(60):
        msgs.append(HumanMessage(f"q{i}"))
        msgs.append(AIMessage(f"a{i}"))
    out = _run(msgs)
    assert len(out) <= ag._HISTORY_MAX_MESSAGES
    assert isinstance(out[0], SystemMessage)  # system prompt is never dropped
    assert out[-1].content == "a59"           # most recent turn is retained


def test_short_history_is_untouched():
    msgs = [SystemMessage("sys"), HumanMessage("q0"), AIMessage("a0")]
    out = _run(msgs)
    assert [m.content for m in out] == ["sys", "q0", "a0"]
