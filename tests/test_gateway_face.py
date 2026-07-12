"""Gateway face integration tests — auth, routing, passthrough, streaming, usage logging."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.gateway.routes import register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.settings import ProviderKeys
from ylang.usage.store import UsageWindow, open_store

_AUTH_HEADERS = {"Authorization": "Bearer secret-token"}


@pytest.fixture
def gateway_setup(tmp_path: object) -> tuple[TestClient, object, Engine, ModelRouter]:
    store = open_store(tmp_path / "gateway-face.db")  # type: ignore[operator]
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
    return TestClient(app), store, engine, router


def _litellm_completion_response(
    *,
    content: str = "hello",
    model: str = "openai/gpt-4o",
    prompt_tokens: int = 12,
    completion_tokens: int = 8,
    cost: float = 0.01,
) -> MagicMock:
    mock_message = MagicMock()
    mock_message.content = content
    mock_message.tool_calls = None
    mock_choice = MagicMock(message=mock_message)
    return MagicMock(
        choices=[mock_choice],
        model=model,
        usage=MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        _hidden_params={"response_cost": cost},
    )


def _stream_content_chunk(content: str, *, model: str = "openai/gpt-4o") -> MagicMock:
    chunk = MagicMock()
    chunk.choices = [MagicMock(delta=MagicMock(content=content), finish_reason=None)]
    chunk.model = model
    chunk.usage = None
    chunk._hidden_params = {}
    return chunk


def _stream_usage_chunk(
    *,
    model: str = "openai/gpt-4o",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    cost: float = 0.02,
) -> MagicMock:
    chunk = MagicMock()
    chunk.choices = []
    chunk.model = model
    chunk.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    chunk._hidden_params = {"response_cost": cost}
    return chunk


def _usage_rows(store: object) -> list[object]:
    return store.recall_usage(UsageWindow.last_hours(1))  # type: ignore[attr-defined]


# --- Auth ---


def test_chat_completions_requires_bearer_token(gateway_setup: tuple[TestClient, object, Engine, ModelRouter]) -> None:
    client, _, _, _ = gateway_setup
    response = client.post(
        "/v1/chat/completions",
        json={"model": "route-code", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401


def test_usage_dashboard_requires_bearer_token(gateway_setup: tuple[TestClient, object, Engine, ModelRouter]) -> None:
    client, _, _, _ = gateway_setup
    response = client.get("/usage")
    assert response.status_code == 401


def test_chat_completions_accepts_bearer_token(gateway_setup: tuple[TestClient, object, Engine, ModelRouter]) -> None:
    client, _, _, _ = gateway_setup
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_litellm_completion_response(),
    ):
        response = client.post(
            "/v1/chat/completions",
            headers=_AUTH_HEADERS,
            json={"model": "route-code", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hello"


def test_usage_dashboard_accepts_bearer_token(gateway_setup: tuple[TestClient, object, Engine, ModelRouter]) -> None:
    client, _, _, _ = gateway_setup
    response = client.get("/usage", headers=_AUTH_HEADERS)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Ylang Usage Dashboard" in response.text


def test_health_is_unauthenticated(gateway_setup: tuple[TestClient, object, Engine, ModelRouter]) -> None:
    client, _, _, _ = gateway_setup
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "ylang"


# --- Routing ---


def test_route_code_resolves_through_router_and_logs_one_gateway_row(
    gateway_setup: tuple[TestClient, object, Engine, ModelRouter],
) -> None:
    client, store, _, router = gateway_setup
    with (
        patch(
            "ylang.core.engine.litellm.completion",
            return_value=_litellm_completion_response(model="openai/gpt-4o"),
        ) as completion_mock,
        patch.object(ModelRouter, "build_attempt_chain", wraps=router.build_attempt_chain) as chain_mock,
    ):
        response = client.post(
            "/v1/chat/completions",
            headers=_AUTH_HEADERS,
            json={"model": "route-code", "messages": [{"role": "user", "content": "write code"}]},
        )

    assert response.status_code == 200
    chain_mock.assert_called_once()
    assert chain_mock.call_args.args[0] == "code"
    assert chain_mock.call_args.kwargs.get("explicit_model") is None
    completion_mock.assert_called_once()
    assert completion_mock.call_args.kwargs["model"] == "openai/gpt-4o"

    rows = _usage_rows(store)
    assert len(rows) == 1
    assert rows[0].surface == "gateway"
    assert rows[0].activity == "code"
    assert rows[0].model_used == "openai/gpt-4o"
    assert rows[0].success is True
    assert rows[0].prompt_tokens == 12
    assert rows[0].cost == pytest.approx(0.01)


# --- Passthrough ---


def test_passthrough_model_is_honored(gateway_setup: tuple[TestClient, object, Engine, ModelRouter]) -> None:
    client, store, _, router = gateway_setup
    with (
        patch(
            "ylang.core.engine.litellm.completion",
            return_value=_litellm_completion_response(
                content="local reply",
                model="ollama/qwen2.5",
                prompt_tokens=6,
                completion_tokens=4,
                cost=0.0,
            ),
        ) as completion_mock,
        patch.object(ModelRouter, "build_attempt_chain", wraps=router.build_attempt_chain) as chain_mock,
    ):
        response = client.post(
            "/v1/chat/completions",
            headers=_AUTH_HEADERS,
            json={
                "model": "ollama/qwen2.5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "ollama/qwen2.5"
    assert body["choices"][0]["message"]["content"] == "local reply"

    chain_mock.assert_called_once()
    assert chain_mock.call_args.args[0] == "other"
    assert chain_mock.call_args.kwargs.get("explicit_model") == "ollama/qwen2.5"
    completion_mock.assert_called_once()
    assert completion_mock.call_args.kwargs["model"] == "ollama/qwen2.5"

    rows = _usage_rows(store)
    assert len(rows) == 1
    assert rows[0].surface == "gateway"
    assert rows[0].activity == "other"
    assert rows[0].model_used == "ollama/qwen2.5"


# --- Streaming ---


def test_stream_returns_openai_sse_and_logs_one_usage_row(
    gateway_setup: tuple[TestClient, object, Engine, ModelRouter],
) -> None:
    client, store, _, _ = gateway_setup

    def fake_stream(*_args: object, **_kwargs: object) -> Iterator[MagicMock]:
        yield _stream_content_chunk("hel")
        yield _stream_content_chunk("lo")
        yield _stream_usage_chunk(prompt_tokens=10, completion_tokens=5, cost=0.03)

    with patch("ylang.core.engine.litellm.completion", side_effect=fake_stream):
        response = client.post(
            "/v1/chat/completions",
            headers=_AUTH_HEADERS,
            json={
                "model": "route-code",
                "messages": [{"role": "user", "content": "stream please"}],
                "stream": True,
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "data: [DONE]" in text
    assert "chat.completion.chunk" in text
    assert '"delta":{"content":"hel"}' in text.replace(" ", "")
    assert '"delta":{"content":"lo"}' in text.replace(" ", "")
    compact = text.replace(" ", "")
    assert '"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}' in compact

    rows = _usage_rows(store)
    assert len(rows) == 1
    assert rows[0].surface == "gateway"
    assert rows[0].activity == "code"
    assert rows[0].success is True
    assert rows[0].prompt_tokens == 10
    assert rows[0].cost == pytest.approx(0.03)
