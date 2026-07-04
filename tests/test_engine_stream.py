"""Tests for Engine streaming completions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.types import StreamCompletionError
from ylang.settings import ProviderKeys
from ylang.usage.store import UsageWindow, open_store


@pytest.fixture
def engine(tmp_path: object) -> Engine:
    store = open_store(tmp_path / "stream.db")  # type: ignore[operator]
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
    return Engine(store, surface="gateway", router=router)


def _stream_chunk(content: str) -> MagicMock:
    chunk = MagicMock()
    chunk.choices = [MagicMock(delta=MagicMock(content=content), finish_reason=None)]
    chunk.model = "openai/gpt-4o"
    chunk.usage = None
    chunk._hidden_params = {}
    return chunk


def test_complete_stream_yields_deltas_and_logs_once(engine: Engine) -> None:
    stream = [_stream_chunk("hel"), _stream_chunk("lo")]

    with patch("ylang.core.engine.litellm.completion", return_value=iter(stream)):
        chunks = list(engine.complete_stream([{"role": "user", "content": "hi"}], "code"))

    assert [chunk.content for chunk in chunks] == ["hel", "lo"]
    rows = engine._store.recall_usage(UsageWindow.last_hours(1))  # type: ignore[attr-defined]
    assert len(rows) == 1
    assert rows[0].surface == "gateway"
    assert rows[0].success is True


def test_complete_stream_failure_logs_once_and_raises(engine: Engine) -> None:
    with patch(
        "ylang.core.engine.litellm.completion",
        side_effect=RuntimeError("stream failed"),
    ):
        with pytest.raises(StreamCompletionError):
            list(engine.complete_stream([{"role": "user", "content": "hi"}], "code"))

    rows = engine._store.recall_usage(UsageWindow.last_hours(1))  # type: ignore[attr-defined]
    assert len(rows) == 1
    assert rows[0].success is False
