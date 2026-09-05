"""Console page renderers."""

from __future__ import annotations

from html import escape

from ylang.console.layout import render_console_page
from ylang.console.proposals import PendingProposal
from ylang.core.runtime_settings import SETTING_DESCRIPTIONS, RuntimeSettingRow
from ylang.settings import Settings
from ylang.console.page_modules.control import _render_proposal_blocks

def render_settings_page(
    *,
    runtime_rows: list[RuntimeSettingRow],
    restart_snapshot: dict[str, str],
    flags: dict[str, bool],
    base_settings: Settings | None = None,
    saved: bool = False,
    proposals: list[PendingProposal] | None = None,
    preferred_candidates: list[dict[str, str]] | None = None,
) -> str:
    """Render hot-reloadable settings form and read-only env display."""
    from ylang.core.runtime_settings import effective_int_setting, merge_settings

    flash = '<div class="flash ok">Parameters saved.</div>' if saved else ""
    overrides = {row.key: row.value for row in runtime_rows}
    effective = merge_settings(base_settings, overrides) if base_settings else None

    def effective_hint(name: str) -> str:
        if effective is None:
            return ""
        if name.startswith("models_"):
            activity = name.removeprefix("models_")
            models = effective.activity_model_lists.get(activity, [])  # type: ignore[arg-type]
            eff = ", ".join(models)
        elif name == "improver_timeout_sec":
            eff = str(
                effective_int_setting(
                    name,
                    env_var="YLANG_IMPROVER_TIMEOUT_SEC",
                    default=12,
                    overrides=overrides,
                )
            )
        elif name == "learned_template_limit":
            eff = str(
                effective_int_setting(
                    name,
                    env_var="YLANG_LEARNED_TEMPLATE_LIMIT",
                    default=1,
                    overrides=overrides,
                )
            )
        elif name == "pattern_alert_threshold":
            eff = str(
                effective_int_setting(
                    name,
                    default=3,
                    overrides=overrides,
                )
            )
        elif name == "daily_budget_usd":
            eff = (
                f"{effective.daily_budget_usd:.2f}"
                if effective.daily_budget_usd is not None
                else "—"
            )
        elif name in {"improver_critique", "experiments", "edit_feedback"}:
            eff = "on" if flags.get(name) else "off"
        elif name == "usage_digest_enabled":
            raw = overrides.get("usage_digest_enabled")
            eff = "on" if raw and raw.lower() in {"1", "true", "yes", "on"} else "off"
        elif name == "pattern_detector":
            eff = overrides.get(name) or "lexical"
        else:
            eff = overrides.get(name) or "(env default)"
        override = overrides.get(name)
        if override:
            return (
                f'<p class="subtitle">Effective: <code>{escape(eff)}</code> · '
                f'Override: <code>{escape(override)}</code> '
                f'<span class="badge warn">runtime</span></p>'
            )
        return (
            f'<p class="subtitle">Effective: <code>{escape(eff)}</code> · '
            f'<span class="badge">env default</span></p>'
        )

    def field(
        name: str, label: str, *, input_type: str = "text", value: str = ""
    ) -> str:
        current = overrides.get(name, value)
        hint = SETTING_DESCRIPTIONS.get(name, "")
        hint_html = f'<p class="subtitle">{escape(hint)}</p>' if hint else ""
        eff_html = effective_hint(name)
        reset = (
            f' <button type="submit" name="reset_key" value="{escape(name)}" '
            f'class="btn-secondary" formnovalidate>Reset</button>'
            if name in overrides
            else ""
        )
        if input_type == "checkbox":
            checked = "checked" if current.lower() in {"1", "true", "yes"} else ""
            return (
                f'<div class="form-row"><label><input type="checkbox" name="{escape(name)}" {checked}> '
                f"{escape(label)}</label>{hint_html}{eff_html}{reset}</div>"
            )
        if input_type == "select" and name == "pattern_detector":
            options = ("lexical", "semantic")
            opts = "".join(
                f'<option value="{opt}"{" selected" if current == opt else ""}>'
                f"{opt}</option>"
                for opt in options
            )
            return (
                f'<div class="form-row"><label for="{escape(name)}">{escape(label)}</label>'
                f"{hint_html}{eff_html}"
                f'<select id="{escape(name)}" name="{escape(name)}">{opts}</select>'
                f"{reset}</div>"
            )
        chips = ""
        if name.startswith("models_"):
            chips = (
                f'<p class="subtitle">Presets: '
                f'<button type="button" class="btn-secondary model-chip" data-target="{escape(name)}" '
                f'data-value="mistral/mistral-small-latest,anthropic/claude-haiku-4-5">fast</button> '
                f'<button type="button" class="btn-secondary model-chip" data-target="{escape(name)}" '
                f'data-value="anthropic/claude-sonnet-5,openai/gpt-5.5">quality</button></p>'
            )
        preferred_picker = ""
        if name == "retrieval_preferred_template_ids" and preferred_candidates:
            preferred_picker = _render_preferred_template_picker(
                preferred_candidates,
                selected_csv=current,
            )
        return (
            f'<div class="form-row"><label for="{escape(name)}">{escape(label)}</label>'
            f'{hint_html}{eff_html}{chips}'
            f'<input type="{escape(input_type)}" id="{escape(name)}" name="{escape(name)}" '
            f'value="{escape(current)}">{reset}'
            f"{preferred_picker}</div>"
        )

    def section(title: str, fields: list[str], *, section_id: str) -> str:
        return (
            f'<fieldset class="settings-section" id="{escape(section_id)}">'
            f"<legend>{escape(title)}</legend>"
            f"{''.join(fields)}"
            f"</fieldset>"
        )

    timeout_eff = effective_int_setting(
        "improver_timeout_sec",
        env_var="YLANG_IMPROVER_TIMEOUT_SEC",
        default=12,
        overrides=overrides,
    )
    learned_eff = effective_int_setting(
        "learned_template_limit",
        env_var="YLANG_LEARNED_TEMPLATE_LIMIT",
        default=1,
        overrides=overrides,
    )
    models_improve_eff = overrides.get("models_improve", "")
    if not models_improve_eff and effective is not None:
        models_improve_eff = ",".join(
            effective.activity_model_lists.get("improve", [])
        )
    impact_bits: list[str] = []
    # ≤18 matches Fast/cheap timeout guidance (pair with hook timeout ≥20).
    if timeout_eff <= 18 and learned_eff <= 1:
        impact_bits.append("favors latency")
    if models_improve_eff.strip().lower().startswith("mistral"):
        impact_bits.append("fast path")
    if not impact_bits:
        impact_bits.append("quality-leaning (trim timeout/learned_limit or prefer mistral for speed)")
    impact_html = (
        f'<p class="subtitle">Impact estimate: {escape(", ".join(impact_bits))}.</p>'
    )

    routing = section(
        "Routing",
        [
            field("models_code", "Models: code (comma-separated)"),
            field("models_search", "Models: search"),
            field("models_reason", "Models: reason"),
            field("models_improve", "Models: improve"),
            field("models_other", "Models: other"),
            field("quality_band", "Quality band", input_type="number", value="0"),
            field("fallback_model", "Fallback model"),
        ],
        section_id="params-routing",
    )
    improver = section(
        "Improver",
        [
            impact_html,
            field(
                "improver_timeout_sec",
                "Improver timeout (seconds, 0=off, default 12)",
                input_type="number",
                value="12",
            ),
            field(
                "improver_critique",
                "Enable improver critique pass",
                input_type="checkbox",
            ),
            field(
                "learned_template_limit",
                "Learned template limit",
                input_type="number",
                value="1",
            ),
            field(
                "retrieval_preferred_template_ids",
                "Preferred template ids (comma-separated, retrieval boost)",
            ),
        ],
        section_id="params-improver",
    )
    limits = section(
        "Limits",
        [
            field("daily_budget_usd", "Daily budget (USD)", input_type="number", value=""),
            field(
                "provider_cooldown_seconds",
                "Provider cooldown (seconds)",
                input_type="number",
            ),
            field(
                "rate_limit_per_minute",
                "Rate limit per minute (0=off)",
                input_type="number",
            ),
            field(
                "pattern_alert_threshold",
                "Pattern alert threshold",
                input_type="number",
                value="3",
            ),
        ],
        section_id="params-limits",
    )
    digest_last = overrides.get("usage_digest_last_at", "")
    flags_section = section(
        "Flags",
        [
            field("experiments", "Enable experiments", input_type="checkbox"),
            field(
                "edit_feedback",
                "Enable edit feedback capture",
                input_type="checkbox",
            ),
            field(
                "pattern_detector",
                "Pattern detector",
                input_type="select",
                value="lexical",
            ),
            field(
                "usage_digest_enabled",
                "Usage digest via CLI/cron (also enables desktop notify-send when a display is available)",
                input_type="checkbox",
            ),
            (
                "<p>Digests are <strong>not</strong> emailed or pushed by the console. "
                "Run <code>ylang usage digest --last-days 7</code> (or schedule it with cron). "
                "When the checkbox above is on, that command also attempts a Linux desktop "
                "notification via <code>notify-send</code> if <code>DISPLAY</code> or "
                "<code>WAYLAND_DISPLAY</code> is set; otherwise it prints only.</p>"
                f'<p class="subtitle">Last digest: <code>{escape(digest_last or "never")}</code></p>'
            ),
            (
                f'<p class="subtitle">Effective flags: Critique '
                f'<span class="badge">{"on" if flags.get("improver_critique") else "off"}</span> · '
                f'Experiments <span class="badge">{"on" if flags.get("experiments") else "off"}</span> · '
                f'Edit feedback <span class="badge">{"on" if flags.get("edit_feedback") else "off"}</span></p>'
            ),
        ],
        section_id="params-flags",
    )

    restart_rows = "".join(
        f"<tr><td>{escape(key)}</td><td><code>{escape(value)}</code></td></tr>"
        for key, value in sorted(restart_snapshot.items())
    )

    pending = proposals or []
    runtime_pending = [
        item for item in pending if item.apply_type == "runtime_setting"
    ] or pending
    proposals_panel = ""
    if runtime_pending:
        proposals_panel = f"""
<div class="panel">
  <h2>Pending proposals</h2>
  <p class="subtitle">Governed Apply from optimizer / experiments (last 7 days).
  Showing {len(runtime_pending)} proposal(s).</p>
  {_render_proposal_blocks(runtime_pending, return_to="/console/settings")}
</div>"""

    body = f"""
{flash}
{proposals_panel}
<div class="panel">
  <h2>Presets</h2>
  <p class="subtitle">Fill hot-reload fields — click Save parameters to persist. Jump to
  <a href="#params-routing">Routing</a>, <a href="#params-improver">Improver</a>,
  <a href="#params-limits">Limits</a>, or <a href="#params-flags">Flags</a>.</p>
  <button type="button" class="btn-secondary" id="presetFast">Fast / cheap</button>
  <button type="button" class="btn-secondary" id="presetQuality">Quality</button>
</div>
<div class="panel">
  <h2>Parameters</h2>
  <p class="subtitle">Hot-reload runtime overrides (SQLite). Each field shows effective value vs env default or runtime override.</p>
  <form method="post" action="/console/settings" id="settingsForm">
    {routing}
    {improver}
    {limits}
    {flags_section}
    <button type="submit">Save parameters</button>
  </form>
</div>
<script src="/console/static/page-settings-render_settings_page-1.js" defer></script>
<div class="panel">
  <h2>Restart-required (read-only)</h2>
  <p class="subtitle">Set via environment variables. Secrets are masked.</p>
  <div class="table-wrap">
  <table><thead><tr><th style="width:40%">Key</th><th>Value</th></tr></thead><tbody>{restart_rows}</tbody></table>
  </div>
</div>
"""
    return render_console_page(
        title="Parameters",
        subtitle="Routing, improver, limits, and feature flags (hot-reload)",
        body_html=body,
        active_nav="settings",
    )


