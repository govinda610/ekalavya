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
    """The MCP servers to connect to. Only Context7 (accurate, current library docs;
    works without a key). Web search is handled by the local `web_search` tool
    (Tavily → Serper) which is in AGENT_TOOLS on every interface — so we deliberately
    do NOT also load the Tavily MCP server, which would just duplicate the web tool."""
    context7 = {"transport": "streamable_http", "url": "https://mcp.context7.com/mcp"}
    context7_key = os.environ.get("CONTEXT7_API_KEY")
    if context7_key:
        context7["headers"] = {"CONTEXT7_API_KEY": context7_key}
    return {"context7": context7}


async def _fetch() -> list:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    servers = _servers()
    if not servers:
        return []
    return await MultiServerMCPClient(servers).get_tools()


def _sync_wrap(async_tool):
    """MCP tools are async-only (`StructuredTool does not support sync invocation`).
    Wrap each so it also runs under our sync-invoked agent: the agent executes in a
    threadpool/worker with no running event loop, so `asyncio.run` here is safe."""
    import asyncio

    from langchain_core.tools import StructuredTool

    def _run(**kwargs):
        return asyncio.run(async_tool.ainvoke(kwargs))

    return StructuredTool.from_function(
        func=_run,
        name=async_tool.name,
        description=async_tool.description,
        args_schema=async_tool.args_schema,
    )


def load_mcp_tools() -> list:
    """Fetch the MCP tools once and cache them, wrapped to be sync-callable. Call from
    a sync startup context (e.g. the `serve` command). Never raises — returns [] on
    failure. Warms the cache that `cached_mcp_tools()` then serves everywhere."""
    global _cached
    if _cached is None:
        import asyncio

        try:
            _cached = [_sync_wrap(t) for t in asyncio.run(_fetch())]
        except Exception:
            _cached = []
    return _cached


def cached_mcp_tools() -> list:
    """Return already-loaded MCP tools without fetching — safe in any context (async
    request handlers, tests). Empty until `load_mcp_tools()` warms it at startup, so
    tests (which never warm it) stay fully offline."""
    return _cached or []
