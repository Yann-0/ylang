"""Tests for AI fact suggestions grounded in improver usage."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from ylang.console.fact_suggester import _parse_suggestions, suggest_facts_from_usage
from ylang.core.types import CompletionResult
from ylang.usage.store import UsageStore, UsageWindow


def test_parse_suggestions_json() -> None:
    parsed = _parse_suggestions(
        '{"suggestions":[{"fact":"Prefer Vitest","scope":"shareable","workspace":"ylang","rationale":"samples"}]}'
    )
    assert len(parsed) == 1
    assert parsed[0]["fact"] == "Prefer Vitest"
    assert parsed[0]["scope"] == "shareable"
    assert parsed[0]["workspace"] == "ylang"


def test_parse_suggestions_invalid_scope_defaults_private() -> None:
    parsed = _parse_suggestions(
        '{"suggestions":[{"fact":"Keep PRs small","scope":"team","workspace":""}]}'
    )
    assert parsed[0]["scope"] == "private"


def test_suggest_facts_from_usage_success(tmp_path: object) -> None:
    store = UsageStore.open(tmp_path / "usage.db")  # type: ignore[operator]
    store.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="test/model",
        prompt_tokens=10,
        cost=0.01,
        improver_fired=True,
        improver_accepted=False,
        latency_ms=100,
        success=True,
        improver_input_sample="Add Vitest coverage for the facts module",
        improver_validated=True,
        improver_changed=True,
        improver_rejection_reason="too verbose",
        timestamp=datetime.now(timezone.utc),
    )
    engine = MagicMock()
    engine.complete.return_value = CompletionResult(
        content=(
            '{"suggestions":[{"fact":"Prefer concise improver output",'
            '"scope":"private","workspace":"","rationale":"rejection too verbose"}]}'
        ),
        model_used="test/model",
        prompt_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=True,
        error=None,
    )
    result = suggest_facts_from_usage(store, engine, window=UsageWindow.last_days(7))
    assert result["ok"] is True
    assert result["suggestions"][0]["fact"] == "Prefer concise improver output"
    engine.complete.assert_called_once()
    _args, kwargs = engine.complete.call_args
    assert kwargs.get("activity") == "reason"
    assert "model" not in kwargs


def test_suggest_facts_from_usage_empty_analytics(tmp_path: object) -> None:
    store = UsageStore.open(tmp_path / "usage.db")  # type: ignore[operator]
    engine = MagicMock()
    result = suggest_facts_from_usage(store, engine, window=UsageWindow.last_days(7))
    assert result["ok"] is False
    assert "Not enough improver usage" in result["error"]
    engine.complete.assert_not_called()


def test_suggest_facts_from_usage_llm_failure(tmp_path: object) -> None:
    store = UsageStore.open(tmp_path / "usage.db")  # type: ignore[operator]
    store.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="test/model",
        prompt_tokens=10,
        cost=0.01,
        improver_fired=True,
        improver_accepted=True,
        latency_ms=100,
        success=True,
        improver_input_sample="Refactor memory store",
        timestamp=datetime.now(timezone.utc),
    )
    engine = MagicMock()
    engine.complete.return_value = CompletionResult(
        content="",
        model_used="test/model",
        prompt_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=False,
        error="unavailable",
    )
    result = suggest_facts_from_usage(store, engine)
    assert result["ok"] is False
    assert result["error"] == "unavailable"
