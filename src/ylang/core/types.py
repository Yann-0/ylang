"""Core request/response types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

Activity = Literal["code", "search", "reason", "other"]


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
    error: str | None = None
