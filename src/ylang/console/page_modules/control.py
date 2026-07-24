"""Console page renderers."""

from __future__ import annotations

from html import escape

from ylang.console.control_data import (
    EffectiveConfigSummary,
    StoreInventory,
    format_ratio_percent,
    improver_avg_latency_ms,
    performance_ratio_subtitle,
    polish_ratio_subtitle,
    should_show_facts_onboarding_cta,
    sort_by_priority,
)
from ylang.console.layout import render_console_page
from ylang.console.proposals import PendingProposal
from ylang.console.page_modules.proposals import _proposal_apply_summary
from ylang.usage.aggregates import UsageSummary
from ylang.usage.improver_analytics import (
    ImproverQualityScores,
    TemplateEffectivenessRow,
)

def _render_proposal_blocks(
    proposals: list[PendingProposal],
    *,
    return_to: str = "/console/control",
) -> str:
    """Render apply forms for pending proposals with a post-apply redirect."""
    blocks: list[str] = []
    for item in proposals:
        blocks.append(
            f'<div class="suggestion {escape(item.priority)}">'
            f"<strong>{escape(item.title)}</strong> "
            f'<span class="badge">{escape(item.kind)}</span>'
            f"<p>{escape(item.description)}</p>"
            f'<p class="subtitle">{escape(item.evidence)}</p>'
            f'<p class="subtitle">{_proposal_apply_summary(item)}</p>'
            f'<form method="post" action="/console/proposals/apply" style="margin-top:0.5rem">'
            f'<input type="hidden" name="proposal_id" value="{escape(item.proposal_id)}">'
            f'<input type="hidden" name="return_to" value="{escape(return_to)}">'
            f'<button type="submit">Apply</button></form></div>'
        )
    return "".join(blocks)


