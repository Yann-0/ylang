"""Propose-only optimization suggestions from usage analytics."""

from __future__ import annotations

import json
import sqlite3
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ylang.library.pattern_detector import (
    UsagePatternDetector,
    propose_template_from_pattern_outcome,
)
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import (
    ImproverFunnelSummary,
    ImproverQualityScores,
    TemplateEffectivenessRow,
    summarize_improver,
    template_effectiveness,
)
from ylang.usage.store import UsageStore, UsageWindow

if TYPE_CHECKING:
    from ylang.core.engine import Engine

logger = logging.getLogger(__name__)

_NARRATIVE_SYSTEM = """\
You summarize Ylang improver usage analytics into 2-3 actionable sentences for an admin.
Be specific, cite rates and counts from the data, and avoid generic advice.
Respond with plain text only (no markdown).
"""

# Apply action kinds consumed by console/proposals.py
APPLY_RUNTIME_SETTING = "runtime_setting"
APPLY_LEARNED_TEMPLATE = "learned_template"
APPLY_ARCHIVE_TEMPLATES = "archive_templates"

# Fast/cheap improver preset (matches console Parameters "fast" chip).
_FAST_IMPROVE_MODELS = "mistral/mistral-small-latest,anthropic/claude-haiku-4-5"


@dataclass(frozen=True, slots=True)
class OptimizationSuggestion:
    """One evidence-backed propose-only optimization suggestion.

    When ``apply_action`` is set, the suggestion is applyable via the governed
    proposals flow (explicit Apply only). Concrete payloads:

    - ``runtime_setting``: ``setting_key`` + ``setting_value``
    - ``learned_template``: ``template_id`` (pattern-derived learned template)
    - ``archive_templates``: ``template_id`` (comma-separated ids allowed)
    """

    suggestion_id: str
    kind: str
    title: str
    description: str
    evidence: str
    priority: str
    apply_action: str | None = None
    setting_key: str | None = None
    setting_value: str | None = None
    template_id: str | None = None


def _runtime_setting_already_applied(
    runtime_overrides: dict[str, str] | None,
    key: str | None,
    value: str | None,
) -> bool:
    """Return True when ``key`` already has ``value`` in runtime overrides."""
    if not runtime_overrides or not key or value is None:
        return False
    current = runtime_overrides.get(key)
    if current is None:
        return False
    left = current.strip().lower()
    right = value.strip().lower()
    if left in {"1", "true", "yes", "on"}:
        left = "true"
    if left in {"0", "false", "no", "off"}:
        left = "false"
    if right in {"1", "true", "yes", "on"}:
        right = "true"
    if right in {"0", "false", "no", "off"}:
        right = "false"
    return left == right



def _suggestions_improver_accept_rate(
    funnel: ImproverFunnelSummary,
) -> list[OptimizationSuggestion]:
    """Suggest context trim when improver accept rate is low."""
    if funnel.total_fired < 5 or funnel.accept_rate >= 0.5:
        return []
    return [
        OptimizationSuggestion(
            suggestion_id="improver-accept-rate-low",
            kind="improver_tuning",
            title="Improver accept rate is below 50%",
            description=(
                "Apply runtime setting learned_template_limit=1 to trim improver "
                "context and reduce latency/noise from low-signal templates."
            ),
            evidence=(
                f"Accept rate {funnel.accept_rate:.0%} over {funnel.total_fired} improver calls "
                f"({funnel.total_accepted} accepted)."
            ),
            priority="high",
            apply_action=APPLY_RUNTIME_SETTING,
            setting_key="learned_template_limit",
            setting_value="1",
        )
    ]


