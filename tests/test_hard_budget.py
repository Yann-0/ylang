"""Financial admission, durability and migration acceptance using private synthetic SQLite."""
from __future__ import annotations

import multiprocessing
import os
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ylang.core.migrations import run_migrations
from ylang.usage.hard_budget import (
    MAX_NANOS, BudgetRefused, CostQuote, HardBudgetStore, usd_to_nanos,
)
from ylang.usage.store import UsageStore

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ONE = 1_000_000_000


def quote(cost: int = 600_000_000, *, now: datetime = NOW) -> CostQuote:
    """Supply a bounded synthetic attempt with immutable identities."""
    return CostQuote("synthetic/model", "synthetic:test", "offline", "v1",
                     now + timedelta(hours=1), "a" * 64, "b" * 64, cost, 32, 64)


@pytest.fixture
def ledger(tmp_path: Path):
    """Create an acknowledged empty ledger under one fixed synthetic clock."""
    with HardBudgetStore.open(tmp_path / "budget.db", clock=lambda: NOW) as store:
        store.initialize_policy(limit_nanos=ONE, opening_evidence="empty synthetic fixture")
        yield store


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1e100", "bad", 1.0, True])
def test_invalid_money_refused(value: Any) -> None:
    """Financial authorities never accept binary floats or nonfinite amounts."""
    with pytest.raises(BudgetRefused):
        usd_to_nanos(value)


def test_rounding_is_conservative_beyond_decimal_default_precision() -> None:
    """Sub-nano fractions do not disappear through Decimal's default precision."""
    assert usd_to_nanos("0.000000001000000000000000000000000000000000001") == 2
    assert usd_to_nanos("0.000000001999999999999999999999999999999999999", cap=True) == 1
    assert usd_to_nanos(Decimal("0")) == 0


@pytest.mark.parametrize("changes", [
    {"expires_at": NOW}, {"expires_at": NOW.replace(tzinfo=None)},
    {"request_hash": "unknown"}, {"config_hash": ""},
    {"model": ""}, {"account_id": ""}, {"pricing_version": ""},
    {"max_cost_nanos": True}, {"max_cost_nanos": -1}, {"max_cost_nanos": MAX_NANOS + 1},
    {"input_token_bound": -1}, {"max_output_tokens": 0},
])
def test_invalid_quote_refuses_before_reservation(ledger: HardBudgetStore, changes: dict) -> None:
    """Unknown bounds, identities or expiries cannot consume admission."""
    with pytest.raises(BudgetRefused):
        ledger.reserve_many([replace(quote(), **changes)])
    assert ledger.exposure_nanos() == 0


def test_pair_is_all_or_nothing_and_exact_cap_is_reserved(ledger: HardBudgetStore) -> None:
    """Insufficient aggregate capacity creates neither arm nor a partial hold."""
    with pytest.raises(BudgetRefused):
        ledger.reserve_many([quote(), quote()], scope_limit_nanos=ONE)
    assert ledger.exposure_nanos() == 0
    arms = ledger.reserve_many([quote(400_000_000), quote()], scope_limit_nanos=ONE)
    assert len(arms) == 2
    assert arms[0].scope_id == arms[1].scope_id
    assert arms[0].request_id != arms[1].request_id
    assert ledger.exposure_nanos() == ONE
    with pytest.raises(BudgetRefused):
        ledger.reserve_many([quote(1)])


def test_scope_cap_and_retry_cap_share_the_same_transaction(ledger: HardBudgetStore) -> None:
    """A large daily allowance cannot bypass an evaluation's lifetime limit."""
    with pytest.raises(BudgetRefused):
        ledger.reserve_many([quote(1), quote(2)], scope_limit_nanos=2)
    first, second = ledger.reserve_many([quote(100), quote(100)], scope_limit_nanos=200)
    token = ledger.begin_dispatch(first)
    ledger.settle(token, 100, evidence={"receipt": "one"})
    with pytest.raises(BudgetRefused):
        ledger.reserve_many([quote(1)], request_id=first.request_id)
    ledger.cancel(second)
    assert ledger.exposure_nanos() == 100


