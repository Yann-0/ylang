"""Upstream drift reporting for promoted and operator-local skills."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.importer.source_store import PromptSourceStore


@dataclass(frozen=True, slots=True)
class DriftedPromotedItem:
    """Promoted template whose upstream content hash changed."""

    item_id: str
    source_id: str
    title: str
    linked_template_id: str
    linked_template_version: int | None
    upstream_revision: str | None
    content_hash: str
    previous_content_hash: str | None


@dataclass(frozen=True, slots=True)
class UnlinkedOperatorItem:
    """New operator-owned file waiting for first promote."""

    item_id: str
    source_id: str
    title: str
    upstream_item_id: str
    first_seen_at: str


@dataclass(frozen=True, slots=True)
class PromptDriftReport:
    """Summary of upstream drift and unlinked operator skill files."""

    promoted_drifted: tuple[DriftedPromotedItem, ...]
    operator_unlinked_new: tuple[UnlinkedOperatorItem, ...]


def collect_prompt_drift(store: PromptSourceStore) -> PromptDriftReport:
    """Collect promoted drift and unlinked operator-local candidates."""
    operator_ids = {
        source.source_id
        for source in store.list_sources()
        if source.trust_tier == "operator-owned"
    }
    promoted_drifted: list[DriftedPromotedItem] = []
    unlinked: list[UnlinkedOperatorItem] = []
    for item in store.list_items(limit=100_000):
        if item.candidate_state == "candidate_changed" and item.linked_template_id:
            promoted_drifted.append(
                DriftedPromotedItem(
                    item_id=item.item_id,
                    source_id=item.source_id,
                    title=item.title,
                    linked_template_id=item.linked_template_id,
                    linked_template_version=item.linked_template_version,
                    upstream_revision=item.source_revision,
                    content_hash=item.content_hash,
                    previous_content_hash=item.previous_content_hash,
                )
            )
        if (
            item.source_id in operator_ids
            and item.candidate_state == "candidate_new"
            and not item.linked_template_id
        ):
            unlinked.append(
                UnlinkedOperatorItem(
                    item_id=item.item_id,
                    source_id=item.source_id,
                    title=item.title,
                    upstream_item_id=item.upstream_item_id,
                    first_seen_at=item.first_seen_at,
                )
            )
    promoted_drifted.sort(key=lambda row: row.item_id)
    unlinked.sort(key=lambda row: row.first_seen_at)
    return PromptDriftReport(
        promoted_drifted=tuple(promoted_drifted),
        operator_unlinked_new=tuple(unlinked),
    )