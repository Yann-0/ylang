"""HTML usage dashboard generator with live Chart.js charts."""

from __future__ import annotations

import json
from html import escape

from ylang.usage.aggregates import DailyUsageBucket, UsageSummary
from ylang.usage.improver_analytics import ImproverFunnelSummary


def render_usage_dashboard_html(
    summary: UsageSummary,
    *,
    title: str = "Ylang Usage",
    daily_buckets: list[DailyUsageBucket] | None = None,
    improver_funnel: ImproverFunnelSummary | None = None,
    refresh_seconds: int = 30,
    live: bool = False,
) -> str:
    """Render an HTML dashboard with Chart.js charts from aggregated usage data."""
    daily_buckets = daily_buckets or []
    cost_labels = [bucket.date for bucket in daily_buckets]
    cost_values = [round(bucket.cost, 4) for bucket in daily_buckets]
    request_values = [bucket.requests for bucket in daily_buckets]
    success_rates = [
        round(bucket.successes / bucket.requests * 100, 1) if bucket.requests else 0.0
        for bucket in daily_buckets
    ]

    activity_labels = list(summary.by_activity.keys())
    activity_values = list(summary.by_activity.values())
    model_labels = list(summary.by_model.keys())
    model_values = list(summary.by_model.values())

    improver_mode_labels: list[str] = []
    improver_accept_rates: list[float] = []
    rejection_labels: list[str] = []
    rejection_values: list[int] = []
    if improver_funnel is not None:
        for mode, stats in sorted(improver_funnel.by_mode.items()):
            improver_mode_labels.append(mode)
            rate = stats.accepted / stats.fired * 100 if stats.fired else 0.0
            improver_accept_rates.append(round(rate, 1))
        for reason, count in list(improver_funnel.top_rejection_reasons.items())[:8]:
            rejection_labels.append(reason[:40])
            rejection_values.append(count)

    refresh_meta = (
        f'<meta http-equiv="refresh" content="{refresh_seconds}">' if live else ""
    )
    chart_data = json.dumps(
        {
            "costLabels": cost_labels,
            "costValues": cost_values,
            "requestValues": request_values,
            "successRates": success_rates,
            "activityLabels": activity_labels,
            "activityValues": activity_values,
            "modelLabels": model_labels,
            "modelValues": model_values,
            "successRate": round(summary.success_rate * 100, 1),
            "improverModeLabels": improver_mode_labels,
            "improverAcceptRates": improver_accept_rates,
            "rejectionLabels": rejection_labels,
            "rejectionValues": rejection_values,
            "improverAcceptRate": round(improver_funnel.accept_rate * 100, 1)
            if improver_funnel
            else 0.0,
            "improverValidationRate": round(improver_funnel.validation_rate * 100, 1)
            if improver_funnel
            else 0.0,
        }
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{refresh_meta}
<title>{escape(title)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0f1419; color: #e7ecf3; }}
  h1 {{ margin-bottom: 0.25rem; }}
  .subtitle {{ color: #9aa7b8; margin-bottom: 2rem; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: #1a2332; border-radius: 0.5rem; padding: 1rem 1.25rem; }}
  .card .label {{ color: #9aa7b8; font-size: 0.85rem; }}
  .card .value {{ font-size: 1.75rem; font-weight: 600; margin-top: 0.25rem; }}
  section {{ margin-bottom: 2rem; }}
  h2 {{ font-size: 1.1rem; margin-bottom: 0.75rem; }}
  .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: 1.5rem; }}
  .chart-box {{ background: #1a2332; border-radius: 0.5rem; padding: 1rem; }}
  canvas {{ max-height: 16rem; }}
</style>
</head>
<body>
<h1>{escape(title)}</h1>
<p class="subtitle">Rolling usage summary{" (auto-refresh)" if live else ""}</p>
<div class="cards">
  <div class="card"><div class="label">Requests</div><div class="value">{summary.total_requests}</div></div>
  <div class="card"><div class="label">Total cost</div><div class="value">${summary.total_cost:.4f}</div></div>
  <div class="card"><div class="label">Tokens</div><div class="value">{summary.total_tokens:,}</div></div>
  <div class="card"><div class="label">Success rate</div><div class="value">{summary.success_rate * 100:.1f}%</div></div>
  {f'<div class="card"><div class="label">Improver accept</div><div class="value">{improver_funnel.accept_rate * 100:.1f}%</div></div>' if improver_funnel else ''}
  {f'<div class="card"><div class="label">Improver validated</div><div class="value">{improver_funnel.validation_rate * 100:.1f}%</div></div>' if improver_funnel else ''}
</div>
<section>
  <h2>Cost over time</h2>
  <div class="charts">
    <div class="chart-box"><canvas id="costChart"></canvas></div>
    <div class="chart-box"><canvas id="requestsChart"></canvas></div>
  </div>
</section>
<section>
  <h2>Requests by activity</h2>
  <div class="chart-box"><canvas id="activityChart"></canvas></div>
</section>
<section>
  <h2>Requests by model</h2>
  <div class="chart-box"><canvas id="modelChart"></canvas></div>
</section>
<section>
  <h2>Daily success rate</h2>
  <div class="chart-box"><canvas id="successChart"></canvas></div>
</section>
<section>
  <h2>Improver accept rate by mode</h2>
  <div class="chart-box"><canvas id="improverModeChart"></canvas></div>
</section>
<section>
  <h2>Top improver rejection reasons</h2>
  <div class="chart-box"><canvas id="rejectionChart"></canvas></div>
</section>
<script>
const DATA = {chart_data};
const gridColor = "rgba(154, 167, 184, 0.15)";
const textColor = "#9aa7b8";
Chart.defaults.color = textColor;
Chart.defaults.borderColor = gridColor;
function barChart(id, labels, values, label, color) {{
  const ctx = document.getElementById(id);
  if (!ctx || !labels.length) return;
  new Chart(ctx, {{
    type: "bar",
    data: {{ labels, datasets: [{{ label, data: values, backgroundColor: color }}] }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
  }});
}}
function doughnutChart(id, labels, values, label) {{
  const ctx = document.getElementById(id);
  if (!ctx || !labels.length) return;
  new Chart(ctx, {{
    type: "doughnut",
    data: {{ labels, datasets: [{{ label, data: values }}] }},
    options: {{ responsive: true }}
  }});
}}
barChart("costChart", DATA.costLabels, DATA.costValues, "Cost (USD)", "rgba(59, 130, 246, 0.8)");
barChart("requestsChart", DATA.costLabels, DATA.requestValues, "Requests", "rgba(99, 102, 241, 0.8)");
doughnutChart("activityChart", DATA.activityLabels, DATA.activityValues, "Requests");
doughnutChart("modelChart", DATA.modelLabels, DATA.modelValues, "Requests");
barChart("successChart", DATA.costLabels, DATA.successRates, "Success %", "rgba(34, 197, 94, 0.8)");
barChart("improverModeChart", DATA.improverModeLabels, DATA.improverAcceptRates, "Accept %", "rgba(168, 85, 247, 0.8)");
barChart("rejectionChart", DATA.rejectionLabels, DATA.rejectionValues, "Count", "rgba(239, 68, 68, 0.8)");
</script>
</body>
</html>
"""
