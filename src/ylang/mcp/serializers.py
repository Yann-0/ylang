"""MCP response/request serializers and parsers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ylang.core.memory import Fact, RememberResult
from ylang.improver.context import ImproveContext
from ylang.improver.types import Change, ImprovementResult
from ylang.library.patterns import TemplateProposal
from ylang.library.types import (
    Template,
    TemplateParam,
    TemplateSource,
    TemplateSummary,
    TemplateVisibility,
)
from ylang.usage.store import UsageRecord, UsageWindow

def _serialize_improvement(result: ImprovementResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "original": result.original,
        "improved": result.improved,
        "changes": [_serialize_change(change) for change in result.changes],
        "auto_apply_default": result.auto_apply_default,
        "validated": result.validated,
        "cursor_mode": result.cursor_mode,
        "mode_source": result.mode_source,
    }
    if result.rejection_reason is not None:
        payload["rejection_reason"] = result.rejection_reason
    return payload


def _serialize_change(change: Change) -> dict[str, Any]:
    return {
        "kind": change.kind,
        "description": change.description,
        "before": change.before,
        "after": change.after,
    }


def _serialize_template(template: Template) -> dict[str, Any]:
    return {
        "template_id": template.template_id,
        "name": template.name,
        "version": template.version,
        "body": template.body,
        "params": [_serialize_param(param) for param in template.params],
        "source": template.source,
        "created_at": template.created_at.isoformat(),
        "visibility": template.visibility,
        "tags": list(template.tags),
    }


def _serialize_param(param: TemplateParam) -> dict[str, Any]:
    return {
        "name": param.name,
        "description": param.description,
        "default": param.default,
    }


def _serialize_summary(summary: TemplateSummary) -> dict[str, Any]:
    return {
        "template_id": summary.template_id,
        "name": summary.name,
        "latest_version": summary.latest_version,
        "source": summary.source,
        "updated_at": summary.updated_at.isoformat(),
        "param_names": list(summary.param_names),
        "visibility": summary.visibility,
        "tags": list(summary.tags),
    }


def _serialize_usage(record: UsageRecord) -> dict[str, Any]:
    context_templates: list[str] = []
    if record.improver_context_templates:
        context_templates = [
            part.strip()
            for part in record.improver_context_templates.split(",")
            if part.strip()
        ]
    payload: dict[str, Any] = {
        "id": record.id,
        "timestamp": record.timestamp.isoformat(),
        "surface": record.surface,
        "activity": record.activity,
        "model_used": record.model_used,
        "prompt_tokens": record.prompt_tokens,
        "cost": record.cost,
        "improver_fired": record.improver_fired,
        "improver_accepted": record.improver_accepted,
        "improver_input_sample": record.improver_input_sample,
        "latency_ms": record.latency_ms,
        "success": record.success,
        "improver_context_templates": context_templates,
    }
    if record.improver_validated is not None:
        payload["improver_validated"] = record.improver_validated
    if record.improver_changed is not None:
        payload["improver_changed"] = record.improver_changed
    if record.improver_rejection_reason is not None:
        payload["improver_rejection_reason"] = record.improver_rejection_reason
    if record.improver_task_class is not None:
        payload["improver_task_class"] = record.improver_task_class
    if record.cursor_mode is not None:
        payload["cursor_mode"] = record.cursor_mode
    if record.experiment_variant is not None:
        payload["experiment_variant"] = record.experiment_variant
    return payload


def _parse_params(raw: list[dict[str, str | None]]) -> list[TemplateParam]:
    return [
        TemplateParam(
            name=str(item["name"]),
            description=str(item.get("description") or ""),
            default=item.get("default"),
        )
        for item in raw
    ]


def _parse_source(source: str | None) -> TemplateSource | None:
    if source is None:
        return None
    if source not in ("seed", "user", "learned"):
        msg = "source must be seed, user, or learned"
        raise ValueError(msg)
    return source  # type: ignore[return-value]


def _parse_visibility(visibility: str | None) -> TemplateVisibility:
    if visibility is None:
        return "private"
    if visibility not in ("public", "private", "archived"):
        msg = "visibility must be public, private, or archived"
        raise ValueError(msg)
    return visibility  # type: ignore[return-value]


def _serialize_context_used(
    context: ImproveContext,
    conversation: list[dict[str, str]] | None,
) -> dict[str, Any]:
    conversation_turns = 0
    if conversation and context.conversation_block:
        conversation_turns = len(
            [line for line in context.conversation_block.splitlines() if line.strip()]
        )
    facts_count = 0
    if context.facts_block:
        facts_count = len(
            [line for line in context.facts_block.splitlines() if line.strip()]
        )
    reference_prompts_count = 0
    if context.reference_prompts_block:
        reference_prompts_count = context.reference_prompts_block.count("### ")
    return {
        "conversation_turns": conversation_turns,
        "facts_count": facts_count,
        "reference_prompts_count": reference_prompts_count,
        "had_conversation_input": bool(conversation),
    }


def _parse_window(
    *,
    last_hours: int | None,
    last_days: int | None,
    since: str | None,
    until: str | None,
) -> UsageWindow:
    specs = [
        last_hours is not None,
        last_days is not None,
        since is not None or until is not None,
    ]
    if sum(specs) > 1:
        msg = "provide only one of last_hours, last_days, or since/until"
        raise ValueError(msg)
    if last_hours is not None:
        return UsageWindow.last_hours(last_hours)
    if last_days is not None:
        return UsageWindow.last_days(last_days)
    if since is not None and until is not None:
        return UsageWindow(since=_parse_utc(since), until=_parse_utc(until))
    return UsageWindow.last_days(7)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_remember(result: RememberResult) -> dict[str, Any]:
    return {
        "ok": True,
        "id": result.id,
        "fact": result.fact,
        "scope": result.scope,
        "created_at": result.created_at.isoformat(),
    }


def _serialize_fact(fact: Fact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "fact": fact.fact,
        "scope": fact.scope,
        "workspace": fact.workspace,
        "created_at": fact.created_at.isoformat(),
    }


def _serialize_pattern(pattern: object) -> dict[str, Any]:
    from ylang.library.patterns import DetectedPattern

    assert isinstance(pattern, DetectedPattern)
    return {
        "pattern_id": pattern.pattern_id,
        "sample_text": pattern.sample_text,
        "occurrence_count": pattern.occurrence_count,
    }


def _serialize_proposal(proposal: TemplateProposal) -> dict[str, Any]:
    return {
        "suggested_template_id": proposal.suggested_template_id,
        "name": proposal.name,
        "body": proposal.body,
        "params": [_serialize_param(param) for param in proposal.params],
        "rationale": proposal.rationale,
    }
