"""Explainable routing reason payloads (no secrets)."""

from __future__ import annotations

import json
from typing import Any

from ylang.core.model_router import (
    ModelRouter,
    apply_budget_filter,
    apply_preference_order,
)
from ylang.core.types import Activity


def build_routing_reason(
    router: ModelRouter,
    activity: Activity | str,
    *,
    attempt_chain: list[str],
    selected: str,
    explicit_model: str | None = None,
    fallback_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a structured routing explanation for persistence and operators.

    Never includes API keys or Authorization values — only model slugs,
    provider names, numeric policy knobs, and error classes.
    """
    bucket = router.activity_for(activity)
    configured = list(router._activity_model_lists[bucket])  # noqa: SLF001
    preferred = apply_preference_order(
        configured,
        bucket,
        store=router._usage_store,  # noqa: SLF001
    )
    ordered = apply_budget_filter(
        preferred,
        bucket,
        store=router._usage_store,  # noqa: SLF001
        daily_budget_usd=router._daily_budget_usd,  # noqa: SLF001
    )

    steps: list[dict[str, Any]] = [
        {"code": "configured_preference", "detail": f"bucket={bucket}"},
    ]
    if preferred != configured:
        steps.append(
            {"code": "learned_preference", "detail": "reordered_by=usage_counts"}
        )
    if ordered != preferred:
        steps.append({"code": "budget_constraint", "detail": _budget_detail(router)})

    no_key = [
        model
        for model in configured
        if router.candidate_status(model) == "skipped:no_key"
    ]
    if no_key:
        steps.append({"code": "provider_unavailable", "models": no_key})

    cooled = [
        model
        for model in configured
        if router.candidate_status(model) == "skipped:cooldown"
    ]
    if cooled:
        steps.append({"code": "cooldown", "models": cooled})

    if explicit_model:
        steps.append(
            {"code": "explicit_override", "detail": f"requested={explicit_model}"}
        )

    available = [model for model in ordered if router.is_available(model)]
    if not available:
        steps.append(
            {
                "code": "fallback",
                "detail": "no_available_candidates",
                "to": selected,
            }
        )
    elif router.quality_band > 0 or (
        available and selected == available[0] and router.quality_band == 0
    ):
        # Record tie-break whenever quality_band allows cost selection among a pool.
        if router.quality_band > 0:
            steps.append(
                {
                    "code": "quality_cost_tiebreak",
                    "band": router.quality_band,
                    "selected": selected,
                }
            )

    for event in fallback_events or []:
        steps.append(
            {
                "code": "fallback",
                "from": event.get("from"),
                "to": event.get("to"),
                "error_class": event.get("error_class"),
            }
        )

    return {
        "schema": 1,
        "activity": str(activity),
        "bucket": bucket,
        "selected": selected,
        "steps": steps,
        "candidates": list(attempt_chain),
        "policy": {
            "daily_budget_usd": router._daily_budget_usd,  # noqa: SLF001
            "quality_band": router.quality_band,
            "fallback_model": router.fallback_model,
        },
    }


def _budget_detail(router: ModelRouter) -> str:
    cap = router._daily_budget_usd  # noqa: SLF001
    if router._usage_store is None or cap is None:  # noqa: SLF001
        return f"cap_usd={cap} local_only=true"
    from ylang.usage.aggregates import default_daily_window, rolling_cost

    spent = rolling_cost(router._usage_store, default_daily_window())  # noqa: SLF001
    return f"spent_usd={spent:.4f} cap_usd={cap} local_only=true"


def routing_reason_json(
    router: ModelRouter,
    activity: Activity | str,
    *,
    attempt_chain: list[str],
    selected: str,
    explicit_model: str | None = None,
    fallback_events: list[dict[str, Any]] | None = None,
) -> str:
    """Serialize :func:`build_routing_reason` as compact JSON text."""
    payload = build_routing_reason(
        router,
        activity,
        attempt_chain=attempt_chain,
        selected=selected,
        explicit_model=explicit_model,
        fallback_events=fallback_events,
    )
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def routing_one_liner(reason: dict[str, Any] | str | None) -> str:
    """Return a short operator-facing explanation from a reason payload."""
    if reason is None:
        return "Routing reason unavailable"
    if isinstance(reason, str):
        try:
            payload = json.loads(reason)
        except json.JSONDecodeError:
            return "Routing reason unavailable"
    else:
        payload = reason
    selected = payload.get("selected") or "?"
    steps = payload.get("steps") or []
    codes = [str(step.get("code")) for step in steps if isinstance(step, dict)]
    priority = (
        "explicit_override",
        "budget_constraint",
        "fallback",
        "cooldown",
        "provider_unavailable",
        "learned_preference",
        "quality_cost_tiebreak",
        "configured_preference",
    )
    chosen = next((code for code in priority if code in codes), "configured_preference")
    return f"Selected {selected} because {chosen}"