def test_uncertain_holds_and_fences_survive_reopen(tmp_path: Path) -> None:
    """A crash/restart or rolling-window change cannot release unknown billing."""
    path = tmp_path / "durable.db"
    with HardBudgetStore.open(path, clock=lambda: NOW) as store:
        store.initialize_policy(limit_nanos=ONE, opening_evidence="empty synthetic fixture")
        (reserved,) = store.reserve_many([quote()])
        token = store.begin_dispatch(reserved)
        store.settle(token, None, evidence={"timeout": "unknown billability"})
    future = NOW + timedelta(days=2)
    with HardBudgetStore.open(path, clock=lambda: future) as store:
        assert store.exposure_nanos() == 600_000_000
        with pytest.raises(BudgetRefused):
            store.cancel(reserved)
        with pytest.raises(BudgetRefused):
            store.reserve_many([quote(500_000_000, now=future)], request_id=reserved.request_id)
        with pytest.raises(BudgetRefused):
            store.reconcile(reserved.attempt_id, 0, evidence={})
        store.reconcile(reserved.attempt_id, 0, evidence={"billability_confirmed": True, "receipt": "synthetic zero"})
        assert store.exposure_nanos() == 0


def test_cancel_and_dispatch_compete_for_one_fenced_transition(ledger: HardBudgetStore) -> None:
    """Cancellation before dispatch cannot leave a stale token able to send later."""
    (reserved,) = ledger.reserve_many([quote()])
    ledger.cancel(reserved)
    ledger.cancel(reserved)
    with pytest.raises(BudgetRefused):
        ledger.begin_dispatch(reserved)
    assert ledger.exposure_nanos() == 0


def test_terminal_settlement_is_idempotent_and_conflicts_refused(ledger: HardBudgetStore) -> None:
    """Repeated callbacks do not double count or replace a settled charge."""
    (reserved,) = ledger.reserve_many([quote()])
    token = ledger.begin_dispatch(reserved)
    ledger.settle(token, 200_000_000, evidence={"receipt": "stable"})
    ledger.settle(token, 200_000_000, evidence={"receipt": "stable"})
    with pytest.raises(BudgetRefused):
        ledger.settle(token, 0, evidence={"receipt": "other"})
    assert ledger.exposure_nanos() == 200_000_000


def test_bound_breach_records_actual_charge_and_freezes_admission(ledger: HardBudgetStore) -> None:
    """An out-of-contract bill is retained and disables further paid admission."""
    (reserved,) = ledger.reserve_many([quote()])
    ledger.settle(ledger.begin_dispatch(reserved), 700_000_000, evidence={"receipt": "breach"})
    assert ledger.get_attempt(reserved.attempt_id)["state"] == "BREACH"
    assert ledger.exposure_nanos() == 700_000_000
    with pytest.raises(BudgetRefused):
        ledger.reserve_many([quote(1)])


def test_backward_clock_freeze_persists_after_restart(tmp_path: Path) -> None:
    """Restoring the clock cannot silently clear a detected accounting anomaly."""
    clock = [NOW]
    path = tmp_path / "clock.db"
    with HardBudgetStore.open(path, clock=lambda: clock[0]) as store:
        store.initialize_policy(limit_nanos=ONE, opening_evidence="empty synthetic fixture")
        clock[0] -= timedelta(microseconds=1)
        with pytest.raises(BudgetRefused):
            store.reserve_many([quote(1)])
    with HardBudgetStore.open(path, clock=lambda: NOW + timedelta(seconds=1)) as store:
        with pytest.raises(BudgetRefused):
            store.reserve_many([quote(1)])


def _insert_usage(connection: sqlite3.Connection, cost: float = 0.2) -> int:
    """Insert a terminal fixture row without stealing transaction ownership."""
    row = connection.execute(
        "INSERT INTO usage(timestamp,surface,activity,model_used,prompt_tokens,cost,"
        "improver_fired,improver_accepted,latency_ms,success) VALUES (?,'test','other',"
        "'synthetic/model',1,?,0,0,1,1)", (NOW.isoformat(), cost),
    )
    assert row.lastrowid is not None
    return row.lastrowid


