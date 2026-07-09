"""Expose Ekalavya's deterministic spine as an MCP server.

This realises "any agent can drive Ekalavya": a coding agent (Claude Code, Cursor,
…) becomes the teaching brain, while Ekalavya provides the real state — spaced
repetition, ratings, sandbox grading, streaks. The other agent runs the session
by calling these tools.

Note: over stdio, stdout IS the protocol wire, so nothing here prints to it.
"""

from __future__ import annotations


def build_server():
    """Build the FastMCP server with Ekalavya's tools registered."""
    from mcp.server.fastmcp import FastMCP

    from . import progress, report, tools
    from .db import init_db

    init_db()
    server = FastMCP("Ekalavya")

    @server.tool()
    def get_progress() -> dict:
        """Return the learner's streak, level, XP, and mastery grid."""
        return {"stats": progress.stats(), "mastery": report.grid()}

    @server.tool()
    def suggest_focus(minutes: int = 30) -> str:
        """Suggest what to practise now — weakest (pillar, axis) cells + due reviews."""
        return tools.suggest_focus(minutes)

    @server.tool()
    def list_goals() -> str:
        """List the learner's active goals."""
        return tools.list_goals()

    @server.tool()
    def run_code(code: str) -> str:
        """Run the learner's Python in a sandbox; return output + timing."""
        return tools.run_code(code)

    @server.tool()
    def grade_code(code: str, tests: str) -> str:
        """Grade learner code against assert-based hidden tests. Returns pass/fail + output."""
        return tools.grade_code(code, tests)

    @server.tool()
    def record_attempt(pillar: str, axis: str, concept: str, confidence: int,
                       correct: bool, seconds: float = 0.0, ai_off: bool = True) -> str:
        """Record one graded attempt: updates the rating, schedules the spaced-repetition
        review, logs it, and awards XP. axis is one of syntax_recall, debugging,
        code_reading, api_memory, decomposition."""
        return tools.record_attempt(pillar, axis, concept, confidence, correct, seconds, ai_off)

    return server


def run() -> None:
    """Run the server over stdio (the default transport)."""
    build_server().run()
