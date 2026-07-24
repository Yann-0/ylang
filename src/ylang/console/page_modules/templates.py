"""Console page renderers."""

from __future__ import annotations

import json

from html import escape

from ylang.console.icons import icon_delete, icon_edit
from ylang.console.layout import render_console_page, render_empty_state
from ylang.console.template_list import TemplateListPage, build_template_list_query
from ylang.console.template_params import render_param_editor
from ylang.library.types import TemplateParam

def _render_template_studio_script(form_id: str) -> str:
    """Shared JS for AI improve and live preview on template forms."""
    return f"""
<script>
(() => {{
  const form = document.getElementById({json.dumps(form_id)});
  if (!form) return;
  const PLACEHOLDER = /\\{{\\{{([a-zA-Z_][a-zA-Z0-9_]*)\\}}\\}}|(?<!\\{{)\\{{([a-zA-Z_][a-zA-Z0-9_]*)\\}}(?!\\}})/g;
  function detectNames(body) {{
    const seen = new Set();
    const names = [];
    for (const match of body.matchAll(PLACEHOLDER)) {{
      const name = match[1] || match[2];
      if (name && !seen.has(name)) {{ seen.add(name); names.push(name); }}
    }}
    return names;
  }}
  function collectParams() {{
    const names = [...form.querySelectorAll('input[name="param_name"]')].map((el) => el.value);
    const descriptions = [...form.querySelectorAll('input[name="param_description"]')].map((el) => el.value);
    const defaults = [...form.querySelectorAll('input[name="param_default"]')].map((el) => el.value);
    const params = [];
    for (let i = 0; i < names.length; i++) {{
      if (!names[i]?.trim()) continue;
      params.push({{
        name: names[i].trim(),
        description: (descriptions[i] || "").trim(),
        default: (defaults[i] || "").trim() || null,
      }});
    }}
    return params;
  }}
  function setParams(params) {{
    const rows = form.querySelectorAll(".param-row");
    rows.forEach((row, index) => {{
      if (index > 0) row.remove();
    }});
    const container = form.querySelector(".param-rows");
    const first = form.querySelector(".param-row");
    const applyRow = (row, param) => {{
      row.querySelector('input[name="param_name"]').value = param.name || "";
      row.querySelector('input[name="param_description"]').value = param.description || "";
      row.querySelector('input[name="param_default"]').value = param.default || "";
    }};
    if (!params.length) return;
    applyRow(first, params[0]);
    for (let i = 1; i < params.length; i++) {{
      const clone = first.cloneNode(true);
      applyRow(clone, params[i]);
      container.appendChild(clone);
    }}
  }}
  function ensurePreviewPanel() {{
    let panel = form.querySelector(".template-preview-panel");
    if (panel) return panel;
    panel = document.createElement("div");
    panel.className = "template-preview-panel";
    panel.innerHTML = `
      <p class="subtitle">Preview parameter values (edit and re-render)</p>
      <div class="template-preview-values"></div>
      <button type="button" class="btn-secondary template-preview-update">Update preview</button>
      <pre class="template-preview-output" style="margin-top:1rem"></pre>`;
    form.appendChild(panel);
    panel.querySelector(".template-preview-update")?.addEventListener("click", () => runPreview());
    return panel;
  }}
  function collectPreviewValues(panel) {{
    const values = {{}};
    panel.querySelectorAll(".preview-param-row").forEach((row) => {{
      const name = row.dataset.name;
      const input = row.querySelector("input");
      if (name) values[name] = input?.value || "";
    }});
    return values;
  }}
  function syncPreviewInputs(panel) {{
    const body = form.querySelector('textarea[name="body"]')?.value || "";
    const declared = collectParams();
    const byName = Object.fromEntries(declared.map((p) => [p.name, p]));
    const names = [...new Set([...declared.map((p) => p.name), ...detectNames(body)])];
    const valuesRoot = panel.querySelector(".template-preview-values");
    const previous = collectPreviewValues(panel);
    valuesRoot.innerHTML = "";
    if (!names.length) {{
      valuesRoot.innerHTML = '<p class="usage-hint">No parameters to fill.</p>';
      return;
    }}
    names.forEach((name) => {{
      const row = document.createElement("div");
      row.className = "preview-param-row form-row";
      row.dataset.name = name;
      const label = document.createElement("label");
      label.textContent = name;
      const input = document.createElement("input");
      input.type = "text";
      const fallback = byName[name]?.default || "";
      input.value = previous[name] !== undefined ? previous[name] : fallback;
      input.placeholder = "value for preview";
      row.appendChild(label);
      row.appendChild(input);
      valuesRoot.appendChild(row);
    }});
  }}
  async function runPreview() {{
    const panel = ensurePreviewPanel();
    syncPreviewInputs(panel);
    const preview = panel.querySelector(".template-preview-output");
    if (preview) preview.textContent = "Rendering…";
    try {{
      const response = await fetch("/console/api/render-template", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{
          body: form.querySelector('textarea[name="body"]')?.value || "",
          param_values: collectPreviewValues(panel),
        }}),
      }});
      const result = await response.json();
      if (preview) preview.textContent = result.ok ? result.rendered : (result.error || "Render failed");
    }} finally {{
      window.ylangLoadingDone?.();
    }}
  }}
  form.querySelector(".template-improve-btn")?.addEventListener("click", async () => {{
    const status = form.querySelector(".template-studio-status");
    if (status) status.textContent = "Improving with AI…";
    const payload = {{
      name: form.querySelector('input[name="name"]')?.value || "",
      body: form.querySelector('textarea[name="body"]')?.value || "",
      params: collectParams(),
      instruction: form.querySelector('input[name="ai_instruction"]')?.value || "",
    }};
    try {{
      const response = await fetch("/console/api/improve-template", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify(payload),
      }});
      const result = await response.json();
      if (!result.ok) {{
        if (status) status.textContent = result.error || "Improve failed";
        return;
      }}
      if (result.name) form.querySelector('input[name="name"]').value = result.name;
      form.querySelector('textarea[name="body"]').value = result.body;
      if (result.params) setParams(result.params);
      if (status) status.textContent = result.rationale || "Template improved.";
    }} finally {{
      window.ylangLoadingDone?.();
    }}
  }});
  form.querySelector(".template-preview-btn")?.addEventListener("click", () => runPreview());
  form.querySelector(".template-detect-btn")?.addEventListener("click", () => {{
    window.ylangLoadingDone?.();
  }});
}})();
</script>
"""


