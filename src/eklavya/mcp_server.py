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
    def grade_and_record(pillar: str, axis: str, concept: str, code: str, tests: str,
                         confidence: int, reference: str, seconds: float = 0.0) -> str:
        """Tamper-proof grading of a code drill: validates YOUR `tests` against YOUR
        `reference` solution first, then runs the learner's `code` in the sandbox and
        records the real verdict (rating + spaced-repetition + XP) in one step — the
        outcome can't be faked. Use for every code drill. axis: syntax_recall |
        debugging | code_reading | api_memory | decomposition."""
        return tools.grade_and_record(pillar, axis, concept, code, tests, confidence, reference, seconds)

    @server.tool()
    def record_attempt(pillar: str, axis: str, concept: str, confidence: int,
                       correct: bool, seconds: float = 0.0, ai_off: bool = True) -> str:
        """Record one NON-code graded attempt (conceptual / self-assessed): updates the
        rating, schedules the spaced-repetition review, logs it, and awards XP. axis is one
        of syntax_recall, debugging, code_reading, api_memory, decomposition."""
        return tools.record_attempt(pillar, axis, concept, confidence, correct, seconds, ai_off)

    @server.tool()
    def review_ai_usage() -> str:
        """AI-enabled interview only: read the in-interview AI-assistant usage log for THIS
        interview, INCLUDING any bug the assistant deliberately planted (the candidate never
        saw it flagged). Each planted bug shows an `assist_id=` — pass it to record_bug_verdict."""
        return tools.review_ai_usage()

    @server.tool()
    def record_bug_verdict(assist_id: int, verdict: str, note: str = "") -> str:
        """AI-enabled interview only: record structurally whether the candidate CAUGHT /
        MISSED / PARTIALLY caught a specific planted bug. `assist_id` comes from
        review_ai_usage(); `verdict` is one of caught | missed | partial."""
        return tools.record_bug_verdict(assist_id, verdict, note)

    @server.tool()
    def web_search(query: str) -> str:
        """Search the live web (Tavily → Serper) for real, current interview questions,
        references, or to research a target role's requirements."""
        return tools.web_search(query)

    return server


def run() -> None:
    """Run the server over stdio (the default transport)."""
    build_server().run()
