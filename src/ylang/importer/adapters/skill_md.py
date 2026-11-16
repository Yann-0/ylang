"""Parse Cursor-style SKILL.md artifacts into upstream items."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ylang.importer.adapters.frontmatter import parse_simple_frontmatter
from ylang.importer.source_types import ParsedUpstreamItem

_SKILL_MD = re.compile(r"(^|/)SKILL\.md$", re.I)
_PROMPT_MD = re.compile(r"\.prompt\.md$", re.I)


def is_skill_md_path(path: str) -> bool:
    """Return True when ``path`` is a skill definition file."""
    normalized = path.replace("\\", "/")
    return bool(_SKILL_MD.search(normalized))


def is_prompt_md_path(path: str) -> bool:
    """Return True when ``path`` is a flat prompt markdown file."""
    return bool(_PROMPT_MD.search(path.replace("\\", "/")))


def skill_upstream_id(path: str) -> str:
    """Stable upstream id for a skill file path."""
    return path.replace("\\", "/")


def parse_skill_file(
    path: str,
    text: str,
    *,
    revision: str,
    canonical_url: str | None,
    adapter: str,
) -> ParsedUpstreamItem:
    """Parse one SKILL.md into a skill candidate (metadata only; no tool grants)."""
    meta, body = parse_simple_frontmatter(text)
    name = str(meta.get("name") or path.rsplit("/", 2)[-2])
    description = str(meta.get("description") or name)
    when_to_use = str(meta.get("when_to_use") or meta.get("when-to-use") or "")
    composed = body.strip()
    if when_to_use and when_to_use not in composed:
        composed = f"{when_to_use.strip()}\n\n{composed}".strip()
    title = description if len(description) <= 120 else name
    tags: tuple[str, ...] = ("artifact:skill",)
    return ParsedUpstreamItem(
        upstream_item_id=skill_upstream_id(path),
        title=title,
        body=composed,
        canonical_url=canonical_url,
        metadata={
            "path": path,
            "artifact": "skill",
            "skill_name": name,
            "description": description,
            "when_to_use": when_to_use or None,
            "adapter": adapter,
        },
        tags=tags,
    )


def parse_prompt_md_file(
    path: str,
    text: str,
    *,
    revision: str,
    canonical_url: str | None,
    adapter: str,
) -> ParsedUpstreamItem:
    """Parse a ``*.prompt.md`` file into a candidate."""
    meta, body = parse_simple_frontmatter(text)
    title = str(meta.get("description") or path.rsplit("/", 1)[-1])
    model_hint = meta.get("model")
    if model_hint is not None:
        model_hint = str(model_hint)
    tools = meta.get("tools")
    return ParsedUpstreamItem(
        upstream_item_id=path.replace("\\", "/"),
        title=title,
        body=body.strip(),
        canonical_url=canonical_url,
        metadata={
            "path": path,
            "artifact": "prompt",
            "description": meta.get("description"),
            "agent": meta.get("agent"),
            "model": model_hint,
            "tools": tools,
            "tags": meta.get("tags"),
            "adapter": adapter,
        },
        model_hint=model_hint,
        tags=tuple(meta["tags"]) if isinstance(meta.get("tags"), list) else (),
    )


def parse_skill_or_prompt_files(
    files: Mapping[str, str],
    *,
    revision: str,
    adapter: str,
    raw_url_for_path: Any,
) -> list[ParsedUpstreamItem]:
    """Parse a map of path → text into upstream items."""
    items: list[ParsedUpstreamItem] = []
    for path, text in sorted(files.items()):
        normalized = path.replace("\\", "/")
        url = raw_url_for_path(revision, normalized)
        if is_skill_md_path(normalized):
            items.append(
                parse_skill_file(
                    normalized,
                    text,
                    revision=revision,
                    canonical_url=url,
                    adapter=adapter,
                )
            )
        elif is_prompt_md_path(normalized):
            items.append(
                parse_prompt_md_file(
                    normalized,
                    text,
                    revision=revision,
                    canonical_url=url,
                    adapter=adapter,
                )
            )
    return items