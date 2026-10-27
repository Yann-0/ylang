"""Explicit trusted offline adapters for Engine financial integration tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ylang.core.bounded_completion import (
    BoundedResponse, PreparedAttempt, canonical_json, configuration, digest,
)
from ylang.core.types import Message
from ylang.usage.hard_budget import CostQuote, HardBudgetStore
from ylang.usage.store import UsageStore


class OfflineAdapter:
    """One synthetic attempt per execute call, with explicit queued outcomes."""

    synthetic = True
    adapter_id = "synthetic:offline-v1"

    def __init__(self, *outcomes: BoundedResponse | BaseException, bound: int = 20_000_000) -> None:
        """Retain exact dispatches and immutable request snapshots for assertions."""
        self.outcomes = list(outcomes)
        self.bound = bound
        self.calls: list[PreparedAttempt] = []

    def prepare(self, model: str, messages: list[Message], *, max_output_tokens: int) -> PreparedAttempt:
        """Freeze a text-only synthetic request with a conservative fixture bound."""
        wire = canonical_json({"model": model, "messages": messages,
                               "max_output_tokens": max_output_tokens})
        config = configuration(max_output_tokens)
        quote = CostQuote(model=model, adapter_id=self.adapter_id, account_id="offline-account",
                          pricing_version="fixture-v1", expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                          request_hash=digest(wire), config_hash=digest(config),
                          max_cost_nanos=self.bound, input_token_bound=10_000,
                          max_output_tokens=max_output_tokens)
        return PreparedAttempt(wire, config, quote)

    def execute(self, prepared: PreparedAttempt) -> BoundedResponse:
        """Consume exactly one fixture outcome without any provider transport."""
        self.calls.append(prepared)
        outcome = self.outcomes.pop(0) if self.outcomes else response(model=prepared.quote.model)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def response(content: str = "hello", *, model: str = "openai/gpt-4o", charge: int = 10_000_000) -> BoundedResponse:
    """Build complete trusted fixture charge evidence."""
    return BoundedResponse(content, model, 10, 25, charge,
                           {"source": "synthetic-fixture", "request_id": "fixture-response", "charge_nanos": charge})


def initialize_budget(store: UsageStore, *, limit: int = 1_000_000_000) -> None:
    """Explicitly acknowledge clean private fixture accounting before paid tests."""
    with HardBudgetStore.open(store.database_path) as ledger:
        ledger.initialize_policy(limit_nanos=limit, opening_evidence="new private synthetic database")


class MockedCompletionAdapter(OfflineAdapter):
    """Opt-in bridge for old tests that explicitly patch LiteLLM completion.

    The caller must provide the MagicMock transport itself: this fixture cannot
    accidentally resolve a real provider function. Known failure charge is an
    explicit fixture fact, never a production error-name/billing heuristic.
    """

    def __init__(self, transport: object, *, known_failure_charge_nanos: int | None = None) -> None:
        """Require an actual unittest mock before admitting a legacy test transport."""
        from unittest.mock import Mock

        super().__init__()
        if not isinstance(transport, Mock):
            raise TypeError("synthetic legacy transport must be an explicit Mock")
        self.transport = transport
        self.known_failure_charge_nanos = known_failure_charge_nanos

    def execute(self, prepared: PreparedAttempt) -> BoundedResponse:
        """Exercise legacy response parsing with the exact frozen synthetic request."""
        import json
        from decimal import Decimal, ROUND_CEILING
        from ylang.core.bounded_completion import BoundedFailure
        from ylang.core.engine import _parse_response

        self.calls.append(prepared)
        wire = json.loads(prepared.wire_json)
        try:
            reply = self.transport(model=wire["model"], messages=wire["messages"],
                                   max_tokens=wire["max_output_tokens"], caching=False,
                                   num_retries=0)
        except Exception as exc:
            if self.known_failure_charge_nanos is None:
                raise
            raise BoundedFailure(str(exc), charge_nanos=self.known_failure_charge_nanos,
                                 evidence={"source": "explicit mock terminal fixture"},
                                 retry_allowed=True) from exc
        content, model, prompt, completion, cost, tools = _parse_response(reply, default_model=wire["model"])
        if tools:
            raise ValueError("synthetic bounded tests support text only; use local fixture for tool transport")
        charge = int((Decimal(str(cost)) * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))
        return BoundedResponse(content, model, prompt, completion, charge,
                               {"source": "explicit mock terminal fixture", "charge_nanos": charge})
