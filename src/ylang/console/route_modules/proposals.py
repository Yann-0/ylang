"""Console routes: proposals."""

from __future__ import annotations

from urllib.parse import quote_plus

from starlette.requests import Request
from starlette.responses import (
    RedirectResponse,
    Response,
)

from ylang.console.apply_audit import ApplyAuditStore
from ylang.console.context import (
    ConsoleContext,
)
from ylang.console.proposals import (
    apply_proposal,
    collect_pending_proposals,
    proposal_redirect_after_apply,
)
from ylang.console.pages import (
    render_proposals_page,
)
from ylang.usage.async_ops import run_store_sync
from ylang.usage.store import UsageWindow


def register_proposals_routes(ctx: ConsoleContext) -> None:
    """Register proposals console routes."""
    @ctx.server.custom_route("/console/proposals", methods=["GET"])
    async def console_proposals(request: Request) -> Response:
        message = request.query_params.get("msg")
        window = UsageWindow.last_days(7)
        proposals = await run_store_sync(
            collect_pending_proposals,
            ctx.deps.store,
            ctx.deps.store._connection,
            window,
        )
        audit = ApplyAuditStore(ctx.deps.store._connection)
        audit_rows = audit.recent(limit=20)
        return ctx.render(
            lambda: render_proposals_page(
                proposals=proposals,
                audit_entries=audit_rows,
                message=message,
            )
        )


    @ctx.server.custom_route("/console/proposals/apply", methods=["POST"])
    async def console_proposals_apply(request: Request) -> Response:
        form = await request.form()
        proposal_id = str(form.get("proposal_id", "")).strip()
        if not proposal_id:
            return RedirectResponse(
                "/console/proposals?msg=No+proposal+selected",
                status_code=303,
            )
        window = UsageWindow.last_days(7)
        audit = ApplyAuditStore(ctx.deps.store._connection)

        def _apply() -> str:
            return apply_proposal(
                proposal_id,
                store=ctx.deps.store,
                library=ctx.deps.library,
                connection=ctx.deps.store._connection,
                runtime_store=ctx.runtime_store,
                audit_store=audit,
                window=window,
                actor="console",
            )

        try:
            detail = await run_store_sync(_apply)
        except ValueError as exc:
            return RedirectResponse(
                f"/console/proposals?msg={quote_plus(str(exc))}",
                status_code=303,
            )
        return_to = str(form.get("return_to", "")).strip()
        redirect = proposal_redirect_after_apply(proposal_id)
        if redirect:
            return RedirectResponse(
                f"{redirect}&msg={quote_plus('Applied: ' + detail)}",
                status_code=303,
            )
        if return_to.startswith("/console"):
            return RedirectResponse(
                f"{return_to}?msg={quote_plus('Applied: ' + detail)}",
                status_code=303,
            )
        return RedirectResponse(
            f"/console/proposals?msg=Applied:+{quote_plus(detail)}",
            status_code=303,
        )

