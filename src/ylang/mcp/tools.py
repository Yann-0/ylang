"""MCP tool adapters — translate inputs/outputs only."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ylang.mcp.deps import YlangDeps
from ylang.mcp.tool_groups.analytics import register_analytics_tools
from ylang.mcp.tool_groups.core_improve import register_core_improve_tools
from ylang.mcp.tool_groups.library import register_library_tools
from ylang.mcp.tool_groups.memory_usage import register_memory_usage_tools


def register_tools(server: FastMCP, deps: YlangDeps) -> None:
    """Register all Ylang MCP tools on the server."""
    register_core_improve_tools(server, deps)
    register_library_tools(server, deps)
    register_memory_usage_tools(server, deps)
    register_analytics_tools(server, deps)
