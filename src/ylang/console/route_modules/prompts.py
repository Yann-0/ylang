"""Console routes: prompt sources and candidates."""

from __future__ import annotations

from urllib.parse import quote_plus

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from ylang.console.context import ConsoleContext
from ylang.console.page_modules.prompts import (
    render_candidates_page,
    render_sources_page,
)
from ylang.importer.evaluate import evaluate_candidate
from ylang.importer.policy import SourcePolicyError
from ylang.importer.promote import (
    PromotionError,
    candidate_diff_text,
    promote_candidate,
    reject_candidate,
    review_candidate,
)
from ylang.importer.refresh import open_source_store, refresh_source
from ylang.importer.source_store import PromptSourceStore
from ylang.importer.source_types import REVIEW_QUEUE_STATES
from ylang.usage.experiments import ExperimentStore


def register_prompt_intelligence_routes(ctx: ConsoleContext) -> None:
    """Register sources/candidates console routes."""

    def _store() -> PromptSourceStore:
        return open_source_store(ctx.deps.library)

    @ctx.server.custom_route("/console/sources", methods=["GET"])
    async def console_sources(request: Request) -> Response:
        message = request.query_params.get("msg")
        sources = _store().list_sources()
        return ctx.render(lambda: render_sources_page(sources, message=message))

    @ctx.server.custom_route("/console/sources/enable", methods=["POST"])
    async def console_sources_enable(request: Request) -> Response:
        form = await request.form()
        source_id = str(form.get("source_id", ""))
        try:
            _store().set_enabled(source_id, True)
            msg = f"enabled {source_id}"
        except SourcePolicyError as exc:
            msg = str(exc)
        return RedirectResponse(
            f"/console/sources?msg={quote_plus(msg)}",
            status_code=303,
        )

    @ctx.server.custom_route("/console/sources/disable", methods=["POST"])
    async def console_sources_disable(request: Request) -> Response:
        form = await request.form()
        source_id = str(form.get("source_id", ""))
        _store().set_enabled(source_id, False)
        return RedirectResponse(
            f"/console/sources?msg={quote_plus('disabled ' + source_id)}",
            status_code=303,
        )

    @ctx.server.custom_route("/console/sources/refresh", methods=["POST"])
    async def console_sources_refresh(request: Request) -> Response:
        form = await request.form()
        source_id = str(form.get("source_id", ""))
        summary = refresh_source(_store(), ctx.deps.library, source_id)
        msg = f"{source_id} {summary.status} new={summary.new} changed={summary.changed}"
        if summary.error:
            msg = f"{source_id} {summary.status}: {summary.error}"
        return RedirectResponse(
            f"/console/sources?msg={quote_plus(msg)}",
            status_code=303,
        )

    @ctx.server.custom_route("/console/candidates", methods=["GET"])
    async def console_candidates(request: Request) -> Response:
        store = _store()
        item_id = request.query_params.get("id")
        message = request.query_params.get("msg")
        items = store.list_items(states=tuple(REVIEW_QUEUE_STATES))
        selected = store.get_item(item_id) if item_id else None
        diff = (
            candidate_diff_text(selected, ctx.deps.library)
            if selected is not None
            else None
        )
        return ctx.render(
            lambda: render_candidates_page(
                items, selected=selected, diff_text=diff, message=message
            )
        )

    @ctx.server.custom_route("/console/candidates/review", methods=["POST"])
    async def console_candidates_review(request: Request) -> Response:
        form = await request.form()
        item_id = str(form.get("item_id", ""))
        try:
            review_candidate(_store(), item_id)
            msg = "reviewed"
        except PromotionError as exc:
            msg = str(exc)
        return RedirectResponse(
            f"/console/candidates?id={quote_plus(item_id)}&msg={quote_plus(msg)}",
            status_code=303,
        )

    @ctx.server.custom_route("/console/candidates/reject", methods=["POST"])
    async def console_candidates_reject(request: Request) -> Response:
        form = await request.form()
        item_id = str(form.get("item_id", ""))
        try:
            reject_candidate(_store(), item_id)
            msg = "rejected"
        except PromotionError as exc:
            msg = str(exc)
        return RedirectResponse(
            f"/console/candidates?id={quote_plus(item_id)}&msg={quote_plus(msg)}",
            status_code=303,
        )

    @ctx.server.custom_route("/console/candidates/promote", methods=["POST"])
    async def console_candidates_promote(request: Request) -> Response:
        form = await request.form()
        item_id = str(form.get("item_id", ""))
        acknowledge = str(form.get("acknowledge_risk", "")) in {"1", "on", "true"}
        try:
            template = promote_candidate(
                _store(),
                ctx.deps.library,
                item_id,
                acknowledge_risk=acknowledge,
                usage_store=ctx.deps.store,
            )
            msg = f"promoted {template.template_id} v{template.version}"
        except PromotionError as exc:
            msg = str(exc)
        return RedirectResponse(
            f"/console/candidates?id={quote_plus(item_id)}&msg={quote_plus(msg)}",
            status_code=303,
        )

    @ctx.server.custom_route("/console/candidates/evaluate", methods=["POST"])
    async def console_candidates_evaluate(request: Request) -> Response:
        form = await request.form()
        item_id = str(form.get("item_id", ""))
        store = _store()
        item = store.get_item(item_id)
        if item is None:
            return RedirectResponse(
                f"/console/candidates?msg={quote_plus('unknown candidate')}",
                status_code=303,
            )
        report = evaluate_candidate(
            item,
            ctx.deps.library,
            ExperimentStore(ctx.deps.store._connection),
            ctx.deps.store,
            source_store=store,
        )
        parts = [
            f"inspect {report.experiment_id} (observational; zero provider calls; no auto-traffic)"
        ]
        if report.current_template_id:
            parts.append(f"vs {report.current_template_id}")
        if report.current_accept_rate is not None:
            parts.append(f"accept={report.current_accept_rate:.0%}")
        if report.current_avg_cost is not None:
            parts.append(f"cost=${report.current_avg_cost:.4f}")
        if report.body_diff_ratio is not None:
            parts.append(f"diff={report.body_diff_ratio:.0%}")
        msg = " ".join(parts)
        return RedirectResponse(
            f"/console/candidates?id={quote_plus(item_id)}&msg={quote_plus(msg)}",
            status_code=303,
        )
