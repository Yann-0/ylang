"""Console page renderers."""

from __future__ import annotations

from html import escape

from ylang.console.layout import render_console_page, render_empty_state
from ylang.usage.experiment_results import VariantOutcome
from ylang.usage.experiments import ExperimentVariant

def render_experiments_page(
    variants: list[ExperimentVariant],
    outcomes: list[VariantOutcome],
    *,
    experiments_enabled: bool = False,
) -> str:
    """Render experiment variant management and outcomes."""
    rows = []
    for item in variants:
        toggle = "Deactivate" if item.active else "Activate"
        action = "deactivate" if item.active else "activate"
        rows.append(
            f"<tr><td>{escape(item.experiment_id)}</td><td>{escape(item.variant_id)}</td>"
            f"<td><code>{escape(item.config_hash)}</code></td>"
            f"<td>{item.traffic_pct:.0f}%</td>"
            f"<td>{'active' if item.active else 'inactive'}</td>"
            f"""<td><form method="post" action="/console/experiments/toggle" style="display:inline">
            <input type="hidden" name="experiment_id" value="{escape(item.experiment_id)}">
            <input type="hidden" name="variant_id" value="{escape(item.variant_id)}">
            <input type="hidden" name="active" value="{action}">
            <button type="submit" class="btn-secondary">{toggle}</button></form></td></tr>"""
        )
    outcome_rows = []
    best = max(outcomes, key=lambda item: item.accept_rate, default=None)
    for item in outcomes:
        winner = " ★" if best and item.variant_id == best.variant_id and item.samples >= 5 else ""
        outcome_rows.append(
            f"<tr><td>{escape(item.variant_id)}{winner}</td><td>{escape(item.config_hash)}</td>"
            f"<td>{item.samples}</td><td>{item.accept_rate * 100:.1f}%</td>"
            f"<td>{item.validated}</td></tr>"
        )

    empty_banner = ""
    if not experiments_enabled:
        empty_banner = render_empty_state(
            title="Experiments are off",
            body=(
                "A/B assignment for improver system prompts is disabled. "
                "Enable the flag to route traffic across variants you create here."
            ),
            primary_href="/console/settings",
            primary_label="Enable in Settings",
        )
    elif not variants:
        empty_banner = render_empty_state(
            title="No variants yet",
            body=(
                "Create a control and at least one alternate config hash, "
                "then watch accept rate in the 7-day outcomes table."
            ),
        )

    create_form = """
<form method="post" action="/console/experiments" class="panel" id="createVariantForm">
  <h2>Create variant</h2>
  <div class="form-row"><label>Experiment ID</label><input name="experiment_id" value="improver-agent" required></div>
  <div class="form-row"><label>Variant ID</label><input name="variant_id" placeholder="control|variant-a" required></div>
  <div class="form-row"><label>Config hash</label>
    <select name="config_hash" required>
      <option value="control">control — default system prompt</option>
      <option value="concise">concise — shorter structured output</option>
      <option value="verbose">verbose — expanded deliverables section</option>
    </select></div>
  <div class="form-row"><label>Traffic %</label><input name="traffic_pct" type="number" value="50" min="0" max="100"></div>
  <button type="submit">Upsert variant</button>
</form>
"""
    body = f"""
<p class="subtitle">Prompt A/B experiments for improver system prompt variants (7-day window).</p>
{empty_banner}
{create_form}
<table><thead><tr><th>Experiment</th><th>Variant</th><th>Config</th><th>Traffic</th><th>Status</th><th>Action</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="6">No variants</td></tr>'}</tbody></table>
<div class="panel"><h2>Outcomes (7 days)</h2>
<table><thead><tr><th>Variant</th><th>Config</th><th>Samples</th><th>Accept rate</th><th>Validated</th></tr></thead>
<tbody>{"".join(outcome_rows) or '<tr><td colspan="5">No experiment traffic yet</td></tr>'}</tbody></table>
<p class="subtitle">★ marks leading variant when samples ≥ 5.</p></div>
"""
    return render_console_page(
        title="Experiments", body_html=body, active_nav="experiments"
    )

