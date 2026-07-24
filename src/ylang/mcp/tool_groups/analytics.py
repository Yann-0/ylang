"""MCP tool group registration."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.mcp.deps import YlangDeps
from ylang.mcp.serializers import (
    _parse_window,
)
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import (
    summarize_improver_quality,
    template_effectiveness,
)
from ylang.usage.optimizer import (
    generate_optimization_suggestions,
    serialize_funnel,
    serialize_suggestion,
    serialize_template_row,
)


def register_analytics_tools(server: FastMCP, deps: YlangDeps) -> None:
    """Register analytics MCP tools."""
    @server.tool()
    def create_experiment_variant(
        experiment_id: str,
        variant_id: str,
        config_hash: str,
        traffic_pct: float = 50.0,
        active: bool = True,
    ) -> dict[str, Any]:
        """Create or update a prompt A/B experiment variant for the improver."""
        from ylang.usage.experiment_config import list_known_config_hashes
        from ylang.usage.experiments import ExperimentStore

        if config_hash not in list_known_config_hashes():
            return {
                "ok": False,
                "error": f"unknown config_hash; known: {', '.join(list_known_config_hashes())}",
            }
        store = ExperimentStore(deps.store._connection)
        variant = store.upsert_variant(
            experiment_id=experiment_id,
            variant_id=variant_id,
            config_hash=config_hash,
            traffic_pct=traffic_pct,
            active=active,
        )
        return {
            "ok": True,
            "experiment_id": variant.experiment_id,
            "variant_id": variant.variant_id,
            "config_hash": variant.config_hash,
            "traffic_pct": variant.traffic_pct,
            "active": variant.active,
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
        feedback = FeedbackStore(deps.store._connection)
        report = summarize_improver_quality(deps.store, window, feedback)
        return {"ok": True, **serialize_funnel(report.funnel, report.quality)}

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
            runtime_overrides=RuntimeSettingsStore(deps.store._connection).as_dict(),
        )
        return {
            "ok": True,
            "suggestions": [serialize_suggestion(item) for item in suggestions],
        }

