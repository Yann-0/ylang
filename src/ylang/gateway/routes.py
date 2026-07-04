"""OpenAI-compatible HTTP routes — thin adapter over ``Engine``."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

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

logger = logging.getLogger(__name__)


def register_gateway_routes(server: FastMCP, engine: Engine) -> None:
    """Register OpenAI-compatible routes on the shared HTTP app."""

    @server.custom_route("/v1/chat/completions", methods=["POST"])
    async def chat_completions(request: Request) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return openai_error_response("Invalid JSON body")

        try:
            messages, request_model, stream = parse_chat_request(body)
        except GatewayRequestError as exc:
            return openai_error_response(
                exc.message,
                param=exc.param,
                code=exc.code,
            )

        route = resolve_gateway_model(request_model)

        # Opt-in improver pass (disabled: gateway traffic is real completions, not improve requests):
        # improved = improver.improve(...)

        if stream:
            return _stream_response(
                engine,
                messages=messages,
                route_activity=route.activity,
                explicit_model=route.explicit_model,
                request_model=route.request_model,
            )

        return _complete_response(
            engine,
            messages=messages,
            route_activity=route.activity,
            explicit_model=route.explicit_model,
            request_model=route.request_model,
        )

    @server.custom_route("/v1/models", methods=["GET"])
    async def list_models(_request: Request) -> Response:
        return JSONResponse(models_list_payload())


def _complete_response(
    engine: Engine,
    *,
    messages: list,
    route_activity: str,
    explicit_model: str | None,
    request_model: str,
) -> Response:
    try:
        result = engine.complete(
            messages,
            route_activity,
            model=explicit_model,
            improver_fired=False,
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
) -> tuple[Iterator[StreamChunk] | None, StreamCompletionError | None]:
    """Pull the first stream chunk so pre-stream failures become JSON errors."""
    generator = engine.complete_stream(
        messages,
        route_activity,
        model=explicit_model,
        improver_fired=False,
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


def _stream_response(
    engine: Engine,
    *,
    messages: list,
    route_activity: str,
    explicit_model: str | None,
    request_model: str,
) -> Response:
    completion_id = new_completion_id()
    chunks, stream_error = _start_stream(
        engine,
        messages=messages,
        route_activity=route_activity,
        explicit_model=explicit_model,
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
        try:
            for chunk in chunks:
                if chunk.content:
                    if not role_sent:
                        yield sse_chunk_payload(
                            completion_id=completion_id,
                            request_model=request_model,
                            delta={"role": "assistant"},
                        )
                        role_sent = True
                    yield sse_chunk_payload(
                        completion_id=completion_id,
                        request_model=request_model,
                        delta={"content": chunk.content},
                    )
            if role_sent:
                yield sse_chunk_payload(
                    completion_id=completion_id,
                    request_model=request_model,
                    delta={},
                    finish_reason="stop",
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
