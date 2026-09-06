"""Shared core engine and routing primitives.

Re-exports ``Engine``, ``ModelRouter``, chat types, and default activity model
lists from ``settings``.
"""

from ylang.core.engine import FALLBACK_MODEL, Engine
from ylang.core.model_router import ModelRouter
from ylang.core.types import (
    Activity,
    CompletionResult,
    Message,
    ModelResolution,
    ResolutionReason,
)
from ylang.settings import DEFAULT_ACTIVITY_MODELS, DEFAULT_ACTIVITY_MODEL_LISTS

__all__ = [
    "Activity",
    "CompletionResult",
    "DEFAULT_ACTIVITY_MODELS",
    "DEFAULT_ACTIVITY_MODEL_LISTS",
    "Engine",
    "FALLBACK_MODEL",
    "Message",
    "ModelResolution",
    "ModelRouter",
    "ResolutionReason",
]
