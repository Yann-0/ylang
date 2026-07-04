"""Quality-first model selection with cost tie-break and provider cooldown."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import litellm

from ylang.core.types import Activity
from ylang.settings import (
    DEFAULT_ACTIVITY_MODEL_LISTS,
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_PROVIDER_COOLDOWN_SECONDS,
    DEFAULT_QUALITY_BAND,
    ProviderKeys,
    provider_from_litellm_model,
    provider_has_key,
)

if TYPE_CHECKING:
    from ylang.settings import Settings
    from ylang.usage.store import UsageStore

logger = logging.getLogger(__name__)

_ACTIVITIES: tuple[Activity, ...] = ("code", "search", "reason", "improve", "other")

CandidateStatus = str  # ``available`` | ``skipped:no_key`` | ``skipped:cooldown``

# Cursor IDE model slugs → LiteLLM provider/model strings (best-effort).
_CURSOR_SLUG_ALIASES: dict[str, str] = {
    "claude-4.6-sonnet-high-thinking": "anthropic/claude-sonnet-4-6",
    "claude-4.6-opus-high-thinking": "anthropic/claude-opus-4-6",
    "claude-4.6-sonnet-medium-thinking": "anthropic/claude-sonnet-4-6",
    "claude-3.5-sonnet-high-thinking": "anthropic/claude-sonnet-4-6",
    "claude-sonnet-4-5": "anthropic/claude-sonnet-4-6",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4-6",
    "composer": "anthropic/claude-sonnet-4-6",
    "composer-2.5-fast": "anthropic/claude-sonnet-4-6",
    "gpt-5.3-codex-high-fast": "openai/gpt-4o",
    "gpt-5.5-medium": "openai/gpt-4o",
    "gemini-3.1-pro": "openai/gpt-4o",
}


@dataclass
class ProviderCooldownTracker:
    """In-memory provider cooldown after retryable LLM failures."""

    cooldown_seconds: float = DEFAULT_PROVIDER_COOLDOWN_SECONDS
    _until: dict[str, float] = field(default_factory=dict)

    def is_cooled_down(self, model: str) -> bool:
        """Return True when the model's provider is in cooldown."""
        provider = provider_from_litellm_model(model)
        if provider is None:
            return False
        expiry = self._until.get(provider)
        if expiry is None:
            return False
        if time.monotonic() >= expiry:
            del self._until[provider]
            return False
        return True

    def mark_failed(self, model: str) -> None:
        """Start cooldown for the model's provider."""
        provider = provider_from_litellm_model(model)
        if provider is None:
            return
        self._until[provider] = time.monotonic() + self.cooldown_seconds


def estimated_unit_cost(model: str) -> float:
    """Return input+output per-token cost from LiteLLM; 0.0 when unknown."""
    try:
        info = litellm.get_model_info(model=model)
    except Exception:
        return 0.0
    input_cost = float(info.get("input_cost_per_token") or 0.0)
    output_cost = float(info.get("output_cost_per_token") or 0.0)
    return input_cost + output_cost


# Personal preference: reorder candidates by historical success counts (Seam 2C).
def apply_preference_order(
    candidates: list[str],
    activity: Activity | str,
    *,
    store: UsageStore | None = None,
) -> list[str]:
    """Reorder candidates from usage feedback — boost models with high success counts."""
    if store is None or not candidates:
        return candidates
    from ylang.usage.aggregates import default_daily_window, summarize_usage

    summary = summarize_usage(store, default_daily_window())
    if not summary.model_success_counts:
        return candidates

    def score(model: str) -> int:
        return summary.model_success_counts.get(model, 0)

    ranked = sorted(candidates, key=score, reverse=True)
    return ranked


