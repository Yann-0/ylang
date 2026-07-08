"""MCP tool adapters — translate inputs/outputs only."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from ylang.core.memory import Fact, RememberResult
from ylang.importer import DEFAULT_PROMPTS_URL, import_prompts
from ylang.improver.context import ImproveContext, build_improve_context
from ylang.improver.types import Change, ImprovementResult
from ylang.library.patterns import (
    TemplateProposal,
    detect_patterns as run_pattern_detection,
    propose_template_from_pattern,
)
from ylang.library.store import save_learned_template as persist_learned_template
from ylang.library.types import (
    Template,
    TemplateParam,
    TemplateSource,
    TemplateSummary,
    TemplateVisibility,
)
from ylang.mcp.deps import YlangDeps
from ylang.usage.aggregates import summarize_usage
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import summarize_improver, template_effectiveness
from ylang.usage.optimizer import (
    generate_optimization_suggestions,
    serialize_funnel,
    serialize_suggestion,
    serialize_template_row,
)
from ylang.usage.store import UsageRecord, UsageWindow


def register_tools(server: FastMCP, deps: YlangDeps) -> None:
    """Register all Ylang MCP tools on the server."""

    @server.tool()
    def improve_prompt(
        text: str,
        tool: str,
        model: str,
        use_context: bool = True,
        conversation: list[dict[str, str]] | None = None,
        mode: str | None = None,
        accepted: bool = False,
        record_acceptance_only: bool = False,
    ) -> dict[str, Any]:
        """Expand rough prompts into full specs; mode-aware for Cursor agent/plan/debug/ask/multitask."""
        if record_acceptance_only:
            deps.store.update_last_improver_accepted(accepted)
            return {"ok": True, "recorded": accepted}
        context: ImproveContext | None = None
        if use_context:
            context = build_improve_context(
                text,
                tool,
                conversation,
                deps.library,
                deps.memory,
                mode=mode,
                store=deps.store,
            )
        result = deps.improver.improve(
            text,
            tool,
            model=model,
            context=context,
            mode=mode,
            accepted=accepted,
        )
        if use_context and context is not None and context.reference_template_ids:
            deps.store.update_last_improver_context_templates(
                list(context.reference_template_ids)
            )
        payload = _serialize_improvement(result)
        if use_context and context is not None:
            payload["context_used"] = _serialize_context_used(context, conversation)
        return payload

    @server.tool()
    def save_template(
        template_id: str,
        name: str,
        body: str,
        params: list[dict[str, str | None]],
        visibility: str = "private",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Save a new user template version to the local library."""
        try:
            parsed_visibility = _parse_visibility(visibility)
            parsed_tags = list(tags) if tags is not None else []
            template = deps.library.save(
                template_id,
                name=name,
                body=body,
                params=_parse_params(params),
                source="user",
                visibility=parsed_visibility,
                tags=parsed_tags,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        payload = _serialize_template(template)
        payload["ok"] = True
        return payload

    @server.tool()
    def recall_template(
        template_id: str,
        version: int | None = None,
        param_values: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch a template by id; optionally render with param values."""
        template = deps.library.recall(template_id, version=version)
        if template is None:
            return {"found": False}
        payload = _serialize_template(template)
        payload["found"] = True
        if param_values is not None:
            try:
                payload["rendered"] = deps.library.render(
                    template_id,
                    param_values,
                    version=version,
                )
            except KeyError as exc:
                return {"found": True, "ok": False, "error": str(exc)}
        return payload

    @server.tool()
    def list_templates(
        source: str | None = None,
        visibility: str | None = None,
    ) -> dict[str, Any]:
        """List templates with latest-version metadata."""
        try:
            parsed_source = _parse_source(source)
            parsed_visibility = _parse_visibility(visibility) if visibility is not None else None
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "templates": []}
        templates = [
            _serialize_summary(item)
            for item in deps.library.list(source=parsed_source, visibility=parsed_visibility)
        ]
        return {"ok": True, "templates": templates}

    @server.tool()
    def import_public_prompts(url: str | None = None) -> dict[str, Any]:
        """Import a public prompts CSV into the local library (default: awesome-chatgpt-prompts)."""
        source_url = url or DEFAULT_PROMPTS_URL
        try:
            result = import_prompts(deps.library, url=source_url)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "source_url": source_url}
        return {
            "ok": True,
            "imported": result.imported,
            "skipped": result.skipped,
            "source_url": source_url,
        }

    @server.tool()
    def remember(fact: str, scope: str, workspace: str = "") -> dict[str, Any]:
        """Persist a user fact under a named scope via core memory."""
        try:
            result = deps.memory.remember(fact, scope, workspace=workspace)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return _serialize_remember(result)

    @server.tool()
    def recall_facts(
        scope: str | None = None,
        limit: int = 100,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Return persisted facts, newest first, optionally filtered by scope."""
        try:
            facts = deps.memory.recall(scope=scope, limit=limit, workspace=workspace)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "facts": []}
        return {
            "ok": True,
            "facts": [_serialize_fact(fact) for fact in facts],
        }

    @server.tool()
    def recall_usage(
        last_hours: int | None = None,
        last_days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Return raw usage rows for a time window."""
        try:
            window = _parse_window(
                last_hours=last_hours,
                last_days=last_days,
                since=since,
                until=until,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "rows": []}
        rows = [_serialize_usage(row) for row in deps.store.recall_usage(window)]
        return {"ok": True, "rows": rows}

    @server.tool()
    def usage_summary(
        last_hours: int | None = None,
        last_days: int | None = None,
    ) -> dict[str, Any]:
        """Return aggregated usage statistics for a time window."""
        try:
            window = _parse_window(
                last_hours=last_hours,
                last_days=last_days,
                since=None,
                until=None,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        summary = summarize_usage(deps.store, window)
        return {
            "ok": True,
            "total_requests": summary.total_requests,
            "total_cost": summary.total_cost,
            "total_tokens": summary.total_tokens,
            "success_rate": summary.success_rate,
            "by_activity": summary.by_activity,
            "by_model": summary.by_model,
            "model_costs": summary.model_costs,
        }

    @server.tool()
    def detect_patterns(window_days: int = 30) -> dict[str, Any]:
        """Detect repeated improver usage patterns and propose learned templates."""
        patterns = run_pattern_detection(window_days=window_days)
        proposals = []
        for pattern in patterns:
            proposal = propose_template_from_pattern(pattern)
            if proposal is not None:
                proposals.append(_serialize_proposal(proposal))
        return {"ok": True, "patterns": [_serialize_pattern(p) for p in patterns], "proposals": proposals}

    @server.tool()
    def save_learned_template(
        template_id: str,
        name: str,
        body: str,
        params: list[dict[str, str | None]],
    ) -> dict[str, Any]:
        """Save a learned template from an accepted pattern proposal."""
        try:
            template = persist_learned_template(
                deps.library,
                template_id,
                name=name,
                body=body,
                params=_parse_params(params),
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        payload = _serialize_template(template)
        payload["ok"] = True
        return payload

    @server.tool()
    def search_templates(query: str, limit: int = 20) -> dict[str, Any]:
        """Search templates by keyword using the local FTS index."""
        try:
            results = deps.library.search(query, limit=limit)
        except sqlite3.OperationalError as exc:
            return {"ok": False, "error": str(exc), "templates": []}
        return {
            "ok": True,
            "query": query,
            "templates": [_serialize_summary(item) for item in results],
        }

    @server.tool()
    def improver_analytics(
        last_hours: int | None = None,
        last_days: int | None = None,
    ) -> dict[str, Any]:
        """Return improver funnel statistics for a time window."""
        try:
            window = _parse_window(
                last_hours=last_hours,
                last_days=last_days,
                since=None,
                until=None,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        funnel = summarize_improver(deps.store, window)
        return {"ok": True, **serialize_funnel(funnel)}

    @server.tool()
    def template_effectiveness_report(
        last_hours: int | None = None,
        last_days: int | None = None,
        min_samples: int = 3,
    ) -> dict[str, Any]:
        """Rank templates by accept rate when injected into improver context."""
        try:
            window = _parse_window(
                last_hours=last_hours,
                last_days=last_days,
                since=None,
                until=None,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "templates": []}
        rows = template_effectiveness(deps.store, window, min_samples=min_samples)
        return {
            "ok": True,
            "templates": [serialize_template_row(row) for row in rows],
        }

    @server.tool()
    def optimization_suggestions(
        last_hours: int | None = None,
        last_days: int | None = None,
    ) -> dict[str, Any]:
        """Return evidence-backed propose-only prompt optimization suggestions."""
        try:
            window = _parse_window(
                last_hours=last_hours,
                last_days=last_days,
                since=None,
                until=None,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "suggestions": []}
        feedback = FeedbackStore(deps.store._connection)
        suggestions = generate_optimization_suggestions(
            deps.store,
            window,
            feedback=feedback,
        )
        return {
            "ok": True,
            "suggestions": [serialize_suggestion(item) for item in suggestions],
        }

    @server.tool()
    def record_prompt_edit(
        original_text: str,
        submitted_text: str,
    ) -> dict[str, Any]:
        """Record user edit feedback between improved and submitted prompt text."""
        feedback = FeedbackStore(deps.store._connection)
        usage_id = deps.store.latest_usage_id()
        event = feedback.record_edit(
            original_text=original_text,
            submitted_text=submitted_text,
            usage_id=usage_id,
        )
        return {
            "ok": True,
            "id": event.id,
            "edit_distance": event.edit_distance,
        }


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
    if visibility not in ("public", "private"):
        msg = "visibility must be public or private"
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
