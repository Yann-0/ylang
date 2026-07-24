"""Console routes: experiments."""

from __future__ import annotations


from starlette.requests import Request
from starlette.responses import (
    RedirectResponse,
    Response,
)

from ylang.console.context import (
    ConsoleContext,
)
from ylang.console.pages import (
    render_experiments_page,
)
from ylang.core.runtime_settings import (
    effective_feature_flags,
)
from ylang.usage.async_ops import run_store_sync
from ylang.usage.experiment_results import summarize_experiment_outcomes
from ylang.usage.experiments import ExperimentStore
from ylang.usage.store import UsageWindow


def register_experiments_routes(ctx: ConsoleContext) -> None:
    """Register experiments console routes."""
    @ctx.server.custom_route("/console/experiments", methods=["GET", "POST"])
    async def console_experiments(request: Request) -> Response:
        store = ExperimentStore(ctx.deps.store._connection)
        if request.method == "POST":
            form = await request.form()
            store.upsert_variant(
                experiment_id=str(form.get("experiment_id", "")),
                variant_id=str(form.get("variant_id", "")),
                config_hash=str(form.get("config_hash", "control")),
                traffic_pct=float(form.get("traffic_pct", 50)),
            )
            return RedirectResponse("/console/experiments", status_code=303)
        variants = store.list_all()
        window = UsageWindow.last_days(7)
        outcomes = await run_store_sync(summarize_experiment_outcomes, ctx.deps.store, window)
        flags = effective_feature_flags(ctx.runtime_store.as_dict())
        return ctx.render(
            lambda: render_experiments_page(
                variants,
                outcomes,
                experiments_enabled=bool(flags.get("experiments")),
            )
        )


    @ctx.server.custom_route("/console/experiments/toggle", methods=["POST"])
    async def console_experiments_toggle(request: Request) -> Response:
        form = await request.form()
        store = ExperimentStore(ctx.deps.store._connection)
        store.set_active(
            experiment_id=str(form.get("experiment_id", "")),
            variant_id=str(form.get("variant_id", "")),
            active=str(form.get("active", "")) == "activate",
        )
        return RedirectResponse("/console/experiments", status_code=303)

