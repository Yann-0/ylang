"""Read-only data browser queries for the admin console."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TablePreview:
    """Paginated preview of one SQLite table."""

    table_name: str
    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]]
    total_count: int


_BROWSE_TABLES: tuple[str, ...] = (
    "usage",
    "templates",
    "template_versions",
    "facts",
    "runtime_settings",
    "improver_cache",
    "feedback_events",
    "prompt_experiments",
    "apply_audit_log",
)

# (label, table) — primary domain shortcuts shown above raw table browse
DATA_DOMAIN_VIEWS: tuple[tuple[str, str], ...] = (
    ("Usage", "usage"),
    ("Templates", "templates"),
    ("Facts", "facts"),
    ("Feedback", "feedback_events"),
    ("Cache", "improver_cache"),
    ("Audit", "apply_audit_log"),
)


def list_browse_tables() -> tuple[str, ...]:
    """Return table names available in the data browser."""
    return _BROWSE_TABLES


def list_data_domains() -> tuple[tuple[str, str], ...]:
    """Return labeled domain shortcuts for the data browser nav."""
    return DATA_DOMAIN_VIEWS


def domain_table_for_label(label: str) -> str | None:
    """Resolve a domain label (case-insensitive) to its SQLite table name."""
    needle = label.strip().lower()
    for domain_label, table in DATA_DOMAIN_VIEWS:
        if domain_label.lower() == needle:
            return table
    return None


def preview_table(
    connection: sqlite3.Connection,
    table_name: str,
    *,
    limit: int = 50,
    offset: int = 0,
    activity: str | None = None,
    search: str | None = None,
) -> TablePreview | None:
    """Return a paginated preview for a known table, or ``None`` when unknown."""
    if table_name not in _BROWSE_TABLES:
        return None
    where_parts: list[str] = []
    params: list[object] = []
    if table_name == "usage" and activity:
        where_parts.append("activity = ?")
        params.append(activity)
    if search and search.strip():
        cursor = connection.execute(f"SELECT * FROM {table_name} LIMIT 0")  # noqa: S608
        columns = [str(item[0]) for item in cursor.description or ()]
        text_cols = [
            col
            for col in columns
            if col not in {"id", "prompt_tokens", "cost", "latency_ms"}
        ]
        if text_cols:
            like = f"%{search.strip()}%"
            where_parts.append(
                "(" + " OR ".join(f"{col} LIKE ?" for col in text_cols) + ")"
            )
            params.extend([like] * len(text_cols))
    where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
    count_row = connection.execute(
        f"SELECT COUNT(*) FROM {table_name}{where_sql}",  # noqa: S608 — table_name whitelisted
        params,
    ).fetchone()
    total = int(count_row[0]) if count_row else 0
    cursor = connection.execute(
        f"SELECT * FROM {table_name}{where_sql} LIMIT ? OFFSET ?",  # noqa: S608
        [*params, limit, offset],
    )
    columns = tuple(str(item[0]) for item in cursor.description or ())
    rows = [tuple(row) for row in cursor.fetchall()]
    return TablePreview(
        table_name=table_name,
        columns=columns,
        rows=rows,
        total_count=total,
    )


def db_stats(connection: sqlite3.Connection) -> dict[str, int]:
    """Return row counts for all browsable tables."""
    stats: dict[str, int] = {}
    for table in _BROWSE_TABLES:
        row = connection.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        stats[table] = int(row.fetchone()[0])
    return stats
