"""Operator-console metrics derived from real usage rows."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.settings import provider_from_litellm_model
from ylang.usage.aggregates import _cached_recall_usage
from ylang.usage.store import UsageStore, UsageWindow


@dataclass(frozen=True, slots=True)
class TodayMetrics:
    """TODAY hub metrics for the last rolling window."""

    requests: int
    spend: float
    successes: int
    failures: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    local_requests: int
    cloud_requests: int


@dataclass(frozen=True, slots=True)
class RoutingMetrics:
    """ROUTING hub distribution and fallback stats."""

    by_model: dict[str, int]
    fallback_count: int
    provider_failure_classes: dict[str, int]
    routing_one_liners: list[str]


def _percentile(sorted_values: list[int], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def today_metrics(store: UsageStore, window: UsageWindow) -> TodayMetrics:
    """Compute TODAY metrics from persisted usage rows."""
    rows = _cached_recall_usage(store, window)
    latencies = sorted(row.latency_ms for row in rows)
    local = 0
    cloud = 0
    for row in rows:
        if provider_from_litellm_model(row.model_used) is None:
            local += 1
        else:
            cloud += 1
    successes = sum(1 for row in rows if row.success)
    return TodayMetrics(
        requests=len(rows),
        spend=sum(row.cost for row in rows),
        successes=successes,
        failures=len(rows) - successes,
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        local_requests=local,
        cloud_requests=cloud,
    )


def routing_metrics(store: UsageStore, window: UsageWindow) -> RoutingMetrics:
    """Compute ROUTING metrics including fallback and reason one-liners."""
    from ylang.core.routing_reason import routing_one_liner

    rows = _cached_recall_usage(store, window)
    by_model: dict[str, int] = {}
    fallback_count = 0
    failure_classes: dict[str, int] = {}
    one_liners: list[str] = []
    for row in rows:
        by_model[row.model_used] = by_model.get(row.model_used, 0) + 1
        if row.fallback_events_json:
            fallback_count += 1
        if row.error_class:
            failure_classes[row.error_class] = (
                failure_classes.get(row.error_class, 0) + 1
            )
        if row.routing_reason_json and len(one_liners) < 20:
            one_liners.append(routing_one_liner(row.routing_reason_json))
    return RoutingMetrics(
        by_model=dict(sorted(by_model.items(), key=lambda item: (-item[1], item[0]))),
        fallback_count=fallback_count,
        provider_failure_classes=dict(
            sorted(failure_classes.items(), key=lambda item: (-item[1], item[0]))
        ),
        routing_one_liners=one_liners,
    )


def sensitive_trace_count(store: UsageStore, window: UsageWindow) -> int:
    """Count rows that likely hold higher-sensitivity capture content."""
    rows = _cached_recall_usage(store, window)
    return sum(
        1
        for row in rows
        if (row.capture_level or "") in {"redacted", "full_local"}
        or row.prompt_body_redacted
    )
