"""Usage aggregation helpers for budget metering and analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ylang.usage.store import UsageStore, UsageWindow


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


def rolling_cost(store: UsageStore, window: UsageWindow) -> float:
    """Sum cost for all usage rows in the given window."""
    return sum(row.cost for row in store.recall_usage(window))


def summarize_usage(store: UsageStore, window: UsageWindow) -> UsageSummary:
    """Build aggregated usage statistics for a time window."""
    rows = store.recall_usage(window)
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