def _render_preferred_template_picker(
    candidates: list[dict[str, str]],
    *,
    selected_csv: str,
) -> str:
    """Render checkboxes that sync into the preferred-template CSV input."""
    selected = {
        part.strip() for part in selected_csv.split(",") if part.strip()
    }
    boxes: list[str] = []
    for item in candidates:
        tid = item.get("id", "").strip()
        name = item.get("name", tid).strip() or tid
        if not tid:
            continue
        checked = " checked" if tid in selected else ""
        boxes.append(
            f'<label class="preferred-chip">'
            f'<input type="checkbox" class="preferred-template-cb" '
            f'value="{escape(tid)}"{checked}> '
            f"<code>{escape(tid)}</code> {escape(name)}</label>"
        )
    if not boxes:
        return ""
    return (
        '<div class="preferred-picker" id="preferredPicker">'
        '<p class="subtitle">Pick preferred templates (syncs into the CSV field):</p>'
        f'<div class="preferred-chip-list">{"".join(boxes)}</div></div>'
    )


def _preferred_picker_script() -> str:
    """Inline JS syncing preferred-template checkboxes to the CSV input."""
    return """
(function syncPreferredPicker() {
  const input = document.getElementById("retrieval_preferred_template_ids");
  const picker = document.getElementById("preferredPicker");
  if (!input || !picker) return;
  const boxes = () => [...picker.querySelectorAll(".preferred-template-cb")];
  const writeCsv = () => {
    input.value = boxes()
      .filter((cb) => cb.checked)
      .map((cb) => cb.value)
      .join(",");
  };
  boxes().forEach((cb) => cb.addEventListener("change", writeCsv));
})();
"""

