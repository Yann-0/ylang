"""Ylang — personal AI efficiency layer.

v0.2.0 ships one shared core engine with multiple thin faces: MCP (stdio/HTTP),
an OpenAI-compatible gateway on HTTP transport, and CLI helpers for usage
reporting and pattern-based template suggestions. Domain packages cover
propose-only prompt improvement, a versioned template library, usage tracking,
and scoped user memory. See ``docs/`` for installation, gateway setup, and
architecture.
"""

__version__ = "0.4.0"
__all__ = ["__version__"]
