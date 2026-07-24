"""Console page renderers."""

from __future__ import annotations

from html import escape

from ylang.console.fact_list import FactListPage, build_fact_list_query, per_page_options
from ylang.console.icons import icon_delete, icon_edit
from ylang.console.layout import render_console_page, render_empty_state
from ylang.core.memory import Fact

def _render_facts_list_styles() -> str:
    """CSS for facts browser table actions and pagination."""
    return """
<link rel="stylesheet" href="/console/static/page-facts-render_facts_list_styles-1.css">
"""


def _render_facts_pagination(list_page: FactListPage) -> str:
    """Render pagination controls for the facts list."""
    from ylang.console.fact_list import FactListFilters

    filters = list_page.filters
    total_pages = list_page.total_pages

    def page_link(page_num: int, label: str, *, current: bool = False) -> str:
        if current:
            return f'<span class="current">{escape(label)}</span>'
        qs = build_fact_list_query(
            FactListFilters(
                query=filters.query,
                scope=filters.scope,
                workspace=filters.workspace,
                sort=filters.sort,
                order=filters.order,
                page=page_num,
                per_page=filters.per_page,
            )
        )
        href = f"/console/facts?{qs}" if qs else "/console/facts"
        return f'<a href="{href}">{escape(label)}</a>'

    links: list[str] = []
    if list_page.page > 1:
        links.append(page_link(list_page.page - 1, "Previous"))
    window_start = max(1, list_page.page - 2)
    window_end = min(total_pages, list_page.page + 2)
    if window_start > 1:
        links.append(page_link(1, "1"))
        if window_start > 2:
            links.append("<span>…</span>")
    for page_num in range(window_start, window_end + 1):
        links.append(
            page_link(page_num, str(page_num), current=page_num == list_page.page)
        )
    if window_end < total_pages:
        if window_end < total_pages - 1:
            links.append("<span>…</span>")
        links.append(page_link(total_pages, str(total_pages)))
    if list_page.page < total_pages:
        links.append(page_link(list_page.page + 1, "Next"))

    if list_page.total > 0:
        range_text = (
            f"Showing {list_page.start_index}–{list_page.end_index} "
            f"of {list_page.total} facts"
        )
    else:
        range_text = "No facts match the current filters"

    return f"""
<div class="pagination">
  <span>{range_text}</span>
  <div class="pagination-links">{"".join(links)}</div>
</div>"""


def _render_fact_suggest_panel(*, auto_run: bool = False) -> str:
    """Render AI fact-suggestion panel (propose-only until Save selected)."""
    auto_flag = "true" if auto_run else "false"
    return f"""
<div class="panel" id="suggest-facts">
  <h2>Suggest facts with AI</h2>
  <p class="subtitle">Propose preferences from recent improver usage and rejection
  patterns. Nothing is saved until you click Save selected.</p>
  <button type="button" id="suggestFactsBtnPanel">Suggest facts with AI</button>
  <p id="suggestFactsStatus" class="subtitle" style="margin-top:0.75rem"></p>
  <form method="post" action="/console/facts/accept-suggestions" id="acceptSuggestionsForm"
        style="display:none;margin-top:1rem">
    <div id="suggestFactsList"></div>
    <button type="submit" style="margin-top:1rem">Save selected</button>
  </form>
</div>
<script>
(function () {{
  const statusEl = document.getElementById("suggestFactsStatus");
  const listEl = document.getElementById("suggestFactsList");
  const formEl = document.getElementById("acceptSuggestionsForm");
  const autoRun = {auto_flag};

  async function runSuggest() {{
    if (!statusEl || !listEl || !formEl) return;
    statusEl.textContent = "Running…";
    formEl.style.display = "none";
    listEl.innerHTML = "";
    try {{
      const response = await fetch("/console/api/suggest-facts", {{ method: "POST" }});
      const payload = await response.json();
      if (!payload.ok) {{
        statusEl.textContent = payload.error || "Could not suggest facts.";
        return;
      }}
      const suggestions = payload.suggestions || [];
      if (!suggestions.length) {{
        statusEl.textContent = "No suggestions returned.";
        return;
      }}
      statusEl.textContent = suggestions.length + " candidate(s) — review and save selected.";
      suggestions.forEach((item, index) => {{
        const wrapper = document.createElement("div");
        wrapper.className = "suggestion medium";
        wrapper.style.marginBottom = "0.75rem";
        const id = "suggest_" + index;
        const encoded = JSON.stringify({{
          fact: item.fact || "",
          scope: item.scope || "private",
          workspace: item.workspace || ""
        }});
        wrapper.innerHTML =
          '<label style="display:flex;gap:0.75rem;align-items:flex-start;cursor:pointer">' +
          '<input type="checkbox" name="selected" value="" checked id="' + id + '">' +
          '<span><strong></strong> ' +
          '<span class="badge"></span>' +
          '<p class="subtitle" style="margin:0.35rem 0 0"></p></span></label>';
        const checkbox = wrapper.querySelector("input");
        checkbox.value = encoded;
        wrapper.querySelector("strong").textContent = item.fact || "";
        wrapper.querySelector(".badge").textContent = item.scope || "private";
        const rationale = wrapper.querySelector(".subtitle");
        rationale.textContent = item.rationale || "";
        listEl.appendChild(wrapper);
      }});
      formEl.style.display = "block";
    }} catch (err) {{
      statusEl.textContent = "Request failed.";
    }} finally {{
      window.ylangLoadingDone?.();
    }}
  }}

  document.getElementById("suggestFactsBtn")?.addEventListener("click", runSuggest);
  document.getElementById("suggestFactsBtnPanel")?.addEventListener("click", runSuggest);
  if (autoRun) {{
    runSuggest();
  }}
}})();
</script>
"""


