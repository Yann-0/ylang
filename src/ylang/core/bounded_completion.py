"""Immutable, synthetic-only boundary for financially bounded attempts.

No production adapter is certified. Constructor injection is trusted Python code,
never a settings or request-payload extension point.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ylang.core.types import CompletionResult, Message
from ylang.usage.hard_budget import BudgetRefused, CostQuote


def canonical_json(value: object) -> str:
    """Freeze supported request data into deterministic JSON."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: str) -> str:
    """Hash the exact canonical wire/configuration bytes."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def configuration(max_output_tokens: int) -> str:
    """Require a finite explicit ceiling and prohibit hidden retries/cache/fallback."""
    if type(max_output_tokens) is not int or not 0 < max_output_tokens <= 2**31 - 1:
        raise BudgetRefused("explicit positive output token limit required")
    return canonical_json({"cache": False, "retries": 0, "fallbacks": False,
                           "max_output_tokens": max_output_tokens})


def text_messages(messages: list[Message]) -> str:
    """Admit text-only messages with no unsupported billable extensions."""
    if not messages:
        raise BudgetRefused("nonempty text messages required")
    for message in messages:
        if set(message) != {"role", "content"}:
            raise BudgetRefused("unsupported message fields")
        if message["role"] not in {"system", "user", "assistant"} or not isinstance(message["content"], str):
            raise BudgetRefused("only text system/user/assistant messages supported")
    return canonical_json(messages)


@dataclass(frozen=True)
class PreparedAttempt:
    """Exact frozen request and quote produced by a trusted synthetic adapter."""

    wire_json: str
    config_json: str
    quote: CostQuote
    simulated: bool = True

    def validate(self) -> None:
        """Revalidate the complete supported wire contract immediately before dispatch."""
        if self.simulated is not True or not self.quote.adapter_id.startswith("synthetic:"):
            raise BudgetRefused("no production bounded adapters certified")
        self.quote.validate(datetime.now(timezone.utc))
        try:
            wire = json.loads(self.wire_json)
            if set(wire) != {"model", "messages", "max_output_tokens"}:
                raise BudgetRefused("unsupported wire request fields")
            if canonical_json(wire) != self.wire_json:
                raise BudgetRefused("wire request is not canonical")
            if wire["model"] != self.quote.model:
                raise BudgetRefused("quoted model differs from wire model")
            if type(wire["max_output_tokens"]) is not int or wire["max_output_tokens"] != self.quote.max_output_tokens:
                raise BudgetRefused("quoted output limit differs from wire limit")
            text_messages(wire["messages"])
            if self.config_json != configuration(self.quote.max_output_tokens):
                raise BudgetRefused("unsupported generation configuration")
            if digest(self.wire_json) != self.quote.request_hash or digest(self.config_json) != self.quote.config_hash:
                raise BudgetRefused("prepared request/configuration digest mismatch")
        except (TypeError, ValueError, KeyError) as exc:
            raise BudgetRefused("invalid prepared request") from exc

    def messages(self) -> list[Message]:
        """Return a fresh message copy, preserving the immutable serialized request."""
        return json.loads(self.wire_json)["messages"]


@dataclass(frozen=True)
class BoundedResponse:
    """Trusted synthetic charge evidence, independent of caller-supplied costs."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    charge_nanos: int
    evidence: dict[str, object]

    def validate(self, prepared: PreparedAttempt) -> None:
        """Reject missing, mismatched, or unbounded response evidence."""
        for value in (self.prompt_tokens, self.completion_tokens, self.charge_nanos):
            if type(value) is not int or not 0 <= value <= 2**63 - 1:
                raise BudgetRefused("invalid trusted response accounting")
        if self.model != prepared.quote.model:
            raise BudgetRefused("response model differs from reserved model")
        if self.prompt_tokens > prepared.quote.input_token_bound or self.completion_tokens > prepared.quote.max_output_tokens:
            raise BudgetRefused("response tokens exceed certified bounds")
        if not isinstance(self.content, str) or not self.evidence:
            raise BudgetRefused("missing terminal response evidence")
        canonical_json(self.evidence)


    def observation(self) -> dict[str, object]:
        """Keep observed identity separate from validated identity without persisting raw output."""
        return {
            "model": self.model if isinstance(self.model, str) else None,
            "prompt_tokens": self.prompt_tokens if type(self.prompt_tokens) is int and self.prompt_tokens >= 0 else None,
            "completion_tokens": self.completion_tokens if type(self.completion_tokens) is int and self.completion_tokens >= 0 else None,
            "reported_charge_nanos": self.charge_nanos if type(self.charge_nanos) is int and self.charge_nanos >= 0 else None,
            "output_hash": digest(self.content) if isinstance(self.content, str) else None,
        }


class BoundedEvidenceError(RuntimeError):
    """Carry an already captured completion through a separate accounting-write failure."""

    def __init__(self, completion: CompletionResult, accounting_error: Exception) -> None:
        """Preserve transport result identity while the evaluator aborts and saves partial evidence."""
        super().__init__("accounting write failed: " + str(accounting_error))
        self.completion = completion
        self.accounting_error = str(accounting_error)


class BoundedFailure(Exception):
    """Trusted synthetic adapter reports a terminal failed attempt and its charge."""

    def __init__(self, message: str, *, charge_nanos: int,
                 evidence: dict[str, object], retry_allowed: bool = False) -> None:
        """Require explicit charge evidence before any retry can be considered."""
        super().__init__(message)
        if type(charge_nanos) is not int or not 0 <= charge_nanos <= 2**63 - 1 or not evidence:
            raise BudgetRefused("invalid failure charge evidence")
        canonical_json(evidence)
        self.charge_nanos = charge_nanos
        self.evidence = evidence
        self.retry_allowed = retry_allowed is True


class SyntheticBoundedAdapter(Protocol):
    """Trusted in-process offline test seam; no real transport is supplied."""

    synthetic: bool
    adapter_id: str

    def prepare(self, model: str, messages: list[Message], *, max_output_tokens: int) -> PreparedAttempt:
        """Prepare one immutable, fully bounded text request."""
        ...

    def execute(self, prepared: PreparedAttempt) -> BoundedResponse:
        """Perform exactly one synthetic attempt, with no cache/retry/fallback."""
        ...


def is_known_local_model(model: str) -> bool:
    """Only explicitly local Ollama namespaces retain the legacy transport path."""
    return (model.startswith(("ollama/", "ollama_chat/"))
            and bool(model.split("/", 1)[1]) and "cloud" not in model.lower())
