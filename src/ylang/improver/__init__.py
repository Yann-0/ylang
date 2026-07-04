"""Propose-only prompt improvement with Cursor mode resolution.

The improver never auto-applies edits; hooks and clients decide whether to use
``improved`` text. Exports ``Improver``, mode registry helpers, and result types.
"""

from ylang.improver.improver import Improver
from ylang.improver.registry import (
    PRECISION_TOOLS,
    CursorMode,
    default_auto_apply,
    is_precision_tool,
    mode_guidance,
    resolve_cursor_mode,
)
from ylang.improver.types import Change, ChangeKind, ImprovementResult

__all__ = [
    "Change",
    "ChangeKind",
    "CursorMode",
    "ImprovementResult",
    "Improver",
    "PRECISION_TOOLS",
    "default_auto_apply",
    "is_precision_tool",
    "mode_guidance",
    "resolve_cursor_mode",
]
