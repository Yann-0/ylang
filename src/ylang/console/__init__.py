"""Ylang admin console — server-rendered HTML dashboard."""

from __future__ import annotations

from typing import Any

__all__ = ["register_console_routes"]


def __getattr__(name: str) -> Any:
    if name == "register_console_routes":
        from ylang.console.routes import register_console_routes

        return register_console_routes
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
