"""Shared SQLite connection helpers for all Ylang stores."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Self


class StoragePermissionError(OSError):
    """Raised when the SQLite storage path is not writable by the current process."""

    def __init__(self, db_path: Path, detail: str) -> None:
        user = os.getenv("USER") or "unknown"
        resolved = db_path.expanduser().resolve()
        message = (
            f"SQLite storage is not writable: {resolved}\n"
            f"  detail: {detail}\n"
            f"  running as: {user}\n"
            "  fix (production systemd service running as ylang):\n"
            f"    sudo chown -R ylang:ylang {resolved.parent}\n"
            f"    sudo chmod 750 {resolved.parent}\n"
            "    sudo systemctl restart ylang"
        )
        super().__init__(message)
        self.db_path = resolved
        self.detail = detail


def verify_storage_writable(db_path: Path) -> None:
    """Fail fast when the database file or its directory cannot be written."""
    resolved = db_path.expanduser().resolve()
    parent = resolved.parent
    if not parent.exists():
        msg = f"parent directory does not exist: {parent}"
        raise StoragePermissionError(resolved, msg)
    if not os.access(parent, os.W_OK | os.X_OK):
        msg = f"directory not writable: {parent}"
        raise StoragePermissionError(resolved, msg)
    if resolved.exists() and not os.access(resolved, os.W_OK):
        msg = f"database file not writable: {resolved}"
        raise StoragePermissionError(resolved, msg)


def open_connection(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and busy timeout."""
    verify_storage_writable(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    _verify_connection_writable(connection, db_path)
    return connection


def _verify_connection_writable(connection: sqlite3.Connection, db_path: Path) -> None:
    """Ensure SQLite did not downgrade the connection to read-only."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ROLLBACK")
    except sqlite3.OperationalError as exc:
        if "readonly" in str(exc).lower():
            raise StoragePermissionError(
                db_path.expanduser().resolve(),
                "SQLite opened the database read-only",
            ) from exc
        raise


def _is_readonly_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "readonly" in str(exc).lower()


@dataclass
class YlangDatabase:
    """Single shared SQLite connection backing usage, library, and memory stores."""

    connection: sqlite3.Connection
    path: Path

    @classmethod
    def open(cls, db_path: Path) -> Self:
        """Open (or create) the Ylang database file."""
        resolved = db_path.expanduser().resolve()
        return cls(connection=open_connection(resolved), path=resolved)

    def reconnect(self) -> None:
        """Close and reopen the shared connection (e.g. after permissions change)."""
        self.connection.close()
        self.connection = open_connection(self.path)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self.connection.close()
