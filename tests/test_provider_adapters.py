"""Private offline qualification of exact native provider bodies and accounting."""
from __future__ import annotations

import json
import socket
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from ylang.core.bounded_completion import ProviderContractViolation, canonical_json, digest
from ylang.core.provider_adapters import (
    JSON_INSTRUCTION, PROFILES, TARIFF_EXPIRY, NativeProviderAdapter, build_provider_adapters,
)
from ylang.core.provider_transport import (
    MAX_RESPONSE_BYTES, DirectHTTPSProviderTransport, HTTPReply, ProviderTransportError,
)
from ylang.settings import ProviderKeys, Settings
from ylang.usage.hard_budget import BudgetRefused

NOW = datetime(2026, 10, 27, 16, tzinfo=timezone.utc)
MESSAGES = [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "Hello"}]


class FixtureTransport:
    """Capture one request using fake credentials; this fixture never opens sockets."""
    live = False

    def __init__(self, reply: HTTPReply | Exception) -> None:
        """Store exactly one explicit offline outcome."""
        self.reply = reply
        self.calls: list[tuple] = []

    def post(self, host: str, path: str, headers: dict[str, str], body: bytes, timeout: float) -> HTTPReply:
        """Return fixture bytes once, without retries or external provider calls."""
        self.calls.append((host, path, headers, body, timeout))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def native_reply(profile_key: str, *, content: str = "hello", extra_usage: dict | None = None) -> dict:
    """Provide complete representative native envelope and accounting evidence."""
    profile = PROFILES[profile_key]
    if profile.provider == "anthropic":
        data = {"id": "msg-fixture", "type": "message", "role": "assistant", "model": profile.pinned_id,
                "content": [{"type": "text", "text": content}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5}}
    else:
        data = {"id": "chat-fixture", "model": profile.pinned_id,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    if extra_usage:
        data["usage"].update(extra_usage)
    return data


def adapter_for(key: str, data: dict | None = None, **kwargs: object) -> tuple[NativeProviderAdapter, FixtureTransport]:
    """Bind fixture transport and fixed reviewed clock to one pinned adapter."""
    transport = FixtureTransport(HTTPReply(200, canonical_json(data if data is not None else native_reply(key)).encode(), "request-fixture"))
    return NativeProviderAdapter(key, "fake-private-key", transport=transport,
                                 clock=lambda: NOW, **kwargs), transport


@pytest.mark.parametrize("key", PROFILES)
def test_profiles_reserve_published_full_context_and_bind_exact_body(key: str) -> None:
    adapter, transport = adapter_for(key)
    prepared = adapter.prepare(PROFILES[key].aliases[0], MESSAGES, max_output_tokens=512)
    profile = PROFILES[key]
    assert prepared.quote.model == key
    assert prepared.simulated is True and adapter.synthetic is False
    assert prepared.quote.input_token_bound == profile.input_bound
    assert prepared.quote.max_cost_nanos == profile.input_bound * profile.input_ceiling_nanos_per_token + 512 * profile.output_nanos_per_token
    assert prepared.quote.request_hash == digest(prepared.provider_wire_json or "")
    body = json.loads(prepared.provider_wire_json or "{}")
    assert body["model"] == profile.pinned_id and body["stream"] is False
    result = adapter.execute(prepared)
    assert result.model == key and result.content == "hello"
    assert result.charge_nanos == 10 * profile.input_ceiling_nanos_per_token + 5 * profile.output_nanos_per_token
    assert result.evidence["cost_basis"] == "standard_tariff_upper_bound"
    assert result.evidence["cost_is_upper_bound"] is True
    assert len(transport.calls) == 1 and transport.calls[0][3].decode() == prepared.provider_wire_json
    assert "fake-private-key" not in repr(adapter) + prepared.quote.to_json() + canonical_json(result.evidence)


@pytest.mark.parametrize("key", PROFILES)
def test_only_reviewed_aliases_resolve(key: str) -> None:
    adapter, _ = adapter_for(key)
    for alias in PROFILES[key].aliases:
        assert adapter.resolve_model(alias) == key
    with pytest.raises(BudgetRefused):
        adapter.resolve_model("openai/arbitrary-latest")


@pytest.mark.parametrize("key", PROFILES)
def test_json_object_body_instruction_and_valid_result(key: str) -> None:
    adapter, _ = adapter_for(key, native_reply(key, content='{"ok":true}'))
    prepared = adapter.prepare(key, MESSAGES, max_output_tokens=512, response_format={"type": "json_object"})
    assert json.loads(prepared.wire_json)["messages"] == MESSAGES
    native = json.loads(prepared.provider_wire_json or "{}")
    if PROFILES[key].provider == "anthropic":
        assert JSON_INSTRUCTION in native["system"]
        assert native["thinking"] == {"type": "disabled"}
    else:
        assert native["messages"][0]["content"] == JSON_INSTRUCTION
        assert native["response_format"] == {"type": "json_object"}
        assert native["n"] == 1
    assert adapter.execute(prepared).validation_error is None


@pytest.mark.parametrize("content", ["not JSON", "[]", "null", '{"n":NaN}', '{"a":1,"a":2}'])
def test_invalid_json_keeps_validated_charge_and_observed_content(content: str) -> None:
    key = "openai/gpt-4o-2024-08-06"
    adapter, _ = adapter_for(key, native_reply(key, content=content))
    prepared = adapter.prepare(key, MESSAGES, max_output_tokens=512, response_format={"type": "json_object"})
    result = adapter.execute(prepared)
    assert result.validation_error and result.content == content
    assert result.charge_nanos > 0 and result.model == key


@pytest.mark.parametrize("status", [302, 400, 401, 429, 500, 503])
def test_error_status_is_never_reported_free_or_retried(status: int) -> None:
    adapter, transport = adapter_for("openai/gpt-4o-2024-08-06")
    transport.reply = HTTPReply(status, b'{"error":"fixture"}')
    prepared = adapter.prepare(adapter.profile.model, MESSAGES, max_output_tokens=512)
    with pytest.raises(ProviderTransportError):
        adapter.execute(prepared)
    assert len(transport.calls) == 1


def test_ambiguous_timeout_is_never_retried() -> None:
    adapter, transport = adapter_for("openai/gpt-4o-2024-08-06")
    transport.reply = TimeoutError("offline injected disconnect")
    prepared = adapter.prepare(adapter.profile.model, MESSAGES, max_output_tokens=512)
    with pytest.raises(TimeoutError):
        adapter.execute(prepared)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("malformation", ["missing_usage", "boolean_usage", "negative_usage", "float_usage", "total", "model", "missing_id", "multiple_choices", "tools", "output_limit"])
def test_contract_violations_preserve_observed_output(malformation: str) -> None:
    key = "openai/gpt-4o-2024-08-06"
    data = native_reply(key, content="captured text")
    if malformation == "missing_usage":
        del data["usage"]
    elif malformation in {"boolean_usage", "negative_usage", "float_usage"}:
        data["usage"]["prompt_tokens"] = {"boolean_usage": True, "negative_usage": -1, "float_usage": 1.0}[malformation]
    elif malformation == "total":
        data["usage"]["total_tokens"] = 16
    elif malformation == "model":
        data["model"] = "unrecognized-revision"
    elif malformation == "missing_id":
        del data["id"]
    elif malformation == "multiple_choices":
        data["choices"] *= 2
    elif malformation == "tools":
        data["choices"][0]["message"]["tool_calls"] = [{"id": "unexpected"}]
    else:
        data["usage"].update(completion_tokens=513, total_tokens=523)
    adapter, transport = adapter_for(key, data)
    prepared = adapter.prepare(key, MESSAGES, max_output_tokens=512)
    with pytest.raises(ProviderContractViolation) as error:
        adapter.execute(prepared)
    assert error.value.observed_response is not None
    assert error.value.observed_response.content == "captured text"
    if malformation == "output_limit":
        assert error.value.observed_response.completion_tokens == 513
    assert len(transport.calls) == 1


def test_anthropic_cache_counters_are_added_without_discounting() -> None:
    key = "anthropic/claude-sonnet-4-6"
    data = native_reply(key, extra_usage={"cache_creation_input_tokens": 20, "cache_read_input_tokens": 30,
                                        "cache_creation": {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 10}})
    adapter, _ = adapter_for(key, data)
    result = adapter.execute(adapter.prepare(key, MESSAGES, max_output_tokens=512))
    assert result.prompt_tokens == 60
    assert result.charge_nanos == 60 * 6000 + 5 * 15000


@pytest.mark.parametrize("change", ["messages", "native", "output", "config", "account", "tariff", "bound", "simulated"])
def test_prepared_mutation_is_refused_before_transport(change: str) -> None:
    key = "openai/gpt-4o-2024-08-06"
    adapter, transport = adapter_for(key)
    prepared = adapter.prepare(key, MESSAGES, max_output_tokens=512)
    if change == "messages":
        prepared = replace(prepared, wire_json=prepared.wire_json.replace("Hello", "Changed"))
    elif change == "native":
        native = (prepared.provider_wire_json or "").replace('"n":1', '"n":2')
        prepared = replace(prepared, provider_wire_json=native, quote=replace(prepared.quote, request_hash=digest(native)))
    elif change == "output":
        prepared = replace(prepared, quote=replace(prepared.quote, max_output_tokens=513))
    elif change == "config":
        prepared = replace(prepared, config_json='{"cache":true}')
    elif change == "account":
        prepared = replace(prepared, quote=replace(prepared.quote, account_id="other"))
    elif change == "tariff":
        prepared = replace(prepared, quote=replace(prepared.quote, pricing_version="old"))
    elif change == "bound":
        prepared = replace(prepared, quote=replace(prepared.quote, max_cost_nanos=1))
    else:
        prepared = replace(prepared, simulated=False)
    with pytest.raises(BudgetRefused):
        adapter.execute(prepared)
    assert not transport.calls


def test_tariff_expiry_and_short_quote_expiry_refuse_before_dispatch() -> None:
    key = "openai/gpt-4o-2024-08-06"
    clock = [NOW]
    adapter, transport = adapter_for(key)
    adapter._clock = lambda: clock[0]
    prepared = adapter.prepare(key, MESSAGES, max_output_tokens=512)
    clock[0] += timedelta(seconds=121)
    with pytest.raises(BudgetRefused):
        adapter.execute(prepared)
    clock[0] = TARIFF_EXPIRY
    with pytest.raises(BudgetRefused):
        adapter.prepare(key, MESSAGES, max_output_tokens=512)
    assert not transport.calls


def test_default_live_transport_gate_refuses_preparation_without_a_network_call() -> None:
    adapter = NativeProviderAdapter("openai/gpt-4o-2024-08-06", "fake-key", clock=lambda: NOW)
    with patch("ylang.core.provider_transport.socket.socket") as network:
        with pytest.raises(BudgetRefused):
            adapter.prepare(adapter.profile.model, MESSAGES, max_output_tokens=512)
    network.assert_not_called()


def test_factory_requires_opt_in_and_maps_only_configured_reviewed_profiles() -> None:
    transport = FixtureTransport(HTTPReply(200, b"{}"))
    settings = Settings(provider_keys=ProviderKeys(openai="fake-key", anthropic="fake-key", mistral="fake-key"))
    assert build_provider_adapters(settings, transport=transport) == {}
    settings = settings.model_copy(update={"bounded_providers_enabled": True})
    adapters = build_provider_adapters(settings, transport=transport, clock=lambda: NOW)
    assert set(adapters) == {alias for profile in PROFILES.values() for alias in profile.aliases}
    assert "gemini/unreviewed" not in adapters
    assert not transport.calls


def test_native_input_rejects_tools_multimodal_and_excessive_bytes() -> None:
    adapter, transport = adapter_for("openai/gpt-4o-2024-08-06")
    for messages in [[{"role": "user", "content": [], "tool_calls": []}],
                     [{"role": "user", "content": "x" * (1024 * 1024)}]]:
        with pytest.raises((BudgetRefused, TypeError)):
            adapter.prepare(adapter.profile.model, messages, max_output_tokens=512)
    assert not transport.calls


def test_dns_completion_after_owner_timeout_cannot_dispatch_http() -> None:
    release = threading.Event()
    resolved = threading.Event()

    def late_dns(*args: object, **kwargs: object) -> list[tuple]:
        """Finish after owner timeout while having no access to transport operations."""
        release.wait(1)
        resolved.set()
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    with patch("ylang.core.provider_transport.socket.getaddrinfo", side_effect=late_dns):
        with patch("ylang.core.provider_transport.socket.socket") as network:
            with pytest.raises(TimeoutError):
                DirectHTTPSProviderTransport().post("api.openai.com", "/v1/chat/completions", {}, b"{}", 0.01)
            network.assert_not_called()
            release.set()
            assert resolved.wait(1)
            network.assert_not_called()


def test_direct_transport_one_post_and_no_redirect_or_proxy_processing() -> None:
    active = MagicMock()
    response = MagicMock(status=302)
    response.getheader.side_effect = lambda key: "fixture-request" if key == "x-request-id" else None
    response.read1.side_effect = [b"fixture", b""]
    connection = MagicMock()
    connection.getresponse.return_value = response
    with patch("ylang.core.provider_transport._resolve_address", return_value=(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))):
        with patch("ylang.core.provider_transport.socket.socket") as sockets:
            with patch("ylang.core.provider_transport.ssl.create_default_context") as tls:
                tls.return_value.wrap_socket.return_value = active
                with patch("ylang.core.provider_transport.http.client.HTTPSConnection", return_value=connection):
                    reply = DirectHTTPSProviderTransport().post("api.openai.com", "/v1/chat/completions", {"content-type": "application/json"}, b"{}", 1)
    assert reply.status == 302 and reply.body == b"fixture"
    connection.request.assert_called_once_with("POST", "/v1/chat/completions", body=b"{}", headers={"content-type": "application/json"})
    assert sockets.call_count == 1
    tls.return_value.wrap_socket.assert_called_once()
    assert tls.return_value.wrap_socket.call_args.kwargs["server_hostname"] == "api.openai.com"


