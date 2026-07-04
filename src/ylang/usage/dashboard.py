"""HTML usage dashboard generator with live Chart.js charts."""

from __future__ import annotations

import json
from html import escape

from ylang.usage.aggregates import DailyUsageBucket, UsageSummary


def render_usage_dashboard_html(
    summary: UsageSummary,
    *,
    title: str = "Ylang Usage",
    daily_buckets: list[DailyUsageBucket] | None = None,
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
</script>
</body>
</html>
"""
