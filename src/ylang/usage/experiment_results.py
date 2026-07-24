"""Experiment outcome stats from usage rows."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ylang.usage.aggregates import _cached_recall_usage
from ylang.usage.store import UsageStore, UsageWindow


@dataclass(frozen=True, slots=True)
class VariantOutcome:
    """Aggregated improver outcomes for one experiment variant."""

    variant_id: str
    config_hash: str
    samples: int
    accepted: int
    validated: int
    accept_rate: float


def _variant_config_map(connection: sqlite3.Connection) -> dict[str, str]:
    cursor = connection.execute(
        "SELECT variant_id, config_hash FROM prompt_experiments"
    )
    return {str(row[0]): str(row[1]) for row in cursor.fetchall()}


def summarize_experiment_outcomes(
    store: UsageStore,
    window: UsageWindow,
) -> list[VariantOutcome]:
    """Aggregate improver accept/validation rates per experiment variant."""
    config_map = _variant_config_map(store._connection)
    rows = _cached_recall_usage(store, window)
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        if not row.improver_fired or not row.experiment_variant:
            continue
        variant_id = row.experiment_variant
        bucket = buckets.setdefault(
            variant_id,
            {"samples": 0, "accepted": 0, "validated": 0},
        )
        bucket["samples"] += 1
        if row.improver_accepted:
            bucket["accepted"] += 1
        if row.improver_validated:
            bucket["validated"] += 1
    outcomes: list[VariantOutcome] = []
    for variant_id, counts in sorted(buckets.items()):
        samples = counts["samples"]
        accepted = counts["accepted"]
        validated = counts["validated"]
        outcomes.append(
            VariantOutcome(
                variant_id=variant_id,
                config_hash=config_map.get(variant_id, "unknown"),
                samples=samples,
                accepted=accepted,
                validated=validated,
                accept_rate=accepted / samples if samples else 0.0,
            )
        )
    return outcomes
