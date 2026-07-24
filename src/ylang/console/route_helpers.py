"""Shared helpers for console route modules."""

from __future__ import annotations

import json
import secrets

from ylang.core.runtime_settings import RuntimeSettingsStore, effective_int_setting
from ylang.library.patterns import DetectedPattern, TemplateProposal
from ylang.settings import Settings


def _valid_tokens(settings: Settings) -> list[str]:
    tokens: list[str] = []
    if settings.auth_token:
        tokens.append(settings.auth_token)
    if settings.auth_token_previous:
        tokens.append(settings.auth_token_previous)
    return tokens


def _token_ok(candidate: str, settings: Settings) -> bool:
    return any(secrets.compare_digest(candidate, token) for token in _valid_tokens(settings))


def _pattern_threshold(runtime_store: RuntimeSettingsStore) -> int:
    return effective_int_setting(
        "pattern_alert_threshold",
        default=3,
        overrides=runtime_store.as_dict(),
    )


def _preferred_template_candidates(
    library: object,
    *,
    limit: int = 30,
) -> list[dict[str, str]]:
    """Return seed then private non-archived templates for the preferred-id picker."""
    from ylang.library.store import Library

    assert isinstance(library, Library)
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(summary: object) -> bool:
        template_id = getattr(summary, "template_id", "")
        name = getattr(summary, "name", template_id)
        if not template_id or template_id in seen:
            return False
        seen.add(template_id)
        candidates.append({"id": template_id, "name": name})
        return len(candidates) >= limit

    for summary in library.list(source="seed"):
        if _add(summary):
            return candidates
    for summary in library.list(visibility="private"):
        if summary.source == "seed":
            continue
        if _add(summary):
            return candidates
    return candidates


def _serialize_pattern_cache(
    patterns: list[DetectedPattern],
    proposals: list[TemplateProposal | None],
    skip_reasons: list[str | None] | None = None,
) -> str:
    payload = []
    reasons = skip_reasons or [None] * len(patterns)
    for pattern, proposal, skip_reason in zip(patterns, proposals, reasons, strict=False):
        item: dict[str, object] = {
            "pattern_id": pattern.pattern_id,
            "sample_text": pattern.sample_text,
            "occurrence_count": pattern.occurrence_count,
        }
        if skip_reason:
            item["skip_reason"] = skip_reason
        if proposal is not None:
            item["proposal"] = {
                "suggested_template_id": proposal.suggested_template_id,
                "name": proposal.name,
                "body": proposal.body,
                "rationale": proposal.rationale,
            }
        payload.append(item)
    return json.dumps(payload)


def _deserialize_pattern_cache(
    raw: str | None,
) -> tuple[list[DetectedPattern], list[TemplateProposal | None], list[str | None]]:
    if not raw:
        return [], [], []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [], [], []
    if not isinstance(payload, list):
        return [], [], []
    patterns: list[DetectedPattern] = []
    proposals: list[TemplateProposal | None] = []
    skip_reasons: list[str | None] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        patterns.append(
            DetectedPattern(
                pattern_id=str(item.get("pattern_id", "")),
                sample_text=str(item.get("sample_text", "")),
                occurrence_count=int(item.get("occurrence_count", 1)),
            )
        )
        skip_reasons.append(
            str(item["skip_reason"]) if item.get("skip_reason") else None
        )
        proposal_raw = item.get("proposal")
        if isinstance(proposal_raw, dict):
            proposals.append(
                TemplateProposal(
                    suggested_template_id=str(proposal_raw.get("suggested_template_id", "")),
                    name=str(proposal_raw.get("name", "")),
                    body=str(proposal_raw.get("body", "")),
                    params=[],
                    rationale=str(proposal_raw.get("rationale", "")),
                )
            )
        else:
            proposals.append(None)
    return patterns, proposals, skip_reasons