# Budget meter: drop cloud models when rolling 24h spend exceeds cap (Seam 2B).
def apply_budget_filter(
    candidates: list[str],
    activity: Activity | str,
    *,
    store: UsageStore | None = None,
    daily_budget_usd: float | None = None,
) -> list[str]:
    """Drop cloud candidates when rolling 24h spend exceeds the daily budget cap."""
    _ = activity
    if store is None or daily_budget_usd is None:
        return candidates
    from ylang.usage.aggregates import default_daily_window, rolling_cost

    spent = rolling_cost(store, default_daily_window())
    if spent < daily_budget_usd:
        return candidates
    return [model for model in candidates if provider_from_litellm_model(model) is None]


def _dedupe_preserve_order(models: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for model in models:
        if model not in seen:
            seen.add(model)
            result.append(model)
    return result


def is_litellm_routable(model: str) -> bool:
    """Return True when the model string can be routed by LiteLLM."""
    if provider_from_litellm_model(model) is not None:
        return True
    return model.lower().startswith("ollama/")


def resolve_explicit_model(model: str) -> str | None:
    """Map a client model slug to LiteLLM form, or None to use activity routing."""
    if is_litellm_routable(model):
        return model
    if mapped := _CURSOR_SLUG_ALIASES.get(model):
        return mapped
    lowered = model.lower()
    if mapped := _CURSOR_SLUG_ALIASES.get(lowered):
        return mapped
    if lowered.startswith("claude-sonnet-4-"):
        return "anthropic/claude-sonnet-4-6"
    if lowered.startswith("claude-opus-4-"):
        return "anthropic/claude-opus-4-6"
    logger.warning(
        "Ignoring non-LiteLLM model slug %r; using activity routing instead",
        model,
    )
    return None


def normalize_model_list(models: list[str]) -> list[str]:
    """Deduplicate a model list while preserving first occurrence order."""
    if not models:
        msg = "activity model list must not be empty"
        raise ValueError(msg)
    return _dedupe_preserve_order(models)


_IMPROVE_MODE_BUCKETS: dict[str, Activity] = {
    "ask": "reason",
    "plan": "reason",
    "debug": "code",
    "agent": "code",
    "multitask": "code",
}


class ModelRouter:
    """Select and chain LiteLLM models by activity, availability, and quality band."""

    def __init__(
        self,
        *,
        activity_model_lists: dict[Activity, list[str]] | None = None,
        provider_keys: ProviderKeys | None = None,
        fallback_model: str = DEFAULT_FALLBACK_MODEL,
        quality_band: int = DEFAULT_QUALITY_BAND,
        provider_cooldown_seconds: float = DEFAULT_PROVIDER_COOLDOWN_SECONDS,
        usage_store: UsageStore | None = None,
        daily_budget_usd: float | None = None,
    ) -> None:
        raw_lists = activity_model_lists or {
            activity: list(models) for activity, models in DEFAULT_ACTIVITY_MODEL_LISTS.items()
        }
        self._activity_model_lists = {
            activity: normalize_model_list(models) for activity, models in raw_lists.items()
        }
        self._provider_keys = provider_keys or ProviderKeys()
        self._fallback_model = fallback_model
        self._quality_band = quality_band
        self._usage_store = usage_store
        self._daily_budget_usd = daily_budget_usd
        self.cooldown = ProviderCooldownTracker(cooldown_seconds=provider_cooldown_seconds)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        usage_store: UsageStore | None = None,
    ) -> ModelRouter:
        """Build a router from a loaded Settings instance."""
        return cls(
            activity_model_lists=settings.activity_model_lists,
            provider_keys=settings.provider_keys,
            fallback_model=settings.fallback_model,
            quality_band=settings.quality_band,
            provider_cooldown_seconds=settings.provider_cooldown_seconds,
            usage_store=usage_store,
            daily_budget_usd=settings.daily_budget_usd,
        )

    @property
    def provider_keys(self) -> ProviderKeys:
        """Configured cloud provider API keys."""
        return self._provider_keys

    @property
    def fallback_model(self) -> str:
        """Local floor model appended when absent from an activity list."""
        return self._fallback_model

    @property
    def quality_band(self) -> int:
        """Max rank offset from the best available model for cost tie-break."""
        return self._quality_band

    def activity_for(self, activity: Activity | str) -> Activity:
        """Map a runtime activity string to a configured routing bucket."""
        if activity in self._activity_model_lists:
            return activity  # type: ignore[return-value]
        if isinstance(activity, str) and activity.startswith("improve:"):
            mode = activity.removeprefix("improve:")
            bucket = _IMPROVE_MODE_BUCKETS.get(mode)
            if bucket is not None:
                return bucket
            return "improve"
        return "other"

    def ordered_candidates(self, activity: Activity | str) -> list[str]:
        """Return the quality-ordered list for an activity after preference/budget seams."""
        bucket = self.activity_for(activity)
        ordered = list(self._activity_model_lists[bucket])
        ordered = apply_preference_order(ordered, bucket, store=self._usage_store)
        return apply_budget_filter(
            ordered,
            bucket,
            store=self._usage_store,
            daily_budget_usd=self._daily_budget_usd,
        )

    def candidate_status(self, model: str) -> CandidateStatus:
        """Explain why a model is or is not selectable."""
        if self.cooldown.is_cooled_down(model):
            return "skipped:cooldown"
        if not provider_has_key(model, self._provider_keys):
            return "skipped:no_key"
        return "available"

    def is_available(self, model: str) -> bool:
        """Return True when a model may be attempted."""
        if self.cooldown.is_cooled_down(model):
            return False
        return provider_has_key(model, self._provider_keys)

    def select_model(self, activity: Activity | str) -> str:
        """Pick the highest-quality available model, cost tie-breaking within band."""
        ordered = self.ordered_candidates(activity)
        ranked_available: list[tuple[int, str]] = []
        for rank, model in enumerate(ordered):
            if self.is_available(model):
                ranked_available.append((rank, model))

        if not ranked_available:
            return self._fallback_model

        best_rank = min(rank for rank, _ in ranked_available)
        tie_pool = [
            model
            for rank, model in ranked_available
            if rank - best_rank <= self._quality_band
        ]
        return min(tie_pool, key=estimated_unit_cost)

    def build_attempt_chain(
        self,
        activity: Activity | str,
        *,
        explicit_model: str | None = None,
    ) -> list[str]:
        """Build the ordered list of models to try before giving up."""
        ordered = self.ordered_candidates(activity)
        chain: list[str] = []
        seen: set[str] = set()

        if explicit_model is not None:
            resolved_explicit = resolve_explicit_model(explicit_model)
            if resolved_explicit is not None:
                chain.append(resolved_explicit)
                seen.add(resolved_explicit)

        first = self.select_model(activity)
        if first not in seen:
            chain.append(first)
            seen.add(first)

        for model in ordered:
            if model in seen:
                continue
            if self.is_available(model):
                chain.append(model)
                seen.add(model)

        if self._fallback_model not in seen:
            chain.append(self._fallback_model)

        return chain

    def selected_models_by_activity(self) -> dict[Activity, str]:
        """Return the pre-call selected model for each activity bucket."""
        return {activity: self.select_model(activity) for activity in _ACTIVITIES}

    def format_routing_report(self) -> str:
        """Format per-activity routing status for startup logs."""
        lines: list[str] = []
        lines.append(f"  quality_band: {self._quality_band}")
        lines.append("  activity routing (quality order → selected):")
        selected = self.selected_models_by_activity()
        for activity in _ACTIVITIES:
            pick = selected[activity]
            lines.append(f"    {activity}:")
            for rank, model in enumerate(self.ordered_candidates(activity)):
                status = self.candidate_status(model)
                marker = "  ← selected" if model == pick else ""
                lines.append(f"      [{rank}] {model}  {status}{marker}")
        floor_status = self.candidate_status(self._fallback_model)
        lines.append(f"  fallback floor: {self._fallback_model}  {floor_status}")
        return "\n".join(lines)
