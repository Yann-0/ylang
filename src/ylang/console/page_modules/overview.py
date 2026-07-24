"""Console page renderers."""

from __future__ import annotations

from html import escape

from ylang import __version__
from ylang.console.control_data import (
    format_ratio_percent,
    performance_ratio_subtitle,
    polish_ratio_subtitle,
)
from ylang.console.layout import render_console_page
from ylang.usage.improver_analytics import (
    ImproverFunnelSummary,
    ImproverQualityScores,
)
from ylang.usage.optimizer import OptimizationSuggestion

def render_overview_page(
    *,
    health_ok: bool,
    version: str,
    providers_configured: list[str],
    providers_missing: list[str],
    budget_spent: float | None,
    budget_cap: float | None,
    funnel: ImproverFunnelSummary,
    suggestions: list[OptimizationSuggestion],
    narrative: str | None = None,
    narrative_available: bool = False,
    fact_count: int = 0,
    quality: ImproverQualityScores | None = None,
) -> str:
    """Render the console overview with health, budget, funnel, and suggestions."""
    health_badge = (
        '<span class="badge ok">OK</span>'
        if health_ok
        else '<span class="badge err">Error</span>'
    )
    provider_text = (
        ", ".join(providers_configured) if providers_configured else "(none)"
    )
    budget_value = "—"
    if budget_cap is not None:
        spent = budget_spent or 0.0
        budget_value = f"${spent:.2f} / ${budget_cap:.2f}"

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

    cards = f"""
<div class="cards">
  <div class="card"><div class="label">Health</div><div class="value">{health_badge}</div></div>
  <div class="card"><div class="label">Version</div><div class="value">{escape(version)}</div></div>
  <div class="card"><div class="label">Providers</div><div class="value" style="font-size:1rem">{escape(provider_text)}</div></div>
  <div class="card"><div class="label">24h budget</div><div class="value">{budget_value}</div></div>
  <div class="card"><div class="label">Improver accept</div><div class="value">{funnel.accept_rate * 100:.1f}%</div></div>
  <div class="card"><div class="label">Improver validated</div><div class="value">{funnel.validation_rate * 100:.1f}%</div></div>
  <div class="card"><div class="label">Polish ratio</div><div class="value">{polish_value}</div></div>
  <div class="card"><div class="label">Performance ratio</div><div class="value">{perf_value}</div></div>
  <div class="card"><div class="label">Facts</div><div class="value">{fact_count}</div></div>
</div>
<p class="subtitle">Polish: {escape(polish_hint)} · Performance: {escape(perf_hint)}</p>
"""

    suggestion_html = ""
    if fact_count == 0:
        suggestion_html += """
<div class="panel">
  <h2>Add facts</h2>
  <p class="subtitle">No memory facts yet. Suggest preferences from recent improver
  usage, or add samples on the Facts page.</p>
  <a class="btn" href="/console/facts?suggest=1">Suggest facts with AI</a>
</div>
"""
    if narrative:
        suggestion_html += f'<div class="panel"><h2>AI optimization narrative</h2><p>{escape(narrative)}</p></div>'
    elif narrative_available:
        suggestion_html += """
<div class="panel">
  <h2>AI optimization narrative</h2>
  <p class="subtitle">Generate a short LLM summary of improver analytics (uses one reason-model call).</p>
  <button type="button" id="narrativeBtn">Generate narrative</button>
  <pre id="narrativeResult" style="margin-top:1rem;display:none"></pre>
</div>
<script>
document.getElementById("narrativeBtn")?.addEventListener("click", async () => {
  const el = document.getElementById("narrativeResult");
  el.style.display = "block";
  el.textContent = "Running…";
  try {
    const response = await fetch("/console/api/narrative", { method: "POST" });
    const payload = await response.json();
    el.textContent = payload.narrative || payload.error || JSON.stringify(payload, null, 2);
  } finally {
    window.ylangLoadingDone?.();
  }
});
</script>
"""
    if suggestions:
        blocks = []
        for item in suggestions[:8]:
            blocks.append(
                f'<div class="suggestion {escape(item.priority)}">'
                f"<strong>{escape(item.title)}</strong> "
                f'<span class="badge">{escape(item.kind)}</span>'
                f"<p>{escape(item.description)}</p>"
                f'<p class="subtitle">{escape(item.evidence)}</p></div>'
            )
        suggestion_html += f'<div class="panel"><h2>Optimization suggestions</h2>{"".join(blocks)}</div>'

    improver_panel = """
<div class="panel" id="improver-sandbox">
  <h2>Test improver</h2>
  <form id="improveForm" data-no-loading>
    <div class="form-row">
      <label for="prompt">Prompt</label>
      <textarea id="prompt" name="prompt" rows="4" placeholder="Rough task description…"></textarea>
    </div>
    <div class="form-row">
      <label for="mode">Cursor mode</label>
      <select id="mode" name="mode">
        <option value="agent">agent</option>
        <option value="plan">plan</option>
        <option value="debug">debug</option>
        <option value="ask">ask</option>
        <option value="multitask">multitask</option>
      </select>
    </div>
    <button type="button" id="improvePreviewBtn">Preview improvement</button>
  </form>
  <div id="improveDiff" style="margin-top:1rem;display:none">
    <div class="panel"><h3>Original</h3><pre id="improveOriginal"></pre></div>
    <div class="panel"><h3>Improved</h3><pre id="improveImproved"></pre></div>
    <p id="improveMeta" class="subtitle"></p>
  </div>
</div>
<script>
document.getElementById("improvePreviewBtn")?.addEventListener("click", async () => {
  const prompt = document.getElementById("prompt").value;
  const mode = document.getElementById("mode").value;
  const diffEl = document.getElementById("improveDiff");
  diffEl.style.display = "block";
  document.getElementById("improveOriginal").textContent = "Running…";
  document.getElementById("improveImproved").textContent = "";
  document.getElementById("improveMeta").textContent = "";
  try {
    const response = await fetch("/console/api/improve-preview", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: prompt, mode, tool: "cursor-" + mode, model: "auto"}),
    });
    const payload = await response.json();
    if (!payload.ok) {
      document.getElementById("improveOriginal").textContent = payload.error || "Error";
      return;
    }
    document.getElementById("improveOriginal").textContent = payload.original || "";
    document.getElementById("improveImproved").textContent = payload.improved || "";
    document.getElementById("improveMeta").textContent =
      `validated=${payload.validated} changed=${payload.changed} auto_apply=${payload.auto_apply_default}` +
      (payload.rejection_reason ? ` rejection=${payload.rejection_reason}` : "");
  } finally {
    window.ylangLoadingDone?.();
  }
});
</script>
"""

    body = cards + suggestion_html + improver_panel
    return render_console_page(
        title="Overview",
        subtitle=f"Ylang admin console v{__version__}",
        body_html=body,
        active_nav="overview",
    )

