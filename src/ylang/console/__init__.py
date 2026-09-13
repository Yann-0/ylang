"""Ylang admin console — server-rendered HTML dashboard."""

from __future__ import annotations

from typing import Any

__all__ = ["register_console_routes"]


def register_console_routes(*args: Any, **kwargs: Any) -> None:
    """Register admin console routes on the HTTP app."""
    from ylang.console.routes import register_console_routes as _register

    _register(*args, **kwargs)
