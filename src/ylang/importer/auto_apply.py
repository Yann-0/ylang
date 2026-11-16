"""Auto-apply upstream updates for operator-owned linked skills only."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ylang.importer.convert import normalize_body
from ylang.importer.policy import auto_apply_allowed
from ylang.importer.promote import _params_from_item
from ylang.importer.source_store import PromptSourceStore
from ylang.importer.source_types import PromptSource, SourceItem

if TYPE_CHECKING:
    from ylang.library.store import Library


def auto_apply_linked_updates(
    store: PromptSourceStore,
    library: Library,
    source: PromptSource,
) -> int:
    """Write new template versions for changed, already-linked operator items.

    Brand-new files and public sources never auto-apply. High-risk quarantine is skipped.
    """
    if not auto_apply_allowed(source):
        return 0
    applied = 0
    for item in store.list_items(source_id=source.source_id, limit=50_000):
        if item.candidate_state != "candidate_changed":
            continue
        if not item.linked_template_id:
            continue
        if item.risk_level == "high":
            continue
        if _apply_one_linked(store, library, item):
            applied += 1
    return applied


def _apply_one_linked(
    store: PromptSourceStore,
    library: Library,
    item: SourceItem,
) -> bool:
    template_id = item.linked_template_id
    if not template_id:
        return False
    existing = library.recall(template_id)
    if existing is None:
        return False
    try:
        meta = json.loads(item.metadata_json)
    except json.JSONDecodeError:
        meta = {}
    tags = list(existing.tags)
    for tag in (f"source:{item.source_id}", item.task_family):
        if tag not in tags:
            tags.append(tag)
    if meta.get("artifact") == "skill" and "artifact:skill" not in tags:
        tags.append("artifact:skill")
    _body, _params = normalize_body(item.body)
    library.save(
        template_id,
        name=item.title,
        body=item.body,
        params=_params_from_item(item),
        source="user",
        visibility=existing.visibility,
        tags=tags,
    )
    template = library.recall(template_id)
    if template is None:
        return False
    store.link_promotion(
        item.item_id,
        template_id=template.template_id,
        version=template.version,
    )
    return True
