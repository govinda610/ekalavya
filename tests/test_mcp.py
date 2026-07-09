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
    assert {
        "get_progress", "suggest_focus", "list_goals",
        "run_code", "grade_code", "record_attempt",
    } <= names


async def test_run_code_tool_works_through_server():
    server = build_server()
    # call_tool returns provider-specific content; just assert it ran our sandbox.
    result = await server.call_tool("run_code", {"code": "print(6 * 7)"})
    assert "42" in str(result)
