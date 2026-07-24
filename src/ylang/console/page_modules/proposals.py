"""Console page renderers."""

from __future__ import annotations

from html import escape

from ylang.console.apply_audit import ApplyAuditEntry
from ylang.console.layout import render_console_page
from ylang.console.proposals import PendingProposal

def _proposal_apply_summary(item: PendingProposal) -> str:
    """Human-readable apply payload for a pending proposal."""
    if item.setting_key and item.setting_value is not None:
        return f"Will set <code>{escape(item.setting_key)}={escape(item.setting_value)}</code>"
    if item.apply_type == "archive_templates" and item.template_id:
        count = len(item.template_id.split(","))
        return f"Will archive <code>{count}</code> template(s)"
    if item.apply_type == "suggest_facts":
        return "Will open Facts page with AI suggestions"
    if item.template_id:
        return f"Will save learned template <code>{escape(item.template_id)}</code>"
    if item.apply_type == "experiment_activate":
        return "Will activate the winning experiment variant"
    return f"Apply type: <code>{escape(item.apply_type)}</code>"


def render_proposals_page(
    *,
    proposals: list[PendingProposal],
    audit_entries: list[ApplyAuditEntry],
    message: str | None = None,
) -> str:
    """Render pending optimization proposals and recent apply audit log."""
    flash = f'<div class="flash ok">{escape(message)}</div>' if message else ""
    proposal_blocks = []
    for item in proposals:
        proposal_blocks.append(
            f'<div class="suggestion {escape(item.priority)}">'
            f"<strong>{escape(item.title)}</strong> "
            f'<span class="badge">{escape(item.kind)}</span>'
            f"<p>{escape(item.description)}</p>"
            f'<p class="subtitle">{escape(item.evidence)}</p>'
            f'<p class="subtitle">{_proposal_apply_summary(item)}</p>'
            f'<form method="post" action="/console/proposals/apply" style="margin-top:0.5rem">'
            f'<input type="hidden" name="proposal_id" value="{escape(item.proposal_id)}">'
            f'<button type="submit">Apply</button></form></div>'
        )
    audit_rows = []
    for entry in audit_entries:
        audit_rows.append(
            f"<tr><td>{escape(entry.timestamp.isoformat())}</td>"
            f"<td>{escape(entry.actor)}</td>"
            f"<td>{escape(entry.proposal_id)}</td>"
            f"<td>{escape(entry.action_type)}</td>"
            f"<td>{escape(entry.detail)}</td></tr>"
        )
    body = f"""
{flash}
<p class="subtitle">Proposals are suggest-only until you click <strong>Apply</strong>. Nothing is auto-applied.</p>
<div class="panel"><h2>Pending proposals</h2>
{"".join(proposal_blocks) or "<p>No applyable proposals in the last 7 days.</p>"}</div>
<div class="panel"><h2>Apply audit log</h2>
<div class="table-wrap">
<table><thead><tr><th>Time</th><th>Actor</th><th>Proposal</th><th>Action</th><th>Detail</th></tr></thead>
<tbody>{"".join(audit_rows) or '<tr><td colspan="5">No apply actions yet</td></tr>'}</tbody></table>
</div></div>
"""
    return render_console_page(title="Proposals", body_html=body, active_nav="proposals")