def test_direct_transport_refuses_alternate_hosts_and_oversized_response() -> None:
    with patch("ylang.core.provider_transport.socket.socket") as network:
        with pytest.raises(ValueError):
            DirectHTTPSProviderTransport().post("attacker.invalid", "/v1/chat/completions", {}, b"{}", 1)
    network.assert_not_called()
    response = MagicMock(status=200)
    response.getheader.return_value = str(MAX_RESPONSE_BYTES + 1)
    connection = MagicMock()
    connection.getresponse.return_value = response
    with patch("ylang.core.provider_transport._resolve_address", return_value=(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))):
        with patch("ylang.core.provider_transport.socket.socket"):
            with patch("ylang.core.provider_transport.ssl.create_default_context"):
                with patch("ylang.core.provider_transport.http.client.HTTPSConnection", return_value=connection):
                    with pytest.raises(ProviderTransportError):
                        DirectHTTPSProviderTransport().post("api.openai.com", "/v1/chat/completions", {}, b"{}", 1)
    assert connection.request.call_count == 1 and response.read1.call_count == 0


def test_credential_identity_cannot_change_after_preparation() -> None:
    adapter, transport = adapter_for("openai/gpt-4o-2024-08-06")
    prepared = adapter.prepare(adapter.profile.model, MESSAGES, max_output_tokens=512)
    adapter._api_key = "different-fake-key"
    with pytest.raises(BudgetRefused):
        adapter.execute(prepared)
    assert not transport.calls


