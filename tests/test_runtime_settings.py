"""Tests for runtime settings store and merge."""

from __future__ import annotations

import sqlite3

import pytest

from ylang.core.migrations import run_migrations
from ylang.core.runtime_settings import RuntimeSettingsStore, merge_settings, effective_int_setting
from ylang.settings import Settings


def test_runtime_settings_roundtrip(tmp_path: object) -> None:
    db = tmp_path / "runtime.db"  # type: ignore[operator]
    with sqlite3.connect(db) as connection:
        run_migrations(connection)
        store = RuntimeSettingsStore(connection)
        row = store.set("daily_budget_usd", "12.5")
        assert row.key == "daily_budget_usd"
        assert store.get("daily_budget_usd") == "12.5"
        assert len(store.list_all()) == 1
        assert store.delete("daily_budget_usd") is True
        assert store.get("daily_budget_usd") is None


def test_merge_settings_applies_overrides() -> None:
    base = Settings()
    merged = merge_settings(
        base,
        {
            "daily_budget_usd": "25",
            "quality_band": "2",
            "fallback_model": "ollama/llama3",
            "models_code": "openai/gpt-4o,anthropic/claude-3-5-sonnet-latest",
        },
    )
    assert merged.daily_budget_usd == 25.0
    assert merged.quality_band == 2
    assert merged.fallback_model == "ollama/llama3"
    assert merged.activity_model_lists["code"][0] == "openai/gpt-4o"


def test_effective_int_setting_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YLANG_LEARNED_TEMPLATE_LIMIT", "3")
    assert (
        effective_int_setting(
            "learned_template_limit",
            env_var="YLANG_LEARNED_TEMPLATE_LIMIT",
            default=2,
            overrides={"learned_template_limit": "5"},
        )
        == 5
    )
    assert (
        effective_int_setting(
            "learned_template_limit",
            env_var="YLANG_LEARNED_TEMPLATE_LIMIT",
            default=2,
            overrides=None,
        )
        == 3
    )
    monkeypatch.delenv("YLANG_LEARNED_TEMPLATE_LIMIT", raising=False)
    assert (
        effective_int_setting(
            "learned_template_limit",
            env_var="YLANG_LEARNED_TEMPLATE_LIMIT",
            default=2,
        )
        == 2
    )
