"""Control-plane trace, privacy, and routing-reason tests (YLANG-CP-015/023)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import litellm
import pytest

from ylang.core.db import open_connection
from ylang.core.engine import Engine
from ylang.core.migrations import USAGE_TRACE_COLUMNS, run_migrations
from ylang.core.model_router import ModelRouter
from ylang.core.routing_reason import build_routing_reason, routing_reason_json
from ylang.settings import ProviderKeys, Settings
from ylang.usage.capture import (
    hash_prompt_text,
    parse_capture_level,
    prompt_body_for_capture,
    redact_secrets,
)
from ylang.usage.store import UsageWindow, open_store


def _mock_response(content: str = "ok", *, model: str = "openai/gpt-4o") -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content, tool_calls=None))]
    response.model = model
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=25)
    response._hidden_params = {"response_cost": 0.01}
    return response


def test_parse_capture_level_defaults() -> None:
    assert parse_capture_level(None) == "minimal"
    assert parse_capture_level("off") == "off"
    assert parse_capture_level("FULL_LOCAL") == "full_local"
    assert parse_capture_level("nope") == "minimal"


def test_privacy_defaults_minimal_keeps_hash_drops_body() -> None:
    sample, body = prompt_body_for_capture("secret sk-abcdefghijklmnop body", "minimal")
    assert sample is not None
    assert "sk-" not in sample
    assert body is None


def test_privacy_off_drops_bodies() -> None:
    sample, body = prompt_body_for_capture("hello world", "off")
    assert sample is None
    assert body is None


def test_redact_secrets_masks_bearer() -> None:
    assert "***" in redact_secrets("Authorization Bearer abcdefghijklmnop")


def test_migration_11_adds_trace_columns_on_legacy_db(tmp_path: Path) -> None:
    """Historical DBs without migrations ledger still upgrade safely."""
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                surface TEXT NOT NULL,
                activity TEXT NOT NULL,
                model_used TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                cost REAL NOT NULL,
                improver_fired INTEGER NOT NULL,
                improver_accepted INTEGER NOT NULL,
                improver_input_sample TEXT,
                latency_ms INTEGER NOT NULL,
                success INTEGER NOT NULL
            );
            INSERT INTO usage (
                timestamp, surface, activity, model_used, prompt_tokens, cost,
                improver_fired, improver_accepted, latency_ms, success
            ) VALUES (
                '2026-01-01T00:00:00+00:00', 'mcp', 'code', 'ollama/qwen2.5',
                1, 0.0, 0, 0, 10, 1
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    connection = open_connection(db_path)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(usage)").fetchall()
        }
        for name, _ddl in USAGE_TRACE_COLUMNS:
            assert name in columns
        # Pre-trace row survives; capture_level may be NULL for historical rows.
        row = connection.execute(
            "SELECT model_used, capture_level, trace_id FROM usage"
        ).fetchone()
        assert row is not None
        assert row[0] == "ollama/qwen2.5"
        assert row[2] is None
        version = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0]
        assert int(version) >= 11
    finally:
        connection.close()


def test_migration_11_idempotent(tmp_path: Path) -> None:
    connection = open_connection(tmp_path / "idemp.db")
    try:
        assert run_migrations(connection) == 0
    finally:
        connection.close()


def test_engine_persists_trace_and_routing_reason(tmp_path: Path) -> None:
    store = open_store(tmp_path / "trace.db")
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="test-key"),
        fallback_model="ollama/qwen2.5",
    )
    engine = Engine(store, surface="test", router=router, capture_level="minimal")
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("hello"),
    ):
        result = engine.complete(
            [{"role": "user", "content": "hi there"}],
            "code",
            mcp_tool="improve_prompt",
            selected_route="route-code",
        )
    assert result.success is True
    rows = store.recall_usage(UsageWindow.last_hours(1))
    assert len(rows) == 1
    row = rows[0]
    assert row.trace_id
    assert row.capture_level == "minimal"
    assert row.completion_tokens == 25
    assert row.mcp_tool == "improve_prompt"
    assert row.selected_route == "route-code"
    assert row.candidate_models_json is not None
    assert "openai/gpt-4o" in row.candidate_models_json
    assert row.routing_reason_json is not None
    reason = json.loads(row.routing_reason_json)
    assert reason["schema"] == 1
    assert reason["selected"] == "openai/gpt-4o"
    assert row.prompt_hash == hash_prompt_text("hi there")
    assert row.prompt_body_redacted is None
    assert row.result_status == "success"


def test_engine_fallback_events_traced(tmp_path: Path) -> None:
    store = open_store(tmp_path / "fallback.db")
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="test-key"),
        fallback_model="ollama/qwen2.5",
    )
    engine = Engine(store, surface="test", router=router)

    def side_effect(**kwargs: object) -> MagicMock:
        model = str(kwargs["model"])
        if model == "openai/gpt-4o":
            raise litellm.RateLimitError("rate limited", "openai", "gpt-4o")
        return _mock_response("fallback-ok", model=model)

    with patch("ylang.core.engine.litellm.completion", side_effect=side_effect):
        result = engine.complete([{"role": "user", "content": "hi"}], "code")
    assert result.success is True
    row = store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.fallback_events_json is not None
    events = json.loads(row.fallback_events_json)
    assert events[0]["from"] == "openai/gpt-4o"
    assert events[0]["error_class"] == "rate_limit"
    reason = json.loads(row.routing_reason_json or "{}")
    codes = [step["code"] for step in reason["steps"]]
    assert "fallback" in codes


def test_capture_level_off_omits_prompt_hash(tmp_path: Path) -> None:
    store = open_store(tmp_path / "off.db")
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="test-key"),
        fallback_model="ollama/qwen2.5",
    )
    engine = Engine(store, surface="test", router=router, capture_level="off")
    with patch(
        "ylang.core.engine.litellm.completion",
        return_value=_mock_response("ok"),
    ):
        engine.complete([{"role": "user", "content": "secret prompt"}], "code")
    row = store.recall_usage(UsageWindow.last_hours(1))[0]
    assert row.capture_level == "off"
    assert row.prompt_hash is None
    assert row.prompt_body_redacted is None
    assert row.routing_reason_json is not None


def test_routing_reason_reproducible() -> None:
    router = ModelRouter(
        activity_model_lists={
            "code": ["openai/gpt-4o", "anthropic/claude-3-5-sonnet-latest"],
            "search": ["openai/gpt-4o"],
            "reason": ["openai/gpt-4o"],
            "improve": ["openai/gpt-4o"],
            "other": ["openai/gpt-4o"],
        },
        provider_keys=ProviderKeys(openai="k"),
        fallback_model="ollama/qwen2.5",
        quality_band=0,
    )
    chain = router.build_attempt_chain("code")
    selected = chain[0]
    first = routing_reason_json(
        router, "code", attempt_chain=chain, selected=selected
    )
    second = routing_reason_json(
        router, "code", attempt_chain=chain, selected=selected
    )
    assert first == second
    payload = build_routing_reason(
        router, "code", attempt_chain=chain, selected=selected
    )
    assert payload["selected"] == selected
    assert any(step["code"] == "provider_unavailable" for step in payload["steps"])


def test_settings_capture_level_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YLANG_CAPTURE_LEVEL", "redacted")
    settings = Settings.load()
    assert settings.capture_level == "redacted"
