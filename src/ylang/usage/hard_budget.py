"""Durable per-attempt reservations for one canonical local USD budget domain."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
from pathlib import Path
from typing import Self

NANOS_PER_USD = 1_000_000_000
MAX_NANOS = (1 << 63) - 1
_ACTIVE = frozenset({"RESERVED", "DISPATCHING", "UNCERTAIN"})
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class BudgetRefused(ValueError):
    """A required monetary bound, policy or state transition is unavailable."""


def checked_nanos(value: int) -> int:
    """Reject noninteger, negative and out-of-range monetary authorities."""
    if type(value) is not int or not 0 <= value <= MAX_NANOS:
        raise BudgetRefused("money must be an integer nano-USD amount in range")
    return value


def usd_to_nanos(value: str | Decimal, *, cap: bool = False) -> int:
    """Floor caps and ceil charges without using binary float authority."""
    if not isinstance(value, (str, Decimal)):
        raise BudgetRefused("USD authority must be a Decimal or decimal string")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0 or amount > MAX_NANOS:
            raise BudgetRefused("USD authority must be finite, nonnegative and in range")
        with localcontext() as context:
            context.prec = max(50, len(amount.as_tuple().digits) + 12)
            scaled = amount * NANOS_PER_USD
            rounded = scaled.to_integral_value(rounding=ROUND_FLOOR if cap else ROUND_CEILING)
            return checked_nanos(int(rounded))
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise BudgetRefused("invalid decimal USD authority") from exc


def _time_us(value: datetime) -> int:
    """Convert an aware UTC timestamp to integer microseconds without float rounding."""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise BudgetRefused("budget timestamps must be aware UTC")
    delta = value - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


@dataclass(frozen=True, slots=True)
class CostQuote:
    """Immutable adapter-certified upper bound for one exact prepared attempt."""
    model: str
    adapter_id: str
    account_id: str
    pricing_version: str
    expires_at: datetime
    request_hash: str
    config_hash: str
    max_cost_nanos: int
    input_token_bound: int
    max_output_tokens: int

    def validate(self, now: datetime) -> None:
        """Refuse expired, incomplete or unsupported quote identities and limits."""
        checked_nanos(self.max_cost_nanos)
        if any(not isinstance(x, str) or not x.strip() for x in (
            self.model, self.adapter_id, self.account_id, self.pricing_version
        )):
            raise BudgetRefused("quote identity is incomplete")
        if any(not isinstance(x, str) or re.fullmatch(r"[0-9a-f]{64}", x) is None for x in (
            self.request_hash, self.config_hash
        )):
            raise BudgetRefused("quote requires exact request and configuration digests")
        if _time_us(self.expires_at) <= _time_us(now):
            raise BudgetRefused("quote expired before dispatch")
        if type(self.input_token_bound) is not int or not 0 <= self.input_token_bound <= MAX_NANOS:
            raise BudgetRefused("missing input token upper bound")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= MAX_NANOS:
            raise BudgetRefused("missing enforced output token ceiling")

    def to_json(self) -> str:
        """Serialize quote facts without storing request bodies or provider secrets."""
        data = asdict(self)
        data["expires_at"] = self.expires_at.isoformat()
        return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, raw: str) -> Self:
        """Recover immutable quote facts from a reserved attempt."""
        data = json.loads(raw)
        data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class Reservation:
    """Internally generated attempt identity and its compare-and-swap fencing token."""
    attempt_id: str
    request_id: str
    scope_id: str | None
    fence: int


class HardBudgetStore:
    """Own a serialized connection for reservation, settlement and usage-link transactions."""

    def __init__(self, connection: sqlite3.Connection, clock: Callable[[], datetime]) -> None:
        """Keep financial transactions separate from shared application-store connections."""
        self._connection = connection
        self.database_path = Path(connection.execute("PRAGMA database_list").fetchone()[2]).resolve()
        self._clock = clock
        self._lock = threading.RLock()

    @classmethod
    def open(cls, path: Path, *, clock: Callable[[], datetime] | None = None) -> Self:
        """Open a dedicated local ledger connection and bootstrap versioned schemas."""
        from ylang.usage.store import UsageStore

        path = Path(path).expanduser().resolve()
        bootstrap = UsageStore.open(path)
        bootstrap.close()
        connection = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return cls(connection, clock or (lambda: datetime.now(timezone.utc)))

    def __enter__(self) -> Self:
        """Allow deterministic closure of the owned financial connection."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close this connection after the caller's operation."""
        self.close()

    def close(self) -> None:
        """Close only this ledger's owned connection."""
        with self._lock:
            self._connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize threads and acquire SQLite's cross-process writer lock before admission."""
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise

    def initialize_policy(
        self, *, limit_nanos: int, opening_liability_nanos: int = 0, opening_evidence: str,
    ) -> None:
        """Install one canonical policy only after an explicit opening-liability acknowledgement."""
        checked_nanos(limit_nanos)
        checked_nanos(opening_liability_nanos)
        if not isinstance(opening_evidence, str) or not opening_evidence.strip():
            raise BudgetRefused("reviewed opening-liability evidence is required")
        with self._transaction() as connection:
            if connection.execute("SELECT 1 FROM budget_policies").fetchone():
                raise BudgetRefused("canonical policy already exists; settings cannot replace it")
            connection.execute(
                "INSERT INTO budget_policies(policy_id,limit_nanos,opening_liability_nanos,opening_evidence,last_now_us)"
                " VALUES ('default',?,?,?,?)",
                (limit_nanos, opening_liability_nanos, opening_evidence, _time_us(self._clock())),
            )

    def _policy(self, connection: sqlite3.Connection, now: datetime) -> sqlite3.Row:
        """Check canonical policy, monotonic UTC watermark and frozen state inside admission."""
        policy = connection.execute(
            "SELECT * FROM budget_policies WHERE policy_id='default'"
        ).fetchone()
        if policy is None:
            raise BudgetRefused("canonical hard-budget policy is not initialized")
        stamp = _time_us(now)
        if stamp < policy["last_now_us"]:
            connection.execute(
                "UPDATE budget_policies SET frozen_reason='backward_clock' WHERE policy_id='default'"
            )
            connection.commit()
            raise BudgetRefused("clock moved backward; paid admission is frozen")
        if policy["frozen_reason"] is not None:
            raise BudgetRefused("hard-budget policy frozen: " + str(policy["frozen_reason"]))
        connection.execute(
            "UPDATE budget_policies SET last_now_us=? WHERE policy_id='default'", (stamp,),
        )
        return policy

    def _exposure(self, connection: sqlite3.Connection, now: datetime, scope_id: str | None = None) -> int:
        """Count active holds at every age and settled charges in the policy or scope window."""
        total = 0
        if scope_id is None:
            policy = connection.execute(
                "SELECT opening_liability_nanos FROM budget_policies WHERE policy_id='default'"
            ).fetchone()
            if policy is None:
                raise BudgetRefused("canonical hard-budget policy is not initialized")
            total = checked_nanos(policy[0])
        for row in connection.execute(
            "SELECT a.state,a.max_cost_nanos,a.actual_cost_nanos,a.dispatched_at_us,r.scope_id"
            " FROM budget_attempts a JOIN budget_requests r USING(request_id)"
        ):
            if scope_id is not None and row["scope_id"] != scope_id:
                continue
            state = row["state"]
            if state in _ACTIVE:
                total += checked_nanos(row["max_cost_nanos"])
            elif state == "BREACH":
                total += max(checked_nanos(row["max_cost_nanos"]), checked_nanos(row["actual_cost_nanos"]))
            elif state == "SETTLED" and (
                scope_id is not None or row["dispatched_at_us"] >= _time_us(now - timedelta(days=1))
            ):
                total += checked_nanos(row["actual_cost_nanos"])
            checked_nanos(total)
        if scope_id is None:
            for timestamp, cost in connection.execute(
                "SELECT u.timestamp,u.cost FROM usage u LEFT JOIN budget_requests r ON r.usage_row_id=u.id"
                " WHERE r.request_id IS NULL",
            ):
                try:
                    stamp = _time_us(datetime.fromisoformat(timestamp))
                except (TypeError, ValueError) as exc:
                    raise BudgetRefused("unknown historical usage timestamp") from exc
                if stamp < _time_us(now - timedelta(days=1)):
                    continue
                if cost is None:
                    raise BudgetRefused("unknown historical usage liability")
                total += usd_to_nanos(str(cost))
                checked_nanos(total)
        return total

    def exposure_nanos(self) -> int:
        """Read current aggregate liability under the same serialized writer boundary."""
        with self._transaction() as connection:
            return self._exposure(connection, self._clock())

    def reserve_many(
        self, quotes: Sequence[CostQuote], *, scope_limit_nanos: int | None = None,
        metadata: Sequence[dict[str, object]] | None = None, request_id: str | None = None,
    ) -> tuple[Reservation, ...]:
        """Reserve an entire attempt batch atomically before dispatching any member."""
        if not quotes or (request_id is not None and len(quotes) != 1):
            raise BudgetRefused("a nonempty batch or one existing logical request is required")
        if metadata is not None and len(metadata) != len(quotes):
            raise BudgetRefused("reservation metadata length mismatch")
        if scope_limit_nanos is not None:
            checked_nanos(scope_limit_nanos)
            if request_id is not None:
                raise BudgetRefused("an existing request cannot move to a new budget scope")
        with self._transaction() as connection:
            now = self._clock()
            policy = self._policy(connection, now)
            for quote in quotes:
                quote.validate(now)
            requested = checked_nanos(sum(q.max_cost_nanos for q in quotes))
            if checked_nanos(self._exposure(connection, now) + requested) > policy["limit_nanos"]:
                raise BudgetRefused("daily budget has insufficient unreserved capacity")
            scope_id = str(uuid.uuid4()) if scope_limit_nanos is not None else None
            if scope_limit_nanos is not None:
                if requested > scope_limit_nanos:
                    raise BudgetRefused("evaluation scope has insufficient unreserved capacity")
                connection.execute("INSERT INTO budget_scopes VALUES (?,'default',?)", (scope_id, scope_limit_nanos))
            result = []
            for index, quote in enumerate(quotes):
                current_request = request_id or str(uuid.uuid4())
                if request_id is None:
                    details = metadata[index] if metadata is not None else {}
                    connection.execute(
                        "INSERT INTO budget_requests(request_id,policy_id,scope_id,metadata_json) VALUES (?,'default',?,?)",
                        (current_request, scope_id, json.dumps(details, sort_keys=True, allow_nan=False)),
                    )
                else:
                    request = connection.execute(
                        "SELECT * FROM budget_requests WHERE request_id=?", (request_id,),
                    ).fetchone()
                    if request is None or request["usage_row_id"] is not None:
                        raise BudgetRefused("unknown or finalized logical request")
                    scope_id = request["scope_id"]
                    if scope_id is not None:
                        cap = connection.execute(
                            "SELECT limit_nanos FROM budget_scopes WHERE scope_id=?", (scope_id,),
                        ).fetchone()[0]
                        if checked_nanos(self._exposure(connection, now, scope_id) + requested) > cap:
                            raise BudgetRefused("evaluation scope has insufficient capacity")
                    pending = connection.execute(
                        "SELECT 1 FROM budget_attempts WHERE request_id=? AND state IN ('RESERVED','DISPATCHING','UNCERTAIN','BREACH')",
                        (request_id,),
                    ).fetchone()
                    if pending:
                        raise BudgetRefused("an unresolved attempt cannot be retried")
                ordinal = connection.execute(
                    "SELECT COALESCE(MAX(ordinal),0)+1 FROM budget_attempts WHERE request_id=?", (current_request,),
                ).fetchone()[0]
                attempt_id = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO budget_attempts(attempt_id,request_id,ordinal,state,policy_generation,quote_json,max_cost_nanos,reserved_at_us)"
                    " VALUES (?,?,?,'RESERVED',?,?,?,?)",
                    (attempt_id, current_request, ordinal, policy["generation"], quote.to_json(),
                     quote.max_cost_nanos, _time_us(now)),
                )
                result.append(Reservation(attempt_id, current_request, scope_id, 0))
            return tuple(result)

    def _attempt(self, connection: sqlite3.Connection, token: Reservation) -> sqlite3.Row:
        """Bind caller-held fencing tokens to their internally generated logical identities."""
        row = connection.execute(
            "SELECT a.*,r.scope_id FROM budget_attempts a JOIN budget_requests r USING(request_id)"
            " WHERE attempt_id=?", (token.attempt_id,),
        ).fetchone()
        if row is None or row["request_id"] != token.request_id or row["scope_id"] != token.scope_id:
            raise BudgetRefused("unknown reservation identity")
        return row

    def begin_dispatch(self, reservation: Reservation) -> Reservation:
        """Persist fenced dispatch intent after rechecking policy and quote expiry."""
        with self._transaction() as connection:
            now = self._clock()
            policy = self._policy(connection, now)
            row = self._attempt(connection, reservation)
            if row["state"] != "RESERVED" or row["fence"] != reservation.fence:
                raise BudgetRefused("reservation was dispatched, cancelled or fenced")
            if row["policy_generation"] != policy["generation"]:
                raise BudgetRefused("reservation policy generation changed")
            CostQuote.from_json(row["quote_json"]).validate(now)
            connection.execute(
                "UPDATE budget_attempts SET state='DISPATCHING',fence=fence+1,dispatched_at_us=? WHERE attempt_id=?",
                (_time_us(now), reservation.attempt_id),
            )
            return Reservation(reservation.attempt_id, reservation.request_id, reservation.scope_id, reservation.fence + 1)

    def cancel(self, reservation: Reservation) -> None:
        """Release only a fenced reservation whose transport dispatch never began."""
        with self._transaction() as connection:
            row = self._attempt(connection, reservation)
            if row["state"] == "CANCELLED" and row["fence"] == reservation.fence + 1:
                return
            if row["state"] != "RESERVED" or row["fence"] != reservation.fence:
                raise BudgetRefused("dispatched or fenced liability cannot be cancelled")
            connection.execute(
                "UPDATE budget_attempts SET state='CANCELLED',fence=fence+1 WHERE attempt_id=?",
                (reservation.attempt_id,),
            )

    def _terminal(
        self, connection: sqlite3.Connection, row: sqlite3.Row,
        charge_nanos: int | None, evidence_json: str,
    ) -> None:
        """Replace a hold by a proven charge or preserve it as unresolved liability."""
        state = "UNCERTAIN" if charge_nanos is None else (
            "BREACH" if charge_nanos > row["max_cost_nanos"] else "SETTLED"
        )
        connection.execute(
            "UPDATE budget_attempts SET state=?,actual_cost_nanos=?,evidence_json=?,settled_at_us=?,fence=fence+1"
            " WHERE attempt_id=?",
            (state, charge_nanos, evidence_json, _time_us(self._clock()), row["attempt_id"]),
        )
        if state == "BREACH":
            connection.execute(
                "UPDATE budget_policies SET frozen_reason='certified_bound_exceeded' WHERE policy_id='default'"
            )

    def settle(
        self, token: Reservation, charge_nanos: int | None, *, evidence: dict[str, object],
    ) -> None:
        """Settle once or retain the full bound when billability remains unknown."""
        if charge_nanos is not None:
            checked_nanos(charge_nanos)
        raw = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._transaction() as connection:
            row = self._attempt(connection, token)
            if row["state"] in {"SETTLED", "UNCERTAIN", "BREACH"}:
                if row["fence"] == token.fence + 1 and row["actual_cost_nanos"] == charge_nanos and row["evidence_json"] == raw:
                    return
                raise BudgetRefused("conflicting or fenced terminal settlement")
            if row["state"] != "DISPATCHING" or row["fence"] != token.fence:
                raise BudgetRefused("attempt has not won fenced dispatch admission")
            self._terminal(connection, row, charge_nanos, raw)

    def reconcile(self, attempt_id: str, charge_nanos: int, *, evidence: dict[str, object]) -> None:
        """Apply explicit trusted billability evidence to an uncertain attempt only."""
        checked_nanos(charge_nanos)
        if evidence.get("billability_confirmed") is not True:
            raise BudgetRefused("reconciliation requires explicit trusted billability evidence")
        raw = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM budget_attempts WHERE attempt_id=?", (attempt_id,),
            ).fetchone()
            if row is None or row["state"] != "UNCERTAIN":
                raise BudgetRefused("only an explicitly uncertain attempt can be reconciled")
            self._terminal(connection, row, charge_nanos, raw)

    def get_attempt(self, attempt_id: str) -> dict[str, object]:
        """Read retained financial state without treating external traces as identity."""
        with self._lock:
            row = self._connection.execute(
                "SELECT a.*,r.scope_id,r.metadata_json AS request_metadata_json,r.usage_row_id"
                " FROM budget_attempts a JOIN budget_requests r USING(request_id) WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise BudgetRefused("unknown attempt")
            return dict(row)

    def link_usage(self, request_id: str, insert: Callable[[sqlite3.Connection], int]) -> int:
        """Commit the exact usage insert and internal request link in one owned transaction."""
        with self._transaction() as connection:
            request = connection.execute(
                "SELECT * FROM budget_requests WHERE request_id=?", (request_id,),
            ).fetchone()
            if request is None:
                raise BudgetRefused("unknown logical request")
            if request["usage_row_id"] is not None:
                return int(request["usage_row_id"])
            if connection.execute(
                "SELECT 1 FROM budget_attempts WHERE request_id=? AND state IN ('RESERVED','DISPATCHING')",
                (request_id,),
            ).fetchone():
                raise BudgetRefused("usage cannot finalize a request with undispatched or running attempts")
            row_id = insert(connection)
            if type(row_id) is not int or row_id <= 0 or not connection.in_transaction:
                raise BudgetRefused("usage writer must return its inserted row ID without committing")
            connection.execute(
                "UPDATE budget_requests SET usage_row_id=? WHERE request_id=?", (row_id, request_id),
            )
            return row_id
