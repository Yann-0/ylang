"""Shared fixtures for Ylang integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from ylang.core import Engine
from ylang.core.memory import open_memory
from ylang.improver import Improver
from ylang.library.store import open_library
from ylang.mcp.deps import YlangDeps
from ylang.mcp.server import create_server
from ylang.usage.store import open_store


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Single SQLite file shared by usage store and library."""
    return tmp_path / "ylang.db"


@pytest.fixture
def ylang_deps(db_path: Path) -> Iterator[YlangDeps]:
    """Wired backends matching production MCP startup."""
    store = open_store(db_path)
    library = open_library(db_path)
    memory = open_memory(db_path)
    engine = Engine(store, surface="mcp")
    improver = Improver(engine)
    deps = YlangDeps(improver=improver, library=library, store=store, memory=memory)
    try:
        yield deps
    finally:
        library.close()
        store.close()
        memory.close()


@pytest.fixture
async def mcp_server(ylang_deps: YlangDeps) -> AsyncIterator[Any]:
    """FastMCP server with all six Ylang tools registered."""
    yield create_server(ylang_deps)
