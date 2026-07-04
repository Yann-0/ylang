"""Integration tests for daily budget edge cases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ylang.core.model_router import ModelRouter
from ylang.settings import ProviderKeys
from ylang.usage.store import open_store


@pytest.fixture
def budget_router(tmp_path: object) -> tuple[ModelRouter, object]:
    store = open_store(tmp_path / "budget-edge.db")  # type: ignore[operator]
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
        daily_budget_usd=10.0,
    )
    return router, store


def _write_spend(store: object, *, cost: float, hours_ago: int = 1) -> None:
    now = datetime.now(timezone.utc)
    store.write_usage(  # type: ignore[attr-defined]
        surface="test",
        activity="code",
        model_used="openai/gpt-4o",
        prompt_tokens=100,
        cost=cost,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=now - timedelta(hours=hours_ago),
    )


def test_budget_just_under_cap_keeps_cloud_models(budget_router: tuple[ModelRouter, object]) -> None:
    router, store = budget_router
    _write_spend(store, cost=9.99)
    ordered = router.ordered_candidates("code")
    assert "openai/gpt-4o" in ordered
    assert "anthropic/claude-3-5-sonnet-latest" in ordered


def test_budget_at_cap_drops_cloud_models(budget_router: tuple[ModelRouter, object]) -> None:
    router, store = budget_router
    _write_spend(store, cost=10.0)
    ordered = router.ordered_candidates("code")
    assert ordered == []


def test_budget_over_cap_drops_cloud_models(budget_router: tuple[ModelRouter, object]) -> None:
    router, store = budget_router
    _write_spend(store, cost=12.0)
    ordered = router.ordered_candidates("code")
    assert ordered == []
    chain = router.build_attempt_chain("code")
    assert chain == ["ollama/qwen2.5"]


def test_budget_warning_at_eighty_percent(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ylang.settings import Settings
    from ylang.usage.budget import warn_budget_threshold

    store = open_store(tmp_path / "warn.db")  # type: ignore[operator]
    _write_spend(store, cost=8.5)
    settings = Settings(daily_budget_usd=10.0)
    warn_budget_threshold(settings, store)
    captured = capsys.readouterr()
    assert "warning:" in captured.err
    assert "80%" in captured.err or "85%" in captured.err
