"""MCP tool group registration."""

from __future__ import annotations

import sqlite3
from typing import Any

from mcp.server.fastmcp import FastMCP

from ylang.importer import DEFAULT_PROMPTS_URL, import_prompts
from ylang.library.patterns import (
    detect_patterns as run_pattern_detection,
    propose_template_from_pattern_outcome,
)
from ylang.library.store import save_learned_template as persist_learned_template
from ylang.mcp.deps import YlangDeps
from ylang.mcp.serializers import (
    _parse_params,
    _parse_source,
    _parse_visibility,
    _serialize_pattern,
    _serialize_proposal,
    _serialize_summary,
    _serialize_template,
)


def register_library_tools(server: FastMCP, deps: YlangDeps) -> None:
    """Register library MCP tools."""
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
            parsed_visibility = (
                _parse_visibility(visibility) if visibility is not None else None
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "templates": []}
        templates = [
            _serialize_summary(item)
            for item in deps.library.list(
                source=parsed_source, visibility=parsed_visibility
            )
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
    def detect_patterns(window_days: int = 30) -> dict[str, Any]:
        """Detect repeated improver usage patterns and propose learned templates."""
        from ylang.core.engine import Engine
        from ylang.settings import Settings

        patterns = run_pattern_detection(window_days=window_days)
        engine = Engine.from_settings(
            deps.store, surface="mcp", settings=Settings.load()
        )
        proposals = []
        pattern_items = []
        for pattern in patterns:
            outcome = propose_template_from_pattern_outcome(pattern, engine=engine)
            item = _serialize_pattern(pattern)
            if outcome.skip_reason:
                item["skip_reason"] = outcome.skip_reason
            if outcome.proposal is not None:
                item["proposal"] = _serialize_proposal(outcome.proposal)
                proposals.append(_serialize_proposal(outcome.proposal))
            pattern_items.append(item)
        return {
            "ok": True,
            "patterns": pattern_items,
            "proposals": proposals,
        }

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

