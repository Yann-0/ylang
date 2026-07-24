"""Tests for persistent improver cache storage."""

from __future__ import annotations

import sqlite3

from ylang.core.migrations import run_migrations
from ylang.improver.cache_store import (
    clear_improver_cache_store,
    get_cached_improvement,
    set_cached_improvement,
)
from ylang.improver.improver import clear_improve_cache
from ylang.improver.types import ImprovementResult


def _sample_result() -> ImprovementResult:
    return ImprovementResult(
        original="fix bug",
        improved="Fix the login bug in auth.py with tests.",
        changes=[],
        auto_apply_default=True,
        validated=True,
    )


def test_improver_cache_store_roundtrip(tmp_path: object) -> None:
    db = tmp_path / "cache.db"  # type: ignore[operator]
    with sqlite3.connect(db) as connection:
        run_migrations(connection)
        key = "abc123"
        result = _sample_result()
        set_cached_improvement(connection, key, result)
        cached = get_cached_improvement(connection, key)
        assert cached is not None
        assert cached.improved == result.improved
        assert cached.auto_apply_default is True


def test_improver_cache_survives_memory_clear(tmp_path: object) -> None:
    db = tmp_path / "cache-survive.db"  # type: ignore[operator]
    with sqlite3.connect(db) as connection:
        run_migrations(connection)
        key = "persist-key"
        result = _sample_result()
        set_cached_improvement(connection, key, result)
        clear_improve_cache()
        cached = get_cached_improvement(connection, key)
        assert cached is not None
        assert cached.original == "fix bug"
        clear_improver_cache_store(connection)
