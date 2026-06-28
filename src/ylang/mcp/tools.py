"""MCP tool adapters — translate inputs/outputs only."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from ylang.improver.types import Change, ImprovementResult
from ylang.library.types import Template, TemplateParam, TemplateSource, TemplateSummary
from ylang.mcp.deps import YlangDeps
from ylang.usage.store import UsageRecord, UsageWindow


def register_tools(server: FastMCP, deps: YlangDeps) -> None:
    """Register all Ylang MCP tools on the server."""

    @server.tool()
    def improve_prompt(text: str, tool: str, model: str) -> dict[str, Any]:
        """Propose-only structural prompt edits; never applies changes."""
        result = deps.improver.improve(text, tool, model=model)
        return _serialize_improvement(result)

    @server.tool()
    def save_template(
        template_id: str,
        name: str,
        body: str,
        params: list[dict[str, str | None]],
    ) -> dict[str, Any]:
        """Save a new user template version to the local library."""
        template = deps.library.save(
            template_id,
            name=name,
            body=body,
            params=_parse_params(params),
            source="user",
        )
        return _serialize_template(template)

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
            payload["rendered"] = deps.library.render(
                template_id,
                param_values,
                version=version,
            )
        return payload

    @server.tool()
    def list_templates(source: str | None = None) -> list[dict[str, Any]]:
        """List templates with latest-version metadata."""
        parsed_source = _parse_source(source)
        return [_serialize_summary(item) for item in deps.library.list(source=parsed_source)]

    @server.tool()
    def remember(fact: str, scope: str) -> dict[str, Any]:
        """Persist a user fact under a named scope via core memory."""
        remember_fn = _load_core_remember()
        if remember_fn is None:
            return {
                "ok": False,
                "error": "remember is unavailable until ylang.core.memory is implemented",
            }
        result = remember_fn(fact, scope)
        if hasattr(result, "__dataclass_fields__"):
            return {"ok": True, **_dataclass_to_dict(result)}
        if isinstance(result, dict):
            return {"ok": True, **result}
        return {"ok": True, "result": result}

    @server.tool()
    def recall_usage(
        last_hours: int | None = None,
        last_days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return raw usage rows for a time window."""
        window = _parse_window(
            last_hours=last_hours,
            last_days=last_days,
            since=since,
            until=until,
        )
        return [_serialize_usage(row) for row in deps.store.recall_usage(window)]


def _serialize_improvement(result: ImprovementResult) -> dict[str, Any]:
    return {
        "original": result.original,
        "improved": result.improved,
        "changes": [_serialize_change(change) for change in result.changes],
        "auto_apply_default": result.auto_apply_default,
    }


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
    }


def _serialize_usage(record: UsageRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "timestamp": record.timestamp.isoformat(),
        "surface": record.surface,
        "activity": record.activity,
        "model_used": record.model_used,
        "prompt_tokens": record.prompt_tokens,
        "cost": record.cost,
        "improver_fired": record.improver_fired,
        "improver_accepted": record.improver_accepted,
        "latency_ms": record.latency_ms,
        "success": record.success,
    }


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


def _load_core_remember() -> Any | None:
    try:
        module = importlib.import_module("ylang.core.memory")
    except ModuleNotFoundError:
        return None
    return getattr(module, "remember", None)


def _dataclass_to_dict(value: Any) -> dict[str, Any]:
    from dataclasses import asdict

    payload = asdict(value)
    for key, item in payload.items():
        if isinstance(item, datetime):
            payload[key] = item.isoformat()
    return payload
