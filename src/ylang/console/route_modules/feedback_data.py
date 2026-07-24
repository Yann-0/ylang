"""Console routes: feedback data."""

from __future__ import annotations

from urllib.parse import quote_plus

from starlette.requests import Request
from starlette.responses import (
    RedirectResponse,
    Response,
)

from ylang.console.context import (
    ConsoleContext,
)
from ylang.console.data_mutators import (
    clear_improver_caches,
    delete_usage_row,
    purge_usage_older_than,
)
from ylang.console.data_queries import db_stats, list_browse_tables, preview_table
from ylang.console.pages_full import (
    render_data_page,
    render_feedback_page,
)
from ylang.core.runtime_settings import (
    effective_feature_flags,
)
from ylang.usage.feedback import FeedbackStore


def register_feedback_data_routes(ctx: ConsoleContext) -> None:
    """Register feedback_data console routes."""
    @ctx.server.custom_route("/console/feedback", methods=["GET"])
    async def console_feedback(_request: Request) -> Response:
        feedback = FeedbackStore(ctx.deps.store._connection)
        events = feedback.recent(limit=100)
        flags = effective_feature_flags(ctx.runtime_store.as_dict())
        return ctx.render(
            lambda: render_feedback_page(
                events,
                edit_feedback_enabled=bool(flags.get("edit_feedback")),
            )
        )


    @ctx.server.custom_route("/console/data", methods=["GET"])
    async def console_data(request: Request) -> Response:
        table_name = request.query_params.get("table", "usage")
        if table_name not in list_browse_tables():
            table_name = "usage"
        offset = int(request.query_params.get("offset", "0") or "0")
        activity = request.query_params.get("activity")
        search = request.query_params.get("q")
        message = request.query_params.get("msg")
        stats = db_stats(ctx.deps.store._connection)
        preview = preview_table(
            ctx.deps.store._connection,
            table_name,
            limit=50,
            offset=offset,
            activity=activity,
            search=search,
        )
        return ctx.render(
            lambda: render_data_page(
                stats=stats,
                preview=preview,
                table_name=table_name,
                offset=offset,
                activity_filter=activity,
                search_query=search,
                message=message,
            )
        )


    @ctx.server.custom_route("/console/data/clear-cache", methods=["POST"])
    async def console_data_clear_cache(_request: Request) -> Response:
        form = await _request.form()
        if str(form.get("confirm", "")).strip() != "CLEAR":
            return RedirectResponse(
                "/console/data?table=improver_cache&msg=Confirmation+required",
                status_code=303,
            )
        _mem, db_rows = clear_improver_caches(ctx.deps.store._connection)
        return RedirectResponse(
            f"/console/data?table=improver_cache&msg={quote_plus(f'Cleared improver cache ({db_rows} DB rows)')}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/data/delete-usage", methods=["POST"])
    async def console_data_delete_usage(request: Request) -> Response:
        form = await request.form()
        row_id_raw = str(form.get("row_id", "")).strip()
        table = str(form.get("table", "usage")).strip()
        offset = str(form.get("offset", "0")).strip()
        if not row_id_raw.isdigit():
            return RedirectResponse(
                f"/console/data?table={quote_plus(table)}&msg=Invalid+row+id",
                status_code=303,
            )
        removed = delete_usage_row(ctx.deps.store._connection, int(row_id_raw))
        msg = "Deleted usage row" if removed else "Row not found"
        return RedirectResponse(
            f"/console/data?table={quote_plus(table)}&offset={quote_plus(offset)}&msg={quote_plus(msg)}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/data/purge-usage", methods=["POST"])
    async def console_data_purge_usage(request: Request) -> Response:
        form = await request.form()
        days_raw = str(form.get("days", "90")).strip()
        try:
            days = int(days_raw)
        except ValueError:
            return RedirectResponse(
                "/console/data?table=usage&msg=Invalid+days",
                status_code=303,
            )
        try:
            count = purge_usage_older_than(ctx.deps.store._connection, days)
        except ValueError as exc:
            return RedirectResponse(
                f"/console/data?table=usage&msg={quote_plus(str(exc))}",
                status_code=303,
            )
        return RedirectResponse(
            f"/console/data?table=usage&msg={quote_plus(f'Purged {count} usage row(s) older than {days} days')}",
            status_code=303,
        )

