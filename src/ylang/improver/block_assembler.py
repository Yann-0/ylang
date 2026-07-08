"""Dynamic prompt block assembly from tagged templates."""

from __future__ import annotations

import re

from ylang.library.store import Library
from ylang.library.types import TemplateSummary

_BLOCK_TAG_PREFIX = "block:"
_BLOCK_TYPES = ("persona", "task", "constraints", "examples", "output_format")
_BLOCK_HEADER_RE = re.compile(r"^##\s+(\w[\w\s-]*)\s*$", re.MULTILINE)


def block_type_from_tags(tags: tuple[str, ...]) -> str | None:
    """Extract block type from template tags (e.g. ``block:constraints``)."""
    for tag in tags:
        lowered = tag.lower()
        if lowered.startswith(_BLOCK_TAG_PREFIX):
            block_type = lowered.removeprefix(_BLOCK_TAG_PREFIX)
            if block_type in _BLOCK_TYPES:
                return block_type
    return None


def select_blocks(
    library: Library,
    *,
    cursor_mode: str | None = None,
    max_chars: int = 3000,
) -> tuple[str, tuple[str, ...]]:
    """Assemble prompt blocks from tagged templates; return body and template ids."""
    summaries = library.list()
    by_type: dict[str, TemplateSummary] = {}
    for summary in summaries:
        block_type = block_type_from_tags(summary.tags)
        if block_type is None:
            continue
        if cursor_mode and cursor_mode in summary.tags:
            by_type[block_type] = summary
        elif block_type not in by_type:
            by_type[block_type] = summary

    ordered_types = [block_type for block_type in _BLOCK_TYPES if block_type in by_type]
    sections: list[str] = []
    template_ids: list[str] = []
    used = 0
    for block_type in ordered_types:
        summary = by_type[block_type]
        template = library.recall(summary.template_id)
        if template is None:
            continue
        header = block_type.replace("_", " ").title()
        section = f"### {header}\n{template.body.strip()}"
        if used + len(section) + 2 > max_chars and sections:
            break
        sections.append(section)
        template_ids.append(summary.template_id)
        used += len(section) + 2

    if not sections:
        return "", tuple()
    return "\n\n".join(sections), tuple(template_ids)
