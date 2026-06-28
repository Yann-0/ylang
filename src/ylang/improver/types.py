"""Improver request/response types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChangeKind = Literal["clarity", "format", "constraint", "example"]


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