def render_facts_page(
    list_page: FactListPage,
    *,
    selected: Fact | None = None,
    message: str | None = None,
    error: str | None = None,
    auto_suggest: bool = False,
) -> str:
    """Render facts browser with search, filters, pagination, and edit panel."""
    filters = list_page.filters
    flash = ""
    if message:
        flash += f'<div class="flash ok">{escape(message)}</div>'
    if error:
        flash += f'<div class="flash err">{escape(error)}</div>'
    list_qs = build_fact_list_query(filters)
    show_suggest = auto_suggest or (
        list_page.total == 0
        and not filters.query
        and filters.scope is None
        and not filters.workspace
    )

    def row_href(fact_id: int) -> str:
        qs = build_fact_list_query(filters, fact_id=fact_id)
        return f"/console/facts?{qs}#fact-edit"

    table_rows: list[str] = []
    for item in list_page.rows:
        is_selected = selected is not None and selected.id == item.id
        row_class = "selected" if is_selected else ""
        edit_href = row_href(item.id)
        created = item.created_at.isoformat()
        table_rows.append(
            f'<tr class="{row_class}">'
            f'<td class="col-id"><a href="{edit_href}">{item.id}</a></td>'
            f"<td>{escape(item.scope)}</td>"
            f"<td>{escape(item.workspace) or '—'}</td>"
            f'<td><a href="{edit_href}">{escape(item.fact)}</a></td>'
            f"<td>{escape(created)}</td>"
            f'<td class="col-actions">'
            f'<a href="{edit_href}" class="icon-btn" title="Edit">{icon_edit()}</a>'
            f"""
<form method="post" action="/console/facts/delete" class="inline-form"
      onsubmit="return confirm('Delete fact #{item.id}?')">
  <input type="hidden" name="fact_id" value="{item.id}">
  <input type="hidden" name="return_query" value="{escape(list_qs)}">
  <button type="submit" class="icon-btn danger" title="Delete">{icon_delete()}</button>
</form>"""
            f"</td></tr>"
        )

    scope_options = [
        ("", "All scopes"),
        ("private", "private"),
        ("shareable", "shareable"),
    ]
    scope_options_html = ""
    for value, label in scope_options:
        selected_opt = (filters.scope == value) if value else filters.scope is None
        scope_options_html += (
            f'<option value="{value}"{" selected" if selected_opt else ""}>'
            f"{escape(label)}</option>"
        )

    sort_options = [
        ("created", "Created"),
        ("id", "ID"),
        ("fact", "Fact text"),
        ("scope", "Scope"),
        ("workspace", "Workspace"),
    ]
    sort_options_html = "".join(
        f'<option value="{key}"{" selected" if filters.sort == key else ""}>'
        f"{escape(label)}</option>"
        for key, label in sort_options
    )
    order_selected_asc = " selected" if filters.order == "asc" else ""
    order_selected_desc = " selected" if filters.order == "desc" else ""
    per_page_options_html = "".join(
        f'<option value="{size}"{" selected" if size == filters.per_page else ""}>'
        f"{size}</option>"
        for size in per_page_options()
    )

    detail = ""
    if selected is not None:
        private_sel = " selected" if selected.scope == "private" else ""
        shareable_sel = " selected" if selected.scope == "shareable" else ""
        detail = f"""
<div class="panel" id="fact-edit">
  <h2>{icon_edit()} Edit fact #{selected.id}</h2>
  <p class="subtitle">Facts are injected into improver context when improve_prompt runs.</p>
  <form method="post" action="/console/facts/update">
    <input type="hidden" name="fact_id" value="{selected.id}">
    <input type="hidden" name="return_query" value="{escape(list_qs)}">
    <div class="form-row"><label>Fact</label>
      <textarea name="fact" rows="3" required>{escape(selected.fact)}</textarea></div>
    <div class="form-row"><label>Scope</label>
      <select name="scope">
        <option value="private"{private_sel}>private</option>
        <option value="shareable"{shareable_sel}>shareable</option>
      </select></div>
    <div class="form-row"><label>Workspace</label>
      <input name="workspace" value="{escape(selected.workspace)}"
             placeholder="optional project tag"></div>
    <button type="submit">Save changes</button>
  </form>
  <form method="post" action="/console/facts/delete" style="margin-top:1rem"
        onsubmit="return confirm('Delete fact #{selected.id}?')">
    <input type="hidden" name="fact_id" value="{selected.id}">
    <input type="hidden" name="return_query" value="{escape(list_qs)}">
    <button type="submit" class="btn-secondary">{icon_delete()} Delete fact</button>
  </form>
</div>
"""

    empty_state = ""
    if list_page.total == 0 and not filters.query and filters.scope is None and not filters.workspace:
        empty_state = render_empty_state(
            title="No facts yet",
            body=(
                "Facts are short preferences the improver includes as context "
                "(stack choices, style rules, project conventions). "
                "Add one below, load starter examples, or suggest facts from "
                "recent improver usage."
            ),
            secondary_html=(
                '<button type="button" id="suggestFactsBtn">Suggest facts with AI</button>'
                '<form method="post" action="/console/facts/seed-samples" style="display:inline">'
                "<button type=\"submit\">Add sample facts</button></form>"
            ),
        )
    elif list_page.total == 0:
        empty_state = render_empty_state(
            title="No matching facts",
            body="Try clearing filters or search terms.",
            primary_href="/console/facts",
            primary_label="Clear filters",
        )

    suggest_panel = _render_fact_suggest_panel(auto_run=auto_suggest) if show_suggest else ""

    body = f"""
{_render_facts_list_styles()}
{flash}
{detail}
{suggest_panel}
{empty_state}
<form method="post" action="/console/facts" class="panel" id="createFactForm">
  <h2>Add fact</h2>
  <p class="usage-hint">Saved facts appear in improve_prompt context (newest first, capped per mode).</p>
  <input type="hidden" name="return_query" value="{escape(list_qs)}">
  <div class="form-row"><label for="new_fact">Fact</label>
    <textarea id="new_fact" name="fact" rows="2" required
      placeholder="e.g. Prefer Vitest over Jest for unit tests"></textarea></div>
  <div class="form-row"><label for="new_scope">Scope</label>
    <select id="new_scope" name="scope">
      <option value="private">private</option>
      <option value="shareable">shareable</option>
    </select></div>
  <div class="form-row"><label for="new_workspace">Workspace</label>
    <input id="new_workspace" name="workspace" placeholder="optional, e.g. ylang"></div>
  <button type="submit">Remember</button>
</form>
<form method="get" action="/console/facts" class="panel">
  <h2>Browse facts</h2>
  <div class="facts-toolbar">
    <div class="form-row">
      <label for="q">Search</label>
      <input type="search" id="q" name="q" value="{escape(filters.query)}"
             placeholder="Keyword search…">
    </div>
    <div class="form-row">
      <label for="scope">Scope</label>
      <select id="scope" name="scope">{scope_options_html}</select>
    </div>
    <div class="form-row">
      <label for="workspace">Workspace</label>
      <input id="workspace" name="workspace" value="{escape(filters.workspace)}"
             placeholder="Filter workspace…">
    </div>
    <div class="form-row">
      <label for="sort">Sort by</label>
      <select id="sort" name="sort">{sort_options_html}</select>
    </div>
    <div class="form-row">
      <label for="order">Order</label>
      <select id="order" name="order">
        <option value="desc"{order_selected_desc}>Newest first</option>
        <option value="asc"{order_selected_asc}>Oldest first</option>
      </select>
    </div>
    <div class="form-row">
      <label for="per_page">Per page</label>
      <select id="per_page" name="per_page">{per_page_options_html}</select>
    </div>
    <button type="submit">Apply</button>
  </div>
</form>
<div class="panel facts-table-wrap">
  <table class="facts-table">
    <thead><tr>
      <th class="col-id">ID</th><th>Scope</th><th>Workspace</th>
      <th>Fact</th><th>Created</th><th class="col-actions">Actions</th>
    </tr></thead>
    <tbody>{"".join(table_rows) or '<tr><td colspan="6">No facts</td></tr>'}</tbody>
  </table>
  {_render_facts_pagination(list_page)}
</div>
"""
    return render_console_page(
        title="Facts",
        body_html=body,
        active_nav="facts",
        subtitle="Local memory for the improver — preferences injected into prompt context",
    )

