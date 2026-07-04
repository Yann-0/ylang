"""Improver request/response types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ylang.improver.registry import CursorMode, ModeSource


ChangeKind = Literal["clarity", "format", "constraint", "example", "scope"]


@dataclass(frozen=True, slots=True)
class Change:
    """One auditable structural edit."""

    kind: ChangeKind
    description: str
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class ImprovementResult:
    """Proposed improvement; caller decides whether to apply."""

    original: str
    improved: str
    changes: list[Change]
    auto_apply_default: bool
    validated: bool = True
    rejection_reason: str | None = None
    cursor_mode: CursorMode = "agent"
    mode_source: ModeSource = "default"
