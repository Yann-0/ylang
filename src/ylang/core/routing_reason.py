"""Explainable routing reason payloads (no secrets)."""

from __future__ import annotations

import json
from typing import Any

from ylang.core.model_router import (
    ModelRouter,
    apply_budget_filter,
    apply_preference_order,
    lookup_explicit_model,
    resolve_improver_explicit_model,
)
from ylang.core.types import Activity, ExplicitModelLookup, ModelResolution


def build_routing_reason(
    router: ModelRouter,
    activity: Activity | str,
    *,
    attempt_chain: list[str],
    selected: str,
    explicit_model: str | None = None,
    fallback_events: list[dict[str, Any]] | None = None,
    selected_route: str | None = None,
    attempt_index: int = 0,
    resolution: ModelResolution | None = None,
) -> dict[str, Any]:
    """Build a structured routing explanation for persistence and operators.

    Never includes API keys or Authorization values — only model slugs,
    provider names, numeric policy knobs, and error classes.
    """
    bucket = router.activity_for(activity)
    configured = list(router.activity_model_lists[bucket])
    preferred = apply_preference_order(
        configured,
        bucket,
        store=router.usage_store,
    )
    ordered = apply_budget_filter(
        preferred,
        bucket,
        store=router.usage_store,
        daily_budget_usd=router.daily_budget_usd,
    )
    resolved = resolution or router.resolve(
        activity,
        explicit_model=explicit_model,
        selected=selected,
        attempt_chain=attempt_chain,
        attempt_index=attempt_index,
    )
    lookup = _explicit_lookup(router, activity, explicit_model)

    steps: list[dict[str, Any]] = [
        {"code": "configured_preference", "detail": f"bucket={bucket}"},
    ]
    if bucket in router.operator_overridden_buckets:
        steps.append({"code": "operator_override", "detail": f"bucket={bucket}"})
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

    if lookup is not None and lookup.resolved is not None:
        if lookup.reason == "compatibility_alias":
            steps.append(
                {
                    "code": "compatibility_alias",
                    "requested_alias": lookup.requested_alias,
                    "resolved_model": lookup.resolved,
                    "alias_source": lookup.alias_source,
                }
            )
        else:
            steps.append(
                {
                    "code": "explicit_override",
                    "detail": f"requested={explicit_model}",
                }
            )
    elif explicit_model:
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

    payload: dict[str, Any] = {
        "schema": 1,
        "activity": str(activity),
        "bucket": bucket,
        "selected": selected,
        "steps": steps,
        "candidates": list(attempt_chain),
        "policy": {
            "daily_budget_usd": router.daily_budget_usd,
            "quality_band": router.quality_band,
            "fallback_model": router.fallback_model,
        },
    }
    payload.update(resolved.as_trace_fields())
    if selected_route is not None:
        payload["gateway_route"] = selected_route
    return payload


def _explicit_lookup(
    router: ModelRouter,
    activity: Activity | str,
    explicit_model: str | None,
) -> ExplicitModelLookup | None:
    if explicit_model is None:
        return None
    classified = lookup_explicit_model(explicit_model)
    if router.activity_for(activity) != "improve":
        return classified
    resolved = resolve_improver_explicit_model(explicit_model)
    return ExplicitModelLookup(
        requested=classified.requested,
        resolved=resolved,
        requested_alias=classified.requested_alias if resolved is None else None,
        reason="explicit_model" if resolved is not None else "activity_default",
        alias_source=classified.alias_source if resolved is None else None,
    )


def _budget_detail(router: ModelRouter) -> str:
    cap = router.daily_budget_usd
    if router.usage_store is None or cap is None:
        return f"cap_usd={cap} local_only=true"
    from ylang.usage.aggregates import default_daily_window, rolling_cost

    spent = rolling_cost(router.usage_store, default_daily_window())
    return f"spent_usd={spent:.4f} cap_usd={cap} local_only=true"


def routing_reason_json(
    router: ModelRouter,
    activity: Activity | str,
    *,
    attempt_chain: list[str],
    selected: str,
    explicit_model: str | None = None,
    fallback_events: list[dict[str, Any]] | None = None,
    selected_route: str | None = None,
    attempt_index: int = 0,
    resolution: ModelResolution | None = None,
) -> str:
    """Serialize :func:`build_routing_reason` as compact JSON text."""
    payload = build_routing_reason(
        router,
        activity,
        attempt_chain=attempt_chain,
        selected=selected,
        explicit_model=explicit_model,
        fallback_events=fallback_events,
        selected_route=selected_route,
        attempt_index=attempt_index,
        resolution=resolution,
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
    selected = payload.get("selected") or payload.get("selected_model") or "?"
    primary = payload.get("resolution_reason")
    if isinstance(primary, str) and primary:
        return f"Selected {selected} because {primary}"
    steps = payload.get("steps") or []
    codes = [str(step.get("code")) for step in steps if isinstance(step, dict)]
    priority = (
        "compatibility_alias",
        "explicit_override",
        "operator_override",
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
