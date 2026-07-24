"""MCP server adapter over the shared core.

On HTTP transport, gateway routes and the usage dashboard share the same process
and bearer auth. Re-exports ``create_server``, ``run_server``, and ``YlangDeps``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ylang.mcp.deps import YlangDeps

if TYPE_CHECKING:
    from ylang.mcp.server import create_server as create_server
    from ylang.mcp.server import run_server as run_server

__all__ = ["YlangDeps", "create_server", "run_server"]


def __getattr__(name: str) -> Any:
    if name in {"create_server", "run_server"}:
        from ylang.mcp import server as _server

        return getattr(_server, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
