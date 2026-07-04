"""Tests for gateway completion token shaping."""

from __future__ import annotations

from ylang.core.types import CompletionResult
from ylang.gateway.openai import chat_completion_payload


def test_chat_completion_payload_includes_completion_tokens() -> None:
    result = CompletionResult(
        content="hello",
        model_used="openai/gpt-4o",
        prompt_tokens=12,
        completion_tokens=34,
        cost=0.01,
        latency_ms=5,
        success=True,
    )
    payload = chat_completion_payload(
        result,
        completion_id="chatcmpl-test",
        request_model="route-code",
    )
    usage = payload["usage"]
    assert usage["prompt_tokens"] == 12
    assert usage["completion_tokens"] == 34
    assert usage["total_tokens"] == 46
