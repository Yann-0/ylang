"""GitHub awesome-copilot adapter: prompt files only (MIT)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ylang.importer.source_types import ParsedUpstreamItem

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
_OWNER = "github"
_REPO = "awesome-copilot"
SKIP_DIR_PARTS = frozenset({"agents", "skills", "instructions", "mcp"})
LAYOUT_HINT = (
    "*.prompt.md outside agents/skills/instructions/mcp "
    "(including prompts/ and .github/prompts/)"
)


def parse_simple_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-ish frontmatter without a YAML dependency.

    Supports ``key: value``, quoted scalars, and ``[a, b]`` lists.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    meta: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        raw_value = value.strip()
        meta[key] = _parse_scalar(raw_value)
    body = text[match.end() :]
    return meta, body


def _parse_scalar(raw: str) -> Any:
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(part.strip()) for part in inner.split(",") if part.strip()]
    return _strip_quotes(raw)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
        return value[1:-1]
    return value


def _is_prompt_path(path: str) -> bool:
    if not path.endswith(".prompt.md"):
        return False
    parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    if parts & SKIP_DIR_PARTS:
        return False
    return True


class AwesomeCopilotAdapter:
    """Import ``*.prompt.md`` files; ignore agents, skills, MCP, and instructions."""

    source_id = "github-awesome-copilot"
    layout_hint = LAYOUT_HINT

    def select_paths(self, tree_paths: list[str]) -> list[str]:
        """Keep prompt files only."""
        return [path for path in tree_paths if _is_prompt_path(path)]

    def parse(
        self,
        files: Mapping[str, str],
        *,
        revision: str,
    ) -> list[ParsedUpstreamItem]:
        """Parse prompt files and preserve frontmatter as metadata only."""
        items: list[ParsedUpstreamItem] = []
        for path, text in sorted(files.items()):
            if not _is_prompt_path(path):
                continue
            meta, body = parse_simple_frontmatter(text)
            title = str(meta.get("description") or path.rsplit("/", 1)[-1])
            model_hint = meta.get("model")
            if model_hint is not None:
                model_hint = str(model_hint)
            tools = meta.get("tools")
            items.append(
                ParsedUpstreamItem(
                    upstream_item_id=path,
                    title=title,
                    body=body.strip(),
                    canonical_url=(
                        f"https://github.com/{_OWNER}/{_REPO}/blob/{revision}/{path}"
                    ),
                    metadata={
                        "path": path,
                        "description": meta.get("description"),
                        "agent": meta.get("agent"),
                        "model": model_hint,
                        "tools": tools,
                        "tags": meta.get("tags"),
                        "adapter": self.source_id,
                    },
                    model_hint=model_hint,
                    tags=tuple(meta["tags"]) if isinstance(meta.get("tags"), list) else (),
                )
            )
        return items


def awesome_copilot_raw_url(revision: str, path: str) -> str:
    """Raw GitHub URL for a prompt file at ``revision``."""
    return f"https://raw.githubusercontent.com/{_OWNER}/{_REPO}/{revision}/{path}"