def _suggestions_improver_timeouts(
    funnel: ImproverFunnelSummary,
) -> list[OptimizationSuggestion]:
    """Suggest timeout/context/model changes when timeouts dominate."""
    timeout_count = funnel.top_rejection_reasons.get("improver timeout", 0)
    if timeout_count < 2:
        return []
    agent_latency = ""
    if funnel.by_mode.get("agent"):
        agent_latency = (
            f"; agent avg latency {funnel.by_mode['agent'].avg_latency_ms / 1000:.0f}s"
        )
    return [
        OptimizationSuggestion(
            suggestion_id="improver-timeout-raise",
            kind="improver_tuning",
            title="Raise improver timeout to reduce hook timeouts",
            description=(
                "Apply runtime setting improver_timeout_sec=18 after raising "
                "YLANG_HOOK_TIMEOUT_SEC to at least 20 so hooks still fail-open cleanly."
            ),
            evidence=f"Rejected {timeout_count} times with improver timeout in lookback.",
            priority="high",
            apply_action=APPLY_RUNTIME_SETTING,
            setting_key="improver_timeout_sec",
            setting_value="18",
        ),
        OptimizationSuggestion(
            suggestion_id="improver-context-trim",
            kind="improver_tuning",
            title="Trim learned templates in improver context",
            description=(
                "Apply runtime setting learned_template_limit=1 to shrink reference "
                "context and improve latency."
            ),
            evidence=(
                f"Top rejection: improver timeout ({timeout_count}×){agent_latency}."
            ),
            priority="high",
            apply_action=APPLY_RUNTIME_SETTING,
            setting_key="learned_template_limit",
            setting_value="1",
        ),
        OptimizationSuggestion(
            suggestion_id="improver-fast-models",
            kind="improver_tuning",
            title="Prefer faster models for improve routing",
            description=(
                "Apply runtime setting models_improve with fast/cheap models first "
                f"({ _FAST_IMPROVE_MODELS.replace(',', ', ') })."
            ),
            evidence=f"Improver timeout rejected {timeout_count} calls in lookback.",
            priority="high",
            apply_action=APPLY_RUNTIME_SETTING,
            setting_key="models_improve",
            setting_value=_FAST_IMPROVE_MODELS,
        ),
    ]


def _suggestions_rejection_reasons(
    funnel: ImproverFunnelSummary,
) -> list[OptimizationSuggestion]:
    """Surface top unhandled rejection reasons (not auto-applyable)."""
    handled = frozenset(
        {
            "improver timeout",
            "change.before not anchored to original",
            "improved text changed but changes[] is empty",
            "change replay failed without scope changes",
            "example change missing placeholder",
        }
    )
    out: list[OptimizationSuggestion] = []
    for reason, count in list(funnel.top_rejection_reasons.items())[:3]:
        if reason in handled:
            continue
        out.append(
            OptimizationSuggestion(
                suggestion_id=f"rejection-{reason[:32]}",
                kind="validation",
                title=f"Top rejection reason: {reason}",
                description=(
                    "Review improver validation rules for this failure mode "
                    "(not auto-applyable)."
                ),
                evidence=f"Rejected {count} times in the lookback window.",
                priority="low",
            )
        )
    return out


