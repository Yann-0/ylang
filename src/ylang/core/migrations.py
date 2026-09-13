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

USAGE_TRACE_PHASE_B_COLUMNS: tuple[tuple[str, str], ...] = (
    ("session_id", "TEXT"),
    ("workspace", "TEXT"),
    ("context_sources_json", "TEXT"),
    ("memory_fact_ids_json", "TEXT"),
    ("mcp_server", "TEXT"),
    ("retention_until", "TEXT"),
    ("cost_actual", "REAL"),
    ("template_version", "INTEGER"),
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


@migration(13, "usage_trace_phase_b")
def _migrate_usage_trace_phase_b(connection: sqlite3.Connection) -> None:
    """Add Phase B control-plane usage columns (session, workspace, retention)."""
    if not _table_exists(connection, "usage"):
        return
    for column, ddl in USAGE_TRACE_PHASE_B_COLUMNS:
        if not _column_exists(connection, "usage", column):
            connection.execute(f"ALTER TABLE usage ADD COLUMN {column} {ddl}")


@migration(14, "prompt_intelligence_sources")
def _migrate_prompt_intelligence_sources(connection: sqlite3.Connection) -> None:
    """Add prompt source/candidate tables without altering template origins."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS prompt_sources (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            adapter TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            repo_url TEXT,
            license_spdx TEXT NOT NULL,
            license_url TEXT,
            trust_tier TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            refresh_interval_hours INTEGER NOT NULL DEFAULT 168,
            last_attempt_at TEXT,
            last_success_at TEXT,
            last_revision TEXT,
            last_etag TEXT,
            last_error TEXT,
            policy_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prompt_source_items (
            item_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            upstream_item_id TEXT NOT NULL,
            canonical_url TEXT,
            source_revision TEXT,
            content_hash TEXT NOT NULL,
            normalized_fingerprint TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            params_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            candidate_state TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            risk_reasons_json TEXT NOT NULL DEFAULT '[]',
            quality_score INTEGER NOT NULL DEFAULT 0,
            quality_reasons_json TEXT NOT NULL DEFAULT '[]',
            task_family TEXT NOT NULL DEFAULT 'other',
            model_hint TEXT,
            duplicate_of_item_id TEXT,
            duplicate_template_id TEXT,
            linked_template_id TEXT,
            linked_template_version INTEGER,
            license_spdx TEXT,
            adapter_version TEXT NOT NULL,
            previous_body TEXT,
            previous_content_hash TEXT,
            UNIQUE (source_id, upstream_item_id),
            FOREIGN KEY (source_id) REFERENCES prompt_sources(source_id)
        );

        CREATE INDEX IF NOT EXISTS idx_prompt_source_items_source
            ON prompt_source_items (source_id, candidate_state);
        CREATE INDEX IF NOT EXISTS idx_prompt_source_items_hash
            ON prompt_source_items (content_hash);
        CREATE INDEX IF NOT EXISTS idx_prompt_source_items_fingerprint
            ON prompt_source_items (normalized_fingerprint);

        CREATE TABLE IF NOT EXISTS template_provenance (
            template_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            upstream_revision TEXT,
            content_hash TEXT NOT NULL,
            canonical_url TEXT,
            promoted_at TEXT NOT NULL,
            PRIMARY KEY (template_id, version)
        );

        CREATE TABLE IF NOT EXISTS prompt_refresh_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            revision_before TEXT,
            revision_after TEXT,
            status TEXT NOT NULL,
            new_count INTEGER NOT NULL DEFAULT 0,
            changed_count INTEGER NOT NULL DEFAULT 0,
            removed_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            quarantined_count INTEGER NOT NULL DEFAULT 0,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_prompt_refresh_runs_source
            ON prompt_refresh_runs (source_id, started_at DESC);
        """
    )
    from ylang.importer.source_store import PromptSourceStore

    PromptSourceStore(connection).ensure_builtin_sources()


@migration(15, "prompt_evaluation_baselines")
def _migrate_prompt_evaluation_baselines(connection: sqlite3.Connection) -> None:
    """Persist candidate evaluations and promote-time outcome snapshots."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS prompt_evaluation_snapshots (
            item_id TEXT PRIMARY KEY,
            vs_template_id TEXT,
            vs_template_version INTEGER,
            current_accept_rate REAL,
            current_avg_cost REAL,
            current_avg_latency_ms REAL,
            current_injections INTEGER NOT NULL DEFAULT 0,
            current_body_hash TEXT,
            candidate_content_hash TEXT NOT NULL,
            quality_score INTEGER NOT NULL DEFAULT 0,
            risk_level TEXT NOT NULL,
            body_diff_ratio REAL,
            fixture_hash TEXT,
            fixture_chars INTEGER,
            experiment_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (item_id) REFERENCES prompt_source_items(item_id)
        );

        CREATE TABLE IF NOT EXISTS prompt_promotion_baselines (
            template_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            accept_rate REAL,
            avg_cost REAL,
            avg_latency_ms REAL,
            injections INTEGER NOT NULL DEFAULT 0,
            captured_at TEXT NOT NULL,
            PRIMARY KEY (template_id, version)
        );
        """
    )


@migration(16, "prompt_intelligence_fail_closed")
def _migrate_prompt_intelligence_fail_closed(connection: sqlite3.Connection) -> None:
    """Compatibility flags, refresh leases, and bounded evaluation runs."""
    from ylang.importer.policy import COPILOT_INCOMPATIBLE_NOTE

    if _table_exists(connection, "prompt_sources"):
        if not _column_exists(connection, "prompt_sources", "compatibility_status"):
            connection.execute(
                "ALTER TABLE prompt_sources ADD COLUMN compatibility_status "
                "TEXT NOT NULL DEFAULT 'unverified'"
            )
        if not _column_exists(connection, "prompt_sources", "compatibility_note"):
            connection.execute(
                "ALTER TABLE prompt_sources ADD COLUMN compatibility_note TEXT"
            )
        connection.execute(
            """
            UPDATE prompt_sources
            SET compatibility_status = 'incompatible',
                compatibility_note = ?,
                enabled = 0
            WHERE source_id = 'github-awesome-copilot'
              AND compatibility_status = 'unverified'
            """,
            (COPILOT_INCOMPATIBLE_NOTE,),
        )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS prompt_refresh_leases (
            source_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prompt_evaluation_runs (
            run_id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            evidence_class TEXT NOT NULL,
            vs_template_id TEXT,
            vs_template_version INTEGER,
            vs_content_hash TEXT,
            candidate_content_hash TEXT NOT NULL,
            model TEXT,
            authorized INTEGER NOT NULL DEFAULT 0,
            budget_usd REAL,
            cost_usd REAL NOT NULL DEFAULT 0,
            baseline_output TEXT,
            candidate_output TEXT,
            baseline_error TEXT,
            candidate_error TEXT,
            baseline_latency_ms INTEGER,
            candidate_latency_ms INTEGER,
            baseline_prompt_tokens INTEGER,
            candidate_prompt_tokens INTEGER,
            baseline_completion_tokens INTEGER,
            candidate_completion_tokens INTEGER,
            evaluator_json TEXT NOT NULL DEFAULT '{}',
            fixture_hash TEXT,
            created_at TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_prompt_evaluation_runs_item
            ON prompt_evaluation_runs (item_id, created_at DESC);
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
