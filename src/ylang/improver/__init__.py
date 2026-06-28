"""Propose-only text improvement (Phase 1)."""

from ylang.improver.improver import Improver
from ylang.improver.registry import PRECISION_TOOLS, default_auto_apply, is_precision_tool
from ylang.improver.types import Change, ChangeKind, ImprovementResult

__all__ = [
    "Change",
    "ChangeKind",
    "ImprovementResult",
    "Improver",
    "PRECISION_TOOLS",
    "default_auto_apply",
    "is_precision_tool",
]
