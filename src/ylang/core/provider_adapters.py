"""Pinned native text providers with conservative tariff liability accounting.

Amounts are standard-tariff upper liabilities, never asserted invoice amounts.
No provider is reachable unless the caller explicitly enables the live transport.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from ylang.core.bounded_completion import (
    BoundedResponse, PreparedAttempt, ProviderContractViolation,
    canonical_json, configuration, digest, text_messages,
)
from ylang.core.provider_transport import (
    ALLOWED_ENDPOINTS, DirectHTTPSProviderTransport, HTTPReply as HTTPReply,
    ProviderTransport, ProviderTransportError,
)
from ylang.core.types import Message
from ylang.usage.hard_budget import BudgetRefused, CostQuote, checked_nanos

if TYPE_CHECKING:
    from ylang.settings import Settings

TARIFF_EXPIRY = datetime(2026, 11, 26, tzinfo=timezone.utc)
QUOTE_TTL_SECONDS = 120
MAX_REQUEST_BYTES = 512 * 1024
MAX_MESSAGES = 128
JSON_INSTRUCTION = "Return exactly one valid JSON object. Do not use Markdown fences or any surrounding text."
PRICING_VERSION = "2026-10-27-standard-tariff-upper-v2-geography"


@dataclass(frozen=True)
class ProviderProfile:
    """One reviewed model revision and its published conservative token tariffs."""
    provider: str
    pinned_id: str
    aliases: tuple[str, ...]
    input_bound: int
    max_output: int
    input_base_nanos_per_token: int
    input_ceiling_nanos_per_token: int
    output_nanos_per_token: int

    @property
    def model(self) -> str:
        """Return the canonical identity bound into quotes and response evidence."""
        return self.provider + "/" + self.pinned_id


PROFILES = {
    "anthropic/claude-sonnet-4-6": ProviderProfile(
        "anthropic", "claude-sonnet-4-6", ("anthropic/claude-sonnet-4-6", "anthropic/claude-3-5-sonnet-latest"),
        # Include cache-write maximum and US inference's 1.1x surcharge without changing workspace geo.
        1048576, 128000, 3000, 6600, 16500),
    "anthropic/claude-haiku-4-5-20251001": ProviderProfile(
        "anthropic", "claude-haiku-4-5-20251001", ("anthropic/claude-haiku-4-5", "anthropic/claude-haiku-4-5-20251001"),
        200000, 64000, 1000, 2000, 5000),
    "openai/gpt-4o-2024-08-06": ProviderProfile(
        "openai", "gpt-4o-2024-08-06", ("openai/gpt-4o", "openai/gpt-4o-2024-08-06"),
        128000, 16384, 2500, 2500, 10000),
    "mistral/mistral-small-2603": ProviderProfile(
        "mistral", "mistral-small-2603", ("mistral/mistral-small-latest", "mistral/mistral-small-2603"),
        262144, 16384, 150, 150, 600),
}


def _now(clock: Callable[[], datetime]) -> datetime:
    """Reject ambiguous clocks rather than extending tariff validity."""
    value = clock()
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise BudgetRefused("provider clock must be aware UTC")
    if value >= TARIFF_EXPIRY:
        raise BudgetRefused("reviewed provider tariffs expired")
    return value


def _integer(value: object, name: str) -> int:
    """Require explicit nonnegative integral native usage rather than estimating it."""
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("missing or malformed provider " + name)
    return value


def _object_json(raw: str) -> dict[str, Any]:
    """Reject duplicate keys and nonfinite numbers in native and generated JSON."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        """Prevent duplicate accounting or model fields from shadowing each other."""
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_: str) -> None:
        """Exclude JavaScript-only nonfinite numeric constants."""
        raise ValueError("nonfinite JSON number")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


class NativeProviderAdapter:
    """Exact reviewed adapter class; authentication never enters wire/config evidence."""
    synthetic = False

    def __init__(self, profile: ProviderProfile | str, api_key: str, *,
                 transport: ProviderTransport | None = None, allow_network: bool = False,
                 clock: Callable[[], datetime] | None = None) -> None:
        """Bind one immutable reviewed profile, credential identity and transport gate."""
        if isinstance(profile, str):
            if profile not in PROFILES:
                raise BudgetRefused("unsupported bounded provider profile")
            profile = PROFILES[profile]
        if profile not in PROFILES.values():
            raise BudgetRefused("unreviewed provider profile")
        if not isinstance(api_key, str) or not api_key or not api_key.isascii() or any(not 33 <= ord(c) <= 126 for c in api_key):
            raise BudgetRefused("provider credential is missing or malformed")
        self.profile = profile
        self._api_key = api_key
        self._transport = transport if transport is not None else DirectHTTPSProviderTransport()
        if type(self._transport.live) is not bool:
            raise BudgetRefused("transport must explicitly declare whether it is live")
        self._allow_network = allow_network is True
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.adapter_id = "provider:" + profile.model + ":native-v1"
        self.account_id = "credential-sha256:" + hashlib.sha256(api_key.encode()).hexdigest()

    def resolve_model(self, requested: str) -> str:
        """Resolve only reviewed aliases to the pinned native model revision."""
        if requested not in self.profile.aliases:
            raise BudgetRefused("requested model has no reviewed pinned profile")
        return self.profile.model

    def _native_body(self, model: str, messages: list[Message], max_output_tokens: int,
                     response_format: dict[str, str] | None) -> str:
        """Reconstruct the entire native billable body with only supported features."""
        text_messages(messages)
        if len(messages) > MAX_MESSAGES:
            raise BudgetRefused("too many provider messages")
        native_messages = json.loads(canonical_json(messages))
        if response_format is not None:
            configuration(max_output_tokens, response_format)
            native_messages.insert(0, {"role": "system", "content": JSON_INSTRUCTION})
        if self.profile.provider == "anthropic":
            system: list[str] = []
            conversational: list[dict[str, str]] = []
            for message in native_messages:
                if message["role"] == "system":
                    if conversational:
                        raise BudgetRefused("Anthropic system messages must precede conversation")
                    system.append(message["content"])
                else:
                    conversational.append(message)
            if not conversational or conversational[-1]["role"] != "user":
                raise BudgetRefused("Anthropic requests must end with a user message")
            body: dict[str, Any] = {"model": self.profile.pinned_id,
                                    "messages": conversational,
                                    "max_tokens": max_output_tokens,
                                    "stream": False, "thinking": {"type": "disabled"},
                                    "service_tier": "standard_only"}
            if system:
                body["system"] = "\n\n".join(system)
        else:
            body = {"model": self.profile.pinned_id, "messages": native_messages,
                    "n": 1, "stream": False}
            if self.profile.provider == "openai":
                body.update(max_completion_tokens=max_output_tokens, store=False, service_tier="default")
            else:
                body.update(max_tokens=max_output_tokens, reasoning_effort="none", service_tier="standard_only")
            if response_format is not None:
                body["response_format"] = {"type": "json_object"}
        serialized = canonical_json(body)
        if len(serialized.encode()) > MAX_REQUEST_BYTES:
            raise BudgetRefused("provider request exceeds supported byte bound")
        return serialized

    def prepare(self, model: str, messages: list[Message], *, max_output_tokens: int,
                response_format: dict[str, str] | None = None) -> PreparedAttempt:
        """Freeze exact native bytes and reserve full-context conservative liability."""
        if self._transport.live and not self._allow_network:
            raise BudgetRefused("live bounded provider transport is disabled")
        now = _now(self._clock)
        canonical_model = self.resolve_model(model)
        config = configuration(max_output_tokens, response_format)
        if max_output_tokens > self.profile.max_output:
            raise BudgetRefused("output ceiling exceeds reviewed model capability")
        normalized: dict[str, Any] = {"model": canonical_model,
                                      "messages": json.loads(text_messages(messages)),
                                      "max_output_tokens": max_output_tokens}
        if response_format is not None:
            normalized["response_format"] = {"type": "json_object"}
        native = self._native_body(canonical_model, messages, max_output_tokens, response_format)
        quote = CostQuote(
            model=canonical_model, adapter_id=self.adapter_id, account_id=self.account_id,
            pricing_version=PRICING_VERSION,
            expires_at=min(now + timedelta(seconds=QUOTE_TTL_SECONDS), TARIFF_EXPIRY),
            request_hash=digest(native), config_hash=digest(config),
            max_cost_nanos=checked_nanos(self.profile.input_bound * self.profile.input_ceiling_nanos_per_token
                                          + max_output_tokens * self.profile.output_nanos_per_token),
            input_token_bound=self.profile.input_bound, max_output_tokens=max_output_tokens,
        )
        prepared = PreparedAttempt(canonical_json(normalized), config, quote,
                                   simulated=not self._transport.live, provider_wire_json=native)
        self.validate_prepared(prepared)
        return prepared

    def validate_prepared(self, prepared: PreparedAttempt) -> None:
        """Bind normalized messages/configuration, native bytes, tariffs and credential identity."""
        if self._transport.live and not self._allow_network:
            raise BudgetRefused("live bounded provider transport is disabled")
        now = _now(self._clock)
        quote = prepared.quote
        quote.validate(now)
        credential_id = "credential-sha256:" + hashlib.sha256(self._api_key.encode()).hexdigest()
        if (self.profile not in PROFILES.values() or self.account_id != credential_id
                or self.adapter_id != "provider:" + self.profile.model + ":native-v1"):
            raise BudgetRefused("provider identity changed after construction")
        try:
            wire = _object_json(prepared.wire_json)
            if set(wire) not in ({"model", "messages", "max_output_tokens"},
                                  {"model", "messages", "max_output_tokens", "response_format"}):
                raise ValueError("unsupported normalized provider fields")
            if canonical_json(wire) != prepared.wire_json:
                raise ValueError("noncanonical normalized provider request")
            if wire["model"] != self.profile.model or self.resolve_model(wire["model"]) != quote.model:
                raise ValueError("wrong pinned provider model")
            output = wire["max_output_tokens"]
            config = configuration(output, wire.get("response_format"))
            native = self._native_body(wire["model"], wire["messages"], output, wire.get("response_format"))
            maximum = checked_nanos(self.profile.input_bound * self.profile.input_ceiling_nanos_per_token
                                    + output * self.profile.output_nanos_per_token)
            if (type(output) is not int or output > self.profile.max_output or output != quote.max_output_tokens
                    or prepared.config_json != config or quote.config_hash != digest(config)
                    or prepared.provider_wire_json != native or quote.request_hash != digest(native)
                    or quote.adapter_id != self.adapter_id or quote.account_id != self.account_id
                    or quote.pricing_version != PRICING_VERSION or quote.max_cost_nanos != maximum
                    or quote.input_token_bound != self.profile.input_bound
                    or quote.expires_at > min(now + timedelta(seconds=QUOTE_TTL_SECONDS), TARIFF_EXPIRY)
                    or prepared.simulated is not (not self._transport.live)):
                raise ValueError("prepared provider contract mismatch")
        except (TypeError, ValueError, KeyError) as exc:
            raise BudgetRefused("invalid prepared native provider request") from exc

    def _headers(self) -> dict[str, str]:
        """Build fixed native authentication headers without recording their values."""
        headers = {"content-type": "application/json", "accept": "application/json"}
        if self.profile.provider == "anthropic":
            headers.update({"x-api-key": self._api_key, "anthropic-version": "2023-06-01"})
        else:
            headers["authorization"] = "Bearer " + self._api_key
        return headers

    def _content(self, data: dict[str, Any]) -> str:
        """Extract observed text conservatively before validating financial metadata."""
        if self.profile.provider == "anthropic":
            blocks = data.get("content")
            if isinstance(blocks, list):
                return "".join(b.get("text", "") for b in blocks
                               if isinstance(b, dict) and isinstance(b.get("text"), str))
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
        return ""

    def _usage(self, data: dict[str, Any]) -> tuple[int, int]:
        """Count all native input/output counters, including Anthropic cache input."""
        usage = data.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("native usage is missing")
        if self.profile.provider == "anthropic":
            prompt = _integer(usage.get("input_tokens"), "input_tokens")
            completion = _integer(usage.get("output_tokens"), "output_tokens")
            creation = _integer(usage.get("cache_creation_input_tokens", 0), "cache creation tokens")
            read = _integer(usage.get("cache_read_input_tokens", 0), "cache read tokens")
            prompt += creation + read
            details = usage.get("cache_creation")
            if details is not None:
                if not isinstance(details, dict) or sum(_integer(v, "cache creation detail") for v in details.values()) != creation:
                    raise ValueError("inconsistent cache creation usage")
            tools = usage.get("server_tool_use", {})
            if not isinstance(tools, dict) or any(_integer(v, "server tool usage") != 0 for v in tools.values()):
                raise ValueError("unsupported server-side tool billing")
            if usage.get("service_tier", "standard") != "standard":
                raise ValueError("unsupported provider service tier")
            if self.profile.pinned_id == "claude-sonnet-4-6" and usage.get("inference_geo", "global") not in {"global", "us"}:
                raise ValueError("unsupported provider inference geography")
        else:
            prompt = _integer(usage.get("prompt_tokens"), "prompt_tokens")
            completion = _integer(usage.get("completion_tokens"), "completion_tokens")
            if _integer(usage.get("total_tokens"), "total_tokens") != prompt + completion:
                raise ValueError("inconsistent native token totals")
            for key in ("prompt_tokens_details", "completion_tokens_details"):
                details = usage.get(key)
                if details is not None:
                    if not isinstance(details, dict):
                        raise ValueError("malformed token details")
                    for name, value in details.items():
                        count = _integer(value, "token detail")
                        if name == "cached_tokens":
                            if count > prompt:
                                raise ValueError("cache usage exceeds prompt total")
                        elif count != 0:
                            raise ValueError("unsupported nontext/reasoning/prediction usage")
            allowed_tiers = {"default"} if self.profile.provider == "openai" else {"default", "standard", "standard_only"}
            if data.get("service_tier", "default") not in allowed_tiers:
                raise ValueError("unsupported provider service tier")
            for key in ("prompt_audio_seconds", "completion_audio_seconds"):
                if key in usage and usage[key] != 0:
                    raise ValueError("unsupported audio billing")
        return prompt, completion

    def execute(self, prepared: PreparedAttempt) -> BoundedResponse:
        """Perform one native request; statuses and malformed accounting stay uncertain."""
        self.validate_prepared(prepared)
        host = {"openai": "api.openai.com", "anthropic": "api.anthropic.com",
                "mistral": "api.mistral.ai"}[self.profile.provider]
        native = prepared.provider_wire_json
        if native is None:
            raise BudgetRefused("missing native provider request")
        reply = self._transport.post(host, ALLOWED_ENDPOINTS[host], self._headers(), native.encode(), 30.0)
        if not 200 <= reply.status < 300:
            raise ProviderTransportError("provider returned HTTP " + str(reply.status))
        try:
            if len(reply.body) > 2 * 1024 * 1024:
                raise ValueError("response exceeds byte limit")
            data = _object_json(reply.body.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ProviderContractViolation("provider returned malformed native JSON") from exc
        content = self._content(data)
        actual_id = data.get("model")
        observed_model = self.profile.provider + "/" + actual_id if isinstance(actual_id, str) else ""
        observed = BoundedResponse(content, observed_model, -1, -1, -1,
                                   {"source": "native-provider", "response_hash": hashlib.sha256(reply.body).hexdigest()})
        try:
            prompt, completion = self._usage(data)
            observed = BoundedResponse(content, observed_model, prompt, completion, -1, observed.evidence)
            if actual_id != self.profile.pinned_id:
                raise ValueError("provider returned a different model revision")
            charge = checked_nanos(prompt * self.profile.input_ceiling_nanos_per_token
                                   + completion * self.profile.output_nanos_per_token)
            evidence: dict[str, object] = {
                "source": "native-provider", "provider": self.profile.provider,
                "response_id": data.get("id") if isinstance(data.get("id"), str) else None,
                "transport_request_id": reply.request_id, "actual_model": observed_model,
                "request_hash": prepared.quote.request_hash, "config_hash": prepared.quote.config_hash,
                "pricing_version": PRICING_VERSION, "cost_basis": "standard_tariff_upper_bound",
                "cost_is_upper_bound": True, "prompt_tokens": prompt, "completion_tokens": completion,
                "recognized_liability_nanos": charge, "response_hash": hashlib.sha256(reply.body).hexdigest(),
            }
            observed = BoundedResponse(content, observed_model, prompt, completion, charge, evidence)
            if (prompt > self.profile.input_bound or completion > prepared.quote.max_output_tokens):
                raise ValueError("provider exceeded reserved token ceilings")
            if not isinstance(data.get("id"), str) or not data["id"] or len(data["id"]) > 256:
                raise ValueError("native response identity is missing or malformed")
            if self.profile.provider == "anthropic":
                if data.get("type") != "message" or data.get("role") != "assistant":
                    raise ValueError("invalid Anthropic response envelope")
                if data.get("stop_reason") not in {"end_turn", "max_tokens", "stop_sequence", "refusal"}:
                    raise ValueError("unsupported Anthropic stop reason")
                blocks = data.get("content")
                if not isinstance(blocks, list) or any(not isinstance(b, dict) or b.get("type") != "text" or not isinstance(b.get("text"), str) for b in blocks):
                    raise ValueError("unsupported native Anthropic content block")
            else:
                choices = data.get("choices")
                if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                    raise ValueError("native response must contain exactly one choice")
                choice = choices[0]
                if type(choice.get("index")) is not int or choice["index"] != 0 or choice.get("finish_reason") not in {"stop", "length", "content_filter", "model_length"}:
                    raise ValueError("unsupported native choice identity or finish reason")
                message = choice.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    raise ValueError("invalid native assistant response")
                if not isinstance(message, dict) or message.get("tool_calls") or message.get("function_call"):
                    raise ValueError("unsupported native tool response")
                if message.get("content") is not None and not isinstance(message["content"], str):
                    raise ValueError("unsupported native multimodal response")
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderContractViolation(str(exc), observed_response=observed) from exc
        validation_error = None
        if not content:
            validation_error = "provider returned no text content"
        elif json.loads(prepared.wire_json).get("response_format") is not None:
            try:
                _object_json(content)
            except (ValueError, TypeError, RecursionError):
                validation_error = "provider output is not a valid JSON object"
        return BoundedResponse(content, observed_model, prompt, completion, charge, evidence,
                               validation_error=validation_error)


def build_provider_adapters(settings: Settings, *, transport: ProviderTransport | None = None,
                            clock: Callable[[], datetime] | None = None) -> dict[str, NativeProviderAdapter]:
    """Enable only explicitly configured reviewed profiles; never initialize financial policy."""
    if getattr(settings, "bounded_providers_enabled", False) is not True:
        return {}
    adapters: dict[str, NativeProviderAdapter] = {}
    for profile in PROFILES.values():
        key = getattr(settings.provider_keys, profile.provider, None)
        if not key:
            continue
        adapter = NativeProviderAdapter(profile, key, transport=transport, allow_network=True, clock=clock)
        for alias in profile.aliases:
            adapters[alias] = adapter
    return adapters
