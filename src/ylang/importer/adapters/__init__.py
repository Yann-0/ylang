"""Tier-A source adapters (structured data only; no generic crawler)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ylang.importer.source_types import ParsedUpstreamItem


class SourceAdapter(Protocol):
    """Parse already-fetched files for one allowlisted source."""

    source_id: str
    layout_hint: str

    def select_paths(self, tree_paths: list[str]) -> list[str]:
        """Return relative paths to import from a git tree listing."""
        ...

    def parse(
        self,
        files: Mapping[str, str],
        *,
        revision: str,
    ) -> list[ParsedUpstreamItem]:
        """Parse fetched file contents into upstream items."""
        ...
