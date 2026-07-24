"""MCP tool group registration."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ylang.mcp.deps import YlangDeps
from ylang.mcp.serializers import (
    _parse_window,
    _serialize_fact,
    _serialize_remember,
    _serialize_usage,
)
from ylang.usage.aggregates import summarize_usage
from ylang.usage.feedback import FeedbackStore


def register_memory_usage_tools(server: FastMCP, deps: YlangDeps) -> None:
    """Register memory usage MCP tools."""
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

