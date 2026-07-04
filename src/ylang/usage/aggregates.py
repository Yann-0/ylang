"""Usage aggregation helpers for budget metering and analytics."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from ylang.usage.store import UsageRecord, UsageStore, UsageWindow

# Short TTL avoids full-table scans on every model-router decision.
_DEFAULT_CACHE_TTL_SECONDS = 45.0


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """Aggregated usage statistics for a time window."""

    total_requests: int
    total_cost: float
    total_tokens: int
    success_rate: float
    by_activity: dict[str, int]
    by_model: dict[str, int]
    model_costs: dict[str, float]
    model_success_counts: dict[str, int]


@dataclass
class _WindowCacheEntry:
    """In-memory cache entry for usage rows in a time window."""

    expires_at: float
    rows: list[UsageRecord]


_window_cache: dict[tuple[int, str, str], _WindowCacheEntry] = {}


def clear_aggregate_cache() -> None:
    """Clear the in-memory usage aggregate cache (primarily for tests)."""
    _window_cache.clear()


def _cache_key(store: UsageStore, window: UsageWindow) -> tuple[int, str, str]:
    return (id(store), window.since.isoformat(), window.until.isoformat())


def _cached_recall_usage(
    store: UsageStore,
    window: UsageWindow,
    *,
    ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
) -> list[UsageRecord]:
    """Return usage rows for a window, reusing a short-TTL in-memory cache."""
    key = _cache_key(store, window)
    now = time.monotonic()
    entry = _window_cache.get(key)
    if entry is not None and entry.expires_at > now:
        return entry.rows

    rows = store.recall_usage(window)
    _window_cache[key] = _WindowCacheEntry(
        expires_at=now + ttl_seconds,
        rows=rows,
    )
    return rows


def rolling_cost(store: UsageStore, window: UsageWindow) -> float:
    """Sum cost for all usage rows in the given window."""
    return sum(row.cost for row in _cached_recall_usage(store, window))


def summarize_usage(store: UsageStore, window: UsageWindow) -> UsageSummary:
    """Build aggregated usage statistics for a time window."""
    rows = _cached_recall_usage(store, window)
    by_activity: dict[str, int] = {}
    by_model: dict[str, int] = {}
    model_costs: dict[str, float] = {}
    model_success: dict[str, int] = {}
    total_cost = 0.0
    total_tokens = 0
    successes = 0

    for row in rows:
        by_activity[row.activity] = by_activity.get(row.activity, 0) + 1
        by_model[row.model_used] = by_model.get(row.model_used, 0) + 1
        model_costs[row.model_used] = model_costs.get(row.model_used, 0.0) + row.cost
        if row.success:
            successes += 1
            model_success[row.model_used] = model_success.get(row.model_used, 0) + 1
        total_cost += row.cost
        total_tokens += row.prompt_tokens

    total = len(rows)
    success_rate = successes / total if total else 0.0
    return UsageSummary(
        total_requests=total,
        total_cost=total_cost,
        total_tokens=total_tokens,
        success_rate=success_rate,
        by_activity=by_activity,
        by_model=by_model,
        model_costs=model_costs,
        model_success_counts=model_success,
    )


def default_daily_window(*, now: datetime | None = None) -> UsageWindow:
    """Return a UTC window covering the last 24 hours."""
    anchor = now or datetime.now(timezone.utc)
    return UsageWindow.last_hours(24, now=anchor)
