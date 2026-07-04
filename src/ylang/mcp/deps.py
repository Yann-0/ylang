"""Shared MCP dependencies wired at startup."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.core.memory import MemoryStore
from ylang.improver import Improver
from ylang.library import Library
from ylang.usage import UsageStore


@dataclass(frozen=True, slots=True)
class YlangDeps:
    """Backend instances injected into MCP tool handlers."""

    improver: Improver
    library: Library
    store: UsageStore
    memory: MemoryStore
    surface: str = "mcp"  # Persisted on usage rows written by MCP tools
