"""Optional observability export.

Ylang's local usage/trace store remains the default. OTLP is an optional
side channel, disabled unless explicitly enabled.
"""

from ylang.telemetry.export import (
    NoOpUsageSpanSink,
    RecordingUsageSpanSink,
    UsageSpanSink,
    completion_span_attributes,
    exporter_from_settings,
)

__all__ = [
    "NoOpUsageSpanSink",
    "RecordingUsageSpanSink",
    "UsageSpanSink",
    "completion_span_attributes",
    "exporter_from_settings",
]
