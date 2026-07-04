"""Tests for gateway model-name mapping."""

from __future__ import annotations

from ylang.gateway.mapping import (
    VIRTUAL_MODEL_NAMES,
    resolve_gateway_model,
)


def test_virtual_models_map_to_activity_routing() -> None:
    route = resolve_gateway_model("route-code")
    assert route.activity == "code"
    assert route.explicit_model is None
    assert route.request_model == "route-code"


def test_passthrough_model_uses_other_activity() -> None:
    route = resolve_gateway_model("ollama/qwen2.5")
    assert route.activity == "other"
    assert route.explicit_model == "ollama/qwen2.5"


def test_virtual_model_catalog() -> None:
    assert set(VIRTUAL_MODEL_NAMES) == {
        "route-code",
        "route-search",
        "route-reason",
        "route-other",
    }
