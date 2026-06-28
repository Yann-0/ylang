"""MCP server entry — thin adapter over core."""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from ylang.improver import Improver
from ylang.library import open_library
from ylang.mcp.deps import YlangDeps
from ylang.mcp.tools import register_tools
from ylang.settings import Settings
from ylang.usage.store import open_store

_TOOL_NAMES = (
    "improve_prompt",
    "save_template",
    "recall_template",
    "list_templates",
    "remember",
    "recall_usage",
)


def create_server(deps: YlangDeps) -> FastMCP:
    """Create and configure the MCP server instance."""
    server = FastMCP("ylang")
    register_tools(server, deps)
    return server


def _print_connection_details(settings: Settings) -> None:
    storage = settings.resolved_storage_path()
    print("Ylang MCP server", file=sys.stderr)
    print("  name: ylang", file=sys.stderr)
    print("  transport: stdio", file=sys.stderr)
    print("  command: python -m ylang", file=sys.stderr)
    print(f"  storage: {storage}", file=sys.stderr)
    print(f"  tools ({len(_TOOL_NAMES)}): {', '.join(_TOOL_NAMES)}", file=sys.stderr)
    print("  ready - waiting for MCP client on stdin/stdout", file=sys.stderr)


def run_server() -> None:
    """Wire dependencies and run the MCP server over stdio."""
    settings = Settings.load()
    path = settings.resolved_storage_path()
    store = open_store(path)
    library = open_library(path)
    improver = Improver(store, surface="mcp")
    deps = YlangDeps(improver=improver, library=library, store=store)
    _print_connection_details(settings)
    try:
        create_server(deps).run(transport="stdio")
    finally:
        library.close()
        store.close()
