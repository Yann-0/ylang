"""Ylang — personal AI efficiency layer.

v0.7.0 ships prompt intelligence (allowlisted public sources, candidate
quarantine, explicit promotion) on the local-first control plane: MCP
(stdio/HTTP), an OpenAI-compatible gateway, an admin console (Portal), and CLI
helpers. Completions record explainable ``ModelResolution``; optional OTLP export
is off by default. See ``docs/`` for installation, gateway setup, Portal, and
architecture.
"""

__version__ = "0.7.0"
__all__ = ["__version__"]
