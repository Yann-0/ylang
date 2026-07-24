"""Safe, whitelisted mutators for the console data browser."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from ylang.improver.cache_store import clear_improver_cache_store
from ylang.improver.improver import clear_improve_cache

_MUTABLE_TABLES = frozenset({"usage", "improver_cache"})


def clear_improver_caches(connection: sqlite3.Connection) -> tuple[int, int]:
    """Clear in-memory and SQLite improver caches; return (memory_cleared, db_rows)."""
    clear_improve_cache()
    row = connection.execute("SELECT COUNT(*) FROM improver_cache").fetchone()
    db_rows = int(row[0]) if row else 0
    clear_improver_cache_store(connection)
    return (1, db_rows)


def delete_usage_row(connection: sqlite3.Connection, row_id: int) -> bool:
    """Delete one usage row by primary key."""
    cursor = connection.execute("DELETE FROM usage WHERE id = ?", (row_id,))
    connection.commit()
    return cursor.rowcount > 0


def purge_usage_older_than(connection: sqlite3.Connection, days: int) -> int:
    """Delete usage rows older than ``days`` days; return rows removed."""
    if days < 1:
        msg = "days must be at least 1"
        raise ValueError(msg)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cursor = connection.execute(
        "DELETE FROM usage WHERE timestamp < ?",
        (cutoff.isoformat(),),
    )
    connection.commit()
    return int(cursor.rowcount)
