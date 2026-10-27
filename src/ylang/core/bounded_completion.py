"""Immutable requests and accounting evidence for bounded completion attempts.

Synthetic adapters are trusted offline seams. Native adapters are a closed,
explicitly enabled registry; settings and request bodies cannot supply plugins.
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


def configuration(max_output_tokens: int, response_format: dict[str, str] | None = None) -> str:
    """Pin finite generation limits, object output, and the absence of hidden attempts."""
    if type(max_output_tokens) is not int or not 0 < max_output_tokens <= 2**31 - 1:
        raise BudgetRefused("explicit positive output token limit required")
    data: dict[str, object] = {"cache": False, "retries": 0, "fallbacks": False,
                               "max_output_tokens": max_output_tokens}
    if response_format is not None:
        if response_format != {"type": "json_object"}:
            raise BudgetRefused("only JSON-object response format is bounded")
        data["response_format"] = {"type": "json_object"}
    return canonical_json(data)


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
    """Exact normalized request, optional native wire bytes, and its funding quote."""

    wire_json: str
    config_json: str
    quote: CostQuote
    simulated: bool = True
    provider_wire_json: str | None = None

    def validate(self) -> None:
        """Check canonical identity before the adapter verifies its native contract."""
        native = self.quote.adapter_id.startswith("provider:")
        if type(self.simulated) is not bool:
            raise BudgetRefused("invalid simulation identity")
        if not native and (self.simulated is not True or not self.quote.adapter_id.startswith("synthetic:")):
            raise BudgetRefused("unregistered bounded adapter identity")
        self.quote.validate(datetime.now(timezone.utc))
        try:
            wire = json.loads(self.wire_json)
            required = {"model", "messages", "max_output_tokens"}
            if not required <= set(wire) or set(wire) - required - {"response_format"}:
                raise BudgetRefused("unsupported wire request fields")
            if not native and set(wire) != required:
                raise BudgetRefused("synthetic request format cannot authorize native features")
            if canonical_json(wire) != self.wire_json or wire["model"] != self.quote.model:
                raise BudgetRefused("quoted model differs from canonical wire model")
            if type(wire["max_output_tokens"]) is not int or wire["max_output_tokens"] != self.quote.max_output_tokens:
                raise BudgetRefused("quoted output limit differs from wire limit")
            text_messages(wire["messages"])
            if self.config_json != configuration(self.quote.max_output_tokens, wire.get("response_format")):
                raise BudgetRefused("unsupported generation configuration")
            body = self.wire_json
            if native:
                if not isinstance(self.provider_wire_json, str):
                    raise BudgetRefused("native request bytes are missing")
                if canonical_json(json.loads(self.provider_wire_json)) != self.provider_wire_json:
                    raise BudgetRefused("native request is not canonical")
                body = self.provider_wire_json
            elif self.provider_wire_json is not None:
                raise BudgetRefused("synthetic request cannot supply a native body")
            if digest(body) != self.quote.request_hash or digest(self.config_json) != self.quote.config_hash:
                raise BudgetRefused("prepared request/configuration digest mismatch")
        except (TypeError, ValueError, KeyError) as exc:
            raise BudgetRefused("invalid prepared request") from exc

    def messages(self) -> list[Message]:
        """Return a fresh message copy without changing the reserved native bytes."""
        return json.loads(self.wire_json)["messages"]


@dataclass(frozen=True)
class BoundedResponse:
    """Terminal usage evidence; native costs are documented tariff upper liabilities."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    charge_nanos: int
    evidence: dict[str, object]
    validation_error: str | None = None

    def validate(self, prepared: PreparedAttempt) -> None:
        """Reject invalid accounting before handling a known-charge output failure."""
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
        if self.validation_error is not None:
            if not isinstance(self.validation_error, str) or not self.validation_error:
                raise BudgetRefused("invalid terminal validation failure")
            raise BoundedFailure(self.validation_error, charge_nanos=self.charge_nanos,
                                 evidence=self.evidence, retry_allowed=False)

    def observation(self) -> dict[str, object]:
        """Retain actual identity independently of validity without persisting raw output."""
        return {
            "model": self.model if isinstance(self.model, str) else None,
            "prompt_tokens": self.prompt_tokens if type(self.prompt_tokens) is int and self.prompt_tokens >= 0 else None,
            "completion_tokens": self.completion_tokens if type(self.completion_tokens) is int and self.completion_tokens >= 0 else None,
            "reported_charge_nanos": self.charge_nanos if type(self.charge_nanos) is int and self.charge_nanos >= 0 else None,
            "output_hash": digest(self.content) if isinstance(self.content, str) else None,
            "cost_is_upper_bound": self.evidence.get("cost_is_upper_bound") is True,
        }


class ProviderContractViolation(BudgetRefused):
    """Stop admission after native model, usage, or protocol evidence violates its bound."""

    def __init__(self, message: str, *, observed_response: BoundedResponse | None = None) -> None:
        """Preserve any captured output while treating its billability as uncertain."""
        super().__init__(message)
        self.observed_response = observed_response


class BoundedEvidenceError(RuntimeError):
    """Carry a captured completion through a separate accounting-write failure."""

    def __init__(self, completion: CompletionResult, accounting_error: Exception) -> None:
        """Preserve transport identity while evaluation saves partial evidence and aborts."""
        super().__init__("accounting write failed: " + str(accounting_error))
        self.completion = completion
        self.accounting_error = str(accounting_error)


class BoundedFailure(Exception):
    """Report a failed attempt with explicit trusted terminal charge evidence."""

    def __init__(self, message: str, *, charge_nanos: int,
                 evidence: dict[str, object], retry_allowed: bool = False) -> None:
        """Require terminal evidence before considering any follow-up attempt."""
        super().__init__(message)
        if type(charge_nanos) is not int or not 0 <= charge_nanos <= 2**63 - 1 or not evidence:
            raise BudgetRefused("invalid failure charge evidence")
        canonical_json(evidence)
        self.charge_nanos = charge_nanos
        self.evidence = evidence
        self.retry_allowed = retry_allowed is True


class SyntheticBoundedAdapter(Protocol):
    """Trusted adapter interface; the historical name remains an import compatibility alias."""

    synthetic: bool
    adapter_id: str

    def prepare(self, model: str, messages: list[Message], *, max_output_tokens: int) -> PreparedAttempt:
        """Prepare one immutable, fully bounded request."""
        ...

    def execute(self, prepared: PreparedAttempt) -> BoundedResponse:
        """Perform exactly one attempt without hidden retry or fallback."""
        ...


def is_known_local_model(model: str) -> bool:
    """Only explicitly local Ollama namespaces retain the legacy transport path."""
    return (model.startswith(("ollama/", "ollama_chat/"))
            and bool(model.split("/", 1)[1]) and "cloud" not in model.lower())
