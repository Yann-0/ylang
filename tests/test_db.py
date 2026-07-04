"""Tests for SQLite storage permission checks and reconnect."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ylang.core.db import StoragePermissionError, verify_storage_writable
from ylang.core.stores import open_stores
from ylang.usage.store import UsageWindow


def test_verify_storage_writable_allows_new_database(tmp_path: Path) -> None:
    db_path = tmp_path / "ylang.db"
    verify_storage_writable(db_path)


def test_verify_storage_writable_rejects_readonly_file(tmp_path: Path) -> None:
    db_path = tmp_path / "ylang.db"
    db_path.write_text("")
    db_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    with pytest.raises(StoragePermissionError, match="database file not writable"):
        verify_storage_writable(db_path)


def test_reconnect_shared_refreshes_store_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "ylang.db"
    stores = open_stores(db_path)
    first_connection = stores.store._connection
    stores.reconnect_shared()
    assert stores.store._connection is not first_connection
    assert stores.library._connection is stores.store._connection
    assert stores.memory._connection is stores.store._connection
    stores.store.write_usage(
        surface="test",
        activity="test",
        model_used="test",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=1,
        success=True,
    )
    rows = stores.store.recall_usage(UsageWindow.last_hours(1))
    assert len(rows) == 1
    stores.close()


def test_open_stores_rejects_unwritable_directory(tmp_path: Path) -> None:
    readonly_dir = tmp_path / "locked"
    readonly_dir.mkdir()
    readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
    db_path = readonly_dir / "ylang.db"
    try:
        with pytest.raises(StoragePermissionError, match="directory not writable"):
            open_stores(db_path)
    finally:
        readonly_dir.chmod(stat.S_IRWXU)
        if os.getenv("USER") == "root":
            readonly_dir.chmod(stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
