"""MCP server adapter over the shared core.

On HTTP transport, gateway routes and the usage dashboard share the same process
and bearer auth. Re-exports ``create_server``, ``run_server``, and ``YlangDeps``.
"""

from ylang.mcp.deps import YlangDeps
from ylang.mcp.server import create_server, run_server

__all__ = ["YlangDeps", "create_server", "run_server"]
