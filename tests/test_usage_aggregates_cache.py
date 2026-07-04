"""Tests for short-TTL usage aggregate caching."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from ylang.usage.aggregates import (
    clear_aggregate_cache,
    default_daily_window,
    rolling_cost,
    summarize_usage,
)
from ylang.usage.store import open_store


def test_cached_recall_avoids_repeated_store_reads(tmp_path: object) -> None:
    store = open_store(tmp_path / "cache.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    store.write_usage(
        surface="test",
        activity="code",
        model_used="openai/gpt-4o",
        prompt_tokens=10,
        cost=1.5,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(hours=1),
    )
    clear_aggregate_cache()
    window = default_daily_window(now=now)

    with patch.object(store, "recall_usage", wraps=store.recall_usage) as recall:
        assert rolling_cost(store, window) == 1.5
        assert summarize_usage(store, window).total_requests == 1
        assert recall.call_count == 1


def test_cache_expires_after_ttl(tmp_path: object) -> None:
    store = open_store(tmp_path / "cache-expire.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    store.write_usage(
        surface="test",
        activity="code",
        model_used="openai/gpt-4o",
        prompt_tokens=5,
        cost=2.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(hours=1),
    )
    clear_aggregate_cache()
    window = default_daily_window(now=now)

    with patch.object(store, "recall_usage", wraps=store.recall_usage) as recall:
        with patch("ylang.usage.aggregates.time.monotonic", side_effect=[100.0, 200.0]):
            assert rolling_cost(store, window) == 2.0
            assert rolling_cost(store, window) == 2.0
        assert recall.call_count == 2
