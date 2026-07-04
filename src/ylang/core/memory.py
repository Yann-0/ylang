"""SQLite-backed user facts store — scoped remember/recall."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Self

from ylang.core.db import open_connection

FactScope = Literal["private", "shareable"]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('private', 'shareable')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_scope_created ON facts (scope, created_at DESC);
"""

_VALID_SCOPES = frozenset({"private", "shareable"})


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


def _validate_scope(scope: str) -> FactScope:
    if scope not in _VALID_SCOPES:
        msg = "scope must be private or shareable"
        raise ValueError(msg)
    return scope  # type: ignore[return-value]


def _validate_fact(fact: str) -> str:
    if not fact.strip():
        msg = "fact must not be empty"
        raise ValueError(msg)
    return fact


@dataclass(frozen=True, slots=True)
class Fact:
    """One persisted fact row."""

    id: int
    fact: str
    scope: FactScope
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RememberResult:
    """Result of persisting a new fact."""

    id: int
    fact: str
    scope: FactScope
    created_at: datetime


class MemoryStore:
    """Thin wrapper around a SQLite connection for scoped facts."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, db_path: Path) -> Self:
        """Open (or create) the memory database file."""
        return cls.from_connection(open_connection(db_path))

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> Self:
        """Attach a memory store to an existing SQLite connection."""
        store = cls(connection)
        store._ensure_schema()
        return store

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def _ensure_schema(self) -> None:
        self._connection.executescript(_SCHEMA_SQL)
        self._connection.commit()

    def remember(self, fact: str, scope: str) -> RememberResult:
        """Persist one fact under the given scope. Commits immediately."""
        validated_fact = _validate_fact(fact)
        validated_scope = _validate_scope(scope)
        created_at = datetime.now(timezone.utc)
        cursor = self._connection.execute(
            """
            INSERT INTO facts (fact, scope, created_at)
            VALUES (?, ?, ?)
            """,
            (validated_fact, validated_scope, _to_iso(created_at)),
        )
        self._connection.commit()
        return RememberResult(
            id=int(cursor.lastrowid),
            fact=validated_fact,
            scope=validated_scope,
            created_at=created_at,
        )

    def recall(
        self,
        *,
        scope: str | None = None,
        limit: int = 100,
    ) -> list[Fact]:
        """Return facts newest first, optionally filtered by scope."""
        if scope is not None:
            validated_scope = _validate_scope(scope)
            cursor = self._connection.execute(
                """
                SELECT id, fact, scope, created_at
                FROM facts
                WHERE scope = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (validated_scope, limit),
            )
        else:
            cursor = self._connection.execute(
                """
                SELECT id, fact, scope, created_at
                FROM facts
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [_row_to_fact(row) for row in cursor.fetchall()]


def _row_to_fact(row: tuple[object, ...]) -> Fact:
    return Fact(
        id=int(row[0]),
        fact=str(row[1]),
        scope=str(row[2]),  # type: ignore[arg-type]
        created_at=_from_iso(str(row[3])),
    )


def open_memory(db_path: Path) -> MemoryStore:
    """Open the memory store at the given path."""
    return MemoryStore.open(db_path)


_bound_store: MemoryStore | None = None


def bind_memory(store: MemoryStore) -> None:
    """Bind the module-level remember/recall helpers to a store instance."""
    global _bound_store
    _bound_store = store


def remember(fact: str, scope: str) -> RememberResult:
    """Persist a fact using the bound store."""
    if _bound_store is None:
        msg = "memory store is not bound; call bind_memory first"
        raise RuntimeError(msg)
    return _bound_store.remember(fact, scope)


def recall(*, scope: str | None = None, limit: int = 100) -> list[Fact]:
    """Recall facts using the bound store."""
    if _bound_store is None:
        msg = "memory store is not bound; call bind_memory first"
        raise RuntimeError(msg)
    return _bound_store.recall(scope=scope, limit=limit)
