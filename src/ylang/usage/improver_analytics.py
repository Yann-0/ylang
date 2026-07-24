"""Improver funnel and template effectiveness analytics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from ylang.usage.aggregates import _cached_recall_usage
from ylang.usage.feedback import FeedbackEvent
from ylang.usage.store import UsageRecord, UsageStore, UsageWindow

if TYPE_CHECKING:
    from ylang.usage.feedback import FeedbackStore


class _ModeBucket(TypedDict):
    """Mutable per-mode counters while building funnel stats."""

    fired: int
    validated: int
    changed: int
    accepted: int
    latency_sum: int
    cost_sum: float
    rejections: dict[str, int]

_IMPROVE_PREFIX = "improve:"
_MIN_TEMPLATE_SAMPLES = 3
#: BL-010 p50 latency target used by :func:`compute_performance_ratio`.
PERFORMANCE_TARGET_LATENCY_MS = 8000.0


@dataclass(frozen=True, slots=True)
class ImproverModeStats:
    """Improver funnel metrics for one Cursor mode."""

    mode: str
    fired: int
    validated: int
    changed: int
    accepted: int
    avg_latency_ms: float
    avg_cost: float
    top_rejection_reasons: dict[str, int]


@dataclass(frozen=True, slots=True)
class ImproverFunnelSummary:
    """Aggregated improver funnel across all modes."""

    total_fired: int
    total_validated: int
    total_changed: int
    total_accepted: int
    validation_rate: float
    change_rate: float
    accept_rate: float
    by_mode: dict[str, ImproverModeStats]
    top_rejection_reasons: dict[str, int]


@dataclass(frozen=True, slots=True)
class TemplateEffectivenessRow:
    """Acceptance and cost stats for one template injected into improver context."""

    template_id: str
    injections: int
    accepted: int
    validated: int
    accept_rate: float
    avg_cost: float
    avg_latency_ms: float


@dataclass(frozen=True, slots=True)
class ImproverQualityScores:
    """Polish and performance ratios explaining improver effectiveness."""

    polish_ratio: float | None
    performance_ratio: float | None
    polish_sample_count: int
    polish_kept_as_is_rate: float | None
    avg_edit_distance: float | None
    avg_latency_ms: float | None
    performance_by_mode: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class ImproverAnalyticsReport:
    """Funnel summary plus polish/performance quality scores."""

    funnel: ImproverFunnelSummary
    quality: ImproverQualityScores


def compute_performance_ratio(
    accept_rate: float,
    avg_latency_ms: float | None,
    *,
    target_latency_ms: float = PERFORMANCE_TARGET_LATENCY_MS,
) -> float | None:
    """Return accept×latency efficiency in ``[0, 1]``, or ``None`` when unknown.

    Formula: ``accept_rate * min(1.0, target_latency_ms / avg_latency_ms)``.
    """
    if avg_latency_ms is None or avg_latency_ms <= 0:
        return None
    latency_factor = min(1.0, target_latency_ms / avg_latency_ms)
    return max(0.0, min(1.0, accept_rate * latency_factor))


def compute_polish_ratio_from_edits(
    events: list[FeedbackEvent],
) -> tuple[float | None, int, float | None, float | None]:
    """Derive polish stats from ``prompt_edit`` feedback events.

    Returns ``(polish_ratio, sample_count, kept_as_is_rate, avg_edit_distance)``.
    Polish is the mean of ``1 - edit_distance / max(len(original), 1)`` clamped
    to ``[0, 1]``. Returns ``None`` polish when there are no usable samples.
    """
    ratios: list[float] = []
    distances: list[int] = []
    kept = 0
    for event in events:
        distance = event.edit_distance
        if distance is None:
            continue
        original = (event.original_text or "").strip()
        denom = max(len(original), 1)
        ratio = 1.0 - (float(distance) / float(denom))
        ratios.append(max(0.0, min(1.0, ratio)))
        distances.append(int(distance))
        if distance == 0:
            kept += 1
    sample_count = len(ratios)
    if sample_count == 0:
        return None, 0, None, None
    polish = sum(ratios) / sample_count
    kept_rate = kept / sample_count
    avg_distance = sum(distances) / sample_count
    return polish, sample_count, kept_rate, avg_distance


def weighted_avg_latency_ms(funnel: ImproverFunnelSummary) -> float | None:
    """Return fired-weighted average latency across modes, or ``None`` when empty."""
    if funnel.total_fired <= 0:
        return None
    total = sum(
        stats.avg_latency_ms * stats.fired for stats in funnel.by_mode.values()
    )
    return total / funnel.total_fired if funnel.total_fired else None


def summarize_improver_quality(
    store: UsageStore,
    window: UsageWindow,
    feedback: FeedbackStore | None = None,
) -> ImproverAnalyticsReport:
    """Build funnel stats plus polish/performance ratios for ``window``."""
    funnel = summarize_improver(store, window)
    avg_latency = weighted_avg_latency_ms(funnel)
    performance = (
        compute_performance_ratio(funnel.accept_rate, avg_latency)
        if funnel.total_fired > 0
        else None
    )
    performance_by_mode: dict[str, float | None] = {}
    for mode, stats in funnel.by_mode.items():
        mode_accept = stats.accepted / stats.fired if stats.fired else 0.0
        performance_by_mode[mode] = (
            compute_performance_ratio(mode_accept, stats.avg_latency_ms)
            if stats.fired > 0
            else None
        )

    polish: float | None = None
    polish_sample_count = 0
    kept_rate: float | None = None
    avg_edit: float | None = None
    if feedback is not None:
        edits = feedback.recall_edits(window)
        polish, polish_sample_count, kept_rate, avg_edit = (
            compute_polish_ratio_from_edits(edits)
        )

    quality = ImproverQualityScores(
        polish_ratio=polish,
        performance_ratio=performance,
        polish_sample_count=polish_sample_count,
        polish_kept_as_is_rate=kept_rate,
        avg_edit_distance=avg_edit,
        avg_latency_ms=avg_latency,
        performance_by_mode=performance_by_mode,
    )
    return ImproverAnalyticsReport(funnel=funnel, quality=quality)


def _is_improver_row(row: UsageRecord) -> bool:
    if row.improver_rejection_reason == "improver timeout orphan":
        return False
    return row.improver_fired or row.activity.startswith(_IMPROVE_PREFIX)


def _resolve_mode(row: UsageRecord) -> str:
    if row.cursor_mode:
        return row.cursor_mode
    if row.activity.startswith(_IMPROVE_PREFIX):
        return row.activity.removeprefix(_IMPROVE_PREFIX)
    return "unknown"


def _parse_template_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _collect_template_injection_stats(
    store: UsageStore,
    window: UsageWindow,
) -> dict[str, dict[str, float | int]]:
    """Aggregate per-template improver injection metrics within a time window."""
    rows = [row for row in _cached_recall_usage(store, window) if _is_improver_row(row)]
    stats: dict[str, dict[str, float | int]] = {}
    for row in rows:
        for template_id in _parse_template_ids(row.improver_context_templates):
            bucket = stats.setdefault(
                template_id,
                {
                    "injections": 0,
                    "accepted": 0,
                    "validated": 0,
                    "cost_sum": 0.0,
                    "latency_sum": 0,
                },
            )
            bucket["injections"] = int(bucket["injections"]) + 1
            bucket["cost_sum"] = float(bucket["cost_sum"]) + row.cost
            bucket["latency_sum"] = int(bucket["latency_sum"]) + row.latency_ms
            if row.improver_accepted:
                bucket["accepted"] = int(bucket["accepted"]) + 1
            if row.improver_validated:
                bucket["validated"] = int(bucket["validated"]) + 1
    return stats


def template_injection_counts(
    store: UsageStore,
    window: UsageWindow,
) -> dict[str, int]:
    """Return how many times each template was injected into improver context."""
    stats = _collect_template_injection_stats(store, window)
    return {
        template_id: int(bucket["injections"]) for template_id, bucket in stats.items()
    }


def summarize_improver(store: UsageStore, window: UsageWindow) -> ImproverFunnelSummary:
    """Build improver fired → validated → changed → accepted funnel statistics."""
    rows = [row for row in _cached_recall_usage(store, window) if _is_improver_row(row)]
    by_mode: dict[str, _ModeBucket] = {}
    global_rejections: dict[str, int] = {}

    for row in rows:
        mode = _resolve_mode(row)
        bucket = by_mode.setdefault(
            mode,
            {
                "fired": 0,
                "validated": 0,
                "changed": 0,
                "accepted": 0,
                "latency_sum": 0,
                "cost_sum": 0.0,
                "rejections": {},
            },
        )
        bucket["fired"] += 1
        bucket["latency_sum"] += row.latency_ms
        bucket["cost_sum"] += row.cost
        if row.improver_validated:
            bucket["validated"] += 1
        if row.improver_changed:
            bucket["changed"] += 1
        if row.improver_accepted:
            bucket["accepted"] += 1
        if row.improver_rejection_reason:
            reason = row.improver_rejection_reason
            rejections = bucket["rejections"]
            rejections[reason] = rejections.get(reason, 0) + 1
            global_rejections[reason] = global_rejections.get(reason, 0) + 1

    mode_stats: dict[str, ImproverModeStats] = {}
    for mode, bucket in by_mode.items():
        fired = bucket["fired"]
        rejections = bucket["rejections"]
        mode_stats[mode] = ImproverModeStats(
            mode=mode,
            fired=fired,
            validated=bucket["validated"],
            changed=bucket["changed"],
            accepted=bucket["accepted"],
            avg_latency_ms=bucket["latency_sum"] / fired if fired else 0.0,
            avg_cost=bucket["cost_sum"] / fired if fired else 0.0,
            top_rejection_reasons=dict(
                sorted(rejections.items(), key=lambda item: item[1], reverse=True)[:5]
            ),
        )

    total_fired = len(rows)
    total_validated = sum(1 for row in rows if row.improver_validated)
    total_changed = sum(1 for row in rows if row.improver_changed)
    total_accepted = sum(1 for row in rows if row.improver_accepted)

    return ImproverFunnelSummary(
        total_fired=total_fired,
        total_validated=total_validated,
        total_changed=total_changed,
        total_accepted=total_accepted,
        validation_rate=total_validated / total_fired if total_fired else 0.0,
        change_rate=total_changed / total_fired if total_fired else 0.0,
        accept_rate=total_accepted / total_fired if total_fired else 0.0,
        by_mode=mode_stats,
        top_rejection_reasons=dict(
            sorted(global_rejections.items(), key=lambda item: item[1], reverse=True)[
                :10
            ]
        ),
    )


def template_effectiveness(
    store: UsageStore,
    window: UsageWindow,
    *,
    min_samples: int = _MIN_TEMPLATE_SAMPLES,
) -> list[TemplateEffectivenessRow]:
    """Rank templates by accept rate when injected into improver context."""
    stats = _collect_template_injection_stats(store, window)
    results: list[TemplateEffectivenessRow] = []
    for template_id, bucket in stats.items():
        injections = int(bucket["injections"])
        if injections < min_samples:
            continue
        accepted = int(bucket["accepted"])
        results.append(
            TemplateEffectivenessRow(
                template_id=template_id,
                injections=injections,
                accepted=accepted,
                validated=int(bucket["validated"]),
                accept_rate=accepted / injections,
                avg_cost=float(bucket["cost_sum"]) / injections,
                avg_latency_ms=int(bucket["latency_sum"]) / injections,
            )
        )
    return sorted(
        results, key=lambda item: (item.accept_rate, item.injections), reverse=True
    )