def render_control_page(
    *,
    config: EffectiveConfigSummary,
    inventory: StoreInventory,
    budget_spent: float | None,
    budget_cap: float | None,
    funnel,
    usage_summary: UsageSummary | None,
    control_proposals: list[PendingProposal],
    optimizer_proposals: list[PendingProposal],
    zero_accept_templates: tuple[TemplateEffectivenessRow, ...] = (),
    quality: ImproverQualityScores | None = None,
    message: str | None = None,
) -> str:
    """Render the Operator Hub with KPIs, proposals, alerts, and quick links."""
    flash = f'<div class="flash ok">{escape(message)}</div>' if message else ""

    budget_value = "—"
    if budget_cap is not None:
        spent = budget_spent or 0.0
        budget_value = f"${spent:.2f} / ${budget_cap:.2f}"

    usage_requests = usage_summary.total_requests if usage_summary else 0
    usage_cost = usage_summary.total_cost if usage_summary else 0.0
    avg_latency = improver_avg_latency_ms(funnel)
    latency_value = f"{avg_latency:.0f}ms" if avg_latency is not None else "—"
    polish_value = format_ratio_percent(quality.polish_ratio if quality else None)
    perf_value = format_ratio_percent(quality.performance_ratio if quality else None)
    polish_hint = (
        polish_ratio_subtitle(quality)
        if quality is not None
        else "Enable edit_feedback to unlock Polish ratio."
    )
    perf_hint = (
        performance_ratio_subtitle(quality)
        if quality is not None
        else "No improver calls in this window."
    )

    kpi_cards = f"""
<div class="cards">
  <div class="card"><div class="label">Improver accept (7d)</div><div class="value">{funnel.accept_rate * 100:.1f}%</div></div>
  <div class="card"><div class="label">Avg latency (7d)</div><div class="value">{latency_value}</div></div>
  <div class="card"><div class="label">Polish ratio (7d)</div><div class="value">{polish_value}</div></div>
  <div class="card"><div class="label">Performance ratio (7d)</div><div class="value">{perf_value}</div></div>
  <div class="card"><div class="label">24h budget</div><div class="value">{budget_value}</div></div>
  <div class="card"><div class="label">7d cost</div><div class="value">${usage_cost:.2f}</div></div>
  <div class="card"><div class="label">7d requests</div><div class="value">{usage_requests}</div></div>
  <div class="card"><div class="label">Improver fired (7d)</div><div class="value">{funnel.total_fired}</div></div>
</div>
<p class="subtitle">Polish: {escape(polish_hint)}</p>
<p class="subtitle">Performance: {escape(perf_hint)}</p>"""

    cta_row = """
<div class="hub-cta-row">
  <a class="btn" href="/console/settings">Parameters</a>
  <a class="btn btn-secondary" href="/console/data">Data</a>
  <a class="btn btn-secondary" href="/console#improver-sandbox">Improver sandbox</a>
  <a class="btn btn-secondary" href="/console/proposals">All proposals</a>
  <a class="btn btn-secondary" href="/console/usage">Usage charts</a>
</div>"""

    toxic_count = len(zero_accept_templates)
    accept_pct = f"{funnel.accept_rate * 100:.1f}%"
    wizard_panel = f"""
<div class="panel" id="optimize-wizard">
  <h2>Optimize Ylang</h2>
  <p class="subtitle">Four steps: diagnose → propose → apply → measure.</p>
  <ol class="optimize-steps">
    <li><strong>Diagnose</strong> — Accept {escape(accept_pct)}, latency {escape(latency_value)},
      toxic templates {toxic_count} (0% accept, ≥3 injections).</li>
    <li><strong>Propose</strong> — Review <a href="#top-proposals">pending proposals</a> below
      (optimizer + Control presets).</li>
    <li><strong>Apply</strong> — Use governed <strong>Apply</strong> on a proposal (audited;
      runtime settings hot-reload; archives take effect immediately).</li>
    <li><strong>Measure</strong> — Check <a href="/console/improver">Improver</a> and
      <a href="/console/usage">Usage</a>. Restart only if you changed env-only settings.</li>
  </ol>
</div>"""

    zero_accept_alert = ""
    if zero_accept_templates:
        rows = []
        for row in zero_accept_templates[:8]:
            rows.append(
                f"<tr><td><code>{escape(row.template_id)}</code></td>"
                f"<td>{row.injections}</td>"
                f"<td>0%</td>"
                f'<td><a href="/console/templates?q={escape(row.template_id)}">Open</a></td></tr>'
            )
        zero_accept_alert = f"""
<div class="panel alert-panel">
  <h2>Zero-accept templates</h2>
  <p class="subtitle">{len(zero_accept_templates)} template(s) with 0% accept rate and ≥3 injections in the last 7 days.
  Review on <a href="/console/improver">Improver</a> or apply archive proposals below.</p>
  <table><thead><tr><th>Template</th><th>Injections</th><th>Accept</th><th></th></tr></thead>
  <tbody>{"".join(rows)}</tbody></table>
</div>"""

    facts_onboarding = ""
    if should_show_facts_onboarding_cta(inventory):
        facts_onboarding = f"""
<div class="panel">
  <h2>Add memory facts</h2>
  <p class="subtitle">Only {inventory.facts_total} fact(s) stored — improver context improves with a few
  preferences. Browse <a href="/console/facts">Facts</a> or run the suggester
  (<code>POST /console/api/suggest-facts</code>) to draft candidates from recent usage.</p>
  <a class="btn" href="/console/facts?suggest=1">Suggest facts with AI</a>
  <a class="btn btn-secondary" href="/console/facts">Open Facts</a>
</div>"""

    seen_ids = {p.proposal_id for p in control_proposals}
    all_ops = sort_by_priority(
        control_proposals
        + [item for item in optimizer_proposals if item.proposal_id not in seen_ids]
    )
    top_ops = all_ops[:6]
    ops_html = _render_proposal_blocks(top_ops)
    ops_panel = f"""
<div class="panel" id="top-proposals"><h2>Top applyable proposals</h2>
<p class="subtitle">Governed Apply runs through proposals + audit. Showing {len(top_ops)} of {len(all_ops)} pending.</p>
{ops_html or "<p>No pending proposals in the last 7 days.</p>"}
</div>"""

    config_rows = []
    for row in config.rows[:6]:
        override_note = (
            f' <span class="badge warn">override</span> <code>{escape(row.override)}</code>'
            if row.override
            else ' <span class="badge">default</span>'
        )
        config_rows.append(
            f"<tr><td><code>{escape(row.key)}</code></td>"
            f"<td>{escape(row.effective)}{override_note}</td></tr>"
        )
    source_bits = ", ".join(
        f"{escape(k)}={v}" for k, v in sorted(inventory.templates.by_source.items())
    ) or "—"

    glance_panel = f"""
<div class="panel"><h2>At a glance</h2>
<div class="cards">
  <div class="card"><div class="label">Templates</div><div class="value">{inventory.templates.total}</div></div>
  <div class="card"><div class="label">Facts</div><div class="value">{inventory.facts_total}</div></div>
  <div class="card"><div class="label">Usage rows</div><div class="value">{inventory.usage_rows}</div></div>
  <div class="card"><div class="label">Archived</div><div class="value">{inventory.templates.archived}</div></div>
</div>
<p class="subtitle">By source: {source_bits} · models_improve: <code>{escape(config.models_improve)}</code></p>
<table><thead><tr><th>Key</th><th>Effective</th></tr></thead>
<tbody>{"".join(config_rows)}</tbody></table>
<p class="subtitle"><a href="/console/settings">Edit parameters</a> ·
<a href="/console/templates">Templates</a> · <a href="/console/facts">Facts</a></p>
</div>"""

    body = (
        flash
        + wizard_panel
        + kpi_cards
        + cta_row
        + facts_onboarding
        + zero_accept_alert
        + ops_panel
        + glance_panel
    )
    return render_console_page(
        title="Operator Hub",
        subtitle="Health KPIs, governed proposals, and quick operator links",
        body_html=body,
        active_nav="control",
    )

