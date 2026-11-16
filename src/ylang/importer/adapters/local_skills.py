"""Operator-owned local directory adapter for SKILL.md and *.prompt.md."""

from __future__ import annotations

import os
from pathlib import Path

from ylang.importer.adapters.skill_md import (
    is_prompt_md_path,
    is_skill_md_path,
    parse_skill_or_prompt_files,
)
from ylang.importer.source_types import ParsedUpstreamItem

LAYOUT_HINT = "SKILL.md and *.prompt.md under a configured local directory"
_LOCAL_SKIP = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv"})


def select_local_paths(root: Path) -> list[str]:
    """Return relative paths to ingest under ``root``."""
    selected: list[str] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames if name not in _LOCAL_SKIP and not name.startswith(".")
        ]
        rel_dir = Path(dirpath).relative_to(root)
        for filename in filenames:
            rel = (rel_dir / filename).as_posix()
            if rel.startswith("./"):
                rel = rel[2:]
            if is_skill_md_path(rel) or is_prompt_md_path(rel):
                selected.append(rel)
    selected.sort()
    return selected


def read_local_files(root: Path, paths: list[str]) -> dict[str, str]:
    """Read selected paths relative to ``root``."""
    files: dict[str, str] = {}
    root = root.resolve()
    for rel in paths:
        target = (root / rel).resolve()
        if not str(target).startswith(str(root)):
            continue
        if not target.is_file():
            continue
        files[rel] = target.read_text(encoding="utf-8")
    return files


class LocalSkillsAdapter:
    """Ingest operator-local skills from a directory on disk."""

    source_id = "operator-local-skills"
    layout_hint = LAYOUT_HINT

    def select_paths(self, tree_paths: list[str]) -> list[str]:
        """Keep skill and prompt files (paths already relative)."""
        return [
            path
            for path in tree_paths
            if is_skill_md_path(path) or is_prompt_md_path(path)
        ]

    def parse(
        self,
        files: dict[str, str],
        *,
        revision: str,
    ) -> list[ParsedUpstreamItem]:
        """Parse local skill and prompt files."""

        def _local_url(_revision: str, path: str) -> str:
            return f"local://operator-local-skills/{path}"

        return parse_skill_or_prompt_files(
            files,
            revision=revision,
            adapter=self.source_id,
            raw_url_for_path=_local_url,
        )