@pytest.mark.parametrize("key", PROFILES)
def test_native_controls_disable_unbounded_features(key: str) -> None:
    adapter, transport = adapter_for(key)
    prepared = adapter.prepare(key, MESSAGES, max_output_tokens=512)
    adapter.execute(prepared)
    native = json.loads(transport.calls[0][3])
    headers = transport.calls[0][2]
    assert "tools" not in native and "thinking_budget" not in native
    if PROFILES[key].provider == "anthropic":
        assert native["max_tokens"] == 512 and native["thinking"] == {"type": "disabled"}
        assert set(headers) == {"content-type", "accept", "x-api-key", "anthropic-version"}
        assert headers["anthropic-version"] == "2023-06-01"
    elif PROFILES[key].provider == "openai":
        assert native["max_completion_tokens"] == 512 and native["service_tier"] == "default"
        assert native["store"] is False and native["n"] == 1
    else:
        assert native["max_tokens"] == 512 and native["reasoning_effort"] == "none" and native["n"] == 1


def test_direct_transport_total_deadline_interrupts_partial_reply() -> None:
    clock = [0.0]
    active = MagicMock()
    response = MagicMock(status=200)
    response.getheader.return_value = None

    def late_read(_: int) -> bytes:
        """Advance the total deadline despite making partial read progress."""
        clock[0] = 2.0
        return b"partial"

    response.read1.side_effect = late_read
    connection = MagicMock()
    connection.getresponse.return_value = response
    with patch("ylang.core.provider_transport._resolve_address", return_value=(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))):
        with patch("ylang.core.provider_transport.time.monotonic", side_effect=lambda: clock[0]):
            with patch("ylang.core.provider_transport.socket.socket"):
                with patch("ylang.core.provider_transport.ssl.create_default_context") as tls:
                    tls.return_value.wrap_socket.return_value = active
                    with patch("ylang.core.provider_transport.http.client.HTTPSConnection", return_value=connection):
                        with pytest.raises(TimeoutError):
                            DirectHTTPSProviderTransport().post("api.openai.com", "/v1/chat/completions", {}, b"{}", 1)
    assert connection.request.call_count == 1 and response.read1.call_count == 1
    connection.close.assert_called_once()


