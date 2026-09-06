"""LiteLLM-backed completion engine with activity routing and usage logging."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import litellm
from litellm.caching.caching import Cache

from ylang.core.model_router import ModelRouter
from ylang.core.routing_reason import routing_reason_json
from ylang.core.types import (
    Activity,
    CompletionResult,
    Message,
    ModelResolution,
    StreamChunk,
    StreamCompletionError,
)
from ylang.settings import (
    DEFAULT_FALLBACK_MODEL,
    ProviderKeys,
    api_key_for_model,
)
from ylang.usage.capture import (
    DEFAULT_CAPTURE_LEVEL,
    CaptureLevel,
    classify_error,
    hash_messages,
    parse_capture_level,
    prompt_body_for_capture,
    redact_error_message,
    redact_secrets,
    tool_calls_for_capture,
)
from ylang.usage.evaluation import evaluation_json_for_write
from ylang.usage.purge import DEFAULT_TRACE_RETENTION_DAYS
from ylang.usage.store import UsageStore, dumps_json_list

if TYPE_CHECKING:
    from ylang.settings import Settings
    from ylang.telemetry.export import UsageSpanSink

logger = logging.getLogger(__name__)

FALLBACK_MODEL: str = DEFAULT_FALLBACK_MODEL

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

if litellm.cache is None:
    litellm.cache = Cache()


@dataclass
class _StreamUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    model_used: str = ""


class Engine:
    """Shared core engine: route by activity, call LiteLLM, log usage."""

    def __init__(
        self,
        store: UsageStore,
        *,
        surface: str,
        router: ModelRouter | None = None,
        base_settings: Settings | None = None,
        activity_model_lists: dict[Activity, list[str]] | None = None,
        provider_keys: ProviderKeys | None = None,
        fallback_model: str = FALLBACK_MODEL,
        quality_band: int | None = None,
        provider_cooldown_seconds: int | None = None,
        capture_level: CaptureLevel | None = None,
        telemetry: UsageSpanSink | None = None,
    ) -> None:
        """Wire a usage store and routing surface label for completion logging.

        Args:
            store: Shared usage store for writes and router budget/preference reads.
            surface: Logical face label persisted on usage rows (e.g. ``mcp``, ``gateway``).
            router: Pre-built router; when omitted, built from the remaining kwargs.
            base_settings: Env snapshot for merging runtime overrides; set by
                ``from_settings``.
            activity_model_lists: Per-activity model priority lists.
            provider_keys: Cloud API keys for availability checks.
            fallback_model: Local floor model appended to every attempt chain.
            quality_band: Max rank offset for cost tie-break among available models.
            provider_cooldown_seconds: Cooldown after retryable provider failures.
            capture_level: Trace privacy tier; defaults to ``minimal``.
            telemetry: Optional span sink (OTLP); local usage writes always run.
        """
        self._store = store
        self._surface = surface
        self._base_settings = base_settings
        if capture_level is not None:
            self._capture_level: CaptureLevel = capture_level
        elif base_settings is not None:
            self._capture_level = base_settings.capture_level
        else:
            self._capture_level = DEFAULT_CAPTURE_LEVEL
        if router is not None:
            self._router = router
        else:
            router_kwargs: dict[str, object] = {
                "provider_keys": provider_keys or ProviderKeys(),
                "fallback_model": fallback_model,
            }
            if activity_model_lists is not None:
                router_kwargs["activity_model_lists"] = activity_model_lists
            if quality_band is not None:
                router_kwargs["quality_band"] = quality_band
            if provider_cooldown_seconds is not None:
                router_kwargs["provider_cooldown_seconds"] = provider_cooldown_seconds
            self._router = ModelRouter(**router_kwargs)  # type: ignore[arg-type]
        if telemetry is not None:
            self._telemetry = telemetry
        else:
            from ylang.telemetry.export import NoOpUsageSpanSink

            self._telemetry = NoOpUsageSpanSink()
        self._otel_export_content = False
        if base_settings is not None:
            self._otel_export_content = bool(base_settings.otel_export_content)

    @property
    def router(self) -> ModelRouter:
        """Model router used for selection, chaining, and cooldown tracking."""
        return self._router

    @property
    def store(self) -> UsageStore:
        """Usage store shared with the model router for budget and preferences."""
        return self._store

    @classmethod
    def from_settings(
        cls,
        store: UsageStore,
        *,
        surface: str,
        settings: Settings,
    ) -> Engine:
        """Build an engine from a loaded Settings instance."""
        from ylang.telemetry.export import exporter_from_settings

        return cls(
            store,
            surface=surface,
            router=ModelRouter.from_settings(settings, usage_store=store),
            base_settings=settings,
            capture_level=settings.capture_level,
            telemetry=exporter_from_settings(settings),
        )

    def _refresh_routing(self) -> None:
        """Apply hot-reloadable runtime overrides to the model router.

        No-op when the engine was constructed without ``base_settings`` (tests
        and ad-hoc routers inject lists directly and must not be overwritten by
        env defaults).
        """
        if self._base_settings is None:
            return
        from ylang.core.runtime_settings import RuntimeSettingsStore, merge_settings

        overrides = RuntimeSettingsStore(self._store._connection).as_dict()
        effective = merge_settings(self._base_settings, overrides)
        self._router.apply_settings(effective)
        self._capture_level = effective.capture_level

    def _effective_capture_level(self) -> CaptureLevel:
        """Return the capture level for this request (runtime-aware when possible)."""
        if self._base_settings is None:
            return self._capture_level
        from ylang.core.runtime_settings import RuntimeSettingsStore, merge_settings

        overrides = RuntimeSettingsStore(self._store._connection).as_dict()
        if "capture_level" not in overrides:
            return self._capture_level
        effective = merge_settings(self._base_settings, overrides)
        return parse_capture_level(effective.capture_level)

    def complete(
        self,
        messages: list[Message],
        activity: Activity | str,
        *,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
        improver_fired: bool = False,
        improver_accepted: bool = False,
        improver_input_sample: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        usage_cancelled: threading.Event | None = None,
        parent_trace_id: str | None = None,
        mcp_tool: str | None = None,
        selected_route: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
        workspace: str | None = None,
        context_sources_json: str | None = None,
        memory_fact_ids_json: str | None = None,
        mcp_server: str | None = None,
        retention_until: str | None = None,
        cost_actual: float | None = None,
        template_version: int | None = None,
    ) -> CompletionResult:
        """Resolve model from activity, complete via LiteLLM, write usage.

        When ``usage_cancelled`` is set before the usage write, the write is
        skipped so a caller timeout path can record the outcome instead.
        """
        self._refresh_routing()
        attempt_chain = self._router.build_attempt_chain(
            activity,
            explicit_model=model,
        )
        capture_level = self._effective_capture_level()
        allocated_trace_id = trace_id or str(uuid.uuid4())

        started = time.perf_counter()
        content = ""
        tool_calls: list[dict[str, Any]] = []
        model_used = attempt_chain[0] if attempt_chain else self._router.fallback_model
        prompt_tokens = 0
        completion_tokens = 0
        cost = 0.0
        error: str | None = None
        last_exc: BaseException | None = None
        success = False
        fallback_events: list[dict[str, Any]] = []
        attempt_index = 0

        for index, candidate in enumerate(attempt_chain):
            api_key = api_key_for_model(candidate, self._router.provider_keys)
            try:
                (
                    content,
                    model_used,
                    prompt_tokens,
                    completion_tokens,
                    cost,
                    tool_calls,
                ) = _call_litellm(
                    candidate,
                    messages,
                    api_key=api_key,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=tool_choice,
                )
                success = True
                attempt_index = index
                break
            except Exception as exc:
                last_exc = exc
                error = str(exc)
                if index + 1 >= len(attempt_chain) or not _should_try_next_model(exc):
                    break
                next_model = attempt_chain[index + 1]
                error_class = classify_error(exc, success=False) or "error"
                fallback_events.append(
                    {
                        "from": candidate,
                        "to": next_model,
                        "error_class": error_class,
                    }
                )
                if _is_retryable_llm_error(exc):
                    self._router.cooldown.mark_failed(candidate)
                logger.warning(
                    "LLM fallback: %s -> %s (%s)",
                    candidate,
                    next_model,
                    redact_secrets(_error_reason(exc)),
                )

        latency_ms = int((time.perf_counter() - started) * 1000)
        if usage_cancelled is None or not usage_cancelled.is_set():
            self._write_traced_usage(
                messages=messages,
                activity=activity,
                model_used=model_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                improver_fired=improver_fired,
                improver_accepted=improver_accepted,
                improver_input_sample=improver_input_sample,
                latency_ms=latency_ms,
                success=success,
                error=error,
                last_exc=last_exc,
                tool_calls=tool_calls,
                attempt_chain=attempt_chain,
                explicit_model=model,
                fallback_events=fallback_events,
                capture_level=capture_level,
                trace_id=allocated_trace_id,
                parent_trace_id=parent_trace_id,
                mcp_tool=mcp_tool,
                selected_route=selected_route,
                attempt_index=attempt_index,
                session_id=session_id,
                workspace=workspace,
                context_sources_json=context_sources_json,
                memory_fact_ids_json=memory_fact_ids_json,
                mcp_server=mcp_server,
                retention_until=retention_until,
                cost_actual=cost_actual,
                template_version=template_version,
            )
        return CompletionResult(
            content=content,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            latency_ms=latency_ms,
            success=success,
            error=error,
            tool_calls=tool_calls,
            trace_id=allocated_trace_id,
        )

    def complete_stream(
        self,
        messages: list[Message],
        activity: Activity | str,
        *,
        model: str | None = None,
        improver_fired: bool = False,
        improver_accepted: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parent_trace_id: str | None = None,
        mcp_tool: str | None = None,
        selected_route: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
        workspace: str | None = None,
        context_sources_json: str | None = None,
        memory_fact_ids_json: str | None = None,
        mcp_server: str | None = None,
        retention_until: str | None = None,
        cost_actual: float | None = None,
        template_version: int | None = None,
    ) -> Iterator[StreamChunk]:
        """Stream completion deltas via LiteLLM; write exactly one usage row at end."""
        self._refresh_routing()
        attempt_chain = self._router.build_attempt_chain(
            activity,
            explicit_model=model,
        )
        capture_level = self._effective_capture_level()
        allocated_trace_id = trace_id or str(uuid.uuid4())

        started = time.perf_counter()
        model_used = attempt_chain[0] if attempt_chain else self._router.fallback_model
        prompt_tokens = 0
        completion_tokens = 0
        cost = 0.0
        error: str | None = None
        last_exc: BaseException | None = None
        success = False
        emitted = False
        fallback_events: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        attempt_index = 0

        try:
            for index, candidate in enumerate(attempt_chain):
                api_key = api_key_for_model(candidate, self._router.provider_keys)
                try:
                    stream_usage = _StreamUsage(model_used=candidate)
                    for chunk in _iter_litellm_stream(
                        candidate,
                        messages,
                        api_key=api_key,
                        usage=stream_usage,
                        tools=tools,
                        tool_choice=tool_choice,
                    ):
                        if (
                            chunk.content
                            or chunk.tool_calls_delta
                            or chunk.usage is not None
                        ):
                            emitted = True
                            if chunk.tool_calls_delta:
                                tool_calls.extend(chunk.tool_calls_delta)
                            yield chunk
                    model_used = stream_usage.model_used or candidate
                    prompt_tokens = stream_usage.prompt_tokens
                    completion_tokens = stream_usage.completion_tokens
                    cost = stream_usage.cost
                    success = True
                    attempt_index = index
                    return
                except Exception as exc:
                    last_exc = exc
                    error = str(exc)
                    if emitted:
                        raise StreamCompletionError(
                            message=str(exc),
                            model_used=model_used,
                        ) from exc
                    if index + 1 >= len(attempt_chain) or not _should_try_next_model(
                        exc
                    ):
                        break
                    next_model = attempt_chain[index + 1]
                    error_class = classify_error(exc, success=False) or "error"
                    fallback_events.append(
                        {
                            "from": candidate,
                            "to": next_model,
                            "error_class": error_class,
                        }
                    )
                    if _is_retryable_llm_error(exc):
                        self._router.cooldown.mark_failed(candidate)
                    logger.warning(
                        "LLM stream fallback: %s -> %s (%s)",
                        candidate,
                        next_model,
                        redact_secrets(_error_reason(exc)),
                    )
                    model_used = next_model
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._write_traced_usage(
                messages=messages,
                activity=activity,
                model_used=model_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                improver_fired=improver_fired,
                improver_accepted=improver_accepted,
                improver_input_sample=None,
                latency_ms=latency_ms,
                success=success,
                error=error,
                last_exc=last_exc,
                tool_calls=tool_calls,
                attempt_chain=attempt_chain,
                explicit_model=model,
                fallback_events=fallback_events,
                capture_level=capture_level,
                trace_id=allocated_trace_id,
                parent_trace_id=parent_trace_id,
                mcp_tool=mcp_tool,
                selected_route=selected_route,
                attempt_index=attempt_index,
                session_id=session_id,
                workspace=workspace,
                context_sources_json=context_sources_json,
                memory_fact_ids_json=memory_fact_ids_json,
                mcp_server=mcp_server,
                retention_until=retention_until,
                cost_actual=cost_actual,
                template_version=template_version,
            )

        if not success:
            raise StreamCompletionError(
                message=error or "completion failed",
                model_used=model_used,
            )

    def _write_traced_usage(
        self,
        *,
        messages: list[Message],
        activity: Activity | str,
        model_used: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
        improver_fired: bool,
        improver_accepted: bool,
        improver_input_sample: str | None,
        latency_ms: int,
        success: bool,
        error: str | None,
        last_exc: BaseException | None,
        tool_calls: list[dict[str, Any]],
        attempt_chain: list[str],
        explicit_model: str | None,
        fallback_events: list[dict[str, Any]],
        capture_level: CaptureLevel,
        trace_id: str,
        parent_trace_id: str | None,
        mcp_tool: str | None,
        selected_route: str | None,
        attempt_index: int = 0,
        session_id: str | None = None,
        workspace: str | None = None,
        context_sources_json: str | None = None,
        memory_fact_ids_json: str | None = None,
        mcp_server: str | None = None,
        retention_until: str | None = None,
        cost_actual: float | None = None,
        template_version: int | None = None,
    ) -> None:
        """Persist one usage row with control-plane trace fields."""
        resolution = self._router.resolve(
            activity,
            explicit_model=explicit_model,
            selected=model_used,
            attempt_chain=attempt_chain,
            attempt_index=attempt_index,
        )
        reason = routing_reason_json(
            self._router,
            activity,
            attempt_chain=attempt_chain,
            selected=model_used,
            explicit_model=explicit_model,
            fallback_events=fallback_events,
            selected_route=selected_route,
            attempt_index=attempt_index,
            resolution=resolution,
        )
        sample, body = prompt_body_for_capture(improver_input_sample, capture_level)
        prompt_hash = None
        if capture_level != "off":
            prompt_hash = hash_messages(messages)
        policy = {
            "daily_budget_usd": self._router._daily_budget_usd,  # noqa: SLF001
            "quality_band": self._router.quality_band,
            "fallback_model": self._router.fallback_model,
            "explicit_model": explicit_model,
            "capture_level": capture_level,
        }
        evaluation = evaluation_json_for_write(
            success=success,
            latency_ms=latency_ms,
            cost=cost,
            completion_tokens=completion_tokens,
            error_class=classify_error(last_exc, success=success),
            fallback_events=fallback_events,
            improver_fired=improver_fired,
            improver_accepted=improver_accepted,
        )
        resolved_mcp_server = mcp_server
        if mcp_tool is not None and resolved_mcp_server is None:
            resolved_mcp_server = "ylang"
        resolved_retention = retention_until
        if (
            capture_level in {"redacted", "full_local"}
            and resolved_retention is None
        ):
            resolved_retention = (
                datetime.now(timezone.utc)
                + timedelta(days=DEFAULT_TRACE_RETENTION_DAYS)
            ).isoformat()
        self._store.write_usage(
            surface=self._surface,
            activity=activity,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            cost=cost,
            improver_fired=improver_fired,
            improver_accepted=improver_accepted,
            improver_input_sample=sample,
            latency_ms=latency_ms,
            success=success,
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            prompt_hash=prompt_hash,
            prompt_body_redacted=body,
            mcp_tool=mcp_tool,
            selected_route=selected_route,
            candidate_models_json=dumps_json_list(attempt_chain),
            routing_reason_json=reason,
            fallback_events_json=(
                json.dumps(fallback_events, separators=(",", ":"), sort_keys=True)
                if fallback_events
                else None
            ),
            tool_calls_json=tool_calls_for_capture(tool_calls, capture_level),
            completion_tokens=completion_tokens,
            error_class=classify_error(last_exc, success=success),
            error_message_redacted=(
                None if capture_level == "off" else redact_error_message(error)
            ),
            result_status="success" if success else "error",
            policy_decision_json=json.dumps(policy, separators=(",", ":"), sort_keys=True),
            capture_level=capture_level,
            evaluation_json=evaluation,
            session_id=session_id,
            workspace=workspace,
            context_sources_json=context_sources_json,
            memory_fact_ids_json=memory_fact_ids_json,
            mcp_server=resolved_mcp_server,
            retention_until=resolved_retention,
            cost_actual=cost_actual,
            template_version=template_version,
        )
        self._emit_telemetry(
            activity=activity,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            latency_ms=latency_ms,
            success=success,
            trace_id=trace_id,
            session_id=session_id,
            workspace=workspace,
            selected_route=selected_route,
            capture_level=capture_level,
            prompt_body_redacted=body,
            tool_calls=tool_calls,
            resolution=resolution,
        )

    def _emit_telemetry(
        self,
        *,
        activity: Activity | str,
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
        capture_level: CaptureLevel,
        prompt_body_redacted: str | None,
        tool_calls: list[dict[str, Any]],
        resolution: ModelResolution,
    ) -> None:
        """Best-effort OTLP export; never fails the completion path."""
        from ylang.telemetry.export import completion_span_attributes

        try:
            attributes = completion_span_attributes(
                surface=self._surface,
                activity=str(activity),
                model_used=model_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=latency_ms,
                success=success,
                trace_id=trace_id,
                session_id=session_id,
                workspace=workspace,
                selected_route=selected_route,
                resolution=resolution,
                export_content=self._otel_export_content,
                capture_level=capture_level,
                prompt_body_redacted=prompt_body_redacted,
                tool_calls=tool_calls,
            )
            self._telemetry.emit(attributes)
        except Exception:
            logger.warning("telemetry export failed", exc_info=True)


def _should_try_next_model(exc: BaseException) -> bool:
    """Return True when the attempt chain should continue to the next candidate."""
    if _is_retryable_llm_error(exc):
        return True
    if isinstance(exc, litellm.NotFoundError):
        return True
    if isinstance(exc, litellm.BadRequestError):
        message = str(exc)
        return "Provider NOT provided" in message or "model" in message.lower()
    return False


def _is_retryable_llm_error(exc: BaseException) -> bool:
    """Return True for rate limits and server errors that should fall through."""
    if isinstance(
        exc,
        (
            litellm.RateLimitError,
            litellm.ServiceUnavailableError,
            litellm.BadGatewayError,
            litellm.InternalServerError,
        ),
    ):
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code in _RETRYABLE_STATUS_CODES


def _error_reason(exc: BaseException) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return f"HTTP {status_code}"
    return type(exc).__name__


def _call_litellm(
    model: str,
    messages: list[Message],
    *,
    api_key: str | None = None,
    response_format: dict[str, str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> tuple[str, str, int, int, float, list[dict[str, Any]]]:
    """Call LiteLLM with caching; return content, usage metadata, and tool_calls."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "caching": True,
    }
    if api_key is not None:
        kwargs["api_key"] = api_key
    if response_format is not None:
        kwargs["response_format"] = response_format
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    response = litellm.completion(**kwargs)
    return _parse_response(response, default_model=model)


