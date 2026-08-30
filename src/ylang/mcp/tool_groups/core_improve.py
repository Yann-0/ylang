"""MCP tool group registration."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ylang.improver.context import ImproveContext, build_improve_context
from ylang.mcp.deps import YlangDeps
from ylang.mcp.serializers import (
    _serialize_context_used,
    _serialize_improvement,
)
from ylang.usage.store import UsageWindow


def register_core_improve_tools(server: FastMCP, deps: YlangDeps) -> None:
    """Register core improve MCP tools."""

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
        parent_trace_id: str | None = None,
        session_id: str | None = None,
        workspace: str | None = None,
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
            parent_trace_id=parent_trace_id,
            session_id=session_id,
            workspace=workspace,
        )
        if use_context and context is not None and context.reference_template_ids:
            deps.store.update_last_improver_context_templates(
                list(context.reference_template_ids)
            )
        payload = _serialize_improvement(result)
        if use_context and context is not None:
            payload["context_used"] = _serialize_context_used(context, conversation)
        latest_id = deps.store.latest_usage_id()
        if latest_id is not None:
            for row in deps.store.recall_usage(UsageWindow.last_hours(1)):
                if row.id == latest_id and row.trace_id:
                    payload["trace_id"] = row.trace_id
                    break
        return payload
