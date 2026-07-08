"""Propose-only optimization suggestions from usage analytics."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.library.pattern_detector import UsagePatternDetector, propose_template_from_pattern
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import (
    ImproverFunnelSummary,
    TemplateEffectivenessRow,
    summarize_improver,
    template_effectiveness,
)
from ylang.usage.store import UsageStore, UsageWindow


@dataclass(frozen=True, slots=True)
class OptimizationSuggestion:
    """One evidence-backed propose-only optimization suggestion."""

    suggestion_id: str
    kind: str
    title: str
    description: str
    evidence: str
    priority: str


def generate_optimization_suggestions(
    store: UsageStore,
    window: UsageWindow,
    *,
    feedback: FeedbackStore | None = None,
) -> list[OptimizationSuggestion]:
    """Analyze usage and return ranked propose-only optimization suggestions."""
    funnel = summarize_improver(store, window)
    templates = template_effectiveness(store, window)
    suggestions: list[OptimizationSuggestion] = []

    if funnel.total_fired >= 5 and funnel.accept_rate < 0.5:
        suggestions.append(
            OptimizationSuggestion(
                suggestion_id="improver-accept-rate-low",
                kind="improver_tuning",
                title="Improver accept rate is below 50%",
                description=(
                    "Review validation rules or mode guidance for modes with low acceptance. "
                    "Consider saving successful improved prompts as learned templates."
                ),
                evidence=(
                    f"Accept rate {funnel.accept_rate:.0%} over {funnel.total_fired} improver calls "
                    f"({funnel.total_accepted} accepted)."
                ),
                priority="high",
            )
        )

    for reason, count in list(funnel.top_rejection_reasons.items())[:3]:
        suggestions.append(
            OptimizationSuggestion(
                suggestion_id=f"rejection-{reason[:32]}",
                kind="validation",
                title=f"Top rejection reason: {reason}",
                description="Tune improver validation or add salvage path for this failure mode.",
                evidence=f"Rejected {count} times in the lookback window.",
                priority="medium",
            )
        )

    for row in templates[:5]:
        if row.accept_rate >= 0.6:
            suggestions.append(
                OptimizationSuggestion(
                    suggestion_id=f"template-boost-{row.template_id}",
                    kind="template_retrieval",
                    title=f"Boost template '{row.template_id}' in retrieval",
                    description=(
                        "This template correlates with higher accept rates when injected "
                        "into improver context."
                    ),
                    evidence=(
                        f"Accept rate {row.accept_rate:.0%} over {row.injections} injections "
                        f"(avg cost ${row.avg_cost:.4f})."
                    ),
                    priority="high" if row.accept_rate >= 0.75 else "medium",
                )
            )
        elif row.accept_rate <= 0.2 and row.injections >= 5:
            suggestions.append(
                OptimizationSuggestion(
                    suggestion_id=f"template-review-{row.template_id}",
                    kind="template_revision",
                    title=f"Review template '{row.template_id}'",
                    description="Low accept rate when this template is in context; consider revising body.",
                    evidence=(
                        f"Accept rate {row.accept_rate:.0%} over {row.injections} injections."
                    ),
                    priority="medium",
                )
            )

    detector = UsagePatternDetector(store)
    days = max(1, int((window.until - window.since).total_seconds() // 86400))
    patterns = detector.detect(window_days=days)
    for pattern in patterns[:3]:
        proposal = propose_template_from_pattern(pattern)
        if proposal is None:
            continue
        suggestions.append(
            OptimizationSuggestion(
                suggestion_id=f"pattern-{pattern.pattern_id}",
                kind="learned_template",
                title="Save learned template from repeated prompt",
                description=proposal.rationale,
                evidence=(
                    f"Pattern seen {pattern.occurrence_count} times; "
                    f"suggested id: {proposal.suggested_template_id}."
                ),
                priority="medium",
            )
        )

    if feedback is not None:
        edits = [event for event in feedback.recent(limit=20) if event.event_type == "prompt_edit"]
        heavy_edits = [event for event in edits if (event.edit_distance or 0) > 40]
        if len(heavy_edits) >= 3:
            suggestions.append(
                OptimizationSuggestion(
                    suggestion_id="user-edit-drift",
                    kind="improver_tuning",
                    title="Users frequently edit improved prompts heavily",
                    description=(
                        "Captured edit feedback shows large diffs between improved and submitted text. "
                        "Review improver scope expansion rules."
                    ),
                    evidence=f"{len(heavy_edits)} edits with distance > 40 in recent feedback.",
                    priority="high",
                )
            )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(suggestions, key=lambda item: priority_order.get(item.priority, 9))


def serialize_suggestion(suggestion: OptimizationSuggestion) -> dict[str, str]:
    """Serialize an optimization suggestion for MCP/CLI output."""
    return {
        "suggestion_id": suggestion.suggestion_id,
        "kind": suggestion.kind,
        "title": suggestion.title,
        "description": suggestion.description,
        "evidence": suggestion.evidence,
        "priority": suggestion.priority,
    }


def serialize_funnel(funnel: ImproverFunnelSummary) -> dict[str, object]:
    """Serialize improver funnel summary for MCP/CLI output."""
    return {
        "total_fired": funnel.total_fired,
        "total_validated": funnel.total_validated,
        "total_changed": funnel.total_changed,
        "total_accepted": funnel.total_accepted,
        "validation_rate": round(funnel.validation_rate, 4),
        "change_rate": round(funnel.change_rate, 4),
        "accept_rate": round(funnel.accept_rate, 4),
        "top_rejection_reasons": funnel.top_rejection_reasons,
        "by_mode": {
            mode: {
                "fired": stats.fired,
                "validated": stats.validated,
                "changed": stats.changed,
                "accepted": stats.accepted,
                "accept_rate": round(stats.accepted / stats.fired, 4) if stats.fired else 0.0,
                "avg_latency_ms": round(stats.avg_latency_ms, 1),
                "avg_cost": round(stats.avg_cost, 6),
                "top_rejection_reasons": stats.top_rejection_reasons,
            }
            for mode, stats in funnel.by_mode.items()
        },
    }


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
