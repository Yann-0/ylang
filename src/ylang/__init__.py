"""Ylang — personal AI efficiency layer.

v0.6.0 ships one shared core engine with multiple thin faces: MCP (stdio/HTTP),
an OpenAI-compatible gateway on HTTP transport, an admin console (Portal), and CLI
helpers for usage reporting and pattern-based template suggestions. Completions
record explainable ``ModelResolution``; optional OTLP export is off by default.
Domain packages cover propose-only prompt improvement, a versioned template
library, usage tracking, and scoped user memory. See ``docs/`` for installation,
gateway setup, Portal, and architecture.
"""

__version__ = "0.6.0"
__all__ = ["__version__"]
