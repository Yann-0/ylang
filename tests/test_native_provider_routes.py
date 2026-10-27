"""Independent native route QA; chains mirror routing-compatibility.json (2026-10-27).

Every HTTP response is fixture data. No live credentials, provider transport,
local daemon, environment file, or deployed database participates.
"""
from __future__ import annotations

from functools import partial
import json
from pathlib import Path
import sqlite3
from typing import Any
from unittest.mock import Mock

from mcp.server.fastmcp import FastMCP
import pytest
from starlette.testclient import TestClient

from ylang.core.engine import Engine
from ylang.core import provider_adapters
from ylang.core.provider_adapters import (
    HTTPReply, NativeProviderAdapter, build_provider_adapters,
)
from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.gateway.routes import register_gateway_routes
from ylang.improver import Improver
from ylang.settings import ProviderKeys, Settings
from ylang.usage.hard_budget import HardBudgetStore
from ylang.usage.store import UsageWindow, open_store

SONNET = "anthropic/claude-3-5-sonnet-latest"
MISTRAL = "mistral/mistral-small-latest"
ROUTES = {
    activity: (
        [MISTRAL, "anthropic/claude-haiku-4-5", "ollama/qwen2.5"]
        if activity == "improve"
        else [SONNET, "openai/gpt-4o", "ollama/qwen2.5"]
    )
    for activity in ("code", "search", "reason", "improve", "other")
}
PINNED = {
    SONNET: "anthropic/claude-sonnet-4-6",
    MISTRAL: "mistral/mistral-small-2603",
    "openai/gpt-4o": "openai/gpt-4o-2024-08-06",
    "anthropic/claude-haiku-4-5": "anthropic/claude-haiku-4-5-20251001",
}
# Independent expected values from the reviewed provider-interface contract.
TARIFF = {
    "anthropic/claude-sonnet-4-6": (1_048_576, 6_600, 16_500),
    "anthropic/claude-haiku-4-5-20251001": (200_000, 2_000, 5_000),
    "openai/gpt-4o-2024-08-06": (128_000, 2_500, 10_000),
    "mistral/mistral-small-2603": (262_144, 150, 600),
}
MESSAGES = [{"role": "user", "content": "Reply with a short answer."}]


