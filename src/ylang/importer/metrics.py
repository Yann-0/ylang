"""Local prompt-intelligence metrics. Import volume is not the product goal."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ylang.importer.evaluate import (
    MIN_OUTCOME_SAMPLES,
    PromotedOutcomeDelta,
    classify_outcome_delta,
    measure_template,
)
from ylang.importer.source_store import PromptSourceStore
from ylang.library.effectiveness import build_effectiveness_scores
from ylang.library.store import Library
from ylang.usage.store import UsageStore


@dataclass(frozen=True, slots=True)
class PromptIntelligenceMetrics:
    """Local counts plus whether promoted prompts are actually used."""

    sources: int
    enabled_sources: int
    source_errors: int
    candidates_new: int
    candidates_changed: int
    removed_upstream: int
    duplicates: int
    quarantined: int
    reviewed: int
    promoted: int
    rejected: int
    promoted_used: int
    promoted_with_accept: int
    promoted_improved: int
    promoted_regressed: int
    promoted_pending_outcome: int


def pending_review_count(connection: sqlite3.Connection) -> int:
    """Count candidates awaiting human review."""
    try:
        row = connection.execute(
            """
            SELECT COUNT(*) FROM prompt_source_items
            WHERE candidate_state IN (
                'candidate_new', 'candidate_changed', 'quarantined', 'reviewed'
            )
            """
        ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0


def promoted_outcome_deltas(
    store: PromptSourceStore,
    library: Library,
    usage: UsageStore,
    *,
    min_samples: int = MIN_OUTCOME_SAMPLES,
) -> list[PromotedOutcomeDelta]:
    """Compare post-promotion usage to the snapshot taken at promote time."""
    deltas: list[PromotedOutcomeDelta] = []
    seen: set[str] = set()
    for baseline in store.list_promotion_baselines():
        if baseline.template_id in seen:
            continue
        seen.add(baseline.template_id)
        current = measure_template(library, usage, baseline.template_id)
        status, accept_delta = classify_outcome_delta(
            baseline_accept_rate=baseline.accept_rate,
            current_accept_rate=current.accept_rate,
            current_injections=current.injections,
            min_samples=min_samples,
        )
        cost_delta = None
        if baseline.avg_cost is not None and current.avg_cost is not None:
            cost_delta = round(current.avg_cost - baseline.avg_cost, 6)
        latency_delta = None
        if baseline.avg_latency_ms is not None and current.avg_latency_ms is not None:
            latency_delta = round(current.avg_latency_ms - baseline.avg_latency_ms, 1)
        deltas.append(
            PromotedOutcomeDelta(
                template_id=baseline.template_id,
                version=baseline.version,
                item_id=baseline.item_id,
                baseline_accept_rate=baseline.accept_rate,
                current_accept_rate=current.accept_rate,
                accept_delta=accept_delta,
                cost_delta=cost_delta,
                latency_delta=latency_delta,
                current_injections=current.injections,
                status=status,
            )
        )
    return deltas


def collect_metrics(
    store: PromptSourceStore,
    usage: UsageStore | None = None,
    *,
    library: Library | None = None,
) -> PromptIntelligenceMetrics:
    """Aggregate source/candidate counts and promoted-template usage."""
    sources = store.list_sources()
    items = store.list_items(limit=50_000)
    by_state: dict[str, int] = {}
    duplicates = 0
    for item in items:
        by_state[item.candidate_state] = by_state.get(item.candidate_state, 0) + 1
        if item.duplicate_of_item_id or item.duplicate_template_id:
            duplicates += 1
    promoted_ids = {
        item.linked_template_id
        for item in items
        if item.candidate_state == "promoted" and item.linked_template_id
    }
    used = 0
    with_accept = 0
    improved = 0
    regressed = 0
    pending = 0
    if usage is not None and promoted_ids:
        scores = build_effectiveness_scores(usage, min_samples=1)
        from ylang.usage.improver_analytics import template_injection_counts
        from ylang.usage.store import UsageWindow

        injections = template_injection_counts(usage, UsageWindow.all_time())
        for template_id in promoted_ids:
            if injections.get(template_id, 0) > 0:
                used += 1
            if scores.get(template_id, 0) > 0:
                with_accept += 1
        if library is not None:
            for delta in promoted_outcome_deltas(store, library, usage):
                if delta.status == "improved":
                    improved += 1
                elif delta.status == "regressed":
                    regressed += 1
                else:
                    pending += 1
    error_sources = sum(1 for source in sources if source.last_error)
    return PromptIntelligenceMetrics(
        sources=len(sources),
        enabled_sources=sum(1 for source in sources if source.enabled),
        source_errors=error_sources,
        candidates_new=by_state.get("candidate_new", 0),
        candidates_changed=by_state.get("candidate_changed", 0),
        removed_upstream=by_state.get("removed_upstream", 0),
        duplicates=duplicates,
        quarantined=by_state.get("quarantined", 0),
        reviewed=by_state.get("reviewed", 0),
        promoted=by_state.get("promoted", 0),
        rejected=by_state.get("rejected", 0),
        promoted_used=used,
        promoted_with_accept=with_accept,
        promoted_improved=improved,
        promoted_regressed=regressed,
        promoted_pending_outcome=pending,
    )
