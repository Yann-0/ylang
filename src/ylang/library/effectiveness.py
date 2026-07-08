"""Template effectiveness scoring for outcome-aware retrieval."""

from __future__ import annotations

from ylang.usage.improver_analytics import template_effectiveness
from ylang.usage.store import UsageStore, UsageWindow


def build_effectiveness_scores(
    store: UsageStore,
    *,
    window_days: int = 30,
    min_samples: int = 3,
) -> dict[str, float]:
    """Return template_id → accept_rate for templates with enough samples."""
    window = UsageWindow.last_days(window_days)
    rows = template_effectiveness(store, window, min_samples=min_samples)
    return {row.template_id: row.accept_rate for row in rows}


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
