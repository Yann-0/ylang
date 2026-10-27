"""Unit tests for the financially bounded shared completion engine."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.bounded_adapter_helpers import OfflineAdapter, initialize_budget, response

from ylang.core.bounded_completion import BoundedFailure
from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.settings import ProviderKeys
from ylang.usage.store import UsageWindow, open_store


def make_engine(tmp_path: Path, adapter: OfflineAdapter) -> Engine:
    """Inject an explicit trusted adapter into a private, initialized budget domain."""
    store = open_store(tmp_path / "engine.db")
    initialize_budget(store)
    router = ModelRouter(activity_model_lists={"code": ["openai/gpt-4o"]},
                         provider_keys=ProviderKeys(openai="test-key"),
                         fallback_model="ollama/qwen2.5")
    return Engine(store, surface="test", router=router,
                  bounded_adapters={"openai/gpt-4o": adapter})


def test_complete_success(tmp_path: Path) -> None:
    adapter = OfflineAdapter(response("hello"))
    engine = make_engine(tmp_path, adapter)
    result = engine.complete([{"role": "user", "content": "hi"}], "code")
    assert result.success is True
    assert result.content == "hello"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 25
    assert len(adapter.calls) == 1


def test_complete_fallback_on_trusted_bounded_failure(tmp_path: Path) -> None:
    adapter = OfflineAdapter(BoundedFailure("rate limited", charge_nanos=1_000_000,
                             evidence={"billability": "trusted synthetic terminal"}, retry_allowed=True))
    engine = make_engine(tmp_path, adapter)
    local = MagicMock()
    local.choices = [MagicMock(message=MagicMock(content="fallback-ok", tool_calls=None))]
    local.model = "ollama/qwen2.5"
    local.usage = MagicMock(prompt_tokens=10, completion_tokens=25)
    local._hidden_params = {"response_cost": 0.0}
    with patch("ylang.core.engine.litellm.completion", return_value=local) as transport:
        result = engine.complete([{"role": "user", "content": "hi"}], "code")
    assert result.success is True
    assert result.content == "fallback-ok"
    assert result.error is None
    assert result.cost == 0.001
    rows = engine.store.recall_usage(UsageWindow.last_hours(1))
    assert len(rows) == 1 and rows[0].success is True
    assert rows[0].error_class is None
    events = json.loads(rows[0].fallback_events_json or "[]")
    assert events[0]["from"] == "openai/gpt-4o"
    assert events[0]["to"] == "ollama/qwen2.5"
    assert len(adapter.calls) == 1
    assert transport.call_count == 1
    assert transport.call_args.kwargs["model"] == "ollama/qwen2.5"


def test_complete_logs_usage_on_failure(tmp_path: Path) -> None:
    adapter = OfflineAdapter(RuntimeError("permanent failure"))
    engine = make_engine(tmp_path, adapter)
    result = engine.complete([{"role": "user", "content": "hi"}], "code")
    assert result.success is False
    usage_rows = engine.store.recall_usage(UsageWindow.last_hours(1))
    assert len(usage_rows) == 1
    assert usage_rows[0].success is False
    assert len(adapter.calls) == 1
