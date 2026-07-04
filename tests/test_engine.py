"""Unit tests for the LiteLLM completion engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import litellm
import pytest

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.settings import ProviderKeys
from ylang.usage.store import UsageWindow, open_store


@pytest.fixture
def engine(tmp_path: object) -> Engine:
    store = open_store(tmp_path / "engine.db")  # type: ignore[operator]
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
    return Engine(store, surface="test", router=router)


def _mock_response(content: str = "ok", *, model: str = "openai/gpt-4o") -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    response.model = model
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=25)
    response._hidden_params = {"response_cost": 0.01}
    return response


def test_complete_success(engine: Engine) -> None:
    with patch("ylang.core.engine.litellm.completion", return_value=_mock_response("hello")):
        result = engine.complete([{"role": "user", "content": "hi"}], "code")
    assert result.success is True
    assert result.content == "hello"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 25


def test_complete_fallback_on_rate_limit(engine: Engine) -> None:
    calls: list[str] = []

    def side_effect(**kwargs: object) -> MagicMock:
        model = str(kwargs["model"])
        calls.append(model)
        if model == "openai/gpt-4o":
            raise litellm.RateLimitError("rate limited", "openai", "gpt-4o")
        return _mock_response("fallback-ok", model=model)

    with patch("ylang.core.engine.litellm.completion", side_effect=side_effect):
        result = engine.complete([{"role": "user", "content": "hi"}], "code")

    assert result.success is True
    assert result.content == "fallback-ok"
    assert calls[0] == "openai/gpt-4o"
    assert "ollama/qwen2.5" in calls


def test_complete_logs_usage_on_failure(engine: Engine) -> None:
    with patch(
        "ylang.core.engine.litellm.completion",
        side_effect=RuntimeError("permanent failure"),
    ):
        result = engine.complete([{"role": "user", "content": "hi"}], "code")
    assert result.success is False
    usage_rows = engine._store.recall_usage(UsageWindow.last_hours(1))  # type: ignore[attr-defined]
    assert len(usage_rows) == 1
    assert usage_rows[0].success is False
