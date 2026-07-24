"""HTTP routes for the Ylang admin console."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ylang.console.context import ConsoleContext
from ylang.console.route_modules.api import register_api_routes
from ylang.console.route_modules.experiments import register_experiments_routes
from ylang.console.route_modules.facts import register_facts_routes
from ylang.console.route_modules.feedback_data import register_feedback_data_routes
from ylang.console.route_modules.ops_misc import register_ops_misc_routes
from ylang.console.route_modules.overview import register_overview_routes
from ylang.console.route_modules.patterns import register_patterns_routes
from ylang.console.route_modules.proposals import register_proposals_routes
from ylang.console.route_modules.settings_control import register_settings_control_routes
from ylang.console.route_modules.static_auth import register_static_auth_routes
from ylang.console.route_modules.templates import register_templates_routes
from ylang.core.engine import Engine
from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.mcp.deps import YlangDeps
from ylang.settings import Settings


def register_console_routes(
    server: FastMCP,
    deps: YlangDeps,
    settings: Settings,
    *,
    gateway_engine: Engine | None = None,
) -> None:
    """Register admin console routes on the HTTP app."""
    engine = gateway_engine or Engine.from_settings(
        deps.store, surface="console", settings=settings
    )
    runtime_store = RuntimeSettingsStore(deps.store._connection)
    ctx = ConsoleContext(
        server=server,
        deps=deps,
        settings=settings,
        engine=engine,
        runtime_store=runtime_store,
    )
    register_static_auth_routes(ctx)
    register_overview_routes(ctx)
    register_settings_control_routes(ctx)
    register_templates_routes(ctx)
    register_facts_routes(ctx)
    register_patterns_routes(ctx)
    register_experiments_routes(ctx)
    register_proposals_routes(ctx)
    register_feedback_data_routes(ctx)
    register_ops_misc_routes(ctx)
    register_api_routes(ctx)