def _suggestions_template_effectiveness(
    store: UsageStore,
    templates: list[TemplateEffectivenessRow],
) -> list[OptimizationSuggestion]:
    """Boost high-accept templates or archive/review low-accept ones."""
    suggestions: list[OptimizationSuggestion] = []
    for row in templates[:5]:
        if row.accept_rate >= 0.6:
            if row.template_id.startswith("learned-"):
                suggestions.append(
                    OptimizationSuggestion(
                        suggestion_id=f"template-boost-{row.template_id}",
                        kind="template_retrieval",
                        title=f"Raise learned template limit for '{row.template_id}'",
                        description=(
                            "Apply runtime setting learned_template_limit=3 so high-performing "
                            f"learned template '{row.template_id}' can appear more often."
                        ),
                        evidence=(
                            f"Accept rate {row.accept_rate:.0%} over {row.injections} injections "
                            f"(avg cost ${row.avg_cost:.4f})."
                        ),
                        priority="high" if row.accept_rate >= 0.75 else "medium",
                        apply_action=APPLY_RUNTIME_SETTING,
                        setting_key="learned_template_limit",
                        setting_value="3",
                    )
                )
            else:
                if row.template_id in _current_preferred_ids(store):
                    continue
                preferred_value = _preferred_ids_with(store, row.template_id)
                suggestions.append(
                    OptimizationSuggestion(
                        suggestion_id=f"template-boost-{row.template_id}",
                        kind="template_retrieval",
                        title=f"Boost template '{row.template_id}' in retrieval",
                        description=(
                            "Apply runtime setting retrieval_preferred_template_ids so this "
                            "high-accept template is ranked higher in improver context."
                        ),
                        evidence=(
                            f"Accept rate {row.accept_rate:.0%} over {row.injections} injections "
                            f"(avg cost ${row.avg_cost:.4f})."
                        ),
                        priority="medium" if row.accept_rate >= 0.75 else "low",
                        apply_action=APPLY_RUNTIME_SETTING,
                        setting_key="retrieval_preferred_template_ids",
                        setting_value=preferred_value,
                    )
                )
        elif row.accept_rate <= 0.2 and row.injections >= 5:
            if row.template_id in _archived_template_ids(store):
                continue
            if row.accept_rate == 0.0 and row.injections >= 3:
                suggestions.append(
                    OptimizationSuggestion(
                        suggestion_id=f"template-archive-{row.template_id}",
                        kind="template_hygiene",
                        title=f"Archive zero-accept template '{row.template_id}'",
                        description=(
                            "Apply: set visibility=archived so this template is excluded "
                            "from improver retrieval."
                        ),
                        evidence=(
                            f"Accept rate {row.accept_rate:.0%} over {row.injections} injections."
                        ),
                        priority="high",
                        apply_action=APPLY_ARCHIVE_TEMPLATES,
                        template_id=row.template_id,
                    )
                )
            else:
                suggestions.append(
                    OptimizationSuggestion(
                        suggestion_id=f"template-review-{row.template_id}",
                        kind="template_revision",
                        title=f"Review template '{row.template_id}'",
                        description=(
                            "Low accept rate when this template is in context; revise body "
                            "in Templates (not auto-applyable)."
                        ),
                        evidence=(
                            f"Accept rate {row.accept_rate:.0%} over {row.injections} injections."
                        ),
                        priority="low",
                    )
                )
    return suggestions


