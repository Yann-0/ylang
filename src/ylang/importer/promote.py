"""Human promotion and rejection of prompt candidates."""

from __future__ import annotations

import difflib
import json
from typing import TYPE_CHECKING

from ylang.importer.convert import normalize_body
from ylang.importer.evaluate import measure_template_observational
from ylang.importer.source_store import PromptSourceStore
from ylang.importer.source_types import SourceItem
from ylang.library.store import Library
from ylang.library.types import Template, TemplateParam

if TYPE_CHECKING:
    from ylang.usage.store import UsageStore


class PromotionError(ValueError):
    """Raised when a candidate cannot be promoted."""


def candidate_diff_text(item: SourceItem, library: Library) -> str:
    """Unified diff against previous upstream body or linked local template."""
    old = item.previous_body or ""
    if not old and item.linked_template_id:
        template = library.recall(item.linked_template_id)
        if template is not None:
            old = template.body
    if not old:
        return item.body
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            item.body.splitlines(keepends=True),
            fromfile="local-or-previous",
            tofile="upstream",
        )
    )


def _params_from_item(item: SourceItem) -> list[TemplateParam]:
    try:
        raw = json.loads(item.params_json)
    except json.JSONDecodeError:
        raw = None
    if not isinstance(raw, list) or not raw:
        _body, params = normalize_body(item.body)
        return params
    params: list[TemplateParam] = []
    for entry in raw:
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        params.append(
            TemplateParam(
                name=str(entry["name"]),
                description=str(entry.get("description") or ""),
                default=entry.get("default"),
            )
        )
    if not params:
        _body, params = normalize_body(item.body)
    return params


def _promotion_template_id(library: Library, item: SourceItem, requested: str | None) -> str:
    if requested:
        return requested
    if item.linked_template_id:
        return item.linked_template_id
    from ylang.importer.convert import slugify

    base = slugify(item.title)
    candidate = base
    existing = library.recall(candidate)
    if existing is None:
        return candidate
    if existing.source == "seed":
        candidate = f"{item.source_id}-{base}"
        if library.recall(candidate) is None:
            return candidate
    suffix = 2
    while library.recall(f"{candidate}-{suffix}") is not None:
        suffix += 1
    return f"{candidate}-{suffix}"


def promote_candidate(
    store: PromptSourceStore,
    library: Library,
    item_id: str,
    *,
    acknowledge_risk: bool = False,
    template_id: str | None = None,
    visibility: str = "public",
    usage_store: UsageStore | None = None,
) -> Template:
    """Create an immutable local template version. Never auto-called by refresh."""
    item = store.get_item(item_id)
    if item is None:
        raise PromotionError(f"unknown candidate: {item_id}")
    if item.candidate_state == "rejected":
        raise PromotionError("rejected candidates cannot be promoted")
    if item.candidate_state == "removed_upstream" and not item.body:
        raise PromotionError("removed upstream item has no body to promote")
    if item.risk_level == "high" and not acknowledge_risk:
        raise PromotionError(
            "high-risk candidates require explicit review (--acknowledge-risk)"
        )
    if item.risk_level == "high" and item.candidate_state == "quarantined" and not acknowledge_risk:
        raise PromotionError("quarantined high-risk candidate requires --acknowledge-risk")
    target_id = _promotion_template_id(library, item, template_id)
    existing = library.recall(target_id)
    if existing is not None and existing.source == "seed" and existing.template_id == target_id:
        raise PromotionError(
            f"refusing to overwrite seed template {target_id}; pass --template-id"
        )
    baseline = (
        measure_template_observational(library, usage_store, target_id)
        if existing is not None
        else None
    )
    tags = [item.task_family, f"source:{item.source_id}"]
    template = library.save(
        target_id,
        name=item.title,
        body=item.body,
        params=_params_from_item(item),
        source="user",
        visibility=visibility,  # type: ignore[arg-type]
        tags=tags,
    )
    store.link_promotion(
        item_id,
        template_id=template.template_id,
        version=template.version,
    )
    store.save_promotion_baseline(
        template_id=template.template_id,
        version=template.version,
        item_id=item.item_id,
        accept_rate=baseline.accept_rate if baseline is not None else None,
        avg_cost=baseline.avg_cost if baseline is not None else None,
        avg_latency_ms=baseline.avg_latency_ms if baseline is not None else None,
        injections=baseline.injections if baseline is not None else 0,
    )
    return template


def reject_candidate(store: PromptSourceStore, item_id: str) -> SourceItem:
    """Reject a candidate. Unchanged hashes will not resurface as new."""
    item = store.get_item(item_id)
    if item is None:
        raise PromotionError(f"unknown candidate: {item_id}")
    updated = store.set_state(item_id, "rejected")
    if updated is None:
        raise PromotionError(f"unknown candidate: {item_id}")
    return updated


def review_candidate(store: PromptSourceStore, item_id: str) -> SourceItem:
    """Mark a candidate reviewed without promoting it."""
    item = store.get_item(item_id)
    if item is None:
        raise PromotionError(f"unknown candidate: {item_id}")
    if item.candidate_state in {"promoted", "rejected"}:
        raise PromotionError(f"cannot review {item.candidate_state} candidate")
    updated = store.set_state(item_id, "reviewed")
    if updated is None:
        raise PromotionError(f"unknown candidate: {item_id}")
    return updated
