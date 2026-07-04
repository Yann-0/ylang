"""Tests for usage dashboard HTML generation."""

from __future__ import annotations

from ylang.usage.aggregates import DailyUsageBucket, UsageSummary
from ylang.usage.dashboard import render_usage_dashboard_html


def test_dashboard_includes_chart_sections() -> None:
    summary = UsageSummary(
        total_requests=5,
        total_cost=0.25,
        total_tokens=500,
        success_rate=0.8,
        by_activity={"code": 3, "search": 2},
        by_model={"openai/gpt-4o": 5},
        model_costs={"openai/gpt-4o": 0.25},
        model_success_counts={"openai/gpt-4o": 4},
    )
    buckets = [
        DailyUsageBucket(date="2026-07-01", requests=2, cost=0.10, successes=2),
        DailyUsageBucket(date="2026-07-02", requests=3, cost=0.15, successes=2),
    ]
    html = render_usage_dashboard_html(
        summary,
        title="Test Dashboard",
        daily_buckets=buckets,
        live=True,
    )
    assert "chart.js" in html.lower()
    assert "costChart" in html
    assert "activityChart" in html
    assert "modelChart" in html
    assert "successChart" in html
    assert "Cost over time" in html
    assert "Success rate" in html
    assert 'http-equiv="refresh"' in html
    assert "2026-07-01" in html
    assert "80.0%" in html
