"""Prompt library types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

TemplateSource = Literal["seed", "user", "learned"]


@dataclass(frozen=True, slots=True)
class TemplateParam:
    """Named placeholder declared by a template."""

    name: str
    description: str = ""
    default: str | None = None


@dataclass(frozen=True, slots=True)
class Template:
    """One immutable template version."""

    template_id: str
    name: str
    version: int
    body: str
    params: list[TemplateParam]
    source: TemplateSource
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TemplateSummary:
    """Latest-version metadata for list views."""

    template_id: str
    name: str
    latest_version: int
    source: TemplateSource
    updated_at: datetime
    param_names: tuple[str, ...]
