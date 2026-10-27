"""Lazy public exports for the shared core without store/Engine import cycles."""
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ylang.core.engine import FALLBACK_MODEL as FALLBACK_MODEL, Engine as Engine
    from ylang.core.model_router import ModelRouter as ModelRouter
    from ylang.core.types import (
        Activity as Activity,
        CompletionResult as CompletionResult,
        Message as Message,
        ModelResolution as ModelResolution,
        ResolutionReason as ResolutionReason,
    )
    from ylang.settings import (
        DEFAULT_ACTIVITY_MODELS as DEFAULT_ACTIVITY_MODELS,
        DEFAULT_ACTIVITY_MODEL_LISTS as DEFAULT_ACTIVITY_MODEL_LISTS,
    )

_EXPORTS = {
    "Engine": "ylang.core.engine",
    "FALLBACK_MODEL": "ylang.core.engine",
    "ModelRouter": "ylang.core.model_router",
    "Activity": "ylang.core.types",
    "CompletionResult": "ylang.core.types",
    "Message": "ylang.core.types",
    "ModelResolution": "ylang.core.types",
    "ResolutionReason": "ylang.core.types",
    "DEFAULT_ACTIVITY_MODELS": "ylang.settings",
    "DEFAULT_ACTIVITY_MODEL_LISTS": "ylang.settings",
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve existing public exports only when requested, after stores can initialize."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value
