"""Tests for OpenAI gateway HTTP routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.types import CompletionResult, StreamChunk
from ylang.gateway.routes import register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.settings import ProviderKeys
from ylang.usage.store import open_store


@pytest.fixture
def gateway_client(tmp_path: object) -> TestClient:
    store = open_store(tmp_path / "gateway.db")  # type: ignore[operator]
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


def test_models_requires_bearer_auth(gateway_client: TestClient) -> None:
    response = gateway_client.get("/v1/models")
    assert response.status_code == 401


def test_models_lists_virtual_models(gateway_client: TestClient) -> None:
    response = gateway_client.get(
        "/v1/models",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    ids = {item["id"] for item in payload["data"]}
    assert ids == {"route-code", "route-search", "route-reason", "route-other"}


def test_chat_completion_non_stream(gateway_client: TestClient) -> None:
    mock_result = CompletionResult(
        content="hello",
        model_used="openai/gpt-4o",
        prompt_tokens=12,
        cost=0.01,
        latency_ms=5,
        success=True,
    )
    with patch.object(Engine, "complete", return_value=mock_result):
        response = gateway_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "model": "route-code",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hello"
    assert body["model"] == "route-code"


def test_chat_completion_stream_sse(gateway_client: TestClient) -> None:
    def fake_stream(*_args: object, **_kwargs: object):
        yield StreamChunk(content="hel")
        yield StreamChunk(content="lo")

    with patch.object(Engine, "complete_stream", side_effect=fake_stream):
        response = gateway_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "model": "route-reason",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in response.text
    assert '"delta":{"content":"hel"}' in response.text.replace(" ", "")


def test_chat_completion_failure_returns_openai_error(gateway_client: TestClient) -> None:
    mock_result = CompletionResult(
        content="",
        model_used="openai/gpt-4o",
        prompt_tokens=0,
        cost=0.0,
        latency_ms=1,
        success=False,
        error="model not found",
    )
    with patch.object(Engine, "complete", return_value=mock_result):
        response = gateway_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "model": "missing/model",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "model_not_found"
