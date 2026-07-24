"""Template effectiveness scoring for outcome-aware retrieval."""

from __future__ import annotations

from ylang.usage.improver_analytics import (
    _MIN_TEMPLATE_SAMPLES,
    template_effectiveness,
)
from ylang.usage.store import UsageStore, UsageWindow

ZERO_ACCEPT_MIN_SAMPLES = _MIN_TEMPLATE_SAMPLES
DEFAULT_EFFECTIVENESS_WINDOW_DAYS = 30


def build_effectiveness_scores(
    store: UsageStore,
    *,
    window_days: int = DEFAULT_EFFECTIVENESS_WINDOW_DAYS,
    min_samples: int = ZERO_ACCEPT_MIN_SAMPLES,
) -> dict[str, float]:
    """Return template_id → accept_rate for templates with enough samples."""
    window = UsageWindow.last_days(window_days)
    rows = template_effectiveness(store, window, min_samples=min_samples)
    return {row.template_id: row.accept_rate for row in rows}


def is_ineffective_template(
    template_id: str,
    effectiveness: dict[str, float] | None,
    *,
    min_accept_rate: float = 0.0,
) -> bool:
    """Return True when analytics show zero accept rate with enough samples."""
    if not effectiveness:
        return False
    accept_rate = effectiveness.get(template_id)
    if accept_rate is None:
        return False
    return accept_rate <= min_accept_rate


def zero_accept_template_ids(
    effectiveness: dict[str, float],
) -> frozenset[str]:
    """Return template ids with measured 0% accept rate (min_samples already applied)."""
    return frozenset(
        template_id
        for template_id, accept_rate in effectiveness.items()
        if accept_rate == 0.0
    )


def zero_accept_template_ids_from_store(
    store: UsageStore,
    *,
    window_days: int = DEFAULT_EFFECTIVENESS_WINDOW_DAYS,
    min_samples: int = ZERO_ACCEPT_MIN_SAMPLES,
) -> frozenset[str]:
    """Return template ids with 0% accept rate and at least ``min_samples`` injections."""
    window = UsageWindow.last_days(window_days)
    rows = template_effectiveness(store, window, min_samples=min_samples)
    return frozenset(row.template_id for row in rows if row.accept_rate == 0.0)


def retrieval_blocked_template_ids(
    store: UsageStore | None,
    effectiveness: dict[str, float] | None = None,
    *,
    window_days: int = DEFAULT_EFFECTIVENESS_WINDOW_DAYS,
    min_samples: int = ZERO_ACCEPT_MIN_SAMPLES,
) -> frozenset[str]:
    """Return template ids that must never be injected into improver context."""
    if store is not None:
        return zero_accept_template_ids_from_store(
            store,
            window_days=window_days,
            min_samples=min_samples,
        )
    if effectiveness:
        return zero_accept_template_ids(effectiveness)
    return frozenset()


def blend_retrieval_score(
    keyword_score: int,
    template_id: str,
    effectiveness: dict[str, float],
    *,
    weight: float = 0.5,
) -> float:
    """Blend keyword retrieval score with historical accept rate."""
    if not effectiveness or template_id not in effectiveness:
        return float(keyword_score)
    accept_rate = effectiveness[template_id]
    effectiveness_component = accept_rate * 10.0
    return keyword_score * (1.0 - weight) + effectiveness_component * weight
