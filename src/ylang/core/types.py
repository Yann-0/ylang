"""Core request/response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

# Routing bucket for model selection and usage activity normalization.
Activity = Literal["code", "search", "reason", "improve", "other"]

# Machine-readable reason for why a concrete provider/model was chosen.
ResolutionReason = Literal[
    "explicit_model",
    "compatibility_alias",
    "activity_default",
    "operator_override",
    "quality_preference",
    "cost_tiebreak",
    "provider_unavailable",
    "provider_cooldown",
    "budget_fallback",
    "local_fallback",
]

RESOLUTION_REASONS: frozenset[str] = frozenset(
    {
        "explicit_model",
        "compatibility_alias",
        "activity_default",
        "operator_override",
        "quality_preference",
        "cost_tiebreak",
        "provider_unavailable",
        "provider_cooldown",
        "budget_fallback",
        "local_fallback",
    }
)


class Message(TypedDict):
    """LiteLLM-compatible chat message."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ExplicitModelLookup:
    """Classification of a client-supplied model string.

    ``reason`` is ``activity_default`` when the string is a sentinel (``auto``)
    or unrecognized and activity routing should choose. Compatibility aliases
    are **not** identity: ``requested_alias`` is the legacy/client identifier
    and ``resolved`` is the currently supported LiteLLM route.
    """

    requested: str
    resolved: str | None
    requested_alias: str | None
    reason: Literal["explicit_model", "compatibility_alias", "activity_default"]
    alias_source: str | None = None


@dataclass(frozen=True, slots=True)
class ModelResolution:
    """Explainable mapping from semantic intent to a concrete LiteLLM route.

    Concrete ``resolved_model`` values are policy implementation choices.
    ``semantic_route`` stays stable when vendor models are swapped in config.
    """

    requested_model: str | None
    requested_alias: str | None
    semantic_route: str
    resolved_route: str
    resolved_provider: str | None
    resolved_model: str
    resolution_reason: ResolutionReason
    attempt_index: int = 0
    alias_source: str | None = None

    def as_trace_fields(self) -> dict[str, str | int | None]:
        """Return JSON-safe fields for ``routing_reason_json`` and telemetry."""
        fields: dict[str, str | int | None] = {
            "requested_model": self.requested_model,
            "requested_alias": self.requested_alias,
            "semantic_route": self.semantic_route,
            "resolved_route": self.resolved_route,
            "selected_provider": self.resolved_provider,
            "selected_model": self.resolved_model,
            "resolution_reason": self.resolution_reason,
            "attempt_index": self.attempt_index,
        }
        if self.alias_source:
            fields["alias_source"] = self.alias_source
        return fields


def model_provider_prefix(model: str) -> str | None:
    """Return the LiteLLM provider prefix of ``model``, or None if unprefixed."""
    if "/" not in model:
        return None
    prefix = model.split("/", 1)[0].strip().lower()
    return prefix or None


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """Outcome of a single core completion call."""

    content: str
    model_used: str
    prompt_tokens: int
    cost: float
    latency_ms: int
    success: bool
    completion_tokens: int = 0
    error: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """One streamed delta from a core completion (content, tool_calls, or usage)."""

    content: str = ""
    tool_calls_delta: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True, slots=True)
class StreamCompletionError(Exception):
    """Stream failed; usage was already logged by ``Engine.complete_stream``."""

    message: str
    model_used: str

    def __str__(self) -> str:
        return self.message