def _iter_litellm_stream(
    model: str,
    messages: list[Message],
    *,
    api_key: str | None = None,
    usage: _StreamUsage,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> Iterator[StreamChunk]:
    """Yield streamed deltas from LiteLLM; updates ``usage`` from stream metadata."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "caching": True,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if api_key is not None:
        kwargs["api_key"] = api_key
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    usage.model_used = model
    response = litellm.completion(**kwargs)
    saw_usage = False
    for chunk in response:
        choices = getattr(chunk, "choices", None) or []
        content = ""
        tool_calls_delta: list[dict[str, Any]] = []
        finish_reason: str | None = None
        if choices:
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is not None:
                content = getattr(delta, "content", None) or ""
                tool_calls_delta = _serialize_stream_tool_calls(
                    getattr(delta, "tool_calls", None),
                )
            finish_reason = getattr(choice, "finish_reason", None)

        response_model = getattr(chunk, "model", None)
        if response_model:
            usage.model_used = str(response_model)
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            usage.prompt_tokens = int(getattr(chunk_usage, "prompt_tokens", 0) or 0)
            usage.completion_tokens = int(
                getattr(chunk_usage, "completion_tokens", 0) or 0
            )
            saw_usage = True
            total = usage.prompt_tokens + usage.completion_tokens
            yield StreamChunk(
                content="",
                usage={
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": total,
                },
            )
        hidden = getattr(chunk, "_hidden_params", {}) or {}
        response_cost = hidden.get("response_cost")
        if response_cost is not None:
            usage.cost = float(response_cost or 0.0)

        if content or tool_calls_delta:
            yield StreamChunk(
                content=content,
                tool_calls_delta=tool_calls_delta,
                finish_reason=finish_reason,
            )
        elif finish_reason and not saw_usage:
            yield StreamChunk(content="", finish_reason=finish_reason)


def _parse_response(
    response: Any,
    *,
    default_model: str,
) -> tuple[str, str, int, int, float, list[dict[str, Any]]]:
    message = response.choices[0].message
    content = message.content or ""
    tool_calls = _serialize_tool_calls(getattr(message, "tool_calls", None))
    model_used = getattr(response, "model", None) or default_model
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    hidden = getattr(response, "_hidden_params", {}) or {}
    cost = float(hidden.get("response_cost", 0.0) or 0.0)
    return content, str(model_used), prompt_tokens, completion_tokens, cost, tool_calls


def _serialize_tool_calls(raw: Any) -> list[dict[str, Any]]:
    """Convert LiteLLM tool_calls objects into OpenAI-compatible dicts."""
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(item)
            continue
        function = getattr(item, "function", None)
        result.append(
            {
                "id": getattr(item, "id", ""),
                "type": getattr(item, "type", "function"),
                "function": {
                    "name": getattr(function, "name", "") if function else "",
                    "arguments": getattr(function, "arguments", "") if function else "",
                },
            }
        )
    return result


def _serialize_stream_tool_calls(raw: Any) -> list[dict[str, Any]]:
    """Convert streaming tool_call deltas into OpenAI-compatible dicts."""
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(item)
            continue
        function = getattr(item, "function", None)
        entry: dict[str, Any] = {"index": getattr(item, "index", 0)}
        item_id = getattr(item, "id", None)
        if item_id:
            entry["id"] = item_id
        item_type = getattr(item, "type", None)
        if item_type:
            entry["type"] = item_type
        if function is not None:
            fn: dict[str, Any] = {}
            name = getattr(function, "name", None)
            if name:
                fn["name"] = name
            arguments = getattr(function, "arguments", None)
            if arguments:
                fn["arguments"] = arguments
            if fn:
                entry["function"] = fn
        result.append(entry)
    return result