def test_truncated_http_body_is_uncertain_even_when_json_prefix_is_complete() -> None:
    response = MagicMock(status=200)
    response.getheader.return_value = "100"
    response.read1.side_effect = [b"{}", b""]
    connection = MagicMock()
    connection.getresponse.return_value = response
    with patch("ylang.core.provider_transport._resolve_address", return_value=(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))):
        with patch("ylang.core.provider_transport.socket.socket"):
            with patch("ylang.core.provider_transport.ssl.create_default_context"):
                with patch("ylang.core.provider_transport.http.client.HTTPSConnection", return_value=connection):
                    with pytest.raises(ProviderTransportError):
                        DirectHTTPSProviderTransport().post("api.openai.com", "/v1/chat/completions", {}, b"{}", 1)
    assert connection.request.call_count == 1 and response.read1.call_count == 2


@pytest.mark.parametrize("key", PROFILES)
def test_native_request_pins_standard_service_capacity(key: str) -> None:
    """Do not let workspace priority defaults escape the quoted standard tariff."""
    adapter, _ = adapter_for(key)
    body = json.loads(adapter.prepare(key, MESSAGES, max_output_tokens=512).provider_wire_json or "{}")
    assert body["service_tier"] == ("default" if PROFILES[key].provider == "openai" else "standard_only")
    assert "inference_geo" not in body


def test_sonnet_geography_surcharge_is_reserved_without_overriding_workspace() -> None:
    """Include the documented 1.1x US surcharge in input/cache and output ceilings."""
    key = "anthropic/claude-sonnet-4-6"
    adapter, _ = adapter_for(key, native_reply(key, extra_usage={"inference_geo": "us"}))
    prepared = adapter.prepare(key, MESSAGES, max_output_tokens=512)
    assert prepared.quote.max_cost_nanos == 1_048_576 * 6_600 + 512 * 16_500
    assert adapter.execute(prepared).charge_nanos == 10 * 6_600 + 5 * 16_500
