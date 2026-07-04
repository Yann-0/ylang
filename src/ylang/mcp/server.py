"""MCP server entry — thin adapter over core."""

from __future__ import annotations

import sys

import anyio
from mcp.server.fastmcp import FastMCP

from ylang.core import Engine
from ylang.core.stores import open_stores
from ylang.improver import Improver
from ylang.library.pattern_detector import UsagePatternDetector
from ylang.library.patterns import register_pattern_detector
from ylang.gateway import VIRTUAL_MODEL_NAMES, register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.mcp.deps import YlangDeps
from ylang.mcp.tools import register_tools
from ylang.settings import Settings
from ylang.usage.budget import warn_budget_threshold

_TOOL_NAMES = (
    "improve_prompt",
    "save_template",
    "recall_template",
    "list_templates",
    "import_public_prompts",
    "remember",
    "recall_facts",
    "recall_usage",
    "usage_summary",
    "detect_patterns",
    "save_learned_template",
)


def create_server(
    deps: YlangDeps,
    settings: Settings | None = None,
    *,
    gateway_engine: Engine | None = None,
) -> FastMCP:
    """Create and configure the MCP server instance.

    When ``settings.transport`` is ``http``, binds host/port and registers MCP on
    ``/mcp``. Pass ``gateway_engine`` to also mount OpenAI gateway routes and
    ``GET /usage`` on the same app (stdio transport ignores ``gateway_engine``).
    """
    if settings is not None and settings.transport == "http":
        server = FastMCP(
            "ylang",
            host=settings.host,
            port=settings.port,
            streamable_http_path="/mcp",
        )
        if gateway_engine is not None:
            register_gateway_routes(server, gateway_engine)
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
        print("  gateway: enabled", file=sys.stderr)
        print("  gateway routes: POST /v1/chat/completions, GET /v1/models, GET /usage", file=sys.stderr)
        print(
            f"  virtual models: {', '.join(VIRTUAL_MODEL_NAMES)}",
            file=sys.stderr,
        )
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
    stores = open_stores(path)
    register_pattern_detector(UsagePatternDetector(stores.store))
    engine = Engine.from_settings(stores.store, surface="mcp", settings=settings)
    gateway_engine = (
        Engine.from_settings(stores.store, surface="gateway", settings=settings)
        if settings.transport == "http"
        else None
    )
    improver = Improver(engine)
    deps = YlangDeps(
        improver=improver,
        library=stores.library,
        store=stores.store,
        memory=stores.memory,
        surface="mcp",
    )
    server = create_server(deps, settings, gateway_engine=gateway_engine)
    _print_connection_details(settings)
    warn_budget_threshold(settings, stores.store)
    settings.log_llm_config(router=engine.router)
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
            try:
                _run_http(server, settings)
            except OSError as exc:
                if exc.errno in (98, 10048):
                    print(
                        f"error: port {settings.port} already in use.\n"
                        "  If ylang runs as a systemd service (production default):\n"
                        "    sudo systemctl restart ylang\n"
                        "  Do not start a second instance with python -m ylang while the service runs.\n"
                        "  Manual stop (only if not using systemd, as the ylang user):\n"
                        f"    fuser -k {settings.port}/tcp",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                raise
    finally:
        stores.close()
