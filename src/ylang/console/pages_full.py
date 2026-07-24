"""Additional admin console page renderers."""

from __future__ import annotations

from html import escape

from ylang.console.control_data import (
    format_ratio_percent,
    performance_ratio_subtitle,
    polish_ratio_subtitle,
)
from ylang.console.data_queries import TablePreview, list_data_domains
from ylang.console.layout import render_console_page, render_empty_state
from ylang.console.proposals import PendingProposal
from ylang.console.provider_health import ProviderStatus
from ylang.usage.feedback import FeedbackEvent
from ylang.usage.improver_analytics import (
    ImproverFunnelSummary,
    ImproverQualityScores,
    TemplateEffectivenessRow,
)


def render_login_page(*, next_path: str, error: str | None = None) -> str:
    """Render the console login form."""
    err = f'<div class="flash err">{escape(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Login — Ylang</title>
<style>
  body {{ font-family: system-ui,sans-serif; background:#0f1419; color:#e7ecf3; display:flex; min-height:100vh; align-items:center; justify-content:center; }}
  .box {{ background:#1a2332; padding:2rem; border-radius:.5rem; width:min(24rem,90vw); }}
  input, button {{ width:100%; margin-top:.5rem; padding:.5rem; font:inherit; }}
  button {{ background:#2563eb; color:#fff; border:none; border-radius:.35rem; cursor:pointer; }}
</style></head><body>
<div class="box">
  <h1>Ylang Console</h1>
  <p>Enter your <code>YLANG_AUTH_TOKEN</code> to open the admin UI.</p>
  {err}
  <form method="post" action="/console/login">
    <input type="hidden" name="next" value="{escape(next_path)}">
    <label for="token">Auth token</label>
    <input id="token" name="token" type="password" required autofocus>
    <button type="submit">Sign in</button>
  </form>
</div></body></html>"""


def render_improver_page(
    funnel: ImproverFunnelSummary,
    templates: list[TemplateEffectivenessRow],
    *,
    quality: ImproverQualityScores | None = None,
) -> str:
    """Render improver funnel and template effectiveness tables."""
    mode_rows = []
    for mode, stats in sorted(funnel.by_mode.items()):
        rate = stats.accepted / stats.fired * 100 if stats.fired else 0.0
        mode_perf = (
            format_ratio_percent(quality.performance_by_mode.get(mode))
            if quality is not None
            else "—"
        )
        mode_rows.append(
            f"<tr><td>{escape(mode)}</td><td>{stats.fired}</td><td>{stats.accepted}</td>"
            f"<td>{rate:.1f}%</td><td>{stats.avg_latency_ms:.0f}ms</td>"
            f"<td>{mode_perf}</td></tr>"
        )
    template_rows = []
    for row in templates[:30]:
        template_rows.append(
            f"<tr><td>{escape(row.template_id)}</td><td>{row.injections}</td>"
            f"<td>{row.accept_rate * 100:.1f}%</td><td>${row.avg_cost:.4f}</td></tr>"
        )
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
    polish_empty = ""
    if quality is not None and quality.polish_sample_count <= 0:
        polish_empty = render_empty_state(
            title="Polish ratio needs edit feedback",
            body=(
                "No edit-feedback samples in this window. Enable "
                "<strong>edit_feedback</strong> in Parameters and submit a few "
                "improved prompts to unlock Polish ratio."
            ),
            primary_href="/console/settings",
            primary_label="Open Parameters",
        )
    body = f"""
<div class="cards">
  <div class="card"><div class="label">Accept rate</div><div class="value">{funnel.accept_rate * 100:.1f}%</div></div>
  <div class="card"><div class="label">Validation rate</div><div class="value">{funnel.validation_rate * 100:.1f}%</div></div>
  <div class="card"><div class="label">Polish ratio</div><div class="value">{polish_value}</div></div>
  <div class="card"><div class="label">Performance ratio</div><div class="value">{perf_value}</div></div>
  <div class="card"><div class="label">Improver calls</div><div class="value">{funnel.total_fired}</div></div>
</div>
<p class="subtitle">Polish: {escape(polish_hint)}</p>
<p class="subtitle">Performance: {escape(perf_hint)}</p>
{polish_empty}
<div class="panel"><h2>By Cursor mode</h2>
<table><thead><tr><th>Mode</th><th>Fired</th><th>Accepted</th><th>Rate</th><th>Latency</th><th>Performance</th></tr></thead>
<tbody>{"".join(mode_rows) or '<tr><td colspan="6">No improver usage yet</td></tr>'}</tbody></table></div>
<div class="panel"><h2>Template effectiveness</h2>
<table><thead><tr><th>Template</th><th>Injections</th><th>Accept rate</th><th>Avg cost</th></tr></thead>
<tbody>{"".join(template_rows) or '<tr><td colspan="4">No template injections yet</td></tr>'}</tbody></table></div>
"""
    return render_console_page(title="Improver", body_html=body, active_nav="improver")


def render_feedback_page(
    events: list[FeedbackEvent],
    *,
    edit_feedback_enabled: bool = False,
) -> str:
    """Render recent edit feedback events."""
    rows = []
    for event in events[:100]:
        rows.append(
            f"<tr><td>{escape(event.timestamp.isoformat())}</td>"
            f"<td>{escape(event.event_type)}</td>"
            f"<td>{event.edit_distance if event.edit_distance is not None else '—'}</td>"
            f"<td><pre>{escape((event.original_text or '')[:120])}</pre></td>"
            f"<td><pre>{escape((event.submitted_text or '')[:120])}</pre></td></tr>"
        )

    empty_banner = ""
    if not edit_feedback_enabled:
        empty_banner = render_empty_state(
            title="Edit feedback is off",
            body=(
                "Enable Parameters <code>edit_feedback</code> and set "
                "<code>YLANG_CAPTURE_EDIT_FEEDBACK=1</code> in the service/hook "
                "env, then restart hooks/session. Captures appear when users "
                "edit an improved prompt before submit."
            ),
            primary_href="/console/settings",
            primary_label="Enable in Settings",
        )
    elif not events:
        empty_banner = render_empty_state(
            title="No feedback events yet",
            body=(
                "Ensure <code>YLANG_CAPTURE_EDIT_FEEDBACK=1</code> is set in the "
                "service/hook env and restart hooks/session. Events appear after "
                "Cursor hook traffic where the user edits an improved prompt "
                "before submit."
            ),
        )

    body = f"""
<p class="subtitle">User edits captured when Parameters <code>edit_feedback</code>
and hook env <code>YLANG_CAPTURE_EDIT_FEEDBACK=1</code> are both on.</p>
{empty_banner}
<table><thead><tr><th>Time</th><th>Type</th><th>Distance</th><th>Original</th><th>Submitted</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="5">No feedback events yet</td></tr>'}</tbody></table>
"""
    return render_console_page(title="Feedback", body_html=body, active_nav="feedback")


def render_data_page(
    *,
    stats: dict[str, int],
    preview: TablePreview | None,
    table_name: str,
    offset: int,
    activity_filter: str | None = None,
    search_query: str | None = None,
    message: str | None = None,
) -> str:
    """Render SQLite data browser with domain shortcuts, search, deep links, and mutators."""
    flash = f'<div class="flash ok">{escape(message)}</div>' if message else ""
    stat_cards = "".join(
        f'<div class="card"><div class="label">{escape(name)}</div>'
        f'<div class="value">{count}</div></div>'
        for name, count in sorted(stats.items())
    )
    domain_links = "".join(
        f'<a class="btn{" active" if tbl == table_name else " btn-secondary"}" '
        f'href="/console/data?table={escape(tbl)}">{escape(label)}</a> '
        for label, tbl in list_data_domains()
    )
    table_links = "".join(
        f'<a class="btn{" btn-secondary" if name != table_name else ""}" '
        f'href="/console/data?table={escape(name)}">{escape(name)}</a> '
        for name in stats
    )

    def cell_link(col: str, value: object) -> str | None:
        if value is None:
            return None
        text = str(value)
        if col == "template_id" or col.endswith("_template_id"):
            return f'/console/templates?q={escape(text)}'
        if col == "id" and table_name == "facts":
            return f"/console/facts?id={escape(text)}"
        if col == "fact_id":
            return f"/console/facts?id={escape(text)}"
        return None

    preview_html = "<p>Select a table to preview rows.</p>"
    if preview is not None:
        header = "".join(f"<th>{escape(col)}</th>" for col in preview.columns)
        body_rows = []
        activity_idx = preview.columns.index("activity") if "activity" in preview.columns else None
        id_idx = preview.columns.index("id") if "id" in preview.columns else None
        for row in preview.rows:
            cells = []
            row_id = row[id_idx] if id_idx is not None else None
            for index, value in enumerate(row):
                col = preview.columns[index]
                text = escape(str(value)[:200])
                href = cell_link(col, value)
                if href:
                    text = f'<a href="{href}">{text}</a>'
                elif (
                    table_name == "usage"
                    and activity_idx is not None
                    and index == activity_idx
                    and value
                ):
                    text = (
                        f'<a href="/console/data?table=usage&amp;activity={escape(str(value))}">'
                        f"{text}</a>"
                    )
                cells.append(f"<td><pre>{text}</pre></td>")
            delete_cell = ""
            if table_name == "usage" and row_id is not None:
                delete_cell = f"""<td>
<form method="post" action="/console/data/delete-usage" class="inline-form"
      onsubmit="return confirm('Delete usage row {escape(str(row_id))}?')">
  <input type="hidden" name="row_id" value="{escape(str(row_id))}">
  <input type="hidden" name="table" value="{escape(table_name)}">
  <input type="hidden" name="offset" value="{offset}">
  <button type="submit" class="btn-secondary">Delete</button>
</form></td>"""
            body_rows.append(f"<tr>{''.join(cells)}{delete_cell}</tr>")
        prev_link = ""
        next_link = ""
        search_qs = f"&q={escape(search_query)}" if search_query else ""
        activity_qs = f"&activity={escape(activity_filter)}" if activity_filter else ""
        if offset > 0:
            prev_offset = max(0, offset - len(preview.rows) if preview.rows else 50)
            prev_link = (
                f'<a class="btn btn-secondary" href="/console/data?table={escape(table_name)}'
                f"&offset={prev_offset}{activity_qs}{search_qs}\">Previous</a> "
            )
        if offset + len(preview.rows) < preview.total_count:
            next_link = (
                f'<a class="btn btn-secondary" href="/console/data?table={escape(table_name)}'
                f"&offset={offset + len(preview.rows)}{activity_qs}{search_qs}\">Next</a>"
            )
        filter_note = ""
        if activity_filter:
            filter_note = (
                f'<p class="subtitle">Filtered by activity '
                f'<code>{escape(activity_filter)}</code> — '
                f'<a href="/console/usage">open usage dashboard</a></p>'
            )
        if search_query:
            filter_note += (
                f'<p class="subtitle">Search: <code>{escape(search_query)}</code></p>'
            )
        delete_header = "<th>Actions</th>" if table_name == "usage" else ""
        preview_html = f"""
{filter_note}
<form method="get" action="/console/data" class="form-row" style="margin-bottom:1rem">
  <input type="hidden" name="table" value="{escape(table_name)}">
  <label for="q">Search rows</label>
  <input type="search" id="q" name="q" value="{escape(search_query or '')}" placeholder="Filter text columns…">
  <button type="submit" style="margin-left:0.5rem">Filter</button>
</form>
<p class="subtitle">{preview.total_count} rows total — showing {offset + 1}–{offset + len(preview.rows)}</p>
<div style="margin-bottom:1rem">{prev_link}{next_link}</div>
<table><thead><tr>{header}{delete_header}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>
"""

    mutators = ""
    if table_name == "improver_cache":
        mutators = """
<div class="panel"><h3>Safe mutators</h3>
<form method="post" action="/console/data/clear-cache"
      onsubmit="return confirm('Clear in-memory and SQLite improver cache?')">
  <input type="hidden" name="table" value="improver_cache">
  <input type="hidden" name="confirm" value="CLEAR">
  <button type="submit" class="btn-secondary">Clear improver cache</button>
</form></div>"""
    elif table_name == "usage":
        mutators = """
<div class="panel"><h3>Safe mutators</h3>
<form method="post" action="/console/data/purge-usage"
      onsubmit="return confirm('Delete usage rows older than N days?')">
  <input type="hidden" name="table" value="usage">
  <div class="form-row"><label>Delete rows older than (days)</label>
  <input type="number" name="days" value="90" min="1" max="3650" required></div>
  <button type="submit" class="btn-secondary">Purge old usage</button>
</form></div>"""

    body = f"""
{flash}
<div class="cards">{stat_cards}</div>
<div class="panel"><h2>Domain views</h2>
<p class="subtitle">Jump to common operator tables. Raw browse below includes all SQLite tables.</p>
<p class="domain-nav">{domain_links}</p></div>
<div class="panel"><h2>All tables</h2><p>{table_links}</p></div>
<div class="panel"><h2>{escape(table_name)}</h2>{preview_html}{mutators}</div>
"""
    return render_console_page(title="Data", body_html=body, active_nav="data")


def render_advisor_page(
    *,
    reply: str | None = None,
    question: str = "",
    setting_proposals: list[PendingProposal] | None = None,
) -> str:
    """Render AI config advisor chat form with optional applyable setting proposals."""
    answer = ""
    if reply:
        answer = f'<div class="panel"><h2>Advisor reply</h2><pre>{escape(reply)}</pre></div>'
    apply_blocks: list[str] = []
    for item in setting_proposals or []:
        apply_blocks.append(
            f'<div class="suggestion {escape(item.priority)}">'
            f"<strong>{escape(item.title)}</strong> "
            f'<span class="badge">{escape(item.kind)}</span>'
            f"<p>{escape(item.description)}</p>"
            f'<p class="subtitle">Will set '
            f"<code>{escape(item.setting_key or '')}={escape(item.setting_value or '')}</code></p>"
            f'<form method="post" action="/console/proposals/apply" style="margin-top:0.5rem">'
            f'<input type="hidden" name="proposal_id" value="{escape(item.proposal_id)}">'
            f'<button type="submit">Apply</button></form></div>'
        )
    apply_panel = ""
    if apply_blocks:
        apply_panel = (
            '<div class="panel"><h2>Applyable setting changes</h2>'
            "<p class=\"subtitle\">Propose-only until you click <strong>Apply</strong> "
            "(same governed path as Proposals).</p>"
            f"{''.join(apply_blocks)}</div>"
        )
    body = f"""
<p class="subtitle">Ask about improver performance, settings, or templates. Uses live analytics + one reason-activity LLM call (no hardcoded model).</p>
<form method="post" action="/console/advisor" class="panel">
  <div class="form-row"><label for="question">Question</label>
  <textarea id="question" name="question" rows="4" required>{escape(question)}</textarea></div>
  <button type="submit">Ask advisor</button>
</form>
{answer}
{apply_panel}
"""
    return render_console_page(title="Advisor", body_html=body, active_nav="advisor")


def render_setup_page(*, checks: list[tuple[str, bool, str]]) -> str:
    """Render browser onboarding / health checklist."""
    rows = []
    for label, ok, detail in checks:
        badge = '<span class="badge ok">ok</span>' if ok else '<span class="badge err">issue</span>'
        rows.append(
            f"<tr><td>{escape(label)}</td><td>{badge}</td><td>{escape(detail)}</td></tr>"
        )
    setup_complete = all(ok for _, ok, _ in checks)
    done_banner = ""
    if setup_complete:
        done_banner = (
            '<div class="flash ok">All checklist items look good. '
            "Setup stays under <strong>Advanced</strong> in the nav when complete.</div>"
        )
    body = f"""
{done_banner}
<p class="subtitle">Quick environment checklist. CLI equivalent: <code>ylang init</code> / <code>ylang doctor</code>.</p>
<table><thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<div class="panel">
  <h2>Next steps</h2>
  <ol>
    <li>Configure provider API keys in your environment.</li>
    <li>Point Cursor MCP to <code>http://127.0.0.1:8787/mcp</code> with Bearer auth.</li>
    <li>Enable hooks via <code>ylang init</code> or copy from <code>deploy/cursor</code>.</li>
    <li>Tune hot-reload settings under Settings.</li>
  <li>View <a href="/console/health">provider health and hook logs</a>.</li>
  </ol>
</div>
"""
    return render_console_page(title="Setup", body_html=body, active_nav="setup")


def render_health_page(
    providers: list[ProviderStatus],
    hook_lines: list[str],
) -> str:
    """Render provider health and hook log tail."""
    provider_rows = "".join(
        f"<tr><td>{escape(item.name)}</td>"
        f"<td>{'<span class=\"badge ok\">ok</span>' if item.ok else '<span class=\"badge err\">fail</span>'}</td>"
        f"<td>{escape(item.detail)}</td></tr>"
        for item in providers
    )
    hook_text = escape("\n".join(hook_lines))
    body = f"""
<div class="panel"><h2>Provider health</h2>
<table><thead><tr><th>Name</th><th>Status</th><th>Detail</th></tr></thead>
<tbody>{provider_rows}</tbody></table></div>
<div class="panel"><h2>Hook log (tail)</h2>
<pre>{hook_text}</pre>
<p class="subtitle">Log path: ~/.cursor/hooks/ylang-improve-prompt.log</p></div>
"""
    return render_console_page(title="Health", body_html=body, active_nav="setup")
