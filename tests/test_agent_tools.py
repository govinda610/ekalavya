"""The builtin deepagents `execute` shell tool must NOT be exposed to the model.

We route all shell work through our approval-gated `run_bash` tool, so `execute`
is excluded at the source via a harness profile (see agent._exclude_execute_tool).
These tests assert the exclusion is wired, without needing a live provider.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-test-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from eklavya import agent as ag  # noqa: E402


def test_execute_excluded_from_model_toolset():
    """After building an agent, a `_ToolExclusionMiddleware` excluding `execute`
    is present, so the model never sees the `execute` tool in its request."""
    from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

    ag.build_agent("test prompt", [], checkpointer=InMemorySaver())

    import gc

    excluded_sets = [
        obj._excluded
        for obj in gc.get_objects()
        if isinstance(obj, _ToolExclusionMiddleware)
    ]
    assert excluded_sets, "no _ToolExclusionMiddleware was installed"
    assert all("execute" in s for s in excluded_sets)


def test_execute_filtered_by_middleware():
    """The exclusion middleware drops `execute` from a model request's tools."""
    from types import SimpleNamespace

    from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

    ag._exclude_execute_tool()

    mw = _ToolExclusionMiddleware(excluded=frozenset({"execute"}))

    class _Req:
        def __init__(self, tools):
            self.tools = tools

        def override(self, tools):
            return _Req(tools)

    tools = [SimpleNamespace(name=n) for n in ("run_bash", "execute", "read_file")]
    captured = {}

    def handler(req):
        captured["names"] = [t.name for t in req.tools]
        return "ok"

    result = mw.wrap_model_call(_Req(tools), handler)
    assert result == "ok"
    assert "execute" not in captured["names"]
    assert "run_bash" in captured["names"]
