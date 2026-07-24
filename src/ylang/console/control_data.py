"""Data helpers for the console Control Center dashboard."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ylang.core.memory import MemoryStore
from ylang.core.runtime_settings import (
    RuntimeSettingsStore,
    effective_feature_flags,
    effective_int_setting,
    merge_settings,
)
from ylang.library.store import Library
from ylang.settings import Settings
from ylang.usage.improver_analytics import (
    ImproverFunnelSummary,
    ImproverQualityScores,
    TemplateEffectivenessRow,
)

@dataclass(frozen=True, slots=True)
class TemplateInventory:
    """Template counts grouped by visibility, source, and archive tag."""

    total: int
    public: int
    private: int
    by_source: dict[str, int]
    archived: int


FACTS_ONBOARDING_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class StoreInventory:
    """Aggregate inventory for templates, facts, and usage rows."""

    templates: TemplateInventory
    facts_total: int
    facts_by_scope: dict[str, int]
    facts_by_workspace: dict[str, int]
    usage_rows: int


@dataclass(frozen=True, slots=True)
class EffectiveConfigRow:
    """One hot-reload setting with effective and optional override values."""

    key: str
    effective: str
    override: str | None
    is_flag: bool = False


@dataclass(frozen=True, slots=True)
class EffectiveConfigSummary:
    """Resolved runtime configuration for the Control Center config panel."""

    models_improve: str
    improver_timeout_sec: int
    learned_template_limit: int
    improver_critique: bool
    daily_budget_usd: float | None
    flags: dict[str, bool]
    rows: tuple[EffectiveConfigRow, ...]


def gather_store_inventory(
    library: Library,
    memory: MemoryStore,
    connection: sqlite3.Connection,
) -> StoreInventory:
    """Return template, fact, and usage row counts from live stores."""
    templates = library.list(include_archived=True)
    public = sum(1 for item in templates if item.visibility == "public")
    private = sum(1 for item in templates if item.visibility == "private")
    archived = sum(1 for item in templates if item.visibility == "archived")
    by_source: dict[str, int] = {}
    for item in templates:
        by_source[item.source] = by_source.get(item.source, 0) + 1

    facts = memory.recall(limit=10_000)
    facts_by_scope: dict[str, int] = {}
    facts_by_workspace: dict[str, int] = {}
    for fact in facts:
        facts_by_scope[fact.scope] = facts_by_scope.get(fact.scope, 0) + 1
        workspace_key = fact.workspace.strip() or "(global)"
        facts_by_workspace[workspace_key] = facts_by_workspace.get(workspace_key, 0) + 1

    usage_row = connection.execute("SELECT COUNT(*) FROM usage").fetchone()
    usage_rows = int(usage_row[0]) if usage_row else 0

    return StoreInventory(
        templates=TemplateInventory(
            total=len(templates),
            public=public,
            private=private,
            by_source=by_source,
            archived=archived,
        ),
        facts_total=len(facts),
        facts_by_scope=facts_by_scope,
        facts_by_workspace=facts_by_workspace,
        usage_rows=usage_rows,
    )


def should_show_facts_onboarding_cta(
    inventory: StoreInventory,
    *,
    threshold: int = FACTS_ONBOARDING_THRESHOLD,
) -> bool:
    """Return True when total or per-workspace fact counts are below *threshold*."""
    if inventory.facts_total < threshold:
        return True
    return any(
        count < threshold
        for workspace, count in inventory.facts_by_workspace.items()
        if workspace != "(global)"
    )


def gather_effective_config(
    settings: Settings,
    runtime_store: RuntimeSettingsStore,
) -> EffectiveConfigSummary:
    """Build effective config summary from env defaults plus runtime overrides."""
    overrides = runtime_store.as_dict()
    effective = merge_settings(settings, overrides)
    flags = effective_feature_flags(overrides)

    timeout = effective_int_setting(
        "improver_timeout_sec",
        env_var="YLANG_IMPROVER_TIMEOUT_SEC",
        default=12,
        overrides=overrides,
    )
    learned_limit = effective_int_setting(
        "learned_template_limit",
        env_var="YLANG_LEARNED_TEMPLATE_LIMIT",
        default=1,
        overrides=overrides,
    )
    models_improve = ", ".join(effective.activity_model_lists.get("improve", []))

    row_specs: list[tuple[str, str, str | None, bool]] = [
        (
            "models_improve",
            models_improve,
            overrides.get("models_improve"),
            False,
        ),
        (
            "improver_timeout_sec",
            str(timeout),
            overrides.get("improver_timeout_sec"),
            False,
        ),
        (
            "learned_template_limit",
            str(learned_limit),
            overrides.get("learned_template_limit"),
            False,
        ),
        (
            "improver_critique",
            "on" if flags.get("improver_critique") else "off",
            overrides.get("improver_critique"),
            True,
        ),
        (
            "daily_budget_usd",
            f"{effective.daily_budget_usd:.2f}"
            if effective.daily_budget_usd is not None
            else "—",
            overrides.get("daily_budget_usd"),
            False,
        ),
        (
            "experiments",
            "on" if flags.get("experiments") else "off",
            overrides.get("experiments"),
            True,
        ),
        (
            "edit_feedback",
            "on" if flags.get("edit_feedback") else "off",
            overrides.get("edit_feedback"),
            True,
        ),
    ]
    rows = tuple(
        EffectiveConfigRow(key=key, effective=effective_val, override=override, is_flag=is_flag)
        for key, effective_val, override, is_flag in row_specs
    )
    return EffectiveConfigSummary(
        models_improve=models_improve,
        improver_timeout_sec=timeout,
        learned_template_limit=learned_limit,
        improver_critique=bool(flags.get("improver_critique")),
        daily_budget_usd=effective.daily_budget_usd,
        flags=flags,
        rows=rows,
    )


def improver_avg_latency_ms(funnel: ImproverFunnelSummary) -> float | None:
    """Return weighted average improver latency across modes, or ``None`` when empty."""
    fired = sum(stats.fired for stats in funnel.by_mode.values())
    if fired <= 0:
        return None
    total_ms = sum(
        stats.avg_latency_ms * stats.fired for stats in funnel.by_mode.values()
    )
    return total_ms / fired


def format_ratio_percent(value: float | None) -> str:
    """Format a 0–1 ratio as a percentage string, or an em dash when missing."""
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def polish_ratio_subtitle(quality: ImproverQualityScores) -> str:
    """Short explanation under the Polish ratio card."""
    if quality.polish_sample_count <= 0:
        return (
            "No edit-feedback samples in this window. Enable edit_feedback in "
            "Parameters and submit a few improved prompts to unlock Polish ratio."
        )
    kept = (
        f"{quality.polish_kept_as_is_rate * 100:.0f}% kept as-is"
        if quality.polish_kept_as_is_rate is not None
        else "kept-as-is n/a"
    )
    avg_edit = (
        f"avg edit distance {quality.avg_edit_distance:.0f}"
        if quality.avg_edit_distance is not None
        else "avg edit distance n/a"
    )
    return (
        f"1 − edit_distance/len(original) · {quality.polish_sample_count} sample(s) · "
        f"{kept} · {avg_edit}"
    )


def performance_ratio_subtitle(quality: ImproverQualityScores) -> str:
    """Short explanation under the Performance ratio card."""
    if quality.performance_ratio is None:
        return "No improver calls in this window."
    latency = (
        f"{quality.avg_latency_ms:.0f}ms avg"
        if quality.avg_latency_ms is not None
        else "latency n/a"
    )
    return f"accept_rate × min(1, 8s / avg_latency) · {latency}"


def gather_zero_accept_templates(
    templates: list[TemplateEffectivenessRow],
    *,
    min_injections: int = 3,
) -> tuple[TemplateEffectivenessRow, ...]:
    """Return templates with zero accept rate and enough injection samples."""
    return tuple(
        row
        for row in templates
        if row.injections >= min_injections and row.accept_rate == 0.0
    )


_PROPOSAL_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def sort_by_priority(items: list, *, priority_attr: str = "priority") -> list:
    """Return *items* sorted high → medium → low by a ``priority`` attribute."""
    return sorted(
        items,
        key=lambda item: _PROPOSAL_PRIORITY_ORDER.get(getattr(item, priority_attr), 9),
    )
