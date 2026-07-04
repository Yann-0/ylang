"""OpenAI model-name mapping into core Engine routing parameters.

Virtual ``route-*`` ids map to activity buckets. Any other ``model`` string is
treated as an explicit passthrough slug with ``activity=other`` (see
``resolve_gateway_model``). The improver is not a gateway route.
"""

from __future__ import annotations

from dataclasses import dataclass

from ylang.core.types import Activity

# Client-visible virtual models for GET /v1/models and activity-based routing.
VIRTUAL_ROUTE_MODELS: dict[str, Activity] = {
    "route-code": "code",
    "route-search": "search",
    "route-reason": "reason",
    "route-other": "other",
}

# Tuple of virtual model ids (stable order for startup logs).
VIRTUAL_MODEL_NAMES: tuple[str, ...] = tuple(VIRTUAL_ROUTE_MODELS.keys())


@dataclass(frozen=True, slots=True)
class ResolvedRoute:
    """Activity and optional explicit model derived from a client model string."""

    activity: Activity | str
    explicit_model: str | None
    request_model: str


def resolve_gateway_model(model: str) -> ResolvedRoute:
    """Map an OpenAI ``model`` field to Engine ``activity`` and ``model`` kwargs.

    Virtual ``route-*`` names select an activity bucket with no explicit model.
    All other strings pass through as ``explicit_model`` under ``activity=other``;
    ``ModelRouter.resolve_explicit_model`` translates Cursor slugs when possible.
    """
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
