"""Alias resolution, semantic routing metadata, and fallback reasons."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ylang.core.model_aliases import (
    DEFAULT_CURSOR_SLUG_ALIASES,
    default_aliases_path,
    lookup_compatibility_alias,
)
from ylang.core.model_router import (
    ModelRouter,
    lookup_explicit_model,
    resolve_explicit_model,
)
from ylang.core.routing_reason import build_routing_reason, routing_reason_json
from ylang.settings import ProviderKeys
from ylang.usage.store import open_store


def _router(**kwargs: object) -> ModelRouter:
    lists = {
        "code": ["anthropic/claude-opus-5", "openai/gpt-5.5", "anthropic/claude-sonnet-5"],
        "search": [
            "perplexity/sonar-pro",
            "anthropic/claude-sonnet-5",
            "gemini/gemini-3.7-flash",
        ],
        "reason": ["anthropic/claude-fable-5", "anthropic/claude-opus-5"],
        "improve": ["anthropic/claude-sonnet-5", "openai/gpt-5.5"],
        "other": ["anthropic/claude-sonnet-5", "openai/gpt-5.5"],
    }
    lists.update(kwargs.pop("activity_model_lists", {}))  # type: ignore[arg-type]
    return ModelRouter(
        activity_model_lists=lists,  # type: ignore[arg-type]
        fallback_model="ollama/qwen2.5",
        **kwargs,  # type: ignore[arg-type]
    )


def test_search_activity_default_is_policy_not_identity() -> None:
    router = _router(provider_keys=ProviderKeys(perplexity="k"))
    chain = router.build_attempt_chain("search")
    resolution = router.resolve("search", selected=chain[0], attempt_chain=chain)
    assert resolution.semantic_route == "search"
    assert resolution.resolved_route == "search"
    assert resolution.resolved_model == "perplexity/sonar-pro"
    assert resolution.resolved_provider == "perplexity"
    assert resolution.requested_alias is None
    assert resolution.resolution_reason == "activity_default"


def test_compatibility_alias_preserves_requested_slug() -> None:
    lookup = lookup_explicit_model("gemini-3.1-pro")
    assert lookup.reason == "compatibility_alias"
    assert lookup.requested_alias == "gemini-3.1-pro"
    assert lookup.resolved == "gemini/gemini-3.7-flash"
    assert lookup.resolved != lookup.requested_alias

    router = _router(provider_keys=ProviderKeys(gemini="k"))
    chain = router.build_attempt_chain("search", explicit_model="gemini-3.1-pro")
    assert chain[0] == "gemini/gemini-3.7-flash"
    resolution = router.resolve(
        "search",
        explicit_model="gemini-3.1-pro",
        selected=chain[0],
        attempt_chain=chain,
    )
    assert resolution.requested_alias == "gemini-3.1-pro"
    assert resolution.resolved_model == "gemini/gemini-3.7-flash"
    assert resolution.resolution_reason == "compatibility_alias"
    payload = build_routing_reason(
        router,
        "search",
        attempt_chain=chain,
        selected=chain[0],
        explicit_model="gemini-3.1-pro",
        resolution=resolution,
    )
    assert payload["resolution_reason"] == "compatibility_alias"
    assert payload["requested_alias"] == "gemini-3.1-pro"
    assert any(step["code"] == "compatibility_alias" for step in payload["steps"])


def test_codex_slug_is_compatibility_not_identity() -> None:
    lookup = lookup_explicit_model("gpt-5.3-codex-high-fast")
    assert lookup.reason == "compatibility_alias"
    assert lookup.requested_alias == "gpt-5.3-codex-high-fast"
    assert lookup.resolved == "openai/gpt-5.5"
    assert resolve_explicit_model("gpt-5.3-codex-high-fast") == "openai/gpt-5.5"


def test_explicit_litellm_route_is_honored() -> None:
    router = _router(provider_keys=ProviderKeys(openai="k", anthropic="k"))
    chain = router.build_attempt_chain("code", explicit_model="openai/gpt-5.5")
    assert chain[0] == "openai/gpt-5.5"
    resolution = router.resolve(
        "code",
        explicit_model="openai/gpt-5.5",
        selected=chain[0],
        attempt_chain=chain,
    )
    assert resolution.requested_alias is None
    assert resolution.requested_model == "openai/gpt-5.5"
    assert resolution.resolution_reason == "explicit_model"
    lookup = lookup_explicit_model("openai/gpt-5.5")
    assert lookup.reason == "explicit_model"


def test_unavailable_provider_falls_back_with_reason() -> None:
    router = _router(
        activity_model_lists={
            "code": ["gemini/gemini-3.7-flash", "openai/gpt-5.5"],
            "search": ["openai/gpt-5.5"],
            "reason": ["openai/gpt-5.5"],
            "improve": ["openai/gpt-5.5"],
            "other": ["openai/gpt-5.5"],
        },
        provider_keys=ProviderKeys(openai="k"),
    )
    chain = router.build_attempt_chain("code")
    assert chain[0] == "openai/gpt-5.5"
    assert "gemini/gemini-3.7-flash" not in chain
    resolution = router.resolve("code", selected=chain[0], attempt_chain=chain)
    assert resolution.resolution_reason == "provider_unavailable"
    assert resolution.resolved_model == "openai/gpt-5.5"


def test_local_fallback_when_no_cloud_keys() -> None:
    router = _router(provider_keys=ProviderKeys())
    chain = router.build_attempt_chain("search")
    assert chain[-1] == "ollama/qwen2.5"
    selected = router.select_model("search")
    assert selected == "ollama/qwen2.5"
    resolution = router.resolve("search", selected=selected, attempt_chain=chain)
    assert resolution.resolution_reason == "local_fallback"
    assert resolution.resolved_provider == "ollama"


def test_budget_fallback_reason(tmp_path: object) -> None:
    store = open_store(tmp_path / "budget.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    store.write_usage(
        surface="t",
        activity="code",
        model_used="openai/gpt-5.5",
        prompt_tokens=1,
        cost=2.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(hours=1),
    )
    router = _router(
        activity_model_lists={
            "code": ["openai/gpt-5.5"],
            "search": ["openai/gpt-5.5"],
            "reason": ["openai/gpt-5.5"],
            "improve": ["openai/gpt-5.5"],
            "other": ["openai/gpt-5.5"],
        },
        provider_keys=ProviderKeys(openai="k"),
        usage_store=store,
        daily_budget_usd=1.0,
    )
    chain = router.build_attempt_chain("code")
    selected = router.select_model("code")
    assert selected == "ollama/qwen2.5"
    resolution = router.resolve("code", selected=selected, attempt_chain=chain)
    assert resolution.resolution_reason == "budget_fallback"


def test_provider_cooldown_reason() -> None:
    router = _router(
        activity_model_lists={
            "code": ["openai/gpt-5.5", "anthropic/claude-sonnet-5"],
            "search": ["openai/gpt-5.5"],
            "reason": ["openai/gpt-5.5"],
            "improve": ["openai/gpt-5.5"],
            "other": ["openai/gpt-5.5"],
        },
        provider_keys=ProviderKeys(openai="k", anthropic="k"),
    )
    router.cooldown.mark_failed("openai/gpt-5.5")
    selected = router.select_model("code")
    assert selected == "anthropic/claude-sonnet-5"
    resolution = router.resolve("code", selected=selected)
    assert resolution.resolution_reason == "provider_cooldown"


def test_quality_preference_reason(tmp_path: object) -> None:
    store = open_store(tmp_path / "pref.db")  # type: ignore[operator]
    now = datetime.now(timezone.utc)
    for _ in range(4):
        store.write_usage(
            surface="t",
            activity="code",
            model_used="openai/gpt-5.5",
            prompt_tokens=1,
            cost=0.0,
            improver_fired=False,
            improver_accepted=False,
            latency_ms=1,
            success=True,
            timestamp=now - timedelta(hours=1),
        )
    router = _router(
        activity_model_lists={
            "code": ["anthropic/claude-opus-5", "openai/gpt-5.5"],
            "search": ["openai/gpt-5.5"],
            "reason": ["openai/gpt-5.5"],
            "improve": ["openai/gpt-5.5"],
            "other": ["openai/gpt-5.5"],
        },
        provider_keys=ProviderKeys(openai="k", anthropic="k"),
        usage_store=store,
    )
    selected = router.select_model("code")
    assert selected == "openai/gpt-5.5"
    resolution = router.resolve("code", selected=selected)
    assert resolution.resolution_reason == "quality_preference"


def test_resolution_is_deterministic() -> None:
    router = _router(provider_keys=ProviderKeys(anthropic="k", openai="k"))
    first = router.resolve("code")
    second = router.resolve("code")
    assert first == second
    chain_a = router.build_attempt_chain("code")
    chain_b = router.build_attempt_chain("code")
    assert chain_a == chain_b
    payload_a = routing_reason_json(
        router, "code", attempt_chain=chain_a, selected=chain_a[0]
    )
    payload_b = routing_reason_json(
        router, "code", attempt_chain=chain_b, selected=chain_b[0]
    )
    assert payload_a == payload_b


def test_existing_aliases_remain_backward_compatible() -> None:
    assert resolve_explicit_model("claude-sonnet-4-5") == "anthropic/claude-sonnet-5"
    assert resolve_explicit_model("composer") == "anthropic/claude-sonnet-5"
    assert resolve_explicit_model("gpt-4o-mini") == "ollama/qwen-coder-14b"
    assert resolve_explicit_model("openai/gpt-4o-mini") == "openai/gpt-4o-mini"
    assert resolve_explicit_model("auto") is None


def test_deploy_alias_json_matches_python_defaults_exactly() -> None:
    path = default_aliases_path()
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert set(payload) == set(DEFAULT_CURSOR_SLUG_ALIASES)
    for key, value in payload.items():
        assert DEFAULT_CURSOR_SLUG_ALIASES[key] == value


def test_prefix_compatibility_is_an_alias() -> None:
    hit = lookup_compatibility_alias("claude-sonnet-4-9-custom")
    assert hit is not None
    assert hit.requested_alias == "claude-sonnet-4-9-custom"
    assert hit.resolved_model == "anthropic/claude-sonnet-5"
    assert hit.source == "prefix"
    lookup = lookup_explicit_model("claude-opus-4-9-custom")
    assert lookup.reason == "compatibility_alias"
    assert lookup.resolved == "anthropic/claude-opus-5"
    assert lookup.alias_source == "prefix"


def test_builtin_alias_source_is_not_identity() -> None:
    lookup = lookup_explicit_model("gemini-3.1-pro")
    assert lookup.reason == "compatibility_alias"
    assert lookup.alias_source == "builtin"
    assert lookup.requested_alias != lookup.resolved


def test_overlay_remap_is_tagged_overlay(tmp_path: Path) -> None:
    from ylang.core.model_aliases import (
        load_cursor_slug_aliases,
        loaded_overlay_alias_keys,
    )

    path = tmp_path / "aliases.json"
    path.write_text(
        json.dumps({"gemini-3.1-pro": "openai/gpt-5.5"}),
        encoding="utf-8",
    )
    table = load_cursor_slug_aliases(path)
    try:
        hit = lookup_compatibility_alias("gemini-3.1-pro", table)
        assert hit is not None
        assert hit.source == "overlay"
        assert hit.resolved_model == "openai/gpt-5.5"
        assert "gemini-3.1-pro" in loaded_overlay_alias_keys()
    finally:
        load_cursor_slug_aliases()


def test_operator_override_reason() -> None:
    from ylang.settings import Settings

    lists = {
        "code": ["anthropic/claude-opus-5", "openai/gpt-5.5"],
        "search": ["openai/gpt-5.5"],
        "reason": ["openai/gpt-5.5"],
        "improve": ["openai/gpt-5.5"],
        "other": ["openai/gpt-5.5"],
    }
    keys = ProviderKeys(openai="k", anthropic="k")
    router = ModelRouter(
        activity_model_lists=lists,
        provider_keys=keys,
        fallback_model="ollama/qwen2.5",
    )
    overridden = {activity: list(models) for activity, models in lists.items()}
    overridden["code"] = ["openai/gpt-5.5", "anthropic/claude-sonnet-5"]
    router.apply_settings(
        Settings(activity_model_lists=overridden, provider_keys=keys)
    )
    selected = router.select_model("code")
    assert selected == "openai/gpt-5.5"
    resolution = router.resolve("code", selected=selected)
    assert resolution.resolution_reason == "operator_override"
    payload = build_routing_reason(
        router,
        "code",
        attempt_chain=router.build_attempt_chain("code"),
        selected=selected,
        resolution=resolution,
    )
    assert any(step["code"] == "operator_override" for step in payload["steps"])


def test_cost_tiebreak_ignores_unknown_zero_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    costs = {
        "openai/gpt-5.5": 0.0,
        "anthropic/claude-sonnet-5": 0.0,
    }
    monkeypatch.setattr(
        "ylang.core.model_router.estimated_unit_cost",
        lambda model: costs.get(model, 0.0),
    )
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-5.5", "anthropic/claude-sonnet-5"],
            "search": ["openai/gpt-5.5"],
            "reason": ["openai/gpt-5.5"],
            "improve": ["openai/gpt-5.5"],
            "other": ["openai/gpt-5.5"],
        },
        provider_keys=ProviderKeys(openai="k", anthropic="k"),
        fallback_model="ollama/qwen2.5",
        quality_band=1,
    )
    selected = router.select_model("code")
    assert selected == "openai/gpt-5.5"
    resolution = router.resolve("code", selected=selected)
    assert resolution.resolution_reason == "activity_default"


def test_cost_tiebreak_uses_known_cheaper_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    costs = {
        "openai/gpt-5.5": 0.02,
        "anthropic/claude-sonnet-5": 0.001,
    }
    monkeypatch.setattr(
        "ylang.core.model_router.estimated_unit_cost",
        lambda model: costs.get(model, 0.0),
    )
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-5.5", "anthropic/claude-sonnet-5"],
            "search": ["openai/gpt-5.5"],
            "reason": ["openai/gpt-5.5"],
            "improve": ["openai/gpt-5.5"],
            "other": ["openai/gpt-5.5"],
        },
        provider_keys=ProviderKeys(openai="k", anthropic="k"),
        fallback_model="ollama/qwen2.5",
        quality_band=1,
    )
    selected = router.select_model("code")
    assert selected == "anthropic/claude-sonnet-5"
    resolution = router.resolve("code", selected=selected)
    assert resolution.resolution_reason == "cost_tiebreak"
