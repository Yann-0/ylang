"""HTML usage dashboard generator."""

from __future__ import annotations

from html import escape

from ylang.usage.aggregates import UsageSummary


def render_usage_dashboard_html(summary: UsageSummary, *, title: str = "Ylang Usage") -> str:
    """Render a minimal static HTML dashboard from aggregated usage data."""
    activity_rows = _bar_rows(summary.by_activity, summary.total_requests)
    model_rows = _bar_rows(summary.by_model, summary.total_requests)
    cost_rows = _cost_rows(summary.model_costs, summary.total_cost)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
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
  .bar {{ display: grid; grid-template-columns: 8rem 1fr 4rem; gap: 0.75rem; align-items: center; margin: 0.35rem 0; }}
  .bar-label {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.9rem; }}
  .bar-track {{ background: #243044; border-radius: 999px; height: 0.65rem; overflow: hidden; }}
  .bar-fill {{ background: linear-gradient(90deg, #3b82f6, #6366f1); height: 100%; border-radius: 999px; }}
  .bar-count {{ text-align: right; color: #9aa7b8; font-size: 0.85rem; }}
</style>
</head>
<body>
<h1>{escape(title)}</h1>
<p class="subtitle">Rolling usage summary</p>
<div class="cards">
  <div class="card"><div class="label">Requests</div><div class="value">{summary.total_requests}</div></div>
  <div class="card"><div class="label">Total cost</div><div class="value">${summary.total_cost:.4f}</div></div>
  <div class="card"><div class="label">Tokens</div><div class="value">{summary.total_tokens:,}</div></div>
  <div class="card"><div class="label">Success rate</div><div class="value">{summary.success_rate * 100:.1f}%</div></div>
</div>
<section>
  <h2>By activity</h2>
  {activity_rows}
</section>
<section>
  <h2>By model (requests)</h2>
  {model_rows}
</section>
<section>
  <h2>By model (cost)</h2>
  {cost_rows}
</section>
</body>
</html>
"""


def _bar_rows(counts: dict[str, int], total: int) -> str:
    if not counts:
        return "<p class='subtitle'>No data</p>"
    max_count = max(counts.values()) or 1
    rows: list[str] = []
    for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        width = (count / max_count) * 100
        pct = (count / total * 100) if total else 0
        rows.append(
            f"<div class='bar'>"
            f"<div class='bar-label'>{escape(label)}</div>"
            f"<div class='bar-track'><div class='bar-fill' style='width:{width:.1f}%'></div></div>"
            f"<div class='bar-count'>{count} ({pct:.0f}%)</div>"
            f"</div>"
        )
    return "\n".join(rows)


def _cost_rows(costs: dict[str, float], total: float) -> str:
    if not costs:
        return "<p class='subtitle'>No data</p>"
    max_cost = max(costs.values()) or 1.0
    rows: list[str] = []
    for label, cost in sorted(costs.items(), key=lambda item: item[1], reverse=True):
        width = (cost / max_cost) * 100
        pct = (cost / total * 100) if total else 0
        rows.append(
            f"<div class='bar'>"
            f"<div class='bar-label'>{escape(label)}</div>"
            f"<div class='bar-track'><div class='bar-fill' style='width:{width:.1f}%'></div></div>"
            f"<div class='bar-count'>${cost:.4f} ({pct:.0f}%)</div>"
            f"</div>"
        )
    return "\n".join(rows)
