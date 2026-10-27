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
from ylang.library.patterns import register_pattern_detector, register_pattern_detector_store
from ylang.mcp.deps import YlangDeps
from ylang.mcp.server import create_server


@pytest.fixture(autouse=True)
def _clear_improver_cache() -> None:
    """Prevent cross-test pollution from the module-level improver cache."""
    from ylang.improver.improver import clear_improve_cache

    clear_improve_cache()
    yield
    clear_improve_cache()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Single SQLite file shared by usage store and library."""
    return tmp_path / "ylang.db"


@pytest.fixture
def ylang_deps(db_path: Path) -> Iterator[YlangDeps]:
    """Wired backends matching production MCP startup."""
    stores = open_stores(db_path)
    register_pattern_detector_store(stores.store)
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


class MockedPaidEngine(Engine):
    """Explicit opt-in Engine for modules with patched text-only cloud fixtures."""

    def __init__(
        self, store: Any, *, known_failure_charge_nanos: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Admit the exact mock route; failure charges require explicit fixture evidence."""
        from unittest.mock import Mock

        from ylang.core import engine as engine_module
        from tests.bounded_adapter_helpers import MockedCompletionAdapter, initialize_budget

        def mocked_transport(**call_kwargs: Any) -> Any:
            """Refuse accidental live transport even when a fixture patch is missing."""
            transport = engine_module.litellm.completion
            if not isinstance(transport, Mock):
                raise AssertionError("offline bounded fixture requires patched completion")
            return transport(**call_kwargs)

        initialize_budget(store)
        adapters = {
            "openai/gpt-4o": MockedCompletionAdapter(
                Mock(side_effect=mocked_transport),
                known_failure_charge_nanos=known_failure_charge_nanos,
            ),
        }
        super().__init__(store, bounded_adapters=adapters, **kwargs)
