"""LiteLLM-backed completion engine with activity routing and usage logging."""

from __future__ import annotations

import time
from typing import Any

import litellm
from litellm.caching.caching import Cache

from ylang.core.types import Activity, CompletionResult, Message
from ylang.usage.store import UsageStore

DEFAULT_ACTIVITY_MODELS: dict[Activity, str] = {
    "code": "anthropic/claude-3-5-sonnet-latest",
    "search": "openai/gpt-4o-mini",
    "reason": "openai/o3-mini",
    "other": "openai/gpt-4o-mini",
}

FALLBACK_MODEL: str = "ollama/qwen2.5"

if litellm.cache is None:
    litellm.cache = Cache()


class Engine:
    """Shared core engine: route by activity, call LiteLLM, log usage."""

    def __init__(
        self,
        store: UsageStore,
        *,
        surface: str,
        activity_models: dict[Activity, str] | None = None,
        fallback_model: str = FALLBACK_MODEL,
    ) -> None:
        self._store = store
        self._surface = surface
        self._activity_models = activity_models or DEFAULT_ACTIVITY_MODELS
        self._fallback_model = fallback_model

    def complete(
        self,
        messages: list[Message],
        activity: Activity | str,
        *,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
        improver_fired: bool = False,
        improver_accepted: bool = False,
    ) -> CompletionResult:
        """Resolve model from activity, complete via LiteLLM, write usage."""
        if model is not None:
            resolved_model = model
        elif activity in self._activity_models:
            resolved_model = self._activity_models[activity]  # type: ignore[index]
        else:
            resolved_model = self._activity_models["other"]
        started = time.perf_counter()
        content = ""
        model_used = resolved_model
        prompt_tokens = 0
        cost = 0.0
        error: str | None = None
        success = False
        try:
            content, model_used, prompt_tokens, cost = _call_litellm(
                resolved_model,
                messages,
                fallback_model=self._fallback_model,
                response_format=response_format,
            )
            success = True
        except Exception as exc:
            error = str(exc)
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
        return CompletionResult(
            content=content,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            cost=cost,
            latency_ms=latency_ms,
            success=success,
            error=error,
        )


def _call_litellm(
    model: str,
    messages: list[Message],
    *,
    fallback_model: str,
    response_format: dict[str, str] | None = None,
) -> tuple[str, str, int, float]:
    """Call LiteLLM with caching and fallback; return content and usage metadata."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "fallbacks": [fallback_model],
        "caching": True,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    response = litellm.completion(**kwargs)
    return _parse_response(response, default_model=model)


def _parse_response(
    response: Any,
    *,
    default_model: str,
) -> tuple[str, str, int, float]:
    content = response.choices[0].message.content or ""
    model_used = getattr(response, "model", None) or default_model
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    hidden = getattr(response, "_hidden_params", {}) or {}
    cost = float(hidden.get("response_cost", 0.0) or 0.0)
    return content, str(model_used), prompt_tokens, cost
