"""Offline adversarial qualification of the paid Engine boundary."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import litellm
import pytest

from tests.bounded_adapter_helpers import (
    MockedCompletionAdapter, OfflineAdapter, initialize_budget, response,
)
from ylang.core.bounded_completion import BoundedFailure, canonical_json
from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.types import StreamCompletionError
from ylang.settings import ProviderKeys
from ylang.usage.hard_budget import BudgetRefused, HardBudgetStore
from ylang.usage.store import UsageWindow, open_store

MESSAGES = [{"role": "user", "content": "hi"}]
MODEL = "openai/gpt-4o"


def engine_at(tmp_path: Path, adapter: OfflineAdapter | None = None, *, initialize: bool = True) -> Engine:
    """Construct an isolated real ledger with explicit synthetic transport injection."""
    store = open_store(tmp_path / "engine.db")
    if initialize:
        initialize_budget(store)
    router = ModelRouter(activity_model_lists={"code": [MODEL]},
                         provider_keys=ProviderKeys(openai="fixture-key"),
                         fallback_model="ollama/qwen2.5")
    return Engine(store, surface="test", router=router,
                  bounded_adapters={MODEL: adapter} if adapter else None)


def attempts(engine: Engine) -> list[sqlite3.Row]:
    """Inspect durable financial attempts instead of presentation-only usage."""
    with sqlite3.connect(engine.store.database_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM budget_attempts ORDER BY rowid").fetchall()


def test_no_adapter_denies_without_any_transport(tmp_path: Path) -> None:
    engine = engine_at(tmp_path)
    with patch("ylang.core.engine.litellm.completion") as transport:
        result = engine.complete(MESSAGES, "code", cost_actual=0)
    assert not result.success
    transport.assert_not_called()
    assert attempts(engine) == []


def test_missing_policy_denies_before_transport(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter, initialize=False)
    result = engine.complete(MESSAGES, "code")
    assert not result.success and not adapter.calls


@pytest.mark.parametrize("kwargs", [{"tools": []}, {"tool_choice": "auto"}, {"response_format": {"type": "json_object"}}])
def test_paid_unsupported_features_fail_before_transport(tmp_path: Path, kwargs: dict) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    assert not engine.complete(MESSAGES, "code", **kwargs).success
    assert not adapter.calls and not attempts(engine)


def test_paid_stream_refused_before_dispatch(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    with patch("ylang.core.engine.litellm.completion") as transport:
        with pytest.raises(StreamCompletionError):
            list(engine.complete_stream(MESSAGES, "code"))
    transport.assert_not_called()
    assert not adapter.calls and not attempts(engine)


def test_ambiguous_failure_holds_and_never_falls_back(tmp_path: Path) -> None:
    adapter = OfflineAdapter(TimeoutError("billability unknown"))
    engine = engine_at(tmp_path, adapter)
    with patch("ylang.core.engine.litellm.completion") as transport:
        result = engine.complete(MESSAGES, "code")
    assert not result.success
    transport.assert_not_called()
    rows = attempts(engine)
    assert len(rows) == 1 and rows[0]["state"] == "UNCERTAIN"
    with HardBudgetStore.open(engine.store.database_path) as ledger:
        assert ledger.exposure_nanos() == adapter.bound


def test_caller_cancellation_and_cost_cannot_suppress_or_forge_settlement(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    cancelled = threading.Event()
    cancelled.set()
    assert engine.complete(MESSAGES, "code", usage_cancelled=cancelled,
                           cost_actual=-100, trace_id="untrusted").success
    row = attempts(engine)[0]
    assert row["state"] == "SETTLED" and row["actual_cost_nanos"] == 10_000_000
    usage = engine.store.recall_usage(UsageWindow.last_hours(1))
    assert len(usage) == 1 and usage[0].cost_actual == 0.01
    with HardBudgetStore.open(engine.store.database_path) as ledger:
        assert ledger.exposure_nanos() == 10_000_000


def test_baseexception_preserves_uncertain_liability(tmp_path: Path) -> None:
    adapter = OfflineAdapter(KeyboardInterrupt())
    engine = engine_at(tmp_path, adapter)
    with pytest.raises(KeyboardInterrupt):
        engine.complete(MESSAGES, "code")
    assert attempts(engine)[0]["state"] == "UNCERTAIN"


def test_breach_freezes_and_does_not_retry(tmp_path: Path) -> None:
    adapter = OfflineAdapter(response(charge=21_000_000))
    engine = engine_at(tmp_path, adapter)
    assert not engine.complete(MESSAGES, "code").success
    assert attempts(engine)[0]["state"] == "BREACH"
    assert not engine.complete(MESSAGES, "code").success
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("change", ["wire", "config", "output", "model", "simulated"])
def test_prepared_tampering_never_reaches_transport(tmp_path: Path, change: str) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    prepared = engine.prepare_bounded(MODEL, MESSAGES)
    if change == "wire":
        prepared = replace(prepared, wire_json=prepared.wire_json.replace("hi", "changed"))
    elif change == "config":
        prepared = replace(prepared, config_json=canonical_json({"cache": True}))
    elif change == "output":
        prepared = replace(prepared, quote=replace(prepared.quote, max_output_tokens=100))
    elif change == "model":
        prepared = replace(prepared, quote=replace(prepared.quote, model="alias"))
    else:
        prepared = replace(prepared, simulated=False)
    with pytest.raises(BudgetRefused):
        engine.reserve_bounded_pair((prepared, prepared), scope_limit_nanos=100_000_000, metadata=({}, {}))
    assert not adapter.calls and not attempts(engine)


def test_mutating_original_messages_does_not_mutate_prepared(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    messages = [{"role": "user", "content": "original"}]
    prepared = engine.prepare_bounded(MODEL, messages)
    messages[0]["content"] = "changed"
    assert prepared.messages()[0]["content"] == "original"


def test_atomic_pair_capacity_denial_executes_neither(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    prepared = engine.prepare_bounded(MODEL, MESSAGES)
    with pytest.raises(BudgetRefused):
        engine.reserve_bounded_pair((prepared, prepared), scope_limit_nanos=adapter.bound,
                                    metadata=({}, {}))
    assert not adapter.calls and not attempts(engine)


def test_prepared_pair_runs_once_each_with_exact_linkage(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    prepared = engine.prepare_bounded(MODEL, MESSAGES)
    reservations = engine.reserve_bounded_pair((prepared, prepared), scope_limit_nanos=2 * adapter.bound,
                                               metadata=({}, {}))
    assert len(attempts(engine)) == 2 and not adapter.calls
    for token in reservations:
        assert engine.complete_prepared(prepared, token, activity="code").success
    assert len(adapter.calls) == 2
    assert all(row["state"] == "SETTLED" for row in attempts(engine))
    assert not engine.complete_prepared(prepared, reservations[0], activity="code").success
    assert len(adapter.calls) == 2
    with HardBudgetStore.open(engine.store.database_path) as ledger:
        assert ledger.exposure_nanos() == 20_000_000
    assert len(engine.store.recall_usage(UsageWindow.last_hours(1))) == 2


def test_wrong_prepared_reservation_binding_denies_dispatch(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    first = engine.prepare_bounded(MODEL, MESSAGES)
    second = engine.prepare_bounded(MODEL, [{"role": "user", "content": "different"}])
    tokens = engine.reserve_bounded_pair((first, second), scope_limit_nanos=2 * adapter.bound, metadata=({}, {}))
    assert not engine.complete_prepared(second, tokens[0], activity="code").success
    assert not adapter.calls and attempts(engine)[0]["state"] == "RESERVED"


def test_duplicate_external_traces_do_not_merge_financial_requests(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    for _ in range(2):
        assert engine.complete(MESSAGES, "code", trace_id="duplicate").success
    rows = attempts(engine)
    assert len({row["request_id"] for row in rows}) == 2


def test_two_paid_attempts_keep_failed_charge_and_one_terminal_usage(tmp_path: Path) -> None:
    adapter = OfflineAdapter(BoundedFailure("known failure", charge_nanos=2_000_000,
                             evidence={"source": "trusted synthetic"}, retry_allowed=True))
    second_model = "openai/gpt-4o-mini"
    engine = engine_at(tmp_path, adapter)
    second = OfflineAdapter(response(model=second_model))
    engine = Engine(engine.store, surface="test", router=ModelRouter(
        activity_model_lists={"code": [MODEL, second_model]}, provider_keys=ProviderKeys(openai="fixture")),
        bounded_adapters={MODEL: adapter, second_model: second})
    result = engine.complete(MESSAGES, "code")
    assert result.success and result.cost == 0.012
    rows = attempts(engine)
    assert len(rows) == 2 and len({row["request_id"] for row in rows}) == 1
    assert all(row["state"] == "SETTLED" for row in rows)
    assert len(engine.store.recall_usage(UsageWindow.last_hours(1))) == 1
    with HardBudgetStore.open(engine.store.database_path) as ledger:
        assert ledger.exposure_nanos() == 12_000_000


def test_settlement_storage_failure_keeps_durable_dispatch_hold(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    with patch.object(HardBudgetStore, "settle", side_effect=sqlite3.OperationalError("readonly")):
        with pytest.raises((BudgetRefused, sqlite3.OperationalError)):
            engine.complete(MESSAGES, "code")
    assert len(adapter.calls) == 1 and attempts(engine)[0]["state"] == "DISPATCHING"


def test_response_model_mismatch_is_uncertain(tmp_path: Path) -> None:
    adapter = OfflineAdapter(response(model="unexpected"))
    engine = engine_at(tmp_path, adapter)
    assert not engine.complete(MESSAGES, "code").success
    assert attempts(engine)[0]["state"] == "UNCERTAIN"


def test_financial_usage_insert_does_not_reconnect(tmp_path: Path) -> None:
    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    with patch.object(engine.store, "_execute_write", side_effect=sqlite3.OperationalError("readonly")) as insert:
        with patch.object(engine.store, "_reconnect") as reconnect:
            with pytest.raises(sqlite3.OperationalError):
                engine.complete(MESSAGES, "code")
    assert insert.call_count == 1
    reconnect.assert_not_called()
    assert attempts(engine)[0]["state"] == "SETTLED"
    with HardBudgetStore.open(engine.store.database_path) as ledger:
        assert ledger.exposure_nanos() == 10_000_000


def test_known_local_namespace_is_pinned_to_loopback(tmp_path: Path) -> None:
    engine = engine_at(tmp_path)
    with patch("ylang.core.engine._parse_response", return_value=("ok", "ollama/qwen2.5", 1, 1, 0.0, [])):
        with patch("ylang.core.engine.litellm.completion") as transport:
            assert engine.complete(MESSAGES, "code", model="ollama/qwen2.5").success
    assert transport.call_args.kwargs["api_base"] == "http://localhost:11434"


def test_ollama_cloud_model_is_not_classified_local(tmp_path: Path) -> None:
    engine = engine_at(tmp_path)
    with patch("ylang.core.engine.litellm.completion") as transport:
        assert not engine.complete(MESSAGES, "code", model="ollama/gpt-oss:cloud").success
    transport.assert_not_called()


def test_injected_ledger_cannot_use_another_database(tmp_path: Path) -> None:
    engine = engine_at(tmp_path)
    with HardBudgetStore.open(tmp_path / "other.db") as ledger:
        with pytest.raises(BudgetRefused):
            Engine(engine.store, surface="test", budget_store=ledger)


def test_bounded_failure_retains_provider_classification(tmp_path: Path) -> None:
    adapter = MockedCompletionAdapter(
        Mock(side_effect=litellm.RateLimitError("rate limited", "openai", "gpt-4o")),
        known_failure_charge_nanos=0,
    )
    engine = engine_at(tmp_path, adapter)
    with patch("ylang.core.engine._call_litellm", return_value=("fallback", "ollama/qwen2.5", 1, 1, 0.0, [])):
        result = engine.complete(MESSAGES, "code")
    assert result.success
    rows = engine.store.recall_usage(UsageWindow.last_hours(1))
    events = json.loads(rows[0].fallback_events_json or "[]")
    assert events[0]["error_class"] == "rate_limit"
    assert attempts(engine)[0]["state"] == "SETTLED"


def test_reported_breach_takes_precedence_over_other_invalid_response_fields(tmp_path: Path) -> None:
    adapter = OfflineAdapter(replace(response(model="unexpected", charge=21_000_000),
                                     completion_tokens=100_000))
    engine = engine_at(tmp_path, adapter)
    assert not engine.complete(MESSAGES, "code").success
    row = attempts(engine)[0]
    assert row["state"] == "BREACH" and row["actual_cost_nanos"] == 21_000_000
    assert not engine.complete(MESSAGES, "code").success
    assert len(adapter.calls) == 1


def test_regular_completion_uses_hot_reloaded_output_ceiling(tmp_path: Path) -> None:
    """A valid runtime ceiling changes ordinary dispatch instead of causing a stale-limit refusal."""
    from ylang.core.runtime_settings import RuntimeSettingsStore
    from ylang.settings import Settings

    adapter = OfflineAdapter()
    store = open_store(tmp_path / "output-limit.db")
    initialize_budget(store)
    settings = Settings(provider_keys=ProviderKeys(openai="fixture-key"),
                        activity_model_lists={"code": [MODEL]},
                        hard_budget_max_output_tokens=128)
    engine = Engine(store, surface="test", base_settings=settings, bounded_adapters={MODEL: adapter})
    RuntimeSettingsStore(store._connection).set("hard_budget_max_output_tokens", "64")
    try:
        result = engine.complete(MESSAGES, "code", model=MODEL)
        assert result.success
        assert adapter.calls[0].quote.max_output_tokens == 64
    finally:
        store.close()


def test_quote_expiring_after_dispatch_does_not_discard_settled_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry gates admission; reading the completed immutable request must not reauthorize it."""
    from datetime import datetime, timedelta, timezone
    import ylang.core.bounded_completion as bounded

    class LaterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) + timedelta(hours=2)

    adapter = OfflineAdapter()
    engine = engine_at(tmp_path, adapter)
    prepared = engine.prepare_bounded(MODEL, MESSAGES)
    reservations = engine.reserve_bounded_pair((prepared, prepared), scope_limit_nanos=40_000_000,
                                               metadata=({}, {}))
    execute = adapter.execute
    def finish_after_expiry(request):
        monkeypatch.setattr(bounded, "datetime", LaterClock)
        return execute(request)
    monkeypatch.setattr(adapter, "execute", finish_after_expiry)
    try:
        result = engine.complete_prepared(prepared, reservations[0], activity="code")
        assert result.success and result.content == "hello"
        assert engine.bounded_attempt_evidence(reservations[0])["state"] == "SETTLED"
        engine.cancel_bounded(reservations[1])
    finally:
        engine.store.close()
