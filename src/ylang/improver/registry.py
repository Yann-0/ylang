"""Tool registry for precision handling and auto-apply defaults."""

from __future__ import annotations

PRECISION_TOOLS: frozenset[str] = frozenset(
    {
        "run_command",
        "edit_file",
        "execute_sql",
    }
)


def is_precision_tool(tool: str) -> bool:
    """Return True when the tool must never auto-apply improvements."""
    return tool in PRECISION_TOOLS


def default_auto_apply(tool: str) -> bool:
    """Return the default auto-apply hint for a tool (Phase 1: always False)."""
    _ = tool
    return False
