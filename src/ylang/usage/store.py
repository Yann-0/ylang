"""SQLite usage store — one table, write on every request, read by time window."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Self

from collections.abc import Callable

from ylang.core.db import YlangDatabase, _is_readonly_error, open_connection
from ylang.core.sqlite_rows import (
    SqliteRow,
    cell_bool,
    cell_float,
    cell_int,
    cell_optional_bool,
    cell_optional_str,
    cell_str,
)
from ylang.usage.activity import normalize_usage_activity
from ylang.usage.sample import truncate_improver_input_sample

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
    improver_input_sample TEXT,
    latency_ms          INTEGER NOT NULL CHECK (latency_ms >= 0),
    success             INTEGER NOT NULL CHECK (success IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage (timestamp);
"""


def _open_connection(db_path: Path) -> sqlite3.Connection:
    return open_connection(db_path)


def from_connection(connection: sqlite3.Connection) -> UsageStore:
    """Attach a usage store to an existing SQLite connection."""
    store = UsageStore(connection)
    store._ensure_schema()
    return store


def from_database(database: YlangDatabase) -> UsageStore:
    """Attach a usage store to a shared database handle."""
    store = UsageStore(database.connection, database=database)
    store._ensure_schema()
    return store


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
    improver_input_sample: str | None
    latency_ms: int
    success: bool
    improver_context_templates: str | None = None
    improver_validated: bool | None = None
    improver_changed: bool | None = None
    improver_rejection_reason: str | None = None
    improver_task_class: str | None = None
    cursor_mode: str | None = None
    experiment_variant: str | None = None


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
        """Rolling window ending at ``now`` (UTC), spanning ``days`` calendar days."""
        anchor = now or datetime.now(timezone.utc)
        _require_utc(anchor)
        return cls(since=anchor - timedelta(days=days), until=anchor)

    @classmethod
    def last_hours(cls, hours: int, *, now: datetime | None = None) -> UsageWindow:
        """Rolling window ending at ``now`` (UTC), spanning ``hours`` hours."""
        anchor = now or datetime.now(timezone.utc)
        _require_utc(anchor)
        return cls(since=anchor - timedelta(hours=hours), until=anchor)

    @classmethod
    def all_time(cls, *, now: datetime | None = None) -> UsageWindow:
        """Window from epoch through ``now`` (UTC) for lifetime aggregates."""
        anchor = now or datetime.now(timezone.utc)
        _require_utc(anchor)
        epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
        return cls(since=epoch, until=anchor)


