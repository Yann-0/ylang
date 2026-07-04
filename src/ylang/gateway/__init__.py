"""Desktop gateway seam — future face over the shared core engine."""

from __future__ import annotations


def run_gateway() -> None:
    """Start the desktop gateway face (not yet implemented).

    The gateway will be a thin adapter over ``ylang.core.Engine``,
    mirroring the MCP server's separation of concerns.
    """
    msg = (
        "Desktop gateway is not implemented yet. "
        "Use `python -m ylang` for the MCP face."
    )
    raise NotImplementedError(msg)
