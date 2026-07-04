"""Tests for gateway tool-calling passthrough."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.types import CompletionResult
from ylang.gateway.openai import chat_completion_payload, parse_chat_request
from ylang.gateway.routes import register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.settings import ProviderKeys
from ylang.usage.store import open_store


@pytest.fixture
def gateway_client(tmp_path: object) -> TestClient:
    store = open_store(tmp_path / "tools.db")  # type: ignore[operator]
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


def test_parse_chat_request_accepts_tools() -> None:
    body = {
        "model": "route-code",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function", "function": {"name": "search", "parameters": {}}}],
        "tool_choice": "auto",
    }
    messages, model, stream, tools, tool_choice = parse_chat_request(body)
    assert model == "route-code"
    assert stream is False
    assert tools is not None
    assert len(tools) == 1
    assert tool_choice == "auto"


def test_chat_completion_payload_includes_tool_calls() -> None:
    result = CompletionResult(
        content="",
        model_used="openai/gpt-4o",
        prompt_tokens=10,
        completion_tokens=5,
        cost=0.0,
        latency_ms=1,
        success=True,
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search", "arguments": "{}"},
            }
        ],
    )
    payload = chat_completion_payload(result, completion_id="id", request_model="route-code")
    message = payload["choices"][0]["message"]
    assert message["tool_calls"][0]["function"]["name"] == "search"
    assert payload["choices"][0]["finish_reason"] == "tool_calls"


def test_gateway_forwards_tools_to_engine(gateway_client: TestClient) -> None:
    mock_result = CompletionResult(
        content="",
        model_used="openai/gpt-4o",
        prompt_tokens=12,
        completion_tokens=8,
        cost=0.01,
        latency_ms=5,
        success=True,
        tool_calls=[
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
            }
        ],
    )
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
    with patch.object(Engine, "complete", return_value=mock_result) as complete_mock:
        response = gateway_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "model": "route-code",
                "messages": [{"role": "user", "content": "weather?"}],
                "tools": tools,
                "tool_choice": "auto",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    assert body["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
    _, kwargs = complete_mock.call_args
    assert kwargs["tools"] == tools
    assert kwargs["tool_choice"] == "auto"


def test_engine_forwards_tools_to_litellm(tmp_path: object) -> None:
    store = open_store(tmp_path / "litellm-tools.db")  # type: ignore[operator]
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k"),
        fallback_model="ollama/qwen2.5",
    )
    engine = Engine(store, surface="test", router=router)
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

    mock_message = MagicMock()
    mock_message.content = ""
    mock_function = MagicMock()
    mock_function.name = "search"
    mock_function.arguments = "{}"
    mock_message.tool_calls = [
        MagicMock(
            id="call_1",
            type="function",
            function=mock_function,
        )
    ]
    mock_choice = MagicMock(message=mock_message)
    mock_response = MagicMock(
        choices=[mock_choice],
        model="openai/gpt-4o",
        usage=MagicMock(prompt_tokens=5, completion_tokens=3),
        _hidden_params={"response_cost": 0.0},
    )

    with patch("ylang.core.engine.litellm.completion", return_value=mock_response) as completion_mock:
        result = engine.complete(
            [{"role": "user", "content": "find docs"}],
            "code",
            tools=tools,
            tool_choice="auto",
        )

    assert result.success is True
    assert result.tool_calls[0]["function"]["name"] == "search"
    completion_mock.assert_called_once()
    assert completion_mock.call_args.kwargs["tools"] == tools
