"""OpenAI-compatible HTTP routes — thin adapter over ``Engine``."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from ylang.core.engine import Engine
from ylang.core.types import StreamChunk, StreamCompletionError
from ylang.gateway.mapping import resolve_gateway_model
from ylang.gateway.openai import (
    GatewayRequestError,
    chat_completion_payload,
    models_list_payload,
    new_completion_id,
    openai_error_response,
    parse_chat_request,
    sse_chunk_payload,
    sse_done,
)
from ylang.usage.aggregates import daily_usage_buckets, summarize_usage
from ylang.usage.async_ops import run_store_sync
from ylang.usage.dashboard import render_usage_dashboard_html
from ylang.usage.store import UsageWindow

logger = logging.getLogger(__name__)


def register_health_route(server: FastMCP) -> None:
    """Register unauthenticated ``GET /health`` (exempt in bearer middleware)."""

    @server.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> Response:
        from ylang import __version__

        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "service": "ylang",
            }
        )


def register_gateway_routes(server: FastMCP, engine: Engine) -> None:
    """Register OpenAI-compatible routes on the shared HTTP app."""
    register_health_route(server)

    @server.custom_route("/v1/chat/completions", methods=["POST"])
    async def chat_completions(request: Request) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return openai_error_response("Invalid JSON body")

        try:
            messages, request_model, stream, tools, tool_choice = parse_chat_request(body)
        except GatewayRequestError as exc:
            return openai_error_response(
                exc.message,
                param=exc.param,
                code=exc.code,
            )

        route = resolve_gateway_model(request_model)

        if stream:
            return await _stream_response(
                engine,
                messages=messages,
                route_activity=route.activity,
                explicit_model=route.explicit_model,
                request_model=route.request_model,
                tools=tools,
                tool_choice=tool_choice,
            )

        return await _complete_response(
            engine,
            messages=messages,
            route_activity=route.activity,
            explicit_model=route.explicit_model,
            request_model=route.request_model,
            tools=tools,
            tool_choice=tool_choice,
        )

    @server.custom_route("/v1/models", methods=["GET"])
    async def list_models(_request: Request) -> Response:
        return JSONResponse(models_list_payload())

    @server.custom_route("/usage", methods=["GET"])
    async def usage_dashboard(_request: Request) -> Response:
        """Chart.js dashboard for the last 7 days; auto-refreshes every 30 seconds."""
        window = UsageWindow.last_days(7)
        summary = await run_store_sync(summarize_usage, engine.store, window)
        buckets = await run_store_sync(daily_usage_buckets, engine.store, window)
        html = render_usage_dashboard_html(
            summary,
            title="Ylang Usage Dashboard",
            daily_buckets=buckets,
            live=True,
        )
        return HTMLResponse(html)


async def _complete_response(
    engine: Engine,
    *,
    messages: list,
    route_activity: str,
    explicit_model: str | None,
    request_model: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> Response:
    try:
        result = await run_store_sync(
            engine.complete,
            messages,
            route_activity,
            model=explicit_model,
            improver_fired=False,
            tools=tools,
            tool_choice=tool_choice,
        )
    except Exception as exc:
        logger.exception("Gateway completion failed")
        return openai_error_response(
            str(exc),
            status_code=500,
            error_type="server_error",
        )

    if not result.success:
        return openai_error_response(
            result.error or "Model unavailable",
            status_code=404,
            error_type="invalid_request_error",
            param="model",
            code="model_not_found",
        )

    completion_id = new_completion_id()
    return JSONResponse(
        chat_completion_payload(
            result,
            completion_id=completion_id,
            request_model=request_model,
        )
    )


def _start_stream(
    engine: Engine,
    *,
    messages: list,
    route_activity: str,
    explicit_model: str | None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> tuple[Iterator[StreamChunk] | None, StreamCompletionError | None]:
    """Pull the first stream chunk so pre-stream failures become JSON errors."""
    generator = engine.complete_stream(
        messages,
        route_activity,
        model=explicit_model,
        improver_fired=False,
        tools=tools,
        tool_choice=tool_choice,
    )
    iterator = iter(generator)
    try:
        first = next(iterator)
    except StopIteration:
        return iter(()), None
    except StreamCompletionError as exc:
        return None, exc

    def remaining() -> Iterator[StreamChunk]:
        yield first
        yield from iterator

    return remaining(), None


async def _stream_response(
    engine: Engine,
    *,
    messages: list,
    route_activity: str,
    explicit_model: str | None,
    request_model: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> Response:
    completion_id = new_completion_id()
    chunks, stream_error = await run_store_sync(
        _start_stream,
        engine,
        messages=messages,
        route_activity=route_activity,
        explicit_model=explicit_model,
        tools=tools,
        tool_choice=tool_choice,
    )
    if stream_error is not None:
        return openai_error_response(
            stream_error.message,
            status_code=404,
            error_type="invalid_request_error",
            param="model",
            code="model_not_found",
        )

    def event_stream() -> Iterator[str]:
        role_sent = False
        content_sent = False
        tool_calls_sent = False
        finish_reason = "stop"
        try:
            for chunk in chunks:
                if chunk.usage is not None:
                    yield sse_chunk_payload(
                        completion_id=completion_id,
                        request_model=request_model,
                        delta={},
                        usage=chunk.usage,
                    )
                    continue
                if chunk.tool_calls_delta:
                    if not role_sent:
                        yield sse_chunk_payload(
                            completion_id=completion_id,
                            request_model=request_model,
                            delta={"role": "assistant"},
                        )
                        role_sent = True
                    tool_calls_sent = True
                    yield sse_chunk_payload(
                        completion_id=completion_id,
                        request_model=request_model,
                        delta={"tool_calls": chunk.tool_calls_delta},
                    )
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                    continue
                if chunk.content:
                    if not role_sent:
                        yield sse_chunk_payload(
                            completion_id=completion_id,
                            request_model=request_model,
                            delta={"role": "assistant"},
                        )
                        role_sent = True
                    content_sent = True
                    yield sse_chunk_payload(
                        completion_id=completion_id,
                        request_model=request_model,
                        delta={"content": chunk.content},
                    )
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
            if tool_calls_sent:
                finish_reason = "tool_calls"
            if role_sent or content_sent or tool_calls_sent:
                yield sse_chunk_payload(
                    completion_id=completion_id,
                    request_model=request_model,
                    delta={},
                    finish_reason=finish_reason,
                )
            else:
                yield sse_chunk_payload(
                    completion_id=completion_id,
                    request_model=request_model,
                    delta={"role": "assistant", "content": ""},
                )
                yield sse_chunk_payload(
                    completion_id=completion_id,
                    request_model=request_model,
                    delta={},
                    finish_reason="stop",
                )
            yield sse_done()
        except StreamCompletionError as exc:
            logger.warning("Gateway stream ended after partial output: %s", exc.message)
            yield sse_chunk_payload(
                completion_id=completion_id,
                request_model=request_model,
                delta={},
                finish_reason="stop",
            )
            yield sse_done()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
