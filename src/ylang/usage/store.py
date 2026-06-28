"""SQLite usage store — one table, write on every request, read by time window."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Self

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    surface             TEXT    NOT NULL,
    activity            TEXT    NOT NULL,
    model_used          TEXT    NOT NULL,
    prompt_tokens       INTEGER NOT NULL CHECK (prompt_tokens >= 0),
    cost                REAL    NOT NULL CHECK (cost >= 0),
    improver_fired      INTEGER NOT NULL CHECK (improver_fired IN (0, 1)),
    improver_accepted   INTEGER NOT NULL CHECK (improver_accepted IN (0, 1)),
    latency_ms          INTEGER NOT NULL CHECK (latency_ms >= 0),
    success             INTEGER NOT NULL CHECK (success IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage (timestamp);
"""


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None:
        msg = "datetime must be timezone-aware"
        raise ValueError(msg)
    if value.utcoffset() != timedelta(0):
        msg = "datetime must be UTC"
        raise ValueError(msg)


def _to_iso(value: datetime) -> str:
    _require_utc(value)
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    _require_utc(parsed)
    return parsed


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One persisted usage row."""

    id: int
    timestamp: datetime
    surface: str
    activity: str
    model_used: str
    prompt_tokens: int
    cost: float
    improver_fired: bool
    improver_accepted: bool
    latency_ms: int
    success: bool


@dataclass(frozen=True, slots=True)
class UsageWindow:
    """Half-open UTC time range: [since, until)."""

    since: datetime
    until: datetime

    def __post_init__(self) -> None:
        _require_utc(self.since)
        _require_utc(self.until)
        if self.since >= self.until:
            msg = "since must be strictly before until"
            raise ValueError(msg)

    @classmethod
    def last_days(cls, days: int, *, now: datetime | None = None) -> UsageWindow:
        anchor = now or datetime.now(timezone.utc)
        _require_utc(anchor)
        return cls(since=anchor - timedelta(days=days), until=anchor)

    @classmethod
    def last_hours(cls, hours: int, *, now: datetime | None = None) -> UsageWindow:
        anchor = now or datetime.now(timezone.utc)
        _require_utc(anchor)
        return cls(since=anchor - timedelta(hours=hours), until=anchor)


class UsageStore:
    """Thin wrapper around a SQLite connection for usage events."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, db_path: Path) -> Self:
        """Open (or create) the usage database file."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path)
        store = cls(connection)
        store._ensure_schema()
        return store

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def _ensure_schema(self) -> None:
        self._connection.executescript(_SCHEMA_SQL)
        self._connection.commit()

    def write_usage(
        self,
        *,
        surface: str,
        activity: str,
        model_used: str,
        prompt_tokens: int,
        cost: float,
        improver_fired: bool,
        improver_accepted: bool,
        latency_ms: int,
        success: bool,
        timestamp: datetime | None = None,
    ) -> None:
        """Insert one per-request usage row. Commits immediately."""
        when = timestamp or datetime.now(timezone.utc)
        self._connection.execute(
            """
            INSERT INTO usage (
                timestamp, surface, activity, model_used, prompt_tokens, cost,
                improver_fired, improver_accepted, latency_ms, success
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _to_iso(when),
                surface,
                activity,
                model_used,
                prompt_tokens,
                cost,
                int(improver_fired),
                int(improver_accepted),
                latency_ms,
                int(success),
            ),
        )
        self._connection.commit()

    def recall_usage(self, window: UsageWindow) -> list[UsageRecord]:
        """Return usage rows with timestamp in [since, until), newest first."""
        cursor = self._connection.execute(
            """
            SELECT
                id, timestamp, surface, activity, model_used, prompt_tokens, cost,
                improver_fired, improver_accepted, latency_ms, success
            FROM usage
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY timestamp DESC, id DESC
            """,
            (_to_iso(window.since), _to_iso(window.until)),
        )
        return [_row_to_record(row) for row in cursor.fetchall()]


def _row_to_record(row: tuple[object, ...]) -> UsageRecord:
    return UsageRecord(
        id=int(row[0]),
        timestamp=_from_iso(str(row[1])),
        surface=str(row[2]),
        activity=str(row[3]),
        model_used=str(row[4]),
        prompt_tokens=int(row[5]),
        cost=float(row[6]),
        improver_fired=bool(row[7]),
        improver_accepted=bool(row[8]),
        latency_ms=int(row[9]),
        success=bool(row[10]),
    )


def open_store(db_path: Path) -> UsageStore:
    """Open the usage store at the given path."""
    return UsageStore.open(db_path)
