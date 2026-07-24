"""Console page renderers."""

from __future__ import annotations

from html import escape

from ylang.console.layout import render_console_page
from ylang.library.patterns import DetectedPattern, TemplateProposal

def render_patterns_page(
    patterns: list[DetectedPattern],
    proposals: list[TemplateProposal | None],
    *,
    skip_reasons: list[str | None] | None = None,
    alert_count: int = 0,
    threshold: int = 3,
) -> str:
    """Render detected patterns with save-learned actions."""
    alert = ""
    if alert_count >= threshold:
        alert = f'<div class="flash ok">{alert_count} pattern(s) meet the alert threshold ({threshold}+).</div>'
    blocks = []
    reasons = skip_reasons or [None] * len(patterns)
    for pattern, proposal, skip_reason in zip(patterns, proposals, reasons, strict=False):
        proposal_html = "<p>No proposal</p>"
        if skip_reason:
            proposal_html = (
                f'<p class="flash warn">Skipped: {escape(skip_reason)}</p>'
            )
        elif proposal is not None:
            proposal_html = (
                f"<p><strong>{escape(proposal.name)}</strong></p>"
                f"<pre>{escape(proposal.body)}</pre>"
                f"<p class='subtitle'>{escape(proposal.rationale)}</p>"
                f"""<form method="post" action="/console/patterns/save">
                <input type="hidden" name="template_id" value="{escape(proposal.suggested_template_id)}">
                <input type="hidden" name="name" value="{escape(proposal.name)}">
                <input type="hidden" name="body" value="{escape(proposal.body)}">
                <button type="submit">Save learned template</button></form>"""
            )
        blocks.append(
            f'<div class="panel"><h3>{escape(pattern.pattern_id)} '
            f'<span class="badge">{pattern.occurrence_count}×</span></h3>'
            f"<pre>{escape(pattern.sample_text[:500])}</pre>{proposal_html}</div>"
        )
    body = (
        alert
        + '<p class="subtitle">Run detection on demand (may call LLM to synthesize template bodies).</p>'
        + '<form method="post" action="/console/patterns/run" class="panel"><button type="submit">Run pattern detection</button></form>'
        + ("".join(blocks) or '<div class="panel">No patterns stored yet — run detection above.</div>')
    )
    return render_console_page(
        title="Patterns",
        body_html=body,
        active_nav="patterns",
        alert_badge=str(alert_count) if alert_count >= threshold else None,
    )

