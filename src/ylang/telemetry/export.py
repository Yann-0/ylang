"""Optional OpenTelemetry/OTLP export of completion metadata.

The local SQLite usage store is independent of this module. Enabling OTLP
never replaces local traces. Export is disabled by default, does not run
during ordinary unit tests, and must not fail LLM operations.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ylang.core.types import ModelResolution
from ylang.usage.capture import redact_secrets

if TYPE_CHECKING:
    from ylang.settings import Settings

logger = logging.getLogger(__name__)

_CONTENT_CAPTURE_LEVELS = frozenset({"redacted", "full_local"})


class UsageSpanSink(Protocol):
    """Destination for one completion's telemetry attributes."""

    def emit(self, attributes: dict[str, str | int | float | bool]) -> None:
        """Export one span's attributes. Must not raise to callers."""


@dataclass
class NoOpUsageSpanSink:
    """Drop telemetry when OTLP is disabled or unavailable."""

    def emit(self, attributes: dict[str, str | int | float | bool]) -> None:
        _ = attributes


@dataclass
class RecordingUsageSpanSink:
    """In-memory sink for tests; never opens a network connection."""

    spans: list[dict[str, str | int | float | bool]] = field(default_factory=list)

    def emit(self, attributes: dict[str, str | int | float | bool]) -> None:
        self.spans.append(dict(attributes))


def completion_span_attributes(
    *,
    surface: str,
    activity: str,
    model_used: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost: float,
    latency_ms: int,
    success: bool,
    trace_id: str,
    session_id: str | None,
    workspace: str | None,
    selected_route: str | None,
    resolution: ModelResolution,
    export_content: bool,
    capture_level: str,
    prompt_body_redacted: str | None,
    tool_calls: list[dict[str, Any]],
) -> dict[str, str | int | float | bool]:
    """Build OTLP attributes for one completion. Prompt bodies off by default."""
    attributes: dict[str, str | int | float | bool] = {
        "ylang.surface": surface,
        "ylang.activity": activity,
        "ylang.semantic_route": resolution.semantic_route,
        "ylang.resolved_route": resolution.resolved_route,
        "ylang.model": resolution.resolved_model or model_used,
        "ylang.resolution_reason": resolution.resolution_reason,
        "ylang.attempt_index": resolution.attempt_index,
        "ylang.prompt_tokens": prompt_tokens,
        "ylang.completion_tokens": completion_tokens,
        "ylang.cost": cost,
        "ylang.latency_ms": latency_ms,
        "ylang.status": "success" if success else "error",
        "ylang.trace_id": trace_id,
    }
    if resolution.resolved_provider:
        attributes["ylang.provider"] = resolution.resolved_provider
    if resolution.requested_model:
        attributes["ylang.requested_model"] = resolution.requested_model
    if resolution.requested_alias:
        attributes["ylang.requested_alias"] = resolution.requested_alias
    if resolution.alias_source:
        attributes["ylang.alias_source"] = resolution.alias_source
    if selected_route:
        attributes["ylang.selected_route"] = selected_route
    if session_id:
        attributes["ylang.session_id"] = session_id
    if workspace:
        attributes["ylang.workspace"] = workspace
    tool_names = _tool_names(tool_calls)
    if tool_names:
        attributes["ylang.tool_names"] = tool_names
    if (
        export_content
        and capture_level in _CONTENT_CAPTURE_LEVELS
        and prompt_body_redacted
    ):
        attributes["ylang.prompt_body_redacted"] = redact_secrets(prompt_body_redacted)
    return attributes


def _tool_names(tool_calls: list[dict[str, Any]]) -> str:
    names: list[str] = []
    for call in tool_calls:
        function = call.get("function")
        name = None
        if isinstance(function, dict):
            name = function.get("name")
        elif "name" in call:
            name = call.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return ",".join(names)


def exporter_from_settings(settings: Settings) -> UsageSpanSink:
    """Return a no-op sink unless OTLP is explicitly enabled."""
    if not settings.otel_enabled:
        return NoOpUsageSpanSink()
    endpoint = (settings.otel_endpoint or "").strip()
    if not endpoint:
        logger.warning(
            "YLANG_OTEL_ENABLED is set but YLANG_OTEL_ENDPOINT is empty; OTLP export disabled"
        )
        return NoOpUsageSpanSink()
    sink = _try_build_otlp_sink(endpoint)
    if sink is None:
        return NoOpUsageSpanSink()
    return sink


def _try_build_otlp_sink(endpoint: str) -> UsageSpanSink | None:
    try:
        otlp_http = importlib.import_module(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter"
        )
        resources = importlib.import_module("opentelemetry.sdk.resources")
        sdk_trace = importlib.import_module("opentelemetry.sdk.trace")
        sdk_export = importlib.import_module("opentelemetry.sdk.trace.export")
    except ImportError:
        logger.warning(
            "YLANG_OTEL_ENABLED is set but OpenTelemetry is not installed; "
            "pip install 'ylang[otel]'"
        )
        return None
    try:
        processor_cls = sdk_export.BatchSpanProcessor
        try:
            exporter = otlp_http.OTLPSpanExporter(endpoint=endpoint, timeout=5)
        except TypeError:
            exporter = otlp_http.OTLPSpanExporter(endpoint=endpoint)
        return OtlpUsageSpanSink(
            endpoint=endpoint,
            resource=resources.Resource.create({"service.name": "ylang"}),
            exporter=exporter,
            provider_cls=sdk_trace.TracerProvider,
            processor_cls=processor_cls,
        )
    except Exception:
        logger.warning("Failed to initialize OTLP exporter; continuing without it", exc_info=True)
        return None


class OtlpUsageSpanSink:
    """OTLP HTTP exporter. Export is batched off the request path.

    Failures are logged and swallowed. A slow collector cannot fail an LLM call.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        resource: Any,
        exporter: Any,
        provider_cls: Any,
        processor_cls: Any,
    ) -> None:
        _ = endpoint
        self._provider = provider_cls(resource=resource)
        self._provider.add_span_processor(
            processor_cls(
                exporter,
                max_queue_size=2048,
                schedule_delay_millis=1000,
                export_timeout_millis=5000,
                max_export_batch_size=512,
            )
        )
        self._tracer = self._provider.get_tracer("ylang")

    def emit(self, attributes: dict[str, str | int | float | bool]) -> None:
        try:
            with self._tracer.start_as_current_span("ylang.completion") as span:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
                status = attributes.get("ylang.status")
                if status == "error":
                    otel_trace = importlib.import_module("opentelemetry.trace")
                    span.set_status(
                        otel_trace.Status(otel_trace.StatusCode.ERROR)
                    )
        except Exception:
            logger.warning("OTLP span export failed", exc_info=True)
