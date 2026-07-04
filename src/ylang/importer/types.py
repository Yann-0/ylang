"""Importer result types."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.library.types import TemplateParam


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Counts from a single import run."""

    imported: int
    skipped: int


@dataclass(frozen=True, slots=True)
class ParsedPrompt:
    """One external prompt converted to library fields."""

    template_id: str
    name: str
    body: str
    params: list[TemplateParam]
