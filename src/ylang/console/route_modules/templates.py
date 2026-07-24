"""Console routes: templates."""

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
from ylang.console.template_list import (
    filter_and_paginate_templates,
    parse_template_list_filters,
)
from ylang.console.template_params import (
    detect_placeholders,
    merge_detected_params,
    parse_params_from_form,
)
from ylang.console.pages import (
    render_templates_page,
)
from ylang.library.hygiene import (
    archive_template,
    eligible_unused_public_template_ids,
    eligible_zero_accept_template_ids,
    unarchive_template,
)
from ylang.library.store import save_learned_template
from ylang.library.types import TemplateParam
from ylang.usage.async_ops import run_store_sync
from ylang.usage.improver_analytics import (
    template_injection_counts,
)
from ylang.usage.store import UsageWindow


def register_templates_routes(ctx: ConsoleContext) -> None:
    """Register templates console routes."""
    @ctx.server.custom_route("/console/templates", methods=["GET"])
    async def console_templates(request: Request) -> Response:
        params = dict(request.query_params)
        list_filters = parse_template_list_filters(params)
        selected_id = params.get("id")
        message = params.get("msg")
        query = list_filters.query
        if query:
            templates = ctx.deps.library.search(query, limit=10_000)
        elif list_filters.visibility == "all":
            templates = ctx.deps.library.list(include_archived=True)
        elif list_filters.visibility is not None:
            templates = ctx.deps.library.list(visibility=list_filters.visibility)
        else:
            templates = ctx.deps.library.list()
        usage_counts = await run_store_sync(
            template_injection_counts,
            ctx.deps.store,
            UsageWindow.all_time(),
        )
        toxic_id_list = await run_store_sync(
            eligible_zero_accept_template_ids,
            ctx.deps.library,
            ctx.deps.store,
        )
        toxic_ids = frozenset(toxic_id_list)
        list_page = filter_and_paginate_templates(
            templates,
            filters=list_filters,
            usage_counts=usage_counts,
            toxic_ids=toxic_ids,
        )
        bulk_archive_eligible = len(
            eligible_unused_public_template_ids(ctx.deps.library, usage_counts)
        )
        toxic_archive_eligible = len(toxic_id_list)
        selected_body = None
        selected_name = None
        selected_source = None
        selected_params: list[TemplateParam] = []
        version_rows: list[tuple[int, str, str]] = []
        if selected_id:
            template = ctx.deps.library.recall(selected_id)
            if template is not None:
                selected_body = template.body
                selected_name = template.name
                selected_source = template.source
                selected_params = list(template.params)
                version_rows = ctx.deps.library.list_versions(selected_id)
        return ctx.render(
            lambda: render_templates_page(
                list_page,
                usage_counts=usage_counts,
                bulk_archive_eligible=bulk_archive_eligible,
                toxic_archive_eligible=toxic_archive_eligible,
                toxic_ids=toxic_ids,
                selected_id=selected_id,
                selected_body=selected_body,
                selected_name=selected_name,
                selected_source=selected_source,
                selected_params=selected_params,
                version_rows=version_rows,
                message=message,
            )
        )


    @ctx.server.custom_route("/console/templates/save", methods=["POST"])
    async def console_templates_save(request: Request) -> Response:
        form = await request.form()
        template_id = str(form.get("template_id", "")).strip()
        name = str(form.get("name", "")).strip()
        body = str(form.get("body", "")).strip()
        params = merge_detected_params(
            parse_params_from_form(form),
            detect_placeholders(body),
        )
        if not template_id or not name or not body:
            return RedirectResponse("/console/templates?msg=Missing+fields", status_code=303)
        existing = ctx.deps.library.recall(template_id)
        source = existing.source if existing else "user"
        if source == "learned":
            save_learned_template(
                ctx.deps.library,
                template_id,
                name=name,
                body=body,
                params=params,
            )
        else:
            ctx.deps.library.save(
                template_id,
                name=name,
                body=body,
                params=params,
                source=source if existing else "user",
            )
        return_query = str(form.get("return_query", "")).strip()
        suffix = f"&{return_query}" if return_query else ""
        return RedirectResponse(
            f"/console/templates?id={quote_plus(template_id)}&msg=Saved{suffix}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/templates/delete", methods=["POST"])
    async def console_templates_delete(request: Request) -> Response:
        form = await request.form()
        template_id = str(form.get("template_id", "")).strip()
        return_query = str(form.get("return_query", "")).strip()
        try:
            ctx.deps.library.delete(template_id)
            message = "Deleted"
        except ValueError as exc:
            message = str(exc)
        suffix = f"&{return_query}" if return_query else ""
        return RedirectResponse(
            f"/console/templates?msg={quote_plus(message)}{suffix}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/templates/archive", methods=["POST"])
    async def console_templates_archive(request: Request) -> Response:
        form = await request.form()
        template_id = str(form.get("template_id", "")).strip()
        return_query = str(form.get("return_query", "")).strip()
        if archive_template(ctx.deps.library, template_id):
            message = "Archived"
        else:
            message = "Could not archive template"
        suffix = f"&{return_query}" if return_query else ""
        return RedirectResponse(
            f"/console/templates?msg={quote_plus(message)}{suffix}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/templates/unarchive", methods=["POST"])
    async def console_templates_unarchive(request: Request) -> Response:
        form = await request.form()
        template_id = str(form.get("template_id", "")).strip()
        return_query = str(form.get("return_query", "")).strip()
        if unarchive_template(ctx.deps.library, template_id):
            message = "Unarchived"
        else:
            message = "Could not unarchive template"
        suffix = f"&{return_query}" if return_query else ""
        return RedirectResponse(
            f"/console/templates?msg={quote_plus(message)}{suffix}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/templates/archive-bulk", methods=["POST"])
    async def console_templates_archive_bulk(request: Request) -> Response:
        form = await request.form()
        return_query = str(form.get("return_query", "")).strip()
        usage_counts = await run_store_sync(
            template_injection_counts,
            ctx.deps.store,
            UsageWindow.all_time(),
        )
        eligible = eligible_unused_public_template_ids(ctx.deps.library, usage_counts)
        archived = sum(
            1 for template_id in eligible if archive_template(ctx.deps.library, template_id)
        )
        message = f"Archived {archived} unused public template(s)"
        suffix = f"&{return_query}" if return_query else ""
        return RedirectResponse(
            f"/console/templates?msg={quote_plus(message)}{suffix}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/templates/archive-toxic", methods=["POST"])
    async def console_templates_archive_toxic(request: Request) -> Response:
        form = await request.form()
        return_query = str(form.get("return_query", "")).strip()
        eligible = await run_store_sync(
            eligible_zero_accept_template_ids,
            ctx.deps.library,
            ctx.deps.store,
        )
        archived = sum(
            1 for template_id in eligible if archive_template(ctx.deps.library, template_id)
        )
        message = f"Quarantined {archived} toxic template(s)"
        suffix = f"&{return_query}" if return_query else ""
        return RedirectResponse(
            f"/console/templates?msg={quote_plus(message)}{suffix}",
            status_code=303,
        )

