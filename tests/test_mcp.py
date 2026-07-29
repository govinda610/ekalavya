"""MCP server tests — the tools are registered and callable through the server."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-mcp-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

from eklavya.mcp_server import build_server  # noqa: E402


async def test_server_exposes_expected_tools():
    server = build_server()
    names = {t.name for t in await server.list_tools()}
    # aligned with the app's spine: tamper-proof grading + web search, not the old
    # run_code/grade_code (dropped as redundant with grade_and_record).
    assert {
        "get_progress", "suggest_focus", "list_goals",
        "grade_and_record", "record_attempt", "web_search",
    } <= names
    assert "run_code" not in names and "grade_code" not in names


async def test_grade_and_record_tool_works_through_server():
    server = build_server()
    # call_tool returns provider-specific content; assert the tamper-proof grader ran
    # in the sandbox and marked a correct solution as passing.
    result = await server.call_tool("grade_and_record", {
        "pillar": "Python Fundamentals", "axis": "syntax_recall", "concept": "sum a list",
        "code": "def s(xs): return sum(xs)",
        "tests": "assert s([1,2,3]) == 6",
        "confidence": 3, "reference": "def s(xs): return sum(xs)",
    })
    assert "PASS" in str(result)
