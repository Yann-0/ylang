"""Bundled seed templates loaded idempotently on first library open."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ylang.library.types import TemplateParam

if TYPE_CHECKING:
    from ylang.library.store import Library


@dataclass(frozen=True, slots=True)
class SeedTemplateSpec:
    """Definition of a bundled seed template."""

    template_id: str
    name: str
    body: str
    params: list[TemplateParam]
    tags: tuple[str, ...] = ()


SEED_TEMPLATES: list[SeedTemplateSpec] = [
    SeedTemplateSpec(
        template_id="summarize",
        name="Summarize",
        body="Summarize the following text in about {length} words.\n\n{text}",
        params=[
            TemplateParam(name="text", description="Text to summarize"),
            TemplateParam(name="length", description="Target word count", default="100"),
        ],
        tags=("summarize", "text", "summary"),
    ),
    SeedTemplateSpec(
        template_id="code-explain",
        name="Explain Code",
        body="Explain the following {language} code clearly and concisely.\n\n{code}",
        params=[
            TemplateParam(name="code", description="Source code to explain"),
            TemplateParam(name="language", description="Programming language", default="Python"),
        ],
        tags=("code-explain", "code", "explain"),
    ),
    SeedTemplateSpec(
        template_id="structured-output",
        name="Structured Output",
        body=(
            "Complete the task below. Respond in {format} format only.\n\n"
            "Task: {task}"
        ),
        params=[
            TemplateParam(name="task", description="Task to complete"),
            TemplateParam(name="format", description="Output format", default="JSON"),
        ],
        tags=("structured-output", "format", "json"),
    ),
]


def ensure_seeds(library: Library) -> None:
    """Insert seed templates at version 1 when template_id is not yet present."""
    for spec in SEED_TEMPLATES:
        if library.recall(spec.template_id) is not None:
            continue
        library.save(
            spec.template_id,
            name=spec.name,
            body=spec.body,
            params=spec.params,
            source="seed",
            tags=list(spec.tags),
        )
