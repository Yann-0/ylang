"""OpenAI model-name mapping into core Engine routing parameters."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.core.types import Activity

VIRTUAL_ROUTE_MODELS: dict[str, Activity] = {
    "route-code": "code",
    "route-search": "search",
    "route-reason": "reason",
    "route-other": "other",
}

VIRTUAL_MODEL_NAMES: tuple[str, ...] = tuple(VIRTUAL_ROUTE_MODELS.keys())


@dataclass(frozen=True, slots=True)
class ResolvedRoute:
    """Activity and optional explicit model derived from a client model string."""

    activity: Activity | str
    explicit_model: str | None
    request_model: str


def resolve_gateway_model(model: str) -> ResolvedRoute:
    """Map an OpenAI ``model`` field to Engine ``activity`` and ``model`` kwargs."""
    activity = VIRTUAL_ROUTE_MODELS.get(model)
    if activity is not None:
        return ResolvedRoute(
            activity=activity,
            explicit_model=None,
            request_model=model,
        )
    return ResolvedRoute(
        activity="other",
        explicit_model=model,
        request_model=model,
    )