def _suggestions_from_patterns(
    store: UsageStore,
    window: UsageWindow,
    templates: list[TemplateEffectivenessRow],
) -> list[OptimizationSuggestion]:
    """Propose learned templates from repeated usage patterns."""
    archived_ids = _archived_template_ids(store)
    zero_accept_ids = {
        row.template_id
        for row in templates
        if row.accept_rate == 0.0 and row.injections >= 3
    }
    detector = UsagePatternDetector(store)
    days = max(1, int((window.until - window.since).total_seconds() // 86400))
    patterns = detector.detect(window_days=days)
    suggestions: list[OptimizationSuggestion] = []
    for pattern in patterns[:5]:
        outcome = propose_template_from_pattern_outcome(pattern)
        proposal = outcome.proposal
        if proposal is None:
            continue
        suggested_id = proposal.suggested_template_id
        if suggested_id in archived_ids or suggested_id in zero_accept_ids:
            continue
        suggestions.append(
            OptimizationSuggestion(
                suggestion_id=f"pattern-{pattern.pattern_id}",
                kind="learned_template",
                title=f"Save learned template '{suggested_id}'",
                description=(
                    f"Apply: save learned template id `{suggested_id}`. "
                    f"{proposal.rationale}"
                ),
                evidence=(
                    f"Pattern seen {pattern.occurrence_count} times; "
                    f"suggested id: {suggested_id}."
                ),
                priority="medium",
                apply_action=APPLY_LEARNED_TEMPLATE,
                template_id=suggested_id,
            )
        )
    return suggestions


def _suggestions_from_feedback(
    feedback: FeedbackStore | None,
) -> list[OptimizationSuggestion]:
    """Suggest critique when users heavily edit improved prompts."""
    if feedback is None:
        return []
    edits = [
        event
        for event in feedback.recent(limit=20)
        if event.event_type == "prompt_edit"
    ]
    heavy_edits = [event for event in edits if (event.edit_distance or 0) > 40]
    if len(heavy_edits) < 3:
        return []
    return [
        OptimizationSuggestion(
            suggestion_id="user-edit-drift",
            kind="improver_tuning",
            title="Users frequently edit improved prompts heavily",
            description=(
                "Apply runtime setting improver_critique=true to tighten first-pass "
                "output before users edit."
            ),
            evidence=f"{len(heavy_edits)} edits with distance > 40 in recent feedback.",
            priority="high",
            apply_action=APPLY_RUNTIME_SETTING,
            setting_key="improver_critique",
            setting_value="true",
        )
    ]


def generate_optimization_suggestions(
    store: UsageStore,
    window: UsageWindow,
    *,
    feedback: FeedbackStore | None = None,
    runtime_overrides: dict[str, str] | None = None,
) -> list[OptimizationSuggestion]:
    """Analyze usage and return ranked propose-only optimization suggestions.

    When ``runtime_overrides`` is provided, runtime_setting suggestions whose
    key/value already match are omitted (avoids nagging applied Fast path).
    """
    if runtime_overrides is None:
        try:
            from ylang.core.runtime_settings import RuntimeSettingsStore

            runtime_overrides = RuntimeSettingsStore(store._connection).as_dict()
        except (OSError, sqlite3.Error, AttributeError, ValueError, TypeError):
            # Analytics must not fail when settings table/connection is unavailable.
            runtime_overrides = None

    funnel = summarize_improver(store, window)
    templates = template_effectiveness(store, window)
    suggestions: list[OptimizationSuggestion] = []
    suggestions.extend(_suggestions_improver_accept_rate(funnel))
    suggestions.extend(_suggestions_improver_timeouts(funnel))
    suggestions.extend(_suggestions_rejection_reasons(funnel))
    suggestions.extend(_suggestions_template_effectiveness(store, templates))
    suggestions.extend(_suggestions_from_patterns(store, window, templates))
    suggestions.extend(_suggestions_from_feedback(feedback))

    if runtime_overrides:
        suggestions = [
            item
            for item in suggestions
            if not (
                item.apply_action == APPLY_RUNTIME_SETTING
                and _runtime_setting_already_applied(
                    runtime_overrides, item.setting_key, item.setting_value
                )
            )
        ]

    priority_order = {"high": 0, "medium": 1, "low": 2}

    def _display_sort_key(item: OptimizationSuggestion) -> tuple[int, int]:
        applyable_rank = 0 if item.apply_action else 1
        return (applyable_rank, priority_order.get(item.priority, 9))

    return sorted(suggestions, key=_display_sort_key)



def generate_llm_optimization_narrative(
    store: UsageStore,
    window: UsageWindow,
    engine: Engine,
    *,
    model: str | None = None,
) -> str | None:
    """Return an optional LLM narrative summarizing funnel stats; ``None`` when unavailable."""
    funnel = summarize_improver(store, window)
    if funnel.total_fired < 3:
        return None
    suggestions = generate_optimization_suggestions(store, window)[:5]
    evidence = {
        "accept_rate": round(funnel.accept_rate, 3),
        "validation_rate": round(funnel.validation_rate, 3),
        "total_fired": funnel.total_fired,
        "top_rejections": funnel.top_rejection_reasons,
        "suggestions": [serialize_suggestion(item) for item in suggestions],
    }
    completion = engine.complete(
        [
            {"role": "system", "content": _NARRATIVE_SYSTEM},
            {"role": "user", "content": json.dumps(evidence)},
        ],
        activity="reason",
        model=model,
        improver_fired=False,
    )
    if not completion.success:
        logger.debug("optimization narrative LLM failed: %s", completion.error)
        return None
    text = completion.content.strip()
    return text or None


def _current_preferred_ids(store: UsageStore) -> frozenset[str]:
    """Return template ids listed in ``retrieval_preferred_template_ids``."""
    try:
        from ylang.core.runtime_settings import RuntimeSettingsStore

        raw = RuntimeSettingsStore(store._connection).get(  # type: ignore[attr-defined]
            "retrieval_preferred_template_ids"
        )
    except Exception:  # noqa: BLE001 — settings table may be absent
        return frozenset()
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _preferred_ids_with(store: UsageStore, template_id: str) -> str:
    """Return CSV of preferred ids with ``template_id`` appended (deduped)."""
    ordered = list(_current_preferred_ids(store))
    if template_id not in ordered:
        ordered.append(template_id)
    return ",".join(ordered)


def _archived_template_ids(store: UsageStore) -> frozenset[str]:
    """Return template ids currently marked ``archived`` in the library table."""
    try:
        rows = store._connection.execute(
            "SELECT template_id FROM templates WHERE visibility = 'archived'"
        ).fetchall()
    except Exception:  # noqa: BLE001 — table may be absent in minimal fixtures
        return frozenset()
    return frozenset(str(row[0]) for row in rows)


def serialize_suggestion(suggestion: OptimizationSuggestion) -> dict[str, str]:
    """Serialize an optimization suggestion for MCP/CLI output."""
    payload: dict[str, str] = {
        "suggestion_id": suggestion.suggestion_id,
        "kind": suggestion.kind,
        "title": suggestion.title,
        "description": suggestion.description,
        "evidence": suggestion.evidence,
        "priority": suggestion.priority,
    }
    if suggestion.apply_action:
        payload["apply_action"] = suggestion.apply_action
    if suggestion.setting_key is not None:
        payload["setting_key"] = suggestion.setting_key
    if suggestion.setting_value is not None:
        payload["setting_value"] = suggestion.setting_value
    if suggestion.template_id is not None:
        payload["template_id"] = suggestion.template_id
    return payload


def serialize_funnel(
    funnel: ImproverFunnelSummary,
    quality: ImproverQualityScores | None = None,
) -> dict[str, object]:
    """Serialize improver funnel summary for MCP/CLI output."""
    by_mode: dict[str, object] = {}
    for mode, stats in funnel.by_mode.items():
        mode_payload: dict[str, object] = {
            "fired": stats.fired,
            "validated": stats.validated,
            "changed": stats.changed,
            "accepted": stats.accepted,
            "accept_rate": round(stats.accepted / stats.fired, 4)
            if stats.fired
            else 0.0,
            "avg_latency_ms": round(stats.avg_latency_ms, 1),
            "avg_cost": round(stats.avg_cost, 6),
            "top_rejection_reasons": stats.top_rejection_reasons,
        }
        if quality is not None:
            mode_perf = quality.performance_by_mode.get(mode)
            mode_payload["performance_ratio"] = (
                round(mode_perf, 4) if mode_perf is not None else None
            )
        by_mode[mode] = mode_payload

    payload: dict[str, object] = {
        "total_fired": funnel.total_fired,
        "total_validated": funnel.total_validated,
        "total_changed": funnel.total_changed,
        "total_accepted": funnel.total_accepted,
        "validation_rate": round(funnel.validation_rate, 4),
        "change_rate": round(funnel.change_rate, 4),
        "accept_rate": round(funnel.accept_rate, 4),
        "top_rejection_reasons": funnel.top_rejection_reasons,
        "by_mode": by_mode,
    }
    if quality is not None:
        payload["polish_ratio"] = (
            round(quality.polish_ratio, 4) if quality.polish_ratio is not None else None
        )
        payload["performance_ratio"] = (
            round(quality.performance_ratio, 4)
            if quality.performance_ratio is not None
            else None
        )
        payload["polish_sample_count"] = quality.polish_sample_count
        payload["polish_kept_as_is_rate"] = (
            round(quality.polish_kept_as_is_rate, 4)
            if quality.polish_kept_as_is_rate is not None
            else None
        )
        payload["avg_edit_distance"] = (
            round(quality.avg_edit_distance, 1)
            if quality.avg_edit_distance is not None
            else None
        )
        payload["avg_latency_ms"] = (
            round(quality.avg_latency_ms, 1)
            if quality.avg_latency_ms is not None
            else None
        )
    return payload


def serialize_template_row(row: TemplateEffectivenessRow) -> dict[str, object]:
    """Serialize one template effectiveness row."""
    return {
        "template_id": row.template_id,
        "injections": row.injections,
        "accepted": row.accepted,
        "validated": row.validated,
        "accept_rate": round(row.accept_rate, 4),
        "avg_cost": round(row.avg_cost, 6),
        "avg_latency_ms": round(row.avg_latency_ms, 1),
    }
