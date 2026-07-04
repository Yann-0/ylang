"""Tests for gateway streaming tool calls and usage token counts."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.types import StreamChunk
from ylang.gateway.routes import register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.settings import ProviderKeys
from ylang.usage.store import open_store


@pytest.fixture
def gateway_client(tmp_path: object) -> TestClient:
    store = open_store(tmp_path / "stream-tools.db")  # type: ignore[operator]
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="test-key"),
        fallback_model="ollama/qwen2.5",
    )
    engine = Engine(store, surface="gateway", router=router)
    server = FastMCP("ylang-test", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), "secret-token")
    return TestClient(app)


def test_stream_forwards_tools_to_engine(gateway_client: TestClient) -> None:
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

    def fake_stream(*_args: object, **kwargs: object):
        assert kwargs.get("tools") == tools
        assert kwargs.get("tool_choice") == "auto"
        yield StreamChunk(
            tool_calls_delta=[
                {
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        )

    with patch.object(Engine, "complete_stream", side_effect=fake_stream):
        response = gateway_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "model": "route-code",
                "messages": [{"role": "user", "content": "find docs"}],
                "stream": True,
                "tools": tools,
                "tool_choice": "auto",
            },
        )

    assert response.status_code == 200
    text = response.text.replace(" ", "")
    assert '"tool_calls"' in text
    assert '"finish_reason":"tool_calls"' in text
    assert "data: [DONE]" in response.text


def test_stream_emits_usage_tokens(gateway_client: TestClient) -> None:
    def fake_stream(*_args: object, **_kwargs: object):
        yield StreamChunk(content="hi")
        yield StreamChunk(
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        )

    with patch.object(Engine, "complete_stream", side_effect=fake_stream):
        response = gateway_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "model": "route-code",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )

    assert response.status_code == 200
    text = response.text.replace(" ", "")
    assert '"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}' in text
