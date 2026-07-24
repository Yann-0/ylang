"""Console routes: overview."""

from __future__ import annotations


from starlette.requests import Request
from starlette.responses import (
    Response,
)

from ylang import __version__
from ylang.console.context import (
    ConsoleContext,
)
from ylang.console.pages import (
    render_overview_page,
    render_usage_page,
)
from ylang.console.pages_full import (
    render_improver_page,
)
from ylang.usage.aggregates import daily_usage_buckets, rolling_cost, summarize_usage
from ylang.usage.async_ops import run_store_sync
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import (
    summarize_improver_quality,
    template_effectiveness,
)
from ylang.usage.optimizer import (
    generate_optimization_suggestions,
)
from ylang.usage.store import UsageWindow


def register_overview_routes(ctx: ConsoleContext) -> None:
    """Register overview console routes."""
    @ctx.server.custom_route("/console", methods=["GET"])
    async def console_overview(_request: Request) -> Response:
        eff = ctx.effective_settings()
        window = UsageWindow.last_days(7)
        feedback = FeedbackStore(ctx.deps.store._connection)
        report = await run_store_sync(
            summarize_improver_quality, ctx.deps.store, window, feedback
        )
        funnel = report.funnel
        suggestions = await run_store_sync(
            generate_optimization_suggestions,
            ctx.deps.store,
            window,
        )
        spent = await run_store_sync(rolling_cost, ctx.deps.store, UsageWindow.last_days(1))
        fact_count = len(ctx.deps.memory.recall(limit=10_000))
        return ctx.render(
            lambda: render_overview_page(
                health_ok=True,
                version=__version__,
                providers_configured=eff.provider_keys.configured_names(),
                providers_missing=eff.provider_keys.missing_names(),
                budget_spent=spent,
                budget_cap=eff.daily_budget_usd,
                funnel=funnel,
                suggestions=suggestions,
                narrative=None,
                narrative_available=funnel.total_fired >= 3,
                fact_count=fact_count,
                quality=report.quality,
            )
        )


    @ctx.server.custom_route("/console/usage", methods=["GET"])
    async def console_usage(_request: Request) -> Response:
        window = UsageWindow.last_days(7)
        summary = await run_store_sync(summarize_usage, ctx.engine.store, window)
        buckets = await run_store_sync(daily_usage_buckets, ctx.engine.store, window)
        feedback = FeedbackStore(ctx.engine.store._connection)
        report = await run_store_sync(
            summarize_improver_quality, ctx.engine.store, window, feedback
        )
        return ctx.render(
            lambda: render_usage_page(
                summary, daily_buckets=buckets, funnel=report.funnel
            )
        )


    @ctx.server.custom_route("/console/improver", methods=["GET"])
    async def console_improver(_request: Request) -> Response:
        window = UsageWindow.last_days(7)
        feedback = FeedbackStore(ctx.deps.store._connection)
        report = await run_store_sync(
            summarize_improver_quality, ctx.deps.store, window, feedback
        )
        templates = await run_store_sync(template_effectiveness, ctx.deps.store, window)
        return ctx.render(
            lambda: render_improver_page(
                report.funnel, templates, quality=report.quality
            )
        )

