"""Retention purge for sensitive trace bodies (local-only)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone


DEFAULT_TRACE_RETENTION_DAYS = 90


def purge_sensitive_trace_bodies(
    connection: sqlite3.Connection,
    *,
    older_than_days: int = DEFAULT_TRACE_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Null out redacted/full prompt bodies older than the retention window.

    Keeps metrics, hashes, and routing reasons. Returns rows updated.
    """
    if older_than_days < 0:
        msg = "older_than_days must be >= 0"
        raise ValueError(msg)
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        msg = "now must be timezone-aware UTC"
        raise ValueError(msg)
    cutoff = (anchor - timedelta(days=older_than_days)).isoformat()
    cursor = connection.execute(
        """
        UPDATE usage
        SET prompt_body_redacted = NULL,
            improver_input_sample = NULL
        WHERE timestamp < ?
          AND (
            prompt_body_redacted IS NOT NULL
            OR improver_input_sample IS NOT NULL
          )
        """,
        (cutoff,),
    )
    connection.commit()
    return int(cursor.rowcount)
