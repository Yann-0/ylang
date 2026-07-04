"""OpenAI-compatible request parsing and response shaping for the gateway face."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from starlette.responses import JSONResponse

from ylang.core.types import CompletionResult, Message


class GatewayRequestError(Exception):
    """Invalid OpenAI-style chat completion request."""

    def __init__(
        self,
        message: str,
        *,
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.param = param
        self.code = code


def new_completion_id() -> str:
    """Return a unique OpenAI-style chat completion id."""
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def parse_chat_request(body: Any) -> tuple[list[Message], str, bool, list[dict[str, Any]] | None, Any]:
    """Parse POST /v1/chat/completions JSON into messages, model, stream, tools, tool_choice."""
    if not isinstance(body, dict):
        msg = "Request body must be a JSON object"
        raise GatewayRequestError(msg)

    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        msg = "model is required"
        raise GatewayRequestError(msg, param="model", code="model_not_found")

    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        msg = "messages is required"
        raise GatewayRequestError(msg, param="messages")

    messages: list[Message] = []
    for index, raw in enumerate(raw_messages):
        if not isinstance(raw, dict):
            msg = f"messages[{index}] must be an object"
            raise GatewayRequestError(msg, param="messages")
        role = raw.get("role")
        if role not in ("system", "user", "assistant"):
            msg = f"messages[{index}].role must be system, user, or assistant"
            raise GatewayRequestError(msg, param="messages")
        content = _message_content(raw.get("content"))
        if content is None:
            msg = f"messages[{index}].content must be a string"
            raise GatewayRequestError(msg, param="messages")
        messages.append({"role": role, "content": content})

    stream = bool(body.get("stream", False))
    tools = body.get("tools")
    if tools is not None and not isinstance(tools, list):
        msg = "tools must be an array"
        raise GatewayRequestError(msg, param="tools")
    tool_choice = body.get("tool_choice")
    return messages, model.strip(), stream, tools, tool_choice


def _message_content(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else ""
    return None


def openai_error_response(
    message: str,
    *,
    status_code: int = 400,
    error_type: str = "invalid_request_error",
    param: str | None = None,
    code: str | None = None,
) -> JSONResponse:
    """Build an OpenAI-format error JSON response."""
    error: dict[str, Any] = {
        "message": message,
        "type": error_type,
    }
    if param is not None:
        error["param"] = param
    if code is not None:
        error["code"] = code
    return JSONResponse({"error": error}, status_code=status_code)


def models_list_payload() -> dict[str, Any]:
    """Return the virtual model catalog for GET /v1/models."""
    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": created,
                "owned_by": "ylang",
            }
            for model_id in (
                "route-code",
                "route-search",
                "route-reason",
                "route-other",
            )
        ],
    }


def chat_completion_payload(
    result: CompletionResult,
    *,
    completion_id: str,
    request_model: str,
) -> dict[str, Any]:
    """Shape a non-streaming Engine result as OpenAI chat.completion JSON."""
    message: dict[str, Any] = {
        "role": "assistant",
        "content": result.content,
    }
    finish_reason = "stop"
    if result.tool_calls:
        message["tool_calls"] = result.tool_calls
        finish_reason = "tool_calls"
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.prompt_tokens + result.completion_tokens,
        },
    }


def sse_chunk_payload(
    *,
    completion_id: str,
    request_model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
) -> str:
    """Encode one OpenAI streaming chunk as an SSE ``data:`` line."""
    payload: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": request_model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage is not None:
        payload["usage"] = usage
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def sse_done() -> str:
    """Return the OpenAI SSE stream terminator."""
    return "data: [DONE]\n\n"
