"""Core request/response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

# Routing bucket for model selection and usage activity normalization.
Activity = Literal["code", "search", "reason", "improve", "other"]


class Message(TypedDict):
    """LiteLLM-compatible chat message."""

    role: Literal["system", "user", "assistant"]
    content: str


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
