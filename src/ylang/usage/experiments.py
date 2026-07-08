"""Prompt A/B experiment assignment and management."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExperimentVariant:
    """One variant in a prompt experiment."""

    experiment_id: str
    variant_id: str
    config_hash: str
    traffic_pct: float
    active: bool


class ExperimentStore:
    """Manage prompt experiment variants in SQLite."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert_variant(
        self,
        *,
        experiment_id: str,
        variant_id: str,
        config_hash: str,
        traffic_pct: float = 50.0,
        active: bool = True,
    ) -> ExperimentVariant:
        """Create or update an experiment variant."""
        self._connection.execute(
            """
            INSERT INTO prompt_experiments (
                experiment_id, variant_id, config_hash, traffic_pct, active
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(experiment_id, variant_id) DO UPDATE SET
                config_hash = excluded.config_hash,
                traffic_pct = excluded.traffic_pct,
                active = excluded.active
            """,
            (experiment_id, variant_id, config_hash, traffic_pct, int(active)),
        )
        self._connection.commit()
        return ExperimentVariant(
            experiment_id=experiment_id,
            variant_id=variant_id,
            config_hash=config_hash,
            traffic_pct=traffic_pct,
            active=active,
        )

    def list_active(self, experiment_id: str) -> list[ExperimentVariant]:
        """Return active variants for an experiment."""
        cursor = self._connection.execute(
            """
            SELECT experiment_id, variant_id, config_hash, traffic_pct, active
            FROM prompt_experiments
            WHERE experiment_id = ? AND active = 1
            ORDER BY variant_id
            """,
            (experiment_id,),
        )
        return [
            ExperimentVariant(
                experiment_id=str(row[0]),
                variant_id=str(row[1]),
                config_hash=str(row[2]),
                traffic_pct=float(row[3]),
                active=bool(row[4]),
            )
            for row in cursor.fetchall()
        ]

    def assign_variant(
        self,
        experiment_id: str,
        *,
        workspace_key: str = "default",
    ) -> ExperimentVariant | None:
        """Deterministically assign a variant based on workspace key."""
        variants = self.list_active(experiment_id)
        if not variants:
            return None
        digest = hashlib.sha256(f"{experiment_id}:{workspace_key}".encode()).hexdigest()
        bucket = int(digest[:8], 16) % 100
        cumulative = 0.0
        for variant in variants:
            cumulative += variant.traffic_pct
            if bucket < cumulative:
                return variant
        return variants[-1]
