"""Console routes: patterns."""

from __future__ import annotations

from urllib.parse import quote_plus

from starlette.requests import Request
from starlette.responses import (
    RedirectResponse,
    Response,
)

from ylang.console.context import (
    PATTERN_CACHE_KEY,
    ConsoleContext,
)
from ylang.console.pages import (
    render_patterns_page,
)
from ylang.console.route_helpers import (
    _deserialize_pattern_cache,
    _pattern_threshold,
    _serialize_pattern_cache,
)
from ylang.library.patterns import (
    TemplateProposal,
    detect_patterns,
    propose_template_from_pattern_outcome,
)
from ylang.library.store import save_learned_template


def register_patterns_routes(ctx: ConsoleContext) -> None:
    """Register patterns console routes."""
    @ctx.server.custom_route("/console/patterns", methods=["GET"])
    async def console_patterns(_request: Request) -> Response:
        cached = ctx.runtime_store.get(PATTERN_CACHE_KEY)
        patterns, proposals, skip_reasons = _deserialize_pattern_cache(cached)
        threshold = _pattern_threshold(ctx.runtime_store)
        alert_count = sum(
            1 for pattern in patterns if pattern.occurrence_count >= threshold
        )
        return ctx.render(
            lambda: render_patterns_page(
                patterns,
                proposals,
                skip_reasons=skip_reasons,
                alert_count=alert_count,
                threshold=threshold,
            )
        )


    @ctx.server.custom_route("/console/patterns/run", methods=["POST"])
    async def console_patterns_run(_request: Request) -> Response:
        patterns = detect_patterns(window_days=30)
        proposals: list[TemplateProposal | None] = []
        skip_reasons: list[str | None] = []
        for pattern in patterns:
            outcome = propose_template_from_pattern_outcome(pattern, engine=ctx.engine)
            proposals.append(outcome.proposal)
            skip_reasons.append(outcome.skip_reason)
        ctx.runtime_store.set(
            PATTERN_CACHE_KEY,
            _serialize_pattern_cache(patterns, proposals, skip_reasons),
        )
        return RedirectResponse("/console/patterns", status_code=303)


    @ctx.server.custom_route("/console/patterns/save", methods=["POST"])
    async def console_patterns_save(request: Request) -> Response:
        form = await request.form()
        try:
            save_learned_template(
                ctx.deps.library,
                str(form.get("template_id", "")),
                name=str(form.get("name", "")),
                body=str(form.get("body", "")),
                params=[],
            )
        except ValueError as exc:
            return RedirectResponse(
                f"/console/patterns?msg={quote_plus(str(exc))}",
                status_code=303,
            )
        return RedirectResponse("/console/templates", status_code=303)

