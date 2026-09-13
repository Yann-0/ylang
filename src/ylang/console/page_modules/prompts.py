"""Console pages for prompt sources and candidates."""

from __future__ import annotations

from html import escape

from ylang.console.layout import render_console_page, render_empty_state
from ylang.importer.source_types import PromptSource, SourceItem, TemplateProvenance


def render_sources_page(
    sources: list[PromptSource],
    *,
    message: str | None = None,
) -> str:
    """Render allowlisted prompt sources (not a marketplace)."""
    flash = f'<div class="flash ok">{escape(message)}</div>' if message else ""
    if not sources:
        body = render_empty_state(
            title="No sources registered",
            body="Built-in sources should appear after opening the local database.",
            primary_href="/console/templates",
            primary_label="Templates",
        )
    else:
        rows = []
        for source in sources:
            enabled = "on" if source.enabled else "off"
            err = (
                f'<span class="badge err">{escape(source.last_error[:80])}</span>'
                if source.last_error
                else '<span class="badge ok">ok</span>'
            )
            enable_action = "disable" if source.enabled else "enable"
            enable_btn = ""
            if source.source_id != "manual-import":
                enable_btn = f"""
<form method="post" action="/console/sources/{enable_action}" class="inline-form">
  <input type="hidden" name="source_id" value="{escape(source.source_id)}">
  <button type="submit" class="btn-secondary">{enable_action}</button>
</form>"""
            refresh_btn = ""
            if source.source_id != "manual-import":
                refresh_btn = f"""
<form method="post" action="/console/sources/refresh" class="inline-form">
  <input type="hidden" name="source_id" value="{escape(source.source_id)}">
  <button type="submit">Refresh</button>
</form>"""
            rows.append(
                "<tr>"
                f"<td>{escape(source.source_id)}</td>"
                f"<td>{escape(source.license_spdx)}</td>"
                f"<td>{enabled}</td>"
                f"<td>{escape(source.last_success_at or '—')}</td>"
                f"<td><code>{escape((source.last_revision or '—')[:12])}</code></td>"
                f"<td>{err}</td>"
                f'<td class="col-actions">{enable_btn}{refresh_btn}</td>'
                "</tr>"
            )
        body = f"""
{flash}
<p class="subtitle">Refresh automatically; trust manually. Scheduled sources stay
disabled until you enable them. Arbitrary URL imports never become scheduled sources.</p>
<div class="panel">
<table>
<thead><tr>
  <th>Source</th><th>License</th><th>Enabled</th><th>Last refresh</th>
  <th>Revision</th><th>Status</th><th></th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
"""
    return render_console_page(
        title="Prompt sources",
        body_html=body,
        active_nav="sources",
    )


def render_candidates_page(
    items: list[SourceItem],
    *,
    selected: SourceItem | None = None,
    diff_text: str | None = None,
    message: str | None = None,
) -> str:
    """Render candidate quarantine for human review."""
    flash = f'<div class="flash ok">{escape(message)}</div>' if message else ""
    if not items and selected is None:
        body = flash + render_empty_state(
            title="No candidates",
            body="Refresh an allowlisted source from CLI or Sources. Nothing is auto-promoted.",
            primary_href="/console/sources",
            primary_label="Sources",
        )
        return render_console_page(
            title="Prompt candidates",
            body_html=body,
            active_nav="candidates",
        )
    rows = []
    for item in items:
        href = f"/console/candidates?id={escape(item.item_id)}"
        rows.append(
            "<tr>"
            f'<td><a href="{href}">{escape(item.title[:80])}</a></td>'
            f"<td>{escape(item.task_family)}</td>"
            f"<td>{escape(item.source_id)}</td>"
            f"<td>{escape(item.candidate_state)}</td>"
            f"<td>{escape(item.risk_level)}</td>"
            f"<td>{'yes' if item.duplicate_of_item_id or item.duplicate_template_id else '—'}</td>"
            f"<td>{item.quality_score}</td>"
            "</tr>"
        )
    detail = ""
    if selected is not None:
        risk_note = ",".join(selected.risk_reasons) or "—"
        ack = ""
        if selected.risk_level == "high":
            ack = '<label><input type="checkbox" name="acknowledge_risk" value="1"> Acknowledge risk</label>'
        diff_block = (
            f"<h3>Diff</h3><pre>{escape(diff_text)}</pre>" if diff_text else ""
        )
        detail = f"""
<div class="panel">
  <h2>{escape(selected.title)}</h2>
  <p class="subtitle">{escape(selected.item_id)} · {escape(selected.candidate_state)} ·
  risk {escape(selected.risk_level)} ({escape(risk_note)}) · quality {selected.quality_score}
  · {escape(selected.canonical_url or '')}</p>
  <pre>{escape(selected.body)}</pre>
  {diff_block}
  <form method="post" action="/console/candidates/review" class="inline-form">
    <input type="hidden" name="item_id" value="{escape(selected.item_id)}">
    <button type="submit" class="btn-secondary">Review</button>
  </form>
  <form method="post" action="/console/candidates/reject" class="inline-form"
        onsubmit="return confirm('Reject this candidate?')">
    <input type="hidden" name="item_id" value="{escape(selected.item_id)}">
    <button type="submit" class="btn-secondary">Reject</button>
  </form>
  <form method="post" action="/console/candidates/promote" class="inline-form">
    <input type="hidden" name="item_id" value="{escape(selected.item_id)}">
    {ack}
    <button type="submit">Promote</button>
  </form>
  <form method="post" action="/console/candidates/evaluate" class="inline-form">
    <input type="hidden" name="item_id" value="{escape(selected.item_id)}">
    <button type="submit" class="btn-secondary">Evaluate vs current</button>
  </form>
</div>
"""
    body = f"""
{flash}
<p class="subtitle">Candidates are untrusted until you promote them. Promotion creates
an immutable local template version and never grants tools from upstream metadata.</p>
<div class="panel table-wrap">
<table>
<thead><tr>
  <th>Name</th><th>Task</th><th>Source</th><th>State</th><th>Risk</th>
  <th>Duplicate</th><th>Quality</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
{detail}
"""
    return render_console_page(
        title="Prompt candidates",
        body_html=body,
        active_nav="candidates",
    )


def render_provenance_panel(
    rows: list[TemplateProvenance],
    *,
    effectiveness: str | None = None,
) -> str:
    """HTML snippet for template detail provenance."""
    if not rows:
        return ""
    body_rows = "".join(
        "<tr>"
        f"<td>{row.version}</td>"
        f"<td>{escape(row.source_id)}</td>"
        f"<td><code>{escape((row.upstream_revision or '—')[:12])}</code></td>"
        f"<td><a href=\"/console/candidates?id={escape(row.item_id)}\">candidate</a></td>"
        f"<td>{escape(row.canonical_url or '—')}</td>"
        "</tr>"
        for row in rows
    )
    extra = f"<p>Usage/effectiveness: {escape(effectiveness)}</p>" if effectiveness else ""
    return f"""
<div class="panel">
  <h3>Upstream provenance</h3>
  {extra}
  <table>
  <thead><tr><th>Version</th><th>Source</th><th>Revision</th><th>Candidate</th><th>URL</th></tr></thead>
  <tbody>{body_rows}</tbody>
  </table>
</div>
"""
