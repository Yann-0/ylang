"""Improver funnel and template effectiveness analytics."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.usage.aggregates import _cached_recall_usage
from ylang.usage.store import UsageRecord, UsageStore, UsageWindow

_IMPROVE_PREFIX = "improve:"
_MIN_TEMPLATE_SAMPLES = 3


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


def _is_improver_row(row: UsageRecord) -> bool:
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


def summarize_improver(store: UsageStore, window: UsageWindow) -> ImproverFunnelSummary:
    """Build improver fired → validated → changed → accepted funnel statistics."""
    rows = [row for row in _cached_recall_usage(store, window) if _is_improver_row(row)]
    by_mode: dict[str, dict[str, object]] = {}
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
        bucket["fired"] = int(bucket["fired"]) + 1
        bucket["latency_sum"] = int(bucket["latency_sum"]) + row.latency_ms
        bucket["cost_sum"] = float(bucket["cost_sum"]) + row.cost
        if row.improver_validated:
            bucket["validated"] = int(bucket["validated"]) + 1
        if row.improver_changed:
            bucket["changed"] = int(bucket["changed"]) + 1
        if row.improver_accepted:
            bucket["accepted"] = int(bucket["accepted"]) + 1
        if row.improver_rejection_reason:
            reason = row.improver_rejection_reason
            rejections = bucket["rejections"]
            assert isinstance(rejections, dict)
            rejections[reason] = rejections.get(reason, 0) + 1
            global_rejections[reason] = global_rejections.get(reason, 0) + 1

    mode_stats: dict[str, ImproverModeStats] = {}
    for mode, bucket in by_mode.items():
        fired = int(bucket["fired"])
        rejections = bucket["rejections"]
        assert isinstance(rejections, dict)
        mode_stats[mode] = ImproverModeStats(
            mode=mode,
            fired=fired,
            validated=int(bucket["validated"]),
            changed=int(bucket["changed"]),
            accepted=int(bucket["accepted"]),
            avg_latency_ms=int(bucket["latency_sum"]) / fired if fired else 0.0,
            avg_cost=float(bucket["cost_sum"]) / fired if fired else 0.0,
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
            sorted(global_rejections.items(), key=lambda item: item[1], reverse=True)[:10]
        ),
    )


def template_effectiveness(
    store: UsageStore,
    window: UsageWindow,
    *,
    min_samples: int = _MIN_TEMPLATE_SAMPLES,
) -> list[TemplateEffectivenessRow]:
    """Rank templates by accept rate when injected into improver context."""
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
    return sorted(results, key=lambda item: (item.accept_rate, item.injections), reverse=True)
