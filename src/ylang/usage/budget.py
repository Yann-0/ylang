"""Budget threshold warnings at startup."""

from __future__ import annotations

import sys

from ylang.settings import Settings
from ylang.usage.aggregates import clear_aggregate_cache, default_daily_window, rolling_cost
from ylang.usage.store import UsageStore

_BUDGET_WARN_FRACTION = 0.80


def warn_budget_threshold(settings: Settings, store: UsageStore) -> None:
    """Log a stderr warning when rolling 24h spend reaches 80% of the daily budget cap."""
    budget = settings.daily_budget_usd
    if budget is None or budget <= 0:
        return
    clear_aggregate_cache()
    spent = rolling_cost(store, default_daily_window())
    threshold = budget * _BUDGET_WARN_FRACTION
    if spent < threshold:
        return
    pct = (spent / budget) * 100 if budget else 0.0
    print(
        f"warning: rolling 24h spend ${spent:.2f} is {pct:.0f}% of "
        f"daily budget ${budget:.2f}",
        file=sys.stderr,
    )
