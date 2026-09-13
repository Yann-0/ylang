"""Importer result types."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.library.types import TemplateParam


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Counts from a single import/refresh run (candidate quarantine)."""

    imported: int
    skipped: int
    new: int = 0
    changed: int = 0
    quarantined: int = 0
    source_id: str = ""
    error: str | None = None
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ParsedPrompt:
    """One external prompt converted to library fields."""

    template_id: str
    name: str
    body: str
    params: list[TemplateParam]