def _render_template_list_styles() -> str:
    """CSS for template browser table actions and pagination."""
    return """
<link rel="stylesheet" href="/console/static/page-templates-render_template_list_styles-1.css">
"""


def _render_template_pagination(list_page: TemplateListPage) -> str:
    """Render Google-style pagination controls."""
    from ylang.console.template_list import TemplateListFilters

    filters = list_page.filters
    total_pages = list_page.total_pages

    def page_link(page_num: int, label: str, *, current: bool = False) -> str:
        if current:
            return f'<span class="current">{escape(label)}</span>'
        qs = build_template_list_query(
            TemplateListFilters(
                query=filters.query,
                source=filters.source,
                visibility=filters.visibility,
                unused_only=filters.unused_only,
                toxic_only=filters.toxic_only,
                sort=filters.sort,
                order=filters.order,
                page=page_num,
                per_page=filters.per_page,
            )
        )
        href = f"/console/templates?{qs}" if qs else "/console/templates"
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
            f"of {list_page.total} templates"
        )
    else:
        range_text = "No templates match the current filters"

    return f"""
<div class="pagination">
  <span>{range_text}</span>
  <div class="pagination-links">{"".join(links)}</div>
</div>"""


def render_templates_page(
    list_page: TemplateListPage,
    *,
    usage_counts: dict[str, int] | None = None,
    bulk_archive_eligible: int = 0,
    toxic_archive_eligible: int = 0,
    toxic_ids: frozenset[str] | set[str] | None = None,
    selected_id: str | None = None,
    selected_body: str | None = None,
    selected_name: str | None = None,
    selected_source: str | None = None,
    selected_params: list[TemplateParam] | None = None,
    version_rows: list[tuple[int, str, str]] | None = None,
    message: str | None = None,
) -> str:
    """Render template browser with search, filters, pagination, edit, and usage counts."""
    from ylang.console.template_list import per_page_options

    all_usage = usage_counts or {}
    toxic_set = toxic_ids or frozenset()
    filters = list_page.filters
    flash = f'<div class="flash ok">{escape(message)}</div>' if message else ""
    list_qs = build_template_list_query(filters)

    def row_href(template_id: str) -> str:
        qs = build_template_list_query(filters, template_id=template_id)
        return f"/console/templates?{qs}#template-edit"

    table_rows: list[str] = []
    for row in list_page.rows:
        item = row.summary
        is_selected = selected_id == item.template_id
        param_hint = ", ".join(item.param_names) if item.param_names else "—"
        row_class = "selected" if is_selected else ""
        edit_href = row_href(item.template_id)
        delete_btn = ""
        archive_btn = ""
        if item.source != "seed":
            if item.visibility == "archived":
                archive_btn = f"""
<form method="post" action="/console/templates/unarchive" class="inline-form">
  <input type="hidden" name="template_id" value="{escape(item.template_id)}">
  <input type="hidden" name="return_query" value="{escape(list_qs)}">
  <button type="submit" class="icon-btn" title="Unarchive">↩</button>
</form>"""
            else:
                archive_label = (
                    "Quarantine"
                    if item.template_id in toxic_set
                    else "Archive"
                )
                archive_btn = f"""
<form method="post" action="/console/templates/archive" class="inline-form"
      onsubmit="return confirm('{escape(archive_label)} template {escape(item.template_id)}?')">
  <input type="hidden" name="template_id" value="{escape(item.template_id)}">
  <input type="hidden" name="return_query" value="{escape(list_qs)}">
  <button type="submit" class="icon-btn" title="{escape(archive_label)}">A</button>
</form>"""
                delete_btn = f"""
<form method="post" action="/console/templates/delete" class="inline-form"
      onsubmit="return confirm('Delete template {escape(item.template_id)}?')">
  <input type="hidden" name="template_id" value="{escape(item.template_id)}">
  <input type="hidden" name="return_query" value="{escape(list_qs)}">
  <button type="submit" class="icon-btn danger" title="Delete">{icon_delete()}</button>
</form>"""
        table_rows.append(
            f'<tr class="{row_class}">'
            f'<td><a href="{edit_href}">{escape(item.template_id)}</a></td>'
            f"<td><a href=\"{edit_href}\">{escape(item.name)}</a></td>"
            f"<td>{escape(item.source)}</td>"
            f"<td>{escape(item.visibility)}</td>"
            f"<td>{item.latest_version}</td>"
            f'<td class="col-usage">{row.usage_count}</td>'
            f"<td>{escape(param_hint)}</td>"
            f'<td class="col-actions">'
            f'<a href="{edit_href}" class="icon-btn" title="Edit">{icon_edit()}</a>'
            f"{archive_btn}"
            f"{delete_btn}"
            f"</td></tr>"
        )

    per_page_options_html = "".join(
        f'<option value="{size}"{" selected" if size == filters.per_page else ""}>'
        f"{size}</option>"
        for size in per_page_options()
    )
    source_options = [
        ("", "All sources"),
        ("seed", "seed"),
        ("user", "user"),
        ("learned", "learned"),
    ]
    source_options_html = ""
    for value, label in source_options:
        selected = (filters.source == value) if value else filters.source is None
        source_options_html += (
            f'<option value="{value}"{" selected" if selected else ""}>'
            f"{escape(label)}</option>"
        )

    visibility_options = [
        ("", "Active (not archived)"),
        ("public", "public"),
        ("private", "private"),
        ("archived", "archived"),
        ("all", "all (incl. archived)"),
    ]
    visibility_options_html = ""
    for value, label in visibility_options:
        if value:
            selected = filters.visibility == value
        else:
            selected = filters.visibility is None
        visibility_options_html += (
            f'<option value="{value}"{" selected" if selected else ""}>'
            f"{escape(label)}</option>"
        )

    sort_options = [
        ("name", "Name"),
        ("id", "ID"),
        ("source", "Source"),
        ("version", "Version"),
        ("usage", "Usage"),
        ("updated", "Updated"),
    ]
    sort_options_html = "".join(
        f'<option value="{key}"{" selected" if filters.sort == key else ""}>'
        f"{escape(label)}</option>"
        for key, label in sort_options
    )
    order_selected_asc = " selected" if filters.order == "asc" else ""
    order_selected_desc = " selected" if filters.order == "desc" else ""

    detail = ""
    if selected_id and selected_body is not None:
        delete_form = ""
        if selected_source != "seed":
            delete_form = f"""
<form method="post" action="/console/templates/delete" style="margin-top:1rem"
      onsubmit="return confirm('Delete template {escape(selected_id)}?')">
  <input type="hidden" name="template_id" value="{escape(selected_id)}">
  <input type="hidden" name="return_query" value="{escape(list_qs)}">
  <button type="submit" class="btn-secondary">{icon_delete()} Delete template</button>
</form>"""
        version_table = ""
        if version_rows:
            vrows = "".join(
                f"<tr><td>{version}</td><td>{escape(source)}</td><td>{escape(created)}</td></tr>"
                for version, source, created in version_rows
            )
            version_table = f"""
<div class="panel"><h3>Version history</h3>
<table><thead><tr><th>Version</th><th>Source</th><th>Created</th></tr></thead>
<tbody>{vrows}</tbody></table></div>"""
        selected_usage = all_usage.get(selected_id, 0)
        detail = f"""
<div class="panel" id="template-edit">
  <h2>{icon_edit()} Edit {escape(selected_id)}</h2>
  <p class="subtitle">Saving creates a new version. Source: {escape(selected_source or '')}.
  Used by improver: <strong>{selected_usage}</strong> time(s) (lifetime injections).</p>
  <form method="post" action="/console/templates/save" id="editTemplateForm">
    <input type="hidden" name="template_id" value="{escape(selected_id)}">
    <input type="hidden" name="return_query" value="{escape(list_qs)}">
    <div class="form-row"><label>Name</label><input name="name" value="{escape(selected_name or selected_id)}" required></div>
    <div class="form-row"><label>Body</label><textarea name="body" rows="12" required>{escape(selected_body)}</textarea></div>
    {render_param_editor(selected_params, editor_id="editParamEditor")}
    <div class="form-row"><label>AI instruction (optional)</label>
    <input name="ai_instruction" placeholder="e.g. make deliverables clearer"></div>
    <p class="template-studio-status subtitle"></p>
    <button type="submit">Save new version</button>
    <button type="button" class="template-improve-btn">Improve with AI</button>
    <button type="button" class="template-preview-btn btn-secondary">Preview render</button>
  </form>
  {_render_template_studio_script("editTemplateForm")}
  {delete_form}
</div>
{version_table}
"""

    unused_checked = " checked" if filters.unused_only else ""
    toxic_checked = " checked" if filters.toxic_only else ""
    has_list_filters = bool(
        filters.query
        or filters.source is not None
        or filters.visibility is not None
        or filters.unused_only
        or filters.toxic_only
    )
    bulk_archive_html = ""
    if filters.unused_only and bulk_archive_eligible > 0:
        bulk_archive_html = f"""
<form method="post" action="/console/templates/archive-bulk" style="margin-top:0.75rem"
      onsubmit="return confirm('Archive {bulk_archive_eligible} unused public template(s)?')">
  <input type="hidden" name="return_query" value="{escape(list_qs)}">
  <button type="submit" class="btn-secondary">Archive {bulk_archive_eligible} unused public</button>
</form>"""
    toxic_quarantine_html = ""
    if toxic_archive_eligible > 0:
        toxic_quarantine_html = f"""
<form method="post" action="/console/templates/archive-toxic" style="margin-top:0.75rem"
      onsubmit="return confirm('Quarantine {toxic_archive_eligible} toxic template(s) with 0% accept?')">
  <input type="hidden" name="return_query" value="{escape(list_qs)}">
  <button type="submit" class="btn-secondary">Quarantine toxic (0% accept)</button>
</form>"""
    empty_state = ""
    create_open = ""
    if list_page.total == 0 and not has_list_filters:
        empty_state = render_empty_state(
            title="No templates yet",
            body=(
                "Prompt templates are reusable bodies with optional {param} placeholders. "
                "Create one below, or import a library from Ops."
            ),
            primary_href="#template-create",
            primary_label="New template",
            secondary_html='<a class="btn-secondary btn" href="/console/ops">Open Ops</a>',
        )
        create_open = " open"
    elif list_page.total == 0:
        empty_state = render_empty_state(
            title="No matching templates",
            body="Try clearing search, source, visibility, or the Unused/Toxic filters.",
            primary_href="/console/templates",
            primary_label="Clear filters",
        )

    table_body = (
        "".join(table_rows)
        if table_rows
        else '<tr><td colspan="8">No templates</td></tr>'
    )
    body = f"""
{_render_template_list_styles()}
{flash}
<form method="get" action="/console/templates" class="panel">
  <div class="template-browse-header">
    <h2>Browse templates</h2>
    <a class="template-new-link" href="#template-create"
       onclick="document.getElementById('template-create')?.setAttribute('open','');">New template</a>
  </div>
  <p class="usage-hint">Usage counts improver injections (when a template is included in improve_prompt context).
  Filter <strong>Unused only</strong> to find candidates for archiving — archive hides templates from improver retrieval without deleting them.</p>
  <div class="template-toolbar">
    <div class="form-row">
      <label for="q">Search</label>
      <input type="search" id="q" name="q" value="{escape(filters.query)}" placeholder="Keyword search…">
    </div>
    <div class="form-row">
      <label for="source">Source</label>
      <select id="source" name="source">{source_options_html}</select>
    </div>
    <div class="form-row">
      <label for="visibility">Visibility</label>
      <select id="visibility" name="visibility">{visibility_options_html}</select>
    </div>
    <div class="form-row checkbox-row">
      <input type="checkbox" id="unused" name="unused" value="1"{unused_checked}>
      <label for="unused">Unused only</label>
    </div>
    <div class="form-row checkbox-row">
      <input type="checkbox" id="toxic" name="toxic" value="1"{toxic_checked}>
      <label for="toxic">Toxic only (0% accept)</label>
    </div>
    <div class="form-row">
      <label for="sort">Sort by</label>
      <select id="sort" name="sort">{sort_options_html}</select>
    </div>
    <div class="form-row">
      <label for="order">Order</label>
      <select id="order" name="order">
        <option value="asc"{order_selected_asc}>Ascending</option>
        <option value="desc"{order_selected_desc}>Descending</option>
      </select>
    </div>
    <div class="form-row">
      <label for="per_page">Per page</label>
      <select id="per_page" name="per_page">{per_page_options_html}</select>
    </div>
    <button type="submit">Apply</button>
  </div>
  {bulk_archive_html}
  {toxic_quarantine_html}
</form>
{empty_state}
<div class="panel template-table-wrap">
  <table class="template-table">
    <thead><tr>
      <th>ID</th><th>Name</th><th>Source</th><th>Visibility</th><th>Version</th>
      <th class="col-usage">Usage</th><th>Params</th><th class="col-actions">Actions</th>
    </tr></thead>
    <tbody>{table_body}</tbody>
  </table>
  {_render_template_pagination(list_page)}
</div>
{detail}
<details class="panel" id="template-create"{create_open}>
  <summary>New template</summary>
  <form method="post" action="/console/templates/save" id="createTemplateForm">
    <div class="form-row"><label>Template ID</label><input name="template_id" required pattern="[a-z0-9-]+"></div>
    <div class="form-row"><label>Name</label><input name="name" required></div>
    <div class="form-row"><label>Body</label><textarea name="body" rows="6" required placeholder="Use {{param}} or {{{{param}}}} placeholders…"></textarea></div>
    {render_param_editor([], editor_id="createParamEditor")}
    <div class="form-row"><label>AI instruction (optional)</label>
    <input name="ai_instruction" placeholder="e.g. optimize for code review tasks"></div>
    <p class="template-studio-status subtitle"></p>
    <button type="submit">Create</button>
    <button type="button" class="template-improve-btn">Improve with AI</button>
    <button type="button" class="template-preview-btn btn-secondary">Preview render</button>
  </form>
  {_render_template_studio_script("createTemplateForm")}
</details>
"""
    return render_console_page(
        title="Templates",
        body_html=body,
        active_nav="templates",
        subtitle="Browse, edit, and create prompt templates with improver usage tracking",
    )

