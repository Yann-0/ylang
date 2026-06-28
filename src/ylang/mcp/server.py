"""MCP server entry — thin adapter over core."""

from __future__ import annotations

import sys

import anyio
from mcp.server.fastmcp import FastMCP

from ylang.core import Engine
from ylang.core.memory import open_memory
from ylang.improver import Improver
from ylang.library import open_library
from ylang.mcp.auth import BearerTokenMiddleware
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


def create_server(deps: YlangDeps, settings: Settings | None = None) -> FastMCP:
    """Create and configure the MCP server instance."""
    if settings is not None and settings.transport == "http":
        server = FastMCP(
            "ylang",
            host=settings.host,
            port=settings.port,
            streamable_http_path="/mcp",
        )
    else:
        server = FastMCP("ylang")
    register_tools(server, deps)
    return server


def _print_connection_details(settings: Settings) -> None:
    storage = settings.resolved_storage_path()
    print("Ylang MCP server", file=sys.stderr)
    print("  name: ylang", file=sys.stderr)
    if settings.transport == "stdio":
        print("  transport: stdio", file=sys.stderr)
        print("  command: python -m ylang", file=sys.stderr)
        print("  ready - waiting for MCP client on stdin/stdout", file=sys.stderr)
    else:
        print("  transport: http (streamable-http)", file=sys.stderr)
        print(f"  listen: {settings.host}:{settings.port}/mcp", file=sys.stderr)
        print("  auth: Bearer token required", file=sys.stderr)
        print("  ready - waiting for MCP client", file=sys.stderr)
    print(f"  storage: {storage}", file=sys.stderr)
    print(f"  tools ({len(_TOOL_NAMES)}): {', '.join(_TOOL_NAMES)}", file=sys.stderr)


async def _run_http_async(server: FastMCP, settings: Settings) -> None:
    import uvicorn

    base_app = server.streamable_http_app()
    app = BearerTokenMiddleware(base_app, settings.auth_token or "")
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level=server.settings.log_level.lower(),
    )
    await uvicorn.Server(config).serve()


def _run_http(server: FastMCP, settings: Settings) -> None:
    anyio.run(lambda: _run_http_async(server, settings))


def run_server() -> None:
    """Wire dependencies and run the MCP server."""
    settings = Settings.load()
    path = settings.resolved_storage_path()
    store = open_store(path)
    library = open_library(path)
    memory = open_memory(path)
    engine = Engine(store, surface="mcp")
    improver = Improver(engine)
    deps = YlangDeps(improver=improver, library=library, store=store, memory=memory)
    server = create_server(deps, settings)
    _print_connection_details(settings)
    try:
        if settings.transport == "stdio":
            server.run(transport="stdio")
        else:
            if settings.auth_token is None:
                print(
                    "error: YLANG_AUTH_TOKEN is required when YLANG_TRANSPORT=http",
                    file=sys.stderr,
                )
                sys.exit(1)
            _run_http(server, settings)
    finally:
        library.close()
        store.close()
        memory.close()
