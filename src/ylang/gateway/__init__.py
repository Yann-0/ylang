"""OpenAI-compatible gateway face over the shared core engine."""

from __future__ import annotations

from ylang.gateway.mapping import VIRTUAL_MODEL_NAMES
from ylang.gateway.routes import register_gateway_routes

__all__ = ["VIRTUAL_MODEL_NAMES", "register_gateway_routes"]
