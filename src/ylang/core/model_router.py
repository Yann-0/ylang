"""Quality-first model selection with cost tie-break and provider cooldown."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import litellm

from ylang.core.model_aliases import (
    AUTO_MODEL_SENTINELS,
    classify_explicit_model,
    load_cursor_slug_aliases,
    lookup_compatibility_alias,
)
from ylang.core.types import (
    Activity,
    ExplicitModelLookup,
    ModelResolution,
    ResolutionReason,
    model_provider_prefix,
)
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

_ACTIVITIES: tuple[Activity, ...] = ("code", "search", "reason", "improve", "other")

CandidateStatus = str  # ``available`` | ``skipped:no_key`` | ``skipped:cooldown``

_CURSOR_SLUG_ALIASES: dict[str, str] = load_cursor_slug_aliases()


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
    """Return input+output per-token cost from LiteLLM; 0.0 when unknown.

    Zero means "no reliable cost data", not "free". Callers must not treat
    unknown costs as cheaper than a known positive cost.
    """
    try:
        info = litellm.get_model_info(model=model)
    except Exception:
        # LiteLLM raises provider-specific errors for unknown/local models.
        return 0.0
    input_cost = float(info.get("input_cost_per_token") or 0.0)
    output_cost = float(info.get("output_cost_per_token") or 0.0)
    return input_cost + output_cost


def select_from_quality_band(tie_pool: list[str]) -> str:
    """Pick from a quality-band pool using known LiteLLM unit costs only.

    Unknown/zero costs never win a tie-break. If no candidate has a known
    cost, keep the first (quality-order) model.
    """
    if len(tie_pool) == 1:
        return tie_pool[0]
    chosen = tie_pool[0]
    chosen_cost = estimated_unit_cost(chosen)
    known_cost = chosen_cost if chosen_cost > 0.0 else None
    for model in tie_pool[1:]:
        cost = estimated_unit_cost(model)
        if cost <= 0.0:
            continue
        if known_cost is None or cost < known_cost:
            chosen = model
            known_cost = cost
    return chosen


# Buckets that route improver traffic — prefer improver_accepted over raw success.
_IMPROVER_ROUTING_BUCKETS: frozenset[str] = frozenset({"improve", "code", "reason"})


def _preference_counts(
    summary: object,
    activity: Activity | str,
) -> dict[str, int]:
    """Return per-model counts used to reorder candidates for an activity bucket."""
    from ylang.usage.aggregates import UsageSummary

    assert isinstance(summary, UsageSummary)
    bucket = str(activity)
    if bucket in _IMPROVER_ROUTING_BUCKETS and summary.model_improver_accepted_counts:
        return summary.model_improver_accepted_counts
    return summary.model_success_counts


# Personal preference: reorder candidates by historical success counts (Seam 2C).
def apply_preference_order(
    candidates: list[str],
    activity: Activity | str,
    *,
    store: UsageStore | None = None,
) -> list[str]:
    """Reorder candidates from usage feedback — boost models with high success counts.

    For improver-routing buckets (``code``, ``reason``), uses ``improver_accepted``
    counts when any exist; otherwise falls back to LLM ``success`` counts.

    The ``improve`` bucket keeps the configured ``models_improve`` order so runtime
    and env lists stay authoritative for prompt-improvement cost control.
    """
    if str(activity) == "improve":
        return candidates
    if store is None or not candidates:
        return candidates
    from ylang.usage.aggregates import default_daily_window, summarize_usage

    summary = summarize_usage(store, default_daily_window())
    counts = _preference_counts(summary, activity)
    if not counts:
        return candidates

    def score(model: str) -> int:
        return counts.get(model, 0)

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


def lookup_explicit_model(model: str) -> ExplicitModelLookup:
    """Classify a client model string without losing alias vs identity.

    Sentinels ``auto`` / ``default`` / ``route`` / empty string skip the explicit
    model and let the activity bucket choose.

    Compatibility aliases are applied **before** LiteLLM-routable checks so
    colliding local tags (e.g. ``ollama/gpt-4o-mini``) can be rewritten.
    An alias is a compatibility mapping, not a claim that the two ids are
    the same model.
    """
    return classify_explicit_model(
        model,
        aliases=_CURSOR_SLUG_ALIASES,
        is_routable=is_litellm_routable,
    )


def resolve_improver_explicit_model(model: str) -> str | None:
    """Resolve improver ``model`` kwargs; defer Cursor slugs to ``models_improve``.

    Only direct LiteLLM strings (``provider/model``) are honored as explicit
    overrides. Cursor slugs (``claude-sonnet-4-*``, ``composer``, etc.) and
    ``auto`` defer to the configured ``models_improve`` activity chain.
    """
    stripped = model.strip()
    if not stripped:
        return None
    if stripped.lower() in AUTO_MODEL_SENTINELS:
        return None
    if is_litellm_routable(stripped):
        return stripped
    return None


def resolve_explicit_model(model: str) -> str | None:
    """Map a client model slug to LiteLLM form, or None to use activity routing.

    Prefer :func:`lookup_explicit_model` when the caller needs to distinguish
    compatibility aliases from explicit LiteLLM routes.
    """
    return lookup_explicit_model(model).resolved


def normalize_model_list(models: list[str]) -> list[str]:
    """Deduplicate a model list while preserving first occurrence order."""
    if not models:
        msg = "activity model list must not be empty"
        raise ValueError(msg)
    return _dedupe_preserve_order(models)


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
            activity: list(models)
            for activity, models in DEFAULT_ACTIVITY_MODEL_LISTS.items()
        }
        self._activity_model_lists = {
            activity: normalize_model_list(models)
            for activity, models in raw_lists.items()
        }
        self._provider_keys = provider_keys or ProviderKeys()
        self._fallback_model = fallback_model
        self._quality_band = quality_band
        self._usage_store = usage_store
        self._daily_budget_usd = daily_budget_usd
        self.cooldown = ProviderCooldownTracker(
            cooldown_seconds=provider_cooldown_seconds
        )
        self._baseline_activity_model_lists = {
            activity: list(models)
            for activity, models in self._activity_model_lists.items()
        }
        self._operator_overridden_buckets: frozenset[Activity] = frozenset()

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

    def apply_settings(self, settings: Settings) -> None:
        """Refresh hot-reloadable routing fields from effective settings."""
        self._activity_model_lists = {
            activity: normalize_model_list(models)
            for activity, models in settings.activity_model_lists.items()
        }
        overridden: set[Activity] = set()
        for activity, models in self._activity_model_lists.items():
            if models != self._baseline_activity_model_lists.get(activity):
                overridden.add(activity)
        self._operator_overridden_buckets = frozenset(overridden)
        self._quality_band = settings.quality_band
        self._fallback_model = settings.fallback_model
        self._daily_budget_usd = settings.daily_budget_usd

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

    @property
    def activity_model_lists(self) -> dict[Activity, list[str]]:
        """Configured per-activity candidate lists (copies)."""
        return cast(
            dict[Activity, list[str]],
            {
                activity: list(models)
                for activity, models in self._activity_model_lists.items()
            },
        )

    @property
    def usage_store(self) -> UsageStore | None:
        """Usage store used for preference reorder and budget filtering."""
        return self._usage_store

    @property
    def daily_budget_usd(self) -> float | None:
        """Optional rolling 24h spend cap, or None when uncapped."""
        return self._daily_budget_usd

    @property
    def operator_overridden_buckets(self) -> frozenset[Activity]:
        """Activity buckets whose lists differ from construction-time baseline."""
        return self._operator_overridden_buckets

    def activity_for(self, activity: Activity | str) -> Activity:
        """Map a runtime activity string to a configured routing bucket.

        All ``improve:*`` activities use the dedicated ``improve`` list
        (``YLANG_MODELS_IMPROVE`` / ``models_improve``), not code/reason.
        """
        if activity in self._activity_model_lists:
            return activity  # type: ignore[return-value]
        if isinstance(activity, str) and activity.startswith("improve:"):
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
        return select_from_quality_band(tie_pool)

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

        bucket = self.activity_for(activity)
        if explicit_model is not None:
            if bucket == "improve":
                resolved_explicit = resolve_improver_explicit_model(explicit_model)
            else:
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

    def resolve(
        self,
        activity: Activity | str,
        *,
        explicit_model: str | None = None,
        selected: str | None = None,
        attempt_chain: list[str] | None = None,
        attempt_index: int = 0,
    ) -> ModelResolution:
        """Explain the semantic route and concrete model chosen for a request.

        ``selected`` defaults to the first attempt-chain entry (pre-call pick).
        After a completion, pass the model that actually answered.
        """
        bucket = self.activity_for(activity)
        chain = (
            attempt_chain
            if attempt_chain is not None
            else self.build_attempt_chain(activity, explicit_model=explicit_model)
        )
        resolved_model = (
            selected
            if selected is not None
            else (chain[0] if chain else self._fallback_model)
        )
        lookup: ExplicitModelLookup | None = None
        if explicit_model is not None:
            if bucket == "improve":
                resolved_explicit = resolve_improver_explicit_model(explicit_model)
                alias_hit = lookup_compatibility_alias(
                    explicit_model, _CURSOR_SLUG_ALIASES
                )
                lookup = ExplicitModelLookup(
                    requested=explicit_model.strip(),
                    resolved=resolved_explicit,
                    requested_alias=(
                        alias_hit.requested_alias
                        if alias_hit is not None and resolved_explicit is None
                        else None
                    ),
                    reason=(
                        "explicit_model"
                        if resolved_explicit is not None
                        else "activity_default"
                    ),
                    alias_source=(
                        alias_hit.source
                        if alias_hit is not None and resolved_explicit is None
                        else None
                    ),
                )
            else:
                lookup = lookup_explicit_model(explicit_model)
        reason = self._primary_resolution_reason(
            bucket=bucket,
            selected=resolved_model,
            explicit_lookup=lookup,
        )
        requested_alias = lookup.requested_alias if lookup else None
        requested_model = explicit_model.strip() if explicit_model else None
        return ModelResolution(
            requested_model=requested_model,
            requested_alias=requested_alias,
            semantic_route=bucket,
            resolved_route=bucket,
            resolved_provider=model_provider_prefix(resolved_model),
            resolved_model=resolved_model,
            resolution_reason=reason,
            attempt_index=attempt_index,
            alias_source=lookup.alias_source if lookup else None,
        )

    def _primary_resolution_reason(
        self,
        *,
        bucket: Activity,
        selected: str,
        explicit_lookup: ExplicitModelLookup | None,
    ) -> ResolutionReason:
        """Return the most specific machine-readable reason for ``selected``."""
        if (
            explicit_lookup is not None
            and explicit_lookup.resolved is not None
            and selected == explicit_lookup.resolved
        ):
            return explicit_lookup.reason

        configured = list(self._activity_model_lists[bucket])
        preferred = apply_preference_order(
            configured, bucket, store=self._usage_store
        )
        ordered = apply_budget_filter(
            preferred,
            bucket,
            store=self._usage_store,
            daily_budget_usd=self._daily_budget_usd,
        )
        available = [model for model in ordered if self.is_available(model)]

        if selected == self._fallback_model and not available:
            if ordered != preferred:
                return "budget_fallback"
            return "local_fallback"

        first_configured = configured[0] if configured else None
        if (
            first_configured
            and selected != first_configured
            and (
                explicit_lookup is None
                or explicit_lookup.resolved is None
                or selected != explicit_lookup.resolved
            )
        ):
            first_status = self.candidate_status(first_configured)
            if first_status == "skipped:cooldown":
                return "provider_cooldown"
            if first_status == "skipped:no_key":
                return "provider_unavailable"

        if available and selected != available[0]:
            if self._quality_band > 0 and estimated_unit_cost(selected) > 0.0:
                return "cost_tiebreak"
            if preferred != configured:
                return "quality_preference"

        if (
            preferred != configured
            and available
            and selected == available[0]
            and configured
            and configured[0] != selected
        ):
            return "quality_preference"

        if bucket in self._operator_overridden_buckets:
            return "operator_override"

        return "activity_default"

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
