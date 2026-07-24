"""Tests for experiment config application."""

from __future__ import annotations

import pytest

from ylang.core.engine import Engine
from ylang.core.migrations import run_migrations
from ylang.improver.improver import Improver
from ylang.usage.experiment_config import resolve_experiment_config
from ylang.usage.experiments import ExperimentStore
from ylang.usage.store import open_store


@pytest.fixture
def improver(tmp_path: object) -> Improver:
    store = open_store(tmp_path / "exp.db")  # type: ignore[operator]
    engine = Engine(store, surface="test")
    return Improver(engine)


def test_resolve_experiment_config_known() -> None:
    config = resolve_experiment_config("concise")
    assert "concise" in config.system_prompt_suffix.lower()
    assert config.include_test_plan_scope is False


def test_resolve_unknown_config_defaults_to_control() -> None:
    config = resolve_experiment_config("unknown-hash")
    assert config.config_hash == "control"
    assert config.system_prompt_suffix == ""


def test_experiment_assignment_deterministic(tmp_path: object) -> None:
    import sqlite3

    db = tmp_path / "exp-assign.db"  # type: ignore[operator]
    with sqlite3.connect(db) as connection:
        run_migrations(connection)
        store = ExperimentStore(connection)
        store.upsert_variant(
            experiment_id="improver-agent",
            variant_id="control",
            config_hash="control",
            traffic_pct=50.0,
        )
        store.upsert_variant(
            experiment_id="improver-agent",
            variant_id="variant-a",
            config_hash="concise",
            traffic_pct=50.0,
        )
        first = store.assign_variant("improver-agent", workspace_key="ws-1")
        second = store.assign_variant("improver-agent", workspace_key="ws-1")
        assert first is not None
        assert first.variant_id == second.variant_id


def test_improver_resolve_experiment_applies_suffix(
    improver: Improver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YLANG_EXPERIMENTS", "1")
    run_migrations(improver._engine.store._connection)
    exp = ExperimentStore(improver._engine.store._connection)
    exp.upsert_variant(
        experiment_id="improver-agent",
        variant_id="verbose-only",
        config_hash="verbose",
        traffic_pct=100.0,
    )
    variant_id, system_prompt = improver._resolve_experiment("agent")
    assert variant_id == "verbose-only"
    assert "Experiment variant (verbose)" in system_prompt
