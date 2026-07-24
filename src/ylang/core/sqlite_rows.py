"""Helpers for typing SQLite ``fetchone`` / ``fetchall`` rows.

Pyright treats ``tuple[object, ...]`` poorly when indexing (spurious
"index out of range" cascades). Prefer ``SqliteRow`` (``Sequence[Any]``)
plus these converters at row boundaries.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeAlias

SqliteRow: TypeAlias = Sequence[Any]


def cell(row: SqliteRow, index: int) -> Any:
    """Return ``row[index]`` (typed as ``Any`` for downstream converters)."""
    return row[index]


def cell_int(row: SqliteRow, index: int) -> int:
    """Read an integer cell."""
    return int(row[index])


def cell_float(row: SqliteRow, index: int) -> float:
    """Read a float cell."""
    return float(row[index])


def cell_str(row: SqliteRow, index: int) -> str:
    """Read a string cell."""
    return str(row[index])


def cell_bool(row: SqliteRow, index: int) -> bool:
    """Read a boolean cell (SQLite 0/1)."""
    return bool(row[index])


def cell_optional_str(row: SqliteRow, index: int) -> str | None:
    """Read an optional string cell; ``None`` when missing or SQL NULL."""
    if index >= len(row) or row[index] is None:
        return None
    return str(row[index])


def cell_optional_int(row: SqliteRow, index: int) -> int | None:
    """Read an optional int cell; ``None`` when missing or SQL NULL."""
    if index >= len(row) or row[index] is None:
        return None
    return int(row[index])


def cell_optional_bool(row: SqliteRow, index: int) -> bool | None:
    """Read an optional bool cell; ``None`` when missing or SQL NULL."""
    if index >= len(row) or row[index] is None:
        return None
    return bool(row[index])
