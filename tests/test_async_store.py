"""Tests for async SQLite store operations from gateway handlers."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.types import CompletionResult
from ylang.gateway.routes import register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.settings import ProviderKeys
from ylang.usage.store import open_store


@pytest.fixture
def gateway_client(tmp_path: object) -> TestClient:
    store = open_store(tmp_path / "async.db")  # type: ignore[operator]
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
    engine = Engine(store, surface="gateway", router=router)
    server = FastMCP("ylang-test", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), "secret-token")
    return TestClient(app)


def test_concurrent_gateway_requests_do_not_deadlock(gateway_client: TestClient) -> None:
    mock_result = CompletionResult(
        content="ok",
        model_used="openai/gpt-4o",
        prompt_tokens=1,
        completion_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=True,
    )

    def slow_complete(*_args: object, **_kwargs: object) -> CompletionResult:
        time.sleep(0.05)
        return mock_result

    with patch.object(Engine, "complete", side_effect=slow_complete):

        def make_request(index: int) -> object:
            return gateway_client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer secret-token"},
                json={
                    "model": "route-code",
                    "messages": [{"role": "user", "content": f"hi {index}"}],
                },
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(make_request, range(6)))

    assert all(response.status_code == 200 for response in responses)  # type: ignore[attr-defined]


def test_usage_dashboard_route(gateway_client: TestClient) -> None:
    response = gateway_client.get(
        "/usage",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Ylang Usage Dashboard" in response.text
