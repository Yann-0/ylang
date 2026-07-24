"""Parse and render template parameter forms for the admin console."""

from __future__ import annotations

import json
import re
from html import escape

from starlette.datastructures import FormData

from ylang.library.types import TemplateParam

# ``{{param}}`` (mustache-style) or ``{param}`` (str.format), identifier names only.
# Prefer double-brace when both could match; scan in document order.
_PLACEHOLDER = re.compile(
    r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}"
    r"|"
    r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})"
)


def detect_placeholders(body: str) -> list[str]:
    """Return unique placeholder names found in ``body``, in first-seen order.

    Recognizes both ``{{name}}`` and ``{name}`` forms. Names must be valid
    Python format identifiers (letter/underscore, then alphanumerics).
    """
    seen: dict[str, None] = {}
    for match in _PLACEHOLDER.finditer(body):
        name = match.group(1) or match.group(2)
        if name:
            seen.setdefault(name, None)
    return list(seen)


def merge_detected_params(
    existing: list[TemplateParam],
    detected_names: list[str],
) -> list[TemplateParam]:
    """Merge detected placeholder names into existing param rows.

    Preserves description/default for names already declared. Appends new
    names with empty description and no default. Keeps existing order, then
    adds newly detected names in detection order.
    """
    by_name = {item.name: item for item in existing if item.name}
    merged: list[TemplateParam] = []
    used: set[str] = set()
    for item in existing:
        if not item.name or item.name in used:
            continue
        used.add(item.name)
        merged.append(item)
    for name in detected_names:
        if name in used:
            continue
        used.add(name)
        prior = by_name.get(name)
        merged.append(
            prior
            if prior is not None
            else TemplateParam(name=name, description="", default=None)
        )
    return merged


def parse_params_from_form(form: FormData) -> list[TemplateParam]:
    """Build ``TemplateParam`` list from repeated form fields."""
    names = [str(item).strip() for item in form.getlist("param_name")]
    descriptions = [str(item).strip() for item in form.getlist("param_description")]
    defaults = [str(item).strip() for item in form.getlist("param_default")]
    count = max(len(names), len(descriptions), len(defaults), 0)
    params: list[TemplateParam] = []
    for index in range(count):
        name = names[index] if index < len(names) else ""
        if not name:
            continue
        description = descriptions[index] if index < len(descriptions) else ""
        default_raw = defaults[index] if index < len(defaults) else ""
        params.append(
            TemplateParam(
                name=name,
                description=description,
                default=default_raw or None,
            )
        )
    return params


def render_param_editor(
    params: list[TemplateParam] | None = None,
    *,
    editor_id: str = "paramEditor",
) -> str:
    """Return HTML + JS for a repeatable template parameter editor."""
    rows = []
    items = list(params or [])
    if not items:
        items = [TemplateParam(name="", description="", default=None)]
    for item in items:
        default_value = item.default or ""
        rows.append(
            f"""
<div class="param-row">
  <input name="param_name" placeholder="name" value="{escape(item.name)}">
  <input name="param_description" placeholder="description" value="{escape(item.description)}">
  <input name="param_default" placeholder="default" value="{escape(default_value)}">
  <button type="button" class="btn-secondary param-remove">Remove</button>
</div>"""
        )
    add_id = f"{editor_id}Add"
    detect_id = f"{editor_id}Detect"
    return f"""
<div class="panel" id="{escape(editor_id)}">
  <h3>Parameters</h3>
  <p class="subtitle">Declare placeholders used as <code>{{name}}</code> or <code>{{{{name}}}}</code> in the template body.</p>
  <div class="param-rows">{"".join(rows)}</div>
  <button type="button" class="btn-secondary" id="{escape(add_id)}" data-no-loading>Add parameter</button>
  <button type="button" class="btn-secondary" id="{escape(detect_id)}" data-no-loading>Detect from body</button>
</div>
<style>
.param-row {{ display:grid; grid-template-columns: 1fr 1.5fr 1fr auto; gap:0.5rem; margin-bottom:0.5rem; }}
.param-row input {{ width:100%; max-width:none; }}
</style>
<script>
(() => {{
  const root = document.getElementById({json.dumps(editor_id)});
  if (!root) return;
  const rows = root.querySelector(".param-rows");
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
  function emptyRow() {{
    const row = document.createElement("div");
    row.className = "param-row";
    row.innerHTML = `
      <input name="param_name" placeholder="name">
      <input name="param_description" placeholder="description">
      <input name="param_default" placeholder="default">
      <button type="button" class="btn-secondary param-remove">Remove</button>`;
    return row;
  }}
  document.getElementById({json.dumps(add_id)})?.addEventListener("click", () => {{
    rows.appendChild(emptyRow());
  }});
  document.getElementById({json.dumps(detect_id)})?.addEventListener("click", () => {{
    const form = root.closest("form");
    const body = form?.querySelector('textarea[name="body"]')?.value || "";
    const names = detectNames(body);
    if (!names.length) {{
      window.alert("No {{param}} or {{{{param}}}} placeholders found in the body.");
      return;
    }}
    const existingOrder = [];
    const existing = {{}};
    rows.querySelectorAll(".param-row").forEach((row) => {{
      const name = row.querySelector('input[name="param_name"]')?.value?.trim();
      if (!name || existing[name]) return;
      existingOrder.push(name);
      existing[name] = {{
        description: row.querySelector('input[name="param_description"]')?.value || "",
        default: row.querySelector('input[name="param_default"]')?.value || "",
      }};
    }});
    const merged = [...existingOrder];
    names.forEach((name) => {{ if (!existing[name] && !merged.includes(name)) merged.push(name); }});
    rows.innerHTML = "";
    merged.forEach((name) => {{
      const row = emptyRow();
      row.querySelector('input[name="param_name"]').value = name;
      const prior = existing[name];
      if (prior) {{
        row.querySelector('input[name="param_description"]').value = prior.description;
        row.querySelector('input[name="param_default"]').value = prior.default;
      }}
      rows.appendChild(row);
    }});
  }});
  rows.addEventListener("click", (event) => {{
    const target = event.target;
    if (target instanceof HTMLElement && target.classList.contains("param-remove")) {{
      const row = target.closest(".param-row");
      if (row && rows.children.length > 1) row.remove();
    }}
  }});
}})();
</script>
"""
