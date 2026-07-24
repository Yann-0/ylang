"""Console routes: facts."""

from __future__ import annotations

import json
from urllib.parse import quote_plus

from starlette.requests import Request
from starlette.responses import (
    RedirectResponse,
    Response,
)

from ylang.console.context import (
    ConsoleContext,
)
from ylang.console.fact_list import (
    SAMPLE_FACTS,
    filter_and_paginate_facts,
    parse_fact_list_filters,
)
from ylang.console.pages import (
    render_facts_page,
)


def register_facts_routes(ctx: ConsoleContext) -> None:
    """Register facts console routes."""
    @ctx.server.custom_route("/console/facts", methods=["GET", "POST"])
    async def console_facts(request: Request) -> Response:
        if request.method == "POST":
            form = await request.form()
            fact = str(form.get("fact", "")).strip()
            scope = str(form.get("scope", "private")).strip()
            workspace = str(form.get("workspace", "")).strip()
            return_query = str(form.get("return_query", "")).strip()
            suffix = f"&{return_query}" if return_query else ""
            if not fact:
                return RedirectResponse(
                    f"/console/facts?msg={quote_plus('Fact text is required')}{suffix}",
                    status_code=303,
                )
            try:
                created = ctx.deps.memory.remember(fact, scope, workspace=workspace)
            except ValueError as exc:
                return RedirectResponse(
                    f"/console/facts?msg={quote_plus(str(exc))}{suffix}",
                    status_code=303,
                )
            return RedirectResponse(
                f"/console/facts?id={created.id}&msg={quote_plus('Fact saved.')}{suffix}",
                status_code=303,
            )

        params = dict(request.query_params)
        list_filters = parse_fact_list_filters(params)
        message = params.get("msg")
        selected_id_raw = params.get("id", "").strip()
        auto_suggest = params.get("suggest", "").strip() in {"1", "true", "yes"}
        selected_id: int | None = None
        if selected_id_raw.isdigit():
            selected_id = int(selected_id_raw)
        all_facts = ctx.deps.memory.recall(limit=10_000)
        list_page = filter_and_paginate_facts(all_facts, filters=list_filters)
        selected = None
        if selected_id is not None:
            selected = next(
                (item for item in all_facts if item.id == selected_id),
                None,
            )
        return ctx.render(
            lambda: render_facts_page(
                list_page,
                selected=selected,
                message=message,
                auto_suggest=auto_suggest,
            )
        )


    @ctx.server.custom_route("/console/facts/seed-samples", methods=["POST"])
    async def console_facts_seed_samples(_request: Request) -> Response:
        existing = ctx.deps.memory.recall(limit=1)
        if existing:
            return RedirectResponse(
                f"/console/facts?msg={quote_plus('Facts already exist — samples not added.')}",
                status_code=303,
            )
        for fact_text, scope, workspace in SAMPLE_FACTS:
            ctx.deps.memory.remember(fact_text, scope, workspace=workspace)
        return RedirectResponse(
            f"/console/facts?msg={quote_plus(f'Added {len(SAMPLE_FACTS)} sample facts.')}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/facts/accept-suggestions", methods=["POST"])
    async def console_facts_accept_suggestions(request: Request) -> Response:
        form = await request.form()
        selected = form.getlist("selected")
        saved = 0
        errors: list[str] = []
        for raw in selected:
            text = str(raw).strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                errors.append("invalid suggestion payload")
                continue
            if not isinstance(payload, dict):
                errors.append("invalid suggestion payload")
                continue
            fact = str(payload.get("fact", "")).strip()
            scope = str(payload.get("scope", "private")).strip() or "private"
            workspace = str(payload.get("workspace", "")).strip()
            if not fact:
                continue
            try:
                ctx.deps.memory.remember(fact, scope, workspace=workspace)
                saved += 1
            except ValueError as exc:
                errors.append(str(exc))
        if saved:
            message = f"Saved {saved} fact{'s' if saved != 1 else ''}."
            if errors:
                message += f" ({len(errors)} skipped)"
            return RedirectResponse(
                f"/console/facts?msg={quote_plus(message)}",
                status_code=303,
            )
        err = errors[0] if errors else "Select at least one suggestion to save."
        return RedirectResponse(
            f"/console/facts?suggest=1&msg={quote_plus(err)}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/facts/update", methods=["POST"])
    async def console_facts_update(request: Request) -> Response:
        form = await request.form()
        fact_id = int(form.get("fact_id", 0))
        return_query = str(form.get("return_query", "")).strip()
        suffix = f"&{return_query}" if return_query else ""
        try:
            updated = ctx.deps.memory.update(
                fact_id,
                fact=str(form.get("fact", "")),
                scope=str(form.get("scope", "private")),
                workspace=str(form.get("workspace", "")),
            )
        except ValueError as exc:
            return RedirectResponse(
                f"/console/facts?id={fact_id}&msg={quote_plus(str(exc))}{suffix}",
                status_code=303,
            )
        if updated:
            return RedirectResponse(
                f"/console/facts?id={fact_id}&msg={quote_plus('Fact updated.')}{suffix}",
                status_code=303,
            )
        return RedirectResponse(
            f"/console/facts?msg={quote_plus('Fact not found.')}{suffix}",
            status_code=303,
        )


    @ctx.server.custom_route("/console/facts/delete", methods=["POST"])
    async def console_facts_delete(request: Request) -> Response:
        form = await request.form()
        fact_id = int(form.get("fact_id", 0))
        return_query = str(form.get("return_query", "")).strip()
        suffix = f"&{return_query}" if return_query else ""
        removed = ctx.deps.memory.forget(fact_id)
        message = "Fact deleted." if removed else "Fact not found."
        return RedirectResponse(
            f"/console/facts?msg={quote_plus(message)}{suffix}",
            status_code=303,
        )

