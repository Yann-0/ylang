"""Shared fixtures for Ylang integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from ylang.core import Engine
from ylang.core.stores import open_stores
from ylang.improver import Improver
from ylang.library.pattern_detector import UsagePatternDetector
from ylang.library.patterns import register_pattern_detector
from ylang.mcp.deps import YlangDeps
from ylang.mcp.server import create_server


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Single SQLite file shared by usage store and library."""
    return tmp_path / "ylang.db"


@pytest.fixture
def ylang_deps(db_path: Path) -> Iterator[YlangDeps]:
    """Wired backends matching production MCP startup."""
    stores = open_stores(db_path)
    register_pattern_detector(UsagePatternDetector(stores.store))
    engine = Engine(stores.store, surface="mcp")
    improver = Improver(engine)
    deps = YlangDeps(
        improver=improver,
        library=stores.library,
        store=stores.store,
        memory=stores.memory,
        surface="mcp",
    )
    try:
        yield deps
    finally:
        stores.close()


@pytest.fixture
async def mcp_server(ylang_deps: YlangDeps) -> AsyncIterator[Any]:
    """FastMCP server with all Ylang tools registered."""
    yield create_server(ylang_deps)