class FixtureHTTP:
    """Record one native POST and return independently authored wire fixtures."""

    live = False

    def __init__(self, content: str = "fixture native answer", *,
                 fault: str | None = None) -> None:
        """Retain explicit fault behavior and calls without a network dependency."""
        self.content = content
        self.fault = fault
        self.calls: list[dict[str, Any]] = []

    def post(self, host: str, path: str, headers: dict[str, str],
             body: bytes, timeout: float) -> HTTPReply:
        """Produce the provider's native schema from the pinned outgoing model."""
        request = json.loads(body)
        self.calls.append({"host": host, "path": path, "headers": headers,
                           "body": request, "timeout": timeout})
        if self.fault == "timeout":
            raise TimeoutError("fixture response lost after possible acceptance")
        if self.fault == "http503":
            return HTTPReply(503, b'{"error":{"message":"fixture unavailable"}}', "req-fixture")
        model = request["model"]
        if host == "api.anthropic.com":
            reply = {
                "id": "msg-fixture", "type": "message", "role": "assistant",
                "model": model, "stop_reason": "end_turn", "stop_sequence": None,
                "content": [{"type": "text", "text": self.content}],
                "usage": {"input_tokens": 12, "output_tokens": 8},
            }
        else:
            reply = {
                "id": "chatcmpl-fixture", "object": "chat.completion", "model": model,
                "choices": [{"index": 0, "message": {
                    "role": "assistant", "content": self.content,
                }, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8,
                          "total_tokens": 20},
            }
        if self.fault == "model":
            reply["model"] = "unrequested-model"
        elif self.fault == "usage":
            reply.pop("usage")
        elif self.fault == "bound":
            assert host == "api.anthropic.com"
            reply["usage"] = {"input_tokens": 1_048_577, "output_tokens": 513}
        elif self.fault in {"length", "content_filter"}:
            if host == "api.anthropic.com":
                reply["stop_reason"] = "max_tokens" if self.fault == "length" else "refusal"
            else:
                reply["choices"][0]["finish_reason"] = self.fault
        return HTTPReply(200, json.dumps(reply).encode(), "req-fixture")


@pytest.fixture(autouse=True)
def forbid_legacy_dispatch(monkeypatch: pytest.MonkeyPatch):
    """Fail qualification if any route silently falls back to LiteLLM/local transport."""
    transport = Mock(side_effect=AssertionError("legacy transport is forbidden"))
    monkeypatch.setattr("ylang.core.engine.litellm.completion", transport)
    yield
    transport.assert_not_called()


@pytest.fixture
def engine_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Wire the real settings factory with only its HTTP transport replaced."""
    stores = []

    def create(transport: FixtureHTTP | None = None, *, enabled: bool = True,
               limit: int | None = 100_000_000_000, runtime: bool = False):
        """Create one private policy and reproducible current activity configuration."""
        transport = transport or FixtureHTTP()
        store = open_store(tmp_path / f"native-{len(stores)}.db")
        stores.append(store)
        settings = Settings(
            bounded_providers_enabled=enabled,
            provider_keys=ProviderKeys(
                anthropic="fixture-anthropic-key", openai="fixture-openai-key",
                mistral="fixture-mistral-key",
            ),
            activity_model_lists=(
                {activity: ["ollama/unused"] for activity in ROUTES}
                if runtime else ROUTES
            ),
            hard_budget_max_output_tokens=512,
        )
        if runtime:
            overrides = RuntimeSettingsStore(store._connection)
            for activity, chain in ROUTES.items():
                overrides.set("models_" + activity, ",".join(chain))
        if limit is not None:
            with HardBudgetStore.open(store.database_path) as ledger:
                ledger.initialize_policy(
                    limit_nanos=limit,
                    opening_evidence="new private native route fixture database",
                )
        monkeypatch.setattr(
            provider_adapters, "build_provider_adapters",
            partial(build_provider_adapters, transport=transport),
        )
        engine = Engine.from_settings(store, surface="gateway", settings=settings)
        assert all(type(adapter) is NativeProviderAdapter
                   for adapter in engine._bounded_adapters.values())
        return engine, transport

    yield create
    for store in stores:
        store.close()


def ledger_rows(engine: Engine, table: str) -> list[sqlite3.Row]:
    """Read immutable qualification evidence from this fixture's private database."""
    assert table in {"budget_attempts", "budget_requests", "budget_policies"}
    with sqlite3.connect(engine.store.database_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()


def assert_settled_once(engine: Engine, transport: FixtureHTTP,
                        requested: str, returned: str) -> None:
    """Require one POST, one reservation, one linked usage and pinned identities."""
    assert len(transport.calls) == 1
    attempts = ledger_rows(engine, "budget_attempts")
    requests = ledger_rows(engine, "budget_requests")
    usage = engine.store.recall_usage(UsageWindow.last_hours(1))
    assert len(attempts) == len(requests) == len(usage) == 1
    assert attempts[0]["state"] == "SETTLED"
    assert requests[0]["usage_row_id"] is not None
    metadata = json.loads(requests[0]["metadata_json"])
    assert metadata["requested_model"] == requested
    assert metadata["resolved_model"] == returned
    assert json.loads(attempts[0]["quote_json"])["model"] == returned
    assert usage[0].model_used == returned
    assert usage[0].cost_actual is None
    evidence = json.loads(attempts[0]["evidence_json"])
    assert evidence["cost_basis"] == "standard_tariff_upper_bound"
    assert evidence["cost_is_upper_bound"] is True
    assert evidence["observed_response"]["model"] == returned
    input_bound, input_rate, output_rate = TARIFF[returned]
    assert attempts[0]["max_cost_nanos"] == input_bound * input_rate + 512 * output_rate
    assert attempts[0]["actual_cost_nanos"] == 12 * input_rate + 8 * output_rate
    assert usage[0].cost == attempts[0]["actual_cost_nanos"] / 1_000_000_000
    body = transport.calls[0]["body"]
    assert body["model"] == returned.split("/", 1)[1]
    assert body.get("stream", False) is False
    assert "tools" not in body and "tool_choice" not in body


@pytest.mark.parametrize("runtime", [False, True], ids=["settings", "runtime-overrides"])
@pytest.mark.parametrize("activity", list(ROUTES))
def test_actual_five_activity_routes_settle_native_response(
    engine_factory, activity: str, runtime: bool,
) -> None:
    """Qualify current chains through settings and real runtime merge before dispatch."""
    engine, transport = engine_factory(runtime=runtime)
    result = engine.complete(MESSAGES, activity)
    assert result.success is True
    assert result.content == "fixture native answer"
    assert engine.router.ordered_candidates(activity) == ROUTES[activity]
    requested = ROUTES[activity][0]
    assert_settled_once(engine, transport, requested, PINNED[requested])


@pytest.mark.parametrize("requested", ["openai/gpt-4o", "anthropic/claude-haiku-4-5"])
def test_additional_models_in_current_chains_are_pinned(
    engine_factory, requested: str,
) -> None:
    """Exercise both secondary provider profiles without inducing ambiguous retry."""
    engine, transport = engine_factory()
    result = engine.complete(MESSAGES, "code", model=requested)
    assert result.success is True and result.content == "fixture native answer"
    assert_settled_once(engine, transport, requested, PINNED[requested])


def test_prompt_improver_consumes_native_json_not_fallback(engine_factory) -> None:
    """Require exact improved text from real native JSON transport and one settlement."""
    improved = "Fix the bug in main.py"
    transport = FixtureHTTP(json.dumps({"improved": improved, "changes": []}))
    engine, transport = engine_factory(transport, runtime=True)
    result = Improver(engine).improve(
        "fix bug", "cursor-agent", model="claude-sonnet-4-5",
    )
    assert result.original == "fix bug"
    assert result.improved == improved
    assert_settled_once(engine, transport, MISTRAL, PINNED[MISTRAL])
    body = transport.calls[0]["body"]
    assert body["response_format"] == {"type": "json_object"}
    assert any("fix bug" in message["content"] for message in body["messages"])


@pytest.mark.parametrize("stream", [False, True], ids=["completion", "buffered-sse"])
def test_registered_gateway_route_returns_exact_native_output(
    engine_factory, stream: bool,
) -> None:
    """Exercise the registered HTTP handler and its real payload/SSE serialization."""
    engine, transport = engine_factory()
    server = FastMCP("offline-native-routes", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    with TestClient(server.streamable_http_app()) as client:
        response = client.post("/v1/chat/completions", json={
            "model": "route-code", "messages": MESSAGES, "stream": stream,
        })
    assert response.status_code == 200
    if stream:
        assert response.headers["content-type"].startswith("text/event-stream")
        payloads = [json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: ") and line != "data: [DONE]"]
        assert response.text.count("data: [DONE]") == 1
        content = "".join(payload["choices"][0]["delta"].get("content", "")
                          for payload in payloads if payload.get("choices"))
        assert content == "fixture native answer"
        assert any(payload.get("usage", {}).get("total_tokens") == 20
                   for payload in payloads)
    else:
        payload = response.json()
        assert payload["choices"][0]["message"]["content"] == "fixture native answer"
        assert payload["model"] == "route-code"
        assert payload["usage"] == {
            "prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20,
        }
    assert_settled_once(engine, transport, SONNET, PINNED[SONNET])


def test_buffered_stream_cancel_after_first_chunk_retains_settlement(engine_factory) -> None:
    """Close the actual Engine generator only after inspecting durable pre-yield money."""
    engine, transport = engine_factory()
    stream = engine.complete_stream(MESSAGES, "code")
    first = next(stream)
    assert first.content == "fixture native answer"
    assert_settled_once(engine, transport, SONNET, PINNED[SONNET])
    stream.close()
    assert_settled_once(engine, transport, SONNET, PINNED[SONNET])


@pytest.mark.parametrize("stream", [False, True], ids=["completion", "stream"])
@pytest.mark.parametrize("mode", ["disabled", "missing-policy", "insufficient-budget"])
def test_financial_admission_failures_dispatch_nothing(
    engine_factory, mode: str, stream: bool,
) -> None:
    """Reject exact unavailable-model gateway results before any native POST."""
    engine, transport = engine_factory(
        enabled=mode != "disabled",
        limit=None if mode == "missing-policy" else (1 if mode == "insufficient-budget"
                                                   else 100_000_000_000),
    )
    server = FastMCP("offline-native-refusals", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    with TestClient(server.streamable_http_app()) as client:
        response = client.post("/v1/chat/completions", json={
            "model": "route-code", "messages": MESSAGES, "stream": stream,
        })
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert error["code"] == "model_not_found" and error["param"] == "model"
    assert transport.calls == []
    assert ledger_rows(engine, "budget_attempts") == []


@pytest.mark.parametrize("fault", ["timeout", "http503"])
def test_ambiguous_provider_failure_retains_full_hold_without_retry(
    engine_factory, fault: str,
) -> None:
    """Do not infer free billing or dispatch another configured model after ambiguity."""
    engine, transport = engine_factory(FixtureHTTP(fault=fault))
    result = engine.complete(MESSAGES, "code")
    assert result.success is False
    assert len(transport.calls) == 1
    attempt = ledger_rows(engine, "budget_attempts")[0]
    assert attempt["state"] == "UNCERTAIN"
    assert attempt["actual_cost_nanos"] is None
    with HardBudgetStore.open(engine.store.database_path) as ledger:
        assert ledger.exposure_nanos() == attempt["max_cost_nanos"]
    assert len(engine.store.recall_usage(UsageWindow.last_hours(1))) == 1


@pytest.mark.parametrize("fault", ["model", "usage"])
def test_native_contract_mismatch_freezes_and_preserves_hold(
    engine_factory, fault: str,
) -> None:
    """Persist uncertain native evidence and freeze subsequent financial admission."""
    engine, transport = engine_factory(FixtureHTTP(fault=fault))
    result = engine.complete(MESSAGES, "code")
    assert result.success is False
    assert len(transport.calls) == 1
    attempt = ledger_rows(engine, "budget_attempts")[0]
    assert attempt["state"] == "UNCERTAIN"
    assert ledger_rows(engine, "budget_policies")[0]["frozen_reason"] == (
        "native_provider_contract_violation"
    )
    with HardBudgetStore.open(engine.store.database_path) as ledger:
        assert ledger.exposure_nanos() == attempt["max_cost_nanos"]
    again = engine.complete(MESSAGES, "code")
    assert again.success is False
    assert len(transport.calls) == 1
    assert len(ledger_rows(engine, "budget_attempts")) == 1


def test_paid_tools_are_refused_before_transport(engine_factory) -> None:
    """Never send unbounded tool fields through a native adapter."""
    engine, transport = engine_factory()
    result = engine.complete(MESSAGES, "code", tools=[{
        "type": "function", "function": {"name": "lookup", "parameters": {}},
    }], tool_choice="auto")
    assert result.success is False
    assert result.error == "paid tools are not bounded"
    assert transport.calls == []
    assert ledger_rows(engine, "budget_attempts") == []


def test_reported_native_charge_above_hold_is_a_durable_breach(engine_factory) -> None:
    """Preserve a valid reported excess charge rather than understating it as a hold."""
    engine, transport = engine_factory(FixtureHTTP(fault="bound"))
    result = engine.complete(MESSAGES, "code")
    assert result.success is False
    assert len(transport.calls) == 1
    attempt = ledger_rows(engine, "budget_attempts")[0]
    expected_charge = 1_048_577 * 6_600 + 513 * 16_500
    assert attempt["state"] == "BREACH"
    assert attempt["actual_cost_nanos"] == expected_charge
    assert expected_charge > attempt["max_cost_nanos"]
    assert ledger_rows(engine, "budget_policies")[0]["frozen_reason"] == (
        "certified_bound_exceeded"
    )
    with HardBudgetStore.open(engine.store.database_path) as ledger:
        assert ledger.exposure_nanos() == expected_charge
    assert engine.complete(MESSAGES, "code").success is False
    assert len(transport.calls) == 1


@pytest.mark.parametrize("stream", [False, True], ids=["completion", "buffered-sse"])
@pytest.mark.parametrize("reason", ["length", "content_filter"])
@pytest.mark.parametrize("model", ["route-code", "openai/gpt-4o", "mistral/mistral-small-latest"])
def test_gateway_retains_native_termination_reason(engine_factory, model: str, reason: str, stream: bool) -> None:
    """Do not describe truncated/filtered native output as a normal completion."""
    engine, transport = engine_factory(FixtureHTTP(fault=reason))
    server = FastMCP("native-finish-reason", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    with TestClient(server.streamable_http_app()) as client:
        response = client.post("/v1/chat/completions", json={
            "model": model, "messages": MESSAGES, "stream": stream,
        })
    assert response.status_code == 200
    if stream:
        payloads = [json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: ") and line != "data: [DONE]"]
        terminal = [choice["finish_reason"] for payload in payloads for choice in payload.get("choices", [])
                    if choice["finish_reason"] is not None]
        assert terminal == [reason]
        assert response.text.count("data: [DONE]") == 1
    else:
        assert response.json()["choices"][0]["finish_reason"] == reason
    attempts = ledger_rows(engine, "budget_attempts")
    assert len(transport.calls) == len(attempts) == 1
    assert attempts[0]["state"] == "SETTLED"
    evidence = json.loads(attempts[0]["evidence_json"])
    assert evidence["finish_reason"] == reason
    assert evidence["observed_response"]["finish_reason"] == reason
    expected_native = ("max_tokens" if reason == "length" else "refusal") if model == "route-code" else reason
    assert evidence["provider_stop_reason"] == expected_native
