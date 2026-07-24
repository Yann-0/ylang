"""Persistent SQLite cache for improver results."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from ylang.improver.types import Change, ImprovementResult

_IMPROVE_CACHE_TTL_SEC = 60.0


def _serialize_result(result: ImprovementResult) -> str:
    payload: dict[str, Any] = {
        "original": result.original,
        "improved": result.improved,
        "changes": [
            {
                "kind": change.kind,
                "description": change.description,
                "before": change.before,
                "after": change.after,
            }
            for change in result.changes
        ],
        "auto_apply_default": result.auto_apply_default,
        "validated": result.validated,
        "rejection_reason": result.rejection_reason,
        "cursor_mode": result.cursor_mode,
        "mode_source": result.mode_source,
    }
    return json.dumps(payload)


def _deserialize_result(raw: str) -> ImprovementResult:
    data = json.loads(raw)
    changes = [Change(**item) for item in data.get("changes", [])]
    return ImprovementResult(
        original=str(data["original"]),
        improved=str(data["improved"]),
        changes=changes,
        auto_apply_default=bool(data["auto_apply_default"]),
        validated=bool(data.get("validated", True)),
        rejection_reason=data.get("rejection_reason"),
        cursor_mode=data.get("cursor_mode", "agent"),
        mode_source=data.get("mode_source", "default"),
    )


def get_cached_improvement(
    connection: sqlite3.Connection, cache_key: str
) -> ImprovementResult | None:
    """Return a cached improver result when present and not expired."""
    cursor = connection.execute(
        "SELECT result_json, expires_at FROM improver_cache WHERE cache_key = ?",
        (cache_key,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    expires_at = float(row[1])
    if time.time() > expires_at:
        connection.execute(
            "DELETE FROM improver_cache WHERE cache_key = ?",
            (cache_key,),
        )
        connection.commit()
        return None
    return _deserialize_result(str(row[0]))


def set_cached_improvement(
    connection: sqlite3.Connection,
    cache_key: str,
    result: ImprovementResult,
) -> None:
    """Persist an improver result with TTL."""
    expires_at = time.time() + _IMPROVE_CACHE_TTL_SEC
    connection.execute(
        """
        INSERT INTO improver_cache (cache_key, result_json, expires_at)
        VALUES (?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            result_json = excluded.result_json,
            expires_at = excluded.expires_at
        """,
        (cache_key, _serialize_result(result), expires_at),
    )
    connection.commit()


def clear_improver_cache_store(connection: sqlite3.Connection) -> None:
    """Remove all persisted improver cache rows (primarily for tests)."""
    connection.execute("DELETE FROM improver_cache")
    connection.commit()
