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


@migration(7, "runtime_settings")
def _migrate_runtime_settings(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


@migration(8, "improver_cache")
def _migrate_improver_cache(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS improver_cache (
            cache_key    TEXT PRIMARY KEY,
            result_json  TEXT NOT NULL,
            expires_at   REAL NOT NULL
        )
        """
    )


@migration(9, "apply_audit_log")
def _migrate_apply_audit_log(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS apply_audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT NOT NULL,
            actor           TEXT NOT NULL,
            proposal_id     TEXT NOT NULL,
            action_type     TEXT NOT NULL,
            detail          TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_apply_audit_timestamp ON apply_audit_log (timestamp)"
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


@migration(10, "templates_visibility_archived")
def _migrate_templates_visibility_archived(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "templates"):
        return
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='templates'"
    ).fetchone()
    if row is None or "'archived'" in str(row[0]):
        return
    connection.executescript(
        """
        CREATE TABLE templates_new (
            template_id    TEXT PRIMARY KEY,
            name           TEXT    NOT NULL,
            latest_version INTEGER NOT NULL DEFAULT 0,
            updated_at     TEXT    NOT NULL,
            visibility     TEXT    NOT NULL DEFAULT 'private'
                CHECK (visibility IN ('public', 'private', 'archived')),
            tags_json      TEXT    NOT NULL DEFAULT '[]'
        );
        INSERT INTO templates_new
            SELECT template_id, name, latest_version, updated_at, visibility, tags_json
            FROM templates;
        DROP TABLE templates;
        ALTER TABLE templates_new RENAME TO templates;
        """
    )


USAGE_TRACE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("trace_id", "TEXT"),
    ("parent_trace_id", "TEXT"),
    ("prompt_hash", "TEXT"),
    ("prompt_body_redacted", "TEXT"),
    ("mcp_tool", "TEXT"),
    ("selected_route", "TEXT"),
    ("candidate_models_json", "TEXT"),
    ("routing_reason_json", "TEXT"),
    ("fallback_events_json", "TEXT"),
    ("tool_calls_json", "TEXT"),
    ("completion_tokens", "INTEGER"),
    ("error_class", "TEXT"),
    ("error_message_redacted", "TEXT"),
    ("result_status", "TEXT"),
    ("policy_decision_json", "TEXT"),
    ("capture_level", "TEXT"),
    ("evaluation_json", "TEXT"),
)


@migration(11, "usage_trace_columns")
def _migrate_usage_trace_columns(connection: sqlite3.Connection) -> None:
    """Add Phase A control-plane trace columns to ``usage`` (additive)."""
    if not _table_exists(connection, "usage"):
        return
    for column, ddl in USAGE_TRACE_COLUMNS:
        if column == "evaluation_json":
            continue  # added in migration 12 for DBs that already applied v11
        if not _column_exists(connection, "usage", column):
            connection.execute(f"ALTER TABLE usage ADD COLUMN {column} {ddl}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_trace_id ON usage (trace_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_parent_trace_id ON usage (parent_trace_id)"
    )


@migration(12, "usage_evaluation_json")
def _migrate_usage_evaluation_json(connection: sqlite3.Connection) -> None:
    """Add dedicated evaluation_json column (Phase B)."""
    if not _table_exists(connection, "usage"):
        return
    if not _column_exists(connection, "usage", "evaluation_json"):
        connection.execute("ALTER TABLE usage ADD COLUMN evaluation_json TEXT")


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
    cursor = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    )
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
