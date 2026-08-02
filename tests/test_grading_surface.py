"""The tamper-proof grading contract.

The model must NOT be able to stamp a rating/attempt directly: `record_attempt` (which
takes a model-supplied `correct` boolean) is an INTERNAL function only the graders call,
so it is deliberately absent from every agent-facing toolset. The graded wrappers
(grade_and_record / grade_and_record_subject / grade_rubric) are the only write path.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-grade-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

from eklavya import tools  # noqa: E402


def _tool_names(toolset):
    names = set()
    for t in toolset:
        names.add(getattr(t, "name", None) or getattr(t, "__name__", None))
    return names


def test_record_attempt_not_agent_facing():
    names = _tool_names(tools.AGENT_TOOLS)
    assert "record_attempt" not in names
    # It stays importable as an internal function the graders call.
    assert callable(tools.record_attempt)


def test_agent_facing_write_path_is_only_graders():
    names = _tool_names(tools.AGENT_TOOLS)
    assert {"grade_and_record", "grade_and_record_subject", "grade_rubric"} <= names


def test_shared_mode_toolsets_also_exclude_record_attempt():
    for toolset in (tools.ONBOARDING_TOOLS, tools.SESSION_TOOLS, tools.AIINTERVIEW_TOOLS):
        assert "record_attempt" not in _tool_names(toolset)
