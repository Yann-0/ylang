"""Console page renderers."""

from __future__ import annotations


from ylang.console.layout import render_console_page
from ylang.usage.aggregates import DailyUsageBucket, UsageSummary
from ylang.usage.dashboard import render_usage_dashboard_html
from ylang.usage.improver_analytics import (
    ImproverFunnelSummary,
)

def render_usage_page(
    summary: UsageSummary,
    *,
    daily_buckets: list[DailyUsageBucket],
    funnel: ImproverFunnelSummary | None,
) -> str:
    """Embed the existing usage dashboard inside the console layout."""
    inner = render_usage_dashboard_html(
        summary,
        title="Usage",
        daily_buckets=daily_buckets,
        improver_funnel=funnel,
        live=True,
    )
    # Strip outer html/body from dashboard and wrap in console nav
    start = inner.find("<body>")
    end = inner.find("</body>")
    fragment = inner[start + 6 : end] if start >= 0 and end > start else inner
    return render_console_page(
        title="Usage",
        subtitle="Rolling 7-day usage (auto-refresh)",
        body_html=fragment,
        active_nav="usage",
    )

