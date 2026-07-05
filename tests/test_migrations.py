"""Schema migration tests."""

from __future__ import annotations

from pathlib import Path

from ylang.core.db import open_connection
from ylang.core.migrations import run_migrations


def test_run_migrations_creates_fts(db_path: Path) -> None:
    connection = open_connection(db_path)
    try:
        cursor = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'templates_fts'"
        )
        assert cursor.fetchone() is not None
    finally:
        connection.close()


def test_migrations_idempotent(db_path: Path) -> None:
    connection = open_connection(db_path)
    try:
        first = run_migrations(connection)
        second = run_migrations(connection)
        assert second == 0
        assert first >= 0
    finally:
        connection.close()


def test_run_migrations_adds_facts_workspace(db_path: Path) -> None:
    from ylang.core.memory import MemoryStore

    connection = open_connection(db_path)
    try:
        run_migrations(connection)
        MemoryStore.from_connection(connection).remember("test", "private")
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(facts)").fetchall()
        }
        assert "workspace" in columns
    finally:
        connection.close()
