"""SQLite schema migrations for Ylang."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

MigrationFn = Callable[[sqlite3.Connection], None]

_MIGRATIONS: list[tuple[int, str, MigrationFn]] = []


def migration(version: int, name: str) -> Callable[[MigrationFn], MigrationFn]:
    """Register a migration function."""

    def decorator(fn: MigrationFn) -> MigrationFn:
        _MIGRATIONS.append((version, name, fn))
        _MIGRATIONS.sort(key=lambda item: item[0])
        return fn

    return decorator


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    cursor = connection.execute(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in cursor.fetchall())


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    cursor = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    )
    return cursor.fetchone() is not None


@migration(1, "facts_workspace")
def _migrate_facts_workspace(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "facts"):
        return
    if not _column_exists(connection, "facts", "workspace"):
        connection.execute(
            "ALTER TABLE facts ADD COLUMN workspace TEXT NOT NULL DEFAULT ''"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_facts_workspace_scope "
            "ON facts (workspace, scope, created_at DESC)"
        )


@migration(2, "usage_improver_context_templates")
def _migrate_usage_context_templates(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "usage"):
        return
    if not _column_exists(connection, "usage", "improver_context_templates"):
        connection.execute(
            "ALTER TABLE usage ADD COLUMN improver_context_templates TEXT"
        )


@migration(3, "templates_fts")
def _migrate_templates_fts(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS templates_fts USING fts5(
            template_id UNINDEXED,
            name,
            body,
            tags,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )


@migration(4, "usage_improver_outcome_metadata")
def _migrate_usage_improver_outcome(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "usage"):
        return
    for column, ddl in (
        ("improver_validated", "INTEGER"),
        ("improver_changed", "INTEGER"),
        ("improver_rejection_reason", "TEXT"),
        ("improver_task_class", "TEXT"),
        ("cursor_mode", "TEXT"),
        ("experiment_variant", "TEXT"),
    ):
        if not _column_exists(connection, "usage", column):
            connection.execute(f"ALTER TABLE usage ADD COLUMN {column} {ddl}")


@migration(5, "feedback_events")
def _migrate_feedback_events(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            original_text   TEXT,
            submitted_text  TEXT,
            edit_distance   INTEGER,
            usage_id        INTEGER,
            metadata_json   TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback_events (timestamp)"
    )


@migration(6, "prompt_experiments")
def _migrate_prompt_experiments(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_experiments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id   TEXT NOT NULL,
            variant_id      TEXT NOT NULL,
            config_hash     TEXT NOT NULL,
            traffic_pct     REAL NOT NULL DEFAULT 50.0,
            active          INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (experiment_id, variant_id)
        )
        """
    )


def run_migrations(connection: sqlite3.Connection) -> int:
    """Apply pending migrations; return count applied."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    cursor = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
    current = int(cursor.fetchone()[0])
    applied = 0
    for version, name, fn in _MIGRATIONS:
        if version <= current:
            continue
        fn(connection)
        connection.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, name),
        )
        applied += 1
    if applied:
        connection.commit()
    return applied
