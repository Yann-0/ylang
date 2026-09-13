"""Candidate ingest: normalize, scan, dedup, persist. Never auto-promotes."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

from ylang.importer.convert import normalize_body
from ylang.importer.normalize import content_hash, normalize_title, placeholder_fingerprint
from ylang.importer.policy import ADAPTER_VERSION
from ylang.importer.quality import score_prompt_quality
from ylang.importer.risk import scan_prompt_risk
from ylang.importer.source_store import PromptSourceStore
from ylang.importer.source_types import (
    CandidateState,
    ParsedUpstreamItem,
    PromptSource,
    RefreshSummary,
    SourceItem,
    utcnow_iso,
)

if TYPE_CHECKING:
    from ylang.library.store import Library


def item_id_for(source_id: str, upstream_item_id: str) -> str:
    """Stable local identity for an upstream item."""
    return f"{source_id}:{upstream_item_id}"


def _params_json_from_body(body: str) -> str:
    _normalized, params = normalize_body(body)
    payload = [
        {"name": param.name, "description": param.description, "default": param.default}
        for param in params
    ]
    return json.dumps(payload)


def _template_hash_index(library: Library) -> dict[str, str]:
    """Map content hash and fingerprint to template_id."""
    index: dict[str, str] = {}
    for summary in library.list(include_archived=True):
        template = library.recall(summary.template_id)
        if template is None:
            continue
        index[content_hash(template.body)] = template.template_id
        index[placeholder_fingerprint(template.body)] = template.template_id
    return index


def _next_state(
    *,
    existing: SourceItem | None,
    body_hash: str,
    risk_level: str,
    rejected_hashes: set[str],
    duplicate_rejected: bool,
) -> tuple[CandidateState, bool]:
    """Return (state, is_changed). Rejected hashes do not resurface as new."""
    if body_hash in rejected_hashes or duplicate_rejected:
        if existing is None:
            return "rejected", False
        if existing.content_hash == body_hash:
            return "rejected", False
    if risk_level == "high":
        if existing is None:
            return "quarantined", False
        if existing.content_hash == body_hash:
            if existing.candidate_state in {"promoted", "rejected", "reviewed"}:
                return existing.candidate_state, False
            return "quarantined", False
        return "quarantined", True
    if existing is None:
        return "candidate_new", False
    if existing.content_hash == body_hash:
        if existing.candidate_state == "removed_upstream":
            if existing.linked_template_id:
                return "promoted", False
            return "candidate_new", False
        return existing.candidate_state, False
    if existing.candidate_state == "rejected":
        return "candidate_new", True
    if existing.candidate_state == "promoted":
        return "candidate_changed", True
    return "candidate_changed", True


def ingest_parsed_items(
    store: PromptSourceStore,
    library: Library,
    source: PromptSource,
    parsed: list[ParsedUpstreamItem],
    *,
    revision: str,
    mark_removed: bool,
) -> RefreshSummary:
    """Upsert parsed items as candidates. Does not create template versions."""
    now = utcnow_iso()
    rejected = store.rejected_hashes()
    template_index = _template_hash_index(library)
    seen_upstream: set[str] = set()
    new = changed = unchanged = duplicates = quarantined = suppressed = errors = 0

    try:
        store._connection.execute("BEGIN")
    except Exception:
        pass

    try:
        for raw in parsed:
            seen_upstream.add(raw.upstream_item_id)
            try:
                body = raw.body.strip()
                if not body:
                    errors += 1
                    continue
                body_hash = content_hash(body)
                fingerprint = placeholder_fingerprint(body)
                title_key = normalize_title(raw.title)
                existing = store.get_by_upstream(source.source_id, raw.upstream_item_id)
                dup = store.find_duplicate_item(
                    content_hash=body_hash,
                    fingerprint=fingerprint,
                    title_normalized=title_key,
                    exclude_item_id=existing.item_id if existing else None,
                )
                duplicate_rejected = bool(
                    dup is not None and dup.candidate_state == "rejected"
                )
                if dup is None and body_hash in rejected:
                    duplicate_rejected = True
                risk = scan_prompt_risk(
                    body, metadata_tools=(raw.metadata or {}).get("tools")
                )
                quality = score_prompt_quality(
                    title=raw.title,
                    body=body,
                    duplicate=dup is not None,
                    model_hint=raw.model_hint,
                    metadata=raw.metadata,
                )
                state, is_changed = _next_state(
                    existing=existing,
                    body_hash=body_hash,
                    risk_level=risk.level,
                    rejected_hashes=rejected,
                    duplicate_rejected=duplicate_rejected,
                )
                params_json = json.dumps((raw.metadata or {}).get("params")) if (
                    raw.metadata or {}
                ).get("params") else _params_json_from_body(body)
                dup_template = template_index.get(body_hash) or template_index.get(
                    fingerprint
                )
                item = SourceItem(
                    item_id=item_id_for(source.source_id, raw.upstream_item_id),
                    source_id=source.source_id,
                    upstream_item_id=raw.upstream_item_id,
                    canonical_url=raw.canonical_url,
                    source_revision=revision,
                    content_hash=body_hash,
                    normalized_fingerprint=fingerprint,
                    title=raw.title,
                    body=body,
                    params_json=params_json if params_json != "null" else _params_json_from_body(body),
                    metadata_json=json.dumps(raw.metadata or {}),
                    first_seen_at=existing.first_seen_at if existing else now,
                    last_seen_at=now,
                    candidate_state=state,
                    risk_level=risk.level,
                    risk_reasons=risk.reasons,
                    quality_score=quality.score,
                    quality_reasons=quality.reasons,
                    task_family=quality.task_family,
                    model_hint=raw.model_hint,
                    duplicate_of_item_id=None if dup is None else dup.item_id,
                    duplicate_template_id=dup_template,
                    linked_template_id=existing.linked_template_id if existing else None,
                    linked_template_version=(
                        existing.linked_template_version if existing else None
                    ),
                    license_spdx=source.license_spdx,
                    adapter_version=ADAPTER_VERSION,
                    previous_body=(
                        existing.body if existing and existing.content_hash != body_hash else (
                            existing.previous_body if existing else None
                        )
                    ),
                    previous_content_hash=(
                        existing.content_hash
                        if existing and existing.content_hash != body_hash
                        else (existing.previous_content_hash if existing else None)
                    ),
                )
                if existing is not None and existing.content_hash == body_hash:
                    item = replace(item, candidate_state=state)
                    store.upsert_item(item)
                    if state == "rejected":
                        suppressed += 1
                    else:
                        unchanged += 1
                    if item.duplicate_of_item_id:
                        duplicates += 1
                    continue
                store.upsert_item(item)
                if state == "rejected" and existing is None:
                    suppressed += 1
                elif existing is None:
                    new += 1
                elif is_changed:
                    changed += 1
                else:
                    unchanged += 1
                if state == "quarantined":
                    quarantined += 1
                if item.duplicate_of_item_id or item.duplicate_template_id:
                    duplicates += 1
            except (ValueError, TypeError, json.JSONDecodeError):
                errors += 1

        removed = 0
        if mark_removed:
            existing_rows = store.list_items(source_id=source.source_id, limit=50_000)
            for row in existing_rows:
                if row.upstream_item_id in seen_upstream:
                    continue
                if row.candidate_state == "removed_upstream":
                    continue
                store.upsert_item(
                    replace(
                        row,
                        candidate_state="removed_upstream",
                        last_seen_at=now,
                    )
                )
                removed += 1

        store._connection.commit()
    except Exception:
        store._connection.rollback()
        raise

    return RefreshSummary(
        source_id=source.source_id,
        status="success",
        revision_before=source.last_revision,
        revision_after=revision,
        new=new,
        changed=changed,
        removed=removed,
        duplicates=duplicates,
        quarantined=quarantined,
        rejected_suppressed=suppressed,
        errors=errors,
        unchanged=unchanged,
    )