def test_usage_link_is_atomic_idempotent_and_excludes_double_count(ledger: HardBudgetStore) -> None:
    """Use the actual inserted row ID while retaining financial request identity."""
    (reserved,) = ledger.reserve_many([quote()], metadata=[{"trace_id": "duplicate"}])
    ledger.settle(ledger.begin_dispatch(reserved), 200_000_000, evidence={"receipt": "ok"})
    def fail_after_insert(connection: sqlite3.Connection) -> int:
        _insert_usage(connection)
        raise RuntimeError("injected write/link failure")
    with pytest.raises(RuntimeError):
        ledger.link_usage(reserved.request_id, fail_after_insert)
    with sqlite3.connect(ledger.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == 0
    row_id = ledger.link_usage(reserved.request_id, _insert_usage)
    assert ledger.link_usage(reserved.request_id, lambda c: pytest.fail("duplicate insert")) == row_id
    assert ledger.exposure_nanos() == 200_000_000
    with sqlite3.connect(ledger.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM usage WHERE id=?", (row_id,))


def test_legacy_cost_and_opening_liability_are_not_free(tmp_path: Path) -> None:
    """Retrospective usage plus acknowledged unknown liability both reduce capacity."""
    path = tmp_path / "legacy.db"
    with HardBudgetStore.open(path, clock=lambda: NOW) as store:
        with sqlite3.connect(path) as connection:
            _insert_usage(connection, 0.2)
        store.initialize_policy(limit_nanos=ONE, opening_liability_nanos=200_000_000,
                                opening_evidence="reviewed synthetic opening liability")
        assert store.exposure_nanos() == 400_000_000
        with pytest.raises(BudgetRefused):
            store.reserve_many([quote(600_000_001)])


def test_invalid_legacy_timestamp_cannot_expire_unknown_liability(tmp_path: Path) -> None:
    """Malformed historic records deny admission rather than falling out of SQL windows."""
    path = tmp_path / "unknown.db"
    with HardBudgetStore.open(path, clock=lambda: NOW) as store:
        with sqlite3.connect(path) as connection:
            row = _insert_usage(connection)
            connection.execute("UPDATE usage SET timestamp='unknown' WHERE id=?", (row,))
        store.initialize_policy(limit_nanos=ONE, opening_evidence="synthetic legacy fixture")
        with pytest.raises(BudgetRefused):
            store.reserve_many([quote(1)])


def _competing_admission(path: str, barrier: Any, queue: Any) -> None:
    """Synchronize before admission; denied workers never enter a provider callback."""
    with HardBudgetStore.open(Path(path), clock=lambda: NOW) as store:
        barrier.wait(timeout=15)
        try:
            store.reserve_many([quote()])
            queue.put("admitted")
        except BudgetRefused:
            queue.put("denied")


def test_separate_processes_cannot_spend_the_same_allowance(tmp_path: Path) -> None:
    """SQLite writer serialization enforces one aggregate cap across processes."""
    path = tmp_path / "concurrent.db"
    with HardBudgetStore.open(path, clock=lambda: NOW) as store:
        store.initialize_policy(limit_nanos=ONE, opening_evidence="empty synthetic fixture")
    context = multiprocessing.get_context("spawn")
    barrier, queue = context.Barrier(3), context.Queue()
    processes = [context.Process(target=_competing_admission, args=(str(path), barrier, queue)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        barrier.wait(timeout=15)
        results = sorted(queue.get(timeout=20) for _ in processes)
        assert results == ["admitted", "denied"]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
        queue.close()
    with HardBudgetStore.open(path, clock=lambda: NOW) as store:
        assert store.exposure_nanos() == 600_000_000


def _crash_after_intent(path: str, pipe: Any) -> None:
    """Exit after durable dispatch intent without creating a terminal charge."""
    with HardBudgetStore.open(Path(path), clock=lambda: NOW) as store:
        (reserved,) = store.reserve_many([quote()])
        store.begin_dispatch(reserved)
        pipe.send(reserved.attempt_id)
        pipe.close()
        os._exit(0)


def test_process_death_after_dispatch_intent_retains_hold(tmp_path: Path) -> None:
    """Recovery does not treat missing terminal evidence as a free failed attempt."""
    path = tmp_path / "crash.db"
    with HardBudgetStore.open(path, clock=lambda: NOW) as store:
        store.initialize_policy(limit_nanos=ONE, opening_evidence="empty synthetic fixture")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_crash_after_intent, args=(str(path), child))
    process.start()
    try:
        assert parent.poll(20)
        attempt_id = parent.recv()
        process.join(20)
        assert process.exitcode == 0
        with HardBudgetStore.open(path, clock=lambda: NOW + timedelta(days=3)) as store:
            assert store.get_attempt(attempt_id)["state"] == "DISPATCHING"
            assert store.exposure_nanos() == 600_000_000
    finally:
        parent.close()
        child.close()
        if process.is_alive():
            process.terminate()
            process.join()


def test_migration_preserves_existing_rows_and_is_idempotent(tmp_path: Path) -> None:
    """Adding ledger tables leaves prior usage facts intact across a repeated migration."""
    path = tmp_path / "migration.db"
    usage = UsageStore.open(path)
    usage.close()
    with sqlite3.connect(path) as connection:
        _insert_usage(connection)
        before = connection.execute("SELECT * FROM usage").fetchall()
        for table in ["budget_attempts", "budget_requests", "budget_scopes", "budget_policies"]:
            connection.execute("DROP TABLE " + table)
        connection.execute("DELETE FROM schema_migrations WHERE version=17")
        connection.commit()
        assert run_migrations(connection) == 1
        assert run_migrations(connection) == 0
        assert connection.execute("SELECT * FROM usage").fetchall() == before
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO budget_policies VALUES ('other',1,0,'fixture',0,1,NULL)")
