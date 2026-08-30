"""Operator hub console routes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from ylang.console.context import ConsoleContext
from ylang.console.page_modules.hubs import (
    render_privacy_page,
    render_quality_page,
    render_routing_page,
    render_today_page,
)
from ylang.usage.async_ops import run_store_sync
from ylang.usage.improver_analytics import summarize_improver, template_effectiveness
from ylang.usage.operator_metrics import (
    routing_metrics,
    sensitive_trace_count,
    today_metrics,
)
from ylang.usage.purge import DEFAULT_TRACE_RETENTION_DAYS
from ylang.usage.store import UsageWindow


def register_hub_routes(ctx: ConsoleContext) -> None:
    """Register TODAY / QUALITY / ROUTING / PRIVACY operator hubs."""

    @ctx.server.custom_route("/console/today", methods=["GET"])
    async def console_today(_request: Request) -> Response:
        eff = ctx.effective_settings()
        window = UsageWindow.last_hours(24)
        metrics = await run_store_sync(today_metrics, ctx.deps.store, window)
        return ctx.render(
            lambda: render_today_page(
                metrics=metrics,
                budget_cap=eff.daily_budget_usd,
            )
        )

    @ctx.server.custom_route("/console/quality", methods=["GET"])
    async def console_quality(_request: Request) -> Response:
        window = UsageWindow.last_days(7)
        funnel = await run_store_sync(summarize_improver, ctx.deps.store, window)
        effectiveness = await run_store_sync(
            template_effectiveness, ctx.deps.store, window
        )
        weak = [row for row in effectiveness if row.accept_rate < 0.5]
        return ctx.render(
            lambda: render_quality_page(funnel=funnel, effectiveness=weak)
        )

    @ctx.server.custom_route("/console/routing", methods=["GET"])
    async def console_routing(_request: Request) -> Response:
        window = UsageWindow.last_days(7)
        metrics = await run_store_sync(routing_metrics, ctx.deps.store, window)
        return ctx.render(lambda: render_routing_page(metrics=metrics))

    @ctx.server.custom_route("/console/privacy", methods=["GET"])
    async def console_privacy(_request: Request) -> Response:
        eff = ctx.effective_settings()
        window = UsageWindow.last_days(30)
        count = await run_store_sync(sensitive_trace_count, ctx.deps.store, window)
        return ctx.render(
            lambda: render_privacy_page(
                capture_level=eff.capture_level,
                retention_days=DEFAULT_TRACE_RETENTION_DAYS,
                sensitive_count=count,
            )
        )
