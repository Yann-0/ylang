"""Unit tests for activity-based model routing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ylang.core.model_router import (
    ModelRouter,
    resolve_explicit_model,
    resolve_improver_explicit_model,
)
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
    assert router.activity_for("improve:agent") == "improve"
    assert router.activity_for("improve:ask") == "improve"
    assert router.activity_for("improve:plan") == "improve"
    assert router.activity_for("improve:debug") == "improve"
    assert router.activity_for("improve:multitask") == "improve"
    assert router.activity_for("improve:edit_file") == "improve"
    assert router.activity_for("code") == "code"
    assert router.activity_for("unknown") == "other"


def test_resolve_auto_sentinel_uses_activity_routing() -> None:
    assert resolve_explicit_model("auto") is None
    assert resolve_explicit_model("default") is None
    assert resolve_explicit_model("") is None
    assert resolve_explicit_model("  route  ") is None


def test_resolve_cursor_slug_alias() -> None:
    assert resolve_explicit_model("claude-4.6-sonnet-high-thinking") == (
        "anthropic/claude-sonnet-5"
    )
    assert resolve_explicit_model("claude-sonnet-4-5") == "anthropic/claude-sonnet-5"
    assert resolve_explicit_model("gpt-5.5-medium") == "openai/gpt-5.5"
    assert resolve_explicit_model("gpt-5.3-codex-high-fast") == "openai/gpt-5.5"
    assert resolve_explicit_model("gemini-3.1-pro") == "gemini/gemini-3.7-flash"
    assert resolve_explicit_model("claude-4.6-opus-high-thinking") == (
        "anthropic/claude-opus-5"
    )


def test_resolve_claude_prefix_rules_map_to_claude_5() -> None:
    assert resolve_explicit_model("claude-sonnet-4-9-custom") == (
        "anthropic/claude-sonnet-5"
    )
    assert resolve_explicit_model("claude-opus-4-9-custom") == "anthropic/claude-opus-5"
    assert resolve_explicit_model("claude-fable-preview") == "anthropic/claude-fable-5"


def test_resolve_gpt_4o_mini_slug_maps_to_local_ollama() -> None:
    """Cursor ``gpt-4o-mini`` is a local Ollama tag; avoid OpenAI BYOK rate limits."""
    assert resolve_explicit_model("gpt-4o-mini") == "ollama/qwen-coder-14b"
    assert resolve_explicit_model("ollama/gpt-4o-mini") == "ollama/qwen-coder-14b"
    assert resolve_explicit_model("ylang-mini") == "ollama/qwen-coder-14b"
    # Real OpenAI remains available via explicit LiteLLM form.
    assert resolve_explicit_model("openai/gpt-4o-mini") == "openai/gpt-4o-mini"


def test_resolve_improver_fast_slug_defers_to_activity_routing() -> None:
    assert resolve_improver_explicit_model("auto") is None
    assert resolve_improver_explicit_model("composer-2.5-fast") is None
    assert resolve_improver_explicit_model("gpt-5.3-codex-high-fast") is None
    assert resolve_improver_explicit_model("claude-sonnet-4-5") is None
    assert resolve_improver_explicit_model("anthropic/claude-3-5-sonnet-latest") == (
        "anthropic/claude-3-5-sonnet-latest"
    )


def test_resolve_unknown_slug_returns_none() -> None:
    assert resolve_explicit_model("not-a-real-model-slug-xyz") is None


def test_build_attempt_chain_includes_explicit_and_fallback(
    router: ModelRouter,
) -> None:
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



def test_preference_order_uses_improver_accepted_for_improve_bucket(
    tmp_path: object,
) -> None:
    store = open_store(tmp_path / "improve-pref.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    for _ in range(4):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=1,
            cost=0.0,
            improver_fired=True,
            improver_accepted=True,
            latency_ms=1,
            success=True,
            timestamp=now - timedelta(hours=1),
        )
    store.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="anthropic/claude-3-5-sonnet-latest",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=True,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(hours=1),
    )
    router = ModelRouter(
        activity_model_lists={
            "code": ["anthropic/claude-3-5-sonnet-latest", "openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["anthropic/claude-3-5-sonnet-latest", "openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k", anthropic="k"),
        fallback_model="ollama/qwen2.5",
        usage_store=store,
    )
    ordered = router.ordered_candidates("improve")
    assert ordered[0] == "anthropic/claude-3-5-sonnet-latest"


def test_attempt_chain_improve_ignores_cursor_slug_explicit(
    router: ModelRouter,
) -> None:
    chain = router.build_attempt_chain(
        "improve:agent",
        explicit_model="claude-sonnet-4-5",
    )
    assert chain[0] == "anthropic/claude-3-5-sonnet-latest"
    assert "anthropic/claude-sonnet-5" not in chain
    assert "anthropic/claude-sonnet-4-6" not in chain


def test_attempt_chain_improve_honors_litellm_explicit(router: ModelRouter) -> None:
    chain = router.build_attempt_chain(
        "improve:agent",
        explicit_model="openai/gpt-4o",
    )
    assert chain[0] == "openai/gpt-4o"


def test_attempt_chain_boosts_improver_accepted_model_for_code_not_improve(
    tmp_path: object,
) -> None:
    store = open_store(tmp_path / "chain-pref.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    for _ in range(3):
        store.write_usage(
            surface="mcp",
            activity="improve:agent",
            model_used="openai/gpt-4o",
            prompt_tokens=1,
            cost=0.0,
            improver_fired=True,
            improver_accepted=True,
            latency_ms=1,
            success=True,
            timestamp=now - timedelta(hours=1),
        )
    router = ModelRouter(
        activity_model_lists={
            "code": ["anthropic/claude-3-5-sonnet-latest", "openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["anthropic/claude-3-5-sonnet-latest", "openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k", anthropic="k"),
        fallback_model="ollama/qwen2.5",
        usage_store=store,
    )
    chain = router.build_attempt_chain("code")
    assert chain[0] == "openai/gpt-4o"
    assert "anthropic/claude-3-5-sonnet-latest" in chain


def test_default_activity_model_list_heads() -> None:
    from ylang.settings import DEFAULT_ACTIVITY_MODEL_LISTS

    assert DEFAULT_ACTIVITY_MODEL_LISTS["code"][0] == "anthropic/claude-opus-5"
    assert DEFAULT_ACTIVITY_MODEL_LISTS["reason"][0] == "anthropic/claude-fable-5"
    assert DEFAULT_ACTIVITY_MODEL_LISTS["improve"][0] == "anthropic/claude-sonnet-5"
    assert DEFAULT_ACTIVITY_MODEL_LISTS["search"][0] == "perplexity/sonar-pro"
    assert DEFAULT_ACTIVITY_MODEL_LISTS["other"][0] == "anthropic/claude-sonnet-5"
    assert "openai/gpt-5.5" in DEFAULT_ACTIVITY_MODEL_LISTS["code"]
    assert "gemini/gemini-3.7-flash" in DEFAULT_ACTIVITY_MODEL_LISTS["other"]


def test_gemini_skipped_without_key_then_fallback() -> None:
    router = ModelRouter(
        activity_model_lists={
            "code": ["gemini/gemini-3.7-flash", "openai/gpt-5.5"],
            "search": ["openai/gpt-5.5"],
            "reason": ["openai/gpt-5.5"],
            "improve": ["openai/gpt-5.5"],
            "other": ["openai/gpt-5.5"],
        },
        provider_keys=ProviderKeys(openai="k"),
        fallback_model="ollama/qwen2.5",
    )
    assert router.candidate_status("gemini/gemini-3.7-flash") == "skipped:no_key"
    assert router.select_model("code") == "openai/gpt-5.5"
    chain = router.build_attempt_chain("code")
    assert chain[0] == "openai/gpt-5.5"
    assert "gemini/gemini-3.7-flash" not in chain


def test_gemini_available_with_key() -> None:
    from ylang.settings import provider_from_litellm_model

    assert provider_from_litellm_model("gemini/gemini-3.7-flash") == "gemini"
    assert provider_from_litellm_model("google/gemini-3.7-flash") == "gemini"
    router = ModelRouter(
        activity_model_lists={
            "code": ["gemini/gemini-3.7-flash"],
            "search": ["gemini/gemini-3.7-flash"],
            "reason": ["gemini/gemini-3.7-flash"],
            "improve": ["gemini/gemini-3.7-flash"],
            "other": ["gemini/gemini-3.7-flash"],
        },
        provider_keys=ProviderKeys(gemini="k"),
        fallback_model="ollama/qwen2.5",
    )
    assert router.is_available("gemini/gemini-3.7-flash") is True
    assert router.select_model("code") == "gemini/gemini-3.7-flash"
