"""LiteLLM-backed completion engine with activity routing and usage logging."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import litellm
from litellm.caching.caching import Cache

from ylang.core.model_router import ModelRouter
from ylang.core.types import (
    Activity,
    CompletionResult,
    Message,
    StreamChunk,
    StreamCompletionError,
)
from ylang.settings import (
    DEFAULT_FALLBACK_MODEL,
    ProviderKeys,
    api_key_for_model,
)
from ylang.usage.store import UsageStore

if TYPE_CHECKING:
    from ylang.settings import Settings

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
        activity_model_lists: dict[Activity, list[str]] | None = None,
        provider_keys: ProviderKeys | None = None,
        fallback_model: str = FALLBACK_MODEL,
        quality_band: int | None = None,
        provider_cooldown_seconds: int | None = None,
    ) -> None:
        """Wire a usage store and routing surface label for completion logging.

        Args:
            store: Shared usage store for writes and router budget/preference reads.
            surface: Logical face label persisted on usage rows (e.g. ``mcp``, ``gateway``).
            router: Pre-built router; when omitted, built from the remaining kwargs.
            activity_model_lists: Per-activity model priority lists.
            provider_keys: Cloud API keys for availability checks.
            fallback_model: Local floor model appended to every attempt chain.
            quality_band: Max rank offset for cost tie-break among available models.
            provider_cooldown_seconds: Cooldown after retryable provider failures.
        """
        self._store = store
        self._surface = surface
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
        return cls(
            store,
            surface=surface,
            router=ModelRouter.from_settings(settings, usage_store=store),
        )

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
    ) -> CompletionResult:
        """Resolve model from activity, complete via LiteLLM, write usage."""
        attempt_chain = self._router.build_attempt_chain(
            activity,
            explicit_model=model,
        )

        started = time.perf_counter()
        content = ""
        tool_calls: list[dict[str, Any]] = []
        model_used = attempt_chain[0] if attempt_chain else self._router.fallback_model
        prompt_tokens = 0
        completion_tokens = 0
        cost = 0.0
        error: str | None = None
        success = False

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
                break
            except Exception as exc:
                error = str(exc)
                if index + 1 >= len(attempt_chain) or not _should_try_next_model(exc):
                    break
                next_model = attempt_chain[index + 1]
                if _is_retryable_llm_error(exc):
                    self._router.cooldown.mark_failed(candidate)
                logger.warning(
                    "LLM fallback: %s -> %s (%s)",
                    candidate,
                    next_model,
                    _error_reason(exc),
                )

        latency_ms = int((time.perf_counter() - started) * 1000)
        self._store.write_usage(
            surface=self._surface,
            activity=activity,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            cost=cost,
            improver_fired=improver_fired,
            improver_accepted=improver_accepted,
            improver_input_sample=improver_input_sample,
            latency_ms=latency_ms,
            success=success,
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
    ) -> Iterator[StreamChunk]:
        """Stream completion deltas via LiteLLM; write exactly one usage row at end."""
        attempt_chain = self._router.build_attempt_chain(
            activity,
            explicit_model=model,
        )

        started = time.perf_counter()
        model_used = attempt_chain[0] if attempt_chain else self._router.fallback_model
        prompt_tokens = 0
        cost = 0.0
        error: str | None = None
        success = False
        emitted = False

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
                        if chunk.content or chunk.tool_calls_delta or chunk.usage is not None:
                            emitted = True
                            yield chunk
                    model_used = stream_usage.model_used or candidate
                    prompt_tokens = stream_usage.prompt_tokens
                    cost = stream_usage.cost
                    success = True
                    return
                except Exception as exc:
                    error = str(exc)
                    if emitted:
                        raise StreamCompletionError(
                            message=str(exc),
                            model_used=model_used,
                        ) from exc
                    if index + 1 >= len(attempt_chain) or not _should_try_next_model(exc):
                        break
                    next_model = attempt_chain[index + 1]
                    if _is_retryable_llm_error(exc):
                        self._router.cooldown.mark_failed(candidate)
                    logger.warning(
                        "LLM stream fallback: %s -> %s (%s)",
                        candidate,
                        next_model,
                        _error_reason(exc),
                    )
                    model_used = next_model
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._store.write_usage(
                surface=self._surface,
                activity=activity,
                model_used=model_used,
                prompt_tokens=prompt_tokens,
                cost=cost,
                improver_fired=improver_fired,
                improver_accepted=improver_accepted,
                latency_ms=latency_ms,
                success=success,
            )

        if not success:
            raise StreamCompletionError(
                message=error or "completion failed",
                model_used=model_used,
            )


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
            usage.completion_tokens = int(getattr(chunk_usage, "completion_tokens", 0) or 0)
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
