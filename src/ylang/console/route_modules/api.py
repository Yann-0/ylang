"""Console routes: api."""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    Response,
)

from ylang.console.context import (
    ConsoleContext,
)
from ylang.console.template_improver import improve_template_with_ai
from ylang.console.fact_suggester import suggest_facts_from_usage
from ylang.improver.context import build_improve_context
from ylang.library.types import TemplateParam
from ylang.usage.async_ops import run_store_sync
from ylang.usage.optimizer import (
    generate_llm_optimization_narrative,
)
from ylang.usage.store import UsageWindow


def register_api_routes(ctx: ConsoleContext) -> None:
    """Register api console routes."""
    @ctx.server.custom_route("/console/api/improve-template", methods=["POST"])
    async def console_api_improve_template(request: Request) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        name = str(body.get("name", "")).strip()
        text = str(body.get("body", "")).strip()
        instruction = str(body.get("instruction", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "body required"}, status_code=400)
        raw_params = body.get("params", [])
        params: list[TemplateParam] = []
        if isinstance(raw_params, list):
            for item in raw_params:
                if not isinstance(item, dict):
                    continue
                param_name = str(item.get("name", "")).strip()
                if not param_name:
                    continue
                default = item.get("default")
                params.append(
                    TemplateParam(
                        name=param_name,
                        description=str(item.get("description", "")),
                        default=str(default) if default is not None else None,
                    )
                )
        result = await run_store_sync(
            lambda: improve_template_with_ai(
                name=name,
                body=text,
                params=params,
                engine=ctx.engine,
                instruction=instruction,
            )
        )
        return JSONResponse(result)


    @ctx.server.custom_route("/console/api/render-template", methods=["POST"])
    async def console_api_render_template(request: Request) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        template_body = str(body.get("body", "")).strip()
        if not template_body:
            return JSONResponse({"ok": False, "error": "body required"}, status_code=400)
        param_values_raw = body.get("param_values", {})
        if not isinstance(param_values_raw, dict):
            return JSONResponse({"ok": False, "error": "param_values must be object"}, status_code=400)
        param_values = {str(key): str(value) for key, value in param_values_raw.items()}
        try:
            rendered = template_body.format(**param_values)
        except KeyError as exc:
            return JSONResponse(
                {"ok": False, "error": f"missing param: {exc.args[0]}"},
                status_code=400,
            )
        return JSONResponse({"ok": True, "rendered": rendered})


    @ctx.server.custom_route("/console/api/narrative", methods=["POST"])
    async def console_api_narrative(_request: Request) -> Response:
        window = UsageWindow.last_days(7)
        narrative = await run_store_sync(
            generate_llm_optimization_narrative,
            ctx.deps.store,
            window,
            ctx.engine,
        )
        if narrative is None:
            return JSONResponse(
                {"ok": False, "error": "Not enough improver data or LLM unavailable."},
                status_code=503,
            )
        return JSONResponse({"ok": True, "narrative": narrative})


    @ctx.server.custom_route("/console/api/suggest-facts", methods=["POST"])
    async def console_api_suggest_facts(_request: Request) -> Response:
        window = UsageWindow.last_days(7)
        result = await run_store_sync(
            suggest_facts_from_usage,
            ctx.deps.store,
            ctx.engine,
            window=window,
        )
        if not result.get("ok"):
            return JSONResponse(result, status_code=503)
        return JSONResponse(result)


    @ctx.server.custom_route("/console/api/improve-preview", methods=["POST"])
    async def console_improve_preview(request: Request) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        text = str(body.get("text", "")).strip()
        mode = str(body.get("mode", "agent"))
        tool = str(body.get("tool", f"cursor-{mode}"))
        model = str(body.get("model", "auto"))
        if not text:
            return JSONResponse(
                {"ok": False, "error": "text required"}, status_code=400
            )
        context = build_improve_context(
            text,
            tool,
            None,
            ctx.deps.library,
            ctx.deps.memory,
            mode=mode,
            store=ctx.deps.store,
        )
        result = ctx.deps.improver.improve(
            text,
            tool,
            model=model,
            context=context,
            mode=mode,
        )
        return JSONResponse(
            {
                "ok": True,
                "original": result.original,
                "improved": result.improved,
                "validated": result.validated,
                "changed": result.improved.strip() != result.original.strip(),
                "auto_apply_default": result.auto_apply_default,
                "cursor_mode": result.cursor_mode,
                "rejection_reason": result.rejection_reason,
            }
        )
