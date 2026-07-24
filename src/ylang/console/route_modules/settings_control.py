"""Console routes: settings control."""

from __future__ import annotations


from starlette.requests import Request
from starlette.responses import (
    Response,
)

from ylang.console.context import (
    BOOL_FORM_KEYS,
    ConsoleContext,
)
from ylang.console.control_data import (
    gather_effective_config,
    gather_store_inventory,
    gather_zero_accept_templates,
)
from ylang.console.proposals import (
    collect_control_proposals,
    collect_pending_proposals,
)
from ylang.console.pages import (
    render_control_page,
    render_settings_page,
)
from ylang.console.route_helpers import (
    _preferred_template_candidates,
)
from ylang.core.runtime_settings import (
    HOT_RELOADABLE_KEYS,
    effective_feature_flags,
    restart_required_snapshot,
)
from ylang.usage.aggregates import rolling_cost, summarize_usage
from ylang.usage.async_ops import run_store_sync
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import (
    summarize_improver_quality,
    template_effectiveness,
)
from ylang.usage.store import UsageWindow


def register_settings_control_routes(ctx: ConsoleContext) -> None:
    """Register settings_control console routes."""
    @ctx.server.custom_route("/console/settings", methods=["GET", "POST"])
    async def console_settings(request: Request) -> Response:
        saved = False
        if request.method == "POST":
            form = await request.form()
            reset_key = str(form.get("reset_key", "")).strip()
            if reset_key and reset_key in HOT_RELOADABLE_KEYS:
                ctx.runtime_store.delete(reset_key)
                saved = True
            else:
                for key in HOT_RELOADABLE_KEYS:
                    if key in BOOL_FORM_KEYS:
                        continue
                    if key in form and str(form[key]).strip():
                        ctx.runtime_store.set(key, str(form[key]).strip())
                for key in BOOL_FORM_KEYS:
                    ctx.runtime_store.set(key, "true" if key in form else "false")
                saved = True
        rows = ctx.runtime_store.list_all()
        flags = effective_feature_flags(ctx.runtime_store.as_dict())
        window = UsageWindow.last_days(7)
        proposals = await run_store_sync(
            collect_pending_proposals,
            ctx.deps.store,
            ctx.deps.store._connection,
            window,
        )
        preferred_candidates = _preferred_template_candidates(ctx.deps.library)
        return ctx.render(
            lambda: render_settings_page(
                runtime_rows=rows,
                restart_snapshot=restart_required_snapshot(ctx.settings),
                flags=flags,
                base_settings=ctx.settings,
                saved=saved,
                proposals=proposals,
                preferred_candidates=preferred_candidates,
            )
        )


    @ctx.server.custom_route("/console/control", methods=["GET"])
    async def console_control(request: Request) -> Response:
        eff = ctx.effective_settings()
        window = UsageWindow.last_days(7)
        message = request.query_params.get("msg")
        config = gather_effective_config(ctx.settings, ctx.runtime_store)
        inventory = gather_store_inventory(
            ctx.deps.library,
            ctx.deps.memory,
            ctx.deps.store._connection,
        )
        spent = await run_store_sync(rolling_cost, ctx.deps.store, UsageWindow.last_days(1))
        feedback = FeedbackStore(ctx.deps.store._connection)
        report = await run_store_sync(
            summarize_improver_quality, ctx.deps.store, window, feedback
        )
        funnel = report.funnel
        usage_summary = await run_store_sync(summarize_usage, ctx.engine.store, window)
        optimizer = await run_store_sync(
            collect_pending_proposals,
            ctx.deps.store,
            ctx.deps.store._connection,
            window,
        )
        control = await run_store_sync(
            collect_control_proposals,
            ctx.deps.store,
            ctx.deps.library,
            ctx.deps.store._connection,
            window,
        )
        template_stats = await run_store_sync(
            template_effectiveness, ctx.deps.store, window
        )
        zero_accept = gather_zero_accept_templates(template_stats)
        return ctx.render(
            lambda: render_control_page(
                config=config,
                inventory=inventory,
                budget_spent=spent,
                budget_cap=eff.daily_budget_usd,
                funnel=funnel,
                usage_summary=usage_summary,
                quality=report.quality,
                control_proposals=control,
                optimizer_proposals=optimizer,
                zero_accept_templates=zero_accept,
                message=message,
            )
        )

