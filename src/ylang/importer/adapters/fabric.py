"""Fabric pattern adapter: reusable pattern bodies only (MIT)."""

from __future__ import annotations

from collections.abc import Mapping

from ylang.importer.source_types import ParsedUpstreamItem

_OWNER = "danielmiessler"
_REPO = "Fabric"
LAYOUT_HINT = "**/patterns/*/system.md (including data/patterns/)"


def _is_pattern_system(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if not normalized.endswith("/system.md"):
        return False
    return "/patterns/" in f"/{normalized}" or normalized.startswith("data/patterns/")


class FabricPatternsAdapter:
    """Import Fabric ``system.md`` pattern bodies as candidates."""

    source_id = "fabric-patterns"
    layout_hint = LAYOUT_HINT

    def select_paths(self, tree_paths: list[str]) -> list[str]:
        """Keep pattern system prompts; skip other Fabric files."""
        return [path for path in tree_paths if _is_pattern_system(path)]

    def parse(
        self,
        files: Mapping[str, str],
        *,
        revision: str,
    ) -> list[ParsedUpstreamItem]:
        """Parse pattern path + body; do not assume system-prompt optimality."""
        items: list[ParsedUpstreamItem] = []
        for path, text in sorted(files.items()):
            if not _is_pattern_system(path):
                continue
            parts = path.replace("\\", "/").split("/")
            name = parts[-2] if len(parts) >= 2 else path
            items.append(
                ParsedUpstreamItem(
                    upstream_item_id=path,
                    title=name.replace("_", " "),
                    body=text.strip(),
                    canonical_url=(
                        f"https://github.com/{_OWNER}/{_REPO}/blob/{revision}/{path}"
                    ),
                    metadata={
                        "pattern": name,
                        "path": path,
                        "adapter": self.source_id,
                    },
                )
            )
        return items


def fabric_raw_url(revision: str, path: str) -> str:
    """Raw GitHub URL for a Fabric file at ``revision``."""
    return f"https://raw.githubusercontent.com/{_OWNER}/{_REPO}/{revision}/{path}"
