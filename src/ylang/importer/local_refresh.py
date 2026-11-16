"""Filesystem refresh helpers for operator-local skill sources."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ylang.importer.adapters.local_skills import (
    LocalSkillsAdapter,
    read_local_files,
    select_local_paths,
)
from ylang.importer.normalize import sha256_text
from ylang.importer.policy import SourcePolicyError
from ylang.importer.source_types import ParsedUpstreamItem


def local_git_revision(root: Path) -> str | None:
    """Return ``git rev-parse HEAD`` when ``root`` is a git checkout."""
    if not (root / ".git").exists():
        return None
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = output.strip()
    return revision or None


def load_local_skill_items(root: Path) -> tuple[list[ParsedUpstreamItem], str, list[str]]:
    """Scan ``root`` and return parsed items plus a stable revision."""
    resolved = root.resolve()
    if not resolved.is_dir():
        raise SourcePolicyError("layout", f"local path is not a directory: {resolved}")
    paths = select_local_paths(resolved)
    if not paths:
        raise SourcePolicyError(
            "layout",
            f"no SKILL.md or *.prompt.md under {resolved}",
        )
    files = read_local_files(resolved, paths)
    adapter = LocalSkillsAdapter()
    revision = local_git_revision(resolved) or ""
    items = adapter.parse(files, revision=revision or "local")
    if not revision:
        blob = "\n".join(f"{item.upstream_item_id}\n{item.body}" for item in items)
        revision = f"sha256:{sha256_text(blob)}"
    if not items:
        raise SourcePolicyError("layout", f"no parseable skill files under {resolved}")
    return items, revision, paths