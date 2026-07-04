"""Unit tests for activity-based model routing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ylang.core.model_router import ModelRouter, resolve_explicit_model
from ylang.settings import ProviderKeys
from ylang.usage.store import open_store


@pytest.fixture
def router() -> ModelRouter:
    return ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o", "anthropic/claude-3-5-sonnet-latest"],
            "search": ["perplexity/sonar"],
            "reason": ["openai/o3-mini"],
            "improve": ["anthropic/claude-3-5-sonnet-latest", "openai/gpt-4o"],
            "other": ["mistral/mistral-small-latest"],
        },
        provider_keys=ProviderKeys(openai="k", anthropic="k"),
        fallback_model="ollama/qwen2.5",
    )


def test_activity_for_improve_prefix(router: ModelRouter) -> None:
    assert router.activity_for("improve:agent") == "code"
    assert router.activity_for("improve:ask") == "reason"
    assert router.activity_for("improve:plan") == "reason"
    assert router.activity_for("improve:debug") == "code"
    assert router.activity_for("improve:edit_file") == "improve"
    assert router.activity_for("code") == "code"
    assert router.activity_for("unknown") == "other"


def test_resolve_cursor_slug_alias() -> None:
    assert resolve_explicit_model("claude-4.6-sonnet-high-thinking") == (
        "anthropic/claude-sonnet-4-6"
    )
    assert resolve_explicit_model("claude-sonnet-4-5") == "anthropic/claude-sonnet-4-6"


def test_resolve_unknown_slug_returns_none() -> None:
    assert resolve_explicit_model("not-a-real-model-slug-xyz") is None


def test_build_attempt_chain_includes_explicit_and_fallback(router: ModelRouter) -> None:
    chain = router.build_attempt_chain("code", explicit_model="openai/gpt-4o")
    assert chain[0] == "openai/gpt-4o"
    assert "ollama/qwen2.5" in chain


def test_provider_cooldown_skips_provider(router: ModelRouter) -> None:
    router.cooldown.mark_failed("openai/gpt-4o")
    assert router.is_available("openai/gpt-4o") is False
    assert router.candidate_status("openai/gpt-4o") == "skipped:cooldown"


def test_budget_filter_drops_cloud_models_when_over_budget(tmp_path: object) -> None:
    store = open_store(tmp_path / "budget.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    for _ in range(3):
        store.write_usage(
            surface="test",
            activity="code",
            model_used="openai/gpt-4o",
            prompt_tokens=1000,
            cost=5.0,
            improver_fired=False,
            improver_accepted=False,
            latency_ms=1,
            success=True,
            timestamp=now - timedelta(hours=1),
        )
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k"),
        fallback_model="ollama/qwen2.5",
        usage_store=store,
        daily_budget_usd=10.0,
    )
    ordered = router.ordered_candidates("code")
    assert ordered == []
    chain = router.build_attempt_chain("code")
    assert chain[-1] == "ollama/qwen2.5"


def test_preference_order_boosts_successful_models(tmp_path: object) -> None:
    store = open_store(tmp_path / "pref.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    for _ in range(5):
        store.write_usage(
            surface="test",
            activity="code",
            model_used="anthropic/claude-3-5-sonnet-latest",
            prompt_tokens=1,
            cost=0.0,
            improver_fired=False,
            improver_accepted=False,
            latency_ms=1,
            success=True,
            timestamp=now - timedelta(hours=1),
        )
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o", "anthropic/claude-3-5-sonnet-latest"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k", anthropic="k"),
        fallback_model="ollama/qwen2.5",
        usage_store=store,
    )
    ordered = router.ordered_candidates("code")
    assert ordered[0] == "anthropic/claude-3-5-sonnet-latest"
