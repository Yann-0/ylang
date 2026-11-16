"""GitHub awesome-copilot adapter: skills (SKILL.md) and legacy *.prompt.md (MIT)."""

from __future__ import annotations

from collections.abc import Mapping

from ylang.importer.adapters.frontmatter import parse_simple_frontmatter
from ylang.importer.adapters.skill_md import (
    is_prompt_md_path,
    is_skill_md_path,
    parse_skill_or_prompt_files,
)
from ylang.importer.source_types import ParsedUpstreamItem

_OWNER = "github"
_REPO = "awesome-copilot"
SKIP_DIR_PARTS = frozenset({"agents", "instructions", "mcp"})
LAYOUT_HINT = "skills/**/SKILL.md and *.prompt.md outside agents/instructions/mcp"

__all__ = [
    "AwesomeCopilotAdapter",
    "LAYOUT_HINT",
    "awesome_copilot_raw_url",
    "parse_simple_frontmatter",
]


def _is_copilot_prompt_path(path: str) -> bool:
    if not is_prompt_md_path(path):
        return False
    parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    if parts & SKIP_DIR_PARTS:
        return False
    return True


def _is_copilot_skill_path(path: str) -> bool:
    if not is_skill_md_path(path):
        return False
    normalized = path.replace("\\", "/").lower()
    if not normalized.startswith("skills/"):
        return False
    parts = set(normalized.split("/"))
    return not (parts & SKIP_DIR_PARTS)


class AwesomeCopilotAdapter:
    """Import awesome-copilot skills and flat prompt files."""

    source_id = "github-awesome-copilot"
    layout_hint = LAYOUT_HINT

    def select_paths(self, tree_paths: list[str]) -> list[str]:
        """Keep SKILL.md under skills/ and eligible prompt files."""
        selected: list[str] = []
        for path in tree_paths:
            if _is_copilot_skill_path(path) or _is_copilot_prompt_path(path):
                selected.append(path)
        return selected

    def parse(
        self,
        files: Mapping[str, str],
        *,
        revision: str,
    ) -> list[ParsedUpstreamItem]:
        """Parse skill and prompt files; upstream tools stay metadata-only."""
        return parse_skill_or_prompt_files(
            files,
            revision=revision,
            adapter=self.source_id,
            raw_url_for_path=awesome_copilot_raw_url,
        )


def awesome_copilot_raw_url(revision: str, path: str) -> str:
    """Raw GitHub URL for a file at ``revision``."""
    return f"https://raw.githubusercontent.com/{_OWNER}/{_REPO}/{revision}/{path}"