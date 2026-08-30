"""Operator hub page renderers (Today / Quality / Routing / Privacy)."""

from __future__ import annotations

from html import escape

from ylang.console.layout import render_console_page
from ylang.core.routing_reason import routing_one_liner
from ylang.usage.improver_analytics import ImproverFunnelSummary, TemplateEffectivenessRow
from ylang.usage.operator_metrics import RoutingMetrics, TodayMetrics


def render_today_page(*, metrics: TodayMetrics, budget_cap: float | None) -> str:
    """Render TODAY operator hub from real usage aggregates."""
    budget = (
        f"${metrics.spend:.4f} / ${budget_cap:.2f}"
        if budget_cap is not None
        else f"${metrics.spend:.4f}"
    )
    p50 = "—" if metrics.p50_latency_ms is None else f"{metrics.p50_latency_ms:.0f} ms"
    p95 = "—" if metrics.p95_latency_ms is None else f"{metrics.p95_latency_ms:.0f} ms"
    cards = f"""
<div class="cards">
  <div class="card"><div class="label">Requests</div><div class="value">{metrics.requests}</div></div>
  <div class="card"><div class="label">Spend</div><div class="value">{escape(budget)}</div></div>
  <div class="card"><div class="label">Success</div><div class="value">{metrics.successes}</div></div>
  <div class="card"><div class="label">Failure</div><div class="value">{metrics.failures}</div></div>
  <div class="card"><div class="label">p50 latency</div><div class="value">{escape(p50)}</div></div>
  <div class="card"><div class="label">p95 latency</div><div class="value">{escape(p95)}</div></div>
  <div class="card"><div class="label">Local</div><div class="value">{metrics.local_requests}</div></div>
  <div class="card"><div class="label">Cloud</div><div class="value">{metrics.cloud_requests}</div></div>
</div>
"""
    return render_console_page(
        title="Today",
        subtitle="Last 24h requests, spend, success/failure, latency, local/cloud split.",
        body_html=cards,
        active_nav="today",
    )


def render_quality_page(
    *,
    funnel: ImproverFunnelSummary,
    effectiveness: list[TemplateEffectivenessRow],
) -> str:
    """Render QUALITY hub from improver funnel + template effectiveness."""
    rows = "".join(
        f"<tr><td>{escape(item.template_id)}</td>"
        f"<td>{item.injections}</td>"
        f"<td>{item.accept_rate * 100:.1f}%</td></tr>"
        for item in effectiveness[:25]
    ) or "<tr><td colspan='3'>No template samples in window.</td></tr>"
    body = f"""
<div class="cards">
  <div class="card"><div class="label">Improver fired</div><div class="value">{funnel.total_fired}</div></div>
  <div class="card"><div class="label">Accept rate</div><div class="value">{funnel.accept_rate * 100:.1f}%</div></div>
  <div class="card"><div class="label">Validation rate</div><div class="value">{funnel.validation_rate * 100:.1f}%</div></div>
</div>
<section class="panel">
  <h2>Templates losing effectiveness</h2>
  <p class="subtitle">USER + HEURISTIC signals — not “silence as success”.</p>
  <table><thead><tr><th>Template</th><th>Samples</th><th>Accept</th></tr></thead>
  <tbody>{rows}</tbody></table>
</section>
"""
    return render_console_page(
        title="Quality",
        subtitle="Outcome trends and templates with weak accept rates.",
        body_html=body,
        active_nav="quality",
    )


def render_routing_page(*, metrics: RoutingMetrics) -> str:
    """Render ROUTING hub: model mix, fallbacks, reason one-liners."""
    model_rows = "".join(
        f"<tr><td><code>{escape(model)}</code></td><td>{count}</td></tr>"
        for model, count in metrics.by_model.items()
    ) or "<tr><td colspan='2'>No routed calls.</td></tr>"
    fail_rows = "".join(
        f"<tr><td>{escape(klass)}</td><td>{count}</td></tr>"
        for klass, count in metrics.provider_failure_classes.items()
    ) or "<tr><td colspan='2'>No classified provider failures.</td></tr>"
    liners = "".join(
        f"<li>{escape(line)}</li>" for line in metrics.routing_one_liners
    ) or "<li>No routing reasons yet.</li>"
    body = f"""
<div class="cards">
  <div class="card"><div class="label">Fallback events</div><div class="value">{metrics.fallback_count}</div></div>
</div>
<section class="panel">
  <h2>Model distribution</h2>
  <table><thead><tr><th>Model</th><th>Calls</th></tr></thead><tbody>{model_rows}</tbody></table>
</section>
<section class="panel">
  <h2>Provider failure classes</h2>
  <table><thead><tr><th>Class</th><th>Count</th></tr></thead><tbody>{fail_rows}</tbody></table>
</section>
<section class="panel">
  <h2>Why routes were selected</h2>
  <ul>{liners}</ul>
</section>
"""
    return render_console_page(
        title="Routing",
        subtitle="Model mix, fallbacks, and explainable route reasons.",
        body_html=body,
        active_nav="routing",
    )


def render_privacy_page(
    *,
    capture_level: str,
    retention_days: int,
    sensitive_count: int,
) -> str:
    """Render PRIVACY hub: capture policy and non-observables."""
    body = f"""
<div class="cards">
  <div class="card"><div class="label">Capture level</div><div class="value">{escape(capture_level)}</div></div>
  <div class="card"><div class="label">Retention days</div><div class="value">{retention_days}</div></div>
  <div class="card"><div class="label">Sensitive traces</div><div class="value">{sensitive_count}</div></div>
</div>
<section class="panel">
  <h2>What Ylang cannot observe</h2>
  <ul>
    <li>Agent hidden chain-of-thought inside Cursor or other hosts</li>
    <li>Tools invoked outside Ylang faces</li>
    <li>True user satisfaction without an explicit USER SIGNAL</li>
    <li>Cross-process causality without an explicit parent trace id</li>
  </ul>
  <p class="subtitle">Purge redacted bodies with <code>ylang purge-traces</code>. Local-only; no Ylang cloud storage.</p>
</section>
"""
    return render_console_page(
        title="Privacy",
        subtitle="Captured-data policy, retention, and observation limits.",
        body_html=body,
        active_nav="privacy",
    )


def explain_route_line(routing_reason_json: str | None) -> str:
    """Public helper for console/API one-liners (CP-024)."""
    return routing_one_liner(routing_reason_json)
