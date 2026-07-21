"""MCP client — pulls in web search (Tavily) and library docs (Context7) as agent
tools, reusing the official `langchain-mcp-adapters`. Both are hosted HTTP MCP
servers, so there's nothing to install locally.

`load_mcp_tools()` fetches the tools once (sync wrapper, meant to be called at
startup) and caches them. It fails open: if a server is unreachable or unconfigured,
it returns whatever loaded (or an empty list) rather than breaking the agent.
"""

from __future__ import annotations

import os

_cached: list | None = None


def _servers() -> dict:
    """The MCP servers to connect to, built from env. Context7 works without a key
    (lower rate limit); Tavily needs TAVILY_API_KEY."""
    servers: dict = {}

    tavily_key = os.environ.get("TAVILY_API_KEY") or os.environ.get("EKLAVYA_TAVILY_API_KEY")
    if tavily_key:
        servers["tavily"] = {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={tavily_key}",
        }

    context7 = {"transport": "streamable_http", "url": "https://mcp.context7.com/mcp"}
    context7_key = os.environ.get("CONTEXT7_API_KEY")
    if context7_key:
        context7["headers"] = {"CONTEXT7_API_KEY": context7_key}
    servers["context7"] = context7

    return servers


async def _fetch() -> list:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    servers = _servers()
    if not servers:
        return []
    return await MultiServerMCPClient(servers).get_tools()


def load_mcp_tools() -> list:
    """Fetch the MCP tools once and cache them. Call from a sync startup context
    (not from inside a running event loop). Never raises — returns [] on failure."""
    global _cached
    if _cached is None:
        import asyncio

        try:
            _cached = asyncio.run(_fetch())
        except Exception:
            _cached = []
    return _cached
