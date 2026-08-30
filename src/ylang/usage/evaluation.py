"""Evaluation signal taxonomy and assembly for control-plane traces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from ylang.usage.experiment_results import VariantOutcome, summarize_experiment_outcomes
from ylang.usage.store import UsageRecord, UsageStore, UsageWindow

SignalClass = Literal[
    "objective",
    "user",
    "behavioral",
    "heuristic",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class ClassifiedSignal:
    """One evaluation signal with an explicit taxonomy class."""

    name: str
    signal_class: SignalClass
    value: object
    n: int | None = None


# Catalog of known Ylang signals (CP-031).
SIGNAL_CATALOG: dict[str, SignalClass] = {
    "completion_success": "objective",
    "latency_ms": "objective",
    "cost": "objective",
    "prompt_tokens": "objective",
    "completion_tokens": "objective",
    "error_class": "objective",
    "fallback_occurred": "objective",
    "improver_validated": "objective",
    "improver_accepted": "user",
    "improver_changed": "objective",
    "edit_distance": "behavioral",
    "accept_rate_window": "heuristic",
    "silence_as_success": "unknown",
}


def classify_signal(name: str) -> SignalClass:
    """Return the taxonomy class for a known signal name."""
    return SIGNAL_CATALOG.get(name, "unknown")


def assemble_evaluation(
    record: UsageRecord,
    *,
    edit_distance: int | None = None,
    accept_rate_window: float | None = None,
    accept_rate_n: int | None = None,
) -> dict[str, Any]:
    """Build ``evaluation_json`` from known signals on a usage row."""
    signals: list[dict[str, Any]] = [
        {
            "name": "completion_success",
            "class": "objective",
            "value": record.success,
        },
        {
            "name": "latency_ms",
            "class": "objective",
            "value": record.latency_ms,
        },
        {
            "name": "cost",
            "class": "objective",
            "value": record.cost,
        },
    ]
    if record.completion_tokens is not None:
        signals.append(
            {
                "name": "completion_tokens",
                "class": "objective",
                "value": record.completion_tokens,
            }
        )
    if record.error_class:
        signals.append(
            {"name": "error_class", "class": "objective", "value": record.error_class}
        )
    if record.fallback_events_json:
        signals.append(
            {"name": "fallback_occurred", "class": "objective", "value": True}
        )
    if record.improver_fired:
        if record.improver_accepted is not None:
            signals.append(
                {
                    "name": "improver_accepted",
                    "class": "user",
                    "value": record.improver_accepted,
                }
            )
        if record.improver_validated is not None:
            signals.append(
                {
                    "name": "improver_validated",
                    "class": "objective",
                    "value": record.improver_validated,
                }
            )
        if record.improver_changed is not None:
            signals.append(
                {
                    "name": "improver_changed",
                    "class": "objective",
                    "value": record.improver_changed,
                }
            )
    if edit_distance is not None:
        signals.append(
            {
                "name": "edit_distance",
                "class": "behavioral",
                "value": edit_distance,
            }
        )
    if accept_rate_window is not None:
        entry: dict[str, Any] = {
            "name": "accept_rate_window",
            "class": "heuristic",
            "value": accept_rate_window,
        }
        if accept_rate_n is not None:
            entry["n"] = accept_rate_n
        signals.append(entry)
    return {
        "schema": 1,
        "signals": signals,
        "labels": [],
        "notes": "No client task_success supplied",
    }


def evaluation_json_for_write(
    *,
    success: bool,
    latency_ms: int,
    cost: float,
    completion_tokens: int | None,
    error_class: str | None,
    fallback_events: list[dict[str, Any]] | None,
    improver_fired: bool,
    improver_accepted: bool,
) -> str:
    """Compact evaluation payload assembled at Engine write time."""
    record = UsageRecord(
        id=0,
        timestamp=datetime.now(timezone.utc),
        surface="engine",
        activity="other",
        model_used="",
        prompt_tokens=0,
        cost=cost,
        improver_fired=improver_fired,
        improver_accepted=improver_accepted,
        improver_input_sample=None,
        latency_ms=latency_ms,
        success=success,
        completion_tokens=completion_tokens,
        error_class=error_class,
        fallback_events_json=(
            json.dumps(fallback_events) if fallback_events else None
        ),
        improver_validated=None,
        improver_changed=None,
    )
    return json.dumps(assemble_evaluation(record), separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class DimensionCompareRow:
    """One comparable experiment / route / model dimension slice."""

    dimension: str
    key: str
    samples: int
    success_rate: float
    mean_cost: float
    mean_latency_ms: float
    accept_rate: float | None = None


def compare_usage_dimensions(
    store: UsageStore,
    window: UsageWindow,
) -> list[DimensionCompareRow]:
    """Compare model, activity, and surface slices for cost/latency/quality."""
    rows = store.recall_usage(window)
    return (
        _slice_rows(rows, "model", lambda r: r.model_used)
        + _slice_rows(rows, "activity", lambda r: r.activity)
        + _slice_rows(rows, "surface", lambda r: r.surface)
    )


def compare_experiment_variants(
    store: UsageStore,
    window: UsageWindow,
) -> list[VariantOutcome]:
    """Delegate to existing experiment outcome summarizer (CP-033)."""
    return summarize_experiment_outcomes(store, window)


def _slice_rows(
    rows: list[UsageRecord],
    dimension: str,
    key_fn: Any,
) -> list[DimensionCompareRow]:
    buckets: dict[str, list[UsageRecord]] = {}
    for row in rows:
        buckets.setdefault(str(key_fn(row)), []).append(row)
    result: list[DimensionCompareRow] = []
    for key, items in sorted(buckets.items()):
        n = len(items)
        successes = sum(1 for item in items if item.success)
        accepted = [item for item in items if item.improver_fired]
        accept_rate = None
        if accepted:
            accept_rate = sum(1 for item in accepted if item.improver_accepted) / len(
                accepted
            )
        result.append(
            DimensionCompareRow(
                dimension=dimension,
                key=key,
                samples=n,
                success_rate=successes / n if n else 0.0,
                mean_cost=sum(item.cost for item in items) / n if n else 0.0,
                mean_latency_ms=(
                    sum(item.latency_ms for item in items) / n if n else 0.0
                ),
                accept_rate=accept_rate,
            )
        )
    return result
