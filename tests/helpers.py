"""Test helpers for MCP integration tests."""

from __future__ import annotations

from typing import Any


async def call_mcp_tool(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Return structured tool output from FastMCP (second tuple element)."""
    _content, structured = await server.call_tool(name, arguments)
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    return structured
