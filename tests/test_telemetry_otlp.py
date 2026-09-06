"""Optional OTLP export is disabled by default and never requires a collector.

Live export uses BatchSpanProcessor (async queue) so a slow collector cannot
add latency to Engine.complete. These tests stay on in-memory / no-op sinks.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.types import ModelResolution
from ylang.settings import ProviderKeys, Settings
from ylang.telemetry.export import (
    NoOpUsageSpanSink,
    RecordingUsageSpanSink,
    completion_span_attributes,
    exporter_from_settings,
)
from ylang.usage.store import UsageWindow, open_store


def _resolution() -> ModelResolution:
    return ModelResolution(
        requested_model="gemini-3.1-pro",
        requested_alias="gemini-3.1-pro",
        semantic_route="search",
        resolved_route="search",
        resolved_provider="gemini",
        resolved_model="gemini/gemini-3.7-flash",
        resolution_reason="compatibility_alias",
        attempt_index=0,
        alias_source="builtin",
    )


def test_otel_disabled_by_default() -> None:
    settings = Settings()
    assert settings.otel_enabled is False
    assert settings.otel_export_content is False
    sink = exporter_from_settings(settings)
    assert isinstance(sink, NoOpUsageSpanSink)


def test_otel_env_enables_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YLANG_OTEL_ENABLED", "true")
    monkeypatch.setenv("YLANG_OTEL_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    settings = Settings.load()
    assert settings.otel_enabled is True
    assert settings.otel_endpoint == "http://127.0.0.1:4318/v1/traces"
    with patch("ylang.telemetry.export._try_build_otlp_sink", return_value=None):
        sink = exporter_from_settings(settings)
    assert isinstance(sink, NoOpUsageSpanSink)


def test_attributes_omit_prompt_bodies_by_default() -> None:
    attributes = completion_span_attributes(
        surface="gateway",
        activity="search",
        model_used="gemini/gemini-3.7-flash",
        prompt_tokens=10,
        completion_tokens=4,
        cost=0.01,
        latency_ms=12,
        success=True,
        trace_id="trace-1",
        session_id="sess-1",
        workspace="ws-1",
        selected_route="route-search",
        resolution=_resolution(),
        export_content=False,
        capture_level="full_local",
        prompt_body_redacted="secret prompt body",
        tool_calls=[{"function": {"name": "lookup", "arguments": '{"q":"x"}'}}],
    )
    assert attributes["ylang.semantic_route"] == "search"
    assert attributes["ylang.resolution_reason"] == "compatibility_alias"
    assert attributes["ylang.requested_alias"] == "gemini-3.1-pro"
    assert attributes["ylang.alias_source"] == "builtin"
    assert attributes["ylang.provider"] == "gemini"
    assert attributes["ylang.tool_names"] == "lookup"
    assert attributes["ylang.trace_id"] == "trace-1"
    assert "ylang.prompt_body_redacted" not in attributes
    assert "secret prompt body" not in attributes.values()
    dumped = " ".join(str(value) for value in attributes.values())
    assert '{"q":"x"}' not in dumped


def test_content_export_requires_opt_in_and_redacted_capture() -> None:
    attributes = completion_span_attributes(
        surface="mcp",
        activity="code",
        model_used="openai/gpt-5.5",
        prompt_tokens=1,
        completion_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=True,
        trace_id="t",
        session_id=None,
        workspace=None,
        selected_route=None,
        resolution=_resolution(),
        export_content=True,
        capture_level="redacted",
        prompt_body_redacted="safe-preview",
        tool_calls=[],
    )
    assert attributes["ylang.prompt_body_redacted"] == "safe-preview"
    skipped = completion_span_attributes(
        surface="mcp",
        activity="code",
        model_used="openai/gpt-5.5",
        prompt_tokens=1,
        completion_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=True,
        trace_id="t",
        session_id=None,
        workspace=None,
        selected_route=None,
        resolution=_resolution(),
        export_content=True,
        capture_level="minimal",
        prompt_body_redacted="should-not-export",
        tool_calls=[],
    )
    assert "ylang.prompt_body_redacted" not in skipped


def test_engine_emits_to_injected_sink_without_network(tmp_path: Path) -> None:
    store = open_store(tmp_path / "otel.db")
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
    )
    sink = RecordingUsageSpanSink()
    engine = Engine(store, surface="test", router=router, telemetry=sink)
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="ok", tool_calls=None))]
    response.model = "openai/gpt-4o"
    response.usage = MagicMock(prompt_tokens=2, completion_tokens=3)
    response._hidden_params = {"response_cost": 0.0}
    with patch("ylang.core.engine.litellm.completion", return_value=response):
        result = engine.complete(
            [{"role": "user", "content": "hi"}],
            "code",
            selected_route="route-code",
        )
    assert result.success is True
    assert len(sink.spans) == 1
    span = sink.spans[0]
    assert span["ylang.surface"] == "test"
    assert span["ylang.semantic_route"] == "code"
    assert span["ylang.trace_id"] == result.trace_id
    assert span["ylang.selected_route"] == "route-code"
    row = store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.routing_reason_json
    assert row.trace_id == result.trace_id
    reason = json.loads(row.routing_reason_json)
    assert reason["resolution_reason"] == "activity_default"
    assert reason["semantic_route"] == "code"
    assert reason["selected_model"] == "openai/gpt-4o"


def test_exporter_missing_sdk_is_noop() -> None:
    settings = Settings(
        otel_enabled=True,
        otel_endpoint="http://127.0.0.1:4318/v1/traces",
    )
    with patch("ylang.telemetry.export._try_build_otlp_sink", return_value=None):
        sink = exporter_from_settings(settings)
    assert isinstance(sink, NoOpUsageSpanSink)


def test_sink_errors_do_not_fail_completion(tmp_path: Path) -> None:
    class BoomSink:
        def emit(self, attributes: dict[str, str | int | float | bool]) -> None:
            raise RuntimeError("collector down")

    store = open_store(tmp_path / "boom.db")
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
    )
    engine = Engine(store, surface="test", router=router, telemetry=BoomSink())
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="ok", tool_calls=None))]
    response.model = "openai/gpt-4o"
    response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
    response._hidden_params = {"response_cost": 0.0}
    with patch("ylang.core.engine.litellm.completion", return_value=response):
        result = engine.complete([{"role": "user", "content": "hi"}], "code")
    assert result.success is True
    assert store.recall_usage(UsageWindow.last_hours(1))