class UsageStore:
    """Thin wrapper around a SQLite connection for usage events."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        database: YlangDatabase | None = None,
    ) -> None:
        self._database = database
        self._connection = connection
        self._reconnect: Callable[[], None] | None = None

    def bind_reconnect(self, callback: Callable[[], None]) -> None:
        """Register a callback to refresh all stores after a read-only write failure."""
        self._reconnect = callback

    @classmethod
    def open(cls, db_path: Path) -> Self:
        """Open (or create) the usage database file."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = _open_connection(db_path)
        store = cls(connection)
        store._ensure_schema()
        return store

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def _ensure_schema(self) -> None:
        self._connection.executescript(_SCHEMA_SQL)
        columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(usage)").fetchall()
        }
        if "improver_input_sample" not in columns:
            self._connection.execute(
                "ALTER TABLE usage ADD COLUMN improver_input_sample TEXT"
            )
        if "improver_context_templates" not in columns:
            self._connection.execute(
                "ALTER TABLE usage ADD COLUMN improver_context_templates TEXT"
            )
        for column, ddl in (
            ("improver_validated", "INTEGER"),
            ("improver_changed", "INTEGER"),
            ("improver_rejection_reason", "TEXT"),
            ("improver_task_class", "TEXT"),
            ("cursor_mode", "TEXT"),
            ("experiment_variant", "TEXT"),
        ):
            if column not in columns:
                self._connection.execute(f"ALTER TABLE usage ADD COLUMN {column} {ddl}")
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
        improver_input_sample: str | None = None,
        improver_context_templates: str | None = None,
        improver_validated: bool | None = None,
        improver_changed: bool | None = None,
        improver_rejection_reason: str | None = None,
        improver_task_class: str | None = None,
        cursor_mode: str | None = None,
        experiment_variant: str | None = None,
    ) -> None:
        """Insert one per-request usage row. Commits immediately."""
        when = timestamp or datetime.now(timezone.utc)
        sample = truncate_improver_input_sample(improver_input_sample)
        params = (
            _to_iso(when),
            surface,
            normalize_usage_activity(activity),
            model_used,
            prompt_tokens,
            cost,
            int(improver_fired),
            int(improver_accepted),
            sample,
            latency_ms,
            int(success),
            improver_context_templates,
            int(improver_validated) if improver_validated is not None else None,
            int(improver_changed) if improver_changed is not None else None,
            improver_rejection_reason,
            improver_task_class,
            cursor_mode,
            experiment_variant,
        )
        try:
            self._execute_write(params)
        except sqlite3.OperationalError as exc:
            if not _is_readonly_error(exc):
                raise
            if self._reconnect is not None:
                self._reconnect()
            elif self._database is not None:
                self._database.reconnect()
                self._connection = self._database.connection
            else:
                raise
            self._execute_write(params)

    def _execute_write(self, params: tuple[object, ...]) -> None:
        if len(params) == 11:
            self._connection.execute(
                """
                INSERT INTO usage (
                    timestamp, surface, activity, model_used, prompt_tokens, cost,
                    improver_fired, improver_accepted, improver_input_sample,
                    latency_ms, success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        elif len(params) == 12:
            self._connection.execute(
                """
                INSERT INTO usage (
                    timestamp, surface, activity, model_used, prompt_tokens, cost,
                    improver_fired, improver_accepted, improver_input_sample,
                    latency_ms, success, improver_context_templates
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        else:
            self._connection.execute(
                """
                INSERT INTO usage (
                    timestamp, surface, activity, model_used, prompt_tokens, cost,
                    improver_fired, improver_accepted, improver_input_sample,
                    latency_ms, success, improver_context_templates,
                    improver_validated, improver_changed, improver_rejection_reason,
                    improver_task_class, cursor_mode, experiment_variant
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        self._connection.commit()

    def update_last_improver_accepted(self, accepted: bool) -> None:
        """Set improver_accepted on the most recently inserted usage row."""
        self._connection.execute(
            """
            UPDATE usage
            SET improver_accepted = ?
            WHERE id = (SELECT id FROM usage ORDER BY id DESC LIMIT 1)
            """,
            (int(accepted),),
        )
        self._connection.commit()

    def update_last_improver_context_templates(self, template_ids: list[str]) -> None:
        """Attach reference template ids to the most recent usage row."""
        if not template_ids:
            return
        joined = ",".join(template_ids)
        self._connection.execute(
            """
            UPDATE usage
            SET improver_context_templates = ?
            WHERE id = (SELECT id FROM usage ORDER BY id DESC LIMIT 1)
            """,
            (joined,),
        )
        self._connection.commit()

    def update_last_improver_outcome(
        self,
        *,
        validated: bool,
        changed: bool,
        rejection_reason: str | None = None,
        task_class: str | None = None,
        cursor_mode: str | None = None,
        experiment_variant: str | None = None,
    ) -> None:
        """Persist improver outcome metadata on the most recent usage row."""
        self._connection.execute(
            """
            UPDATE usage
            SET improver_validated = ?,
                improver_changed = ?,
                improver_rejection_reason = ?,
                improver_task_class = ?,
                cursor_mode = ?,
                experiment_variant = ?
            WHERE id = (SELECT id FROM usage ORDER BY id DESC LIMIT 1)
            """,
            (
                int(validated),
                int(changed),
                rejection_reason,
                task_class,
                cursor_mode,
                experiment_variant,
            ),
        )
        self._connection.commit()

    def latest_usage_id(self) -> int | None:
        """Return the most recently inserted usage row id."""
        cursor = self._connection.execute(
            "SELECT id FROM usage ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return int(row[0]) if row is not None else None

    def mark_late_improver_orphans(self, *, after_id: int) -> int:
        """Mark late successful improver rows after a timeout stub as skipped.

        Used when a wall-clock timeout already recorded the outcome and a
        background ``Engine.complete`` still managed to write a usage row.
        Returns the number of rows neutralized.
        """
        cursor = self._connection.execute(
            """
            UPDATE usage
            SET success = 0,
                improver_fired = 0,
                improver_validated = 0,
                improver_changed = 0,
                improver_rejection_reason = 'improver timeout orphan'
            WHERE id > ?
              AND improver_fired = 1
              AND success = 1
            """,
            (after_id,),
        )
        self._connection.commit()
        return int(cursor.rowcount)

    def recall_usage(self, window: UsageWindow) -> list[UsageRecord]:
        """Return usage rows with timestamp in [since, until), newest first."""
        cursor = self._connection.execute(
            """
            SELECT
                id, timestamp, surface, activity, model_used, prompt_tokens, cost,
                improver_fired, improver_accepted, improver_input_sample,
                latency_ms, success, improver_context_templates,
                improver_validated, improver_changed, improver_rejection_reason,
                improver_task_class, cursor_mode, experiment_variant
            FROM usage
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY timestamp DESC, id DESC
            """,
            (_to_iso(window.since), _to_iso(window.until)),
        )
        return [_row_to_record(row) for row in cursor.fetchall()]


def _row_to_record(row: SqliteRow) -> UsageRecord:
    context_templates = cell_optional_str(row, 12)
    validated = cell_optional_bool(row, 13)
    changed = cell_optional_bool(row, 14)
    rejection = cell_optional_str(row, 15)
    task_class = cell_optional_str(row, 16)
    cursor_mode = cell_optional_str(row, 17)
    experiment = cell_optional_str(row, 18)
    return UsageRecord(
        id=cell_int(row, 0),
        timestamp=_from_iso(cell_str(row, 1)),
        surface=cell_str(row, 2),
        activity=cell_str(row, 3),
        model_used=cell_str(row, 4),
        prompt_tokens=cell_int(row, 5),
        cost=cell_float(row, 6),
        improver_fired=cell_bool(row, 7),
        improver_accepted=cell_bool(row, 8),
        improver_input_sample=cell_optional_str(row, 9),
        latency_ms=cell_int(row, 10),
        success=cell_bool(row, 11),
        improver_context_templates=context_templates,
        improver_validated=validated,
        improver_changed=changed,
        improver_rejection_reason=rejection,
        improver_task_class=task_class,
        cursor_mode=cursor_mode,
        experiment_variant=experiment,
    )


def open_store(db_path: Path) -> UsageStore:
    """Open the usage store at the given path."""
    return UsageStore.open(db_path)
